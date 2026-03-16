"""
Resource Calendar API - Dispatch View

Provides endpoints for:
- Weekly/daily schedule grid (technician × time)
- Available slots per technician
- Reschedule with audit trail
- Lock schedule for SPV approval
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

calendar_bp = Blueprint("calendar", __name__, url_prefix="/api/v1/enterprise")


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
                "total_jobs": len(jobs),
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
