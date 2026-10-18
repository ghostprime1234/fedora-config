#!/usr/bin/env python3
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
BASE_DIR = Path(__file__).parent
TOKEN_PATH = BASE_DIR / "token.json"

if not TOKEN_PATH.exists():
    print("token.json not found. Run process_gmail.py first to authenticate.")
    exit(1)

creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
service = build("gmail", "v1", credentials=creds)

print("Scanning inbox messages...")

# 1. Fetch all message IDs currently sitting in the inbox
message_stubs = []
next_page_token = None

while True:
    res = service.users().messages().list(
        userId="me",
        q="in:inbox",
        maxResults=500,
        pageToken=next_page_token
    ).execute()

    message_stubs.extend(res.get("messages", []))
    next_page_token = res.get("nextPageToken")
    if not next_page_token:
        break

if not message_stubs:
    print("Inbox is empty!")
    exit(0)

print(f"Found {len(message_stubs)} email(s). Fetching metadata via HTTP batches...")

# 2. Batch retrieve metadata in groups of 100
fetched_data = []

def make_callback(index_num):
    def callback(request_id, response, exception):
        if exception is not None:
            return

        headers = {h["name"].lower(): h["value"] for h in response.get("payload", {}).get("headers", [])}

        # Format date
        raw_date = headers.get("date", "")
        try:
            date_str = parsedate_to_datetime(raw_date).strftime("%Y-%m-%d")
        except Exception:
            date_str = "Unknown"

        # Format sender
        from_name, from_addr = parseaddr(headers.get("from", ""))
        sender = from_name if from_name else from_addr
        sender = (sender[:29] + "...") if len(sender) > 32 else sender

        # Format subject
        subject = headers.get("subject", "(No Subject)")
        subject = (subject[:45] + "...") if len(subject) > 48 else subject

        fetched_data.append((index_num, date_str, sender, subject))
    return callback

# Gmail allows up to 100 calls bundled inside one HTTP batch
BATCH_CHUNK_SIZE = 100

for chunk_start in range(0, len(message_stubs), BATCH_CHUNK_SIZE):
    chunk = message_stubs[chunk_start:chunk_start + BATCH_CHUNK_SIZE]
    batch = service.new_batch_http_request()

    for idx, item in enumerate(chunk, start=chunk_start + 1):
        req = service.users().messages().get(
            userId="me",
            id=item["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        )
        batch.add(req, callback=make_callback(idx))

    batch.execute()

# Sort results by the original list order
fetched_data.sort(key=lambda x: x[0])

# 3. Print the formatted table
print(f"\n{'#':<4} | {'DATE':<12} | {'FROM':<32} | {'SUBJECT'}")
print("-" * 90)

for index_num, date_str, sender, subject in fetched_data:
    print(f"{index_num:<4} | {date_str:<12} | {sender:<32} | {subject}")