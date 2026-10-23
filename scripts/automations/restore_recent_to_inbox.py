#!/usr/bin/env python3
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
BASE_DIR = Path(__file__).parent
TOKEN_PATH = BASE_DIR / "token.json"
BATCH_SIZE = 1000

# Keep only actionable categories
TARGET_LABELS = [
    "Careers/Applications",
    "Family",
    "Support & Health",
]

LOOKBACK_DAYS = 30

# Exclude invoices, statements, welcome letters, and OTPs from ever being restored
EXCLUDE_TERMS = (
    '-subject:"invoice" '
    '-subject:"statement" '
    '-subject:"welcome to" '
    '-subject:"payment confirmation" '
    '-subject:"confirmation of your" '
    '-subject:"security code" '
    '-subject:"verify" '
    '-subject:"login"'
)


def authenticate_gmail():
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"Missing {TOKEN_PATH}. Run process_gmail.py first to authenticate.")
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    return build("gmail", "v1", credentials=creds)


def fetch_matching_ids(service, query: str):
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


def batch_add_to_inbox(service, msg_ids: list):
    for i in range(0, len(msg_ids), BATCH_SIZE):
        chunk = msg_ids[i:i + BATCH_SIZE]
        service.users().messages().batchModify(
            userId="me",
            body={"ids": chunk, "addLabelIds": ["INBOX"]}
        ).execute()


def main():
    service = authenticate_gmail()
    print(f"Scanning target labels for actionable emails from the last {LOOKBACK_DAYS} days...\n")

    total_restored = 0
    for label in TARGET_LABELS:
        query = f'label:"{label}" -in:inbox newer_than:{LOOKBACK_DAYS}d {EXCLUDE_TERMS}'
        msg_ids = fetch_matching_ids(service, query)

        if not msg_ids:
            print(f"  [{label}]: No actionable archived emails to restore.")
            continue

        print(f"  [{label}]: Restoring {len(msg_ids)} email(s) to INBOX...")
        batch_add_to_inbox(service, msg_ids)
        total_restored += len(msg_ids)

    print(f"\n✓ Completed. Restored {total_restored} actionable email(s) to INBOX.")


if __name__ == "__main__":
    main()
