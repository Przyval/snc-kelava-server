"""
Schedule Template API (Plants vs Zombies)
==========================================
Template-based scheduling system for recurring visit patterns.
Zombies = Technicians, Plants = Clients.

Meeting notes:
- 100% klien punya template jadwal
- Template dari operasional, bisa per bulan bahkan per tahun
- Marketing tentukan jumlah kunjungan (dari kontrak)
- Operasional tentukan jadwal jam
- Drag-and-drop assignment (UI side)
- Unassigned clients shown on sidebar
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

scheduling_bp = Blueprint("scheduling", __name__, url_prefix="/scheduling")

DAYS_OF_WEEK = {0: "Minggu", 1: "Senin", 2: "Selasa", 3: "Rabu", 4: "Kamis", 5: "Jumat", 6: "Sabtu"}


def _fmt(row):
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _auth_user_id():
    user = getattr(g, "user", None)
    return str(user.id) if user else None


# ── Template CRUD ───────────────────────────────────────────


@scheduling_bp.route("/templates", methods=["GET"])
@require_auth
def list_templates():
    """
    List all schedule templates with filters.

    Query params:
        technician_id: Filter by technician
        customer_id: Filter by customer
        day_of_week: Filter by day (0-6)
        active_only: true (default) to show only active templates
    """
    uid = _auth_user_id()
    tech_id = request.args.get("technician_id")
    cust_id = request.args.get("customer_id")
    dow = request.args.get("day_of_week")
    active_only = request.args.get("active_only", "true").lower() == "true"

    where_clauses = []
    params = []

    if active_only:
        where_clauses.append("st.is_active = true")

    if tech_id:
        where_clauses.append("st.technician_id = %s")
        params.append(int(tech_id))

    if cust_id:
        where_clauses.append("st.customer_id = %s")
        params.append(int(cust_id))

    if dow is not None:
        where_clauses.append("st.day_of_week = %s")
        params.append(int(dow))

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    rows = execute_kelava_query(
        f"""
        SELECT
            st.id,
            st.customer_id,
            c.name as customer_name,
            st.technician_id,
            u.fullname as technician_name,
            st.day_of_week,
            st.scheduled_time,
            st.visit_type,
            st.frequency,
            st.shift,
            st.duration_estimate,
            st.is_active,
            st.source,
            st.notes
        FROM schedule_templates st
        JOIN m_customer c ON c.id = st.customer_id
        LEFT JOIN p_user u ON u.id = st.technician_id
        WHERE {where_sql}
        ORDER BY st.day_of_week, st.scheduled_time, c.name
        """,
        tuple(params) if params else None,
        user_id=uid,
    )

    # Enrich with day names
    results = []
    for r in rows:
        item = _fmt(r)
        item["day_name"] = DAYS_OF_WEEK.get(r["day_of_week"], "?")
        results.append(item)

    return jsonify({
        "templates": results,
        "total": len(results),
        "generated_at": datetime.now().isoformat(),
    })


@scheduling_bp.route("/templates", methods=["POST"])
@require_auth
def create_template():
    """
    Create a new schedule template.

    Body: {
        customer_id: int,
        technician_id?: int,
        day_of_week: 0-6,
        scheduled_time: "HH:MM",
        visit_type?: "REGULAR"|"MAINTENANCE"|"INSPECTION",
        frequency?: "WEEKLY"|"BIWEEKLY"|"MONTHLY",
        shift?: "PAGI"|"SORE"|"MALAM",
        duration_estimate?: int (minutes),
        contract_id?: int,
        notes?: string
    }
    """
    data = request.json or {}
    uid = _auth_user_id()

    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"error": "customer_id is required"}), 400

    dow = data.get("day_of_week")
    if dow is None or not (0 <= int(dow) <= 6):
        return jsonify({"error": "day_of_week must be 0-6"}), 400

    sched_time = data.get("scheduled_time")
    if not sched_time:
        return jsonify({"error": "scheduled_time is required (HH:MM format)"}), 400

    result = execute_kelava_query_single(
        """
        INSERT INTO schedule_templates
            (customer_id, technician_id, day_of_week, scheduled_time, visit_type,
             frequency, shift, duration_estimate, contract_id, notes, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'MANUAL')
        RETURNING *
        """,
        (
            customer_id,
            data.get("technician_id"),
            int(dow),
            sched_time,
            data.get("visit_type", "REGULAR"),
            data.get("frequency", "WEEKLY"),
            data.get("shift", "PAGI"),
            data.get("duration_estimate", 60),
            data.get("contract_id"),
            data.get("notes", ""),
        ),
        user_id=uid,
    )

    return jsonify({
        "message": "Template created",
        "template": _fmt(result) if result else {},
    }), 201


@scheduling_bp.route("/templates/<int:template_id>", methods=["PATCH"])
@require_auth
def update_template(template_id: int):
    """Update a schedule template."""
    data = request.json or {}
    uid = _auth_user_id()

    # Build SET clauses dynamically
    allowed_fields = {
        "technician_id", "day_of_week", "scheduled_time", "visit_type",
        "frequency", "shift", "duration_estimate", "is_active", "notes",
    }

    set_parts = []
    params = []
    for field in allowed_fields:
        if field in data:
            set_parts.append(f"{field} = %s")
            params.append(data[field])

    if not set_parts:
        return jsonify({"error": "No fields to update"}), 400

    set_parts.append("updated_at = NOW()")
    params.append(template_id)

    result = execute_kelava_query_single(
        f"""
        UPDATE schedule_templates
        SET {', '.join(set_parts)}
        WHERE id = %s
        RETURNING *
        """,
        tuple(params),
        user_id=uid,
    )

    if not result:
        return jsonify({"error": "Template not found"}), 404

    return jsonify({"message": "Template updated", "template": _fmt(result)})


@scheduling_bp.route("/templates/<int:template_id>", methods=["DELETE"])
@require_auth
def deactivate_template(template_id: int):
    """Deactivate (soft-delete) a schedule template."""
    uid = _auth_user_id()

    result = execute_kelava_query_single(
        """
        UPDATE schedule_templates
        SET is_active = false, updated_at = NOW()
        WHERE id = %s
        RETURNING id
        """,
        (template_id,), user_id=uid,
    )

    if not result:
        return jsonify({"error": "Template not found"}), 404

    return jsonify({"message": "Template deactivated", "id": template_id})


# ── Assignment Board (Plants vs Zombies view) ──────────────


@scheduling_bp.route("/board", methods=["GET"])
@require_auth
def assignment_board():
    """
    The "Plants vs Zombies" scheduling board.
    Shows technicians as rows, days as columns, with assigned/unassigned clients.

    Query params:
        start_date: YYYY-MM-DD (default: Monday of current week)
        days: number of days (default: 7)
    """
    uid = _auth_user_id()
    start = request.args.get("start_date")
    days_count = int(request.args.get("days", 7))

    if not start:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        start = monday.isoformat()

    start_dt = date.fromisoformat(start)
    end_dt = start_dt + timedelta(days=days_count - 1)

    # Get all templates for the date range
    templates = execute_kelava_query(
        """
        SELECT
            st.id as template_id,
            st.customer_id,
            c.name as customer_name,
            st.technician_id,
            u.fullname as technician_name,
            st.day_of_week,
            st.scheduled_time,
            st.visit_type,
            st.frequency,
            st.shift,
            st.duration_estimate
        FROM schedule_templates st
        JOIN m_customer c ON c.id = st.customer_id
        LEFT JOIN p_user u ON u.id = st.technician_id
        WHERE st.is_active = true
        ORDER BY st.technician_id, st.day_of_week, st.scheduled_time
        """,
        user_id=uid,
    )

    # Get actual road plans for the period (to show what's actually scheduled)
    actuals = execute_kelava_query(
        """
        SELECT
            rp.id as road_plan_id,
            rp.id_user as technician_id,
            rp.id_customer as customer_id,
            c.name as customer_name,
            rp.visit_date,
            rp.status,
            v.check_in,
            v.check_out
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.visit_date::date BETWEEN %s AND %s
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY rp.id_user, rp.visit_date
        """,
        (start_dt, end_dt),
        user_id=uid,
    )

    # Build the board
    # Rows = technicians, Columns = dates
    tech_map = {}

    # From templates
    for t in templates:
        tid = t["technician_id"]
        if tid and tid not in tech_map:
            tech_map[tid] = {
                "id": tid,
                "name": t["technician_name"],
                "slots": {},
            }

    # From actuals
    for a in actuals:
        tid = a["technician_id"]
        if tid not in tech_map:
            tech_map[tid] = {
                "id": tid,
                "name": None,  # will be filled
                "slots": {},
            }

        d = a["visit_date"].isoformat() if hasattr(a["visit_date"], "isoformat") else str(a["visit_date"])
        if d not in tech_map[tid]["slots"]:
            tech_map[tid]["slots"][d] = []

        tech_map[tid]["slots"][d].append({
            "road_plan_id": a["road_plan_id"],
            "customer_id": a["customer_id"],
            "customer_name": a["customer_name"],
            "status": a["status"],
            "check_in": a["check_in"].isoformat() if a.get("check_in") else None,
            "check_out": a["check_out"].isoformat() if a.get("check_out") else None,
            "source": "ACTUAL",
        })

    # Add template-based slots (for future dates without actuals)
    for t in templates:
        tid = t["technician_id"]
        if not tid:
            continue

        current = start_dt
        while current <= end_dt:
            if current.weekday() == (t["day_of_week"] - 1) % 7:  # Convert to Python weekday
                d = current.isoformat()
                if d not in tech_map.get(tid, {}).get("slots", {}):
                    if tid not in tech_map:
                        tech_map[tid] = {"id": tid, "name": t["technician_name"], "slots": {}}
                    if d not in tech_map[tid]["slots"]:
                        tech_map[tid]["slots"][d] = []

                    # Check if this customer already has an actual for this day
                    existing = [s for s in tech_map[tid]["slots"][d]
                                if s.get("customer_id") == t["customer_id"]]
                    if not existing:
                        tech_map[tid]["slots"][d].append({
                            "template_id": t["template_id"],
                            "customer_id": t["customer_id"],
                            "customer_name": t["customer_name"],
                            "scheduled_time": str(t["scheduled_time"]),
                            "visit_type": t["visit_type"],
                            "source": "TEMPLATE",
                        })
            current += timedelta(days=1)

    # Unassigned clients (templates without technician)
    unassigned = [
        _fmt(t) for t in templates if not t["technician_id"]
    ]

    # Generate date headers
    dates = []
    current = start_dt
    while current <= end_dt:
        dates.append({
            "date": current.isoformat(),
            "day_name": DAYS_OF_WEEK.get(current.isoweekday() % 7, "?"),
            "is_today": current == date.today(),
        })
        current += timedelta(days=1)

    return jsonify({
        "period": {"start_date": start, "end_date": end_dt.isoformat()},
        "dates": dates,
        "technicians": list(tech_map.values()),
        "unassigned_clients": unassigned,
        "summary": {
            "total_technicians": len(tech_map),
            "unassigned_count": len(unassigned),
        },
        "generated_at": datetime.now().isoformat(),
    })


# ── Assign technician to template ──────────────────────────


@scheduling_bp.route("/assign", methods=["POST"])
@require_auth
def assign_technician():
    """
    Assign a technician to a schedule template (drag-and-drop).

    Body: { template_id: int, technician_id: int }
    """
    data = request.json or {}
    uid = _auth_user_id()

    template_id = data.get("template_id")
    tech_id = data.get("technician_id")

    if not template_id or not tech_id:
        return jsonify({"error": "template_id and technician_id required"}), 400

    result = execute_kelava_query_single(
        """
        UPDATE schedule_templates
        SET technician_id = %s, updated_at = NOW()
        WHERE id = %s
        RETURNING *
        """,
        (tech_id, template_id),
        user_id=uid,
    )

    if not result:
        return jsonify({"error": "Template not found"}), 404

    return jsonify({
        "message": "Technician assigned",
        "template": _fmt(result),
    })


# ── Technician list (for dropdowns) ──────────────────────


@scheduling_bp.route("/technicians-list", methods=["GET"])
@require_auth
def technicians_list():
    """Simple technician list for dropdowns (id + name + segment)."""
    uid = _auth_user_id()
    rows = execute_kelava_query(
        """
        SELECT u.id, u.fullname as name,
               COALESCE(ts.segment, 'UNASSIGNED') as segment
        FROM p_user u
        LEFT JOIN technician_segments ts ON ts.technician_id = u.id
        WHERE COALESCE(u.is_deleted, false) = false
          AND u.id_client = 111
        ORDER BY u.fullname
        """,
        user_id=uid,
    )
    return jsonify({"technicians": [_fmt(r) for r in rows]})


# ── Auto-assign (load-balanced) ──────────────────────────


@scheduling_bp.route("/auto-assign", methods=["POST"])
@require_auth
def auto_assign():
    """
    Auto-assign unassigned templates to technicians using load balancing.

    Algorithm:
    1. Get all unassigned templates (technician_id IS NULL)
    2. Get all active technicians with current load per day
    3. For each unassigned template, assign to the tech with least load on that day
    4. Optionally filter by segment

    Body: {
        max_per_day?: int (default: 6, max visits per technician per day),
        segment_filter?: string (only assign to technicians in this segment),
        dry_run?: bool (default: false, preview without saving)
    }
    """
    data = request.json or {}
    uid = _auth_user_id()
    max_per_day = data.get("max_per_day", 6)
    segment_filter = data.get("segment_filter")
    dry_run = data.get("dry_run", False)

    # 1. Get unassigned templates
    unassigned = execute_kelava_query(
        """
        SELECT st.id, st.customer_id, c.name as customer_name,
               st.day_of_week, st.scheduled_time, st.duration_estimate
        FROM schedule_templates st
        JOIN m_customer c ON c.id = st.customer_id
        WHERE st.is_active = true AND st.technician_id IS NULL
        ORDER BY st.day_of_week, st.scheduled_time
        """,
        user_id=uid,
    )

    if not unassigned:
        return jsonify({"message": "No unassigned templates", "assigned": 0, "assignments": []})

    # 2. Get technicians with segment filter
    tech_where = "COALESCE(u.is_deleted, false) = false AND u.id_client = 111"
    tech_params = []
    if segment_filter:
        tech_where += " AND ts.segment = %s"
        tech_params.append(segment_filter)

    technicians = execute_kelava_query(
        f"""
        SELECT u.id, u.fullname as name,
               COALESCE(ts.segment, 'UNASSIGNED') as segment
        FROM p_user u
        LEFT JOIN technician_segments ts ON ts.technician_id = u.id
        WHERE {tech_where}
        ORDER BY u.fullname
        """,
        tuple(tech_params) if tech_params else None,
        user_id=uid,
    )

    if not technicians:
        return jsonify({"error": "No technicians available for assignment"}), 400

    # 3. Build current load map: tech_id -> { day_of_week: count }
    current_load = execute_kelava_query(
        """
        SELECT technician_id, day_of_week, COUNT(*) as slot_count
        FROM schedule_templates
        WHERE is_active = true AND technician_id IS NOT NULL
        GROUP BY technician_id, day_of_week
        """,
        user_id=uid,
    )

    load_map = {}  # tech_id -> { dow: count }
    for row in current_load:
        tid = row["technician_id"]
        dow = row["day_of_week"]
        if tid not in load_map:
            load_map[tid] = {}
        load_map[tid][dow] = row["slot_count"]

    # 4. Assign each unassigned template to least-loaded technician
    assignments = []
    tech_ids = [t["id"] for t in technicians]
    tech_names = {t["id"]: t["name"] for t in technicians}

    for tmpl in unassigned:
        dow = tmpl["day_of_week"]

        # Find technician with lowest load on this day
        best_tech = None
        best_load = 999

        for tid in tech_ids:
            day_load = load_map.get(tid, {}).get(dow, 0)
            if day_load < max_per_day and day_load < best_load:
                best_load = day_load
                best_tech = tid

        if best_tech is None:
            continue  # All technicians full on this day

        # Assign
        if not dry_run:
            execute_kelava_query_single(
                """
                UPDATE schedule_templates
                SET technician_id = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id
                """,
                (best_tech, tmpl["id"]),
                user_id=uid,
            )

        # Update load map
        if best_tech not in load_map:
            load_map[best_tech] = {}
        load_map[best_tech][dow] = load_map[best_tech].get(dow, 0) + 1

        assignments.append({
            "template_id": tmpl["id"],
            "customer_name": tmpl["customer_name"],
            "day_of_week": dow,
            "day_name": DAYS_OF_WEEK.get(dow, "?"),
            "technician_id": best_tech,
            "technician_name": tech_names.get(best_tech, "?"),
            "day_load_after": load_map[best_tech][dow],
        })

    return jsonify({
        "message": f"{'Would assign' if dry_run else 'Assigned'} {len(assignments)} templates",
        "assigned": len(assignments),
        "unassigned_remaining": len(unassigned) - len(assignments),
        "dry_run": dry_run,
        "assignments": assignments,
    })


# ── Pattern Detection ───────────────────────────────────────


@scheduling_bp.route("/detect-patterns", methods=["POST"])
@require_auth
def detect_patterns():
    """
    AI-powered pattern detection from historical visit data.
    Reads check-in patterns and creates template suggestions.

    Body: { months_back: int (default: 3), min_occurrences: int (default: 3) }
    """
    data = request.json or {}
    uid = _auth_user_id()
    months = data.get("months_back", 3)
    min_occ = data.get("min_occurrences", 3)

    patterns = execute_kelava_query(
        """
        WITH visit_patterns AS (
            SELECT
                rp.id_user as technician_id,
                rp.id_customer as customer_id,
                EXTRACT(DOW FROM v.realization_date) as day_of_week,
                DATE_TRUNC('hour', v.check_in)::time as approx_time,
                COUNT(*) as occurrence_count
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE v.realization_date >= CURRENT_DATE - make_interval(months => %s)
              AND v.check_in IS NOT NULL
            GROUP BY rp.id_user, rp.id_customer, EXTRACT(DOW FROM v.realization_date),
                     DATE_TRUNC('hour', v.check_in)::time
            HAVING COUNT(*) >= %s
        )
        SELECT
            vp.technician_id,
            u.fullname as technician_name,
            vp.customer_id,
            c.name as customer_name,
            vp.day_of_week::int,
            vp.approx_time as suggested_time,
            vp.occurrence_count,
            -- Check if template already exists
            EXISTS(
                SELECT 1 FROM schedule_templates st
                WHERE st.customer_id = vp.customer_id
                  AND st.technician_id = vp.technician_id
                  AND st.day_of_week = vp.day_of_week
                  AND st.is_active = true
            ) as template_exists
        FROM visit_patterns vp
        JOIN p_user u ON u.id = vp.technician_id
        JOIN m_customer c ON c.id = vp.customer_id
        ORDER BY vp.occurrence_count DESC
        """,
        (months, min_occ),
        user_id=uid,
    )

    # Separate new suggestions from existing templates
    suggestions = []
    already_exists = []
    for p in patterns:
        item = _fmt(p)
        item["day_name"] = DAYS_OF_WEEK.get(p["day_of_week"], "?")
        if p["template_exists"]:
            already_exists.append(item)
        else:
            suggestions.append(item)

    return jsonify({
        "parameters": {"months_back": months, "min_occurrences": min_occ},
        "new_suggestions": suggestions,
        "already_templated": already_exists,
        "total_patterns": len(patterns),
        "generated_at": datetime.now().isoformat(),
    })


@scheduling_bp.route("/apply-patterns", methods=["POST"])
@require_auth
def apply_patterns():
    """
    Create templates from detected patterns.

    Body: {
        patterns: [
            { customer_id, technician_id, day_of_week, scheduled_time },
            ...
        ]
    }
    """
    data = request.json or {}
    uid = _auth_user_id()
    patterns = data.get("patterns", [])

    created = 0
    skipped = 0

    for p in patterns:
        # Check if template already exists
        existing = execute_kelava_query_single(
            """
            SELECT id FROM schedule_templates
            WHERE customer_id = %s AND technician_id = %s
              AND day_of_week = %s AND is_active = true
            """,
            (p["customer_id"], p["technician_id"], p["day_of_week"]),
            user_id=uid,
        )

        if existing:
            skipped += 1
            continue

        execute_kelava_query(
            """
            INSERT INTO schedule_templates
                (customer_id, technician_id, day_of_week, scheduled_time, source)
            VALUES (%s, %s, %s, %s, 'PATTERN_DETECTED')
            """,
            (p["customer_id"], p["technician_id"], p["day_of_week"], p["scheduled_time"]),
            user_id=uid,
        )
        created += 1

    return jsonify({
        "message": f"Created {created} templates, skipped {skipped} duplicates",
        "created": created,
        "skipped": skipped,
    })
