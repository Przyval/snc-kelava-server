#!/usr/bin/env python3
"""
Late Checkout Rule
==================
Triggers on: gps.location_update
Logic:
1. Check if tech has an ACTIVE visit (checked_in, not checked_out)
2. Calculate distance between current GPS and Visit Location
3. If distance > 500m, raise 'late_checkout_detected'
"""

import json
import math
from datetime import datetime


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + math.cos(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) * math.sin(dlon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def get_active_visit(conn, tech_id: int):
    cursor = conn.cursor()

    # Logic: Last visit.started for this tech without subsequent visit.completed
    # We use events_norm which is populated by outbox consumer
    cursor.execute(
        """
        SELECT payload 
        FROM events_norm 
        WHERE event_type = 'visit.started'
          AND payload->>'tech_id' = %s
          AND occurred_at > CURRENT_DATE
        ORDER BY occurred_at DESC
        LIMIT 1
    """,
        (str(tech_id),),
    )

    row = cursor.fetchone()
    if not row:
        return None

    start_payload = row["payload"]
    if isinstance(start_payload, str):
        start_payload = json.loads(start_payload)

    visit_id = start_payload.get("visit_id")

    # Check if completed
    cursor.execute(
        """
        SELECT 1 
        FROM events_norm 
        WHERE event_type = 'visit.completed'
          AND payload->>'visit_id' = %s
    """,
        (str(visit_id),),
    )

    if cursor.fetchone():
        return None  # Already completed

    return start_payload


def create_issue(conn, context: dict):
    cursor = conn.cursor()

    issue_key = f"late_checkout:{context['visit_id']}"

    cursor.execute(
        """
        INSERT INTO issues (
            issue_key, issue_type, severity, title, description, context
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (issue_key) DO NOTHING
    """,
        (
            issue_key,
            "late_checkout",
            "high",
            f"Late Checkout Detected (Visit {context['visit_id']})",
            f"Technician left site ({context['dist_m']}m away) without checking out.",
            json.dumps(context),
        ),
    )
    conn.commit()  # COMMIT HERE
    return cursor.rowcount > 0


def evaluate_late_checkout(conn, event_payload: dict):
    tech_id = event_payload.get("tech_id")
    curr_lat = event_payload.get("lat")
    curr_lng = event_payload.get("lng")

    if not tech_id or curr_lat is None:
        return

    active_visit = get_active_visit(conn, tech_id)
    if not active_visit:
        return

    site_lat = active_visit.get("latitude") or active_visit.get("lat")
    site_lng = active_visit.get("longitude") or active_visit.get("lng")

    if not site_lat:
        return

    dist_km = haversine_km(
        float(curr_lat), float(curr_lng), float(site_lat), float(site_lng)
    )
    dist_m = dist_km * 1000

    if dist_m > 500:
        context = {
            "tech_id": tech_id,
            "visit_id": active_visit.get("visit_id"),
            "current_loc": {"lat": curr_lat, "lng": curr_lng},
            "site_loc": {"lat": site_lat, "lng": site_lng},
            "dist_m": int(dist_m),
            "detected_at": datetime.now().isoformat(),
        }

        if create_issue(conn, context):
            print(f"  🚨 Issue created: Late Checkout (Dist: {int(dist_m)}m)")
