"""
Chemical Usage Tracking API
==============================
Track chemical/pesticide application per visit.
Mandatory fields during service completion.

Meeting: "chemical yang dipakai apa, berapa banyak"
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

chemical_bp = Blueprint("chemical_tracking", __name__, url_prefix="/chemicals")

_TABLE_ENSURED = False


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return

    # Chemical catalog
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS chemical_catalog (
            id              BIGSERIAL PRIMARY KEY,
            name            VARCHAR(200) NOT NULL,
            brand           VARCHAR(100),
            category        VARCHAR(50) DEFAULT 'INSECTICIDE',
            unit_measure    VARCHAR(20) DEFAULT 'ml',
            active_ingredient TEXT,
            safety_class    VARCHAR(20),
            is_active       BOOLEAN DEFAULT true,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    # Usage logs per visit
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS chemical_usage_logs (
            id              BIGSERIAL PRIMARY KEY,
            road_plan_id    INTEGER,
            visit_id        INTEGER,
            technician_id   INTEGER NOT NULL,
            customer_id     INTEGER NOT NULL,
            chemical_id     BIGINT,
            chemical_name   VARCHAR(200) NOT NULL,
            quantity         NUMERIC(10,2) NOT NULL,
            unit_measure    VARCHAR(20) DEFAULT 'ml',
            application_method VARCHAR(50),
            target_pest     VARCHAR(100),
            area_treated    VARCHAR(200),
            notes           TEXT,
            applied_at      TIMESTAMPTZ DEFAULT NOW(),
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_chem_usage_rp
        ON chemical_usage_logs (road_plan_id)
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_chem_usage_tech
        ON chemical_usage_logs (technician_id, applied_at DESC)
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


CATEGORIES = ("INSECTICIDE", "RODENTICIDE", "FUNGICIDE", "HERBICIDE", "DISINFECTANT", "OTHER")
METHODS = ("SPRAY", "GEL", "BAIT", "FOGGING", "MISTING", "DUSTING", "GRANULE", "OTHER")


# ── Chemical Catalog ──────────────────────────────────────────


@chemical_bp.route("/catalog", methods=["GET"])
@require_auth
def list_catalog():
    """List all chemicals in catalog."""
    _ensure_tables()
    active_only = request.args.get("active_only", "true").lower() == "true"

    where = "WHERE is_active = true" if active_only else ""
    rows = execute_kelava_query(
        f"SELECT * FROM chemical_catalog {where} ORDER BY name"
    )

    return jsonify({"chemicals": [_fmt(r) for r in rows], "total": len(rows)})


@chemical_bp.route("/catalog", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def add_chemical():
    """Add a chemical to the catalog."""
    _ensure_tables()
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    result = execute_kelava_query_single(
        """
        INSERT INTO chemical_catalog
            (name, brand, category, unit_measure, active_ingredient, safety_class)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            name, data.get("brand", ""),
            data.get("category", "INSECTICIDE"),
            data.get("unit_measure", "ml"),
            data.get("active_ingredient", ""),
            data.get("safety_class", ""),
        ),
    )

    return jsonify({"message": "Chemical added", "chemical": _fmt(result)}), 201


# ── Log Chemical Usage (Mobile) ───────────────────────────────


@chemical_bp.route("/log", methods=["POST"])
@require_auth
def log_usage():
    """
    Log chemical usage for a visit.

    Body: {
        road_plan_id?: int,
        customer_id: int,
        chemicals: [
            {
                chemical_id?: int (from catalog),
                chemical_name: string,
                quantity: float,
                unit_measure?: string,
                application_method?: string,
                target_pest?: string,
                area_treated?: string,
                notes?: string
            },
            ...
        ]
    }
    """
    _ensure_tables()
    user = g.current_user
    data = request.json or {}

    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"error": "customer_id required"}), 400

    chemicals = data.get("chemicals", [])
    if not chemicals:
        return jsonify({"error": "At least one chemical entry required"}), 400

    tech_id = user.p_user_id or user.id
    rp_id = data.get("road_plan_id")
    logged = 0

    for chem in chemicals:
        name = chem.get("chemical_name", "")
        qty = chem.get("quantity", 0)
        if not name or qty <= 0:
            continue

        execute_kelava_query(
            """
            INSERT INTO chemical_usage_logs
                (road_plan_id, technician_id, customer_id, chemical_id,
                 chemical_name, quantity, unit_measure, application_method,
                 target_pest, area_treated, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                rp_id, tech_id, customer_id,
                chem.get("chemical_id"),
                name, qty,
                chem.get("unit_measure", "ml"),
                chem.get("application_method"),
                chem.get("target_pest"),
                chem.get("area_treated"),
                chem.get("notes", ""),
            ),
        )
        logged += 1

    return jsonify({"message": f"{logged} chemical entries logged", "logged": logged}), 201


# ── Usage History ─────────────────────────────────────────────


@chemical_bp.route("/usage", methods=["GET"])
@require_auth
def usage_history():
    """Chemical usage history. Filters: customer_id, technician_id, days."""
    _ensure_tables()
    customer_id = request.args.get("customer_id")
    tech_id = request.args.get("technician_id")
    days = int(request.args.get("days", 30))
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 100)

    where = ["cl.applied_at >= NOW() - INTERVAL '%s days'"]
    params = [days]

    if customer_id:
        where.append("cl.customer_id = %s")
        params.append(int(customer_id))
    if tech_id:
        where.append("cl.technician_id = %s")
        params.append(int(tech_id))

    where_sql = " AND ".join(where)
    params.extend([per_page, (page - 1) * per_page])

    rows = execute_kelava_query(
        f"""
        SELECT cl.*, u.fullname AS tech_name, c.name AS customer_name
        FROM chemical_usage_logs cl
        JOIN p_user u ON u.id = cl.technician_id
        JOIN m_customer c ON c.id = cl.customer_id
        WHERE {where_sql}
        ORDER BY cl.applied_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    return jsonify({"usage": [_fmt(r) for r in rows], "total": len(rows)})


# ── Usage Summary Report ──────────────────────────────────────


@chemical_bp.route("/summary", methods=["GET"])
@require_auth
def usage_summary():
    """Aggregate chemical usage by type/chemical for reporting."""
    _ensure_tables()
    days = int(request.args.get("days", 30))

    rows = execute_kelava_query(
        """
        SELECT
            cl.chemical_name,
            cl.unit_measure,
            COUNT(*) AS application_count,
            SUM(cl.quantity) AS total_quantity,
            COUNT(DISTINCT cl.customer_id) AS customers_treated,
            COUNT(DISTINCT cl.technician_id) AS technicians_involved
        FROM chemical_usage_logs cl
        WHERE cl.applied_at >= NOW() - INTERVAL '%s days'
        GROUP BY cl.chemical_name, cl.unit_measure
        ORDER BY total_quantity DESC
        """,
        (days,),
    )

    return jsonify({
        "summary": [_fmt(r) for r in rows],
        "period_days": days,
        "generated_at": datetime.now().isoformat(),
    })
