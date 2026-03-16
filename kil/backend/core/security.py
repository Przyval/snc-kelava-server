"""
Enterprise Authentication Middleware
======================================
Standalone JWT verification - no external service dependency.
Validates tokens signed with our own SECRET_KEY.

Fallback: If token verification fails, allows unauthenticated access
in development mode (KIL_ENV != 'PROD') for backwards compatibility.
"""

import os
from functools import wraps

import jwt
from flask import g, jsonify, request

JWT_SECRET = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
IS_PROD = os.environ.get("KIL_ENV", "").upper() == "PROD"


class AuthUser:
    """Lightweight user object injected into Flask g."""

    def __init__(self, user_id, email, full_name, role, p_user_id=None):
        self.id = user_id
        self.email = email
        self.full_name = full_name
        self.role = role
        self.p_user_id = p_user_id
        self.user_metadata = {"full_name": full_name, "role": role}

    def __repr__(self):
        return f"<AuthUser {self.email} ({self.role})>"


def require_auth(f):
    """
    Authentication decorator for API endpoints.
    Verifies JWT from Authorization: Bearer <token> header.

    On success: sets g.user with AuthUser object.
    On failure in PROD: returns 401.
    On failure in DEV: allows through with anonymous user for development.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")

        if auth_header:
            try:
                token = auth_header.split(" ")[1]
                payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

                g.user = AuthUser(
                    user_id=int(payload["sub"]),
                    email=payload.get("email", ""),
                    full_name=payload.get("full_name", ""),
                    role=payload.get("role", "viewer"),
                    p_user_id=payload.get("p_user_id"),
                )
                g.current_user = g.user
                return f(*args, **kwargs)

            except jwt.ExpiredSignatureError:
                return (
                    jsonify({"error": "Token expired", "code": "AUTH_002"}),
                    401,
                )
            except (jwt.InvalidTokenError, IndexError, KeyError) as e:
                if IS_PROD:
                    return (
                        jsonify(
                            {
                                "error": f"Invalid token: {e!s}",
                                "code": "AUTH_003",
                            }
                        ),
                        401,
                    )
                # In dev, fall through to anonymous access

        # No auth header or invalid token in dev mode
        if IS_PROD:
            return (
                jsonify({"error": "Missing Authorization Header", "code": "AUTH_001"}),
                401,
            )

        # Development fallback: anonymous user
        g.user = AuthUser(
            user_id=0,
            email="dev@sanocare.work",
            full_name="Development User",
            role="admin",
        )
        g.current_user = g.user
        return f(*args, **kwargs)

    return decorated_function


def require_role(*allowed_roles):
    """
    Role-based access control decorator. Use AFTER @require_auth.

    Role hierarchy: admin > koordinator > supervisor > viewer/technician.
    - admin: bypasses all role checks
    - koordinator: inherits supervisor access automatically

    Usage:
        @some_bp.route("/admin-only")
        @require_auth
        @require_role("admin")
        def admin_endpoint():
            ...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = getattr(g, "user", None)
            if not user:
                return jsonify({"error": "Not authenticated"}), 401

            # Admin bypasses all role checks
            if user.role == "admin":
                return f(*args, **kwargs)

            # Koordinator inherits supervisor access
            if user.role == "koordinator" and "supervisor" in allowed_roles:
                return f(*args, **kwargs)

            if user.role not in allowed_roles:
                return (
                    jsonify(
                        {
                            "error": "Insufficient permissions",
                            "required_role": list(allowed_roles),
                            "your_role": user.role,
                        }
                    ),
                    403,
                )

            return f(*args, **kwargs)

        return decorated_function

    return decorator
