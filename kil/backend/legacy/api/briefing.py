"""
Daily Operational Briefing API
================================
Aggregated morning briefing: today's schedule, gaps, yesterday's issues,
pending complaints, expiring contracts.

Meeting: "setiap hari... pattern-nya kita kosongnya di mana...
admin cuma nambahin yang kosong"
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

briefing_bp = Blueprint("briefing", __name__, url_prefix="/briefing")


def _fmt(row):
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _auth_user_id():
    user = getattr(g, "user", None)
    return str(user.id) if user else None


@briefing_bp.route("/today", methods=["GET"])
@require_auth
def today_briefing():
    """
    Morning briefing: everything admin needs to know today.

    Returns:
    - today_schedule: who goes where today
    - schedule_gaps: unassigned time slots
    - yesterday_late: who was late yesterday
    - pending_issues: unresolved technician issues
    - expiring_contracts: contracts expiring within 14 days
    - pending_complaints: open/unresolved complaints
    - workforce_status: who's active, who's absent
    """
    uid = _auth_user_id()
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    dow = date.today().weekday()  # 0=Monday

    # 1. Today's Schedule
    schedule = execute_kelava_query(
        """
        SELECT
            rp.id_user as technician_id,
            u.fullname as name,
            COALESCE(ts.segment, 'UNASSIGNED') as segment,
            COUNT(*) as planned_visits,
            ARRAY_AGG(c.name ORDER BY rp.visit_date) as customer_names
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN technician_segments ts ON ts.technician_id = rp.id_user
        WHERE rp.visit_date::date = %s
          AND COALESCE(rp.is_cancel, false) = false
        GROUP BY rp.id_user, u.fullname, ts.segment
        ORDER BY u.fullname
        """,
        (today,),
        user_id=uid,
    )

    # 2. Schedule Gaps - technicians with templates but no road_plan today
    gaps = execute_kelava_query(
        """
        SELECT DISTINCT
            st.technician_id,
            u.fullname as name,
            c.name as customer_name,
            st.scheduled_time,
            COALESCE(ts.segment, 'UNASSIGNED') as segment
        FROM schedule_templates st
        JOIN p_user u ON u.id = st.technician_id
        JOIN m_customer c ON c.id = st.customer_id
        LEFT JOIN technician_segments ts ON ts.technician_id = st.technician_id
        WHERE st.day_of_week = %s
          AND st.is_active = true
          AND NOT EXISTS (
              SELECT 1 FROM t_road_plan rp
              WHERE rp.id_user = st.technician_id
                AND rp.id_customer = st.customer_id
                AND rp.visit_date::date = %s
                AND COALESCE(rp.is_cancel, false) = false
          )
        ORDER BY u.fullname, st.scheduled_time
        """,
        (dow, today),
        user_id=uid,
    )

    # 3. Yesterday's Late Records
    yesterday_late = execute_kelava_query(
        """
        WITH yesterday_visits AS (
            SELECT
                rp.id_user as technician_id,
                v.check_in::time as checkin_time,
                ROW_NUMBER() OVER (PARTITION BY rp.id_user ORDER BY v.check_in) as seq
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE v.realization_date = %s AND v.check_in IS NOT NULL
        )
        SELECT
            yv.technician_id,
            u.fullname as name,
            yv.checkin_time as actual_time,
            st.scheduled_time,
            ROUND(EXTRACT(EPOCH FROM (yv.checkin_time - st.scheduled_time)) / 60) as delta_minutes
        FROM yesterday_visits yv
        JOIN p_user u ON u.id = yv.technician_id
        LEFT JOIN LATERAL (
            SELECT st2.scheduled_time FROM schedule_templates st2
            WHERE st2.technician_id = yv.technician_id
              AND st2.day_of_week = EXTRACT(DOW FROM %s::date)
              AND st2.is_active = true
            ORDER BY st2.scheduled_time LIMIT 1
        ) st ON true
        WHERE yv.seq = 1
          AND st.scheduled_time IS NOT NULL
          AND EXTRACT(EPOCH FROM (yv.checkin_time - st.scheduled_time)) / 60 > 0
        ORDER BY delta_minutes DESC
        """,
        (yesterday, yesterday),
        user_id=uid,
    )

    # 4. Pending Issues (unresolved technician issues)
    pending_issues = execute_kelava_query(
        """
        SELECT ti.id, ti.technician_id, u.fullname as name, ti.issue_type,
               ti.severity, ti.status, ti.context, ti.created_at
        FROM technician_issues ti
        JOIN p_user u ON u.id = ti.technician_id
        WHERE ti.status NOT IN ('resolved', 'dismissed')
        ORDER BY
            CASE ti.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
            ti.created_at DESC
        LIMIT 10
        """,
        user_id=uid,
    )

    # 5. Expiring Contracts (14 days)
    try:
        expiring = execute_kelava_query(
            """
            SELECT
                ck.id,
                c.name as customer_name,
                ck.end_date as end_date,
                ck.end_date::date - CURRENT_DATE as days_remaining,
                ck.status
            FROM m_customer_kontrak ck
            JOIN m_customer c ON c.id = ck.id_customer
            WHERE ck.end_date::date BETWEEN CURRENT_DATE AND CURRENT_DATE + 14
            ORDER BY ck.end_date
            """,
            user_id=uid,
        )
    except Exception:
        expiring = []

    # 6. Open Complaints (table may not exist yet)
    try:
        complaints = execute_kelava_query(
            """
            SELECT id, customer_id, title, severity, status, created_at
            FROM complaint_tickets
            WHERE status IN ('open', 'in_progress')
            ORDER BY
                CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
                created_at
            LIMIT 10
            """,
            user_id=uid,
        )
    except Exception:
        complaints = []

    # 7. Workforce Status
    total_techs = execute_kelava_query_single(
        "SELECT COUNT(*) as cnt FROM technician_segments WHERE is_active = true",
        user_id=uid,
    )
    scheduled_today = len(schedule)

    # 8. Today's attendance (who checked in, who hasn't)
    try:
        checked_in = execute_kelava_query(
            """
            SELECT DISTINCT rp.id_user as technician_id, u.fullname as name,
                   MIN(v.check_in) as first_checkin
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            JOIN p_user u ON u.id = rp.id_user
            WHERE v.realization_date = %s AND v.check_in IS NOT NULL
            GROUP BY rp.id_user, u.fullname
            ORDER BY MIN(v.check_in)
            """,
            (today,),
            user_id=uid,
        )
    except Exception:
        checked_in = []

    try:
        not_checked_in = execute_kelava_query(
            """
            SELECT DISTINCT rp.id_user as technician_id, u.fullname as name,
                   COUNT(*) as planned_visits
            FROM t_road_plan rp
            JOIN p_user u ON u.id = rp.id_user
            WHERE rp.visit_date::date = %s
              AND COALESCE(rp.is_cancel, false) = false
              AND NOT EXISTS (
                  SELECT 1 FROM t_visit v2
                  JOIN t_road_plan rp2 ON rp2.id = v2.id_road_plan
                  WHERE rp2.id_user = rp.id_user
                    AND v2.realization_date = %s
                    AND v2.check_in IS NOT NULL
              )
            GROUP BY rp.id_user, u.fullname
            ORDER BY u.fullname
            """,
            (today, today),
            user_id=uid,
        )
    except Exception:
        not_checked_in = []

    # 9. Yesterday completion rate
    try:
        yesterday_stats = execute_kelava_query_single(
            """
            SELECT
                COUNT(DISTINCT rp.id) as total_planned,
                COUNT(DISTINCT CASE WHEN v.check_out IS NOT NULL THEN rp.id END) as completed,
                COUNT(DISTINCT rp.id_user) as total_techs
            FROM t_road_plan rp
            LEFT JOIN t_visit v ON v.id_road_plan = rp.id
            WHERE rp.visit_date::date = %s
              AND COALESCE(rp.is_cancel, false) = false
            """,
            (yesterday,),
            user_id=uid,
        )
    except Exception:
        yesterday_stats = {"total_planned": 0, "completed": 0, "total_techs": 0}

    # 10. Yesterday top performers
    try:
        top_performers = execute_kelava_query(
            """
            SELECT
                rp.id_user as technician_id,
                u.fullname as name,
                COUNT(DISTINCT CASE WHEN v.check_out IS NOT NULL THEN rp.id END) as completed_visits,
                ROUND(AVG(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 0) as avg_duration_min
            FROM t_road_plan rp
            JOIN t_visit v ON v.id_road_plan = rp.id
            JOIN p_user u ON u.id = rp.id_user
            WHERE rp.visit_date::date = %s
              AND v.check_out IS NOT NULL
            GROUP BY rp.id_user, u.fullname
            ORDER BY completed_visits DESC, avg_duration_min ASC
            LIMIT 3
            """,
            (yesterday,),
            user_id=uid,
        )
    except Exception:
        top_performers = []

    return jsonify({
        "date": today,
        "day_of_week": date.today().strftime("%A"),
        "today_schedule": [_fmt(r) for r in schedule],
        "scheduled_technicians": scheduled_today,
        "total_technicians": total_techs["cnt"] if total_techs else 0,
        "schedule_gaps": [_fmt(r) for r in gaps],
        "gap_count": len(gaps),
        "yesterday_late": [_fmt(r) for r in yesterday_late],
        "pending_issues": [_fmt(r) for r in pending_issues],
        "expiring_contracts": [_fmt(r) for r in expiring],
        "open_complaints": [_fmt(r) for r in complaints],
        "checked_in_today": [_fmt(r) for r in checked_in],
        "not_checked_in": [_fmt(r) for r in not_checked_in],
        "yesterday_completion": _fmt(yesterday_stats) if yesterday_stats else {},
        "top_performers": [_fmt(r) for r in top_performers],
        "generated_at": datetime.now().isoformat(),
    })
