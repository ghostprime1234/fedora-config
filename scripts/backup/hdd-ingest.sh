#!/usr/bin/env bash
# Import university files from MDS_VAULT into the desktop working copy.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

HDD_MOUNT="/mnt/MDS_VAULT"
HDD_SOURCE="$HDD_MOUNT/University_Vault/Live_Work/"
LOCAL_TARGET="/mnt/Data/University/"
BACKUP_SCRIPT="$SCRIPT_DIR/mds_backup.sh"
HDD_UUID="a358df98-79a1-42fb-af5c-d38f43c60305"
DATA_UUID="5ae96703-ba78-4401-9c92-9d06dd52589d"
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

# ------------------------------------------------------------
# Validate HDD
# ------------------------------------------------------------

if ! mountpoint -q "$HDD_MOUNT"; then
    echo "ERROR: MDS_VAULT is not mounted at $HDD_MOUNT"
    exit 1
fi

HDD_IDENTITY="$(findmnt -n -o FSTYPE,LABEL,UUID --target "$HDD_MOUNT")"
if [[ "$HDD_IDENTITY" != "btrfs MDS_VAULT $HDD_UUID" ]]; then
    echo "ERROR: The filesystem mounted at $HDD_MOUNT is not the expected MDS_VAULT"
    echo "       Btrfs filesystem (UUID $HDD_UUID)."
    exit 1
fi

if [[ ! -d "$HDD_SOURCE" ]]; then
    echo "ERROR: University vault not found at $HDD_SOURCE"
    exit 1
fi

if [[ ! -d "$LOCAL_TARGET" ]]; then
    echo "ERROR: Local University directory not found at $LOCAL_TARGET"
    exit 1
fi

if [[ "$(findmnt -n -o UUID --target "$LOCAL_TARGET")" != "$DATA_UUID" ]]; then
    echo "ERROR: $LOCAL_TARGET is not on the expected data drive (UUID $DATA_UUID)."
    exit 1
fi

if [[ -z "$(find "$HDD_SOURCE" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "ERROR: University vault is empty; refusing a sync that could delete local files."
    exit 1
fi

# ------------------------------------------------------------
# Ingest
# ------------------------------------------------------------

echo "Importing MDS_VAULT into desktop working copy..."

rsync -avu \
    "${RSYNC_DRY_ARGS[@]}" \
    --delete \
    --exclude="snapshots/" \
    "$HDD_SOURCE" \
    "$LOCAL_TARGET"

# ------------------------------------------------------------
# Backup
# ------------------------------------------------------------

if [[ -x "$BACKUP_SCRIPT" ]]; then
    echo "Running MDS backup workflow..."
    if [[ "$DRY_RUN" == true ]]; then
        "$BACKUP_SCRIPT" --dry-run
    else
        "$BACKUP_SCRIPT"
    fi
else
    echo "Warning: mds_backup.sh not found or not executable."
fi

# ------------------------------------------------------------
# Notification
# ------------------------------------------------------------

if [[ "$DRY_RUN" != true ]] && command -v notify-send >/dev/null 2>&1; then
    notify-send \
        "MDS Vault" \
        "Ingest complete." \
        --icon=drive-harddisk
fi

if [[ "$DRY_RUN" == true ]]; then
    echo "MDS Vault ingest dry run complete."
else
    echo "MDS Vault ingest complete."
fi
