"""
Accounts Receivable Blueprint
==============================
Sales Invoices, Payments, Allocation, AR Aging, Dunning,
Bad Debt Provision, Customer Management.
"""

from datetime import date, timedelta

from flask import Blueprint, request

from .core import (
    build_journal_entry,
    err,
    fin_execute,
    fin_execute_returning,
    fin_query,
    ok,
    require_finance_role,
    resolve_period,
    row_to_dict,
    rows_to_list,
    to_idr,
)
from kil.backend.core.security import require_auth

ar_bp = Blueprint("finance_ar", __name__, url_prefix="/api/v1/finance/ar")


# ── Customer Master ──────────────────────────────────────────

@ar_bp.get("/customers")
@require_auth
@require_finance_role
def list_customers():
    search = request.args.get("q", "")
    group  = request.args.get("group")
    rows = fin_query(
        """
        SELECT fc.*,
               COALESCE(ar.total_outstanding, 0) AS total_outstanding,
               ar.last_invoice_date
        FROM   fin_customers fc
        LEFT JOIN (
            SELECT customer_name,
                   SUM(outstanding)    AS total_outstanding,
                   MAX(invoice_date)   AS last_invoice_date
            FROM   fin_sales_invoices
            WHERE  status NOT IN ('PAID','CANCELLED')
            GROUP  BY customer_name
        ) ar ON ar.customer_name = fc.customer_name
        WHERE  (%s = '' OR LOWER(fc.customer_name) LIKE LOWER(%s))
          AND  (%s IS NULL OR fc.customer_group = %s)
        ORDER BY fc.customer_name
        """,
        [search, f"%{search}%", group, group], many=True,
    )
    return ok(rows_to_list(rows))


@ar_bp.post("/customers")
@require_auth
@require_finance_role
def create_customer():
    d = request.get_json()
    if not d.get("customer_name"):
        return err("customer_name required")
    try:
        row = fin_execute_returning(
            """
            INSERT INTO fin_customers
                (customer_name, npwp, address, city, credit_limit,
                 payment_terms, ar_account, customer_group, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
            """,
            [d["customer_name"], d.get("npwp"), d.get("address"), d.get("city"),
             d.get("credit_limit", 0), d.get("payment_terms", 30),
             d.get("ar_account", "1102"), d.get("customer_group"), d.get("notes")],
        )
        return ok(row_to_dict(row), "Customer created", 201)
    except Exception as e:
        return err(str(e))


@ar_bp.patch("/customers/<customer_name>")
@require_auth
@require_finance_role
def update_customer(customer_name):
    d = request.get_json()
    allowed = ["npwp", "address", "city", "credit_limit", "payment_terms",
               "customer_group", "is_active", "notes"]
    updates = {k: v for k, v in d.items() if k in allowed}
    if not updates:
        return err("No valid fields")
    updates["updated_at"] = "NOW()"
    set_clause = ", ".join(
        f"{k} = {'NOW()' if v == 'NOW()' else '%s'}" for k, v in updates.items()
    )
    params = [v for v in updates.values() if v != "NOW()"] + [customer_name]
    row = fin_execute_returning(
        f"UPDATE fin_customers SET {set_clause} WHERE customer_name = %s RETURNING *",
        params,
    )
    return ok(row_to_dict(row) if row else {})


# ── Sales Invoices ───────────────────────────────────────────

@ar_bp.get("/invoices")
@require_auth
@require_finance_role
def list_invoices():
    status   = request.args.get("status")
    customer = request.args.get("customer")
    year     = request.args.get("year", type=int)
    month    = request.args.get("month", type=int)
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    offset   = (page - 1) * per_page

    conditions, params = [], []
    if status:
        conditions.append("si.status = %s"); params.append(status)
    if customer:
        conditions.append("si.customer_name ILIKE %s"); params.append(f"%{customer}%")
    if year:
        conditions.append("fp.year = %s"); params.append(year)
    if month:
        conditions.append("fp.period = %s"); params.append(month)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count = fin_query(
        f"""SELECT COUNT(*) AS cnt FROM fin_sales_invoices si
            LEFT JOIN fin_fiscal_periods fp ON fp.id = si.period_id {where}""",
        params,
    )["cnt"]

    rows = fin_query(
        f"""
        SELECT si.*,
               CURRENT_DATE - si.due_date       AS days_overdue,
               fp.year, fp.period
        FROM   fin_sales_invoices si
        LEFT JOIN fin_fiscal_periods fp ON fp.id = si.period_id
        {where}
        ORDER BY si.invoice_date DESC, si.id DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset], many=True,
    )
    return ok({
        "items": rows_to_list(rows),
        "total": count, "page": page,
        "pages": (count + per_page - 1) // per_page,
    })


@ar_bp.get("/invoices/<int:inv_id>")
@require_auth
@require_finance_role
def get_invoice(inv_id):
    si = fin_query("SELECT * FROM fin_sales_invoices WHERE id = %s", [inv_id])
    if not si:
        return err("Invoice not found", 404)

    lines = fin_query(
        "SELECT * FROM fin_invoice_lines WHERE invoice_id = %s ORDER BY line_no",
        [inv_id], many=True,
    )
    allocs = fin_query(
        """
        SELECT aa.*, p.receipt_no, p.payment_date, p.gross_amount
        FROM   fin_ar_allocations aa
        JOIN   fin_ar_payments p ON p.id = aa.payment_id
        WHERE  aa.invoice_id = %s
        """,
        [inv_id], many=True,
    )
    result = row_to_dict(si)
    result["lines"] = rows_to_list(lines)
    result["payments"] = rows_to_list(allocs)
    result["days_overdue"] = (date.today() - si["due_date"]).days if si["due_date"] else None
    return ok(result)


@ar_bp.post("/invoices")
@require_auth
@require_finance_role
def create_invoice():
    d = request.get_json()
    user = request.environ.get("user_email", "system")

    required = ["customer_name", "invoice_date", "lines"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    try:
        inv_date  = date.fromisoformat(d["invoice_date"])
    except ValueError:
        return err("Invalid invoice_date")

    # Resolve period
    period = resolve_period(inv_date)
    if not period:
        return err(f"No fiscal period for {inv_date}")
    if period["status"] in ("CLOSED", "LOCKED"):
        return err(f"Period {period['year']}/{period['period']} is {period['status']}")

    # Validate customer
    customer = fin_query(
        "SELECT * FROM fin_customers WHERE customer_name = %s", [d["customer_name"]]
    )
    if not customer:
        return err(f"Customer '{d['customer_name']}' not found. Create it first.")

    lines = d.get("lines", [])
    subtotal = sum(to_idr(l.get("total_price", 0)) for l in lines)
    discount = to_idr(d.get("discount_amount", 0))
    dpp      = subtotal - discount
    ppn_rate = to_idr(d.get("ppn_rate", 11.00))
    ppn_amt  = (dpp * ppn_rate / 100).quantize(to_idr(1))
    total    = dpp + ppn_amt

    payment_terms = d.get("payment_terms", customer["payment_terms"] or 30)
    due_date = date.fromisoformat(d["due_date"]) if d.get("due_date") else (inv_date + timedelta(days=payment_terms))

    # Generate invoice number
    inv_no_row = fin_query(
        "SELECT next_invoice_no(%s, %s) AS no", [inv_date.year, inv_date.month]
    )
    inv_no = d.get("invoice_no") or inv_no_row["no"]

    try:
        si_row = fin_execute_returning(
            """
            INSERT INTO fin_sales_invoices
                (invoice_no, invoice_date, due_date, customer_name,
                 service_type, profit_center_id,
                 subtotal, discount_amount, dpp, ppn_rate, ppn_amount, total,
                 outstanding, status, payment_terms, contract_ref,
                 description, period_id, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT',%s,%s,%s,%s,%s)
            RETURNING id
            """,
            [inv_no, inv_date, due_date, d["customer_name"],
             d.get("service_type"), d.get("profit_center_id"),
             float(subtotal), float(discount), float(dpp),
             float(ppn_rate), float(ppn_amt), float(total),
             float(total), payment_terms, d.get("contract_ref"),
             d.get("description"), period["id"], user],
        )
        si_id = si_row["id"]

        for i, line in enumerate(lines, 1):
            fin_execute(
                """
                INSERT INTO fin_invoice_lines
                    (invoice_id, line_no, description, quantity, unit,
                     unit_price, total_price, revenue_account, profit_center_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [si_id, i, line["description"],
                 line.get("quantity", 1), line.get("unit"),
                 float(to_idr(line["unit_price"])),
                 float(to_idr(line["total_price"])),
                 line.get("revenue_account", "4001"),
                 line.get("profit_center_id")],
            )

        return ok({"id": si_id, "invoice_no": inv_no, "total": float(total)},
                  "Invoice created (DRAFT)", 201)
    except Exception as e:
        return err(str(e), 500)


@ar_bp.post("/invoices/<int:inv_id>/post")
@require_auth
@require_finance_role
def post_invoice(inv_id):
    """Post a draft invoice → creates GL entry and marks POSTED."""
    si = fin_query("SELECT * FROM fin_sales_invoices WHERE id = %s", [inv_id])
    if not si:
        return err("Invoice not found", 404)
    if si["status"] != "DRAFT":
        return err(f"Invoice is {si['status']}, cannot post")

    user = request.environ.get("user_email", "system")

    # Determine service type → revenue account
    service_account_map = {
        "PRC": "4001", "TC": "4002", "DISINFECTANT": "4003",
        "FUMIGASI": "4004", "PRODUCT": "4005",
    }
    rev_account = service_account_map.get(si.get("service_type", ""), "4001")

    try:
        je_id = build_journal_entry(
            entry_date=si["invoice_date"],
            description=f"Invoice {si['invoice_no']} — {si['customer_name']}",
            lines=[
                {"account": "1102",    "debit": float(si["total"]),    "credit": 0,
                 "customer_name": si["customer_name"],
                 "description": f"AR: {si['invoice_no']}"},
                {"account": rev_account, "debit": 0, "credit": float(si["dpp"]),
                 "description": f"Revenue: {si['invoice_no']}",
                 "profit_center_id": si.get("profit_center_id")},
                {"account": "2106",    "debit": 0, "credit": float(si["ppn_amount"]),
                 "description": f"PPN: {si['invoice_no']}"},
            ],
            entry_type="AUTO_AR",
            source_module="AR",
            source_id=inv_id,
            created_by=user,
        )
        fin_execute(
            "UPDATE fin_sales_invoices SET status='POSTED', journal_entry_id=%s, updated_at=NOW() WHERE id=%s",
            [je_id, inv_id],
        )
        return ok({"journal_entry_id": je_id}, "Invoice posted to GL")
    except Exception as e:
        return err(str(e), 500)


@ar_bp.post("/invoices/<int:inv_id>/cancel")
@require_auth
@require_finance_role
def cancel_invoice(inv_id):
    si = fin_query("SELECT * FROM fin_sales_invoices WHERE id = %s", [inv_id])
    if not si:
        return err("Invoice not found", 404)
    if si["status"] in ("PAID", "PARTIAL"):
        return err("Cannot cancel invoice with payments")
    fin_execute(
        "UPDATE fin_sales_invoices SET status='CANCELLED', updated_at=NOW() WHERE id=%s",
        [inv_id],
    )
    if si.get("journal_entry_id"):
        # Reverse GL
        from .gl import reverse_journal_entry
        # Build reversal programmatically
        orig_lines = fin_query(
            "SELECT * FROM fin_gl_lines WHERE journal_entry_id = %s", [si["journal_entry_id"]], many=True
        )
        user = request.environ.get("user_email", "system")
        build_journal_entry(
            entry_date=date.today(),
            description=f"CANCEL: Invoice {si['invoice_no']}",
            lines=[{"account": l["account_code"], "debit": float(l["credit"]),
                    "credit": float(l["debit"]), "customer_name": l["customer_name"]} for l in orig_lines],
            entry_type="REVERSAL", source_module="AR", source_id=inv_id, created_by=user,
        )
    return ok({}, "Invoice cancelled")


# ── Payments ─────────────────────────────────────────────────

@ar_bp.post("/payments")
@require_auth
@require_finance_role
def record_payment():
    d = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["customer_name", "payment_date", "gross_amount", "bank_account_id"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    try:
        pmt_date = date.fromisoformat(d["payment_date"])
    except ValueError:
        return err("Invalid payment_date")

    gross  = float(to_idr(d["gross_amount"]))
    charge = float(to_idr(d.get("bank_charge", 0)))
    net    = gross - charge

    bank = fin_query("SELECT * FROM fin_bank_accounts WHERE id = %s", [d["bank_account_id"]])
    if not bank:
        return err("Bank account not found")

    receipt_no_row = fin_query(
        "SELECT next_payment_no('RCP', %s, %s) AS no", [pmt_date.year, pmt_date.month]
    )
    receipt_no = receipt_no_row["no"]

    # GL: Dr Bank, Cr AR
    try:
        je_id = build_journal_entry(
            entry_date=pmt_date,
            description=f"Payment from {d['customer_name']} — {receipt_no}",
            lines=[
                {"account": bank["gl_account"], "debit": gross, "credit": 0,
                 "description": f"Receipt {receipt_no}"},
                {"account": "1102", "debit": 0, "credit": gross,
                 "customer_name": d["customer_name"],
                 "description": f"AR settlement: {receipt_no}"},
                *([{"account": "7004", "debit": charge, "credit": 0,
                    "description": "Bank charge"}] if charge > 0 else []),
            ],
            entry_type="AUTO_AR",
            source_module="AR",
            created_by=user,
        )
        pmt_row = fin_execute_returning(
            """
            INSERT INTO fin_ar_payments
                (receipt_no, payment_date, customer_name, bank_account_id,
                 payment_method, gross_amount, bank_charge, net_amount,
                 reference, notes, journal_entry_id, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            [receipt_no, pmt_date, d["customer_name"], d["bank_account_id"],
             d.get("payment_method", "TRANSFER"), gross, charge, net,
             d.get("reference"), d.get("notes"), je_id, user],
        )
        pmt_id = pmt_row["id"]

        # Auto-allocate to oldest invoices if invoice_ids not specified
        invoice_ids = d.get("invoice_ids", [])
        if not invoice_ids:
            # Auto: oldest due-date first
            oldest = fin_query(
                """SELECT id, outstanding FROM fin_sales_invoices
                   WHERE customer_name = %s AND status NOT IN ('PAID','CANCELLED')
                     AND outstanding > 0
                   ORDER BY due_date, id LIMIT 20""",
                [d["customer_name"]], many=True,
            )
            invoice_ids = [r["id"] for r in oldest]

        remaining = net
        for iid in invoice_ids:
            if remaining <= 0:
                break
            inv = fin_query("SELECT outstanding FROM fin_sales_invoices WHERE id = %s", [iid])
            if not inv or inv["outstanding"] <= 0:
                continue
            alloc = min(float(inv["outstanding"]), remaining)
            fin_execute(
                """INSERT INTO fin_ar_allocations (payment_id, invoice_id, allocated_amount, allocation_date)
                   VALUES (%s,%s,%s,%s) ON CONFLICT (payment_id, invoice_id) DO NOTHING""",
                [pmt_id, iid, alloc, pmt_date],
            )
            remaining -= alloc

        return ok({"payment_id": pmt_id, "receipt_no": receipt_no,
                   "applied": round(net - remaining, 2), "unapplied": round(remaining, 2)},
                  "Payment recorded", 201)
    except Exception as e:
        return err(str(e), 500)


@ar_bp.get("/payments")
@require_auth
@require_finance_role
def list_payments():
    customer = request.args.get("customer")
    year     = request.args.get("year", type=int)
    page     = request.args.get("page", 1, type=int)
    per_page = 50
    offset   = (page - 1) * per_page

    conditions, params = [], []
    if customer:
        conditions.append("p.customer_name ILIKE %s"); params.append(f"%{customer}%")
    if year:
        conditions.append("EXTRACT(YEAR FROM p.payment_date) = %s"); params.append(year)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fin_query(
        f"""SELECT p.*,
                   (SELECT SUM(allocated_amount) FROM fin_ar_allocations WHERE payment_id = p.id) AS allocated
            FROM fin_ar_payments p {where}
            ORDER BY p.payment_date DESC LIMIT %s OFFSET %s""",
        params + [per_page, offset], many=True,
    )
    return ok(rows_to_list(rows))


# ── AR Aging ─────────────────────────────────────────────────

@ar_bp.get("/aging")
@require_auth
@require_finance_role
def ar_aging():
    customer_group = request.args.get("group")
    customer = request.args.get("customer")

    conditions, params = [], []
    if customer_group:
        conditions.append("customer_group = %s"); params.append(customer_group)
    if customer:
        conditions.append("customer_name ILIKE %s"); params.append(f"%{customer}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    summary = fin_query(
        f"""
        SELECT *,
               ROUND(days_over_365 * 100.0 / NULLIF(total_outstanding,0), 1) AS pct_over_365
        FROM   v_fin_ar_aging_summary
        {where}
        ORDER BY total_outstanding DESC
        """,
        params, many=True,
    )

    totals = fin_query(
        f"""
        SELECT
            SUM(total_outstanding) AS grand_total,
            SUM(current_amt)       AS total_current,
            SUM(days_1_30)         AS total_1_30,
            SUM(days_31_60)        AS total_31_60,
            SUM(days_61_90)        AS total_61_90,
            SUM(days_91_180)       AS total_91_180,
            SUM(days_181_365)      AS total_181_365,
            SUM(days_over_365)     AS total_over_365
        FROM v_fin_ar_aging_summary
        {where}
        """,
        params,
    )
    return ok({"summary": rows_to_list(summary), "totals": row_to_dict(totals)})


@ar_bp.get("/aging/detail")
@require_auth
@require_finance_role
def ar_aging_detail():
    customer = request.args.get("customer")
    bucket   = request.args.get("bucket")

    conditions, params = [], []
    if customer:
        conditions.append("customer_name ILIKE %s"); params.append(f"%{customer}%")
    if bucket:
        conditions.append("aging_bucket = %s"); params.append(bucket)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fin_query(
        f"SELECT * FROM v_fin_ar_aging {where} ORDER BY days_overdue DESC",
        params, many=True,
    )
    return ok(rows_to_list(rows))


# ── Dunning ───────────────────────────────────────────────────

@ar_bp.post("/dunning/generate")
@require_auth
@require_finance_role
def generate_dunning():
    """Generate dunning letters for all overdue customers."""
    min_days = request.args.get("min_days", 30, type=int)
    user = request.environ.get("user_email", "system")

    # Find customers with overdue invoices
    overdue = fin_query(
        """
        SELECT customer_name,
               SUM(outstanding)   AS total_outstanding,
               MAX(days_overdue)  AS max_days,
               ARRAY_AGG(invoice_id) AS invoice_ids
        FROM   v_fin_ar_aging
        WHERE  days_overdue >= %s
        GROUP  BY customer_name
        HAVING SUM(outstanding) > 0
        ORDER  BY total_outstanding DESC
        """,
        [min_days], many=True,
    )

    created = []
    for row in overdue:
        level = 1
        if row["max_days"] > 180:
            level = 3
        elif row["max_days"] > 90:
            level = 2

        dr_row = fin_execute_returning(
            """
            INSERT INTO fin_dunning_runs
                (run_date, customer_name, dunning_level, total_outstanding,
                 overdue_days, invoice_ids, created_by)
            VALUES (CURRENT_DATE, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            [row["customer_name"], level, float(row["total_outstanding"]),
             row["max_days"], row["invoice_ids"], user],
        )
        created.append({"customer": row["customer_name"], "level": level,
                        "outstanding": float(row["total_outstanding"]),
                        "dunning_id": dr_row["id"]})

    return ok({"generated": len(created), "items": created})


@ar_bp.get("/dunning")
@require_auth
@require_finance_role
def list_dunning():
    rows = fin_query(
        """SELECT dr.*, CASE dr.dunning_level
               WHEN 1 THEN 'Reminder'
               WHEN 2 THEN 'Warning'
               WHEN 3 THEN 'Final Notice'
               ELSE 'Legal' END AS level_name
           FROM fin_dunning_runs dr
           ORDER BY dr.run_date DESC, dr.total_outstanding DESC
           LIMIT 200""",
        many=True,
    )
    return ok(rows_to_list(rows))


# ── Bad Debt Provision ────────────────────────────────────────

PROVISION_RATES = {
    (0, 90):    0.05,
    (90, 180):  0.10,
    (180, 365): 0.25,
    (365, 730): 0.50,
    (730, None): 1.00,
}


def provision_rate_for_days(days: int) -> float:
    for (lo, hi), rate in PROVISION_RATES.items():
        if days >= lo and (hi is None or days < hi):
            return rate
    return 1.0


@ar_bp.post("/bad-debt/calculate")
@require_auth
@require_finance_role
def calculate_bad_debt():
    """Calculate and post bad debt provision for current open period."""
    period = fin_query(
        "SELECT id, year, period FROM fin_fiscal_periods WHERE status='OPEN' ORDER BY year,period LIMIT 1"
    )
    if not period:
        return err("No open period found")

    user = request.environ.get("user_email", "system")
    detail = fin_query(
        "SELECT * FROM v_fin_ar_aging WHERE days_overdue > 0 ORDER BY customer_name",
        many=True,
    )

    provisions = []
    for row in detail:
        rate = provision_rate_for_days(row["days_overdue"])
        provision = float(to_idr(row["outstanding"])) * rate
        if provision > 0:
            provisions.append({
                "customer_name": row["customer_name"],
                "invoice_id": row["invoice_id"],
                "outstanding": float(row["outstanding"]),
                "overdue_days": row["days_overdue"],
                "provision_rate": rate * 100,
                "provision_amount": round(provision, 2),
            })

    total_provision = sum(p["provision_amount"] for p in provisions)

    if total_provision > 0:
        je_id = build_journal_entry(
            entry_date=date.today(),
            description=f"Bad Debt Provision — {period['year']}/{period['period']:02d}",
            lines=[
                {"account": "6404", "debit": total_provision, "credit": 0,
                 "description": "Bad debt expense"},
                {"account": "1103", "debit": 0, "credit": total_provision,
                 "description": "Allowance for doubtful accounts"},
            ],
            entry_type="MANUAL",
            created_by=user,
        )
        for p in provisions:
            fin_execute(
                """INSERT INTO fin_bad_debt_provisions
                   (period_id, customer_name, invoice_id, outstanding, overdue_days,
                    provision_rate, provision_amount, journal_entry_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (period_id, customer_name, invoice_id) DO UPDATE
                   SET provision_amount = EXCLUDED.provision_amount""",
                [period["id"], p["customer_name"], p.get("invoice_id"),
                 p["outstanding"], p["overdue_days"],
                 p["provision_rate"], p["provision_amount"], je_id],
            )
    return ok({
        "period": f"{period['year']}/{period['period']:02d}",
        "total_provision": total_provision,
        "items": provisions,
        "journal_entry_id": je_id if total_provision > 0 else None,
    })


# ── Customer Statement ────────────────────────────────────────

@ar_bp.get("/statement/<customer_name>")
@require_auth
@require_finance_role
def customer_statement(customer_name):
    year  = request.args.get("year", date.today().year, type=int)
    rows = fin_query(
        """
        SELECT 'INVOICE'              AS txn_type,
               si.invoice_no          AS reference,
               si.invoice_date        AS txn_date,
               si.due_date,
               si.total               AS debit,
               0                      AS credit,
               si.outstanding         AS balance,
               si.status
        FROM   fin_sales_invoices si
        WHERE  si.customer_name = %s AND EXTRACT(YEAR FROM si.invoice_date) = %s
        UNION ALL
        SELECT 'PAYMENT'              AS txn_type,
               p.receipt_no           AS reference,
               p.payment_date         AS txn_date,
               NULL                   AS due_date,
               0                      AS debit,
               p.gross_amount         AS credit,
               0                      AS balance,
               'PAID'                 AS status
        FROM   fin_ar_payments p
        WHERE  p.customer_name = %s AND EXTRACT(YEAR FROM p.payment_date) = %s
        ORDER  BY txn_date, txn_type
        """,
        [customer_name, year, customer_name, year], many=True,
    )
    total_invoiced = sum(float(r["debit"]) for r in rows if r["txn_type"] == "INVOICE")
    total_paid     = sum(float(r["credit"]) for r in rows if r["txn_type"] == "PAYMENT")
    return ok({
        "customer_name": customer_name,
        "year": year,
        "total_invoiced": total_invoiced,
        "total_paid": total_paid,
        "outstanding": round(total_invoiced - total_paid, 2),
        "transactions": rows_to_list(rows),
    })


# ── Collection Forecast ───────────────────────────────────────

@ar_bp.get("/forecast")
@require_auth
@require_finance_role
def collection_forecast():
    rows = fin_query(
        "SELECT * FROM v_fin_collection_forecast ORDER BY 1, 4 DESC",
        many=True,
    )
    # Aggregate by horizon
    horizons: dict[str, float] = {}
    for r in rows:
        horizons[r["horizon"]] = horizons.get(r["horizon"], 0) + float(r["expected_amount"])
    return ok({"by_horizon": horizons, "detail": rows_to_list(rows)})
