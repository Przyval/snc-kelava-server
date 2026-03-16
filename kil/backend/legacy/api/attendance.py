"""
Fingerprint Attendance API
============================
Webhook receiver for BioFinger AT-601 (BioClock.id Push SDK),
attendance dashboard, device management, and user mapping.

Endpoints:
    POST   /webhooks/bioclock/push                  - Receive push events (public, API key auth)
    GET    /attendance/today                         - Today's attendance board
    GET    /attendance/history                       - Historical attendance
    GET    /attendance/stats                         - Attendance statistics
    GET    /attendance/devices                       - List devices
    POST   /attendance/devices                       - Register device (admin)
    PATCH  /attendance/devices/<id>                  - Update device (admin)
    GET    /attendance/user-map                      - List user mappings
    POST   /attendance/user-map                      - Map fingerprint user → technician (admin)
    DELETE /attendance/user-map/<id>                 - Remove mapping (admin)
"""

import json
import logging
import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

log = logging.getLogger(__name__)

attendance_bp = Blueprint("attendance", __name__)


def _fmt(row):
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ══════════════════════════════════════════════════════════════
# BioClock Webhook (PUBLIC - no JWT, validated by device API key)
# ══════════════════════════════════════════════════════════════


@attendance_bp.route("/webhooks/bioclock/push", methods=["POST"])
def bioclock_webhook():
    """
    Receive attendance push events from BioClock.id.

    Expected payload (may vary by BioClock SDK version):
    {
        "sn": "device_serial_number",
        "user_id": "fingerprint_user_id",
        "user_name": "User Name",
        "punch_time": "2026-03-02 08:15:00",
        "verify_type": "1"   // 1=fingerprint, 4=card
    }

    Validates X-API-Key header against attendance_devices.api_key.
    """
    # Validate API key
    api_key = request.headers.get("X-API-Key", "")
    if not api_key:
        # Also check query param (some devices send via URL param)
        api_key = request.args.get("api_key", "")

    if not api_key:
        return jsonify({"error": "API key required"}), 401

    data = request.json or {}
    device_sn = data.get("sn", "")

    if not device_sn:
        return jsonify({"error": "Device SN required"}), 400

    # Verify device + API key
    device = execute_kelava_query_single(
        "SELECT id, device_sn, api_key, is_active FROM attendance_devices WHERE device_sn = %s",
        (device_sn,),
    )

    if not device:
        log.warning(f"Unknown device SN: {device_sn}")
        return jsonify({"error": "Unknown device"}), 404

    if device["api_key"] != api_key:
        log.warning(f"Invalid API key for device {device_sn}")
        return jsonify({"error": "Invalid API key"}), 403

    if not device["is_active"]:
        return jsonify({"error": "Device is disabled"}), 403

    # Parse payload
    finger_user_id = str(data.get("user_id", ""))
    punch_time_str = data.get("punch_time", "")
    verify_type = str(data.get("verify_type", ""))

    if not finger_user_id or not punch_time_str:
        return jsonify({"error": "user_id and punch_time required"}), 400

    try:
        punch_time = datetime.strptime(punch_time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            punch_time = datetime.fromisoformat(punch_time_str)
        except ValueError:
            return jsonify({"error": "Invalid punch_time format"}), 400

    # Map to technician
    mapping = execute_kelava_query_single(
        "SELECT technician_id FROM attendance_user_map WHERE device_sn = %s AND finger_user_id = %s",
        (device_sn, finger_user_id),
    )
    technician_id = mapping["technician_id"] if mapping else None

    # Determine punch type (simple: first = check_in, later = check_out)
    existing_today = execute_kelava_query_single(
        """
        SELECT COUNT(*) as cnt FROM attendance_logs
        WHERE device_sn = %s AND finger_user_id = %s
          AND punch_time::date = %s
        """,
        (device_sn, finger_user_id, punch_time.date().isoformat()),
    )
    punch_type = "check_in" if (existing_today and existing_today["cnt"] == 0) else "check_out"

    # Verify method
    verify_map = {"1": "fingerprint", "2": "face", "4": "card", "15": "face"}
    verify_method = verify_map.get(verify_type, f"type_{verify_type}")

    # Insert log
    execute_kelava_query_single(
        """
        INSERT INTO attendance_logs
            (device_sn, finger_user_id, technician_id, punch_time, punch_type, verify_method, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (device_sn, finger_user_id, technician_id, punch_time, punch_type, verify_method, json.dumps(data)),
    )

    log.info(f"Attendance logged: {finger_user_id} @ {device_sn} [{punch_type}] {punch_time}")

    return jsonify({"status": "ok", "punch_type": punch_type, "technician_id": technician_id})


# ══════════════════════════════════════════════════════════════
# Attendance Dashboard (JWT protected)
# ══════════════════════════════════════════════════════════════


@attendance_bp.route("/attendance/today", methods=["GET"])
@require_auth
def attendance_today():
    """Today's attendance board: who's checked in, who hasn't."""
    target_date = request.args.get("date", date.today().isoformat())

    # Get all mapped technicians
    mapped = execute_kelava_query(
        """
        SELECT am.technician_id, u.fullname as name,
               am.device_sn, ad.device_name, ad.location as device_location
        FROM attendance_user_map am
        JOIN p_user u ON u.id = am.technician_id
        JOIN attendance_devices ad ON ad.device_sn = am.device_sn
        WHERE ad.is_active = true
        ORDER BY u.fullname
        """,
    )

    # Get today's logs
    logs = execute_kelava_query(
        """
        SELECT al.technician_id,
               MIN(al.punch_time) as first_punch,
               MAX(al.punch_time) as last_punch,
               COUNT(*) as punch_count,
               MIN(al.verify_method) as verify_method,
               MIN(ad.device_name) as device_name
        FROM attendance_logs al
        JOIN attendance_devices ad ON ad.device_sn = al.device_sn
        WHERE al.punch_time::date = %s
          AND al.technician_id IS NOT NULL
        GROUP BY al.technician_id
        """,
        (target_date,),
    )
    log_map = {r["technician_id"]: _fmt(r) for r in logs}

    technicians = []
    checked_in = 0
    for m in mapped:
        tid = m["technician_id"]
        log_data = log_map.get(tid, {})
        is_present = tid in log_map

        if is_present:
            checked_in += 1

        technicians.append({
            "technician_id": tid,
            "name": m["name"],
            "device_name": m["device_name"],
            "device_location": m.get("device_location", ""),
            "is_present": is_present,
            "first_punch": log_data.get("first_punch"),
            "last_punch": log_data.get("last_punch"),
            "punch_count": log_data.get("punch_count", 0),
            "verify_method": log_data.get("verify_method", ""),
        })

    return jsonify({
        "date": target_date,
        "total_mapped": len(mapped),
        "checked_in": checked_in,
        "absent": len(mapped) - checked_in,
        "technicians": technicians,
    })


@attendance_bp.route("/attendance/history", methods=["GET"])
@require_auth
def attendance_history():
    """Historical attendance logs."""
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 100)
    start_date = request.args.get("start_date", (date.today() - timedelta(days=7)).isoformat())
    end_date = request.args.get("end_date", date.today().isoformat())
    tech_id = request.args.get("technician_id")
    offset = (page - 1) * per_page

    where = "WHERE al.punch_time::date BETWEEN %s AND %s"
    params = [start_date, end_date]

    if tech_id:
        where += " AND al.technician_id = %s"
        params.append(int(tech_id))

    rows = execute_kelava_query(
        f"""
        SELECT al.id, al.device_sn, al.finger_user_id,
               al.technician_id, u.fullname as tech_name,
               al.punch_time, al.punch_type, al.verify_method,
               ad.device_name, ad.location as device_location
        FROM attendance_logs al
        LEFT JOIN p_user u ON u.id = al.technician_id
        LEFT JOIN attendance_devices ad ON ad.device_sn = al.device_sn
        {where}
        ORDER BY al.punch_time DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params) + (per_page, offset),
    )

    total = execute_kelava_query_single(
        f"SELECT COUNT(*) as cnt FROM attendance_logs al {where}",
        tuple(params),
    )

    return jsonify({
        "logs": [_fmt(r) for r in rows],
        "pagination": {"total": total["cnt"] if total else 0, "page": page, "per_page": per_page},
        "period": {"start_date": start_date, "end_date": end_date},
    })


@attendance_bp.route("/attendance/stats", methods=["GET"])
@require_auth
def attendance_stats():
    """Attendance statistics for a date range."""
    start_date = request.args.get("start_date", (date.today() - timedelta(days=30)).isoformat())
    end_date = request.args.get("end_date", date.today().isoformat())

    # Daily summary
    daily = execute_kelava_query(
        """
        SELECT
            al.punch_time::date as log_date,
            COUNT(DISTINCT al.technician_id) as present_count,
            (SELECT COUNT(DISTINCT technician_id) FROM attendance_user_map
             JOIN attendance_devices ad2 ON ad2.device_sn = attendance_user_map.device_sn
             WHERE ad2.is_active = true) as total_mapped,
            MIN(al.punch_time)::time as earliest_punch,
            COUNT(*) FILTER (WHERE al.punch_type = 'check_in' AND al.punch_time::time <= '08:30:00') as on_time_count
        FROM attendance_logs al
        WHERE al.punch_time::date BETWEEN %s AND %s
          AND al.technician_id IS NOT NULL
        GROUP BY al.punch_time::date
        ORDER BY log_date DESC
        """,
        (start_date, end_date),
    )

    # Overall stats
    total_days = len(daily)
    avg_present = sum(r["present_count"] for r in daily) / total_days if total_days > 0 else 0
    total_mapped = daily[0]["total_mapped"] if daily else 0
    avg_on_time_pct = (
        sum(r["on_time_count"] / max(r["present_count"], 1) * 100 for r in daily) / total_days
        if total_days > 0 else 0
    )

    return jsonify({
        "period": {"start_date": start_date, "end_date": end_date},
        "total_work_days": total_days,
        "total_mapped_technicians": total_mapped,
        "avg_present_per_day": round(avg_present, 1),
        "avg_on_time_pct": round(avg_on_time_pct, 1),
        "daily": [_fmt(r) for r in daily],
    })


# ══════════════════════════════════════════════════════════════
# Device Management (Admin only)
# ══════════════════════════════════════════════════════════════


@attendance_bp.route("/attendance/devices", methods=["GET"])
@require_auth
def list_devices():
    """List all registered attendance devices."""
    rows = execute_kelava_query(
        """
        SELECT ad.*,
               (SELECT COUNT(*) FROM attendance_user_map WHERE device_sn = ad.device_sn) as mapped_users,
               (SELECT COUNT(*) FROM attendance_logs WHERE device_sn = ad.device_sn AND punch_time::date = CURRENT_DATE) as today_punches
        FROM attendance_devices ad
        ORDER BY ad.created_at DESC
        """,
    )
    return jsonify({"devices": [_fmt(r) for r in rows]})


@attendance_bp.route("/attendance/devices", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def register_device():
    """Register a new attendance device."""
    data = request.json or {}
    device_sn = data.get("device_sn", "").strip()
    device_name = data.get("device_name", "").strip()
    location = data.get("location", "").strip()

    if not device_sn or not device_name:
        return jsonify({"error": "device_sn and device_name required"}), 400

    # Generate API key
    api_key = secrets.token_urlsafe(32)

    try:
        row = execute_kelava_query_single(
            """
            INSERT INTO attendance_devices (device_sn, device_name, location, api_key)
            VALUES (%s, %s, %s, %s)
            RETURNING id, device_sn, device_name, location, api_key, created_at
            """,
            (device_sn, device_name, location, api_key),
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return jsonify({"error": f"Device SN '{device_sn}' already registered"}), 409
        raise

    return jsonify({
        "message": "Device registered",
        "device": _fmt(row),
        "webhook_url": f"https://safencare.work/api/v1/enterprise/webhooks/bioclock/push",
        "api_key": api_key,
        "note": "Save this API key! Configure it in BioClock.id Push SDK settings."
    }), 201


@attendance_bp.route("/attendance/devices/<int:device_id>", methods=["PATCH"])
@require_auth
@require_role("admin", "koordinator")
def update_device(device_id: int):
    """Update device details."""
    data = request.json or {}
    updates = []
    params = []

    for field in ("device_name", "location"):
        if field in data:
            updates.append(f"{field} = %s")
            params.append(data[field])
    if "is_active" in data:
        updates.append("is_active = %s")
        params.append(bool(data["is_active"]))

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    params.append(device_id)
    execute_kelava_query_single(
        f"UPDATE attendance_devices SET {', '.join(updates)} WHERE id = %s",
        tuple(params),
    )

    return jsonify({"message": "Device updated"})


# ══════════════════════════════════════════════════════════════
# User Mapping (Admin only)
# ══════════════════════════════════════════════════════════════


@attendance_bp.route("/attendance/user-map", methods=["GET"])
@require_auth
def list_user_map():
    """List fingerprint user → technician mappings."""
    rows = execute_kelava_query(
        """
        SELECT am.*, u.fullname as tech_name, u.email as tech_email,
               ad.device_name
        FROM attendance_user_map am
        JOIN p_user u ON u.id = am.technician_id
        JOIN attendance_devices ad ON ad.device_sn = am.device_sn
        ORDER BY ad.device_name, u.fullname
        """,
    )
    return jsonify({"mappings": [_fmt(r) for r in rows]})


@attendance_bp.route("/attendance/user-map", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def create_user_map():
    """Map a fingerprint user ID to a SanoCare technician."""
    data = request.json or {}
    device_sn = data.get("device_sn", "").strip()
    finger_user_id = str(data.get("finger_user_id", "")).strip()
    finger_user_name = data.get("finger_user_name", "")
    technician_id = data.get("technician_id")

    if not device_sn or not finger_user_id or not technician_id:
        return jsonify({"error": "device_sn, finger_user_id, and technician_id required"}), 400

    # Verify device exists
    device = execute_kelava_query_single("SELECT id FROM attendance_devices WHERE device_sn = %s", (device_sn,))
    if not device:
        return jsonify({"error": f"Device '{device_sn}' not found"}), 404

    # Verify technician exists
    tech = execute_kelava_query_single("SELECT id, fullname FROM p_user WHERE id = %s", (technician_id,))
    if not tech:
        return jsonify({"error": f"Technician {technician_id} not found"}), 404

    try:
        row = execute_kelava_query_single(
            """
            INSERT INTO attendance_user_map (device_sn, finger_user_id, finger_user_name, technician_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (device_sn, finger_user_id, finger_user_name, technician_id),
        )
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return jsonify({"error": "This fingerprint user is already mapped on this device"}), 409
        raise

    return jsonify({
        "message": f"Mapped fingerprint user {finger_user_id} → {tech['fullname']}",
        "mapping_id": row["id"] if row else None,
    }), 201


@attendance_bp.route("/attendance/user-map/<int:mapping_id>", methods=["DELETE"])
@require_auth
@require_role("admin", "koordinator")
def delete_user_map(mapping_id: int):
    """Remove a fingerprint user mapping."""
    existing = execute_kelava_query_single("SELECT id FROM attendance_user_map WHERE id = %s", (mapping_id,))
    if not existing:
        return jsonify({"error": "Mapping not found"}), 404

    execute_kelava_query_single("DELETE FROM attendance_user_map WHERE id = %s", (mapping_id,))
    return jsonify({"message": "Mapping deleted"})
