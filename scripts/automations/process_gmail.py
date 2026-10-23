#!/usr/bin/env python3
import base64
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
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

VALID_CATEGORIES = [
    "Promotions",
    "Tech & Newsletters",
    "Careers/Alerts",
    "Careers/Applications",
    "Networking & Invites",
    "Security & System Alerts",
    "Support & Health",
    "Orders & Receipts",
    "Support Tickets",
    "TRASH",
    "INBOX_KEEP",
]

LOCAL_OLLAMA_URL = "http://localhost:11434/api/generate"
LOCAL_MODEL = "llama3.2:3b"
FALLBACK_GEMINI_MODEL = "gemini-3.8-flash"


def has_nvidia_gpu() -> bool:
    """Checks if an NVIDIA GPU is present and accessible via nvidia-smi."""
    if not shutil.which("nvidia-smi"):
        return False
    try:
        res = subprocess.run(
            ["nvidia-smi", "-L"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return res.returncode == 0 and bool(res.stdout.strip())
    except Exception:
        return False


def is_ollama_running() -> bool:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_ollama_ready() -> bool:
    """Starts Ollama daemon and pulls the model if missing."""
    if not shutil.which("ollama"):
        return False

    # 1. Start daemon if not running
    if not is_ollama_running():
        print("  Starting local Ollama server...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(12):
            time.sleep(0.5)
            if is_ollama_running():
                break

    if not is_ollama_running():
        print("  Failed to connect to local Ollama.")
        return False

    # 2. Verify model exists or pull it
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            installed_names = [m.get("name", "") for m in data.get("models", [])]
            target_base = LOCAL_MODEL.split(":")[0]

            has_model = any(
                LOCAL_MODEL == name or target_base == name.split(":")[0]
                for name in installed_names
            )
            if not has_model:
                print(f"  Model '{LOCAL_MODEL}' not found. Downloading via Ollama...")
                subprocess.run(["ollama", "pull", LOCAL_MODEL], check=True)
                print(f"  ✓ Model '{LOCAL_MODEL}' downloaded successfully.")
        return True
    except Exception as e:
        print(f"  Ollama model verification failed: {e}")
        return False


def classify_with_ollama(prompt: str) -> dict:
    payload = {
        "model": LOCAL_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        LOCAL_OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    # Increased to 60s to accommodate cold-start VRAM model loading
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return json.loads(data.get("response", "{}"))


def classify_with_gemini_api(prompt: str, api_key: str) -> dict:
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=FALLBACK_GEMINI_MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


def classify_inbox_items(emails_metadata: list) -> dict:
    prompt = build_triage_prompt(emails_metadata)

    # 1. Desktop: NVIDIA discrete GPU present -> use local Ollama
    if has_nvidia_gpu():
        print("  Dedicated GPU detected. Using local Ollama...")
        if ensure_ollama_ready():
            try:
                decisions = classify_with_ollama(prompt)
                if decisions:
                    print("  ✓ Processed via local Ollama.")
                    return decisions
            except Exception as e:
                print(f"  Local Ollama error: {e}")

    # 2. Laptop / Fallback: Intel Arc / no NVIDIA GPU -> straight to Cloud API
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            print("  Using Gemini API (Cloud triage)...")
            decisions = classify_with_gemini_api(prompt, api_key)
            print("  ✓ Processed via Gemini Flash API.")
            return decisions
        except Exception as e:
            print(f"  Gemini API error: {e}")

    print("  ✗ No LLM available. Leaving inbox mail untouched.")
    return {}

def load_env_file():
    """Loads environment variables from ~/.config/automation/.env or local .env."""
    candidate_paths = [
        Path.home() / ".config" / "automation" / ".env",
        BASE_DIR / ".env",
    ]
    for env_path in candidate_paths:
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        val = val.strip().strip("'\"")
                        os.environ.setdefault(key.strip(), val)
            break


def load_config():
    load_env_file()
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
    if label_name.upper() == "TRASH":
        return "TRASH"
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


def clean_folders_by_policy(service, config):
    policies = config.get("folder_cleanup_policies", [])
    print("\n[1/4] Running folder retention policies...")
    if not policies:
        print("  ✓ No retention policies configured.")
        return

    for policy in policies:
        label = policy.get("label")
        days = policy.get("retention_days", 30)
        query = f'label:"{label}" older_than:{days}d'
        ids = fetch_all_matching_ids(service, query)
        if ids:
            print(f"  Purging {len(ids)} expired email(s) from '{label}'...")
            batch_modify_messages(service, ids, add_labels=["TRASH"])
    print("  ✓ Retention policies complete.")


def organize_inbox_rules(service, config, label_cache):
    """Executes rule matching with immediate or dynamic age thresholds."""
    print("\n[2/4] Organizing inbox with age-aware rules...")
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
        base_query = rule["query"]
        archive_days = rule.get("archive_after_days")
        immediate_archive = rule.get("archive", False)

        label_id = get_or_create_label(service, label_name, label_cache)

        if label_name == "TRASH":
            trash_ids = fetch_all_matching_ids(service, base_query)
            if trash_ids:
                print(f"  Sending {len(trash_ids)} transient emails to TRASH...")
                batch_modify_messages(service, trash_ids, add_labels=["TRASH"])
        elif immediate_archive:
            ids_to_archive = fetch_all_matching_ids(service, base_query)
            if ids_to_archive:
                print(f"  Routing {len(ids_to_archive)} email(s) -> '{label_name}' (Archived)")
                batch_modify_messages(service, ids_to_archive, add_labels=[label_id], remove_labels=["INBOX"])
        elif archive_days:
            # 1. Label all matches so they are categorized
            ids_to_label = fetch_all_matching_ids(service, f"{base_query} -label:\"{label_name}\"")
            if ids_to_label:
                batch_modify_messages(service, ids_to_label, add_labels=[label_id])
                print(f"  Applied label '{label_name}' to {len(ids_to_label)} email(s).")

            # 2. Archive only those exceeding retention threshold
            age_query = f"{base_query} in:inbox older_than:{archive_days}d"
            ids_to_archive = fetch_all_matching_ids(service, age_query)
            if ids_to_archive:
                print(f"  Archiving {len(ids_to_archive)} '{label_name}' email(s) older than {archive_days} days...")
                batch_modify_messages(service, ids_to_archive, remove_labels=["INBOX"])

    print("  ✓ Rule-based organization complete.")


def is_ollama_running() -> bool:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_ollama_ready() -> bool:
    """Starts Ollama daemon and pulls the model if missing."""
    if not shutil.which("ollama"):
        return False  # Ollama not installed (e.g., laptop environment)

    # 1. Start daemon if not running
    if not is_ollama_running():
        print("  Starting local Ollama server...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(12):
            time.sleep(0.5)
            if is_ollama_running():
                break

    if not is_ollama_running():
        print("  Failed to connect to local Ollama.")
        return False

    # 2. Verify model exists or pull it
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            installed_names = [m.get("name", "") for m in data.get("models", [])]
            target_base = LOCAL_MODEL.split(":")[0]

            has_model = any(
                LOCAL_MODEL == name or target_base == name.split(":")[0]
                for name in installed_names
            )
            if not has_model:
                print(f"  Model '{LOCAL_MODEL}' not found. Downloading via Ollama...")
                subprocess.run(["ollama", "pull", LOCAL_MODEL], check=True)
                print(f"  ✓ Model '{LOCAL_MODEL}' downloaded successfully.")
        return True
    except Exception as e:
        print(f"  Ollama model verification failed: {e}")
        return False


def build_triage_prompt(emails_metadata: list) -> str:
    return f"""
Analyze the email metadata below and categorize each into EXACTLY one of these labels:
{json.dumps(VALID_CATEGORIES)}

Categories Guide:
- 'TRASH': Expired security/verification codes, one-time passwords, password reset links, expired webinar replays, transient app error notices.
- 'Promotions': Marketing deals, discounts, consumer sales, newsletters you did not explicitly work with.
- 'Tech & Newsletters': Engineering blogs, programming digests, GitHub repository updates.
- 'Careers/Alerts': Job notifications, LinkedIn alerts, recruiter inquiries.
- 'Orders & Receipts': Order confirmations, receipts, delivery tracking, parcel updates.
- 'Security & System Alerts': Cloud platform notifications, account notices, subscription changes.
- 'Support & Health': Medical, health insurance, therapy, dental, NDIS support.
- 'INBOX_KEEP': Direct personal communications, active threads Michael must read.

Emails to classify:
{json.dumps(emails_metadata)}

Respond ONLY with a JSON object mapping each message ID to its assigned label string.
Example: {{"msg_id_1": "Promotions", "msg_id_2": "TRASH"}}
"""


def classify_with_ollama(prompt: str) -> dict:
    payload = {
        "model": LOCAL_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        LOCAL_OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return json.loads(data.get("response", "{}"))


def classify_with_gemini_api(prompt: str, api_key: str) -> dict:
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


def classify_inbox_items(emails_metadata: list) -> dict:
    prompt = build_triage_prompt(emails_metadata)

    # 1. Try local Ollama first (auto-start daemon & pull model if installed)
    if ensure_ollama_ready():
        try:
            decisions = classify_with_ollama(prompt)
            if decisions:
                print("  ✓ Processed via local Ollama.")
                return decisions
        except Exception as e:
            print(f"  Local Ollama execution error: {e}")

    # 2. Fall back to Gemini API
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            decisions = classify_with_gemini_api(prompt, api_key)
            print("  ✓ Processed via Gemini 2.5 Flash API.")
            return decisions
        except Exception as e:
            print(f"  Gemini API error: {e}")

    print("  ✗ No LLM available (Ollama offline & GEMINI_API_KEY unset). Leaving remaining mail untouched.")
    return {}


def organize_remaining_inbox_with_llm(service, config, label_cache):
    print("\n[3/4] Running dynamic triage on remaining inbox messages...")
    res = service.users().messages().list(userId="me", q="in:inbox", maxResults=50).execute()
    messages = res.get("messages", [])
    if not messages:
        print("  ✓ Inbox is already clean.")
        return

    items = []
    for m in messages:
        detail = service.users().messages().get(
            userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject"]
        ).execute()
        headers = detail.get("payload", {}).get("headers", [])
        sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown")
        subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "(No Subject)")
        items.append({"id": m["id"], "from": sender, "subject": subject})

    decisions = classify_inbox_items(items)
    for msg_id, label in decisions.items():
        if label not in VALID_CATEGORIES or label == "INBOX_KEEP":
            continue

        label_id = get_or_create_label(service, label, label_cache)
        if label == "TRASH":
            batch_modify_messages(service, [msg_id], add_labels=["TRASH"])
            print(f"  [Trash]: {msg_id}")
        else:
            batch_modify_messages(service, [msg_id], add_labels=[label_id], remove_labels=["INBOX"])
            print(f"  [{label} -> Archived]: {msg_id}")

    print("  ✓ Dynamic classification complete.")


def download_invoices(service, config):
    print("\n[4/4] Checking for invoice attachments...")
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

    clean_folders_by_policy(service, config)
    organize_inbox_rules(service, config, cache)
    organize_remaining_inbox_with_llm(service, config, cache)
    download_invoices(service, config)

    print("\nRoutine finished.")


if __name__ == "__main__":
    main()
