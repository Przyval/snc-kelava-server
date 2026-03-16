"""
Health Check & Monitoring API
==============================
Deep health checks: DB connectivity, disk space, service uptime,
and historical uptime logging.
"""

import os
import shutil
import time
from datetime import datetime

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import (
    execute_kelava_query,
    execute_kelava_query_single,
    kelava_is_reachable,
    reset_circuit_breaker,
)

health_bp = Blueprint("health", __name__, url_prefix="/health")

# Track server start time
_START_TIME = time.time()


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _check_db():
    """Check Kelava DB connectivity and latency."""
    try:
        t0 = time.time()
        result = execute_kelava_query_single("SELECT 1 AS ok, NOW() AS server_time")
        latency_ms = round((time.time() - t0) * 1000, 1)
        return {
            "status": "healthy",
            "latency_ms": latency_ms,
            "server_time": result["server_time"].isoformat() if result else None,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e), "latency_ms": None}


def _check_db_tables():
    """Verify critical tables exist and have data."""
    tables = {
        "p_user": "SELECT COUNT(*) AS cnt FROM p_user",
        "m_customer": "SELECT COUNT(*) AS cnt FROM m_customer",
        "t_visit": "SELECT COUNT(*) AS cnt FROM t_visit",
        "t_road_plan": "SELECT COUNT(*) AS cnt FROM t_road_plan",
        "enterprise_users": "SELECT COUNT(*) AS cnt FROM enterprise_users",
    }
    results = {}
    for table, query in tables.items():
        try:
            row = execute_kelava_query_single(query)
            results[table] = {"status": "ok", "row_count": row["cnt"] if row else 0}
        except Exception as e:
            results[table] = {"status": "error", "error": str(e)}
    return results


def _check_disk():
    """Check disk usage on the server."""
    try:
        usage = shutil.disk_usage("/")
        total_gb = round(usage.total / (1024**3), 1)
        used_gb = round(usage.used / (1024**3), 1)
        free_gb = round(usage.free / (1024**3), 1)
        pct_used = round((usage.used / usage.total) * 100, 1)
        return {
            "status": "warning" if pct_used > 85 else "healthy",
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "percent_used": pct_used,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _check_uploads():
    """Check uploads directory size."""
    upload_dir = os.environ.get("UPLOAD_DIR", "/root/kil-server/uploads")
    if not os.path.exists(upload_dir):
        return {"status": "ok", "size_mb": 0, "file_count": 0, "path": upload_dir}
    total_size = 0
    file_count = 0
    try:
        for dirpath, _, filenames in os.walk(upload_dir):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
                    file_count += 1
        return {
            "status": "ok",
            "size_mb": round(total_size / (1024**2), 1),
            "file_count": file_count,
            "path": upload_dir,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Public health endpoint (no auth) ────────────────────────


@health_bp.route("/ping", methods=["GET"])
def ping():
    """Quick liveness probe (no auth)."""
    return jsonify({"status": "ok", "uptime_seconds": round(time.time() - _START_TIME)})


# ── Deep health check (auth required) ───────────────────────


@health_bp.route("/deep", methods=["GET"])
@require_auth
def deep_health():
    """
    Comprehensive health check with DB, disk, uploads diagnostics.
    Admin/koordinator only in practice.
    """
    db_check = _check_db()
    disk_check = _check_disk()
    uploads_check = _check_uploads()
    table_check = _check_db_tables()

    uptime_seconds = round(time.time() - _START_TIME)
    uptime_hours = round(uptime_seconds / 3600, 1)

    overall = "healthy"
    if db_check["status"] != "healthy":
        overall = "degraded"
    if disk_check["status"] == "warning":
        overall = "warning"
    if db_check["status"] == "unhealthy" or disk_check["status"] == "error":
        overall = "unhealthy"

    # Log this check
    _log_health_check(overall, db_check["latency_ms"])

    return jsonify({
        "status": overall,
        "service": "kil-api",
        "version": "2.1.0",
        "uptime_seconds": uptime_seconds,
        "uptime_hours": uptime_hours,
        "checked_at": datetime.now().isoformat(),
        "checks": {
            "database": db_check,
            "disk": disk_check,
            "uploads": uploads_check,
            "tables": table_check,
        },
    })


# ── Health history ───────────────────────────────────────────


@health_bp.route("/history", methods=["GET"])
@require_auth
def health_history():
    """Get recent health check history."""
    days = int(request.args.get("days", 7))
    rows = execute_kelava_query(
        """
        SELECT * FROM health_check_log
        WHERE checked_at >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY checked_at DESC
        LIMIT 200
        """,
        (days,),
    )
    # Summary stats
    stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total_checks,
            COUNT(*) FILTER (WHERE status = 'healthy') AS healthy_count,
            COUNT(*) FILTER (WHERE status != 'healthy') AS issue_count,
            ROUND(AVG(db_latency_ms)::numeric, 1) AS avg_latency_ms,
            MAX(db_latency_ms) AS max_latency_ms,
            MIN(checked_at) AS first_check,
            MAX(checked_at) AS last_check
        FROM health_check_log
        WHERE checked_at >= NOW() - (%s * INTERVAL '1 day')
        """,
        (days,),
    )
    return jsonify({
        "history": [_fmt(r) for r in rows],
        "stats": _fmt(stats) if stats else {},
        "days": days,
    })


# ── Service status summary (for dashboard widget) ───────────


@health_bp.route("/status", methods=["GET"])
@require_auth
def status_summary():
    """Compact status for dashboard embedding."""
    db = _check_db()
    disk = _check_disk()
    uptime_s = round(time.time() - _START_TIME)

    # Recent visit activity (is data flowing?)
    recent = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) FILTER (WHERE created_date >= NOW() - INTERVAL '1 hour') AS visits_1h,
            COUNT(*) FILTER (WHERE created_date >= NOW() - INTERVAL '24 hours') AS visits_24h,
            MAX(created_date) AS last_visit_at
        FROM t_visit
        WHERE created_date >= NOW() - INTERVAL '24 hours'
        """
    )

    return jsonify({
        "db": db["status"],
        "db_latency_ms": db.get("latency_ms"),
        "disk_pct": disk.get("percent_used"),
        "disk_status": disk["status"],
        "uptime_hours": round(uptime_s / 3600, 1),
        "data_flow": {
            "visits_1h": recent["visits_1h"] if recent else 0,
            "visits_24h": recent["visits_24h"] if recent else 0,
            "last_visit": recent["last_visit_at"].isoformat() if recent and recent.get("last_visit_at") else None,
        },
    })


# ── Helpers ──────────────────────────────────────────────────


# ── Circuit Breaker Reset ────────────────────────────────────


@health_bp.route("/reset-circuit-breaker", methods=["POST"])
@require_auth
def reset_kelava_circuit_breaker():
    """
    Manually reset Kelava circuit breaker after DB comes back online.
    Useful when the 30s cooldown hasn't expired yet but DB is known healthy.
    Admin only in practice.
    """
    was_open = not kelava_is_reachable()
    reset_circuit_breaker()
    return jsonify({
        "message": "Circuit breaker reset. Next query will attempt Kelava DB.",
        "was_open": was_open,
    })


# ── Helpers ──────────────────────────────────────────────────


def _log_health_check(status: str, db_latency_ms: float | None):
    """Log health check to DB for history tracking."""
    try:
        _ensure_health_table()
        execute_kelava_query(
            """
            INSERT INTO health_check_log (status, db_latency_ms)
            VALUES (%s, %s)
            """,
            (status, db_latency_ms),
        )
    except Exception:
        pass  # Don't fail health check if logging fails


def _ensure_health_table():
    """Create health_check_log if it doesn't exist."""
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS health_check_log (
            id BIGSERIAL PRIMARY KEY,
            status TEXT NOT NULL,
            db_latency_ms NUMERIC(8,1),
            checked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    execute_kelava_query(
        "CREATE INDEX IF NOT EXISTS idx_health_checked_at ON health_check_log(checked_at DESC)"
    )
