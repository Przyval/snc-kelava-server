"""
Schedule Template System API
==============================
Create reusable weekly schedule templates for technicians.
Templates define which customers get visited on which day of the week.
Can be applied to generate road_plan entries for a given week.
"""

from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single
from kil.backend.legacy.api.audit_log import log_action

schedule_tpl_bp = Blueprint("schedule_templates", __name__, url_prefix="/schedule-templates")

_TABLE_ENSURED = False


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── List Templates ───────────────────────────────────────────


@schedule_tpl_bp.route("", methods=["GET"])
@require_auth
def list_templates():
    """List all schedule templates, optionally filtered by technician."""
    _ensure_tables()
    tech_id = request.args.get("technician_id")

    where = "1=1"
    params = []
    if tech_id:
        where = "st.technician_id = %s"
        params = [int(tech_id)]

    rows = execute_kelava_query(
        f"""
        SELECT st.*, u.fullname AS tech_name,
               (SELECT COUNT(*) FROM schedule_template_items sti WHERE sti.template_id = st.id) AS item_count
        FROM schedule_templates st
        LEFT JOIN p_user u ON u.id = st.technician_id
        WHERE {where}
        ORDER BY st.updated_at DESC
        """,
        tuple(params) if params else None,
    )
    return jsonify({"templates": [_fmt(r) for r in rows]})


# ── Create Template ──────────────────────────────────────────


@schedule_tpl_bp.route("", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def create_template():
    """
    Create a schedule template.
    Body: {
        name: str,
        technician_id: int,
        items: [{ day_of_week: 0-6 (Mon-Sun), customer_id: int, service_type?: str, notes?: str }]
    }
    """
    _ensure_tables()
    data = request.json or {}
    name = (data.get("name") or "").strip()
    tech_id = data.get("technician_id")
    items = data.get("items", [])

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not tech_id:
        return jsonify({"error": "technician_id is required"}), 400

    user = getattr(g, "current_user", None)
    created_by = user.id if user else None

    tpl = execute_kelava_query_single(
        """
        INSERT INTO schedule_templates (name, technician_id, created_by)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (name, tech_id, created_by),
    )
    tpl_id = tpl["id"]

    # Insert items
    for item in items:
        dow = item.get("day_of_week")
        cust_id = item.get("customer_id")
        if dow is None or cust_id is None:
            continue
        execute_kelava_query(
            """
            INSERT INTO schedule_template_items (template_id, day_of_week, customer_id, service_type, notes)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (tpl_id, dow, cust_id, item.get("service_type", "Regular"), item.get("notes")),
        )

    log_action("scheduling", "create", "schedule_template", tpl_id, f"Template '{name}' with {len(items)} items")
    return jsonify({"id": tpl_id, "status": "created"}), 201


# ── Template Detail ──────────────────────────────────────────


@schedule_tpl_bp.route("/<int:tpl_id>", methods=["GET"])
@require_auth
def template_detail(tpl_id: int):
    """Get template with all items."""
    _ensure_tables()

    tpl = execute_kelava_query_single(
        """
        SELECT st.*, u.fullname AS tech_name
        FROM schedule_templates st
        LEFT JOIN p_user u ON u.id = st.technician_id
        WHERE st.id = %s
        """,
        (tpl_id,),
    )
    if not tpl:
        return jsonify({"error": "Template not found"}), 404

    items = execute_kelava_query(
        """
        SELECT sti.*, c.name AS customer_name, c.address AS customer_address
        FROM schedule_template_items sti
        LEFT JOIN m_customer c ON c.id = sti.customer_id
        WHERE sti.template_id = %s
        ORDER BY sti.day_of_week, sti.id
        """,
        (tpl_id,),
    )

    return jsonify({"template": _fmt(tpl), "items": [_fmt(i) for i in items]})


# ── Update Template ──────────────────────────────────────────


@schedule_tpl_bp.route("/<int:tpl_id>", methods=["PUT"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def update_template(tpl_id: int):
    """
    Replace template items entirely.
    Body: { name?: str, items: [...] }
    """
    _ensure_tables()
    data = request.json or {}

    tpl = execute_kelava_query_single(
        "SELECT id FROM schedule_templates WHERE id = %s", (tpl_id,),
    )
    if not tpl:
        return jsonify({"error": "Template not found"}), 404

    if "name" in data:
        execute_kelava_query(
            "UPDATE schedule_templates SET name = %s, updated_at = NOW() WHERE id = %s",
            (data["name"], tpl_id),
        )

    if "items" in data:
        # Clear old items
        execute_kelava_query("DELETE FROM schedule_template_items WHERE template_id = %s", (tpl_id,))
        for item in data["items"]:
            dow = item.get("day_of_week")
            cust_id = item.get("customer_id")
            if dow is None or cust_id is None:
                continue
            execute_kelava_query(
                """
                INSERT INTO schedule_template_items (template_id, day_of_week, customer_id, service_type, notes)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (tpl_id, dow, cust_id, item.get("service_type", "Regular"), item.get("notes")),
            )
        execute_kelava_query("UPDATE schedule_templates SET updated_at = NOW() WHERE id = %s", (tpl_id,))

    log_action("scheduling", "update", "schedule_template", tpl_id, "Template updated")
    return jsonify({"status": "updated"})


# ── Delete Template ──────────────────────────────────────────


@schedule_tpl_bp.route("/<int:tpl_id>", methods=["DELETE"])
@require_auth
@require_role("admin", "koordinator")
def delete_template(tpl_id: int):
    """Delete a schedule template."""
    _ensure_tables()
    execute_kelava_query("DELETE FROM schedule_template_items WHERE template_id = %s", (tpl_id,))
    execute_kelava_query("DELETE FROM schedule_templates WHERE id = %s", (tpl_id,))
    log_action("scheduling", "delete", "schedule_template", tpl_id, "Template deleted")
    return jsonify({"status": "deleted"})


# ── Apply Template (Generate Road Plans) ─────────────────────


@schedule_tpl_bp.route("/<int:tpl_id>/apply", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def apply_template(tpl_id: int):
    """
    Apply a template to generate road_plan entries for a given week.
    Body: { week_start: "YYYY-MM-DD" (must be a Monday) }

    This creates t_road_plan rows for each template item on the
    appropriate day of the specified week.
    """
    _ensure_tables()
    data = request.json or {}
    week_start_str = data.get("week_start")

    if not week_start_str:
        return jsonify({"error": "week_start is required (YYYY-MM-DD, must be Monday)"}), 400

    week_start = datetime.strptime(week_start_str, "%Y-%m-%d").date()
    if week_start.weekday() != 0:
        return jsonify({"error": "week_start must be a Monday"}), 400

    tpl = execute_kelava_query_single(
        "SELECT * FROM schedule_templates WHERE id = %s", (tpl_id,),
    )
    if not tpl:
        return jsonify({"error": "Template not found"}), 404

    items = execute_kelava_query(
        "SELECT * FROM schedule_template_items WHERE template_id = %s ORDER BY day_of_week",
        (tpl_id,),
    )

    created = 0
    skipped = 0
    for item in items:
        plan_date = week_start + timedelta(days=item["day_of_week"])

        # Check if road_plan already exists for this tech+customer+date
        existing = execute_kelava_query_single(
            """
            SELECT id FROM t_road_plan
            WHERE id_user = %s AND id_customer = %s AND visit_date::date = %s
            """,
            (tpl["technician_id"], item["customer_id"], plan_date),
        )
        if existing:
            skipped += 1
            continue

        execute_kelava_query(
            """
            INSERT INTO t_road_plan (id_user, id_customer, visit_date, type, status, created_date)
            VALUES (%s, %s, %s, %s, 'Baru', NOW())
            """,
            (tpl["technician_id"], item["customer_id"], plan_date, item.get("service_type") or "Regular"),
        )
        created += 1

    log_action("scheduling", "create", "road_plan_batch", tpl_id,
               f"Applied template to {week_start}: {created} created, {skipped} skipped")

    return jsonify({
        "status": "applied",
        "week_start": str(week_start),
        "created": created,
        "skipped": skipped,
        "total_items": len(items),
    })


# ── Technician Search ────────────────────────────────────────


@schedule_tpl_bp.route("/technicians", methods=["GET"])
@require_auth
def search_technicians():
    """Quick technician search for template forms."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        rows = execute_kelava_query(
            """
            SELECT u.id, u.fullname AS name
            FROM p_user u
            JOIN enterprise_users eu ON eu.p_user_id = u.id
            WHERE eu.role = 'technician' AND eu.is_active = true
            ORDER BY u.fullname LIMIT 20
            """
        )
    else:
        rows = execute_kelava_query(
            """
            SELECT u.id, u.fullname AS name
            FROM p_user u
            JOIN enterprise_users eu ON eu.p_user_id = u.id
            WHERE eu.role = 'technician' AND eu.is_active = true
              AND LOWER(u.fullname) LIKE %s
            ORDER BY u.fullname LIMIT 10
            """,
            (f"%{q.lower()}%",),
        )
    return jsonify([_fmt(r) for r in rows])


# ── Table Setup ──────────────────────────────────────────────


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS schedule_templates (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            technician_id BIGINT NOT NULL,
            created_by BIGINT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS schedule_template_items (
            id BIGSERIAL PRIMARY KEY,
            template_id BIGINT NOT NULL,
            day_of_week INT NOT NULL,
            customer_id BIGINT NOT NULL,
            service_type TEXT DEFAULT 'Regular',
            notes TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    execute_kelava_query("CREATE INDEX IF NOT EXISTS idx_sched_tpl_tech ON schedule_templates(technician_id)")
    execute_kelava_query("CREATE INDEX IF NOT EXISTS idx_sched_tpl_items ON schedule_template_items(template_id)")
    _TABLE_ENSURED = True
