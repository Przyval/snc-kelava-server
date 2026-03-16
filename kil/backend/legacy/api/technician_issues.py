"""
Technician Issues API - Escalation Policy Layer
Implements: Review → Warning → Escalated ladder with closure requirements
"""

import json
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from psycopg.types.json import Json

from core.security import require_auth
from kil.db.kelava_db import get_kelava_connection

bp = Blueprint(
    "technician_issues", __name__, url_prefix="/api/v1/enterprise/technician-issues"
)


def get_db():
    """Get database connection to Kelava."""
    return get_kelava_connection()


# Escalation thresholds (in hours)
REVIEW_TO_WARNING_HOURS = 48
WARNING_TO_ESCALATED_HOURS = 24

ISSUE_TYPES = {
    "low_volume": {"label": "Low Volume", "threshold": 2.0},  # visits/day
    "slow_duration": {"label": "Slow Duration", "threshold": 240},  # minutes
    "low_completion": {"label": "Low Completion", "threshold": 75},  # percentage
    "protocol_violation": {"label": "Protocol Violation", "threshold": None},
}

RESOLUTION_TYPES = ["resolved", "acknowledged", "deferred", "false_positive"]


@bp.route("/", methods=["GET"])
@require_auth
def list_issues():
    """List all open technician issues with optional filters."""
    severity = request.args.get("severity")
    technician_id = request.args.get("technician_id")
    status = request.args.get("status", "open")

    conn = get_db()
    cur = conn.cursor()

    query = """
        SELECT 
            ti.*,
            t.fullname as technician_name,
            t.email as technician_email,
            EXTRACT(EPOCH FROM (NOW() - ti.created_at)) / 3600 as hours_open
        FROM technician_issues ti
        LEFT JOIN p_user t ON t.id = ti.technician_id
        WHERE ti.status = %s
    """
    params = [status]

    if severity:
        query += " AND ti.severity = %s"
        params.append(severity)

    if technician_id:
        query += " AND ti.technician_id = %s"
        params.append(technician_id)

    query += """
        ORDER BY 
            CASE ti.severity 
                WHEN 'escalated' THEN 1 
                WHEN 'warning' THEN 2 
                WHEN 'review' THEN 3 
            END,
            ti.created_at DESC
    """

    cur.execute(query, params)
    issues = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify(
        {
            "issues": issues,
            "total": len(issues),
            "filters": {
                "severity": severity,
                "technician_id": technician_id,
                "status": status,
            },
        }
    )


@bp.route("/<int:issue_id>", methods=["GET"])
@require_auth
def get_issue(issue_id):
    """Get issue details with full action history."""
    conn = get_db()
    cur = conn.cursor()

    # Get issue
    cur.execute(
        """
        SELECT 
            ti.*,
            t.fullname as technician_name,
            t.email as technician_email,
            EXTRACT(EPOCH FROM (NOW() - ti.created_at)) / 3600 as hours_open
        FROM technician_issues ti
        LEFT JOIN p_user t ON t.id = ti.technician_id
        WHERE ti.id = %s
    """,
        (issue_id,),
    )
    issue = cur.fetchone()

    if not issue:
        cur.close()
        conn.close()
        return jsonify({"error": "Issue not found"}), 404

    # Get action history
    cur.execute(
        """
        SELECT * FROM issue_actions 
        WHERE issue_id = %s 
        ORDER BY created_at DESC
    """,
        (issue_id,),
    )
    actions = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({"issue": issue, "actions": actions})


@bp.route("/technician/<int:technician_id>", methods=["GET"])
@require_auth
def get_technician_issues(technician_id):
    """Get all issues for a specific technician."""
    status = request.args.get("status")  # 'open', 'resolved', or None for all

    conn = get_db()
    cur = conn.cursor()

    query = """
        SELECT 
            ti.*,
            EXTRACT(EPOCH FROM (NOW() - ti.created_at)) / 3600 as hours_open
        FROM technician_issues ti
        WHERE ti.technician_id = %s
    """
    params = [technician_id]

    if status:
        query += " AND ti.status = %s"
        params.append(status)

    query += " ORDER BY ti.created_at DESC"

    cur.execute(query, params)
    issues = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify(
        {
            "technician_id": technician_id,
            "issues": issues,
            "open_count": len([i for i in issues if i.get("status") == "open"]),
            "resolved_count": len([i for i in issues if i.get("status") == "resolved"]),
        }
    )


@bp.route("/<int:issue_id>/resolve", methods=["POST"])
@require_auth
def resolve_issue(issue_id):
    """Resolve an issue with mandatory resolution type and note."""
    data = request.json or {}

    resolution_type = data.get("resolution_type")
    note = data.get("note", "").strip()
    actor_name = data.get("actor_name", "Supervisor")
    actor_id = data.get("actor_id")

    # Validation
    if resolution_type not in RESOLUTION_TYPES:
        return jsonify(
            {"error": f"Invalid resolution_type. Must be one of: {RESOLUTION_TYPES}"}
        ), 400

    if len(note) < 10:
        return jsonify({"error": "Resolution note must be at least 10 characters"}), 400

    conn = get_db()
    cur = conn.cursor()

    # Check issue exists and is open
    cur.execute("SELECT * FROM technician_issues WHERE id = %s", (issue_id,))
    issue = cur.fetchone()

    if not issue:
        cur.close()
        conn.close()
        return jsonify({"error": "Issue not found"}), 404

    if issue.get("status") == "resolved":
        cur.close()
        conn.close()
        return jsonify({"error": "Issue is already resolved"}), 400

    # Resolve the issue
    cur.execute(
        """
        UPDATE technician_issues 
        SET 
            status = 'resolved',
            resolved_at = NOW(),
            resolution_type = %s,
            resolution_note = %s,
            resolved_by = %s
        WHERE id = %s
        RETURNING *
    """,
        (resolution_type, note, actor_id, issue_id),
    )

    updated_issue = cur.fetchone()

    # Log the action
    cur.execute(
        """
        INSERT INTO issue_actions (issue_id, action_type, actor_id, actor_name, note)
        VALUES (%s, 'resolved', %s, %s, %s)
    """,
        (issue_id, actor_id, actor_name, f"Resolved as '{resolution_type}': {note}"),
    )

    conn.commit()
    cur.close()
    conn.close()

    return jsonify(
        {
            "success": True,
            "issue": updated_issue,
            "message": f"Issue resolved as {resolution_type}",
        }
    )


@bp.route("/<int:issue_id>/escalate", methods=["POST"])
@require_auth
def escalate_issue(issue_id):
    """Manually escalate an issue to the next level."""
    data = request.json or {}
    actor_name = data.get("actor_name", "System")
    reason = data.get("reason", "Manual escalation")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM technician_issues WHERE id = %s", (issue_id,))
    issue = cur.fetchone()

    if not issue:
        cur.close()
        conn.close()
        return jsonify({"error": "Issue not found"}), 404

    current_severity = issue.get("severity", "review")

    # Determine next severity level
    severity_ladder = ["review", "warning", "escalated"]
    current_idx = (
        severity_ladder.index(current_severity)
        if current_severity in severity_ladder
        else 0
    )

    if current_idx >= len(severity_ladder) - 1:
        cur.close()
        conn.close()
        return jsonify({"error": "Issue is already at maximum escalation level"}), 400

    new_severity = severity_ladder[current_idx + 1]

    # Update severity
    cur.execute(
        """
        UPDATE technician_issues 
        SET severity = %s, escalated_at = NOW()
        WHERE id = %s
        RETURNING *
    """,
        (new_severity, issue_id),
    )

    updated_issue = cur.fetchone()

    # Log the action
    cur.execute(
        """
        INSERT INTO issue_actions (issue_id, action_type, actor_name, note)
        VALUES (%s, 'escalated', %s, %s)
    """,
        (
            issue_id,
            actor_name,
            f"Escalated from {current_severity} to {new_severity}: {reason}",
        ),
    )

    conn.commit()
    cur.close()
    conn.close()

    return jsonify(
        {
            "success": True,
            "issue": updated_issue,
            "previous_severity": current_severity,
            "new_severity": new_severity,
        }
    )


@bp.route("/<int:issue_id>/add-note", methods=["POST"])
@require_auth
def add_note(issue_id):
    """Add a supervisory note to an issue without resolving it."""
    data = request.json or {}
    note = data.get("note", "").strip()
    actor_name = data.get("actor_name", "Supervisor")
    actor_id = data.get("actor_id")

    if len(note) < 5:
        return jsonify({"error": "Note must be at least 5 characters"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM technician_issues WHERE id = %s", (issue_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"error": "Issue not found"}), 404

    cur.execute(
        """
        INSERT INTO issue_actions (issue_id, action_type, actor_id, actor_name, note)
        VALUES (%s, 'note_added', %s, %s, %s)
        RETURNING *
    """,
        (issue_id, actor_id, actor_name, note),
    )

    action = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"success": True, "action": action})


@bp.route("/auto-escalate", methods=["POST"])
@require_auth
def auto_escalate():
    """
    Cron endpoint: Auto-escalate issues past SLA threshold.
    Should be called by a scheduler (e.g., every hour).
    """
    conn = get_db()
    cur = conn.cursor()

    escalated_count = 0

    # Review → Warning (after 48 hours)
    cur.execute(
        """
        UPDATE technician_issues 
        SET 
            severity = 'warning', 
            escalated_at = NOW(),
            auto_escalated = TRUE
        WHERE 
            status = 'open' 
            AND severity = 'review'
            AND created_at < NOW() - INTERVAL '%s hours'
        RETURNING id
    """,
        (REVIEW_TO_WARNING_HOURS,),
    )

    review_to_warning = cur.fetchall()
    for issue in review_to_warning:
        cur.execute(
            """
            INSERT INTO issue_actions (issue_id, action_type, actor_name, note)
            VALUES (%s, 'auto_escalated', 'System', 'Auto-escalated from Review to Warning after 48 hours')
        """,
            (issue["id"],),
        )
        escalated_count += 1

    # Warning → Escalated (after additional 24 hours)
    cur.execute(
        """
        UPDATE technician_issues 
        SET 
            severity = 'escalated', 
            escalated_at = NOW(),
            auto_escalated = TRUE
        WHERE 
            status = 'open' 
            AND severity = 'warning'
            AND escalated_at < NOW() - INTERVAL '%s hours'
        RETURNING id
    """,
        (WARNING_TO_ESCALATED_HOURS,),
    )

    warning_to_escalated = cur.fetchall()
    for issue in warning_to_escalated:
        cur.execute(
            """
            INSERT INTO issue_actions (issue_id, action_type, actor_name, note)
            VALUES (%s, 'auto_escalated', 'System', 'Auto-escalated from Warning to Escalated after 24 hours - Management notification triggered')
        """,
            (issue["id"],),
        )
        escalated_count += 1

    conn.commit()
    cur.close()
    conn.close()

    return jsonify(
        {
            "success": True,
            "escalated_count": escalated_count,
            "review_to_warning": len(review_to_warning),
            "warning_to_escalated": len(warning_to_escalated),
            "checked_at": datetime.now().isoformat(),
        }
    )


@bp.route("/create", methods=["POST"])
@require_auth
def create_issue():
    """Create a new technician issue (usually called by the rule engine)."""
    data = request.json or {}

    technician_id = data.get("technician_id")
    issue_type = data.get("issue_type")
    context = data.get("context", {})

    if not technician_id or not issue_type:
        return jsonify({"error": "technician_id and issue_type are required"}), 400

    if issue_type not in ISSUE_TYPES:
        return jsonify(
            {"error": f"Invalid issue_type. Must be one of: {list(ISSUE_TYPES.keys())}"}
        ), 400

    conn = get_db()
    cur = conn.cursor()

    # Check for duplicate open issue
    cur.execute(
        """
        SELECT id FROM technician_issues 
        WHERE technician_id = %s AND issue_type = %s AND status = 'open'
    """,
        (technician_id, issue_type),
    )

    existing = cur.fetchone()
    if existing:
        cur.close()
        conn.close()
        return jsonify(
            {
                "success": False,
                "message": "Duplicate issue already open",
                "existing_issue_id": existing["id"],
            }
        ), 409

    # Create new issue
    cur.execute(
        """
        INSERT INTO technician_issues (technician_id, issue_type, severity, context)
        VALUES (%s, %s, 'review', %s)
        RETURNING *
    """,
        (technician_id, issue_type, Json(context)),
    )

    issue = cur.fetchone()

    # Log creation
    cur.execute(
        """
        INSERT INTO issue_actions (issue_id, action_type, actor_name, note)
        VALUES (%s, 'created', 'System', %s)
    """,
        (issue["id"], f"Issue created: {ISSUE_TYPES[issue_type]['label']}"),
    )

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"success": True, "issue": issue}), 201


@bp.route("/summary", methods=["GET"])
@require_auth
def get_summary():
    """Get summary counts for dashboard display."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            severity,
            COUNT(*) as count
        FROM technician_issues
        WHERE status = 'open'
        GROUP BY severity
    """)

    severity_counts = {row["severity"]: row["count"] for row in cur.fetchall()}

    cur.execute("""
        SELECT 
            issue_type,
            COUNT(*) as count
        FROM technician_issues
        WHERE status = 'open'
        GROUP BY issue_type
    """)

    type_counts = {row["issue_type"]: row["count"] for row in cur.fetchall()}

    cur.close()
    conn.close()

    return jsonify(
        {
            "by_severity": {
                "review": severity_counts.get("review", 0),
                "warning": severity_counts.get("warning", 0),
                "escalated": severity_counts.get("escalated", 0),
            },
            "by_type": type_counts,
            "total_open": sum(severity_counts.values()),
        }
    )
