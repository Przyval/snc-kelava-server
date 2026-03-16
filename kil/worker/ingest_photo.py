#!/usr/bin/env python3
"""
Photo Ingestion Worker (Postgres Version)
=========================================
"""

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
BATCH_SIZE = 5000
STREAM_NAME = "photo"


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


def update_foto_cache(kil_conn, road_plan_id: int, foto_count: int):
    cursor = kil_conn.cursor()
    # Postgres UPSERT
    cursor.execute(
        """
        INSERT INTO foto_cache (road_plan_id, foto_count, last_updated)
        VALUES (%s, %s, %s)
        ON CONFLICT(road_plan_id) DO UPDATE SET
            foto_count = excluded.foto_count,
            last_updated = excluded.last_updated
    """,
        (road_plan_id, foto_count, datetime.now().isoformat()),
    )
    kil_conn.commit()


def run_ingestion():
    print(f"🚀 Starting photo ingestion worker (Postgres)")
    kil_conn = get_db_connection()
    current_cursor = get_cursor(kil_conn)
    print(f"   Starting from cursor: {current_cursor}")

    try:
        kelava_conn = get_kelava_connection()
    except Exception as e:
        print(f"❌ Failed to connect to Kelava: {e}")
        return

    total_updated = 0
    max_id = current_cursor

    try:
        kelava_cursor = kelava_conn.cursor()

        # We aggregate by road_plan_id
        kelava_cursor.execute(
            """
            SELECT 
                id_road_plan,
                COUNT(*) as foto_count,
                MAX(id) as max_photo_id
            FROM t_road_plan_foto
            WHERE id > %s
            GROUP BY id_road_plan
            ORDER BY max_photo_id
            LIMIT %s
        """,
            (current_cursor, BATCH_SIZE),
        )

        rows = kelava_cursor.fetchall()

        print(f"   Fetched {len(rows)} road_plan foto aggregates")

        for row in rows:
            # Psycopg3 vs 2: fetchall returns tuples by default
            road_plan_id, foto_count, max_photo_id = row
            update_foto_cache(kil_conn, road_plan_id, foto_count)
            total_updated += 1
            max_id = max(max_id, max_photo_id)

        if total_updated > 0:
            update_cursor(kil_conn, max_id, total_updated)

        print(f"✅ Ingestion complete:")
        print(f"   Road plans updated: {total_updated}")
        print(f"   New cursor: {max_id}")

    finally:
        kelava_conn.close()
        kil_conn.close()


def refresh_full_cache():
    print(f"🔄 Starting full foto_cache refresh (Postgres)")
    kil_conn = get_db_connection()

    try:
        kelava_conn = get_kelava_connection()
    except Exception as e:
        print(f"❌ Failed to connect to Kelava: {e}")
        return

    try:
        kelava_cursor = kelava_conn.cursor()
        kelava_cursor.execute("""
            SELECT 
                id_road_plan,
                COUNT(*) as foto_count
            FROM t_road_plan_foto
            GROUP BY id_road_plan
        """)

        rows = kelava_cursor.fetchall()
        print(f"   Found {len(rows)} road_plans with photos")

        kil_cursor = kil_conn.cursor()
        now = datetime.now().isoformat()

        # Batch upsert could be optimized but single standard inserts for now
        # Ideally use copy or executemany. Executemany is good.
        data = [(rp, count, now) for rp, count in rows]

        kil_cursor.executemany(
            """
            INSERT INTO foto_cache (road_plan_id, foto_count, last_updated)
            VALUES (%s, %s, %s)
            ON CONFLICT(road_plan_id) DO UPDATE SET
                foto_count = excluded.foto_count,
                last_updated = excluded.last_updated
        """,
            data,
        )

        kil_conn.commit()
        print(f"✅ Full refresh complete: {len(rows)} road plans cached")

    finally:
        kelava_conn.close()
        kil_conn.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--full":
        refresh_full_cache()
    else:
        run_ingestion()
