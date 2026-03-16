"""
Winback Engine API
==================
SAP-Grade campaign management for customer recovery.
Handles batch winback campaigns, contact tracking, and success metrics.
"""

from datetime import datetime

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

winback_bp = Blueprint("winback", __name__, url_prefix="/winback")


def _auth_user_id() -> str | None:
    user = getattr(g, "user", None)
    return str(user.id) if user else None


def _auth_user_name() -> str:
    user = getattr(g, "user", None)
    if user and user.user_metadata:
        return user.user_metadata.get("full_name", user.email or "System")
    return "System"


def _log_activity(entry_id, campaign_id, action, prev_status, new_status, note=None):
    """Write immutable activity log entry."""
    actor_id = _auth_user_id()
    actor_name = _auth_user_name()
    execute_kelava_query(
        """
        INSERT INTO winback_activity_log
            (entry_id, campaign_id, action, previous_status, new_status, actor_id, actor_name, note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (entry_id, campaign_id, action, prev_status, new_status, actor_id, actor_name, note),
        user_id=actor_id,
    )


# ── Campaign CRUD ────────────────────────────────────────────


@winback_bp.route("/campaigns", methods=["GET"])
@require_auth
def list_campaigns():
    """List all winback campaigns with summary stats."""
    status_filter = request.args.get("status")
    uid = _auth_user_id()

    where = "1=1"
    params = []
    if status_filter:
        where = "c.status = %s"
        params = [status_filter]

    campaigns = execute_kelava_query(
        f"""
        SELECT * FROM v_winback_campaign_stats c
        WHERE {where}
        ORDER BY c.created_at DESC
        """,
        tuple(params) if params else None,
        user_id=uid,
    )

    formatted = []
    for row in campaigns:
        item = dict(row)
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        formatted.append(item)

    return jsonify({"campaigns": formatted, "generated_at": datetime.now().isoformat()})


@winback_bp.route("/campaigns", methods=["POST"])
@require_auth
def create_campaign():
    """
    Create a new winback campaign.

    Body: { name, description?, target_segment?, assigned_team?, customer_ids: [int] }
    """
    data = request.json or {}
    name = data.get("name")
    if not name:
        return jsonify({"error": "Campaign name is required"}), 400

    description = data.get("description", "")
    target_segment = data.get("target_segment", "MIXED")
    assigned_team = data.get("assigned_team", "SALES")
    customer_ids = data.get("customer_ids", [])
    uid = _auth_user_id()

    if not customer_ids:
        return jsonify({"error": "At least one customer must be selected"}), 400

    # Create campaign
    campaign = execute_kelava_query_single(
        """
        INSERT INTO winback_campaigns (name, description, target_segment, assigned_team, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (name, description, target_segment, assigned_team, uid),
        user_id=uid,
    )

    if not campaign:
        return jsonify({"error": "Failed to create campaign"}), 500

    campaign_id = campaign["id"]

    # Snapshot customer data from the priority action view and insert entries
    for cid in customer_ids:
        cust = execute_kelava_query_single(
            """
            SELECT customer_id, rfm_segment, priority, days_since_last_visit,
                   last_completed_visit_at, value_monthly
            FROM v_customer_priority_action
            WHERE customer_id = %s
            """,
            (cid,),
            user_id=uid,
        )

        if cust:
            execute_kelava_query(
                """
                INSERT INTO winback_entries
                    (campaign_id, id_customer, priority, rfm_segment,
                     days_dormant, last_visit_date, value_monthly)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (campaign_id, id_customer) DO NOTHING
                """,
                (
                    campaign_id,
                    cid,
                    cust.get("priority"),
                    cust.get("rfm_segment"),
                    cust.get("days_since_last_visit"),
                    cust.get("last_completed_visit_at"),
                    cust.get("value_monthly"),
                ),
                user_id=uid,
            )

            _log_activity(None, campaign_id, "CUSTOMER_ADDED", None, "PENDING",
                          f"Customer {cid} added to campaign")

    # Format response
    result = dict(campaign)
    for k, v in result.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()

    return jsonify({
        "message": f"Campaign created with {len(customer_ids)} customers",
        "campaign": result,
    }), 201


@winback_bp.route("/campaigns/<int:campaign_id>", methods=["GET"])
@require_auth
def campaign_detail(campaign_id: int):
    """Get campaign detail with all entries."""
    uid = _auth_user_id()

    campaign = execute_kelava_query_single(
        "SELECT * FROM v_winback_campaign_stats WHERE campaign_id = %s",
        (campaign_id,),
        user_id=uid,
    )
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    entries = execute_kelava_query(
        """
        SELECT
            e.*,
            c.name as customer_name,
            c.code as customer_code,
            c.phone1,
            c.address,
            u.fullname as assigned_to_name
        FROM winback_entries e
        JOIN m_customer c ON c.id = e.id_customer
        LEFT JOIN p_user u ON u.id = e.assigned_to
        WHERE e.campaign_id = %s
        ORDER BY
            CASE e.status
                WHEN 'PENDING' THEN 1
                WHEN 'CONTACTED' THEN 2
                WHEN 'INTERESTED' THEN 3
                WHEN 'WON' THEN 4
                WHEN 'LOST' THEN 5
                WHEN 'NO_RESPONSE' THEN 6
            END,
            e.value_monthly DESC NULLS LAST
        """,
        (campaign_id,),
        user_id=uid,
    )

    def fmt(row):
        item = dict(row)
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        return item

    return jsonify({
        "campaign": fmt(campaign),
        "entries": [fmt(e) for e in entries],
        "generated_at": datetime.now().isoformat(),
    })


@winback_bp.route("/campaigns/<int:campaign_id>/activate", methods=["POST"])
@require_auth
def activate_campaign(campaign_id: int):
    """Transition campaign: DRAFT → ACTIVE."""
    uid = _auth_user_id()

    campaign = execute_kelava_query_single(
        "SELECT * FROM winback_campaigns WHERE id = %s", (campaign_id,), user_id=uid,
    )
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign["status"] != "DRAFT":
        return jsonify({"error": f"Cannot activate campaign in {campaign['status']} status"}), 400

    execute_kelava_query(
        """
        UPDATE winback_campaigns
        SET status = 'ACTIVE', started_at = NOW(), updated_at = NOW()
        WHERE id = %s
        """,
        (campaign_id,),
        user_id=uid,
    )

    _log_activity(None, campaign_id, "CAMPAIGN_ACTIVATED", "DRAFT", "ACTIVE")

    return jsonify({"message": "Campaign activated", "campaign_id": campaign_id})


@winback_bp.route("/campaigns/<int:campaign_id>/complete", methods=["POST"])
@require_auth
def complete_campaign(campaign_id: int):
    """Transition campaign: ACTIVE → COMPLETED."""
    uid = _auth_user_id()

    campaign = execute_kelava_query_single(
        "SELECT * FROM winback_campaigns WHERE id = %s", (campaign_id,), user_id=uid,
    )
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404
    if campaign["status"] != "ACTIVE":
        return jsonify({"error": f"Cannot complete campaign in {campaign['status']} status"}), 400

    execute_kelava_query(
        """
        UPDATE winback_campaigns
        SET status = 'COMPLETED', completed_at = NOW(), updated_at = NOW()
        WHERE id = %s
        """,
        (campaign_id,),
        user_id=uid,
    )

    _log_activity(None, campaign_id, "CAMPAIGN_COMPLETED", "ACTIVE", "COMPLETED")

    return jsonify({"message": "Campaign completed", "campaign_id": campaign_id})


# ── Entry Operations ─────────────────────────────────────────


@winback_bp.route("/entries/<int:entry_id>/status", methods=["PATCH"])
@require_auth
def update_entry_status(entry_id: int):
    """
    Update winback entry status.

    Body: { status, note? }
    Valid transitions:
        PENDING → CONTACTED
        CONTACTED → INTERESTED | LOST | NO_RESPONSE
        INTERESTED → WON | LOST
    """
    data = request.json or {}
    new_status = data.get("status")
    note = data.get("note", "")
    uid = _auth_user_id()

    valid_statuses = {"PENDING", "CONTACTED", "INTERESTED", "WON", "LOST", "NO_RESPONSE"}
    if new_status not in valid_statuses:
        return jsonify({"error": f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}"}), 400

    entry = execute_kelava_query_single(
        "SELECT * FROM winback_entries WHERE id = %s", (entry_id,), user_id=uid,
    )
    if not entry:
        return jsonify({"error": "Entry not found"}), 404

    prev_status = entry["status"]

    # Validate transitions
    valid_transitions = {
        "PENDING": {"CONTACTED"},
        "CONTACTED": {"INTERESTED", "LOST", "NO_RESPONSE"},
        "INTERESTED": {"WON", "LOST"},
    }
    allowed = valid_transitions.get(prev_status, set())
    if new_status not in allowed and new_status != prev_status:
        return jsonify({
            "error": f"Invalid transition: {prev_status} → {new_status}. Allowed: {', '.join(sorted(allowed))}"
        }), 400

    # Update entry
    if new_status == "CONTACTED":
        execute_kelava_query(
            """
            UPDATE winback_entries
            SET status = %s, contact_note = %s, contact_date = NOW(),
                contact_attempts = contact_attempts + 1, updated_at = NOW()
            WHERE id = %s
            """,
            (new_status, note, entry_id),
            user_id=uid,
        )
    elif new_status in ("WON", "LOST", "NO_RESPONSE"):
        execute_kelava_query(
            """
            UPDATE winback_entries
            SET status = %s, outcome_note = %s, outcome_date = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (new_status, note, entry_id),
            user_id=uid,
        )
    else:
        execute_kelava_query(
            """
            UPDATE winback_entries
            SET status = %s, contact_note = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (new_status, note, entry_id),
            user_id=uid,
        )

    _log_activity(entry_id, entry["campaign_id"], "STATUS_CHANGE", prev_status, new_status, note)

    return jsonify({
        "message": f"Status updated: {prev_status} → {new_status}",
        "entry_id": entry_id,
    })


@winback_bp.route("/entries/<int:entry_id>/assign", methods=["PATCH"])
@require_auth
def assign_entry(entry_id: int):
    """
    Assign a winback entry to a sales rep.
    Body: { assigned_to: int (p_user.id) }
    """
    data = request.json or {}
    assigned_to = data.get("assigned_to")
    uid = _auth_user_id()

    if not assigned_to:
        return jsonify({"error": "assigned_to is required"}), 400

    entry = execute_kelava_query_single(
        "SELECT * FROM winback_entries WHERE id = %s", (entry_id,), user_id=uid,
    )
    if not entry:
        return jsonify({"error": "Entry not found"}), 404

    # Verify user exists
    user = execute_kelava_query_single(
        "SELECT id, fullname FROM p_user WHERE id = %s", (assigned_to,), user_id=uid,
    )
    if not user:
        return jsonify({"error": "Assigned user not found"}), 404

    execute_kelava_query(
        "UPDATE winback_entries SET assigned_to = %s, updated_at = NOW() WHERE id = %s",
        (assigned_to, entry_id),
        user_id=uid,
    )

    _log_activity(
        entry_id, entry["campaign_id"], "ASSIGNED", None, None,
        f"Assigned to {user['fullname']} (ID: {assigned_to})"
    )

    return jsonify({"message": f"Assigned to {user['fullname']}", "entry_id": entry_id})


@winback_bp.route("/entries/<int:entry_id>/note", methods=["POST"])
@require_auth
def add_entry_note(entry_id: int):
    """
    Add a contact note to an entry (without changing status).
    Body: { note: str }
    """
    data = request.json or {}
    note = data.get("note")
    uid = _auth_user_id()

    if not note:
        return jsonify({"error": "Note is required"}), 400

    entry = execute_kelava_query_single(
        "SELECT * FROM winback_entries WHERE id = %s", (entry_id,), user_id=uid,
    )
    if not entry:
        return jsonify({"error": "Entry not found"}), 404

    execute_kelava_query(
        """
        UPDATE winback_entries
        SET contact_note = %s, contact_attempts = contact_attempts + 1, updated_at = NOW()
        WHERE id = %s
        """,
        (note, entry_id),
        user_id=uid,
    )

    _log_activity(entry_id, entry["campaign_id"], "NOTE_ADDED", entry["status"], entry["status"], note)

    return jsonify({"message": "Note added", "entry_id": entry_id})


# ── Activity Log ─────────────────────────────────────────────


@winback_bp.route("/entries/<int:entry_id>/activity", methods=["GET"])
@require_auth
def entry_activity(entry_id: int):
    """Get full activity log for a winback entry."""
    uid = _auth_user_id()

    activities = execute_kelava_query(
        """
        SELECT * FROM winback_activity_log
        WHERE entry_id = %s
        ORDER BY created_at DESC
        """,
        (entry_id,),
        user_id=uid,
    )

    formatted = []
    for row in activities:
        item = dict(row)
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        formatted.append(item)

    return jsonify({"activities": formatted})


# ── Statistics ───────────────────────────────────────────────


@winback_bp.route("/stats", methods=["GET"])
@require_auth
def winback_stats():
    """
    Overall winback engine statistics.
    Returns funnel metrics, win rates, and eligible pool size.
    """
    uid = _auth_user_id()

    # Overall funnel
    funnel = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) as total_entries,
            COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
            COUNT(*) FILTER (WHERE status = 'CONTACTED') as contacted,
            COUNT(*) FILTER (WHERE status = 'INTERESTED') as interested,
            COUNT(*) FILTER (WHERE status = 'WON') as won,
            COUNT(*) FILTER (WHERE status = 'LOST') as lost,
            COUNT(*) FILTER (WHERE status = 'NO_RESPONSE') as no_response,
            ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'WON') / NULLIF(COUNT(*), 0), 1) as overall_win_rate,
            COALESCE(SUM(value_monthly) FILTER (WHERE status = 'WON'), 0) as total_recovered_value
        FROM winback_entries
        """,
        user_id=uid,
    )

    # Active campaigns count
    active = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'ACTIVE') as active_campaigns,
            COUNT(*) FILTER (WHERE status = 'COMPLETED') as completed_campaigns,
            COUNT(*) as total_campaigns
        FROM winback_campaigns
        """,
        user_id=uid,
    )

    # Eligible pool size
    eligible = execute_kelava_query_single(
        """
        SELECT COUNT(*) as eligible_count
        FROM v_customer_priority_action
        WHERE rfm_segment IN ('CHURNED', 'LOW_VALUE')
           OR account_status IN ('DORMANT', 'INACTIVE')
        """,
        user_id=uid,
    )

    def fmt(row):
        if not row:
            return {}
        item = dict(row)
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        return item

    return jsonify({
        "funnel": fmt(funnel),
        "campaigns": fmt(active),
        "eligible_pool": eligible["eligible_count"] if eligible else 0,
        "generated_at": datetime.now().isoformat(),
    })


# ── Eligible Customers ──────────────────────────────────────


@winback_bp.route("/eligible", methods=["GET"])
@require_auth
def eligible_customers():
    """
    Get list of customers eligible for winback.
    Excludes those already in active campaigns.
    """
    uid = _auth_user_id()
    segment = request.args.get("segment")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)
    offset = (page - 1) * per_page

    where = "1=1"
    params = []

    if segment:
        where += " AND pa.rfm_segment = %s"
        params.append(segment)

    params.extend([per_page, offset])

    customers = execute_kelava_query(
        f"""
        SELECT
            pa.customer_id,
            pa.name,
            pa.rfm_segment,
            pa.account_status,
            pa.priority,
            pa.days_since_last_visit,
            pa.value_monthly,
            pa.has_active_contract,
            pa.suggested_action,
            pa.owner,
            c.phone1,
            c.address
        FROM v_customer_priority_action pa
        JOIN m_customer c ON c.id = pa.customer_id
        WHERE (pa.rfm_segment IN ('CHURNED', 'LOW_VALUE') OR pa.account_status IN ('DORMANT', 'INACTIVE'))
          AND pa.customer_id NOT IN (
              SELECT we.id_customer
              FROM winback_entries we
              JOIN winback_campaigns wc ON wc.id = we.campaign_id
              WHERE wc.status = 'ACTIVE'
                AND we.status NOT IN ('WON', 'LOST', 'NO_RESPONSE')
          )
          AND {where}
        ORDER BY pa.value_monthly DESC NULLS LAST, pa.days_since_last_visit DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
        user_id=uid,
    )

    formatted = []
    for row in customers:
        item = dict(row)
        for k, v in item.items():
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        formatted.append(item)

    return jsonify({
        "customers": formatted,
        "page": page,
        "per_page": per_page,
        "generated_at": datetime.now().isoformat(),
    })
