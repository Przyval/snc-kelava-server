"""
Export System API
==================
CSV download endpoints for key operational data:
- Technician leaderboard
- Visit history
- Complaints
- Contract summary
- CSAT ratings
- Audit log
"""

import csv
import io
from datetime import datetime

from flask import Blueprint, Response, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query

export_bp = Blueprint("export", __name__, url_prefix="/export")


def _csv_response(rows, filename, columns=None):
    """Convert query rows to CSV response with proper headers."""
    if not rows:
        return Response("No data", mimetype="text/plain", status=404)

    output = io.StringIO()
    cols = columns or list(dict(rows[0]).keys())
    writer = csv.DictWriter(output, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()

    for row in rows:
        d = dict(row)
        # Convert datetime to string
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        writer.writerow(d)

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Visit History ──────────────────────────────────────────


@export_bp.route("/visits", methods=["GET"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def export_visits():
    """
    Export visit data as CSV.
    Query params: date_from, date_to (YYYY-MM-DD), technician_id
    """
    date_from = request.args.get("date_from", datetime.now().strftime("%Y-%m-01"))
    date_to = request.args.get("date_to", datetime.now().strftime("%Y-%m-%d"))
    tech_id = request.args.get("technician_id")

    where = "rp.visit_date::date BETWEEN %s AND %s"
    params = [date_from, date_to]
    if tech_id:
        where += " AND rp.id_user = %s"
        params.append(int(tech_id))

    rows = execute_kelava_query(
        f"""
        SELECT
            rp.visit_date, u.fullname AS technician,
            c.name AS customer, c.address,
            rp.type AS service_type, rp.status,
            v.check_in, v.check_out,
            CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                 THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60
                 ELSE NULL END AS duration_minutes,
            v.latitude AS lat_in, v.longitude AS lng_in,
            v.latitude_o AS lat_out, v.longitude_o AS lng_out,
            v.note
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE {where}
        ORDER BY rp.visit_date, u.fullname, v.check_in
        """,
        tuple(params),
    )

    filename = f"visits_{date_from}_to_{date_to}.csv"
    return _csv_response(rows, filename)


# ── Technician Leaderboard ─────────────────────────────────


@export_bp.route("/leaderboard", methods=["GET"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def export_leaderboard():
    """
    Export technician performance leaderboard as CSV.
    Query params: date_from, date_to
    """
    date_from = request.args.get("date_from", datetime.now().strftime("%Y-%m-01"))
    date_to = request.args.get("date_to", datetime.now().strftime("%Y-%m-%d"))

    rows = execute_kelava_query(
        """
        SELECT
            u.fullname AS technician,
            COUNT(*) AS total_planned,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            COUNT(*) FILTER (WHERE rp.status NOT IN ('Selesai', 'Berjalan')) AS not_visited,
            ROUND(COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS completion_rate,
            COUNT(DISTINCT rp.visit_date) AS active_days,
            COUNT(DISTINCT rp.id_customer) AS unique_customers
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.visit_date::date BETWEEN %s AND %s
        GROUP BY u.id, u.fullname
        ORDER BY completion_rate DESC, completed DESC
        """,
        (date_from, date_to),
    )

    filename = f"leaderboard_{date_from}_to_{date_to}.csv"
    return _csv_response(rows, filename)


# ── Complaints ──────────────────────────────────────────────


@export_bp.route("/complaints", methods=["GET"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def export_complaints():
    """Export complaints as CSV. Query params: status, date_from, date_to"""
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    status = request.args.get("status")

    where = "1=1"
    params = []
    if date_from:
        where += " AND comp.created_at >= %s"
        params.append(date_from)
    if date_to:
        where += " AND comp.created_at <= %s::date + 1"
        params.append(date_to)
    if status:
        where += " AND comp.status = %s"
        params.append(status)

    rows = execute_kelava_query(
        f"""
        SELECT
            comp.id, comp.created_at, comp.status, comp.priority,
            comp.category, comp.description,
            c.name AS customer, u.fullname AS technician,
            comp.resolution, comp.resolved_at
        FROM complaints comp
        LEFT JOIN m_customer c ON c.id = comp.customer_id
        LEFT JOIN p_user u ON u.id = comp.technician_id
        WHERE {where}
        ORDER BY comp.created_at DESC
        """,
        tuple(params) if params else None,
    )

    filename = f"complaints_{datetime.now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


# ── Contracts ───────────────────────────────────────────────


@export_bp.route("/contracts", methods=["GET"])
@require_auth
@require_role("admin", "koordinator")
def export_contracts():
    """Export contract summary as CSV."""
    rows = execute_kelava_query(
        """
        SELECT
            k.id, k.nomor_kontrak, k.start_date, k.end_date, k.is_active,
            c.name AS customer, c.address, c.phone1,
            k.type AS contract_type,
            CASE WHEN k.end_date < CURRENT_DATE THEN 'EXPIRED'
                 WHEN k.end_date < CURRENT_DATE + 30 THEN 'EXPIRING_SOON'
                 ELSE 'ACTIVE' END AS health_status
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        ORDER BY k.end_date
        """
    )

    filename = f"contracts_{datetime.now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


# ── CSAT Ratings ─────────────────────────────────────────────


@export_bp.route("/csat", methods=["GET"])
@require_auth
@require_role("admin", "koordinator")
def export_csat():
    """Export CSAT ratings as CSV."""
    try:
        rows = execute_kelava_query(
            """
            SELECT
                cr.created_at, cr.rating, cr.category, cr.comment,
                c.name AS customer, u.fullname AS technician
            FROM csat_ratings cr
            LEFT JOIN m_customer c ON c.id = cr.customer_id
            LEFT JOIN p_user u ON u.id = cr.technician_id
            ORDER BY cr.created_at DESC
            """
        )
    except Exception:
        rows = []

    filename = f"csat_ratings_{datetime.now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


# ── Audit Log ───────────────────────────────────────────────


@export_bp.route("/audit-log", methods=["GET"])
@require_auth
@require_role("admin")
def export_audit_log():
    """Export audit log as CSV. Query params: days (default 30)"""
    days = int(request.args.get("days", 30))

    try:
        rows = execute_kelava_query(
            """
            SELECT
                created_at, module, action, entity_type, entity_id,
                detail, actor_name, ip_address
            FROM universal_audit_log
            WHERE created_at >= NOW() - INTERVAL '%s days'
            ORDER BY created_at DESC
            """,
            (days,),
        )
    except Exception:
        rows = []

    filename = f"audit_log_{days}d_{datetime.now().strftime('%Y%m%d')}.csv"
    return _csv_response(rows, filename)


# ── Available Exports Listing ────────────────────────────────


@export_bp.route("", methods=["GET"])
@require_auth
def list_exports():
    """List available export endpoints."""
    return jsonify({
        "exports": [
            {"name": "visits", "url": "/export/visits", "params": ["date_from", "date_to", "technician_id"], "roles": ["admin", "koordinator", "supervisor"]},
            {"name": "leaderboard", "url": "/export/leaderboard", "params": ["date_from", "date_to"], "roles": ["admin", "koordinator", "supervisor"]},
            {"name": "complaints", "url": "/export/complaints", "params": ["status", "date_from", "date_to"], "roles": ["admin", "koordinator", "supervisor"]},
            {"name": "contracts", "url": "/export/contracts", "params": [], "roles": ["admin", "koordinator"]},
            {"name": "csat", "url": "/export/csat", "params": [], "roles": ["admin", "koordinator"]},
            {"name": "audit-log", "url": "/export/audit-log", "params": ["days"], "roles": ["admin"]},
        ]
    })
