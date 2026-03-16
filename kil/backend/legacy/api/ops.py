from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.connection import get_db_connection

ops_bp = Blueprint("ops", __name__)


@ops_bp.route("/ops/summary")
@require_auth
def ops_summary():
    target_date_str = request.args.get("date", date.today().isoformat())
    try:
        target_date = date.fromisoformat(target_date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # KIL Ops Metrics Query
    # 1. Jobs Created
    cursor.execute(
        """
        SELECT COUNT(*) as count 
        FROM events_norm 
        WHERE event_type = 'job.created' 
          AND DATE(occurred_at AT TIME ZONE 'Asia/Jakarta') = %s
    """,
        (target_date,),
    )
    jobs_created = cursor.fetchone()["count"]

    # 2. Visits Completed
    cursor.execute(
        """
        SELECT COUNT(*) as count 
        FROM events_norm 
        WHERE event_type = 'visit.completed' 
          AND DATE(occurred_at AT TIME ZONE 'Asia/Jakarta') = %s
    """,
        (target_date,),
    )
    visits_completed = cursor.fetchone()["count"]

    # 3. Visits Started
    cursor.execute(
        """
        SELECT COUNT(*) as count 
        FROM events_norm 
        WHERE event_type = 'visit.started' 
          AND DATE(occurred_at AT TIME ZONE 'Asia/Jakarta') = %s
    """,
        (target_date,),
    )
    visits_started = cursor.fetchone()["count"]

    # 4. Open Issues by Severity
    cursor.execute("""
        SELECT severity, COUNT(*) as count
        FROM issues
        WHERE status = 'open'
        GROUP BY severity
    """)
    issues_by_severity = {row["severity"]: row["count"] for row in cursor.fetchall()}

    # 5. Active Techs (Unique techs with visits today)
    cursor.execute(
        """
        SELECT COUNT(DISTINCT payload->>'tech_id') as count
        FROM events_norm
        WHERE event_type = 'visit.started'
          AND DATE(occurred_at AT TIME ZONE 'Asia/Jakarta') = %s
    """,
        (target_date,),
    )
    active_techs = cursor.fetchone()["count"]

    conn.close()

    return jsonify(
        {
            "date": target_date.isoformat(),
            "generated_at": datetime.now().isoformat(),
            "jobs": {
                "created": jobs_created,
                "assigned": 0,  # Placeholder
                "canceled": 0,  # Placeholder
            },
            "visits": {"started": visits_started, "completed": visits_completed},
            "issues": {
                "open_critical": issues_by_severity.get("critical", 0),
                "open_high": issues_by_severity.get("high", 0),
                "open_medium": issues_by_severity.get("medium", 0),
                "open_low": issues_by_severity.get("low", 0),
                "resolved_today": 0,
            },
            "technicians_active": active_techs,
        }
    )


@ops_bp.route("/issues")
@require_auth
def list_issues():
    limit = request.args.get("limit", 50)
    status = request.args.get("status", "open")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM issues 
        WHERE status = %s
        ORDER BY created_at DESC
        LIMIT %s
    """,
        (status, limit),
    )

    columns = [desc[0] for desc in cursor.description]
    issues = [dict(zip(columns, row.values())) for row in cursor.fetchall()]

    conn.close()

    return jsonify({"issues": issues})


@ops_bp.route("/events/summary")
@require_auth
def events_summary():
    days = int(request.args.get("days", 7))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 
            DATE(occurred_at AT TIME ZONE 'Asia/Jakarta')::text as event_date,
            event_type,
            COUNT(*) as count
        FROM events_norm
        WHERE occurred_at >= CURRENT_DATE - INTERVAL '%s days'
        GROUP BY 1, 2
        ORDER BY 1 DESC
    """,
        (days,),
    )

    summary = {}
    for row in cursor.fetchall():
        date = row["event_date"]
        if date not in summary:
            summary[date] = {}
        summary[date][row["event_type"]] = row["count"]

    conn.close()

    return jsonify({"summary": summary})


@ops_bp.route("/sync/status")
@require_auth
def sync_status():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM sync_state")
    streams = cursor.fetchall()

    conn.close()
    return jsonify({"streams": streams})


@ops_bp.route("/map/positions")
@require_auth
def map_positions():
    """Get latest position for each technician"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get latest position per internal_id
    cursor.execute("""
        SELECT DISTINCT ON (internal_id) 
            internal_id, 
            latitude, 
            longitude, 
            captured_at,
            TO_CHAR(captured_at AT TIME ZONE 'Asia/Jakarta', 'HH24:MI:SS') as time_str
        FROM gps_positions
        ORDER BY internal_id, captured_at DESC
    """)

    columns = [desc[0] for desc in cursor.description]
    positions = [dict(zip(columns, row.values())) for row in cursor.fetchall()]

    conn.close()
    return jsonify({"positions": positions})
