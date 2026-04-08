"""
Priority Watchlist API
======================
AT_RISK and P1/P2 customer watchlist powered by the ontology views.
Includes revenue-at-risk calculations and due-visit forecasting.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from core.security import require_auth
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

watchlist_bp = Blueprint("watchlist", __name__)


def _fmt(row):
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif hasattr(v, "__float__"):
            # Decimal → float for JSON serialization
            d[k] = float(v)
    return d


@watchlist_bp.route("/watchlist")
@require_auth
def priority_watchlist():
    """
    Priority watchlist: all P1/P2 customers OR account_status AT_RISK/OVERDUE.
    Query params:
        priority: P1 | P2  (filter)
        status:   AT_RISK | OVERDUE | INACTIVE  (filter)
        limit:    max rows (default 200)
    """
    priority_filter = request.args.get("priority")
    status_filter = request.args.get("status")
    limit = min(int(request.args.get("limit", 200)), 500)

    conditions = [
        "(pa.priority IN ('P1', 'P2') OR rfm.account_status IN ('AT_RISK', 'OVERDUE'))"
    ]
    params: list = []

    if priority_filter in ("P1", "P2"):
        conditions.append("pa.priority = %s")
        params.append(priority_filter)
    if status_filter in ("AT_RISK", "OVERDUE", "INACTIVE"):
        conditions.append("rfm.account_status = %s")
        params.append(status_filter)

    params.append(limit)
    where = " AND ".join(conditions)

    rows = execute_kelava_query(
        f"""
        SELECT
            c.id, c.name, c.code, c.address,
            rfm.rfm_segment, rfm.days_since_last_visit, rfm.missed_cycles,
            rfm.account_status, rfm.value_monthly, rfm.has_active_contract,
            rfm.last_completed_visit_at, rfm.expected_cycle_days,
            pa.priority, pa.suggested_action, pa.ui_badge, pa.reason, pa.owner
        FROM m_customer c
        JOIN v_customer_rfm_segment rfm ON rfm.customer_id = c.id
        JOIN v_customer_priority_action pa ON pa.customer_id = c.id
        WHERE {where}
        ORDER BY
            CASE pa.priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
            CASE rfm.account_status WHEN 'OVERDUE' THEN 1 WHEN 'AT_RISK' THEN 2 ELSE 3 END,
            COALESCE(rfm.missed_cycles, 0) DESC,
            rfm.days_since_last_visit DESC NULLS LAST
        LIMIT %s
        """,
        tuple(params),
    )

    # Aggregate stats + revenue at risk (unfiltered — always full picture)
    stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) FILTER (WHERE pa.priority = 'P1') AS p1_count,
            COUNT(*) FILTER (WHERE pa.priority = 'P2') AS p2_count,
            COUNT(*) FILTER (WHERE rfm.account_status = 'AT_RISK') AS at_risk_count,
            COUNT(*) FILTER (WHERE rfm.account_status = 'OVERDUE') AS overdue_count,
            COUNT(*) FILTER (WHERE rfm.account_status = 'INACTIVE') AS inactive_count,
            COALESCE(SUM(rfm.value_monthly) FILTER (
                WHERE pa.priority IN ('P1','P2')
                   OR rfm.account_status IN ('AT_RISK','OVERDUE')
            ), 0) AS revenue_at_risk,
            COALESCE(SUM(rfm.value_monthly) FILTER (WHERE pa.priority = 'P1'), 0) AS p1_revenue,
            COALESCE(SUM(rfm.value_monthly) FILTER (WHERE pa.priority = 'P2'), 0) AS p2_revenue,
            COALESCE(SUM(rfm.value_monthly) FILTER (
                WHERE rfm.account_status = 'OVERDUE'
            ), 0) AS overdue_revenue
        FROM m_customer c
        JOIN v_customer_rfm_segment rfm ON rfm.customer_id = c.id
        JOIN v_customer_priority_action pa ON pa.customer_id = c.id
        WHERE pa.priority IN ('P1', 'P2')
           OR rfm.account_status IN ('AT_RISK', 'OVERDUE')
        """
    )

    s = stats or {}

    return jsonify(
        {
            "stats": {
                "p1_count": s.get("p1_count") or 0,
                "p2_count": s.get("p2_count") or 0,
                "at_risk_count": s.get("at_risk_count") or 0,
                "overdue_count": s.get("overdue_count") or 0,
                "inactive_count": s.get("inactive_count") or 0,
                "revenue_at_risk": float(s.get("revenue_at_risk") or 0),
                "p1_revenue": float(s.get("p1_revenue") or 0),
                "p2_revenue": float(s.get("p2_revenue") or 0),
                "overdue_revenue": float(s.get("overdue_revenue") or 0),
            },
            "customers": [_fmt(r) for r in (rows or [])],
            "total": len(rows or []),
            "generated_at": datetime.now().isoformat(),
        }
    )


@watchlist_bp.route("/due-visits")
@require_auth
def due_visits():
    """
    Customers whose scheduled visit is due within the next N days.
    Calculated from: last_completed_visit_at::date + expected_cycle_days

    Query params:
        days: forecast horizon in days (default 30, max 90)
    """
    horizon = min(int(request.args.get("days", 30)), 90)

    rows = execute_kelava_query(
        """
        SELECT
            c.id, c.name, c.code,
            rfm.last_completed_visit_at::date AS last_visit,
            rfm.expected_cycle_days,
            rfm.value_monthly,
            pa.priority,
            (rfm.last_completed_visit_at::date + rfm.expected_cycle_days) AS due_date,
            (rfm.last_completed_visit_at::date + rfm.expected_cycle_days
             - CURRENT_DATE) AS days_until_due
        FROM m_customer c
        JOIN v_customer_rfm_segment rfm ON rfm.customer_id = c.id
        JOIN v_customer_priority_action pa ON pa.customer_id = c.id
        WHERE rfm.has_active_contract = true
          AND rfm.last_completed_visit_at IS NOT NULL
          AND rfm.expected_cycle_days IS NOT NULL
          AND rfm.expected_cycle_days > 0
          AND (rfm.last_completed_visit_at::date + rfm.expected_cycle_days)
              BETWEEN CURRENT_DATE AND CURRENT_DATE + %s
        ORDER BY due_date ASC
        LIMIT 100
        """,
        (horizon,),
    )

    customers = [_fmt(r) for r in (rows or [])]

    # Bucket counts
    buckets = {"7d": 0, "14d": 0, "30d": 0}
    for c in customers:
        d = c.get("days_until_due") or 0
        if d <= 7:
            buckets["7d"] += 1
        if d <= 14:
            buckets["14d"] += 1
        buckets["30d"] += 1

    return jsonify(
        {
            "customers": customers,
            "total": len(customers),
            "buckets": buckets,
            "horizon_days": horizon,
            "generated_at": datetime.now().isoformat(),
        }
    )
