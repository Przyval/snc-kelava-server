"""
Dashboard Stats Widget API
============================
Single compact endpoint returning all key numbers
for the executive dashboard cards/widgets.
Designed for fast loading — one call instead of many.
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

dashboard_stats_bp = Blueprint("dashboard_stats", __name__, url_prefix="/dashboard-stats")


# ── All-in-one Stats ──────────────────────────────────────


@dashboard_stats_bp.route("", methods=["GET"])
@require_auth
def get_stats():
    """
    Single endpoint returning all dashboard KPIs.
    Optimized for the executive overview cards.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Today's visits
    visits_today = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS planned,
            COUNT(*) FILTER (WHERE status = 'Selesai') AS completed,
            COUNT(*) FILTER (WHERE status NOT IN ('Selesai', 'Berjalan')) AS pending,
            COUNT(DISTINCT id_user) AS active_techs,
            ROUND(COUNT(*) FILTER (WHERE status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS rate
        FROM t_road_plan
        WHERE visit_date::date = %s
        """,
        (today,),
    )

    # Yesterday's rate (for comparison arrow)
    visits_yesterday = execute_kelava_query_single(
        """
        SELECT
            ROUND(COUNT(*) FILTER (WHERE status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS rate
        FROM t_road_plan
        WHERE visit_date::date = %s
        """,
        (yesterday,),
    )

    # 7-day rolling
    week_stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS planned,
            COUNT(*) FILTER (WHERE status = 'Selesai') AS completed,
            ROUND(COUNT(*) FILTER (WHERE status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS rate,
            COUNT(DISTINCT id_user) AS techs,
            COUNT(DISTINCT id_customer) AS customers
        FROM t_road_plan
        WHERE visit_date >= CURRENT_DATE - 7
        """
    )

    # 30-day rolling
    month_stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS planned,
            COUNT(*) FILTER (WHERE status = 'Selesai') AS completed,
            ROUND(COUNT(*) FILTER (WHERE status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS rate
        FROM t_road_plan
        WHERE visit_date >= CURRENT_DATE - 30
        """
    )

    # Active contracts
    contracts = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE is_active = 'YES' AND end_date >= CURRENT_DATE) AS active,
            COUNT(*) FILTER (WHERE is_active = 'YES' AND end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 30) AS expiring_30d,
            COUNT(*) FILTER (WHERE is_active = 'YES' AND end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7) AS expiring_7d
        FROM m_customer_kontrak
        """
    )

    # Open complaints
    try:
        complaints = execute_kelava_query_single(
            """
            SELECT
                COUNT(*) AS total_open,
                COUNT(*) FILTER (WHERE priority = 'high') AS high_priority,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours') AS new_24h
            FROM complaints
            WHERE status NOT IN ('resolved', 'closed')
            """
        )
    except Exception:
        complaints = None

    # Unread notifications count
    try:
        notif_count = execute_kelava_query_single(
            "SELECT COUNT(*) AS cnt FROM enterprise_notifications WHERE read_at IS NULL"
        )
    except Exception:
        notif_count = None

    # Determine rate delta
    today_rate = float(visits_today["rate"]) if visits_today and visits_today.get("rate") else 0
    yesterday_rate = float(visits_yesterday["rate"]) if visits_yesterday and visits_yesterday.get("rate") else 0
    rate_delta = round(today_rate - yesterday_rate, 1)

    def _safe(row, key, default=0):
        if not row:
            return default
        v = row.get(key)
        return v if v is not None else default

    return jsonify({
        "generated_at": datetime.now().isoformat(),
        "today": {
            "date": today,
            "planned": _safe(visits_today, "planned"),
            "completed": _safe(visits_today, "completed"),
            "pending": _safe(visits_today, "pending"),
            "active_techs": _safe(visits_today, "active_techs"),
            "rate": today_rate,
            "rate_delta": rate_delta,
            "rate_trend": "up" if rate_delta > 0 else ("down" if rate_delta < 0 else "flat"),
        },
        "week": {
            "planned": _safe(week_stats, "planned"),
            "completed": _safe(week_stats, "completed"),
            "rate": float(_safe(week_stats, "rate")),
            "techs": _safe(week_stats, "techs"),
            "customers": _safe(week_stats, "customers"),
        },
        "month": {
            "planned": _safe(month_stats, "planned"),
            "completed": _safe(month_stats, "completed"),
            "rate": float(_safe(month_stats, "rate")),
        },
        "contracts": {
            "active": _safe(contracts, "active"),
            "expiring_7d": _safe(contracts, "expiring_7d"),
            "expiring_30d": _safe(contracts, "expiring_30d"),
        },
        "complaints": {
            "total_open": _safe(complaints, "total_open"),
            "high_priority": _safe(complaints, "high_priority"),
            "new_24h": _safe(complaints, "new_24h"),
        },
        "notifications": {
            "unread": _safe(notif_count, "cnt"),
        },
    })
