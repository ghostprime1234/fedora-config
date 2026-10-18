#!/usr/bin/env bash
set -euo pipefail

LOCAL_DIR="/home/michael/University"
REMOTE_TARGET="onedrive:University_Backup"
EXCLUDE_FILE="/home/michael/scripts/rclone-excludes.txt"

# Abort if source folder is missing or unmounted
if [[ ! -d "$LOCAL_DIR" ]]; then
    echo "Error: Source directory $LOCAL_DIR not found." >&2
    exit 1
fi

# Sync to OneDrive:
# --fast-list reduces API transaction calls
# --transfers 4 runs up to 4 uploads in parallel
rclone sync "$LOCAL_DIR" "$REMOTE_TARGET" \
    --filter-from "$EXCLUDE_FILE" \
    --fast-list \
    --transfers 4 \
    --checkers 8 \
    --log-level NOTICE
