"""
Finance Core Utilities
======================
Shared DB helpers, number formatting, period resolution,
and journal entry builder for the Finance module.
"""

import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import wraps
from typing import Any

from flask import g, jsonify, request

log = logging.getLogger(__name__)

# ── Finance DB Connection ────────────────────────────────────


def get_fin_db():
    """Return a finance DB connection (local enterprise DB, same as auth)."""
    from kil.db.kelava_db import _get_local_pool
    return _get_local_pool().connection()


def fin_query(sql: str, params=None, many=False):
    """Execute a read query against the finance DB."""
    with get_fin_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            if many:
                return cur.fetchall()
            return cur.fetchone()


def fin_execute(sql: str, params=None):
    """Execute a write query, return rowcount."""
    with get_fin_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            return cur.rowcount


def fin_execute_returning(sql: str, params=None):
    """Execute INSERT/UPDATE RETURNING, return first row."""
    with get_fin_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or [])
            return cur.fetchone()


# ── Money Utilities ──────────────────────────────────────────


def to_idr(value) -> Decimal:
    """Normalize any numeric value to 2-decimal Decimal (IDR)."""
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt_idr(value) -> str:
    """Format number as Indonesian Rupiah string: 1.234.567,89"""
    if value is None:
        return "0"
    d = Decimal(str(value))
    neg = d < 0
    d = abs(d)
    parts = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"({parts})" if neg else parts


def parse_idr_input(s: str) -> Decimal:
    """Parse user-entered IDR string (1.234.567,89 or 1234567.89) to Decimal."""
    if not s:
        return Decimal("0")
    s = str(s).strip().replace(" ", "")
    # Remove Indonesian thousand separators, normalize decimal
    if "," in s and "." in s:
        # Format: 1.234.567,89
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        # Format: 1234567,89
        s = s.replace(",", ".")
    # else: already plain decimal
    return Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── Period Resolution ────────────────────────────────────────


def resolve_period(entry_date: date) -> dict | None:
    """Find the fiscal period for a given date."""
    row = fin_query(
        """
        SELECT id, year, period, status
        FROM   fin_fiscal_periods
        WHERE  start_date <= %s AND end_date >= %s
        LIMIT  1
        """,
        [entry_date, entry_date],
    )
    return dict(row) if row else None


def get_open_period() -> dict | None:
    """Return the currently open fiscal period."""
    row = fin_query(
        "SELECT id, year, period FROM fin_fiscal_periods WHERE status='OPEN' ORDER BY year,period LIMIT 1"
    )
    return dict(row) if row else None


def assert_period_open(entry_date: date):
    """Raise ValueError if the period for entry_date is closed/locked."""
    period = resolve_period(entry_date)
    if not period:
        raise ValueError(f"No fiscal period found for {entry_date}")
    if period["status"] in ("CLOSED", "LOCKED"):
        raise ValueError(
            f"Period {period['year']}/{period['period']:02d} is {period['status']} — cannot post"
        )
    return period


# ── Journal Entry Builder ────────────────────────────────────


def build_journal_entry(
    entry_date: date,
    description: str,
    lines: list[dict],
    entry_type: str = "MANUAL",
    reference: str = None,
    source_module: str = None,
    source_id: int = None,
    created_by: str = "system",
) -> int:
    """
    Create a POSTED journal entry with balanced lines.

    lines = [
        {"account": "1102", "debit": 1000000, "credit": 0, "description": "...",
         "cost_center_id": None, "profit_center_id": None, "customer_name": None, "vendor_id": None}
    ]
    Returns journal_entry_id.
    Raises ValueError if lines don't balance.
    """
    period = assert_period_open(entry_date)

    total_dr = sum(to_idr(l.get("debit", 0)) for l in lines)
    total_cr = sum(to_idr(l.get("credit", 0)) for l in lines)

    if abs(total_dr - total_cr) > Decimal("0.01"):
        raise ValueError(f"Journal entry unbalanced: debit={total_dr} credit={total_cr}")

    entry_no = fin_query(
        "SELECT next_journal_entry_no(%s, %s) AS no",
        [entry_date.year, entry_date.month],
    )["no"]

    je_row = fin_execute_returning(
        """
        INSERT INTO fin_journal_entries
            (entry_no, entry_date, period_id, reference, description,
             entry_type, total_debit, total_credit, status,
             source_module, source_id, created_by, posted_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'POSTED',%s,%s,%s,NOW())
        RETURNING id
        """,
        [
            entry_no, entry_date, period["id"], reference, description,
            entry_type, float(total_dr), float(total_cr),
            source_module, source_id, created_by,
        ],
    )
    je_id = je_row["id"]

    for i, line in enumerate(lines, 1):
        fin_execute(
            """
            INSERT INTO fin_gl_lines
                (journal_entry_id, line_no, account_code, cost_center_id,
                 profit_center_id, debit, credit, description,
                 customer_name, vendor_id, asset_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            [
                je_id, i,
                line["account"],
                line.get("cost_center_id"),
                line.get("profit_center_id"),
                float(to_idr(line.get("debit", 0))),
                float(to_idr(line.get("credit", 0))),
                line.get("description", description),
                line.get("customer_name"),
                line.get("vendor_id"),
                line.get("asset_id"),
            ],
        )

    log.info("Posted JE %s | %s | dr=%s cr=%s", entry_no, description, total_dr, total_cr)
    return je_id


# ── Response Helpers ────────────────────────────────────────


def ok(data=None, message: str = "OK", status: int = 200):
    resp = {"success": True, "message": message}
    if data is not None:
        resp["data"] = data
    return jsonify(resp), status


def err(message: str, status: int = 400, details=None):
    resp = {"success": False, "error": message}
    if details:
        resp["details"] = details
    return jsonify(resp), status


def require_finance_role(f):
    """Decorator: require authenticated user with finance or admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(g, "user", None)
        if not user:
            return err("Authentication required", 401)
        allowed = {"admin", "finance", "finance_manager", "direktur"}
        if getattr(user, "role", "") not in allowed:
            return err("Finance role required", 403)
        return f(*args, **kwargs)
    return decorated


def paginate(query_fn, page: int = 1, per_page: int = 50) -> dict:
    """Helper to paginate a list result."""
    offset = (page - 1) * per_page
    rows = query_fn(limit=per_page, offset=offset)
    total = query_fn(count_only=True)
    return {
        "items": rows,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page,
    }


def row_to_dict(row) -> dict:
    """Convert a psycopg dict_row to a plain dict with serializable values."""
    if row is None:
        return {}
    result = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            result[k] = float(v)
        elif isinstance(v, (date, datetime)):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def rows_to_list(rows) -> list[dict]:
    return [row_to_dict(r) for r in (rows or [])]
