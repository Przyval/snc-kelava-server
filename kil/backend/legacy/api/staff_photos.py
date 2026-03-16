"""
Staff Photo Management API
============================
Upload/manage technician profile photos.
Photos are stored as <p_user_id>.jpg in static/img/staff/.
"""

import os
from pathlib import Path

from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from core.security import require_auth, require_role
from kil.db.kelava_db import execute_kelava_query

staff_photos_bp = Blueprint("staff_photos", __name__)

STATIC_STAFF_DIR = (
    Path(__file__).parent.parent / "web" / "enterprise" / "static" / "img" / "staff"
)
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@staff_photos_bp.route("/staff-photos", methods=["GET"])
@require_auth
def list_photos():
    """List all staff photos with metadata."""
    STATIC_STAFF_DIR.mkdir(parents=True, exist_ok=True)
    photos = list(STATIC_STAFF_DIR.glob("*.jpg"))

    # Get user names for the IDs
    if photos:
        ids = [int(p.stem) for p in photos if p.stem.isdigit()]
        if ids:
            placeholders = ",".join(["%s"] * len(ids))
            users = execute_kelava_query(
                f"SELECT id, fullname FROM p_user WHERE id IN ({placeholders})",
                tuple(ids),
            )
            user_map = {u["id"]: u["fullname"] for u in users}
        else:
            user_map = {}
    else:
        user_map = {}

    result = []
    for p in sorted(photos):
        if p.stem.isdigit():
            uid = int(p.stem)
            result.append({
                "p_user_id": uid,
                "fullname": user_map.get(uid, "Unknown"),
                "filename": p.name,
                "size_kb": round(p.stat().st_size / 1024, 1),
                "url": f"/enterprise/static/img/staff/{p.name}",
            })

    return jsonify({"photos": result, "count": len(result)})


@staff_photos_bp.route("/staff-photos/<int:p_user_id>", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def upload_photo(p_user_id: int):
    """
    Upload/replace staff photo for a technician.

    Accepts multipart/form-data with file field 'photo'.
    Auto-resizes to 200x200 thumbnail.
    """
    if "photo" not in request.files:
        return jsonify({"error": "No photo file provided"}), 400

    file = request.files["photo"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"error": "Only JPG/PNG files allowed"}), 400

    # Read file and check size
    file_data = file.read()
    if len(file_data) > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 5MB)"}), 400

    # Verify user exists
    user = execute_kelava_query(
        "SELECT id, fullname FROM p_user WHERE id = %s", (p_user_id,)
    )
    if not user:
        return jsonify({"error": f"User {p_user_id} not found"}), 404

    STATIC_STAFF_DIR.mkdir(parents=True, exist_ok=True)
    dst = STATIC_STAFF_DIR / f"{p_user_id}.jpg"

    try:
        from PIL import Image
        from io import BytesIO

        img = Image.open(BytesIO(file_data))
        img = img.convert("RGB")

        # Center crop to square
        w, h = img.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))

        img = img.resize((200, 200), Image.LANCZOS)
        img.save(dst, "JPEG", quality=85)
    except ImportError:
        # Fallback: save raw (no resize)
        with open(dst, "wb") as f:
            f.write(file_data)

    size_kb = round(dst.stat().st_size / 1024, 1)

    return jsonify({
        "message": f"Photo uploaded for {user[0]['fullname']}",
        "p_user_id": p_user_id,
        "filename": f"{p_user_id}.jpg",
        "size_kb": size_kb,
        "url": f"/enterprise/static/img/staff/{p_user_id}.jpg",
    })


@staff_photos_bp.route("/staff-photos/<int:p_user_id>", methods=["DELETE"])
@require_auth
@require_role("admin", "koordinator")
def delete_photo(p_user_id: int):
    """Delete staff photo for a technician."""
    dst = STATIC_STAFF_DIR / f"{p_user_id}.jpg"
    if not dst.exists():
        return jsonify({"error": "Photo not found"}), 404

    dst.unlink()
    return jsonify({"message": f"Photo deleted for user {p_user_id}"})
