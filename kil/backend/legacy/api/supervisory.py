"""
Supervisory Action / Sidak API
================================
Manages supervisor inspections, SP warnings, coaching, and audits.

Meeting notes:
- Supervisor bisa trigger sidak; sistem auto-schedule
- Teknisi tidak tahu kapan akan disidak
- Supervisor punya kalender sendiri untuk sidak
- Yang bisa assign: Bu Ita, Bu Imel, Mas Fahmi, Pak Alex
- Action types: sidak, SP, coaching, pendampingan audit, install klien baru
- Supervisor jadwal mostly kosong, diisi dari sidak + audit + install
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

supervisory_bp = Blueprint("supervisory", __name__, url_prefix="/supervisory")

VALID_ACTION_TYPES = (
    "SIDAK", "SP_WARNING", "COACHING", "REVIEW",
    "NEW_CLIENT_INSTALL", "AUDIT_ACCOMPANY", "COMPLAINT_HANDLING",
)
VALID_STATUSES = ("PENDING_APPROVAL", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "MISSED")
VALID_PRIORITIES = ("LOW", "NORMAL", "HIGH", "URGENT")


def _fmt(row):
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _auth_user_id():
    user = getattr(g, "user", None)
    return str(user.id) if user else None


def _auth_user_name():
    user = getattr(g, "user", None)
    if user and user.user_metadata:
        return user.user_metadata.get("full_name", user.email or "System")
    return "System"


# ── Supervisory Actions CRUD ────────────────────────────────


@supervisory_bp.route("/actions", methods=["GET"])
@require_auth
def list_actions():
    """
    List supervisory actions with filters.

    Query params:
        action_type: Filter by type
        supervisor_id: Filter by supervisor
        target_technician_id: Filter by target technician
        status: Filter by status (default: SCHEDULED,IN_PROGRESS)
        start_date, end_date: Date range
    """
    uid = _auth_user_id()
    action_type = request.args.get("action_type")
    supervisor_id = request.args.get("supervisor_id")
    target_id = request.args.get("target_technician_id")
    status_filter = request.args.get("status", "SCHEDULED,IN_PROGRESS")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    where_parts = []
    params = []

    if status_filter:
        statuses = [s.strip() for s in status_filter.split(",")]
        placeholders = ", ".join(["%s"] * len(statuses))
        where_parts.append(f"sa.status IN ({placeholders})")
        params.extend(statuses)

    if action_type:
        where_parts.append("sa.action_type = %s")
        params.append(action_type.upper())

    if supervisor_id:
        where_parts.append("sa.supervisor_id = %s")
        params.append(int(supervisor_id))

    if target_id:
        where_parts.append("sa.target_technician_id = %s")
        params.append(int(target_id))

    if start_date:
        where_parts.append("sa.scheduled_date >= %s")
        params.append(start_date)

    if end_date:
        where_parts.append("sa.scheduled_date <= %s")
        params.append(end_date)

    where_sql = " AND ".join(where_parts) if where_parts else "1=1"

    rows = execute_kelava_query(
        f"""
        SELECT
            sa.*,
            u_sup.fullname as supervisor_name,
            u_tech.fullname as technician_name,
            c.name as customer_name
        FROM supervisory_actions sa
        LEFT JOIN p_user u_sup ON u_sup.id = sa.supervisor_id
        LEFT JOIN p_user u_tech ON u_tech.id = sa.target_technician_id
        LEFT JOIN m_customer c ON c.id = sa.target_customer_id
        WHERE {where_sql}
        ORDER BY
            CASE sa.priority
                WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2
                WHEN 'NORMAL' THEN 3 ELSE 4
            END,
            sa.scheduled_date, sa.scheduled_time
        """,
        tuple(params) if params else None,
        user_id=uid,
    )

    return jsonify({
        "actions": [_fmt(r) for r in rows],
        "total": len(rows),
        "generated_at": datetime.now().isoformat(),
    })


@supervisory_bp.route("/actions", methods=["POST"])
@require_auth
def create_action():
    """
    Create a supervisory action.

    Body: {
        action_type: "SIDAK"|"SP_WARNING"|"COACHING"|"REVIEW"|"NEW_CLIENT_INSTALL"|"AUDIT_ACCOMPANY"|"COMPLAINT_HANDLING",
        supervisor_id: int,
        target_technician_id?: int,
        target_customer_id?: int,
        scheduled_date: "YYYY-MM-DD",
        scheduled_time?: "HH:MM",
        priority?: "LOW"|"NORMAL"|"HIGH"|"URGENT",
        trigger_reason?: string
    }
    """
    data = request.json or {}
    uid = _auth_user_id()

    action_type = (data.get("action_type") or "").upper()
    if action_type not in VALID_ACTION_TYPES:
        return jsonify({"error": f"action_type must be one of: {', '.join(VALID_ACTION_TYPES)}"}), 400

    supervisor_id = data.get("supervisor_id")
    if not supervisor_id:
        return jsonify({"error": "supervisor_id is required"}), 400

    scheduled_date = data.get("scheduled_date")
    if not scheduled_date:
        return jsonify({"error": "scheduled_date is required"}), 400

    # Sidak & SP_WARNING require koordinator approval
    user = getattr(g, "user", None)
    needs_approval = action_type in ("SIDAK", "SP_WARNING") and user and user.role == "supervisor"
    initial_status = "PENDING_APPROVAL" if needs_approval else "SCHEDULED"

    result = execute_kelava_query_single(
        """
        INSERT INTO supervisory_actions
            (action_type, supervisor_id, target_technician_id, target_customer_id,
             scheduled_date, scheduled_time, priority, trigger_reason, status, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            action_type,
            supervisor_id,
            data.get("target_technician_id"),
            data.get("target_customer_id"),
            scheduled_date,
            data.get("scheduled_time"),
            data.get("priority", "NORMAL").upper(),
            data.get("trigger_reason", ""),
            initial_status,
            uid,
        ),
        user_id=uid,
    )

    status_msg = "menunggu approval koordinator" if needs_approval else "scheduled"
    return jsonify({
        "message": f"{action_type} {status_msg}",
        "action": _fmt(result) if result else {},
        "needs_approval": needs_approval,
    }), 201


@supervisory_bp.route("/actions/<int:action_id>/complete", methods=["POST"])
@require_auth
def complete_action(action_id: int):
    """
    Complete a supervisory action with findings.

    Body: { findings, follow_up_action?, follow_up_deadline? }
    """
    data = request.json or {}
    uid = _auth_user_id()

    findings = data.get("findings", "")
    if len(findings) < 5:
        return jsonify({"error": "findings must be at least 5 characters"}), 400

    result = execute_kelava_query_single(
        """
        UPDATE supervisory_actions
        SET status = 'COMPLETED',
            actual_date = CURRENT_DATE,
            findings = %s,
            follow_up_action = %s,
            follow_up_deadline = %s,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE id = %s AND status IN ('SCHEDULED', 'IN_PROGRESS')
        RETURNING *
        """,
        (
            findings,
            data.get("follow_up_action"),
            data.get("follow_up_deadline"),
            action_id,
        ),
        user_id=uid,
    )

    if not result:
        return jsonify({"error": "Action not found or already completed"}), 404

    return jsonify({"message": "Action completed", "action": _fmt(result)})


@supervisory_bp.route("/actions/<int:action_id>/approve", methods=["POST"])
@require_auth
@require_role("koordinator")
def approve_action(action_id: int):
    """
    Koordinator approves a pending supervisory action (sidak/SP).
    Changes status from PENDING_APPROVAL to SCHEDULED.

    Body: { note?: string }
    """
    data = request.json or {}
    uid = _auth_user_id()
    note = data.get("note", "")

    result = execute_kelava_query_single(
        """
        UPDATE supervisory_actions
        SET status = 'SCHEDULED',
            trigger_reason = trigger_reason || CASE WHEN %s != '' THEN ' | Approved: ' || %s ELSE '' END,
            updated_at = NOW()
        WHERE id = %s AND status = 'PENDING_APPROVAL'
        RETURNING *
        """,
        (note, note, action_id),
        user_id=uid,
    )

    if not result:
        return jsonify({"error": "Action not found or not pending approval"}), 404

    return jsonify({"message": "Action approved and scheduled", "action": _fmt(result)})


@supervisory_bp.route("/actions/<int:action_id>/reject", methods=["POST"])
@require_auth
@require_role("koordinator")
def reject_action(action_id: int):
    """
    Koordinator rejects a pending supervisory action.
    Changes status from PENDING_APPROVAL to CANCELLED.

    Body: { reason: string }
    """
    data = request.json or {}
    uid = _auth_user_id()
    reason = data.get("reason", "Ditolak oleh koordinator")

    if len(reason) < 3:
        return jsonify({"error": "Alasan penolakan harus diisi"}), 400

    result = execute_kelava_query_single(
        """
        UPDATE supervisory_actions
        SET status = 'CANCELLED',
            trigger_reason = trigger_reason || ' | Rejected: ' || %s,
            updated_at = NOW()
        WHERE id = %s AND status = 'PENDING_APPROVAL'
        RETURNING *
        """,
        (reason, action_id),
        user_id=uid,
    )

    if not result:
        return jsonify({"error": "Action not found or not pending approval"}), 404

    return jsonify({"message": "Action rejected", "action": _fmt(result)})


@supervisory_bp.route("/actions/pending", methods=["GET"])
@require_auth
@require_role("koordinator")
def pending_approvals():
    """List all actions pending koordinator approval."""
    uid = _auth_user_id()

    rows = execute_kelava_query(
        """
        SELECT
            sa.*,
            u_sup.fullname as supervisor_name,
            u_tech.fullname as technician_name,
            c.name as customer_name
        FROM supervisory_actions sa
        LEFT JOIN p_user u_sup ON u_sup.id = sa.supervisor_id
        LEFT JOIN p_user u_tech ON u_tech.id = sa.target_technician_id
        LEFT JOIN m_customer c ON c.id = sa.target_customer_id
        WHERE sa.status = 'PENDING_APPROVAL'
        ORDER BY
            CASE sa.priority
                WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2
                WHEN 'NORMAL' THEN 3 ELSE 4
            END,
            sa.created_at
        """,
        user_id=uid,
    )

    return jsonify({
        "pending_actions": [_fmt(r) for r in rows],
        "total": len(rows),
        "generated_at": datetime.now().isoformat(),
    })


@supervisory_bp.route("/actions/<int:action_id>/cancel", methods=["POST"])
@require_auth
def cancel_action(action_id: int):
    """Cancel a scheduled supervisory action."""
    data = request.json or {}
    uid = _auth_user_id()
    reason = data.get("reason", "Cancelled by supervisor")

    result = execute_kelava_query_single(
        """
        UPDATE supervisory_actions
        SET status = 'CANCELLED', trigger_reason = trigger_reason || ' | Cancelled: ' || %s, updated_at = NOW()
        WHERE id = %s AND status = 'SCHEDULED'
        RETURNING *
        """,
        (reason, action_id),
        user_id=uid,
    )

    if not result:
        return jsonify({"error": "Action not found or cannot be cancelled"}), 404

    return jsonify({"message": "Action cancelled", "action": _fmt(result)})


# ── Trigger Sidak ───────────────────────────────────────────


@supervisory_bp.route("/trigger-sidak", methods=["POST"])
@require_auth
def trigger_sidak():
    """
    Trigger a sidak (surprise inspection) for a technician.
    System auto-schedules based on supervisor availability.

    Body: {
        supervisor_id: int,
        target_technician_id: int,
        reason?: string,
        preferred_date?: "YYYY-MM-DD"
    }
    """
    data = request.json or {}
    uid = _auth_user_id()

    supervisor_id = data.get("supervisor_id")
    target_id = data.get("target_technician_id")

    if not supervisor_id or not target_id:
        return jsonify({"error": "supervisor_id and target_technician_id required"}), 400

    # Find next available date for supervisor (no existing actions)
    preferred = data.get("preferred_date")
    if preferred:
        sidak_date = preferred
    else:
        # Auto-pick: next 3 days, find first without existing actions
        avail = execute_kelava_query_single(
            """
            WITH dates AS (
                SELECT generate_series(
                    CURRENT_DATE + INTERVAL '1 day',
                    CURRENT_DATE + INTERVAL '7 days',
                    '1 day'
                )::date as d
            )
            SELECT d FROM dates
            WHERE d NOT IN (
                SELECT scheduled_date FROM supervisory_actions
                WHERE supervisor_id = %s AND status = 'SCHEDULED'
            )
            AND EXTRACT(DOW FROM d) BETWEEN 1 AND 5  -- Weekdays only
            ORDER BY d
            LIMIT 1
            """,
            (supervisor_id,),
            user_id=uid,
        )
        sidak_date = avail["d"].isoformat() if avail else (date.today() + timedelta(days=1)).isoformat()

    # Find where the technician will be on that date
    tech_location = execute_kelava_query_single(
        """
        SELECT rp.id_customer, c.name as customer_name, rp.visit_date
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.id_user = %s AND rp.visit_date::date = %s
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY rp.created_at
        LIMIT 1
        """,
        (target_id, sidak_date),
        user_id=uid,
    )

    customer_id = tech_location["id_customer"] if tech_location else None
    reason = data.get("reason", "Sidak rutin berdasarkan KPI review")

    result = execute_kelava_query_single(
        """
        INSERT INTO supervisory_actions
            (action_type, supervisor_id, target_technician_id, target_customer_id,
             scheduled_date, priority, trigger_reason, created_by)
        VALUES ('SIDAK', %s, %s, %s, %s, 'HIGH', %s, %s)
        RETURNING *
        """,
        (supervisor_id, target_id, customer_id, sidak_date, reason, uid),
        user_id=uid,
    )

    return jsonify({
        "message": f"Sidak scheduled for {sidak_date}",
        "action": _fmt(result) if result else {},
        "location": tech_location["customer_name"] if tech_location else "TBD",
    }), 201


# ── Supervisor Calendar ─────────────────────────────────────


@supervisory_bp.route("/calendar/<int:supervisor_id>", methods=["GET"])
@require_auth
def supervisor_calendar(supervisor_id: int):
    """
    Get supervisor's calendar with all actions.
    Supervisor jadwal mostly kosong - filled by sidak, audit, install.

    Query params:
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
    """
    uid = _auth_user_id()
    start = request.args.get("start_date", date.today().isoformat())
    end = request.args.get(
        "end_date",
        (date.today() + timedelta(days=30)).isoformat(),
    )

    rows = execute_kelava_query(
        """
        SELECT
            sa.id,
            sa.action_type,
            sa.scheduled_date,
            sa.scheduled_time,
            sa.status,
            sa.priority,
            sa.trigger_reason,
            sa.target_technician_id,
            u_tech.fullname as technician_name,
            sa.target_customer_id,
            c.name as customer_name,
            sa.findings
        FROM supervisory_actions sa
        LEFT JOIN p_user u_tech ON u_tech.id = sa.target_technician_id
        LEFT JOIN m_customer c ON c.id = sa.target_customer_id
        WHERE sa.supervisor_id = %s
          AND sa.scheduled_date BETWEEN %s AND %s
        ORDER BY sa.scheduled_date, sa.scheduled_time
        """,
        (supervisor_id, start, end),
        user_id=uid,
    )

    # Group by date
    by_date = {}
    for r in rows:
        d = r["scheduled_date"].isoformat() if hasattr(r["scheduled_date"], "isoformat") else str(r["scheduled_date"])
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(_fmt(r))

    return jsonify({
        "supervisor_id": supervisor_id,
        "period": {"start": start, "end": end},
        "calendar": by_date,
        "total_actions": len(rows),
        "generated_at": datetime.now().isoformat(),
    })


# ── Sidak Candidates (Who needs inspection?) ───────────────


@supervisory_bp.route("/sidak-candidates", methods=["GET"])
@require_auth
def sidak_candidates():
    """
    Suggest technicians that should be inspected based on:
    - Low KPI scores
    - Frequent anomalies (short visits, lupa check-out)
    - No recent supervision
    - Complaint history
    """
    uid = _auth_user_id()
    days = int(request.args.get("days", 30))

    rows = execute_kelava_query(
        """
        WITH tech_metrics AS (
            SELECT
                rp.id_user as technician_id,
                COUNT(*) as total_planned,
                COUNT(*) FILTER (WHERE rp.status = 'Selesai') as completed,
                COUNT(v.id) FILTER (
                    WHERE v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                    AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) < 300
                ) as short_visits,
                COUNT(v.id) FILTER (
                    WHERE v.check_in IS NOT NULL AND v.check_out IS NULL
                ) as missing_checkout
            FROM t_road_plan rp
            LEFT JOIN t_visit v ON v.id_road_plan = rp.id
            WHERE rp.visit_date >= CURRENT_DATE - make_interval(days => %s)
              AND COALESCE(rp.is_cancel, false) = false
            GROUP BY rp.id_user
        ),
        last_sidak AS (
            SELECT
                target_technician_id,
                MAX(scheduled_date) as last_sidak_date
            FROM supervisory_actions
            WHERE action_type = 'SIDAK' AND status = 'COMPLETED'
            GROUP BY target_technician_id
        ),
        complaint_count AS (
            SELECT
                technician_id,
                COUNT(*) as complaints
            FROM complaints
            WHERE complaint_date >= CURRENT_DATE - make_interval(days => %s)
              AND status IN ('OPEN', 'IN_PROGRESS')
            GROUP BY technician_id
        )
        SELECT
            u.id as technician_id,
            u.fullname as name,
            COALESCE(ts.segment, 'UNASSIGNED') as segment,
            COALESCE(tm.total_planned, 0) as total_planned,
            COALESCE(tm.completed, 0) as completed,
            COALESCE(tm.short_visits, 0) as short_visits,
            COALESCE(tm.missing_checkout, 0) as missing_checkout,
            ls.last_sidak_date,
            (CURRENT_DATE - ls.last_sidak_date) as days_since_last_sidak,
            COALESCE(cc.complaints, 0) as complaint_count,
            -- Priority score (higher = more urgent)
            (
                COALESCE(tm.short_visits, 0) * 3 +
                COALESCE(tm.missing_checkout, 0) * 2 +
                COALESCE(cc.complaints, 0) * 5 +
                CASE WHEN ls.last_sidak_date IS NULL THEN 10
                     WHEN (CURRENT_DATE - ls.last_sidak_date) > 30 THEN 5
                     ELSE 0 END
            ) as urgency_score
        FROM p_user u
        LEFT JOIN technician_segments ts ON ts.technician_id = u.id
        LEFT JOIN tech_metrics tm ON tm.technician_id = u.id
        LEFT JOIN last_sidak ls ON ls.target_technician_id = u.id
        LEFT JOIN complaint_count cc ON cc.technician_id = u.id
        WHERE COALESCE(u.is_deleted, false) = false
          AND (
            COALESCE(tm.short_visits, 0) > 0
            OR COALESCE(tm.missing_checkout, 0) > 0
            OR COALESCE(cc.complaints, 0) > 0
            OR ls.last_sidak_date IS NULL
            OR (CURRENT_DATE - ls.last_sidak_date) > 14
          )
        ORDER BY urgency_score DESC
        LIMIT 20
        """,
        (days, days),
        user_id=uid,
    )

    return jsonify({
        "candidates": [_fmt(r) for r in rows],
        "period_days": days,
        "generated_at": datetime.now().isoformat(),
    })


# ── Supervision Report ──────────────────────────────────────


@supervisory_bp.route("/reports", methods=["POST"])
@require_auth
def create_supervision_report():
    """
    Submit a supervision/QC report.

    Body: {
        supervisory_action_id?: int,
        supervisor_id: int,
        technician_id: int,
        customer_id?: int,
        score_appearance: 1-5,
        score_punctuality: 1-5,
        score_procedure: 1-5,
        score_safety: 1-5,
        score_communication: 1-5,
        score_documentation: 1-5,
        findings?: string,
        recommendations?: string,
        follow_up_required?: bool,
        follow_up_deadline?: "YYYY-MM-DD"
    }
    """
    data = request.json or {}
    uid = _auth_user_id()

    supervisor_id = data.get("supervisor_id")
    tech_id = data.get("technician_id")

    if not supervisor_id or not tech_id:
        return jsonify({"error": "supervisor_id and technician_id required"}), 400

    result = execute_kelava_query_single(
        """
        INSERT INTO supervision_reports
            (supervisory_action_id, supervisor_id, technician_id, customer_id,
             score_appearance, score_punctuality, score_procedure,
             score_safety, score_communication, score_documentation,
             findings, recommendations, follow_up_required, follow_up_deadline)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            data.get("supervisory_action_id"),
            supervisor_id,
            tech_id,
            data.get("customer_id"),
            data.get("score_appearance"),
            data.get("score_punctuality"),
            data.get("score_procedure"),
            data.get("score_safety"),
            data.get("score_communication"),
            data.get("score_documentation"),
            data.get("findings", ""),
            data.get("recommendations", ""),
            data.get("follow_up_required", False),
            data.get("follow_up_deadline"),
        ),
        user_id=uid,
    )

    return jsonify({
        "message": "Supervision report submitted",
        "report": _fmt(result) if result else {},
    }), 201


@supervisory_bp.route("/reports/technician/<int:tech_id>", methods=["GET"])
@require_auth
def technician_reports(tech_id: int):
    """Get all supervision reports for a technician."""
    uid = _auth_user_id()

    rows = execute_kelava_query(
        """
        SELECT
            sr.*,
            u_sup.fullname as supervisor_name,
            c.name as customer_name
        FROM supervision_reports sr
        LEFT JOIN p_user u_sup ON u_sup.id = sr.supervisor_id
        LEFT JOIN m_customer c ON c.id = sr.customer_id
        WHERE sr.technician_id = %s
        ORDER BY sr.report_date DESC
        """,
        (tech_id,),
        user_id=uid,
    )

    # Calculate averages
    avg_score = None
    if rows:
        scores = [r.get("overall_score") for r in rows if r.get("overall_score") is not None]
        if scores:
            avg_score = round(sum(float(s) for s in scores) / len(scores), 1)

    return jsonify({
        "technician_id": tech_id,
        "reports": [_fmt(r) for r in rows],
        "average_score": avg_score,
        "total_reports": len(rows),
        "generated_at": datetime.now().isoformat(),
    })
