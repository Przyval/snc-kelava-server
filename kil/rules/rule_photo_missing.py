#!/usr/bin/env python3
"""
Photo Missing Rule (Postgres Version)
=====================================
"""

import json
from datetime import datetime


def get_foto_count(conn, road_plan_id: int) -> int:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT foto_count FROM foto_cache WHERE road_plan_id = %s", (road_plan_id,)
    )
    row = cursor.fetchone()
    # row is dict
    return row["foto_count"] if row else 0


def create_issue(
    conn,
    issue_type: str,
    issue_key: str,
    severity: str,
    title: str,
    description: str,
    context: dict,
    source_event_id: int = None,
) -> bool:
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO issues (
                issue_key, issue_type, severity, 
                title, description, context, source_event_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (issue_key) DO NOTHING
        """,
            (
                issue_key,
                issue_type,
                severity,
                title,
                description,
                json.dumps(context),
                source_event_id,
            ),
        )
        conn.commit()
        # In Postgres + Psycopg, rowcount check is reliable for insert
        return cursor.rowcount > 0
    except Exception as e:
        print(f"Error creating issue: {e}")
        return False


def evaluate_photo_missing(conn, event_payload: dict) -> bool:
    road_plan_id = event_payload.get("road_plan_id")

    if not road_plan_id:
        return False

    foto_count = get_foto_count(conn, int(road_plan_id))

    if foto_count > 0:
        return False

    issue_key = f"photo_missing:{road_plan_id}"
    title = f"Missing photo for visit (road_plan: {road_plan_id})"
    description = "Visit completed without any photo evidence attached."

    context = {
        "road_plan_id": road_plan_id,
        "visit_id": event_payload.get("visit_id"),
        "tech_id": event_payload.get("tech_id"),
        "customer_id": event_payload.get("customer_id"),
        "check_out": event_payload.get("check_out"),
        "detected_at": datetime.now().isoformat(),
    }

    created = create_issue(
        conn=conn,
        issue_type="photo_missing",
        issue_key=issue_key,
        severity="medium",
        title=title,
        description=description,
        context=context,
    )

    if created:
        print(f"  🚨 Issue created: {issue_key}")

    return created
