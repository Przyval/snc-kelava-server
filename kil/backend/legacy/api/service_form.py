"""
Digital Service Form API
==========================
Digital replacement for paper service forms.
Mandatory fields, client signature capture, star rating.

Meeting: "Form pelayanan digital... tanda tangan client... mandatory fields"
"""

import os
import uuid
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request
from werkzeug.utils import secure_filename

from core.security import require_auth, require_role
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

service_form_bp = Blueprint("service_form", __name__, url_prefix="/service-form")

SIGNATURE_DIR = os.environ.get("SIGNATURE_DIR", "/root/kil-server/uploads/signatures")

_TABLE_ENSURED = False


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return

    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS service_forms (
            id                  BIGSERIAL PRIMARY KEY,
            road_plan_id        INTEGER,
            visit_id            INTEGER,
            technician_id       INTEGER NOT NULL,
            customer_id         INTEGER NOT NULL,
            service_date        DATE NOT NULL DEFAULT CURRENT_DATE,
            arrival_time        TIMESTAMPTZ,
            departure_time      TIMESTAMPTZ,
            service_type        VARCHAR(50),
            areas_serviced      TEXT,
            findings            TEXT NOT NULL,
            treatment_applied   TEXT NOT NULL,
            chemicals_used      TEXT,
            recommendations     TEXT,
            pest_activity_level VARCHAR(20) DEFAULT 'LOW',
            follow_up_needed    BOOLEAN DEFAULT false,
            follow_up_date      DATE,
            follow_up_notes     TEXT,
            client_name         VARCHAR(200),
            client_position     VARCHAR(100),
            client_signature    TEXT,
            client_rating       SMALLINT,
            client_feedback     TEXT,
            photo_count         INTEGER DEFAULT 0,
            status              VARCHAR(20) DEFAULT 'DRAFT',
            submitted_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ DEFAULT NOW(),
            updated_at          TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_svc_form_rp
        ON service_forms (road_plan_id)
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_svc_form_tech
        ON service_forms (technician_id, service_date DESC)
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_svc_form_cust
        ON service_forms (customer_id, service_date DESC)
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


PEST_LEVELS = ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL")


# ── Create / Submit Form ──────────────────────────────────────


@service_form_bp.route("", methods=["POST"])
@require_auth
def create_form():
    """
    Create or submit a service form.

    Body: {
        road_plan_id?: int,
        customer_id: int,
        service_type?: string,
        areas_serviced: string,
        findings: string (required),
        treatment_applied: string (required),
        chemicals_used?: string,
        recommendations?: string,
        pest_activity_level: "NONE"|"LOW"|"MEDIUM"|"HIGH"|"CRITICAL",
        follow_up_needed?: bool,
        follow_up_date?: "YYYY-MM-DD",
        follow_up_notes?: string,
        client_name?: string,
        client_position?: string,
        client_signature?: string (base64),
        client_rating?: int (1-5),
        client_feedback?: string,
        status: "DRAFT"|"SUBMITTED"
    }
    """
    _ensure_tables()
    user = g.current_user
    data = request.json or {}

    customer_id = data.get("customer_id")
    findings = (data.get("findings") or "").strip()
    treatment = (data.get("treatment_applied") or "").strip()

    if not customer_id:
        return jsonify({"error": "customer_id required"}), 400
    if not findings:
        return jsonify({"error": "findings required"}), 400
    if not treatment:
        return jsonify({"error": "treatment_applied required"}), 400

    tech_id = user.p_user_id or user.id
    status = data.get("status", "DRAFT")

    # Save signature if base64 provided
    signature_path = None
    sig_data = data.get("client_signature")
    if sig_data and sig_data.startswith("data:image"):
        os.makedirs(SIGNATURE_DIR, exist_ok=True)
        sig_filename = f"sig_{tech_id}_{date.today().isoformat()}_{uuid.uuid4().hex[:8]}.png"
        sig_path = os.path.join(SIGNATURE_DIR, sig_filename)
        try:
            import base64
            # Remove data:image/png;base64, prefix
            b64 = sig_data.split(",", 1)[1] if "," in sig_data else sig_data
            with open(sig_path, "wb") as f:
                f.write(base64.b64decode(b64))
            signature_path = sig_path
        except Exception:
            pass

    result = execute_kelava_query_single(
        """
        INSERT INTO service_forms
            (road_plan_id, technician_id, customer_id, service_type,
             areas_serviced, findings, treatment_applied, chemicals_used,
             recommendations, pest_activity_level,
             follow_up_needed, follow_up_date, follow_up_notes,
             client_name, client_position, client_signature,
             client_rating, client_feedback, status,
             submitted_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                CASE WHEN %s = 'SUBMITTED' THEN NOW() ELSE NULL END)
        RETURNING id, status
        """,
        (
            data.get("road_plan_id"), tech_id, customer_id,
            data.get("service_type"),
            data.get("areas_serviced", ""),
            findings, treatment,
            data.get("chemicals_used", ""),
            data.get("recommendations", ""),
            data.get("pest_activity_level", "LOW"),
            data.get("follow_up_needed", False),
            data.get("follow_up_date"),
            data.get("follow_up_notes", ""),
            data.get("client_name", ""),
            data.get("client_position", ""),
            signature_path,
            data.get("client_rating"),
            data.get("client_feedback", ""),
            status, status,
        ),
    )

    return jsonify({
        "id": result["id"],
        "status": result["status"],
        "message": "Form submitted" if status == "SUBMITTED" else "Draft saved",
    }), 201


# ── Get Form Detail ───────────────────────────────────────────


@service_form_bp.route("/<int:form_id>", methods=["GET"])
@require_auth
def form_detail(form_id):
    """Get service form detail."""
    _ensure_tables()
    row = execute_kelava_query_single(
        """
        SELECT sf.*, u.fullname AS tech_name, c.name AS customer_name, c.address
        FROM service_forms sf
        JOIN p_user u ON u.id = sf.technician_id
        JOIN m_customer c ON c.id = sf.customer_id
        WHERE sf.id = %s
        """,
        (form_id,),
    )
    if not row:
        return jsonify({"error": "Form not found"}), 404
    return jsonify({"form": _fmt(row)})


# ── List Forms ────────────────────────────────────────────────


@service_form_bp.route("", methods=["GET"])
@require_auth
def list_forms():
    """List service forms with filters."""
    _ensure_tables()
    customer_id = request.args.get("customer_id")
    tech_id = request.args.get("technician_id")
    status = request.args.get("status")
    days = int(request.args.get("days", 30))
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 25)), 100)

    where = ["sf.service_date >= CURRENT_DATE - %s"]
    params = [days]

    if customer_id:
        where.append("sf.customer_id = %s")
        params.append(int(customer_id))
    if tech_id:
        where.append("sf.technician_id = %s")
        params.append(int(tech_id))
    if status:
        where.append("sf.status = %s")
        params.append(status)

    where_sql = " AND ".join(where)
    params.extend([per_page, (page - 1) * per_page])

    rows = execute_kelava_query(
        f"""
        SELECT sf.id, sf.service_date, sf.status, sf.client_rating,
               sf.pest_activity_level, sf.follow_up_needed,
               u.fullname AS tech_name, c.name AS customer_name
        FROM service_forms sf
        JOIN p_user u ON u.id = sf.technician_id
        JOIN m_customer c ON c.id = sf.customer_id
        WHERE {where_sql}
        ORDER BY sf.service_date DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    return jsonify({"forms": [_fmt(r) for r in rows], "total": len(rows)})


# ── Update Form ───────────────────────────────────────────────


@service_form_bp.route("/<int:form_id>", methods=["PATCH"])
@require_auth
def update_form(form_id):
    """Update a draft service form."""
    _ensure_tables()
    data = request.json or {}

    allowed = {
        "areas_serviced", "findings", "treatment_applied", "chemicals_used",
        "recommendations", "pest_activity_level", "follow_up_needed",
        "follow_up_date", "follow_up_notes", "client_name", "client_position",
        "client_rating", "client_feedback", "status",
    }

    sets = []
    params = []
    for field in allowed:
        if field in data:
            sets.append(f"{field} = %s")
            params.append(data[field])

    if data.get("status") == "SUBMITTED":
        sets.append("submitted_at = NOW()")

    if not sets:
        return jsonify({"error": "Nothing to update"}), 400

    sets.append("updated_at = NOW()")
    params.append(form_id)

    execute_kelava_query(
        f"UPDATE service_forms SET {', '.join(sets)} WHERE id = %s AND status = 'DRAFT'",
        tuple(params),
    )

    return jsonify({"message": "Form updated"})


# ── Customer Service History (for client portal) ──────────────


@service_form_bp.route("/customer/<int:customer_id>/history", methods=["GET"])
@require_auth
def customer_history(customer_id):
    """Service form history for a customer (for client-facing reports)."""
    _ensure_tables()
    limit = min(int(request.args.get("limit", 20)), 100)

    rows = execute_kelava_query(
        """
        SELECT sf.id, sf.service_date, sf.service_type, sf.findings,
               sf.treatment_applied, sf.pest_activity_level,
               sf.follow_up_needed, sf.follow_up_date,
               sf.client_rating, sf.client_feedback,
               u.fullname AS tech_name
        FROM service_forms sf
        JOIN p_user u ON u.id = sf.technician_id
        WHERE sf.customer_id = %s AND sf.status = 'SUBMITTED'
        ORDER BY sf.service_date DESC
        LIMIT %s
        """,
        (customer_id, limit),
    )

    return jsonify({"history": [_fmt(r) for r in rows], "total": len(rows)})
