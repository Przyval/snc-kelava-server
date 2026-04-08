"""
API Documentation & OpenAPI Spec
==================================
Auto-generates OpenAPI 3.0 JSON from Flask URL map + docstrings.
Powers Swagger UI and the API Explorer frontend.
"""

import re

from flask import Blueprint, current_app, jsonify

api_docs_bp = Blueprint("api_docs", __name__)


def _build_openapi_spec():
    """Build OpenAPI 3.0 spec from Flask URL map."""
    paths: dict = {}

    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint in ("static", "enterprise.static"):
            continue
        if "/static" in rule.rule:
            continue

        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        if not methods:
            continue

        func = current_app.view_functions.get(rule.endpoint)
        doc = ""
        params_desc = []
        if func and func.__doc__:
            raw = func.__doc__.strip()
            lines = raw.split("\n")
            doc = lines[0].strip()
            in_params = False
            for line in lines[1:]:
                line = line.strip()
                if any(k in line.lower() for k in ("param", "query", "args:", "arg:")):
                    in_params = True
                if in_params and ":" in line and line:
                    parts = line.split(":", 1)
                    if len(parts) == 2 and parts[0].strip():
                        params_desc.append({
                            "name": parts[0].strip().split(",")[0].strip(),
                            "description": parts[1].strip(),
                        })

        auth_required = "/enterprise" in rule.rule or "/mobile" in rule.rule

        path_key = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule)
        if path_key not in paths:
            paths[path_key] = {}

        tag = (
            rule.endpoint.split(".")[0].replace("_", " ").title()
            if "." in rule.endpoint
            else "Core"
        )

        for method in methods:
            ml = method.lower()
            operation: dict = {
                "summary": doc or rule.endpoint,
                "operationId": f"{rule.endpoint.replace('.', '_')}_{ml}",
                "tags": [tag],
                "responses": {
                    "200": {"description": "Success"},
                    "401": {"description": "Unauthorized"},
                    "500": {"description": "Server error"},
                },
            }
            if auth_required:
                operation["security"] = [{"bearerAuth": []}]

            path_params = re.findall(r"\{(\w+)\}", path_key)
            if path_params:
                operation["parameters"] = [
                    {
                        "name": p,
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer" if "id" in p else "string"},
                    }
                    for p in path_params
                ]

            if params_desc and ml == "get":
                existing = {p["name"] for p in operation.get("parameters", [])}
                for pd in params_desc:
                    if pd["name"] not in existing:
                        operation.setdefault("parameters", []).append({
                            "name": pd["name"],
                            "in": "query",
                            "required": False,
                            "description": pd["description"],
                            "schema": {"type": "string"},
                        })

            paths[path_key][ml] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "SanoCare KIL API",
            "version": "2.2.0",
            "description": (
                "Operational intelligence API for SanoCare field service management. "
                "Connects to Kelava live database for real-time technician, customer, and visit data."
            ),
            "contact": {"name": "SanoCare Tech", "url": "https://safencare.work"},
        },
        "servers": [
            {"url": "https://safencare.work", "description": "Production"},
            {"url": "http://localhost:5001", "description": "Local dev"},
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "JWT dari POST /api/v1/auth/login",
                }
            }
        },
        "paths": paths,
    }


@api_docs_bp.route("/api/v1/openapi.json")
def openapi_json():
    """OpenAPI 3.0 specification — machine-readable JSON for Swagger UI."""
    return jsonify(_build_openapi_spec())


@api_docs_bp.route("/api/v1/docs")
def api_endpoint_list():
    """List all API endpoints grouped by blueprint (simple JSON for Explorer UI)."""
    endpoints = []

    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint in ("static", "enterprise.static"):
            continue
        if "/static" in rule.rule:
            continue

        methods = sorted(rule.methods - {"HEAD", "OPTIONS"})
        if not methods:
            continue

        func = current_app.view_functions.get(rule.endpoint)
        doc = (func.__doc__ or "").strip().split("\n")[0] if func else ""
        auth_required = "/enterprise" in rule.rule or "/mobile" in rule.rule
        group = rule.endpoint.split(".")[0] if "." in rule.endpoint else "core"

        endpoints.append({
            "path": rule.rule,
            "methods": methods,
            "summary": doc,
            "auth": auth_required,
            "group": group,
        })

    groups: dict = {}
    for ep in endpoints:
        groups.setdefault(ep["group"], []).append(ep)

    return jsonify({
        "total": len(endpoints),
        "base_url": "https://safencare.work",
        "auth": {
            "type": "Bearer JWT",
            "obtain": "POST /api/v1/auth/login",
            "body": {"login": "email or p_user_id", "password": "SanoCare{last4}"},
        },
        "groups": groups,
    })
