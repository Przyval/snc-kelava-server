#!/usr/bin/env python3
"""
Attendance Reminder
====================
Sends WhatsApp reminders to technicians who haven't checked in yet.
Designed to run via cron at 08:00 and 08:30.

Usage:
    python -m kil.backend.scripts.attendance_reminder
    python -m kil.backend.scripts.attendance_reminder --urgent  (more firm message)
"""

import argparse
import sys
from datetime import date, datetime, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kil" / "backend"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single


def send_reminders(urgent: bool = False):
    """
    Check who hasn't checked in today and send WA reminders.
    """
    today = date.today()
    now_time = datetime.now().time()

    # Skip weekends (Sunday = 6)
    if today.weekday() == 6:
        print("Sunday - skipping")
        return

    # Get all mapped technicians
    mapped = execute_kelava_query(
        """
        SELECT DISTINCT am.technician_id, u.fullname as name, u.phone
        FROM attendance_user_map am
        JOIN p_user u ON u.id = am.technician_id
        JOIN attendance_devices ad ON ad.device_sn = am.device_sn
        WHERE ad.is_active = true
        """,
    )

    if not mapped:
        print("No mapped technicians found")
        return

    # Get who already checked in today
    checked_in = execute_kelava_query(
        """
        SELECT DISTINCT technician_id
        FROM attendance_logs
        WHERE punch_time::date = %s
          AND technician_id IS NOT NULL
        """,
        (today.isoformat(),),
    )
    checked_in_ids = {r["technician_id"] for r in checked_in}

    # Find absent technicians
    absent = [m for m in mapped if m["technician_id"] not in checked_in_ids]

    if not absent:
        print(f"All {len(mapped)} technicians checked in!")
        return

    print(f"Found {len(absent)} absent technicians out of {len(mapped)} total")

    from kil.backend.legacy.api.wa_gateway import send_whatsapp

    sent = 0
    skipped = 0
    for tech in absent:
        phone = tech.get("phone", "")
        if not phone:
            skipped += 1
            continue

        # Check if reminder already sent for this time slot
        existing = execute_kelava_query_single(
            """
            SELECT id FROM attendance_reminders
            WHERE technician_id = %s AND reminder_date = %s AND reminder_time = %s
            """,
            (tech["technician_id"], today.isoformat(), now_time.strftime("%H:%M:00")),
        )
        if existing:
            skipped += 1
            continue

        # Build message
        if urgent:
            message = (
                f"*PENGINGAT ABSENSI*\n\n"
                f"Halo {tech['name']},\n"
                f"Anda *belum melakukan absensi* hari ini ({today.strftime('%d %b %Y')}).\n\n"
                f"Segera lakukan check-in di mesin fingerprint.\n"
                f"Jika ada kendala, hubungi koordinator.\n\n"
                f"_SanoCare Enterprise_"
            )
        else:
            message = (
                f"Selamat pagi {tech['name']},\n"
                f"Reminder: Jangan lupa absensi fingerprint ya.\n"
                f"_SanoCare Enterprise_"
            )

        result = send_whatsapp(phone, message)

        # Log reminder
        status = "sent" if result["success"] else "failed"
        execute_kelava_query_single(
            """
            INSERT INTO attendance_reminders
                (technician_id, reminder_date, reminder_time, channel, status, sent_at)
            VALUES (%s, %s, %s, 'whatsapp', %s, %s)
            ON CONFLICT (technician_id, reminder_date, reminder_time) DO UPDATE
            SET status = EXCLUDED.status, sent_at = EXCLUDED.sent_at
            """,
            (
                tech["technician_id"],
                today.isoformat(),
                now_time.strftime("%H:%M:00"),
                status,
                datetime.now() if result["success"] else None,
            ),
        )

        if result["success"]:
            sent += 1
            print(f"  Sent to {tech['name']} ({phone})")
        else:
            print(f"  Failed for {tech['name']}: {result['detail']}")

    print(f"Done: {sent} sent, {skipped} skipped, {len(absent) - sent - skipped} failed")


def main():
    parser = argparse.ArgumentParser(description="Send attendance reminders")
    parser.add_argument("--urgent", action="store_true", help="Send urgent/firm reminder")
    args = parser.parse_args()

    send_reminders(urgent=args.urgent)


if __name__ == "__main__":
    main()
