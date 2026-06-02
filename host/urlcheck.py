#!/usr/bin/env python3
# Copyright 2026 Luis Yax
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
LinkCage Verdict — URL reputation checker

Checks a URL against:
  1. In-process LRU cache (fast path)
  2. SQLite disk cache (persistent)
  3. URLhaus local set (no API key required)
  4. Google Safe Browsing v4 Lookup (optional, only if gsb_api_key is configured)

Fail-open: on any error, returns UNKNOWN so the sandbox still opens.

Verdict levels:
  SAFE        — checked, nothing flagged
  SUSPICIOUS  — flagged but lower confidence (e.g. GSB UNWANTED_SOFTWARE)
  MALICIOUS   — confirmed malware/phishing (URLhaus match or GSB MALWARE)
  UNKNOWN     — could not verify (skipped URL type, cache miss + provider error)
"""

from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from typing import Optional

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

VERDICT_SAFE = "SAFE"
VERDICT_SUSPICIOUS = "SUSPICIOUS"
VERDICT_MALICIOUS = "MALICIOUS"
VERDICT_UNKNOWN = "UNKNOWN"

# TTLs (seconds)
TTL_SAFE = 24 * 60 * 60         # 24 hours
TTL_SUSPICIOUS = 6 * 60 * 60    # 6 hours
TTL_MALICIOUS = 6 * 60 * 60     # 6 hours
TTL_UNKNOWN = 5 * 60            # 5 minutes (retry soon)

LRU_MAX = 1024

DEFAULT_TIMEOUT = 1.5  # sync check deadline

GSB_ENDPOINT = "https://safebrowsing.googleapis.com/v4/threatMatches:find"

# Threat types GSB may return
GSB_MALICIOUS_TYPES = {"MALWARE", "SOCIAL_ENGINEERING"}
GSB_SUSPICIOUS_TYPES = {"UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"}


# -----------------------------------------------------------------------------
# Verdict dataclass
# -----------------------------------------------------------------------------

@dataclass
class Verdict:
    level: str = VERDICT_UNKNOWN
    source: str = "none"
    reason: str = ""
    threat_types: list = field(default_factory=list)
    score: Optional[float] = None
    cached: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def should_block(self) -> bool:
        return self.level == VERDICT_MALICIOUS


# -----------------------------------------------------------------------------
# URL canonicalization + skip list
# -----------------------------------------------------------------------------

SKIP_SCHEMES = {"file", "data", "javascript", "chrome", "chrome-extension", "about", "view-source"}
PRIVATE_HOST_SUFFIXES = (".local", ".lan", ".internal", ".corp", ".home")


def canonicalize(url: str) -> str:
    """
    Normalize a URL for cache key + comparisons.
    - lowercase scheme and host
    - IDNA-encode host
    - strip fragment and userinfo
    - sort query params
    """
    try:
        parts = urllib.parse.urlsplit(url)
        scheme = (parts.scheme or "").lower()
        netloc = parts.hostname or ""
        try:
            netloc = netloc.encode("idna").decode("ascii")
        except (UnicodeError, UnicodeDecodeError):
            pass
        netloc = netloc.lower()
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        path = parts.path or "/"
        query = parts.query
        if query:
            pairs = sorted(urllib.parse.parse_qsl(query, keep_blank_values=True))
            query = urllib.parse.urlencode(pairs, doseq=True)
        return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return url


def extract_host(url: str) -> str:
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
        return host.lower()
    except Exception:
        return ""


def is_skip_url(url: str) -> bool:
    """Return True if we should NOT send this URL to any external provider."""
    try:
        parts = urllib.parse.urlsplit(url)
        scheme = (parts.scheme or "").lower()
        if scheme in SKIP_SCHEMES:
            return True
        host = (parts.hostname or "").lower()
        if not host:
            return True
        if host in ("localhost",) or host.endswith(".localhost"):
            return True
        for suffix in PRIVATE_HOST_SUFFIXES:
            if host.endswith(suffix):
                return True
        # IP literal check
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return True
        except ValueError:
            pass
        return False
    except Exception:
        return True  # fail-safe: skip on parse errors


# -----------------------------------------------------------------------------
# L1: In-memory LRU cache
# -----------------------------------------------------------------------------

class _LRU:
    def __init__(self, max_size: int = LRU_MAX):
        self._data: "OrderedDict[str, tuple[Verdict, float]]" = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_size

    def get(self, key: str) -> Optional[Verdict]:
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            verdict, expires = entry
            if time.time() >= expires:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            v = Verdict(**asdict(verdict))
            v.cached = True
            return v

    def put(self, key: str, verdict: Verdict, ttl: int) -> None:
        with self._lock:
            self._data[key] = (verdict, time.time() + ttl)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


# -----------------------------------------------------------------------------
# L2: SQLite cache
# -----------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS url_verdicts (
  url_canonical TEXT PRIMARY KEY,
  verdict       TEXT NOT NULL,
  source        TEXT NOT NULL,
  reason        TEXT,
  threat_types  TEXT,
  score         REAL,
  checked_at    INTEGER NOT NULL,
  expires_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_url_verdicts_expires ON url_verdicts(expires_at);
"""


class _SqliteCache:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=2.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def get(self, key: str) -> Optional[Verdict]:
        try:
            with self._lock, self._conn() as c:
                row = c.execute(
                    "SELECT verdict, source, reason, threat_types, score, expires_at "
                    "FROM url_verdicts WHERE url_canonical = ?",
                    (key,),
                ).fetchone()
            if not row:
                return None
            verdict, source, reason, threat_types, score, expires_at = row
            if time.time() >= expires_at:
                return None
            types = json.loads(threat_types) if threat_types else []
            return Verdict(
                level=verdict,
                source=source,
                reason=reason or "",
                threat_types=types,
                score=score,
                cached=True,
            )
        except sqlite3.Error:
            return None

    def put(self, key: str, verdict: Verdict, ttl: int) -> None:
        try:
            now = int(time.time())
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT OR REPLACE INTO url_verdicts "
                    "(url_canonical, verdict, source, reason, threat_types, score, checked_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key,
                        verdict.level,
                        verdict.source,
                        verdict.reason,
                        json.dumps(verdict.threat_types),
                        verdict.score,
                        now,
                        now + ttl,
                    ),
                )
                # Prune expired rows periodically (~1% of writes)
                import random
                if random.random() < 0.01:
                    c.execute("DELETE FROM url_verdicts WHERE expires_at < ?", (now,))
        except sqlite3.Error:
            pass


# -----------------------------------------------------------------------------
# URLhaus local provider
# -----------------------------------------------------------------------------

class URLhausProvider:
    """
    Loads the URLhaus bulk hostfile (domains, one per line) into a set.
    File format (abuse.ch hostfile): lines like `127.0.0.1 malicious.example.com`
    Comment lines start with '#'.
    """

    def __init__(self, feed_path: str):
        self.feed_path = feed_path
        self._hosts: set = set()
        self._loaded_at: float = 0
        self._lock = threading.Lock()

    def _load(self) -> None:
        hosts: set = set()
        try:
            with open(self.feed_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        host = parts[1].lower()
                    else:
                        host = parts[0].lower()
                    if host and host != "localhost":
                        hosts.add(host)
        except FileNotFoundError:
            hosts = set()
        except OSError:
            hosts = set()
        with self._lock:
            self._hosts = hosts
            self._loaded_at = time.time()

    def ensure_loaded(self) -> None:
        if not self._hosts:
            self._load()

    def check(self, url: str) -> Optional[Verdict]:
        self.ensure_loaded()
        host = extract_host(url)
        if not host:
            return None
        with self._lock:
            hosts = self._hosts
        if not hosts:
            return None
        # direct match
        if host in hosts:
            return Verdict(
                level=VERDICT_MALICIOUS,
                source="urlhaus",
                reason="Host matched URLhaus malware feed",
                threat_types=["MALWARE"],
            )
        # parent domain match (e.g., foo.bar.example.com -> bar.example.com)
        labels = host.split(".")
        for i in range(1, len(labels) - 1):
            parent = ".".join(labels[i:])
            if parent in hosts:
                return Verdict(
                    level=VERDICT_MALICIOUS,
                    source="urlhaus",
                    reason=f"Parent domain '{parent}' matched URLhaus malware feed",
                    threat_types=["MALWARE"],
                )
        return None


# -----------------------------------------------------------------------------
# Google Safe Browsing (optional)
# -----------------------------------------------------------------------------

class GSBProvider:
    def __init__(self, api_key: str, timeout: float = 1.2):
        self.api_key = api_key
        self.timeout = timeout

    def check(self, url: str) -> Optional[Verdict]:
        if not self.api_key:
            return None
        body = {
            "client": {"clientId": "linkcage", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": [
                    "MALWARE",
                    "SOCIAL_ENGINEERING",
                    "UNWANTED_SOFTWARE",
                    "POTENTIALLY_HARMFUL_APPLICATION",
                ],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url}],
            },
        }
        try:
            req = urllib.request.Request(
                f"{GSB_ENDPOINT}?key={urllib.parse.quote(self.api_key)}",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
            return None

        matches = data.get("matches") or []
        if not matches:
            return Verdict(
                level=VERDICT_SAFE,
                source="gsb",
                reason="No threat match from Safe Browsing",
            )
        threat_types = sorted({m.get("threatType", "") for m in matches if m.get("threatType")})
        if any(t in GSB_MALICIOUS_TYPES for t in threat_types):
            level = VERDICT_MALICIOUS
        elif any(t in GSB_SUSPICIOUS_TYPES for t in threat_types):
            level = VERDICT_SUSPICIOUS
        else:
            level = VERDICT_SUSPICIOUS
        return Verdict(
            level=level,
            source="gsb",
            reason="Flagged by Google Safe Browsing: " + ", ".join(threat_types),
            threat_types=threat_types,
        )


# -----------------------------------------------------------------------------
# UrlChecker — orchestrator
# -----------------------------------------------------------------------------

class UrlChecker:
    def __init__(
        self,
        cache_path: Optional[str],
        urlhaus_feed_path: str,
        gsb_api_key: Optional[str] = None,
    ):
        self.lru = _LRU()
        self.sqlite = _SqliteCache(cache_path) if cache_path else None
        self.urlhaus = URLhausProvider(urlhaus_feed_path)
        self.gsb = GSBProvider(gsb_api_key) if gsb_api_key else None

    @staticmethod
    def _ttl_for(verdict: Verdict) -> int:
        if verdict.level == VERDICT_SAFE:
            return TTL_SAFE
        if verdict.level == VERDICT_SUSPICIOUS:
            return TTL_SUSPICIOUS
        if verdict.level == VERDICT_MALICIOUS:
            return TTL_MALICIOUS
        return TTL_UNKNOWN

    def _store(self, key: str, verdict: Verdict) -> Verdict:
        ttl = self._ttl_for(verdict)
        self.lru.put(key, verdict, ttl)
        if self.sqlite:
            self.sqlite.put(key, verdict, ttl)
        return verdict

    def check(self, url: str, deadline: float = DEFAULT_TIMEOUT) -> Verdict:
        """
        Main entry. Returns a Verdict. Never raises — fail-open to UNKNOWN.
        """
        if not url:
            return Verdict(level=VERDICT_UNKNOWN, source="none", reason="Empty URL")

        if is_skip_url(url):
            return Verdict(
                level=VERDICT_UNKNOWN,
                source="skip",
                reason="Local / internal / non-web URL — not checked",
            )

        key = canonicalize(url)

        # L1
        cached = self.lru.get(key)
        if cached is not None:
            return cached

        # L2
        if self.sqlite:
            cached = self.sqlite.get(key)
            if cached is not None:
                # promote to L1
                self.lru.put(key, cached, self._ttl_for(cached))
                return cached

        start = time.time()

        # URLhaus (local, fast, always run if feed exists)
        try:
            v = self.urlhaus.check(url)
        except Exception:
            v = None
        if v is not None:
            return self._store(key, v)

        remaining = deadline - (time.time() - start)

        # GSB (optional, network)
        if self.gsb and remaining > 0.1:
            self.gsb.timeout = max(0.3, remaining)
            try:
                v = self.gsb.check(url)
            except Exception:
                v = None
            if v is not None:
                return self._store(key, v)

        # No signal from any provider — SAFE if we at least reached URLhaus;
        # otherwise UNKNOWN (likely offline with no cached feed).
        if self.urlhaus._hosts:
            return self._store(
                key,
                Verdict(
                    level=VERDICT_SAFE,
                    source="urlhaus",
                    reason="Not listed in URLhaus malware feed",
                ),
            )
        return Verdict(
            level=VERDICT_UNKNOWN,
            source="none",
            reason="No reputation data available — URLhaus feed may not have synced yet (offline or first run)",
        )


# -----------------------------------------------------------------------------
# Confidence helper (used by the pre-sandbox splash page)
# -----------------------------------------------------------------------------

def compute_confidence(verdict: dict, urlhaus_enabled: bool, gsb_enabled: bool) -> str:
    """
    Return a human-readable confidence label for a verdict.

    Confidence is source-based (which providers were consulted), NOT statistical.
    It describes how much corroboration went into the verdict so the splash page
    can display something meaningful to the user.

        SKIP source         -> "N/A"
        UNKNOWN             -> "None"
        MALICIOUS           -> "High"
        SUSPICIOUS          -> "Moderate"
        SAFE + >=2 providers -> "Moderate"
        SAFE + 1 provider   -> "Limited"
    """
    level = (verdict or {}).get("level", VERDICT_UNKNOWN)
    source = (verdict or {}).get("source", "")
    if source == "skip":
        return "N/A"
    if level == VERDICT_UNKNOWN:
        return "None"
    if level == VERDICT_MALICIOUS:
        return "High"
    if level == VERDICT_SUSPICIOUS:
        return "Moderate"
    if level == VERDICT_SAFE:
        provider_count = int(bool(urlhaus_enabled)) + int(bool(gsb_enabled))
        return "Moderate" if provider_count >= 2 else "Limited"
    return "None"
