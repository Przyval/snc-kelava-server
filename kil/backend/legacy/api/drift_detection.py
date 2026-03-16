"""
GPS Drift Detection & Auto-Sidak Engine
==========================================
Detects GPS anomalies: check-in location vs customer location,
configurable radius per customer (mall=500m, rumah=100m).
Auto-generates sidak (inspection) flags for suspicious activity.

Meeting: "toleransi radius... mall beda sama rumah"
Meeting: "Surat Sidak otomatis kalau ada anomali"
"""

import math
from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

drift_bp = Blueprint("drift_detection", __name__, url_prefix="/drift")

_TABLE_ENSURED = False

# Default drift radius in meters
DEFAULT_RADIUS_M = 200
MALL_RADIUS_M = 500


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return

    # Customer GPS config (radius tolerance per customer)
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS customer_gps_config (
            id              BIGSERIAL PRIMARY KEY,
            customer_id     INTEGER NOT NULL UNIQUE,
            latitude        NUMERIC(10,7),
            longitude       NUMERIC(10,7),
            radius_meters   INTEGER NOT NULL DEFAULT 200,
            location_type   VARCHAR(30) DEFAULT 'STANDARD',
            notes           TEXT,
            updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_cust_gps_config_cid
        ON customer_gps_config (customer_id)
    """)

    # Drift detection results
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS drift_alerts (
            id              BIGSERIAL PRIMARY KEY,
            visit_id        INTEGER,
            road_plan_id    INTEGER,
            technician_id   INTEGER NOT NULL,
            customer_id     INTEGER,
            alert_type      VARCHAR(30) NOT NULL,
            severity        VARCHAR(15) DEFAULT 'warning',
            checkin_lat     NUMERIC(10,7),
            checkin_lng     NUMERIC(10,7),
            expected_lat    NUMERIC(10,7),
            expected_lng    NUMERIC(10,7),
            drift_meters    NUMERIC(10,1),
            allowed_radius  INTEGER,
            detail          TEXT,
            auto_sidak      BOOLEAN DEFAULT false,
            sidak_action_id BIGINT,
            resolved        BOOLEAN DEFAULT false,
            resolved_by     VARCHAR(100),
            resolved_at     TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_drift_alerts_tech
        ON drift_alerts (technician_id, created_at DESC)
    """)

    _TABLE_ENSURED = True


def _haversine(lat1, lng1, lat2, lng2):
    """Calculate distance in meters between two GPS coordinates."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lng2) - float(lng1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Customer GPS Config CRUD ─────────────────────────────────


@drift_bp.route("/config", methods=["GET"])
@require_auth
def list_configs():
    """List all customer GPS configurations."""
    _ensure_tables()

    rows = execute_kelava_query(
        """
        SELECT gc.*, c.name AS customer_name, c.address
        FROM customer_gps_config gc
        JOIN m_customer c ON c.id = gc.customer_id
        ORDER BY c.name
        """
    )

    return jsonify({
        "configs": [_fmt(r) for r in rows],
        "total": len(rows),
        "default_radius_m": DEFAULT_RADIUS_M,
    })


@drift_bp.route("/config", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def set_config():
    """
    Set GPS drift config for a customer.

    Body: {
        customer_id: int,
        latitude: float,
        longitude: float,
        radius_meters: int (default 200),
        location_type: "STANDARD"|"MALL"|"GEDUNG"|"PERUMAHAN"|"PABRIK"|"CUSTOM",
        notes?: string
    }
    """
    _ensure_tables()
    data = request.json or {}

    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"error": "customer_id required"}), 400

    lat = data.get("latitude")
    lng = data.get("longitude")
    radius = data.get("radius_meters", DEFAULT_RADIUS_M)
    loc_type = data.get("location_type", "STANDARD")

    result = execute_kelava_query_single(
        """
        INSERT INTO customer_gps_config
            (customer_id, latitude, longitude, radius_meters, location_type, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (customer_id) DO UPDATE SET
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            radius_meters = EXCLUDED.radius_meters,
            location_type = EXCLUDED.location_type,
            notes = EXCLUDED.notes,
            updated_at = NOW()
        RETURNING *
        """,
        (customer_id, lat, lng, radius, loc_type, data.get("notes", "")),
    )

    return jsonify({"message": "Config saved", "config": _fmt(result)}), 201


@drift_bp.route("/config/bulk-import", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def bulk_import_configs():
    """
    Auto-populate customer GPS configs from visit check-in history.
    Uses the most common check-in location as the "expected" location.
    """
    _ensure_tables()

    # Find most common check-in location per customer (from last 90 days)
    rows = execute_kelava_query(
        """
        WITH ranked AS (
            SELECT
                rp.id_customer,
                ROUND(v.latitude::numeric, 5) AS lat,
                ROUND(v.longitude::numeric, 5) AS lng,
                COUNT(*) AS cnt,
                ROW_NUMBER() OVER (PARTITION BY rp.id_customer ORDER BY COUNT(*) DESC) AS rn
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE v.check_in >= NOW() - INTERVAL '90 days'
              AND v.latitude IS NOT NULL AND v.latitude != 0
              AND v.longitude IS NOT NULL AND v.longitude != 0
            GROUP BY rp.id_customer, ROUND(v.latitude::numeric, 5), ROUND(v.longitude::numeric, 5)
        )
        SELECT id_customer AS customer_id, lat AS latitude, lng AS longitude, cnt AS visit_count
        FROM ranked
        WHERE rn = 1 AND cnt >= 3
        ORDER BY cnt DESC
        """
    )

    imported = 0
    for r in rows:
        execute_kelava_query(
            """
            INSERT INTO customer_gps_config (customer_id, latitude, longitude, radius_meters, location_type, notes)
            VALUES (%s, %s, %s, %s, 'STANDARD', %s)
            ON CONFLICT (customer_id) DO NOTHING
            """,
            (r["customer_id"], r["latitude"], r["longitude"], DEFAULT_RADIUS_M,
             f"Auto-imported from {r['visit_count']} visits"),
        )
        imported += 1

    return jsonify({
        "message": f"Imported {imported} customer GPS configs",
        "imported": imported,
        "candidates": len(rows),
    })


# ── Drift Detection Scan ─────────────────────────────────────


@drift_bp.route("/scan", methods=["POST"])
@require_auth
def run_drift_scan():
    """
    Run GPS drift detection scan for recent visits.
    Compares check-in GPS against customer expected location.
    Auto-creates drift alerts + optionally triggers sidak.

    Body: {
        days: int (default 7),
        auto_sidak: bool (default false) — auto-create sidak for critical drift
    }
    """
    _ensure_tables()
    data = request.json or {}
    days = data.get("days", 7)
    auto_sidak = data.get("auto_sidak", False)

    # Get visits with GPS data
    visits = execute_kelava_query(
        """
        SELECT
            v.id AS visit_id,
            rp.id AS road_plan_id,
            rp.id_user AS technician_id,
            rp.id_customer AS customer_id,
            v.latitude AS checkin_lat,
            v.longitude AS checkin_lng,
            gc.latitude AS expected_lat,
            gc.longitude AS expected_lng,
            COALESCE(gc.radius_meters, %s) AS allowed_radius,
            gc.location_type
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        LEFT JOIN customer_gps_config gc ON gc.customer_id = rp.id_customer
        WHERE v.check_in >= NOW() - INTERVAL '%s days'
          AND v.latitude IS NOT NULL AND v.latitude != 0
          AND v.longitude IS NOT NULL AND v.longitude != 0
          AND gc.latitude IS NOT NULL
          AND v.id NOT IN (SELECT visit_id FROM drift_alerts WHERE visit_id IS NOT NULL)
        """,
        (DEFAULT_RADIUS_M, days),
    )

    alerts_created = 0
    sidak_created = 0

    for v in visits:
        distance = _haversine(
            v["checkin_lat"], v["checkin_lng"],
            v["expected_lat"], v["expected_lng"]
        )
        allowed = int(v["allowed_radius"])

        if distance <= allowed:
            continue  # Within tolerance

        # Determine severity
        if distance > allowed * 5:
            severity = "critical"
        elif distance > allowed * 2:
            severity = "warning"
        else:
            severity = "info"

        detail = (
            f"Check-in {int(distance)}m from expected location "
            f"(allowed: {allowed}m, type: {v['location_type'] or 'STANDARD'})"
        )

        result = execute_kelava_query_single(
            """
            INSERT INTO drift_alerts
                (visit_id, road_plan_id, technician_id, customer_id,
                 alert_type, severity, checkin_lat, checkin_lng,
                 expected_lat, expected_lng, drift_meters, allowed_radius, detail)
            VALUES (%s, %s, %s, %s, 'GPS_DRIFT', %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                v["visit_id"], v["road_plan_id"], v["technician_id"],
                v["customer_id"], severity,
                v["checkin_lat"], v["checkin_lng"],
                v["expected_lat"], v["expected_lng"],
                round(distance, 1), allowed, detail,
            ),
        )
        alerts_created += 1

        # Auto-create sidak for critical drift
        if auto_sidak and severity == "critical":
            sidak = execute_kelava_query_single(
                """
                INSERT INTO supervisory_actions
                    (action_type, target_technician_id, target_customer_id,
                     scheduled_date, priority, trigger_reason, status, created_by)
                VALUES ('SIDAK', %s, %s, CURRENT_DATE + 1, 'URGENT', %s, 'SCHEDULED', %s)
                RETURNING id
                """,
                (
                    v["technician_id"], v["customer_id"],
                    f"AUTO-SIDAK: {detail}",
                    str(g.current_user.id),
                ),
            )
            if sidak:
                execute_kelava_query(
                    "UPDATE drift_alerts SET auto_sidak = true, sidak_action_id = %s WHERE id = %s",
                    (sidak["id"], result["id"]),
                )
                sidak_created += 1

    return jsonify({
        "message": f"Scan complete. {alerts_created} drift alerts, {sidak_created} auto-sidak created.",
        "visits_checked": len(visits),
        "alerts_created": alerts_created,
        "sidak_created": sidak_created,
    })


# ── Drift Alerts List ─────────────────────────────────────────


@drift_bp.route("/alerts", methods=["GET"])
@require_auth
def list_alerts():
    """List drift alerts with filters."""
    _ensure_tables()
    severity = request.args.get("severity")
    tech_id = request.args.get("technician_id")
    resolved = request.args.get("resolved", "false")
    days = int(request.args.get("days", 30))
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 100)

    where = ["da.created_at >= NOW() - INTERVAL '%s days'"]
    params = [days]

    if resolved == "false":
        where.append("da.resolved = false")
    elif resolved == "true":
        where.append("da.resolved = true")

    if severity:
        where.append("da.severity = %s")
        params.append(severity)

    if tech_id:
        where.append("da.technician_id = %s")
        params.append(int(tech_id))

    where_sql = " AND ".join(where)
    params.extend([per_page, (page - 1) * per_page])

    rows = execute_kelava_query(
        f"""
        SELECT da.*, u.fullname AS tech_name, c.name AS customer_name
        FROM drift_alerts da
        LEFT JOIN p_user u ON u.id = da.technician_id
        LEFT JOIN m_customer c ON c.id = da.customer_id
        WHERE {where_sql}
        ORDER BY da.created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    total = execute_kelava_query_single(
        f"SELECT COUNT(*) AS cnt FROM drift_alerts da WHERE {where_sql}",
        tuple(params[:-2]),
    )

    return jsonify({
        "alerts": [_fmt(r) for r in rows],
        "total": total["cnt"] if total else 0,
        "page": page,
        "per_page": per_page,
    })


# ── Resolve Alert ─────────────────────────────────────────────


@drift_bp.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
@require_auth
def resolve_alert(alert_id):
    """Resolve a drift alert."""
    _ensure_tables()
    data = request.json or {}
    note = data.get("note", "")

    execute_kelava_query(
        """
        UPDATE drift_alerts
        SET resolved = true, resolved_by = %s, resolved_at = NOW(),
            detail = detail || ' | Resolution: ' || %s
        WHERE id = %s
        """,
        (g.current_user.full_name, note, alert_id),
    )

    return jsonify({"message": "Alert resolved"})


# ── Technician Drift Score ────────────────────────────────────


@drift_bp.route("/scores", methods=["GET"])
@require_auth
def drift_scores():
    """
    GPS compliance score per technician (last 30 days).
    Shows who has the most drift violations.
    """
    _ensure_tables()
    days = int(request.args.get("days", 30))

    rows = execute_kelava_query(
        """
        SELECT
            da.technician_id,
            u.fullname AS tech_name,
            COUNT(*) AS total_alerts,
            COUNT(*) FILTER (WHERE da.severity = 'critical') AS critical_count,
            COUNT(*) FILTER (WHERE da.severity = 'warning') AS warning_count,
            ROUND(AVG(da.drift_meters)::numeric, 0) AS avg_drift_m,
            MAX(da.drift_meters) AS max_drift_m,
            COUNT(*) FILTER (WHERE da.auto_sidak = true) AS auto_sidak_count
        FROM drift_alerts da
        JOIN p_user u ON u.id = da.technician_id
        WHERE da.created_at >= NOW() - INTERVAL '%s days'
        GROUP BY da.technician_id, u.fullname
        ORDER BY total_alerts DESC
        """,
        (days,),
    )

    return jsonify({
        "scores": [_fmt(r) for r in rows],
        "period_days": days,
        "generated_at": datetime.now().isoformat(),
    })
