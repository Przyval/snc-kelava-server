"""
Daily Digest API
=================
Auto-generate daily operations summary:
- Triggered via cron or manual POST
- Can send to WhatsApp (koordinator) or just store
- Covers: visit completion, missed SLA, complaints, contract alerts
"""

from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

daily_digest_bp = Blueprint("daily_digest", __name__, url_prefix="/daily-digest")

_TABLE_ENSURED = False


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Generate Daily Digest ──────────────────────────────────


@daily_digest_bp.route("/generate", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def generate_digest():
    """
    Generate daily digest for a given date.
    Body: { date?: "YYYY-MM-DD", send_wa?: bool }
    Defaults to yesterday.
    """
    _ensure_table()
    data = request.json or {}
    target_date = data.get("date")
    send_wa = data.get("send_wa", False)

    if not target_date:
        target_date = (datetime.now().date() - timedelta(days=1)).isoformat()

    # Check for existing digest
    existing = execute_kelava_query_single(
        "SELECT id FROM daily_digests WHERE digest_date = %s", (target_date,),
    )
    if existing:
        return jsonify({"error": "Digest already exists for this date", "id": existing["id"]}), 409

    digest = _build_digest(target_date)

    # Store
    stored = execute_kelava_query_single(
        """
        INSERT INTO daily_digests (digest_date, digest_data, generated_by)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (target_date, __import__("json").dumps(digest, default=str), getattr(getattr(g, "current_user", None), "id", None)),
    )

    # Optionally send via WA
    wa_result = None
    if send_wa:
        wa_result = _send_digest_wa(digest, target_date)

    return jsonify({
        "id": stored["id"] if stored else None,
        "date": target_date,
        "digest": digest,
        "wa_sent": wa_result,
    })


# ── Get Latest Digest ─────────────────────────────────────


@daily_digest_bp.route("/latest", methods=["GET"])
@require_auth
def latest_digest():
    """Get the most recent daily digest."""
    _ensure_table()
    row = execute_kelava_query_single(
        "SELECT * FROM daily_digests ORDER BY digest_date DESC LIMIT 1"
    )
    if not row:
        return jsonify({"error": "No digests generated yet"}), 404

    result = _fmt(row)
    if result.get("digest_data") and isinstance(result["digest_data"], str):
        result["digest_data"] = __import__("json").loads(result["digest_data"])
    return jsonify({"digest": result})


# ── Digest History ─────────────────────────────────────────


@daily_digest_bp.route("/history", methods=["GET"])
@require_auth
def digest_history():
    """List generated digests. Query params: days (default 30)"""
    _ensure_table()
    days = int(request.args.get("days", 30))
    rows = execute_kelava_query(
        """
        SELECT id, digest_date, generated_at, generated_by
        FROM daily_digests
        WHERE digest_date >= CURRENT_DATE - %s
        ORDER BY digest_date DESC
        """,
        (days,),
    )
    return jsonify({"digests": [_fmt(r) for r in rows]})


# ── Preview (don't save) ──────────────────────────────────


@daily_digest_bp.route("/preview", methods=["GET"])
@require_auth
def preview_digest():
    """Preview today's digest without saving."""
    target_date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    digest = _build_digest(target_date)
    return jsonify({"date": target_date, "digest": digest})


# ── Build Digest ──────────────────────────────────────────


def _build_digest(date_str: str) -> dict:
    """Collect all metrics for the daily digest."""

    # Visit summary
    visits = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total_planned,
            COUNT(*) FILTER (WHERE status = 'Selesai') AS completed,
            COUNT(*) FILTER (WHERE status NOT IN ('Selesai', 'Berjalan')) AS missed,
            COUNT(DISTINCT id_user) AS active_techs,
            ROUND(COUNT(*) FILTER (WHERE status = 'Selesai')::numeric
                  / NULLIF(COUNT(*), 0) * 100, 1) AS completion_rate
        FROM t_road_plan
        WHERE visit_date::date = %s
        """,
        (date_str,),
    )

    # Top performers (top 3)
    top = execute_kelava_query(
        """
        SELECT u.fullname,
               COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
               COUNT(*) AS planned,
               ROUND(COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric
                     / NULLIF(COUNT(*), 0) * 100, 0) AS rate
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.visit_date::date = %s
        GROUP BY u.id, u.fullname
        HAVING COUNT(*) >= 2
        ORDER BY rate DESC, completed DESC
        LIMIT 3
        """,
        (date_str,),
    )

    # Bottom performers (bottom 3)
    bottom = execute_kelava_query(
        """
        SELECT u.fullname,
               COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
               COUNT(*) AS planned,
               ROUND(COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric
                     / NULLIF(COUNT(*), 0) * 100, 0) AS rate
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.visit_date::date = %s
        GROUP BY u.id, u.fullname
        HAVING COUNT(*) >= 2
        ORDER BY rate ASC, completed ASC
        LIMIT 3
        """,
        (date_str,),
    )

    # Duration stats
    duration = execute_kelava_query_single(
        """
        SELECT
            ROUND(AVG(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 0) AS avg_min,
            ROUND(MIN(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 0) AS min_min,
            ROUND(MAX(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 0) AS max_min
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE rp.visit_date::date = %s
          AND v.check_in IS NOT NULL AND v.check_out IS NOT NULL
          AND v.check_out > v.check_in
          AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) BETWEEN 60 AND 28800
        """,
        (date_str,),
    )

    # Open complaints count
    try:
        complaints = execute_kelava_query_single(
            "SELECT COUNT(*) AS cnt FROM complaints WHERE status NOT IN ('resolved', 'closed')"
        )
        open_complaints = complaints["cnt"] if complaints else 0
    except Exception:
        open_complaints = 0

    # Contracts expiring this week
    expiring = execute_kelava_query_single(
        """
        SELECT COUNT(*) AS cnt
        FROM m_customer_kontrak
        WHERE is_active = 'YES'
          AND end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7
        """
    )

    return {
        "date": date_str,
        "visits": _fmt(visits) if visits else {},
        "top_performers": [_fmt(t) for t in top],
        "bottom_performers": [_fmt(b) for b in bottom],
        "duration": _fmt(duration) if duration else {},
        "open_complaints": open_complaints,
        "contracts_expiring_7d": expiring["cnt"] if expiring else 0,
    }


# ── Send via WhatsApp ─────────────────────────────────────


def _send_digest_wa(digest: dict, date_str: str) -> dict:
    """Format digest as WA message and send to koordinators."""
    try:
        from kil.backend.legacy.api.wa_gateway import send_whatsapp
    except ImportError:
        return {"success": False, "detail": "WA gateway not available"}

    v = digest.get("visits", {})
    rate = v.get("completion_rate", 0)
    top = digest.get("top_performers", [])

    msg = (
        f"*Laporan Harian SanoCare - {date_str}*\n\n"
        f"📊 *Kunjungan*\n"
        f"  Total: {v.get('total_planned', 0)}\n"
        f"  Selesai: {v.get('completed', 0)} ({rate}%)\n"
        f"  Missed: {v.get('missed', 0)}\n"
        f"  Teknisi aktif: {v.get('active_techs', 0)}\n\n"
    )

    if top:
        msg += "🏆 *Top Performers*\n"
        for i, t in enumerate(top, 1):
            msg += f"  {i}. {t.get('fullname', 'N/A')} - {t.get('rate', 0)}%\n"
        msg += "\n"

    dur = digest.get("duration", {})
    if dur.get("avg_min"):
        msg += f"⏱ Durasi rata-rata: {dur['avg_min']} menit\n"

    if digest.get("open_complaints"):
        msg += f"⚠️ Komplain terbuka: {digest['open_complaints']}\n"
    if digest.get("contracts_expiring_7d"):
        msg += f"📋 Kontrak expiring minggu ini: {digest['contracts_expiring_7d']}\n"

    # Get koordinator phones
    koordinators = execute_kelava_query(
        """
        SELECT eu.id, u.phone, u.fullname
        FROM enterprise_users eu
        JOIN p_user u ON u.id = eu.p_user_id
        WHERE eu.role = 'koordinator' AND eu.is_active = true
          AND u.phone IS NOT NULL AND u.phone != ''
        """
    )

    sent = 0
    failed = 0
    for k in koordinators:
        result = send_whatsapp(k["phone"], msg)
        if result.get("success"):
            sent += 1
        else:
            failed += 1

    return {"sent": sent, "failed": failed, "recipients": len(koordinators)}


# ── Table Setup ────────────────────────────────────────────


def _ensure_table():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS daily_digests (
            id BIGSERIAL PRIMARY KEY,
            digest_date DATE UNIQUE NOT NULL,
            digest_data JSONB,
            generated_by BIGINT,
            generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    execute_kelava_query("CREATE INDEX IF NOT EXISTS idx_digest_date ON daily_digests(digest_date DESC)")
    _TABLE_ENSURED = True
