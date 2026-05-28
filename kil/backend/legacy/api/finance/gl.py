"""
General Ledger Blueprint
========================
Chart of Accounts, Journal Entries, Trial Balance, Period Management.
"""

from datetime import date, datetime

from flask import Blueprint, request

from .core import (
    build_journal_entry,
    err,
    fin_execute,
    fin_execute_returning,
    fin_query,
    get_open_period,
    ok,
    require_finance_role,
    resolve_period,
    row_to_dict,
    rows_to_list,
    to_idr,
)
from kil.backend.core.security import require_auth

gl_bp = Blueprint("finance_gl", __name__, url_prefix="/api/v1/finance/gl")


# ── Chart of Accounts ────────────────────────────────────────

@gl_bp.get("/accounts")
@require_auth
@require_finance_role
def list_accounts():
    account_type = request.args.get("type")
    active_only = request.args.get("active", "true").lower() == "true"
    detail_only = request.args.get("detail", "false").lower() == "true"

    conditions = []
    params = []
    if account_type:
        conditions.append("account_type = %s")
        params.append(account_type)
    if active_only:
        conditions.append("is_active = TRUE")
    if detail_only:
        conditions.append("is_detail = TRUE")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fin_query(
        f"SELECT * FROM fin_accounts {where} ORDER BY code",
        params, many=True,
    )
    return ok(rows_to_list(rows))


@gl_bp.get("/accounts/<code>")
@require_auth
@require_finance_role
def get_account(code):
    row = fin_query("SELECT * FROM fin_accounts WHERE code = %s", [code])
    if not row:
        return err("Account not found", 404)
    return ok(row_to_dict(row))


@gl_bp.post("/accounts")
@require_auth
@require_finance_role
def create_account():
    d = request.get_json()
    required = ["code", "name", "account_type"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    try:
        row = fin_execute_returning(
            """
            INSERT INTO fin_accounts (code, name, account_type, normal_balance,
                parent_code, level, is_detail, description)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
            """,
            [d["code"], d["name"], d["account_type"],
             d.get("normal_balance", "DEBIT"), d.get("parent_code"),
             d.get("level", 1), d.get("is_detail", True), d.get("description")],
        )
        return ok(row_to_dict(row), "Account created", 201)
    except Exception as e:
        return err(str(e))


@gl_bp.patch("/accounts/<code>")
@require_auth
@require_finance_role
def update_account(code):
    d = request.get_json()
    allowed = ["name", "description", "is_active", "is_detail", "parent_code"]
    updates = {k: v for k, v in d.items() if k in allowed}
    if not updates:
        return err("No valid fields to update")

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    row = fin_execute_returning(
        f"UPDATE fin_accounts SET {set_clause} WHERE code = %s RETURNING *",
        list(updates.values()) + [code],
    )
    if not row:
        return err("Account not found", 404)
    return ok(row_to_dict(row))


# ── Journal Entries ──────────────────────────────────────────

@gl_bp.get("/journal-entries")
@require_auth
@require_finance_role
def list_journal_entries():
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)
    status = request.args.get("status")
    entry_type = request.args.get("type")
    page  = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    offset = (page - 1) * per_page

    conditions = ["fp.year = %s"]
    params = [year]
    if month:
        conditions.append("fp.period = %s")
        params.append(month)
    if status:
        conditions.append("je.status = %s")
        params.append(status)
    if entry_type:
        conditions.append("je.entry_type = %s")
        params.append(entry_type)

    where = "WHERE " + " AND ".join(conditions)

    count = fin_query(
        f"""SELECT COUNT(*) AS cnt FROM fin_journal_entries je
            JOIN fin_fiscal_periods fp ON fp.id = je.period_id {where}""",
        params,
    )["cnt"]

    rows = fin_query(
        f"""
        SELECT je.*, fp.year, fp.period
        FROM   fin_journal_entries je
        JOIN   fin_fiscal_periods fp ON fp.id = je.period_id
        {where}
        ORDER BY je.entry_date DESC, je.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset], many=True,
    )
    return ok({
        "items": rows_to_list(rows),
        "total": count,
        "page": page,
        "pages": (count + per_page - 1) // per_page,
    })


@gl_bp.get("/journal-entries/<int:je_id>")
@require_auth
@require_finance_role
def get_journal_entry(je_id):
    je = fin_query(
        "SELECT je.*, fp.year, fp.period FROM fin_journal_entries je "
        "JOIN fin_fiscal_periods fp ON fp.id = je.period_id WHERE je.id = %s",
        [je_id],
    )
    if not je:
        return err("Journal entry not found", 404)

    lines = fin_query(
        """
        SELECT gl.*, fa.name AS account_name, fa.account_type,
               cc.name AS cost_center_name, pc.name AS profit_center_name
        FROM   fin_gl_lines gl
        JOIN   fin_accounts fa ON fa.code = gl.account_code
        LEFT JOIN fin_cost_centers cc ON cc.id = gl.cost_center_id
        LEFT JOIN fin_profit_centers pc ON pc.id = gl.profit_center_id
        WHERE  gl.journal_entry_id = %s
        ORDER BY gl.line_no
        """,
        [je_id], many=True,
    )
    result = row_to_dict(je)
    result["lines"] = rows_to_list(lines)
    return ok(result)


@gl_bp.post("/journal-entries")
@require_auth
@require_finance_role
def create_journal_entry():
    d = request.get_json()
    user = request.environ.get("user_email", "system")

    try:
        entry_date = date.fromisoformat(d["entry_date"])
    except (KeyError, ValueError):
        return err("Valid entry_date (YYYY-MM-DD) required")

    lines = d.get("lines", [])
    if len(lines) < 2:
        return err("At least 2 lines required")

    try:
        je_id = build_journal_entry(
            entry_date=entry_date,
            description=d.get("description", "Manual Journal Entry"),
            lines=lines,
            entry_type="MANUAL",
            reference=d.get("reference"),
            created_by=user,
        )
        return ok({"id": je_id}, "Journal entry posted", 201)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(f"Failed to post: {e}", 500)


@gl_bp.post("/journal-entries/<int:je_id>/reverse")
@require_auth
@require_finance_role
def reverse_journal_entry(je_id):
    je = fin_query("SELECT * FROM fin_journal_entries WHERE id = %s", [je_id])
    if not je:
        return err("Journal entry not found", 404)
    if je["status"] != "POSTED":
        return err("Only POSTED entries can be reversed")

    d = request.get_json() or {}
    try:
        reversal_date = date.fromisoformat(d.get("reversal_date", date.today().isoformat()))
    except ValueError:
        return err("Invalid reversal_date")

    # Swap debit/credit on all lines
    orig_lines = fin_query(
        "SELECT * FROM fin_gl_lines WHERE journal_entry_id = %s ORDER BY line_no",
        [je_id], many=True,
    )
    reversal_lines = [
        {
            "account": l["account_code"],
            "debit": float(l["credit"]),
            "credit": float(l["debit"]),
            "description": f"Reversal: {l['description'] or ''}",
            "cost_center_id": l["cost_center_id"],
            "profit_center_id": l["profit_center_id"],
            "customer_name": l["customer_name"],
            "vendor_id": l["vendor_id"],
        }
        for l in orig_lines
    ]

    user = request.environ.get("user_email", "system")
    try:
        rev_id = build_journal_entry(
            entry_date=reversal_date,
            description=f"REVERSAL of {je['entry_no']}: {je['description']}",
            lines=reversal_lines,
            entry_type="REVERSAL",
            reference=je["entry_no"],
            created_by=user,
        )
        fin_execute(
            "UPDATE fin_journal_entries SET reversed_by_id = %s WHERE id = %s",
            [rev_id, je_id],
        )
        return ok({"reversal_id": rev_id}, "Entry reversed")
    except Exception as e:
        return err(str(e), 500)


# ── Trial Balance ────────────────────────────────────────────

@gl_bp.get("/trial-balance")
@require_auth
@require_finance_role
def trial_balance():
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    # Accumulate from beginning of year up to requested period
    period_condition = "fp.year = %s"
    params = [year]
    if month:
        period_condition += " AND fp.period <= %s"
        params.append(month)

    rows = fin_query(
        f"""
        SELECT
            fa.code,
            fa.name,
            fa.account_type,
            fa.normal_balance,
            fa.parent_code,
            fa.level,
            COALESCE(SUM(gl.debit),  0) AS total_debit,
            COALESCE(SUM(gl.credit), 0) AS total_credit,
            CASE WHEN fa.normal_balance = 'DEBIT'
                 THEN COALESCE(SUM(gl.debit),0) - COALESCE(SUM(gl.credit),0)
                 ELSE COALESCE(SUM(gl.credit),0) - COALESCE(SUM(gl.debit),0)
            END                         AS balance
        FROM   fin_accounts fa
        LEFT JOIN fin_gl_lines gl ON gl.account_code = fa.code
        LEFT JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status = 'POSTED'
        LEFT JOIN fin_fiscal_periods fp   ON fp.id = je.period_id AND {period_condition}
        WHERE  fa.is_detail = TRUE
        GROUP BY fa.code, fa.name, fa.account_type, fa.normal_balance, fa.parent_code, fa.level
        ORDER BY fa.code
        """,
        params, many=True,
    )
    total_dr = sum(r["total_debit"] for r in rows)
    total_cr = sum(r["total_credit"] for r in rows)
    return ok({
        "year": year, "month": month,
        "rows": rows_to_list(rows),
        "total_debit": float(total_dr),
        "total_credit": float(total_cr),
        "balanced": abs(total_dr - total_cr) < 0.01,
    })


# ── GL Detail (Account Drilldown) ────────────────────────────

@gl_bp.get("/ledger/<account_code>")
@require_auth
@require_finance_role
def account_ledger(account_code):
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)
    page  = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 100, type=int)
    offset = (page - 1) * per_page

    conditions = ["gl.account_code = %s", "fp.year = %s", "je.status = 'POSTED'"]
    params = [account_code, year]
    if month:
        conditions.append("fp.period = %s")
        params.append(month)

    where = "WHERE " + " AND ".join(conditions)

    rows = fin_query(
        f"""
        SELECT
            je.entry_date,
            je.entry_no,
            je.description     AS je_description,
            gl.description     AS line_description,
            gl.debit,
            gl.credit,
            gl.customer_name,
            v.name             AS vendor_name,
            fp.year,
            fp.period
        FROM   fin_gl_lines gl
        JOIN   fin_journal_entries je ON je.id = gl.journal_entry_id
        JOIN   fin_fiscal_periods fp  ON fp.id = je.period_id
        LEFT JOIN fin_vendors v       ON v.id = gl.vendor_id
        {where}
        ORDER BY je.entry_date, je.id
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset], many=True,
    )
    # Running balance
    account = fin_query("SELECT * FROM fin_accounts WHERE code = %s", [account_code])
    if not account:
        return err("Account not found", 404)

    running = 0.0
    result_rows = []
    for r in rows:
        d = row_to_dict(r)
        if account["normal_balance"] == "DEBIT":
            running += float(r["debit"]) - float(r["credit"])
        else:
            running += float(r["credit"]) - float(r["debit"])
        d["running_balance"] = round(running, 2)
        result_rows.append(d)

    return ok({
        "account": row_to_dict(account),
        "year": year, "month": month,
        "rows": result_rows,
    })


# ── Fiscal Periods ───────────────────────────────────────────

@gl_bp.get("/periods")
@require_auth
@require_finance_role
def list_periods():
    rows = fin_query(
        "SELECT * FROM fin_fiscal_periods ORDER BY year, period",
        many=True,
    )
    return ok(rows_to_list(rows))


@gl_bp.post("/periods/<int:period_id>/close")
@require_auth
@require_finance_role
def close_period(period_id):
    user = getattr(request, "user_email", "system")
    period = fin_query("SELECT * FROM fin_fiscal_periods WHERE id = %s", [period_id])
    if not period:
        return err("Period not found", 404)
    if period["status"] != "OPEN":
        return err(f"Period is already {period['status']}")

    # Check no unposted journals in this period
    unposted = fin_query(
        "SELECT COUNT(*) AS cnt FROM fin_journal_entries WHERE period_id = %s AND status NOT IN ('POSTED','CANCELLED')",
        [period_id],
    )["cnt"]
    if unposted > 0:
        return err(f"{unposted} unposted journal entries must be resolved before closing period")

    row = fin_execute_returning(
        "UPDATE fin_fiscal_periods SET status='CLOSED', closed_by=%s, closed_at=NOW() WHERE id=%s RETURNING *",
        [user, period_id],
    )
    return ok(row_to_dict(row), f"Period {period['year']}/{period['period']:02d} closed")


@gl_bp.post("/periods/<int:period_id>/reopen")
@require_auth
@require_finance_role
def reopen_period(period_id):
    period = fin_query("SELECT * FROM fin_fiscal_periods WHERE id = %s", [period_id])
    if not period:
        return err("Period not found", 404)
    if period["status"] == "LOCKED":
        return err("LOCKED periods cannot be reopened")
    row = fin_execute_returning(
        "UPDATE fin_fiscal_periods SET status='OPEN', closed_by=NULL, closed_at=NULL WHERE id=%s RETURNING *",
        [period_id],
    )
    return ok(row_to_dict(row), "Period reopened")


# ── Month-End Close Checklist ────────────────────────────────

@gl_bp.get("/close-checklist")
@require_auth
@require_finance_role
def close_checklist():
    row = fin_query("SELECT * FROM v_fin_close_checklist")
    return ok(row_to_dict(row) if row else {})
