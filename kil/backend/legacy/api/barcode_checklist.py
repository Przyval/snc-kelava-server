"""
QR Code / Barcode Unit Checklist API
=======================================
Replace photo-based unit verification with barcode scanning.
Each pest control unit gets a QR/barcode label; technician scans on visit.

Meeting: "QR code per unit... scan aja, ga usah foto satu-satu"
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

barcode_bp = Blueprint("barcode_checklist", __name__, url_prefix="/barcode")

_TABLE_ENSURED = False


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return

    # Unit registry (each bait station, trap, etc.)
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS unit_registry (
            id              BIGSERIAL PRIMARY KEY,
            customer_id     INTEGER NOT NULL,
            barcode         VARCHAR(100) NOT NULL UNIQUE,
            unit_type       VARCHAR(50) NOT NULL DEFAULT 'BAIT_STATION',
            unit_label      VARCHAR(100),
            location_desc   TEXT,
            floor_level     VARCHAR(20),
            latitude        NUMERIC(10,7),
            longitude       NUMERIC(10,7),
            is_active       BOOLEAN DEFAULT true,
            installed_at    DATE,
            last_scanned_at TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_unit_barcode ON unit_registry (barcode)
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_unit_customer ON unit_registry (customer_id)
    """)

    # Scan logs
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS unit_scan_logs (
            id              BIGSERIAL PRIMARY KEY,
            unit_id         BIGINT NOT NULL,
            road_plan_id    INTEGER,
            technician_id   INTEGER NOT NULL,
            customer_id     INTEGER NOT NULL,
            scan_time       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            condition_code  VARCHAR(20) DEFAULT 'OK',
            notes           TEXT,
            photo_path      TEXT,
            latitude        NUMERIC(10,7),
            longitude       NUMERIC(10,7),
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_scan_log_unit ON unit_scan_logs (unit_id, scan_time DESC)
    """)

    _TABLE_ENSURED = True


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


UNIT_TYPES = ("BAIT_STATION", "TRAP", "MONITOR", "SPRAY_POINT", "FLY_CATCHER", "OTHER")
CONDITION_CODES = ("OK", "DAMAGED", "MISSING", "NEEDS_REPLACEMENT", "INFESTED", "CLEAN")


# ── Unit Registry CRUD ────────────────────────────────────────


@barcode_bp.route("/units", methods=["GET"])
@require_auth
def list_units():
    """List units for a customer. Query: customer_id (required)."""
    _ensure_tables()
    customer_id = request.args.get("customer_id")
    if not customer_id:
        return jsonify({"error": "customer_id required"}), 400

    rows = execute_kelava_query(
        """
        SELECT ur.*, c.name AS customer_name,
               (SELECT COUNT(*) FROM unit_scan_logs usl WHERE usl.unit_id = ur.id) AS total_scans,
               (SELECT MAX(scan_time) FROM unit_scan_logs usl WHERE usl.unit_id = ur.id) AS last_scan
        FROM unit_registry ur
        JOIN m_customer c ON c.id = ur.customer_id
        WHERE ur.customer_id = %s AND ur.is_active = true
        ORDER BY ur.unit_label, ur.barcode
        """,
        (int(customer_id),),
    )

    return jsonify({"units": [_fmt(r) for r in rows], "total": len(rows)})


@barcode_bp.route("/units", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def register_unit():
    """
    Register a new unit with barcode.

    Body: {
        customer_id: int,
        barcode: string,
        unit_type: "BAIT_STATION"|"TRAP"|"MONITOR"|...,
        unit_label?: string (e.g. "BS-01"),
        location_desc?: string,
        floor_level?: string,
        latitude?: float,
        longitude?: float,
        installed_at?: "YYYY-MM-DD"
    }
    """
    _ensure_tables()
    data = request.json or {}

    customer_id = data.get("customer_id")
    barcode = (data.get("barcode") or "").strip()
    if not customer_id or not barcode:
        return jsonify({"error": "customer_id and barcode required"}), 400

    unit_type = data.get("unit_type", "BAIT_STATION")
    if unit_type not in UNIT_TYPES:
        return jsonify({"error": f"unit_type must be one of: {', '.join(UNIT_TYPES)}"}), 400

    try:
        result = execute_kelava_query_single(
            """
            INSERT INTO unit_registry
                (customer_id, barcode, unit_type, unit_label, location_desc,
                 floor_level, latitude, longitude, installed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                customer_id, barcode, unit_type,
                data.get("unit_label", ""),
                data.get("location_desc", ""),
                data.get("floor_level"),
                data.get("latitude"),
                data.get("longitude"),
                data.get("installed_at"),
            ),
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return jsonify({"error": f"Barcode '{barcode}' already registered"}), 409
        raise

    return jsonify({"message": "Unit registered", "unit": _fmt(result)}), 201


@barcode_bp.route("/units/bulk", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def bulk_register():
    """
    Bulk register units.

    Body: {
        customer_id: int,
        units: [
            { barcode, unit_type?, unit_label?, location_desc? },
            ...
        ]
    }
    """
    _ensure_tables()
    data = request.json or {}
    customer_id = data.get("customer_id")
    units = data.get("units", [])

    if not customer_id or not units:
        return jsonify({"error": "customer_id and units required"}), 400

    created = 0
    errors = []
    for u in units:
        barcode = (u.get("barcode") or "").strip()
        if not barcode:
            continue
        try:
            execute_kelava_query(
                """
                INSERT INTO unit_registry (customer_id, barcode, unit_type, unit_label, location_desc)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (customer_id, barcode, u.get("unit_type", "BAIT_STATION"),
                 u.get("unit_label", ""), u.get("location_desc", "")),
            )
            created += 1
        except Exception as e:
            errors.append({"barcode": barcode, "error": str(e)[:100]})

    return jsonify({
        "message": f"{created} units registered",
        "created": created,
        "errors": errors,
    }), 201


# ── Mobile: Scan Unit ─────────────────────────────────────────


@barcode_bp.route("/scan", methods=["POST"])
@require_auth
def scan_unit():
    """
    Technician scans a unit barcode during visit.

    Body: {
        barcode: string,
        road_plan_id?: int,
        condition_code: "OK"|"DAMAGED"|"MISSING"|"NEEDS_REPLACEMENT"|"INFESTED"|"CLEAN",
        notes?: string,
        latitude?: float,
        longitude?: float
    }
    """
    _ensure_tables()
    user = g.current_user
    data = request.json or {}

    barcode = (data.get("barcode") or "").strip()
    if not barcode:
        return jsonify({"error": "barcode required"}), 400

    # Look up unit
    unit = execute_kelava_query_single(
        "SELECT * FROM unit_registry WHERE barcode = %s AND is_active = true",
        (barcode,),
    )
    if not unit:
        return jsonify({"error": f"Unit with barcode '{barcode}' not found"}), 404

    tech_id = user.p_user_id or user.id
    condition = data.get("condition_code", "OK")
    if condition not in CONDITION_CODES:
        condition = "OK"

    result = execute_kelava_query_single(
        """
        INSERT INTO unit_scan_logs
            (unit_id, road_plan_id, technician_id, customer_id,
             condition_code, notes, latitude, longitude)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, scan_time
        """,
        (
            unit["id"], data.get("road_plan_id"), tech_id, unit["customer_id"],
            condition, data.get("notes", ""),
            data.get("latitude"), data.get("longitude"),
        ),
    )

    # Update last_scanned_at on unit
    execute_kelava_query(
        "UPDATE unit_registry SET last_scanned_at = NOW() WHERE id = %s",
        (unit["id"],),
    )

    return jsonify({
        "message": "Scan recorded",
        "scan_id": result["id"],
        "unit_label": unit["unit_label"],
        "customer_id": unit["customer_id"],
        "condition": condition,
    }), 201


# ── Visit Checklist Status ────────────────────────────────────


@barcode_bp.route("/visit-checklist/<int:road_plan_id>", methods=["GET"])
@require_auth
def visit_checklist(road_plan_id):
    """
    Get checklist status for a visit: which units were scanned, which weren't.
    """
    _ensure_tables()

    # Get customer for this road plan
    rp = execute_kelava_query_single(
        "SELECT id_customer FROM t_road_plan WHERE id = %s", (road_plan_id,),
    )
    if not rp:
        return jsonify({"error": "Road plan not found"}), 404

    customer_id = rp["id_customer"]

    # All active units for this customer
    all_units = execute_kelava_query(
        """
        SELECT ur.id, ur.barcode, ur.unit_type, ur.unit_label, ur.location_desc,
               usl.id AS scan_id, usl.scan_time, usl.condition_code, usl.notes AS scan_notes
        FROM unit_registry ur
        LEFT JOIN unit_scan_logs usl ON usl.unit_id = ur.id AND usl.road_plan_id = %s
        WHERE ur.customer_id = %s AND ur.is_active = true
        ORDER BY ur.unit_label, ur.barcode
        """,
        (road_plan_id, customer_id),
    )

    scanned = sum(1 for u in all_units if u["scan_id"])
    total = len(all_units)

    return jsonify({
        "road_plan_id": road_plan_id,
        "customer_id": customer_id,
        "units": [_fmt(u) for u in all_units],
        "scanned": scanned,
        "total": total,
        "completion_pct": round(scanned / total * 100, 1) if total > 0 else 0,
    })


# ── Unit Scan History ─────────────────────────────────────────


@barcode_bp.route("/units/<int:unit_id>/history", methods=["GET"])
@require_auth
def unit_history(unit_id):
    """Scan history for a specific unit."""
    _ensure_tables()
    limit = min(int(request.args.get("limit", 20)), 100)

    rows = execute_kelava_query(
        """
        SELECT usl.*, u.fullname AS tech_name
        FROM unit_scan_logs usl
        JOIN p_user u ON u.id = usl.technician_id
        WHERE usl.unit_id = %s
        ORDER BY usl.scan_time DESC
        LIMIT %s
        """,
        (unit_id, limit),
    )

    return jsonify({"scans": [_fmt(r) for r in rows], "total": len(rows)})
