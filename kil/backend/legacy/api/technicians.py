"""
Technicians API
================
API endpoints for technician performance tracking and leaderboard.
Connects to Kelava live database.
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single, _get_local_pool

technicians_bp = Blueprint("technicians", __name__)


@technicians_bp.route("/technicians/leaderboard")
@require_auth
def technicians_leaderboard():
    """
    Get technician performance leaderboard.

    Query params:
        start_date, end_date: Date range
        limit: Max results (default: 50)
        sort_by: Sorting field (completion_rate, avg_duration, total_visits)
    """
    end_date = request.args.get("end_date", date.today().isoformat())
    start_date = request.args.get(
        "start_date", (date.today() - timedelta(days=30)).isoformat()
    )
    limit = min(int(request.args.get("limit", 50)), 100)
    sort_by = request.args.get("sort_by", "total_visits")

    try:
        end_dt = date.fromisoformat(end_date)
        start_dt = date.fromisoformat(start_date)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    # Get performance metrics per technician
    leaderboard = execute_kelava_query(
        """
        WITH tech_stats AS (
            SELECT 
                rp.id_user,
                COUNT(*) as total_planned,
                COUNT(*) FILTER (WHERE rp.status = 'Selesai') as total_completed,
                COUNT(DISTINCT rp.visit_date::date) as active_days
            FROM t_road_plan rp
            WHERE rp.visit_date::date BETWEEN %s AND %s
              AND COALESCE(rp.is_cancel, false) = false
            GROUP BY rp.id_user
        ),
        visit_stats AS (
            SELECT 
                rp.id_user,
                COUNT(v.id) as total_visits,
                ROUND(AVG(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 2) as avg_duration_min
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE v.realization_date BETWEEN %s AND %s
              AND v.check_in IS NOT NULL
              AND v.check_out IS NOT NULL
            GROUP BY rp.id_user
        )
        SELECT
            u.id,
            u.fullname,
            u.email,
            COALESCE(seg.segment, 'UNASSIGNED') as segment,
            COALESCE(ts.total_planned, 0) as total_planned,
            COALESCE(ts.total_completed, 0) as total_completed,
            CASE WHEN COALESCE(ts.total_planned, 0) > 0
                 THEN ROUND(ts.total_completed::numeric / ts.total_planned * 100, 1)
                 ELSE 0
            END as completion_rate,
            COALESCE(vs.total_visits, 0) as total_visits,
            COALESCE(vs.avg_duration_min, 0) as avg_duration_min,
            COALESCE(ts.active_days, 0) as active_days,
            CASE WHEN COALESCE(ts.active_days, 0) > 0
                 THEN ROUND(COALESCE(vs.total_visits, 0)::numeric / ts.active_days, 1)
                 ELSE 0
            END as visits_per_day
        FROM p_user u
        LEFT JOIN tech_stats ts ON ts.id_user = u.id
        LEFT JOIN visit_stats vs ON vs.id_user = u.id
        LEFT JOIN technician_segments seg ON seg.technician_id = u.id
        WHERE COALESCE(ts.total_planned, 0) > 0 OR COALESCE(vs.total_visits, 0) > 0
        ORDER BY 
            CASE WHEN %s = 'completion_rate' THEN COALESCE(ts.total_completed::numeric / NULLIF(ts.total_planned, 0) * 100, 0) END DESC,
            CASE WHEN %s = 'avg_duration' THEN COALESCE(vs.avg_duration_min, 999999) END ASC,
            CASE WHEN %s = 'total_visits' THEN COALESCE(vs.total_visits, 0) END DESC,
            COALESCE(vs.total_visits, 0) DESC
        LIMIT %s
    """,
        (start_dt, end_dt, start_dt, end_dt, sort_by, sort_by, sort_by, limit),
    )

    formatted = []
    for row in leaderboard:
        formatted.append(
            {
                "id": row["id"],
                "name": row["fullname"],
                "email": row["email"],
                "segment": row["segment"],
                "metrics": {
                    "total_planned": row["total_planned"],
                    "total_completed": row["total_completed"],
                    "completion_rate_pct": float(row["completion_rate"])
                    if row["completion_rate"]
                    else 0,
                    "total_visits": row["total_visits"],
                    "avg_duration_min": float(row["avg_duration_min"])
                    if row["avg_duration_min"]
                    else 0,
                    "active_days": row["active_days"],
                    "visits_per_day": float(row["visits_per_day"])
                    if row["visits_per_day"]
                    else 0,
                },
            }
        )

    # CSV export support
    if request.args.get("format") == "csv":
        from kil.backend.legacy.api.export_utils import rows_to_csv_response
        flat_rows = []
        for f_row in formatted:
            flat_rows.append({
                "id": f_row["id"],
                "name": f_row["name"],
                "email": f_row["email"],
                **f_row["metrics"],
            })
        return rows_to_csv_response(flat_rows, f"technicians_{start_date}_{end_date}.csv")

    return jsonify(
        {
            "period": {"start_date": start_date, "end_date": end_date},
            "sort_by": sort_by,
            "count": len(formatted),
            "leaderboard": formatted,
            "generated_at": datetime.now().isoformat(),
        }
    )


@technicians_bp.route("/technicians/active-today")
@require_auth
def active_today():
    """Technicians who have checked in today."""
    rows = execute_kelava_query(
        """
        SELECT DISTINCT u.id, u.fullname as name
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        JOIN p_user u ON u.id = rp.id_user
        WHERE v.realization_date = CURRENT_DATE
          AND v.check_in IS NOT NULL
        ORDER BY u.fullname
        """,
    )
    return jsonify({
        "count": len(rows),
        "technicians": [{"id": r["id"], "name": r["name"]} for r in rows],
    })


@technicians_bp.route("/technicians/<int:tech_id>")
@require_auth
def technician_detail(tech_id: int):
    """
    Get detailed profile for a specific technician.
    """
    # Basic info
    user = execute_kelava_query_single(
        """
        SELECT id, fullname, email, phone, NOT is_deleted as is_active, reg_date as created_at
        FROM p_user
        WHERE id = %s
    """,
        (tech_id,),
    )

    if not user:
        return jsonify({"error": "Technician not found"}), 404

    # Performance summary (last 30 days)
    stats = execute_kelava_query_single(
        """
        WITH period AS (
            SELECT 
                COUNT(*) as total_planned,
                COUNT(*) FILTER (WHERE status = 'Selesai') as total_completed
            FROM t_road_plan
            WHERE id_user = %s
              AND visit_date::date >= CURRENT_DATE - INTERVAL '30 days'
              AND COALESCE(is_cancel, false) = false
        ),
        visits AS (
            SELECT 
                COUNT(*) as total_visits,
                ROUND(AVG(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 2) as avg_duration
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE rp.id_user = %s
              AND v.realization_date >= CURRENT_DATE - INTERVAL '30 days'
              AND v.check_in IS NOT NULL AND v.check_out IS NOT NULL
        )
        SELECT 
            p.total_planned,
            p.total_completed,
            v.total_visits,
            v.avg_duration
        FROM period p, visits v
    """,
        (tech_id, tech_id),
    )

    # Recent visits
    recent_visits = execute_kelava_query(
        """
        SELECT 
            v.id,
            v.realization_date,
            v.check_in,
            v.check_out,
            ROUND((EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 1) as duration_min,
            rp.no_ra,
            rp.type,
            c.name as customer_name
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.id_user = %s
        ORDER BY v.realization_date DESC, v.check_in DESC
        LIMIT 10
    """,
        (tech_id,),
    )

    # Format response
    formatted_visits = []
    for row in recent_visits:
        visit = dict(row)
        for key, value in visit.items():
            if hasattr(value, "isoformat"):
                visit[key] = value.isoformat()
        formatted_visits.append(visit)

    return jsonify(
        {
            "technician": {
                "id": user["id"],
                "name": user["fullname"],
                "email": user["email"],
                "phone": user.get("phone"),
                "is_active": user["is_active"],
            },
            "performance_30d": {
                "total_planned": stats["total_planned"] if stats else 0,
                "total_completed": stats["total_completed"] if stats else 0,
                "total_visits": stats["total_visits"] if stats else 0,
                "avg_duration_min": float(stats["avg_duration"] or 0) if stats else 0,
            },
            "recent_visits": formatted_visits,
            "generated_at": datetime.now().isoformat(),
        }
    )


@technicians_bp.route("/technicians/<int:tech_id>/visits")
@require_auth
def technician_visits(tech_id: int):
    """
    Get paginated visit history for a technician.

    Query params:
        page, per_page: Pagination
        start_date, end_date: Date filter
    """
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    offset = (page - 1) * per_page

    end_date = request.args.get("end_date", date.today().isoformat())
    start_date = request.args.get(
        "start_date", (date.today() - timedelta(days=30)).isoformat()
    )

    visits = execute_kelava_query(
        """
        SELECT 
            v.id,
            v.realization_date,
            v.check_in,
            v.check_out,
            ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in))::numeric / 60, 1) as duration_min,
            v.latitude,
            v.longitude,
            rp.id as road_plan_id,
            rp.no_ra,
            rp.type,
            rp.status,
            c.id as customer_id,
            c.name as customer_name,
            c.code as customer_code
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.id_user = %s
          AND v.realization_date BETWEEN %s AND %s
        ORDER BY v.realization_date DESC, v.check_in DESC
        LIMIT %s OFFSET %s
    """,
        (tech_id, start_date, end_date, per_page, offset),
    )

    # Format
    formatted = []
    for row in visits:
        visit = dict(row)
        for key, value in visit.items():
            if hasattr(value, "isoformat"):
                visit[key] = value.isoformat()
        formatted.append(visit)

    return jsonify(
        {
            "tech_id": tech_id,
            "period": {"start_date": start_date, "end_date": end_date},
            "page": page,
            "per_page": per_page,
            "visits": formatted,
            "generated_at": datetime.now().isoformat(),
        }
    )


@technicians_bp.route("/technicians/recommend")
@require_auth
def recommend_technicians():
    """
    Recommend best technicians for a job based on:
    - Availability (Workload for the day)
    - Performance (Completion rate)
    - Reliability (Low exception rate)
    """
    date_str = request.args.get("date", date.today().isoformat())
    limit = min(int(request.args.get("limit", 5)), 20)

    # 1. Get workload for all technicians on target date
    workload = execute_kelava_query(
        """
        SELECT 
            id_user,
            COUNT(*) as job_count
        FROM t_road_plan
        WHERE visit_date::date = %s
          AND COALESCE(is_cancel, false) = false
        GROUP BY id_user
    """,
        (date_str,),
    )

    workload_map = {w["id_user"]: w["job_count"] for w in workload}

    # 2. Get performance metrics (last 30 days)
    performance = execute_kelava_query("""
        WITH stats AS (
            SELECT 
                rp.id_user,
                COUNT(*) as planned,
                COUNT(*) FILTER (WHERE rp.status = 'Selesai') as completed,
                COUNT(v.id) FILTER (
                    WHERE (EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60) < 15 
                    OR (EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60) > 480
                ) as anomalies
            FROM t_road_plan rp
            LEFT JOIN t_visit v ON v.id_road_plan = rp.id
            WHERE rp.visit_date >= CURRENT_DATE - INTERVAL '30 days'
              AND COALESCE(rp.is_cancel, false) = false
            GROUP BY rp.id_user
        )
        SELECT 
            u.id,
            u.fullname as name,
            COALESCE(s.planned, 0) as planned,
            COALESCE(s.completed, 0) as completed,
            COALESCE(s.anomalies, 0) as anomalies
        FROM p_user u
        LEFT JOIN stats s ON s.id_user = u.id
        WHERE COALESCE(u.is_deleted, false) = false
    """)

    recommendations = []
    max_capacity = 5

    for p in performance:
        tech_id = p["id"]
        current_jobs = workload_map.get(tech_id, 0)

        # Calculate Score (Higher is better)
        # Base: Availability (Max 40 points)
        # Performance: Completion Rate (Max 40 points)
        # Reliability: Low Anomaly Rate (Max 20 points)

        availability_score = max(0, (max_capacity - current_jobs) / max_capacity * 40)

        completion_rate = (
            (p["completed"] / p["planned"] * 100) if p["planned"] > 0 else 80
        )  # Default for new
        performance_score = (completion_rate / 100) * 40

        anomaly_rate = (
            (p["anomalies"] / p["completed"] * 100) if p["completed"] > 0 else 0
        )
        reliability_score = max(
            0, (20 - (anomaly_rate / 5))
        )  # Deduct 1 point for every 5% anomaly

        total_score = availability_score + performance_score + reliability_score

        recommendations.append(
            {
                "id": tech_id,
                "name": p["name"],
                "current_workload": current_jobs,
                "capacity_left": max(0, max_capacity - current_jobs),
                "score": round(total_score, 1),
                "metrics": {
                    "completion_rate": round(completion_rate, 1),
                    "anomaly_count": p["anomalies"],
                    "planned_30d": p["planned"],
                },
                "suitability": "High"
                if total_score > 80
                else "Medium"
                if total_score > 60
                else "Low",
            }
        )

    # Filter out those at max capacity if possible, then sort
    recommendations.sort(key=lambda x: x["score"], reverse=True)

    return jsonify(
        {
            "date": date_str,
            "recommendations": recommendations[:limit],
            "algorithm": "workload_performance_v1",
            "generated_at": datetime.now().isoformat(),
        }
    )


# ── Technician Rapor (Report Card) ────────────────────────────


@technicians_bp.route("/technicians/<int:tech_id>/rapor")
@require_auth
def technician_rapor(tech_id: int):
    """
    Comprehensive report card for a technician.
    Designed for HR review: photo, KPI monthly, punctuality, issues.

    Query params:
        months: Number of months to look back (default: 3)
        month: Specific month YYYY-MM (overrides months param for KPI scoring)
    """
    months = int(request.args.get("months", 3))
    specific_month = request.args.get("month", "").strip()  # e.g. "2026-03"

    # Basic info
    tech = execute_kelava_query_single(
        """
        SELECT u.id, u.fullname as name, u.email,
               COALESCE(ts.segment, 'UNASSIGNED') as segment,
               ts.shift_type, ts.weekly_hours_target
        FROM p_user u
        LEFT JOIN technician_segments ts ON ts.technician_id = u.id
        WHERE u.id = %s
        """,
        (tech_id,),
    )
    if not tech:
        return jsonify({"error": "Technician not found"}), 404

    # Detect employee type from HRIS or segment
    emp_type = "mobile"  # default
    try:
        with _get_local_pool().connection() as lconn:
            with lconn.cursor() as lcur:
                lcur.execute("SELECT employee_type, site_assignment FROM hris_employees WHERE full_name = %s OR p_user_id = %s LIMIT 1",
                             (tech["name"], tech_id))
                hris_row = lcur.fetchone()
                if hris_row:
                    emp_type = hris_row["employee_type"]
                    tech = dict(tech)
                    tech["employee_type"] = emp_type
                    tech["site_assignment"] = hris_row["site_assignment"]
    except Exception:
        pass
    if tech.get("segment") == "STATION":
        emp_type = "station"

    # Monthly KPI breakdown
    monthly_kpi = execute_kelava_query(
        """
        WITH monthly AS (
            SELECT
                DATE_TRUNC('month', rp.visit_date::date) as month,
                COUNT(*) as total_planned,
                COUNT(*) FILTER (WHERE rp.status = 'Selesai') as total_completed,
                COUNT(DISTINCT rp.visit_date::date) as active_days
            FROM t_road_plan rp
            WHERE rp.id_user = %s
              AND rp.visit_date::date >= DATE_TRUNC('month', CURRENT_DATE) - make_interval(months => %s)
              AND COALESCE(rp.is_cancel, false) = false
            GROUP BY DATE_TRUNC('month', rp.visit_date::date)
        ),
        monthly_visits AS (
            SELECT
                DATE_TRUNC('month', v.realization_date) as month,
                COUNT(v.id) as total_visits,
                ROUND(AVG(
                    CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60
                    END
                )::numeric, 1) as avg_duration_min
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE rp.id_user = %s
              AND v.realization_date >= DATE_TRUNC('month', CURRENT_DATE) - make_interval(months => %s)
            GROUP BY DATE_TRUNC('month', v.realization_date)
        )
        SELECT
            m.month,
            m.total_planned,
            m.total_completed,
            m.active_days,
            COALESCE(mv.total_visits, 0) as total_visits,
            COALESCE(mv.avg_duration_min, 0) as avg_duration_min,
            CASE WHEN m.active_days > 0
                THEN ROUND(COALESCE(mv.total_visits, 0)::numeric / m.active_days, 1)
                ELSE 0
            END as visits_per_day,
            CASE WHEN m.total_planned > 0
                THEN ROUND(m.total_completed::numeric / m.total_planned * 100, 1)
                ELSE 0
            END as completion_rate
        FROM monthly m
        LEFT JOIN monthly_visits mv ON mv.month = m.month
        ORDER BY m.month DESC
        """,
        (tech_id, months, tech_id, months),
    )

    # Punctuality summary per month
    punctuality = execute_kelava_query(
        """
        WITH daily_first AS (
            SELECT
                DATE_TRUNC('month', v.realization_date) as month,
                v.realization_date,
                MIN(v.check_in)::time as first_checkin
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE rp.id_user = %s
              AND v.realization_date >= DATE_TRUNC('month', CURRENT_DATE) - make_interval(months => %s)
              AND v.check_in IS NOT NULL
            GROUP BY v.realization_date, DATE_TRUNC('month', v.realization_date)
        )
        SELECT
            month,
            COUNT(*) as total_days,
            COUNT(*) FILTER (WHERE first_checkin <= '08:30:00'::time) as on_time_days,
            COUNT(*) FILTER (WHERE first_checkin > '08:30:00'::time) as late_days,
            ROUND(AVG(EXTRACT(EPOCH FROM (first_checkin - '08:00:00'::time)) / 60)::numeric, 1) as avg_arrival_offset_min
        FROM daily_first
        GROUP BY month
        ORDER BY month DESC
        """,
        (tech_id, months),
    )

    # Issue history
    issues = execute_kelava_query(
        """
        SELECT issue_type, severity, status, context, created_at, resolved_at
        FROM technician_issues
        WHERE technician_id = %s
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (tech_id,),
    )

    # Date range for KPI scoring — specific month or last N months
    if specific_month:
        # e.g. "2026-03" → score only that month
        kpi_date_filter_rp = "DATE_TRUNC('month', rp.visit_date::date) = %s::date"
        kpi_date_filter_v = "DATE_TRUNC('month', v.realization_date) = %s::date"
        kpi_date_filter_c = "DATE_TRUNC('month', created_at) = %s::date"
        kpi_date_param = specific_month + "-01"
        kpi_months_divisor = 1
    else:
        kpi_date_filter_rp = "rp.visit_date::date >= CURRENT_DATE - 90"
        kpi_date_filter_v = "v.realization_date >= CURRENT_DATE - 90"
        kpi_date_filter_c = "created_at >= CURRENT_DATE - 90"
        kpi_date_param = None
        kpi_months_divisor = months or 3

    rp_params = (tech_id, kpi_date_param, tech_id, kpi_date_param) if kpi_date_param else (tech_id, tech_id)
    p_params = (tech_id, kpi_date_param) if kpi_date_param else (tech_id,)
    c_params = (tech_id, kpi_date_param) if kpi_date_param else (tech_id,)

    rp_where = kpi_date_filter_rp if kpi_date_param else "rp.visit_date::date >= CURRENT_DATE - 90"
    v_where = kpi_date_filter_v if kpi_date_param else "v.realization_date >= CURRENT_DATE - 90"

    overall_metrics = execute_kelava_query_single(
        f"""
        WITH stats AS (
            SELECT
                COUNT(*) as total_planned,
                COUNT(*) FILTER (WHERE rp.status = 'Selesai') as completed,
                COUNT(*) FILTER (WHERE rp.is_cancel = true) as cancelled,
                COUNT(DISTINCT rp.visit_date::date) as active_days
            FROM t_road_plan rp
            WHERE rp.id_user = %s
              AND {rp_where}
        ),
        vstats AS (
            SELECT
                COUNT(v.id) as total_visits,
                COALESCE(SUM(LEAST(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 3600, 8)), 0) as total_hours,
                COUNT(v.id) FILTER (
                    WHERE v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                ) as with_checkout
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE rp.id_user = %s
              AND {v_where}
              AND v.check_in IS NOT NULL AND v.check_out IS NOT NULL
              AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 BETWEEN 1 AND 480
        )
        SELECT
            s.total_planned,
            s.completed,
            s.cancelled,
            s.active_days,
            v.total_visits,
            ROUND(v.total_hours::numeric, 1) as total_hours,
            v.with_checkout,
            CASE WHEN s.active_days > 0
                THEN ROUND(v.total_visits::numeric / s.active_days, 1)
                ELSE 0
            END as visits_per_day,
            CASE WHEN s.total_planned > 0
                THEN ROUND(s.completed::numeric / s.total_planned * 100, 1)
                ELSE 0
            END as completion_rate
        FROM stats s, vstats v
        """,
        rp_params,
    )

    punct_overall = execute_kelava_query_single(
        f"""
        WITH daily_first AS (
            SELECT v.realization_date, MIN(v.check_in)::time as first_checkin
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE rp.id_user = %s
              AND {v_where}
              AND v.check_in IS NOT NULL
            GROUP BY v.realization_date
        )
        SELECT
            COUNT(*) as total_days,
            COUNT(*) FILTER (WHERE first_checkin <= '08:30:00'::time) as on_time_days,
            COUNT(*) FILTER (WHERE first_checkin > '08:30:00'::time) as late_days
        FROM daily_first
        """,
        p_params,
    )

    complaint_data = execute_kelava_query_single(
        f"""
        SELECT COUNT(*) as total_complaints,
               COUNT(*) FILTER (WHERE severity IN ('critical','high')) as major_complaints
        FROM complaint_tickets
        WHERE assigned_to = %s
          AND {kpi_date_filter_c}
        """,
        c_params,
    )
    if not complaint_data:
        complaint_data = {"total_complaints": 0, "major_complaints": 0}

    # ── KPI Scoring ──
    # Mobile: 13 indicators (kedisiplinan 35%, complain 20%, grooming 10%, kunjungan 35%)
    # Station: 11 indicators (kedisiplinan 30%, kinerja 25%, complain 10%, grooming 10%, penilaian 25%)

    om = overall_metrics or {}
    po = punct_overall or {}

    planned_noncx = float(om.get("total_planned", 0)) - float(om.get("cancelled", 0))
    planned_noncx = max(1, planned_noncx)
    completed = float(om.get("completed", 0))
    cancelled = float(om.get("cancelled", 0))
    total_visits = float(om.get("total_visits", 0))
    total_hours = float(om.get("total_hours", 0))
    active_days = float(om.get("active_days", 0))
    with_checkout = float(om.get("with_checkout", 0))
    total_days_punct = float(po.get("total_days", 0)) or 1
    on_time = float(po.get("on_time_days", 0))
    late_days = total_days_punct - on_time
    major_complaints = float(complaint_data.get("major_complaints", 0))
    total_complaints = float(complaint_data.get("total_complaints", 0))

    # 1. KEDISIPLINAN (30%)
    # Administrasi — Check In/Out sesuai jadwal (5%)
    # Count visits where check-in/out not at location = issues
    checkin_issues = max(0, total_visits - with_checkout)
    adm_checkinout = 0.05 if checkin_issues == 0 else 0.0
    # Administrasi — Laporan lengkap (5%) — no automated data, default pass
    adm_laporan = 0.05

    # Waktu — Tidak terlambat (5%)
    waktu_telat = 0.05 if late_days == 0 else 0.0
    # Waktu — Tidak cancel (5%)
    waktu_cancel = 0.05 if cancelled == 0 else 0.0
    # Waktu — Tidak izin mendadak (5%) — proxy: same as punctuality
    waktu_izin = 0.05 if late_days <= 1 else 0.0

    # Kinerja — pull QC/SPV/Grooming from HRIS DB if available
    hris_qc = None
    hris_spv = None
    hris_grooming = None
    kpi_month = int(specific_month.split("-")[1]) if specific_month else None
    kpi_year = int(specific_month.split("-")[0]) if specific_month else 2025
    try:
        with _get_local_pool().connection() as lconn:
            with lconn.cursor() as lcur:
                # Find HRIS employee by matching name to Kelava p_user
                lcur.execute(
                    "SELECT id FROM hris_employees WHERE p_user_id = %s", (tech_id,))
                hris_emp = lcur.fetchone()
                if not hris_emp:
                    # Try name match
                    lcur.execute(
                        "SELECT he.id FROM hris_employees he "
                        "JOIN enterprise_users eu ON eu.full_name = he.full_name "
                        "WHERE eu.p_user_id = %s LIMIT 1", (tech_id,))
                    hris_emp = lcur.fetchone()

                if hris_emp:
                    hris_eid = hris_emp["id"]
                    # Build month filter
                    if kpi_month:
                        month_filter = "AND s.period_month = %s AND s.period_year = %s"
                        month_params = (hris_eid, kpi_month, kpi_year)
                    else:
                        # Latest available month
                        month_filter = "AND s.period_year = %s ORDER BY s.period_month DESC"
                        month_params = (hris_eid, kpi_year)

                    lcur.execute(f"""
                        SELECT t.indicator, s.score_pct, s.raw_value, s.keterangan
                        FROM hris_kpi_scores s
                        JOIN hris_kpi_templates t ON t.id = s.template_id
                        WHERE s.employee_id = %s {month_filter}
                    """, month_params)
                    for row in lcur.fetchall():
                        ind = row["indicator"].lower()
                        if "penilaian tim qc" in ind:
                            hris_qc = float(row["score_pct"])
                        elif "arahan spv" in ind or "melaksanakan arahan" in ind:
                            hris_spv = float(row["score_pct"])
                        elif "grooming" in ind or "berpenampilan rapi" in ind:
                            hris_grooming = float(row["score_pct"])
    except Exception:
        pass  # Fall back to defaults if HRIS unavailable

    # QC (5%): from HRIS or default 4/5
    if hris_qc is not None:
        kinerja_qc = hris_qc
        qc_value = round(hris_qc / 0.05 * 5, 1)  # reverse to display as X/5
        qc_source = "HRIS"
    else:
        qc_value = 4.0
        kinerja_qc = round(qc_value / 5 * 0.05, 4)
        qc_source = "Default"

    # SPV (5%): from HRIS or default 4.6/5
    if hris_spv is not None:
        kinerja_spv = hris_spv
        spv_value = round(hris_spv / 0.05 * 5, 1)
        spv_source = "HRIS"
    else:
        spv_value = 4.6
        kinerja_spv = round(spv_value / 5 * 0.05, 4)
        spv_source = "Default"

    kedisiplinan = round(adm_checkinout + adm_laporan + waktu_telat + waktu_cancel + waktu_izin + kinerja_qc + kinerja_spv, 4)

    # 2. COMPLAIN (20%)
    # Frekuensi major (10%) — any major = 0
    complain_freq = 0.10 if major_complaints == 0 else 0.0
    # Responsibility (10%) — default pass unless total > 2
    complain_resp = 0.10 if total_complaints <= 1 else 0.0
    complain = round(complain_freq + complain_resp, 4)

    # 3. GROOMING (10%) — from HRIS or default pass
    if hris_grooming is not None:
        grooming = hris_grooming
        grooming_source = "HRIS"
    else:
        grooming = 0.10
        grooming_source = "Default"

    # 4. KUNJUNGAN (35%)
    # Jumlah kunjungan 100% (20%): actual / planned * 0.20
    kunj_jumlah = round(min(0.20, (completed / planned_noncx) * 0.20), 4)
    # Jam kunjungan 150j/9000m per month (10%): hours / 150 * 0.10
    target_hours_month = 150.0
    avg_hours_month = total_hours / kpi_months_divisor
    kunj_jam = round(min(0.10, (avg_hours_month / target_hours_month) * 0.10), 4)
    # Hari efektif (5%): active_days per month / 24 * 0.05
    target_days_month = 24.0
    avg_days_month = active_days / kpi_months_divisor
    kunj_hari = round(min(0.05, (avg_days_month / target_days_month) * 0.05), 4)

    kunjungan = round(kunj_jumlah + kunj_jam + kunj_hari, 4)

    if emp_type == "station":
        # ── STATION KPI (11 indicators, 100%) ──
        # 1. Kedisiplinan (30%): administrasi 10%, waktu 5%+10%+5%
        s_adm = 0.10 if checkin_issues == 0 else 0.05  # partial credit
        s_waktu_telat = 0.05 if late_days == 0 else 0.0
        s_kehadiran = 0.10 if (total_days_punct >= 20) else (0.05 if total_days_punct >= 18 else 0.0)
        s_izin = 0.05 if late_days <= 1 else 0.0
        s_kedisiplinan = round(s_adm + s_waktu_telat + s_kehadiran + s_izin, 4)

        # 2. Kinerja (25%): trend hama 10%, kebersihan 5%, progress 10%
        # No automated data for these — pull from HRIS or default
        s_trend = 0.10  # default pass
        s_kebersihan = 0.05  # default pass
        s_progress = 0.10  # default pass
        s_kinerja = round(s_trend + s_kebersihan + s_progress, 4)

        # 3. Complain (10%): no major complaint
        s_complain = 0.10 if major_complaints == 0 else 0.0

        # 4. Grooming (10%)
        if hris_grooming is not None:
            s_grooming = hris_grooming
        else:
            s_grooming = 0.10

        # 5. Penilaian (25%): client 15% + SPV 10%
        # From HRIS or defaults
        hris_client = None
        try:
            with _get_local_pool().connection() as lc2:
                with lc2.cursor() as lc2c:
                    lc2c.execute("SELECT id FROM hris_employees WHERE full_name = %s OR p_user_id = %s LIMIT 1", (tech["name"], tech_id))
                    he = lc2c.fetchone()
                    if he:
                        mf = f"AND s.period_month = {int(specific_month.split('-')[1])} AND s.period_year = {int(specific_month.split('-')[0])}" if specific_month else ""
                        lc2c.execute(f"SELECT t.indicator, s.score_pct FROM hris_kpi_scores s JOIN hris_kpi_templates t ON t.id = s.template_id WHERE s.employee_id = %s AND t.employee_type = 'station' {mf}", (he["id"],))
                        for row in lc2c.fetchall():
                            ind = row["indicator"].lower()
                            if "penilaian client" in ind:
                                hris_client = float(row["score_pct"])
                            elif "penilaian atasan" in ind or "spv" in ind:
                                hris_spv = float(row["score_pct"])
                                spv_source = "HRIS"
        except Exception:
            pass

        s_client_val = hris_client if hris_client is not None else 0.15
        s_client_source = "HRIS" if hris_client is not None else "Default"
        s_spv_val = hris_spv if 'hris_spv' in dir() and hris_spv is not None else kinerja_spv * 2  # scale 5% → 10%
        s_penilaian = round(s_client_val + min(0.10, s_spv_val), 4)

        total_score_pct = round((s_kedisiplinan + s_kinerja + s_complain + s_grooming + s_penilaian) * 100, 1)

        kpi_breakdown = {
            "kedisiplinan": {
                "total_pct": round(s_kedisiplinan * 100, 1), "max_pct": 30,
                "items": [
                    {"label": "Pengisian administrasi (Daily Treatment & checklist)", "bobot": 10, "score_pct": round(s_adm * 100, 1), "keterangan": f"{int(checkin_issues)} issue" if checkin_issues > 0 else "OK", "sub": "Administrasi"},
                    {"label": "Tidak ada keterlambatan lebih dari 5 menit", "bobot": 5, "score_pct": round(s_waktu_telat * 100, 1), "keterangan": f"{int(late_days)} hari telat" if late_days > 0 else "OK", "sub": "Waktu"},
                    {"label": "Kehadiran (minimal 100%)", "bobot": 10, "score_pct": round(s_kehadiran * 100, 1), "keterangan": f"{int(total_days_punct)} hari hadir", "sub": "Waktu"},
                    {"label": "Tidak izin mendadak", "bobot": 5, "score_pct": round(s_izin * 100, 1), "keterangan": "OK" if late_days <= 1 else f"{int(late_days)} hari", "sub": "Waktu"},
                ],
            },
            "kinerja": {
                "total_pct": round(s_kinerja * 100, 1), "max_pct": 25,
                "items": [
                    {"label": "Trend Hama turun / stabil", "bobot": 10, "score_pct": round(s_trend * 100, 1), "keterangan": "Default"},
                    {"label": "Kebersihan area kerja dan alat", "bobot": 5, "score_pct": round(s_kebersihan * 100, 1), "keterangan": "Default"},
                    {"label": "Melaksanakan semua progress", "bobot": 10, "score_pct": round(s_progress * 100, 1), "keterangan": "Default"},
                ],
            },
            "complain": {
                "total_pct": round(s_complain * 100, 1), "max_pct": 10,
                "items": [
                    {"label": "Tidak ada complain Major di Area", "bobot": 10, "score_pct": round(s_complain * 100, 1), "keterangan": f"{int(major_complaints)} major" if major_complaints > 0 else "OK"},
                ],
            },
            "grooming": {
                "total_pct": round(s_grooming * 100, 1), "max_pct": 10,
                "items": [
                    {"label": "Penampilan rapi, APD lengkap", "bobot": 10, "score_pct": round(s_grooming * 100, 1), "keterangan": grooming_source},
                ],
            },
            "penilaian": {
                "total_pct": round(s_penilaian * 100, 1), "max_pct": 25,
                "items": [
                    {"label": "Penilaian Client", "bobot": 15, "score_pct": round(s_client_val * 100, 1), "keterangan": s_client_source},
                    {"label": "Penilaian Atasan / SPV", "bobot": 10, "score_pct": round(min(0.10, s_spv_val) * 100, 1), "keterangan": f"({spv_source})"},
                ],
            },
            "total_score": total_score_pct,
            "employee_type": "station",
        }
    else:
        # ── MOBILE KPI (existing) ──
        total_score_pct = round((kedisiplinan + complain + grooming + kunjungan) * 100, 1)

        kpi_breakdown = {
            "kedisiplinan": {
                "total_pct": round(kedisiplinan * 100, 1), "max_pct": 35,
                "items": [
                    {"label": "Check In & Out sesuai jadwal", "bobot": 5, "score_pct": round(adm_checkinout * 100, 1), "keterangan": f"{int(checkin_issues)} issue" if checkin_issues > 0 else "OK", "sub": "Administrasi"},
                    {"label": "Kelengkapan laporan administrasi", "bobot": 5, "score_pct": round(adm_laporan * 100, 1), "keterangan": "Default", "sub": "Administrasi"},
                    {"label": "Tidak terlambat kunjungan", "bobot": 5, "score_pct": round(waktu_telat * 100, 1), "keterangan": f"{int(late_days)} hari telat" if late_days > 0 else "OK", "sub": "Waktu"},
                    {"label": "Tidak cancel treatment", "bobot": 5, "score_pct": round(waktu_cancel * 100, 1), "keterangan": f"{int(cancelled)} cancel" if cancelled > 0 else "OK", "sub": "Waktu"},
                    {"label": "Tidak izin mendadak", "bobot": 5, "score_pct": round(waktu_izin * 100, 1), "keterangan": f"{int(late_days)} hari" if late_days > 1 else "OK", "sub": "Waktu"},
                    {"label": "Penilaian Tim QC", "bobot": 5, "score_pct": round(kinerja_qc * 100, 1), "keterangan": f"{qc_value}/5 ({qc_source})", "sub": "Kinerja"},
                    {"label": "Arahan SPV", "bobot": 5, "score_pct": round(kinerja_spv * 100, 1), "keterangan": f"{spv_value}/5 ({spv_source})", "sub": "Kinerja"},
                ],
            },
            "complain": {
                "total_pct": round(complain * 100, 1), "max_pct": 20,
                "items": [
                    {"label": "Frekuensi complain major", "bobot": 10, "score_pct": round(complain_freq * 100, 1), "keterangan": f"{int(major_complaints)} major" if major_complaints > 0 else "OK"},
                    {"label": "Responsibility penanganan", "bobot": 10, "score_pct": round(complain_resp * 100, 1), "keterangan": f"{int(total_complaints)} total" if total_complaints > 1 else "OK"},
                ],
            },
            "grooming": {
                "total_pct": round(grooming * 100, 1), "max_pct": 10,
                "items": [
                    {"label": "Penampilan & APD lengkap", "bobot": 10, "score_pct": round(grooming * 100, 1), "keterangan": grooming_source},
                ],
            },
            "kunjungan": {
                "total_pct": round(kunjungan * 100, 1), "max_pct": 35,
                "items": [
                    {"label": "Jumlah kunjungan (100%)", "bobot": 20, "score_pct": round(kunj_jumlah * 100, 1), "keterangan": f"{int(completed)}/{int(planned_noncx)}"},
                    {"label": "Jam kunjungan (150j/bln)", "bobot": 10, "score_pct": round(kunj_jam * 100, 1), "keterangan": f"avg {round(avg_hours_month, 1)}j/bln"},
                    {"label": "Hari efektif", "bobot": 5, "score_pct": round(kunj_hari * 100, 1), "keterangan": f"avg {round(avg_days_month, 1)}/24 hari"},
                ],
            },
            "total_score": total_score_pct,
            "employee_type": "mobile",
        }

    if total_score_pct >= 85:
        grade = "A"
    elif total_score_pct >= 70:
        grade = "B"
    elif total_score_pct >= 55:
        grade = "C"
    else:
        grade = "D"
    kpi_breakdown["grade"] = grade

    def _fmt_row(row):
        item = dict(row)
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
            elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                item[k] = float(v)
        return item

    return jsonify({
        "technician": _fmt_row(tech),
        "grade": grade,
        "overall_metrics": _fmt_row(overall_metrics) if overall_metrics else {},
        "monthly_kpi": [_fmt_row(r) for r in monthly_kpi],
        "punctuality": [_fmt_row(r) for r in punctuality],
        "issues": [_fmt_row(r) for r in issues],
        "kpi_breakdown": kpi_breakdown,
        "period_months": months,
        "generated_at": datetime.now().isoformat(),
    })


# ── KPI History Archive ────────────────────────────────────


def _fmt(row):
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


@technicians_bp.route("/technicians/<int:tech_id>/kpi-history")
@require_auth
def technician_kpi_history(tech_id: int):
    """
    Get archived KPI history for a technician.
    Returns monthly KPI records from kpi_monthly_archive.

    Query params:
        months: Number of months to look back (default: 12)
    """
    months = int(request.args.get("months", 12))

    tech = execute_kelava_query_single(
        """
        SELECT u.id, u.fullname as name,
               COALESCE(ts.segment, 'UNASSIGNED') as segment
        FROM p_user u
        LEFT JOIN technician_segments ts ON ts.technician_id = u.id
        WHERE u.id = %s
        """,
        (tech_id,),
    )
    if not tech:
        return jsonify({"error": "Technician not found"}), 404

    rows = execute_kelava_query(
        """
        SELECT *
        FROM kpi_monthly_archive
        WHERE technician_id = %s
          AND year_month >= TO_CHAR(CURRENT_DATE - make_interval(months => %s), 'YYYY-MM')
        ORDER BY year_month DESC
        """,
        (tech_id, months),
    )

    return jsonify({
        "technician": _fmt(tech),
        "kpi_history": [_fmt(r) for r in rows],
        "months_requested": months,
        "records_found": len(rows),
        "generated_at": datetime.now().isoformat(),
    })


@technicians_bp.route("/technicians/kpi-archive")
@require_auth
def fleet_kpi_archive():
    """
    Fleet-wide KPI archive for a specific month.

    Query params:
        month: Year-month (default: current month, e.g., "2026-02")
        sort_by: visits_per_day, completion_rate, grade (default: completion_rate)
    """
    year_month = request.args.get("month")
    if not year_month:
        year_month = date.today().strftime("%Y-%m")
    sort_by = request.args.get("sort_by", "completion_rate")

    valid_sorts = {
        "visits_per_day": "kma.visits_per_day DESC",
        "completion_rate": "kma.completion_rate DESC",
        "grade": "kma.grade ASC, kma.completion_rate DESC",
        "total_visits": "kma.total_visits DESC",
    }
    order = valid_sorts.get(sort_by, "kma.completion_rate DESC")

    rows = execute_kelava_query(
        f"""
        SELECT
            kma.*,
            u.fullname as name,
            COALESCE(ts.segment, 'UNASSIGNED') as segment
        FROM kpi_monthly_archive kma
        JOIN p_user u ON u.id = kma.technician_id
        LEFT JOIN technician_segments ts ON ts.technician_id = kma.technician_id
        WHERE kma.year_month = %s
        ORDER BY {order}
        """,
        (year_month,),
    )

    # Summary stats
    grade_dist = {"A": 0, "B": 0, "C": 0, "D": 0}
    total_visits = 0
    for r in rows:
        g = r.get("grade", "D")
        if g in grade_dist:
            grade_dist[g] += 1
        total_visits += r.get("total_visits", 0)

    return jsonify({
        "year_month": year_month,
        "technicians": [_fmt(r) for r in rows],
        "total_technicians": len(rows),
        "grade_distribution": grade_dist,
        "total_visits": total_visits,
        "generated_at": datetime.now().isoformat(),
    })


@technicians_bp.route("/technicians/kpi-archive/recompute", methods=["POST"])
@require_auth
def recompute_current_month():
    """
    Recompute KPI archive for current month (or specified month).
    Body: { month?: "2026-02" }
    """
    from kil.backend.scripts.backfill_kpi_archive import backfill

    data = request.json or {}
    month = data.get("month")

    if month:
        backfill(since=month, current_month_only=False)
    else:
        backfill(current_month_only=True)

    return jsonify({
        "message": "KPI archive recomputed",
        "month": month or date.today().strftime("%Y-%m"),
    })


@technicians_bp.route("/technicians/kpi-archive/available-months")
@require_auth
def available_kpi_months():
    """Get list of months that have KPI archive data."""
    rows = execute_kelava_query(
        """
        SELECT DISTINCT year_month,
               COUNT(*) as technician_count
        FROM kpi_monthly_archive
        GROUP BY year_month
        ORDER BY year_month DESC
        """,
    )

    return jsonify({
        "months": [_fmt(r) for r in rows],
        "generated_at": datetime.now().isoformat(),
    })
