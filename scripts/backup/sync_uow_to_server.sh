#!/usr/bin/env bash

set -Eeuo pipefail

SOURCE="/mnt/Data/University/UOW"
REMOTE_DESTINATION="michael@michael-server-fedora"
REMOTE_PATH="/data/University/UOW"
DEST="${REMOTE_DESTINATION}:${REMOTE_PATH}"
SSH_KEY="$HOME/.ssh/id_ed25519_desktop"
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

echo "Starting UOW sync..."

if [[ ! -d "$SOURCE" ]]; then
    echo "ERROR: Source directory does not exist:"
    echo "  $SOURCE"
    exit 1
fi

if [[ -z "$(find "$SOURCE" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "ERROR: Source directory is empty:"
    echo "  $SOURCE"
    echo "Aborting to prevent accidental deletion of remote data."
    exit 1
fi

if [[ ! -f "$SSH_KEY" ]]; then
    echo "ERROR: SSH key does not exist:"
    echo "  $SSH_KEY"
    exit 1
fi

SSH_ARGS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15)
printf -v SSH_TRANSPORT 'ssh -i %q -o BatchMode=yes -o ConnectTimeout=15' "$SSH_KEY"
printf -v REMOTE_DIRECTORY_TEST 'test -d %q' "$REMOTE_PATH"

# REMOTE_PATH_SHELL was escaped with printf %q above.
# shellcheck disable=SC2029
if ! ssh "${SSH_ARGS[@]}" "$REMOTE_DESTINATION" "$REMOTE_DIRECTORY_TEST"; then
    echo "ERROR: Remote destination does not exist or could not be validated:"
    echo "  $DEST"
    exit 1
fi

rsync -avh \
    "${RSYNC_DRY_ARGS[@]}" \
    --delete \
    --progress \
    -e "$SSH_TRANSPORT" \
    "$SOURCE/" \
    "$DEST/"

echo "UOW sync complete."
