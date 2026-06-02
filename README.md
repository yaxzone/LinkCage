# LinkCage

**Cage every suspicious link. Browse without fear.**

LinkCage is a security tool that lets you **right-click any link in Chrome, Edge, or Firefox and open it inside a fully isolated, sandboxed Docker container**. Suspicious email link? Sketchy URL from a chat message? Unknown redirect? Don't risk your machine — cage it.

Works on **Windows, macOS, and Linux**.

**Website & install guide:** https://linkcage.app

---

## THE PROBLEM

Every day, users encounter links they can't fully trust:

- Phishing emails disguised as legitimate services
- Shortened URLs that hide the real destination
- Links in group chats, forums, or social media
- Unexpected attachments and download prompts

Clicking one bad link on your real browser can lead to **credential theft, drive-by malware downloads, browser exploits, and persistent tracking** — all running with full access to your host machine, cookies, and saved passwords.

## THE SOLUTION

LinkCage creates a **disposable, isolated browser environment** using Docker. When you right-click a link:

1. A sandboxed Chromium browser spins up inside a Docker container
2. The link opens **inside the container**, completely isolated from your host
3. Any malware, exploits, trackers, or drive-by downloads are **trapped in the sandbox**
4. When you're done, the container is destroyed — **nothing persists**

Your real browser, your files, your credentials — **never exposed**.

## SECURITY MODEL

| Layer | Protection |
|-------|-----------|
| **Docker isolation** | The browser runs in a separate OS-level container on a dedicated bridge network, with no access to your filesystem, network shares, or host processes |
| **Hardened image** | Custom Dockerfile applies the full Debian security upgrade — **zero *fixable* High/Critical CVEs (Trivy-verified)** — and purges packages a browser sandbox never needs (the `exim4` mail server, SSH client, Docker CLI plugins, and the unused Wayland stack) to shrink the attack surface |
| **Ephemeral storage** | Container uses `tmpfs` — everything is stored in RAM and destroyed on stop |
| **Localhost-only access** | The container's web UI is bound to `127.0.0.1` — reachable only from your machine, never the LAN |
| **No clipboard bridge** | Clipboard sharing between the sandbox and your host is disabled by default, so a malicious page cannot read or overwrite your host clipboard |
| **No persistence** | Cookies, history, downloads, and malware cannot survive a container restart |

> **Important:** LinkCage is designed for inspecting untrusted links. It is NOT a replacement for antivirus software, endpoint protection, or safe browsing habits. Use it as an additional layer of defense.

---

## How It Works

```
  Right-click a link (Chrome / Edge / Firefox)
           |
           v
  [LinkCage Extension]  ──native messaging──>  [Host Script (Python)]
                                                      |
                                        ┌─────────────┼─────────────┐
                                        v             v             v
                                  Start Docker   Open URL in    Open local
                                  container      container's    browser to
                                  (if needed)    Chromium       container UI
```

---

## Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- Python 3.6+ on PATH
- A supported browser: Google Chrome, Chromium, Microsoft Edge, or Firefox

### One-Command Setup

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

**macOS / Linux:**
```bash
chmod +x setup.sh
./setup.sh
```

The setup script will:
1. Verify prerequisites (Docker, Python, a browser)
2. Pull the hardened Docker image
3. Configure the environment
4. Open Chrome and guide you through loading the extension (you can load it in Edge or Firefox the same way)
5. Register the native messaging host for Chrome, Edge, and Firefox
6. Start the sandbox container

After setup, restart your browser and right-click any link to select **"LinkCage: Open in Sandbox"**.

### Manual Setup

<details>
<summary>Click to expand step-by-step instructions</summary>

#### 1. Pull the hardened image

```bash
docker pull luisyax/linkcage-sandbox:hardened
```

Or build it yourself from source:

```bash
cd docker/
docker build -t luisyax/linkcage-sandbox:hardened .
```

#### 2. Configure

Edit `config.json` and set `composePath` to the directory where you want the Docker container managed:

```json
{
  "composePath": "/path/to/your/docker-compose/directory"
}
```

Copy `docker/docker-compose.yml` to that directory, or point `composePath` at an existing setup.

#### 3. Load the extension

**Chrome / Edge:**
1. Open `chrome://extensions` (Chrome) or `edge://extensions` (Edge)
2. Enable **Developer mode** (toggle, top right)
3. Click **Load unpacked** and select the `extension/` directory
4. Copy the **Extension ID** shown on the card (e.g., `foikoicnbljhghfcoemocgjbolhpkiem`)

**Firefox:**
1. Build the Firefox package: `python scripts/build-extension.py --browser firefox`
2. Open `about:debugging#/runtime/this-firefox`
3. Click **Load Temporary Add-on** and select `dist/linkcage-firefox-<version>.zip`
   (the add-on ID is the pinned gecko id `linkcage@yaxzone`)

> The `extension/` directory ships both `manifest.json` (Chrome/Edge, MV3 service worker) and `manifest.firefox.json` (Firefox, gecko id + event-page background). `scripts/build-extension.py` produces clean per-browser zips in `dist/`.

#### 4. Register the native messaging host

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -ExtensionId <YOUR_EXTENSION_ID> [-GeckoId linkcage@yaxzone]
```

**macOS / Linux:**
```bash
chmod +x install.sh
./install.sh <YOUR_EXTENSION_ID> [firefox-gecko-id]
```

This registers the native host for **Chrome, Edge, and Firefox**. `<YOUR_EXTENSION_ID>` is your Chrome/Edge extension ID; the Firefox gecko id defaults to `linkcage@yaxzone`.

#### 5. Restart your browser

#### 6. Use it

Right-click any link and select **"LinkCage: Open in Sandbox"**.

</details>

---

## Project Structure

```
LinkCage/
├── README.md              # You are here
├── LICENSE                # Apache License 2.0
├── config.json            # User-configurable settings
├── setup.ps1              # One-command setup (Windows)
├── setup.sh               # One-command setup (macOS/Linux)
├── install.ps1            # Manual installer (Windows)
├── install.sh             # Manual installer (macOS/Linux)
├── uninstall.ps1          # Uninstaller (Windows)
├── uninstall.sh           # Uninstaller (macOS/Linux)
├── requirements.txt       # Python host deps (stdlib only today)
├── extension/             # Browser extension, Manifest V3 (Chrome / Edge / Firefox)
│   ├── manifest.json          # Chrome / Edge (service worker)
│   ├── manifest.firefox.json  # Firefox (gecko id + event-page background)
│   ├── background.js
│   └── icons/
├── host/                  # Native messaging host
│   ├── launcher.py        # Cross-platform Python host
│   ├── launcher.bat       # Windows wrapper
│   └── launcher.sh        # macOS/Linux wrapper
├── scripts/
│   └── build-extension.py # Build per-browser store zips into dist/
└── docker/                # Container setup
    ├── Dockerfile         # Hardened image with CVE patches
    └── docker-compose.yml # Container orchestration
```

## Configuration

All settings live in `config.json`:

| Setting | Default | Description |
|---------|---------|-------------|
| `containerName` | `chromium-browser` | Docker container name |
| `composePath` | *(set by user)* | Path to directory containing `docker-compose.yml` |
| `composeFile` | `docker-compose.yml` | Compose filename |
| `localPort` | `3443` | HTTPS port for the container's web UI |
| `protocol` | `https` | Protocol for web UI (`http` or `https`) |
| `chromiumProfileDir` | `.chromium-profile` | Isolated Chrome profile directory |
| `autoStartContainer` | `true` | Auto-start container if not running |
| `autoOpenBrowser` | `true` | Auto-open browser to container's web UI |
| `browserArgs` | `["--incognito"]` | Extra arguments for the local browser window |

## Installed Artifacts

The installer registers the native messaging host so your browser can communicate with the host script. Chrome and Edge use the same Chromium-format manifest (`allowed_origins`); Firefox uses its own manifest (`allowed_extensions`) in its own location.

**Windows** (registry key → manifest path):
| Browser | Registry key | Manifest |
|---------|-------------|----------|
| Chrome | `HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.linkcage.host` | `%LOCALAPPDATA%\LinkCage\com.linkcage.host.json` |
| Edge | `HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.linkcage.host` | `%LOCALAPPDATA%\LinkCage\com.linkcage.host.json` |
| Firefox | `HKCU:\Software\Mozilla\NativeMessagingHosts\com.linkcage.host` | `%LOCALAPPDATA%\LinkCage\com.linkcage.host.firefox.json` |

**macOS** (`~/Library/Application Support/.../NativeMessagingHosts/com.linkcage.host.json`):
| Browser | Directory |
|---------|-----------|
| Chrome | `Google/Chrome` |
| Chromium | `Chromium` |
| Edge | `Microsoft Edge` |
| Firefox | `Mozilla` |

**Linux:**
| Browser | Path |
|---------|------|
| Chrome | `~/.config/google-chrome/NativeMessagingHosts/com.linkcage.host.json` |
| Chromium | `~/.config/chromium/NativeMessagingHosts/com.linkcage.host.json` |
| Edge | `~/.config/microsoft-edge/NativeMessagingHosts/com.linkcage.host.json` |
| Firefox | `~/.mozilla/native-messaging-hosts/com.linkcage.host.json` |

Run the corresponding `uninstall` script to remove them all.

## Local Data Files

LinkCage stores data locally for URL verdict checks. These files are created automatically and are self-healing — deleting them is safe and acts as a reset.

**Windows:** `%LOCALAPPDATA%\LinkCage\`
**macOS/Linux:** `~/.linkcage/`

| File | Purpose | Contains Personal Data? | Regeneration |
|------|---------|------------------------|-------------|
| `cache.sqlite` | Verdict cache — stores every URL you checked, the verdict result, source, reason, and timestamps. **Purpose:** speeds up repeat checks (instant instead of re-scanning) and provides consistent verdicts within the TTL window. | **Yes** — contains a full history of every link you sandboxed | Recreated automatically on next use. Expired entries are pruned periodically. |
| `urlhaus.txt` | URLhaus malware feed — a downloaded list of known malicious domains from abuse.ch | **No** — public threat feed, same for everyone | Re-downloaded automatically if missing or older than 6 hours |
| `linkcage-debug.log` | Debug log for troubleshooting launcher issues. Records URLs opened and internal state. | **Yes** — contains URLs you opened | Not recreated. Safe to delete anytime. |

### Privacy Controls

Both data-storing features can be disabled in `config.json`:

```json
{
  "debug_log": false,
  "verdict": {
    "cache_enabled": false
  }
}
```

| Setting | Default | What it controls |
|---------|---------|-----------------|
| `debug_log` | `false` | When `false`, no debug log is written. Enable only when troubleshooting. |
| `verdict.cache_enabled` | `true` | When `false`, no URL history is stored locally. Each click re-checks the URL from scratch. Slightly slower (~100ms for URLhaus, ~1-2s for GSB) but no local record of what you opened. |

### What Is and Isn't Tracked

LinkCage **only logs the initial URL you right-click** to send to the sandbox — the one you select via "Open in Sandbox" from the context menu. That URL goes through the verdict check and, if caching is enabled, is stored in `cache.sqlite`.

**Once inside the sandbox**, any browsing you do (clicking links, navigating pages, submitting forms) happens entirely within the Docker container. LinkCage has no visibility into that activity — it is not recorded, cached, or logged. The container uses ephemeral `tmpfs` storage, so all in-sandbox browsing history is destroyed when the container stops.

**To clear existing history:** delete `cache.sqlite` and `linkcage-debug.log`, or run the `uninstall` command which removes the entire data directory.

## Offline Behavior

LinkCage is designed to work without a network connection. All verdict checks fail-open — if a check can't complete, the link opens in the sandbox with an UNKNOWN verdict rather than being blocked.

| Component | Online | Offline |
|-----------|--------|---------|
| **URLhaus feed sync** | Downloads fresh feed every 6 hours | Uses existing local feed. If no feed exists (first run), all verdicts return UNKNOWN. |
| **URLhaus check** | N/A — always local file scan | Works normally. No network needed. |
| **Google Safe Browsing** | API call to Google | Fails silently, falls through to next provider. |
| **Verdict result** | SAFE / SUSPICIOUS / MALICIOUS based on providers | UNKNOWN if no feed exists; normal verdicts if a stale feed is present. |
| **Docker container** | Works | Works — container runs locally. |
| **Setup (first time)** | Pulls image from Docker Hub | Fails if image not already local. Build locally with `docker build -t luisyax/linkcage-sandbox:hardened docker/` |

**Key point:** Once you've run setup and synced the URLhaus feed at least once, LinkCage works fully offline. The local feed continues to catch known malware domains even without internet. The feed just won't update until connectivity returns.

## Rebuilding the Image

The hardened image is built fresh from the latest LinuxServer Chromium base: it applies the full Debian security upgrade and purges packages a streamed browser sandbox never needs. Rebuild with `--pull --no-cache` to pick up newly published patches:

```bash
docker build --pull --no-cache -t luisyax/linkcage-sandbox:hardened docker/
```

Verify the result with [Trivy](https://trivy.dev) — no install required, run it via its own container:

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image --severity HIGH,CRITICAL \
  luisyax/linkcage-sandbox:hardened
```

The build targets **zero *fixable* High/Critical CVEs**. A small number of High/Critical advisories remain that have **no upstream fix** and belong to packages the browser genuinely requires — the `mesa` GPU/software-rendering libraries and the `python3.13` runtime used by the streaming layer. They cannot be patched without breaking rendering, and are mitigated by the container isolation above. Add `--ignore-unfixed` to the Trivy command to see only actionable (fixable) findings.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Context menu doesn't appear | Reload extension in `chrome://extensions`, restart Chrome |
| "Native host has exited" error | Verify Python 3 is on PATH; test with `python host/launcher.py` |
| Container doesn't start | Check Docker Desktop is running; verify `composePath` in `config.json` |
| URL doesn't open in container | Check `docker logs chromium-browser` for errors |
| Dark/blank screen in container | Container may still be starting; wait a few seconds and retry |

## Uninstall

**Windows:** `powershell -ExecutionPolicy Bypass -File uninstall.ps1`
**macOS/Linux:** `./uninstall.sh`

This removes the Chrome, Edge, and Firefox host registrations. Then remove the extension itself from `chrome://extensions`, `edge://extensions`, or `about:addons` (Firefox).

## Roadmap

- [x] Firefox extension support
- [x] Edge browser support
- [ ] Safari support (macOS containing-app)
- [ ] Auto-dispose container when the sandbox window is closed (today this requires the 'Close Sandbox Browser' menu)
- [ ] Extension badge showing container status (running/stopped)
- [ ] URL audit log for sandboxed links
- [ ] One-click rebuild for image hardening updates

## Author

**Luis Yax**

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.

---

*Don't click it. Cage it.*
