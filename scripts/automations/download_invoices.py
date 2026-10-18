#!/usr/bin/env python3
import base64
import os
import re
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Read-only scope is sufficient and safest for reading emails/attachments
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Storage directory for invoices
OUTPUT_DIR = Path.home() / "Documents" / "Invoices"

# Search query matching typical bills and invoices with attachments
SEARCH_QUERY = 'has:attachment (filename:pdf OR filename:zip) (subject:invoice OR subject:bill OR subject:statement OR "tax invoice")'


def sanitize_filename(name: str) -> str:
    """Removes invalid characters from file paths."""
    return re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")


def authenticate_gmail():
    """Handles OAuth token flow and returns the Gmail service client."""
    creds = None
    token_path = Path("token.json")
    credentials_path = Path("credentials.json")

    if not credentials_path.exists():
        raise FileNotFoundError(
            "Missing 'credentials.json'. Download it from Google Cloud Console (OAuth Client ID - Desktop App)."
        )

    # Re-use cached token if available
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # Refresh or generate new token via browser flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_header_value(headers: list, target_name: str) -> str:
    """Extracts a specific header value (case-insensitive) from a message payload."""
    for header in headers:
        if header.get("name", "").lower() == target_name.lower():
            return header.get("value", "")
    return ""


def process_attachments(service, message_id: str, email_date_str: str, sender: str):
    """Parses message parts, downloads attachments, and saves them."""
    msg = service.users().messages().get(userId="me", id=message_id).execute()
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])

    # Format date as YYYY-MM-DD
    raw_date = get_header_value(headers, "Date")
    if raw_date:
        try:
            parsed_date = parsedate_to_datetime(raw_date)
            date_prefix = parsed_date.strftime("%Y-%m-%d")
        except Exception:
            date_prefix = datetime.now().strftime("%Y-%m-%d")
    else:
        date_prefix = datetime.now().strftime("%Y-%m-%d")

    # Clean sender name
    raw_from = get_header_value(headers, "From")
    name, addr = parseaddr(raw_from)
    company_identifier = sanitize_filename(name if name else addr.split("@")[0])

    # Breadth-first traversal of MIME parts
    parts = payload.get("parts", [])
    while parts:
        part = parts.pop(0)
        filename = part.get("filename", "")
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")

        # Nested MIME parts (e.g., multipart/mixed)
        if "parts" in part:
            parts.extend(part["parts"])

        # Process valid file attachments
        if filename and attachment_id:
            safe_orig_name = sanitize_filename(filename)
            new_filename = f"{date_prefix}_{company_identifier}_{safe_orig_name}"
            target_path = OUTPUT_DIR / new_filename

            if target_path.exists():
                print(f"Skipping (already exists): {new_filename}")
                continue

            # Fetch the actual attachment data
            attachment = (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )

            file_data = base64.urlsafe_b64decode(attachment["data"].encode("UTF-8"))

            with open(target_path, "wb") as f:
                f.write(file_data)

            print(f"Saved: {new_filename}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    service = authenticate_gmail()

    print(f"Querying Gmail: {SEARCH_QUERY}")
    response = service.users().messages().list(userId="me", q=SEARCH_QUERY).execute()
    messages = response.get("messages", [])

    if not messages:
        print("No matching invoice emails found.")
        return

    print(f"Found {len(messages)} matching email(s). Processing attachments...")
    for msg_meta in messages:
        try:
            process_attachments(service, msg_meta["id"], "", "")
        except Exception as err:
            print(f"Failed to process message ID {msg_meta['id']}: {err}")

    print("Complete.")


if __name__ == "__main__":
    main()