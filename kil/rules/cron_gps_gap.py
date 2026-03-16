#!/usr/bin/env python3
"""
GPS Gap Detection Rule (Cron)
=============================
Run periodically (e.g. every 15 mins).
Logic:
1. Find techs with Active Visits today.
2. Check their last GPS capture time in `gps_positions`.
3. If delta > 30 mins, raise 'gps_gap_detected'.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from kil.db.connection import get_db_connection


def find_gps_gaps():
    print("running GPS Gap Rule...")
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Get Active Techs (those who started a visit today and not finished all?
    # Or just anyone with a visit started today.)
    # Let's say anyone with a visit started today is "Active".
    # Better: Techs with "Active Visit" state.

    # Simplified: Get all techs who emitted `visit.started` today.
    cursor.execute("""
        SELECT DISTINCT payload->>'tech_id' as tech_id
        FROM events_norm
        WHERE event_type = 'visit.started'
          AND occurred_at > CURRENT_DATE
    """)
    active_techs = [row["tech_id"] for row in cursor.fetchall()]

    print(f"   Active Techs today: {active_techs}")

    if not active_techs:
        return

    # 2. Check Last GPS for these techs
    issues_created = 0

    for tech_id in active_techs:
        cursor.execute(
            """
            SELECT captured_at, latitude, longitude
            FROM gps_positions
            WHERE internal_id = %s
            ORDER BY captured_at DESC
            LIMIT 1
        """,
            (tech_id,),
        )

        last_pos = cursor.fetchone()

        if not last_pos:
            # No GPS at all today? That's a huge gap.
            gap_minutes = 999
            last_seen = "Never"
        else:
            # Postgres timestamp is with timezone usually, ensure compatibility
            # captured_at in schema is TIMESTAMPTZ.
            # python datetime.now() is local?
            last_seen_time = last_pos["captured_at"]

            # Ensure timezone awareness match
            now = datetime.now().astimezone()
            if last_seen_time.tzinfo is None:
                # Assume it's in same TZ or UTC?
                # Schema said TIMESTAMPTZ, so psycopg gives datetime with tzinfo.
                pass

            delta = now - last_seen_time
            gap_minutes = delta.total_seconds() / 60
            last_seen = last_seen_time.isoformat()

        if gap_minutes > 30:
            # RAISE ISSUE
            issue_key = f"gps_gap:{tech_id}:{datetime.now().strftime('%Y%m%d_%H')}"  # One alert per hour?
            # Or dedup by tech daily? "gps_gap:tech:date"?
            # If gap persists, we don't want spam. One open issue is enough.
            # If we deduce by key "gps_gap:{tech_id}", it wont persist if resolved.

            issue_key = f"gps_gap:{tech_id}"

            cursor.execute(
                """
                INSERT INTO issues (
                    issue_key, issue_type, severity, title, description, context, status
                ) VALUES (%s, 'gps_gap', 'medium', %s, %s, %s, 'open')
                ON CONFLICT (issue_key) DO UPDATE 
                SET updated_at = NOW(), description = EXCLUDED.description
                WHERE issues.status = 'open'
            """,
                (
                    issue_key,
                    f"GPS Signal Lost (Tech {tech_id})",
                    f"No GPS signal for {int(gap_minutes)} mins. Last seen: {last_seen}",
                    json.dumps(
                        {
                            "tech_id": tech_id,
                            "gap_minutes": int(gap_minutes),
                            "last_seen": last_seen,
                            "last_lat": last_pos["latitude"] if last_pos else None,
                            "last_lng": last_pos["longitude"] if last_pos else None,
                        }
                    ),
                ),
            )
            if cursor.rowcount > 0:
                print(f"   🚨 Gap Detected for Tech {tech_id}: {int(gap_minutes)} mins")
                issues_created += 1

    conn.commit()
    conn.close()
    print(f"✅ GPS Gap Check Complete. New Issues: {issues_created}")


if __name__ == "__main__":
    find_gps_gaps()
