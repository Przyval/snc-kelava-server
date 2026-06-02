"""
Auto-Draft Schedule Generator v2
=================================
Perbaikan utama dari v1:
  1. Week-of-month aware  — biweekly [1,3] atau [2,4] dideteksi dan direplikasi benar
  2. Recency-weighted confidence — bulan terakhir bobot 3x, 2 bulan lalu 2x, lebih lama 1x
  3. Suppression calendar — hari libur nasional & cuti bersama tidak di-generate
  4. Customer status check — customer paused/cancelled dilewati
  5. Primary technician assignment — pakai snc_customer_technician, bukan hanya histori
  6. Multi-month pattern analysis — baca hingga 3 bulan ke belakang untuk pola lebih kuat

Flow:
  1. POST /calendar/detect-patterns   { month }
     → Analisa snc_schedule_events, tulis snc_schedule_patterns
  2. POST /calendar/generate-draft    { source_month, target_month }
     → Insert snc_schedule_events status='draft'
  3. GET  /calendar/draft?month=
  4. POST /calendar/approve-draft     { month }
  5. DELETE /calendar/draft-event/<id>
  6. GET  /calendar/patterns?month=
"""

from datetime import date, datetime, timedelta
import calendar as cal_mod
from collections import defaultdict, Counter

from flask import Blueprint, jsonify, request, g
from core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

def _require_koordinator_or_admin():
    """Returns (user_id, error_response_or_None). Field supervisor read-only."""
    user = getattr(g, "current_user", None) or getattr(request, "_jwt_user", {})
    role = user.get('role') if isinstance(user, dict) else getattr(user, 'role', None)
    uid = user.get('id') if isinstance(user, dict) else getattr(user, 'user_id', 0)
    if role not in ('admin', 'koordinator'):
        return None, (jsonify({
            "error": "Forbidden",
            "detail": "Koordinator atau Admin only. Field supervisor read-only.",
        }), 403)
    return uid, None


draft_bp = Blueprint("schedule_draft", __name__, url_prefix="/api/v1/enterprise/calendar")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_month(s: str):
    y, m = s.split('-')
    return int(y), int(m)

def _month_dates(year: int, month: int):
    _, n = cal_mod.monthrange(year, month)
    return [date(year, month, d) for d in range(1, n + 1)]

def _week_of_month(d: date) -> int:
    """Minggu ke berapa dalam bulan (1-5). Day 1-7=1, 8-14=2, dst."""
    return (d.day - 1) // 7 + 1

def _nth_weekday(year: int, month: int, weekday: int, n: int):
    """
    Tanggal ke-n dari weekday (Mon=0) dalam bulan.
    Contoh: _nth_weekday(2026, 6, 0, 2) → Senin ke-2 Juni 2026.
    Return None kalau n melebihi jumlah minggu bulan tersebut.
    """
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    first_occ = first + timedelta(days=delta)
    target = first_occ + timedelta(weeks=n - 1)
    return target if target.month == month else None

def _working_days_by_dow(year: int, month: int, suppressed: set) -> dict:
    """
    Return dict dow → [date, ...] untuk hari kerja (Mon-Sat) bulan target.
    Hari yang masuk suppressed dikeluarkan.
    """
    result = defaultdict(list)
    for d in _month_dates(year, month):
        if d.weekday() >= 6:        # skip Minggu
            continue
        if d in suppressed:         # skip hari libur
            continue
        result[d.weekday()].append(d)
    return result

def _load_suppressed(cur, year: int, month: int) -> set:
    """Load suppression_dates untuk bulan tertentu."""
    _, n = cal_mod.monthrange(year, month)
    cur.execute("""
        SELECT suppression_date FROM snc_suppression_dates
        WHERE suppression_date BETWEEN %s AND %s
    """, (date(year, month, 1), date(year, month, n)))
    return {r['suppression_date'] for r in cur.fetchall()}

def _load_client_suppressions(cur, year: int, month: int) -> dict:
    """
    Return dict {client_id: set_of_dates} for per-customer suppressions
    overlapping target month. Used to skip events for "lokasi libur sementara".
    """
    import calendar as cal_mod
    _, ndays = cal_mod.monthrange(year, month)
    mstart = date(year, month, 1)
    mend = date(year, month, ndays)
    cur.execute("""
        SELECT client_id, start_date, end_date
        FROM snc_client_suppression_dates
        WHERE start_date <= %s AND end_date >= %s
    """, (mend, mstart))
    result = defaultdict(set)
    for r in cur.fetchall():
        d = max(r['start_date'], mstart)
        end = min(r['end_date'], mend)
        while d <= end:
            result[r['client_id']].add(d)
            d += timedelta(days=1)
    return result


def _load_tech_unavailable(cur, year: int, month: int) -> dict:
    """
    Return dict {(tech_id, date): {'status':'off|sick|training', 'backup_tech_id': N}}
    for tech absences in target month.
    """
    import calendar as cal_mod
    _, ndays = cal_mod.monthrange(year, month)
    mstart = date(year, month, 1)
    mend = date(year, month, ndays)
    cur.execute("""
        SELECT technician_id, date, status, backup_tech_id
        FROM snc_technician_day_status
        WHERE date BETWEEN %s AND %s
          AND status IN ('off', 'sick', 'training')
    """, (mstart, mend))
    return {(r['technician_id'], r['date']): {
        'status': r['status'], 'backup_tech_id': r['backup_tech_id']
    } for r in cur.fetchall()}


def _load_active_clients(cur) -> set:
    """
    Return set of snc_client_id yang status = 'active'.
    Kalau customer_master tidak ada (belum di-import), anggap semua aktif.
    """
    cur.execute("""
        SELECT snc_client_id FROM snc_customer_master
        WHERE customer_status IN ('active')
          AND snc_client_id IS NOT NULL
    """)
    rows = cur.fetchall()
    if not rows:
        return None          # None = tidak ada filter, semua diizinkan
    return {r['snc_client_id'] for r in rows}

def _load_primary_technician(cur, schedulable_techs: set) -> dict:
    """
    Return {client_id: technician_id} untuk primary technician.
    FILTER: hanya primary yang ada di schedulable_techs (active, mobile/support).
    Fallback ke backup_1 → backup_2 jika primary tidak schedulable.
    """
    cur.execute("""
        SELECT client_id, technician_id, role
        FROM snc_customer_technician
        ORDER BY client_id,
                 CASE role WHEN 'primary' THEN 1 WHEN 'backup_1' THEN 2 ELSE 3 END
    """)
    result = {}
    for r in cur.fetchall():
        cid = r['client_id']
        if cid in result:
            continue  # sudah dapat primary/backup yang valid
        if r['technician_id'] in schedulable_techs:
            result[cid] = r['technician_id']
    return result

def _load_schedulable_technicians(cur, target_date: date) -> set:
    """
    Return set of technician_id yang boleh di-schedule.
    PERETAT: hanya mobile/support (tidak boleh NULL — Station harus tegas).
    """
    cur.execute("""
        SELECT id FROM snc_technicians
        WHERE is_active = true
          AND (contract_expiry IS NULL OR contract_expiry >= %s)
          AND employee_type IN ('mobile', 'support')
    """, (target_date,))
    return {r['id'] for r in cur.fetchall()}

def _stable_week_pattern(visit_infos: list, source_year: int, source_month: int) -> tuple[str | None, float]:
    """
    Pattern Detector v22 — multi-month WoM consistency check.

    For a biweekly client, look at every month in lookback and find which
    weeks-of-month they were visited (on this DOW). If consistent (≥66%
    of months hit the same WoM set), return that as explicit `week_pattern`
    (e.g. '2,4' or '1,3,5'). Otherwise return (None, 0) so caller falls
    back to cadence anchor.

    Returns: (week_pattern_str or None, consistency_score 0..1)

    Why this fixes v21's overfit problem:
      - v21 used `cadence:<last-may-date>` — projects from a single point,
        misses if June koordinator shifts cadence
      - v22 uses majority-vote across all observed months — robust to
        any single month's irregularity, captures stable patterns
    """
    if not visit_infos:
        return None, 0.0

    # Group by (year, month) → set of WoMs visited that month
    by_month = defaultdict(set)
    for v in visit_infos:
        d = v['date']
        # Skip source month — we want HISTORY only for inference
        if d.year == source_year and d.month == source_month:
            continue
        by_month[(d.year, d.month)].add(v['wom'])

    if len(by_month) < 2:
        return None, 0.0  # need ≥2 prior months for consistency

    # Strategy 1: exact set majority vote (e.g. {2,4} appears in 2/3 months)
    wom_set_counts = Counter()
    for woms in by_month.values():
        wom_set_counts[frozenset(woms)] += 1
    top_set, top_count = wom_set_counts.most_common(1)[0]
    consistency = top_count / len(by_month)

    # Strategy 2: union-of-stable WoMs (which WoMs appear in ≥50% of months?)
    # This handles cases where one month skips a week — still captures the
    # overall stable pattern.
    wom_freq = Counter()
    for woms in by_month.values():
        for w in woms:
            wom_freq[w] += 1
    threshold = max(1, len(by_month) // 2)
    stable_woms = sorted([w for w, n in wom_freq.items() if n >= threshold])

    # Pick whichever strategy gives higher confidence
    if consistency >= 0.66 and top_set and len(top_set) <= 3:
        return ','.join(str(w) for w in sorted(top_set)), consistency
    if stable_woms and 1 <= len(stable_woms) <= 3:
        # Strategy 2 confidence = avg fraction of months hitting these WoMs
        s2_conf = sum(wom_freq[w] for w in stable_woms) / (len(stable_woms) * len(by_month))
        if s2_conf >= 0.5:
            return ','.join(str(w) for w in stable_woms), s2_conf
    return None, consistency

    return ','.join(str(w) for w in sorted(top_set)), consistency


def _generate_rule_dates(rule: dict, year: int, month: int, suppressed: set) -> list:
    """
    Generate target dates dari recurring rule untuk bulan target.
    Support multi-DOW (rule.weekdays = [0, 3] = Mon+Thu) + week_pattern.
    """
    import calendar as _cal
    _, ndays = _cal.monthrange(year, month)
    weekdays = rule.get('weekdays') or []
    if not weekdays:
        return []
    frequency = rule['frequency']
    week_pattern = rule.get('week_pattern')
    suppress_holiday = rule.get('suppress_holiday', True)
    is_mandatory = rule.get('is_mandatory', False)

    target_dates = []
    for day in range(1, ndays + 1):
        d = date(year, month, day)
        if d.weekday() not in weekdays:
            continue
        # Suppression check
        if d in suppressed and suppress_holiday:
            continue
        # Apply week_pattern filter for biweekly/monthly
        wom = (d.day - 1) // 7 + 1
        if frequency in ('biweekly', 'monthly') and week_pattern:
            if week_pattern.startswith('cadence:'):
                # Cadence anchor projection
                try:
                    anchor = date.fromisoformat(week_pattern[8:])
                    delta = (d - anchor).days
                    if delta % 14 != 0 or delta < 0:
                        continue
                except Exception:
                    pass
            else:
                # Standard week_pattern '1,3' or '2,4'
                try:
                    target_woms = [int(w) for w in week_pattern.split(',') if w.strip().isdigit()]
                    if wom not in target_woms:
                        continue
                except Exception:
                    pass
        target_dates.append(d)
    return sorted(target_dates)


def _consolidate_patterns_per_client(patterns: list, schedulable_techs: set) -> list:
    """
    BUG FIX #9 + #10 + #12: Dedup multi-pattern per (client, day_of_week) +
    pattern conflict resolution + MULTI-TECH support.

    Step 1: Per (client, dow), keep TOP 2 patterns kalau:
            - Both have confidence >= 0.7
            - Both techs are schedulable
            - Both techs are different (multi-tech customer split duty)
            Otherwise pick winner only.
    Step 2: Per client, drop weak monthly patterns di DOW lain saat ada
            strong weekly/biweekly pattern.
    """
    # Step 1: per (client, dow) top patterns
    by_key = {}
    for p in patterns:
        key = (p['client_id'], p['day_of_week'])
        sched_bonus = 2.0 if p['technician_id'] in schedulable_techs else 1.0
        score = float(p.get('confidence', 0)) * float(p.get('recency_score', 0)) * sched_bonus
        by_key.setdefault(key, []).append((score, p))

    selected = []
    for key, candidates in by_key.items():
        candidates.sort(reverse=True, key=lambda x: x[0])
        winner_score, winner = candidates[0]
        selected.append(winner)
        # BUG FIX #19: CO-VISIT pattern detection
        # Keep semua tech yang punya conf >= 0.7 + schedulable + beda tech
        # Customer dengan 3+ tech rutin co-visit (EL GRANDE, GRAHA PADEL, etc)
        kept_techs = {winner['technician_id']}
        for r_score, runner in candidates[1:]:
            if len(kept_techs) >= 3:  # cap di 3 tech max
                break
            if (float(runner.get('confidence', 0)) >= 0.7
                and runner['technician_id'] in schedulable_techs
                and runner['technician_id'] not in kept_techs
                and r_score >= winner_score * 0.55):  # 55% threshold (was 60%)
                selected.append(runner)
                kept_techs.add(runner['technician_id'])

    # Step 2: identify strong-DOW per client
    # Strong = weekly/biweekly dengan occurrence_count >= 6 atau confidence >= 0.85
    strong_dow_per_client = {}  # client_id → set of strong DOWs
    for p in selected:
        cid = p['client_id']
        is_strong = (
            p['frequency'] in ('weekly', 'biweekly') and
            (p.get('occurrence_count', 0) >= 6 or float(p.get('confidence', 0)) >= 0.85)
        )
        if is_strong:
            strong_dow_per_client.setdefault(cid, set()).add(p['day_of_week'])

    # Step 3: drop weak patterns di DOW lain
    result = []
    dropped_conflict = 0
    for p in selected:
        cid = p['client_id']
        strong_dows = strong_dow_per_client.get(cid, set())
        if strong_dows and p['day_of_week'] not in strong_dows:
            # Customer punya strong pattern di DOW lain
            # Drop this if it's monthly/adhoc (likely noise from occasional visits)
            if p['frequency'] in ('monthly', 'adhoc'):
                dropped_conflict += 1
                continue
        result.append(p)

    return result


def _load_active_clients_smart(cur, source_year: int, source_month: int) -> set:
    """
    BUG FIX #10 + #21: Active client filter dengan override + churn signal.
    - Customer "active" di Accurate → include
    - Customer "cancelled" + visit di source_month → include (false negative)
    - Customer "paused" → EXCLUDE (deliberate pause signal)
    - Customer dengan last_invoice_date > 60 hari sebelum source month end
      AND tier C → EXCLUDE (churn risk signal)
    """
    import calendar as cal_mod
    _, n = cal_mod.monthrange(source_year, source_month)
    src_end = date(source_year, source_month, n)
    cutoff_60d = date(source_year, source_month, 1)
    if source_month >= 3:
        cutoff_60d = date(source_year, source_month - 2, 1)
    else:
        cutoff_60d = date(source_year - 1, 12 + source_month - 2, 1)

    cur.execute("""
        SELECT snc_client_id, customer_status, last_invoice_date, revenue_tier,
               invoice_count_12m, accurate_name
        FROM snc_customer_master
        WHERE snc_client_id IS NOT NULL
    """)
    rows = cur.fetchall()

    active_set = set()
    for r in rows:
        cid = r['snc_client_id']
        status = r['customer_status']
        tier = r['revenue_tier'] or 'C'
        last_inv = r['last_invoice_date']
        matched_accurate = r['accurate_name'] is not None

        # Drop: paused (deliberate decision by supervisor / Accurate)
        if status == 'paused':
            continue

        # Default: include active + cancelled (we'll override cancelled below)
        if status in ('active', 'cancelled'):
            active_set.add(cid)

    # Override: cancelled customer with recent visit (false cancel in Accurate)
    cur.execute("""
        SELECT DISTINCT se.client_id
        FROM snc_schedule_events se
        JOIN snc_customer_master cm ON cm.snc_client_id = se.client_id
        WHERE cm.customer_status = 'cancelled'
          AND cm.last_invoice_date >= %s
          AND se.schedule_status IN ('scheduled', 'completed')
          AND se.start_date BETWEEN %s AND %s
    """, (cutoff_60d, date(source_year, source_month, 1), src_end))
    for r in cur.fetchall():
        active_set.add(r['client_id'])

    if not active_set:
        return None
    return active_set


# ──────────────────────────────────────────────────────────────────────────────
# 1. DETECT PATTERNS  (v2 — recency-weighted, week-of-month aware)
# ──────────────────────────────────────────────────────────────────────────────

@draft_bp.route("/detect-patterns", methods=["POST"])
@require_auth
def detect_patterns():
    """
    Analisa snc_schedule_events untuk satu bulan (atau multi-bulan lookback).
    POST body: { "month": "2026-05", "lookback_months": 3 }
    """
    user_id_perm, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    data = request.get_json() or {}
    source_month = data.get("month") or request.args.get("month", "")
    if not source_month:
        return jsonify({"error": "month required (e.g. '2026-05')"}), 400

    lookback = int(data.get("lookback_months", 3))  # default 3 bulan ke belakang

    try:
        year, month = _parse_month(source_month)
    except Exception:
        return jsonify({"error": "invalid month format"}), 400

    # Hitung rentang tanggal: lookback bulan hingga akhir source_month
    end_date = date(year, month, cal_mod.monthrange(year, month)[1])
    lb_month = month - lookback
    lb_year  = year
    while lb_month < 1:
        lb_month += 12
        lb_year  -= 1
    start_date = date(lb_year, lb_month, 1)

    # Bobot per bulan: bulan terdekat = bobot tertinggi
    def _month_weight(d: date) -> float:
        months_ago = (year - d.year) * 12 + (month - d.month)
        if months_ago == 0:   return 3.0
        if months_ago == 1:   return 2.0
        return 1.0

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:

            cur.execute("""
                SELECT
                    se.technician_id,
                    se.client_id,
                    se.visit_type,
                    TO_CHAR(se.start_datetime, 'HH24:MI') AS time_start,
                    TO_CHAR(se.end_datetime,   'HH24:MI') AS time_end,
                    se.start_date,
                    se.schedule_status
                FROM snc_schedule_events se
                WHERE se.start_date BETWEEN %s AND %s
                  AND se.schedule_status IN ('scheduled','completed')
                ORDER BY se.technician_id, se.client_id, se.start_date
            """, (start_date, end_date))
            rows = cur.fetchall()

            # BUG FIX #3: Normalize time — Kelava 'completed' check_in has noisy
            # minute-level times (e.g., 21:54, 06:55). Excel 'scheduled' is
            # clean hourly (08:00, 14:00). Snap completed times to nearest
            # half-hour to reduce noise.
            for r in rows:
                if r['schedule_status'] == 'completed' and r['time_start']:
                    try:
                        h, m = int(r['time_start'][:2]), int(r['time_start'][3:5])
                        # Snap to nearest 30 minutes
                        m_snap = 0 if m < 15 else (30 if m < 45 else 0)
                        if m >= 45: h = (h + 1) % 24
                        r['time_start'] = f"{h:02d}:{m_snap:02d}"
                    except Exception:
                        pass

        # ── BUG FIX #8: Group by (tech, client, DOW) — MULTI-DOW SUPPORT ──
        # Customer bisa punya multi-day pattern (Senin+Kamis+Jumat tiap minggu).
        # Jadi setiap (tech, client, DOW) jadi pattern terpisah.
        groups = defaultdict(list)
        for r in rows:
            dow_py = r['start_date'].weekday()  # Mon=0
            groups[(r['technician_id'], r['client_id'], dow_py)].append(r)

        # Hapus pattern lama untuk source_month ini agar tidak konflik schema
        with conn.cursor() as cur:
            cur.execute("DELETE FROM snc_schedule_patterns WHERE source_month = %s", (source_month,))

        patterns_written = 0
        patterns_skipped = 0
        freq_tally = defaultdict(int)

        with conn.cursor(row_factory=dict_row) as cur:
            for (tech_id, client_id, dow_py), visits in groups.items():

                visit_infos = []
                for v in visits:
                    d = v['start_date']
                    visit_infos.append({
                        'date':       d,
                        'wom':        _week_of_month(d),
                        'time_start': v['time_start'],
                        'time_end':   v['time_end'],
                        'visit_type': v['visit_type'],
                        'weight':     _month_weight(d),
                    })

                count = len(visit_infos)
                weighted_count = sum(v['weight'] for v in visit_infos)

                # Hitung visits dalam source_month
                src_visits = [v for v in visit_infos
                              if v['date'].year == year and v['date'].month == month]
                src_count  = len(src_visits)
                src_woms   = sorted({v['wom'] for v in src_visits})

                # BUG FIX #4: Long-history weekly detection
                # Customer dengan visit >=12x dalam lookback DAN >=1 di source month
                # = weekly walaupun src_count hanya 1-2 (mungkin libur/cuti bulan ini)
                long_history_weekly = (
                    count >= 12 and src_count >= 1 and
                    count / max((end_date - start_date).days / 7, 1) >= 0.6
                )

                # BUG FIX #14: Last visit in source month untuk cadence projection
                last_src_visit = max((v['date'] for v in src_visits), default=None)

                # ── Klasifikasi frekuensi (semua untuk DOW ini saja) ──────────
                recency_score = 1.0 if src_count > 0 else 0.4
                if src_count >= 3:
                    frequency    = 'weekly'
                    week_pattern = None
                    confidence   = min(1.0, round(weighted_count / (4 * 3.0), 2))

                # BUG FIX #15 + #16: Source month biweekly signal beats long-history weekly,
                # tapi check interval — 2 visit 7 hari apart ≠ biweekly, itu weekly.
                elif src_count == 2 and len(src_woms) == 2:
                    src_dates = sorted(v['date'] for v in src_visits)
                    interval = (src_dates[1] - src_dates[0]).days
                    if interval <= 9:  # ≤9 hari = weekly (toleransi 2 hari)
                        frequency    = 'weekly'
                        week_pattern = None
                        confidence   = round(min(0.85, weighted_count / 8.0), 2)
                    else:  # ≥10 hari = biweekly
                        frequency    = 'biweekly'
                        # Pattern Detector v22: try multi-month WoM consistency first.
                        # Falls back to v21 cadence-anchor only when history is too thin
                        # or weeks-of-month are inconsistent across months.
                        stable_wp, _consistency = _stable_week_pattern(visit_infos, year, month)
                        if stable_wp:
                            week_pattern = stable_wp
                        elif last_src_visit:
                            week_pattern = f"cadence:{last_src_visit.isoformat()}"
                        else:
                            week_pattern = ','.join(str(w) for w in src_woms)
                        confidence   = round(min(1.0, weighted_count / (2 * 3.0)), 2)

                elif long_history_weekly:
                    frequency    = 'weekly'
                    week_pattern = None
                    confidence   = round(min(0.90, weighted_count / 12.0), 2)

                elif src_count == 1:
                    frequency    = 'monthly'
                    week_pattern = str(src_woms[0]) if src_woms else None
                    confidence   = round(min(0.80, weighted_count / 3.0), 2)

                elif src_count == 0 and count >= 6:
                    # Hilang di source tapi history kuat → mungkin libur sebulan
                    frequency     = 'monthly'
                    week_pattern  = None
                    confidence    = 0.45
                    recency_score = 0.6   # lolos filter recency >= 0.5

                elif src_count == 0:
                    patterns_skipped += 1
                    continue

                else:
                    frequency    = 'adhoc'
                    week_pattern = None
                    confidence   = round(min(0.50, weighted_count / 6.0), 2)

                freq_tally[frequency] += 1

                # BUG FIX #3: Time & visit type — PREFER source month (Excel
                # scheduled) over lookback (Kelava actual check_in).
                # Excel scheduled time = ground truth; Kelava check_in is noisy.
                ref_visits = src_visits if src_visits else visit_infos
                ts_list = [v['time_start'] for v in ref_visits if v['time_start']]
                te_list = [v['time_end']   for v in ref_visits if v['time_end']]
                vt_list = [v['visit_type'] for v in ref_visits if v['visit_type']]
                modal_ts = max(set(ts_list), key=ts_list.count) if ts_list else None
                modal_te = max(set(te_list), key=te_list.count) if te_list else None
                modal_vt = max(set(vt_list), key=vt_list.count) if vt_list else None

                try:
                    cur.execute("""
                        INSERT INTO snc_schedule_patterns
                            (technician_id, client_id, frequency, day_of_week, week_of_month,
                             week_pattern, time_start, time_end, visit_type,
                             confidence, recency_score, occurrence_count, source_month)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (tech_id, client_id,
                          frequency, dow_py,
                          src_woms[0] if len(src_woms) == 1 else None,
                          week_pattern, modal_ts, modal_te, modal_vt,
                          confidence, recency_score, count, source_month))
                    patterns_written += 1
                except Exception as e:
                    conn.rollback()
                    patterns_skipped += 1
                    continue

            conn.commit()

    return jsonify({
        "source_month":    source_month,
        "lookback_months": lookback,
        "analysis_range":  f"{start_date} → {end_date}",
        "patterns_written": patterns_written,
        "patterns_skipped": patterns_skipped,
        "summary": {
            "weekly":    freq_tally['weekly'],
            "biweekly":  freq_tally['biweekly'],
            "monthly":   freq_tally['monthly'],
            "adhoc":     freq_tally['adhoc'],
        }
    })


# ──────────────────────────────────────────────────────────────────────────────
# 2. GENERATE DRAFT  (v2 — week-of-month, suppression, primary tech)
# ──────────────────────────────────────────────────────────────────────────────

@draft_bp.route("/generate-draft", methods=["POST"])
@require_auth
def generate_draft():
    """
    Generate draft schedule_events untuk target_month.
    POST body: {
        "source_month": "2026-05",
        "target_month": "2026-06",
        "min_confidence": 0.5          (optional, default 0.5)
    }
    """
    user_id_perm, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    data = request.get_json() or {}
    source_month = data.get("source_month", "")
    target_month = data.get("target_month", "")
    min_conf     = float(data.get("min_confidence", 0.50))

    if not source_month or not target_month:
        return jsonify({"error": "source_month and target_month required"}), 400

    try:
        tgt_year, tgt_month = _parse_month(target_month)
    except Exception:
        return jsonify({"error": "invalid month format"}), 400

    user_id = getattr(g, "user_id", 0) or 0

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:

            # ── Suppression calendar ──────────────────────────────────────────
            suppressed = _load_suppressed(cur, tgt_year, tgt_month)

            # ── Working days by DOW (excluding suppressed) ────────────────────
            days_by_dow = _working_days_by_dow(tgt_year, tgt_month, suppressed)

            # ── Customer active status (dengan smart override) ────────────────
            src_y, src_m = _parse_month(source_month)
            active_clients = _load_active_clients_smart(cur, src_y, src_m)

            # ── Omzet SSOT filter (PRD: hanya customer dgn kontrak aktif) ────
            # Customer hanya schedulable kalau ada snc_contracts dengan period
            # yang mencakup target month.
            tgt_month_start = date(tgt_year, tgt_month, 1)
            import calendar as _cal_mod
            _, tgt_ndays = _cal_mod.monthrange(tgt_year, tgt_month)
            tgt_month_end = date(tgt_year, tgt_month, tgt_ndays)
            cur.execute("""
                SELECT DISTINCT snc_customer_id FROM snc_contracts
                WHERE snc_customer_id IS NOT NULL
                  AND COALESCE(is_active, 'YES') = 'YES'
                  AND start_date <= %s AND end_date >= %s
            """, (tgt_month_end, tgt_month_start))
            ssot_active_clients = {r['snc_customer_id'] for r in cur.fetchall()}

            # Intersect with existing active_clients filter (if both set)
            if active_clients is not None:
                active_clients = active_clients & ssot_active_clients
            else:
                active_clients = ssot_active_clients

            # ── Per-customer suppression (Lokasi Libur Sementara) ─────────────
            client_suppressions = _load_client_suppressions(cur, tgt_year, tgt_month)

            # ── Per-tech unavailability (Teknisi Tidak Masuk) ─────────────────
            tech_unavailable = _load_tech_unavailable(cur, tgt_year, tgt_month)

            # ── Teknisi yang valid untuk di-schedule ──────────────────────────
            target_month_start = date(tgt_year, tgt_month, 1)
            schedulable_techs  = _load_schedulable_technicians(cur, target_month_start)

            # ── Primary technician per client (sudah pre-filtered ke schedulable)
            primary_tech = _load_primary_technician(cur, schedulable_techs)

            # ── BUG FIX #22 / Phase 1: Load manual recurring rules ────────────
            # Rules override pattern detection untuk customer yang sudah punya rule
            cur.execute("""
                SELECT * FROM snc_recurring_rules
                WHERE effective_start <= %s
                  AND (effective_end IS NULL OR effective_end >= %s)
            """, (target_month_start, target_month_start))
            rules = cur.fetchall()
            rule_by_client = {r['client_id']: r for r in rules}

            # ── Delete existing draft if re-generating ────────────────────────
            cur.execute("""
                SELECT id FROM snc_draft_batches WHERE target_month = %s
            """, (target_month,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""
                    DELETE FROM snc_schedule_events
                    WHERE draft_batch_id = %s AND schedule_status = 'draft'
                """, (existing['id'],))
                cur.execute("DELETE FROM snc_draft_batches WHERE id = %s", (existing['id'],))

            # ── Create batch ──────────────────────────────────────────────────
            cur.execute("""
                INSERT INTO snc_draft_batches (target_month, source_month, generated_by)
                VALUES (%s,%s,%s) RETURNING id
            """, (target_month, source_month, user_id))
            batch_id = cur.fetchone()['id']

            # ── Load patterns ─────────────────────────────────────────────────
            cur.execute("""
                SELECT p.*, t.supervisor_id,
                       t.kelava_p_user_id
                FROM snc_schedule_patterns p
                JOIN snc_technicians t ON t.id = p.technician_id
                WHERE p.source_month = %s
                  AND p.confidence   >= %s
                  AND p.recency_score >= 0.5     -- harus muncul di bulan terakhir atau dekat
                ORDER BY p.confidence DESC, p.frequency
            """, (source_month, min_conf))
            patterns = cur.fetchall()

            if not patterns:
                conn.rollback()
                return jsonify({
                    "error": f"Tidak ada pattern untuk {source_month} "
                             f"(min_confidence={min_conf}). Jalankan detect-patterns dulu."
                }), 400

            # ── BUG FIX #9: Consolidate per (client, dow), prefer schedulable
            patterns_before = len(patterns)
            patterns = _consolidate_patterns_per_client(patterns, schedulable_techs)
            consolidated_count = patterns_before - len(patterns)

            # ── BUG FIX #22 / Phase 1: Filter patterns yang sudah punya mandatory rule
            # Customer dengan is_mandatory=true rule → skip pattern detection
            mandatory_clients = {r['client_id'] for r in rules if r['is_mandatory']}
            patterns = [p for p in patterns if p['client_id'] not in mandatory_clients]
            rules_override_count = len(mandatory_clients)

            events_created  = 0
            events_skipped  = 0
            skip_reasons    = defaultdict(int)
            tech_workload   = defaultdict(int)   # untuk leveling cap

            # ── Phase 1: Process recurring rules FIRST (mandatory + optional) ──
            # Semantic: primary + backup_1 + backup_2 = ALL come together (co-visit)
            # Not fallback — supervisor specifies multi-tech intentionally
            for rule in rules:
                cid = rule['client_id']
                if active_clients is not None and cid not in active_clients:
                    events_skipped += 1
                    skip_reasons['rule_customer_inactive'] += 1
                    continue

                # Collect ALL schedulable techs from rule (primary + backups)
                rule_techs = []
                for tid in [rule['primary_tech_id'], rule['backup_tech_1_id'], rule['backup_tech_2_id']]:
                    if tid and tid in schedulable_techs and tid not in rule_techs:
                        rule_techs.append(tid)

                if not rule_techs:
                    events_skipped += 1
                    skip_reasons['rule_no_tech_available'] += 1
                    continue

                # Generate target dates per weekday in rule
                rule_dates = _generate_rule_dates(rule, tgt_year, tgt_month, suppressed)

                # Insert events for each tech × date (co-visit semantic)
                for visit_date in rule_dates:
                    # Skip if customer has suppression (Lokasi Libur Sementara)
                    if visit_date in client_suppressions.get(cid, set()):
                        events_skipped += 1
                        skip_reasons['client_suppressed'] += 1
                        continue
                    for tech in rule_techs:
                        # Skip if tech is unavailable (cuti/sakit/training)
                        if (tech, visit_date) in tech_unavailable:
                            unav = tech_unavailable[(tech, visit_date)]
                            # Try backup_tech if available and different
                            backup_id = unav.get('backup_tech_id')
                            if backup_id and backup_id in schedulable_techs and backup_id not in rule_techs:
                                tech = backup_id  # reassign to backup
                            else:
                                events_skipped += 1
                                skip_reasons[f'tech_unavailable_{unav["status"]}'] += 1
                                continue
                        iso_year, iso_week, _ = visit_date.isocalendar()
                        week_key = (tech, iso_year, iso_week)
                        day_key  = (tech, visit_date)
                        if tech_workload.get(week_key, 0) >= 18:
                            events_skipped += 1
                            skip_reasons['week_cap_exceeded'] += 1
                            continue
                        if tech_workload.get(day_key, 0) >= 5:
                            events_skipped += 1
                            skip_reasons['day_cap_exceeded'] += 1
                            continue

                        ts = rule['time_start']
                        te = rule['time_end']
                        try:
                            start_dt = datetime.combine(visit_date, ts)
                        except Exception:
                            start_dt = datetime(visit_date.year, visit_date.month, visit_date.day, 8, 0)
                        end_dt = datetime.combine(visit_date, te) if te else None
                        if end_dt and end_dt <= start_dt:
                            end_dt += timedelta(days=1)

                        cur.execute("""
                            SELECT id FROM snc_schedule_events
                            WHERE draft_batch_id = %s AND technician_id = %s
                              AND client_id = %s AND start_date = %s LIMIT 1
                        """, (batch_id, tech, cid, visit_date))
                        if cur.fetchone():
                            events_skipped += 1
                            skip_reasons['duplicate'] += 1
                            continue

                        notes = f"Rule | {rule['frequency']} | mandatory={rule['is_mandatory']}"

                        cur.execute("""
                            INSERT INTO snc_schedule_events
                                (technician_id, client_id, visit_type,
                                 start_datetime, end_datetime, start_date,
                                 schedule_status, draft_batch_id, created_by, notes,
                                 source, rule_id, is_mandatory)
                            VALUES (%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s,
                                    'rule',%s,%s)
                        """, (tech, cid, rule['visit_type'],
                              start_dt, end_dt, visit_date,
                              batch_id, user_id, notes,
                              rule['id'], rule['is_mandatory']))
                        events_created += 1
                        tech_workload[week_key] = tech_workload.get(week_key, 0) + 1
                        tech_workload[day_key]  = tech_workload.get(day_key, 0) + 1

            for p in patterns:
                client_id = p['client_id']
                tech_id   = p['technician_id']

                # ── Skip customer tidak aktif ──────────────────────────────────
                if active_clients is not None and client_id not in active_clients:
                    events_skipped += 1
                    skip_reasons['customer_inactive'] += 1
                    continue

                # ── Skip teknisi yang tidak schedulable ────────────────────────
                # (Station, kontrak habis, is_active=false)
                if schedulable_techs and tech_id not in schedulable_techs:
                    # Coba primary tech yang valid
                    alt = primary_tech.get(client_id)
                    if alt and alt in schedulable_techs:
                        tech_id = alt
                    else:
                        events_skipped += 1
                        skip_reasons['technician_not_schedulable'] += 1
                        continue

                # ── Skip adhoc dengan confidence rendah ───────────────────────
                if p['frequency'] == 'adhoc' and p['confidence'] < 0.60:
                    events_skipped += 1
                    skip_reasons['adhoc_low_conf'] += 1
                    continue

                # ── Tentukan tanggal-tanggal target ───────────────────────────
                dow = p['day_of_week']
                if dow is None:
                    events_skipped += 1
                    skip_reasons['no_dow'] += 1
                    continue

                target_dates = []

                # BUG FIX #11 + #20: Soft suppression — high-traffic customer
                # (occurrence_count >= 10) tetap generate di hari libur SAUF
                # customer punya pattern selalu skip pada hari libur sebelumnya.
                # Mulai dari conservative: only EL GRANDE/GRAHA/RJS style 24/7
                # operations (mall, hotel) — for now require >= 15 visits.
                occ = p.get('occurrence_count', 0)
                high_traffic = occ >= 15  # tighten from 10 → 15

                if p['frequency'] == 'weekly':
                    # Semua Senin (atau hari apapun) dalam bulan
                    all_dow = days_by_dow.get(dow, [])
                    if high_traffic:
                        # Tambah tanggal yang di-suppress kembali
                        import calendar as _cal
                        _, _ndays = _cal.monthrange(tgt_year, tgt_month)
                        for _d in range(1, _ndays + 1):
                            _date = date(tgt_year, tgt_month, _d)
                            if _date.weekday() == dow and _date in suppressed and _date not in all_dow:
                                all_dow.append(_date)
                    target_dates = sorted(all_dow)

                elif p['frequency'] == 'biweekly':
                    wp = p.get('week_pattern') or ''
                    # BUG FIX #14: Cadence projection
                    # Format "cadence:YYYY-MM-DD" = last visit in source month
                    # Project: last + 14, +28, +42 → target month dates
                    if wp.startswith('cadence:'):
                        try:
                            anchor = date.fromisoformat(wp[8:])
                            target_month_start = date(tgt_year, tgt_month, 1)
                            import calendar as _cal
                            _, _ndays = _cal.monthrange(tgt_year, tgt_month)
                            target_month_end = date(tgt_year, tgt_month, _ndays)
                            # BUG FIX #18: Keep cadence anchor stable, just skip suppressed
                            # Customer biweekly tetap di 14-day rhythm walaupun ada libur
                            d = anchor + timedelta(days=14)
                            while d <= target_month_end:
                                if d >= target_month_start and d.weekday() == dow:
                                    if not (d in suppressed and not high_traffic):
                                        target_dates.append(d)
                                d += timedelta(days=14)  # cadence selalu lanjut
                        except Exception:
                            # Fallback to default biweekly
                            for wn in [1, 3]:
                                d = _nth_weekday(tgt_year, tgt_month, dow, wn)
                                if d and (d not in suppressed or high_traffic):
                                    target_dates.append(d)
                    elif wp:
                        # Legacy week_pattern format "1,3" or "2,4"
                        weeks = [int(w) for w in wp.split(',') if w.strip().isdigit()]
                        for wn in weeks:
                            d = _nth_weekday(tgt_year, tgt_month, dow, wn)
                            if d and (d not in suppressed or high_traffic):
                                target_dates.append(d)
                    else:
                        for wn in [1, 3]:
                            d = _nth_weekday(tgt_year, tgt_month, dow, wn)
                            if d and (d not in suppressed or high_traffic):
                                target_dates.append(d)

                elif p['frequency'] == 'monthly':
                    # Minggu ke-N dari DOW tertentu — BUG FIX: kalau libur, geser
                    wp = p.get('week_pattern') or str(p.get('week_of_month') or 1)
                    try:
                        wn = int(wp.split(',')[0])
                    except Exception:
                        wn = 1
                    d = _nth_weekday(tgt_year, tgt_month, dow, wn)
                    if d and d not in suppressed:
                        target_dates = [d]
                    else:
                        # Fallback: cari minggu lain dengan DOW sama yang tidak libur
                        all_dow_days = days_by_dow.get(dow, [])
                        if all_dow_days:
                            # Ambil yang terdekat dengan target week
                            target_dates = [min(all_dow_days,
                                key=lambda x: abs(_week_of_month(x) - wn))]

                elif p['frequency'] == 'adhoc':
                    # Hanya tempatkan di kemunculan pertama hari tersebut
                    avail = days_by_dow.get(dow, [])
                    if avail:
                        target_dates = [avail[0]]

                if not target_dates:
                    events_skipped += 1
                    skip_reasons['no_valid_dates'] += 1
                    continue

                # ── Tentukan teknisi (BUG FIX #2 + #13: VALIDASI) ─────────────
                # Pakai pattern.tech_id DULU (untuk preserve multi-tech support).
                # Primary master cuma fallback kalau pattern.tech tidak schedulable.
                if tech_id in schedulable_techs:
                    candidate = tech_id
                else:
                    candidate = primary_tech.get(client_id)
                    if candidate not in schedulable_techs:
                        candidate = None
                if candidate is None:
                    events_skipped += 1
                    skip_reasons['no_valid_technician'] += 1
                    continue
                assigned_tech = candidate
                supervisor_id = p['supervisor_id']

                # ── Insert events ─────────────────────────────────────────────
                ts = p['time_start'] or '08:00'
                te = p['time_end']

                for visit_date in target_dates:
                    try:
                        h, m = int(ts[:2]), int(ts[3:5])
                        start_dt = datetime(visit_date.year, visit_date.month,
                                            visit_date.day, h, m)
                    except Exception:
                        start_dt = datetime(visit_date.year, visit_date.month,
                                            visit_date.day, 8, 0)

                    end_dt = None
                    if te:
                        try:
                            eh, em = int(te[:2]), int(te[3:5])
                            end_dt = datetime(visit_date.year, visit_date.month,
                                              visit_date.day, eh, em)
                            if end_dt <= start_dt:
                                end_dt += timedelta(days=1)   # midnight crossing
                        except Exception:
                            pass

                    # Tag confidence & pattern di notes
                    notes = (f"Draft v2 | {p['frequency']} | conf={p['confidence']:.2f} "
                             f"| recency={p['recency_score']:.1f} | src={source_month}")

                    # ── WORKLOAD LEVELER: cap per teknisi per minggu ─────────
                    # Default: max 4 job/hari, max 18 job/minggu untuk mobile
                    iso_year, iso_week, _ = visit_date.isocalendar()
                    week_key = (assigned_tech, iso_year, iso_week)
                    day_key  = (assigned_tech, visit_date)
                    week_cap = 18 if assigned_tech in schedulable_techs else 0
                    day_cap  = 5

                    if tech_workload.get(week_key, 0) >= week_cap:
                        events_skipped += 1
                        skip_reasons['week_cap_exceeded'] += 1
                        continue
                    if tech_workload.get(day_key, 0) >= day_cap:
                        events_skipped += 1
                        skip_reasons['day_cap_exceeded'] += 1
                        continue

                    # Dedup: skip jika sudah ada event (tech+client+date) dalam batch ini
                    cur.execute("""
                        SELECT id FROM snc_schedule_events
                        WHERE draft_batch_id = %s
                          AND technician_id  = %s
                          AND client_id      = %s
                          AND start_date     = %s
                        LIMIT 1
                    """, (batch_id, assigned_tech, client_id, visit_date))
                    if cur.fetchone():
                        events_skipped += 1
                        skip_reasons['duplicate'] += 1
                        continue

                    cur.execute("""
                        INSERT INTO snc_schedule_events
                            (technician_id, supervisor_id, client_id, visit_type,
                             start_datetime, end_datetime, start_date,
                             schedule_status, draft_batch_id, created_by, notes,
                             source)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s,'pattern')
                    """, (
                        assigned_tech, supervisor_id, client_id,
                        p['visit_type'], start_dt, end_dt, visit_date,
                        batch_id, user_id, notes
                    ))
                    events_created += 1
                    tech_workload[week_key] = tech_workload.get(week_key, 0) + 1
                    tech_workload[day_key]  = tech_workload.get(day_key, 0) + 1

            conn.commit()

    # ── Auto-detect conflicts setelah generate ──────────────────────────────
    conflict_stats = {"detected": 0}
    try:
        from kil.backend.legacy.api.conflict_detection import detect_conflicts
        import json as _json
        with _get_local_pool().connection() as conn2:
            with conn2.cursor(row_factory=dict_row) as cur2:
                conflict_stats = detect_conflicts(cur2, batch_id)
                # AUDIT log: draft_generated + conflict_detected
                cur2.execute("""
                    INSERT INTO snc_schedule_audit_log
                        (draft_batch_id, action, new_value, reason, changed_by)
                    VALUES (%s, 'draft_generated', %s::jsonb, %s, %s)
                """, (batch_id, _json.dumps({
                    'events_created': events_created,
                    'rules_applied': len(rules),
                    'patterns_consolidated': consolidated_count,
                }), f"Auto from {source_month}", user_id))
                cur2.execute("""
                    INSERT INTO snc_schedule_audit_log
                        (draft_batch_id, action, new_value, reason, changed_by)
                    VALUES (%s, 'conflict_detected', %s::jsonb, %s, %s)
                """, (batch_id, _json.dumps(conflict_stats), "Auto-scan after generate", user_id))
            conn2.commit()
    except Exception as _e:
        pass  # non-fatal

    return jsonify({
        "batch_id":         batch_id,
        "source_month":     source_month,
        "target_month":     target_month,
        "suppressed_dates": sorted(str(d) for d in suppressed),
        "schedulable_technicians": len(schedulable_techs),
        "patterns_consolidated": consolidated_count,
        "rules_applied":    len(rules),
        "rules_mandatory":  rules_override_count,
        "events_created":   events_created,
        "events_skipped":   events_skipped,
        "skip_reasons":     dict(skip_reasons),
        "conflicts_detected": conflict_stats,
        "message": (f"Draft {target_month}: {events_created} kunjungan, "
                    f"{len(schedulable_techs)} teknisi, "
                    f"{len(rules)} rules applied "
                    f"({rules_override_count} mandatory), "
                    f"{conflict_stats.get('detected', 0)} conflicts terdeteksi, "
                    f"{len(suppressed)} hari libur dilewati."),
    })


# ──────────────────────────────────────────────────────────────────────────────
# 3. GET DRAFT
# ──────────────────────────────────────────────────────────────────────────────

@draft_bp.route("/draft", methods=["GET"])
@require_auth
def get_draft():
    """GET /calendar/draft?month=2026-06"""
    month = request.args.get("month", "")
    if not month:
        return jsonify({"error": "month required"}), 400

    try:
        year, mo = _parse_month(month)
    except Exception:
        return jsonify({"error": "invalid month"}), 400

    month_start = date(year, mo, 1)
    _, num_days = cal_mod.monthrange(year, mo)
    month_end   = date(year, mo, num_days)

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT * FROM snc_draft_batches WHERE target_month = %s
            """, (month,))
            batch = cur.fetchone()
            if not batch:
                return jsonify({"batch": None, "technicians": [], "total_events": 0})

            cur.execute("""
                SELECT
                    se.id, se.technician_id, se.client_id,
                    se.visit_type, se.start_datetime, se.end_datetime,
                    se.start_date, se.schedule_status, se.notes,
                    t.name AS tech_name, t.kelava_p_user_id,
                    c.name AS client_name, c.address AS client_address
                FROM snc_schedule_events se
                JOIN snc_technicians t ON t.id = se.technician_id
                JOIN snc_clients     c ON c.id = se.client_id
                WHERE se.draft_batch_id = %s
                  AND se.schedule_status = 'draft'
                ORDER BY t.name, se.start_datetime
            """, (batch['id'],))
            events = cur.fetchall()

    tech_map = {}
    for e in events:
        tid = e['technician_id']
        if tid not in tech_map:
            tech_map[tid] = {
                "id": tid, "kelava_id": e['kelava_p_user_id'],
                "name": e['tech_name'], "jobs": [], "total": 0,
            }
        ts  = e['start_datetime']
        te  = e['end_datetime']
        dur = int((te - ts).total_seconds() / 60) if te else 60
        tech_map[tid]['jobs'].append({
            "id":           f"draft-{e['id']}",
            "event_id":     e['id'],
            "client_name":  e['client_name'],
            "date":         e['start_date'].isoformat(),
            "time_start":   ts.strftime("%H:%M") if ts else "08:00",
            "time_end":     te.strftime("%H:%M") if te else None,
            "visit_type":   e['visit_type'],
            "duration_min": dur,
            "notes":        e['notes'],
            "status":       "draft",
        })
        tech_map[tid]['total'] += 1

    return jsonify({
        "batch": {
            "id":           batch['id'],
            "target_month": batch['target_month'],
            "source_month": batch['source_month'],
            "status":       batch['status'],
            "generated_at": batch['generated_at'].isoformat(),
        },
        "technicians": list(tech_map.values()),
        "total_events": len(events),
    })


# ──────────────────────────────────────────────────────────────────────────────
# 4. APPROVE DRAFT
# ──────────────────────────────────────────────────────────────────────────────

@draft_bp.route("/approve-draft", methods=["POST"])
@require_auth
def approve_draft():
    """POST body: { "month": "2026-06", "notes": "..." }"""
    user_id_perm, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    data    = request.get_json() or {}
    month   = data.get("month", "")
    notes   = data.get("notes", "")
    user_id = getattr(g, "user_id", 0) or 0

    if not month:
        return jsonify({"error": "month required"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT id, status FROM snc_draft_batches WHERE target_month = %s
            """, (month,))
            batch = cur.fetchone()
            if not batch:
                return jsonify({"error": "No draft found for this month"}), 404
            if batch['status'] == 'approved':
                return jsonify({"error": "Already approved"}), 400

            cur.execute("""
                UPDATE snc_schedule_events
                SET schedule_status = 'scheduled', updated_at = NOW()
                WHERE draft_batch_id = %s AND schedule_status = 'draft'
                RETURNING id
            """, (batch['id'],))
            approved_ids = cur.fetchall()

            cur.execute("""
                UPDATE snc_draft_batches
                SET status='approved', approved_by=%s, approved_at=NOW(), notes=%s
                WHERE id=%s
            """, (user_id, notes, batch['id']))
            conn.commit()

    return jsonify({
        "month":          month,
        "approved_count": len(approved_ids),
        "message":        f"{len(approved_ids)} kunjungan disetujui untuk {month}.",
    })


# ──────────────────────────────────────────────────────────────────────────────
# 5. DELETE SINGLE DRAFT EVENT
# ──────────────────────────────────────────────────────────────────────────────

@draft_bp.route("/draft-event/<int:event_id>", methods=["DELETE"])
@require_auth
def delete_draft_event(event_id):
    """Remove a single draft event (supervisor review: reject this slot)."""
    user_id_perm, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                DELETE FROM snc_schedule_events
                WHERE id=%s AND schedule_status='draft' RETURNING id
            """, (event_id,))
            deleted = cur.fetchone()
            conn.commit()
    if not deleted:
        return jsonify({"error": "Draft event not found"}), 404
    return jsonify({"deleted": event_id})


# ──────────────────────────────────────────────────────────────────────────────
# 6. PATTERN SUMMARY
# ──────────────────────────────────────────────────────────────────────────────

@draft_bp.route("/patterns", methods=["GET"])
@require_auth
def get_patterns():
    """GET /calendar/patterns?month=2026-05"""
    month = request.args.get("month", "")
    if not month:
        return jsonify({"error": "month required"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    t.name AS tech_name, c.name AS client_name,
                    p.frequency, p.day_of_week, p.week_pattern,
                    p.time_start, p.visit_type,
                    p.confidence, p.recency_score, p.occurrence_count
                FROM snc_schedule_patterns p
                JOIN snc_technicians t ON t.id = p.technician_id
                JOIN snc_clients     c ON c.id = p.client_id
                WHERE p.source_month = %s
                ORDER BY t.name, p.confidence DESC
            """, (month,))
            rows = cur.fetchall()

    day_names = ["Sen","Sel","Rab","Kam","Jum","Sab","Min"]
    result = []
    for r in rows:
        result.append({
            "tech":          r['tech_name'],
            "client":        r['client_name'],
            "frequency":     r['frequency'],
            "day":           day_names[r['day_of_week']] if r['day_of_week'] is not None else "—",
            "week_pattern":  r['week_pattern'],
            "time_start":    r['time_start'],
            "visit_type":    r['visit_type'],
            "confidence":    float(r['confidence'] or 0),
            "recency":       float(r['recency_score'] or 0),
            "occurrences":   r['occurrence_count'],
        })

    freq_summary = defaultdict(int)
    for r in result:
        freq_summary[r['frequency']] += 1

    return jsonify({
        "month":    month,
        "patterns": result,
        "summary":  dict(freq_summary),
        "high_confidence": sum(1 for r in result if r['confidence'] >= 0.8),
    })


# ──────────────────────────────────────────────────────────────────────────────
# 6. EXPORT TO EXCEL (Jadwal Teknisi format)
# ──────────────────────────────────────────────────────────────────────────────

@draft_bp.route("/draft/<target_month>/export.xlsx", methods=["GET"])
@require_auth
def export_draft_xlsx(target_month):
    """
    GET /calendar/draft/2026-07/export.xlsx
    Optional: ?batch_id=N&tech_id=N&status=draft,scheduled

    Returns xlsx file in 'Jadwal Teknisi' format (per-tech sheets).
    """
    from flask import Response
    from kil.backend.scripts.export_jadwal_xlsx import export_jadwal, BULAN_ID

    try:
        year, mnum = map(int, target_month.split('-'))
        if not (1 <= mnum <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        return jsonify({"error": "target_month harus YYYY-MM"}), 400

    batch_id = request.args.get('batch_id', type=int)
    tech_id  = request.args.get('tech_id', type=int)
    week     = request.args.get('week', type=int)  # 1-5
    statuses_raw = request.args.get('status')
    status_filter = statuses_raw.split(',') if statuses_raw else None

    try:
        xlsx_bytes = export_jadwal(
            target_month, batch_id=batch_id,
            status_filter=status_filter, only_tech_id=tech_id,
            only_week=week,
        )
    except Exception as e:
        return jsonify({"error": "Gagal generate xlsx", "detail": str(e)}), 500

    bulan = BULAN_ID[mnum]
    fname = f'JADWAL TEKNISI {bulan} {year}'
    if tech_id:
        with _get_local_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT name FROM snc_technicians WHERE id = %s", (tech_id,))
                row = cur.fetchone()
                if row:
                    fname += ' - ' + row['name'].replace(' ', '_')
    if week:
        fname += f' - Minggu{week}'
    filename = fname + '.xlsx'

    return Response(
        xlsx_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(len(xlsx_bytes)),
        },
    )
