#!/usr/bin/env python3

"""
Synchronise the UniSQ MADS study plan from Marks Manager with Betterbird.

Reads the study plan through SSH/Podman, writes the desired folder hierarchy
for a Betterbird helper extension, and updates Betterbird message filters.
The helper creates missing server-side folders using Betterbird's existing
authenticated UniSQ account; no mail password is stored here.

Run Betterbird CLOSED with --apply-filters because msgFilterRules.dat is
modified directly.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

COURSE_CODE = "MADS"

# PostgreSQL running on the mini PC.
#
# Change DB_HOST if "ubuntu-server" is not resolvable from the Fedora desktop.
# A Tailscale hostname is also suitable.
SSH_HOST = os.environ.get(
    "MARKS_SSH_HOST",
    "michael-server-fedora",
)

POSTGRES_CONTAINER = os.environ.get(
    "MARKS_DB_CONTAINER",
    "postgres_db",
)

DB_NAME = os.environ.get(
    "MARKS_DB_NAME",
    "marks-manager-db",
)

DB_USER = os.environ.get(
    "MARKS_DB_USER",
    "Michael",
)

# UniSQ Google Workspace account.
IMAP_USER = os.environ.get(
    "UNISQ_EMAIL",
    "u1185376@umail.usq.edu.au",
)

# Betterbird Flatpak profile.
BETTERBIRD_PROFILE = (
    Path.home()
    / ".var/app/eu.betterbird.Betterbird"
    / ".thunderbird/qkuvod5g.default-default"
)

UNISQ_IMAP_DIR = BETTERBIRD_PROFILE / "ImapMail/imap.gmail-1.com"
FILTER_FILE = UNISQ_IMAP_DIR / "msgFilterRules.dat"

SYNC_DIR = Path.home() / ".local/share/unisq-mail-sync"
FOLDER_REQUEST_FILE = SYNC_DIR / "folder-request.json"
FOLDER_STATUS_FILE = SYNC_DIR / "folder-status.json"

ROOT_FOLDER = "Subjects"

# Marker used to identify filters owned by this script.
FILTER_PREFIX = "[MADS AUTO]"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Subject:
    code: str
    name: str
    trimester: str
    year: int

    @property
    def folder(self) -> str:
        return (
            f"{ROOT_FOLDER}/"
            f"{self.year}/"
            f"{self.trimester}/"
            f"{self.code}"
        )

    @property
    def filter_name(self) -> str:
        return f"{FILTER_PREFIX} {self.code}"


# ---------------------------------------------------------------------------
# PostgreSQL — query Marks Manager through SSH
# ---------------------------------------------------------------------------

def load_subjects() -> list[Subject]:
    """
    Read the MADS study plan from PostgreSQL on the mini PC via SSH.

    Fedora
      -> SSH michael-server-fedora
      -> podman exec postgres_db
      -> PostgreSQL
    """

    print(
        f"Reading {COURSE_CODE} study plan from "
        f"{SSH_HOST}/{POSTGRES_CONTAINER}..."
    )

    sql = f"""
COPY (
    SELECT
        subj.subject_code,
        subj.subject_name,
        sem.name,
        sem.year
    FROM subjects subj
    JOIN semesters sem
        ON sem.id = subj.semester_id
    JOIN courses
        ON sem.course_id = courses.id
    WHERE courses.code = '{COURSE_CODE}'
    ORDER BY
        sem.year,
        sem.name,
        subj.subject_code
) TO STDOUT WITH CSV;
"""

    remote_command = [
        "podman",
        "exec",
        "-i",
        POSTGRES_CONTAINER,
        "psql",
        "-U",
        DB_USER,
        "-d",
        DB_NAME,
        "-X",
        "-q",
        "-c",
        sql,
    ]

    # SSH ultimately passes the remote command through a shell.
    # shlex.join() preserves the SQL as one argument to psql -c.
    cmd = [
        "ssh",
        "-T",
        SSH_HOST,
        shlex.join(remote_command),
    ]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    except subprocess.TimeoutExpired:
        print(
            f"ERROR: Timed out connecting to {SSH_HOST}."
        )
        sys.exit(1)

    except FileNotFoundError:
        print("ERROR: ssh is not installed.")
        sys.exit(1)

    except subprocess.CalledProcessError as exc:
        print("ERROR: Could not query Marks Manager.")

        if exc.stderr:
            print(exc.stderr.strip())

        sys.exit(1)

    import csv
    import io

    reader = csv.reader(io.StringIO(result.stdout))

    subjects: list[Subject] = []

    for row in reader:
        if len(row) != 4:
            continue

        try:
            subjects.append(
                Subject(
                    code=row[0].strip(),
                    name=row[1].strip(),
                    trimester=row[2].strip(),
                    year=int(row[3]),
                )
            )

        except (ValueError, IndexError) as exc:
            print(
                f"WARNING: Ignoring malformed row "
                f"{row!r}: {exc}"
            )

    if not subjects:
        print(
            f"ERROR: No {COURSE_CODE} subjects "
            "were returned."
        )
        sys.exit(1)

    return subjects


# ---------------------------------------------------------------------------
# Folder hierarchy
# ---------------------------------------------------------------------------

def desired_folders(subjects: Iterable[Subject]) -> list[str]:
    """
    Return every folder needed, including parent folders.
    """

    folders = {ROOT_FOLDER}

    for subject in subjects:
        folders.add(f"{ROOT_FOLDER}/{subject.year}")
        folders.add(
            f"{ROOT_FOLDER}/{subject.year}/{subject.trimester}"
        )
        folders.add(subject.folder)

    return sorted(
        folders,
        key=lambda path: (path.count("/"), path),
    )

# ---------------------------------------------------------------------------
# Betterbird folder request
# ---------------------------------------------------------------------------

def write_folder_request(folders: Iterable[str]) -> Path:
    """Write the desired hierarchy for the Betterbird helper extension."""
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "account_email": IMAP_USER,
        "folders": list(folders),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    FOLDER_REQUEST_FILE.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return FOLDER_REQUEST_FILE


# ---------------------------------------------------------------------------
# Betterbird filters
# ---------------------------------------------------------------------------

def escape_filter_value(value: str) -> str:
    """Escape values used in Betterbird filter conditions."""

    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("@", "\\@")
    )


def escape_uri_component(value: str) -> str:
    """Format a Betterbird IMAP folder path."""

    return value


def make_filter(subject: Subject) -> str:
    """
    Generate one Betterbird filter for a MADS subject.

    Match the subject code/name in either the message subject
    or message body.
    """

    email_uri = IMAP_USER.replace("@", "%40")
    folder_uri = escape_uri_component(subject.folder)

    action_uri = (
        f"imap\\://"
        f"{email_uri}"
        f"\\@imap.gmail.com/"
        f"{folder_uri}"
    )

    code = escape_filter_value(subject.code)
    name = escape_filter_value(subject.name)

    condition = (
        f'OR (subject,contains,{code}) '
        f'OR (subject,contains,{name}) '
        f'OR (body,contains,{code}) '
        f'OR (body,contains,{name})'
    )

    return "\n".join(
        [
            f'name="{subject.filter_name}"',
            'enabled="yes"',
            'type="17"',
            'action="Move to folder"',
            f'actionValue="{action_uri}"',
            f'condition="{condition}"',
        ]
    )


def remove_managed_subject_filters(
    text: str,
    subjects: list[Subject],
) -> str:
    """
    Remove MADS subject filters that this script will replace.

    Removes:
      * filters beginning with [MADS AUTO]
      * existing filters whose name contains a current MADS
        subject code

    Unrelated manual filters are preserved.
    """

    subject_codes = {
        subject.code.upper()
        for subject in subjects
    }

    lines = text.splitlines()

    output: list[str] = []
    current: list[str] = []
    remove_current = False

    def flush() -> None:
        nonlocal current, remove_current

        if current and not remove_current:
            output.extend(current)

        current = []
        remove_current = False

    for line in lines:

        if line.startswith('name="'):
            flush()

            current = [line]

            filter_name = line[len('name="'):-1]
            filter_name_upper = filter_name.upper()

            remove_current = (
                filter_name.startswith(FILTER_PREFIX)
                or any(
                    code in filter_name_upper
                    for code in subject_codes
                )
            )

        elif current:
            current.append(line)

        else:
            output.append(line)

    flush()

    return "\n".join(output).rstrip()


def generate_filter_file(
    subjects: list[Subject],
    dry_run: bool,
) -> None:
    """Display or update the Betterbird filter file."""

    print()
    print("Betterbird filters:")

    for subject in subjects:
        print(
            f"  {subject.code:<8} "
            f"→ {subject.folder}"
        )

    if dry_run:
        return

    if not FILTER_FILE.exists():
        print()
        print("ERROR: Betterbird filter file not found:")
        print(f"  {FILTER_FILE}")
        sys.exit(1)

    original = FILTER_FILE.read_text(
        encoding="utf-8",
    )

    # Always make a timestamped backup before modifying it.
    timestamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )

    backup = FILTER_FILE.with_name(
        f"{FILTER_FILE.name}.backup-{timestamp}"
    )

    shutil.copy2(
        FILTER_FILE,
        backup,
    )

    preserved = remove_managed_subject_filters(
        original,
        subjects,
    )

    if not preserved.strip():
        preserved = 'version="9"\nlogging="no"'

    generated = "\n".join(
        make_filter(subject)
        for subject in subjects
    )

    new_contents = (
        preserved.rstrip()
        + "\n"
        + generated
        + "\n"
    )

    FILTER_FILE.write_text(
        new_contents,
        encoding="utf-8",
    )

    print()
    print("Updated:")
    print(f"  {FILTER_FILE}")

    print()
    print("Backup:")
    print(f"  {backup}")

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_plan(subjects: list[Subject]) -> None:

    print()
    print(f"MADS study plan: {len(subjects)} subjects")
    print()

    current_year = None
    current_trimester = None

    for subject in subjects:

        if subject.year != current_year:
            current_year = subject.year
            current_trimester = None

            print(str(subject.year))

        if subject.trimester != current_trimester:
            current_trimester = subject.trimester

            print(f"  {subject.trimester}")

        print(
            f"    {subject.code:<8} "
            f"{subject.name}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronise the MADS study plan with "
            "UniSQ Betterbird filters."
        )
    )

    mode = parser.add_mutually_exclusive_group(
        required=True
    )

    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show expected folders and filters "
            "without changing anything."
        ),
    )

    mode.add_argument(
        "--apply-filters",
        action="store_true",
        help=(
            "Update Betterbird filters without "
            "modifying Gmail folders."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("=" * 64)
    print("UniSQ Betterbird Study Filter Synchroniser")
    print("=" * 64)

    subjects = load_subjects()

    if not subjects:
        print(
            f"No subjects found for course {COURSE_CODE}."
        )
        sys.exit(1)

    print_plan(subjects)

    folders = desired_folders(subjects)

    if args.dry_run:
        print()
        print("*** DRY RUN — nothing will be changed ***")

        print()
        print("Expected Betterbird/Gmail folders:")

        for folder in folders:
            print(f"  {folder}")

        print()
        print(
            "NOTE: Missing folders will be created by the "
            "Betterbird helper when Betterbird starts."
        )

    if not args.dry_run:
        request_file = write_folder_request(folders)
        print()
        print("Betterbird folder request written:")
        print(f"  {request_file}")

    generate_filter_file(
        subjects,
        dry_run=args.dry_run,
    )

    print()
    print("=" * 64)

    if args.dry_run:
        print(
            "Dry run complete. No changes were made."
        )
    else:
        print("Betterbird filters updated.")
        print()
        print(
            "Start Betterbird. The UniSQ Folder Sync helper will "
            "create missing folders using Betterbird's existing "
            "authenticated account."
        )

    print("=" * 64)


if __name__ == "__main__":
    main()
