"""
API Documentation Endpoint
============================
Auto-generates endpoint listing from Flask's URL map.
"""

from flask import Blueprint, current_app, jsonify

api_docs_bp = Blueprint("api_docs", __name__, url_prefix="/docs")


@api_docs_bp.route("", methods=["GET"])
def api_documentation():
    """List all API endpoints with methods and descriptions."""
    endpoints = []

    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint == "static" or rule.rule.startswith("/static"):
            continue

        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        if not methods:
            continue

        # Get docstring from view function
        func = current_app.view_functions.get(rule.endpoint)
        doc = ""
        if func and func.__doc__:
            doc = func.__doc__.strip().split("\n")[0]

        # Determine auth requirement
        auth_required = False
        role_required = None
        if func:
            # Check decorator chain
            inner = func
            while hasattr(inner, "__wrapped__"):
                inner = inner.__wrapped__
            # Simple heuristic: if the endpoint is under /api/v1/enterprise, it needs auth
            if "/enterprise" in rule.rule or "/mobile" in rule.rule:
                auth_required = True

        endpoints.append({
            "path": rule.rule,
            "methods": methods,
            "description": doc,
            "auth_required": auth_required,
            "blueprint": rule.endpoint.split(".")[0] if "." in rule.endpoint else None,
        })

    # Group by blueprint
    groups = {}
    for ep in endpoints:
        bp = ep.get("blueprint") or "core"
        groups.setdefault(bp, []).append(ep)

    return jsonify({
        "total_endpoints": len(endpoints),
        "groups": groups,
        "version": "2.1.0",
        "base_url": "https://safencare.work",
        "auth": {
            "type": "Bearer JWT",
            "login": "POST /api/v1/auth/login",
            "body": {"login": "email or ID Pekerja", "password": "..."},
        },
    })
