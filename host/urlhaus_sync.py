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
LinkCage — URLhaus feed sync

Downloads the URLhaus bulk hostfile from abuse.ch over HTTPS and writes it
atomically to ~/.linkcage/urlhaus.txt.

No API key required. License: CC0.

Source: https://urlhaus.abuse.ch/downloads/hostfile/

Usage:
    python3 urlhaus_sync.py            # Sync if stale (>6h old) or missing
    python3 urlhaus_sync.py --force    # Force re-download
    python3 urlhaus_sync.py --check    # Print staleness and exit
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request


def _ssl_context() -> ssl.SSLContext:
    """TLS context with a working CA bundle.

    macOS's python.org Python ships no system CA bundle, so plain urlopen()
    fails with CERTIFICATE_VERIFY_FAILED. Prefer certifi's bundle when present;
    fall back to the platform default (fine on Windows/Linux)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()

URLHAUS_URL = "https://urlhaus.abuse.ch/downloads/hostfile/"
DEFAULT_FEED_PATH = os.path.expanduser("~/.linkcage/urlhaus.txt")
STALENESS_SECONDS = 6 * 60 * 60  # 6 hours
DOWNLOAD_TIMEOUT = 30  # seconds
USER_AGENT = "LinkCage-Verdict/1.0 (+https://github.com/)"


def is_stale(path: str, max_age: int = STALENESS_SECONDS) -> bool:
    """Return True if the feed file is missing or older than max_age seconds."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return True
    return (time.time() - mtime) > max_age


def feed_age_seconds(path: str) -> int:
    try:
        return int(time.time() - os.path.getmtime(path))
    except OSError:
        return -1


def download(url: str, timeout: int = DOWNLOAD_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        status = getattr(resp, "status", 200)
        if status and status >= 400:
            raise urllib.error.HTTPError(url, status, f"HTTP {status}", resp.headers, None)
        return resp.read()


def atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".urlhaus.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sync(path: str = DEFAULT_FEED_PATH, force: bool = False) -> tuple[bool, str]:
    """
    Sync the URLhaus feed.
    Returns (ok, message).
    """
    if not force and not is_stale(path):
        age = feed_age_seconds(path)
        return True, f"Feed is fresh ({age}s old), skipping download"

    try:
        data = download(URLHAUS_URL)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return False, f"Download failed: {e}"

    if not data or len(data) < 1024:
        return False, f"Download too small ({len(data)} bytes), refusing to write"

    try:
        atomic_write(path, data)
    except OSError as e:
        return False, f"Write failed: {e}"

    # Count non-comment, non-empty lines for reporting
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            count = sum(
                1 for line in f
                if line.strip() and not line.lstrip().startswith("#")
            )
    except OSError:
        count = -1

    return True, f"Wrote {len(data)} bytes ({count} entries) to {path}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync the URLhaus malware feed")
    parser.add_argument(
        "--path",
        default=DEFAULT_FEED_PATH,
        help=f"Feed file path (default: {DEFAULT_FEED_PATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if feed is fresh",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print staleness and exit without downloading",
    )
    args = parser.parse_args()

    if args.check:
        age = feed_age_seconds(args.path)
        if age < 0:
            print(f"Feed missing: {args.path}")
            return 1
        stale = "STALE" if age > STALENESS_SECONDS else "fresh"
        print(f"{args.path}: age={age}s ({stale})")
        return 0

    ok, msg = sync(args.path, force=args.force)
    print(msg)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
