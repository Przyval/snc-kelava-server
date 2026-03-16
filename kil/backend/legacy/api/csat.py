"""
Customer Satisfaction Score (CSAT) API
=======================================
Collect and analyze customer satisfaction ratings after service visits.
Supports:
- Post-visit satisfaction survey (1-5 stars + optional comment)
- CSAT dashboard with aggregated scores
- Technician-level CSAT ranking
- Customer-level satisfaction history
"""

from datetime import datetime

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single
from kil.backend.legacy.api.audit_log import log_action

csat_bp = Blueprint("csat", __name__, url_prefix="/csat")

_TABLE_ENSURED = False


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Submit Rating ────────────────────────────────────────────


@csat_bp.route("/submit", methods=["POST"])
@require_auth
def submit_rating():
    """
    Submit a CSAT rating for a visit.
    Body: {
        visit_id?: int,
        road_plan_id?: int,
        customer_id: int,
        technician_id: int,
        rating: 1-5,
        comment?: str,
        category?: str (service_quality, punctuality, professionalism, cleanliness, overall)
    }
    """
    _ensure_tables()
    data = request.json or {}

    customer_id = data.get("customer_id")
    tech_id = data.get("technician_id")
    rating = data.get("rating")

    if not customer_id or not tech_id or rating is None:
        return jsonify({"error": "customer_id, technician_id, and rating are required"}), 400

    rating = int(rating)
    if rating < 1 or rating > 5:
        return jsonify({"error": "rating must be 1-5"}), 400

    user = getattr(g, "current_user", None)
    submitted_by = user.id if user else None

    result = execute_kelava_query_single(
        """
        INSERT INTO csat_ratings
            (visit_id, road_plan_id, customer_id, technician_id, rating, comment, category, submitted_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            data.get("visit_id"),
            data.get("road_plan_id"),
            customer_id,
            tech_id,
            rating,
            data.get("comment", ""),
            data.get("category", "overall"),
            submitted_by,
        ),
    )

    log_action("csat", "create", "rating", result["id"] if result else None,
               f"CSAT {rating}/5 for tech {tech_id}, customer {customer_id}")

    return jsonify({"id": result["id"] if result else None, "status": "submitted"}), 201


# ── Dashboard ────────────────────────────────────────────────


@csat_bp.route("/dashboard", methods=["GET"])
@require_auth
def csat_dashboard():
    """CSAT overview with aggregated metrics."""
    _ensure_tables()
    days = int(request.args.get("days", 90))

    overall = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total_ratings,
            ROUND(AVG(rating)::numeric, 2) AS avg_rating,
            COUNT(*) FILTER (WHERE rating >= 4) AS satisfied,
            COUNT(*) FILTER (WHERE rating <= 2) AS dissatisfied,
            ROUND(COUNT(*) FILTER (WHERE rating >= 4)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS csat_pct,
            COUNT(DISTINCT customer_id) AS customers_rated,
            COUNT(DISTINCT technician_id) AS technicians_rated
        FROM csat_ratings
        WHERE created_at >= NOW() - INTERVAL '%s days'
        """,
        (days,),
    )

    # Rating distribution
    distribution = execute_kelava_query(
        """
        SELECT rating, COUNT(*) AS count
        FROM csat_ratings
        WHERE created_at >= NOW() - INTERVAL '%s days'
        GROUP BY rating ORDER BY rating
        """,
        (days,),
    )

    # By category
    by_category = execute_kelava_query(
        """
        SELECT category, ROUND(AVG(rating)::numeric, 2) AS avg_rating, COUNT(*) AS count
        FROM csat_ratings
        WHERE created_at >= NOW() - INTERVAL '%s days'
        GROUP BY category ORDER BY avg_rating DESC
        """,
        (days,),
    )

    # Monthly trend
    trend = execute_kelava_query(
        """
        SELECT
            TO_CHAR(created_at, 'YYYY-MM') AS month,
            ROUND(AVG(rating)::numeric, 2) AS avg_rating,
            COUNT(*) AS count,
            ROUND(COUNT(*) FILTER (WHERE rating >= 4)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS csat_pct
        FROM csat_ratings
        WHERE created_at >= NOW() - INTERVAL '%s days'
        GROUP BY month ORDER BY month
        """,
        (days,),
    )

    return jsonify({
        "overall": _fmt(overall) if overall else {},
        "distribution": [_fmt(d) for d in distribution],
        "by_category": [_fmt(c) for c in by_category],
        "trend": [_fmt(t) for t in trend],
        "days": days,
    })


# ── Technician CSAT Ranking ─────────────────────────────────


@csat_bp.route("/technicians", methods=["GET"])
@require_auth
def technician_csat():
    """CSAT ranking by technician."""
    _ensure_tables()
    days = int(request.args.get("days", 90))

    rows = execute_kelava_query(
        """
        SELECT
            cr.technician_id,
            u.fullname AS tech_name,
            ROUND(AVG(cr.rating)::numeric, 2) AS avg_rating,
            COUNT(*) AS total_ratings,
            COUNT(*) FILTER (WHERE cr.rating >= 4) AS satisfied,
            COUNT(*) FILTER (WHERE cr.rating <= 2) AS dissatisfied,
            ROUND(COUNT(*) FILTER (WHERE cr.rating >= 4)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS csat_pct
        FROM csat_ratings cr
        JOIN p_user u ON u.id = cr.technician_id
        WHERE cr.created_at >= NOW() - INTERVAL '%s days'
        GROUP BY cr.technician_id, u.fullname
        HAVING COUNT(*) >= 3
        ORDER BY avg_rating DESC, total_ratings DESC
        """,
        (days,),
    )

    return jsonify({"technicians": [_fmt(r) for r in rows], "days": days})


# ── Customer CSAT History ────────────────────────────────────


@csat_bp.route("/customers/<int:customer_id>", methods=["GET"])
@require_auth
def customer_csat(customer_id: int):
    """CSAT history for a specific customer."""
    _ensure_tables()

    ratings = execute_kelava_query(
        """
        SELECT cr.*, u.fullname AS tech_name
        FROM csat_ratings cr
        LEFT JOIN p_user u ON u.id = cr.technician_id
        WHERE cr.customer_id = %s
        ORDER BY cr.created_at DESC
        LIMIT 50
        """,
        (customer_id,),
    )

    summary = execute_kelava_query_single(
        """
        SELECT
            ROUND(AVG(rating)::numeric, 2) AS avg_rating,
            COUNT(*) AS total,
            ROUND(COUNT(*) FILTER (WHERE rating >= 4)::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS csat_pct
        FROM csat_ratings WHERE customer_id = %s
        """,
        (customer_id,),
    )

    return jsonify({
        "customer_id": customer_id,
        "ratings": [_fmt(r) for r in ratings],
        "summary": _fmt(summary) if summary else {},
    })


# ── Recent Feedback (with comments) ─────────────────────────


@csat_bp.route("/feedback", methods=["GET"])
@require_auth
def recent_feedback():
    """Recent ratings with comments for review."""
    _ensure_tables()
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 50)
    offset = (page - 1) * per_page
    min_rating = request.args.get("max_rating")  # For filtering low scores

    where = "cr.comment IS NOT NULL AND cr.comment != ''"
    params = []
    if min_rating:
        where += " AND cr.rating <= %s"
        params.append(int(min_rating))

    params.extend([per_page, offset])

    rows = execute_kelava_query(
        f"""
        SELECT cr.*, u.fullname AS tech_name, c.name AS customer_name
        FROM csat_ratings cr
        LEFT JOIN p_user u ON u.id = cr.technician_id
        LEFT JOIN m_customer c ON c.id = cr.customer_id
        WHERE {where}
        ORDER BY cr.created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    return jsonify({"feedback": [_fmt(r) for r in rows], "page": page})


# ── Table Setup ──────────────────────────────────────────────


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS csat_ratings (
            id BIGSERIAL PRIMARY KEY,
            visit_id BIGINT,
            road_plan_id BIGINT,
            customer_id BIGINT NOT NULL,
            technician_id BIGINT NOT NULL,
            rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment TEXT,
            category TEXT DEFAULT 'overall',
            submitted_by BIGINT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    execute_kelava_query("CREATE INDEX IF NOT EXISTS idx_csat_customer ON csat_ratings(customer_id)")
    execute_kelava_query("CREATE INDEX IF NOT EXISTS idx_csat_tech ON csat_ratings(technician_id)")
    execute_kelava_query("CREATE INDEX IF NOT EXISTS idx_csat_created ON csat_ratings(created_at DESC)")
    _TABLE_ENSURED = True
