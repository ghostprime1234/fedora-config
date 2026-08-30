#!/usr/bin/env bash

# restore-fedora-data.sh
#
# Restore files after a clean Fedora installation.
#
# Usage:
#   ./restore-fedora-data.sh /path/to/backup
#
# Dry run:
#   DRY_RUN=1 ./restore-fedora-data.sh /path/to/backup

set -euo pipefail

SOURCE_ROOT="${1:-}"
DRY_RUN="${DRY_RUN:-0}"

if [[ -z "$SOURCE_ROOT" ]]; then
    echo "Usage: $0 /path/to/backup"
    exit 1
fi

if [[ ! -d "$SOURCE_ROOT" ]]; then
    echo "ERROR: Backup directory does not exist:"
    echo "  $SOURCE_ROOT"
    exit 1
fi

echo "========================================"
echo " Fedora Data Restore"
echo "========================================"
echo
echo "Source: $SOURCE_ROOT"
echo "Home:   $HOME"
echo

RSYNC_OPTS=(
    -a
    --human-readable
    --info=progress2
)

if [[ "$DRY_RUN" == "1" ]]; then
    RSYNC_OPTS+=(--dry-run)
    echo "DRY RUN ENABLED"
    echo "No files will actually be changed."
    echo
fi

sync_dir() {
    local source="$1"
    local destination="$2"

    if [[ ! -d "$source" ]]; then
        echo "Skipping missing directory: $source"
        return
    fi

    echo
    echo "Restoring:"
    echo "  $source"
    echo "     -> $destination"

    if [[ "$DRY_RUN" != "1" ]]; then
        mkdir -p "$destination"
    fi

    rsync "${RSYNC_OPTS[@]}" \
        "$source/" \
        "$destination/"
}

sync_file() {
    local source="$1"
    local destination="$2"

    if [[ ! -f "$source" ]]; then
        echo "Skipping missing file: $source"
        return
    fi

    echo
    echo "Restoring:"
    echo "  $source"
    echo "     -> $destination"

    if [[ "$DRY_RUN" != "1" ]]; then
        mkdir -p "$(dirname "$destination")"
    fi

    rsync "${RSYNC_OPTS[@]}" \
        "$source" \
        "$destination"
}


# ------------------------------------------------------------
# Standard home directories
# ------------------------------------------------------------

sync_dir "$SOURCE_ROOT/Desktop" \
         "$HOME/Desktop"

sync_dir "$SOURCE_ROOT/Documents" \
         "$HOME/Documents"

sync_dir "$SOURCE_ROOT/Pictures" \
         "$HOME/Pictures"

sync_dir "$SOURCE_ROOT/Videos" \
         "$HOME/Videos"


# ------------------------------------------------------------
# OBS recordings
# ------------------------------------------------------------

sync_dir "$SOURCE_ROOT/OBS Videos" \
         "$HOME/Videos/OBS Videos"


# ------------------------------------------------------------
# Projects and repositories
# ------------------------------------------------------------

sync_dir "$SOURCE_ROOT/Big-Data-Cluster" \
         "$HOME/Big-Data-Cluster"

if [[ -d "$HOME/fedora-config/.git" ]]; then
    echo
    echo "fedora-config already exists as a Git repository."
    echo "Skipping backed-up fedora-config restore."
else
    sync_dir "$SOURCE_ROOT/fedora-config" \
             "$HOME/fedora-config"
fi
sync_dir "$SOURCE_ROOT/openweb-ui" \
         "$HOME/openweb-ui"

sync_dir "$SOURCE_ROOT/exercism" \
         "$HOME/exercism"

sync_dir "$SOURCE_ROOT/system-inventory" \
         "$HOME/system-inventory"


# ------------------------------------------------------------
# Games
# ------------------------------------------------------------

sync_dir "$SOURCE_ROOT/Games" \
         "$HOME/Games"


# ------------------------------------------------------------
# Zotero
# ------------------------------------------------------------

sync_dir "$SOURCE_ROOT/Zotero" \
         "$HOME/Zotero"


# ------------------------------------------------------------
# Actual Budget
# ------------------------------------------------------------

sync_file \
    "$SOURCE_ROOT/Actual Budget Backup.zip" \
    "$HOME/Documents/Backups/Actual Budget/Actual Budget Backup.zip"


# ------------------------------------------------------------
# SSH
# ------------------------------------------------------------

if [[ -d "$SOURCE_ROOT/.ssh" ]]; then
    echo
    echo "Restoring SSH configuration and keys..."

    if [[ "$DRY_RUN" != "1" ]]; then
        mkdir -p "$HOME/.ssh"
    fi

    rsync "${RSYNC_OPTS[@]}" \
    --exclude='config' \
    "$SOURCE_ROOT/.ssh/" \
    "$HOME/.ssh/"

    # Only change permissions during a real restore.
    if [[ "$DRY_RUN" != "1" ]]; then
        chmod 700 "$HOME/.ssh"

        find "$HOME/.ssh" -type f -name "*.pub" \
            -exec chmod 644 {} \;

        find "$HOME/.ssh" -type f ! -name "*.pub" \
            -exec chmod 600 {} \;
    fi
fi


# ------------------------------------------------------------
# .local
# ------------------------------------------------------------

echo
echo "NOTE:"
echo "  $SOURCE_ROOT/.local has NOT been restored automatically."
echo "  Restore individual items from it only if required."


# ------------------------------------------------------------
# Final checks
# ------------------------------------------------------------

echo
echo "========================================"

if [[ "$DRY_RUN" == "1" ]]; then
    echo "Dry run complete."
    echo
    echo "If everything above looks correct, run:"
    echo
    echo "  ./restore-fedora-data.sh \"$SOURCE_ROOT\""
else
    echo "Restore complete."
    echo
    echo "Recommended checks:"
    echo
    echo "  ls -la ~"
    echo "  git -C ~/fedora-config status"
    echo "  git -C ~/Big-Data-Cluster status"
    echo "  ssh -T git@github.com"
fi

echo "========================================"
