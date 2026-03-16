"""
Punctuality Tracking API
=========================
Tracks technician lateness by comparing scheduled vs actual check-in times.

Rules from meeting:
- Station: ZERO tolerance (nggak boleh telat semenit pun)
- Mobile klien pertama: ZERO tolerance
- Mobile klien ke-2+: 30 minute tolerance
- Jadwal dari template operasional (data setahun)
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

punctuality_bp = Blueprint("punctuality", __name__, url_prefix="/punctuality")


def _fmt(row):
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _auth_user_id():
    user = getattr(g, "user", None)
    return str(user.id) if user else None


# ── Daily Punctuality Report ────────────────────────────────


@punctuality_bp.route("/daily", methods=["GET"])
@require_auth
def daily_punctuality():
    """
    Get punctuality report for a specific date.
    Shows all technicians with their scheduled vs actual check-in.

    Query params:
        date: YYYY-MM-DD (default: today)
        segment: Filter by segment
        late_only: true to show only late check-ins
    """
    uid = _auth_user_id()
    target_date = request.args.get("date", date.today().isoformat())
    segment_filter = request.args.get("segment")
    late_only = request.args.get("late_only", "false").lower() == "true"

    where_extra = ""
    params = [target_date]

    if segment_filter:
        where_extra += " AND ts.segment = %s"
        params.append(segment_filter.upper())

    if late_only:
        where_extra += " AND pr.is_late = true"

    # Get punctuality records joined with live data
    rows = execute_kelava_query(
        f"""
        SELECT
            pr.id,
            pr.technician_id,
            u.fullname as name,
            pr.visit_date,
            pr.customer_id,
            c.name as customer_name,
            pr.visit_sequence,
            pr.scheduled_time,
            pr.actual_checkin_time,
            pr.delta_minutes,
            pr.tolerance_minutes,
            pr.is_late,
            COALESCE(pr.segment, ts.segment, 'UNASSIGNED') as segment
        FROM punctuality_records pr
        JOIN p_user u ON u.id = pr.technician_id
        LEFT JOIN m_customer c ON c.id = pr.customer_id
        LEFT JOIN technician_segments ts ON ts.technician_id = pr.technician_id
        WHERE pr.visit_date::date = %s
          {where_extra}
        ORDER BY pr.is_late DESC, ABS(pr.delta_minutes) DESC
        """,
        tuple(params),
        user_id=uid,
    )

    # If no pre-computed records, compute from live data
    if not rows:
        rows = _compute_punctuality_live(target_date, segment_filter, uid)

    total = len(rows)
    late_count = sum(1 for r in rows if r.get("is_late"))

    formatted_records = [_fmt(r) for r in rows] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else rows

    # CSV export support
    if request.args.get("format") == "csv":
        from kil.backend.legacy.api.export_utils import rows_to_csv_response
        return rows_to_csv_response(
            formatted_records,
            f"ketepatan_kerja_{target_date}.csv",
            columns=["name", "segment", "customer_name", "visit_sequence",
                     "scheduled_time", "actual_checkin_time", "delta_minutes",
                     "tolerance_minutes", "is_late"],
        )

    return jsonify({
        "date": target_date,
        "records": formatted_records,
        "summary": {
            "total_checkins": total,
            "on_time": total - late_count,
            "late": late_count,
            "on_time_rate": round((total - late_count) / total * 100, 1) if total > 0 else 100.0,
        },
        "generated_at": datetime.now().isoformat(),
    })


def _compute_punctuality_live(target_date, segment_filter, uid):
    """Compute punctuality from live visit data + schedule templates."""
    where_seg = ""
    params = [target_date, target_date]

    if segment_filter:
        where_seg = "AND ts.segment = %s"
        params.append(segment_filter.upper())

    # Get visits with their sequence (ordered by check-in time per technician)
    visits = execute_kelava_query(
        f"""
        WITH daily_visits AS (
            SELECT
                rp.id_user as technician_id,
                rp.id_customer as customer_id,
                rp.id as road_plan_id,
                v.check_in,
                v.check_in::time as checkin_time,
                ROW_NUMBER() OVER (
                    PARTITION BY rp.id_user
                    ORDER BY v.check_in
                ) as visit_sequence
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE v.realization_date = %s
              AND v.check_in IS NOT NULL
        )
        SELECT
            dv.technician_id,
            u.fullname as name,
            dv.customer_id,
            c.name as customer_name,
            dv.road_plan_id,
            dv.visit_sequence,
            dv.checkin_time as actual_checkin_time,
            st.scheduled_time,
            COALESCE(ts.segment, 'UNASSIGNED') as segment,
            -- Calculate delta
            CASE WHEN st.scheduled_time IS NOT NULL
                THEN EXTRACT(EPOCH FROM (dv.checkin_time - st.scheduled_time)) / 60
                ELSE NULL
            END as delta_minutes,
            -- Tolerance rules
            CASE
                WHEN COALESCE(ts.segment, 'MOBILE') = 'STATION' THEN 0
                WHEN dv.visit_sequence = 1 THEN 0
                ELSE 30
            END as tolerance_minutes
        FROM daily_visits dv
        JOIN p_user u ON u.id = dv.technician_id
        LEFT JOIN m_customer c ON c.id = dv.customer_id
        LEFT JOIN technician_segments ts ON ts.technician_id = dv.technician_id
        LEFT JOIN schedule_templates st ON st.customer_id = dv.customer_id
            AND st.technician_id = dv.technician_id
            AND st.day_of_week = EXTRACT(DOW FROM %s::date)
            AND st.is_active = true
        {where_seg}
        ORDER BY dv.technician_id, dv.visit_sequence
        """,
        tuple(params),
        user_id=uid,
    )

    results = []
    for v in visits:
        delta = v.get("delta_minutes")
        tolerance = v.get("tolerance_minutes", 0)
        is_late = delta is not None and delta > tolerance

        results.append({
            "technician_id": v["technician_id"],
            "name": v["name"],
            "customer_id": v["customer_id"],
            "customer_name": v["customer_name"],
            "visit_sequence": v["visit_sequence"],
            "scheduled_time": str(v["scheduled_time"]) if v.get("scheduled_time") else None,
            "actual_checkin_time": str(v["actual_checkin_time"]) if v.get("actual_checkin_time") else None,
            "delta_minutes": round(delta, 1) if delta is not None else None,
            "tolerance_minutes": tolerance,
            "is_late": is_late,
            "segment": v["segment"],
        })

    return results


# ── Technician Punctuality History ──────────────────────────


@punctuality_bp.route("/technician/<int:tech_id>", methods=["GET"])
@require_auth
def technician_punctuality(tech_id: int):
    """
    Punctuality history for a specific technician.
    Shows calendar of on-time vs late days.

    Query params:
        start_date, end_date: Date range (default: last 30 days)
    """
    uid = _auth_user_id()
    end_date = request.args.get("end_date", date.today().isoformat())
    start_date = request.args.get(
        "start_date", (date.today() - timedelta(days=30)).isoformat()
    )

    # Get daily first-check-in per day
    rows = execute_kelava_query(
        """
        WITH daily_first AS (
            SELECT
                v.realization_date as visit_date,
                MIN(v.check_in) as first_checkin,
                MIN(v.check_in)::time as first_checkin_time,
                COUNT(*) as visits_today
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE rp.id_user = %s
              AND v.realization_date BETWEEN %s AND %s
              AND v.check_in IS NOT NULL
            GROUP BY v.realization_date
        )
        SELECT
            df.visit_date,
            df.first_checkin_time,
            df.visits_today,
            st.scheduled_time as expected_time,
            CASE WHEN st.scheduled_time IS NOT NULL
                THEN ROUND(EXTRACT(EPOCH FROM (df.first_checkin_time - st.scheduled_time)) / 60)
                ELSE NULL
            END as delta_minutes,
            COALESCE(ts.segment, 'UNASSIGNED') as segment
        FROM daily_first df
        LEFT JOIN technician_segments ts ON ts.technician_id = %s
        LEFT JOIN LATERAL (
            SELECT st2.scheduled_time
            FROM schedule_templates st2
            WHERE st2.technician_id = %s
              AND st2.day_of_week = EXTRACT(DOW FROM df.visit_date)
              AND st2.is_active = true
            ORDER BY st2.scheduled_time
            LIMIT 1
        ) st ON true
        ORDER BY df.visit_date DESC
        """,
        (tech_id, start_date, end_date, tech_id, tech_id),
        user_id=uid,
    )

    calendar = []
    late_count = 0
    for r in rows:
        delta = r.get("delta_minutes")
        segment = r.get("segment", "MOBILE")
        tolerance = 0 if segment == "STATION" else 0  # first visit = 0 tolerance
        is_late = delta is not None and delta > tolerance

        if is_late:
            late_count += 1

        calendar.append({
            "date": r["visit_date"].isoformat() if hasattr(r["visit_date"], "isoformat") else str(r["visit_date"]),
            "first_checkin": str(r["first_checkin_time"]) if r.get("first_checkin_time") else None,
            "expected_time": str(r["expected_time"]) if r.get("expected_time") else None,
            "delta_minutes": int(delta) if delta is not None else None,
            "is_late": is_late,
            "visits_today": r["visits_today"],
        })

    total = len(calendar)

    return jsonify({
        "technician_id": tech_id,
        "period": {"start_date": start_date, "end_date": end_date},
        "calendar": calendar,
        "summary": {
            "total_days": total,
            "on_time_days": total - late_count,
            "late_days": late_count,
            "on_time_rate": round((total - late_count) / total * 100, 1) if total > 0 else 100.0,
        },
        "generated_at": datetime.now().isoformat(),
    })


# ── Lateness Ranking (For morning meeting) ──────────────────


@punctuality_bp.route("/ranking", methods=["GET"])
@require_auth
def lateness_ranking():
    """
    Rank technicians by lateness frequency.
    Perfect for daily morning meeting: "Kemarin siapa yang telat?"

    Query params:
        days: Look-back period (default: 7)
        segment: Filter by segment
    """
    uid = _auth_user_id()
    days = int(request.args.get("days", 7))
    segment_filter = request.args.get("segment")

    where_seg = ""
    params = [days]
    if segment_filter:
        where_seg = "AND ts.segment = %s"
        params.append(segment_filter.upper())

    rows = execute_kelava_query(
        f"""
        WITH daily_first AS (
            SELECT
                rp.id_user as technician_id,
                v.realization_date,
                MIN(v.check_in)::time as first_checkin
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE v.realization_date >= CURRENT_DATE - make_interval(days => %s)
              AND v.check_in IS NOT NULL
            GROUP BY rp.id_user, v.realization_date
        ),
        with_schedule AS (
            SELECT
                df.technician_id,
                df.realization_date,
                df.first_checkin,
                st.scheduled_time,
                CASE WHEN st.scheduled_time IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (df.first_checkin - st.scheduled_time)) / 60
                    ELSE NULL
                END as delta_minutes,
                CASE
                    WHEN COALESCE(ts.segment, 'MOBILE') = 'STATION' THEN 0
                    ELSE 0  -- first visit always zero tolerance
                END as tolerance
            FROM daily_first df
            LEFT JOIN technician_segments ts ON ts.technician_id = df.technician_id
            LEFT JOIN LATERAL (
                SELECT st2.scheduled_time
                FROM schedule_templates st2
                WHERE st2.technician_id = df.technician_id
                  AND st2.day_of_week = EXTRACT(DOW FROM df.realization_date)
                  AND st2.is_active = true
                ORDER BY st2.scheduled_time
                LIMIT 1
            ) st ON true
        )
        SELECT
            ws.technician_id,
            u.fullname as name,
            COALESCE(ts.segment, 'UNASSIGNED') as segment,
            COUNT(*) as total_days,
            COUNT(*) FILTER (
                WHERE ws.delta_minutes IS NOT NULL AND ws.delta_minutes > ws.tolerance
            ) as late_days,
            ROUND(AVG(ws.delta_minutes) FILTER (
                WHERE ws.delta_minutes IS NOT NULL AND ws.delta_minutes > 0
            )::numeric, 1) as avg_late_minutes,
            MAX(ws.delta_minutes) as max_late_minutes
        FROM with_schedule ws
        JOIN p_user u ON u.id = ws.technician_id
        LEFT JOIN technician_segments ts ON ts.technician_id = ws.technician_id
        WHERE 1=1 {where_seg}
        GROUP BY ws.technician_id, u.fullname, ts.segment
        HAVING COUNT(*) FILTER (
            WHERE ws.delta_minutes IS NOT NULL AND ws.delta_minutes > ws.tolerance
        ) > 0
        ORDER BY late_days DESC, avg_late_minutes DESC
        """,
        tuple(params),
        user_id=uid,
    )

    return jsonify({
        "period_days": days,
        "ranking": [_fmt(r) for r in rows],
        "total_late_technicians": len(rows),
        "generated_at": datetime.now().isoformat(),
    })


# ── Yesterday's Late Report (for morning standup) ──────────


@punctuality_bp.route("/yesterday", methods=["GET"])
@require_auth
def yesterday_report():
    """
    Quick report: Who was late yesterday?
    Designed for daily morning standup meeting.
    """
    uid = _auth_user_id()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    rows = execute_kelava_query(
        """
        WITH yesterday_visits AS (
            SELECT
                rp.id_user as technician_id,
                rp.id_customer as customer_id,
                v.check_in,
                v.check_in::time as checkin_time,
                ROW_NUMBER() OVER (
                    PARTITION BY rp.id_user
                    ORDER BY v.check_in
                ) as visit_seq
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE v.realization_date = %s
              AND v.check_in IS NOT NULL
        )
        SELECT
            yv.technician_id,
            u.fullname as name,
            yv.customer_id,
            c.name as customer_name,
            yv.visit_seq,
            yv.checkin_time,
            st.scheduled_time,
            COALESCE(ts.segment, 'UNASSIGNED') as segment,
            CASE WHEN st.scheduled_time IS NOT NULL
                THEN ROUND(EXTRACT(EPOCH FROM (yv.checkin_time - st.scheduled_time)) / 60)
                ELSE NULL
            END as delta_minutes,
            CASE
                WHEN COALESCE(ts.segment, 'MOBILE') = 'STATION' THEN 0
                WHEN yv.visit_seq = 1 THEN 0
                ELSE 30
            END as tolerance_minutes
        FROM yesterday_visits yv
        JOIN p_user u ON u.id = yv.technician_id
        LEFT JOIN m_customer c ON c.id = yv.customer_id
        LEFT JOIN technician_segments ts ON ts.technician_id = yv.technician_id
        LEFT JOIN schedule_templates st ON st.customer_id = yv.customer_id
            AND st.technician_id = yv.technician_id
            AND st.day_of_week = EXTRACT(DOW FROM %s::date)
            AND st.is_active = true
        ORDER BY yv.technician_id, yv.visit_seq
        """,
        (yesterday, yesterday),
        user_id=uid,
    )

    late_records = []
    for r in rows:
        delta = r.get("delta_minutes")
        tolerance = r.get("tolerance_minutes", 0)
        if delta is not None and delta > tolerance:
            late_records.append(_fmt(r))

    return jsonify({
        "date": yesterday,
        "late_records": late_records,
        "late_count": len(late_records),
        "total_checkins": len(rows),
        "message": f"{len(late_records)} teknisi terlambat kemarin"
        if late_records
        else "Semua teknisi tepat waktu kemarin!",
        "generated_at": datetime.now().isoformat(),
    })
