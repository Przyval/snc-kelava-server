"""
Absence Cascade — handle teknisi mobile cuti dengan fallback waterfall.

PRD:
  Level 1: Support tech compatible (specialty match) cover same day
  Level 2: Self-reschedule (mobile tetap pegang, geser hari ±7)
  Level 3: Manual decision needed

Constraint:
  - Teknisi MOBILE TIDAK BISA cover klien mobile lain (forbidden)
  - Hanya teknisi SUPPORT yang boleh cover
  - Support dengan specialty='rayap' HANYA boleh cover visit type TTD/TC
  - Support general (specialty=NULL) cover semua KECUALI TTD/TC

API:
  POST /absence/<absence_id>/cascade?dry_run=true|false  → preview / apply
  POST /absence/<absence_id>/cascade/revert              → undo
  GET  /absence/<absence_id>/cascade                     → fetch log
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request

from kil.backend.core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

cascade_bp = Blueprint("absence_cascade", __name__,
                       url_prefix="/api/v1/enterprise/absence")

# Configurable
WINDOW_DAYS = 7
DAY_CAP = 5
RAYAP_TYPES = {"TTD", "TC"}


def _require_koord():
    user = getattr(g, "current_user", None) or getattr(request, "_jwt_user", {})
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
    uid = user.get("id") if isinstance(user, dict) else getattr(user, "id", 0)
    if role not in ("admin", "koordinator"):
        return None, (jsonify({"error": "Forbidden"}), 403)
    return uid, None


# ─────────────────────────────────────────────────────────────────────────────
# Cascade computation
# ─────────────────────────────────────────────────────────────────────────────

def _load_support_pool(cur):
    """Return list of active support technicians with specialty."""
    cur.execute("""
        SELECT id, name, COALESCE(specialty, 'general') AS specialty
        FROM snc_technicians
        WHERE employee_type = 'support' AND is_active = true
        ORDER BY id
    """)
    return cur.fetchall()


def _tech_load_on_date(cur, tech_id, d):
    """Count events for tech on given date."""
    cur.execute("""
        SELECT COUNT(*) AS n FROM snc_schedule_events
        WHERE technician_id = %s AND start_date = %s
          AND schedule_status IN ('draft','scheduled','approved','published')
    """, (tech_id, d))
    return cur.fetchone()["n"]


def _is_tech_absent(cur, tech_id, d):
    cur.execute("""
        SELECT 1 FROM snc_technician_day_status
        WHERE technician_id = %s AND date = %s
          AND status IN ('off','sick','training')
    """, (tech_id, d))
    return cur.fetchone() is not None


def _has_event_for(cur, tech_id, client_id, d):
    cur.execute("""
        SELECT 1 FROM snc_schedule_events
        WHERE technician_id = %s AND client_id = %s AND start_date = %s
    """, (tech_id, client_id, d))
    return cur.fetchone() is not None


def _is_client_suppressed(cur, client_id, d):
    cur.execute("""
        SELECT 1 FROM snc_client_suppression_dates
        WHERE client_id = %s AND start_date <= %s AND end_date >= %s
    """, (client_id, d, d))
    return cur.fetchone() is not None


def _is_holiday(cur, d):
    cur.execute("SELECT 1 FROM snc_suppression_dates WHERE suppression_date = %s", (d,))
    return cur.fetchone() is not None


def _is_compatible(support_tech, visit_type):
    """
    Specialty match logic:
      - support.specialty == 'rayap' → HANYA TTD/TC
      - support.specialty == 'general' (or NULL) → semua KECUALI TTD/TC
    """
    is_rayap_visit = (visit_type or "") in RAYAP_TYPES
    if support_tech["specialty"] == "rayap":
        return is_rayap_visit
    return not is_rayap_visit


def _cascade_decision(cur, event, absence_tech_id, support_pool, ephemeral_loads):
    """
    Decide cascade for ONE event. Returns dict with:
      decision, level, rationale, new_tech_id, new_date
    `ephemeral_loads` tracks support load delta within this cascade run.
    """
    visit_type = event["visit_type"] or ""
    event_date = event["start_date"]

    # ── LEVEL 1: Compatible support tech ──
    candidates = [s for s in support_pool if _is_compatible(s, visit_type)]
    available = []
    for s in candidates:
        if _is_tech_absent(cur, s["id"], event_date):
            continue
        load = _tech_load_on_date(cur, s["id"], event_date) + ephemeral_loads.get((s["id"], event_date), 0)
        if load >= DAY_CAP:
            continue
        if _has_event_for(cur, s["id"], event["client_id"], event_date):
            continue
        available.append((s, load))

    if available:
        # Pick lowest load
        chosen, load = min(available, key=lambda x: x[1])
        spec_label = chosen["specialty"] or "general"
        return {
            "decision": "backup_assigned",
            "level": 1,
            "rationale": f"{chosen['name']} ({spec_label}, load {load}/{DAY_CAP})",
            "new_tech_id": chosen["id"],
            "new_tech_name": chosen["name"],
            "new_date": event_date,
        }

    # ── LEVEL 2: Self-reschedule (Akbar tetap pegang) ──
    for offset in range(1, WINDOW_DAYS + 1):
        cand = event_date + timedelta(days=offset)
        if cand.weekday() == 6:  # skip Minggu
            continue
        if _is_tech_absent(cur, absence_tech_id, cand):
            continue
        if _tech_load_on_date(cur, absence_tech_id, cand) >= DAY_CAP:
            continue
        if _has_event_for(cur, absence_tech_id, event["client_id"], cand):
            continue
        if _is_client_suppressed(cur, event["client_id"], cand):
            continue
        if _is_holiday(cur, cand):
            continue
        return {
            "decision": "rescheduled",
            "level": 2,
            "rationale": f"Self-reschedule +{offset} hari (no support compatible available {event_date})",
            "new_tech_id": absence_tech_id,
            "new_tech_name": event.get("tech_name"),
            "new_date": cand,
        }

    # ── LEVEL 3: Manual ──
    return {
        "decision": "manual_needed",
        "level": 3,
        "rationale": f"Tidak ada support compatible (visit_type={visit_type}) + tidak ada slot Akbar dalam {WINDOW_DAYS} hari",
        "new_tech_id": None,
        "new_tech_name": None,
        "new_date": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Core entry: cascade(absence_id, dry_run, user_id)
# ─────────────────────────────────────────────────────────────────────────────

def cascade(absence_id: int, dry_run: bool, user_id: int):
    """Run cascade for an absence. Returns dict with results."""
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Load absence
            cur.execute("""
                SELECT ts.id, ts.technician_id, ts.date, ts.status, ts.backup_tech_id,
                       t.name AS tech_name, t.employee_type
                FROM snc_technician_day_status ts
                JOIN snc_technicians t ON t.id = ts.technician_id
                WHERE ts.id = %s
            """, (absence_id,))
            absence = cur.fetchone()
            if not absence:
                return {"error": "Absence not found"}, 404
            if absence["status"] not in ("off", "sick", "training"):
                return {"error": f"Cascade only for off/sick/training (got {absence['status']})"}, 400
            if absence["employee_type"] != "mobile":
                return {"error": "Cascade hanya untuk teknisi mobile"}, 400

            # Load affected visits
            cur.execute("""
                SELECT se.id, se.technician_id, se.client_id, se.visit_type,
                       se.start_date, se.start_datetime, se.end_datetime,
                       t.name AS tech_name, c.name AS client_name
                FROM snc_schedule_events se
                JOIN snc_technicians t ON t.id = se.technician_id
                JOIN snc_clients c ON c.id = se.client_id
                WHERE se.technician_id = %s AND se.start_date = %s
                  AND se.schedule_status IN ('draft','scheduled','approved')
            """, (absence["technician_id"], absence["date"]))
            visits = cur.fetchall()
            if not visits:
                return {
                    "absence_id": absence_id,
                    "tech_name": absence["tech_name"],
                    "date": absence["date"].isoformat(),
                    "affected_visits": 0,
                    "results": [],
                    "summary": {},
                    "message": "Tidak ada visit terdampak (mungkin Akbar memang kosong hari itu)"
                }

            support_pool = _load_support_pool(cur)
            ephemeral_loads = defaultdict(int)

            # Decide per visit
            results = []
            for v in visits:
                d = _cascade_decision(cur, v, absence["technician_id"], support_pool, ephemeral_loads)
                results.append({
                    "event_id": v["id"],
                    "client_name": v["client_name"],
                    "visit_type": v["visit_type"],
                    "original_date": v["start_date"].isoformat(),
                    "original_time": v["start_datetime"].strftime("%H:%M") if v["start_datetime"] else None,
                    **d,
                    "new_date": d["new_date"].isoformat() if d["new_date"] else None,
                })
                # Update ephemeral loads for cascading decisions in same run
                if d["decision"] == "backup_assigned":
                    ephemeral_loads[(d["new_tech_id"], v["start_date"])] += 1
                elif d["decision"] == "rescheduled":
                    ephemeral_loads[(d["new_tech_id"], d["new_date"])] += 1

            summary = defaultdict(int)
            for r in results:
                summary[r["decision"]] += 1

            response = {
                "absence_id": absence_id,
                "tech_name": absence["tech_name"],
                "absence_date": absence["date"].isoformat(),
                "affected_visits": len(visits),
                "results": results,
                "summary": dict(summary),
                "dry_run": dry_run,
            }

            if dry_run:
                return response

            # ── APPLY ──
            applied = 0
            for r in results:
                if r["decision"] == "manual_needed":
                    # Log only
                    cur.execute("""
                        INSERT INTO snc_absence_cascade_log
                            (absence_id, original_event_id, cascade_level, decision,
                             rationale, original_tech_id, original_date,
                             original_visit_type, original_client_id,
                             auto_applied, decided_by)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (absence_id, r["event_id"], r["level"], r["decision"],
                          r["rationale"], absence["technician_id"], absence["date"],
                          r["visit_type"], None,  # client_id from original event
                          False, user_id))
                    continue

                # Snapshot original for revert
                cur.execute("""
                    UPDATE snc_schedule_events
                    SET original_start_date = COALESCE(original_start_date, start_date),
                        original_technician_id = COALESCE(original_technician_id, technician_id),
                        reschedule_level = %s,
                        technician_id = %s,
                        start_date = %s,
                        start_datetime = (%s::date + (start_datetime::time))::timestamptz,
                        end_datetime = CASE
                            WHEN end_datetime IS NOT NULL
                            THEN (%s::date + (end_datetime::time))::timestamptz
                            ELSE NULL
                        END,
                        reschedule_reason = %s,
                        updated_at = now()
                    WHERE id = %s
                """, (r["level"], r["new_tech_id"], r["new_date"],
                      r["new_date"], r["new_date"], r["rationale"], r["event_id"]))

                cur.execute("""
                    INSERT INTO snc_absence_cascade_log
                        (absence_id, original_event_id, new_event_id, cascade_level,
                         decision, rationale, original_tech_id, original_date,
                         original_visit_type, original_client_id,
                         new_tech_id, new_date, auto_applied, decided_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (absence_id, r["event_id"], r["event_id"], r["level"],
                      r["decision"], r["rationale"],
                      absence["technician_id"], absence["date"],
                      r["visit_type"], None,
                      r["new_tech_id"], r["new_date"], True, user_id))
                applied += 1

            conn.commit()
            response["applied"] = applied
            response["message"] = f"{applied}/{len(visits)} cascade applied"
            return response


def revert_cascade(absence_id: int, user_id: int):
    """Revert cascade — restore original tech + date on all events."""
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT DISTINCT original_event_id, original_tech_id, original_date
                FROM snc_absence_cascade_log
                WHERE absence_id = %s AND decision IN ('backup_assigned', 'rescheduled')
                  AND original_event_id IS NOT NULL
            """, (absence_id,))
            rows = cur.fetchall()
            reverted = 0
            for r in rows:
                cur.execute("""
                    UPDATE snc_schedule_events
                    SET technician_id = %s,
                        start_date = %s,
                        start_datetime = (%s::date + (start_datetime::time))::timestamptz,
                        end_datetime = CASE
                            WHEN end_datetime IS NOT NULL
                            THEN (%s::date + (end_datetime::time))::timestamptz
                            ELSE NULL
                        END,
                        reschedule_level = NULL,
                        original_start_date = NULL,
                        original_technician_id = NULL,
                        reschedule_reason = 'Reverted (absence deleted)',
                        updated_at = now()
                    WHERE id = %s
                """, (r["original_tech_id"], r["original_date"],
                      r["original_date"], r["original_date"], r["original_event_id"]))
                cur.execute("""
                    INSERT INTO snc_absence_cascade_log
                        (absence_id, original_event_id, cascade_level, decision,
                         rationale, decided_by, auto_applied)
                    VALUES (%s, %s, 0, 'reverted', 'Cascade reverted', %s, true)
                """, (absence_id, r["original_event_id"], user_id))
                reverted += 1
            conn.commit()
    return {"absence_id": absence_id, "reverted": reverted}


# ─────────────────────────────────────────────────────────────────────────────
# Flask endpoints
# ─────────────────────────────────────────────────────────────────────────────

@cascade_bp.route("/<int:absence_id>/cascade", methods=["POST"])
@require_auth
def post_cascade(absence_id):
    user_id, forbidden = _require_koord()
    if forbidden:
        return forbidden
    dry_run = request.args.get("dry_run", "true").lower() == "true"
    result = cascade(absence_id, dry_run=dry_run, user_id=user_id)
    if isinstance(result, tuple):  # error tuple
        return jsonify(result[0]), result[1]
    return jsonify(result)


@cascade_bp.route("/<int:absence_id>/cascade/revert", methods=["POST"])
@require_auth
def post_revert(absence_id):
    user_id, forbidden = _require_koord()
    if forbidden:
        return forbidden
    return jsonify(revert_cascade(absence_id, user_id))


@cascade_bp.route("/<int:absence_id>/cascade", methods=["GET"])
@require_auth
def get_cascade_log(absence_id):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT cl.*, ot.name AS original_tech_name, nt.name AS new_tech_name,
                       c.name AS client_name
                FROM snc_absence_cascade_log cl
                LEFT JOIN snc_technicians ot ON ot.id = cl.original_tech_id
                LEFT JOIN snc_technicians nt ON nt.id = cl.new_tech_id
                LEFT JOIN snc_schedule_events se ON se.id = cl.new_event_id
                LEFT JOIN snc_clients c ON c.id = se.client_id
                WHERE cl.absence_id = %s
                ORDER BY cl.decided_at DESC
            """, (absence_id,))
            log = cur.fetchall()
    for r in log:
        for d in ("original_date", "new_date"):
            if r.get(d):
                r[d] = r[d].isoformat()
        r["decided_at"] = r["decided_at"].isoformat()
    return jsonify({"absence_id": absence_id, "log": log})


# ─────────────────────────────────────────────────────────────────────────────
# Cross-cutting: list active cascades (for Audit Dashboard widget)
# ─────────────────────────────────────────────────────────────────────────────

@cascade_bp.route("/cascade/summary", methods=["GET"])
@require_auth
def cascade_summary():
    """Summary cascade events for a month. ?month=YYYY-MM"""
    month = request.args.get("month", "")
    try:
        y, m = map(int, month.split("-"))
        import calendar as cal_mod
        _, ndays = cal_mod.monthrange(y, m)
        mstart = date(y, m, 1)
        mend = date(y, m, ndays)
    except Exception:
        return jsonify({"error": "month wajib YYYY-MM"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT ts.id AS absence_id, ts.date, ts.status,
                       t.name AS tech_name,
                       COUNT(cl.id) FILTER (WHERE cl.decision='backup_assigned') AS lvl1,
                       COUNT(cl.id) FILTER (WHERE cl.decision='rescheduled') AS lvl2,
                       COUNT(cl.id) FILTER (WHERE cl.decision='manual_needed') AS lvl3,
                       COUNT(cl.id) FILTER (WHERE cl.decision='reverted') AS reverted
                FROM snc_technician_day_status ts
                JOIN snc_technicians t ON t.id = ts.technician_id
                LEFT JOIN snc_absence_cascade_log cl ON cl.absence_id = ts.id
                WHERE ts.date BETWEEN %s AND %s
                  AND ts.status IN ('off','sick','training')
                  AND t.employee_type = 'mobile'
                GROUP BY ts.id, t.name
                ORDER BY ts.date
            """, (mstart, mend))
            rows = cur.fetchall()
    for r in rows:
        r["date"] = r["date"].isoformat()
    return jsonify({"month": month, "absences": rows})
