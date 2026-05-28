"""
Schedule Auto-Generate Engine
================================
Reads schedule_templates (contract frequency patterns) and auto-generates
t_road_plan entries for the next month. Reduces 3-day manual scheduling to minutes.

Also provides drag-and-drop move API for the scheduling board.

Meeting: "3 hari bikin jadwal jadi 5 menit"
Meeting: "drag and drop... pindahin teknisi ke hari lain"
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import _get_local_pool, execute_kelava_query, execute_kelava_query_single
from psycopg.rows import dict_row

schedule_gen_bp = Blueprint("schedule_generator", __name__, url_prefix="/schedule-gen")


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _auth_user_id():
    user = getattr(g, "user", None)
    return str(user.id) if user else None


# ── Auto-Generate Road Plans from Templates ───────────────────


@schedule_gen_bp.route("/generate", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def generate_schedule():
    """
    Auto-generate t_road_plan entries from schedule_templates.

    Body: {
        year: int,
        month: int,
        technician_id?: int (filter specific tech),
        dry_run: bool (default true — preview only)
    }
    """
    data = request.json or {}
    uid = _auth_user_id()

    year = data.get("year", date.today().year)
    month = data.get("month", date.today().month + 1)
    if month > 12:
        month = 1
        year += 1

    tech_filter = data.get("technician_id")
    dry_run = data.get("dry_run", True)

    # Calculate date range for target month
    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)

    # Get active templates
    where = "st.is_active = true AND st.technician_id IS NOT NULL"
    params = []
    if tech_filter:
        where += " AND st.technician_id = %s"
        params.append(int(tech_filter))

    templates = execute_kelava_query(
        f"""
        SELECT st.id AS template_id, st.customer_id, st.technician_id,
               st.day_of_week, st.scheduled_time, st.visit_type,
               st.frequency, st.contract_id,
               u.fullname AS tech_name, c.name AS customer_name
        FROM schedule_templates st
        JOIN m_customer c ON c.id = st.customer_id
        JOIN p_user u ON u.id = st.technician_id
        WHERE {where}
        ORDER BY st.technician_id, st.day_of_week
        """,
        tuple(params) if params else None,
        user_id=uid,
    )

    # Generate entries
    entries = []
    current = month_start
    while current <= month_end:
        # Python weekday: 0=Monday, PG DOW: 0=Sunday
        # schedule_templates uses PG convention: 0=Sunday, 1=Monday...
        pg_dow = (current.weekday() + 1) % 7  # Convert Python to PG

        for t in templates:
            if t["day_of_week"] != pg_dow:
                continue

            # Handle frequency: WEEKLY = every week, BIWEEKLY = every other week, MONTHLY = first occurrence only
            freq = (t.get("frequency") or "WEEKLY").upper()
            if freq == "MONTHLY":
                # Only first occurrence in month
                week_num = (current.day - 1) // 7
                if week_num > 0:
                    continue
            elif freq == "BIWEEKLY":
                # Every other week (odd week numbers)
                week_num = current.isocalendar()[1]
                if week_num % 2 == 0:
                    continue

            entries.append({
                "template_id": t["template_id"],
                "technician_id": t["technician_id"],
                "tech_name": t["tech_name"],
                "customer_id": t["customer_id"],
                "customer_name": t["customer_name"],
                "visit_date": current.isoformat(),
                "visit_type": t["visit_type"],
                "contract_id": t["contract_id"],
                "day_name": current.strftime("%A"),
            })

        current += timedelta(days=1)

    # Check for existing road plans to avoid duplicates
    if not dry_run and entries:
        created = 0
        skipped = 0

        for e in entries:
            # Check if already exists
            existing = execute_kelava_query_single(
                """
                SELECT id FROM t_road_plan
                WHERE id_user = %s AND id_customer = %s
                  AND visit_date::date = %s
                  AND COALESCE(is_cancel, false) = false
                """,
                (e["technician_id"], e["customer_id"], e["visit_date"]),
                user_id=uid,
            )

            if existing:
                skipped += 1
                e["action"] = "SKIP_EXISTS"
                continue

            # Insert new road plan
            try:
                result = execute_kelava_query_single(
                    """
                    INSERT INTO t_road_plan
                        (id_user, id_customer, id_kontrak, visit_date, type, status, created_at)
                    VALUES (%s, %s, %s, %s::timestamp, %s, 'Baru', NOW())
                    RETURNING id
                    """,
                    (
                        e["technician_id"], e["customer_id"],
                        e.get("contract_id"),
                        e["visit_date"] + "T08:00:00",
                        e.get("visit_type", "REGULAR"),
                    ),
                    user_id=uid,
                )
                e["road_plan_id"] = result["id"] if result else None
                e["action"] = "CREATED"
                created += 1
            except Exception as ex:
                e["action"] = f"ERROR: {str(ex)[:80]}"
                skipped += 1

        return jsonify({
            "message": f"Generated {created} road plans, skipped {skipped} duplicates",
            "period": f"{month_start.isoformat()} to {month_end.isoformat()}",
            "created": created,
            "skipped": skipped,
            "entries": entries[:200],  # Limit response size
        })

    return jsonify({
        "message": f"Preview: {len(entries)} road plans would be generated",
        "period": f"{month_start.isoformat()} to {month_end.isoformat()}",
        "total_entries": len(entries),
        "dry_run": True,
        "entries": entries[:200],
    })


# ── Drag-and-Drop: Move Visit ────────────────────────────────


@schedule_gen_bp.route("/move", methods=["PUT"])
@require_auth
@require_role("admin", "koordinator")
def move_visit():
    """
    Move a road plan to a different date and/or technician (drag-and-drop).
    Writes a reschedule override to local DB — does NOT write to read-only Kelava.

    Body: {
        road_plan_id: int,
        new_date?: "YYYY-MM-DD",
        new_technician_id?: int,
        reason?: string
    }
    """
    data = request.json or {}
    uid = _auth_user_id()

    rp_id = data.get("road_plan_id")
    if not rp_id:
        return jsonify({"error": "road_plan_id required"}), 400

    new_date = data.get("new_date")
    new_tech = data.get("new_technician_id")
    reason = data.get("reason", "Dipindah via drag-and-drop")

    if not new_date and not new_tech:
        return jsonify({"error": "new_date or new_technician_id required"}), 400

    # Get current road plan from Kelava (read-only)
    current = execute_kelava_query_single(
        "SELECT id, visit_date, id_user, id_customer, id_kontrak, type, title, remarks FROM t_road_plan WHERE id = %s",
        (rp_id,),
        user_id=uid,
        cache_ttl=0,
    )
    if not current:
        return jsonify({"error": "Road plan not found"}), 404

    final_date = new_date or current["visit_date"].strftime("%Y-%m-%d")
    final_tech_id = int(new_tech) if new_tech else current["id_user"]
    created_by = int(uid) if uid else 0

    try:
        with _get_local_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO snc_road_plans
                        (kelava_road_plan_id, visit_date, p_user_id, customer_id,
                         kontrak_id, visit_type, title, remarks, created_by)
                    VALUES (%s, %s::timestamptz, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        rp_id, final_date + "T08:00:00", final_tech_id,
                        current["id_customer"], current.get("id_kontrak"),
                        current.get("type") or "visit", current.get("title"),
                        reason, created_by,
                    ),
                )
                new_row = cur.fetchone()
                new_plan_id = new_row["id"] if new_row else None

                cur.execute(
                    """
                    INSERT INTO snc_kelava_cancellations
                        (kelava_road_plan_id, reason, new_snc_road_plan_id, created_by)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (kelava_road_plan_id) DO UPDATE
                        SET reason = EXCLUDED.reason,
                            new_snc_road_plan_id = EXCLUDED.new_snc_road_plan_id,
                            created_at = NOW()
                    """,
                    (rp_id, reason, new_plan_id, created_by),
                )
    except Exception as exc:
        return jsonify({"error": f"Database error: {exc}"}), 500

    return jsonify({
        "message": "Visit moved",
        "road_plan_id": rp_id,
        "new_snc_road_plan_id": new_plan_id,
        "new_date": final_date,
        "new_technician_id": final_tech_id,
    })


# ── Swap Two Visits ───────────────────────────────────────────


@schedule_gen_bp.route("/swap", methods=["PUT"])
@require_auth
@require_role("admin", "koordinator")
def swap_visits():
    """
    Swap two road plans' technician assignments.
    Writes reschedule overrides to local DB — does NOT write to read-only Kelava.

    Body: { road_plan_id_1: int, road_plan_id_2: int }
    """
    data = request.json or {}
    uid = _auth_user_id()
    created_by = int(uid) if uid else 0

    id1 = data.get("road_plan_id_1")
    id2 = data.get("road_plan_id_2")
    if not id1 or not id2:
        return jsonify({"error": "road_plan_id_1 and road_plan_id_2 required"}), 400

    rp1 = execute_kelava_query_single(
        "SELECT id, visit_date, id_user, id_customer, id_kontrak, type, title, remarks FROM t_road_plan WHERE id = %s",
        (id1,), user_id=uid, cache_ttl=0,
    )
    rp2 = execute_kelava_query_single(
        "SELECT id, visit_date, id_user, id_customer, id_kontrak, type, title, remarks FROM t_road_plan WHERE id = %s",
        (id2,), user_id=uid, cache_ttl=0,
    )

    if not rp1 or not rp2:
        return jsonify({"error": "One or both road plans not found"}), 404

    reason = "Tukar teknisi via swap"

    def _insert_override(conn, cur, orig, new_tech_id):
        cur.execute(
            """
            INSERT INTO snc_road_plans
                (kelava_road_plan_id, visit_date, p_user_id, customer_id,
                 kontrak_id, visit_type, title, remarks, created_by)
            VALUES (%s, %s::timestamptz, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                orig["id"], orig["visit_date"].strftime("%Y-%m-%dT%H:%M:%S"),
                new_tech_id, orig["id_customer"], orig.get("id_kontrak"),
                orig.get("type") or "visit", orig.get("title"), reason, created_by,
            ),
        )
        row = cur.fetchone()
        new_id = row["id"] if row else None
        cur.execute(
            """
            INSERT INTO snc_kelava_cancellations
                (kelava_road_plan_id, reason, new_snc_road_plan_id, created_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (kelava_road_plan_id) DO UPDATE
                SET reason = EXCLUDED.reason,
                    new_snc_road_plan_id = EXCLUDED.new_snc_road_plan_id,
                    created_at = NOW()
            """,
            (orig["id"], reason, new_id, created_by),
        )
        return new_id

    try:
        with _get_local_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                new1 = _insert_override(conn, cur, rp1, rp2["id_user"])
                new2 = _insert_override(conn, cur, rp2, rp1["id_user"])
    except Exception as exc:
        return jsonify({"error": f"Database error: {exc}"}), 500

    return jsonify({
        "message": "Visits swapped",
        "swap": [
            {"road_plan_id": id1, "new_technician_id": rp2["id_user"], "new_snc_id": new1},
            {"road_plan_id": id2, "new_technician_id": rp1["id_user"], "new_snc_id": new2},
        ],
    })


# ── Schedule Gap Analysis ─────────────────────────────────────


@schedule_gen_bp.route("/gaps", methods=["GET"])
@require_auth
def schedule_gaps():
    """
    Find scheduling gaps: customers with active contracts but no visits scheduled.

    Query params: month (int), year (int)
    """
    uid = _auth_user_id()
    month = int(request.args.get("month", date.today().month))
    year = int(request.args.get("year", date.today().year))

    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)

    rows = execute_kelava_query(
        """
        SELECT
            c.id AS customer_id,
            c.name AS customer_name,
            c.address,
            ck.no_kontrak,
            ck.end_date AS contract_end,
            st.id AS template_id,
            u.fullname AS assigned_tech
        FROM m_customer c
        JOIN m_customer_kontrak ck ON ck.id_customer = c.id AND ck.is_active::text = 'true'
        LEFT JOIN schedule_templates st ON st.customer_id = c.id AND st.is_active = true
        LEFT JOIN p_user u ON u.id = st.technician_id
        WHERE NOT EXISTS (
            SELECT 1 FROM t_road_plan rp
            WHERE rp.id_customer = c.id
              AND rp.visit_date::date BETWEEN %s AND %s
              AND COALESCE(rp.is_cancel, false) = false
        )
        ORDER BY c.name
        """,
        (month_start, month_end),
        user_id=uid,
    )

    return jsonify({
        "period": f"{month_start.isoformat()} to {month_end.isoformat()}",
        "gaps": [_fmt(r) for r in rows],
        "total_gaps": len(rows),
    })
