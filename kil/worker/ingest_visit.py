#!/usr/bin/env python3
"""
Visit Ingestion Worker (Postgres Version)
=========================================
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
STREAM_NAME = "visit"


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
    cursor.execute(
        "SELECT last_cursor FROM sync_state WHERE stream_name = %s", (STREAM_NAME,)
    )
    row = cursor.fetchone()
    # If connection.py provided dict_row factory
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


def emit_event(
    conn, event_type: str, external_id: str, payload: dict, occurred_at: datetime
):
    idempotency_key = f"{event_type}:kelava:{external_id}"
    payload["occurred_at"] = occurred_at.isoformat() if occurred_at else None

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
        return True
    except Exception as e:
        print(f"Error emitting event: {e}")
        raise


def process_visit(kil_conn, row: dict) -> int:
    events_emitted = 0
    visit_id = row["id"]
    road_plan_id = row.get("id_road_plan")

    base_payload = {
        "visit_id": visit_id,
        "road_plan_id": road_plan_id,
        "tech_id": row.get("id_user"),
        "customer_id": row.get("id_customer"),
        "latitude": float(row.get("latitude")) if row.get("latitude") else None,
        "longitude": float(row.get("longitude")) if row.get("longitude") else None,
    }

    check_in = row.get("check_in")
    if check_in:
        started_payload = {
            **base_payload,
            "check_in": check_in.isoformat(),
            "latitude_in": float(row.get("latitude")) if row.get("latitude") else None,
            "longitude_in": float(row.get("longitude"))
            if row.get("longitude")
            else None,
        }
        if emit_event(
            kil_conn,
            "visit.started",
            f"visit:{visit_id}:start",
            started_payload,
            check_in,
        ):
            events_emitted += 1

    check_out = row.get("check_out")
    if check_out:
        duration_minutes = None
        if check_in and check_out:
            duration_minutes = (check_out - check_in).total_seconds() / 60

        completed_payload = {
            **base_payload,
            "check_in": check_in.isoformat() if check_in else None,
            "check_out": check_out.isoformat(),
            "duration_minutes": round(duration_minutes, 2)
            if duration_minutes
            else None,
            "latitude_out": float(row.get("latitude_o"))
            if row.get("latitude_o")
            else None,
            "longitude_out": float(row.get("longitude_o"))
            if row.get("longitude_o")
            else None,
        }
        if emit_event(
            kil_conn,
            "visit.completed",
            f"visit:{visit_id}:complete",
            completed_payload,
            check_out,
        ):
            events_emitted += 1

    return events_emitted


def run_ingestion():
    print(f"🚀 Starting visit ingestion worker (Postgres)")
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
        kelava_cursor.execute(
            """
            SELECT 
                id, id_road_plan, id_user, id_customer,
                check_in, check_out,
                latitude, longitude,
                latitude_o, longitude_o,
                realization_date
            FROM t_visit
            WHERE id > %s
            ORDER BY id
            LIMIT %s
        """,
            (current_cursor, BATCH_SIZE),
        )

        rows = kelava_cursor.fetchall()
        columns = [desc[0] for desc in kelava_cursor.description]

        print(f"   Fetched {len(rows)} rows from Kelava")

        for row in rows:
            row_dict = dict(zip(columns, row))
            events = process_visit(kil_conn, row_dict)
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
