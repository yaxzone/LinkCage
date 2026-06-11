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
LinkCage - Native Messaging Host
Cross-platform (Windows, macOS, Linux) native messaging host for Chrome/Chromium.
Receives URLs from the LinkCage extension and opens them in a sandboxed
Docker Chromium container.
"""

import datetime
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import platform
import tempfile
import time
import urllib.parse

# Local modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import urlcheck  # noqa: E402
    import urlhaus_sync  # noqa: E402
except Exception:
    urlcheck = None
    urlhaus_sync = None

try:
    import splash  # noqa: E402
except Exception:
    splash = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")

# Platform-aware paths
_SYSTEM = platform.system()

if _SYSTEM == "Windows":
    LINKCAGE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LinkCage")
    _LOG_DIR = LINKCAGE_DIR
else:
    LINKCAGE_DIR = os.path.expanduser("~/.linkcage")
    # Keep the debug log in the per-user dir (not shared /tmp) — it can contain
    # opened URLs and must not be world-readable to other local users.
    _LOG_DIR = LINKCAGE_DIR

USER_CONFIG_PATH = os.path.join(LINKCAGE_DIR, "config.json")
CACHE_PATH = os.path.join(LINKCAGE_DIR, "cache.sqlite")
URLHAUS_PATH = os.path.join(LINKCAGE_DIR, "urlhaus.txt")
DEBUG_LOG_PATH = os.path.join(_LOG_DIR, "linkcage-debug.log")

# Splash temp dir
SPLASH_DIR = tempfile.gettempdir()

# Lazy-initialized singleton checker
_url_checker = None


def _find_docker():
    """Find the docker binary on this system."""
    found = shutil.which("docker")
    if found:
        return found
    # Common fallback paths
    candidates = []
    if _SYSTEM == "Darwin":
        candidates = ["/usr/local/bin/docker", "/opt/homebrew/bin/docker"]
    elif _SYSTEM == "Windows":
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", ""), "Docker", "Docker", "resources", "bin", "docker.exe"),
        ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "docker"  # last resort, hope it's on PATH


DOCKER_BIN = _find_docker()


def _find_chrome():
    """Find a Chromium-based browser to launch as the local sandbox viewer.

    Tries PATH first, then standard install locations per OS. Falls back to
    Microsoft Edge (also Chromium, supports the same --app= switch) when
    Chrome isn't installed. Returns None if nothing is found.

    `subprocess.Popen(["chrome.exe", ...])` does NOT use the Windows App Paths
    registry, only PATH — and Chrome's installer does not add itself to PATH,
    so a bare "chrome.exe" reference fails on a default install. This helper
    is what makes the sandbox viewer window actually open.
    """
    for name in ("chrome", "chrome.exe", "google-chrome", "chromium",
                 "chromium-browser", "msedge", "msedge.exe", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    if _SYSTEM == "Windows":
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
    elif _SYSTEM == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:
        candidates = []
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


CHROME_BIN = _find_chrome()


# Minimal Chrome DevTools Protocol client that runs INSIDE the container
# (via `docker exec /lsiopy/bin/python -c`) and opens sys.argv[1] in a new
# INCOGNITO tab. We need CDP-over-WebSocket (not the HTTP /json/new endpoint)
# because /json/new creates tabs in chromium's default — non-incognito —
# browser context even when chromium itself was launched with --incognito.
# Target.createBrowserContext returns a fresh incognito context id; then
# Target.createTarget with that id puts the new tab in incognito.
# The script is stdlib-only (socket / base64 / struct / urllib / json).
_CDP_INCOGNITO_TAB_SCRIPT = r"""
import sys, json, socket, base64, os, struct, urllib.request
def ws_open(h, p, path):
    s = socket.create_connection((h, p), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((
        "GET " + path + " HTTP/1.1\r\n"
        "Host: " + h + ":" + str(p) + "\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        "Sec-WebSocket-Key: " + key + "\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        c = s.recv(4096)
        if not c: raise ConnectionError("ws handshake closed")
        buf += c
    return s
def ws_send(s, text):
    p = text.encode("utf-8"); n = len(p); f = bytearray([0x81])
    if n < 126: f.append(0x80 | n)
    elif n < 65536: f.append(0x80 | 126); f += struct.pack(">H", n)
    else: f.append(0x80 | 127); f += struct.pack(">Q", n)
    m = os.urandom(4); f += m
    f += bytes(b ^ m[i % 4] for i, b in enumerate(p))
    s.sendall(bytes(f))
def ws_recv(s):
    h = b""
    while len(h) < 2:
        c = s.recv(2 - len(h))
        if not c: raise ConnectionError("ws closed")
        h += c
    n = h[1] & 0x7f
    if n == 126:
        ln = b""
        while len(ln) < 2:
            c = s.recv(2 - len(ln))
            if not c: raise ConnectionError("ws closed")
            ln += c
        n = struct.unpack(">H", ln)[0]
    elif n == 127:
        ln = b""
        while len(ln) < 8:
            c = s.recv(8 - len(ln))
            if not c: raise ConnectionError("ws closed")
            ln += c
        n = struct.unpack(">Q", ln)[0]
    p = b""
    while len(p) < n:
        c = s.recv(n - len(p))
        if not c: raise ConnectionError("ws closed")
        p += c
    return p.decode("utf-8")
url = sys.argv[1]
# Find any existing chromium tab. Chromium auto-launched with --incognito
# about:blank, so there is one incognito tab here; we attach to it and use
# window.open(...) to spawn the new URL as another tab in the SAME incognito
# session. Target.createTarget would have been cleaner, but chromium does
# not accept the --incognito-launch context's id for that call (only ids
# returned by Target.createBrowserContext) and creating a fresh CDP context
# yields a separate window that doesn't render as incognito.
tabs = json.loads(urllib.request.urlopen("http://localhost:9222/json", timeout=5).read())
pages = [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
if not pages:
    raise RuntimeError("no chromium page found to attach to")
parts = pages[0]["webSocketDebuggerUrl"].split("://", 1)[1].split("/", 1)
host_port = parts[0].split(":")
sock = ws_open(host_port[0], int(host_port[1]), "/" + parts[1])
# json.dumps(url) gives a JS-safe string literal — bulletproof against any
# character in the user URL. userGesture: True bypasses popup-blocking.
expr = "window.open(" + json.dumps(url) + ", '_blank')"
ws_send(sock, json.dumps({"id": 1, "method": "Runtime.evaluate",
                          "params": {"expression": expr, "userGesture": True}}))
# Drain frames until we see the response for id=1 (CDP may emit events
# before the response; ignore them).
while True:
    msg = json.loads(ws_recv(sock))
    if msg.get("id") == 1:
        break
sock.close()
# Tidy: close any about:blank tabs (left from chromium's --incognito launch)
# so the sandbox shows only the URL we just opened.
try:
    for t in json.loads(urllib.request.urlopen("http://localhost:9222/json", timeout=5).read()):
        if t.get("type") == "page" and t.get("url") == "about:blank" and t.get("id"):
            try:
                urllib.request.urlopen("http://localhost:9222/json/close/" + t["id"], timeout=5).read()
            except Exception:
                pass
except Exception:
    pass
"""



def _popen_detached(args):
    """Spawn a long-running GUI subprocess that outlives this host process.

    Chrome/Firefox put the native-messaging host inside a Windows Job Object
    that is torn down (killing every process in it) when the host exits. The
    host always exits within seconds of replying to the extension, so a
    naively spawned viewer window dies almost immediately and the user sees
    nothing. CREATE_BREAKAWAY_FROM_JOB pulls the spawned process out of that
    job so it survives. If the parent's job disallows breakaway (rare),
    fall back to a plain detached spawn.
    """
    kwargs = {"shell": False, "close_fds": True}
    if _SYSTEM == "Windows":
        base = 0
        for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
            if hasattr(subprocess, name):
                base |= getattr(subprocess, name)
        flags = base
        if hasattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB"):
            flags |= subprocess.CREATE_BREAKAWAY_FROM_JOB
        kwargs["creationflags"] = flags
        try:
            return subprocess.Popen(args, **kwargs)
        except OSError:
            # Parent's job disallows breakaway — best-effort detached spawn.
            kwargs["creationflags"] = base
            return subprocess.Popen(args, **kwargs)
    else:
        kwargs["start_new_session"] = True
        return subprocess.Popen(args, **kwargs)

# Global flag — set once config is loaded. Default OFF so nothing sensitive
# (e.g. URLs) is ever written before the user's debug_log setting is read.
_debug_enabled = False


def _debug(msg):
    if not _debug_enabled:
        return
    try:
        os.makedirs(os.path.dirname(DEBUG_LOG_PATH), exist_ok=True)
        with open(DEBUG_LOG_PATH, "a") as f:
            f.write(f"{datetime.datetime.now()} {msg}\n")
    except OSError:
        pass


def load_config():
    global _debug_enabled
    defaults = {
        "containerName": "chromium-browser",
        "composePath": "",
        "composeFile": "docker-compose.yml",
        "localPort": 3443,
        "protocol": "https",
        "chromiumProfileDir": ".chromium-profile",
        "autoStartContainer": True,
        "autoOpenBrowser": True,
        "browserArgs": ["--incognito"],
        "debug_log": False,
        "verdict": {
            "enabled": True,
            "cache_enabled": True,
            "deadline_seconds": 1.5,
            "urlhaus": {"enabled": True, "refresh_hours": 6},
            "gsb": {"enabled": False, "api_key": ""},
        },
    }
    try:
        # utf-8-sig tolerates a UTF-8 BOM (Windows PowerShell's Out-File -Encoding
        # utf8 writes one); without it json.load raises and the config is silently
        # dropped, leaving composePath empty.
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            defaults.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    # Merge user-level config on top of project config.
    # Keys that control which Docker commands execute are intentionally NOT
    # overridable from the user-level config — otherwise a dropped/tampered
    # config could silently point "docker compose up" at a malicious compose
    # file. These must come from the project install only.
    PROTECTED_KEYS = {"composePath", "composeFile", "containerName"}
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            user_cfg = json.load(f)
        for k, v in user_cfg.items():
            if k in PROTECTED_KEYS:
                continue
            if k == "verdict" and isinstance(v, dict) and isinstance(defaults.get("verdict"), dict):
                _deep_merge(defaults["verdict"], v)
            else:
                defaults[k] = v
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    _debug_enabled = defaults.get("debug_log", False)
    return defaults


def _deep_merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    msg_length = struct.unpack("=I", raw_length)[0]
    msg_data = sys.stdin.buffer.read(msg_length).decode("utf-8")
    return json.loads(msg_data)


def send_message(msg):
    encoded = json.dumps(msg).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def is_container_running(container_name):
    try:
        result = subprocess.run(
            [DOCKER_BIN, "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10
        )
        names = [line.strip() for line in result.stdout.splitlines()]
        return container_name in names
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def start_container(config):
    compose_path = config["composePath"]
    compose_file = os.path.join(compose_path, config["composeFile"])

    if not os.path.exists(compose_file):
        return False, f"docker compose file not found: {compose_file}"

    cmd = [DOCKER_BIN, "compose", "-f", compose_file, "up", "-d"]
    _debug(f"Running command: {cmd}")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, cwd=compose_path
        )
        if result.returncode == 0:
            return True, "Container started"
        return False, result.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        _debug(f"start_container error: {e}")
        return False, str(e)


def stop_container(config):
    """Stop the sandbox: kill Chrome processes pinned to the sandbox profile, then docker compose down."""
    profile_dir = config.get("chromiumProfileDir") or ""
    compose_path = config.get("composePath") or ""
    compose_file = config.get("composeFile") or ""

    # Step 1: Kill Chrome processes matching the sandbox profile dir
    if profile_dir:
        try:
            if _SYSTEM == "Windows":
                # Match the viewer by its user-data-dir, not by binary name —
                # the viewer may be chrome.exe OR msedge.exe (or chromium)
                # depending on which Chromium-based browser _find_chrome()
                # resolved to. The profile dir is the unique signal.
                # Double any single quote so the value can't break out of
                # the PowerShell single-quoted string literal.
                safe_profile = profile_dir.replace("'", "''")
                ps_script = (
                    f"Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe' OR Name='chromium.exe'\" | "
                    f"Where-Object {{ $_.CommandLine -match [regex]::Escape('{safe_profile}') }} | "
                    f"ForEach-Object {{ $_.ProcessId }}"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    capture_output=True, text=True, timeout=10
                )
                for pid in result.stdout.strip().splitlines():
                    pid = pid.strip()
                    if pid:
                        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, timeout=5)
                        _debug(f"stop: killed chrome pid {pid}")
            elif _SYSTEM == "Darwin":
                # Escape regex metacharacters so the profile dir matches
                # literally and can't broaden the pattern (e.g. kill unrelated
                # Chrome windows).
                safe_profile = re.escape(profile_dir)
                pgrep_result = subprocess.run(
                    ["pgrep", "-f", f"user-data-dir=.*{safe_profile}"],
                    capture_output=True, text=True, timeout=10
                )
                for pid in pgrep_result.stdout.strip().splitlines():
                    pid = pid.strip()
                    if pid:
                        subprocess.run(["kill", pid], capture_output=True, timeout=5)
                        _debug(f"stop: killed chrome pid {pid}")
            else:
                safe_profile = re.escape(profile_dir)
                subprocess.run(
                    ["pkill", "-f", f"user-data-dir=.*{safe_profile}"],
                    capture_output=True, timeout=10
                )
                _debug("stop: pkill chrome by profile dir")
        except Exception as e:
            _debug(f"stop: chrome cleanup error: {e}")

    # Step 2: docker compose down
    if not compose_path or not compose_file:
        return False, "Missing composePath or composeFile in config"

    compose_file_path = os.path.join(compose_path, compose_file)
    try:
        cmd = [DOCKER_BIN, "compose", "-f", compose_file_path, "down"]
        _debug(f"stop: running {' '.join(cmd)}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, cwd=compose_path
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:400]
            return False, f"docker compose down failed: {detail}"
        _debug("stop: docker compose down ok")
        return True, "Sandbox stopped"
    except subprocess.TimeoutExpired:
        return False, "docker compose down timed out"
    except FileNotFoundError as e:
        return False, f"docker binary not found: {e}"
    except Exception as e:
        return False, f"stop error: {e}"


def wait_for_container_ready(container_name, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = subprocess.run(
                [
                    DOCKER_BIN, "exec", container_name,
                    "bash", "-c",
                    "test -f /tmp/.X1-lock && pgrep -f chromium > /dev/null"
                ],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                time.sleep(2)
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        time.sleep(1)
    return False


def open_browser_to_container(config, app_url=None):
    container_url = f"{config['protocol']}://localhost:{config['localPort']}"
    if not app_url:
        app_url = container_url
    compose_path = config["composePath"]
    profile_dir = os.path.join(compose_path, config["chromiumProfileDir"])

    common_flags = ["--no-first-run", "--no-default-browser-check"]
    # Only relax TLS validation when talking to the container over https with
    # its self-signed localhost cert — never broaden it beyond that case.
    if config.get("protocol", "https") == "https":
        common_flags += ["--ignore-certificate-errors", "--test-type"]

    if not CHROME_BIN:
        _debug("open_browser_to_container: no Chromium browser found; cannot open sandbox viewer")
        return

    flags = config.get("browserArgs", []) + common_flags + [
        f"--user-data-dir={profile_dir}",
        f"--app={app_url}",
    ]

    if _SYSTEM == "Darwin":
        # Launch through LaunchServices (`open`) rather than exec'ing the app's
        # Mach-O binary directly. A direct exec makes THIS process the
        # "responsible process" for the browser, so the browser's own bundle
        # writes (its auto-updater touching /Applications/*.app) are attributed
        # to us and macOS raises an App Management prompt ("python was prevented
        # from modifying apps"). `open` lets the browser be responsible for
        # itself, so no prompt appears. `-n` forces a separate instance bound to
        # our isolated --user-data-dir.
        app_bundle = CHROME_BIN
        marker = ".app/Contents/MacOS/"
        if marker in CHROME_BIN:
            app_bundle = CHROME_BIN.split(".app/")[0] + ".app"
        _popen_detached(["open", "-n", "-a", app_bundle, "--args"] + flags)
    else:
        _popen_detached([CHROME_BIN] + flags)


def open_url_in_container(config, url):
    container_name = config["containerName"]
    try:
        # Open the URL in a NEW INCOGNITO tab via chromium's CDP. The HTTP
        # /json/new endpoint creates tabs in the regular (non-incognito)
        # browser context even when chromium was launched with --incognito,
        # so we use Target.createBrowserContext + Target.createTarget over
        # WebSocket instead — those let us specify a fresh incognito
        # browserContextId so the resulting tab is truly incognito.
        #
        # The script runs INSIDE the container (docker exec /lsiopy/bin/python)
        # so the DevTools port stays bound to the container's localhost only
        # (never exposed to the host). The URL is passed as a SEPARATE argv
        # element (sys.argv[1]) — never interpolated into the script body —
        # and is then json.dumps'd into a CDP method param, which is
        # bulletproof against any shell metacharacters in the URL.
        subprocess.run(
            [
                DOCKER_BIN, "exec", container_name,
                "/lsiopy/bin/python", "-c", _CDP_INCOGNITO_TAB_SCRIPT, url,
            ],
            capture_output=True, timeout=15,
        )
        return True, "OK"
    except FileNotFoundError as e:
        return False, str(e)


def ensure_linkcage_dir():
    try:
        os.makedirs(LINKCAGE_DIR, exist_ok=True)
    except OSError as e:
        _debug(f"Could not create {LINKCAGE_DIR}: {e}")


def maybe_refresh_urlhaus(config):
    if urlhaus_sync is None:
        return
    vcfg = config.get("verdict", {})
    if not vcfg.get("enabled", True):
        return
    urlhaus_cfg = vcfg.get("urlhaus", {}) if isinstance(vcfg.get("urlhaus"), dict) else {}
    if not urlhaus_cfg.get("enabled", True):
        return
    refresh_hours = urlhaus_cfg.get("refresh_hours", 6)
    max_age = int(refresh_hours) * 3600

    if not urlhaus_sync.is_stale(URLHAUS_PATH, max_age=max_age):
        return

    def _bg():
        try:
            ok, msg = urlhaus_sync.sync(URLHAUS_PATH, force=False)
            _debug(f"urlhaus_sync: ok={ok} msg={msg}")
        except Exception as e:
            _debug(f"urlhaus_sync EXCEPTION: {e}")

    import threading
    t = threading.Thread(target=_bg, daemon=True)
    t.start()


def get_checker(config):
    global _url_checker
    if urlcheck is None:
        return None
    if _url_checker is not None:
        return _url_checker
    try:
        ensure_linkcage_dir()
        vcfg = config.get("verdict", {}) or {}
        gsb_cfg = vcfg.get("gsb", {}) if isinstance(vcfg.get("gsb"), dict) else {}
        gsb_key = gsb_cfg.get("api_key", "") if gsb_cfg.get("enabled") else ""
        cache_on = vcfg.get("cache_enabled", True)
        _url_checker = urlcheck.UrlChecker(
            cache_path=CACHE_PATH if cache_on else None,
            urlhaus_feed_path=URLHAUS_PATH,
            gsb_api_key=gsb_key or None,
        )
        _debug(f"UrlChecker initialized (gsb={'on' if gsb_key else 'off'}, cache={'on' if cache_on else 'off'})")
    except Exception as e:
        _debug(f"get_checker init failed: {e}")
        _url_checker = None
    return _url_checker


def run_verdict_check(config, url):
    vcfg = config.get("verdict", {}) or {}
    if not vcfg.get("enabled", True):
        return None
    checker = get_checker(config)
    if checker is None:
        return None
    deadline = float(vcfg.get("deadline_seconds", 1.5))
    try:
        v = checker.check(url, deadline=deadline)
        _debug(f"verdict: level={v.level} source={v.source} reason={v.reason!r}")
        return v.to_dict()
    except Exception as e:
        _debug(f"run_verdict_check EXCEPTION: {e}")
        return None


def handle_message(msg):
    _debug(f"handle_message called with action={msg.get('action')}, url={msg.get('url')}")
    action = msg.get("action")

    if action == "stop":
        try:
            config = load_config()
        except Exception as e:
            _debug(f"stop: load_config failed: {e}")
            return {"status": "error", "action": "stop", "error": f"Config load failed: {e}"}
        ok, detail = stop_container(config)
        if ok:
            return {"status": "ok", "action": "stop", "detail": detail}
        else:
            return {"status": "error", "action": "stop", "error": detail}

    url = msg.get("url", "")

    if action != "open" or not url:
        _debug(f"Rejected: action={action!r}, url={url!r}")
        return {"status": "error", "error": "Invalid action or missing URL"}

    bypass_verdict = bool(msg.get("bypass_verdict", False))

    try:
        config = load_config()
        container_name = config["containerName"]
    except Exception as e:
        _debug(f"EXCEPTION loading config: {e}")
        return {"status": "error", "error": f"Config load failed: {e}"}

    # Verdict check
    maybe_refresh_urlhaus(config)
    verdict = run_verdict_check(config, url)
    # MALICIOUS links are NOT blocked — they proceed to the sandbox but the
    # splash screen (red, no auto-proceed) requires the user to explicitly
    # click "I accept the risk, continue" before reaching the container.

    # Ensure container is running
    try:
        was_stopped = not is_container_running(container_name)
    except Exception as e:
        _debug(f"EXCEPTION in is_container_running: {e}")
        return {"status": "error", "error": f"Container check failed: {e}"}

    if was_stopped:
        if config["autoStartContainer"]:
            try:
                ok, detail = start_container(config)
            except Exception as e:
                return {"status": "error", "error": f"start_container exception: {e}"}
            if not ok:
                return {"status": "error", "error": f"Failed to start container: {detail}"}
            wait_for_container_ready(container_name, timeout=30)
        else:
            return {"status": "error", "error": "Container is not running and autoStart is disabled"}

    # Open URL in container
    try:
        ok, detail = open_url_in_container(config, url)
    except Exception as e:
        return {"status": "error", "error": f"open_url_in_container exception: {e}"}

    # Open local browser to container UI (with optional splash)
    if config["autoOpenBrowser"]:
        protocol = config.get("protocol", "https")
        local_port = config.get("localPort", 3443)
        container_url = f"{protocol}://localhost:{local_port}"
        splash_path = None

        if splash is not None and verdict and urlcheck is not None:
            try:
                vcfg = config.get("verdict", {}) or {}
                urlhaus_cfg = vcfg.get("urlhaus", {}) if isinstance(vcfg.get("urlhaus"), dict) else {}
                gsb_cfg = vcfg.get("gsb", {}) if isinstance(vcfg.get("gsb"), dict) else {}
                verdict_for_splash = dict(verdict)
                verdict_for_splash["confidence"] = urlcheck.compute_confidence(
                    verdict_for_splash, urlhaus_cfg.get("enabled", True), gsb_cfg.get("enabled", False)
                )
                try:
                    splash.cleanup_old_splashes(out_dir=SPLASH_DIR)
                except Exception:
                    pass
                splash_path = splash.write_splash_file(verdict_for_splash, url, container_url, out_dir=SPLASH_DIR)
                _debug(f"splash: wrote {splash_path}")
            except Exception as e:
                _debug(f"splash: failed ({e}); falling back to direct container URL")
                splash_path = None

        if splash_path:
            # Windows paths need file:///C:/... format
            if _SYSTEM == "Windows":
                app_url = "file:///" + splash_path.replace("\\", "/")
            else:
                app_url = f"file://{splash_path}"
        else:
            app_url = container_url
        try:
            open_browser_to_container(config, app_url=app_url)
        except Exception as e:
            _debug(f"EXCEPTION in open_browser_to_container: {e}")

    response = {"status": "ok" if ok else "partial", "url": url}
    if not ok:
        response["warning"] = detail
    if verdict:
        response["verdict"] = verdict
    return response


def main():
    # Load config first so the debug_log setting is honored before any logging.
    try:
        load_config()
    except Exception:
        pass
    _debug(f"launcher.py started from {__file__}")
    try:
        msg = read_message()
    except Exception as e:
        _debug(f"read_message error: {e}")
        send_message({"status": "error", "error": str(e)})
        return
    _debug(f"Message received: {msg}")
    if msg:
        response = handle_message(msg)
        send_message(response)


if __name__ == "__main__":
    main()
