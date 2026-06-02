"""
Audit API — PRD §8 (7 audit layers), §11 (publish gate), §15 (KPI).

GET  /audit/readiness/<month>          — overall readiness score + breakdown
GET  /audit/blockers/<month>           — list of hard blockers + warnings
GET  /audit/layer/calendar-count/<m>   — Layer 1: per-date count vs Excel
GET  /audit/layer/tech-assignment/<m>  — Layer 4: tech assignment status
GET  /audit/layer/duplicates/<m>       — Layer 7: dup + empty detection
POST /audit/publish-gate/<m>           — perform publish-gate check + log
"""

import json
from collections import defaultdict
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request

from kil.backend.core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

audit_bp = Blueprint("audit_v2", __name__, url_prefix="/api/v1/enterprise/audit")


def _require_koordinator_or_admin():
    user = getattr(g, "current_user", None) or getattr(request, "_jwt_user", {})
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
    uid = user.get("id") if isinstance(user, dict) else getattr(user, "user_id", 0)
    if role not in ("admin", "koordinator"):
        return None, (jsonify({"error": "Forbidden"}), 403)
    return uid, None


# ─────────────────────────────────────────────────────────────────────────────
# Helper: detect all issues for target_month — single query
# ─────────────────────────────────────────────────────────────────────────────

def _collect_audit_issues(cur, target_month: str) -> dict:
    """
    Returns dict with all detected issues, used by readiness + blockers + publish-gate.
    """
    year, mnum = map(int, target_month.split('-'))
    import calendar as cal_mod
    _, ndays = cal_mod.monthrange(year, mnum)
    mstart, mend = date(year, mnum, 1), date(year, mnum, ndays)

    # Latest draft batch
    cur.execute(
        "SELECT id FROM snc_draft_batches WHERE target_month=%s ORDER BY id DESC LIMIT 1",
        (target_month,))
    row = cur.fetchone()
    batch_id = row['id'] if row else None

    issues = {
        'has_batch': batch_id is not None,
        'batch_id': batch_id,
        'visit_no_date': 0,
        'visit_no_customer': 0,
        'visit_no_tech': 0,
        'tech_unavailable_but_assigned': 0,
        'duplicate_visits': 0,
        'unmatched_customers': 0,
        'inactive_customers_scheduled': 0,
        'holiday_conflicts': 0,
        'overlap_conflicts': 0,
        'unresolved_compare': 0,
        # warnings
        'tech_overloaded': 0,
        'manual_visits_no_contract': 0,
        'backup_used': 0,
        'rescheduled_for_holiday': 0,
    }
    if not batch_id:
        return issues

    # H1: visit without date/customer/tech
    cur.execute("""
        SELECT
          SUM(CASE WHEN start_date IS NULL THEN 1 ELSE 0 END) AS no_date,
          SUM(CASE WHEN client_id IS NULL THEN 1 ELSE 0 END) AS no_cust,
          SUM(CASE WHEN technician_id IS NULL THEN 1 ELSE 0 END) AS no_tech
        FROM snc_schedule_events WHERE draft_batch_id=%s
    """, (batch_id,))
    r = cur.fetchone()
    issues['visit_no_date'] = r['no_date'] or 0
    issues['visit_no_customer'] = r['no_cust'] or 0
    issues['visit_no_tech'] = r['no_tech'] or 0

    # H2: tech assigned but marked unavailable that day
    cur.execute("""
        SELECT COUNT(*) AS n FROM snc_schedule_events se
        JOIN snc_technician_day_status ts
          ON ts.technician_id = se.technician_id
         AND ts.date = se.start_date
        WHERE se.draft_batch_id = %s
          AND ts.status IN ('off','sick','training')
    """, (batch_id,))
    issues['tech_unavailable_but_assigned'] = cur.fetchone()['n']

    # H3: duplicate visits (same tech, client, date)
    cur.execute("""
        SELECT COUNT(*) AS n FROM (
            SELECT technician_id, client_id, start_date
            FROM snc_schedule_events
            WHERE draft_batch_id = %s
            GROUP BY 1,2,3 HAVING COUNT(*) > 1
        ) t
    """, (batch_id,))
    issues['duplicate_visits'] = cur.fetchone()['n']

    # H4: inactive customers scheduled
    cur.execute("""
        SELECT COUNT(*) AS n FROM snc_schedule_events se
        JOIN snc_clients c ON c.id = se.client_id
        WHERE se.draft_batch_id = %s AND COALESCE(c.is_active, true) = false
    """, (batch_id,))
    issues['inactive_customers_scheduled'] = cur.fetchone()['n']

    # H5: holiday + overlap conflicts from snc_schedule_conflicts
    cur.execute("""
        SELECT conflict_type, COUNT(*) AS n FROM snc_schedule_conflicts
        WHERE draft_batch_id = %s AND status = 'open'
        GROUP BY conflict_type
    """, (batch_id,))
    for r in cur.fetchall():
        if r['conflict_type'] == 'holiday_exception':
            issues['holiday_conflicts'] = r['n']
        elif r['conflict_type'] in ('overlap', 'double_booking'):
            issues['overlap_conflicts'] += r['n']

    # H6: unresolved compare results (from Excel comparison)
    cur.execute("""
        SELECT COUNT(*) AS n FROM snc_compare_results
        WHERE target_month = %s AND resolution = 'pending'
          AND diff_category NOT IN ('same','manual','approved_exception')
    """, (target_month,))
    issues['unresolved_compare'] = cur.fetchone()['n']

    # W1: tech overload (>5 visits in a day)
    cur.execute("""
        SELECT COUNT(*) AS n FROM (
            SELECT technician_id, start_date FROM snc_schedule_events
            WHERE draft_batch_id = %s
            GROUP BY 1,2 HAVING COUNT(*) > 5
        ) t
    """, (batch_id,))
    issues['tech_overloaded'] = cur.fetchone()['n']

    return issues


# ─────────────────────────────────────────────────────────────────────────────
# GET /audit/readiness/<month> — overall readiness score
# ─────────────────────────────────────────────────────────────────────────────

@audit_bp.route("/readiness/<month>", methods=["GET"])
@require_auth
def readiness(month):
    try:
        datetime.strptime(month + '-01', '%Y-%m-%d')
    except ValueError:
        return jsonify({"error": "Format bulan YYYY-MM"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            issues = _collect_audit_issues(cur, month)
            # Quick stats
            if issues['has_batch']:
                cur.execute("""
                    SELECT COUNT(*) AS total,
                           COUNT(DISTINCT technician_id) AS techs,
                           COUNT(DISTINCT client_id) AS clients,
                           COUNT(DISTINCT start_date) AS days
                    FROM snc_schedule_events WHERE draft_batch_id = %s
                """, (issues['batch_id'],))
                stats = cur.fetchone()
            else:
                stats = {'total': 0, 'techs': 0, 'clients': 0, 'days': 0}

    # Compute readiness score: PRD §11.3
    HARD_BLOCKERS = (
        issues['visit_no_date'] + issues['visit_no_customer'] + issues['visit_no_tech']
        + issues['tech_unavailable_but_assigned'] + issues['duplicate_visits']
        + issues['inactive_customers_scheduled'] + issues['holiday_conflicts']
        + issues['overlap_conflicts'] + issues['unresolved_compare']
    )
    SOFT_WARNINGS = issues['tech_overloaded']

    # Score formula: 100 - (hard*5) - (soft*1), clamped 0-100
    score = max(0, min(100, 100 - (HARD_BLOCKERS * 5) - (SOFT_WARNINGS * 1)))

    if score >= 95:
        status, label = 'ready', 'Siap Publish'
    elif score >= 85:
        status, label = 'warning', 'Bisa Publish dengan Warning'
    elif score >= 70:
        status, label = 'review', 'Perlu Review'
    else:
        status, label = 'not_ready', 'Belum Siap'

    return jsonify({
        'month': month,
        'batch_id': issues['batch_id'],
        'readiness_score': score,
        'status': status,
        'label': label,
        'blockers_total': HARD_BLOCKERS,
        'warnings_total': SOFT_WARNINGS,
        'issues': issues,
        'stats': stats,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /audit/blockers/<month> — detailed blocker + warning list
# ─────────────────────────────────────────────────────────────────────────────

@audit_bp.route("/blockers/<month>", methods=["GET"])
@require_auth
def blockers(month):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            issues = _collect_audit_issues(cur, month)

    BLOCKER_DEFS = [
        ('visit_no_date', '❌ Visit tanpa tanggal', 'Tidak boleh publish — visit harus punya tanggal.'),
        ('visit_no_customer', '❌ Visit tanpa lokasi', 'Tidak boleh publish — visit harus punya customer.'),
        ('visit_no_tech', '❌ Visit tanpa teknisi', 'Assign teknisi sebelum publish.'),
        ('tech_unavailable_but_assigned', '❌ Teknisi cuti tapi tetap dijadwal', 'Reassign ke backup atau skip.'),
        ('duplicate_visits', '❌ Duplikasi visit (tech+client+date)', 'Hapus atau merge duplicate.'),
        ('inactive_customers_scheduled', '❌ Lokasi disembunyikan masih dijadwal', 'Hapus dari draft.'),
        ('holiday_conflicts', '❌ Visit di hari libur', 'Reschedule atau approve sebagai exception.'),
        ('overlap_conflicts', '❌ Bentrok jam teknisi', 'Move time atau reassign.'),
        ('unresolved_compare', '❌ Perbedaan vs Excel belum diresolve', 'Resolve di Perbandingan Excel.'),
    ]
    WARNING_DEFS = [
        ('tech_overloaded', '⚠️ Teknisi overload (>5 visit/hari)', 'OK kalau koord setuju.'),
        ('manual_visits_no_contract', '⚠️ Visit manual tanpa kontrak', 'Tandai sebagai manual visit.'),
        ('backup_used', '⚠️ Backup teknisi dipakai', 'Logged, OK.'),
        ('rescheduled_for_holiday', '⚠️ Visit di-reschedule karena holiday', 'OK.'),
    ]

    blockers_list = [
        {'key': key, 'label': label, 'count': issues.get(key, 0), 'hint': hint}
        for key, label, hint in BLOCKER_DEFS if issues.get(key, 0) > 0
    ]
    warnings_list = [
        {'key': key, 'label': label, 'count': issues.get(key, 0), 'hint': hint}
        for key, label, hint in WARNING_DEFS if issues.get(key, 0) > 0
    ]
    return jsonify({
        'month': month,
        'batch_id': issues['batch_id'],
        'blockers': blockers_list,
        'warnings': warnings_list,
        'can_publish': len(blockers_list) == 0,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /audit/layer/calendar-count/<m> — Layer 1: PRD §8.1
# ─────────────────────────────────────────────────────────────────────────────

@audit_bp.route("/layer/calendar-count/<month>", methods=["GET"])
@require_auth
def layer_calendar_count(month):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT id FROM snc_draft_batches WHERE target_month=%s ORDER BY id DESC LIMIT 1
            """, (month,))
            r = cur.fetchone()
            batch_id = r['id'] if r else None
            if not batch_id:
                return jsonify({"error": "No batch", "month": month}), 404
            cur.execute("""
                SELECT TO_CHAR(start_date,'YYYY-MM-DD') AS d, COUNT(*) AS n
                FROM snc_schedule_events
                WHERE draft_batch_id = %s
                GROUP BY d ORDER BY d
            """, (batch_id,))
            sys_per_day = {r['d']: r['n'] for r in cur.fetchall()}

            # Latest Excel upload for compare (if any)
            cur.execute("""
                SELECT parsed_payload FROM snc_excel_upload
                WHERE target_month = %s ORDER BY id DESC LIMIT 1
            """, (month,))
            up = cur.fetchone()
            xlsx_per_day = {}
            if up and up['parsed_payload']:
                payload = up['parsed_payload']
                if isinstance(payload, str):
                    payload = json.loads(payload)
                for v in (payload.get('visits') or []):
                    d = v.get('date', '')[:10]
                    if d: xlsx_per_day[d] = xlsx_per_day.get(d, 0) + 1

    all_dates = sorted(set(sys_per_day) | set(xlsx_per_day))
    rows = []
    for d in all_dates:
        s = sys_per_day.get(d, 0)
        x = xlsx_per_day.get(d, 0)
        diff = s - x
        status = 'ok' if (x == 0 and s > 0) or diff == 0 else ('over' if diff > 0 else 'under')
        rows.append({'date': d, 'system_count': s, 'excel_count': x, 'diff': diff, 'status': status})
    return jsonify({'month': month, 'batch_id': batch_id, 'has_excel_compare': bool(xlsx_per_day), 'rows': rows})


# ─────────────────────────────────────────────────────────────────────────────
# GET /audit/layer/tech-assignment/<m> — Layer 4: PRD §8.4
# ─────────────────────────────────────────────────────────────────────────────

@audit_bp.route("/layer/tech-assignment/<month>", methods=["GET"])
@require_auth
def layer_tech_assignment(month):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""SELECT id FROM snc_draft_batches WHERE target_month=%s ORDER BY id DESC LIMIT 1""",
                       (month,))
            r = cur.fetchone()
            batch_id = r['id'] if r else None
            if not batch_id:
                return jsonify({"error": "No batch"}), 404
            cur.execute("""
                SELECT t.name AS tech, t.is_active,
                       COUNT(*) AS total,
                       COUNT(DISTINCT se.start_date) AS days_worked,
                       SUM(CASE WHEN ts.id IS NOT NULL THEN 1 ELSE 0 END) AS unavail_assigned,
                       (SELECT COUNT(*) FROM (
                          SELECT start_date FROM snc_schedule_events
                          WHERE technician_id = se.technician_id AND draft_batch_id = se.draft_batch_id
                          GROUP BY start_date HAVING COUNT(*) > 5
                       ) ov) AS overload_days
                FROM snc_schedule_events se
                JOIN snc_technicians t ON t.id = se.technician_id
                LEFT JOIN snc_technician_day_status ts
                  ON ts.technician_id = se.technician_id AND ts.date = se.start_date
                 AND ts.status IN ('off','sick','training')
                WHERE se.draft_batch_id = %s
                GROUP BY t.id, t.name, t.is_active, se.technician_id, se.draft_batch_id
                ORDER BY total DESC
            """, (batch_id,))
            rows = cur.fetchall()
    return jsonify({'month': month, 'batch_id': batch_id, 'rows': rows})


# ─────────────────────────────────────────────────────────────────────────────
# GET /audit/layer/duplicates/<m> — Layer 7: PRD §8.7
# ─────────────────────────────────────────────────────────────────────────────

@audit_bp.route("/layer/duplicates/<month>", methods=["GET"])
@require_auth
def layer_duplicates(month):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""SELECT id FROM snc_draft_batches WHERE target_month=%s ORDER BY id DESC LIMIT 1""",
                       (month,))
            r = cur.fetchone()
            batch_id = r['id'] if r else None
            if not batch_id:
                return jsonify({"error": "No batch"}), 404
            cur.execute("""
                SELECT se.technician_id, t.name AS tech_name, se.client_id, c.name AS client_name,
                       se.start_date, COUNT(*) AS dup_count,
                       ARRAY_AGG(se.id) AS event_ids
                FROM snc_schedule_events se
                JOIN snc_technicians t ON t.id = se.technician_id
                JOIN snc_clients c ON c.id = se.client_id
                WHERE se.draft_batch_id = %s
                GROUP BY se.technician_id, t.name, se.client_id, c.name, se.start_date
                HAVING COUNT(*) > 1
                ORDER BY dup_count DESC, se.start_date
            """, (batch_id,))
            dups = cur.fetchall()
    for d in dups:
        d['start_date'] = d['start_date'].isoformat()
    return jsonify({'month': month, 'batch_id': batch_id, 'duplicates': dups})


# ─────────────────────────────────────────────────────────────────────────────
# POST /audit/publish-gate/<m> — formal publish-gate check + log decision
# ─────────────────────────────────────────────────────────────────────────────

@audit_bp.route("/publish-gate/<month>", methods=["POST"])
@require_auth
def publish_gate(month):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    data = request.get_json() or {}
    override = bool(data.get('override', False))
    notes = data.get('notes', '')

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            issues = _collect_audit_issues(cur, month)
            batch_id = issues['batch_id']
            if not batch_id:
                return jsonify({"error": "No batch"}), 404

            HARD_KEYS = ['visit_no_date','visit_no_customer','visit_no_tech',
                         'tech_unavailable_but_assigned','duplicate_visits',
                         'inactive_customers_scheduled','holiday_conflicts',
                         'overlap_conflicts','unresolved_compare']
            SOFT_KEYS = ['tech_overloaded','manual_visits_no_contract',
                         'backup_used','rescheduled_for_holiday']
            blockers_total = sum(issues.get(k, 0) for k in HARD_KEYS)
            warnings_total = sum(issues.get(k, 0) for k in SOFT_KEYS)
            score = max(0, min(100, 100 - blockers_total*5 - warnings_total*1))

            if blockers_total > 0 and not override:
                decision = 'not_ready'
                allowed = False
            elif blockers_total > 0 and override:
                decision = 'override_publish'
                allowed = True
            elif warnings_total > 0:
                decision = 'warning_publish'
                allowed = True
            else:
                decision = 'ready'
                allowed = True

            cur.execute("""
                INSERT INTO snc_publish_gate_log
                    (batch_id, target_month, readiness_score, blockers_count,
                     warnings_count, decision, decided_by, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (batch_id, month, score, blockers_total, warnings_total,
                  decision, user_id, notes))
            log_id = cur.fetchone()['id']
            conn.commit()

    return jsonify({
        'gate_log_id': log_id, 'decision': decision, 'allowed': allowed,
        'readiness_score': score, 'blockers_total': blockers_total,
        'warnings_total': warnings_total,
    })
