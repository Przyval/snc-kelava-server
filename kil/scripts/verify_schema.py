#!/usr/bin/env python3
"""
Verify Kelava Schema
====================
Checks if the expected tables and columns exist in Kelava database.
"""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psycopg
from dotenv import load_dotenv

load_dotenv()

EXPECTED_SCHEMA = {
    "t_road_plan": [
        "id",
        "id_user",
        "id_customer",
        "visit_date",
        "status",
        "type",
        "title",
        "is_cancel",
        "created_date",
    ],
    "t_visit": [
        "id",
        "id_road_plan",
        "id_user",
        "id_customer",
        "check_in",
        "check_out",
        "latitude",
        "longitude",
        "latitude_o",
        "longitude_o",
        "realization_date",
    ],
    "t_road_plan_foto": ["id", "id_road_plan"],
}


def check_schema():
    print("🔍 verify_schema: Connecting to Kelava...")
    try:
        conn = psycopg.connect(
            host=os.environ.get("KELAVA_HOST"),
            port=os.environ.get("KELAVA_PORT"),
            dbname=os.environ.get("KELAVA_DB"),
            user=os.environ.get("KELAVA_USER"),
            password=os.environ.get("KELAVA_PASSWORD"),
        )
        print("✅ Connection successful!")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

    cursor = conn.cursor()
    success = True

    for table, columns in EXPECTED_SCHEMA.items():
        print(f"\nChecking table: {table}")

        # Check if table exists
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = %s
            );
        """,
            (table,),
        )

        if not cursor.fetchone()[0]:
            print(f"  ❌ Table {table} NOT FOUND")
            success = False
            continue

        print(f"  ✅ Table {table} exists")

        # Check columns
        cursor.execute(
            """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s;
        """,
            (table,),
        )

        existing_columns = {row[0] for row in cursor.fetchall()}

        for col in columns:
            if col in existing_columns:
                print(f"  ✅ Column {col} found")
            else:
                print(f"  ❌ Column {col} NOT FOUND")
                success = False

    conn.close()
    return success


if __name__ == "__main__":
    if check_schema():
        print("\n✅ SCHEMA VERIFICATION PASSED")
        sys.exit(0)
    else:
        print("\n❌ SCHEMA VERIFICATION FAILED")
        sys.exit(1)
