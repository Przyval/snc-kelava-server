"""
Technicians API
================
API endpoints for technician performance tracking and leaderboard.
Connects to Kelava live database.
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

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
    """
    months = int(request.args.get("months", 3))

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

    # Calculate overall grade
    overall_metrics = execute_kelava_query_single(
        """
        WITH stats AS (
            SELECT
                COUNT(*) as total_planned,
                COUNT(*) FILTER (WHERE rp.status = 'Selesai') as completed,
                COUNT(DISTINCT rp.visit_date::date) as active_days
            FROM t_road_plan rp
            WHERE rp.id_user = %s
              AND rp.visit_date::date >= CURRENT_DATE - 90
              AND COALESCE(rp.is_cancel, false) = false
        ),
        vstats AS (
            SELECT COUNT(v.id) as total_visits
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE rp.id_user = %s
              AND v.realization_date >= CURRENT_DATE - 90
        )
        SELECT
            s.total_planned,
            s.completed,
            s.active_days,
            v.total_visits,
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
        (tech_id, tech_id),
    )

    # Grade calculation
    grade = "D"
    if overall_metrics:
        vpd = float(overall_metrics.get("visits_per_day", 0))
        cr = float(overall_metrics.get("completion_rate", 0))
        score = (vpd / 4 * 40) + (cr / 100 * 60)  # 40% volume, 60% completion
        if score >= 80:
            grade = "A"
        elif score >= 65:
            grade = "B"
        elif score >= 50:
            grade = "C"

    def _fmt_row(row):
        item = dict(row)
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        return item

    return jsonify({
        "technician": _fmt_row(tech),
        "grade": grade,
        "overall_metrics": _fmt_row(overall_metrics) if overall_metrics else {},
        "monthly_kpi": [_fmt_row(r) for r in monthly_kpi],
        "punctuality": [_fmt_row(r) for r in punctuality],
        "issues": [_fmt_row(r) for r in issues],
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
