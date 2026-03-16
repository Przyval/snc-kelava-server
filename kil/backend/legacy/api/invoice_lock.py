"""
Invoice Lock API - Contract-level Validation
===========================================
Prevents invoicing if operational evidence is incomplete.
Enforces the "Zero Missing Units" discipline.
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

invoice_lock_bp = Blueprint("invoice_lock", __name__, url_prefix="/api/v1/enterprise")


@invoice_lock_bp.route("/invoice-lock/contracts")
@require_auth
def list_contract_readiness():
    """
    List contracts with their readiness for invoicing based on visit execution proof.
    """
    limit = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))

    # Get active contracts with visit counts
    contracts = execute_kelava_query(
        """
        SELECT 
            mk.id,
            mk.no_kontrak,
            c.name as customer_name,
            mk.start_date,
            mk.end_date,
            COUNT(rp.id) as total_jobs,
            COUNT(rp.id) FILTER (WHERE rp.status = 'Selesai') as completed_jobs
        FROM m_customer_kontrak mk
        JOIN m_customer c ON mk.id_customer = c.id
        LEFT JOIN t_road_plan rp ON rp.id_kontrak = mk.id
        WHERE mk.is_active = 'YES'
        GROUP BY mk.id, mk.no_kontrak, c.name, mk.start_date, mk.end_date
        HAVING COUNT(rp.id) > 0
        ORDER BY mk.end_date DESC
        LIMIT %s OFFSET %s
    """,
        (limit, offset),
    )

    contract_status = []
    for k in contracts:
        # Check for missing evidence in completed jobs
        evidence = execute_kelava_query_single(
            """
            WITH completed_visits AS (
                SELECT v.id
                FROM t_visit v
                JOIN t_road_plan rp ON v.id_road_plan = rp.id
                WHERE rp.id_kontrak = %s AND rp.status = 'Selesai'
            ),
            photo_counts AS (
                SELECT vd.id_visit, COUNT(*) as count
                FROM t_visit_data vd
                JOIN completed_visits cv ON vd.id_visit = cv.id
                WHERE (
                    (vd.foto_display IS NOT NULL AND vd.foto_display != '')
                    OR (vd.foto_kompetitor IS NOT NULL AND vd.foto_kompetitor != '')
                    OR (vd.foto_pengunjung IS NOT NULL AND vd.foto_pengunjung != '')
                )
                GROUP BY vd.id_visit
            )
            SELECT 
                COUNT(*) as total_completed,
                COUNT(*) FILTER (WHERE id NOT IN (SELECT id_visit FROM photo_counts)) as missing_photos
            FROM completed_visits
        """,
            (k["id"],),
        )

        missing_photos = evidence["missing_photos"] if evidence else 0
        all_completed = (k["total_jobs"] == k["completed_jobs"]) and k["total_jobs"] > 0

        is_locked = not all_completed or missing_photos > 0

        reasons = []
        if k["total_jobs"] > k["completed_jobs"]:
            reasons.append(
                f"{k['total_jobs'] - k['completed_jobs']} jobs still pending/in-progress"
            )
        if missing_photos > 0:
            reasons.append(f"{missing_photos} visits missing photo evidence")

        contract_status.append(
            {
                "id": k["id"],
                "no_kontrak": k["no_kontrak"],
                "customer": k["customer_name"],
                "period": {
                    "start": k["start_date"].isoformat() if k["start_date"] else None,
                    "end": k["end_date"].isoformat() if k["end_date"] else None,
                },
                "stats": {
                    "total": k["total_jobs"],
                    "completed": k["completed_jobs"],
                    "missing_photos": missing_photos,
                },
                "is_locked": is_locked,
                "reasons": reasons,
                "status": "Ready" if not is_locked else "Blocked",
            }
        )

    return jsonify(
        {
            "contracts": contract_status,
            "count": len(contract_status),
            "generated_at": datetime.now().isoformat(),
        }
    )


@invoice_lock_bp.route("/invoice-lock/contracts/<int:contract_id>/readiness")
@require_auth
def contract_readiness_detail(contract_id):
    """
    Detailed checklist of why a contract is locked or ready for invoicing.
    """
    contract = execute_kelava_query_single(
        """
        SELECT mk.id, mk.no_kontrak, c.name as customer_name
        FROM m_customer_kontrak mk
        JOIN m_customer c ON mk.id_customer = c.id
        WHERE mk.id = %s
    """,
        (contract_id,),
    )

    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    # Get all jobs for this contract
    jobs = execute_kelava_query(
        """
        SELECT 
            rp.id,
            rp.visit_date,
            rp.status,
            rp.type,
            v.check_in,
            v.check_out,
            (
                SELECT COUNT(*) 
                FROM t_visit_data vd 
                WHERE vd.id_visit = v.id 
                AND (
                    (vd.foto_display IS NOT NULL AND vd.foto_display != '')
                    OR (vd.foto_kompetitor IS NOT NULL AND vd.foto_kompetitor != '')
                    OR (vd.foto_pengunjung IS NOT NULL AND vd.foto_pengunjung != '')
                )
            ) as photo_count
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_kontrak = %s
        ORDER BY rp.visit_date DESC
    """,
        (contract_id,),
    )

    checklist = []
    for j in jobs:
        issues = []
        if j["status"] != "Selesai":
            issues.append("Job not completed")
        elif not j["check_in"] or not j["check_out"]:
            issues.append("Missing GPS logs")
        elif j["photo_count"] == 0:
            issues.append("Missing photo evidence")

        checklist.append(
            {
                "id": j["id"],
                "date": j["visit_date"].strftime("%Y-%m-%d")
                if j["visit_date"]
                else None,
                "status": j["status"],
                "type": j["type"],
                "has_gps": bool(j["check_in"] and j["check_out"]),
                "photos": j["photo_count"],
                "passed": len(issues) == 0,
                "issues": issues,
            }
        )

    is_ready = all(item["passed"] for item in checklist)

    return jsonify(
        {
            "contract": contract,
            "is_ready": is_ready,
            "checklist": checklist,
            "summary": {
                "total_items": len(checklist),
                "passed_items": sum(1 for i in checklist if i["passed"]),
                "failed_items": sum(1 for i in checklist if not i["passed"]),
            },
        }
    )
