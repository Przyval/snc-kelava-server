"""
Accurate Accounting Export API
==============================
Generates daily batch CSV compatible with Accurate accounting software
used by SanoCare for invoicing.
"""

import calendar
import csv
import io
from datetime import date, datetime

from flask import Blueprint, g, jsonify, make_response, request

from core.security import require_auth, require_role
from kil.db.kelava_db import execute_kelava_query

accurate_bp = Blueprint("accurate_export", __name__, url_prefix="/accurate")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_month(month_str: str):
    """Parse 'YYYY-MM' → (first_day, last_day) as date objects."""
    dt = datetime.strptime(month_str, "%Y-%m")
    first_day = date(dt.year, dt.month, 1)
    last_day = date(dt.year, dt.month, calendar.monthrange(dt.year, dt.month)[1])
    return first_day, last_day


def _current_month_str() -> str:
    today = date.today()
    return today.strftime("%Y-%m")


_VISIT_QUERY = """
SELECT
    rp.id AS road_plan_id,
    rp.visit_date::date AS tanggal,
    c.name AS nama_customer,
    c.id AS customer_id,
    u.fullname AS teknisi,
    rp.status,
    k.no_kontrak
FROM t_road_plan rp
JOIN m_customer c ON rp.id_customer = c.id
JOIN p_user u ON rp.id_user = u.id
LEFT JOIN m_customer_kontrak k ON k.id_customer = c.id AND k.is_active = 'YES'
WHERE rp.visit_date::date BETWEEN %s AND %s
  AND rp.status = 'Selesai'
ORDER BY rp.visit_date, c.name
"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@accurate_bp.route("/preview", methods=["GET"])
@require_auth
def preview():
    """GET /accurate/preview?month=YYYY-MM — preview completed visits for a month."""
    month_str = request.args.get("month", _current_month_str())

    try:
        first_day, last_day = _parse_month(month_str)
    except ValueError:
        return jsonify({"error": "Invalid month format. Use YYYY-MM."}), 400

    try:
        rows = execute_kelava_query(_VISIT_QUERY, (first_day, last_day))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if rows is None:
        rows = []

    result_rows = []
    customer_ids = set()
    for row in rows:
        customer_ids.add(row["customer_id"])
        result_rows.append({
            "road_plan_id": row["road_plan_id"],
            "tanggal": str(row["tanggal"]),
            "nama_customer": row["nama_customer"],
            "teknisi": row["teknisi"],
            "no_kontrak": row["no_kontrak"],
            "status": row["status"],
        })

    return jsonify({
        "month": month_str,
        "rows": result_rows,
        "total_visits": len(result_rows),
        "total_customers": len(customer_ids),
        "preview_generated_at": datetime.utcnow().isoformat() + "Z",
    })


@accurate_bp.route("/download", methods=["GET"])
@require_auth
@require_role("admin", "koordinator")
def download():
    """GET /accurate/download?month=YYYY-MM — download CSV for Accurate import."""
    month_str = request.args.get("month", _current_month_str())

    try:
        first_day, last_day = _parse_month(month_str)
    except ValueError:
        return jsonify({"error": "Invalid month format. Use YYYY-MM."}), 400

    try:
        rows = execute_kelava_query(_VISIT_QUERY, (first_day, last_day))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if rows is None:
        rows = []

    # Build CSV in memory with BOM for Excel UTF-8 compatibility
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["No", "Tanggal", "Customer", "No Kontrak", "Teknisi", "Road Plan ID"])

    for idx, row in enumerate(rows, start=1):
        writer.writerow([
            idx,
            str(row["tanggal"]),
            row["nama_customer"],
            row["no_kontrak"] or "",
            row["teknisi"],
            row["road_plan_id"],
        ])

    csv_bytes = b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")

    filename = f"accurate_export_{month_str}.csv"
    response = make_response(csv_bytes)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Log the export (best-effort — don't fail the download if log insert fails)
    try:
        execute_kelava_query(
            """
            INSERT INTO enterprise_accurate_export_log
                (exported_by, export_month, row_count, exported_at)
            VALUES (%s, %s, %s, NOW())
            """,
            (g.user.id, month_str, len(rows)),
        )
    except Exception:
        pass  # table may not exist yet on first deploy

    return response


@accurate_bp.route("/summary", methods=["GET"])
@require_auth
def summary():
    """GET /accurate/summary?months=3 — monthly roll-up for the last N months."""
    try:
        months = int(request.args.get("months", 3))
        if months < 1 or months > 24:
            raise ValueError("out of range")
    except ValueError:
        return jsonify({"error": "months must be an integer between 1 and 24."}), 400

    summary_query = """
    SELECT
        TO_CHAR(rp.visit_date, 'YYYY-MM') AS bulan,
        COUNT(*) AS total_kunjungan,
        COUNT(DISTINCT rp.id_customer) AS total_customer
    FROM t_road_plan rp
    WHERE rp.status = 'Selesai'
      AND rp.visit_date >= NOW() - (%s * INTERVAL '1 month')
    GROUP BY TO_CHAR(rp.visit_date, 'YYYY-MM')
    ORDER BY bulan DESC
    """

    try:
        rows = execute_kelava_query(summary_query, (months,))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if rows is None:
        rows = []

    result = []
    for row in rows:
        result.append({
            "bulan": row["bulan"],
            "total_kunjungan": row["total_kunjungan"],
            "total_customer": row["total_customer"],
        })

    return jsonify({"months": result})
