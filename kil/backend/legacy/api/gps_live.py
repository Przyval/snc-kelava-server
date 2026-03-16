"""
GPS Live Map API v2
====================
Real-time technician positions, route tracking, playback mode,
and enriched position data with KPI scores + visit progress.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

gps_live_bp = Blueprint("gps_live", __name__, url_prefix="/gps-live")


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Latest Positions (enriched with KPI + visit progress) ────


@gps_live_bp.route("/positions", methods=["GET"])
@require_auth
def latest_positions():
    """
    Get the most recent GPS position for each active technician.
    Enriched with today's visit progress and latest KPI grade.
    Query params: date (YYYY-MM-DD, default: today)
    """
    target_date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    # Try gps_positions table first (may not exist yet)
    try:
        rows = execute_kelava_query(
            """
            SELECT DISTINCT ON (gp.internal_id)
                gp.internal_id AS tech_id,
                u.fullname AS tech_name,
                gp.latitude AS lat,
                gp.longitude AS lng,
                gp.captured_at,
                EXTRACT(EPOCH FROM (NOW() - gp.captured_at))::int AS seconds_ago
            FROM gps_positions gp
            JOIN p_user u ON u.id = gp.internal_id
            WHERE gp.captured_at::date = %s::date
              AND gp.captured_at >= NOW() - INTERVAL '24 hours'
            ORDER BY gp.internal_id, gp.captured_at DESC
            """,
            (target_date,),
        )
    except Exception:
        rows = []

    # Supplement with check-in data for techs not in gps_positions
    visit_positions = execute_kelava_query(
        """
        SELECT DISTINCT ON (rp.id_user)
            rp.id_user AS tech_id,
            u.fullname AS tech_name,
            v.latitude AS lat,
            v.longitude AS lng,
            v.check_in AS captured_at,
            EXTRACT(EPOCH FROM (NOW() - v.check_in))::int AS seconds_ago,
            c.name AS current_customer,
            rp.status
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        JOIN p_user u ON u.id = rp.id_user
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.visit_date::date = %s
          AND v.latitude IS NOT NULL AND v.latitude != 0
          AND v.longitude IS NOT NULL AND v.longitude != 0
        ORDER BY rp.id_user, v.check_in DESC
        """,
        (target_date,),
    )

    # Merge: GPS positions take priority
    seen_techs = {r["tech_id"] for r in rows}
    for vp in visit_positions:
        if vp["tech_id"] not in seen_techs:
            rows.append(vp)
            seen_techs.add(vp["tech_id"])

    # Enrich with visit progress per tech for this date
    visit_progress = execute_kelava_query(
        """
        SELECT
            rp.id_user AS tech_id,
            COUNT(*) AS planned,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            COUNT(*) FILTER (WHERE rp.status = 'Berjalan') AS in_progress
        FROM t_road_plan rp
        WHERE rp.visit_date::date = %s
          AND COALESCE(rp.is_cancel, false) = false
        GROUP BY rp.id_user
        """,
        (target_date,),
    )
    progress_map = {r["tech_id"]: r for r in visit_progress}

    # Enrich with latest rapor grade (try daily_kpi_rapor if exists)
    rapor_map = {}
    try:
        rapors = execute_kelava_query(
            """
            SELECT DISTINCT ON (technician_id)
                technician_id AS tech_id,
                overall_score,
                grade,
                rapor_date
            FROM daily_kpi_rapor
            WHERE rapor_date >= CURRENT_DATE - 7
            ORDER BY technician_id, rapor_date DESC
            """,
        )
        rapor_map = {r["tech_id"]: r for r in rapors}
    except Exception:
        pass

    # Build enriched response
    enriched = []
    for r in rows:
        item = _fmt(r)
        tid = r["tech_id"]

        # Visit progress
        prog = progress_map.get(tid, {})
        item["visits_planned"] = prog.get("planned", 0) or 0
        item["visits_completed"] = prog.get("completed", 0) or 0
        item["visits_in_progress"] = prog.get("in_progress", 0) or 0

        # Rapor data
        rap = rapor_map.get(tid)
        if rap:
            item["kpi_score"] = float(rap["overall_score"]) if rap["overall_score"] else None
            item["kpi_grade"] = rap["grade"]
        else:
            item["kpi_score"] = None
            item["kpi_grade"] = None

        # Photo URL (convention: /enterprise/static/img/staff/{tech_id}.jpg)
        item["photo_url"] = f"/enterprise/static/img/staff/{tid}.jpg"

        enriched.append(item)

    return jsonify({
        "positions": enriched,
        "total": len(enriched),
        "date": target_date,
        "fetched_at": datetime.now().isoformat(),
    })


# ── Technician Trail (for playback) ─────────────────────────


@gps_live_bp.route("/trail/<int:tech_id>", methods=["GET"])
@require_auth
def technician_trail(tech_id: int):
    """
    Get GPS trail for a specific technician on a given date.
    Returns ordered positions for route visualization / playback.
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    # GPS breadcrumbs (high-frequency trail, table may not exist)
    gps_trail = []
    try:
        gps_trail = execute_kelava_query(
            """
            SELECT latitude AS lat, longitude AS lng, captured_at,
                   speed, bearing, is_moving
            FROM gps_breadcrumbs
            WHERE technician_id = %s
              AND captured_at::date = %s::date
            ORDER BY captured_at
            """,
            (tech_id, date),
        )
    except Exception:
        pass

    # Fallback: gps_positions table
    if not gps_trail:
        try:
            gps_trail = execute_kelava_query(
                """
                SELECT latitude AS lat, longitude AS lng, captured_at
                FROM gps_positions
                WHERE internal_id = %s
                  AND captured_at::date = %s::date
                ORDER BY captured_at
                """,
                (tech_id, date),
            )
        except Exception:
            pass

    # Visit locations (check-in/out points) — always available
    visit_points = execute_kelava_query(
        """
        SELECT
            v.latitude AS lat_in, v.longitude AS lng_in, v.check_in,
            v.latitude_o AS lat_out, v.longitude_o AS lng_out, v.check_out,
            c.name AS customer_name, c.address,
            rp.status,
            CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                 THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in))::int / 60
                 ELSE NULL END AS duration_min
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.id_user = %s AND rp.visit_date::date = %s
          AND v.latitude IS NOT NULL AND v.latitude != 0
        ORDER BY v.check_in
        """,
        (tech_id, date),
    )

    # If no GPS trail, synthesize one from visit check-in/out points
    if not gps_trail and visit_points:
        synthetic = []
        for vp in visit_points:
            if vp["lat_in"] and vp["lng_in"] and vp["check_in"]:
                synthetic.append({
                    "lat": vp["lat_in"], "lng": vp["lng_in"],
                    "captured_at": vp["check_in"],
                })
            if vp["lat_out"] and vp["lng_out"] and vp["check_out"]:
                synthetic.append({
                    "lat": vp["lat_out"], "lng": vp["lng_out"],
                    "captured_at": vp["check_out"],
                })
        gps_trail = synthetic

    return jsonify({
        "tech_id": tech_id,
        "date": date,
        "gps_trail": [_fmt(g) for g in gps_trail],
        "visit_points": [_fmt(v) for v in visit_points],
        "trail_points": len(gps_trail),
    })


# ── Today's Activity Summary ────────────────────────────────


@gps_live_bp.route("/activity", methods=["GET"])
@require_auth
def activity_summary():
    """
    Field activity summary for a date.
    Query params: date (YYYY-MM-DD, default: today)
    """
    target_date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    # Active technicians on date
    active = execute_kelava_query_single(
        """
        SELECT
            COUNT(DISTINCT id_user) AS active_techs,
            COUNT(*) AS total_planned,
            COUNT(*) FILTER (WHERE status = 'Selesai') AS completed,
            COUNT(*) FILTER (WHERE status = 'Berjalan') AS in_progress,
            COUNT(*) FILTER (WHERE status NOT IN ('Selesai', 'Berjalan')) AS pending
        FROM t_road_plan
        WHERE visit_date::date = %s
          AND COALESCE(is_cancel, false) = false
        """,
        (target_date,),
    )

    # Techs with GPS data in last hour (table may not exist yet)
    try:
        gps_active = execute_kelava_query_single(
            """
            SELECT COUNT(DISTINCT internal_id) AS cnt
            FROM gps_positions
            WHERE captured_at >= NOW() - INTERVAL '1 hour'
            """
        )
    except Exception:
        gps_active = None

    # Customer locations visited on date (from visit check-in GPS)
    visited_locations = execute_kelava_query(
        """
        SELECT DISTINCT ON (rp.id_customer)
            v.latitude, v.longitude,
            c.name AS customer_name,
            rp.id_user, u.fullname AS tech_name
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        JOIN m_customer c ON c.id = rp.id_customer
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.visit_date::date = %s AND rp.status = 'Selesai'
          AND v.latitude IS NOT NULL AND v.latitude != 0
          AND v.longitude IS NOT NULL AND v.longitude != 0
        ORDER BY rp.id_customer, v.check_in DESC
        """,
        (target_date,),
    )

    return jsonify({
        "date": target_date,
        "active_technicians": (active["active_techs"] or 0) if active else 0,
        "gps_active_1h": (gps_active["cnt"] or 0) if gps_active else 0,
        "visits": {
            "total": (active["total_planned"] or 0) if active else 0,
            "completed": (active["completed"] or 0) if active else 0,
            "in_progress": (active["in_progress"] or 0) if active else 0,
            "pending": (active["pending"] or 0) if active else 0,
        },
        "visited_locations": [_fmt(v) for v in visited_locations],
    })


# ── Available Dates (for calendar picker) ────────────────────


@gps_live_bp.route("/available-dates", methods=["GET"])
@require_auth
def available_dates():
    """
    Return dates that have GPS/visit data, for the calendar picker.
    Query params: months (int, default: 3)
    """
    months = int(request.args.get("months", 3))

    rows = execute_kelava_query(
        """
        SELECT
            visit_date::date AS dt,
            COUNT(DISTINCT id_user) AS tech_count,
            COUNT(*) AS visit_count
        FROM t_road_plan
        WHERE visit_date::date >= CURRENT_DATE - (%s * 30)
          AND visit_date::date <= CURRENT_DATE
          AND COALESCE(is_cancel, false) = false
        GROUP BY visit_date::date
        ORDER BY dt DESC
        """,
        (months,),
    )

    return jsonify({
        "dates": [
            {
                "date": r["dt"].isoformat(),
                "tech_count": r["tech_count"],
                "visit_count": r["visit_count"],
            }
            for r in rows
        ],
    })
