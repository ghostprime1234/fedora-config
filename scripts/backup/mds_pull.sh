#!/usr/bin/env bash
# Pull the latest university files from the mini PC.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXCLUDES="$SCRIPT_DIR/rsync-excludes.txt"

# ------------------------------------------------------------
# Local path detection
# ------------------------------------------------------------

if [[ -d "/mnt/Data/University/" ]]; then
    # Desktop
    LOCAL_TARGET="/mnt/Data/University/"
elif [[ -d "$HOME/Documents/University/" ]]; then
    # Laptop
    LOCAL_TARGET="$HOME/Documents/University/"
else
    echo "ERROR: Local University directory does not exist."
    exit 1
fi

# ------------------------------------------------------------
# Server routing
# ------------------------------------------------------------

# Prefer the LAN connection when at home.
if ping -c 1 -W 1 192.168.8.2 >/dev/null 2>&1; then
    echo "Home network detected. Using LAN connection."
    REMOTE_HOST="michael@192.168.8.2"
else
    echo "LAN server unavailable. Using Tailscale/SSH configuration."
    REMOTE_HOST="server"
fi

REMOTE_SOURCE="$REMOTE_HOST:/home/michael/University/"

# ------------------------------------------------------------
# Pull
# ------------------------------------------------------------

echo "Pulling latest files from Mini PC..."

rsync -auv \
    --exclude-from="$EXCLUDES" \
    --exclude="snapshots/" \
    "$REMOTE_SOURCE" \
    "$LOCAL_TARGET"

echo "Pull complete."
