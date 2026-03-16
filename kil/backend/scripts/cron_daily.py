#!/usr/bin/env python3
"""
Daily Cron Job for KIL Enterprise
==================================
Runs daily tasks:
1. Generate daily digest (yesterday's data)
2. Scan and create notifications
3. Log execution result

Schedule: 06:00 WIB (23:00 UTC previous day)
Crontab:  0 23 * * * /root/kil-server/.venv/bin/python3 /root/kil-server/kil/backend/scripts/cron_daily.py >> /root/kil-server/cron.log 2>&1
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kil" / "backend"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from kil.backend.legacy.app import app


def run_daily_tasks():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*50}")
    print(f"[{ts}] KIL Daily Cron starting...")

    with app.test_client() as client:
        # Get auth token (use system admin)
        login = client.post("/api/v1/auth/login", json={
            "email": os.environ.get("CRON_ADMIN_EMAIL", "admin@sanocare.work"),
            "password": os.environ.get("CRON_ADMIN_PASSWORD", "SanoCare2026!"),
        })
        if login.status_code != 200:
            print(f"  [ERROR] Login failed: {login.status_code}")
            return

        import json
        token = json.loads(login.data)["access_token"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # 1. Generate daily digest
        print("  [1] Generating daily digest...")
        r = client.post("/api/v1/enterprise/daily-digest/generate", headers=headers, json={})
        try:
            data = json.loads(r.data)
        except Exception:
            data = {"error": r.data.decode()[:200]}
        if r.status_code == 200:
            visits = data.get("digest", {}).get("visits", {})
            print(f"      OK: {visits.get('completed', 0)}/{visits.get('total_planned', 0)} visits, rate={visits.get('completion_rate', 0)}%")
        elif r.status_code == 409:
            print(f"      SKIP: Digest already exists for {data.get('id')}")
        else:
            print(f"      ERROR: {r.status_code} - {data}")

        # 2. Generate notifications
        print("  [2] Scanning for notifications...")
        r = client.post("/api/v1/enterprise/notifications/generate", headers=headers, json={})
        try:
            data = json.loads(r.data)
        except Exception:
            data = {"error": r.data.decode()[:200]}
        if r.status_code == 200:
            print(f"      OK: {data.get('created', 0)} new notifications created")
        else:
            print(f"      ERROR: {r.status_code} - {data}")

        # 3. SLA breach sweep (mark overdue complaints)
        print("  [3] SLA breach sweep...")
        r = client.get("/api/v1/enterprise/complaints/sla-status", headers=headers)
        try:
            data = json.loads(r.data)
        except Exception:
            data = {}
        if r.status_code == 200:
            breached = data.get("breached", 0)
            at_risk = data.get("at_risk", 0)
            print(f"      OK: {breached} breached, {at_risk} at-risk complaints")
        else:
            print(f"      ERROR: {r.status_code}")

        # 4. Health check
        print("  [4] Health check...")
        r = client.get("/health")
        data = json.loads(r.data)
        print(f"      Status: {data.get('status', 'unknown')}")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Daily cron completed.")


if __name__ == "__main__":
    run_daily_tasks()
