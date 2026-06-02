"""
Lokasi Libur Sementara — Customer Suppression API.

POST /lokasi/<id>/libur          — create suppression
PUT  /libur/<id>                 — update
DELETE /libur/<id>               — delete (hard, with audit)
GET  /libur                      — cross-customer list (filter by month/active)
GET  /lokasi/<id>/libur          — per-customer list
"""

import json
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request

from kil.backend.core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

libur_bp = Blueprint("client_suppression", __name__, url_prefix="/api/v1/enterprise")


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


def _validate_payload(data: dict) -> tuple[dict | None, str | None]:
    if not data:
        return None, "Body kosong"
    sd = data.get("start_date")
    ed = data.get("end_date")
    if not sd or not ed:
        return None, "Tanggal mulai dan tanggal selesai wajib diisi"
    try:
        sd_d = date.fromisoformat(sd)
        ed_d = date.fromisoformat(ed)
    except ValueError:
        return None, "Format tanggal tidak valid (gunakan YYYY-MM-DD)"
    if ed_d < sd_d:
        return None, "Tanggal selesai harus setelah tanggal mulai"
    if (ed_d - sd_d).days > 90:
        return None, "Rentang libur maksimal 90 hari (pakai deactivate jadwal kalau lebih lama)"
    reason = (data.get("reason") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None
    return {
        "start_date": sd_d,
        "end_date": ed_d,
        "reason": reason,
        "notes": notes,
    }, None


def _log(cur, supp_id, client_id, action, fields, reason, user_id):
    cur.execute("""
        INSERT INTO snc_client_suppression_log
            (suppression_id, client_id, action, changed_fields, reason, changed_by)
        VALUES (%s, %s, %s, %s::jsonb, %s, %s)
    """, (supp_id, client_id, action, json.dumps(fields, default=str), reason, user_id))


def _count_affected_draft_events(cur, client_id, start_date, end_date) -> int:
    cur.execute("""
        SELECT COUNT(*) AS n
        FROM snc_schedule_events
        WHERE client_id = %s
          AND start_date BETWEEN %s AND %s
          AND schedule_status IN ('draft', 'scheduled')
    """, (client_id, start_date, end_date))
    return cur.fetchone()["n"]


# ─────────────────────────────────────────────────────────────────────────────
# POST /lokasi/<id>/libur — create suppression for a customer
# ─────────────────────────────────────────────────────────────────────────────

@libur_bp.route("/lokasi/<int:client_id>/libur", methods=["POST"])
@require_auth
def create_suppression(client_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    cleaned, err = _validate_payload(request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name FROM snc_clients WHERE id = %s", (client_id,))
            client = cur.fetchone()
            if not client:
                return jsonify({"error": "Lokasi tidak ditemukan"}), 404

            affected = _count_affected_draft_events(
                cur, client_id, cleaned["start_date"], cleaned["end_date"]
            )

            cur.execute("""
                INSERT INTO snc_client_suppression_dates
                    (client_id, start_date, end_date, reason, notes, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (client_id, cleaned["start_date"], cleaned["end_date"],
                  cleaned["reason"], cleaned["notes"], user_id))
            supp_id = cur.fetchone()["id"]
            _log(cur, supp_id, client_id, "created", cleaned, "Catat lokasi libur", user_id)
            conn.commit()

    return jsonify({
        "id": supp_id,
        "client_name": client["name"],
        "affected_draft_events": affected,
        "message": f"{client['name']} libur tersimpan",
    }), 201


# ─────────────────────────────────────────────────────────────────────────────
# GET /libur — cross-customer list
# ─────────────────────────────────────────────────────────────────────────────

@libur_bp.route("/libur", methods=["GET"])
@require_auth
def list_all_suppressions():
    filter_month = request.args.get("month")  # YYYY-MM
    show = request.args.get("show", "active")  # 'active' | 'upcoming' | 'past' | 'all'
    today = date.today()

    where = ["1=1"]
    params = []
    if filter_month:
        try:
            y, m = filter_month.split("-")
            mstart = date(int(y), int(m), 1)
            mend = date(int(y), int(m) + 1, 1) if int(m) < 12 else date(int(y) + 1, 1, 1)
            where.append("(start_date < %s AND end_date >= %s)")
            params.extend([mend, mstart])
        except (ValueError, IndexError):
            return jsonify({"error": "month harus format YYYY-MM"}), 400
    elif show == "active":
        where.append("start_date <= %s AND end_date >= %s")
        params.extend([today, today])
    elif show == "upcoming":
        where.append("start_date > %s")
        params.append(today)
    elif show == "past":
        where.append("end_date < %s")
        params.append(today)
    # 'all' = no filter

    sql = f"""
        SELECT s.id, s.client_id, c.name AS client_name,
               s.start_date, s.end_date, s.reason, s.notes,
               s.created_by, s.created_at,
               (s.end_date - s.start_date + 1) AS days
        FROM snc_client_suppression_dates s
        JOIN snc_clients c ON c.id = s.client_id
        WHERE {' AND '.join(where)}
        ORDER BY s.start_date DESC
        LIMIT 500
    """
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    for r in rows:
        r["start_date"] = r["start_date"].isoformat()
        r["end_date"] = r["end_date"].isoformat()
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
    return jsonify({"suppressions": rows, "total": len(rows)})


# ─────────────────────────────────────────────────────────────────────────────
# GET /lokasi/<id>/libur — per-customer list
# ─────────────────────────────────────────────────────────────────────────────

@libur_bp.route("/lokasi/<int:client_id>/libur", methods=["GET"])
@require_auth
def list_client_suppressions(client_id):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT id, start_date, end_date, reason, notes, created_by, created_at,
                       (end_date - start_date + 1) AS days
                FROM snc_client_suppression_dates
                WHERE client_id = %s
                ORDER BY start_date DESC
            """, (client_id,))
            rows = cur.fetchall()
    today = date.today()
    for r in rows:
        s, e = r["start_date"], r["end_date"]
        r["status"] = ("past" if e < today
                       else "active" if s <= today <= e
                       else "upcoming")
        r["start_date"] = s.isoformat()
        r["end_date"] = e.isoformat()
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
    return jsonify({"suppressions": rows})


# ─────────────────────────────────────────────────────────────────────────────
# PUT /libur/<id> — update
# ─────────────────────────────────────────────────────────────────────────────

@libur_bp.route("/libur/<int:supp_id>", methods=["PUT"])
@require_auth
def update_suppression(supp_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    cleaned, err = _validate_payload(request.get_json() or {})
    if err:
        return jsonify({"error": err}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT client_id FROM snc_client_suppression_dates WHERE id = %s",
                (supp_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Catatan libur tidak ditemukan"}), 404
            cur.execute("""
                UPDATE snc_client_suppression_dates
                SET start_date=%s, end_date=%s, reason=%s, notes=%s,
                    updated_at=now(), updated_by=%s
                WHERE id=%s
            """, (cleaned["start_date"], cleaned["end_date"],
                  cleaned["reason"], cleaned["notes"], user_id, supp_id))
            _log(cur, supp_id, row["client_id"], "updated", cleaned,
                 (request.get_json() or {}).get("reason") or "Ubah catatan libur",
                 user_id)
            conn.commit()

    return jsonify({"id": supp_id, "message": "Catatan libur diubah"})


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /libur/<id> — delete (hard)
# ─────────────────────────────────────────────────────────────────────────────

@libur_bp.route("/libur/<int:supp_id>", methods=["DELETE"])
@require_auth
def delete_suppression(supp_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    reason = (request.get_json() or {}).get("reason") or "Hapus catatan libur"

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM snc_client_suppression_dates WHERE id = %s",
                (supp_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Catatan libur tidak ditemukan"}), 404
            snapshot = {
                "start_date": row["start_date"].isoformat(),
                "end_date": row["end_date"].isoformat(),
                "reason": row["reason"],
                "notes": row["notes"],
            }
            cur.execute("DELETE FROM snc_client_suppression_dates WHERE id = %s", (supp_id,))
            _log(cur, None, row["client_id"], "deleted", snapshot, reason, user_id)
            conn.commit()

    return jsonify({"id": supp_id, "message": "Catatan libur dihapus"})
