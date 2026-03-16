"""
Face Verification Attendance API
==================================
Selfie-based clock-in with face comparison against staff photo database.
Captures GPS in background during clock-in.

Meeting: "Selfie dulu baru bisa clock-in... face recognition"
"""

import hashlib
import os
import uuid
from datetime import date, datetime, timezone

from flask import Blueprint, g, jsonify, request
from werkzeug.utils import secure_filename

from core.security import require_auth
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

STAFF_PHOTO_DIR = os.environ.get("STAFF_PHOTO_DIR", "/root/kil-server/uploads/staff_photos")
SELFIE_DIR = os.environ.get("SELFIE_DIR", "/root/kil-server/uploads/selfies")
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
FACE_MATCH_THRESHOLD = 0.6  # Cosine similarity threshold

face_attendance_bp = Blueprint("face_attendance", __name__, url_prefix="/face-attendance")

_TABLE_ENSURED = False


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS face_attendance_logs (
            id              BIGSERIAL PRIMARY KEY,
            technician_id   INTEGER NOT NULL,
            punch_type      VARCHAR(15) NOT NULL DEFAULT 'clock_in',
            selfie_path     TEXT,
            reference_path  TEXT,
            match_score     NUMERIC(4,3),
            match_result    VARCHAR(15) DEFAULT 'PENDING',
            latitude        NUMERIC(10,7),
            longitude       NUMERIC(10,7),
            accuracy        NUMERIC(8,2),
            device_info     TEXT,
            punch_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            verified_by     VARCHAR(100),
            verified_at     TIMESTAMPTZ,
            override_reason TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    execute_kelava_query("""
        CREATE INDEX IF NOT EXISTS idx_face_att_tech_date
        ON face_attendance_logs (technician_id, punch_time DESC)
    """)
    _TABLE_ENSURED = True


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _compare_faces(selfie_path, reference_path):
    """
    Compare two face images. Returns similarity score 0.0-1.0.
    Uses basic image hash comparison as fallback when face_recognition is not installed.
    Production should use proper face_recognition or deepface library.
    """
    try:
        import face_recognition
        selfie_img = face_recognition.load_image_file(selfie_path)
        ref_img = face_recognition.load_image_file(reference_path)

        selfie_enc = face_recognition.face_encodings(selfie_img)
        ref_enc = face_recognition.face_encodings(ref_img)

        if not selfie_enc or not ref_enc:
            return None, "NO_FACE_DETECTED"

        distance = face_recognition.face_distance([ref_enc[0]], selfie_enc[0])[0]
        score = 1.0 - float(distance)
        return score, "MATCHED" if score >= FACE_MATCH_THRESHOLD else "MISMATCH"
    except ImportError:
        # Fallback: perceptual hash comparison using Pillow
        try:
            from PIL import Image
            # Simple average hash comparison
            def _avg_hash(path, size=16):
                img = Image.open(path).resize((size, size)).convert("L")
                pixels = list(img.getdata())
                avg = sum(pixels) / len(pixels)
                return sum(1 << i for i, p in enumerate(pixels) if p > avg)

            h1 = _avg_hash(selfie_path)
            h2 = _avg_hash(reference_path)
            # Hamming distance
            xor = h1 ^ h2
            diff = bin(xor).count("1")
            score = 1.0 - (diff / 256.0)
            return score, "MATCHED" if score >= FACE_MATCH_THRESHOLD else "MISMATCH"
        except Exception:
            return None, "COMPARISON_ERROR"


# ── Clock In with Selfie ──────────────────────────────────────


@face_attendance_bp.route("/clock-in", methods=["POST"])
@require_auth
def clock_in():
    """
    Clock in with selfie face verification.
    Accepts multipart/form-data with:
        - selfie: image file (required)
        - latitude: float
        - longitude: float
        - accuracy: float
        - device_info: string
    """
    _ensure_tables()
    user = g.current_user
    tech_id = user.p_user_id or user.id

    # Check not already clocked in today
    existing = execute_kelava_query_single(
        """
        SELECT id FROM face_attendance_logs
        WHERE technician_id = %s AND punch_type = 'clock_in'
          AND punch_time::date = CURRENT_DATE
        """,
        (tech_id,),
    )
    if existing:
        return jsonify({"error": "Sudah clock-in hari ini"}), 409

    # Get selfie file
    selfie = request.files.get("selfie")
    if not selfie:
        return jsonify({"error": "Selfie photo required"}), 400

    ext = (selfie.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "Invalid image format"}), 400

    # Save selfie
    os.makedirs(SELFIE_DIR, exist_ok=True)
    filename = f"{tech_id}_{date.today().isoformat()}_{uuid.uuid4().hex[:8]}.{ext}"
    selfie_path = os.path.join(SELFIE_DIR, secure_filename(filename))
    selfie.save(selfie_path)

    # Find reference photo
    ref_path = None
    ref_dir = os.path.join(STAFF_PHOTO_DIR, str(tech_id))
    if os.path.isdir(ref_dir):
        for f in os.listdir(ref_dir):
            if f.rsplit(".", 1)[-1].lower() in ALLOWED_EXT:
                ref_path = os.path.join(ref_dir, f)
                break

    # Compare faces
    match_score = None
    match_result = "NO_REFERENCE"
    if ref_path:
        match_score, match_result = _compare_faces(selfie_path, ref_path)

    lat = request.form.get("latitude")
    lng = request.form.get("longitude")

    result = execute_kelava_query_single(
        """
        INSERT INTO face_attendance_logs
            (technician_id, punch_type, selfie_path, reference_path,
             match_score, match_result, latitude, longitude, accuracy, device_info, punch_time)
        VALUES (%s, 'clock_in', %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        RETURNING id, match_score, match_result, punch_time
        """,
        (
            tech_id, selfie_path, ref_path,
            match_score, match_result,
            lat, lng,
            request.form.get("accuracy"),
            request.form.get("device_info", ""),
        ),
    )

    return jsonify({
        "id": result["id"],
        "match_result": match_result,
        "match_score": float(match_score) if match_score else None,
        "punch_time": result["punch_time"].isoformat() if result["punch_time"] else None,
        "message": "Clock-in berhasil" if match_result in ("MATCHED", "NO_REFERENCE") else "Clock-in tercatat, verifikasi wajah gagal",
    }), 201


# ── Clock Out ─────────────────────────────────────────────────


@face_attendance_bp.route("/clock-out", methods=["POST"])
@require_auth
def clock_out():
    """
    Clock out (simpler — selfie optional).
    Accepts multipart/form-data or JSON with latitude/longitude.
    """
    _ensure_tables()
    user = g.current_user
    tech_id = user.p_user_id or user.id

    lat = request.form.get("latitude") or (request.json or {}).get("latitude")
    lng = request.form.get("longitude") or (request.json or {}).get("longitude")

    # Save selfie if provided
    selfie_path = None
    selfie = request.files.get("selfie") if request.content_type and "multipart" in request.content_type else None
    if selfie:
        os.makedirs(SELFIE_DIR, exist_ok=True)
        ext = (selfie.filename or "").rsplit(".", 1)[-1].lower()
        if ext in ALLOWED_EXT:
            filename = f"{tech_id}_{date.today().isoformat()}_out_{uuid.uuid4().hex[:8]}.{ext}"
            selfie_path = os.path.join(SELFIE_DIR, secure_filename(filename))
            selfie.save(selfie_path)

    result = execute_kelava_query_single(
        """
        INSERT INTO face_attendance_logs
            (technician_id, punch_type, selfie_path, match_result,
             latitude, longitude, punch_time)
        VALUES (%s, 'clock_out', %s, 'N/A', %s, %s, NOW())
        RETURNING id, punch_time
        """,
        (tech_id, selfie_path, lat, lng),
    )

    return jsonify({
        "id": result["id"],
        "punch_time": result["punch_time"].isoformat() if result["punch_time"] else None,
        "message": "Clock-out berhasil",
    }), 201


# ── Today's Attendance Board ──────────────────────────────────


@face_attendance_bp.route("/today", methods=["GET"])
@require_auth
def today_board():
    """Today's face attendance board."""
    _ensure_tables()
    target_date = request.args.get("date", date.today().isoformat())

    rows = execute_kelava_query(
        """
        SELECT
            fa.technician_id,
            u.fullname AS tech_name,
            MIN(CASE WHEN fa.punch_type = 'clock_in' THEN fa.punch_time END) AS clock_in_time,
            MAX(CASE WHEN fa.punch_type = 'clock_out' THEN fa.punch_time END) AS clock_out_time,
            MIN(CASE WHEN fa.punch_type = 'clock_in' THEN fa.match_result END) AS face_result,
            MIN(CASE WHEN fa.punch_type = 'clock_in' THEN fa.match_score END) AS face_score,
            MIN(CASE WHEN fa.punch_type = 'clock_in' THEN fa.latitude END) AS clock_in_lat,
            MIN(CASE WHEN fa.punch_type = 'clock_in' THEN fa.longitude END) AS clock_in_lng
        FROM face_attendance_logs fa
        JOIN p_user u ON u.id = fa.technician_id
        WHERE fa.punch_time::date = %s::date
        GROUP BY fa.technician_id, u.fullname
        ORDER BY clock_in_time
        """,
        (target_date,),
    )

    return jsonify({
        "date": target_date,
        "attendance": [_fmt(r) for r in rows],
        "total_present": len(rows),
    })


# ── Manual Override (admin) ───────────────────────────────────


@face_attendance_bp.route("/<int:log_id>/override", methods=["POST"])
@require_auth
def override_result(log_id):
    """Admin manually overrides face match result."""
    data = request.json or {}
    reason = data.get("reason", "")
    new_result = data.get("result", "MATCHED")

    if not reason:
        return jsonify({"error": "Reason required for override"}), 400

    execute_kelava_query(
        """
        UPDATE face_attendance_logs
        SET match_result = %s, verified_by = %s, verified_at = NOW(), override_reason = %s
        WHERE id = %s
        """,
        (new_result, g.current_user.full_name, reason, log_id),
    )

    return jsonify({"message": "Override applied"})
