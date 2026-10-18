#!/usr/bin/env python3
import base64
import json
import os
import re
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "rules.json"
BATCH_SIZE = 1000


def load_config():
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Missing config file: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    config["output_dir"] = Path(os.path.expanduser(config.get("output_dir", "~/Documents/Invoices")))
    return config


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")


def authenticate_gmail():
    token_path = BASE_DIR / "token.json"
    credentials_path = BASE_DIR / "credentials.json"

    if not credentials_path.exists():
        raise FileNotFoundError(f"Missing {credentials_path}")

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_label_cache(service):
    results = service.users().labels().list(userId="me").execute()
    return {l["name"].lower(): l["id"] for l in results.get("labels", [])}


def get_or_create_label(service, label_name: str, cache: dict) -> str:
    key = label_name.lower()
    if key in cache:
        return cache[key]

    created = service.users().labels().create(
        userId="me",
        body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    ).execute()
    cache[key] = created["id"]
    return created["id"]


def fetch_all_matching_ids(service, query: str):
    ids = []
    next_page_token = None
    while True:
        res = service.users().messages().list(
            userId="me", q=query, maxResults=500, pageToken=next_page_token
        ).execute()
        
        batch = res.get("messages", [])
        ids.extend([m["id"] for m in batch])
        
        next_page_token = res.get("nextPageToken")
        if not next_page_token:
            break
    return ids


def batch_modify_messages(service, msg_ids: list, add_labels=None, remove_labels=None):
    if not msg_ids:
        return
    add_labels = add_labels or []
    remove_labels = remove_labels or []

    for i in range(0, len(msg_ids), BATCH_SIZE):
        chunk = msg_ids[i:i + BATCH_SIZE]
        service.users().messages().batchModify(
            userId="me",
            body={
                "ids": chunk,
                "addLabelIds": add_labels,
                "removeLabelIds": remove_labels
            }
        ).execute()
        print(f"    Processed batch {i + len(chunk)}/{len(msg_ids)}...")


def clean_folders_by_policy(service, config):
    """Purges expired emails across folders defined in folder_cleanup_policies."""
    policies = config.get("folder_cleanup_policies", [])
    print("\n[1/3] Running folder retention policies...")

    if not policies:
        print("  ✓ No retention policies configured.")
        return

    for policy in policies:
        label = policy.get("label")
        days = policy.get("retention_days", 30)
        query = f'label:"{label}" older_than:{days}d'

        print(f"  Checking '{label}' older than {days} days...")
        ids = fetch_all_matching_ids(service, query)

        if not ids:
            print(f"    ✓ Up to date (0 expired).")
            continue

        print(f"    Moving {len(ids)} expired email(s) to Trash...")
        batch_modify_messages(service, ids, add_labels=["TRASH"])

    print("  ✓ Folder cleanups complete.")


def organize_inbox(service, config, label_cache):
    print("\n[2/3] Organizing inbox messages...")
    rules = list(config.get("organization_rules", []))
    
    promo_senders = config.get("promo_senders", [])
    if promo_senders:
        sender_query = " OR ".join([f"from:{s}" for s in promo_senders])
        rules.append({
            "label": "Promotions",
            "query": f"in:inbox ({sender_query} OR category:promotions)",
            "archive": True
        })

    for rule in rules:
        label_name = rule["label"]
        query = rule["query"]
        should_archive = rule.get("archive", True)

        label_id = get_or_create_label(service, label_name, label_cache)

        ids = fetch_all_matching_ids(service, query)
        if not ids:
            continue

        print(f"  Routing {len(ids)} emails -> '{label_name}' (Archive: {should_archive})")
        remove_labels = ["INBOX"] if should_archive else []
        batch_modify_messages(service, ids, add_labels=[label_id], remove_labels=remove_labels)

    print("  ✓ Organization complete.")


def download_invoices(service, config):
    print("\n[3/3] Checking for invoice attachments...")
    query = config.get("invoice_download_query")
    output_dir = config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    res = service.users().messages().list(userId="me", q=query).execute()
    messages = res.get("messages", [])

    if not messages:
        print("  ✓ No new invoice emails.")
        return

    saved_count = 0
    for msg_meta in messages:
        msg_id = msg_meta["id"]
        try:
            msg = service.users().messages().get(userId="me", id=msg_id).execute()
            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            raw_date = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
            try:
                date_prefix = parsedate_to_datetime(raw_date).strftime("%Y-%m-%d")
            except Exception:
                date_prefix = datetime.now().strftime("%Y-%m-%d")

            raw_from = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
            name, addr = parseaddr(raw_from)
            sender_id = sanitize_filename(name if name else addr.split("@")[0])

            parts = payload.get("parts", [])
            while parts:
                part = parts.pop(0)
                filename = part.get("filename", "")
                attachment_id = part.get("body", {}).get("attachmentId")
                if "parts" in part:
                    parts.extend(part["parts"])

                if filename and attachment_id:
                    ext = Path(filename).suffix.lower()
                    if ext not in [".pdf", ".zip", ".csv", ".xlsx"]:
                        continue

                    safe_orig = sanitize_filename(filename)
                    out_path = output_dir / f"{date_prefix}_{sender_id}_{safe_orig}"
                    if not out_path.exists():
                        att = service.users().messages().attachments().get(
                            userId="me", messageId=msg_id, id=attachment_id
                        ).execute()
                        data = base64.urlsafe_b64decode(att["data"].encode("UTF-8"))
                        with open(out_path, "wb") as f:
                            f.write(data)
                        print(f"  Saved: {out_path.name}")
                        saved_count += 1
        except Exception as err:
            print(f"  Error processing invoice {msg_id}: {err}")

    print(f"  ✓ Processed invoices ({saved_count} new files saved).")


def main():
    config = load_config()
    service = authenticate_gmail()
    cache = get_label_cache(service)

    # 1. Purge expired emails across defined folders
    clean_folders_by_policy(service, config)

    # 2. Sort current inbox into sections
    organize_inbox(service, config, cache)

    # 3. Pull bill attachments
    download_invoices(service, config)

    print("\nRoutine finished.")


if __name__ == "__main__":
    main()