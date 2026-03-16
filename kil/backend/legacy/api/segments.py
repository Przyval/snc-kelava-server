"""
Technician Segments API
========================
Manages technician role segments (Mobile/Station/Support/Supervisor)
and segment-specific KPI rules.

Meeting notes:
- Mobile: keliling, visit-per-day focused, toleransi 30 menit klien ke-2+
- Station: satu tempat, zero tolerance keterlambatan, shift pagi/sore
- Support: 40-42 jam efektif/minggu, harus sering ketemu klien
- Supervisor: install klien baru, pendampingan audit, sidak, supervisi
"""

from datetime import datetime

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

segments_bp = Blueprint("segments", __name__, url_prefix="/segments")

VALID_SEGMENTS = ("MOBILE", "STATION", "SUPPORT", "SUPERVISOR")
VALID_SHIFTS = ("MORNING", "EVENING")


def _fmt(row):
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _auth_user_id():
    user = getattr(g, "user", None)
    return str(user.id) if user else None


# ── Segment CRUD ────────────────────────────────────────────


@segments_bp.route("", methods=["GET"])
@require_auth
def list_segments():
    """List all technicians with their segments and KPI summary."""
    segment_filter = request.args.get("segment")
    uid = _auth_user_id()

    where = "1=1"
    params = []

    if segment_filter and segment_filter.upper() in VALID_SEGMENTS:
        where = "ts.segment = %s"
        params = [segment_filter.upper()]

    rows = execute_kelava_query(
        f"""
        SELECT
            ts.id,
            ts.technician_id,
            u.fullname as name,
            u.email,
            ts.segment,
            ts.shift_type,
            ts.weekly_hours_target,
            ts.is_active,
            ts.notes,
            ts.created_at
        FROM technician_segments ts
        JOIN p_user u ON u.id = ts.technician_id
        WHERE {where}
        ORDER BY ts.segment, u.fullname
        """,
        tuple(params) if params else None,
        user_id=uid,
    )

    # Group by segment for summary
    by_segment = {}
    for row in rows:
        seg = row["segment"]
        if seg not in by_segment:
            by_segment[seg] = 0
        by_segment[seg] += 1

    return jsonify({
        "technicians": [_fmt(r) for r in rows],
        "summary": by_segment,
        "total": len(rows),
        "generated_at": datetime.now().isoformat(),
    })


@segments_bp.route("", methods=["POST"])
@require_auth
def assign_segment():
    """
    Assign or update a technician's segment.

    Body: {
        technician_id: int,
        segment: "MOBILE"|"STATION"|"SUPPORT"|"SUPERVISOR",
        shift_type?: "MORNING"|"EVENING",
        weekly_hours_target?: float,
        notes?: string
    }
    """
    data = request.json or {}
    uid = _auth_user_id()

    tech_id = data.get("technician_id")
    segment = (data.get("segment") or "").upper()
    shift_type = (data.get("shift_type") or "MORNING").upper()
    hours = data.get("weekly_hours_target", 40.0)
    notes = data.get("notes", "")

    if not tech_id:
        return jsonify({"error": "technician_id is required"}), 400
    if segment not in VALID_SEGMENTS:
        return jsonify({"error": f"segment must be one of: {', '.join(VALID_SEGMENTS)}"}), 400
    if shift_type not in VALID_SHIFTS:
        return jsonify({"error": f"shift_type must be one of: {', '.join(VALID_SHIFTS)}"}), 400

    # Verify technician exists
    tech = execute_kelava_query_single(
        "SELECT id, fullname FROM p_user WHERE id = %s",
        (tech_id,), user_id=uid,
    )
    if not tech:
        return jsonify({"error": "Technician not found"}), 404

    # Upsert segment
    result = execute_kelava_query_single(
        """
        INSERT INTO technician_segments (technician_id, segment, shift_type, weekly_hours_target, notes)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (technician_id) DO UPDATE SET
            segment = EXCLUDED.segment,
            shift_type = EXCLUDED.shift_type,
            weekly_hours_target = EXCLUDED.weekly_hours_target,
            notes = EXCLUDED.notes,
            updated_at = NOW()
        RETURNING *
        """,
        (tech_id, segment, shift_type, hours, notes),
        user_id=uid,
    )

    return jsonify({
        "message": f"{tech['fullname']} assigned to {segment}",
        "segment": _fmt(result) if result else {},
    }), 201


@segments_bp.route("/batch", methods=["POST"])
@require_auth
def batch_assign_segments():
    """
    Batch assign segments to multiple technicians.

    Body: {
        assignments: [
            { technician_id: int, segment: str, shift_type?: str },
            ...
        ]
    }
    """
    data = request.json or {}
    uid = _auth_user_id()
    assignments = data.get("assignments", [])

    if not assignments:
        return jsonify({"error": "assignments array is required"}), 400

    results = []
    errors = []

    for a in assignments:
        tech_id = a.get("technician_id")
        segment = (a.get("segment") or "").upper()

        if not tech_id or segment not in VALID_SEGMENTS:
            errors.append({"technician_id": tech_id, "error": "invalid data"})
            continue

        shift_type = (a.get("shift_type") or "MORNING").upper()
        hours = a.get("weekly_hours_target", 40.0)

        execute_kelava_query(
            """
            INSERT INTO technician_segments (technician_id, segment, shift_type, weekly_hours_target)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (technician_id) DO UPDATE SET
                segment = EXCLUDED.segment,
                shift_type = EXCLUDED.shift_type,
                weekly_hours_target = EXCLUDED.weekly_hours_target,
                updated_at = NOW()
            """,
            (tech_id, segment, shift_type, hours),
            user_id=uid,
        )
        results.append({"technician_id": tech_id, "segment": segment})

    return jsonify({
        "message": f"Assigned {len(results)} technicians",
        "assigned": results,
        "errors": errors,
    })


@segments_bp.route("/<int:tech_id>", methods=["GET"])
@require_auth
def get_technician_segment(tech_id: int):
    """Get segment info and KPI rules for a specific technician."""
    uid = _auth_user_id()

    segment = execute_kelava_query_single(
        """
        SELECT
            ts.*,
            u.fullname as name,
            u.email
        FROM technician_segments ts
        JOIN p_user u ON u.id = ts.technician_id
        WHERE ts.technician_id = %s
        """,
        (tech_id,), user_id=uid,
    )

    if not segment:
        return jsonify({"error": "Segment not assigned for this technician"}), 404

    # Get KPI rules for this segment
    kpi_rules = execute_kelava_query(
        """
        SELECT metric_name, metric_label, weight, threshold_green,
               threshold_yellow, threshold_red, unit, description
        FROM segment_kpi_rules
        WHERE segment = %s
        ORDER BY weight DESC
        """,
        (segment["segment"],), user_id=uid,
    )

    return jsonify({
        "technician": _fmt(segment),
        "kpi_rules": [_fmt(r) for r in kpi_rules],
        "generated_at": datetime.now().isoformat(),
    })


# ── KPI Rules ───────────────────────────────────────────────


@segments_bp.route("/kpi-rules", methods=["GET"])
@require_auth
def list_kpi_rules():
    """Get all KPI rules grouped by segment."""
    uid = _auth_user_id()
    segment_filter = request.args.get("segment")

    where = "1=1"
    params = []
    if segment_filter:
        where = "segment = %s"
        params = [segment_filter.upper()]

    rules = execute_kelava_query(
        f"""
        SELECT * FROM segment_kpi_rules
        WHERE {where}
        ORDER BY segment, weight DESC
        """,
        tuple(params) if params else None,
        user_id=uid,
    )

    # Group by segment
    grouped = {}
    for r in rules:
        seg = r["segment"]
        if seg not in grouped:
            grouped[seg] = []
        grouped[seg].append(_fmt(r))

    return jsonify({
        "kpi_rules": grouped,
        "generated_at": datetime.now().isoformat(),
    })


# ── Segment-aware Leaderboard ───────────────────────────────


@segments_bp.route("/leaderboard", methods=["GET"])
@require_auth
def segment_leaderboard():
    """
    Leaderboard split by segment.
    Each segment is scored using its own KPI weights.

    Query params:
        segment: Filter to one segment
        days: Period in days (default: 30)
    """
    uid = _auth_user_id()
    segment_filter = request.args.get("segment")
    days = int(request.args.get("days", 30))

    where_seg = ""
    params = [days]
    if segment_filter and segment_filter.upper() in VALID_SEGMENTS:
        where_seg = "AND ts.segment = %s"
        params.append(segment_filter.upper())

    rows = execute_kelava_query(
        f"""
        WITH tech_metrics AS (
            SELECT
                rp.id_user,
                COUNT(*) as total_planned,
                COUNT(*) FILTER (WHERE rp.status = 'Selesai') as total_completed,
                COUNT(DISTINCT rp.visit_date::date) as active_days,
                COUNT(v.id) as total_visits,
                ROUND(AVG(
                    CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60
                    END
                )::numeric, 1) as avg_duration_min
            FROM t_road_plan rp
            LEFT JOIN t_visit v ON v.id_road_plan = rp.id
            WHERE rp.visit_date::date >= CURRENT_DATE - make_interval(days => %s)
              AND COALESCE(rp.is_cancel, false) = false
            GROUP BY rp.id_user
        )
        SELECT
            u.id as technician_id,
            u.fullname as name,
            u.email,
            COALESCE(ts.segment, 'UNASSIGNED') as segment,
            ts.shift_type,
            COALESCE(tm.total_planned, 0) as total_planned,
            COALESCE(tm.total_completed, 0) as total_completed,
            COALESCE(tm.total_visits, 0) as total_visits,
            COALESCE(tm.active_days, 0) as active_days,
            COALESCE(tm.avg_duration_min, 0) as avg_duration_min,
            CASE WHEN COALESCE(tm.active_days, 0) > 0
                 THEN ROUND(COALESCE(tm.total_visits, 0)::numeric / tm.active_days, 1)
                 ELSE 0
            END as visits_per_day,
            CASE WHEN COALESCE(tm.total_planned, 0) > 0
                 THEN ROUND(tm.total_completed::numeric / tm.total_planned * 100, 1)
                 ELSE 0
            END as completion_rate
        FROM p_user u
        LEFT JOIN technician_segments ts ON ts.technician_id = u.id
        LEFT JOIN tech_metrics tm ON tm.id_user = u.id
        WHERE (COALESCE(tm.total_planned, 0) > 0 OR COALESCE(tm.total_visits, 0) > 0)
          {where_seg}
        ORDER BY ts.segment, COALESCE(tm.total_visits, 0) DESC
        """,
        tuple(params),
        user_id=uid,
    )

    # Group by segment
    grouped = {}
    for r in rows:
        seg = r["segment"]
        if seg not in grouped:
            grouped[seg] = []
        grouped[seg].append(_fmt(r))

    return jsonify({
        "period_days": days,
        "leaderboard": grouped,
        "total_technicians": len(rows),
        "generated_at": datetime.now().isoformat(),
    })


@segments_bp.route("/kpi-rules/<int:rule_id>", methods=["PATCH"])
@require_auth
@require_role("admin", "koordinator")
def update_kpi_rule(rule_id: int):
    """
    Update KPI rule thresholds (green/yellow/red).

    Body: {
        threshold_green?: float,
        threshold_yellow?: float,
        threshold_red?: float,
        weight?: float,
        description?: string
    }
    """
    uid = _auth_user_id()
    data = request.json or {}

    # Verify rule exists
    rule = execute_kelava_query_single(
        "SELECT * FROM segment_kpi_rules WHERE id = %s",
        (rule_id,), user_id=uid,
    )
    if not rule:
        return jsonify({"error": "KPI rule not found"}), 404

    # Build SET clause
    updates = []
    params = []
    for field in ("threshold_green", "threshold_yellow", "threshold_red", "weight", "description"):
        if field in data:
            updates.append(f"{field} = %s")
            params.append(data[field])

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    updates.append("updated_at = NOW()")
    params.append(rule_id)

    result = execute_kelava_query_single(
        f"UPDATE segment_kpi_rules SET {', '.join(updates)} WHERE id = %s RETURNING *",
        tuple(params),
        user_id=uid,
    )

    return jsonify({
        "message": f"KPI rule '{rule['metric_label']}' updated",
        "rule": _fmt(result) if result else {},
    })


@segments_bp.route("/unassigned", methods=["GET"])
@require_auth
def unassigned_technicians():
    """List technicians who haven't been assigned to any segment yet."""
    uid = _auth_user_id()

    rows = execute_kelava_query(
        """
        SELECT u.id, u.fullname as name, u.email
        FROM p_user u
        WHERE COALESCE(u.is_deleted, false) = false
          AND u.id NOT IN (SELECT technician_id FROM technician_segments)
        ORDER BY u.fullname
        """,
        user_id=uid,
    )

    return jsonify({
        "unassigned": [_fmt(r) for r in rows],
        "count": len(rows),
        "generated_at": datetime.now().isoformat(),
    })
