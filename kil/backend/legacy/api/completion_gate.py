"""
Completion Gate API - Evidence Enforcement

Provides endpoints for:
- Visit completion status (checklist of required evidence)
- Validate and attempt to mark visit as complete
- Block completion if evidence is missing

This enforces that visits CANNOT be marked complete without:
- GPS Check-in
- GPS Check-out
- Duration > 15 min and < 8 hours
- At least 1 photo
- Service notes filled
"""

from datetime import datetime

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

completion_gate_bp = Blueprint(
    "completion_gate", __name__, url_prefix="/api/v1/enterprise"
)

# Completion requirements
COMPLETION_RULES = {
    "has_check_in": {
        "label": "GPS Check-in",
        "required": True,
        "severity": "critical",
    },
    "has_check_out": {
        "label": "GPS Check-out",
        "required": True,
        "severity": "critical",
    },
    "valid_duration": {
        "label": "Valid Duration (15 min - 8 hours)",
        "required": True,
        "severity": "critical",
    },
    "has_photo": {
        "label": "At least 1 Photo",
        "required": True,
        "severity": "high",
    },
    "has_notes": {
        "label": "Service Notes",
        "required": False,  # Recommended but not blocking
        "severity": "medium",
    },
}


@completion_gate_bp.route("/visits/<int:visit_id>/completion-status")
@require_auth
def visit_completion_status(visit_id):
    """
    Get completion checklist status for a specific visit.
    Returns each requirement and whether it's satisfied.
    """
    # Get visit details
    visit = execute_kelava_query_single(
        """
        SELECT 
            v.id,
            v.id_road_plan,
            v.check_in,
            v.check_out,
            v.keterangan as notes,
            v.lat_check_in,
            v.long_check_in,
            v.lat_check_out,
            v.long_check_out,
            rp.visit_date,
            rp.status as road_plan_status,
            c.name as customer_name,
            u.fullname as technician_name,
            -- Duration in minutes
            CASE 
                WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL 
                THEN ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)
                ELSE NULL 
            END as duration_minutes
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        JOIN m_customer c ON c.id = rp.id_customer
        JOIN p_user u ON u.id = rp.id_user
        WHERE v.id = %s
    """,
        (visit_id,),
    )

    if not visit:
        return jsonify({"error": "Visit not found"}), 404

    # Count photos for this visit
    photo_count = execute_kelava_query_single(
        """
        SELECT COUNT(*) as count
        FROM t_visit_data vd
        WHERE vd.id_visit = %s
          AND (
              (vd.foto_display IS NOT NULL AND vd.foto_display != '')
              OR (vd.foto_kompetitor IS NOT NULL AND vd.foto_kompetitor != '')
              OR (vd.foto_pengunjung IS NOT NULL AND vd.foto_pengunjung != '')
          )
    """,
        (visit_id,),
    )

    photos = photo_count["count"] if photo_count else 0
    duration = visit.get("duration_minutes")

    # Evaluate each requirement
    checks = {
        "has_check_in": {
            "passed": visit["check_in"] is not None,
            "value": visit["check_in"].isoformat() if visit["check_in"] else None,
            "has_gps": visit["lat_check_in"] is not None,
        },
        "has_check_out": {
            "passed": visit["check_out"] is not None,
            "value": visit["check_out"].isoformat() if visit["check_out"] else None,
            "has_gps": visit["lat_check_out"] is not None,
        },
        "valid_duration": {
            "passed": duration is not None and 15 <= duration <= 480,
            "value": duration,
            "reason": (
                "Too short"
                if duration and duration < 15
                else "Too long (>8hr)"
                if duration and duration > 480
                else "Missing check-in/out"
                if duration is None
                else "OK"
            ),
        },
        "has_photo": {
            "passed": photos > 0,
            "value": photos,
        },
        "has_notes": {
            "passed": bool(visit.get("notes") and len(visit["notes"].strip()) > 0),
            "value": len(visit["notes"]) if visit.get("notes") else 0,
        },
    }

    # Build checklist with rule metadata
    checklist = []
    required_passed = 0
    required_total = 0

    for key, rule in COMPLETION_RULES.items():
        check = checks.get(key, {"passed": False})
        item = {
            "id": key,
            "label": rule["label"],
            "required": rule["required"],
            "severity": rule["severity"],
            "passed": check["passed"],
            "value": check.get("value"),
        }
        if "reason" in check:
            item["reason"] = check["reason"]
        if "has_gps" in check:
            item["has_gps"] = check["has_gps"]
        checklist.append(item)

        if rule["required"]:
            required_total += 1
            if check["passed"]:
                required_passed += 1

    # Calculate completion readiness
    completion_pct = (
        round(required_passed / required_total * 100) if required_total > 0 else 0
    )
    can_complete = required_passed == required_total

    return jsonify(
        {
            "visit_id": visit_id,
            "visit": {
                "road_plan_id": visit["id_road_plan"],
                "customer": visit["customer_name"],
                "technician": visit["technician_name"],
                "date": visit["visit_date"].strftime("%Y-%m-%d")
                if visit["visit_date"]
                else None,
                "current_status": visit["road_plan_status"],
            },
            "checklist": checklist,
            "summary": {
                "required_passed": required_passed,
                "required_total": required_total,
                "completion_pct": completion_pct,
                "can_complete": can_complete,
                "blocking_items": [
                    c["label"] for c in checklist if c["required"] and not c["passed"]
                ],
            },
            "generated_at": datetime.now().isoformat(),
        }
    )


@completion_gate_bp.route("/visits/<int:visit_id>/validate", methods=["POST"])
@require_auth
def validate_visit_completion(visit_id):
    """
    Attempt to validate a visit for completion.
    Returns success if all required checks pass, otherwise returns blocking reasons.

    Note: This is a READ-ONLY check. Actual status update would require
    write access to the Kelava database which we don't have.
    """
    # Get completion status
    visit = execute_kelava_query_single(
        """
        SELECT 
            v.id,
            v.check_in,
            v.check_out,
            v.keterangan as notes,
            rp.status,
            CASE 
                WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL 
                THEN ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)
                ELSE NULL 
            END as duration_minutes
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE v.id = %s
    """,
        (visit_id,),
    )

    if not visit:
        return jsonify({"error": "Visit not found", "valid": False}), 404

    # Already complete?
    if visit["status"] == "Selesai":
        return jsonify(
            {
                "visit_id": visit_id,
                "valid": True,
                "already_complete": True,
                "message": "Visit is already marked as complete",
            }
        )

    # Count photos
    photo_count = execute_kelava_query_single(
        """
        SELECT COUNT(*) as count
        FROM t_visit_data vd
        WHERE vd.id_visit = %s
          AND (
              (vd.foto_display IS NOT NULL AND vd.foto_display != '')
              OR (vd.foto_kompetitor IS NOT NULL AND vd.foto_kompetitor != '')
              OR (vd.foto_pengunjung IS NOT NULL AND vd.foto_pengunjung != '')
          )
    """,
        (visit_id,),
    )

    photos = photo_count["count"] if photo_count else 0
    duration = visit.get("duration_minutes")

    # Evaluate blocking conditions
    blocking = []

    if not visit["check_in"]:
        blocking.append({"id": "has_check_in", "label": "Missing Check-in"})

    if not visit["check_out"]:
        blocking.append({"id": "has_check_out", "label": "Missing Check-out"})

    if duration is None:
        blocking.append({"id": "valid_duration", "label": "Cannot calculate duration"})
    elif duration < 15:
        blocking.append(
            {"id": "valid_duration", "label": f"Duration too short ({duration} min)"}
        )
    elif duration > 480:
        blocking.append(
            {
                "id": "valid_duration",
                "label": f"Duration too long ({duration} min > 8hr)",
            }
        )

    if photos == 0:
        blocking.append({"id": "has_photo", "label": "No photos uploaded"})

    # Determine result
    is_valid = len(blocking) == 0

    return jsonify(
        {
            "visit_id": visit_id,
            "valid": is_valid,
            "blocking_reasons": blocking,
            "message": "Visit can be marked as complete"
            if is_valid
            else "Visit cannot be completed - missing requirements",
            "action_required": [b["label"] for b in blocking] if not is_valid else [],
            "validated_at": datetime.now().isoformat(),
        }
    )


@completion_gate_bp.route("/completion-gate/pending")
@require_auth
def pending_completions():
    """
    Get list of visits that have check-in but are not yet complete.
    Useful for SPV to see what needs attention.
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    limit = int(request.args.get("limit", 50))

    pending = execute_kelava_query(
        """
        SELECT 
            v.id as visit_id,
            rp.id as road_plan_id,
            rp.visit_date,
            c.name as customer_name,
            u.fullname as technician_name,
            v.check_in,
            v.check_out,
            rp.status,
            CASE 
                WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL 
                THEN ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)
                ELSE NULL 
            END as duration_minutes,
            -- Time since check-in
            CASE 
                WHEN v.check_in IS NOT NULL AND v.check_out IS NULL
                THEN ROUND(EXTRACT(EPOCH FROM (NOW() - v.check_in)) / 60)
                ELSE NULL
            END as minutes_since_checkin
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        JOIN m_customer c ON c.id = rp.id_customer
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.visit_date::date = %s
          AND rp.status != 'Selesai'
          AND v.check_in IS NOT NULL
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY v.check_in DESC
        LIMIT %s
    """,
        (date, limit),
    )

    # Categorize by issue
    missing_checkout = []
    ready_to_complete = []

    for p in pending:
        item = {
            "visit_id": p["visit_id"],
            "road_plan_id": p["road_plan_id"],
            "customer": p["customer_name"],
            "technician": p["technician_name"],
            "check_in": p["check_in"].isoformat() if p["check_in"] else None,
            "check_out": p["check_out"].isoformat() if p["check_out"] else None,
            "status": p["status"],
            "duration_minutes": p["duration_minutes"],
            "minutes_since_checkin": p["minutes_since_checkin"],
        }

        if not p["check_out"]:
            item["issue"] = "missing_checkout"
            item["urgency"] = (
                "high" if (p["minutes_since_checkin"] or 0) > 240 else "medium"
            )
            missing_checkout.append(item)
        else:
            item["issue"] = "pending_completion"
            ready_to_complete.append(item)

    return jsonify(
        {
            "date": date,
            "missing_checkout": {
                "count": len(missing_checkout),
                "items": missing_checkout,
            },
            "ready_to_complete": {
                "count": len(ready_to_complete),
                "items": ready_to_complete,
            },
            "total_pending": len(pending),
            "generated_at": datetime.now().isoformat(),
        }
    )


@completion_gate_bp.route("/completion-gate/stats")
@require_auth
def completion_stats():
    """
    Get completion gate statistics for today.
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    stats = execute_kelava_query_single(
        """
        WITH visit_data AS (
            SELECT 
                v.id,
                rp.status,
                v.check_in,
                v.check_out,
                CASE 
                    WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL 
                    THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60
                    ELSE NULL 
                END as duration_min
            FROM t_visit v
            JOIN t_road_plan rp ON rp.id = v.id_road_plan
            WHERE rp.visit_date::date = %s
              AND COALESCE(rp.is_cancel, false) = false
        )
        SELECT 
            COUNT(*) as total_visits,
            COUNT(*) FILTER (WHERE status = 'Selesai') as completed,
            COUNT(*) FILTER (WHERE check_in IS NOT NULL AND check_out IS NULL) as missing_checkout,
            COUNT(*) FILTER (WHERE duration_min IS NOT NULL AND duration_min < 15) as too_short,
            COUNT(*) FILTER (WHERE duration_min IS NOT NULL AND duration_min > 480) as too_long,
            COUNT(*) FILTER (WHERE check_in IS NOT NULL AND status != 'Selesai') as pending_gate
        FROM visit_data
    """,
        (date,),
    )

    total = stats["total_visits"] if stats else 0
    completed = stats["completed"] if stats else 0

    return jsonify(
        {
            "date": date,
            "stats": {
                "total_visits": total,
                "completed": completed,
                "completion_rate": round(completed / total * 100, 1)
                if total > 0
                else 0,
                "missing_checkout": stats["missing_checkout"] if stats else 0,
                "duration_issues": {
                    "too_short": stats["too_short"] if stats else 0,
                    "too_long": stats["too_long"] if stats else 0,
                },
                "pending_at_gate": stats["pending_gate"] if stats else 0,
            },
            "generated_at": datetime.now().isoformat(),
        }
    )
