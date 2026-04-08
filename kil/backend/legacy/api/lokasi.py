"""
Lokasi (Customer) API — Kelava-compatible
==========================================
Paginated customer listing with filters, matching Kelava mCustomer/index.
"""

from flask import Blueprint, jsonify, request

from core.security import require_auth
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

lokasi_bp = Blueprint("lokasi", __name__)


@lokasi_bp.route("/lokasi", methods=["GET"])
@require_auth
def lokasi_list():
    """Paginated customer list with filters."""
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(10, int(request.args.get("per_page", 25))))
    name = request.args.get("name", "").strip()
    address = request.args.get("address", "").strip()
    pic = request.args.get("pic", "").strip()
    owner = request.args.get("owner", "").strip()
    phone = request.args.get("phone", "").strip()

    where = ["COALESCE(c.is_deleted, false) = false"]
    params = []

    if name:
        where.append("LOWER(c.name) LIKE %s")
        params.append(f"%{name.lower()}%")
    if address:
        where.append("LOWER(c.address) LIKE %s")
        params.append(f"%{address.lower()}%")
    if pic:
        where.append("LOWER(c.contact_person_name) LIKE %s")
        params.append(f"%{pic.lower()}%")
    if owner:
        where.append("LOWER(o.name) LIKE %s")
        params.append(f"%{owner.lower()}%")
    if phone:
        where.append("(c.phone1 LIKE %s OR c.contact_person_phone LIKE %s)")
        params.append(f"%{phone}%")
        params.append(f"%{phone}%")

    where_sql = " AND ".join(where)

    # Count
    count_row = execute_kelava_query_single(
        f"SELECT COUNT(*) AS cnt FROM m_customer c LEFT JOIN m_customer o ON o.id = c.id_owner WHERE {where_sql}",
        tuple(params),
    )
    total = count_row["cnt"] if count_row else 0
    total_pages = max(1, (total + per_page - 1) // per_page)
    offset = (page - 1) * per_page

    # Data
    rows = execute_kelava_query(
        f"""
        SELECT c.id, c.name, c.address, c.contact_person_name AS nama_pic,
               c.phone1 AS telepon_pic, o.name AS owner
        FROM m_customer c
        LEFT JOIN m_customer o ON o.id = c.id_owner
        WHERE {where_sql}
        ORDER BY c.name
        LIMIT %s OFFSET %s
        """,
        tuple(params) + (per_page, offset),
    )

    return jsonify({
        "records": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    })


@lokasi_bp.route("/lokasi/filters", methods=["GET"])
@require_auth
def lokasi_filters():
    """Distinct values for filter dropdowns."""
    owners = execute_kelava_query("""
        SELECT DISTINCT o.name
        FROM m_customer c
        JOIN m_customer o ON o.id = c.id_owner
        WHERE COALESCE(c.is_deleted, false) = false AND c.id_owner IS NOT NULL
        ORDER BY o.name
    """)
    pics = execute_kelava_query("""
        SELECT DISTINCT contact_person_name AS name
        FROM m_customer
        WHERE COALESCE(is_deleted, false) = false
          AND contact_person_name IS NOT NULL AND contact_person_name != ''
        ORDER BY contact_person_name
    """)
    return jsonify({
        "owners": [r["name"] for r in owners],
        "pics": [r["name"] for r in pics],
    })
