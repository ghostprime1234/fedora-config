#!/usr/bin/env python3
import json, struct, sys
from pathlib import Path
SYNC_DIR = Path.home() / ".local/share/unisq-mail-sync"
REQUEST = SYNC_DIR / "folder-request.json"
STATUS = SYNC_DIR / "folder-status.json"

def recv():
    raw = sys.stdin.buffer.read(4)
    if not raw: return None
    n = struct.unpack("@I", raw)[0]
    return json.loads(sys.stdin.buffer.read(n).decode())

def send(obj):
    data = json.dumps(obj).encode()
    sys.stdout.buffer.write(struct.pack("@I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()

msg = recv()
if msg:
    if msg.get("command") == "get_request":
        send(json.loads(REQUEST.read_text()) if REQUEST.exists()
             else {"error": f"Missing request: {REQUEST}"})
    elif msg.get("command") == "write_status":
        SYNC_DIR.mkdir(parents=True, exist_ok=True)
        STATUS.write_text(json.dumps(msg.get("status", {}), indent=2) + "\n")
        send({"ok": True})
    else:
        send({"error": "Unknown command"})
