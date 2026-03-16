"""
Exception Queue API - Operational Issue Tracking

Provides endpoints for:
- Full exception queue with categorized issues
- Exception resolution with audit trail
- Audit log of resolved exceptions

Exception Types:
- overdue_visit: Visit planned but not executed (past date)
- missing_checkout: Check-in > 4hr ago, no check-out
- gps_anomaly: Check-in GPS far from customer location
- missing_evidence: Status "complete" but no photos
- late_arrival: Check-in > 20 min after scheduled
- duration_anomaly: Duration < 15 min or > 8 hours
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

exceptions_bp = Blueprint("exceptions", __name__, url_prefix="/api/v1/enterprise")


@exceptions_bp.route("/exceptions/queue")
@require_auth
def exceptions_queue():
    """
    Get full exception queue - all issues requiring attention.
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    include_resolved = request.args.get("include_resolved", "false").lower() == "true"

    exceptions = []

    # 1) Overdue Visits (planned before today, not completed)
    overdue = execute_kelava_query(
        """
        SELECT 
            rp.id as road_plan_id,
            rp.visit_date,
            rp.status,
            c.name as customer_name,
            c.address as customer_address,
            u.fullname as technician_name,
            u.id as technician_id,
            CURRENT_DATE - rp.visit_date::date as days_overdue
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.visit_date::date < %s
          AND rp.status NOT IN ('Selesai', 'Batal')
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY rp.visit_date DESC
        LIMIT 50
    """,
        (date,),
    )

    for o in overdue:
        exceptions.append(
            {
                "id": f"overdue_{o['road_plan_id']}",
                "type": "overdue_visit",
                "severity": "high" if o["days_overdue"] > 3 else "medium",
                "label": f"Overdue: {o['customer_name']}",
                "description": f"{o['days_overdue']} days overdue",
                "road_plan_id": o["road_plan_id"],
                "customer": o["customer_name"],
                "technician": o["technician_name"],
                "technician_id": o["technician_id"],
                "visit_date": o["visit_date"].strftime("%Y-%m-%d")
                if o["visit_date"]
                else None,
                "action_url": f"/enterprise/operations/{o['road_plan_id']}",
                "suggested_action": "Reschedule or mark as cancelled",
            }
        )

    # 2) Missing Check-out (today, checked in > 4 hours ago, no checkout)
    missing_checkout = execute_kelava_query(
        """
        SELECT 
            v.id as visit_id,
            rp.id as road_plan_id,
            c.name as customer_name,
            u.fullname as technician_name,
            u.id as technician_id,
            v.check_in,
            ROUND(EXTRACT(EPOCH FROM (NOW() - v.check_in)) / 60) as minutes_since_checkin
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        JOIN m_customer c ON c.id = rp.id_customer
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.visit_date::date = %s
          AND v.check_in IS NOT NULL
          AND v.check_out IS NULL
          AND v.check_in < NOW() - INTERVAL '4 hours'
        ORDER BY v.check_in
        LIMIT 30
    """,
        (date,),
    )

    for m in missing_checkout:
        hours = (
            round(m["minutes_since_checkin"] / 60, 1)
            if m["minutes_since_checkin"]
            else 0
        )
        exceptions.append(
            {
                "id": f"missing_checkout_{m['visit_id']}",
                "type": "missing_checkout",
                "severity": "high",
                "label": f"Missing checkout: {m['customer_name']}",
                "description": f"Checked in {hours}hrs ago, no checkout",
                "visit_id": m["visit_id"],
                "road_plan_id": m["road_plan_id"],
                "customer": m["customer_name"],
                "technician": m["technician_name"],
                "technician_id": m["technician_id"],
                "check_in": m["check_in"].isoformat() if m["check_in"] else None,
                "action_url": f"/enterprise/operations/{m['road_plan_id']}",
                "suggested_action": "Contact technician or force checkout",
            }
        )

    # 3) Duration Anomalies (completed visits with suspicious duration)
    duration_issues = execute_kelava_query(
        """
        SELECT 
            v.id as visit_id,
            rp.id as road_plan_id,
            c.name as customer_name,
            u.fullname as technician_name,
            u.id as technician_id,
            v.check_in,
            v.check_out,
            ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60) as duration_min
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        JOIN m_customer c ON c.id = rp.id_customer
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.visit_date::date = %s
          AND v.check_in IS NOT NULL
          AND v.check_out IS NOT NULL
          AND (
              EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 < 15
              OR EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 > 480
          )
        LIMIT 30
    """,
        (date,),
    )

    for d in duration_issues:
        dur = d["duration_min"]
        is_short = dur < 15
        exceptions.append(
            {
                "id": f"duration_{d['visit_id']}",
                "type": "duration_anomaly",
                "severity": "medium" if is_short else "low",
                "label": f"Duration issue: {d['customer_name']}",
                "description": f"{'Too short' if is_short else 'Too long'}: {dur} min",
                "visit_id": d["visit_id"],
                "road_plan_id": d["road_plan_id"],
                "customer": d["customer_name"],
                "technician": d["technician_name"],
                "technician_id": d["technician_id"],
                "duration_min": dur,
                "action_url": f"/enterprise/operations/{d['road_plan_id']}",
                "suggested_action": "Review visit quality"
                if is_short
                else "Verify work completed",
            }
        )

    # 4) Technicians with high pending count (> 5 pending today)
    overloaded_techs = execute_kelava_query(
        """
        SELECT 
            u.id,
            u.fullname as name,
            COUNT(rp.id) as pending_count
        FROM p_user u
        JOIN t_road_plan rp ON rp.id_user = u.id
        WHERE rp.visit_date::date = %s
          AND rp.status IN ('Baru', 'Requested')
          AND COALESCE(rp.is_cancel, false) = false
        GROUP BY u.id, u.fullname
        HAVING COUNT(rp.id) > 5
        ORDER BY pending_count DESC
        LIMIT 10
    """,
        (date,),
    )

    for t in overloaded_techs:
        exceptions.append(
            {
                "id": f"overload_{t['id']}",
                "type": "technician_overload",
                "severity": "medium",
                "label": f"Overloaded: {t['name']}",
                "description": f"{t['pending_count']} pending visits today",
                "technician": t["name"],
                "technician_id": t["id"],
                "pending_count": t["pending_count"],
                "action_url": f"/enterprise/technicians/{t['id']}",
                "suggested_action": "Reassign some visits",
            }
        )

    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    exceptions.sort(key=lambda x: severity_order.get(x["severity"], 3))

    # Count by type
    by_type = {}
    for e in exceptions:
        t = e["type"]
        by_type[t] = by_type.get(t, 0) + 1

    return jsonify(
        {
            "date": date,
            "exceptions": exceptions,
            "summary": {
                "total": len(exceptions),
                "by_type": by_type,
                "high_severity": len(
                    [e for e in exceptions if e["severity"] == "high"]
                ),
                "medium_severity": len(
                    [e for e in exceptions if e["severity"] == "medium"]
                ),
                "low_severity": len([e for e in exceptions if e["severity"] == "low"]),
            },
            "generated_at": datetime.now().isoformat(),
        }
    )


@exceptions_bp.route("/exceptions/by-technician")
@require_auth
def exceptions_by_technician():
    """
    Get exception counts grouped by technician.
    Useful for identifying problem technicians.
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    days = int(request.args.get("days", 7))
    start_date = (
        datetime.strptime(date, "%Y-%m-%d") - timedelta(days=days - 1)
    ).strftime("%Y-%m-%d")

    # Get technicians with issues
    tech_issues = execute_kelava_query(
        """
        WITH tech_stats AS (
            SELECT 
                u.id,
                u.fullname as name,
                COUNT(DISTINCT rp.id) as total_visits,
                COUNT(DISTINCT CASE 
                    WHEN rp.visit_date::date < CURRENT_DATE 
                    AND rp.status NOT IN ('Selesai', 'Batal') 
                    THEN rp.id 
                END) as overdue,
                COUNT(DISTINCT CASE 
                    WHEN v.check_in IS NOT NULL AND v.check_out IS NULL 
                    AND v.check_in < NOW() - INTERVAL '4 hours' 
                    THEN v.id 
                END) as missing_checkout,
                COUNT(DISTINCT CASE 
                    WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                    AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 < 15 
                    THEN v.id 
                END) as too_short
            FROM p_user u
            JOIN t_road_plan rp ON rp.id_user = u.id
            LEFT JOIN t_visit v ON v.id_road_plan = rp.id
            WHERE rp.visit_date::date BETWEEN %s AND %s
              AND COALESCE(rp.is_cancel, false) = false
            GROUP BY u.id, u.fullname
        )
        SELECT * FROM tech_stats
        WHERE overdue > 0 OR missing_checkout > 0 OR too_short > 0
        ORDER BY (overdue + missing_checkout + too_short) DESC
        LIMIT 20
    """,
        (start_date, date),
    )

    technicians = []
    for t in tech_issues:
        issue_count = t["overdue"] + t["missing_checkout"] + t["too_short"]
        technicians.append(
            {
                "id": t["id"],
                "name": t["name"],
                "total_visits": t["total_visits"],
                "issues": {
                    "overdue": t["overdue"],
                    "missing_checkout": t["missing_checkout"],
                    "too_short": t["too_short"],
                },
                "issue_count": issue_count,
                "issue_rate": round(issue_count / t["total_visits"] * 100, 1)
                if t["total_visits"] > 0
                else 0,
            }
        )

    return jsonify(
        {
            "period": {"start": start_date, "end": date, "days": days},
            "technicians": technicians,
            "generated_at": datetime.now().isoformat(),
        }
    )


@exceptions_bp.route("/exceptions/summary")
@require_auth
def exceptions_summary():
    """
    Get exception summary for dashboard widget.
    """
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    # Count each type
    overdue = execute_kelava_query_single(
        """
        SELECT COUNT(*) as count
        FROM t_road_plan rp
        WHERE rp.visit_date::date < %s
          AND rp.status NOT IN ('Selesai', 'Batal')
          AND COALESCE(rp.is_cancel, false) = false
    """,
        (date,),
    )

    missing_checkout = execute_kelava_query_single(
        """
        SELECT COUNT(*) as count
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE rp.visit_date::date = %s
          AND v.check_in IS NOT NULL
          AND v.check_out IS NULL
          AND v.check_in < NOW() - INTERVAL '4 hours'
    """,
        (date,),
    )

    duration_issues = execute_kelava_query_single(
        """
        SELECT COUNT(*) as count
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE rp.visit_date::date = %s
          AND v.check_in IS NOT NULL AND v.check_out IS NOT NULL
          AND (
              EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 < 15
              OR EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 > 480
          )
    """,
        (date,),
    )

    overdue_count = overdue["count"] if overdue else 0
    missing_count = missing_checkout["count"] if missing_checkout else 0
    duration_count = duration_issues["count"] if duration_issues else 0
    total = overdue_count + missing_count + duration_count

    return jsonify(
        {
            "date": date,
            "summary": {
                "total": total,
                "overdue_visits": overdue_count,
                "missing_checkout": missing_count,
                "duration_issues": duration_count,
            },
            "has_critical": missing_count > 0 or overdue_count > 10,
            "generated_at": datetime.now().isoformat(),
        }
    )
