#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HOME/.local/lib/unisq-mail-sync"
HOST="$APP/unisq_mail_sync_host.py"
NM="$HOME/.var/app/eu.betterbird.Betterbird/.mozilla/native-messaging-hosts"
mkdir -p "$APP" "$NM"
install -m 0755 "$HERE/native-host/unisq_mail_sync_host.py" "$HOST"
cat > "$NM/unisq_mail_sync.json" <<EOF
{
  "name": "unisq_mail_sync",
  "description": "UniSQ Betterbird folder sync bridge",
  "path": "$HOST",
  "type": "stdio",
  "allowed_extensions": ["unisq-folder-sync@local"]
}
EOF
echo "Native host installed."
echo "Load this temporary add-on in Betterbird:"
echo "  $HERE/extension/manifest.json"
