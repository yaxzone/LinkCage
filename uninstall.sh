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
# LinkCage - macOS/Linux Uninstaller
# Removes the native messaging host registration.
#

set -e

HOST_NAME="com.linkcage.host"
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
        echo "ERROR: Unsupported OS: $OS (use uninstall.ps1 for Windows)"
        exit 1
        ;;
esac

for dir in "$CHROME_DIR" "$CHROMIUM_DIR" "$EDGE_DIR" "$FIREFOX_DIR"; do
    manifest="$dir/$HOST_NAME.json"
    if [ -f "$manifest" ]; then
        rm "$manifest"
        echo "[OK] Removed: $manifest"
    else
        echo "[--] Not found: $manifest"
    fi
done

echo ""
echo "=== LinkCage - Uninstalled ==="
echo "  Restart Chrome/Chromium for changes to take effect."
echo ""
