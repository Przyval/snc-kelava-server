"""
Tax Compliance Blueprint
=========================
PPN Faktur Pajak, PPh23 Bukti Potong, SPT Masa, Tax Calendar.
"""

import csv
import io
from datetime import date

from flask import Blueprint, request, Response

from .core import (
    err, fin_execute, fin_execute_returning, fin_query,
    ok, require_finance_role, row_to_dict, rows_to_list, to_idr,
)
from kil.backend.core.security import require_auth

tax_bp = Blueprint("finance_tax", __name__, url_prefix="/api/v1/finance/tax")

COMPANY_NPWP = "01.234.567.8-123.000"   # replace with actual NPWP
COMPANY_NAME = "PT. ALINDRA PRIMA INDONESIA"


# ── Tax Calendar ──────────────────────────────────────────────

@tax_bp.get("/calendar")
@require_auth
@require_finance_role
def tax_calendar():
    year = request.args.get("year", date.today().year, type=int)
    rows = fin_query(
        """
        SELECT *,
               deadline - CURRENT_DATE AS days_until,
               CASE
                   WHEN status = 'DONE' THEN 'DONE'
                   WHEN deadline < CURRENT_DATE THEN 'OVERDUE'
                   WHEN deadline <= CURRENT_DATE + 7 THEN 'DUE_SOON'
                   ELSE 'UPCOMING'
               END AS urgency
        FROM fin_tax_calendar
        WHERE period_year = %s
        ORDER BY deadline
        """,
        [year], many=True,
    )
    overdue  = sum(1 for r in rows if r["urgency"] == "OVERDUE")
    due_soon = sum(1 for r in rows if r["urgency"] == "DUE_SOON")
    return ok({"items": rows_to_list(rows), "overdue": overdue, "due_soon": due_soon})


@tax_bp.post("/calendar/<int:cal_id>/complete")
@require_auth
@require_finance_role
def mark_tax_done(cal_id: int):
    d    = request.get_json() or {}
    user = request.environ.get("user_email", "system")
    fin_execute(
        """UPDATE fin_tax_calendar
           SET status='DONE', completed_at=NOW(), completed_by=%s, notes=%s
           WHERE id=%s""",
        [user, d.get("notes"), cal_id],
    )
    return ok({}, "Tax obligation marked done")


# ── PPN — Faktur Pajak ────────────────────────────────────────

@tax_bp.get("/ppn/faktur")
@require_auth
@require_finance_role
def list_ppn_faktur():
    year     = request.args.get("year", date.today().year, type=int)
    month    = request.args.get("month", type=int)
    faktur_type = request.args.get("type")  # KELUARAN | MASUKAN

    conditions = ["period_year = %s"]
    params: list = [year]
    if month:
        conditions.append("period_month = %s"); params.append(month)
    if faktur_type:
        conditions.append("faktur_type = %s"); params.append(faktur_type)

    rows = fin_query(
        f"SELECT * FROM fin_ppn_faktur WHERE {' AND '.join(conditions)} ORDER BY faktur_date DESC",
        params, many=True,
    )
    total_keluaran = sum(float(r["ppn_amount"]) for r in rows if r["faktur_type"] == "KELUARAN")
    total_masukan  = sum(float(r["ppn_amount"]) for r in rows if r["faktur_type"] == "MASUKAN")
    return ok({
        "items": rows_to_list(rows),
        "ppn_keluaran": total_keluaran,
        "ppn_masukan":  total_masukan,
        "ppn_kurang_bayar": total_keluaran - total_masukan,
    })


@tax_bp.post("/ppn/faktur")
@require_auth
@require_finance_role
def create_ppn_faktur():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["faktur_date", "faktur_type", "dpp"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    try:
        faktur_date = date.fromisoformat(d["faktur_date"])
    except ValueError:
        return err("Invalid faktur_date")

    dpp        = float(to_idr(d["dpp"]))
    ppn_rate   = float(d.get("ppn_rate", 11.00))
    ppn_amount = round(dpp * ppn_rate / 100, 2)

    # Generate faktur number: 010.000-YY.XXXXXXXX
    count_row = fin_query(
        "SELECT COUNT(*)+1 AS n FROM fin_ppn_faktur WHERE period_year = %s AND period_month = %s",
        [faktur_date.year, faktur_date.month],
    )
    seq = count_row["n"]
    yy  = str(faktur_date.year)[-2:]
    faktur_no = f"010.000-{yy}.{seq:08d}"

    row = fin_execute_returning(
        """
        INSERT INTO fin_ppn_faktur
            (faktur_no, faktur_type, faktur_date, period_year, period_month,
             seller_npwp, seller_name, buyer_npwp, buyer_name, buyer_address,
             dpp, ppn_rate, ppn_amount,
             sales_invoice_id, purchase_invoice_id, notes, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id, faktur_no
        """,
        [faktur_no, d["faktur_type"], faktur_date,
         faktur_date.year, faktur_date.month,
         d.get("seller_npwp", COMPANY_NPWP if d["faktur_type"] == "KELUARAN" else d.get("seller_npwp")),
         d.get("seller_name", COMPANY_NAME if d["faktur_type"] == "KELUARAN" else d.get("seller_name")),
         d.get("buyer_npwp"), d.get("buyer_name"), d.get("buyer_address"),
         dpp, ppn_rate, ppn_amount,
         d.get("sales_invoice_id"), d.get("purchase_invoice_id"),
         d.get("notes"), user],
    )
    return ok({"id": row["id"], "faktur_no": row["faktur_no"], "ppn_amount": ppn_amount},
              "Faktur Pajak created", 201)


@tax_bp.get("/ppn/summary")
@require_auth
@require_finance_role
def ppn_summary():
    year = request.args.get("year", date.today().year, type=int)
    rows = fin_query(
        "SELECT * FROM v_fin_ppn_summary WHERE period_year = %s ORDER BY period_month",
        [year], many=True,
    )
    total_keluaran = sum(float(r["ppn_keluaran"]) for r in rows)
    total_masukan  = sum(float(r["ppn_masukan"]) for r in rows)
    return ok({
        "monthly": rows_to_list(rows),
        "ytd_keluaran":   total_keluaran,
        "ytd_masukan":    total_masukan,
        "ytd_kurang_bayar": total_keluaran - total_masukan,
        "year": year,
    })


@tax_bp.get("/ppn/export-csv")
@require_auth
@require_finance_role
def export_ppn_csv():
    """Export PPN faktur in DJP-compatible CSV format."""
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    conditions = ["period_year = %s", "faktur_type = 'KELUARAN'", "status != 'CANCELLED'"]
    params: list = [year]
    if month:
        conditions.append("period_month = %s"); params.append(month)

    rows = fin_query(
        f"SELECT * FROM fin_ppn_faktur WHERE {' AND '.join(conditions)} ORDER BY faktur_date",
        params, many=True,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["No","Kode Transaksi","BKP/JKP","No Faktur","Tanggal","NPWP Pembeli","Nama Pembeli","DPP","PPN"])
    for i, r in enumerate(rows, 1):
        writer.writerow([
            i, "01", "1", r["faktur_no"],
            r["faktur_date"],
            (r["buyer_npwp"] or "").replace(".","").replace("-",""),
            r["buyer_name"] or "",
            int(r["dpp"]), int(r["ppn_amount"]),
        ])

    filename = f"faktur_ppn_{year}{f'_{month:02d}' if month else ''}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── PPh 23 — Bukti Potong ─────────────────────────────────────

@tax_bp.get("/pph23")
@require_auth
@require_finance_role
def list_pph23():
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    conditions = ["c.period_year = %s"]
    params: list = [year]
    if month:
        conditions.append("c.period_month = %s"); params.append(month)

    rows = fin_query(
        f"""
        SELECT c.*, v.name AS vendor_name, v.npwp AS vendor_npwp
        FROM   fin_pph23_certificates c
        JOIN   fin_vendors v ON v.id = c.vendor_id
        WHERE  {' AND '.join(conditions)}
        ORDER  BY c.period_month, v.name
        """,
        params, many=True,
    )
    total_pph = sum(float(r["pph23_amount"]) for r in rows)
    return ok({"items": rows_to_list(rows), "total_pph23": total_pph, "year": year})


@tax_bp.post("/pph23/generate")
@require_auth
@require_finance_role
def generate_pph23_certificate():
    """Generate bukti potong from an AP payment."""
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["vendor_id", "period_year", "period_month", "gross_amount", "pph23_amount"]
    if not all(d.get(k) is not None for k in required):
        return err(f"Required: {required}")

    # Generate bukti potong number: BP23-YYYYMM-XXXX
    count_row = fin_query(
        "SELECT COUNT(*)+1 AS n FROM fin_pph23_certificates WHERE period_year=%s AND period_month=%s",
        [d["period_year"], d["period_month"]],
    )
    bp_no = f"BP23-{d['period_year']}{d['period_month']:02d}-{count_row['n']:04d}"

    row = fin_execute_returning(
        """
        INSERT INTO fin_pph23_certificates
            (bukti_potong_no, vendor_id, period_year, period_month,
             income_type, gross_amount, pph23_rate, pph23_amount,
             payment_date, ap_payment_id, status, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ISSUED',%s)
        ON CONFLICT DO NOTHING
        RETURNING id, bukti_potong_no
        """,
        [bp_no, d["vendor_id"], d["period_year"], d["period_month"],
         d.get("income_type", "Jasa"), float(to_idr(d["gross_amount"])),
         float(d.get("pph23_rate", 2.00)), float(to_idr(d["pph23_amount"])),
         d.get("payment_date"), d.get("ap_payment_id"), user],
    )
    if not row:
        return ok({}, "Certificate already exists for this payment")
    return ok({"id": row["id"], "bukti_potong_no": row["bukti_potong_no"]},
              "Bukti Potong PPh23 generated", 201)


@tax_bp.get("/pph23/summary")
@require_auth
@require_finance_role
def pph23_summary():
    year = request.args.get("year", date.today().year, type=int)
    rows = fin_query(
        "SELECT * FROM v_fin_pph23_monthly WHERE period_year = %s ORDER BY period_month",
        [year], many=True,
    )
    return ok({"monthly": rows_to_list(rows), "year": year})


@tax_bp.get("/pph23/export-csv")
@require_auth
@require_finance_role
def export_pph23_csv():
    """Export PPh23 rekap for SPT Masa."""
    year  = request.args.get("year", date.today().year, type=int)
    month = request.args.get("month", type=int)

    conditions = ["c.period_year = %s"]
    params: list = [year]
    if month:
        conditions.append("c.period_month = %s"); params.append(month)

    rows = fin_query(
        f"""
        SELECT c.bukti_potong_no, c.period_month, v.name AS vendor_name,
               v.npwp AS vendor_npwp, c.income_type,
               c.gross_amount, c.pph23_rate, c.pph23_amount, c.payment_date
        FROM fin_pph23_certificates c
        JOIN fin_vendors v ON v.id = c.vendor_id
        WHERE {' AND '.join(conditions)}
        ORDER BY c.period_month, v.name
        """,
        params, many=True,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["No Bukti Potong","Bulan","NPWP Vendor","Nama Vendor","Jenis Penghasilan",
                     "Jumlah Bruto","Tarif PPh23 (%)","PPh23 Dipotong","Tanggal Bayar"])
    for r in rows:
        writer.writerow([
            r["bukti_potong_no"], r["period_month"],
            (r["vendor_npwp"] or "").replace(".","").replace("-",""),
            r["vendor_name"], r["income_type"],
            int(r["gross_amount"]), r["pph23_rate"], int(r["pph23_amount"]),
            r["payment_date"] or "",
        ])

    filename = f"pph23_{year}{f'_{month:02d}' if month else ''}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── SPT Masa Management ───────────────────────────────────────

@tax_bp.get("/spt")
@require_auth
@require_finance_role
def list_spt():
    year = request.args.get("year", date.today().year, type=int)
    rows = fin_query(
        "SELECT * FROM fin_spt_masa WHERE period_year = %s ORDER BY spt_type, period_month",
        [year], many=True,
    )
    return ok(rows_to_list(rows))


@tax_bp.post("/spt")
@require_auth
@require_finance_role
def upsert_spt():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["spt_type", "period_year", "period_month"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    row = fin_execute_returning(
        """
        INSERT INTO fin_spt_masa
            (spt_type, period_year, period_month, total_dpp, total_tax,
             tax_paid, kurang_bayar, lebih_bayar, status, filing_date,
             payment_date, ntpn, notes, created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (spt_type, period_year, period_month) DO UPDATE SET
            total_dpp    = EXCLUDED.total_dpp,
            total_tax    = EXCLUDED.total_tax,
            tax_paid     = EXCLUDED.tax_paid,
            status       = EXCLUDED.status,
            filing_date  = EXCLUDED.filing_date,
            ntpn         = EXCLUDED.ntpn
        RETURNING id, status
        """,
        [d["spt_type"], d["period_year"], d["period_month"],
         float(to_idr(d.get("total_dpp", 0))), float(to_idr(d.get("total_tax", 0))),
         float(to_idr(d.get("tax_paid", 0))), float(to_idr(d.get("kurang_bayar", 0))),
         float(to_idr(d.get("lebih_bayar", 0))), d.get("status", "DRAFT"),
         d.get("filing_date"), d.get("payment_date"), d.get("ntpn"),
         d.get("notes"), user],
    )
    return ok(row_to_dict(row), "SPT saved", 201)


# ── Tax Dashboard ─────────────────────────────────────────────

@tax_bp.get("/dashboard")
@require_auth
@require_finance_role
def tax_dashboard():
    year = request.args.get("year", date.today().year, type=int)

    ppn  = fin_query("SELECT * FROM v_fin_ppn_summary WHERE period_year = %s ORDER BY period_month", [year], many=True)
    pph  = fin_query("SELECT * FROM v_fin_pph23_monthly WHERE period_year = %s ORDER BY period_month", [year], many=True)
    cal  = fin_query(
        """SELECT * FROM fin_tax_calendar WHERE period_year = %s AND status != 'DONE'
           ORDER BY deadline LIMIT 10""",
        [year], many=True,
    )
    overdue = fin_query("SELECT COUNT(*) AS n FROM v_fin_tax_overdue", many=False)

    return ok({
        "ppn_monthly":  rows_to_list(ppn),
        "pph23_monthly": rows_to_list(pph),
        "upcoming_obligations": rows_to_list(cal),
        "overdue_count": int(overdue["n"]) if overdue else 0,
        "year": year,
    })
