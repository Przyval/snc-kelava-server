#!/usr/bin/env python3
"""
Outbox Consumer Worker (Postgres Version)
=========================================
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Fix: Import specific function to avoid circular import if needed
# but standard import is fine.
from kil.db.connection import get_db_connection
from kil.rules.rule_late_checkout import evaluate_late_checkout
from kil.rules.rule_photo_missing import evaluate_photo_missing

# Configuration
BATCH_SIZE = 3000
MAX_RETRIES = 3


def process_event(conn, event_row: dict) -> bool:
    cursor = conn.cursor()

    try:
        # Pyscopg3 dict row access
        payload_str = event_row["payload"]
        # Postgres JSONB comes as dict automatically if using psycopg with standard adapters?
        # Actually psycopg 3 adapts JSONB to python objects automatically.
        # But let's check if it's a string or dict.
        # If schema is JSONB, it returns dict/list.
        payload = (
            payload_str
            if isinstance(payload_str, (dict, list))
            else json.loads(payload_str)
        )

        occurred_at = payload.get("occurred_at") or event_row["created_at"]

        # Insert into events_norm (with dedupe)
        cursor.execute(
            """
            INSERT INTO events_norm (
                event_type, source_system, external_id,
                occurred_at, payload, context
            ) VALUES (%s, %s, %s, %s, %s, NULL)
            ON CONFLICT(event_type, external_id) DO NOTHING
        """,
            (
                event_row["event_type"],
                event_row["source_system"],
                event_row["external_id"],
                occurred_at,
                json.dumps(
                    payload
                ),  # Postgres JSONB expects valid json string or adapted object.
                # Psycopg adapts dict -> json automatically.
                # Ideally pass 'payload' object.
            ),
        )

        # Mark as sent
        cursor.execute(
            """
            UPDATE outbox_events 
            SET status = 'sent', sent_at = %s
            WHERE id = %s
        """,
            (datetime.now().isoformat(), event_row["id"]),
        )

        conn.commit()

        # Trigger rules for certain event types
        if event_row["event_type"] == "visit.completed":
            evaluate_photo_missing(conn, payload)
        elif event_row["event_type"] == "gps.location_update":
            evaluate_late_checkout(conn, payload)

        return True

    except Exception as e:
        # Mark as failed with error
        conn.rollback()
        cursor.execute(
            """
            UPDATE outbox_events 
            SET status = 'failed', 
                retry_count = retry_count + 1,
                error_message = %s
            WHERE id = %s
        """,
            (str(e)[:500], event_row["id"]),
        )
        conn.commit()

        print(f"  ❌ Failed to process event {event_row['id']}: {e}")
        return False


def run_consumer():
    print(f"🚀 Starting outbox consumer (Postgres)")
    print(f"   Batch size: {BATCH_SIZE}")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Fetch pending events
        cursor.execute(
            """
            SELECT 
                id, idempotency_key, event_type, source_system,
                external_id, payload, status, created_at, retry_count
            FROM outbox_events
            WHERE status = 'pending'
               OR (status = 'failed' AND retry_count < %s)
            ORDER BY created_at
            LIMIT %s
        """,
            (MAX_RETRIES, BATCH_SIZE),
        )

        rows = cursor.fetchall()
        # rows are dicts (from connection factory)

        print(f"   Found {len(rows)} pending events")

        success = 0
        failed = 0

        for row in rows:
            if process_event(conn, row):
                success += 1
            else:
                failed += 1

        print(f"✅ Consumer complete:")
        print(f"   Successful: {success}")
        print(f"   Failed: {failed}")

        cursor.execute("SELECT COUNT(*) as count FROM events_norm")
        total_events = cursor.fetchone()["count"]
        print(f"   Total events in events_norm: {total_events}")

    finally:
        conn.close()


def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM outbox_events 
            GROUP BY status
        """)
        outbox_stats = {row["status"]: row["count"] for row in cursor.fetchall()}

        cursor.execute("""
            SELECT event_type, COUNT(*) as count
            FROM events_norm 
            GROUP BY event_type
        """)
        event_stats = {row["event_type"]: row["count"] for row in cursor.fetchall()}

        return {"outbox": outbox_stats, "events": event_stats}

    finally:
        conn.close()


if __name__ == "__main__":
    run_consumer()
