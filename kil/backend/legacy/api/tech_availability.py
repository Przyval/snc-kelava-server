"""
Teknisi Tidak Masuk — Tech Availability API.

POST /tech-availability         — record absence (1 day OR range)
PUT  /tech-availability/<id>
DELETE /tech-availability/<id>
GET  /tech-availability          — list with filters
GET  /tech-availability/calendar — calendar grid per month
"""

import json
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, g, jsonify, request

from kil.backend.core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

availability_bp = Blueprint("tech_availability", __name__, url_prefix="/api/v1/enterprise")

ALLOWED_STATUS = {"off", "sick", "training", "half_day", "available"}


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


def _log(cur, status_id, technician_id, date_, action, fields, reason, user_id):
    cur.execute("""
        INSERT INTO snc_tech_status_log
            (tech_status_id, technician_id, date, action, changed_fields, reason, changed_by)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
    """, (status_id, technician_id, date_, action,
          json.dumps(fields, default=str), reason, user_id))


# ─────────────────────────────────────────────────────────────────────────────
# POST /tech-availability — record absence (single or range)
# ─────────────────────────────────────────────────────────────────────────────

@availability_bp.route("/tech-availability", methods=["POST"])
@require_auth
def create_availability():
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden

    data = request.get_json() or {}
    tech_id = data.get("technician_id")
    sd = data.get("date_from") or data.get("date")
    ed = data.get("date_to") or sd
    status = data.get("status")
    reason = (data.get("reason") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None
    half_period = (data.get("half_day_period") or "").strip() or None
    backup_tech_id = data.get("backup_tech_id") or None

    if not tech_id:
        return jsonify({"error": "Teknisi wajib dipilih"}), 400
    if not status or status not in ALLOWED_STATUS:
        return jsonify({"error": f"Status harus salah satu: {', '.join(ALLOWED_STATUS)}"}), 400
    if not sd:
        return jsonify({"error": "Tanggal wajib diisi"}), 400
    try:
        sd_d = date.fromisoformat(sd)
        ed_d = date.fromisoformat(ed)
    except ValueError:
        return jsonify({"error": "Format tanggal tidak valid"}), 400
    if ed_d < sd_d:
        return jsonify({"error": "Tanggal selesai harus setelah tanggal mulai"}), 400
    if (ed_d - sd_d).days > 365:
        return jsonify({"error": "Rentang maksimal 365 hari per record"}), 400
    if status == "half_day" and half_period not in ("morning", "afternoon"):
        return jsonify({"error": "half_day butuh half_day_period 'morning' atau 'afternoon'"}), 400

    inserted_ids = []
    affected_total = 0
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name FROM snc_technicians WHERE id = %s", (tech_id,))
            tech = cur.fetchone()
            if not tech:
                return jsonify({"error": "Teknisi tidak ditemukan"}), 404

            d = sd_d
            while d <= ed_d:
                # Count affected events for this day
                cur.execute("""
                    SELECT COUNT(*) AS n FROM snc_schedule_events
                    WHERE technician_id = %s AND start_date = %s
                      AND schedule_status IN ('draft', 'scheduled')
                """, (tech_id, d))
                affected_total += cur.fetchone()["n"]

                # Upsert (tech, date)
                cur.execute("""
                    INSERT INTO snc_technician_day_status
                        (technician_id, date, status, reason, notes,
                         half_day_period, backup_tech_id, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (technician_id, date) DO UPDATE SET
                        status = EXCLUDED.status,
                        reason = EXCLUDED.reason,
                        notes  = EXCLUDED.notes,
                        half_day_period = EXCLUDED.half_day_period,
                        backup_tech_id  = EXCLUDED.backup_tech_id,
                        updated_at = now(),
                        updated_by = EXCLUDED.created_by
                    RETURNING id
                """, (tech_id, d, status, reason, notes,
                      half_period, backup_tech_id, user_id))
                sid = cur.fetchone()["id"]
                inserted_ids.append(sid)
                _log(cur, sid, tech_id, d, "created",
                     {"status": status, "reason": reason,
                      "half_day_period": half_period, "backup_tech_id": backup_tech_id},
                     reason or "Catat tidak masuk", user_id)
                d += timedelta(days=1)
            conn.commit()

    return jsonify({
        "ids": inserted_ids,
        "tech_name": tech["name"],
        "days": len(inserted_ids),
        "affected_draft_events": affected_total,
        "message": (f"{tech['name']} tidak masuk {len(inserted_ids)} hari tersimpan"
                    if len(inserted_ids) > 1
                    else f"{tech['name']} tidak masuk tersimpan"),
    }), 201


# ─────────────────────────────────────────────────────────────────────────────
# GET /tech-availability — list with filters
# ─────────────────────────────────────────────────────────────────────────────

@availability_bp.route("/tech-availability", methods=["GET"])
@require_auth
def list_availability():
    from_d = request.args.get("from")
    to_d = request.args.get("to")
    tech_id = request.args.get("tech_id", type=int)
    status = request.args.get("status")

    where = ["1=1"]
    params = []
    if from_d:
        where.append("ts.date >= %s")
        params.append(from_d)
    if to_d:
        where.append("ts.date <= %s")
        params.append(to_d)
    if tech_id:
        where.append("ts.technician_id = %s")
        params.append(tech_id)
    if status:
        where.append("ts.status = %s")
        params.append(status)
    else:
        where.append("ts.status != 'available'")

    sql = f"""
        SELECT ts.id, ts.technician_id, t.name AS tech_name,
               ts.date, ts.status, ts.reason, ts.notes,
               ts.half_day_period, ts.backup_tech_id,
               bt.name AS backup_tech_name,
               ts.created_by, ts.created_at
        FROM snc_technician_day_status ts
        JOIN snc_technicians t ON t.id = ts.technician_id
        LEFT JOIN snc_technicians bt ON bt.id = ts.backup_tech_id
        WHERE {' AND '.join(where)}
        ORDER BY ts.date DESC, t.name
        LIMIT 500
    """
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    for r in rows:
        r["date"] = r["date"].isoformat()
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
    return jsonify({"rows": rows, "total": len(rows)})


# ─────────────────────────────────────────────────────────────────────────────
# GET /tech-availability/calendar — calendar grid per month
# ─────────────────────────────────────────────────────────────────────────────

@availability_bp.route("/tech-availability/calendar", methods=["GET"])
@require_auth
def calendar_view():
    month = request.args.get("month", "")
    try:
        y, m = month.split("-")
        y, m = int(y), int(m)
    except (ValueError, IndexError):
        return jsonify({"error": "month wajib format YYYY-MM"}), 400

    mstart = date(y, m, 1)
    mend = date(y, m + 1, 1) if m < 12 else date(y + 1, 1, 1)
    mend -= timedelta(days=1)

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT ts.id, ts.technician_id, t.name AS tech_name,
                       ts.date, ts.status, ts.reason
                FROM snc_technician_day_status ts
                JOIN snc_technicians t ON t.id = ts.technician_id
                WHERE ts.date BETWEEN %s AND %s
                  AND ts.status != 'available'
                ORDER BY ts.date
            """, (mstart, mend))
            rows = cur.fetchall()

    days = defaultdict(list)
    for r in rows:
        days[r["date"].isoformat()].append({
            "id": r["id"],
            "tech_id": r["technician_id"],
            "tech_name": r["tech_name"],
            "status": r["status"],
            "reason": r["reason"],
        })
    return jsonify({"month": month, "days": dict(days)})


# ─────────────────────────────────────────────────────────────────────────────
# PUT /tech-availability/<id>
# ─────────────────────────────────────────────────────────────────────────────

@availability_bp.route("/tech-availability/<int:status_id>", methods=["PUT"])
@require_auth
def update_availability(status_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    data = request.get_json() or {}
    reason_change = data.pop("reason_change", None) or "Ubah catatan tidak masuk"

    fields = {}
    for f in ("status", "reason", "notes", "half_day_period", "backup_tech_id", "date"):
        if f in data:
            fields[f] = data[f]
    if not fields:
        return jsonify({"error": "Tidak ada field untuk diubah"}), 400

    set_parts = [f"{k} = %s" for k in fields]
    params = list(fields.values()) + [user_id, status_id]

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT technician_id, date FROM snc_technician_day_status WHERE id = %s",
                (status_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Catatan tidak ditemukan"}), 404
            cur.execute(
                f"UPDATE snc_technician_day_status SET {', '.join(set_parts)}, "
                f"updated_at=now(), updated_by=%s WHERE id=%s",
                params,
            )
            _log(cur, status_id, row["technician_id"], row["date"],
                 "updated", fields, reason_change, user_id)
            conn.commit()
    return jsonify({"id": status_id, "fields": list(fields), "message": "Catatan diubah"})


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /tech-availability/<id>
# ─────────────────────────────────────────────────────────────────────────────

@availability_bp.route("/tech-availability/<int:status_id>", methods=["DELETE"])
@require_auth
def delete_availability(status_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    reason = (request.get_json() or {}).get("reason") or "Hapus catatan tidak masuk"

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM snc_technician_day_status WHERE id = %s",
                (status_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Catatan tidak ditemukan"}), 404
            snapshot = {
                "status": row["status"], "date": row["date"].isoformat(),
                "reason": row["reason"], "notes": row["notes"],
            }
            cur.execute("DELETE FROM snc_technician_day_status WHERE id = %s", (status_id,))
            _log(cur, None, row["technician_id"], row["date"],
                 "deleted", snapshot, reason, user_id)
            conn.commit()
    return jsonify({"id": status_id, "message": "Catatan dihapus"})
