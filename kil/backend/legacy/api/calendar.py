"""
Resource Calendar API - Dispatch View

Provides endpoints for:
- Weekly/daily schedule grid (technician × time)
- Available slots per technician
- Reschedule with audit trail
- Lock schedule for SPV approval
"""

from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import _get_local_pool, execute_kelava_query, execute_kelava_query_single
from psycopg.rows import dict_row

calendar_bp = Blueprint("calendar", __name__, url_prefix="/api/v1/enterprise")


def _duration_min(time_start, time_end):
    """Return estimated duration in minutes from 'HH:MM' strings. Handles midnight crossing."""
    try:
        if not time_start or not time_end:
            return 60
        h1, m1 = int(time_start[:2]), int(time_start[3:5])
        h2, m2 = int(time_end[:2]), int(time_end[3:5])
        mins = (h2 * 60 + m2) - (h1 * 60 + m1)
        if mins <= 0:
            mins += 24 * 60  # midnight crossing
        return max(30, min(mins, 480))
    except Exception:
        return 60


@calendar_bp.route("/calendar/schedule")
@require_auth
def calendar_schedule():
    """
    Get weekly schedule grid: technicians × time slots.
    Returns jobs positioned on a grid for dispatch calendar view.

    Query params:
    - start_date: YYYY-MM-DD (default: today)
    - end_date: YYYY-MM-DD (default: start + 6 days)
    """
    start_date = request.args.get("start_date", datetime.now().strftime("%Y-%m-%d"))
    end_date = request.args.get(
        "end_date",
        (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=6)).strftime(
            "%Y-%m-%d"
        ),
    )

    # Get all technicians with jobs in this period
    technicians = execute_kelava_query(
        """
        SELECT DISTINCT
            u.id,
            u.fullname as name,
            u.email,
            COALESCE(u.phone, '') as phone
        FROM p_user u
        JOIN t_road_plan rp ON rp.id_user = u.id
        WHERE rp.visit_date::date BETWEEN %s AND %s
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY u.fullname
    """,
        (start_date, end_date),
    )

    # Get all jobs for this period
    jobs = execute_kelava_query(
        """
        SELECT 
            rp.id,
            rp.id_user,
            rp.id_customer,
            c.name as customer_name,
            c.address as customer_address,
            rp.visit_date,
            rp.status,
            rp.remarks as notes,
            rp.type,
            COALESCE(rp.is_cancel, false) as is_cancelled,
            -- Check if has visit record
            CASE WHEN v.id IS NOT NULL THEN true ELSE false END as has_visit,
            v.check_in,
            v.check_out,
            -- Use check_in time for scheduling display
            v.check_in::time as actual_start_time,
            -- Duration in minutes if completed
            CASE 
                WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL 
                THEN ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)
                ELSE NULL 
            END as actual_duration_min
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.visit_date::date BETWEEN %s AND %s
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY rp.visit_date, v.check_in NULLS LAST
    """,
        (start_date, end_date),
    )

    # Build grid structure
    tech_map = {
        t["id"]: {
            "id": t["id"],
            "name": t["name"],
            "email": t["email"],
            "phone": t["phone"],
            "jobs": [],
        }
        for t in technicians
    }

    for job in jobs:
        tech_id = job["id_user"]
        if tech_id in tech_map:
            # Determine job status color
            status = job["status"] or "Baru"
            if job["is_cancelled"]:
                color = "gray"
            elif status == "Selesai":
                color = "green"
            elif status == "Berjalan":
                color = "blue"
            elif job["check_in"] and not job["check_out"]:
                color = "orange"  # In progress but not checked out
            else:
                color = "slate"  # Pending

            tech_map[tech_id]["jobs"].append(
                {
                    "id": job["id"],
                    "customer_id": job["id_customer"],
                    "customer_name": job["customer_name"],
                    "customer_address": job["customer_address"],
                    "date": job["visit_date"].strftime("%Y-%m-%d")
                    if job["visit_date"]
                    else None,
                    "time_start": job["actual_start_time"].strftime("%H:%M")
                    if job.get("actual_start_time")
                    else "08:00",
                    "time_end": "",  # No scheduled end time in schema
                    "job_type": job.get("type", "VISIT"),
                    "status": status,
                    "color": color,
                    "has_visit": job["has_visit"],
                    "check_in": job["check_in"].isoformat()
                    if job["check_in"]
                    else None,
                    "check_out": job["check_out"].isoformat()
                    if job["check_out"]
                    else None,
                    "actual_duration_min": job["actual_duration_min"],
                    # Phase 12: Operational Dispatch Fields
                    "estimated_duration": 120
                    if str(job.get("type", "")).upper() == "MAINTENANCE"
                    else 60,
                    "is_overrun": (
                        datetime.now().astimezone()
                        - (
                            job["check_in"]
                            if isinstance(job["check_in"], datetime)
                            else datetime.fromisoformat(
                                str(job["check_in"])
                            ).astimezone()
                        )
                    ).total_seconds()
                    / 60
                    > 90
                    if job["check_in"] and not job["check_out"]
                    else False,
                }
            )

    # Phase 12: Workload Calculation
    for tech in tech_map.values():
        job_count = len(tech["jobs"])
        if job_count > 6:
            tech["workload_status"] = "OVERLOAD"  # Red
        elif job_count >= 4:
            tech["workload_status"] = "HIGH"  # Yellow
        else:
            tech["workload_status"] = "OPTIMAL"  # Green

    # Generate date range for calendar header
    dates = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    while current <= end:
        dates.append(
            {
                "date": current.strftime("%Y-%m-%d"),
                "day_name": current.strftime("%A"),
                "day_short": current.strftime("%a"),
                "is_today": current.date() == datetime.now().date(),
            }
        )
        current += timedelta(days=1)

    # Apply reschedule overrides from local DB
    cancelled_ids: set = set()
    if jobs:
        rp_ids = [j["id"] for j in jobs]
        placeholders = ",".join(str(i) for i in rp_ids)
        try:
            with _get_local_pool().connection() as _conn:
                with _conn.cursor(row_factory=dict_row) as _cur:
                    _cur.execute(
                        f"SELECT kelava_road_plan_id FROM snc_kelava_cancellations WHERE kelava_road_plan_id = ANY(ARRAY[{placeholders}])"
                    )
                    for row in _cur.fetchall():
                        cancelled_ids.add(row["kelava_road_plan_id"])
        except Exception:
            pass

        # Remove cancelled jobs from tech_map
        if cancelled_ids:
            for tech in tech_map.values():
                tech["jobs"] = [j for j in tech["jobs"] if j["id"] not in cancelled_ids]

    # Fetch rescheduled snc_road_plans for this period and merge into grid
    snc_jobs = []
    try:
        with _get_local_pool().connection() as _conn:
            with _conn.cursor(row_factory=dict_row) as _cur:
                _cur.execute(
                    """
                    SELECT id, p_user_id AS id_user, customer_id AS id_customer,
                           COALESCE(customer_name, '') AS snc_customer_name,
                           visit_date, status, visit_type AS type,
                           time_start, time_end, service_type,
                           kelava_road_plan_id, remarks AS notes, is_cancel
                    FROM snc_road_plans
                    WHERE visit_date::date BETWEEN %s AND %s
                      AND is_cancel = false
                    """,
                    (start_date, end_date),
                )
                snc_jobs = _cur.fetchall()

        # Enrich with customer names from Kelava for jobs that have customer_id
        if snc_jobs:
            kelava_ids = list({j["id_customer"] for j in snc_jobs if j["id_customer"]})
            cust_map = {}
            if kelava_ids:
                cust_ids_sql = ",".join(str(i) for i in kelava_ids)
                cust_rows = execute_kelava_query(
                    f"SELECT id, name, address FROM m_customer WHERE id = ANY(ARRAY[{cust_ids_sql}])"
                )
                cust_map = {c["id"]: c for c in cust_rows}
            enriched = []
            for j in snc_jobs:
                if j["id_customer"] and j["id_customer"] in cust_map:
                    name = cust_map[j["id_customer"]]["name"]
                    addr = cust_map[j["id_customer"]].get("address")
                else:
                    name = j.get("snc_customer_name") or "—"
                    addr = None
                enriched.append({**j, "customer_name": name, "customer_address": addr})
            snc_jobs = enriched
    except Exception:
        snc_jobs = []

    # Ensure technicians for snc_jobs are in tech_map
    for snc_job in snc_jobs:
        tech_id = snc_job["id_user"]
        if tech_id not in tech_map:
            # Fetch technician info from Kelava
            tech_info = execute_kelava_query_single(
                "SELECT id, fullname AS name, email, COALESCE(phone, '') AS phone FROM p_user WHERE id = %s",
                (tech_id,),
            )
            if tech_info:
                tech_map[tech_id] = {
                    "id": tech_info["id"],
                    "name": tech_info["name"],
                    "email": tech_info["email"],
                    "phone": tech_info["phone"],
                    "jobs": [],
                    "workload_status": "OPTIMAL",
                }

        status = snc_job.get("status") or "Baru"
        color = "green" if status == "Selesai" else ("blue" if status == "Berjalan" else "slate")
        if tech_id in tech_map:
            tech_map[tech_id]["jobs"].append({
                "id": f"snc-{snc_job['id']}",
                "customer_id": snc_job["id_customer"],
                "customer_name": snc_job["customer_name"],
                "customer_address": snc_job.get("customer_address"),
                "date": snc_job["visit_date"].strftime("%Y-%m-%d") if snc_job["visit_date"] else None,
                "time_start": snc_job.get("time_start") or "08:00",
                "time_end": snc_job.get("time_end") or "",
                "job_type": snc_job.get("service_type") or snc_job.get("type") or "VISIT",
                "status": status,
                "color": color,
                "has_visit": False,
                "check_in": None,
                "check_out": None,
                "actual_duration_min": None,
                "estimated_duration": _duration_min(snc_job.get("time_start"), snc_job.get("time_end")),
                "is_overrun": False,
                "is_rescheduled": bool(snc_job.get("kelava_road_plan_id")),
                "kelava_road_plan_id": snc_job.get("kelava_road_plan_id"),
            })

    # ── SSOT: snc_schedule_events ────────────────────────────────────────────
    # Fetch scheduled/draft events from the SSOT table (imported from Excel or
    # generated by the auto-draft engine). These are keyed by snc_technicians
    # which carry kelava_p_user_id for merging into the existing tech_map.
    try:
        with _get_local_pool().connection() as _conn:
            with _conn.cursor(row_factory=dict_row) as _cur:
                _cur.execute(
                    """
                    SELECT
                        se.id,
                        se.technician_id,
                        se.client_id,
                        se.visit_type,
                        se.start_datetime,
                        se.end_datetime,
                        se.start_date,
                        se.schedule_status,
                        se.notes,
                        st.name  AS tech_name,
                        st.kelava_p_user_id,
                        sc.name  AS client_name
                    FROM snc_schedule_events se
                    JOIN snc_technicians st ON st.id = se.technician_id
                    JOIN snc_clients     sc ON sc.id = se.client_id
                    WHERE se.start_date BETWEEN %s AND %s
                      AND se.schedule_status IN ('scheduled', 'draft', 'completed')
                    ORDER BY se.start_datetime
                    """,
                    (start_date, end_date),
                )
                ssot_events = _cur.fetchall()

        for ev in ssot_events:
            # Map to Kelava p_user_id if available, otherwise use synthetic key
            kpid = ev["kelava_p_user_id"]
            map_key = kpid if kpid else f"snc-tech-{ev['technician_id']}"

            if map_key not in tech_map:
                tech_map[map_key] = {
                    "id": map_key,
                    "name": ev["tech_name"],
                    "email": "",
                    "phone": "",
                    "jobs": [],
                    "workload_status": "OPTIMAL",
                }

            ts = ev["start_datetime"]
            te = ev["end_datetime"]
            status_map = {
                "draft": "draft",
                "scheduled": "Baru",
                "completed": "Selesai",
                "cancelled": "Dibatalkan",
            }
            ev_status = status_map.get(ev["schedule_status"], "Baru")
            color = "indigo" if ev["schedule_status"] == "draft" else (
                "green" if ev["schedule_status"] == "completed" else "slate"
            )

            tech_map[map_key]["jobs"].append({
                "id": f"ssot-{ev['id']}",
                "customer_id": None,
                "customer_name": ev["client_name"],
                "customer_address": None,
                "date": ev["start_date"].strftime("%Y-%m-%d") if ev["start_date"] else None,
                "time_start": ts.strftime("%H:%M") if ts else "08:00",
                "time_end": te.strftime("%H:%M") if te else "",
                "job_type": ev["visit_type"] or "VISIT",
                "status": ev_status,
                "color": color,
                "has_visit": ev["schedule_status"] == "completed",
                "check_in": None,
                "check_out": None,
                "actual_duration_min": None,
                "estimated_duration": _duration_min(
                    ts.strftime("%H:%M") if ts else None,
                    te.strftime("%H:%M") if te else None,
                ),
                "is_overrun": False,
                "is_rescheduled": False,
                "is_draft": ev["schedule_status"] == "draft",
                "ssot_event_id": ev["id"],
                "notes": ev["notes"],
            })
    except Exception:
        pass
    # ── End SSOT merge ───────────────────────────────────────────────────────

    # Recalculate workload after merges
    for tech in tech_map.values():
        job_count = len(tech["jobs"])
        if job_count > 6:
            tech["workload_status"] = "OVERLOAD"
        elif job_count >= 4:
            tech["workload_status"] = "HIGH"
        else:
            tech["workload_status"] = "OPTIMAL"

    return jsonify(
        {
            "period": {
                "start_date": start_date,
                "end_date": end_date,
            },
            "dates": dates,
            "technicians": list(tech_map.values()),
            "summary": {
                "total_technicians": len(tech_map),
                "total_jobs": sum(len(t["jobs"]) for t in tech_map.values()),
            },
            "generated_at": datetime.now().isoformat(),
        }
    )


@calendar_bp.route("/calendar/technician/<int:tech_id>/slots")
@require_auth
def technician_slots(tech_id):
    """
    Get available slots for a specific technician.
    Used when assigning new jobs or rescheduling.

    Query params:
    - date: YYYY-MM-DD (default: today)
    - days: number of days to check (default: 7)
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    days = int(request.args.get("days", 7))
    end_date = (
        datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days - 1)
    ).strftime("%Y-%m-%d")

    # Get technician info
    tech = execute_kelava_query_single(
        """
        SELECT id, fullname as name, email
        FROM p_user WHERE id = %s
    """,
        (tech_id,),
    )

    if not tech:
        return jsonify({"error": "Technician not found"}), 404

    # Get existing jobs for this technician
    existing_jobs = execute_kelava_query(
        """
        SELECT 
            rp.visit_date,
            v.check_in::time as start_time,
            c.name as customer_name
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_user = %s
          AND rp.visit_date::date BETWEEN %s AND %s
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY rp.visit_date
    """,
        (tech_id, date, end_date),
    )

    # Build occupied slots by date (simplified - just count jobs per day)
    jobs_by_date = {}
    for job in existing_jobs:
        d = job["visit_date"].strftime("%Y-%m-%d")
        if d not in jobs_by_date:
            jobs_by_date[d] = []
        jobs_by_date[d].append(
            {
                "customer": job["customer_name"],
                "start": job["start_time"].strftime("%H:%M")
                if job.get("start_time")
                else None,
            }
        )

    # Simplified slot availability (count-based, not time-based)
    slots_by_date = []
    current = datetime.strptime(date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    max_jobs_per_day = 5  # Typical max capacity

    while current <= end:
        d = current.strftime("%Y-%m-%d")
        jobs_today = jobs_by_date.get(d, [])
        available = max_jobs_per_day - len(jobs_today)

        slots_by_date.append(
            {
                "date": d,
                "day_name": current.strftime("%A"),
                "is_weekend": current.weekday() >= 5,
                "jobs_scheduled": len(jobs_today),
                "slots_available": max(0, available),
                "is_full": available <= 0,
                "jobs": jobs_today,
            }
        )

        current += timedelta(days=1)

    return jsonify(
        {
            "technician": tech,
            "period": {"start": date, "end": end_date},
            "schedule": slots_by_date,
            "generated_at": datetime.now().isoformat(),
        }
    )


@calendar_bp.route("/calendar/conflicts")
@require_auth
def calendar_conflicts():
    """
    Detect scheduling conflicts (double bookings, overload).
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    # Since t_road_plan doesn't have time_start/time_end, check for overloaded technicians only
    # (overlap detection not possible without scheduled times)
    conflicts = []

    # Find overloaded technicians (>6 jobs per day)
    overloaded = execute_kelava_query(
        """
        SELECT 
            u.id,
            u.fullname as name,
            COUNT(rp.id) as job_count
        FROM p_user u
        JOIN t_road_plan rp ON rp.id_user = u.id
        WHERE rp.visit_date::date = %s
          AND COALESCE(rp.is_cancel, false) = false
        GROUP BY u.id, u.fullname
        HAVING COUNT(rp.id) > 6
        ORDER BY job_count DESC
    """,
        (date,),
    )

    return jsonify(
        {
            "date": date,
            "overlap_conflicts": [],  # Not available without time_start/time_end
            "overloaded_technicians": [
                {"id": o["id"], "name": o["name"], "job_count": o["job_count"]}
                for o in overloaded
            ],
            "has_issues": len(overloaded) > 0,
            "generated_at": datetime.now().isoformat(),
        }
    )


@calendar_bp.route("/calendar/day-summary")
@require_auth
def calendar_day_summary():
    """
    Get summary for a specific day - useful for calendar header.
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    summary = execute_kelava_query_single(
        """
        SELECT 
            COUNT(*) as total_jobs,
            COUNT(*) FILTER (WHERE status = 'Selesai') as completed,
            COUNT(*) FILTER (WHERE status = 'Berjalan') as in_progress,
            COUNT(*) FILTER (WHERE status IN ('Baru', 'Requested')) as pending,
            COUNT(DISTINCT id_user) as technicians_active
        FROM t_road_plan
        WHERE visit_date::date = %s
          AND COALESCE(is_cancel, false) = false
    """,
        (date,),
    )

    return jsonify(
        {
            "date": date,
            "summary": {
                "total_jobs": summary["total_jobs"] if summary else 0,
                "completed": summary["completed"] if summary else 0,
                "in_progress": summary["in_progress"] if summary else 0,
                "pending": summary["pending"] if summary else 0,
                "technicians_active": summary["technicians_active"] if summary else 0,
                "completion_rate": round(
                    (summary["completed"] / summary["total_jobs"] * 100)
                    if summary and summary["total_jobs"] > 0
                    else 0,
                    1,
                ),
            },
            "generated_at": datetime.now().isoformat(),
        }
    )


@calendar_bp.route("/calendar/reschedule", methods=["POST"])
@require_auth
def calendar_reschedule():
    """
    Reschedule a Kelava road plan from the dashboard.

    Body: {
        road_plan_id: int,           -- Kelava t_road_plan.id
        new_date?: "YYYY-MM-DD",
        new_technician_id?: int,
        reason?: string
    }

    Creates a new snc_road_plans entry (the replacement) and records the
    original in snc_kelava_cancellations so it is hidden from the calendar.
    """
    data = request.json or {}
    user = getattr(g, "current_user", None) or getattr(request, "_jwt_user", {})
    created_by = (user.id if hasattr(user, "id") else user.get("id", 0)) or 0

    rp_id = data.get("road_plan_id")
    if not rp_id:
        return jsonify({"error": "road_plan_id required"}), 400

    new_date = data.get("new_date")
    new_tech_id = data.get("new_technician_id")
    reason = data.get("reason", "")

    if not new_date and not new_tech_id:
        return jsonify({"error": "new_date or new_technician_id required"}), 400

    # Fetch original road plan from Kelava
    original = execute_kelava_query_single(
        "SELECT id, visit_date, id_user, id_customer, id_kontrak, type, title, remarks FROM t_road_plan WHERE id = %s",
        (rp_id,),
        cache_ttl=0,
    )
    if not original:
        return jsonify({"error": "Road plan not found"}), 404

    final_date = new_date or original["visit_date"].strftime("%Y-%m-%d")
    final_tech_id = int(new_tech_id) if new_tech_id else original["id_user"]

    new_plan_id = None
    try:
        with _get_local_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Create replacement road plan
                cur.execute(
                    """
                    INSERT INTO snc_road_plans
                        (kelava_road_plan_id, visit_date, p_user_id, customer_id,
                         kontrak_id, visit_type, title, remarks, created_by)
                    VALUES (%s, %s::timestamptz, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        rp_id,
                        final_date + "T08:00:00",
                        final_tech_id,
                        original["id_customer"],
                        original.get("id_kontrak"),
                        original.get("type") or "visit",
                        original.get("title"),
                        reason or original.get("remarks"),
                        created_by,
                    ),
                )
                row = cur.fetchone()
                new_plan_id = row["id"] if row else None

                # Record the original as cancelled/overridden
                cur.execute(
                    """
                    INSERT INTO snc_kelava_cancellations
                        (kelava_road_plan_id, reason, new_snc_road_plan_id, created_by)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (kelava_road_plan_id) DO UPDATE
                        SET reason = EXCLUDED.reason,
                            new_snc_road_plan_id = EXCLUDED.new_snc_road_plan_id,
                            created_by = EXCLUDED.created_by,
                            created_at = NOW()
                    """,
                    (rp_id, reason, new_plan_id, created_by),
                )
    except Exception as exc:
        return jsonify({"error": f"Database error: {exc}"}), 500

    # FCM push to new technician (best-effort)
    try:
        from kil.backend.legacy.api.scheduling_write import _notify_technician
        _notify_technician(final_tech_id, new_plan_id, datetime.fromisoformat(final_date + "T08:00:00"))
    except Exception:
        pass

    return jsonify({
        "message": "Rescheduled successfully",
        "original_road_plan_id": rp_id,
        "new_snc_road_plan_id": new_plan_id,
        "new_date": final_date,
        "new_technician_id": final_tech_id,
    })


@calendar_bp.route("/calendar/cancel", methods=["POST"])
@require_auth
def calendar_cancel():
    """
    Cancel a Kelava road plan from the dashboard (without rescheduling).

    Body: { road_plan_id: int, reason?: string }
    """
    data = request.json or {}
    user = getattr(request, "_jwt_user", {})
    created_by = user.get("id", 0) or 0

    rp_id = data.get("road_plan_id")
    if not rp_id:
        return jsonify({"error": "road_plan_id required"}), 400

    try:
        with _get_local_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO snc_kelava_cancellations
                        (kelava_road_plan_id, reason, created_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (kelava_road_plan_id) DO UPDATE
                        SET reason = EXCLUDED.reason, created_at = NOW()
                    """,
                    (rp_id, data.get("reason", "Dibatalkan dari dashboard"), created_by),
                )
    except Exception as exc:
        return jsonify({"error": f"Database error: {exc}"}), 500

    return jsonify({"message": "Cancelled", "road_plan_id": rp_id})
