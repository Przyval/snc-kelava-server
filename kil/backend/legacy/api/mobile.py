"""
Mobile API — safeandcare.work
==============================
Endpoints for the SNC Flutter mobile app.
All data reads from Kelava DB; writes go to our own tables.
Requires valid JWT (all roles).
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from core.security import require_auth
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

# Photo uploads directory
UPLOAD_DIR = os.environ.get("MOBILE_UPLOAD_DIR", "/root/kil-server/uploads/visit_photos")
ALLOWED_PHOTO_EXT = {"jpg", "jpeg", "png", "heic", "heif", "webp"}
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10 MB

mobile_bp = Blueprint("mobile", __name__, url_prefix="/api/v1/mobile")


# ── Dashboard ─────────────────────────────────────────────────


@mobile_bp.route("/dashboard", methods=["GET"])
@require_auth
def dashboard():
    """Summary stats for the mobile home screen."""
    today = date.today().isoformat()

    # Visits scheduled today (from road plan)
    total_today = execute_kelava_query_single(
        "SELECT COUNT(*) AS cnt FROM t_road_plan WHERE DATE(visit_date) = %s",
        (today,),
    )

    # Currently checked in (check_in set, check_out null) — from our mobile_visits
    checked_in = execute_kelava_query_single(
        """
        SELECT COUNT(*) AS cnt FROM mobile_visits
        WHERE check_in IS NOT NULL AND check_out IS NULL
          AND DATE(check_in) = %s
        """,
        (today,),
    )

    # Completed today
    completed = execute_kelava_query_single(
        "SELECT COUNT(*) AS cnt FROM mobile_visits WHERE DATE(check_out) = %s",
        (today,),
    )

    # Pending approvals
    pending = execute_kelava_query_single(
        "SELECT COUNT(*) AS cnt FROM supervisory_actions WHERE status = 'PENDING_APPROVAL'",
    )

    # Total customers (all statuses — Kelava uses 'Place'/'Leads'/'Pelanggan')
    customers = execute_kelava_query_single(
        "SELECT COUNT(*) AS cnt FROM m_customer",
    )

    return jsonify({
        "total_visits_today": total_today["cnt"] if total_today else 0,
        "checked_in_now": checked_in["cnt"] if checked_in else 0,
        "completed_today": completed["cnt"] if completed else 0,
        "pending_approvals": pending["cnt"] if pending else 0,
        "total_customers": customers["cnt"] if customers else 0,
    })


# ── Visits ────────────────────────────────────────────────────


@mobile_bp.route("/visits/today", methods=["GET"])
@require_auth
def visits_today():
    """
    Today's road plan for the logged-in technician (by p_user_id).
    Supervisor/koordinator/admin see all technicians' plans.
    """
    today = date.today().isoformat()
    user = g.current_user

    if user.role in ("technician", "viewer") and user.p_user_id:
        rows = execute_kelava_query(
            """
            SELECT rp.id, rp.visit_date, rp.status, rp.id_customer,
                   c.name AS customer_name, c.address AS customer_address,
                   k.no_kontrak AS kontrak_no, rp.type AS visit_type,
                   mv.id AS mv_id, mv.check_in, mv.check_out, mv.remarks,
                   mv.latitude_in AS latitude, mv.longitude_in AS longitude
            FROM t_road_plan rp
            LEFT JOIN m_customer c ON c.id = rp.id_customer
            LEFT JOIN m_customer_kontrak k ON k.id = rp.id_kontrak
            LEFT JOIN mobile_visits mv ON mv.road_plan_id = rp.id
              AND mv.user_id = %s
            WHERE DATE(rp.visit_date) = %s AND rp.id_user = %s
            ORDER BY rp.visit_date
            """,
            (user.id, today, user.p_user_id),
        )
    else:
        rows = execute_kelava_query(
            """
            SELECT rp.id, rp.visit_date, rp.status, rp.id_customer,
                   c.name AS customer_name, c.address AS customer_address,
                   k.no_kontrak AS kontrak_no, rp.type AS visit_type,
                   mv.id AS mv_id, mv.check_in, mv.check_out, mv.remarks,
                   mv.latitude_in AS latitude, mv.longitude_in AS longitude,
                   pu.fullname AS technician_name
            FROM t_road_plan rp
            LEFT JOIN m_customer c ON c.id = rp.id_customer
            LEFT JOIN m_customer_kontrak k ON k.id = rp.id_kontrak
            LEFT JOIN p_user pu ON pu.id = rp.id_user
            LEFT JOIN mobile_visits mv ON mv.road_plan_id = rp.id
            WHERE DATE(rp.visit_date) = %s
            ORDER BY rp.visit_date
            """,
            (today,),
        )

    result = []
    for r in rows:
        result.append({
            "id": r["mv_id"] or r["id"],
            "road_plan_id": r["id"],
            "customer_name": r["customer_name"] or "-",
            "customer_address": r["customer_address"],
            "kontrak_no": r["kontrak_no"],
            "visit_type": r.get("visit_type"),
            "status": _visit_status(r),
            "scheduled_date": r["visit_date"].isoformat() if r["visit_date"] else None,
            "check_in": r["check_in"].isoformat() if r["check_in"] else None,
            "check_out": r["check_out"].isoformat() if r["check_out"] else None,
            "latitude": float(r["latitude"]) if r["latitude"] else None,
            "longitude": float(r["longitude"]) if r["longitude"] else None,
            "remarks": r["remarks"],
        })

    return jsonify(result)


@mobile_bp.route("/visits/schedule", methods=["GET"])
@require_auth
def visits_schedule():
    """
    Visit schedule for a given date (defaults to today).
    Query param: ?date=YYYY-MM-DD
    Returns same structure as visits/today but for any date.
    """
    target_date = request.args.get("date", date.today().isoformat())
    user = g.current_user

    if user.role in ("technician", "viewer") and user.p_user_id:
        rows = execute_kelava_query(
            """
            SELECT rp.id, rp.visit_date, rp.status, rp.id_customer,
                   c.name AS customer_name, c.address AS customer_address,
                   k.no_kontrak AS kontrak_no, rp.type AS visit_type,
                   mv.id AS mv_id, mv.check_in, mv.check_out, mv.remarks,
                   mv.latitude_in AS latitude, mv.longitude_in AS longitude,
                   mv.latitude_out, mv.longitude_out, mv.photo_count
            FROM t_road_plan rp
            LEFT JOIN m_customer c ON c.id = rp.id_customer
            LEFT JOIN m_customer_kontrak k ON k.id = rp.id_kontrak
            LEFT JOIN mobile_visits mv ON mv.road_plan_id = rp.id
              AND mv.user_id = %s
            WHERE DATE(rp.visit_date) = %s AND rp.id_user = %s
            ORDER BY rp.visit_date
            """,
            (user.id, target_date, user.p_user_id),
        )
    else:
        rows = execute_kelava_query(
            """
            SELECT rp.id, rp.visit_date, rp.status, rp.id_customer,
                   c.name AS customer_name, c.address AS customer_address,
                   k.no_kontrak AS kontrak_no, rp.type AS visit_type,
                   mv.id AS mv_id, mv.check_in, mv.check_out, mv.remarks,
                   mv.latitude_in AS latitude, mv.longitude_in AS longitude,
                   mv.latitude_out, mv.longitude_out, mv.photo_count,
                   pu.fullname AS technician_name
            FROM t_road_plan rp
            LEFT JOIN m_customer c ON c.id = rp.id_customer
            LEFT JOIN m_customer_kontrak k ON k.id = rp.id_kontrak
            LEFT JOIN p_user pu ON pu.id = rp.id_user
            LEFT JOIN mobile_visits mv ON mv.road_plan_id = rp.id
            WHERE DATE(rp.visit_date) = %s
            ORDER BY rp.visit_date
            """,
            (target_date,),
        )

    result = []
    for r in rows:
        item = {
            "id": r["mv_id"] or r["id"],
            "road_plan_id": r["id"],
            "customer_name": r["customer_name"] or "-",
            "customer_address": r["customer_address"],
            "kontrak_no": r["kontrak_no"],
            "visit_type": r.get("visit_type"),
            "status": _visit_status(r),
            "scheduled_date": r["visit_date"].isoformat() if r["visit_date"] else None,
            "check_in": r["check_in"].isoformat() if r["check_in"] else None,
            "check_out": r["check_out"].isoformat() if r["check_out"] else None,
            "latitude": float(r["latitude"]) if r["latitude"] else None,
            "longitude": float(r["longitude"]) if r["longitude"] else None,
            "remarks": r["remarks"],
            "photo_count": r.get("photo_count") or 0,
        }
        if r.get("technician_name"):
            item["technician_name"] = r["technician_name"]
        result.append(item)

    return jsonify(result)


def _visit_status(row):
    if row.get("check_out"):
        return "COMPLETED"
    if row.get("check_in"):
        return "IN_PROGRESS"
    return "SCHEDULED"


@mobile_bp.route("/visits/<int:road_plan_id>/checkin", methods=["POST"])
@require_auth
def checkin(road_plan_id):
    """Check in to a visit — creates or updates mobile_visits record."""
    user = g.current_user
    data = request.json or {}

    # Check road plan exists
    rp = execute_kelava_query_single(
        "SELECT id, id_customer FROM t_road_plan WHERE id = %s",
        (road_plan_id,),
    )
    if not rp:
        return jsonify({"error": "Road plan not found"}), 404

    # Check not already checked in
    existing = execute_kelava_query_single(
        "SELECT id, check_in FROM mobile_visits WHERE road_plan_id = %s AND user_id = %s",
        (road_plan_id, user.id),
    )
    if existing and existing["check_in"]:
        return jsonify({"error": "Already checked in"}), 409

    lat = data.get("latitude")
    lng = data.get("longitude")
    now = datetime.now(timezone.utc)

    if existing:
        execute_kelava_query(
            """
            UPDATE mobile_visits SET check_in = %s, latitude_in = %s, longitude_in = %s
            WHERE id = %s
            """,
            (now, lat, lng, existing["id"]),
        )
        visit_id = existing["id"]
    else:
        result = execute_kelava_query(
            """
            INSERT INTO mobile_visits
                (road_plan_id, user_id, customer_id, check_in, latitude_in, longitude_in, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (road_plan_id, user.id, rp["id_customer"], now, lat, lng),
        )
        visit_id = result[0]["id"]

    return jsonify({"id": visit_id, "check_in": now.isoformat(), "status": "IN_PROGRESS"})


@mobile_bp.route("/visits/<int:road_plan_id>/checkout", methods=["POST"])
@require_auth
def checkout(road_plan_id):
    """Check out from a visit."""
    user = g.current_user
    data = request.json or {}
    remarks = data.get("remarks", "")
    lat = data.get("latitude")
    lng = data.get("longitude")
    now = datetime.now(timezone.utc)

    existing = execute_kelava_query_single(
        "SELECT id, check_in FROM mobile_visits WHERE road_plan_id = %s AND user_id = %s",
        (road_plan_id, user.id),
    )
    if not existing or not existing["check_in"]:
        return jsonify({"error": "Not checked in"}), 409

    execute_kelava_query(
        """
        UPDATE mobile_visits
        SET check_out = %s, latitude_out = %s, longitude_out = %s, remarks = %s
        WHERE id = %s
        """,
        (now, lat, lng, remarks, existing["id"]),
    )

    return jsonify({"check_out": now.isoformat(), "status": "COMPLETED"})


# ── Customers ─────────────────────────────────────────────────


@mobile_bp.route("/customers", methods=["GET"])
@require_auth
def customers():
    """Customer list with visit count."""
    search = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 100)), 200)

    if search:
        rows = execute_kelava_query(
            """
            SELECT c.id, c.code, c.name, c.address, c.phone1 AS phone,
                   c.contact_person_name AS contact_person, c.status,
                   s.name AS segment,
                   COUNT(rp.id) AS total_visits
            FROM m_customer c
            LEFT JOIN m_customer_segment s ON s.id = c.id_segment
            LEFT JOIN t_road_plan rp ON rp.id_customer = c.id
            WHERE LOWER(c.name) LIKE %s OR LOWER(c.code) LIKE %s
            GROUP BY c.id, c.code, c.name, c.address, c.phone1,
                     c.contact_person_name, c.status, s.name
            ORDER BY c.name
            LIMIT %s
            """,
            (f"%{search.lower()}%", f"%{search.lower()}%", limit),
        )
    else:
        rows = execute_kelava_query(
            """
            SELECT c.id, c.code, c.name, c.address, c.phone1 AS phone,
                   c.contact_person_name AS contact_person, c.status,
                   s.name AS segment,
                   COUNT(rp.id) AS total_visits
            FROM m_customer c
            LEFT JOIN m_customer_segment s ON s.id = c.id_segment
            LEFT JOIN t_road_plan rp ON rp.id_customer = c.id
            GROUP BY c.id, c.code, c.name, c.address, c.phone1,
                     c.contact_person_name, c.status, s.name
            ORDER BY c.name
            LIMIT %s
            """,
            (limit,),
        )

    return jsonify([
        {
            "id": r["id"],
            "code": r["code"] or "",
            "name": r["name"] or "-",
            "address": r["address"],
            "phone": r["phone"],
            "contact_person": r["contact_person"],
            "segment": r["segment"],
            "status": r["status"],
            "total_visits": r["total_visits"],
        }
        for r in rows
    ])


# ── Customer Detail ──────────────────────────────────────────


@mobile_bp.route("/customers/<int:customer_id>", methods=["GET"])
@require_auth
def customer_detail(customer_id):
    """Customer detail with contracts and recent visit history."""
    # Basic info
    cust = execute_kelava_query_single(
        """
        SELECT c.id, c.code, c.name, c.address, c.phone1 AS phone,
               c.contact_person_name AS contact_person, c.status,
               s.name AS segment
        FROM m_customer c
        LEFT JOIN m_customer_segment s ON s.id = c.id_segment
        WHERE c.id = %s
        """,
        (customer_id,),
    )
    if not cust:
        return jsonify({"error": "Customer not found"}), 404

    # Active contracts
    contracts = execute_kelava_query(
        """
        SELECT ck.id, ck.no_kontrak, ck.start_date, ck.end_date,
               ck.is_active
        FROM m_customer_kontrak ck
        WHERE ck.id_customer = %s
        ORDER BY ck.end_date DESC NULLS LAST
        LIMIT 5
        """,
        (customer_id,),
    )

    # Recent visit history (last 20)
    visits = execute_kelava_query(
        """
        SELECT rp.id AS road_plan_id, rp.visit_date,
               v.check_in, v.check_out, v.realization_date,
               u.fullname AS technician_name,
               rp.status AS plan_status,
               v.remarks
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        LEFT JOIN p_user u ON u.id = rp.id_user
        WHERE rp.id_customer = %s
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY rp.visit_date DESC, v.check_in DESC NULLS LAST
        LIMIT 20
        """,
        (customer_id,),
    )

    # Visit summary stats
    stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(DISTINCT rp.id) AS total_visits,
            COUNT(DISTINCT CASE WHEN v.check_out IS NOT NULL THEN rp.id END) AS completed,
            COUNT(DISTINCT rp.id_user) AS unique_technicians,
            MIN(rp.visit_date)::text AS first_visit,
            MAX(rp.visit_date)::text AS last_visit
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_customer = %s
          AND COALESCE(rp.is_cancel, false) = false
        """,
        (customer_id,),
    )

    def _fmt_row(r):
        d = dict(r)
        for k, val in d.items():
            if hasattr(val, "isoformat"):
                d[k] = val.isoformat()
        return d

    def _fmt_visit(r):
        d = _fmt_row(r)
        # Derive visit_status in Python
        if d.get("check_out"):
            d["visit_status"] = "COMPLETED"
        elif d.get("check_in"):
            d["visit_status"] = "IN_PROGRESS"
        else:
            d["visit_status"] = "SCHEDULED"
        return d

    def _fmt_contract(r):
        d = _fmt_row(r)
        d["status"] = "active" if d.get("is_active") else "expired"
        return d

    return jsonify({
        "customer": _fmt_row(cust),
        "contracts": [_fmt_contract(c) for c in contracts],
        "visits": [_fmt_visit(v) for v in visits],
        "stats": _fmt_row(stats) if stats else {},
    })


# ── Approvals ─────────────────────────────────────────────────


@mobile_bp.route("/approvals", methods=["GET"])
@require_auth
def list_approvals():
    """Pending supervisory actions awaiting koordinator approval."""
    rows = execute_kelava_query(
        """
        SELECT sa.id, sa.action_type, sa.status, sa.trigger_reason AS description,
               sa.scheduled_date, sa.created_at,
               sa.created_by, sa.target_technician_id,
               c.name AS customer_name
        FROM supervisory_actions sa
        LEFT JOIN m_customer c ON c.id = sa.target_customer_id
        WHERE sa.status = 'PENDING_APPROVAL'
        ORDER BY sa.created_at DESC
        """,
    )

    # Fetch user names from local enterprise DB
    user_ids = set()
    for r in rows:
        if r.get("created_by"):
            user_ids.add(r["created_by"])
        if r.get("target_technician_id"):
            user_ids.add(r["target_technician_id"])
    names = {}
    if user_ids:
        name_rows = execute_kelava_query(
            f"SELECT id, full_name FROM enterprise_users WHERE id = ANY(ARRAY[{','.join(str(i) for i in user_ids)}])"
        )
        names = {r["id"]: r["full_name"] for r in name_rows}

    return jsonify([
        {
            "id": r["id"],
            "action_type": r["action_type"],
            "status": r["status"],
            "description": r["description"],
            "scheduled_date": r["scheduled_date"].isoformat()
                if hasattr(r.get("scheduled_date"), "isoformat")
                else r.get("scheduled_date"),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "created_by_name": names.get(r.get("created_by"), "-"),
            "technician_name": names.get(r.get("target_technician_id"), "-"),
            "customer_name": r["customer_name"],
        }
        for r in rows
    ])


@mobile_bp.route("/approvals/<int:action_id>/approve", methods=["POST"])
@require_auth
def approve_action(action_id):
    """Koordinator approves a pending action."""
    user = g.current_user
    if user.role not in ("koordinator", "admin"):
        return jsonify({"error": "Koordinator or admin required"}), 403

    execute_kelava_query(
        """
        UPDATE supervisory_actions
        SET status = 'SCHEDULED', approved_by = %s, approved_at = NOW()
        WHERE id = %s AND status = 'PENDING_APPROVAL'
        """,
        (user.id, action_id),
    )
    return jsonify({"status": "SCHEDULED"})


@mobile_bp.route("/approvals/<int:action_id>/reject", methods=["POST"])
@require_auth
def reject_action(action_id):
    """Koordinator rejects a pending action."""
    user = g.current_user
    if user.role not in ("koordinator", "admin"):
        return jsonify({"error": "Koordinator or admin required"}), 403

    data = request.json or {}
    reason = data.get("reason", "")

    execute_kelava_query(
        """
        UPDATE supervisory_actions
        SET status = 'CANCELLED', rejection_reason = %s,
            approved_by = %s, approved_at = NOW()
        WHERE id = %s AND status = 'PENDING_APPROVAL'
        """,
        (reason, user.id, action_id),
    )
    return jsonify({"status": "CANCELLED"})


# ── Visit Photos ──────────────────────────────────────────────


@mobile_bp.route("/visits/<int:road_plan_id>/photos", methods=["POST"])
@require_auth
def upload_visit_photos(road_plan_id):
    """
    Upload photo evidence for a visit (check-in or check-out).
    Accepts multipart/form-data with field 'photos' (multiple files).
    Optional field 'stage' = 'checkin' | 'checkout'.
    """
    user = g.current_user
    stage = request.form.get("stage", "evidence")

    # Verify visit exists
    visit = execute_kelava_query_single(
        "SELECT id FROM mobile_visits WHERE road_plan_id = %s AND user_id = %s",
        (road_plan_id, user.id),
    )
    if not visit:
        return jsonify({"error": "Visit not found"}), 404

    visit_id = visit["id"]
    files = request.files.getlist("photos")
    if not files:
        return jsonify({"error": "No photos provided"}), 400

    # Ensure upload directory exists
    visit_dir = os.path.join(UPLOAD_DIR, str(visit_id))
    os.makedirs(visit_dir, exist_ok=True)

    saved = []
    for f in files:
        ext = (f.filename or "").rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_PHOTO_EXT:
            continue

        # Check file size
        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        if size > MAX_PHOTO_SIZE:
            continue

        filename = f"{stage}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(visit_dir, secure_filename(filename))
        f.save(filepath)
        saved.append(filename)

    # Update photo count
    if saved:
        execute_kelava_query(
            "UPDATE mobile_visits SET photo_count = COALESCE(photo_count, 0) + %s WHERE id = %s",
            (len(saved), visit_id),
        )

    return jsonify({
        "visit_id": visit_id,
        "uploaded": len(saved),
        "filenames": saved,
    })


@mobile_bp.route("/visits/<int:road_plan_id>/photos", methods=["GET"])
@require_auth
def list_visit_photos(road_plan_id):
    """List all photos for a visit (mobile-uploaded + Kelava originals)."""
    photos = []

    # 1. Mobile-uploaded photos (from disk)
    visit = execute_kelava_query_single(
        "SELECT id FROM mobile_visits WHERE road_plan_id = %s",
        (road_plan_id,),
    )
    if visit:
        visit_dir = os.path.join(UPLOAD_DIR, str(visit["id"]))
        if os.path.isdir(visit_dir):
            for fname in sorted(os.listdir(visit_dir)):
                ext = fname.rsplit(".", 1)[-1].lower()
                if ext in ALLOWED_PHOTO_EXT:
                    stage = fname.split("_")[0] if "_" in fname else "evidence"
                    photos.append({
                        "source": "mobile",
                        "filename": fname,
                        "stage": stage,
                        "url": f"/api/v1/mobile/visits/{road_plan_id}/photos/{fname}",
                    })

    # 2. Kelava original photos (from t_road_plan_foto)
    try:
        kelava_photos = execute_kelava_query(
            "SELECT id, path FROM t_road_plan_foto WHERE id_road_plan = %s ORDER BY id",
            (road_plan_id,),
        )
        for p in kelava_photos:
            photos.append({
                "source": "kelava",
                "id": p["id"],
                "stage": "evidence",
                "url": f"/api/v1/enterprise/verification/photo-proxy?path={p['path']}&size=medium",
                "thumb_url": f"/api/v1/enterprise/verification/photo-proxy?path={p['path']}&size=thumb",
            })
    except Exception:
        pass

    return jsonify({"photos": photos, "count": len(photos)})


@mobile_bp.route("/visits/<int:road_plan_id>/photos/<path:filename>", methods=["GET"])
def serve_visit_photo(road_plan_id, filename):
    """Serve a mobile-uploaded photo file."""
    # Find visit by road_plan_id
    visit = execute_kelava_query_single(
        "SELECT id FROM mobile_visits WHERE road_plan_id = %s",
        (road_plan_id,),
    )
    if not visit:
        return jsonify({"error": "Not found"}), 404

    visit_dir = os.path.join(UPLOAD_DIR, str(visit["id"]))
    safe_name = secure_filename(filename)
    filepath = os.path.join(visit_dir, safe_name)

    if not os.path.isfile(filepath):
        return jsonify({"error": "Photo not found"}), 404

    return send_from_directory(visit_dir, safe_name, max_age=86400)


# ── Personal Performance Stats ──────────────────────────────


@mobile_bp.route("/my-performance", methods=["GET"])
@require_auth
def my_performance():
    """Personal performance stats for the logged-in technician."""
    user = g.current_user
    p_user_id = user.p_user_id

    # If no linked p_user_id, try to look it up
    if not p_user_id:
        eu = execute_kelava_query_single(
            "SELECT p_user_id FROM enterprise_users WHERE id = %s",
            (user.id,),
        )
        p_user_id = eu["p_user_id"] if eu and eu.get("p_user_id") else None

    if not p_user_id:
        return jsonify({"error": "No linked technician account"}), 400

    today = date.today()
    # Current week (Monday-based)
    week_start = today - timedelta(days=today.weekday())
    # Current month
    month_start = today.replace(day=1)
    # Previous month
    if today.month == 1:
        prev_month_start = today.replace(year=today.year - 1, month=12, day=1)
    else:
        prev_month_start = today.replace(month=today.month - 1, day=1)
    prev_month_end = month_start - timedelta(days=1)

    # This week's stats
    week_stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(DISTINCT rp.id) AS planned,
            COUNT(DISTINCT CASE WHEN v.check_out IS NOT NULL THEN rp.id END) AS completed,
            COUNT(DISTINCT CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NULL THEN rp.id END) AS in_progress,
            ROUND(AVG(CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 END)::numeric, 0) AS avg_duration_min,
            COUNT(DISTINCT rp.visit_date::date) AS days_worked
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_user = %s
          AND rp.visit_date::date >= %s AND rp.visit_date::date <= %s
          AND COALESCE(rp.is_cancel, false) = false
        """,
        (p_user_id, week_start.isoformat(), today.isoformat()),
    )

    # This month's stats
    month_stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(DISTINCT rp.id) AS planned,
            COUNT(DISTINCT CASE WHEN v.check_out IS NOT NULL THEN rp.id END) AS completed,
            ROUND(AVG(CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 END)::numeric, 0) AS avg_duration_min,
            COUNT(DISTINCT rp.visit_date::date) AS days_worked
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_user = %s
          AND rp.visit_date::date >= %s AND rp.visit_date::date <= %s
          AND COALESCE(rp.is_cancel, false) = false
        """,
        (p_user_id, month_start.isoformat(), today.isoformat()),
    )

    # Previous month (for comparison)
    prev_stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(DISTINCT rp.id) AS planned,
            COUNT(DISTINCT CASE WHEN v.check_out IS NOT NULL THEN rp.id END) AS completed
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_user = %s
          AND rp.visit_date::date >= %s AND rp.visit_date::date <= %s
          AND COALESCE(rp.is_cancel, false) = false
        """,
        (p_user_id, prev_month_start.isoformat(), prev_month_end.isoformat()),
    )

    # Recent visits (last 7 days with check-in/out times)
    recent = execute_kelava_query(
        """
        SELECT rp.visit_date, c.name AS customer_name,
               v.check_in, v.check_out,
               CASE WHEN v.check_out IS NOT NULL THEN 'COMPLETED'
                    WHEN v.check_in IS NOT NULL THEN 'IN_PROGRESS'
                    ELSE 'SCHEDULED' END AS status
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        LEFT JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.id_user = %s
          AND rp.visit_date::date >= %s
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY rp.visit_date DESC, v.check_in DESC NULLS LAST
        LIMIT 15
        """,
        (p_user_id, (today - timedelta(days=7)).isoformat()),
    )

    def _safe(row):
        if not row:
            return {}
        d = dict(row)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d

    # Compute completion rates
    def _rate(stats):
        if not stats or not stats["planned"]:
            return 0
        return round(stats["completed"] / stats["planned"] * 100)

    return jsonify({
        "week": {
            **_safe(week_stats),
            "completion_rate": _rate(week_stats),
            "start": week_start.isoformat(),
            "end": today.isoformat(),
        },
        "month": {
            **_safe(month_stats),
            "completion_rate": _rate(month_stats),
            "label": today.strftime("%B %Y"),
        },
        "prev_month": {
            **_safe(prev_stats),
            "completion_rate": _rate(prev_stats),
            "label": prev_month_start.strftime("%B %Y"),
        },
        "recent_visits": [_safe(r) for r in recent],
    })
