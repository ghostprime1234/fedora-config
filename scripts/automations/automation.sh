#!/usr/bin/env bash
# ==============================================================================
# Personal Routine & Maintenance Automation Script
# ==============================================================================
set -euo pipefail

# Configuration & Directories
AUTOMATION_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/automation"
ENV_FILE="$AUTOMATION_DIR/.env"
DOWNLOADS_DIR="$HOME/Downloads"
SCREENSHOTS_DIR="$HOME/Desktop"            # Adjust if saved elsewhere
SCREENSHOT_REVIEW_DIR="$HOME/Pictures/Screenshots_Review"
REPORTS_DIR="$HOME/Documents/WeeklyReports"
REPOS_DIR="$HOME/Workspace"                # Parent directory of your Git projects

# Load environment variables (API keys, webhooks) if present
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
fi

log() {
    printf "[%(%Y-%m-%d %H:%M:%S)T] %s\n" -1 "$*"
}

# ------------------------------------------------------------------------------
# 1. Download Cleanup & Organization
# ------------------------------------------------------------------------------
sort_downloads() {
    log "Starting Downloads cleanup..."
    mkdir -p "$DOWNLOADS_DIR"/{Documents,Archives,Installers,Media}

    # Sort files modified more than 1 day ago to avoid moving active downloads
    find "$DOWNLOADS_DIR" -maxdepth 1 -type f -mtime +1 | while IFS= read -r file; do
        ext="${file##*.}"
        case "${ext,,}" in
            pdf|docx|txt|epub|csv|xlsx)
                mv "$file" "$DOWNLOADS_DIR/Documents/"
                ;;
            zip|tar|gz|bz2|7z|xz)
                mv "$file" "$DOWNLOADS_DIR/Archives/"
                ;;
            deb|rpm|dmg|pkg|AppImage|exe|msi)
                mv "$file" "$DOWNLOADS_DIR/Installers/"
                ;;
            png|jpg|jpeg|gif|mp4|mkv|mov|mp3)
                mv "$file" "$DOWNLOADS_DIR/Media/"
                ;;
            *)
                # Leave unrecognized files untouched
                ;;
        esac
    done
    log "Downloads folder sorted."
}

# ------------------------------------------------------------------------------
# 2. Screenshot Archiving
# ------------------------------------------------------------------------------
move_old_screenshots() {
    log "Moving old screenshots to review folder..."
    mkdir -p "$SCREENSHOT_REVIEW_DIR"

    # Match common screenshot naming patterns (e.g., macOS, GNOME, Flameshot) older than 7 days
    find "$SCREENSHOTS_DIR" -maxdepth 1 -type f \
        \( -name "Screenshot*" -o -name "Screen Shot*" -o -name "flameshot*" \) \
        -mtime +7 -exec mv {} "$SCREENSHOT_REVIEW_DIR/" \;

    log "Screenshots older than 7 days moved to $SCREENSHOT_REVIEW_DIR."
}

# ------------------------------------------------------------------------------
# 3. Weekly Git Work Summary
# ------------------------------------------------------------------------------
create_work_summary() {
    log "Compiling weekly git commit summary..."
    mkdir -p "$REPORTS_DIR"
    local report_file="$REPORTS_DIR/summary_$(date +%Y-%m-%d).txt"

    {
        echo "=================================================="
        echo " Weekly Work Summary: $(date +'%Y-%m-%d')"
        echo "=================================================="
        echo

        if [[ -d "$REPOS_DIR" ]]; then
            # Find git repos 1 level deep
            find "$REPOS_DIR" -maxdepth 2 -type d -name ".git" | while IFS= read -r gitdir; do
                repo_path="$(dirname "$gitdir")"
                repo_name="$(basename "$repo_path")"
                
                commits=$(git -C "$repo_path" log --author="$(git config user.name)" --since="7 days ago" --oneline 2>/dev/null || true)
                if [[ -n "$commits" ]]; then
                    echo "[$repo_name]"
                    echo "$commits"
                    echo
                fi
            done
        fi
    } > "$report_file"

    log "Weekly commit report written to $report_file."
}

# ------------------------------------------------------------------------------
# 4. Webhook / Notification Reminder Stub
# ------------------------------------------------------------------------------
send_due_reminders() {
    log "Checking notifications / recurring triggers..."
    # Example: If a DISCORD_WEBHOOK or SLACK_WEBHOOK is configured in .env
    if [[ -n "${NOTIFICATION_WEBHOOK_URL:-}" ]]; then
        curl -s -X POST -H "Content-Type: application/json" \
            -d '{"content": "Automation Notice: Daily cleanup routine completed successfully."}' \
            "$NOTIFICATION_WEBHOOK_URL" > /dev/null || true
    fi
}

# ------------------------------------------------------------------------------
# Task Bundles & Entrypoint
# ------------------------------------------------------------------------------
daily_tasks() {
    log "--- Running Daily Tasks ---"
    sort_downloads
    move_old_screenshots
    send_due_reminders
}

weekly_tasks() {
    log "--- Running Weekly Tasks ---"
    create_work_summary
}

case "${1:-daily}" in
    daily)
        daily_tasks
        ;;
    weekly)
        weekly_tasks
        ;;
    all)
        daily_tasks
        weekly_tasks
        ;;
    *)
        echo "Usage: $0 {daily|weekly|all}"
        exit 1
        ;;
esac