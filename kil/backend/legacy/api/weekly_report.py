"""
Automated Weekly Report API
=============================
Generates weekly operations summary:
- Visit completion rates
- Technician performance ranking
- Complaint summary
- Contract renewal alerts
- Data quality flags

Can be triggered via cron or on-demand from the dashboard.
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single
from kil.backend.legacy.api.audit_log import log_action

weekly_report_bp = Blueprint("weekly_report", __name__, url_prefix="/weekly-report")

_TABLE_ENSURED = False


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Generate Report ──────────────────────────────────────────


@weekly_report_bp.route("/generate", methods=["POST"])
@require_auth
def generate_report():
    """
    Generate a weekly report for the given week.
    Body: { week_start?: "YYYY-MM-DD" }  (defaults to last Monday)
    """
    data = request.json or {}
    week_start_str = data.get("week_start")

    if week_start_str:
        week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
    else:
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())  # Monday
        if today.weekday() < 1:  # If Mon/Tue, use previous week
            week_start = week_start - timedelta(days=7)

    week_end = week_start + timedelta(days=6)

    report = _build_report(week_start, week_end)

    # Store report
    _ensure_table()
    stored = execute_kelava_query_single(
        """
        INSERT INTO weekly_reports (week_start, week_end, report_data)
        VALUES (%s, %s, %s)
        ON CONFLICT (week_start)
        DO UPDATE SET report_data = EXCLUDED.report_data, generated_at = NOW()
        RETURNING id
        """,
        (week_start, week_end, _report_to_json(report)),
    )

    log_action("weekly_report", "create", "report", stored["id"] if stored else None,
               f"Weekly report {week_start} to {week_end}")

    return jsonify({"report": report, "stored_id": stored["id"] if stored else None})


@weekly_report_bp.route("/latest", methods=["GET"])
@require_auth
def latest_report():
    """Get the most recent weekly report."""
    _ensure_table()
    row = execute_kelava_query_single(
        """
        SELECT * FROM weekly_reports
        ORDER BY week_start DESC LIMIT 1
        """
    )
    if not row:
        return jsonify({"error": "No reports generated yet"}), 404
    return jsonify({"report": _fmt(row)})


@weekly_report_bp.route("/history", methods=["GET"])
@require_auth
def report_history():
    """List all generated weekly reports."""
    _ensure_table()
    rows = execute_kelava_query(
        """
        SELECT id, week_start, week_end, generated_at
        FROM weekly_reports
        ORDER BY week_start DESC
        LIMIT 52
        """
    )
    return jsonify({"reports": [_fmt(r) for r in rows]})


@weekly_report_bp.route("/<int:report_id>", methods=["GET"])
@require_auth
def get_report(report_id: int):
    """Get a specific weekly report by ID."""
    _ensure_table()
    row = execute_kelava_query_single(
        "SELECT * FROM weekly_reports WHERE id = %s",
        (report_id,),
    )
    if not row:
        return jsonify({"error": "Report not found"}), 404
    return jsonify({"report": _fmt(row)})


# ── Preview (no save) ────────────────────────────────────────


@weekly_report_bp.route("/preview", methods=["GET"])
@require_auth
def preview_report():
    """Preview this week's report without saving."""
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    report = _build_report(week_start, week_end)
    return jsonify({"report": report, "preview": True})


# ── Report Builder ───────────────────────────────────────────


def _build_report(week_start, week_end) -> dict:
    """Build the complete weekly report data."""

    # 1. Visit completion
    visit_stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total_planned,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            COUNT(*) FILTER (WHERE rp.status NOT IN ('Selesai', 'Berjalan')) AS not_visited,
            COUNT(DISTINCT rp.id_user) AS active_technicians,
            COUNT(DISTINCT rp.id_customer) AS customers_served
        FROM t_road_plan rp
        WHERE rp.visit_date::date BETWEEN %s AND %s
        """,
        (week_start, week_end),
    )

    # 2. Technician ranking
    tech_ranking = execute_kelava_query(
        """
        SELECT
            u.id, u.fullname,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            COUNT(*) AS planned,
            ROUND(
                COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric /
                NULLIF(COUNT(*), 0) * 100, 1
            ) AS completion_rate,
            ROUND(AVG(
                EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60
            )::numeric, 1) AS avg_duration_min
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.visit_date::date BETWEEN %s AND %s
        GROUP BY u.id, u.fullname
        HAVING COUNT(*) >= 3
        ORDER BY completion_rate DESC, completed DESC
        LIMIT 20
        """,
        (week_start, week_end),
    )

    # 3. Complaint summary
    complaint_stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'open') AS open_count,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
            COUNT(*) FILTER (WHERE status = 'resolved') AS resolved,
            COUNT(*) FILTER (WHERE severity = 'critical') AS critical_count,
            COUNT(*) FILTER (WHERE severity = 'high') AS high_count
        FROM complaint_tickets
        WHERE created_at >= %s AND created_at < %s + INTERVAL '1 day'
        """,
        (week_start, week_end),
    )

    # 4. Contract alerts
    contract_alerts = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) FILTER (WHERE end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days') AS expiring_30d,
            COUNT(*) FILTER (WHERE end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '60 days') AS expiring_60d,
            COUNT(*) FILTER (WHERE end_date < CURRENT_DATE AND end_date >= CURRENT_DATE - INTERVAL '7 days') AS just_expired
        FROM m_customer_kontrak
        WHERE UPPER(TRIM(COALESCE(is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
        """
    )

    # 5. Visit duration stats
    duration_stats = execute_kelava_query_single(
        """
        SELECT
            ROUND(AVG(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 1) AS avg_min,
            ROUND(MIN(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 1) AS min_min,
            ROUND(MAX(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 1) AS max_min,
            COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 < 15) AS under_15min,
            COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 > 120) AS over_2h
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE rp.visit_date::date BETWEEN %s AND %s
          AND v.check_out IS NOT NULL AND v.check_in IS NOT NULL
        """,
        (week_start, week_end),
    )

    # 6. Day-by-day breakdown
    daily = execute_kelava_query(
        """
        SELECT
            rp.visit_date AS date,
            COUNT(*) AS planned,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            COUNT(DISTINCT rp.id_user) AS technicians
        FROM t_road_plan rp
        WHERE rp.visit_date::date BETWEEN %s AND %s
        GROUP BY rp.visit_date
        ORDER BY rp.visit_date
        """,
        (week_start, week_end),
    )

    planned = (visit_stats["total_planned"] or 0) if visit_stats else 0
    completed = (visit_stats["completed"] or 0) if visit_stats else 0
    completion_rate = round(completed / planned * 100, 1) if planned > 0 else 0

    return {
        "week_start": str(week_start),
        "week_end": str(week_end),
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_planned": planned,
            "total_completed": completed,
            "completion_rate": completion_rate,
            "active_technicians": (visit_stats["active_technicians"] or 0) if visit_stats else 0,
            "customers_served": (visit_stats["customers_served"] or 0) if visit_stats else 0,
        },
        "technician_ranking": [_fmt(t) for t in tech_ranking],
        "complaints": _fmt(complaint_stats) if complaint_stats else {},
        "contract_alerts": _fmt(contract_alerts) if contract_alerts else {},
        "duration_stats": _fmt(duration_stats) if duration_stats else {},
        "daily_breakdown": [_fmt(d) for d in daily],
    }


def _report_to_json(report: dict) -> str:
    """Convert report dict to JSON string for storage."""
    import json
    return json.dumps(report, default=str)


def _ensure_table():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS weekly_reports (
            id BIGSERIAL PRIMARY KEY,
            week_start DATE NOT NULL UNIQUE,
            week_end DATE NOT NULL,
            report_data JSONB,
            generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    execute_kelava_query(
        "CREATE INDEX IF NOT EXISTS idx_weekly_reports_start ON weekly_reports(week_start DESC)"
    )
    _TABLE_ENSURED = True
