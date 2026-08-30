#!/usr/bin/env bash

# ==============================================================================
# MDS WORKSTATION SYNCHRONISATION
#
# Desktop ↔ Fedora server live-file synchronisation
# Desktop → USB vault live-work replication
# Fedora server handles snapshots, archives, NAS and OneDrive backups
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
    REMOTE_PATH
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
REMOTE_PATH="${REMOTE_PATH%/}"

if [[ ! "$REMOTE_USER" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "⚠ CRITICAL ERROR: REMOTE_USER contains unsupported characters."
    exit 1
fi

if [[ ! "$REMOTE_HOST" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "⚠ CRITICAL ERROR: REMOTE_HOST contains unsupported characters."
    exit 1
fi

if [[ ! "$REMOTE_PATH" =~ ^/[A-Za-z0-9._/-]+$ || "$REMOTE_PATH" == "/" ]]; then
    echo "⚠ CRITICAL ERROR: REMOTE_PATH must be a safe absolute path other than '/'."
    exit 1
fi

# ==============================================================================
# 1. NETWORK / PATH CONFIGURATION
# ==============================================================================

SSH_ARGS=(
    -i "$SSH_KEY"
    -o BatchMode=yes
    -o ConnectTimeout=15
)

SSH_DESTINATION="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_TARGET="${SSH_DESTINATION}:${REMOTE_PATH}"

printf -v SSH_TRANSPORT 'ssh -i %q -o BatchMode=yes -o ConnectTimeout=15' "$SSH_KEY"
printf -v REMOTE_DIRECTORY_TEST 'test -d %q' "$REMOTE_PATH"
printf -v REMOTE_NESTING_TEST 'test -d %q' "${REMOTE_PATH}/University"

USB_LIVE_WORK="${LOCAL_VAULT}/Live_Work"
VAULT_MOUNT="/mnt/MDS_VAULT"
VAULT_UUID="a358df98-79a1-42fb-af5c-d38f43c60305"
DATA_UUID="5ae96703-ba78-4401-9c92-9d06dd52589d"

# ==============================================================================
# 2. GUARDIAN LAYER
# ==============================================================================

echo "--- Running safety checks ---"

if [[ ! -d "$SOURCE" ]]; then
    echo "⚠ CRITICAL ERROR: Source directory does not exist:"
    echo "  $SOURCE"
    exit 1
fi

if [[ "$(findmnt -n -o UUID --target "$SOURCE" 2>/dev/null || true)" != "$DATA_UUID" ]]; then
    echo "⚠ CRITICAL ERROR: Source is not on the expected data drive:"
    echo "  $SOURCE"
    echo "Expected filesystem UUID: $DATA_UUID"
    exit 1
fi

if [[ -z "$(find "$SOURCE" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "⚠ CRITICAL ERROR: Source directory is empty:"
    echo "  $SOURCE"
    echo "Aborting to prevent accidental deletion of remote data."
    exit 1
fi

if [[ ! -f "$EXCLUDES" ]]; then
    echo "⚠ CRITICAL ERROR: Rsync exclusions file does not exist:"
    echo "  $EXCLUDES"
    exit 1
fi

if [[ ! -f "$SSH_KEY" ]]; then
    echo "⚠ CRITICAL ERROR: SSH private key does not exist:"
    echo "  $SSH_KEY"
    exit 1
fi

# Protect against accidental University/University nesting.
if [[ -d "${SOURCE}/University" ]]; then
    echo "⚠ CRITICAL ERROR: Unexpected nested University directory exists:"
    echo "  ${SOURCE}/University"
    exit 1
fi

REMOTE_AVAILABLE=false

# REMOTE_PATH_SHELL was escaped with printf %q above.
# shellcheck disable=SC2029
if ssh "${SSH_ARGS[@]}" "$SSH_DESTINATION" \
    "$REMOTE_DIRECTORY_TEST" 2>/dev/null; then

    REMOTE_AVAILABLE=true
    echo "✓ Fedora server is available."
else
    echo "⚠ WARNING: Fedora server is unavailable."
    echo "Remote synchronisation will be skipped."
fi

if [[ "$REMOTE_AVAILABLE" == true ]]; then
    # shellcheck disable=SC2029
    if ssh "${SSH_ARGS[@]}" "$SSH_DESTINATION" \
        "$REMOTE_NESTING_TEST"; then

        echo "⚠ CRITICAL ERROR: Unexpected nested University directory exists remotely:"
        echo "  ${SSH_DESTINATION}:${REMOTE_PATH}/University"
        exit 1
    else
        SSH_TEST_STATUS=$?
        if (( SSH_TEST_STATUS != 1 )); then
            echo "⚠ CRITICAL ERROR: Unable to validate the remote directory layout."
            exit 1
        fi
    fi
fi

# ==============================================================================
# 3. DESKTOP ↔ FEDORA SERVER
# ==============================================================================

if [[ "$REMOTE_AVAILABLE" == true ]]; then

    echo
    echo "--- Step 1a: Pulling newer files from Fedora server ---"

    if ! rsync -avu \
        "${RSYNC_DRY_ARGS[@]}" \
        -e "$SSH_TRANSPORT" \
        --exclude-from="$EXCLUDES" \
        "$REMOTE_TARGET/" \
        "$SOURCE/"; then

        echo "⚠ CRITICAL ERROR: Server pull failed."
        exit 1
    fi

    echo
    echo "--- Step 1b: Pushing desktop files to Fedora server ---"

    if ! rsync -av \
        "${RSYNC_DRY_ARGS[@]}" \
        -e "$SSH_TRANSPORT" \
        --exclude-from="$EXCLUDES" \
        "$SOURCE/" \
        "$REMOTE_TARGET/"; then

        echo "⚠ CRITICAL ERROR: Server push failed."
        echo "Remote cleanup has been skipped."
        exit 1
    fi

    echo
    echo "--- Step 1c: Reconciling deleted files on Fedora server ---"

    if ! rsync -av \
        "${RSYNC_DRY_ARGS[@]}" \
        --delete \
        --existing \
        -e "$SSH_TRANSPORT" \
        --exclude-from="$EXCLUDES" \
        "$SOURCE/" \
        "$REMOTE_TARGET/"; then

        echo "⚠ CRITICAL ERROR: Remote cleanup failed."
        exit 1
    fi
fi

# ==============================================================================
# 4. USB VAULT LIVE-WORK COPY
# ==============================================================================

VAULT_IDENTITY="$(findmnt -n -o TARGET,FSTYPE,LABEL,UUID --target "$LOCAL_VAULT" 2>/dev/null || true)"

if [[ -d "$LOCAL_VAULT" &&
      "$VAULT_IDENTITY" == "$VAULT_MOUNT btrfs MDS_VAULT $VAULT_UUID" &&
      ( -w "$LOCAL_VAULT" || "$DRY_RUN" == true ) ]]; then

    if [[ "$DRY_RUN" != true ]]; then
        mkdir -p "$USB_LIVE_WORK"
    fi

    echo
    echo "--- Step 2a: Pushing live work to USB vault ---"

    if rsync -av \
        "${RSYNC_DRY_ARGS[@]}" \
        --exclude-from="$EXCLUDES" \
        "$SOURCE/" \
        "$USB_LIVE_WORK/"; then

        echo
        echo "--- Step 2b: Reconciling deleted files on USB vault ---"

        if ! rsync -av \
            "${RSYNC_DRY_ARGS[@]}" \
            --delete \
            --existing \
            --exclude-from="$EXCLUDES" \
            "$SOURCE/" \
            "$USB_LIVE_WORK/"; then

            echo "⚠ WARNING: USB vault cleanup failed."
        fi
    else
        echo "⚠ WARNING: USB vault push failed."
        echo "USB cleanup was skipped."
    fi

else
    echo
    echo "⏸ USB vault unavailable, read-only, or not the expected mounted filesystem:"
    echo "  $LOCAL_VAULT"
fi

# ==============================================================================
# 5. STATUS
# ==============================================================================

if [[ "$DRY_RUN" != true ]]; then
    mkdir -p "$(dirname "$STATUS_FILE")"

    {
        echo "Last MDS Sync: $(date --iso-8601=seconds)"
        echo "Source: $SOURCE"
        echo "Remote: ${SSH_DESTINATION}:${REMOTE_PATH}"
    } > "$STATUS_FILE"
fi

echo
echo "============================================================"
echo "✓ MDS workstation synchronisation completed"
echo "  Source: $SOURCE"
echo "  Remote: ${SSH_DESTINATION}:${REMOTE_PATH}"
echo "============================================================"
