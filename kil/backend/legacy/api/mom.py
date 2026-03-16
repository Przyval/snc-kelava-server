"""
MOM (Minutes of Meeting) API
==============================
Meeting recording, AI transcription (Gemini), summarization, and WhatsApp distribution.

Endpoints:
    POST   /meetings                    - Create meeting
    GET    /meetings                    - List meetings
    GET    /meetings/<id>               - Meeting detail
    POST   /meetings/<id>/audio         - Upload audio
    POST   /meetings/<id>/transcribe    - AI transcription (Gemini)
    PATCH  /meetings/<id>/transcript    - Edit transcript
    POST   /meetings/<id>/summarize     - AI summarization (Gemini)
    PATCH  /meetings/<id>/actions/<aid> - Update action item
    POST   /meetings/<id>/send          - Send MOM via WhatsApp
    GET    /meetings/<id>/distributions - Send history
    DELETE /meetings/<id>               - Delete meeting
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

log = logging.getLogger(__name__)

mom_bp = Blueprint("mom", __name__)

UPLOAD_DIR = Path(os.environ.get("MOM_UPLOAD_DIR", "/root/kil-server/uploads/meetings"))
ALLOWED_AUDIO_EXT = {"wav", "webm", "mp3", "ogg", "m4a", "mp4"}
MAX_AUDIO_SIZE = 100 * 1024 * 1024  # 100MB

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


def _fmt(row):
    """Format DB row for JSON serialization."""
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


def _auth_user_id():
    user = getattr(g, "user", None)
    return user.id if user else None


# ── CRUD ───────────────────────────────────────────────────────


@mom_bp.route("/meetings", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def create_meeting():
    """Create a new meeting record."""
    data = request.json or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400

    meeting_date = data.get("meeting_date", datetime.now().strftime("%Y-%m-%d"))
    location = data.get("location", "")
    participants = data.get("participants", [])

    row = execute_kelava_query_single(
        """
        INSERT INTO meetings (title, meeting_date, location, participants, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id, title, status, created_at
        """,
        (title, meeting_date, location, participants, _auth_user_id()),
    )

    return jsonify({"meeting": _fmt(row)}), 201


@mom_bp.route("/meetings", methods=["GET"])
@require_auth
def list_meetings():
    """List meetings with pagination and search."""
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 50)
    search = request.args.get("search", "").strip()
    offset = (page - 1) * per_page

    where = "WHERE 1=1"
    params = []
    if search:
        where += " AND (m.title ILIKE %s OR m.location ILIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    rows = execute_kelava_query(
        f"""
        SELECT m.id, m.title, m.meeting_date, m.location,
               m.status, m.audio_duration_sec, m.created_at,
               eu.full_name as created_by_name,
               (SELECT COUNT(*) FROM meeting_action_items WHERE meeting_id = m.id) as action_count,
               (SELECT COUNT(*) FROM meeting_distributions WHERE meeting_id = m.id AND status = 'sent') as sent_count
        FROM meetings m
        LEFT JOIN enterprise_users eu ON eu.id = m.created_by
        {where}
        ORDER BY m.meeting_date DESC, m.created_at DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params) + (per_page, offset) if params else (per_page, offset),
    )

    total = execute_kelava_query_single(
        f"SELECT COUNT(*) as cnt FROM meetings m {where}",
        tuple(params) if params else None,
    )

    return jsonify({
        "meetings": [_fmt(r) for r in rows],
        "pagination": {"total": total["cnt"] if total else 0, "page": page, "per_page": per_page},
    })


@mom_bp.route("/meetings/<int:meeting_id>", methods=["GET"])
@require_auth
def meeting_detail(meeting_id: int):
    """Get meeting detail with transcript, summary, and action items."""
    meeting = execute_kelava_query_single(
        """
        SELECT m.*, eu.full_name as created_by_name
        FROM meetings m
        LEFT JOIN enterprise_users eu ON eu.id = m.created_by
        WHERE m.id = %s
        """,
        (meeting_id,),
    )
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404

    actions = execute_kelava_query(
        "SELECT * FROM meeting_action_items WHERE meeting_id = %s ORDER BY id",
        (meeting_id,),
    )

    distributions = execute_kelava_query(
        "SELECT * FROM meeting_distributions WHERE meeting_id = %s ORDER BY id DESC",
        (meeting_id,),
    )

    result = _fmt(meeting)
    result["action_items"] = [_fmt(a) for a in actions]
    result["distributions"] = [_fmt(d) for d in distributions]

    return jsonify({"meeting": result})


@mom_bp.route("/meetings/<int:meeting_id>", methods=["DELETE"])
@require_auth
@require_role("admin")
def delete_meeting(meeting_id: int):
    """Delete a meeting (admin only)."""
    meeting = execute_kelava_query_single("SELECT id FROM meetings WHERE id = %s", (meeting_id,))
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404

    execute_kelava_query_single("DELETE FROM meetings WHERE id = %s", (meeting_id,))

    # Clean up audio file
    audio_dir = UPLOAD_DIR / str(meeting_id)
    if audio_dir.exists():
        import shutil
        shutil.rmtree(audio_dir, ignore_errors=True)

    return jsonify({"message": "Meeting deleted"})


# ── Audio Upload ───────────────────────────────────────────────


@mom_bp.route("/meetings/<int:meeting_id>/audio", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def upload_audio(meeting_id: int):
    """Upload audio recording for a meeting."""
    meeting = execute_kelava_query_single("SELECT id, status FROM meetings WHERE id = %s", (meeting_id,))
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404

    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    file = request.files["audio"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_AUDIO_EXT:
        return jsonify({"error": f"File type '{ext}' not allowed. Use: {', '.join(ALLOWED_AUDIO_EXT)}"}), 400

    file_data = file.read()
    if len(file_data) > MAX_AUDIO_SIZE:
        return jsonify({"error": "File too large (max 100MB)"}), 400

    # Save file
    audio_dir = UPLOAD_DIR / str(meeting_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    filename = f"audio.{ext}"
    filepath = audio_dir / filename
    with open(filepath, "wb") as f:
        f.write(file_data)

    size_mb = round(len(file_data) / (1024 * 1024), 2)

    execute_kelava_query_single(
        "UPDATE meetings SET audio_filename = %s, status = 'uploaded', updated_at = NOW() WHERE id = %s",
        (str(filepath), meeting_id),
    )

    return jsonify({
        "message": "Audio uploaded",
        "filename": filename,
        "size_mb": size_mb,
        "meeting_id": meeting_id,
    })


# ── AI Transcription (Gemini) ─────────────────────────────────


@mom_bp.route("/meetings/<int:meeting_id>/transcribe", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def transcribe_meeting(meeting_id: int):
    """Transcribe meeting audio using Google Gemini."""
    meeting = execute_kelava_query_single(
        "SELECT id, audio_filename, status FROM meetings WHERE id = %s",
        (meeting_id,),
    )
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    if not meeting["audio_filename"]:
        return jsonify({"error": "No audio uploaded yet"}), 400

    audio_path = Path(meeting["audio_filename"])
    if not audio_path.exists():
        return jsonify({"error": "Audio file not found on disk"}), 404

    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not configured"}), 500

    # Update status
    execute_kelava_query_single(
        "UPDATE meetings SET status = 'transcribing', updated_at = NOW() WHERE id = %s",
        (meeting_id,),
    )

    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)

        # Upload audio to Gemini
        audio_file = genai.upload_file(str(audio_path))

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            [
                audio_file,
                """Transkripsikan audio meeting ini secara lengkap dan akurat.
Gunakan bahasa yang sama dengan yang diucapkan dalam audio (campuran Indonesia/Jawa/English).
Format output:
- Gunakan paragraf terpisah untuk setiap pembicara berbeda
- Tandai pergantian pembicara dengan baris baru
- Sertakan timestamp perkiraan di awal setiap paragraf jika memungkinkan [MM:SS]
- Jangan ringkas, tulis verbatim/kata per kata sebisa mungkin""",
            ],
        )

        transcript = response.text

        # Calculate approximate duration from file size (rough estimate)
        file_size = audio_path.stat().st_size
        # ~16KB/s for compressed audio (rough)
        est_duration = int(file_size / 16000)

        execute_kelava_query_single(
            """UPDATE meetings SET transcript = %s, status = 'transcribed',
               audio_duration_sec = %s, updated_at = NOW() WHERE id = %s""",
            (transcript, est_duration, meeting_id),
        )

        return jsonify({
            "message": "Transcription complete",
            "transcript_length": len(transcript),
            "estimated_duration_sec": est_duration,
        })

    except Exception as e:
        log.error(f"Transcription error: {e}")
        execute_kelava_query_single(
            "UPDATE meetings SET status = 'uploaded', updated_at = NOW() WHERE id = %s",
            (meeting_id,),
        )
        return jsonify({"error": f"Transcription failed: {str(e)}"}), 500


# ── Edit Transcript ────────────────────────────────────────────


@mom_bp.route("/meetings/<int:meeting_id>/transcript", methods=["PATCH"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def edit_transcript(meeting_id: int):
    """Edit/correct the transcript manually."""
    data = request.json or {}
    transcript = data.get("transcript", "")
    if not transcript:
        return jsonify({"error": "Transcript text required"}), 400

    execute_kelava_query_single(
        "UPDATE meetings SET transcript = %s, updated_at = NOW() WHERE id = %s",
        (transcript, meeting_id),
    )

    return jsonify({"message": "Transcript updated"})


# ── AI Summarization (Gemini) ─────────────────────────────────


@mom_bp.route("/meetings/<int:meeting_id>/summarize", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def summarize_meeting(meeting_id: int):
    """Generate structured MOM summary using Gemini."""
    meeting = execute_kelava_query_single(
        "SELECT id, title, meeting_date, location, participants, transcript, status FROM meetings WHERE id = %s",
        (meeting_id,),
    )
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    if not meeting["transcript"]:
        return jsonify({"error": "No transcript available. Transcribe first."}), 400

    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not configured"}), 500

    execute_kelava_query_single(
        "UPDATE meetings SET status = 'summarizing', updated_at = NOW() WHERE id = %s",
        (meeting_id,),
    )

    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.0-flash")

        participants_str = ", ".join(meeting["participants"]) if meeting["participants"] else "Tidak disebutkan"

        prompt = f"""Kamu adalah asisten notulensi professional. Buatkan Minutes of Meeting (MOM) yang terstruktur dan menarik dari transkrip berikut.

INFORMASI MEETING:
- Judul: {meeting['title']}
- Tanggal: {meeting['meeting_date']}
- Lokasi: {meeting['location'] or 'Tidak disebutkan'}
- Peserta: {participants_str}

TRANSKRIP:
{meeting['transcript'][:30000]}

INSTRUKSI:
Hasilkan output dalam format JSON yang valid dengan struktur berikut:
{{
    "executive_summary": "Ringkasan singkat 2-3 kalimat tentang meeting ini",
    "key_discussions": [
        {{
            "topic": "Topik pembahasan",
            "summary": "Ringkasan pembahasan",
            "speaker": "Pembicara utama (jika teridentifikasi)"
        }}
    ],
    "decisions": [
        "Keputusan 1",
        "Keputusan 2"
    ],
    "action_items": [
        {{
            "description": "Deskripsi tugas",
            "assignee": "Nama PIC",
            "due_date": "Estimasi deadline (jika disebutkan, format YYYY-MM-DD)"
        }}
    ],
    "next_steps": [
        "Langkah selanjutnya 1"
    ],
    "notable_quotes": [
        {{
            "quote": "Kutipan penting",
            "speaker": "Pembicara"
        }}
    ]
}}

PENTING:
- Hanya output JSON, tanpa markdown code block
- Gunakan bahasa Indonesia
- Fokus pada poin substansial, bukan basa-basi
- Identifikasi action items secara cermat"""

        response = model.generate_content(prompt)
        raw_text = response.text.strip()

        # Clean markdown code blocks if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].strip()
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()

        summary = json.loads(raw_text)

        # Store summary
        execute_kelava_query_single(
            "UPDATE meetings SET summary_json = %s, status = 'ready', updated_at = NOW() WHERE id = %s",
            (json.dumps(summary), meeting_id),
        )

        # Create action items from summary
        for item in summary.get("action_items", []):
            due = item.get("due_date")
            if due and due.lower() in ("null", "none", "-", ""):
                due = None
            execute_kelava_query_single(
                """
                INSERT INTO meeting_action_items (meeting_id, description, assignee, due_date)
                VALUES (%s, %s, %s, %s)
                """,
                (meeting_id, item["description"], item.get("assignee", ""), due),
            )

        return jsonify({
            "message": "Summary generated",
            "summary": summary,
            "action_items_created": len(summary.get("action_items", [])),
        })

    except json.JSONDecodeError as e:
        log.error(f"JSON parse error in summary: {e}")
        # Store raw text as fallback
        execute_kelava_query_single(
            "UPDATE meetings SET summary_json = %s, status = 'ready', updated_at = NOW() WHERE id = %s",
            (json.dumps({"raw_summary": raw_text, "parse_error": str(e)}), meeting_id),
        )
        return jsonify({"message": "Summary generated (raw format)", "warning": "JSON parse failed, stored as raw text"})

    except Exception as e:
        log.error(f"Summarization error: {e}")
        execute_kelava_query_single(
            "UPDATE meetings SET status = 'transcribed', updated_at = NOW() WHERE id = %s",
            (meeting_id,),
        )
        return jsonify({"error": f"Summarization failed: {str(e)}"}), 500


# ── Action Items ───────────────────────────────────────────────


@mom_bp.route("/meetings/<int:meeting_id>/actions/<int:action_id>", methods=["PATCH"])
@require_auth
def update_action_item(meeting_id: int, action_id: int):
    """Update action item status or details."""
    data = request.json or {}
    updates = []
    params = []

    if "status" in data:
        if data["status"] not in ("open", "in_progress", "done"):
            return jsonify({"error": "Invalid status"}), 400
        updates.append("status = %s")
        params.append(data["status"])
    if "assignee" in data:
        updates.append("assignee = %s")
        params.append(data["assignee"])
    if "due_date" in data:
        updates.append("due_date = %s")
        params.append(data["due_date"] or None)

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    params.extend([action_id, meeting_id])
    execute_kelava_query_single(
        f"UPDATE meeting_action_items SET {', '.join(updates)} WHERE id = %s AND meeting_id = %s",
        tuple(params),
    )

    return jsonify({"message": "Action item updated"})


# ── WhatsApp Distribution ─────────────────────────────────────


@mom_bp.route("/meetings/<int:meeting_id>/send", methods=["POST"])
@require_auth
@require_role("admin", "koordinator", "supervisor")
def send_mom(meeting_id: int):
    """Send MOM summary via WhatsApp."""
    from kil.backend.legacy.api.wa_gateway import send_whatsapp

    meeting = execute_kelava_query_single(
        "SELECT id, title, meeting_date, location, participants, summary_json FROM meetings WHERE id = %s",
        (meeting_id,),
    )
    if not meeting:
        return jsonify({"error": "Meeting not found"}), 404
    if not meeting["summary_json"]:
        return jsonify({"error": "No summary available. Summarize first."}), 400

    data = request.json or {}
    recipients = data.get("recipients", [])
    if not recipients:
        return jsonify({"error": "Recipients required: [{name, phone}]"}), 400

    # Format MOM for WhatsApp
    summary = meeting["summary_json"] if isinstance(meeting["summary_json"], dict) else json.loads(meeting["summary_json"])
    msg = _format_mom_whatsapp(meeting, summary)

    results = []
    for r in recipients:
        phone = r.get("phone", "")
        name = r.get("name", phone)
        if not phone:
            continue

        wa_result = send_whatsapp(phone, msg)

        # Log distribution
        execute_kelava_query_single(
            """
            INSERT INTO meeting_distributions (meeting_id, channel, recipient, sent_at, status, error_message)
            VALUES (%s, 'whatsapp', %s, %s, %s, %s)
            """,
            (
                meeting_id,
                f"{name} ({phone})",
                datetime.now() if wa_result["success"] else None,
                "sent" if wa_result["success"] else "failed",
                None if wa_result["success"] else wa_result["detail"][:500],
            ),
        )

        results.append({"name": name, "phone": phone, "success": wa_result["success"], "detail": wa_result["detail"]})

    # Update meeting status
    if any(r["success"] for r in results):
        execute_kelava_query_single(
            "UPDATE meetings SET status = 'sent', updated_at = NOW() WHERE id = %s",
            (meeting_id,),
        )

    return jsonify({
        "message": f"Sent to {sum(1 for r in results if r['success'])}/{len(results)} recipients",
        "results": results,
    })


@mom_bp.route("/meetings/<int:meeting_id>/distributions", methods=["GET"])
@require_auth
def distribution_history(meeting_id: int):
    """Get send history for a meeting."""
    rows = execute_kelava_query(
        "SELECT * FROM meeting_distributions WHERE meeting_id = %s ORDER BY id DESC",
        (meeting_id,),
    )
    return jsonify({"distributions": [_fmt(r) for r in rows]})


def _format_mom_whatsapp(meeting: dict, summary: dict) -> str:
    """Format MOM summary as WhatsApp-friendly text."""
    lines = [
        f"*NOTULEN RAPAT*",
        f"━━━━━━━━━━━━━━",
        f"*{meeting['title']}*",
        f"Tanggal: {meeting['meeting_date']}",
    ]
    if meeting.get("location"):
        lines.append(f"Lokasi: {meeting['location']}")
    if meeting.get("participants"):
        lines.append(f"Peserta: {', '.join(meeting['participants'])}")
    lines.append("")

    # Executive summary
    if summary.get("executive_summary"):
        lines.append(f"*Ringkasan:*")
        lines.append(summary["executive_summary"])
        lines.append("")

    # Key discussions
    if summary.get("key_discussions"):
        lines.append("*Pembahasan Utama:*")
        for i, d in enumerate(summary["key_discussions"], 1):
            lines.append(f"{i}. *{d['topic']}*")
            lines.append(f"   {d['summary']}")
        lines.append("")

    # Decisions
    if summary.get("decisions"):
        lines.append("*Keputusan:*")
        for d in summary["decisions"]:
            lines.append(f"  - {d}")
        lines.append("")

    # Action items
    if summary.get("action_items"):
        lines.append("*Action Items:*")
        for a in summary["action_items"]:
            assignee = f" [{a.get('assignee', '?')}]" if a.get("assignee") else ""
            due = f" (deadline: {a['due_date']})" if a.get("due_date") else ""
            lines.append(f"  [ ] {a['description']}{assignee}{due}")
        lines.append("")

    # Next steps
    if summary.get("next_steps"):
        lines.append("*Next Steps:*")
        for n in summary["next_steps"]:
            lines.append(f"  -> {n}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━")
    lines.append("_Dibuat otomatis oleh SanoCare Enterprise_")

    return "\n".join(lines)
