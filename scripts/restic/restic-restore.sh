#!/usr/bin/env bash

set -Eeuo pipefail

RESTIC_PASSWORD_FILE="$HOME/.config/restic/university-password"

install_if_missing() {
    local package="$1"

    if ! command -v "$package" >/dev/null 2>&1; then
        echo "$package is not installed."
        echo "Installing $package..."
        sudo dnf install -y "$package"
    fi
}

install_if_missing restic

case "${1:-onedrive}" in
    nas)
        REPO="sftp:Michael@lab-ds423:/University/backups/restic"
        ;;
    onedrive)
        install_if_missing rclone
        REPO="rclone:unisq_onedrive:University_Sync/Backups/restic"
        ;;
    *)
        echo "Usage: $0 {nas|onedrive}"
        exit 1
        ;;
esac

if [[ ! -r "$RESTIC_PASSWORD_FILE" ]]; then
    echo "ERROR: Restic password file not found:"
    echo "  $RESTIC_PASSWORD_FILE"
    exit 1
fi

case "${1:-}" in
    nas)
        REPO="sftp:Michael@lab-ds423:/University/backups/restic"
        ;;
    onedrive)
        REPO="rclone:unisq_onedrive:University_Sync/Backups/restic"
        ;;
    *)
        echo "Usage:"
        echo "  $0 nas [snapshot] [target]"
        echo "  $0 onedrive [snapshot] [target]"
        echo
        echo "Examples:"
        echo "  $0 nas"
        echo "  $0 onedrive latest"
        echo "  $0 nas abc12345 ~/University-Restore"
        exit 1
        ;;
esac

SNAPSHOT="${2:-latest}"
TARGET="${3:-$HOME/restic-restore}"

echo "Repository: $REPO"
echo "Snapshot:   $SNAPSHOT"
echo "Target:     $TARGET"
echo

mkdir -p "$TARGET"

restic \
    --repo "$REPO" \
    --password-file "$RESTIC_PASSWORD_FILE" \
    restore "$SNAPSHOT" \
    --target "$TARGET"

echo
echo "Restore completed:"
echo "  $TARGET"
