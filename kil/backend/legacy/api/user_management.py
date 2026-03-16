"""
User Management API
====================
Admin-only endpoints for managing enterprise users.
CRUD users, assign roles, reset passwords, view auth logs.
"""

import bcrypt
from flask import Blueprint, g, jsonify, request

from core.security import require_auth, require_role
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

user_mgmt_bp = Blueprint("user_mgmt", __name__, url_prefix="/users")


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ── List Users ────────────────────────────────────────────────


@user_mgmt_bp.route("/", methods=["GET"])
@require_auth
@require_role("admin", "supervisor")
def list_users():
    """List all enterprise users with filtering."""
    role_filter = request.args.get("role", "")
    search = request.args.get("search", "").strip()
    active_only = request.args.get("active", "true").lower() == "true"
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, int(request.args.get("per_page", 50)))

    conditions = []
    params = []

    if role_filter:
        conditions.append("role = %s")
        params.append(role_filter)

    if search:
        conditions.append("(LOWER(email) LIKE %s OR LOWER(full_name) LIKE %s)")
        params.extend([f"%{search.lower()}%", f"%{search.lower()}%"])

    if active_only:
        conditions.append("is_active = true")

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    total = execute_kelava_query_single(
        f"SELECT COUNT(*) as cnt FROM enterprise_users {where}", params
    )

    users = execute_kelava_query(
        f"""
        SELECT id, email, full_name, role, is_active, p_user_id,
               last_login_at, failed_login_count, locked_until,
               created_at, updated_at
        FROM enterprise_users
        {where}
        ORDER BY
            CASE role WHEN 'admin' THEN 1 WHEN 'koordinator' THEN 2
                      WHEN 'supervisor' THEN 3 WHEN 'viewer' THEN 4 ELSE 5 END,
            full_name
        LIMIT %s OFFSET %s
        """,
        params + [per_page, (page - 1) * per_page],
    )

    # Serialize datetimes
    for u in users:
        for k, v in u.items():
            if hasattr(v, "isoformat"):
                u[k] = v.isoformat()

    return jsonify({
        "users": users,
        "total": total["cnt"],
        "page": page,
        "per_page": per_page,
    })


# ── Get User Detail ──────────────────────────────────────────


@user_mgmt_bp.route("/<int:user_id>", methods=["GET"])
@require_auth
@require_role("admin", "supervisor")
def get_user(user_id):
    """Get detailed user info including recent auth activity."""
    user = execute_kelava_query_single(
        """
        SELECT id, email, full_name, role, is_active, p_user_id,
               last_login_at, failed_login_count, locked_until,
               created_at, updated_at
        FROM enterprise_users WHERE id = %s
        """,
        (user_id,),
    )

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Recent auth events
    auth_log = execute_kelava_query(
        """
        SELECT action, success, ip_address, detail, created_at
        FROM enterprise_auth_log
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (user_id,),
    )

    # Active sessions count
    sessions = execute_kelava_query_single(
        """
        SELECT COUNT(*) as cnt FROM enterprise_refresh_tokens
        WHERE user_id = %s AND revoked = false AND expires_at > NOW()
        """,
        (user_id,),
    )

    for k, v in user.items():
        if hasattr(v, "isoformat"):
            user[k] = v.isoformat()

    for log in auth_log:
        for k, v in log.items():
            if hasattr(v, "isoformat"):
                log[k] = v.isoformat()

    return jsonify({
        "user": user,
        "auth_log": auth_log,
        "active_sessions": sessions["cnt"],
    })


# ── Create User ──────────────────────────────────────────────


@user_mgmt_bp.route("/", methods=["POST"])
@require_auth
@require_role("admin")
def create_user():
    """Create a new enterprise user."""
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    full_name = (data.get("full_name") or "").strip()
    password = data.get("password") or ""
    role = data.get("role", "viewer")

    if not email or not full_name:
        return jsonify({"error": "email and full_name are required"}), 400

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    if role not in ("admin", "koordinator", "supervisor", "viewer", "technician"):
        return jsonify({"error": "Invalid role"}), 400

    # Check duplicate
    existing = execute_kelava_query_single(
        "SELECT id FROM enterprise_users WHERE email = %s", (email,)
    )
    if existing:
        return jsonify({"error": "Email already exists"}), 409

    pw_hash = _hash_password(password)
    p_user_id = data.get("p_user_id")

    result = execute_kelava_query_single(
        """
        INSERT INTO enterprise_users (email, password_hash, full_name, role, p_user_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (email, pw_hash, full_name, role, p_user_id),
    )

    return jsonify({"id": result["id"], "message": "User created"}), 201


# ── Update User ──────────────────────────────────────────────


@user_mgmt_bp.route("/<int:user_id>", methods=["PATCH"])
@require_auth
@require_role("admin")
def update_user(user_id):
    """Update user profile (role, name, active status)."""
    data = request.json or {}

    user = execute_kelava_query_single(
        "SELECT * FROM enterprise_users WHERE id = %s", (user_id,)
    )
    if not user:
        return jsonify({"error": "User not found"}), 404

    updates = []
    params = []

    if "full_name" in data:
        updates.append("full_name = %s")
        params.append(data["full_name"].strip())

    if "role" in data:
        if data["role"] not in ("admin", "koordinator", "supervisor", "viewer", "technician"):
            return jsonify({"error": "Invalid role"}), 400
        updates.append("role = %s")
        params.append(data["role"])

    if "is_active" in data:
        updates.append("is_active = %s")
        params.append(bool(data["is_active"]))

    if "email" in data:
        new_email = data["email"].strip().lower()
        dup = execute_kelava_query_single(
            "SELECT id FROM enterprise_users WHERE email = %s AND id != %s",
            (new_email, user_id),
        )
        if dup:
            return jsonify({"error": "Email already in use"}), 409
        updates.append("email = %s")
        params.append(new_email)

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    updates.append("updated_at = NOW()")
    params.append(user_id)

    execute_kelava_query(
        f"UPDATE enterprise_users SET {', '.join(updates)} WHERE id = %s",
        params,
    )

    return jsonify({"message": "User updated"})


# ── Reset Password (Admin) ───────────────────────────────────


@user_mgmt_bp.route("/<int:user_id>/reset-password", methods=["POST"])
@require_auth
@require_role("admin")
def reset_password(user_id):
    """Admin reset - set a new password for a user."""
    data = request.json or {}
    new_pw = data.get("new_password", "")

    if len(new_pw) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    user = execute_kelava_query_single(
        "SELECT id FROM enterprise_users WHERE id = %s", (user_id,)
    )
    if not user:
        return jsonify({"error": "User not found"}), 404

    pw_hash = _hash_password(new_pw)

    execute_kelava_query(
        """
        UPDATE enterprise_users
        SET password_hash = %s, failed_login_count = 0, locked_until = NULL, updated_at = NOW()
        WHERE id = %s
        """,
        (pw_hash, user_id),
    )

    # Revoke all sessions
    execute_kelava_query(
        "UPDATE enterprise_refresh_tokens SET revoked = true WHERE user_id = %s",
        (user_id,),
    )

    # Log
    execute_kelava_query(
        """
        INSERT INTO enterprise_auth_log (user_id, action, success, detail)
        VALUES (%s, 'PASSWORD_RESET_BY_ADMIN', true, %s)
        """,
        (user_id, f"Reset by user #{getattr(g, 'user', None) and g.user.id}"),
    )

    return jsonify({"message": "Password reset. All sessions revoked."})


# ── Unlock Account ────────────────────────────────────────────


@user_mgmt_bp.route("/<int:user_id>/unlock", methods=["POST"])
@require_auth
@require_role("admin")
def unlock_account(user_id):
    """Unlock a locked-out user account."""
    execute_kelava_query(
        """
        UPDATE enterprise_users
        SET failed_login_count = 0, locked_until = NULL, updated_at = NOW()
        WHERE id = %s
        """,
        (user_id,),
    )
    return jsonify({"message": "Account unlocked"})


# ── Auth Audit Log ────────────────────────────────────────────


@user_mgmt_bp.route("/auth-log", methods=["GET"])
@require_auth
@require_role("admin")
def auth_audit_log():
    """View system-wide auth audit log."""
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, int(request.args.get("per_page", 50)))
    action_filter = request.args.get("action", "")

    conditions = []
    params = []

    if action_filter:
        conditions.append("eal.action = %s")
        params.append(action_filter)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    logs = execute_kelava_query(
        f"""
        SELECT eal.*, eu.email, eu.full_name
        FROM enterprise_auth_log eal
        LEFT JOIN enterprise_users eu ON eu.id = eal.user_id
        {where}
        ORDER BY eal.created_at DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, (page - 1) * per_page],
    )

    for log in logs:
        for k, v in log.items():
            if hasattr(v, "isoformat"):
                log[k] = v.isoformat()

    return jsonify({"logs": logs, "page": page})


# ── Role Summary Stats ───────────────────────────────────────


@user_mgmt_bp.route("/stats", methods=["GET"])
@require_auth
@require_role("admin", "supervisor")
def user_stats():
    """User management overview stats."""
    by_role = execute_kelava_query(
        "SELECT role, COUNT(*) as cnt FROM enterprise_users GROUP BY role ORDER BY cnt DESC"
    )
    total = execute_kelava_query_single("SELECT COUNT(*) as cnt FROM enterprise_users")
    active = execute_kelava_query_single(
        "SELECT COUNT(*) as cnt FROM enterprise_users WHERE is_active = true"
    )
    locked = execute_kelava_query_single(
        "SELECT COUNT(*) as cnt FROM enterprise_users WHERE locked_until > NOW()"
    )
    recent_logins = execute_kelava_query_single(
        """
        SELECT COUNT(*) as cnt FROM enterprise_users
        WHERE last_login_at > NOW() - INTERVAL '7 days'
        """
    )

    return jsonify({
        "total": total["cnt"],
        "active": active["cnt"],
        "locked": locked["cnt"],
        "recent_logins_7d": recent_logins["cnt"],
        "by_role": by_role,
    })
