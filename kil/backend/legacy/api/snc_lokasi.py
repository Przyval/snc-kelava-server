"""
Lokasi Master (snc_clients) CRUD API.

GET    /snc-lokasi               — list with search/filter
GET    /snc-lokasi/<id>          — detail + audit log + activity stats
POST   /snc-lokasi               — create new customer
PUT    /snc-lokasi/<id>          — update (partial)
DELETE /snc-lokasi/<id>          — soft delete (set is_active=false)
POST   /snc-lokasi/<id>/reactivate — un-hide

Berbeda dengan lokasi.py (Kelava browse): ini manage snc_clients local
yang dipakai scheduler.
"""

import json
import re
from datetime import date

from flask import Blueprint, g, jsonify, request

from kil.backend.core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

snc_lokasi_bp = Blueprint("snc_lokasi", __name__, url_prefix="/api/v1/enterprise")


def _require_koordinator_or_admin():
    user = getattr(g, "current_user", None) or getattr(request, "_jwt_user", {})
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
    uid = user.get("id") if isinstance(user, dict) else getattr(user, "user_id", 0)
    if role not in ("admin", "koordinator"):
        return None, (jsonify({
            "error": "Forbidden",
            "message": "Hanya admin atau koordinator yang bisa ubah data ini."
        }), 403)
    return uid, None


def _validate(data: dict, is_create: bool) -> tuple[dict | None, str | None]:
    name = (data.get("name") or "").strip()
    if is_create and (not name or len(name) < 2):
        return None, "Nama lokasi wajib (min 2 karakter)"
    if name and len(name) > 200:
        return None, "Nama lokasi maksimal 200 karakter"

    vt = (data.get("default_visit_type") or "").strip().upper() or None
    if vt and vt not in ("PRC", "PC", "RC", "S-OUT"):
        return None, "Jenis service tidak valid (PRC / PC / RC / S-OUT)"

    phone = (data.get("contact_phone") or "").strip() or None
    if phone and not re.match(r"^[+\d\-\s\(\)]{6,20}$", phone):
        return None, "Format nomor WhatsApp tidak valid"

    return {
        "name": name or None,
        "area": (data.get("area") or "").strip() or None,
        "address": (data.get("address") or "").strip() or None,
        "default_visit_type": vt,
        "contact_person": (data.get("contact_person") or "").strip() or None,
        "contact_phone": phone,
        "notes": (data.get("notes") or "").strip() or None,
    }, None


def _log(cur, client_id, action, fields, reason, user_id):
    cur.execute("""
        INSERT INTO snc_client_log
            (client_id, action, changed_fields, reason, changed_by)
        VALUES (%s, %s, %s::jsonb, %s, %s)
    """, (client_id, action, json.dumps(fields, default=str), reason, user_id))


# ─────────────────────────────────────────────────────────────────────────────
# GET /snc-lokasi — list with search + filters
# ─────────────────────────────────────────────────────────────────────────────

@snc_lokasi_bp.route("/snc-lokasi", methods=["GET"])
@require_auth
def list_lokasi():
    search = (request.args.get("search") or "").strip()
    area = (request.args.get("area") or "").strip()
    active_only = request.args.get("active_only", "true").lower() == "true"
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))

    where = ["1=1"]
    params = []
    if active_only:
        where.append("COALESCE(c.is_active, true) = true")
    if search:
        where.append("c.name ILIKE %s")
        params.append(f"%{search}%")
    if area:
        where.append("c.area = %s")
        params.append(area)

    sql = f"""
        SELECT c.id, c.name, c.area, c.address,
               c.default_visit_type, c.contact_person, c.contact_phone,
               c.is_active, c.notes, c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM snc_recurring_rules r
                WHERE r.client_id = c.id
                  AND (r.effective_end IS NULL OR r.effective_end >= CURRENT_DATE)
               ) AS active_rule_count,
               (SELECT COUNT(*) FROM snc_schedule_events e
                WHERE e.client_id = c.id
                  AND e.start_date >= CURRENT_DATE - INTERVAL '30 days'
                  AND e.schedule_status IN ('scheduled', 'completed')
               ) AS visits_30d
        FROM snc_clients c
        WHERE {' AND '.join(where)}
        ORDER BY c.name
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cnt_sql = f"SELECT COUNT(*) AS n FROM snc_clients c WHERE {' AND '.join(where)}"
            cur.execute(cnt_sql, params[:-2])
            total = cur.fetchone()["n"]

            # Areas for dropdown
            cur.execute(
                "SELECT DISTINCT area FROM snc_clients "
                "WHERE area IS NOT NULL AND area != '' ORDER BY area"
            )
            areas = [r["area"] for r in cur.fetchall()]

    for r in rows:
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
        r["updated_at"] = r["updated_at"].isoformat() if r.get("updated_at") else None

    return jsonify({
        "total": total,
        "limit": limit,
        "offset": offset,
        "areas": areas,
        "rows": rows,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /snc-lokasi/<id> — detail + audit log
# ─────────────────────────────────────────────────────────────────────────────

@snc_lokasi_bp.route("/snc-lokasi/<int:client_id>", methods=["GET"])
@require_auth
def get_lokasi(client_id):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT c.*,
                    (SELECT COUNT(*) FROM snc_recurring_rules r
                     WHERE r.client_id = c.id
                       AND (r.effective_end IS NULL OR r.effective_end >= CURRENT_DATE)
                    ) AS active_rule_count,
                    (SELECT COUNT(*) FROM snc_schedule_events e
                     WHERE e.client_id = c.id
                       AND e.start_date >= CURRENT_DATE - INTERVAL '90 days'
                       AND e.schedule_status IN ('scheduled', 'completed')
                    ) AS visits_90d
                FROM snc_clients c WHERE c.id = %s
            """, (client_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Lokasi tidak ditemukan"}), 404

            cur.execute("""
                SELECT id, action, changed_fields, reason, changed_by, changed_at
                FROM snc_client_log WHERE client_id = %s
                ORDER BY changed_at DESC LIMIT 20
            """, (client_id,))
            log = cur.fetchall()

    for d in ("created_at", "updated_at", "deactivated_at"):
        if row.get(d):
            row[d] = row[d].isoformat()
    for e in log:
        e["changed_at"] = e["changed_at"].isoformat()
    return jsonify({"lokasi": row, "audit_log": log})


# ─────────────────────────────────────────────────────────────────────────────
# POST /snc-lokasi — create new customer
# ─────────────────────────────────────────────────────────────────────────────

@snc_lokasi_bp.route("/snc-lokasi", methods=["POST"])
@require_auth
def create_lokasi():
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    cleaned, err = _validate(request.get_json() or {}, is_create=True)
    if err:
        return jsonify({"error": err}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Pre-check duplicate
            cur.execute("SELECT id, area FROM snc_clients WHERE name = %s", (cleaned["name"],))
            existing = cur.fetchone()
            if existing:
                return jsonify({
                    "error": "duplicate",
                    "message": f'"{cleaned["name"]}" sudah ada di daftar.',
                    "existing_id": existing["id"],
                    "existing_area": existing["area"],
                }), 409
            try:
                cur.execute("""
                    INSERT INTO snc_clients
                        (name, area, address, default_visit_type,
                         contact_person, contact_phone, notes,
                         is_active, created_by)
                    VALUES (%(name)s, %(area)s, %(address)s, %(default_visit_type)s,
                            %(contact_person)s, %(contact_phone)s, %(notes)s,
                            true, %(user_id)s)
                    RETURNING id
                """, {**cleaned, "user_id": user_id})
                client_id = cur.fetchone()["id"]
                _log(cur, client_id, "created", cleaned, "Tambah lokasi baru", user_id)
                conn.commit()
            except Exception as e:
                conn.rollback()
                return jsonify({"error": "Database error", "detail": str(e)}), 500

    return jsonify({
        "id": client_id,
        "message": f'"{cleaned["name"]}" tersimpan',
    }), 201


# ─────────────────────────────────────────────────────────────────────────────
# PUT /snc-lokasi/<id>
# ─────────────────────────────────────────────────────────────────────────────

@snc_lokasi_bp.route("/snc-lokasi/<int:client_id>", methods=["PUT"])
@require_auth
def update_lokasi(client_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    data = request.get_json() or {}
    reason = data.pop("reason", "Ubah lokasi")
    cleaned, err = _validate(data, is_create=False)
    if err:
        return jsonify({"error": err}), 400

    # Filter only fields provided
    update_fields = {k: v for k, v in cleaned.items() if k in data}
    if not update_fields:
        return jsonify({"error": "Tidak ada field untuk diubah"}), 400

    set_parts = [f"{k} = %s" for k in update_fields]
    params = list(update_fields.values()) + [user_id, client_id]
    sql = (f"UPDATE snc_clients SET {', '.join(set_parts)}, "
           f"updated_at = now(), updated_by = %s WHERE id = %s")

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id FROM snc_clients WHERE id = %s", (client_id,))
            if not cur.fetchone():
                return jsonify({"error": "Lokasi tidak ditemukan"}), 404
            try:
                cur.execute(sql, params)
                _log(cur, client_id, "updated", update_fields, reason, user_id)
                conn.commit()
            except Exception as e:
                conn.rollback()
                if "snc_clients_name_unique" in str(e):
                    return jsonify({
                        "error": "duplicate",
                        "message": "Nama lokasi sudah dipakai oleh lokasi lain"
                    }), 409
                return jsonify({"error": "Database error", "detail": str(e)}), 500

    return jsonify({"id": client_id, "fields": list(update_fields), "message": "Lokasi diubah"})


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /snc-lokasi/<id> — soft delete
# ─────────────────────────────────────────────────────────────────────────────

@snc_lokasi_bp.route("/snc-lokasi/<int:client_id>", methods=["DELETE"])
@require_auth
def deactivate_lokasi(client_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    reason = (request.get_json() or {}).get("reason") or "Sembunyikan lokasi"

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name, is_active FROM snc_clients WHERE id = %s", (client_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Lokasi tidak ditemukan"}), 404
            cur.execute("""
                UPDATE snc_clients
                SET is_active = false, deactivated_at = now(),
                    deactivation_reason = %s, updated_at = now(), updated_by = %s
                WHERE id = %s
            """, (reason, user_id, client_id))
            _log(cur, client_id, "deactivated", {"reason": reason}, reason, user_id)
            conn.commit()
    return jsonify({"id": client_id, "message": f'"{row["name"]}" disembunyikan'})


# ─────────────────────────────────────────────────────────────────────────────
# POST /snc-lokasi/<id>/reactivate
# ─────────────────────────────────────────────────────────────────────────────

@snc_lokasi_bp.route("/snc-lokasi/<int:client_id>/reactivate", methods=["POST"])
@require_auth
def reactivate_lokasi(client_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    reason = (request.get_json() or {}).get("reason") or "Munculkan kembali"

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name FROM snc_clients WHERE id = %s", (client_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Lokasi tidak ditemukan"}), 404
            cur.execute("""
                UPDATE snc_clients
                SET is_active = true, deactivated_at = NULL,
                    deactivation_reason = NULL, updated_at = now(), updated_by = %s
                WHERE id = %s
            """, (user_id, client_id))
            _log(cur, client_id, "reactivated", {}, reason, user_id)
            conn.commit()
    return jsonify({"id": client_id, "message": f'"{row["name"]}" dimunculkan kembali'})
