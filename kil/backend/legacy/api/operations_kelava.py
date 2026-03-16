"""
Operations API
===============
API endpoints for operational overview and exception tracking.
Connects to Kelava live database.
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

operations_bp = Blueprint("operations", __name__)


@operations_bp.route("/operations/workload")
@require_auth
def operations_workload():
    """
    Get today's workload summary.

    Query params:
        date: Target date (default: today)
    """
    target_date_str = request.args.get("date", date.today().isoformat())

    try:
        target_date = date.fromisoformat(target_date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    # Planned today
    planned = execute_kelava_query_single(
        """
        SELECT COUNT(*) as count 
        FROM t_road_plan
        WHERE visit_date::date = %s
          AND COALESCE(is_cancel, false) = false
    """,
        (target_date,),
    )

    # By status
    by_status = execute_kelava_query(
        """
        SELECT status, COUNT(*) as count
        FROM t_road_plan
        WHERE visit_date::date = %s
          AND COALESCE(is_cancel, false) = false
        GROUP BY status
    """,
        (target_date,),
    )

    status_dict = {row["status"]: row["count"] for row in by_status}

    # Executed today (from t_visit)
    executed = execute_kelava_query_single(
        """
        SELECT COUNT(*) as count
        FROM t_visit
        WHERE realization_date = %s
    """,
        (target_date,),
    )

    return jsonify(
        {
            "date": target_date_str,
            "workload": {
                "planned_total": planned["count"] if planned else 0,
                "executed": executed["count"] if executed else 0,
                "baru": status_dict.get("Baru", 0),
                "requested": status_dict.get("Requested", 0),
                "berjalan": status_dict.get("Berjalan", 0),
                "selesai": status_dict.get("Selesai", 0),
            },
            "generated_at": datetime.now().isoformat(),
        }
    )


@operations_bp.route("/operations/exceptions")
@require_auth
def operations_exceptions():
    """
    Get exception counts (overdue, missing data, etc.).
    """
    # Overdue road plans (past date, not completed)
    overdue = execute_kelava_query_single("""
        SELECT COUNT(*) as count
        FROM t_road_plan rp
        WHERE rp.visit_date::date < CURRENT_DATE
          AND rp.status IN ('Baru', 'Requested', 'Berjalan')
          AND COALESCE(rp.is_cancel, false) = false
    """)

    # Missing check_out (check_in exists but no check_out, last 7 days)
    missing_checkout = execute_kelava_query_single("""
        SELECT COUNT(*) as count
        FROM t_visit v
        WHERE v.check_in IS NOT NULL
          AND v.check_out IS NULL
          AND v.realization_date >= CURRENT_DATE - INTERVAL '7 days'
    """)

    # Visits with very short duration (<5 min) - potential data issues
    short_visits = execute_kelava_query_single("""
        SELECT COUNT(*) as count
        FROM t_visit v
        WHERE v.check_in IS NOT NULL
          AND v.check_out IS NOT NULL
          AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) < 300
          AND v.realization_date >= CURRENT_DATE - INTERVAL '7 days'
    """)

    # Cancelled road plans this week
    cancelled = execute_kelava_query_single("""
        SELECT COUNT(*) as count
        FROM t_road_plan
        WHERE is_cancel = true
          AND visit_date::date >= CURRENT_DATE - INTERVAL '7 days'
    """)

    return jsonify(
        {
            "exceptions": {
                "overdue_road_plans": overdue["count"] if overdue else 0,
                "missing_checkout": missing_checkout["count"]
                if missing_checkout
                else 0,
                "short_visits_under_5min": short_visits["count"] if short_visits else 0,
                "cancelled_this_week": cancelled["count"] if cancelled else 0,
            },
            "generated_at": datetime.now().isoformat(),
        }
    )


@operations_bp.route("/operations/exceptions/table")
@require_auth
def operations_exceptions_table():
    """
    Get paginated list of road plans needing attention.

    Query params:
        type: Exception type (overdue, missing_checkout, short_visit)
        page: Page number (default: 1)
        per_page: Items per page (default: 20)
    """
    exception_type = request.args.get("type", "overdue")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    offset = (page - 1) * per_page

    if exception_type == "overdue":
        items = execute_kelava_query(
            """
            SELECT 
                rp.id,
                rp.no_ra,
                rp.visit_date::date as visit_date,
                rp.status,
                rp.type,
                rp.id_user,
                u.fullname as tech_name,
                c.name as customer_name,
                c.code as customer_code,
                (CURRENT_DATE - rp.visit_date::date) as days_overdue
            FROM t_road_plan rp
            LEFT JOIN p_user u ON u.id = rp.id_user
            LEFT JOIN m_customer c ON c.id = rp.id_customer
            WHERE rp.visit_date::date < CURRENT_DATE
              AND rp.status IN ('Baru', 'Requested', 'Berjalan')
              AND COALESCE(rp.is_cancel, false) = false
            ORDER BY rp.visit_date ASC
            LIMIT %s OFFSET %s
        """,
            (per_page, offset),
        )

    elif exception_type == "missing_checkout":
        items = execute_kelava_query(
            """
            SELECT 
                v.id,
                v.id_road_plan,
                rp.no_ra,
                v.realization_date,
                v.check_in,
                rp.id_user,
                u.fullname as tech_name,
                c.name as customer_name
            FROM t_visit v
            LEFT JOIN t_road_plan rp ON rp.id = v.id_road_plan
            LEFT JOIN p_user u ON u.id = rp.id_user
            LEFT JOIN m_customer c ON c.id = rp.id_customer
            WHERE v.check_in IS NOT NULL
              AND v.check_out IS NULL
              AND v.realization_date >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY v.check_in DESC
            LIMIT %s OFFSET %s
        """,
            (per_page, offset),
        )

    else:
        items = []

    # Format dates and times
    formatted_items = []
    for row in items:
        item = dict(row)
        for key, value in item.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        formatted_items.append(item)

    return jsonify(
        {
            "type": exception_type,
            "page": page,
            "per_page": per_page,
            "items": formatted_items,
            "generated_at": datetime.now().isoformat(),
        }
    )


@operations_bp.route("/operations/road-plans")
@require_auth
def operations_road_plans():
    """
    Get paginated list of road plans with filters.

    Query params:
        date: Target date (default: today)
        status: Filter by status
        type: Filter by type
        page, per_page: Pagination
    """
    target_date = request.args.get("date", date.today().isoformat())
    status_filter = request.args.get("status")
    type_filter = request.args.get("type")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)
    offset = (page - 1) * per_page

    # Build query with optional filters
    where_clauses = [
        "rp.visit_date::date = %s",
        "COALESCE(rp.is_cancel, false) = false",
    ]
    params = [target_date]

    if status_filter:
        where_clauses.append("rp.status = %s")
        params.append(status_filter)

    if type_filter:
        where_clauses.append("rp.type = %s")
        params.append(type_filter)

    where_sql = " AND ".join(where_clauses)
    params.extend([per_page, offset])

    items = execute_kelava_query(
        f"""
        SELECT 
            rp.id,
            rp.no_ra,
            rp.visit_date::date as visit_date,
            rp.status,
            rp.type,
            rp.id_user,
            u.fullname as tech_name,
            c.name as customer_name,
            c.code as customer_code,
            v.id as visit_id,
            v.check_in,
            v.check_out
        FROM t_road_plan rp
        LEFT JOIN p_user u ON u.id = rp.id_user
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE {where_sql}
        ORDER BY rp.created_date DESC
        LIMIT %s OFFSET %s
    """,
        tuple(params),
    )

    # Format dates
    formatted = []
    for row in items:
        item = dict(row)
        for key, value in item.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        formatted.append(item)

    return jsonify(
        {
            "date": target_date,
            "filters": {"status": status_filter, "type": type_filter},
            "page": page,
            "per_page": per_page,
            "items": formatted,
            "generated_at": datetime.now().isoformat(),
        }
    )
