"""
Supervisory Action Log API
============================
SAP-Grade audit trail and escalation workflow.
Provides cross-entity action log, supervisory review, and escalation tracking.
"""

from datetime import datetime

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

audit_bp = Blueprint("audit", __name__, url_prefix="/audit")


def _auth_user_id() -> str | None:
    user = getattr(g, "user", None)
    return str(user.id) if user else None


def _auth_user_name() -> str:
    user = getattr(g, "user", None)
    if user and user.user_metadata:
        return user.user_metadata.get("full_name", user.email or "System")
    return "System"


def _fmt(row):
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Supervisory Dashboard ────────────────────────────────────


@audit_bp.route("/dashboard", methods=["GET"])
@require_auth
def audit_dashboard():
    """
    Supervisory overview: open reviews, escalation counts, recent activity.
    """
    uid = _auth_user_id()

    # Open reviews summary
    open_reviews = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) as total_open,
            COUNT(*) FILTER (WHERE escalation_level = 'WATCH') as watch_count,
            COUNT(*) FILTER (WHERE escalation_level = 'ATTENTION') as attention_count,
            COUNT(*) FILTER (WHERE escalation_level = 'ESCALATED') as escalated_count
        FROM operational_governance
        WHERE review_status = 'OPEN'
        """,
        user_id=uid,
    )

    # Recent activity (last 30 days)
    recent_count = execute_kelava_query_single(
        """
        SELECT COUNT(*) as cnt
        FROM governance_audit_log
        WHERE created_at >= NOW() - INTERVAL '30 days'
        """,
        user_id=uid,
    )

    # Pending actions by entity type
    pending_by_type = execute_kelava_query(
        """
        SELECT
            action,
            COUNT(*) as count
        FROM governance_audit_log
        WHERE created_at >= NOW() - INTERVAL '30 days'
        GROUP BY action
        ORDER BY count DESC
        """,
        user_id=uid,
    )

    # Open escalations with customer info
    escalations = execute_kelava_query(
        """
        SELECT
            og.id, og.id_customer, og.review_status, og.escalation_level,
            og.last_review_at, og.review_note,
            c.name as customer_name, c.code as customer_code,
            u.fullname as last_reviewer_name
        FROM operational_governance og
        JOIN m_customer c ON c.id = og.id_customer
        LEFT JOIN p_user u ON u.id = og.last_reviewer_id
        WHERE og.review_status = 'OPEN'
        ORDER BY
            CASE og.escalation_level
                WHEN 'ESCALATED' THEN 1
                WHEN 'ATTENTION' THEN 2
                WHEN 'WATCH' THEN 3
            END,
            og.updated_at DESC
        LIMIT 20
        """,
        user_id=uid,
    )

    # Winback campaign activity (cross-reference)
    winback_recent = execute_kelava_query(
        """
        SELECT
            wal.action, wal.note, wal.actor_name, wal.created_at,
            wc.name as campaign_name, wc.status as campaign_status
        FROM winback_activity_log wal
        JOIN winback_campaigns wc ON wc.id = wal.campaign_id
        WHERE wal.created_at >= NOW() - INTERVAL '7 days'
        ORDER BY wal.created_at DESC
        LIMIT 10
        """,
        user_id=uid,
    )

    # Contract renewal activity
    renewal_recent = execute_kelava_query(
        """
        SELECT
            crl.action, crl.note, crl.created_at, crl.next_follow_up,
            k.no_kontrak, c.name as customer_name
        FROM contract_renewal_log crl
        JOIN m_customer_kontrak k ON k.id = crl.contract_id
        JOIN m_customer c ON c.id = k.id_customer
        WHERE crl.created_at >= NOW() - INTERVAL '7 days'
        ORDER BY crl.created_at DESC
        LIMIT 10
        """,
        user_id=uid,
    )

    return jsonify({
        "open_reviews": _fmt(open_reviews) if open_reviews else {},
        "recent_activity_30d": recent_count["cnt"] if recent_count else 0,
        "activity_by_type": [_fmt(a) for a in pending_by_type],
        "escalations": [_fmt(e) for e in escalations],
        "winback_activity": [_fmt(w) for w in winback_recent],
        "renewal_activity": [_fmt(r) for r in renewal_recent],
        "generated_at": datetime.now().isoformat(),
    })


# ── Unified Activity Feed ────────────────────────────────────


@audit_bp.route("/feed", methods=["GET"])
@require_auth
def activity_feed():
    """
    Unified activity feed across all modules:
    governance, winback, contracts.
    """
    uid = _auth_user_id()
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 30)), 100)
    offset = (page - 1) * per_page
    module_filter = request.args.get("module")

    feeds = []

    # Governance audit log
    if not module_filter or module_filter == "governance":
        gov_logs = execute_kelava_query(
            """
            SELECT
                'governance' as module,
                gal.action as action_type,
                gal.note,
                gal.created_at,
                gal.actor_id::text as actor_id,
                u.fullname as actor_name,
                c.name as entity_name,
                gal.id_customer as entity_id,
                'customer' as entity_type
            FROM governance_audit_log gal
            LEFT JOIN p_user u ON u.id = gal.actor_id
            LEFT JOIN m_customer c ON c.id = gal.id_customer
            ORDER BY gal.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (per_page, offset),
            user_id=uid,
        )
        feeds.extend(gov_logs)

    # Winback activity log
    if not module_filter or module_filter == "winback":
        wb_logs = execute_kelava_query(
            """
            SELECT
                'winback' as module,
                wal.action as action_type,
                wal.note,
                wal.created_at,
                wal.actor_id::text as actor_id,
                wal.actor_name,
                wc.name as entity_name,
                wal.campaign_id as entity_id,
                'campaign' as entity_type
            FROM winback_activity_log wal
            JOIN winback_campaigns wc ON wc.id = wal.campaign_id
            ORDER BY wal.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (per_page, offset),
            user_id=uid,
        )
        feeds.extend(wb_logs)

    # Contract renewal log
    if not module_filter or module_filter == "contracts":
        cr_logs = execute_kelava_query(
            """
            SELECT
                'contracts' as module,
                crl.action as action_type,
                crl.note,
                crl.created_at,
                crl.actor_id as actor_id,
                NULL as actor_name,
                c.name as entity_name,
                crl.contract_id as entity_id,
                'contract' as entity_type
            FROM contract_renewal_log crl
            JOIN m_customer_kontrak k ON k.id = crl.contract_id
            JOIN m_customer c ON c.id = k.id_customer
            ORDER BY crl.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (per_page, offset),
            user_id=uid,
        )
        feeds.extend(cr_logs)

    # Sort all feeds by created_at descending
    feeds.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)

    # Trim to per_page
    feeds = feeds[:per_page]

    return jsonify({
        "feed": [_fmt(f) for f in feeds],
        "page": page,
        "per_page": per_page,
        "generated_at": datetime.now().isoformat(),
    })


# ── Supervisory Action ──────────────────────────────────────


@audit_bp.route("/action", methods=["POST"])
@require_auth
def log_supervisory_action():
    """
    Log a supervisory action on any entity.

    Body: {
        entity_type: 'customer' | 'technician' | 'contract' | 'campaign',
        entity_id: int,
        action: str,
        note: str (mandatory),
        escalation_level?: str
    }
    """
    data = request.json or {}
    entity_type = data.get("entity_type")
    entity_id = data.get("entity_id")
    action = data.get("action")
    note = data.get("note")
    escalation_level = data.get("escalation_level")
    uid = _auth_user_id()

    if not all([entity_type, entity_id, action, note]):
        return jsonify({"error": "entity_type, entity_id, action, and note are required"}), 400

    # Log to supervisory_action_log
    _ensure_supervisory_table()

    result = execute_kelava_query_single(
        """
        INSERT INTO supervisory_action_log
            (entity_type, entity_id, action, note, escalation_level, actor_id, actor_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (entity_type, entity_id, action, note, escalation_level, uid, _auth_user_name()),
        user_id=uid,
    )

    # If it's a customer action, also update operational_governance
    if entity_type == "customer" and escalation_level:
        execute_kelava_query(
            """
            INSERT INTO operational_governance (id_customer, escalation_level, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (id_customer)
            DO UPDATE SET escalation_level = EXCLUDED.escalation_level, updated_at = NOW()
            """,
            (entity_id, escalation_level),
            user_id=uid,
        )

    return jsonify({
        "message": "Supervisory action logged",
        "action": _fmt(result) if result else {},
    }), 201


@audit_bp.route("/actions/<entity_type>/<int:entity_id>", methods=["GET"])
@require_auth
def get_entity_actions(entity_type: str, entity_id: int):
    """Get all supervisory actions for a specific entity."""
    uid = _auth_user_id()

    _ensure_supervisory_table()

    actions = execute_kelava_query(
        """
        SELECT * FROM supervisory_action_log
        WHERE entity_type = %s AND entity_id = %s
        ORDER BY created_at DESC
        """,
        (entity_type, entity_id),
        user_id=uid,
    )

    return jsonify({"actions": [_fmt(a) for a in actions]})


def _ensure_supervisory_table():
    """Create supervisory_action_log if it doesn't exist."""
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS supervisory_action_log (
            id BIGSERIAL PRIMARY KEY,
            entity_type VARCHAR(50) NOT NULL,
            entity_id INTEGER NOT NULL,
            action VARCHAR(100) NOT NULL,
            note TEXT NOT NULL,
            escalation_level VARCHAR(30),
            actor_id VARCHAR(100),
            actor_name VARCHAR(200),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
    """)
    execute_kelava_query(
        "CREATE INDEX IF NOT EXISTS idx_sup_action_entity ON supervisory_action_log(entity_type, entity_id)"
    )
    execute_kelava_query(
        "CREATE INDEX IF NOT EXISTS idx_sup_action_created ON supervisory_action_log(created_at DESC)"
    )
