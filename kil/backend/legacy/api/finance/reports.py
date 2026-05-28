"""
Financial Reports Blueprint
============================
P&L, Balance Sheet, Cash Flow Statement, Budget vs Actual,
Customer Profitability, Executive Dashboard.
"""

from datetime import date
from decimal import Decimal

from flask import Blueprint, request

from .core import (
    err, fin_query, ok, require_finance_role,
    row_to_dict, rows_to_list,
)
from kil.backend.core.security import require_auth

reports_bp = Blueprint("finance_reports", __name__, url_prefix="/api/v1/finance/reports")


# ── Profit & Loss Statement ───────────────────────────────────

@reports_bp.get("/pl")
@require_auth
@require_finance_role
def profit_and_loss():
    year       = request.args.get("year",  date.today().year, type=int)
    month_from = request.args.get("month_from", 1, type=int)
    month_to   = request.args.get("month_to", 12, type=int)
    compare    = request.args.get("compare_year", type=int)

    def fetch_pl_data(y: int, mf: int, mt: int) -> dict:
        rows = fin_query(
            """
            SELECT
                fa.code, fa.name, fa.account_type, fa.normal_balance,
                fa.parent_code, fa.level,
                COALESCE(SUM(gl.debit),  0) AS total_debit,
                COALESCE(SUM(gl.credit), 0) AS total_credit,
                CASE WHEN fa.normal_balance = 'DEBIT'
                     THEN COALESCE(SUM(gl.debit),0) - COALESCE(SUM(gl.credit),0)
                     ELSE COALESCE(SUM(gl.credit),0) - COALESCE(SUM(gl.debit),0)
                END AS balance
            FROM fin_accounts fa
            LEFT JOIN fin_gl_lines gl ON gl.account_code = fa.code
            LEFT JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status = 'POSTED'
            LEFT JOIN fin_fiscal_periods fp   ON fp.id = je.period_id
                AND fp.year = %s AND fp.period BETWEEN %s AND %s
            WHERE fa.account_type IN ('REVENUE','COGS','EXPENSE','NON_OP')
              AND fa.is_detail = TRUE
            GROUP BY fa.code, fa.name, fa.account_type, fa.normal_balance, fa.parent_code, fa.level
            ORDER BY fa.code
            """,
            [y, mf, mt], many=True,
        )

        data = {
            "revenue":  [],
            "cogs":     [],
            "opex":     [],
            "non_op":   [],
            "totals":   {},
        }

        rev_total = cogs_total = opex_total = non_op_debit = non_op_credit = Decimal(0)

        for r in rows:
            item = {
                "code":    r["code"],
                "name":    r["name"],
                "balance": float(r["balance"]),
                "level":   r["level"],
            }
            at = r["account_type"]
            if at == "REVENUE":
                data["revenue"].append(item)
                rev_total += Decimal(str(r["balance"]))
            elif at == "COGS":
                data["cogs"].append(item)
                cogs_total += Decimal(str(r["balance"]))
            elif at == "EXPENSE":
                data["opex"].append(item)
                opex_total += Decimal(str(r["balance"]))
            elif at == "NON_OP":
                data["non_op"].append(item)
                if r["normal_balance"] == "CREDIT":
                    non_op_credit += Decimal(str(r["balance"]))
                else:
                    non_op_debit += Decimal(str(r["balance"]))

        gross_profit = rev_total - cogs_total
        op_profit    = gross_profit - opex_total
        non_op_net   = non_op_credit - non_op_debit
        net_profit   = op_profit + non_op_net

        data["totals"] = {
            "revenue":          float(rev_total),
            "cogs":             float(cogs_total),
            "gross_profit":     float(gross_profit),
            "gross_margin_pct": round(float(gross_profit / rev_total * 100), 1) if rev_total else 0,
            "opex":             float(opex_total),
            "operating_profit": float(op_profit),
            "op_margin_pct":    round(float(op_profit / rev_total * 100), 1) if rev_total else 0,
            "non_op_net":       float(non_op_net),
            "net_profit":       float(net_profit),
            "net_margin_pct":   round(float(net_profit / rev_total * 100), 1) if rev_total else 0,
        }
        return data

    result = {
        "year": year, "month_from": month_from, "month_to": month_to,
        "current": fetch_pl_data(year, month_from, month_to),
    }
    if compare:
        result["compare"] = fetch_pl_data(compare, month_from, month_to)
        result["compare_year"] = compare

        # Variance
        curr = result["current"]["totals"]
        comp = result["compare"]["totals"]
        result["variance"] = {
            k: round(curr.get(k, 0) - comp.get(k, 0), 2)
            for k in curr if isinstance(curr[k], float)
        }

    return ok(result)


# ── Balance Sheet ─────────────────────────────────────────────

@reports_bp.get("/balance-sheet")
@require_auth
@require_finance_role
def balance_sheet():
    year  = request.args.get("year",  date.today().year, type=int)
    month = request.args.get("month", 12, type=int)

    rows = fin_query(
        """
        SELECT
            fa.code, fa.name, fa.account_type, fa.normal_balance,
            fa.parent_code, fa.level,
            CASE WHEN fa.normal_balance = 'DEBIT'
                 THEN COALESCE(SUM(gl.debit),0) - COALESCE(SUM(gl.credit),0)
                 ELSE COALESCE(SUM(gl.credit),0) - COALESCE(SUM(gl.debit),0)
            END AS balance
        FROM fin_accounts fa
        LEFT JOIN fin_gl_lines gl ON gl.account_code = fa.code
        LEFT JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status = 'POSTED'
        LEFT JOIN fin_fiscal_periods fp   ON fp.id = je.period_id
            AND (fp.year < %s OR (fp.year = %s AND fp.period <= %s))
        WHERE fa.account_type IN ('ASSET','LIABILITY','EQUITY')
          AND fa.is_detail = TRUE
        GROUP BY fa.code, fa.name, fa.account_type, fa.normal_balance, fa.parent_code, fa.level
        ORDER BY fa.code
        """,
        [year, year, month], many=True,
    )

    assets = liabilities = equity = Decimal(0)
    result = {"assets": [], "liabilities": [], "equity": [], "totals": {}}

    for r in rows:
        item = {"code": r["code"], "name": r["name"],
                "balance": float(r["balance"]), "level": r["level"]}
        at = r["account_type"]
        if at == "ASSET":
            result["assets"].append(item)
            assets += Decimal(str(r["balance"]))
        elif at == "LIABILITY":
            result["liabilities"].append(item)
            liabilities += Decimal(str(r["balance"]))
        elif at == "EQUITY":
            result["equity"].append(item)
            equity += Decimal(str(r["balance"]))

    result["totals"] = {
        "total_assets":        float(assets),
        "total_liabilities":   float(liabilities),
        "total_equity":        float(equity),
        "liabilities_equity":  float(liabilities + equity),
        "balanced":            abs(assets - liabilities - equity) < 0.01,
    }
    return ok({"year": year, "month": month, **result})


# ── Cash Flow Statement (Indirect Method) ────────────────────

@reports_bp.get("/cash-flow")
@require_auth
@require_finance_role
def cash_flow():
    year       = request.args.get("year",  date.today().year, type=int)
    month_from = request.args.get("month_from", 1, type=int)
    month_to   = request.args.get("month_to", 12, type=int)

    # Net income from P&L
    pl_data = fin_query(
        """
        SELECT
            SUM(CASE WHEN fa.account_type='REVENUE' AND fa.normal_balance='CREDIT'
                     THEN gl.credit - gl.debit ELSE 0 END) AS revenue,
            SUM(CASE WHEN fa.account_type IN ('COGS','EXPENSE')
                     THEN gl.debit - gl.credit ELSE 0 END) AS total_costs
        FROM fin_gl_lines gl
        JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status='POSTED'
        JOIN fin_fiscal_periods fp   ON fp.id = je.period_id
            AND fp.year = %s AND fp.period BETWEEN %s AND %s
        JOIN fin_accounts fa ON fa.code = gl.account_code
        WHERE fa.account_type IN ('REVENUE','COGS','EXPENSE')
        """,
        [year, month_from, month_to],
    )
    net_income = float(pl_data["revenue"] or 0) - float(pl_data["total_costs"] or 0)

    # Changes in working capital (AR, AP, Inventory)
    ar_change = fin_query(
        """SELECT COALESCE(SUM(debit)-SUM(credit),0) AS chg FROM fin_gl_lines gl
           JOIN fin_journal_entries je ON je.id=gl.journal_entry_id AND je.status='POSTED'
           JOIN fin_fiscal_periods fp ON fp.id=je.period_id AND fp.year=%s AND fp.period BETWEEN %s AND %s
           WHERE gl.account_code = '1102'""",
        [year, month_from, month_to],
    )["chg"]

    ap_change = fin_query(
        """SELECT COALESCE(SUM(credit)-SUM(debit),0) AS chg FROM fin_gl_lines gl
           JOIN fin_journal_entries je ON je.id=gl.journal_entry_id AND je.status='POSTED'
           JOIN fin_fiscal_periods fp ON fp.id=je.period_id AND fp.year=%s AND fp.period BETWEEN %s AND %s
           WHERE gl.account_code = '2101'""",
        [year, month_from, month_to],
    )["chg"]

    # Depreciation (non-cash add-back)
    depreciation = fin_query(
        """SELECT COALESCE(SUM(debit)-SUM(credit),0) AS dep FROM fin_gl_lines gl
           JOIN fin_journal_entries je ON je.id=gl.journal_entry_id AND je.status='POSTED'
           JOIN fin_fiscal_periods fp ON fp.id=je.period_id AND fp.year=%s AND fp.period BETWEEN %s AND %s
           WHERE gl.account_code IN ('6501','6502','6503')""",
        [year, month_from, month_to],
    )["dep"]

    # CapEx (asset purchases)
    capex = fin_query(
        """SELECT COALESCE(SUM(debit)-SUM(credit),0) AS capex FROM fin_gl_lines gl
           JOIN fin_journal_entries je ON je.id=gl.journal_entry_id AND je.status='POSTED'
           JOIN fin_fiscal_periods fp ON fp.id=je.period_id AND fp.year=%s AND fp.period BETWEEN %s AND %s
           WHERE gl.account_code IN ('1201','1202','1203')""",
        [year, month_from, month_to],
    )["capex"]

    # Bank balance change
    bank_net = fin_query(
        """SELECT COALESCE(SUM(credit)-SUM(debit),0) AS net FROM fin_gl_lines gl
           JOIN fin_journal_entries je ON je.id=gl.journal_entry_id AND je.status='POSTED'
           JOIN fin_fiscal_periods fp ON fp.id=je.period_id AND fp.year=%s AND fp.period BETWEEN %s AND %s
           WHERE gl.account_code IN ('1101-01','1101-02','1101-03','1101-04','1101-05')""",
        [year, month_from, month_to],
    )["net"]

    operating_cf = net_income + float(depreciation or 0) - float(ar_change or 0) + float(ap_change or 0)
    investing_cf = -float(capex or 0)
    financing_cf = float(bank_net or 0) - operating_cf - investing_cf

    return ok({
        "year": year, "month_from": month_from, "month_to": month_to,
        "operating": {
            "net_income":               round(net_income, 2),
            "add_depreciation":         round(float(depreciation or 0), 2),
            "change_in_ar":            -round(float(ar_change or 0), 2),
            "change_in_ap":             round(float(ap_change or 0), 2),
            "net_operating_cash_flow":  round(operating_cf, 2),
        },
        "investing": {
            "capex":                   -round(float(capex or 0), 2),
            "net_investing_cash_flow":  round(investing_cf, 2),
        },
        "financing": {
            "net_financing_cash_flow":  round(financing_cf, 2),
        },
        "net_change_in_cash":    round(float(bank_net or 0), 2),
    })


# ── Budget vs Actual ──────────────────────────────────────────

@reports_bp.get("/budget-vs-actual")
@require_auth
@require_finance_role
def budget_vs_actual():
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    conditions = ["year = %s"]
    params = [year]
    if month:
        conditions.append("period = %s"); params.append(month)

    rows = fin_query(
        f"SELECT * FROM v_fin_budget_vs_actual WHERE {' AND '.join(conditions)} ORDER BY account_code",
        params, many=True,
    )

    by_type: dict[str, dict] = {}
    for r in rows:
        at = r["account_type"]
        if at not in by_type:
            by_type[at] = {"rows": [], "budget_total": 0, "actual_total": 0}
        by_type[at]["rows"].append(row_to_dict(r))
        by_type[at]["budget_total"] += float(r["budget"] or 0)
        by_type[at]["actual_total"] += float(r["actual"] or 0)

    return ok({"year": year, "month": month, "by_type": by_type})


# ── Customer Profitability ────────────────────────────────────

@reports_bp.get("/customer-profitability")
@require_auth
@require_finance_role
def customer_profitability():
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    conditions = ["year = %s"]
    params = [year]
    if month:
        conditions.append("period = %s"); params.append(month)

    rows = fin_query(
        f"""
        SELECT customer_name, customer_group,
               SUM(revenue)          AS revenue,
               SUM(collected)        AS collected,
               SUM(uncollected)      AS uncollected,
               SUM(invoice_count)    AS invoice_count,
               CASE WHEN SUM(revenue)>0
                    THEN ROUND(SUM(collected)*100.0/SUM(revenue),1) ELSE 0 END AS collection_rate
        FROM v_fin_customer_profitability
        WHERE {' AND '.join(conditions)}
        GROUP BY customer_name, customer_group
        ORDER BY revenue DESC
        LIMIT 100
        """,
        params, many=True,
    )
    total_rev = sum(float(r["revenue"]) for r in rows)
    result = []
    for r in rows:
        d = row_to_dict(r)
        d["pct_of_total"] = round(float(r["revenue"]) / total_rev * 100, 1) if total_rev else 0
        result.append(d)

    return ok({"year": year, "total_revenue": total_rev, "customers": result})


# ── Executive Dashboard ───────────────────────────────────────

@reports_bp.get("/dashboard")
@require_auth
@require_finance_role
def dashboard():
    today = date.today()
    year  = today.year
    month = today.month

    # YTD P&L
    ytd_pl = fin_query(
        """
        SELECT
            SUM(CASE WHEN fa.account_type='REVENUE' AND fa.normal_balance='CREDIT'
                     THEN gl.credit - gl.debit ELSE 0 END) AS revenue,
            SUM(CASE WHEN fa.account_type='COGS'
                     THEN gl.debit - gl.credit ELSE 0 END) AS cogs,
            SUM(CASE WHEN fa.account_type='EXPENSE'
                     THEN gl.debit - gl.credit ELSE 0 END) AS opex
        FROM fin_gl_lines gl
        JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status='POSTED'
        JOIN fin_fiscal_periods fp   ON fp.id = je.period_id AND fp.year = %s
        JOIN fin_accounts fa ON fa.code = gl.account_code
        WHERE fa.account_type IN ('REVENUE','COGS','EXPENSE')
        """,
        [year],
    )

    rev   = float(ytd_pl["revenue"] or 0)
    cogs  = float(ytd_pl["cogs"] or 0)
    opex  = float(ytd_pl["opex"] or 0)
    net   = rev - cogs - opex
    gp    = rev - cogs

    # Cash
    cash = fin_query(
        "SELECT COALESCE(SUM(current_balance),0) AS bal FROM fin_bank_accounts WHERE is_active",
    )["bal"]

    # AR Outstanding
    ar = fin_query(
        "SELECT COALESCE(SUM(outstanding),0) AS amt FROM fin_sales_invoices WHERE status NOT IN ('PAID','CANCELLED')",
    )["amt"]

    # AP Outstanding
    ap = fin_query(
        "SELECT COALESCE(SUM(outstanding),0) AS amt FROM fin_purchase_invoices WHERE status NOT IN ('PAID','CANCELLED')",
    )["amt"]

    # Overdue AR
    ar_overdue = fin_query(
        "SELECT COALESCE(SUM(outstanding),0) AS amt FROM fin_sales_invoices WHERE status NOT IN ('PAID','CANCELLED') AND due_date < CURRENT_DATE",
    )["amt"]

    # Recent JEs
    recent_je = fin_query(
        "SELECT entry_no, entry_date, description, total_debit, status FROM fin_journal_entries ORDER BY created_at DESC LIMIT 5",
        many=True,
    )

    # AR aging buckets summary
    aging = fin_query(
        """SELECT aging_bucket, SUM(outstanding) AS total
           FROM v_fin_ar_aging GROUP BY aging_bucket ORDER BY bucket_order""",
        many=True,
    )

    return ok({
        "as_of":       today.isoformat(),
        "ytd": {
            "revenue":        round(rev, 2),
            "gross_profit":   round(gp, 2),
            "gp_margin_pct":  round(gp / rev * 100, 1) if rev else 0,
            "net_profit":     round(net, 2),
            "net_margin_pct": round(net / rev * 100, 1) if rev else 0,
        },
        "balance_sheet": {
            "cash":           round(float(cash), 2),
            "ar_outstanding": round(float(ar), 2),
            "ar_overdue":     round(float(ar_overdue), 2),
            "ap_outstanding": round(float(ap), 2),
        },
        "ar_aging_buckets": rows_to_list(aging),
        "recent_journal_entries": rows_to_list(recent_je),
        "alerts": _build_alerts(float(cash), float(ar_overdue), float(ap)),
    })


def _build_alerts(cash: float, ar_overdue: float, ap_outstanding: float) -> list[dict]:
    alerts = []
    if ar_overdue > 500_000_000:
        alerts.append({"level": "danger", "msg": f"AR overdue Rp {ar_overdue/1e6:.0f}M — immediate collection action needed"})
    elif ar_overdue > 200_000_000:
        alerts.append({"level": "warning", "msg": f"AR overdue Rp {ar_overdue/1e6:.0f}M — follow up required"})
    if cash < 100_000_000:
        alerts.append({"level": "danger", "msg": f"Cash Rp {cash/1e6:.0f}M — below Rp 100M threshold"})
    elif cash < 200_000_000:
        alerts.append({"level": "warning", "msg": f"Cash Rp {cash/1e6:.0f}M — monitor closely"})
    if ap_outstanding > cash:
        alerts.append({"level": "warning", "msg": f"AP Rp {ap_outstanding/1e6:.0f}M exceeds current cash Rp {cash/1e6:.0f}M"})
    return alerts


# ── Multi-Year Trend ──────────────────────────────────────────

@reports_bp.get("/trend")
@require_auth
@require_finance_role
def multi_year_trend():
    """Revenue, GP, Net Profit trend across all available years."""
    rows = fin_query(
        """
        SELECT
            fp.year,
            SUM(CASE WHEN fa.account_type='REVENUE' AND fa.normal_balance='CREDIT'
                     THEN gl.credit - gl.debit ELSE 0 END) AS revenue,
            SUM(CASE WHEN fa.account_type='COGS'
                     THEN gl.debit - gl.credit ELSE 0 END) AS cogs,
            SUM(CASE WHEN fa.account_type='EXPENSE'
                     THEN gl.debit - gl.credit ELSE 0 END) AS opex
        FROM fin_gl_lines gl
        JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status='POSTED'
        JOIN fin_fiscal_periods fp   ON fp.id = je.period_id
        JOIN fin_accounts fa ON fa.code = gl.account_code
        WHERE fa.account_type IN ('REVENUE','COGS','EXPENSE')
        GROUP BY fp.year ORDER BY fp.year
        """,
        many=True,
    )

    result = []
    for r in rows:
        rev  = float(r["revenue"] or 0)
        cogs = float(r["cogs"] or 0)
        opex = float(r["opex"] or 0)
        gp   = rev - cogs
        net  = gp - opex
        result.append({
            "year":           r["year"],
            "revenue":        round(rev, 2),
            "gross_profit":   round(gp, 2),
            "net_profit":     round(net, 2),
            "gp_margin_pct":  round(gp / rev * 100, 1) if rev else 0,
            "np_margin_pct":  round(net / rev * 100, 1) if rev else 0,
        })
    return ok(result)
