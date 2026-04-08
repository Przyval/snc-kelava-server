"""
Executive Summary API
======================
API endpoints for executive-level KPIs and trends.
Connects to Kelava live database.
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from core.security import require_auth
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

executive_bp = Blueprint("executive", __name__)


@executive_bp.route("/executive/kpis")
@require_auth
def executive_kpis():
    """
    Get executive-level KPI summary.

    Query params:
        start_date: ISO date string (default: 7 days ago)
        end_date: ISO date string (default: today)
    """
    end_date = request.args.get("end_date", date.today().isoformat())
    start_date = request.args.get(
        "start_date", (date.today() - timedelta(days=7)).isoformat()
    )

    try:
        end_dt = date.fromisoformat(end_date)
        start_dt = date.fromisoformat(start_date)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    # 1) Planned Visits
    planned = execute_kelava_query_single(
        """
        SELECT COUNT(*) AS planned
        FROM t_road_plan rp
        WHERE rp.visit_date::date BETWEEN %s AND %s
          AND COALESCE(rp.is_cancel, false) = false
    """,
        (start_dt, end_dt),
    )

    # 2) Executed Visits
    executed = execute_kelava_query_single(
        """
        SELECT COUNT(*) AS executed
        FROM t_visit v
        WHERE v.realization_date BETWEEN %s AND %s
    """,
        (start_dt, end_dt),
    )

    # 3) Completion Rate
    planned_n = planned["planned"] if planned else 0
    executed_n = executed["executed"] if executed else 0
    completion_rate = round((executed_n / planned_n * 100), 2) if planned_n > 0 else 0

    # 4) Avg Service Duration (minutes) - CLEANED: exclude > 8 hours (480 min)
    duration_stats = execute_kelava_query_single(
        """
        WITH clean_durations AS (
            SELECT EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 AS duration_min
            FROM t_visit v
            WHERE v.realization_date BETWEEN %s AND %s
              AND v.check_in IS NOT NULL
              AND v.check_out IS NOT NULL
              AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 BETWEEN 1 AND 480
        )
        SELECT 
            ROUND(AVG(duration_min)::numeric, 1) AS avg_minutes,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_min)::numeric, 1) AS median_minutes,
            COUNT(*) AS included_count,
            (
                SELECT COUNT(*) FROM t_visit v
                WHERE v.realization_date BETWEEN %s AND %s
                  AND v.check_in IS NOT NULL AND v.check_out IS NOT NULL
            ) - COUNT(*) AS excluded_count
        FROM clean_durations
    """,
        (start_dt, end_dt, start_dt, end_dt),
    )

    # 5) Active Contracts - show total active + expiring breakdown
    contracts_stats = execute_kelava_query_single("""
        SELECT 
            COUNT(*) FILTER (
                WHERE COALESCE(is_active, '') ILIKE 'active'
                  AND CURRENT_DATE BETWEEN start_date AND end_date
            ) AS active_total,
            COUNT(*) FILTER (
                WHERE COALESCE(is_active, '') ILIKE 'active'
                  AND end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
            ) AS expiring_30d,
            COUNT(*) FILTER (
                WHERE COALESCE(is_active, '') ILIKE 'active'
                  AND end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '14 days'
            ) AS expiring_14d
        FROM m_customer_kontrak
    """)

    # 6) Visits by Status (today)
    status_counts = execute_kelava_query("""
        SELECT status, COUNT(*) as count
        FROM t_road_plan
        WHERE visit_date::date = CURRENT_DATE
          AND COALESCE(is_cancel, false) = false
        GROUP BY status
    """)

    status_dict = {row["status"]: row["count"] for row in status_counts}

    return jsonify(
        {
            "period": {
                "start_date": start_date,
                "end_date": end_date,
            },
            "kpis": {
                "planned_visits": planned_n,
                "executed_visits": executed_n,
                "completion_rate_pct": completion_rate,
                # Duration now includes median and excluded count for context
                "duration": {
                    "avg_minutes": float(duration_stats["avg_minutes"] or 0)
                    if duration_stats
                    else 0,
                    "median_minutes": float(duration_stats["median_minutes"] or 0)
                    if duration_stats
                    else 0,
                    "included_count": duration_stats["included_count"]
                    if duration_stats
                    else 0,
                    "excluded_count": duration_stats["excluded_count"]
                    if duration_stats
                    else 0,
                },
                # Active contracts shows total and expiring breakdown
                "contracts": {
                    "active_total": contracts_stats["active_total"]
                    if contracts_stats
                    else 0,
                    "expiring_30d": contracts_stats["expiring_30d"]
                    if contracts_stats
                    else 0,
                    "expiring_14d": contracts_stats["expiring_14d"]
                    if contracts_stats
                    else 0,
                },
            },
            "today_status": {
                "baru": status_dict.get("Baru", 0),
                "requested": status_dict.get("Requested", 0),
                "berjalan": status_dict.get("Berjalan", 0),
                "selesai": status_dict.get("Selesai", 0),
            },
            "generated_at": datetime.now().isoformat(),
        }
    )


@executive_bp.route("/executive/attention-required")
@require_auth
def attention_required():
    """
    Get items requiring immediate attention for Ops Head.
    Returns overdue visits, missing check-outs, idle technicians.
    """
    # 1) Overdue visits (planned but not executed, visit_date < today)
    overdue = execute_kelava_query_single("""
        SELECT COUNT(*) as count
        FROM t_road_plan rp
        WHERE rp.visit_date::date < CURRENT_DATE
          AND rp.status NOT IN ('Selesai', 'Batal')
          AND COALESCE(rp.is_cancel, false) = false
    """)

    # 2) Missing check-out (today, checked in but not out, > 4 hours ago)
    missing_checkout = execute_kelava_query_single("""
        SELECT COUNT(*) as count
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE rp.visit_date::date = CURRENT_DATE
          AND v.check_in IS NOT NULL
          AND v.check_out IS NULL
          AND v.check_in < NOW() - INTERVAL '4 hours'
    """)

    # 3) Technicians with pending visits today (not started)
    techs_pending = execute_kelava_query("""
        SELECT 
            u.id,
            u.fullname as name,
            COUNT(rp.id) as pending_count
        FROM p_user u
        JOIN t_road_plan rp ON rp.id_user = u.id
        WHERE rp.visit_date::date = CURRENT_DATE
          AND rp.status IN ('Baru', 'Requested')
          AND COALESCE(rp.is_cancel, false) = false
        GROUP BY u.id, u.fullname
        HAVING COUNT(rp.id) >= 3
        ORDER BY pending_count DESC
        LIMIT 5
    """)

    # 4) Contracts expiring within 7 days (urgent)
    urgent_contracts = execute_kelava_query_single("""
        SELECT COUNT(*) as count
        FROM m_customer_kontrak
        WHERE COALESCE(is_active, '') ILIKE 'active'
          AND end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
    """)

    return jsonify(
        {
            "attention_items": [
                {
                    "type": "overdue_visits",
                    "label": "Overdue Visits",
                    "count": overdue["count"] if overdue else 0,
                    "severity": "high"
                    if (overdue and overdue["count"] > 5)
                    else "medium",
                    "action_url": "/enterprise/operations?filter=overdue",
                },
                {
                    "type": "missing_checkout",
                    "label": "Missing Check-out",
                    "count": missing_checkout["count"] if missing_checkout else 0,
                    "severity": "high"
                    if (missing_checkout and missing_checkout["count"] > 0)
                    else "low",
                    "action_url": "/enterprise/operations?filter=missing_checkout",
                },
                {
                    "type": "urgent_contracts",
                    "label": "Contracts Expiring <7d",
                    "count": urgent_contracts["count"] if urgent_contracts else 0,
                    "severity": "high"
                    if (urgent_contracts and urgent_contracts["count"] > 0)
                    else "low",
                    "action_url": "/enterprise/?tab=contracts",
                },
            ],
            "technicians_high_pending": [
                {"id": t["id"], "name": t["name"], "pending": t["pending_count"]}
                for t in techs_pending
            ],
            "generated_at": datetime.now().isoformat(),
        }
    )


@executive_bp.route("/executive/trends")
@require_auth
def executive_trends():
    """
    Get daily trend of planned vs executed visits.

    Query params:
        days: Number of days to look back (default: 7)
    """
    days = int(request.args.get("days", 7))

    # Planned per day
    planned_trend = execute_kelava_query(
        """
        SELECT 
            visit_date::date as day,
            COUNT(*) as planned
        FROM t_road_plan
        WHERE visit_date::date >= CURRENT_DATE - INTERVAL '%s days'
          AND COALESCE(is_cancel, false) = false
        GROUP BY visit_date::date
        ORDER BY visit_date::date
    """,
        (days,),
    )

    # Executed per day
    executed_trend = execute_kelava_query(
        """
        SELECT 
            realization_date as day,
            COUNT(*) as executed
        FROM t_visit
        WHERE realization_date >= CURRENT_DATE - INTERVAL '%s days'
        GROUP BY realization_date
        ORDER BY realization_date
    """,
        (days,),
    )

    # Merge into dict by date
    trend_data = {}
    for row in planned_trend:
        day_str = row["day"].isoformat() if row["day"] else None
        if day_str:
            trend_data[day_str] = {"planned": row["planned"], "executed": 0}

    for row in executed_trend:
        day_str = row["day"].isoformat() if row["day"] else None
        if day_str:
            if day_str in trend_data:
                trend_data[day_str]["executed"] = row["executed"]
            else:
                trend_data[day_str] = {"planned": 0, "executed": row["executed"]}

    # Sort and format for charts
    sorted_dates = sorted(trend_data.keys())
    chart_data = {
        "labels": sorted_dates,
        "datasets": {
            "planned": [trend_data[d]["planned"] for d in sorted_dates],
            "executed": [trend_data[d]["executed"] for d in sorted_dates],
        },
    }

    return jsonify(
        {
            "days": days,
            "trend": trend_data,
            "chart_data": chart_data,
            "generated_at": datetime.now().isoformat(),
        }
    )


@executive_bp.route("/executive/visits-by-type")
@require_auth
def visits_by_type():
    """
    Get breakdown of visits by type.

    Query params:
        start_date, end_date: Date range
    """
    end_date = request.args.get("end_date", date.today().isoformat())
    start_date = request.args.get(
        "start_date", (date.today() - timedelta(days=30)).isoformat()
    )

    try:
        end_dt = date.fromisoformat(end_date)
        start_dt = date.fromisoformat(start_date)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    by_type = execute_kelava_query(
        """
        SELECT 
            type,
            COUNT(*) as count,
            COUNT(*) FILTER (WHERE status = 'Selesai') as completed
        FROM t_road_plan
        WHERE visit_date::date BETWEEN %s AND %s
          AND COALESCE(is_cancel, false) = false
        GROUP BY type
        ORDER BY count DESC
    """,
        (start_dt, end_dt),
    )

    return jsonify(
        {
            "period": {"start_date": start_date, "end_date": end_date},
            "by_type": [
                {
                    "type": row["type"],
                    "count": row["count"],
                    "completed": row["completed"],
                    "completion_rate_pct": round(
                        row["completed"] / row["count"] * 100, 1
                    )
                    if row["count"] > 0
                    else 0,
                }
                for row in by_type
            ],
            "generated_at": datetime.now().isoformat(),
        }
    )


@executive_bp.route("/executive/leaderboard-mini")
@require_auth
def leaderboard_mini():
    """Top 5 technicians by completed visits this calendar month."""
    rows = execute_kelava_query(
        """
        SELECT u.id, u.fullname AS name,
               COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS selesai,
               COUNT(*) AS total
        FROM p_user u
        JOIN t_road_plan rp ON rp.id_user = u.id
        WHERE rp.visit_date::date >= DATE_TRUNC('month', CURRENT_DATE)
          AND COALESCE(rp.is_cancel, false) = false
        GROUP BY u.id, u.fullname
        ORDER BY selesai DESC
        LIMIT 5
        """
    )
    return jsonify({
        "technicians": [
            {"id": r["id"], "name": r["name"], "selesai": r["selesai"], "total": r["total"]}
            for r in (rows or [])
        ],
        "generated_at": datetime.now().isoformat(),
    })


@executive_bp.route("/executive/contracts/expiring")
@require_auth
def contracts_expiring():
    """
    Get contracts expiring within 30 days.

    Query params:
        days: Days to look ahead (default: 30)
        limit: Max results (default: 50)
    """
    days = int(request.args.get("days", 30))
    limit = int(request.args.get("limit", 50))

    contracts = execute_kelava_query(
        """
        SELECT 
            k.id,
            k.no_kontrak,
            k.id_customer,
            c.name as customer_name,
            c.code as customer_code,
            k.start_date,
            k.end_date,
            (k.end_date - CURRENT_DATE) AS days_to_expire
        FROM m_customer_kontrak k
        LEFT JOIN m_customer c ON c.id = k.id_customer
        WHERE COALESCE(k.is_active, '') ILIKE 'active'
          AND k.end_date BETWEEN CURRENT_DATE AND (CURRENT_DATE + INTERVAL '%s days')
        ORDER BY k.end_date ASC
        LIMIT %s
    """,
        (days, limit),
    )

    # Format dates for JSON
    formatted = []
    for row in contracts:
        formatted.append(
            {
                "id": row["id"],
                "no_kontrak": row["no_kontrak"],
                "customer_id": row["id_customer"],
                "customer_name": row["customer_name"],
                "customer_code": row["customer_code"],
                "start_date": row["start_date"].isoformat()
                if row["start_date"]
                else None,
                "end_date": row["end_date"].isoformat() if row["end_date"] else None,
                "days_to_expire": row["days_to_expire"],
            }
        )

    return jsonify(
        {
            "look_ahead_days": days,
            "count": len(formatted),
            "contracts": formatted,
            "generated_at": datetime.now().isoformat(),
        }
    )


# ── Briefing Widgets ──────────────────────────────────────────


@executive_bp.route("/executive/briefing-widgets", methods=["GET"])
@require_auth
def briefing_widgets():
    """Four operational briefing widgets for the executive dashboard."""

    def _fmt(row):
        d = dict(row)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                d[k] = float(v)
        return d

    # A) Kontrak Baru Belum Di-Plot
    #    Contracts started in last 30 days with no scheduled visit
    new_unplotted = execute_kelava_query("""
        SELECT c.id, c.name, c.code, c.address,
               k.no_kontrak, k.start_date, k.end_date
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        WHERE UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
          AND k.start_date >= CURRENT_DATE - INTERVAL '30 days'
          AND NOT EXISTS (
              SELECT 1 FROM t_road_plan rp
              WHERE rp.id_customer = k.id_customer
                AND rp.visit_date::date >= k.start_date
                AND COALESCE(rp.is_cancel, false) = false
          )
        ORDER BY k.start_date DESC
        LIMIT 50
    """)

    # B) Cancel Kemarin
    #    Visits cancelled yesterday
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    cancelled_yesterday = execute_kelava_query("""
        SELECT rp.id, rp.visit_date::date AS visit_date, rp.type,
               c.name AS customer_name, c.code AS customer_code,
               u.fullname AS technician_name
        FROM t_road_plan rp
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN p_user u ON u.id = rp.id_user
        WHERE rp.is_cancel = true
          AND rp.visit_date::date = %s
        ORDER BY c.name
    """, (yesterday,))

    # C) Cancel Belum Reschedule
    #    Cancelled this month with no future visit for that customer
    cancel_no_resched = execute_kelava_query("""
        SELECT rp.id, rp.visit_date::date AS cancel_date,
               c.id AS customer_id, c.name AS customer_name, c.code,
               u.fullname AS technician_name
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN p_user u ON u.id = rp.id_user
        WHERE rp.is_cancel = true
          AND rp.visit_date::date >= DATE_TRUNC('month', CURRENT_DATE)
          AND NOT EXISTS (
              SELECT 1 FROM t_road_plan rp2
              WHERE rp2.id_customer = rp.id_customer
                AND rp2.visit_date::date > rp.visit_date::date
                AND COALESCE(rp2.is_cancel, false) = false
          )
        ORDER BY rp.visit_date::date DESC
        LIMIT 50
    """)

    # D) Complete Bulan Ini
    #    Customers where ALL visits this month are Selesai
    completed_month = execute_kelava_query("""
        SELECT c.id, c.name, c.code,
               COUNT(*) AS total_visits,
               MAX(rp.visit_date::date) AS last_visit_date
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.visit_date::date >= DATE_TRUNC('month', CURRENT_DATE)
          AND rp.visit_date::date <= CURRENT_DATE
          AND COALESCE(rp.is_cancel, false) = false
        GROUP BY c.id, c.name, c.code
        HAVING COUNT(*) = COUNT(*) FILTER (WHERE rp.status = 'Selesai')
           AND COUNT(*) > 0
        ORDER BY c.name
        LIMIT 100
    """)

    return jsonify({
        "new_unplotted": [_fmt(r) for r in new_unplotted],
        "new_unplotted_count": len(new_unplotted),
        "cancelled_yesterday": [_fmt(r) for r in cancelled_yesterday],
        "cancelled_yesterday_count": len(cancelled_yesterday),
        "cancel_no_reschedule": [_fmt(r) for r in cancel_no_resched],
        "cancel_no_reschedule_count": len(cancel_no_resched),
        "completed_month": [_fmt(r) for r in completed_month],
        "completed_month_count": len(completed_month),
        "generated_at": datetime.now().isoformat(),
    })
