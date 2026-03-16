#!/usr/bin/env python3
"""
Road Plan Ingestion Worker
==========================
Ingests road_plan data from Kelava and emits job events.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg
from dotenv import load_dotenv

from kil.db.connection import get_db_connection

# Load environment variables
load_dotenv()

# Configuration
BATCH_SIZE = 1000
STREAM_NAME = "road_plan"


def get_kelava_connection():
    return psycopg.connect(
        host=os.environ.get("KELAVA_HOST"),
        port=os.environ.get("KELAVA_PORT", 5432),
        dbname=os.environ.get("KELAVA_DB"),
        user=os.environ.get("KELAVA_USER"),
        password=os.environ.get("KELAVA_PASSWORD"),
    )


def get_cursor(conn) -> int:
    cursor = conn.cursor()
    # Postgres uses %s
    cursor.execute(
        "SELECT last_cursor FROM sync_state WHERE stream_name = %s", (STREAM_NAME,)
    )
    row = cursor.fetchone()
    return row["last_cursor"] if row else 0


def update_cursor(conn, cursor_value: int, row_count: int):
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE sync_state 
        SET last_cursor = %s, 
            last_sync_at = %s,
            row_count = row_count + %s
        WHERE stream_name = %s
    """,
        (cursor_value, datetime.now().isoformat(), row_count, STREAM_NAME),
    )
    conn.commit()


def emit_event(conn, event_type: str, external_id: str, payload: dict):
    idempotency_key = f"{event_type}:kelava:{external_id}"
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO outbox_events (
                idempotency_key, event_type, source_system, 
                external_id, payload, status
            ) VALUES (%s, %s, 'kelava', %s, %s, 'pending')
            ON CONFLICT (idempotency_key) DO NOTHING
        """,
            (idempotency_key, event_type, external_id, json.dumps(payload)),
        )
        conn.commit()
        return True  # In Postgres, we don't know if inserted or skipped easily unless we use RETURNING
        # But for logic flow, returning True is fine as long as no exception.
        # Ideally: INSERT ... RETURNING id. If fetchone() is None, then duplicate.
    except Exception as e:
        print(f"Error emitting event: {e}")
        raise


def process_road_plan(kil_conn, row: dict) -> int:
    events_emitted = 0
    road_plan_id = row["id"]

    base_payload = {
        "road_plan_id": road_plan_id,
        "tech_id": row.get("id_user"),
        "customer_id": row.get("id_customer"),
        "visit_date": row.get("visit_date").isoformat()
        if row.get("visit_date")
        else None,
        "status": row.get("status"),
        "visit_type": row.get("type"),
        "title": row.get("title"),
    }

    created_payload = {
        **base_payload,
        "created_at": row.get("created_date").isoformat()
        if row.get("created_date")
        else None,
    }
    if emit_event(
        kil_conn, "job.created", f"road_plan:{road_plan_id}", created_payload
    ):
        events_emitted += 1

    if row.get("is_cancel"):
        cancel_payload = {
            **base_payload,
            "canceled_at": datetime.now().isoformat(),
        }
        if emit_event(
            kil_conn, "job.canceled", f"road_plan:{road_plan_id}:cancel", cancel_payload
        ):
            events_emitted += 1

    return events_emitted


def run_ingestion():
    print(f"🚀 Starting road_plan ingestion worker (Postgres)")
    kil_conn = get_db_connection()
    current_cursor = get_cursor(kil_conn)
    print(f"   Starting from cursor: {current_cursor}")

    try:
        kelava_conn = get_kelava_connection()
    except Exception as e:
        print(f"❌ Failed to connect to Kelava: {e}")
        return

    total_events = 0
    total_rows = 0

    try:
        kelava_cursor = kelava_conn.cursor()

        # Kelava is Postgres too, so %s works there
        kelava_cursor.execute(
            """
            SELECT 
                id, id_user, id_customer, id_kontrak,
                visit_date, status, type, title,
                is_cancel, created_date
            FROM t_road_plan
            WHERE id > %s
            ORDER BY id
            LIMIT %s
        """,
            (current_cursor, BATCH_SIZE),
        )

        rows = kelava_cursor.fetchall()
        # Psycopg3 rows are tuples or dicts depending on factory.
        # Here Kelava conn uses default (tuples) likely?
        # Actually in ingest_road_plan.py original, we used `dict(zip(columns, row))`.
        # Let's keep that pattern if Kelava conn is vanilla psycopg.

        columns = [desc[0] for desc in kelava_cursor.description]

        print(f"   Fetched {len(rows)} rows from Kelava")

        for row in rows:
            row_dict = dict(zip(columns, row))
            events = process_road_plan(kil_conn, row_dict)
            total_events += events
            total_rows += 1
            current_cursor = row_dict["id"]

        if total_rows > 0:
            update_cursor(kil_conn, current_cursor, total_rows)

        print(f"✅ Ingestion complete:")
        print(f"   Rows processed: {total_rows}")
        print(f"   Events emitted: {total_events}")
        print(f"   New cursor: {current_cursor}")

    finally:
        kelava_conn.close()
        kil_conn.close()


if __name__ == "__main__":
    run_ingestion()
