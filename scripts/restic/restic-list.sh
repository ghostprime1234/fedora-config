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
install_if_missing rclone

if [[ ! -r "$RESTIC_PASSWORD_FILE" ]]; then
    echo "ERROR: Restic password file not found:"
    echo "  $RESTIC_PASSWORD_FILE"
    exit 1
fi

case "${1:-onedrive}" in
    nas)
        REPO="sftp:Michael@lab-ds423:/University/backups/restic"
        ;;
    onedrive)
        REPO="rclone:unisq_onedrive:University_Sync/Backups/restic"
        ;;
    *)
        echo "Usage: $0 {nas|onedrive}"
        exit 1
        ;;
esac

echo "Repository: $REPO"
echo

restic \
    --repo "$REPO" \
    --password-file "$RESTIC_PASSWORD_FILE" \
    snapshots
