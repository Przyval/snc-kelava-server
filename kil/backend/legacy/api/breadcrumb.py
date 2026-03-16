"""
Breadcrumb GPS Tracking API
==============================
High-frequency GPS trail capture from mobile app (like Gojek tracking).
Receives position pings every 1-5 minutes, stores trail, provides replay.

Meeting: "Kita mau ngenalin fitur Breadcrumb... kayak Gojek"
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

breadcrumb_bp = Blueprint("breadcrumb", __name__, url_prefix="/breadcrumb")

_TABLE_ENSURED = False


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS gps_breadcrumbs (
            id          BIGSERIAL PRIMARY KEY,
            technician_id INTEGER NOT NULL,
            latitude    NUMERIC(10,7) NOT NULL,
            longitude   NUMERIC(10,7) NOT NULL,
            accuracy    NUMERIC(8,2),
            speed       NUMERIC(6,2),
            bearing     NUMERIC(6,2),
            battery_pct SMALLINT,
            is_moving   BOOLEAN DEFAULT true,
            captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    # Index for trail queries
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_breadcrumb_tech_date
        ON gps_breadcrumbs (technician_id, captured_at DESC)
    """)
    # Daily summary cache
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS gps_daily_summary (
            id              BIGSERIAL PRIMARY KEY,
            technician_id   INTEGER NOT NULL,
            summary_date    DATE NOT NULL,
            total_points    INTEGER DEFAULT 0,
            total_distance_m NUMERIC(10,1) DEFAULT 0,
            active_minutes  INTEGER DEFAULT 0,
            idle_minutes    INTEGER DEFAULT 0,
            first_seen      TIMESTAMPTZ,
            last_seen       TIMESTAMPTZ,
            bbox_lat_min    NUMERIC(10,7),
            bbox_lat_max    NUMERIC(10,7),
            bbox_lng_min    NUMERIC(10,7),
            bbox_lng_max    NUMERIC(10,7),
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(technician_id, summary_date)
        )
    """)
    _TABLE_ENSURED = True


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Mobile: Single GPS Ping ──────────────────────────────────


@breadcrumb_bp.route("/ping", methods=["POST"])
@require_auth
def gps_ping():
    """
    Receive a single GPS position from mobile app.

    Body: {
        latitude: float,
        longitude: float,
        accuracy?: float (meters),
        speed?: float (m/s),
        bearing?: float (degrees),
        battery_pct?: int (0-100),
        is_moving?: bool,
        captured_at?: ISO timestamp (device time)
    }
    """
    _ensure_tables()
    user = g.current_user
    data = request.json or {}

    lat = data.get("latitude")
    lng = data.get("longitude")
    if lat is None or lng is None:
        return jsonify({"error": "latitude and longitude required"}), 400

    # Use p_user_id if available, otherwise user.id
    tech_id = user.p_user_id or user.id
    captured = data.get("captured_at", datetime.now().isoformat())

    execute_kelava_query(
        """
        INSERT INTO gps_breadcrumbs
            (technician_id, latitude, longitude, accuracy, speed,
             bearing, battery_pct, is_moving, captured_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            tech_id, lat, lng,
            data.get("accuracy"),
            data.get("speed"),
            data.get("bearing"),
            data.get("battery_pct"),
            data.get("is_moving", True),
            captured,
        ),
    )

    return jsonify({"status": "ok"}), 201


# ── Mobile: Batch GPS Pings ──────────────────────────────────


@breadcrumb_bp.route("/ping-batch", methods=["POST"])
@require_auth
def gps_ping_batch():
    """
    Receive multiple GPS positions at once (offline sync).

    Body: {
        points: [
            { latitude, longitude, accuracy?, speed?, captured_at },
            ...
        ]
    }
    """
    _ensure_tables()
    user = g.current_user
    data = request.json or {}
    points = data.get("points", [])

    if not points:
        return jsonify({"error": "No points provided"}), 400
    if len(points) > 500:
        return jsonify({"error": "Max 500 points per batch"}), 400

    tech_id = user.p_user_id or user.id
    inserted = 0

    for pt in points:
        lat = pt.get("latitude")
        lng = pt.get("longitude")
        if lat is None or lng is None:
            continue

        execute_kelava_query(
            """
            INSERT INTO gps_breadcrumbs
                (technician_id, latitude, longitude, accuracy, speed,
                 bearing, battery_pct, is_moving, captured_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tech_id, lat, lng,
                pt.get("accuracy"),
                pt.get("speed"),
                pt.get("bearing"),
                pt.get("battery_pct"),
                pt.get("is_moving", True),
                pt.get("captured_at", datetime.now().isoformat()),
            ),
        )
        inserted += 1

    return jsonify({"status": "ok", "inserted": inserted}), 201


# ── Enterprise: Trail View (replay) ──────────────────────────


@breadcrumb_bp.route("/trail/<int:tech_id>", methods=["GET"])
@require_auth
def trail(tech_id: int):
    """
    Get GPS breadcrumb trail for a technician on a specific date.
    Returns ordered positions for route visualization/replay.

    Query params:
        date: YYYY-MM-DD (default: today)
        simplify: true (default) — reduce points for rendering
    """
    _ensure_tables()
    target_date = request.args.get("date", date.today().isoformat())
    simplify = request.args.get("simplify", "true").lower() == "true"

    # Get trail points
    rows = execute_kelava_query(
        """
        SELECT latitude, longitude, accuracy, speed, bearing,
               battery_pct, is_moving, captured_at
        FROM gps_breadcrumbs
        WHERE technician_id = %s AND captured_at::date = %s::date
        ORDER BY captured_at
        """,
        (tech_id, target_date),
    )

    points = [_fmt(r) for r in rows]

    # Optional simplification: keep every Nth point for performance
    if simplify and len(points) > 200:
        step = max(1, len(points) // 200)
        # Always keep first and last
        simplified = [points[0]]
        for i in range(step, len(points) - 1, step):
            simplified.append(points[i])
        simplified.append(points[-1])
        points = simplified

    # Also get visit check-in/out markers for the same day
    visit_markers = execute_kelava_query(
        """
        SELECT
            v.latitude AS lat_in, v.longitude AS lng_in, v.check_in,
            v.latitude_o AS lat_out, v.longitude_o AS lng_out, v.check_out,
            c.name AS customer_name, rp.status
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.id_user = %s AND rp.visit_date::date = %s
          AND v.latitude IS NOT NULL AND v.latitude != 0
        ORDER BY v.check_in
        """,
        (tech_id, target_date),
    )

    return jsonify({
        "tech_id": tech_id,
        "date": target_date,
        "trail": points,
        "total_raw_points": len(rows),
        "displayed_points": len(points),
        "visit_markers": [_fmt(v) for v in visit_markers],
    })


# ── Enterprise: Live Positions (all techs) ───────────────────


@breadcrumb_bp.route("/live", methods=["GET"])
@require_auth
def live_positions():
    """
    Get the most recent GPS position for each active technician (last 2 hours).
    """
    _ensure_tables()

    rows = execute_kelava_query(
        """
        SELECT DISTINCT ON (gb.technician_id)
            gb.technician_id,
            u.fullname AS tech_name,
            gb.latitude, gb.longitude,
            gb.speed, gb.bearing, gb.battery_pct, gb.is_moving,
            gb.captured_at,
            EXTRACT(EPOCH FROM (NOW() - gb.captured_at))::int AS seconds_ago
        FROM gps_breadcrumbs gb
        JOIN p_user u ON u.id = gb.technician_id
        WHERE gb.captured_at >= NOW() - INTERVAL '2 hours'
        ORDER BY gb.technician_id, gb.captured_at DESC
        """
    )

    return jsonify({
        "positions": [_fmt(r) for r in rows],
        "total": len(rows),
        "fetched_at": datetime.now().isoformat(),
    })


# ── Enterprise: Daily Summary ─────────────────────────────────


@breadcrumb_bp.route("/summary/<int:tech_id>", methods=["GET"])
@require_auth
def daily_summary(tech_id: int):
    """
    Get daily GPS summary for a technician (distance traveled, active time, etc.)

    Query params:
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
    """
    _ensure_tables()
    start = request.args.get("start_date", (date.today() - timedelta(days=7)).isoformat())
    end = request.args.get("end_date", date.today().isoformat())

    rows = execute_kelava_query(
        """
        SELECT
            captured_at::date AS summary_date,
            COUNT(*) AS total_points,
            MIN(captured_at) AS first_seen,
            MAX(captured_at) AS last_seen,
            EXTRACT(EPOCH FROM (MAX(captured_at) - MIN(captured_at))) / 60 AS span_minutes,
            COUNT(*) FILTER (WHERE is_moving = true) AS moving_points,
            COUNT(*) FILTER (WHERE is_moving = false) AS idle_points,
            AVG(speed) FILTER (WHERE speed > 0) AS avg_speed,
            MIN(latitude) AS lat_min, MAX(latitude) AS lat_max,
            MIN(longitude) AS lng_min, MAX(longitude) AS lng_max
        FROM gps_breadcrumbs
        WHERE technician_id = %s
          AND captured_at::date BETWEEN %s AND %s
        GROUP BY captured_at::date
        ORDER BY summary_date DESC
        """,
        (tech_id, start, end),
    )

    return jsonify({
        "tech_id": tech_id,
        "period": {"start": start, "end": end},
        "days": [_fmt(r) for r in rows],
        "total_days": len(rows),
    })


# ── Enterprise: Heatmap Data ─────────────────────────────────


@breadcrumb_bp.route("/heatmap", methods=["GET"])
@require_auth
def heatmap_data():
    """
    GPS density heatmap data for all technicians on a given date.
    Returns aggregated lat/lng grid for heatmap visualization.

    Query params: date (default: today)
    """
    _ensure_tables()
    target_date = request.args.get("date", date.today().isoformat())

    rows = execute_kelava_query(
        """
        SELECT
            ROUND(latitude::numeric, 3) AS lat_grid,
            ROUND(longitude::numeric, 3) AS lng_grid,
            COUNT(*) AS intensity,
            COUNT(DISTINCT technician_id) AS tech_count
        FROM gps_breadcrumbs
        WHERE captured_at::date = %s::date
        GROUP BY ROUND(latitude::numeric, 3), ROUND(longitude::numeric, 3)
        HAVING COUNT(*) >= 2
        ORDER BY intensity DESC
        LIMIT 500
        """,
        (target_date,),
    )

    return jsonify({
        "date": target_date,
        "grid": [_fmt(r) for r in rows],
        "total_cells": len(rows),
    })
