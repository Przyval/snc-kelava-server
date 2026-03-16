"""
Complaint Tracking API
=======================
CRUD for customer complaint tickets (complaint_tickets table).
Admin/Supervisor can create, assign, and resolve complaints.
"""

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single
from kil.backend.legacy.api.audit_log import log_action

complaints_bp = Blueprint("complaints", __name__, url_prefix="/complaints")


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── List / Search ─────────────────────────────────────────────


@complaints_bp.route("", methods=["GET"])
@require_auth
def list_complaints():
    """List complaints with optional filters."""
    status_filter = request.args.get("status", "open,in_progress")
    severity = request.args.get("severity")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 25)), 100)
    offset = (page - 1) * per_page

    where_parts = []
    params = []

    if status_filter and status_filter != "all":
        statuses = [s.strip() for s in status_filter.split(",")]
        placeholders = ", ".join(["%s"] * len(statuses))
        where_parts.append(f"ct.status IN ({placeholders})")
        params.extend(statuses)

    if severity:
        where_parts.append("ct.severity = %s")
        params.append(severity)

    where_sql = " AND ".join(where_parts) if where_parts else "1=1"
    params.extend([per_page, offset])

    rows = execute_kelava_query(
        f"""
        SELECT ct.*, c.name AS customer_name,
               u.fullname AS assigned_name
        FROM complaint_tickets ct
        LEFT JOIN m_customer c ON c.id = ct.customer_id
        LEFT JOIN p_user u ON u.id = ct.assigned_to
        WHERE {where_sql}
        ORDER BY
            CASE ct.severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END,
            ct.created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    # Auto-mark SLA breaches for open tickets (best-effort)
    try:
        execute_kelava_query(
            """
            UPDATE complaint_tickets
            SET sla_breached = TRUE
            WHERE sla_deadline IS NOT NULL
              AND sla_deadline < NOW()
              AND status NOT IN ('resolved', 'closed')
              AND (sla_breached IS NULL OR sla_breached = FALSE)
            """
        )
    except Exception:
        pass  # SLA columns may not exist yet (before migration 006)

    # Stats
    stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'open') AS open_count,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_count,
            COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_count,
            COUNT(*) FILTER (WHERE status = 'closed') AS closed_count,
            COUNT(*) FILTER (WHERE sla_breached = TRUE AND status NOT IN ('resolved','closed')) AS sla_breached_count,
            COUNT(*) AS total
        FROM complaint_tickets
        """
    )

    return jsonify({
        "complaints": [_fmt(r) for r in rows],
        "stats": _fmt(stats),
    })


# ── Create ────────────────────────────────────────────────────


@complaints_bp.route("", methods=["POST"])
@require_auth
def create_complaint():
    """Create a new complaint ticket."""
    data = request.json or {}

    customer_id = data.get("customer_id")
    title = (data.get("title") or "").strip()

    if not customer_id:
        return jsonify({"error": "customer_id is required"}), 400
    if not title:
        return jsonify({"error": "title is required"}), 400

    severity = data.get("severity", "medium")
    sla_hours = {"critical": 4, "high": 24, "medium": 48, "low": 72}.get(severity, 48)

    result = execute_kelava_query_single(
        """
        INSERT INTO complaint_tickets
            (customer_id, contract_id, title, description, severity, category,
             assigned_to, reported_by, sla_hours, sla_deadline)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW() + (%s * INTERVAL '1 hour'))
        RETURNING id
        """,
        (
            customer_id,
            data.get("contract_id"),
            title,
            data.get("description", ""),
            severity,
            data.get("category", "other"),
            data.get("assigned_to"),
            data.get("reported_by", ""),
            sla_hours,
            sla_hours,
        ),
    )

    log_action("complaints", "create", "complaint", result["id"], f"Complaint created: {title}")
    return jsonify({"id": result["id"], "status": "created"}), 201


# ── Detail ────────────────────────────────────────────────────


@complaints_bp.route("/<int:complaint_id>", methods=["GET"])
@require_auth
def complaint_detail(complaint_id):
    """Get complaint detail."""
    row = execute_kelava_query_single(
        """
        SELECT ct.*, c.name AS customer_name, c.address AS customer_address,
               c.phone1 AS customer_phone,
               u.fullname AS assigned_name
        FROM complaint_tickets ct
        LEFT JOIN m_customer c ON c.id = ct.customer_id
        LEFT JOIN p_user u ON u.id = ct.assigned_to
        WHERE ct.id = %s
        """,
        (complaint_id,),
    )
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"complaint": _fmt(row)})


# ── Update ────────────────────────────────────────────────────


@complaints_bp.route("/<int:complaint_id>", methods=["PATCH"])
@require_auth
def update_complaint(complaint_id):
    """Update complaint: status, assignment, resolution, etc."""
    data = request.json or {}

    sets = []
    params = []

    for field in ("title", "description", "severity", "category", "assigned_to", "reported_by", "status"):
        if field in data:
            sets.append(f"{field} = %s")
            params.append(data[field])

    if "resolution" in data:
        sets.append("resolution = %s")
        params.append(data["resolution"])

    if data.get("status") == "resolved":
        sets.append("resolved_at = NOW()")
        sets.append("resolved_by = %s")
        sets.append("sla_breached = (sla_deadline IS NOT NULL AND sla_deadline < NOW())")
        params.append(g.current_user.id)
    if "resolution_notes" in data:
        sets.append("resolution_notes = %s")
        params.append(data["resolution_notes"])

    if not sets:
        return jsonify({"error": "Nothing to update"}), 400

    sets.append("updated_at = NOW()")
    params.append(complaint_id)

    execute_kelava_query(
        f"UPDATE complaint_tickets SET {', '.join(sets)} WHERE id = %s",
        tuple(params),
    )

    detail_parts = []
    if "status" in data:
        detail_parts.append(f"status={data['status']}")
    if "assigned_to" in data:
        detail_parts.append(f"assigned_to={data['assigned_to']}")
    if "resolution" in data:
        detail_parts.append("resolution added")
    log_action("complaints", "update", "complaint", complaint_id, "; ".join(detail_parts) or "fields updated")
    return jsonify({"status": "updated"})


# ── Helpers ───────────────────────────────────────────────────


@complaints_bp.route("/customers/search", methods=["GET"])
@require_auth
def search_customers():
    """Quick customer search for the complaint form."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    rows = execute_kelava_query(
        """
        SELECT id, code, name, address
        FROM m_customer
        WHERE LOWER(name) LIKE %s OR LOWER(code) LIKE %s
        ORDER BY name LIMIT 10
        """,
        (f"%{q.lower()}%", f"%{q.lower()}%"),
    )
    return jsonify([_fmt(r) for r in rows])


@complaints_bp.route("/sla-status", methods=["GET"])
@require_auth
def sla_status():
    """SLA health: counts of breached, at-risk (< 4h left), and on-track open tickets."""
    try:
        row = execute_kelava_query_single(
            """
            SELECT
                COUNT(*) FILTER (WHERE sla_breached = TRUE AND status NOT IN ('resolved','closed'))
                    AS breached,
                COUNT(*) FILTER (WHERE sla_deadline BETWEEN NOW() AND NOW() + INTERVAL '4 hours'
                    AND status NOT IN ('resolved','closed'))
                    AS at_risk,
                COUNT(*) FILTER (WHERE sla_deadline > NOW() + INTERVAL '4 hours'
                    AND status NOT IN ('resolved','closed'))
                    AS on_track,
                AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600)
                    FILTER (WHERE resolved_at IS NOT NULL)
                    AS avg_resolution_hours
            FROM complaint_tickets
            WHERE created_at >= NOW() - INTERVAL '30 days'
            """
        )
        return jsonify(_fmt(row) if row else {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@complaints_bp.route("/technicians", methods=["GET"])
@require_auth
def list_technicians():
    """List technicians for assignment dropdown."""
    rows = execute_kelava_query(
        """
        SELECT u.id, u.fullname AS name
        FROM p_user u
        JOIN enterprise_users eu ON eu.p_user_id = u.id
        WHERE eu.role = 'technician' AND eu.is_active = true
        ORDER BY u.fullname
        """
    )
    return jsonify([_fmt(r) for r in rows])
