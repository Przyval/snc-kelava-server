"""
Photo & GPS Verification API
==============================
Service evidence verification, anomaly detection, and compliance scoring.
"""

import hashlib
import os
from io import BytesIO
from pathlib import Path

import httpx
from flask import Blueprint, g, jsonify, request, send_file

from core.security import require_auth
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

# Photo proxy config
KELAVA_PHOTO_BASE = "https://app.kelava.id/sanocare/repo/"
PHOTO_CACHE_DIR = Path(os.environ.get("PHOTO_CACHE_DIR", "/tmp/sanocare_photo_cache"))
PHOTO_SIZES = {
    "thumb": (300, 300, 60),    # width, height, quality
    "medium": (800, 800, 75),
    "full": (1600, 1600, 80),
}

verification_bp = Blueprint("verification", __name__, url_prefix="/verification")


# ── Dashboard Overview ────────────────────────────────────────


@verification_bp.route("/dashboard", methods=["GET"])
@require_auth
def dashboard():
    """Verification dashboard overview with anomaly counts and trends."""
    days = int(request.args.get("days", 30))
    interval = f"{days} days"

    # Overall anomaly counts
    summary = execute_kelava_query_single(f"""
        SELECT
            COUNT(*) as total_visits,
            SUM(CASE WHEN flag_no_photo THEN 1 ELSE 0 END) as no_photo,
            SUM(CASE WHEN flag_no_gps THEN 1 ELSE 0 END) as no_gps,
            SUM(CASE WHEN flag_gps_drift THEN 1 ELSE 0 END) as gps_drift,
            SUM(CASE WHEN flag_too_short THEN 1 ELSE 0 END) as too_short,
            SUM(CASE WHEN flag_too_long THEN 1 ELSE 0 END) as too_long,
            ROUND(AVG(photo_count)::numeric, 1) as avg_photos,
            ROUND(AVG(CASE WHEN drift_meters IS NOT NULL THEN drift_meters END)::numeric, 0) as avg_drift_m
        FROM v_visit_verification
        WHERE check_in > NOW() - INTERVAL '{interval}'
    """)

    # Unresolved flags
    unresolved = execute_kelava_query_single(
        "SELECT COUNT(*) as cnt FROM verification_flags WHERE resolved = false"
    )

    # Daily trend (last N days)
    daily = execute_kelava_query(f"""
        SELECT
            check_in::date as day,
            COUNT(*) as visits,
            SUM(CASE WHEN flag_no_photo THEN 1 ELSE 0 END) as no_photo,
            SUM(CASE WHEN flag_gps_drift THEN 1 ELSE 0 END) as gps_drift
        FROM v_visit_verification
        WHERE check_in > NOW() - INTERVAL '{interval}'
        GROUP BY check_in::date
        ORDER BY day DESC
        LIMIT 30
    """)

    for d in daily:
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()

    result = dict(summary) if summary else {}
    for k, v in result.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        if v is None:
            result[k] = 0

    result["unresolved_flags"] = unresolved["cnt"] if unresolved else 0
    result["daily_trend"] = daily

    return jsonify(result)


# ── Technician Scorecard ──────────────────────────────────────


@verification_bp.route("/scorecards", methods=["GET"])
@require_auth
def scorecards():
    """Technician compliance scorecards (30-day window)."""
    sort = request.args.get("sort", "compliance_pct")
    order = request.args.get("order", "asc")

    valid_sorts = {
        "compliance_pct", "total_visits", "no_photo_visits",
        "gps_drift_visits", "too_short_visits", "technician_name",
    }
    if sort not in valid_sorts:
        sort = "compliance_pct"

    direction = "ASC" if order == "asc" else "DESC"

    rows = execute_kelava_query(f"""
        SELECT * FROM v_tech_verification_score
        ORDER BY {sort} {direction} NULLS LAST
    """)

    for r in rows:
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
            elif isinstance(v, (float,)) and v != v:  # NaN check
                r[k] = None

    return jsonify({"scorecards": rows})


# ── Flagged Visits (Anomalies) ────────────────────────────────


@verification_bp.route("/anomalies", methods=["GET"])
@require_auth
def anomalies():
    """List visits with anomaly flags."""
    flag_type = request.args.get("type", "")  # no_photo, gps_drift, too_short, too_long, no_gps
    tech_id = request.args.get("technician_id", "")
    days = int(request.args.get("days", 7))
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, int(request.args.get("per_page", 30)))

    conditions = [f"check_in > NOW() - INTERVAL '{days} days'"]
    params = []

    if flag_type == "no_photo":
        conditions.append("flag_no_photo = true")
    elif flag_type == "gps_drift":
        conditions.append("flag_gps_drift = true")
    elif flag_type == "too_short":
        conditions.append("flag_too_short = true")
    elif flag_type == "too_long":
        conditions.append("flag_too_long = true")
    elif flag_type == "no_gps":
        conditions.append("flag_no_gps = true")
    else:
        # Show any flagged visit
        conditions.append(
            "(flag_no_photo OR flag_gps_drift OR flag_too_short OR flag_too_long OR flag_no_gps)"
        )

    if tech_id:
        conditions.append("technician_id = %s")
        params.append(int(tech_id))

    where = "WHERE " + " AND ".join(conditions)

    total = execute_kelava_query_single(
        f"SELECT COUNT(*) as cnt FROM v_visit_verification {where}", params
    )

    visits = execute_kelava_query(
        f"""
        SELECT visit_id, road_plan_id, technician_id, technician_name,
               customer_id, customer_name, check_in, check_out,
               ROUND(duration_minutes::numeric, 1) as duration_minutes,
               checkin_lat, checkin_lng, checkout_lat, checkout_lng,
               ROUND(drift_meters::numeric, 0) as drift_meters,
               photo_count, flag_no_photo, flag_gps_drift,
               flag_too_short, flag_too_long, flag_no_gps
        FROM v_visit_verification
        {where}
        ORDER BY check_in DESC
        LIMIT %s OFFSET %s
        """,
        params + [per_page, (page - 1) * per_page],
    )

    for v in visits:
        for k, val in v.items():
            if hasattr(val, "isoformat"):
                v[k] = val.isoformat()

    return jsonify({
        "anomalies": visits,
        "total": total["cnt"],
        "page": page,
        "per_page": per_page,
    })


# ── Visit Detail with Photos ─────────────────────────────────


@verification_bp.route("/visit/<int:visit_id>", methods=["GET"])
@require_auth
def visit_detail(visit_id):
    """Full verification detail for a single visit: GPS, photos, flags."""
    visit = execute_kelava_query_single(
        """
        SELECT * FROM v_visit_verification WHERE visit_id = %s
        """,
        (visit_id,),
    )

    if not visit:
        return jsonify({"error": "Visit not found"}), 404

    # Get photos
    photos = execute_kelava_query(
        "SELECT id, path FROM t_road_plan_foto WHERE id_road_plan = %s ORDER BY id",
        (visit.get("road_plan_id"),),
    ) if visit.get("road_plan_id") else []

    # Get existing flags
    flags = execute_kelava_query(
        """
        SELECT * FROM verification_flags
        WHERE visit_id = %s
        ORDER BY created_at DESC
        """,
        (visit_id,),
    )

    for k, v in visit.items():
        if hasattr(v, "isoformat"):
            visit[k] = v.isoformat()

    for f in flags:
        for k, v in f.items():
            if hasattr(v, "isoformat"):
                f[k] = v.isoformat()

    return jsonify({
        "visit": visit,
        "photos": photos,
        "flags": flags,
    })


# ── Flag a Visit (Create Manual Flag) ────────────────────────


@verification_bp.route("/flag", methods=["POST"])
@require_auth
def create_flag():
    """Manually flag a visit for review."""
    data = request.json or {}
    visit_id = data.get("visit_id")
    flag_type = data.get("flag_type")
    severity = data.get("severity", "warning")
    detail = data.get("detail", "")

    if not visit_id or not flag_type:
        return jsonify({"error": "visit_id and flag_type are required"}), 400

    if flag_type not in ("NO_PHOTO", "GPS_DRIFT", "TOO_SHORT", "TOO_LONG", "SUSPICIOUS", "MANUAL"):
        return jsonify({"error": "Invalid flag_type"}), 400

    if severity not in ("info", "warning", "critical"):
        return jsonify({"error": "Invalid severity"}), 400

    # Get visit data
    visit = execute_kelava_query_single(
        """
        SELECT visit_id, road_plan_id, technician_id, customer_id,
               checkin_lat, checkin_lng, checkout_lat, checkout_lng,
               drift_meters, photo_count
        FROM v_visit_verification WHERE visit_id = %s
        """,
        (visit_id,),
    )

    if not visit:
        return jsonify({"error": "Visit not found"}), 404

    result = execute_kelava_query_single(
        """
        INSERT INTO verification_flags
            (visit_id, road_plan_id, technician_id, customer_id, flag_type, severity, detail,
             gps_checkin_lat, gps_checkin_lng, gps_checkout_lat, gps_checkout_lng,
             drift_meters, photo_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            visit_id, visit["road_plan_id"], visit["technician_id"],
            visit["customer_id"], flag_type, severity, detail,
            visit["checkin_lat"], visit["checkin_lng"],
            visit["checkout_lat"], visit["checkout_lng"],
            visit["drift_meters"], visit["photo_count"],
        ),
    )

    return jsonify({"id": result["id"], "message": "Flag created"}), 201


# ── Resolve a Flag ────────────────────────────────────────────


@verification_bp.route("/flag/<int:flag_id>/resolve", methods=["POST"])
@require_auth
def resolve_flag(flag_id):
    """Mark a flag as resolved with notes."""
    data = request.json or {}
    note = data.get("note", "")

    user_name = getattr(g, "user", None) and g.user.full_name or "Unknown"

    execute_kelava_query(
        """
        UPDATE verification_flags
        SET resolved = true, resolved_by = %s, resolved_at = NOW(), resolution_note = %s
        WHERE id = %s
        """,
        (user_name, note, flag_id),
    )

    return jsonify({"message": "Flag resolved"})


# ── Run Auto-Detection (Batch) ────────────────────────────────


@verification_bp.route("/scan", methods=["POST"])
@require_auth
def run_scan():
    """Run anomaly detection scan for recent visits and auto-create flags."""
    days = int(request.args.get("days", 7))

    # Find visits with anomalies that aren't already flagged
    anomalies = execute_kelava_query(f"""
        SELECT visit_id, road_plan_id, technician_id, customer_id,
               checkin_lat, checkin_lng, checkout_lat, checkout_lng,
               drift_meters, photo_count,
               flag_no_photo, flag_gps_drift, flag_too_short, flag_too_long
        FROM v_visit_verification
        WHERE check_in > NOW() - INTERVAL '{days} days'
        AND (flag_no_photo OR flag_gps_drift OR flag_too_short OR flag_too_long)
        AND visit_id NOT IN (SELECT visit_id FROM verification_flags WHERE resolved = false)
    """)

    created = 0
    for a in anomalies:
        flags_to_create = []
        if a["flag_no_photo"]:
            flags_to_create.append(("NO_PHOTO", "warning", "No photos uploaded for this visit"))
        if a["flag_gps_drift"]:
            sev = "critical" if (a["drift_meters"] or 0) > 2000 else "warning"
            flags_to_create.append(("GPS_DRIFT", sev, f"Check-in/out GPS drift: {int(a['drift_meters'] or 0)}m"))
        if a["flag_too_short"]:
            flags_to_create.append(("TOO_SHORT", "warning", "Visit duration under 5 minutes"))
        if a["flag_too_long"]:
            flags_to_create.append(("TOO_LONG", "info", "Visit duration over 8 hours"))

        for flag_type, severity, detail in flags_to_create:
            execute_kelava_query(
                """
                INSERT INTO verification_flags
                    (visit_id, road_plan_id, technician_id, customer_id,
                     flag_type, severity, detail,
                     gps_checkin_lat, gps_checkin_lng, gps_checkout_lat, gps_checkout_lng,
                     drift_meters, photo_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    a["visit_id"], a["road_plan_id"], a["technician_id"],
                    a["customer_id"], flag_type, severity, detail,
                    a["checkin_lat"], a["checkin_lng"],
                    a["checkout_lat"], a["checkout_lng"],
                    a["drift_meters"], a["photo_count"],
                ),
            )
            created += 1

    return jsonify({
        "message": f"Scan complete. {created} new flags created from {len(anomalies)} anomalous visits.",
        "flags_created": created,
        "visits_scanned": len(anomalies),
    })


# ── Photo Gallery for Visit ──────────────────────────────────


@verification_bp.route("/photos/<int:road_plan_id>", methods=["GET"])
@require_auth
def visit_photos(road_plan_id):
    """Get all photos for a road plan."""
    photos = execute_kelava_query(
        "SELECT id, path FROM t_road_plan_foto WHERE id_road_plan = %s ORDER BY id",
        (road_plan_id,),
    )
    return jsonify({"photos": photos, "count": len(photos)})


# ── Photo Proxy with Compression ────────────────────────────


ALLOWED_PHOTO_HOSTS = {"app.kelava.id", "dev.kelava.id"}


@verification_bp.route("/photo-proxy", methods=["GET"])
def photo_proxy():
    """Proxy and compress photos from Kelava server.

    No JWT required — <img src> tags can't send auth headers.
    Security: only allows fetching from whitelisted Kelava hosts.

    Query params:
        path: photo path from t_road_plan_foto.path
        size: thumb (300px) | medium (800px) | full (1600px), default=medium
    """
    photo_path = request.args.get("path", "").strip()
    size = request.args.get("size", "medium")

    if not photo_path:
        return jsonify({"error": "path parameter required"}), 400

    if size not in PHOTO_SIZES:
        size = "medium"

    max_w, max_h, quality = PHOTO_SIZES[size]

    # Resolve source URL from various path formats
    if photo_path.startswith("https://") or photo_path.startswith("http://"):
        source_url = photo_path
    elif photo_path.startswith("file://"):
        return jsonify({"error": "Local file path not accessible"}), 404
    else:
        source_url = KELAVA_PHOTO_BASE + photo_path

    # SSRF protection: only allow whitelisted hosts
    from urllib.parse import urlparse

    parsed = urlparse(source_url)
    if parsed.hostname not in ALLOWED_PHOTO_HOSTS:
        return jsonify({"error": "Host not allowed"}), 403

    # Build cache path based on photo path + size
    path_hash = hashlib.md5(photo_path.encode()).hexdigest()
    cache_dir = PHOTO_CACHE_DIR / size
    cache_file = cache_dir / f"{path_hash}.jpg"

    # Serve from cache if exists
    if cache_file.exists():
        return send_file(
            cache_file,
            mimetype="image/jpeg",
            max_age=2592000,  # 30 days browser cache
        )

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(source_url)
            resp.raise_for_status()
    except Exception as e:
        return jsonify({"error": f"Failed to fetch photo: {str(e)}"}), 502

    # Compress with Pillow
    try:
        from PIL import Image

        img = Image.open(BytesIO(resp.content))

        # Convert RGBA/palette to RGB for JPEG
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        # Resize maintaining aspect ratio
        img.thumbnail((max_w, max_h), Image.LANCZOS)

        # Save compressed version to cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        buf.seek(0)

        # Write cache file
        with open(cache_file, "wb") as f:
            f.write(buf.getvalue())

        buf.seek(0)
        return send_file(
            buf,
            mimetype="image/jpeg",
            max_age=2592000,
        )
    except ImportError:
        # Pillow not installed - serve original with cache headers
        return send_file(
            BytesIO(resp.content),
            mimetype=resp.headers.get("content-type", "image/jpeg"),
            max_age=2592000,
        )
    except Exception as e:
        # Corrupted image or other error - serve original
        return send_file(
            BytesIO(resp.content),
            mimetype=resp.headers.get("content-type", "image/jpeg"),
            max_age=2592000,
        )
