"""
Accounts Payable Blueprint
===========================
Vendor Master, Purchase Invoices, AP Payments, PPh23 Certificates.
"""

from datetime import date, timedelta

from flask import Blueprint, request

from .core import (
    build_journal_entry,
    err, fin_execute, fin_execute_returning, fin_query,
    ok, require_finance_role, resolve_period,
    row_to_dict, rows_to_list, to_idr,
)
from kil.backend.core.security import require_auth

ap_bp = Blueprint("finance_ap", __name__, url_prefix="/api/v1/finance/ap")


# ── Vendor Master ─────────────────────────────────────────────

@ap_bp.get("/vendors")
@require_auth
@require_finance_role
def list_vendors():
    search = request.args.get("q", "")
    rows = fin_query(
        """
        SELECT v.*,
               COALESCE(ap.total_outstanding, 0) AS total_outstanding
        FROM   fin_vendors v
        LEFT JOIN (
            SELECT vendor_id, SUM(outstanding) AS total_outstanding
            FROM   fin_purchase_invoices
            WHERE  status NOT IN ('PAID','CANCELLED')
            GROUP  BY vendor_id
        ) ap ON ap.vendor_id = v.id
        WHERE  %s = '' OR LOWER(v.name) LIKE LOWER(%s)
        ORDER  BY v.name
        """,
        [search, f"%{search}%"], many=True,
    )
    return ok(rows_to_list(rows))


@ap_bp.post("/vendors")
@require_auth
@require_finance_role
def create_vendor():
    d = request.get_json()
    if not d.get("name"):
        return err("name required")
    try:
        row = fin_execute_returning(
            """
            INSERT INTO fin_vendors
                (name, npwp, address, city, bank_name, bank_account,
                 bank_account_name, payment_terms, ap_account,
                 vendor_category, pph23_subject, pph23_rate, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
            """,
            [d["name"], d.get("npwp"), d.get("address"), d.get("city"),
             d.get("bank_name"), d.get("bank_account"), d.get("bank_account_name"),
             d.get("payment_terms", 30), d.get("ap_account", "2101"),
             d.get("vendor_category"), d.get("pph23_subject", False),
             d.get("pph23_rate", 2.00), d.get("notes")],
        )
        return ok(row_to_dict(row), "Vendor created", 201)
    except Exception as e:
        return err(str(e))


# ── Purchase Invoices ─────────────────────────────────────────

@ap_bp.get("/invoices")
@require_auth
@require_finance_role
def list_purchase_invoices():
    status   = request.args.get("status")
    vendor   = request.args.get("vendor", type=int)
    year     = request.args.get("year", type=int)
    page     = request.args.get("page", 1, type=int)
    per_page = 50
    offset   = (page - 1) * per_page

    conditions, params = [], []
    if status:
        conditions.append("pi.status = %s"); params.append(status)
    if vendor:
        conditions.append("pi.vendor_id = %s"); params.append(vendor)
    if year:
        conditions.append("EXTRACT(YEAR FROM pi.invoice_date) = %s"); params.append(year)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fin_query(
        f"""
        SELECT pi.*, v.name AS vendor_name,
               CURRENT_DATE - pi.due_date AS days_overdue
        FROM   fin_purchase_invoices pi
        JOIN   fin_vendors v ON v.id = pi.vendor_id
        {where}
        ORDER  BY pi.invoice_date DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset], many=True,
    )
    return ok(rows_to_list(rows))


@ap_bp.post("/invoices")
@require_auth
@require_finance_role
def create_purchase_invoice():
    d = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["vendor_id", "invoice_date", "lines"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    try:
        inv_date = date.fromisoformat(d["invoice_date"])
    except ValueError:
        return err("Invalid invoice_date")

    period = resolve_period(inv_date)
    if not period or period["status"] in ("CLOSED", "LOCKED"):
        return err("Period closed or not found")

    vendor = fin_query("SELECT * FROM fin_vendors WHERE id = %s", [d["vendor_id"]])
    if not vendor:
        return err("Vendor not found")

    lines = d.get("lines", [])
    subtotal = sum(to_idr(l.get("total_price", 0)) for l in lines)
    ppn_amt  = to_idr(d.get("ppn_amount", 0))
    total_gross = subtotal + ppn_amt
    pph23 = to_idr(0)
    if vendor["pph23_subject"]:
        pph23 = (subtotal * to_idr(vendor["pph23_rate"]) / 100)
    total_net = total_gross - pph23

    payment_terms = d.get("payment_terms", vendor["payment_terms"] or 30)
    due_date = date.fromisoformat(d["due_date"]) if d.get("due_date") else (inv_date + timedelta(days=payment_terms))

    inv_no_row = fin_query(
        "SELECT next_purchase_invoice_no(%s,%s) AS no", [inv_date.year, inv_date.month]
    )
    inv_no = inv_no_row["no"]

    try:
        pi_row = fin_execute_returning(
            """
            INSERT INTO fin_purchase_invoices
                (invoice_no, vendor_invoice_no, invoice_date, due_date, vendor_id,
                 cost_center_id, subtotal, ppn_amount, pph23_amount, total_gross, total_net,
                 outstanding, status, description, period_id, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RECEIVED',%s,%s,%s)
            RETURNING id
            """,
            [inv_no, d.get("vendor_invoice_no"), inv_date, due_date, d["vendor_id"],
             d.get("cost_center_id"),
             float(subtotal), float(ppn_amt), float(pph23),
             float(total_gross), float(total_net), float(total_net),
             d.get("description"), period["id"], user],
        )
        pi_id = pi_row["id"]

        for i, line in enumerate(lines, 1):
            fin_execute(
                """INSERT INTO fin_purchase_lines
                   (invoice_id, line_no, description, quantity, unit,
                    unit_price, total_price, expense_account, cost_center_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [pi_id, i, line["description"], line.get("quantity", 1), line.get("unit"),
                 float(to_idr(line["unit_price"])), float(to_idr(line["total_price"])),
                 line.get("expense_account", "5001"), line.get("cost_center_id")],
            )

        # Auto-post GL on creation
        expense_account = lines[0].get("expense_account", "5001") if lines else "5001"
        gl_lines = [
            {"account": expense_account, "debit": float(subtotal), "credit": 0,
             "vendor_id": d["vendor_id"], "description": f"Expense: {inv_no}"},
            {"account": "2101", "debit": 0, "credit": float(total_net),
             "vendor_id": d["vendor_id"], "description": f"AP: {inv_no}"},
        ]
        if float(ppn_amt) > 0:
            gl_lines.append({"account": "1108-01", "debit": float(ppn_amt), "credit": 0,
                              "description": f"PPN masukan: {inv_no}"})
        if float(pph23) > 0:
            gl_lines.append({"account": "2107", "debit": 0, "credit": float(pph23),
                              "description": f"PPh23 payable: {inv_no}"})

        je_id = build_journal_entry(
            entry_date=inv_date,
            description=f"Purchase Invoice {inv_no} — {vendor['name']}",
            lines=gl_lines,
            entry_type="AUTO_AP",
            source_module="AP", source_id=pi_id,
            created_by=user,
        )
        fin_execute(
            "UPDATE fin_purchase_invoices SET status='APPROVED', journal_entry_id=%s, approved_by=%s, approved_at=NOW() WHERE id=%s",
            [je_id, user, pi_id],
        )
        return ok({"id": pi_id, "invoice_no": inv_no, "total_net": float(total_net)},
                  "Purchase invoice created and posted", 201)
    except Exception as e:
        return err(str(e), 500)


# ── AP Payments ───────────────────────────────────────────────

@ap_bp.post("/payments")
@require_auth
@require_finance_role
def record_ap_payment():
    d = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["vendor_id", "payment_date", "gross_amount", "bank_account_id", "invoice_ids"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    try:
        pmt_date = date.fromisoformat(d["payment_date"])
    except ValueError:
        return err("Invalid payment_date")

    vendor = fin_query("SELECT * FROM fin_vendors WHERE id = %s", [d["vendor_id"]])
    if not vendor:
        return err("Vendor not found")

    bank = fin_query("SELECT * FROM fin_bank_accounts WHERE id = %s", [d["bank_account_id"]])
    if not bank:
        return err("Bank account not found")

    gross  = float(to_idr(d["gross_amount"]))
    pph23  = float(to_idr(d.get("pph23_withheld", 0)))
    net    = gross - pph23

    pmt_no_row = fin_query(
        "SELECT next_payment_no('PMT',%s,%s) AS no", [pmt_date.year, pmt_date.month]
    )
    pmt_no = pmt_no_row["no"]

    gl_lines = [
        {"account": "2101", "debit": gross, "credit": 0,
         "vendor_id": d["vendor_id"], "description": f"AP settlement: {pmt_no}"},
        {"account": bank["gl_account"], "debit": 0, "credit": net,
         "description": f"Payment {pmt_no}"},
    ]
    if pph23 > 0:
        gl_lines.append({"account": "2107", "debit": 0, "credit": pph23,
                         "description": f"PPh23 withheld: {pmt_no}"})

    try:
        je_id = build_journal_entry(
            entry_date=pmt_date,
            description=f"AP Payment to {vendor['name']} — {pmt_no}",
            lines=gl_lines,
            entry_type="AUTO_AP",
            source_module="AP",
            created_by=user,
        )
        pmt_row = fin_execute_returning(
            """INSERT INTO fin_ap_payments
               (payment_no, payment_date, vendor_id, bank_account_id, payment_method,
                gross_amount, pph23_withheld, net_amount, reference, notes,
                journal_entry_id, created_by, approved_by, approved_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()) RETURNING id""",
            [pmt_no, pmt_date, d["vendor_id"], d["bank_account_id"],
             d.get("payment_method", "TRANSFER"),
             gross, pph23, net, d.get("reference"), d.get("notes"),
             je_id, user, user],
        )
        pmt_id = pmt_row["id"]

        for iid in d["invoice_ids"]:
            inv = fin_query("SELECT outstanding FROM fin_purchase_invoices WHERE id = %s", [iid])
            if inv:
                fin_execute(
                    """INSERT INTO fin_ap_allocations (payment_id, invoice_id, allocated_amount, allocation_date)
                       VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    [pmt_id, iid, float(inv["outstanding"]), pmt_date],
                )
        return ok({"payment_id": pmt_id, "payment_no": pmt_no}, "AP Payment recorded", 201)
    except Exception as e:
        return err(str(e), 500)


# ── AP Aging ──────────────────────────────────────────────────

@ap_bp.get("/aging")
@require_auth
@require_finance_role
def ap_aging():
    rows = fin_query(
        """
        SELECT vendor_name, vendor_category,
               SUM(outstanding)                                        AS total_outstanding,
               SUM(CASE WHEN aging_bucket='CURRENT' THEN outstanding ELSE 0 END) AS current_amt,
               SUM(CASE WHEN aging_bucket='1-30'    THEN outstanding ELSE 0 END) AS days_1_30,
               SUM(CASE WHEN aging_bucket='31-60'   THEN outstanding ELSE 0 END) AS days_31_60,
               SUM(CASE WHEN aging_bucket='61-90'   THEN outstanding ELSE 0 END) AS days_61_90,
               SUM(CASE WHEN aging_bucket='>90'     THEN outstanding ELSE 0 END) AS days_over_90,
               MAX(days_overdue)                                       AS max_days_overdue
        FROM   v_fin_ap_aging
        GROUP  BY vendor_name, vendor_category
        ORDER  BY total_outstanding DESC
        """,
        many=True,
    )
    return ok(rows_to_list(rows))


# ── Payment Forecast ──────────────────────────────────────────

@ap_bp.get("/forecast")
@require_auth
@require_finance_role
def payment_forecast():
    rows = fin_query(
        "SELECT * FROM v_fin_payment_forecast ORDER BY 1, 4 DESC",
        many=True,
    )
    horizons: dict[str, float] = {}
    for r in rows:
        horizons[r["horizon"]] = horizons.get(r["horizon"], 0) + float(r["expected_payment"])
    return ok({"by_horizon": horizons, "detail": rows_to_list(rows)})


# ── PPh23 Certificates ────────────────────────────────────────

@ap_bp.get("/pph23")
@require_auth
@require_finance_role
def list_pph23():
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    conditions = ["c.period_year = %s"]
    params = [year]
    if month:
        conditions.append("c.period_month = %s"); params.append(month)

    rows = fin_query(
        f"""SELECT c.*, v.name AS vendor_name, v.npwp AS vendor_npwp
            FROM fin_pph23_certificates c JOIN fin_vendors v ON v.id = c.vendor_id
            WHERE {' AND '.join(conditions)} ORDER BY c.period_month, v.name""",
        params, many=True,
    )
    total = sum(float(r["pph23_amount"]) for r in rows)
    return ok({"items": rows_to_list(rows), "total_pph23": total, "year": year})
