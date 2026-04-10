"""
Scheduling Write API
=====================
Write endpoints for road plan management.
Koordinator creates/updates/cancels schedules via this API.
Data stored in snc_road_plans (enterprise DB), readable alongside Kelava data.
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import _get_local_pool, execute_kelava_query

scheduling_write_bp = Blueprint("scheduling_write", __name__)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _require_role(*roles):
    """Return 403 if current user doesn't have one of the given roles."""
    user = getattr(request, "_jwt_user", None)
    if user and user.get("role") not in roles:
        return jsonify({"error": "Forbidden — insufficient role"}), 403
    return None


# ── List (unified: Kelava + SNC) ─────────────────────────────────────────────


@scheduling_write_bp.route("/scheduling/road-plans")
@require_auth
def list_road_plans():
    """
    List all road plans (merged: Kelava live + SNC-created).

    Query params:
        date: YYYY-MM-DD (default today)
        p_user_id: filter by technician
        status: filter by status
        source: 'kelava' | 'snc' | 'all' (default all)
    """
    from datetime import date

    target_date = request.args.get("date", date.today().isoformat())
    p_user_id = request.args.get("p_user_id")
    status_filter = request.args.get("status")
    source = request.args.get("source", "all")

    results = []

    # Kelava source
    if source in ("all", "kelava"):
        where = "WHERE rp.visit_date::date = %s AND COALESCE(rp.is_cancel, false) = false"
        params: list = [target_date]

        if p_user_id:
            where += " AND rp.id_user = %s"
            params.append(int(p_user_id))
        if status_filter:
            where += " AND rp.status = %s"
            params.append(status_filter)

        rows = execute_kelava_query(
            f"""
            SELECT rp.id, rp.visit_date, rp.status, rp.is_cancel,
                   rp.id_user AS p_user_id, rp.id_customer AS customer_id,
                   rp.id_kontrak AS kontrak_id, rp.type AS visit_type,
                   rp.no_ra, rp.remarks, rp.title,
                   c.name AS customer_name, c.address AS customer_address,
                   u.fullname AS technician_name,
                   k.no_kontrak
            FROM t_road_plan rp
            JOIN m_customer c ON c.id = rp.id_customer
            JOIN p_user u ON u.id = rp.id_user
            LEFT JOIN m_customer_kontrak k ON k.id = rp.id_kontrak
            {where}
            ORDER BY rp.visit_date
            """,
            params,
        )
        for r in rows:
            results.append({
                **r,
                "source": "kelava",
                "visit_date": r["visit_date"].isoformat() if r.get("visit_date") else None,
            })

    # SNC source
    if source in ("all", "snc"):
        where_snc = "WHERE rp.visit_date::date = %s AND rp.is_cancel = false"
        params_snc: list = [target_date]

        if p_user_id:
            where_snc += " AND rp.p_user_id = %s"
            params_snc.append(int(p_user_id))
        if status_filter:
            where_snc += " AND rp.status = %s"
            params_snc.append(status_filter)

        with _get_local_pool().connection() as conn:
            with conn.cursor(row_factory=_dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT rp.id, rp.visit_date, rp.status, rp.is_cancel,
                           rp.p_user_id, rp.customer_id, rp.kontrak_id,
                           rp.visit_type, rp.no_ra, rp.remarks, rp.title,
                           rp.created_at
                    FROM snc_road_plans rp
                    {where_snc}
                    ORDER BY rp.visit_date
                    """,
                    params_snc,
                )
                snc_rows = cur.fetchall()

        # Enrich with customer/technician names from Kelava
        customer_ids = list({r["customer_id"] for r in snc_rows})
        user_ids = list({r["p_user_id"] for r in snc_rows})

        customers = {}
        users = {}
        if customer_ids:
            for c in execute_kelava_query(
                f"SELECT id, name, address FROM m_customer WHERE id = ANY(ARRAY[{','.join(str(i) for i in customer_ids)}])"
            ):
                customers[c["id"]] = c
        if user_ids:
            for u in execute_kelava_query(
                f"SELECT id, fullname FROM p_user WHERE id = ANY(ARRAY[{','.join(str(i) for i in user_ids)}])"
            ):
                users[u["id"]] = u

        for r in snc_rows:
            cust = customers.get(r["customer_id"], {})
            tech = users.get(r["p_user_id"], {})
            results.append({
                **r,
                "source": "snc",
                "customer_name": cust.get("name", "-"),
                "customer_address": cust.get("address"),
                "technician_name": tech.get("fullname", "-"),
                "visit_date": r["visit_date"].isoformat() if r.get("visit_date") else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })

    results.sort(key=lambda x: x.get("visit_date") or "")
    return jsonify({"total": len(results), "road_plans": results})


# ── Create ───────────────────────────────────────────────────────────────────


@scheduling_write_bp.route("/scheduling/road-plans", methods=["POST"])
@require_auth
def create_road_plan():
    """
    Create a new road plan (stored in enterprise DB).

    Body (JSON):
        p_user_id: integer (required) — technician Kelava ID
        customer_id: integer (required) — Kelava customer ID
        visit_date: ISO datetime string (required)
        kontrak_id: integer (optional)
        title: string (optional)
        remarks: string (optional)
        visit_type: string (default 'visit')
    """
    guard = _require_role("admin", "koordinator")
    if guard:
        return guard

    data = request.get_json(force=True)
    user = getattr(request, "_jwt_user", {})

    required = ("p_user_id", "customer_id", "visit_date")
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        visit_dt = datetime.fromisoformat(data["visit_date"])
    except ValueError:
        return jsonify({"error": "Invalid visit_date format — use ISO 8601"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row) as cur:
            cur.execute(
                """
                INSERT INTO snc_road_plans
                    (p_user_id, customer_id, kontrak_id, visit_date,
                     title, remarks, visit_type, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, visit_date, status, no_ra
                """,
                (
                    int(data["p_user_id"]),
                    int(data["customer_id"]),
                    int(data["kontrak_id"]) if data.get("kontrak_id") else None,
                    visit_dt,
                    data.get("title"),
                    data.get("remarks"),
                    data.get("visit_type", "visit"),
                    user.get("id", 0),
                ),
            )
            row = cur.fetchone()
        conn.commit()

    # Send push notification to technician (best-effort)
    try:
        _notify_technician(int(data["p_user_id"]), row["id"], visit_dt)
    except Exception:
        pass

    return jsonify({
        "message": "Road plan created",
        "id": row["id"],
        "visit_date": row["visit_date"].isoformat(),
        "status": row["status"],
    }), 201


# ── Update ───────────────────────────────────────────────────────────────────


@scheduling_write_bp.route("/scheduling/road-plans/<int:plan_id>", methods=["PUT"])
@require_auth
def update_road_plan(plan_id: int):
    """
    Update a SNC road plan status, date, or remarks.

    Body (JSON): any subset of visit_date, status, remarks, title, is_cancel
    """
    guard = _require_role("admin", "koordinator", "supervisor")
    if guard:
        return guard

    data = request.get_json(force=True)
    allowed = {"visit_date", "status", "remarks", "title", "is_cancel"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    set_clauses = []
    params = []
    for k, v in updates.items():
        if k == "visit_date":
            try:
                v = datetime.fromisoformat(v)
            except ValueError:
                return jsonify({"error": "Invalid visit_date format"}), 400
        set_clauses.append(f"{k} = %s")
        params.append(v)

    set_clauses.append("updated_at = NOW()")
    params.append(plan_id)

    with _get_local_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE snc_road_plans SET {', '.join(set_clauses)} WHERE id = %s RETURNING id",
                params,
            )
            if cur.rowcount == 0:
                return jsonify({"error": "Road plan not found"}), 404
        conn.commit()

    return jsonify({"message": "Updated", "id": plan_id})


# ── Cancel ───────────────────────────────────────────────────────────────────


@scheduling_write_bp.route("/scheduling/road-plans/<int:plan_id>/cancel", methods=["POST"])
@require_auth
def cancel_road_plan(plan_id: int):
    """Cancel a SNC road plan."""
    guard = _require_role("admin", "koordinator")
    if guard:
        return guard

    with _get_local_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE snc_road_plans SET is_cancel = true, status = 'Cancelled', updated_at = NOW() WHERE id = %s RETURNING id",
                (plan_id,),
            )
            if cur.rowcount == 0:
                return jsonify({"error": "Road plan not found"}), 404
        conn.commit()

    return jsonify({"message": "Cancelled", "id": plan_id})


# ── Technician Check-in/Check-out (SNC visits) ───────────────────────────────


@scheduling_write_bp.route("/scheduling/road-plans/<int:plan_id>/checkin", methods=["POST"])
@require_auth
def snc_checkin(plan_id: int):
    """
    Technician check-in for a SNC road plan.
    Body: latitude, longitude
    """
    data = request.get_json(force=True) or {}
    user = getattr(request, "_jwt_user", {})

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row) as cur:
            # Create or update visit record
            cur.execute(
                """
                INSERT INTO snc_visits (road_plan_id, p_user_id, check_in, latitude, longitude)
                VALUES (%s, %s, NOW(), %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (plan_id, user.get("p_user_id"), data.get("latitude"), data.get("longitude")),
            )
            visit = cur.fetchone()
            visit_id = visit["id"] if visit else None

            # Update road plan status
            cur.execute(
                "UPDATE snc_road_plans SET status = 'Berjalan', updated_at = NOW() WHERE id = %s",
                (plan_id,),
            )
        conn.commit()

    return jsonify({"message": "Check-in recorded", "visit_id": visit_id})


@scheduling_write_bp.route("/scheduling/road-plans/<int:plan_id>/checkout", methods=["POST"])
@require_auth
def snc_checkout(plan_id: int):
    """
    Technician check-out for a SNC road plan.
    Body: remarks, latitude, longitude
    """
    data = request.get_json(force=True) or {}
    user = getattr(request, "_jwt_user", {})

    with _get_local_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE snc_visits
                SET check_out = NOW(), latitude_out = %s, longitude_out = %s,
                    remarks = %s
                WHERE road_plan_id = %s AND p_user_id = %s AND check_out IS NULL
                """,
                (
                    data.get("latitude"),
                    data.get("longitude"),
                    data.get("remarks"),
                    plan_id,
                    user.get("p_user_id"),
                ),
            )
            cur.execute(
                "UPDATE snc_road_plans SET status = 'Selesai', updated_at = NOW() WHERE id = %s",
                (plan_id,),
            )
        conn.commit()

    return jsonify({"message": "Check-out recorded"})


# ── FCM Token Registration ────────────────────────────────────────────────────


@scheduling_write_bp.route("/scheduling/fcm-token", methods=["POST"])
@require_auth
def register_fcm_token():
    """
    Register or update FCM token for push notifications.
    Body: token, platform ('android' | 'ios')
    """
    data = request.get_json(force=True) or {}
    user = getattr(request, "_jwt_user", {})
    token = data.get("token", "").strip()
    if not token:
        return jsonify({"error": "token required"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO snc_fcm_tokens (enterprise_user_id, p_user_id, fcm_token, device_platform, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (enterprise_user_id) DO UPDATE
                SET fcm_token = EXCLUDED.fcm_token,
                    device_platform = EXCLUDED.device_platform,
                    updated_at = NOW()
                """,
                (user.get("id"), user.get("p_user_id"), token, data.get("platform", "android")),
            )
        conn.commit()

    return jsonify({"message": "FCM token registered"})


# ── Internal helpers ──────────────────────────────────────────────────────────


def _dict_row(cursor, row):
    """Row factory: dict from cursor description."""
    if row is None:
        return None
    cols = [desc[0] for desc in cursor.description]
    return dict(zip(cols, row))


def _notify_technician(p_user_id: int, road_plan_id: int, visit_date: datetime) -> None:
    """Send FCM push to technician. Best-effort — exceptions are caught by caller."""
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row) as cur:
            cur.execute(
                "SELECT fcm_token FROM snc_fcm_tokens WHERE p_user_id = %s LIMIT 1",
                (p_user_id,),
            )
            row = cur.fetchone()

    if not row or not row.get("fcm_token"):
        return

    import os
    import urllib.request
    import json

    fcm_key = os.environ.get("FCM_SERVER_KEY")
    if not fcm_key:
        return

    date_str = visit_date.strftime("%A, %d %b %Y %H:%M")
    payload = json.dumps({
        "to": row["fcm_token"],
        "notification": {
            "title": "Jadwal Kunjungan Baru",
            "body": f"Kamu punya jadwal baru: {date_str}",
            "sound": "default",
        },
        "data": {
            "type": "new_road_plan",
            "road_plan_id": str(road_plan_id),
            "visit_date": visit_date.isoformat(),
        },
    }).encode()

    req = urllib.request.Request(
        "https://fcm.googleapis.com/fcm/send",
        data=payload,
        headers={
            "Authorization": f"key={fcm_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5)
