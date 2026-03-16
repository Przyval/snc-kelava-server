"""
Performance Trends API
========================
Historical KPI tracking per technician and overall:
- Weekly/monthly completion rates
- Trend direction (improving/declining)
- Peer comparison percentiles
- Customer coverage trends
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

trends_bp = Blueprint("trends", __name__, url_prefix="/trends")


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Overall Weekly Trends ──────────────────────────────────


@trends_bp.route("/weekly", methods=["GET"])
@require_auth
def weekly_trends():
    """
    Overall weekly completion trends for the past N weeks.
    Query params: weeks (default 12)
    """
    weeks = min(int(request.args.get("weeks", 12)), 52)

    rows = execute_kelava_query(
        """
        SELECT
            DATE_TRUNC('week', rp.visit_date)::date AS week_start,
            COUNT(*) AS total_planned,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            COUNT(DISTINCT rp.id_user) AS active_techs,
            COUNT(DISTINCT rp.id_customer) AS unique_customers,
            ROUND(COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS completion_rate
        FROM t_road_plan rp
        WHERE rp.visit_date >= CURRENT_DATE - (%s * 7)
        GROUP BY DATE_TRUNC('week', rp.visit_date)
        ORDER BY week_start
        """,
        (weeks,),
    )

    # Compute trend direction
    data = [_fmt(r) for r in rows]
    trend = "stable"
    if len(data) >= 3:
        recent = [r["completion_rate"] for r in data[-3:] if r.get("completion_rate")]
        older = [r["completion_rate"] for r in data[:3] if r.get("completion_rate")]
        if recent and older:
            avg_recent = sum(float(x) for x in recent) / len(recent)
            avg_older = sum(float(x) for x in older) / len(older)
            if avg_recent > avg_older + 3:
                trend = "improving"
            elif avg_recent < avg_older - 3:
                trend = "declining"

    return jsonify({"weeks": data, "trend": trend, "period_weeks": weeks})


# ── Technician Performance Trend ───────────────────────────


@trends_bp.route("/technician/<int:tech_id>", methods=["GET"])
@require_auth
def technician_trend(tech_id: int):
    """
    Performance trend for a specific technician.
    Query params: weeks (default 12)
    """
    weeks = min(int(request.args.get("weeks", 12)), 52)

    # Weekly breakdown
    weekly = execute_kelava_query(
        """
        SELECT
            DATE_TRUNC('week', rp.visit_date)::date AS week_start,
            COUNT(*) AS planned,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            ROUND(COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS rate,
            COUNT(DISTINCT rp.id_customer) AS customers
        FROM t_road_plan rp
        WHERE rp.id_user = %s AND rp.visit_date >= CURRENT_DATE - (%s * 7)
        GROUP BY DATE_TRUNC('week', rp.visit_date)
        ORDER BY week_start
        """,
        (tech_id, weeks),
    )

    # Average duration trend (from visits with check-in/out)
    duration_trend = execute_kelava_query(
        """
        SELECT
            DATE_TRUNC('week', rp.visit_date)::date AS week_start,
            ROUND(AVG(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 0) AS avg_duration_min,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP
                  (ORDER BY EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 0) AS median_duration_min
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE rp.id_user = %s
          AND rp.visit_date >= CURRENT_DATE - (%s * 7)
          AND v.check_in IS NOT NULL AND v.check_out IS NOT NULL
          AND v.check_out > v.check_in
          AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) BETWEEN 60 AND 28800
        GROUP BY DATE_TRUNC('week', rp.visit_date)
        ORDER BY week_start
        """,
        (tech_id, weeks),
    )

    # Peer comparison (percentile rank)
    peer = execute_kelava_query_single(
        """
        WITH tech_rates AS (
            SELECT rp.id_user,
                   ROUND(COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric
                         / NULLIF(COUNT(*), 0) * 100, 1) AS rate
            FROM t_road_plan rp
            WHERE rp.visit_date >= CURRENT_DATE - 30
            GROUP BY rp.id_user
            HAVING COUNT(*) >= 5
        )
        SELECT
            rate,
            ROUND(PERCENT_RANK() OVER (ORDER BY rate) * 100)::int AS percentile
        FROM tech_rates
        WHERE id_user = %s
        """,
        (tech_id,),
    )

    # Trend direction
    data = [_fmt(r) for r in weekly]
    trend = "stable"
    if len(data) >= 4:
        rates = [float(r["rate"]) for r in data if r.get("rate") is not None]
        if len(rates) >= 4:
            first_half = sum(rates[:len(rates)//2]) / (len(rates)//2)
            second_half = sum(rates[len(rates)//2:]) / (len(rates) - len(rates)//2)
            if second_half > first_half + 3:
                trend = "improving"
            elif second_half < first_half - 3:
                trend = "declining"

    return jsonify({
        "tech_id": tech_id,
        "weekly": data,
        "duration_trend": [_fmt(r) for r in duration_trend],
        "peer_comparison": _fmt(peer) if peer else {"rate": None, "percentile": None},
        "trend": trend,
        "period_weeks": weeks,
    })


# ── All Technicians Comparison ─────────────────────────────


@trends_bp.route("/comparison", methods=["GET"])
@require_auth
def technician_comparison():
    """
    Compare all technicians' performance for a given period.
    Query params: days (default 30)
    """
    days = min(int(request.args.get("days", 30)), 365)

    rows = execute_kelava_query(
        """
        SELECT
            rp.id_user AS tech_id,
            u.fullname AS name,
            COUNT(*) AS planned,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            ROUND(COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS rate,
            COUNT(DISTINCT rp.visit_date) AS active_days,
            COUNT(DISTINCT rp.id_customer) AS customers,
            ROUND(AVG(CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                            AND v.check_out > v.check_in
                            AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) BETWEEN 60 AND 28800
                       THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 END)::numeric, 0)
                AS avg_duration_min
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.visit_date >= CURRENT_DATE - %s
        GROUP BY rp.id_user, u.fullname
        HAVING COUNT(*) >= 3
        ORDER BY rate DESC
        """,
        (days,),
    )

    data = [_fmt(r) for r in rows]
    rates = [float(r["rate"]) for r in data if r.get("rate") is not None]

    return jsonify({
        "technicians": data,
        "summary": {
            "total_techs": len(data),
            "avg_rate": round(sum(rates) / len(rates), 1) if rates else 0,
            "top_rate": max(rates) if rates else 0,
            "bottom_rate": min(rates) if rates else 0,
        },
        "period_days": days,
    })


# ── Customer Coverage Trend ────────────────────────────────


@trends_bp.route("/coverage", methods=["GET"])
@require_auth
def coverage_trend():
    """
    Monthly customer coverage: how many unique customers visited vs total.
    Query params: months (default 6)
    """
    months = min(int(request.args.get("months", 6)), 24)

    rows = execute_kelava_query(
        """
        SELECT
            DATE_TRUNC('month', rp.visit_date)::date AS month,
            COUNT(DISTINCT rp.id_customer) AS visited_customers,
            COUNT(DISTINCT CASE WHEN rp.status = 'Selesai' THEN rp.id_customer END) AS completed_customers,
            COUNT(*) AS total_plans,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed_visits
        FROM t_road_plan rp
        WHERE rp.visit_date >= CURRENT_DATE - (%s * 30)
        GROUP BY DATE_TRUNC('month', rp.visit_date)
        ORDER BY month
        """,
        (months,),
    )

    # Total active customers (with active contract)
    total_customers = execute_kelava_query_single(
        """
        SELECT COUNT(DISTINCT id_customer) AS cnt
        FROM m_customer_kontrak
        WHERE is_active = 'YES' AND end_date >= CURRENT_DATE
        """
    )

    return jsonify({
        "monthly": [_fmt(r) for r in rows],
        "total_active_customers": total_customers["cnt"] if total_customers else 0,
        "period_months": months,
    })
