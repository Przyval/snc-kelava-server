#!/bin/bash
# ============================================================
# SanoCare KPI Pipeline - Cron Wrapper
# ============================================================
# Usage: Add to crontab for scheduled execution
#
# Example crontab (WIB, Mon-Sat 18:30):
#   30 18 * * 1-6 /path/to/kpi_cron.sh >> /path/to/logs/kpi_cron.log 2>&1
#
# Features:
# - Runs the full pipeline
# - Sends notification on failure
# - Logs all output with timestamps
# ============================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PIPELINE_SCRIPT="$SCRIPT_DIR/run_kpi_pipeline.py"
LOG_DIR="$SCRIPT_DIR/logs"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

# Notification settings (customize for your environment)
NOTIFY_ON_FAILURE="true"
NOTIFY_EMAIL=""  # Set to email address if using email
NOTIFY_WEBHOOK="" # Set to Slack/WA webhook URL if using webhooks

# ============================================================
# Functions
# ============================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

send_notification() {
    local status="$1"
    local message="$2"
    local run_id="$3"
    
    if [ "$NOTIFY_ON_FAILURE" != "true" ] && [ "$status" = "FAILURE" ]; then
        return
    fi
    
    # Email notification
    if [ -n "$NOTIFY_EMAIL" ]; then
        echo "$message" | mail -s "KPI Pipeline $status - $run_id" "$NOTIFY_EMAIL"
        log "Notification sent to $NOTIFY_EMAIL"
    fi
    
    # Webhook notification (Slack/Teams/WA)
    if [ -n "$NOTIFY_WEBHOOK" ]; then
        curl -s -X POST "$NOTIFY_WEBHOOK" \
            -H "Content-Type: application/json" \
            -d "{\"text\": \"KPI Pipeline $status\\n$message\\nRun ID: $run_id\"}"
        log "Webhook notification sent"
    fi
}

# ============================================================
# Main Execution
# ============================================================

log "============================================================"
log "KPI Pipeline Cron Job Started"
log "============================================================"

# Create logs directory
mkdir -p "$LOG_DIR"

# Change to script directory
cd "$SCRIPT_DIR"

# Capture run start
RUN_START=$(date '+%Y-%m-%d %H:%M:%S')

# Execute pipeline
log "Executing: $PYTHON_BIN $PIPELINE_SCRIPT"

if $PYTHON_BIN "$PIPELINE_SCRIPT"; then
    RUN_STATUS="SUCCESS"
    RUN_END=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Get the latest run ID
    LATEST_RUN=$(ls -1t runs/ | head -1)
    
    log "Pipeline completed successfully"
    log "Run ID: $LATEST_RUN"
    log "Output: $SCRIPT_DIR/runs/$LATEST_RUN"
    
    # Send success notification (optional)
    # send_notification "SUCCESS" "Pipeline completed at $RUN_END" "$LATEST_RUN"
    
else
    RUN_STATUS="FAILURE"
    RUN_END=$(date '+%Y-%m-%d %H:%M:%S')
    EXIT_CODE=$?
    
    # Get the latest run ID (might have failure notes)
    LATEST_RUN=$(ls -1t runs/ | head -1)
    
    log "Pipeline FAILED with exit code $EXIT_CODE"
    log "Check: $SCRIPT_DIR/runs/$LATEST_RUN/FAILURE_NOTES.md"
    
    # Send failure notification
    FAILURE_MSG="Pipeline failed at $RUN_END (exit code: $EXIT_CODE)
Check FAILURE_NOTES.md for details."
    
    send_notification "FAILURE" "$FAILURE_MSG" "$LATEST_RUN"
fi

log "============================================================"
log "KPI Pipeline Cron Job Finished - $RUN_STATUS"
log "============================================================"

exit 0
