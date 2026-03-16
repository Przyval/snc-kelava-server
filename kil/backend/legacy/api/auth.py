"""
Enterprise Authentication API
===============================
Standalone JWT authentication - no external dependency required.
Handles login, token refresh, profile, and password management.
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from flask import Blueprint, jsonify, request

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single, kelava_is_reachable
from kil.backend.legacy.api.audit_log import log_action

auth_api_bp = Blueprint("auth_api", __name__, url_prefix="/auth")

# JWT Configuration
JWT_SECRET = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRY = timedelta(hours=2)
JWT_REFRESH_EXPIRY = timedelta(days=30)

# Account lockout
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

# IP-based rate limiting (in-memory)
_login_attempts = {}  # {ip: [timestamp, ...]}
MAX_LOGIN_PER_MINUTE = 10


def _hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _create_access_token(user: dict) -> str:
    """Create a signed JWT access token."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "iat": now,
        "exp": now + JWT_ACCESS_EXPIRY,
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _create_refresh_token(_user_id: int) -> tuple[str, str]:
    """Create a refresh token and return (raw_token, token_hash)."""
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, token_hash


def _log_auth_event(user_id, action: str, success: bool, detail: str = None):
    """Write to immutable auth audit log."""
    ip = request.remote_addr
    ua = request.headers.get("User-Agent", "")[:500]
    execute_kelava_query(
        """
        INSERT INTO enterprise_auth_log (user_id, action, success, ip_address, user_agent, detail)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (user_id, action, success, ip, ua, detail),
    )


# ── Login ────────────────────────────────────────────────────


@auth_api_bp.route("/login", methods=["POST"])
def login():
    """
    Authenticate with ID Pekerja / email + password, receive JWT tokens.

    Body: { "login": "...", "password": "..." }
    Also accepts legacy { "email": "...", "password": "..." }
    Returns: { "access_token": "...", "refresh_token": "...", "user": {...} }
    """
    # IP rate limiting
    ip = request.remote_addr
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=1)
    attempts = _login_attempts.get(ip, [])
    attempts = [t for t in attempts if t > cutoff]
    if len(attempts) >= MAX_LOGIN_PER_MINUTE:
        return jsonify({"error": "Terlalu banyak percobaan login. Coba lagi nanti."}), 429
    attempts.append(now)
    _login_attempts[ip] = attempts

    data = request.json or {}
    login_input = (data.get("login") or data.get("email") or "").strip()
    password = data.get("password") or ""

    if not login_input or not password:
        return jsonify({"error": "ID Pekerja/email dan password harus diisi"}), 400

    # Strategy 1: Try as email
    user = execute_kelava_query_single(
        "SELECT * FROM enterprise_users WHERE LOWER(email) = %s",
        (login_input.lower(),),
    )

    # Strategy 2: Try as p_user_id (numeric ID Pekerja)
    if not user:
        try:
            p_id = int(login_input)
            user = execute_kelava_query_single(
                "SELECT * FROM enterprise_users WHERE p_user_id = %s",
                (p_id,),
            )
        except (ValueError, TypeError):
            pass

    # Strategy 3: Try matching p_user.username in Kelava (skip if DB unreachable)
    if not user and kelava_is_reachable():
        try:
            pu = execute_kelava_query_single(
                "SELECT id FROM p_user WHERE LOWER(username) = %s",
                (login_input.lower(),),
            )
            if pu:
                user = execute_kelava_query_single(
                    "SELECT * FROM enterprise_users WHERE p_user_id = %s",
                    (pu["id"],),
                )
        except Exception:
            pass  # Kelava DB unreachable — skip username lookup

    if not user:
        _log_auth_event(None, "LOGIN", False, f"Unknown login: {login_input}")
        log_action("auth", "login_failed", "user", None, f"Unknown login: {login_input}")
        return jsonify({"error": "ID Pekerja atau password salah"}), 401

    # Check lockout
    if user["locked_until"] and user["locked_until"] > datetime.now(timezone.utc):
        remaining = int((user["locked_until"] - datetime.now(timezone.utc)).total_seconds())
        _log_auth_event(user["id"], "LOGIN", False, "Account locked")
        return jsonify({
            "error": "Account temporarily locked",
            "locked_for_seconds": remaining,
        }), 423

    # Check active
    if not user["is_active"]:
        _log_auth_event(user["id"], "LOGIN", False, "Account deactivated")
        return jsonify({"error": "Account deactivated. Contact administrator."}), 403

    # Verify password
    if not _verify_password(password, user["password_hash"]):
        # Increment failed count
        new_count = (user["failed_login_count"] or 0) + 1
        locked_until = None
        if new_count >= MAX_FAILED_ATTEMPTS:
            locked_until = datetime.now(timezone.utc) + LOCKOUT_DURATION

        execute_kelava_query(
            """
            UPDATE enterprise_users
            SET failed_login_count = %s, locked_until = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (new_count, locked_until, user["id"]),
        )
        _log_auth_event(user["id"], "LOGIN", False, f"Wrong password (attempt {new_count})")
        log_action("auth", "login_failed", "user", user["id"], f"Wrong password (attempt {new_count})", actor_id=user["id"], actor_name=user.get("full_name"))
        return jsonify({"error": "Invalid credentials"}), 401

    # Success - reset failed count, update last_login
    execute_kelava_query(
        """
        UPDATE enterprise_users
        SET failed_login_count = 0, locked_until = NULL,
            last_login_at = NOW(), updated_at = NOW()
        WHERE id = %s
        """,
        (user["id"],),
    )

    # Create tokens
    access_token = _create_access_token(user)
    raw_refresh, refresh_hash = _create_refresh_token(user["id"])

    # Store refresh token
    execute_kelava_query(
        """
        INSERT INTO enterprise_refresh_tokens
            (user_id, token_hash, expires_at, user_agent, ip_address)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            user["id"],
            refresh_hash,
            datetime.now(timezone.utc) + JWT_REFRESH_EXPIRY,
            request.headers.get("User-Agent", "")[:500],
            request.remote_addr,
        ),
    )

    _log_auth_event(user["id"], "LOGIN", True)
    log_action("auth", "login", "user", user["id"], f"Login successful", actor_id=user["id"], actor_name=user.get("full_name"))

    return jsonify({
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "Bearer",
        "expires_in": int(JWT_ACCESS_EXPIRY.total_seconds()),
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "p_user_id": user.get("p_user_id"),
        },
    })


# ── Token Refresh ────────────────────────────────────────────


@auth_api_bp.route("/refresh", methods=["POST"])
def refresh_token():
    """
    Exchange refresh token for new access + refresh tokens.

    Body: { "refresh_token": "..." }
    """
    data = request.json or {}
    raw_token = data.get("refresh_token")

    if not raw_token:
        return jsonify({"error": "refresh_token is required"}), 400

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    # Find and validate refresh token
    stored = execute_kelava_query_single(
        """
        SELECT rt.*, eu.email, eu.full_name, eu.role, eu.is_active
        FROM enterprise_refresh_tokens rt
        JOIN enterprise_users eu ON eu.id = rt.user_id
        WHERE rt.token_hash = %s AND rt.revoked = false
        """,
        (token_hash,),
    )

    if not stored:
        return jsonify({"error": "Invalid refresh token"}), 401

    if stored["expires_at"] < datetime.now(timezone.utc):
        # Revoke expired token
        execute_kelava_query(
            "UPDATE enterprise_refresh_tokens SET revoked = true WHERE id = %s",
            (stored["id"],),
        )
        return jsonify({"error": "Refresh token expired"}), 401

    if not stored["is_active"]:
        return jsonify({"error": "Account deactivated"}), 403

    # Revoke old refresh token (rotation)
    execute_kelava_query(
        "UPDATE enterprise_refresh_tokens SET revoked = true WHERE id = %s",
        (stored["id"],),
    )

    # Look up p_user_id for the user
    eu = execute_kelava_query_single(
        "SELECT p_user_id FROM enterprise_users WHERE id = %s",
        (stored["user_id"],),
    )

    # Issue new tokens
    user = {
        "id": stored["user_id"],
        "email": stored["email"],
        "full_name": stored["full_name"],
        "role": stored["role"],
        "p_user_id": eu["p_user_id"] if eu else None,
    }
    new_access = _create_access_token(user)
    new_raw_refresh, new_refresh_hash = _create_refresh_token(user["id"])

    execute_kelava_query(
        """
        INSERT INTO enterprise_refresh_tokens
            (user_id, token_hash, expires_at, user_agent, ip_address)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            user["id"],
            new_refresh_hash,
            datetime.now(timezone.utc) + JWT_REFRESH_EXPIRY,
            request.headers.get("User-Agent", "")[:500],
            request.remote_addr,
        ),
    )

    _log_auth_event(user["id"], "TOKEN_REFRESH", True)

    return jsonify({
        "access_token": new_access,
        "refresh_token": new_raw_refresh,
        "token_type": "Bearer",
        "expires_in": int(JWT_ACCESS_EXPIRY.total_seconds()),
        "user": user,
    })


# ── Current User Profile ─────────────────────────────────────


@auth_api_bp.route("/me", methods=["GET"])
def get_me():
    """Get current authenticated user profile."""
    # Verify token manually (this endpoint uses its own auth check)
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "Missing Authorization header"}), 401

    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (IndexError, jwt.ExpiredSignatureError, jwt.InvalidTokenError) as e:
        return jsonify({"error": f"Invalid token: {str(e)}"}), 401

    user = execute_kelava_query_single(
        """
        SELECT id, email, full_name, role, is_active, last_login_at, created_at, p_user_id
        FROM enterprise_users WHERE id = %s
        """,
        (int(payload["sub"]),),
    )

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Get permissions
    permissions = execute_kelava_query(
        "SELECT resource, action FROM enterprise_permissions WHERE role = %s",
        (user["role"],),
    )

    result = dict(user)
    for k, v in result.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()

    result["permissions"] = [
        {"resource": p["resource"], "action": p["action"]} for p in permissions
    ]

    return jsonify({"user": result})


# ── Change Password ──────────────────────────────────────────


@auth_api_bp.route("/change-password", methods=["POST"])
def change_password():
    """
    Change password for current user.

    Body: { "current_password": "...", "new_password": "..." }
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"error": "Missing Authorization header"}), 401

    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (IndexError, jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"error": "Invalid token"}), 401

    data = request.json or {}
    current_pw = data.get("current_password")
    new_pw = data.get("new_password")

    if not current_pw or not new_pw:
        return jsonify({"error": "current_password and new_password are required"}), 400

    if len(new_pw) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    user = execute_kelava_query_single(
        "SELECT * FROM enterprise_users WHERE id = %s",
        (int(payload["sub"]),),
    )

    if not user:
        return jsonify({"error": "User not found"}), 404

    if not _verify_password(current_pw, user["password_hash"]):
        _log_auth_event(user["id"], "PASSWORD_CHANGE", False, "Wrong current password")
        return jsonify({"error": "Current password is incorrect"}), 401

    new_hash = _hash_password(new_pw)
    execute_kelava_query(
        "UPDATE enterprise_users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
        (new_hash, user["id"]),
    )

    # Revoke all refresh tokens (force re-login on all devices)
    execute_kelava_query(
        "UPDATE enterprise_refresh_tokens SET revoked = true WHERE user_id = %s",
        (user["id"],),
    )

    _log_auth_event(user["id"], "PASSWORD_CHANGE", True)
    log_action("auth", "password_change", "user", user["id"], "Password changed", actor_id=user["id"], actor_name=user.get("full_name"))

    return jsonify({"message": "Password changed successfully. Please log in again."})


# ── Logout ───────────────────────────────────────────────────


@auth_api_bp.route("/logout", methods=["POST"])
def logout():
    """Revoke current refresh token."""
    data = request.json or {}
    raw_token = data.get("refresh_token")

    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        execute_kelava_query(
            "UPDATE enterprise_refresh_tokens SET revoked = true WHERE token_hash = %s",
            (token_hash,),
        )

    return jsonify({"message": "Logged out successfully"})


# ── Verify Token (for frontend health check) ─────────────────


@auth_api_bp.route("/verify", methods=["GET"])
def verify_token():
    """Quick token verification endpoint."""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"valid": False}), 401

    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return jsonify({
            "valid": True,
            "user_id": payload["sub"],
            "role": payload["role"],
            "exp": payload["exp"],
        })
    except (IndexError, jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return jsonify({"valid": False}), 401
