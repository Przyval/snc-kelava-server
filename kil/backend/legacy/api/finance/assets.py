"""
Asset Management (AM) Blueprint
=================================
Asset Register, Depreciation Runs, Disposal, Physical Inventory.
"""

from datetime import date
from decimal import Decimal

from flask import Blueprint, request

from .core import (
    build_journal_entry,
    err, fin_execute, fin_execute_returning, fin_query,
    ok, require_finance_role, resolve_period,
    row_to_dict, rows_to_list, to_idr,
)
from kil.backend.core.security import require_auth

am_bp = Blueprint("finance_am", __name__, url_prefix="/api/v1/finance/assets")


# ── Asset Register ────────────────────────────────────────────

@am_bp.get("")
@require_auth
@require_finance_role
def list_assets():
    category = request.args.get("category")
    status   = request.args.get("status")   # ACTIVE | DISPOSED | FULLY_DEPRECIATED
    q        = request.args.get("q", "")
    page     = request.args.get("page", 1, type=int)
    per_page = 50

    conditions, params = [], []
    if category:
        conditions.append("category = %s"); params.append(category)
    if status == "DISPOSED":
        conditions.append("status = 'DISPOSED'")
    elif status == "ACTIVE":
        conditions.append("status != 'DISPOSED'")
    if q:
        conditions.append("(LOWER(description) LIKE LOWER(%s) OR asset_no LIKE %s)")
        params += [f"%{q}%", f"%{q}%"]

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fin_query(
        f"SELECT * FROM v_fin_asset_register {where} ORDER BY asset_no LIMIT %s OFFSET %s",
        params + [per_page, (page-1)*per_page], many=True,
    )
    return ok(rows_to_list(rows))


@am_bp.get("/<int:asset_id>")
@require_auth
@require_finance_role
def get_asset(asset_id: int):
    asset = fin_query("SELECT * FROM v_fin_asset_register WHERE id = %s", [asset_id])
    if not asset:
        return err("Asset not found", 404)

    movements = fin_query(
        "SELECT * FROM fin_asset_movements WHERE asset_id = %s ORDER BY movement_date DESC",
        [asset_id], many=True,
    )
    dep_sched = fin_query(
        """SELECT * FROM fin_depreciation_schedule
           WHERE asset_id = %s ORDER BY period_year DESC, period_month DESC
           LIMIT 24""",
        [asset_id], many=True,
    )
    return ok({
        "asset": row_to_dict(asset),
        "movements": rows_to_list(movements),
        "depreciation_schedule": rows_to_list(dep_sched),
    })


@am_bp.post("")
@require_auth
@require_finance_role
def create_asset():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["description", "category", "purchase_date", "purchase_cost", "useful_life_months"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    # Auto-generate asset_no: CATEGORY-YEAR-SEQ
    cat_prefix = d["category"][:3].upper()
    count_row  = fin_query(
        "SELECT COUNT(*)+1 AS n FROM fin_assets WHERE category = %s", [d["category"]]
    )
    asset_no = f"{cat_prefix}-{date.today().year}-{count_row['n']:04d}"

    try:
        purchase_cost = float(to_idr(d["purchase_cost"]))
        row = fin_execute_returning(
            """
            INSERT INTO fin_assets
                (asset_no, description, category, brand, model, serial_no,
                 purchase_date, purchase_cost, useful_life_months, depreciation_method,
                 salvage_value, location, cost_center_id, condition,
                 asset_account, depreciation_account, accumulated_depreciation_account,
                 notes, current_book_value, accumulated_depreciation,
                 status, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,'ACTIVE',%s)
            RETURNING id, asset_no
            """,
            [asset_no, d["description"], d["category"],
             d.get("brand"), d.get("model"), d.get("serial_no"),
             d["purchase_date"], purchase_cost,
             d["useful_life_months"],
             d.get("depreciation_method", "STRAIGHT_LINE"),
             float(to_idr(d.get("salvage_value", 0))),
             d.get("location"), d.get("cost_center_id"),
             d.get("condition", "GOOD"),
             d.get("asset_account", "1501"),
             d.get("depreciation_account", "6101"),
             d.get("accumulated_depreciation_account", "1502"),
             d.get("notes"), purchase_cost, user],
        )

        # Generate depreciation schedule upfront (24 months)
        _generate_dep_schedule(row["id"], d)

        return ok({"id": row["id"], "asset_no": row["asset_no"]}, "Asset created", 201)
    except Exception as e:
        return err(str(e), 500)


def _generate_dep_schedule(asset_id: int, d: dict):
    """Pre-compute monthly depreciation schedule for the asset."""
    purchase_cost = float(to_idr(d["purchase_cost"]))
    salvage       = float(to_idr(d.get("salvage_value", 0)))
    life_months   = int(d["useful_life_months"])
    method        = d.get("depreciation_method", "STRAIGHT_LINE")
    purchase_date = date.fromisoformat(d["purchase_date"])

    book_value = purchase_cost
    for i in range(min(life_months, 120)):  # cap at 10 years preview
        m     = (purchase_date.month - 1 + i) % 12 + 1
        y     = purchase_date.year + (purchase_date.month - 1 + i) // 12
        if method == "STRAIGHT_LINE":
            dep = round((purchase_cost - salvage) / life_months, 2)
        else:  # DECLINING_BALANCE
            dep = round(max(book_value - salvage, 0) * 2 / life_months, 2)

        dep = min(dep, max(book_value - salvage, 0))
        closing = round(book_value - dep, 2)

        fin_execute(
            """
            INSERT INTO fin_depreciation_schedule
                (asset_id, period_year, period_month, opening_value, depreciation, closing_value)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (asset_id, period_year, period_month) DO NOTHING
            """,
            [asset_id, y, m, round(book_value, 2), dep, closing],
        )
        book_value = closing
        if book_value <= salvage:
            break


# ── Depreciation Run ──────────────────────────────────────────

@am_bp.post("/depreciation/run")
@require_auth
@require_finance_role
def run_depreciation():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["period_year", "period_month"]
    if not all(d.get(k) for k in required):
        return err("period_year and period_month required")

    year  = int(d["period_year"])
    month = int(d["period_month"])

    period = fin_query(
        "SELECT * FROM fin_fiscal_periods WHERE year = %s AND period = %s",
        [year, month],
    )
    if not period or period["status"] in ("CLOSED", "LOCKED"):
        return err("Period closed/locked or not found")

    # Get all unposted depreciation for this period
    lines = fin_query(
        """
        SELECT ds.*, a.description, a.asset_no,
               a.depreciation_account, a.accumulated_depreciation_account,
               a.cost_center_id
        FROM fin_depreciation_schedule ds
        JOIN fin_assets a ON a.id = ds.asset_id
        WHERE ds.period_year = %s AND ds.period_month = %s
          AND ds.is_posted = FALSE
          AND a.status != 'DISPOSED'
          AND ds.depreciation > 0
        """,
        [year, month], many=True,
    )
    if not lines:
        return ok({"posted": 0}, "No depreciation entries to post")

    total_dep = sum(float(l["depreciation"]) for l in lines)

    # Build GL lines
    gl_lines = []
    for l in lines:
        gl_lines.append({
            "account": l["depreciation_account"] or "6101",
            "debit": float(l["depreciation"]), "credit": 0,
            "cost_center_id": l["cost_center_id"],
            "description": f"Depreciation {l['asset_no']} {year}/{month:02d}",
        })
        gl_lines.append({
            "account": l["accumulated_depreciation_account"] or "1502",
            "debit": 0, "credit": float(l["depreciation"]),
            "description": f"Acc.Dep {l['asset_no']} {year}/{month:02d}",
        })

    try:
        dep_date = date(year, month, 1)
        # Find last day of month
        import calendar as cal
        dep_date = date(year, month, cal.monthrange(year, month)[1])

        je_id = build_journal_entry(
            entry_date=dep_date,
            description=f"Monthly Depreciation Run {year}/{month:02d}",
            lines=gl_lines,
            entry_type="AUTO_DEPRECIATION",
            source_module="AM",
            created_by=user,
        )

        # Create run record
        run_row = fin_execute_returning(
            """
            INSERT INTO fin_depreciation_runs
                (period_id, run_date, total_depreciation, posted)
            VALUES (%s, %s, %s, TRUE) RETURNING id
            """,
            [period["id"], dep_date, total_dep],
        )
        run_id = run_row["id"]

        # Mark schedule lines as posted + update asset book values
        for l in lines:
            fin_execute(
                """
                UPDATE fin_depreciation_schedule
                SET is_posted = TRUE, journal_entry_id = %s
                WHERE id = %s
                """,
                [je_id, l["id"]],
            )
            fin_execute(
                """
                UPDATE fin_assets
                SET accumulated_depreciation = accumulated_depreciation + %s,
                    current_book_value = purchase_cost - accumulated_depreciation - %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                [float(l["depreciation"]), float(l["depreciation"]) + float(l.get("accumulated_depreciation", 0) or 0), l["asset_id"]],
            )

        return ok(
            {"run_id": run_id, "posted": len(lines), "total_depreciation": total_dep},
            f"Depreciation run posted: {len(lines)} assets, total Rp {total_dep:,.0f}",
        )
    except Exception as e:
        return err(str(e), 500)


@am_bp.get("/depreciation/schedule")
@require_auth
@require_finance_role
def depreciation_schedule():
    year = request.args.get("year", date.today().year, type=int)
    rows = fin_query(
        """
        SELECT a.asset_no, a.description, a.category,
               SUM(ds.depreciation) AS total_dep,
               COUNT(*) AS months
        FROM fin_depreciation_schedule ds
        JOIN fin_assets a ON a.id = ds.asset_id
        WHERE ds.period_year = %s AND ds.is_posted = FALSE
        GROUP BY a.asset_no, a.description, a.category
        ORDER BY total_dep DESC
        """,
        [year], many=True,
    )
    return ok(rows_to_list(rows))


@am_bp.get("/depreciation/forecast")
@require_auth
@require_finance_role
def depreciation_forecast():
    rows = fin_query("SELECT * FROM v_fin_depreciation_forecast ORDER BY forecast_month, asset_id", many=True)
    # Aggregate by month
    by_month: dict = {}
    for r in rows:
        k = str(r["forecast_month"])[:7]
        by_month[k] = by_month.get(k, 0) + float(r["monthly_depreciation"] or 0)
    return ok({"by_month": by_month, "detail": rows_to_list(rows)})


# ── Asset Disposal ────────────────────────────────────────────

@am_bp.post("/<int:asset_id>/dispose")
@require_auth
@require_finance_role
def dispose_asset(asset_id: int):
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    required = ["disposal_date", "disposal_type"]
    if not all(d.get(k) for k in required):
        return err(f"Required: {required}")

    asset = fin_query("SELECT * FROM fin_assets WHERE id = %s", [asset_id])
    if not asset:
        return err("Asset not found", 404)
    if asset["status"] == "DISPOSED":
        return err("Asset already disposed")

    try:
        disposal_date = date.fromisoformat(d["disposal_date"])
    except ValueError:
        return err("Invalid disposal_date")

    book_value = float(asset["current_book_value"] or
                       (float(asset["purchase_cost"]) - float(asset["accumulated_depreciation"] or 0)))
    sale_amount = float(to_idr(d.get("sale_amount", 0)))
    gain_loss   = sale_amount - book_value

    period = resolve_period(disposal_date)
    if not period or period["status"] in ("CLOSED", "LOCKED"):
        return err("Period closed or not found")

    gl_lines = [
        {"account": asset["accumulated_depreciation_account"] or "1502",
         "debit": float(asset["accumulated_depreciation"] or 0), "credit": 0,
         "description": f"Acc.dep disposal {asset['asset_no']}"},
        {"account": asset["asset_account"] or "1501",
         "debit": 0, "credit": float(asset["purchase_cost"]),
         "description": f"Asset disposal {asset['asset_no']}"},
    ]
    if sale_amount > 0:
        gl_lines.append({
            "account": "1101", "debit": sale_amount, "credit": 0,
            "description": f"Proceeds disposal {asset['asset_no']}"
        })
    if gain_loss > 0:
        gl_lines.append({"account": "7001", "debit": 0, "credit": gain_loss,
                         "description": f"Gain on disposal {asset['asset_no']}"})
    elif gain_loss < 0:
        gl_lines.append({"account": "7002", "debit": abs(gain_loss), "credit": 0,
                         "description": f"Loss on disposal {asset['asset_no']}"})

    try:
        je_id = build_journal_entry(
            entry_date=disposal_date,
            description=f"Asset Disposal {asset['asset_no']} — {d['disposal_type']}",
            lines=gl_lines,
            entry_type="AUTO_DEPRECIATION",
            source_module="AM", source_id=asset_id,
            created_by=user,
        )
        dis_row = fin_execute_returning(
            """
            INSERT INTO fin_asset_disposals
                (asset_id, disposal_date, disposal_type, sale_amount,
                 book_value_at_disposal, gain_loss, buyer_name, reference,
                 journal_entry_id, approved_by, notes, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """,
            [asset_id, disposal_date, d["disposal_type"], sale_amount,
             book_value, gain_loss, d.get("buyer_name"), d.get("reference"),
             je_id, user, d.get("notes"), user],
        )
        fin_execute(
            "UPDATE fin_assets SET status = 'DISPOSED', updated_at = NOW() WHERE id = %s",
            [asset_id],
        )
        return ok(
            {"disposal_id": dis_row["id"], "gain_loss": gain_loss},
            f"Asset disposed. {'Gain' if gain_loss >= 0 else 'Loss'}: Rp {abs(gain_loss):,.0f}",
        )
    except Exception as e:
        return err(str(e), 500)


# ── Asset Movements ───────────────────────────────────────────

@am_bp.post("/<int:asset_id>/move")
@require_auth
@require_finance_role
def move_asset(asset_id: int):
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    if not d.get("to_location"):
        return err("to_location required")

    asset = fin_query("SELECT location, cost_center_id FROM fin_assets WHERE id = %s", [asset_id])
    if not asset:
        return err("Asset not found", 404)

    fin_execute_returning(
        """
        INSERT INTO fin_asset_movements
            (asset_id, movement_date, from_location, to_location,
             from_cc_id, to_cc_id, from_user, to_user, reason, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        [asset_id, d.get("movement_date", date.today().isoformat()),
         asset["location"], d["to_location"],
         asset["cost_center_id"], d.get("to_cc_id"),
         d.get("from_user"), d.get("to_user"),
         d.get("reason"), user],
    )
    fin_execute(
        "UPDATE fin_assets SET location = %s, cost_center_id = COALESCE(%s, cost_center_id), updated_at = NOW() WHERE id = %s",
        [d["to_location"], d.get("to_cc_id"), asset_id],
    )
    return ok({}, "Asset moved")


# ── Physical Inventory ────────────────────────────────────────

@am_bp.post("/inventory/sessions")
@require_auth
@require_finance_role
def create_inventory_session():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    import uuid
    session_code = f"INV-{date.today().strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}"

    total = fin_query("SELECT COUNT(*) AS n FROM fin_assets WHERE status != 'DISPOSED'")
    row = fin_execute_returning(
        """
        INSERT INTO fin_inventory_sessions
            (session_code, conducted_by, total_assets, notes)
        VALUES (%s,%s,%s,%s) RETURNING id, session_code
        """,
        [session_code, d.get("conducted_by", user), total["n"] if total else 0, d.get("notes")],
    )
    return ok(row_to_dict(row), "Inventory session created", 201)


@am_bp.post("/inventory/scan")
@require_auth
@require_finance_role
def scan_asset():
    d    = request.get_json()
    user = request.environ.get("user_email", "system")
    if not d.get("asset_id") and not d.get("asset_no"):
        return err("asset_id or asset_no required")

    asset_id = d.get("asset_id")
    if not asset_id:
        a = fin_query("SELECT id FROM fin_assets WHERE asset_no = %s", [d["asset_no"]])
        if not a:
            return err("Asset not found")
        asset_id = a["id"]

    fin_execute(
        """
        INSERT INTO fin_asset_scans
            (scan_session_id, asset_id, scanned_by, location_found, condition_found, notes)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        [d.get("session_id"), asset_id, user,
         d.get("location_found"), d.get("condition_found"), d.get("notes")],
    )
    return ok({"asset_id": asset_id}, "Scan recorded")


# ── Categories & Summary ──────────────────────────────────────

@am_bp.get("/categories")
@require_auth
@require_finance_role
def asset_categories():
    rows = fin_query(
        """
        SELECT category,
               COUNT(*) AS total_assets,
               COUNT(*) FILTER (WHERE status != 'DISPOSED') AS active_assets,
               SUM(purchase_cost) AS total_cost,
               SUM(accumulated_depreciation) AS total_accumulated_dep,
               SUM(GREATEST(purchase_cost - accumulated_depreciation - salvage_value, 0)) AS total_nbv
        FROM fin_assets
        GROUP BY category ORDER BY total_cost DESC
        """, many=True,
    )
    return ok(rows_to_list(rows))
