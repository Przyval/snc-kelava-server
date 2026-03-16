import json
from datetime import datetime

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

governance_bp = Blueprint("governance", __name__, url_prefix="/governance")

# --- Policies Definition ---
POLICIES = {
    "SLA_BREACH": "Service Agreement requires visits every 30 days. Current status is overdue.",
    "VISIT_GAP_CRITICAL": "Gap between visits has exceeded 60 days, triggering a critical dormant alert.",
    "RISK_HIGH": "Account risk score > 8 due to multiple operational flags (Overdue + Compliance < 50%).",
    "LONG_DURATION": "Service duration exceeded 2 standard deviations from the mean for this service type.",
}


# --- Helpers ---
def log_audit_event(customer_id, action, previous_state, new_state, actor_id, note):
    """
    Writes to the immutable governance_audit_log.
    """
    sql = """
        INSERT INTO governance_audit_log (
            id_customer, action, previous_state, new_state, actor_id, note, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
    """
    # Convert dicts to JSON strings for JSONB column
    prev_json = json.dumps(previous_state, default=str) if previous_state else None
    new_json = json.dumps(new_state, default=str) if new_state else None

    execute_kelava_query(
        sql, (customer_id, action, prev_json, new_json, actor_id, note)
    )


def get_current_governance_state(customer_id):
    """
    Fetches current state from operational_governance.
    Returns default state if no record exists.
    """
    sql = "SELECT * FROM operational_governance WHERE id_customer = %s"
    row = execute_kelava_query_single(sql, (customer_id,))

    if not row:
        return {"review_status": "OPEN", "escalation_level": "WATCH"}
    return row


# --- Endpoints ---


@governance_bp.route("/review/close", methods=["POST"])
@require_auth
def close_review():
    """
    Transition account from OPEN -> CLOSED (RESOLVED or ACCEPTED_RISK).
    Mandatory: id_customer, outcome, note
    """
    data = request.json
    customer_id = data.get("customer_id")
    outcome = data.get("outcome")  # RESOLVED, ACCEPTED_RISK
    note = data.get("note")
    user = getattr(g, "current_user", None)
    actor_id = user.id if user else 1

    if not all([customer_id, outcome, note]):
        return jsonify({"error": "Missing mandatory fields"}), 400

    if outcome not in ["RESOLVED", "ACCEPTED_RISK"]:
        return jsonify(
            {"error": "Invalid outcome. Must be RESOLVED or ACCEPTED_RISK"}
        ), 400

    # Get previous state for audit
    prev_state = get_current_governance_state(customer_id)

    # Upsert operational_governance
    # Using Postgres ON CONFLICT to handle first-time records
    sql_upsert = """
        INSERT INTO operational_governance (
            id_customer, review_status, last_review_at, last_reviewer_id, review_note, updated_at
        ) VALUES (%s, %s, NOW(), %s, %s, NOW())
        ON CONFLICT (id_customer) 
        DO UPDATE SET 
            review_status = EXCLUDED.review_status,
            last_review_at = NOW(),
            last_reviewer_id = EXCLUDED.last_reviewer_id,
            review_note = EXCLUDED.review_note,
            updated_at = NOW()
        RETURNING *
    """
    new_status = f"CLOSED_{outcome}"
    new_row = execute_kelava_query_single(
        sql_upsert, (customer_id, new_status, actor_id, note)
    )

    # Log Audit
    log_audit_event(
        customer_id=customer_id,
        action="REVIEW_CLOSE",
        previous_state=prev_state,
        new_state=new_row,
        actor_id=actor_id,
        note=note,
    )

    return jsonify({"message": "Review closed successfully", "state": new_row})


@governance_bp.route("/escalate", methods=["POST"])
@require_auth
def escalate_account():
    """
    Move escalation level: WATCH -> ATTENTION -> ESCALATED.
    """
    data = request.json
    customer_id = data.get("customer_id")
    level = data.get("level")  # WATCH, ATTENTION, ESCALATED
    reason = data.get("reason")
    actor_id = 1

    if not all([customer_id, level, reason]):
        return jsonify({"error": "Missing mandatory fields"}), 400

    if level not in ["WATCH", "ATTENTION", "ESCALATED"]:
        return jsonify({"error": "Invalid level"}), 400

    prev_state = get_current_governance_state(customer_id)

    sql_upsert = """
        INSERT INTO operational_governance (
            id_customer, escalation_level, updated_at
        ) VALUES (%s, %s, NOW())
        ON CONFLICT (id_customer) 
        DO UPDATE SET 
            escalation_level = EXCLUDED.escalation_level,
            updated_at = NOW()
        RETURNING *
    """
    new_row = execute_kelava_query_single(sql_upsert, (customer_id, level))

    log_audit_event(
        customer_id=customer_id,
        action="ESCALATE",
        previous_state=prev_state,
        new_state=new_row,
        actor_id=actor_id,
        note=reason,
    )

    return jsonify({"message": "Escalation level updated", "state": new_row})


@governance_bp.route("/history/<int:customer_id>", methods=["GET"])
@require_auth
def get_governance_history(customer_id):
    """
    Get audit trail for the courtroom view.
    """
    sql = """
        SELECT 
            l.id, l.action, l.note, l.created_at,
            u.fullname as actor_name,
            l.previous_state, l.new_state
        FROM governance_audit_log l
        LEFT JOIN p_user u ON u.id = l.actor_id
        WHERE l.id_customer = %s
        ORDER BY l.created_at DESC
    """
    history = execute_kelava_query(sql, (customer_id,))
    return jsonify({"history": history})


@governance_bp.route("/policies/explain", methods=["GET"])
@require_auth
def explain_policy():
    """
    Get text justification for a rule code.
    """
    code = request.args.get("code")
    explanation = POLICIES.get(code, "Policy rule definition not found.")
    return jsonify({"code": code, "explanation": explanation})
