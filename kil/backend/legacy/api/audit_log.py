"""
Universal Audit Log API
========================
Logs every significant action across all modules:
- Auth events (login, logout, failed login)
- CRUD operations (create, update, delete)
- Status changes (complaint resolved, contract renewed, etc.)
- Data exports

Provides both a logging function (call from other modules) and
query endpoints for the audit trail dashboard.
"""

from datetime import datetime

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

audit_log_bp = Blueprint("audit_log", __name__, url_prefix="/audit-log")

_TABLE_ENSURED = False


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Public API: log an action (used by other modules) ───────


def log_action(
    module: str,
    action: str,
    entity_type: str | None = None,
    entity_id: int | str | None = None,
    detail: str | None = None,
    actor_id: int | str | None = None,
    actor_name: str | None = None,
    ip_address: str | None = None,
):
    """
    Log an action to the universal audit trail.

    Args:
        module: Module name (auth, complaints, contracts, scheduling, etc.)
        action: Action type (login, create, update, delete, export, status_change, etc.)
        entity_type: Type of entity (user, complaint, contract, visit, etc.)
        entity_id: ID of the entity
        detail: Human-readable detail
        actor_id: Who performed the action (enterprise_users.id)
        actor_name: Actor's display name
        ip_address: Client IP address
    """
    try:
        _ensure_table()

        # Try to get actor info from Flask g if not provided
        if actor_id is None:
            user = getattr(g, "current_user", None)
            if user:
                actor_id = getattr(user, "id", None)
                if actor_name is None:
                    actor_name = getattr(user, "full_name", None) or getattr(user, "email", None)

        if ip_address is None:
            try:
                ip_address = request.remote_addr
            except RuntimeError:
                pass  # Outside request context

        execute_kelava_query(
            """
            INSERT INTO universal_audit_log
                (module, action, entity_type, entity_id, detail, actor_id, actor_name, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (module, action, entity_type, str(entity_id) if entity_id else None,
             detail, str(actor_id) if actor_id else None, actor_name, ip_address),
        )
    except Exception as e:
        # Never let audit logging break the main flow
        import logging
        logging.getLogger("audit").warning(f"Failed to log audit: {e}")


# ── Query endpoints ──────────────────────────────────────────


@audit_log_bp.route("", methods=["GET"])
@require_auth
def list_audit_logs():
    """
    Query audit logs with filters.
    Params: module, action, entity_type, actor_id, days, page, per_page, q
    """
    module = request.args.get("module")
    action = request.args.get("action")
    entity_type = request.args.get("entity_type")
    actor_id = request.args.get("actor_id")
    days = int(request.args.get("days", 30))
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)
    offset = (page - 1) * per_page
    search = request.args.get("q", "").strip()

    where_parts = ["created_at >= NOW() - INTERVAL '%s days'"]
    params = [days]

    if module:
        where_parts.append("module = %s")
        params.append(module)
    if action:
        where_parts.append("action = %s")
        params.append(action)
    if entity_type:
        where_parts.append("entity_type = %s")
        params.append(entity_type)
    if actor_id:
        where_parts.append("actor_id = %s")
        params.append(actor_id)
    if search:
        where_parts.append("(LOWER(detail) LIKE %s OR LOWER(actor_name) LIKE %s OR LOWER(module) LIKE %s)")
        params.extend([f"%{search.lower()}%"] * 3)

    where_sql = " AND ".join(where_parts)
    params.extend([per_page, offset])

    rows = execute_kelava_query(
        f"""
        SELECT * FROM universal_audit_log
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    # Count total
    count_params = params[:-2]  # Remove LIMIT/OFFSET params
    total = execute_kelava_query_single(
        f"SELECT COUNT(*) AS cnt FROM universal_audit_log WHERE {where_sql}",
        tuple(count_params),
    )

    return jsonify({
        "logs": [_fmt(r) for r in rows],
        "total": total["cnt"] if total else 0,
        "page": page,
        "per_page": per_page,
        "days": days,
    })


@audit_log_bp.route("/stats", methods=["GET"])
@require_auth
def audit_stats():
    """Audit log statistics for the dashboard."""
    days = int(request.args.get("days", 30))

    # Overall stats
    stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total_events,
            COUNT(DISTINCT actor_id) FILTER (WHERE actor_id IS NOT NULL) AS unique_actors,
            COUNT(DISTINCT module) AS modules_active,
            COUNT(*) FILTER (WHERE action = 'login') AS login_count,
            COUNT(*) FILTER (WHERE action = 'login_failed') AS failed_login_count,
            COUNT(*) FILTER (WHERE action = 'create') AS create_count,
            COUNT(*) FILTER (WHERE action = 'update') AS update_count,
            COUNT(*) FILTER (WHERE action = 'delete') AS delete_count,
            COUNT(*) FILTER (WHERE action = 'export') AS export_count
        FROM universal_audit_log
        WHERE created_at >= NOW() - INTERVAL '%s days'
        """,
        (days,),
    )

    # Activity by module
    by_module = execute_kelava_query(
        """
        SELECT module, COUNT(*) AS count
        FROM universal_audit_log
        WHERE created_at >= NOW() - INTERVAL '%s days'
        GROUP BY module
        ORDER BY count DESC
        """,
        (days,),
    )

    # Activity by hour (for heatmap)
    by_hour = execute_kelava_query(
        """
        SELECT EXTRACT(HOUR FROM created_at)::int AS hour, COUNT(*) AS count
        FROM universal_audit_log
        WHERE created_at >= NOW() - INTERVAL '%s days'
        GROUP BY hour
        ORDER BY hour
        """,
        (days,),
    )

    # Top actors
    top_actors = execute_kelava_query(
        """
        SELECT actor_name, actor_id, COUNT(*) AS count
        FROM universal_audit_log
        WHERE created_at >= NOW() - INTERVAL '%s days' AND actor_name IS NOT NULL
        GROUP BY actor_name, actor_id
        ORDER BY count DESC
        LIMIT 10
        """,
        (days,),
    )

    # Recent security events (login failures, etc.)
    security = execute_kelava_query(
        """
        SELECT * FROM universal_audit_log
        WHERE created_at >= NOW() - INTERVAL '%s days'
          AND action IN ('login_failed', 'password_change', 'role_change', 'user_deactivate')
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (days,),
    )

    return jsonify({
        "stats": _fmt(stats) if stats else {},
        "by_module": [_fmt(r) for r in by_module],
        "by_hour": [_fmt(r) for r in by_hour],
        "top_actors": [_fmt(r) for r in top_actors],
        "security_events": [_fmt(r) for r in security],
        "days": days,
    })


@audit_log_bp.route("/entity/<entity_type>/<entity_id>", methods=["GET"])
@require_auth
def entity_history(entity_type: str, entity_id: str):
    """Get full audit history for a specific entity."""
    rows = execute_kelava_query(
        """
        SELECT * FROM universal_audit_log
        WHERE entity_type = %s AND entity_id = %s
        ORDER BY created_at DESC
        LIMIT 100
        """,
        (entity_type, entity_id),
    )
    return jsonify({"history": [_fmt(r) for r in rows]})


# ── Table setup ──────────────────────────────────────────────


def _ensure_table():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS universal_audit_log (
            id BIGSERIAL PRIMARY KEY,
            module TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            detail TEXT,
            actor_id TEXT,
            actor_name TEXT,
            ip_address TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    execute_kelava_query(
        "CREATE INDEX IF NOT EXISTS idx_ual_created ON universal_audit_log(created_at DESC)"
    )
    execute_kelava_query(
        "CREATE INDEX IF NOT EXISTS idx_ual_module ON universal_audit_log(module, action)"
    )
    execute_kelava_query(
        "CREATE INDEX IF NOT EXISTS idx_ual_entity ON universal_audit_log(entity_type, entity_id)"
    )
    execute_kelava_query(
        "CREATE INDEX IF NOT EXISTS idx_ual_actor ON universal_audit_log(actor_id)"
    )
    _TABLE_ENSURED = True
