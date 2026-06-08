# LinkCage — Testing Guide

Two layers: **automated unit tests** (run them on every change) and a **manual end-to-end matrix** (browser × OS — native messaging + Docker can't be fully automated without a real browser and Docker Desktop).

---

## 1. Automated unit tests

Stdlib `unittest` only — no third-party test deps, nothing to install.

```bash
python -m unittest discover -s tests
```

| File | Covers |
|------|--------|
| `tests/test_host.py` | Command-injection safety (URL passed as discrete argv after `--`, no shell), native-messaging framing round-trip, config trust boundary (composePath/composeFile/containerName not overridable from user config), debug-log per-user path |
| `tests/test_urlcheck.py` | URL skip rules (local/private/non-web), canonicalization, URLhaus exact + parent-domain matching, verdict levels, LRU cache hit |
| `tests/test_splash.py` | Splash HTML escapes attacker-controlled URL/reason (no XSS), valid document + CSP |
| `tests/test_build.py` | Per-browser packaging: Chrome/Edge = service worker + no gecko + no `key`; Firefox = event page + pinned gecko id; Firefox manifest never leaks into Chromium zips; 3 permissions only |

Expected: all green (`OK`).

## 2. Build & static verification (no browser needed)

```bash
# Per-browser store zips -> dist/
python scripts/build-extension.py            # all three
python scripts/build-extension.py --browser firefox

# Extension JS syntax
node --check extension/background.js

# Installer syntax
bash -n setup.sh
pwsh -NoProfile -Command "foreach($f in 'setup.ps1'){ \$e=\$null; [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path \$f), [ref]\$null, [ref]\$e); if(\$e){\$e}else{\"\$f OK\"} }"

# Manifests are valid JSON
python -c "import json;[json.load(open('extension/'+f)) for f in ['manifest.json','manifest.firefox.json']];print('manifests OK')"
```

## 3. Docker image verification

```bash
# Boot test: container comes up, Chromium runs, UI responds
docker compose -f docker/docker-compose.yml up -d
docker ps --filter name=chromium-browser --format "{{.Ports}}"   # expect 127.0.0.1:... only
docker exec chromium-browser bash -c "test -f /tmp/.X1-lock && pgrep -f chromium >/dev/null && echo READY"
docker exec chromium-browser bash -c "curl -sk -o /dev/null -w '%{http_code}\n' https://localhost:3001"  # expect 200

# CVE scan (no install; via Trivy container)
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image --severity HIGH,CRITICAL --ignore-unfixed \
  luisyax/linkcage-sandbox:hardened    # expect: 0 (fixable)
```

---

## 4. End-to-end matrix (manual — needs real browsers + Docker Desktop)

Run per cell. macOS uses `setup.sh`; Windows uses `setup.ps1`. Edit `config.json` `composePath` first (or let setup set it).

| Step | Chrome | Edge | Firefox |
|------|:---:|:---:|:---:|
| Install host (`setup`/`install` registers all 3) | ☐ | ☐ | ☐ |
| Load extension (unpacked / `manifest.firefox.json` zip for FF) | ☐ | ☐ | ☐ |
| Context menu "LinkCage: Open in Sandbox" appears on a link | ☐ | ☐ | ☐ |
| Right-click a benign link → container starts, sandbox window opens | ☐ | ☐ | ☐ |
| Verdict splash shows (SAFE/SUSPICIOUS/UNKNOWN) | ☐ | ☐ | ☐ |
| "Close Sandbox Browser" stops the container | ☐ | ☐ | ☐ |
| **Setup-missing prompt**: with host unregistered, click → "setup needed" notification (FF: button-less, click body) | ☐ | ☐ | ☐ |
| Uninstall removes this browser's host registration | ☐ | ☐ | ☐ |

Do the full matrix on **Windows** and on **macOS**.

### 4a. Command-injection proof (do once per OS)
Right-click this exact link → "Open in Sandbox":
```
http://example.com/$(touch /config/INJECTED)
```
Then confirm the payload did NOT execute in the container:
```bash
docker exec chromium-browser ls -la /config/INJECTED   # expect: No such file or directory
```

### 4b. Firefox notification fallback
Firefox has no notification buttons. Verify:
- MALICIOUS / setup notifications render with body text instructing to click.
- Clicking the notification body performs the primary action (open setup guide / proceed).
- Dismissing cancels. A MALICIOUS link is never auto-opened.

### 4c. Privacy default
With `debug_log` at default, after several clicks confirm no log file exists:
- Windows: `%LOCALAPPDATA%\LinkCage\linkcage-debug.log` → absent
- macOS/Linux: `~/.linkcage/linkcage-debug.log` → absent

---

## What's automated vs manual

- **Automated/verified here:** unit tests (host security, verdict logic, splash escaping, cross-browser packaging), build output per browser, installer/script syntax (both shells), manifest validity, Docker boot + Trivy.
- **Manual (needs human + browser + Docker):** the §4 matrix — native messaging end-to-end, the in-sandbox open, the injection proof, and per-browser/per-OS registration. These can't be driven without a real browser invoking the native host.
