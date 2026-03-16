from datetime import datetime

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import get_kelava_connection

tracking_bp = Blueprint("tracking", __name__)


@tracking_bp.route("/tracking/position", methods=["POST"])
@require_auth
def receive_position():
    """
    Receive high-frequency GPS position from technician app.
    Payload: { "lat": -7.25, "lng": 112.75, "timestamp": "ISO...", "tech_id": 123 }
    """
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    required_fields = ["lat", "lng", "tech_id"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    lat = data["lat"]
    lng = data["lng"]
    tech_id = data["tech_id"]
    timestamp = data.get("timestamp", datetime.now().isoformat())

    try:
        conn = get_kelava_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gps_positions (internal_id, latitude, longitude, captured_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (tech_id, lat, lng, timestamp),
            )
            new_id = cur.fetchone()[0]
            conn.commit()

        return jsonify({"status": "success", "id": new_id}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
