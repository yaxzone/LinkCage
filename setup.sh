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
# LinkCage - Setup & Management (macOS / Linux)
#
# Usage:
#   ./setup.sh              Full setup
#   ./setup.sh start        Start the sandbox container + open browser
#   ./setup.sh stop         Stop the container + close browser
#   ./setup.sh status       Show container and browser status
#   ./setup.sh uninstall    Full removal
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_NAME="com.linkcage.host"
CONFIG_PATH="$SCRIPT_DIR/config.json"
GECKO_ID="${GECKO_ID:-linkcage@yaxzone}"

# ── Colors ───────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
NC='\033[0m'

# ── Python helper ────────────────────────────────────────────────
# PYTHON_CMD bootstraps the venv once; all runtime calls use VENV_PY.
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
if [ -x "$VENV_PY" ]; then
    PY="$VENV_PY"
else
    PY="$PYTHON_CMD"
fi

# ── Load config ──────────────────────────────────────────────────
get_config() {
    "$PY" -c "
import json
try:
    c = json.load(open('$CONFIG_PATH'))
except: c = {}
print(c.get('$1', '$2'))
"
}

OS="$(uname -s)"

# Determine NativeMessagingHosts directories
case "$OS" in
    Darwin)
        CHROME_NMH_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
        CHROMIUM_NMH_DIR="$HOME/Library/Application Support/Chromium/NativeMessagingHosts"
        EDGE_NMH_DIR="$HOME/Library/Application Support/Microsoft Edge/NativeMessagingHosts"
        FIREFOX_NMH_DIR="$HOME/Library/Application Support/Mozilla/NativeMessagingHosts"
        ;;
    Linux)
        CHROME_NMH_DIR="$HOME/.config/google-chrome/NativeMessagingHosts"
        CHROMIUM_NMH_DIR="$HOME/.config/chromium/NativeMessagingHosts"
        EDGE_NMH_DIR="$HOME/.config/microsoft-edge/NativeMessagingHosts"
        FIREFOX_NMH_DIR="$HOME/.mozilla/native-messaging-hosts"
        ;;
esac

# ══════════════════════════════════════════════════════════════════
# ── STOP ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
cmd_stop() {
    CONTAINER_NAME="$(get_config containerName chromium-browser)"
    COMPOSE_PATH="$(get_config composePath "$SCRIPT_DIR/docker")"
    COMPOSE_FILE="$(get_config composeFile docker-compose.yml)"
    PROFILE_DIR="$(get_config chromiumProfileDir .chromium-profile)"
    USER_DATA_DIR="$COMPOSE_PATH/$PROFILE_DIR"

    # Close sandbox browser window
    echo -e "${CYAN}Closing sandbox browser window...${NC}"
    if [ "$OS" = "Darwin" ]; then
        # Find Chrome processes using our user-data-dir
        pgrep -f "user-data-dir=.*$PROFILE_DIR" | while read pid; do
            kill "$pid" 2>/dev/null || true
        done
    else
        pkill -f "user-data-dir=.*$PROFILE_DIR" 2>/dev/null || true
    fi
    echo -e "${GREEN}  Browser window closed.${NC}"

    # Stop Docker container
    RUNNING=$(docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" 2>/dev/null)
    if [ -n "$RUNNING" ]; then
        echo -e "${CYAN}Stopping sandbox container...${NC}"
        docker compose -f "$COMPOSE_PATH/$COMPOSE_FILE" down
        echo -e "${GREEN}  Container stopped.${NC}"
    else
        echo -e "${GRAY}  Container is not running.${NC}"
    fi
}

# ══════════════════════════════════════════════════════════════════
# ── START ────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
cmd_start() {
    CONTAINER_NAME="$(get_config containerName chromium-browser)"
    COMPOSE_PATH="$(get_config composePath "$SCRIPT_DIR/docker")"
    COMPOSE_FILE="$(get_config composeFile docker-compose.yml)"
    PROTOCOL="$(get_config protocol https)"
    PORT="$(get_config localPort 3443)"
    PROFILE_DIR="$(get_config chromiumProfileDir .chromium-profile)"
    USER_DATA_DIR="$COMPOSE_PATH/$PROFILE_DIR"

    # Start container if not running
    RUNNING=$(docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" 2>/dev/null)
    if [ -n "$RUNNING" ]; then
        echo -e "${YELLOW}Sandbox container is already running.${NC}"
    else
        echo -e "${GREEN}Starting sandbox container...${NC}"
        docker compose -f "$COMPOSE_PATH/$COMPOSE_FILE" up -d
    fi

    # Open browser
    CONTAINER_URL="${PROTOCOL}://localhost:${PORT}"
    echo -e "${CYAN}Opening sandbox browser...${NC}"
    if [ "$OS" = "Darwin" ]; then
        open -a "Google Chrome" --args --incognito --user-data-dir="$USER_DATA_DIR" "$CONTAINER_URL"
    else
        BROWSER="google-chrome"
        command -v google-chrome &>/dev/null || BROWSER="chromium-browser"
        command -v chromium-browser &>/dev/null || BROWSER="chromium"
        "$BROWSER" --incognito --user-data-dir="$USER_DATA_DIR" "$CONTAINER_URL" &>/dev/null &
    fi
    echo -e "${GREEN}  Done.${NC}"
}

# ══════════════════════════════════════════════════════════════════
# ── STATUS ───────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
cmd_status() {
    CONTAINER_NAME="$(get_config containerName chromium-browser)"
    PROFILE_DIR="$(get_config chromiumProfileDir .chromium-profile)"

    echo ""
    echo -e "${CYAN}  LinkCage Status${NC}"
    echo -e "${CYAN}  ───────────────${NC}"

    # Container
    RUNNING=$(docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" 2>/dev/null)
    if [ -n "$RUNNING" ]; then
        docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        echo -e "${YELLOW}  Container: Not running${NC}"
    fi

    # Browser
    if pgrep -f "user-data-dir=.*$PROFILE_DIR" &>/dev/null; then
        echo -e "${GREEN}  Browser:   Running${NC}"
    else
        echo -e "${GRAY}  Browser:   Not running${NC}"
    fi

    # Host registration
    HOST_FOUND=0
    for dir in "$CHROME_NMH_DIR" "$CHROMIUM_NMH_DIR"; do
        if [ -f "$dir/$HOST_NAME.json" ]; then
            HOST_FOUND=1
            break
        fi
    done
    if [ $HOST_FOUND -eq 1 ]; then
        echo -e "${GREEN}  Host:      Registered (Chrome)${NC}"
    else
        echo -e "${YELLOW}  Host:      Not registered (Chrome)${NC}"
    fi
    if [ -f "$EDGE_NMH_DIR/$HOST_NAME.json" ]; then
        echo -e "${GREEN}  Host:      Registered (Edge)${NC}"
    else
        echo -e "${YELLOW}  Host:      Not registered (Edge)${NC}"
    fi
    if [ -f "$FIREFOX_NMH_DIR/$HOST_NAME.json" ]; then
        echo -e "${GREEN}  Host:      Registered (Firefox)${NC}"
    else
        echo -e "${YELLOW}  Host:      Not registered (Firefox)${NC}"
    fi
    echo ""
}

# ══════════════════════════════════════════════════════════════════
# ── UNINSTALL ────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
cmd_uninstall() {
    echo ""
    echo -e "${YELLOW}  LinkCage - Uninstalling...${NC}"
    echo ""

    CONTAINER_NAME="$(get_config containerName chromium-browser)"
    COMPOSE_PATH="$(get_config composePath "$SCRIPT_DIR/docker")"
    COMPOSE_FILE="$(get_config composeFile docker-compose.yml)"
    PROFILE_DIR="$(get_config chromiumProfileDir .chromium-profile)"
    USER_DATA_DIR="$COMPOSE_PATH/$PROFILE_DIR"

    # Stop browser
    pkill -f "user-data-dir=.*$PROFILE_DIR" 2>/dev/null || true
    echo -e "${GREEN}  Browser closed.${NC}"

    # Stop container
    RUNNING=$(docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" 2>/dev/null)
    if [ -n "$RUNNING" ]; then
        docker compose -f "$COMPOSE_PATH/$COMPOSE_FILE" down
        echo -e "${GREEN}  Container stopped.${NC}"
    fi

    # Remove host manifests (Chrome/Chromium/Edge + Firefox)
    for dir in "$CHROME_NMH_DIR" "$CHROMIUM_NMH_DIR" "$EDGE_NMH_DIR" "$FIREFOX_NMH_DIR"; do
        manifest="$dir/$HOST_NAME.json"
        if [ -f "$manifest" ]; then
            rm "$manifest"
            echo -e "${GREEN}  Removed: $manifest${NC}"
        fi
    done

    # Clean up browser profile
    if [ -d "$USER_DATA_DIR" ]; then
        rm -rf "$USER_DATA_DIR"
        echo -e "${GREEN}  Browser profile cleaned.${NC}"
    fi

    # Remove LinkCage data directory (verdict cache, URLhaus feed, debug logs)
    LINKCAGE_DATA_DIR="$HOME/.linkcage"
    if [ -d "$LINKCAGE_DATA_DIR" ]; then
        rm -rf "$LINKCAGE_DATA_DIR"
        echo -e "${GREEN}  LinkCage data directory removed (verdict cache, URLhaus feed).${NC}"
    fi

    # Remove project virtualenv
    if [ -d "$VENV_DIR" ]; then
        rm -rf "$VENV_DIR"
        echo -e "${GREEN}  Virtualenv removed.${NC}"
    fi

    echo ""
    echo -e "${GREEN}  ╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}  ║       LinkCage - Uninstalled             ║${NC}"
    echo -e "${GREEN}  ╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${WHITE}  Remove the extension from chrome://extensions manually.${NC}"
    echo -e "${GRAY}  To remove the Docker image: docker rmi luisyax/linkcage-sandbox:hardened${NC}"
    echo ""
}

# ══════════════════════════════════════════════════════════════════
# ── SETUP (default) ──────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════
cmd_setup() {
    # ── Banner ───────────────────────────────────────────────────
    echo ""
    echo -e "${CYAN}  ╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}  ║          LinkCage Setup v1.0.0           ║${NC}"
    echo -e "${CYAN}  ║    Don't click it. Cage it.              ║${NC}"
    echo -e "${CYAN}  ╚══════════════════════════════════════════╝${NC}"
    echo ""

    # ── Step 1: Check prerequisites ──────────────────────────────
    echo -e "${YELLOW}[1/6] Checking prerequisites...${NC}"

    if ! command -v docker &> /dev/null; then
        echo -e "${RED}  ERROR: Docker is not installed.${NC}"
        exit 1
    fi
    if ! docker info &> /dev/null; then
        echo -e "${RED}  ERROR: Docker is not running. Start Docker Desktop first.${NC}"
        exit 1
    fi
    echo -e "${GREEN}  Docker: OK${NC}"

    if ! command -v $PYTHON_CMD &> /dev/null; then
        echo -e "${RED}  ERROR: Python 3 is not installed or not on PATH.${NC}"
        exit 1
    fi
    echo -e "${GREEN}  Python: OK${NC}"

    # Isolated virtualenv — host Python runs here, never against system Python
    if [ ! -x "$VENV_PY" ]; then
        echo -e "${CYAN}  Creating virtualenv at .venv ...${NC}"
        "$PYTHON_CMD" -m venv "$VENV_DIR"
        if [ ! -x "$VENV_PY" ]; then
            echo -e "${RED}  ERROR: Failed to create virtualenv.${NC}"
            exit 1
        fi
    fi
    if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        "$VENV_PY" -m pip install --quiet --upgrade pip
        "$VENV_PY" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
    fi
    PY="$VENV_PY"
    echo -e "${GREEN}  Virtualenv: OK${NC}"

    CHROME_CMD=""
    if [ "$OS" = "Darwin" ]; then
        if [ -d "/Applications/Google Chrome.app" ]; then
            CHROME_CMD="open -a 'Google Chrome'"
            echo -e "${GREEN}  Chrome: OK${NC}"
        fi
    else
        for cmd in google-chrome chromium-browser chromium; do
            if command -v $cmd &> /dev/null; then
                CHROME_CMD="$cmd"
                echo -e "${GREEN}  Chrome/Chromium: OK${NC}"
                break
            fi
        done
    fi
    [ -z "$CHROME_CMD" ] && echo -e "${YELLOW}  WARNING: Chrome/Chromium not found.${NC}"

    # ── Step 2: Pull image ───────────────────────────────────────
    echo ""
    echo -e "${YELLOW}[2/6] Checking Docker image...${NC}"
    if docker images luisyax/linkcage-sandbox:hardened --format "{{.ID}}" 2>/dev/null | grep -q .; then
        echo -e "${GREEN}  Image already present, skipping pull.${NC}"
    else
        echo -e "${YELLOW}  Pulling hardened Docker image...${NC}"
        if docker pull luisyax/linkcage-sandbox:hardened; then
            echo -e "${GREEN}  Image pulled: OK${NC}"
        else
            echo -e "${RED}  ERROR: Failed to pull image. No network or Docker Hub unreachable.${NC}"
            echo -e "${YELLOW}  You can build locally instead: docker build -t luisyax/linkcage-sandbox:hardened docker/${NC}"
            exit 1
        fi
    fi

    # ── Step 3: Configure ────────────────────────────────────────
    echo ""
    echo -e "${YELLOW}[3/6] Configuring environment...${NC}"

    DOCKER_DIR="$SCRIPT_DIR/docker"
    "$PY" - "$CONFIG_PATH" "$DOCKER_DIR" <<'PYEOF'
import json, sys
config_path, docker_dir = sys.argv[1], sys.argv[2]
with open(config_path, 'r') as f:
    config = json.load(f)
if not config.get('composePath'):
    config['composePath'] = docker_dir
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"  composePath set to: {docker_dir}")
PYEOF
    echo -e "${GREEN}  Config: OK${NC}"

    # ── Step 4: Load Chrome extension ────────────────────────────
    echo ""
    echo -e "${YELLOW}[4/6] Chrome extension setup...${NC}"
    echo ""

    EXTENSION_DIR="$SCRIPT_DIR/extension"

    if [ -n "$CHROME_CMD" ]; then
        echo -e "${CYAN}  Opening Chrome to the extensions page...${NC}"
        if [ "$OS" = "Darwin" ]; then
            open -a "Google Chrome" "chrome://extensions" 2>/dev/null || true
        else
            $CHROME_CMD "chrome://extensions" &>/dev/null &
        fi
    fi

    echo ""
    echo -e "${WHITE}  ┌────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${WHITE}  │  In Chrome:                                                │${NC}"
    echo -e "${WHITE}  │                                                            │${NC}"
    echo -e "${WHITE}  │  1. Enable 'Developer mode' (toggle, top right)           │${NC}"
    echo -e "${WHITE}  │  2. Click 'Load unpacked'                                  │${NC}"
    echo -e "${WHITE}  │  3. Select this folder:                                    │${NC}"
    echo -e "${YELLOW}  │     $EXTENSION_DIR${NC}"
    echo -e "${WHITE}  │  4. Copy the Extension ID shown on the card                │${NC}"
    echo -e "${WHITE}  │                                                            │${NC}"
    echo -e "${WHITE}  └────────────────────────────────────────────────────────────┘${NC}"
    echo ""

    read -rp "  Paste your Extension ID here: " EXTENSION_ID
    EXTENSION_ID="$(echo "$EXTENSION_ID" | tr -d '[:space:]')"

    if [ -z "$EXTENSION_ID" ] || [ ${#EXTENSION_ID} -lt 10 ]; then
        echo -e "${RED}  ERROR: Invalid Extension ID.${NC}"
        exit 1
    fi
    echo -e "${GREEN}  Extension ID: $EXTENSION_ID${NC}"

    # ── Step 5: Register native messaging host ───────────────────
    echo ""
    echo -e "${YELLOW}[5/6] Registering native messaging host...${NC}"

    LAUNCHER="$SCRIPT_DIR/host/launcher.sh"
    chmod +x "$LAUNCHER" "$SCRIPT_DIR/host/launcher.py"

    build_manifest() {
        cat <<MANIFEST
{
  "name": "$HOST_NAME",
  "description": "LinkCage - Opens links in a sandboxed Docker Chromium container",
  "path": "$LAUNCHER",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXTENSION_ID/"
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

    # Chrome, Chromium and Edge share the same Chromium-format manifest.
    for dir in "$CHROME_NMH_DIR" "$CHROMIUM_NMH_DIR" "$EDGE_NMH_DIR"; do
        if [ -d "$(dirname "$dir")" ]; then
            mkdir -p "$dir"
            build_manifest > "$dir/$HOST_NAME.json"
            echo -e "${GREEN}  Installed: $dir/$HOST_NAME.json${NC}"
        fi
    done

    # Firefox always gets registered (its parent dir may not exist until first run)
    mkdir -p "$FIREFOX_NMH_DIR"
    build_firefox_manifest > "$FIREFOX_NMH_DIR/$HOST_NAME.json"
    echo -e "${GREEN}  Installed: $FIREFOX_NMH_DIR/$HOST_NAME.json (gecko id: $GECKO_ID)${NC}"

    # ── Step 6: Start the container ──────────────────────────────
    echo ""
    echo -e "${YELLOW}[6/6] Starting sandbox container...${NC}"

    COMPOSE_PATH="$("$PY" -c "import json; print(json.load(open('$CONFIG_PATH'))['composePath'])")"
    COMPOSE_FILE="$COMPOSE_PATH/docker-compose.yml"

    if [ -f "$COMPOSE_FILE" ]; then
        # Remove stale container if it exists but is stopped
        STALE=$(docker ps -a --filter "name=chromium-browser" --filter "status=exited" --format "{{.ID}}" 2>/dev/null)
        if [ -n "$STALE" ]; then
            echo -e "${GRAY}  Removing stale container...${NC}"
            docker rm chromium-browser 2>/dev/null || true
        fi

        RUNNING=$(docker ps --filter "name=chromium-browser" --format "{{.Names}}" 2>/dev/null)
        if [ -n "$RUNNING" ]; then
            echo -e "${GREEN}  Container is already running.${NC}"
        else
            docker compose -f "$COMPOSE_FILE" up -d
            echo -e "${GREEN}  Container started: OK${NC}"
        fi
    else
        echo -e "${YELLOW}  WARNING: docker-compose.yml not found at $COMPOSE_FILE${NC}"
    fi

    # ── Done ─────────────────────────────────────────────────────
    echo ""
    echo -e "${GREEN}  ╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}  ║       LinkCage setup complete!           ║${NC}"
    echo -e "${GREEN}  ╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${WHITE}  1. Restart Chrome${NC}"
    echo -e "${WHITE}  2. Right-click any link -> 'LinkCage: Open in Sandbox'${NC}"
    echo ""
    echo -e "${GRAY}  Management commands:${NC}"
    echo -e "${GRAY}    ./setup.sh start      Start the sandbox${NC}"
    echo -e "${GRAY}    ./setup.sh stop       Stop the sandbox${NC}"
    echo -e "${GRAY}    ./setup.sh status     Check status${NC}"
    echo -e "${GRAY}    ./setup.sh uninstall  Full removal${NC}"
    echo ""
    echo -e "${CYAN}  Don't click it. Cage it.${NC}"
    echo ""
}

# ── Route command ────────────────────────────────────────────────
case "${1:-}" in
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    status)     cmd_status ;;
    uninstall)  cmd_uninstall ;;
    *)          cmd_setup ;;
esac
