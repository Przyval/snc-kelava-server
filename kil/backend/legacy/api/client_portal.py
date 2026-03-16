"""
Client Portal API
===================
Read-only shareable links for clients to view their service data.
Token-based access without requiring login.

Meeting: "share link ke client... untuk audit/presentasi"
"""

import hashlib
import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

client_portal_bp = Blueprint("client_portal", __name__, url_prefix="/client-portal")

_TABLE_ENSURED = False


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return

    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS client_portal_tokens (
            id              BIGSERIAL PRIMARY KEY,
            customer_id     INTEGER NOT NULL,
            token           VARCHAR(64) NOT NULL UNIQUE,
            label           VARCHAR(200),
            expires_at      TIMESTAMPTZ,
            scopes          TEXT DEFAULT 'visits,forms,schedule',
            is_active       BOOLEAN DEFAULT true,
            created_by      VARCHAR(100),
            access_count    INTEGER DEFAULT 0,
            last_accessed   TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_portal_token ON client_portal_tokens (token)
    """)

    _TABLE_ENSURED = True


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _validate_token(token):
    """Validate portal token and return customer_id + scopes."""
    _ensure_tables()
    row = execute_kelava_query_single(
        """
        SELECT id, customer_id, scopes FROM client_portal_tokens
        WHERE token = %s AND is_active = true
          AND (expires_at IS NULL OR expires_at > NOW())
        """,
        (token,),
    )
    if not row:
        return None, None

    # Update access stats
    execute_kelava_query(
        "UPDATE client_portal_tokens SET access_count = access_count + 1, last_accessed = NOW() WHERE id = %s",
        (row["id"],),
    )

    return row["customer_id"], (row["scopes"] or "").split(",")


# ── Admin: Create Portal Token ────────────────────────────────


@client_portal_bp.route("/tokens", methods=["POST"])
def create_token():
    """
    Create a shareable portal token for a customer.
    Requires auth header (standard JWT auth).

    Body: {
        customer_id: int,
        label?: string (e.g. "Q1 2026 Audit"),
        expires_days?: int (default: 90, null=never),
        scopes?: string (comma-separated: "visits,forms,schedule,complaints")
    }
    """
    from core.security import require_auth
    # Manual auth check since this is a mixed endpoint
    from flask import g
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "Authorization required to create tokens"}), 401

    _ensure_tables()
    data = request.json or {}

    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"error": "customer_id required"}), 400

    token = secrets.token_urlsafe(32)
    expires_days = data.get("expires_days", 90)
    expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat() if expires_days else None

    result = execute_kelava_query_single(
        """
        INSERT INTO client_portal_tokens
            (customer_id, token, label, expires_at, scopes, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, token, expires_at
        """,
        (
            customer_id, token,
            data.get("label", ""),
            expires_at,
            data.get("scopes", "visits,forms,schedule"),
            "admin",
        ),
    )

    portal_url = f"https://safencare.work/api/v1/enterprise/client-portal/view?token={token}"

    return jsonify({
        "token": token,
        "portal_url": portal_url,
        "expires_at": result["expires_at"].isoformat() if result.get("expires_at") else None,
        "message": "Portal token created. Share the URL with the client.",
    }), 201


# ── Public: View Portal (no auth required) ────────────────────


@client_portal_bp.route("/view", methods=["GET"])
def portal_view():
    """
    Public client portal view. Accessed via token query parameter.
    Returns customer overview with allowed data scopes.
    """
    token = request.args.get("token", "")
    if not token:
        return jsonify({"error": "Token required"}), 401

    customer_id, scopes = _validate_token(token)
    if not customer_id:
        return jsonify({"error": "Invalid or expired token"}), 403

    # Customer info
    customer = execute_kelava_query_single(
        """
        SELECT c.id, c.name, c.address, c.phone1 AS phone,
               c.contact_person_name AS contact_person
        FROM m_customer c WHERE c.id = %s
        """,
        (customer_id,),
    )
    if not customer:
        return jsonify({"error": "Customer not found"}), 404

    result = {"customer": _fmt(customer), "scopes": scopes}

    # Visits (last 90 days)
    if "visits" in scopes:
        visits = execute_kelava_query(
            """
            SELECT rp.visit_date, rp.status, u.fullname AS technician,
                   v.check_in, v.check_out,
                   CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                        THEN ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)
                        ELSE NULL END AS duration_minutes
            FROM t_road_plan rp
            JOIN p_user u ON u.id = rp.id_user
            LEFT JOIN t_visit v ON v.id_road_plan = rp.id
            WHERE rp.id_customer = %s
              AND rp.visit_date::date >= CURRENT_DATE - 90
              AND COALESCE(rp.is_cancel, false) = false
            ORDER BY rp.visit_date DESC
            LIMIT 50
            """,
            (customer_id,),
        )
        result["visits"] = [_fmt(v) for v in visits]
        result["visit_count"] = len(visits)

    # Schedule (upcoming)
    if "schedule" in scopes:
        schedule = execute_kelava_query(
            """
            SELECT rp.visit_date, u.fullname AS technician, rp.type AS visit_type
            FROM t_road_plan rp
            JOIN p_user u ON u.id = rp.id_user
            WHERE rp.id_customer = %s
              AND rp.visit_date::date >= CURRENT_DATE
              AND COALESCE(rp.is_cancel, false) = false
            ORDER BY rp.visit_date
            LIMIT 20
            """,
            (customer_id,),
        )
        result["upcoming_schedule"] = [_fmt(s) for s in schedule]

    # Service forms
    if "forms" in scopes:
        try:
            forms = execute_kelava_query(
                """
                SELECT sf.service_date, sf.findings, sf.treatment_applied,
                       sf.pest_activity_level, sf.recommendations,
                       sf.client_rating, u.fullname AS technician
                FROM service_forms sf
                JOIN p_user u ON u.id = sf.technician_id
                WHERE sf.customer_id = %s AND sf.status = 'SUBMITTED'
                ORDER BY sf.service_date DESC
                LIMIT 20
                """,
                (customer_id,),
            )
            result["service_forms"] = [_fmt(f) for f in forms]
        except Exception:
            result["service_forms"] = []

    # Complaints
    if "complaints" in scopes:
        try:
            complaints = execute_kelava_query(
                """
                SELECT ct.title, ct.status, ct.severity, ct.created_at, ct.resolution
                FROM complaint_tickets ct
                WHERE ct.customer_id = %s
                ORDER BY ct.created_at DESC
                LIMIT 10
                """,
                (customer_id,),
            )
            result["complaints"] = [_fmt(c) for c in complaints]
        except Exception:
            result["complaints"] = []

    # Contract info
    contracts = execute_kelava_query(
        """
        SELECT ck.no_kontrak, ck.start_date, ck.end_date, ck.is_active
        FROM m_customer_kontrak ck
        WHERE ck.id_customer = %s
        ORDER BY ck.end_date DESC
        LIMIT 5
        """,
        (customer_id,),
    )
    result["contracts"] = [_fmt(c) for c in contracts]

    return jsonify(result)


# ── Admin: List Tokens ────────────────────────────────────────


@client_portal_bp.route("/tokens", methods=["GET"])
def list_tokens():
    """List all portal tokens (admin view)."""
    _ensure_tables()

    rows = execute_kelava_query(
        """
        SELECT cpt.*, c.name AS customer_name
        FROM client_portal_tokens cpt
        JOIN m_customer c ON c.id = cpt.customer_id
        ORDER BY cpt.created_at DESC
        """
    )

    return jsonify({"tokens": [_fmt(r) for r in rows], "total": len(rows)})


# ── Admin: Revoke Token ───────────────────────────────────────


@client_portal_bp.route("/tokens/<int:token_id>/revoke", methods=["POST"])
def revoke_token(token_id):
    """Revoke a portal token."""
    _ensure_tables()
    execute_kelava_query(
        "UPDATE client_portal_tokens SET is_active = false WHERE id = %s",
        (token_id,),
    )
    return jsonify({"message": "Token revoked"})
