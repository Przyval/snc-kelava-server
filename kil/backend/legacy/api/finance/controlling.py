"""
Controlling (CO) Blueprint
===========================
Cost Center P&L, Budget vs Actual, Variance Analysis,
Profit Center Reporting, Internal Orders.
"""

from datetime import date

from flask import Blueprint, request

from .core import (
    err, fin_execute, fin_execute_returning, fin_query,
    ok, require_finance_role, row_to_dict, rows_to_list, to_idr,
)
from kil.backend.core.security import require_auth

co_bp = Blueprint("finance_co", __name__, url_prefix="/api/v1/finance/co")


# ── Cost Centers ──────────────────────────────────────────────

@co_bp.get("/cost-centers")
@require_auth
@require_finance_role
def list_cost_centers():
    rows = fin_query(
        """
        SELECT cc.*,
               COALESCE(ytd.actual_ytd, 0)  AS actual_ytd,
               COALESCE(ytd.budget_ytd, 0)  AS budget_ytd,
               COALESCE(ytd.variance_ytd, 0) AS variance_ytd
        FROM   fin_cost_centers cc
        LEFT JOIN v_fin_cost_center_ytd ytd ON ytd.cost_center_id = cc.id
        ORDER  BY cc.name
        """, many=True,
    )
    return ok(rows_to_list(rows))


@co_bp.get("/cost-centers/<int:cc_id>/pl")
@require_auth
@require_finance_role
def cost_center_pl(cc_id: int):
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    conditions = ["gl.cost_center_id = %s", "je.status = 'POSTED'", "fp.year = %s"]
    params = [cc_id, year]
    if month:
        conditions.append("fp.period = %s")
        params.append(month)

    rows = fin_query(
        f"""
        SELECT
            gl.account_code,
            fa.name                      AS account_name,
            fa.account_type,
            fp.period                    AS month,
            SUM(gl.debit)                AS total_debit,
            SUM(gl.credit)               AS total_credit,
            SUM(gl.debit - gl.credit)    AS net_amount
        FROM fin_gl_lines gl
        JOIN fin_journal_entries je ON je.id = gl.journal_entry_id
        JOIN fin_fiscal_periods  fp ON fp.id = je.period_id
        LEFT JOIN fin_accounts   fa ON fa.code = gl.account_code
        WHERE {' AND '.join(conditions)}
        GROUP BY gl.account_code, fa.name, fa.account_type, fp.period
        ORDER BY fa.account_type, gl.account_code
        """,
        params, many=True,
    )
    return ok(rows_to_list(rows))


# ── Profit Centers ────────────────────────────────────────────

@co_bp.get("/profit-centers")
@require_auth
@require_finance_role
def list_profit_centers():
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    conditions = ["fp.year = %s"]
    params: list = [year]
    if month:
        conditions.append("fp.period = %s")
        params.append(month)
    else:
        conditions.append("fp.period <= %s")
        params.append(date.today().month)

    rows = fin_query(
        f"""
        SELECT
            pl.profit_center_id,
            pl.profit_center,
            pl.service_type,
            SUM(pl.revenue) AS revenue,
            SUM(pl.cogs)    AS cogs,
            SUM(pl.opex)    AS opex,
            SUM(pl.net_profit) AS net_profit,
            CASE WHEN SUM(pl.revenue) > 0
                 THEN ROUND(SUM(pl.net_profit) / SUM(pl.revenue) * 100, 2)
                 ELSE 0
            END AS margin_pct
        FROM v_fin_profit_center_pl pl
        JOIN fin_fiscal_periods fp
            ON fp.year = pl.year AND fp.period = pl.month
        WHERE {' AND '.join(conditions)}
        GROUP BY pl.profit_center_id, pl.profit_center, pl.service_type
        ORDER BY revenue DESC
        """,
        params, many=True,
    )
    return ok(rows_to_list(rows))


# ── Budget Management ─────────────────────────────────────────

@co_bp.get("/budgets")
@require_auth
@require_finance_role
def list_budgets():
    year = request.args.get("year", date.today().year, type=int)
    cc   = request.args.get("cost_center_id", type=int)

    conditions = ["b.year = %s"]
    params: list = [year]
    if cc:
        conditions.append("b.cost_center_id = %s")
        params.append(cc)

    rows = fin_query(
        f"""
        SELECT b.*,
               cc.name AS cost_center_name,
               fa.name AS account_name,
               fa.account_type
        FROM   fin_budgets b
        LEFT JOIN fin_cost_centers cc ON cc.id = b.cost_center_id
        LEFT JOIN fin_accounts     fa ON fa.code = b.account_code
        WHERE  {' AND '.join(conditions)}
        ORDER  BY b.year, b.period, cc.name, b.account_code
        """,
        params, many=True,
    )
    return ok(rows_to_list(rows))


@co_bp.post("/budgets")
@require_auth
@require_finance_role
def upsert_budget():
    """Create or update a budget line. Idempotent via ON CONFLICT."""
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["year", "period", "cost_center_id", "account_code", "amount"]
    if not all(d.get(k) is not None for k in required):
        return err(f"Required: {required}")

    row = fin_execute_returning(
        """
        INSERT INTO fin_budgets
            (year, period, cost_center_id, profit_center_id, account_code,
             amount, description, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (year, period, cost_center_id, account_code)
        DO UPDATE SET
            amount      = EXCLUDED.amount,
            description = EXCLUDED.description
        RETURNING *
        """,
        [d["year"], d["period"], d["cost_center_id"],
         d.get("profit_center_id"), d["account_code"],
         float(to_idr(d["amount"])), d.get("description"), user],
    )
    return ok(row_to_dict(row), "Budget saved", 201)


@co_bp.post("/budgets/bulk")
@require_auth
@require_finance_role
def bulk_upsert_budgets():
    """Upload full budget matrix: [{year,period,cost_center_id,account_code,amount}]"""
    lines = request.get_json()
    user  = request.environ.get("user_email", "system")
    if not isinstance(lines, list) or not lines:
        return err("Expected non-empty array")

    saved = 0
    for d in lines:
        if not all(d.get(k) is not None for k in ["year","period","cost_center_id","account_code","amount"]):
            continue
        fin_execute(
            """
            INSERT INTO fin_budgets
                (year, period, cost_center_id, account_code, amount, description, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (year, period, cost_center_id, account_code)
            DO UPDATE SET amount = EXCLUDED.amount
            """,
            [d["year"], d["period"], d["cost_center_id"], d["account_code"],
             float(to_idr(d["amount"])), d.get("description"), user],
        )
        saved += 1
    return ok({"saved": saved}, f"{saved} budget lines saved")


# ── Budget vs Actual ──────────────────────────────────────────

@co_bp.get("/budget-vs-actual")
@require_auth
@require_finance_role
def budget_vs_actual():
    year = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)
    cc    = request.args.get("cost_center_id", type=int)

    conditions = ["bva.year = %s"]
    params: list = [year]
    if month:
        conditions.append("bva.month = %s"); params.append(month)
    if cc:
        conditions.append("cc.id = %s"); params.append(cc)

    rows = fin_query(
        f"""
        SELECT bva.*, cc.name AS cost_center_name
        FROM   v_fin_budget_vs_actual_detail bva
        JOIN   fin_cost_centers cc ON cc.name = bva.cost_center
        WHERE  {' AND '.join(conditions)}
        ORDER  BY bva.cost_center, bva.month, bva.account_code
        LIMIT 500
        """,
        params, many=True,
    )

    # Aggregate summary
    summary: dict[str, dict] = {}
    for r in rows:
        cc_name = r["cost_center"]
        if cc_name not in summary:
            summary[cc_name] = {"cost_center": cc_name, "budget": 0, "actual": 0, "variance": 0}
        summary[cc_name]["budget"]   += float(r["budget"] or 0)
        summary[cc_name]["actual"]   += float(r["actual"] or 0)
        summary[cc_name]["variance"] += float(r["variance"] or 0)

    return ok({
        "detail": rows_to_list(rows),
        "summary": list(summary.values()),
        "year": year,
        "month": month,
    })


# ── Variance Notes ────────────────────────────────────────────

@co_bp.get("/variance-notes")
@require_auth
@require_finance_role
def list_variance_notes():
    period_id = request.args.get("period_id", type=int)
    cc        = request.args.get("cost_center_id", type=int)

    conditions, params = [], []
    if period_id:
        conditions.append("vn.period_id = %s"); params.append(period_id)
    if cc:
        conditions.append("vn.cost_center_id = %s"); params.append(cc)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fin_query(
        f"""
        SELECT vn.*, cc.name AS cost_center_name,
               fp.year || '-' || LPAD(fp.period::text,2,'0') AS period_label
        FROM   fin_variance_notes vn
        LEFT JOIN fin_cost_centers cc ON cc.id = vn.cost_center_id
        LEFT JOIN fin_fiscal_periods fp ON fp.id = vn.period_id
        {where}
        ORDER BY vn.created_at DESC
        """,
        params, many=True,
    )
    return ok(rows_to_list(rows))


@co_bp.post("/variance-notes")
@require_auth
@require_finance_role
def add_variance_note():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    if not d.get("explanation"):
        return err("explanation required")

    row = fin_execute_returning(
        """
        INSERT INTO fin_variance_notes
            (period_id, cost_center_id, account_code, variance_amount,
             variance_pct, explanation, action_required, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """,
        [d.get("period_id"), d.get("cost_center_id"), d.get("account_code"),
         d.get("variance_amount"), d.get("variance_pct"),
         d["explanation"], d.get("action_required"), user],
    )
    return ok({"id": row["id"]}, "Variance note saved", 201)


# ── Internal Orders ───────────────────────────────────────────

@co_bp.get("/internal-orders")
@require_auth
@require_finance_role
def list_internal_orders():
    rows = fin_query(
        """
        SELECT io.*,
               cc.name AS cost_center_name,
               pc.name AS profit_center_name,
               COALESCE(act.actual_spend, 0) AS actual_spend,
               io.budget_amount - COALESCE(act.actual_spend, 0) AS remaining
        FROM fin_internal_orders io
        LEFT JOIN fin_cost_centers cc ON cc.id = io.cost_center_id
        LEFT JOIN fin_profit_centers pc ON pc.id = io.profit_center_id
        LEFT JOIN (
            SELECT gl.internal_order_id, SUM(gl.debit - gl.credit) AS actual_spend
            FROM fin_gl_lines gl
            JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status = 'POSTED'
            WHERE gl.internal_order_id IS NOT NULL
            GROUP BY gl.internal_order_id
        ) act ON act.internal_order_id = io.id
        ORDER BY io.created_at DESC
        """, many=True,
    )
    return ok(rows_to_list(rows))


@co_bp.post("/internal-orders")
@require_auth
@require_finance_role
def create_internal_order():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    if not d.get("description"):
        return err("description required")

    # Auto-generate order number
    order_no_row = fin_query(
        "SELECT 'IO-' || EXTRACT(YEAR FROM NOW())::TEXT || '-' || LPAD((COUNT(*)+1)::TEXT,4,'0') AS no FROM fin_internal_orders"
    )
    order_no = order_no_row["no"]

    row = fin_execute_returning(
        """
        INSERT INTO fin_internal_orders
            (order_no, description, cost_center_id, profit_center_id,
             responsible_user, budget_amount, start_date, end_date, notes, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
        """,
        [order_no, d["description"], d.get("cost_center_id"),
         d.get("profit_center_id"), d.get("responsible_user"),
         float(to_idr(d.get("budget_amount", 0))),
         d.get("start_date"), d.get("end_date"), d.get("notes"), user],
    )
    return ok(row_to_dict(row), "Internal order created", 201)


# ── Cost Allocation Run ───────────────────────────────────────

@co_bp.post("/allocations")
@require_auth
@require_finance_role
def create_allocation():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["period_id", "from_cost_center_id", "to_profit_center_id", "amount"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    row = fin_execute_returning(
        """
        INSERT INTO fin_cost_allocations
            (period_id, from_cost_center_id, to_profit_center_id,
             account_code, amount, allocation_key, description, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """,
        [d["period_id"], d["from_cost_center_id"], d["to_profit_center_id"],
         d.get("account_code", "6001"), float(to_idr(d["amount"])),
         d.get("allocation_key", "MANUAL"), d.get("description"), user],
    )
    return ok({"id": row["id"]}, "Allocation recorded", 201)


# ── Dashboard Summary ─────────────────────────────────────────

@co_bp.get("/dashboard")
@require_auth
@require_finance_role
def co_dashboard():
    year = request.args.get("year", date.today().year, type=int)

    # Cost center YTD
    cc_rows = fin_query(
        "SELECT * FROM v_fin_cost_center_ytd", many=True
    )

    # Profit center YTD
    pc_rows = fin_query(
        """
        SELECT profit_center_id, profit_center, service_type,
               SUM(revenue) AS revenue, SUM(cogs) AS cogs,
               SUM(opex) AS opex, SUM(net_profit) AS net_profit
        FROM v_fin_profit_center_pl
        WHERE year = %s AND month <= %s
        GROUP BY profit_center_id, profit_center, service_type
        ORDER BY revenue DESC
        """,
        [year, date.today().month], many=True,
    )

    # Budget utilisation
    budget_util = fin_query(
        """
        SELECT COALESCE(SUM(budget), 0)  AS total_budget,
               COALESCE(SUM(actual), 0)  AS total_actual,
               COALESCE(SUM(variance), 0) AS total_variance
        FROM v_fin_budget_vs_actual_detail
        WHERE year = %s AND month <= %s
        """,
        [year, date.today().month],
    )

    return ok({
        "cost_centers": rows_to_list(cc_rows),
        "profit_centers": rows_to_list(pc_rows),
        "budget_utilisation": row_to_dict(budget_util) if budget_util else {},
        "year": year,
    })
