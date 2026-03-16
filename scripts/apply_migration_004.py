#!/usr/bin/env python3
"""
Apply Migration 004: Meeting Features
=======================================
Applies the database schema for features discussed in the 2026-02-19 meeting:
- Technician Segments (Mobile/Station/Support/Supervisor)
- Schedule Templates (Plants vs Zombies scheduling)
- Punctuality Tracking
- Supervisory Actions / Sidak
- Complaint Tracking
- Supervision Reports
- Customer Audit Schedules

Usage:
    python scripts/apply_migration_004.py [--dry-run]
"""

import os
import sys
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from kil.db.kelava_db import get_kelava_connection


def apply_migration(dry_run: bool = False):
    migration_path = PROJECT_ROOT / "kil" / "db" / "migrations" / "004_meeting_features.sql"

    if not migration_path.exists():
        print(f"Migration file not found: {migration_path}")
        sys.exit(1)

    sql = migration_path.read_text()

    print(f"Migration: {migration_path.name}")
    print(f"Size: {len(sql)} bytes")
    print(f"Dry run: {dry_run}")
    print("-" * 60)

    if dry_run:
        print("SQL Preview (first 500 chars):")
        print(sql[:500])
        print("...")
        print("\nDry run complete. Use without --dry-run to apply.")
        return

    conn = get_kelava_connection()
    # Need autocommit=False for transaction
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print("Migration applied successfully!")

        # Verify tables created
        with conn.cursor() as cur:
            tables = [
                "technician_segments",
                "segment_kpi_rules",
                "schedule_templates",
                "punctuality_records",
                "supervisory_actions",
                "complaints",
                "complaint_actions",
                "supervision_reports",
                "customer_audit_schedules",
            ]
            for table in tables:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = %s",
                    (table,),
                )
                result = cur.fetchone()
                status = "OK" if result and result["cnt"] > 0 else "MISSING"
                print(f"  {status}: {table}")

    except Exception as e:
        conn.rollback()
        print(f"Migration FAILED: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    apply_migration(dry_run=dry_run)
