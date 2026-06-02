#!/bin/bash
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
#
# LinkCage - macOS/Linux Installer
# Registers the native messaging host for Chrome/Chromium.
#
# Usage: ./install.sh <chrome-extension-id> [firefox-gecko-id]
#

set -e

HOST_NAME="com.linkcage.host"

# Published Web Store extension IDs. After the extension is approved, add each
# store-assigned ID here (Chrome Web Store + Edge Add-ons). Store-installed users
# then get native messaging without passing an ID; dev/unpacked installs still
# pass their own ID as the first argument.
PUBLISHED_EXTENSION_IDS=(
    "namalaooippodkhbjpjnagbgpggcphld"  # Edge Add-ons (LinkCage)
    # "<chrome-web-store-id>"           # add after Chrome approval
)

if [ -z "$1" ] && [ ${#PUBLISHED_EXTENSION_IDS[@]} -eq 0 ]; then
    echo "Usage: $0 <chrome-extension-id> [firefox-gecko-id]"
    echo ""
    echo "  Get the extension ID from chrome://extensions after loading the unpacked extension."
    echo "  (Optional once a published Store ID is baked into this script.)"
    echo "  firefox-gecko-id defaults to linkcage@yaxzone."
    exit 1
fi

# --- Dependency checks ----------------------------------------------------
# LinkCage needs Docker (to run the sandboxed browser) and Python 3.10+
# (the background helper). Fail fast with a friendly message rather than
# registering the host and breaking silently at runtime.

DOCKER_URL="https://www.docker.com/products/docker-desktop/"
PYTHON_URL="https://www.python.org/downloads/"
MISSING=0

if ! command -v docker > /dev/null 2>&1; then
    echo "ERROR: Docker is not installed."
    echo "       LinkCage needs Docker Desktop to run the sandboxed browser."
    echo "       Download: $DOCKER_URL"
    echo ""
    MISSING=1
elif ! docker info > /dev/null 2>&1; then
    echo "WARNING: Docker is installed but the daemon isn't responding."
    echo "         macOS/Windows: start Docker Desktop from your menu bar / tray."
    echo "         Linux: 'sudo systemctl start docker' (and make sure your user is in the 'docker' group)."
    echo ""
    # Not fatal — user can start it after install completes.
fi

# Find a usable Python 3.10+. Don't trust `command -v` alone — on Windows
# the "python3" name can be a Microsoft Store stub that exits with an error
# message but counts as present. We actually run the candidate to verify.
PYTHON_CMD=""
PYTHON_FOUND_BUT_TOO_OLD=""
for candidate in python3 python; do
    if command -v "$candidate" > /dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' > /dev/null 2>&1; then
            PYTHON_CMD="$candidate"
            break
        fi
        if [ -z "$PYTHON_FOUND_BUT_TOO_OLD" ]; then
            V=$("$candidate" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || true)
            if [ -n "$V" ]; then
                PYTHON_FOUND_BUT_TOO_OLD="$candidate ($V)"
            fi
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    if [ -n "$PYTHON_FOUND_BUT_TOO_OLD" ]; then
        echo "ERROR: Python 3.10 or newer is required (found: $PYTHON_FOUND_BUT_TOO_OLD)."
        echo "       Download a newer version: $PYTHON_URL"
    else
        echo "ERROR: Python is not installed."
        echo "       LinkCage's background helper is written in Python (3.10 or newer)."
        echo "       Download: $PYTHON_URL"
    fi
    echo ""
    MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
    echo "Install the missing requirement(s) and run this script again."
    exit 1
fi
# --- end dependency checks -------------------------------------------------

EXTENSION_ID="$1"
GECKO_ID="${2:-linkcage@yaxzone}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_DIR="$SCRIPT_DIR/host"
LAUNCHER="$HOST_DIR/launcher.sh"

chmod +x "$LAUNCHER" "$HOST_DIR/launcher.py"

OS="$(uname -s)"
case "$OS" in
    Darwin)
        CHROME_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
        CHROMIUM_DIR="$HOME/Library/Application Support/Chromium/NativeMessagingHosts"
        EDGE_DIR="$HOME/Library/Application Support/Microsoft Edge/NativeMessagingHosts"
        FIREFOX_DIR="$HOME/Library/Application Support/Mozilla/NativeMessagingHosts"
        ;;
    Linux)
        CHROME_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
        CHROMIUM_DIR="$HOME/.config/chromium/NativeMessagingHosts"
        EDGE_DIR="$HOME/.config/microsoft-edge/NativeMessagingHosts"
        FIREFOX_DIR="$HOME/.mozilla/native-messaging-hosts"
        ;;
    *)
        echo "ERROR: Unsupported OS: $OS (use install.ps1 for Windows)"
        exit 1
        ;;
esac

build_manifest() {
    # Combine the dev/unpacked ID with any published Store IDs into the allow-list.
    local origins=()
    local id
    for id in "$EXTENSION_ID" "${PUBLISHED_EXTENSION_IDS[@]}"; do
        [ -n "$id" ] && origins+=("    \"chrome-extension://$id/\"")
    done
    local joined
    joined=$(printf '%s,\n' "${origins[@]}")
    joined=${joined%,$'\n'}
    cat <<MANIFEST
{
  "name": "$HOST_NAME",
  "description": "LinkCage - Opens links in a sandboxed Docker Chromium container",
  "path": "$LAUNCHER",
  "type": "stdio",
  "allowed_origins": [
$joined
  ]
}
MANIFEST
}

# Firefox: same launcher, allowed_extensions instead of allowed_origins
build_firefox_manifest() {
    cat <<MANIFEST
{
  "name": "$HOST_NAME",
  "description": "LinkCage - Opens links in a sandboxed Docker Chromium container",
  "path": "$LAUNCHER",
  "type": "stdio",
  "allowed_extensions": [
    "$GECKO_ID"
  ]
}
MANIFEST
}

# Chrome, Chromium and Edge all use the same Chromium-format manifest
# (allowed_origins); each just reads it from its own location.
for dir in "$CHROME_DIR" "$CHROMIUM_DIR" "$EDGE_DIR"; do
    if [ -d "$(dirname "$dir")" ]; then
        mkdir -p "$dir"
        build_manifest > "$dir/$HOST_NAME.json"
        echo "[OK] Installed: $dir/$HOST_NAME.json"
    fi
done

# Firefox always gets registered (its parent dir may not exist until first run)
mkdir -p "$FIREFOX_DIR"
build_firefox_manifest > "$FIREFOX_DIR/$HOST_NAME.json"
echo "[OK] Installed: $FIREFOX_DIR/$HOST_NAME.json"

echo ""
echo "=== LinkCage - Installed ==="
echo "  Extension ID: $EXTENSION_ID"
echo "  Gecko ID:     $GECKO_ID"
echo ""
echo "Next steps:"
echo "  1. Restart Chrome/Chromium if it's running"
echo "  2. Right-click any link -> 'LinkCage: Open in Sandbox'"
echo ""
