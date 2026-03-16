#!/usr/bin/env python3
"""
GPS Ingestion Worker (Docker Exec Strategy)
===========================================
Reads GPS positions from Fleetbase via `docker exec` (CSV dump)
to bypass host <-> container network auth issues.
"""

import csv
import io
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg

from kil.db.connection import get_db_connection

# Config
BATCH_SIZE = 1000


def fetch_data_via_docker():
    """Run docker exec mysql query and return CSV string"""
    print("   Fetching data from Fleetbase (via docker exec)...")

    # Query: Get new positions with driver info
    # We join drivers to value-add the event with internal_id (Kelava ID)
    query = """
    SELECT 
        p.uuid as position_uuid,
        p.subject_uuid as driver_uuid,
        d.public_id,
        d.internal_id,
        ST_X(p.coordinates) as lat,
        ST_Y(p.coordinates) as lng,
        p.created_at
    FROM positions p
    JOIN drivers d ON p.subject_uuid = d.uuid
    ORDER BY p.created_at ASC
    LIMIT 200;
    """

    # Use -B (batch) maybe? No, simple -e is fine. But wait, output format?
    # Getting clean CSV from mysql CLI is tricky without sed/awk hacking or INTO OUTFILE.
    # We will use python's csv module on the raw TSV output (mysql default).

    cmd = [
        "docker",
        "exec",
        "-i",
        "fleetbase-database-1",
        "mysql",
        "-u",
        "root",
        "fleetbase",
        "-B",
        "-e",
        query,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Docker exec failed: {result.stderr}")
        return None

    return result.stdout


def ingest_gps():
    print("🚀 Starting GPS Ingestion Worker")

    # 1. Fetch Data
    raw_data = fetch_data_via_docker()
    if not raw_data:
        return

    # 2. Parse TSV/Output
    # MySQL -B outputs TSV with header
    reader = csv.DictReader(io.StringIO(raw_data), delimiter="\t")
    rows = list(reader)
    print(f"   Fetched {len(rows)} positions")

    if not rows:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    events_count = 0

    try:
        for row in rows:
            # Parse row
            # Columns: position_uuid, driver_uuid, public_id, internal_id, lat, lng, created_at

            # 1. Insert into gps_positions (Cache)
            # Check dupes? Just insert for log.
            cursor.execute(
                """
                INSERT INTO gps_positions (internal_id, latitude, longitude, captured_at)
                VALUES (%s, %s, %s, %s)
            """,
                (row["internal_id"], row["lat"], row["lng"], row["created_at"]),
            )

            # 2. Emit Event
            payload = {
                "tech_id": row["internal_id"],
                "driver_id": row["public_id"],
                "lat": float(row["lat"]),
                "lng": float(row["lng"]),
                "pos_uuid": row["position_uuid"],
            }

            occurred_at = row["created_at"]

            # Insert outbox? Or direct to events_norm?
            # Standard pattern: Ingest -> Outbox -> Consumer -> Events.
            # But high frequency GPS... maybe direct to specific table?
            # Implementation Plan said "Stream: gps_position".
            # Let's put in outbox for consistency, filtering dupes with idempotency.

            idempotency_key = f"gps:{row['position_uuid']}"

            cursor.execute(
                """
                INSERT INTO outbox_events (
                    idempotency_key, event_type, source_system, external_id, payload, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING
            """,
                (
                    idempotency_key,
                    "gps.location_update",
                    "fleetbase",
                    row["position_uuid"],
                    json.dumps(payload),
                    datetime.now(),  # or occurred_at for created? better now.
                ),
            )

            if cursor.rowcount > 0:
                events_count += 1

        conn.commit()
        print(f"✅ Ingestion complete.")
        print(f"   GPS Points Saved: {len(rows)}")
        print(f"   Events Queued: {events_count}")

    finally:
        conn.close()


if __name__ == "__main__":
    ingest_gps()
