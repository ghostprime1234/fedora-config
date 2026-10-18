#!/usr/bin/env bash

# ==============================================================================
# MDS WORKSTATION BACKUP & CLOUD TRIGGER
#
# 1. Desktop → USB vault live-work backup (Btrfs verified)
# 2. Triggers Fedora server to execute OneDrive cloud backup
#
# (Live file synchronization Desktop ↔ Laptop ↔ Server is handled by Syncthing)
# ==============================================================================

set -Eeuo pipefail

DRY_RUN=false

case "${1:-}" in
    --dry-run)
        DRY_RUN=true
        echo "=== DRY RUN MODE ==="
        ;;
    "")
        ;;
    *)
        echo "Usage: $0 [--dry-run]"
        exit 1
        ;;
esac

if (( $# > 1 )); then
    echo "Usage: $0 [--dry-run]"
    exit 1
fi

RSYNC_DRY_ARGS=()
if [[ "$DRY_RUN" == true ]]; then
    RSYNC_DRY_ARGS+=(--dry-run)
fi

# ==============================================================================
# 0. ENVIRONMENT CONFIGURATION
# ==============================================================================

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/mds_backup.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "⚠ CRITICAL ERROR: Configuration file '$ENV_FILE' not found."
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

REQUIRED_VARIABLES=(
    SOURCE
    LOCAL_VAULT
    EXCLUDES
    STATUS_FILE
    REMOTE_USER
    REMOTE_HOST
    REMOTE_SYNC_SCRIPT
    SSH_KEY
)

for variable in "${REQUIRED_VARIABLES[@]}"; do
    if [[ -z "${!variable:-}" ]]; then
        echo "⚠ CRITICAL ERROR: Required variable '$variable' is not configured."
        exit 1
    fi
done

SOURCE="${SOURCE%/}"
LOCAL_VAULT="${LOCAL_VAULT%/}"

if [[ ! "$REMOTE_USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "⚠ CRITICAL ERROR: REMOTE_USER contains unsupported characters."
    exit 1
fi

if [[ ! "$REMOTE_HOST" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "⚠ CRITICAL ERROR: REMOTE_HOST contains unsupported characters."
    exit 1
fi

# ==============================================================================
# 1. PATHS & GUARDIAN LAYER
# ==============================================================================

USB_LIVE_WORK="${LOCAL_VAULT}/Live_Work"
VAULT_MOUNT="/mnt/MDS_VAULT"
VAULT_UUID="a358df98-79a1-42fb-af5c-d38f43c60305"
DATA_UUID="${DATA_UUID:-b6ef847d-4259-4089-bc6a-f5552df0b2ab}"

SSH_ARGS=(
    -i "$SSH_KEY"
    -o BatchMode=yes
    -o ConnectTimeout=10
)
SSH_DESTINATION="${REMOTE_USER}@${REMOTE_HOST}"

echo "--- Running safety checks ---"

if [[ ! -d "$SOURCE" ]]; then
    echo "⚠ CRITICAL ERROR: Source directory does not exist: $SOURCE"
    exit 1
fi

if [[ "$(findmnt -n -o UUID --target "$SOURCE" 2>/dev/null || true)" != "$DATA_UUID" ]]; then
    echo "⚠ CRITICAL ERROR: Source is not on expected data drive (UUID: $DATA_UUID): $SOURCE"
    exit 1
fi

if [[ -z "$(find "$SOURCE" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "⚠ CRITICAL ERROR: Source directory is empty. Aborting: $SOURCE"
    exit 1
fi

if [[ ! -f "$EXCLUDES" ]]; then
    echo "⚠ CRITICAL ERROR: Rsync exclusions file does not exist: $EXCLUDES"
    exit 1
fi

if [[ ! -f "$SSH_KEY" ]]; then
    echo "⚠ CRITICAL ERROR: SSH private key does not exist: $SSH_KEY"
    exit 1
fi

# ==============================================================================
# 2. USB VAULT LIVE-WORK REPLICATION
# ==============================================================================

VAULT_IDENTITY="$(findmnt -n -t btrfs -o TARGET,FSTYPE,LABEL,UUID --target "$LOCAL_VAULT" 2>/dev/null || true)"

if [[ -d "$LOCAL_VAULT" &&
      "$VAULT_IDENTITY" == "$VAULT_MOUNT btrfs MDS_VAULT $VAULT_UUID" &&
      ( -w "$LOCAL_VAULT" || "$DRY_RUN" == true ) ]]; then

    if [[ "$DRY_RUN" != true ]]; then
        mkdir -p "$USB_LIVE_WORK"
    fi

    echo
    echo "--- Step 1: Replicating live work to USB vault ---"

    if ! rsync -avh --delete-after \
        "${RSYNC_DRY_ARGS[@]}" \
        --exclude-from="$EXCLUDES" \
        "$SOURCE/" \
        "$USB_LIVE_WORK/"; then

        echo "⚠ WARNING: USB vault replication failed."
    else
        echo "✓ USB vault replication complete."
    fi
else
    echo
    echo "⏸ USB vault unavailable, read-only, or UUID mismatch. Skipping USB copy:"
    echo "  Target: $LOCAL_VAULT"
fi

# ==============================================================================
# 3. REMOTE ONEDRIVE BACKUP TRIGGER
# ==============================================================================

echo
echo "--- Step 2: Triggering remote OneDrive sync on Fedora server ---"

if ssh "${SSH_ARGS[@]}" "$SSH_DESTINATION" "test -x $(printf '%q' "$REMOTE_SYNC_SCRIPT")" 2>/dev/null; then
    echo "✓ Connected to $SSH_DESTINATION."

    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY RUN] Would execute remote script: $REMOTE_SYNC_SCRIPT"
    else
        echo "Executing: $REMOTE_SYNC_SCRIPT on $REMOTE_HOST..."
        if ssh "${SSH_ARGS[@]}" "$SSH_DESTINATION" "$REMOTE_SYNC_SCRIPT"; then
            echo "✓ Remote cloud backup completed successfully."
        else
            echo "⚠ WARNING: Remote sync script returned an error."
        fi
    fi
else
    echo "⚠ WARNING: Fedora server is unreachable or remote script is not executable."
    echo "  Script path: $REMOTE_SYNC_SCRIPT"
    echo "Remote OneDrive backup was skipped."
fi

# ==============================================================================
# 4. STATUS LOGGING
# ==============================================================================

if [[ "$DRY_RUN" != true ]]; then
    mkdir -p "$(dirname "$STATUS_FILE")"

    {
        echo "Last Backup Run: $(date --iso-8601=seconds)"
        echo "Source: $SOURCE"
        echo "Vault: $USB_LIVE_WORK"
        echo "Cloud Trigger: ${SSH_DESTINATION}:${REMOTE_SYNC_SCRIPT}"
    } > "$STATUS_FILE"
fi

echo
echo "============================================================"
echo "✓ MDS backup and remote cloud trigger finished"
echo "  Source: $SOURCE"
echo "============================================================"
