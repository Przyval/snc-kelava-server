"""
Cash & Bank Management Blueprint
==================================
Bank Accounts, Transactions, Reconciliation, Forecast, Petty Cash.
"""

from datetime import date, timedelta

from flask import Blueprint, request

from .core import (
    build_journal_entry, err, fin_execute, fin_execute_returning,
    fin_query, ok, require_finance_role,
    row_to_dict, rows_to_list, to_idr,
)
from kil.backend.core.security import require_auth

cash_bp = Blueprint("finance_cash", __name__, url_prefix="/api/v1/finance/cash")


# ── Bank Accounts ─────────────────────────────────────────────

@cash_bp.get("/accounts")
@require_auth
@require_finance_role
def list_bank_accounts():
    rows = fin_query(
        "SELECT * FROM v_fin_cash_position ORDER BY code",
        many=True,
    )
    total = sum(float(r["current_balance"]) for r in rows)
    return ok({"accounts": rows_to_list(rows), "total_balance": total})


@cash_bp.get("/accounts/<int:acct_id>")
@require_auth
@require_finance_role
def get_bank_account(acct_id):
    row = fin_query("SELECT * FROM fin_bank_accounts WHERE id = %s", [acct_id])
    if not row:
        return err("Bank account not found", 404)
    return ok(row_to_dict(row))


@cash_bp.patch("/accounts/<int:acct_id>/balance")
@require_auth
@require_finance_role
def update_bank_balance(acct_id):
    """Update current balance after reconciliation."""
    d = request.get_json()
    balance = d.get("current_balance")
    if balance is None:
        return err("current_balance required")
    fin_execute(
        "UPDATE fin_bank_accounts SET current_balance = %s, last_reconciled = CURRENT_DATE WHERE id = %s",
        [float(to_idr(balance)), acct_id],
    )
    return ok({}, "Balance updated")


# ── Bank Transactions ─────────────────────────────────────────

@cash_bp.get("/transactions")
@require_auth
@require_finance_role
def list_transactions():
    acct_id  = request.args.get("account_id", type=int)
    year     = request.args.get("year", date.today().year, type=int)
    month    = request.args.get("month", type=int)
    unreconciled = request.args.get("unreconciled", "false").lower() == "true"
    page     = request.args.get("page", 1, type=int)
    per_page = 100
    offset   = (page - 1) * per_page

    conditions = ["EXTRACT(YEAR FROM bt.txn_date) = %s"]
    params = [year]
    if acct_id:
        conditions.append("bt.bank_account_id = %s"); params.append(acct_id)
    if month:
        conditions.append("EXTRACT(MONTH FROM bt.txn_date) = %s"); params.append(month)
    if unreconciled:
        conditions.append("bt.reconciled = FALSE")

    where = "WHERE " + " AND ".join(conditions)
    rows = fin_query(
        f"""
        SELECT bt.*, ba.name AS account_name, ba.bank_name
        FROM   fin_bank_transactions bt
        JOIN   fin_bank_accounts ba ON ba.id = bt.bank_account_id
        {where}
        ORDER  BY bt.txn_date DESC, bt.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset], many=True,
    )
    return ok(rows_to_list(rows))


@cash_bp.post("/transactions")
@require_auth
@require_finance_role
def create_transaction():
    d = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["bank_account_id", "txn_date", "description"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    debit  = float(to_idr(d.get("debit", 0)))
    credit = float(to_idr(d.get("credit", 0)))
    if debit == 0 and credit == 0:
        return err("Either debit or credit must be > 0")

    bank = fin_query("SELECT * FROM fin_bank_accounts WHERE id = %s", [d["bank_account_id"]])
    if not bank:
        return err("Bank account not found")

    try:
        txn_date = date.fromisoformat(d["txn_date"])
    except ValueError:
        return err("Invalid txn_date")

    # Build GL entry
    if debit > 0:
        # Money out
        gl_lines = [
            {"account": d.get("contra_account", "6403"), "debit": debit, "credit": 0,
             "description": d["description"]},
            {"account": bank["gl_account"], "debit": 0, "credit": debit,
             "description": d["description"]},
        ]
    else:
        # Money in
        gl_lines = [
            {"account": bank["gl_account"], "debit": credit, "credit": 0,
             "description": d["description"]},
            {"account": d.get("contra_account", "4006"), "debit": 0, "credit": credit,
             "description": d["description"]},
        ]

    try:
        je_id = build_journal_entry(
            entry_date=txn_date,
            description=d["description"],
            lines=gl_lines,
            entry_type="AUTO_BANK",
            created_by=user,
        )
        row = fin_execute_returning(
            """INSERT INTO fin_bank_transactions
               (bank_account_id, txn_date, description, reference,
                debit, credit, txn_type, journal_entry_id, source, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'MANUAL',%s) RETURNING id""",
            [d["bank_account_id"], txn_date, d["description"], d.get("reference"),
             debit, credit, d.get("txn_type", "OTHER"), je_id, user],
        )
        # Update account balance
        fin_execute(
            "UPDATE fin_bank_accounts SET current_balance = current_balance + %s WHERE id = %s",
            [credit - debit, d["bank_account_id"]],
        )
        return ok({"id": row["id"]}, "Transaction recorded", 201)
    except Exception as e:
        return err(str(e), 500)


@cash_bp.post("/transactions/import")
@require_auth
@require_finance_role
def import_bank_statement():
    """
    Bulk import bank statement rows.
    Body: { "bank_account_id": 1, "transactions": [ {txn_date, description, debit, credit, reference}, ... ] }
    """
    d = request.get_json()
    acct_id = d.get("bank_account_id")
    txns = d.get("transactions", [])
    if not acct_id or not txns:
        return err("bank_account_id and transactions required")

    bank = fin_query("SELECT * FROM fin_bank_accounts WHERE id = %s", [acct_id])
    if not bank:
        return err("Bank account not found")

    imported = 0
    skipped  = 0
    for t in txns:
        try:
            txn_date = date.fromisoformat(t["txn_date"])
        except (ValueError, KeyError):
            skipped += 1
            continue

        # Skip duplicates by reference
        if t.get("reference"):
            exists = fin_query(
                "SELECT 1 FROM fin_bank_transactions WHERE bank_account_id = %s AND reference = %s",
                [acct_id, t["reference"]],
            )
            if exists:
                skipped += 1
                continue

        fin_execute(
            """INSERT INTO fin_bank_transactions
               (bank_account_id, txn_date, description, reference, debit, credit, source)
               VALUES (%s,%s,%s,%s,%s,%s,'IMPORT')""",
            [acct_id, txn_date, t.get("description", ""), t.get("reference"),
             float(to_idr(t.get("debit", 0))),
             float(to_idr(t.get("credit", 0)))],
        )
        imported += 1

    return ok({"imported": imported, "skipped": skipped})


# ── Bank Reconciliation ───────────────────────────────────────

@cash_bp.post("/reconcile")
@require_auth
@require_finance_role
def start_reconciliation():
    d = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["bank_account_id", "period_id", "statement_date", "statement_balance"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    bank = fin_query("SELECT * FROM fin_bank_accounts WHERE id = %s", [d["bank_account_id"]])
    if not bank:
        return err("Bank account not found")

    gl_balance = fin_query(
        """
        SELECT COALESCE(SUM(gl.credit) - SUM(gl.debit), 0) AS bal
        FROM   fin_gl_lines gl
        JOIN   fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status='POSTED'
        WHERE  gl.account_code = %s
        """,
        [bank["gl_account"]],
    )["bal"]

    stmt_bal = float(to_idr(d["statement_balance"]))
    diff = stmt_bal - float(gl_balance)

    row = fin_execute_returning(
        """
        INSERT INTO fin_bank_reconciliations
            (bank_account_id, period_id, statement_date, statement_balance,
             gl_balance, difference, status, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,'IN_PROGRESS',%s)
        ON CONFLICT (bank_account_id, period_id)
        DO UPDATE SET statement_balance=EXCLUDED.statement_balance,
                      gl_balance=EXCLUDED.gl_balance,
                      difference=EXCLUDED.difference,
                      status='IN_PROGRESS'
        RETURNING *
        """,
        [d["bank_account_id"], d["period_id"], d["statement_date"],
         stmt_bal, float(gl_balance), diff, user],
    )
    return ok({
        **row_to_dict(row),
        "reconciliation_needed": abs(diff) > 0.01,
        "message": "Balanced ✓" if abs(diff) <= 0.01 else f"Difference: {diff:,.2f}",
    })


@cash_bp.post("/reconcile/<int:recon_id>/complete")
@require_auth
@require_finance_role
def complete_reconciliation(recon_id):
    user = request.environ.get("user_email", "system")
    row = fin_execute_returning(
        """UPDATE fin_bank_reconciliations
           SET status='COMPLETE', completed_by=%s, completed_at=NOW()
           WHERE id=%s AND ABS(difference) <= 0.01
           RETURNING *""",
        [user, recon_id],
    )
    if not row:
        return err("Cannot complete: reconciliation not found or has unresolved difference")
    return ok(row_to_dict(row), "Reconciliation completed")


# ── Cash Position Dashboard ───────────────────────────────────

@cash_bp.get("/position")
@require_auth
@require_finance_role
def cash_position():
    accounts = fin_query("SELECT * FROM v_fin_cash_position ORDER BY code", many=True)
    total_balance = sum(float(r["current_balance"]) for r in accounts)

    # AR due in 30 days
    ar_30 = fin_query(
        """SELECT COALESCE(SUM(outstanding),0) AS amt FROM fin_sales_invoices
           WHERE status NOT IN ('PAID','CANCELLED') AND due_date <= CURRENT_DATE + 30""",
    )["amt"]

    # AP due in 30 days
    ap_30 = fin_query(
        """SELECT COALESCE(SUM(outstanding),0) AS amt FROM fin_purchase_invoices
           WHERE status NOT IN ('PAID','CANCELLED') AND due_date <= CURRENT_DATE + 30""",
    )["amt"]

    # Overdue AR
    ar_overdue = fin_query(
        """SELECT COALESCE(SUM(outstanding),0) AS amt FROM fin_sales_invoices
           WHERE status NOT IN ('PAID','CANCELLED') AND due_date < CURRENT_DATE""",
    )["amt"]

    return ok({
        "as_of": date.today().isoformat(),
        "total_cash":        round(float(total_balance), 2),
        "accounts":          rows_to_list(accounts),
        "ar_due_30d":        round(float(ar_30), 2),
        "ap_due_30d":        round(float(ap_30), 2),
        "ar_overdue":        round(float(ar_overdue), 2),
        "projected_30d":     round(float(total_balance) + float(ar_30) - float(ap_30), 2),
    })


# ── Cash Flow Forecast ────────────────────────────────────────

@cash_bp.get("/forecast")
@require_auth
@require_finance_role
def cash_forecast():
    horizon = request.args.get("days", 90, type=int)
    today = date.today()

    # Daily cash flow from AR expected collections (by due date)
    ar_by_day = fin_query(
        """
        SELECT due_date, SUM(outstanding) AS expected
        FROM   fin_sales_invoices
        WHERE  status NOT IN ('PAID','CANCELLED')
          AND  due_date BETWEEN %s AND %s
          AND  outstanding > 0
        GROUP  BY due_date ORDER BY due_date
        """,
        [today, today + timedelta(days=horizon)], many=True,
    )

    # Daily AP obligations
    ap_by_day = fin_query(
        """
        SELECT due_date, SUM(outstanding) AS expected
        FROM   fin_purchase_invoices
        WHERE  status NOT IN ('PAID','CANCELLED')
          AND  due_date BETWEEN %s AND %s
          AND  outstanding > 0
        GROUP  BY due_date ORDER BY due_date
        """,
        [today, today + timedelta(days=horizon)], many=True,
    )

    # Current cash
    total_cash = fin_query(
        "SELECT COALESCE(SUM(current_balance),0) AS bal FROM fin_bank_accounts WHERE is_active",
    )["bal"]

    # Build weekly summary
    weeks = []
    running = float(total_cash)
    for week_start in [today + timedelta(days=i*7) for i in range((horizon // 7) + 1)]:
        week_end = week_start + timedelta(days=6)
        ar_week = sum(
            float(r["expected"]) for r in ar_by_day
            if week_start <= r["due_date"] <= week_end
        )
        ap_week = sum(
            float(r["expected"]) for r in ap_by_day
            if week_start <= r["due_date"] <= week_end
        )
        running += ar_week - ap_week
        weeks.append({
            "week_start": week_start.isoformat(),
            "week_end":   week_end.isoformat(),
            "ar_expected": round(ar_week, 2),
            "ap_expected": round(ap_week, 2),
            "net":         round(ar_week - ap_week, 2),
            "running_balance": round(running, 2),
            "low_cash_alert": running < 100_000_000,
        })

    return ok({
        "opening_cash":    round(float(total_cash), 2),
        "horizon_days":    horizon,
        "weekly_forecast": weeks,
        "ar_schedule":     rows_to_list(ar_by_day),
        "ap_schedule":     rows_to_list(ap_by_day),
    })


# ── Petty Cash ────────────────────────────────────────────────

@cash_bp.get("/petty-cash")
@require_auth
@require_finance_role
def list_petty_cash():
    year  = request.args.get("year", date.today().year, type=int)
    rows = fin_query(
        """SELECT pc.*, cc.name AS cost_center_name
           FROM fin_petty_cash pc
           LEFT JOIN fin_cost_centers cc ON cc.id = pc.cost_center_id
           WHERE EXTRACT(YEAR FROM pc.txn_date) = %s
           ORDER BY pc.txn_date DESC""",
        [year], many=True,
    )
    total_expense = sum(float(r["amount"]) for r in rows if r["txn_type"] == "EXPENSE")
    total_replenishment = sum(float(r["amount"]) for r in rows if r["txn_type"] == "REPLENISHMENT")
    return ok({
        "items": rows_to_list(rows),
        "total_expense": total_expense,
        "total_replenishment": total_replenishment,
        "net_balance": round(total_replenishment - total_expense, 2),
    })


@cash_bp.post("/petty-cash")
@require_auth
@require_finance_role
def add_petty_cash():
    d = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["txn_date", "description", "amount", "txn_type"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    try:
        txn_date = date.fromisoformat(d["txn_date"])
    except ValueError:
        return err("Invalid txn_date")

    amount = float(to_idr(d["amount"]))
    account = d.get("expense_account", "6403")

    gl_lines = (
        [{"account": account, "debit": amount, "credit": 0, "description": d["description"]},
         {"account": "1101-01", "debit": 0, "credit": amount, "description": d["description"]}]
        if d["txn_type"] == "EXPENSE"
        else
        [{"account": "1101-01", "debit": amount, "credit": 0, "description": d["description"]},
         {"account": bank_acct, "debit": 0, "credit": amount, "description": d["description"]}]
        if (bank_acct := d.get("replenishment_from_account", "1101-02")) else []
    )

    try:
        je_id = build_journal_entry(
            entry_date=txn_date,
            description=d["description"],
            lines=gl_lines,
            entry_type="MANUAL",
            created_by=user,
        )
        row = fin_execute_returning(
            """INSERT INTO fin_petty_cash
               (txn_date, txn_type, description, amount, expense_account,
                cost_center_id, receipt_ref, journal_entry_id, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            [txn_date, d["txn_type"], d["description"], amount, account,
             d.get("cost_center_id"), d.get("receipt_ref"), je_id, user],
        )
        return ok({"id": row["id"]}, "Petty cash recorded", 201)
    except Exception as e:
        return err(str(e), 500)
