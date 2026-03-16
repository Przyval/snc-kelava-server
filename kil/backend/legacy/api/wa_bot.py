"""
WhatsApp Bot Gateway API
=========================
Provides:
1. Webhook endpoint for incoming WA messages
2. Command processing (technicians can query via WA)
3. Send API for automated notifications
4. Message templates for common notifications
5. Message log with delivery tracking
"""

import os
import logging
from datetime import datetime

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single
from kil.backend.legacy.api.wa_gateway import send_whatsapp
from kil.backend.legacy.api.audit_log import log_action

wa_bot_bp = Blueprint("wa_bot", __name__, url_prefix="/wa-bot")
logger = logging.getLogger(__name__)

WA_WEBHOOK_TOKEN = os.environ.get("WA_WEBHOOK_TOKEN", "sanocare-wa-webhook-2026")

_TABLE_ENSURED = False


def _fmt(row):
    if not row:
        return {}
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Webhook (incoming messages) ──────────────────────────────


@wa_bot_bp.route("/webhook", methods=["GET"])
def webhook_verify():
    """Webhook verification (for Fonnte/Meta setup)."""
    token = request.args.get("hub.verify_token") or request.args.get("token")
    challenge = request.args.get("hub.challenge", "ok")
    if token == WA_WEBHOOK_TOKEN:
        return challenge, 200
    return "Forbidden", 403


@wa_bot_bp.route("/webhook", methods=["POST"])
def webhook_receive():
    """
    Receive incoming WA messages and process commands.
    Fonnte webhook format: { "sender": "6281...", "message": "...", "name": "..." }
    """
    data = request.json or {}
    sender = data.get("sender", "")
    message = (data.get("message") or "").strip()
    sender_name = data.get("name", "")

    if not sender or not message:
        return jsonify({"status": "ignored"}), 200

    _ensure_tables()

    # Log incoming message
    execute_kelava_query(
        """
        INSERT INTO wa_message_log (direction, phone, sender_name, message, status)
        VALUES ('incoming', %s, %s, %s, 'received')
        """,
        (sender, sender_name, message),
    )

    # Process command
    reply = _process_command(sender, message)

    if reply:
        # Send reply
        result = send_whatsapp(sender, reply)

        # Log outgoing reply
        execute_kelava_query(
            """
            INSERT INTO wa_message_log (direction, phone, sender_name, message, status, template_name)
            VALUES ('outgoing', %s, %s, %s, %s, 'auto_reply')
            """,
            (sender, "SanoCare Bot", reply, "sent" if result.get("success") else "failed"),
        )

    return jsonify({"status": "processed"}), 200


# ── Send Message API (manual) ───────────────────────────────


@wa_bot_bp.route("/send", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def send_message():
    """
    Send a WA message manually.
    Body: { phone: str, message: str, template_name?: str }
    """
    _ensure_tables()
    data = request.json or {}
    phone = data.get("phone", "").strip()
    message = data.get("message", "").strip()
    template_name = data.get("template_name")

    if not phone or not message:
        return jsonify({"error": "phone and message are required"}), 400

    result = send_whatsapp(phone, message)

    # Log
    user = getattr(g, "current_user", None)
    execute_kelava_query(
        """
        INSERT INTO wa_message_log (direction, phone, message, status, template_name, sent_by)
        VALUES ('outgoing', %s, %s, %s, %s, %s)
        """,
        (phone, message, "sent" if result.get("success") else "failed",
         template_name, user.id if user else None),
    )

    log_action("wa_bot", "send", "message", None, f"WA to {phone}: {message[:50]}")

    return jsonify({"success": result.get("success"), "detail": result.get("detail")})


# ── Bulk Send (notifications) ───────────────────────────────


@wa_bot_bp.route("/send-bulk", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def send_bulk():
    """
    Send WA message to multiple recipients.
    Body: { recipients: [{ phone, name? }], message: str, template_name?: str }
    """
    _ensure_tables()
    data = request.json or {}
    recipients = data.get("recipients", [])
    message = data.get("message", "").strip()
    template_name = data.get("template_name")

    if not recipients or not message:
        return jsonify({"error": "recipients and message are required"}), 400

    user = getattr(g, "current_user", None)
    sent = 0
    failed = 0

    for r in recipients:
        phone = r.get("phone", "").strip()
        name = r.get("name", "")
        if not phone:
            continue

        # Personalize message
        personalized = message.replace("{{name}}", name).replace("{{phone}}", phone)
        result = send_whatsapp(phone, personalized)

        execute_kelava_query(
            """
            INSERT INTO wa_message_log (direction, phone, sender_name, message, status, template_name, sent_by)
            VALUES ('outgoing', %s, %s, %s, %s, %s, %s)
            """,
            (phone, name, personalized, "sent" if result.get("success") else "failed",
             template_name, user.id if user else None),
        )

        if result.get("success"):
            sent += 1
        else:
            failed += 1

    log_action("wa_bot", "send_bulk", "message", None, f"Bulk WA: {sent} sent, {failed} failed")

    return jsonify({"sent": sent, "failed": failed, "total": len(recipients)})


# ── Send Schedule Reminder ───────────────────────────────────


@wa_bot_bp.route("/send-schedule-reminder", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def send_schedule_reminder():
    """
    Send tomorrow's schedule to all technicians via WA.
    Body: { date?: "YYYY-MM-DD" (defaults to tomorrow) }
    """
    _ensure_tables()
    data = request.json or {}
    from datetime import timedelta
    target_date = data.get("date")
    if not target_date:
        target_date = (datetime.now().date() + timedelta(days=1)).isoformat()

    # Get schedule by technician
    schedules = execute_kelava_query(
        """
        SELECT
            rp.id_user, u.fullname AS tech_name, u.phone AS tech_phone,
            COUNT(*) AS visit_count,
            STRING_AGG(c.name, ', ' ORDER BY c.name) AS customer_list
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.visit_date::date = %s
        GROUP BY rp.id_user, u.fullname, u.phone
        ORDER BY u.fullname
        """,
        (target_date,),
    )

    sent = 0
    failed = 0
    no_phone = 0

    for s in schedules:
        phone = s.get("tech_phone")
        if not phone:
            no_phone += 1
            continue

        msg = (
            f"*Jadwal Kunjungan {target_date}*\n\n"
            f"Halo {s['tech_name']},\n"
            f"Besok kamu ada *{s['visit_count']} kunjungan*:\n\n"
            f"{s['customer_list']}\n\n"
            f"Pastikan cek-in tepat waktu. Semangat!"
        )

        result = send_whatsapp(phone, msg)
        execute_kelava_query(
            """
            INSERT INTO wa_message_log (direction, phone, sender_name, message, status, template_name, sent_by)
            VALUES ('outgoing', %s, %s, %s, %s, 'schedule_reminder', %s)
            """,
            (phone, s['tech_name'], msg, "sent" if result.get("success") else "failed",
             getattr(getattr(g, "current_user", None), "id", None)),
        )

        if result.get("success"):
            sent += 1
        else:
            failed += 1

    log_action("wa_bot", "send_bulk", "schedule_reminder", None,
               f"Schedule reminder for {target_date}: {sent} sent, {failed} failed, {no_phone} no phone")

    return jsonify({
        "date": target_date,
        "technicians": len(schedules),
        "sent": sent,
        "failed": failed,
        "no_phone": no_phone,
    })


# ── Message Log ──────────────────────────────────────────────


@wa_bot_bp.route("/log", methods=["GET"])
@require_auth
def message_log():
    """Query WA message log."""
    _ensure_tables()
    direction = request.args.get("direction")
    days = int(request.args.get("days", 7))
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)
    offset = (page - 1) * per_page

    where = "created_at >= NOW() - INTERVAL '%s days'"
    params = [days]
    if direction:
        where += " AND direction = %s"
        params.append(direction)

    params.extend([per_page, offset])

    rows = execute_kelava_query(
        f"""
        SELECT * FROM wa_message_log
        WHERE {where}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    stats = execute_kelava_query_single(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE direction = 'outgoing') AS sent,
            COUNT(*) FILTER (WHERE direction = 'incoming') AS received,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed
        FROM wa_message_log
        WHERE created_at >= NOW() - INTERVAL '%s days'
        """,
        (days,),
    )

    return jsonify({
        "messages": [_fmt(r) for r in rows],
        "stats": _fmt(stats) if stats else {},
        "page": page,
        "days": days,
    })


# ── Templates ────────────────────────────────────────────────


@wa_bot_bp.route("/templates", methods=["GET"])
@require_auth
def list_templates():
    """List available message templates."""
    return jsonify({
        "templates": [
            {"name": "schedule_reminder", "description": "Pengingat jadwal besok", "variables": ["tech_name", "visit_count", "customer_list"]},
            {"name": "complaint_update", "description": "Update status komplain", "variables": ["customer_name", "ticket_id", "status"]},
            {"name": "contract_expiry", "description": "Pengingat kontrak akan habis", "variables": ["customer_name", "contract_no", "end_date"]},
            {"name": "visit_completed", "description": "Konfirmasi kunjungan selesai", "variables": ["customer_name", "tech_name", "date"]},
            {"name": "custom", "description": "Pesan kustom", "variables": ["name"]},
        ]
    })


# ── Command Processor ───────────────────────────────────────


def _process_command(sender: str, message: str) -> str | None:
    """
    Process incoming WA command from technician.
    Commands: JADWAL, STATUS, BANTUAN
    """
    msg = message.upper().strip()

    if msg in ("JADWAL", "SCHEDULE", "HARI INI"):
        return _cmd_schedule(sender)
    elif msg in ("STATUS", "PERFORMA", "KINERJA"):
        return _cmd_status(sender)
    elif msg in ("BANTUAN", "HELP", "MENU"):
        return _cmd_help()
    elif msg.startswith("CUTI"):
        return "Untuk pengajuan cuti, hubungi koordinator atau admin melalui aplikasi."

    return None  # Don't reply to unrecognized messages


def _cmd_schedule(phone: str) -> str:
    """Get today's schedule for the technician."""
    # Look up tech by phone
    tech = execute_kelava_query_single(
        "SELECT id, fullname FROM p_user WHERE phone = %s OR phone = %s",
        (phone, "0" + phone[2:] if phone.startswith("62") else phone),
    )
    if not tech:
        return "Maaf, nomor Anda tidak terdaftar di sistem."

    today = datetime.now().strftime("%Y-%m-%d")
    plans = execute_kelava_query(
        """
        SELECT c.name, c.address, rp.status, rp.type
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        WHERE rp.id_user = %s AND rp.visit_date::date = %s
        ORDER BY c.name
        """,
        (tech["id"], today),
    )

    if not plans:
        return f"Halo {tech['fullname']}, tidak ada jadwal kunjungan hari ini."

    lines = [f"*Jadwal Kunjungan Hari Ini*\n{tech['fullname']} - {today}\n"]
    for i, p in enumerate(plans, 1):
        status_icon = "✅" if p["status"] == "Selesai" else "⏳"
        lines.append(f"{i}. {status_icon} {p['name']}")
        if p.get("address"):
            lines.append(f"   📍 {p['address'][:60]}")

    visited = sum(1 for p in plans if p["status"] == "Selesai")
    lines.append(f"\nSelesai: {visited}/{len(plans)}")

    return "\n".join(lines)


def _cmd_status(phone: str) -> str:
    """Get performance status for the technician."""
    tech = execute_kelava_query_single(
        "SELECT id, fullname FROM p_user WHERE phone = %s OR phone = %s",
        (phone, "0" + phone[2:] if phone.startswith("62") else phone),
    )
    if not tech:
        return "Maaf, nomor Anda tidak terdaftar di sistem."

    stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'Selesai') AS completed,
            ROUND(COUNT(*) FILTER (WHERE status = 'Selesai')::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS rate
        FROM t_road_plan
        WHERE id_user = %s AND visit_date >= CURRENT_DATE - INTERVAL '7 days'
        """,
        (tech["id"],),
    )

    total = stats["total"] if stats else 0
    completed = stats["completed"] if stats else 0
    rate = stats["rate"] if stats else 0

    return (
        f"*Status Kinerja - {tech['fullname']}*\n"
        f"📊 7 hari terakhir:\n\n"
        f"Total Jadwal: {total}\n"
        f"Selesai: {completed}\n"
        f"Rate: {rate}%\n\n"
        f"Terus semangat! 💪"
    )


def _cmd_help() -> str:
    """Return help menu."""
    return (
        "*SanoCare Bot* 🤖\n\n"
        "Ketik salah satu perintah:\n\n"
        "*JADWAL* - Lihat jadwal hari ini\n"
        "*STATUS* - Lihat kinerja 7 hari\n"
        "*BANTUAN* - Menu ini\n\n"
        "Butuh bantuan lain? Hubungi koordinator."
    )


# ── Table Setup ──────────────────────────────────────────────


def _ensure_tables():
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    execute_kelava_query("""
        CREATE TABLE IF NOT EXISTS wa_message_log (
            id BIGSERIAL PRIMARY KEY,
            direction TEXT NOT NULL,
            phone TEXT NOT NULL,
            sender_name TEXT,
            message TEXT,
            status TEXT DEFAULT 'pending',
            template_name TEXT,
            sent_by BIGINT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    execute_kelava_query("CREATE INDEX IF NOT EXISTS idx_wa_log_created ON wa_message_log(created_at DESC)")
    execute_kelava_query("CREATE INDEX IF NOT EXISTS idx_wa_log_phone ON wa_message_log(phone)")
    _TABLE_ENSURED = True
