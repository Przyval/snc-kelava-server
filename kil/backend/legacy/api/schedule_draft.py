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
from collections import defaultdict

from flask import Blueprint, jsonify, request, g
from core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

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

def _consolidate_patterns_per_client(patterns: list, schedulable_techs: set) -> list:
    """
    BUG FIX #9: Dedup multi-pattern per (client, day_of_week).
    Pertahankan multi-DOW pattern (client bisa visit beberapa hari/minggu).
    Per (client, dow), pilih winner: score = conf × recency × schedulable_bonus.
    Schedulable tech dapat bonus 2x supaya tidak dipotong oleh tech inactive.
    """
    by_key = {}
    for p in patterns:
        key = (p['client_id'], p['day_of_week'])
        sched_bonus = 2.0 if p['technician_id'] in schedulable_techs else 1.0
        score = float(p.get('confidence', 0)) * float(p.get('recency_score', 0)) * sched_bonus
        if key not in by_key or score > by_key[key][0]:
            by_key[key] = (score, p)
    return [p for _, p in by_key.values()]


def _load_active_clients_smart(cur, source_year: int, source_month: int) -> set:
    """
    BUG FIX #10: Active client filter dengan override.
    Customer "cancelled" di Accurate tetap di-include jika ada visit dalam
    source_month (artinya benar-benar masih aktif meski belum ada invoice).
    Returns None kalau master kosong (no filter).
    """
    cur.execute("""
        SELECT snc_client_id FROM snc_customer_master
        WHERE customer_status IN ('active') AND snc_client_id IS NOT NULL
    """)
    active_set = {r['snc_client_id'] for r in cur.fetchall()}
    if not active_set:
        return None

    # Override: customer cancelled/paused yang ada visit di source_month
    import calendar as cal_mod
    _, n = cal_mod.monthrange(source_year, source_month)
    cur.execute("""
        SELECT DISTINCT se.client_id
        FROM snc_schedule_events se
        JOIN snc_customer_master cm ON cm.snc_client_id = se.client_id
        WHERE cm.customer_status IN ('cancelled', 'paused')
          AND se.schedule_status IN ('scheduled', 'completed')
          AND se.start_date BETWEEN %s AND %s
    """, (date(source_year, source_month, 1), date(source_year, source_month, n)))
    override = {r['client_id'] for r in cur.fetchall()}
    return active_set | override


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
                    se.start_date
                FROM snc_schedule_events se
                WHERE se.start_date BETWEEN %s AND %s
                  AND se.schedule_status IN ('scheduled','completed')
                ORDER BY se.technician_id, se.client_id, se.start_date
            """, (start_date, end_date))
            rows = cur.fetchall()

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

                # Hanya hitung visits dalam source_month
                src_visits = [v for v in visit_infos
                              if v['date'].year == year and v['date'].month == month]
                src_count  = len(src_visits)
                src_woms   = sorted({v['wom'] for v in src_visits})

                # ── Klasifikasi frekuensi (semua untuk DOW ini saja) ──────────
                # Karena sudah di-group by DOW, dow_purity selalu 1.0
                if src_count >= 3:
                    # 3+ visit di DOW yang sama dalam 1 bulan = weekly
                    frequency    = 'weekly'
                    week_pattern = None
                    confidence   = min(1.0, round(weighted_count / (4 * 3.0), 2))

                elif src_count == 2 and len(src_woms) == 2:
                    # 2 visit di 2 minggu berbeda = biweekly
                    frequency    = 'biweekly'
                    week_pattern = ','.join(str(w) for w in src_woms)
                    confidence   = round(min(1.0, weighted_count / (2 * 3.0)), 2)

                elif src_count == 1:
                    # 1 visit di source month = monthly (week-of-month specific)
                    frequency    = 'monthly'
                    week_pattern = str(src_woms[0]) if src_woms else None
                    confidence   = round(min(0.80, weighted_count / 3.0), 2)

                elif src_count == 0 and count >= 2:
                    # Hilang di source, ada di bulan lalu = stale, skip
                    patterns_skipped += 1
                    continue

                else:
                    # 2 visit di minggu yang sama → adhoc dengan conf rendah
                    frequency    = 'adhoc'
                    week_pattern = None
                    confidence   = round(min(0.50, weighted_count / 6.0), 2)

                freq_tally[frequency] += 1

                # Time & visit type
                ref_visits = src_visits if src_visits else visit_infos
                ts_list = [v['time_start'] for v in ref_visits if v['time_start']]
                te_list = [v['time_end']   for v in ref_visits if v['time_end']]
                vt_list = [v['visit_type'] for v in ref_visits if v['visit_type']]
                modal_ts = max(set(ts_list), key=ts_list.count) if ts_list else None
                modal_te = max(set(te_list), key=te_list.count) if te_list else None
                modal_vt = max(set(vt_list), key=vt_list.count) if vt_list else None

                recency_score = 1.0 if src_count > 0 else 0.4

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

            # ── Teknisi yang valid untuk di-schedule ──────────────────────────
            target_month_start = date(tgt_year, tgt_month, 1)
            schedulable_techs  = _load_schedulable_technicians(cur, target_month_start)

            # ── Primary technician per client (sudah pre-filtered ke schedulable)
            primary_tech = _load_primary_technician(cur, schedulable_techs)

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

            events_created  = 0
            events_skipped  = 0
            skip_reasons    = defaultdict(int)
            tech_workload   = defaultdict(int)   # untuk leveling cap

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

                if p['frequency'] == 'weekly':
                    # Semua Senin (atau hari apapun) dalam bulan, kecuali yang suppressed
                    target_dates = days_by_dow.get(dow, [])

                elif p['frequency'] == 'biweekly':
                    # Pakai week_pattern yang terdeteksi ('1,3' atau '2,4', dll.)
                    wp = p.get('week_pattern') or ''
                    if wp:
                        weeks = [int(w) for w in wp.split(',') if w.strip().isdigit()]
                    else:
                        weeks = [1, 3]   # fallback
                    for wn in weeks:
                        d = _nth_weekday(tgt_year, tgt_month, dow, wn)
                        if d and d not in suppressed:
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

                # ── Tentukan teknisi (BUG FIX #2: VALIDASI) ───────────────────
                # Prioritas: primary master → pattern tech → skip
                # SEMUA harus ada di schedulable_techs
                candidate = primary_tech.get(client_id, tech_id)
                if candidate not in schedulable_techs:
                    candidate = tech_id if tech_id in schedulable_techs else None
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
                             schedule_status, draft_batch_id, created_by, notes)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s)
                    """, (
                        assigned_tech, supervisor_id, client_id,
                        p['visit_type'], start_dt, end_dt, visit_date,
                        batch_id, user_id, notes
                    ))
                    events_created += 1
                    tech_workload[week_key] = tech_workload.get(week_key, 0) + 1
                    tech_workload[day_key]  = tech_workload.get(day_key, 0) + 1

            conn.commit()

    return jsonify({
        "batch_id":         batch_id,
        "source_month":     source_month,
        "target_month":     target_month,
        "suppressed_dates": sorted(str(d) for d in suppressed),
        "schedulable_technicians": len(schedulable_techs),
        "patterns_consolidated": consolidated_count,
        "events_created":   events_created,
        "events_skipped":   events_skipped,
        "skip_reasons":     dict(skip_reasons),
        "message": (f"Draft {target_month}: {events_created} kunjungan, "
                    f"{len(schedulable_techs)} teknisi, "
                    f"{consolidated_count} pattern overlap di-dedup, "
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
