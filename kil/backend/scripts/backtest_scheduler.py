"""
Backtest Scheduler Accuracy
============================
Generate prediksi untuk bulan yang sudah punya data aktual, lalu compare.

Metode:
  1. Pakai data Feb-Apr 2026 → detect patterns
  2. Generate "draft Mei 2026"
  3. Compare vs schedule_events aktual Mei 2026 (596 events)

Metrik:
  - Coverage: berapa % event aktual yang berhasil di-predict
  - Precision: berapa % prediksi yang benar muncul
  - Tech accuracy: berapa % prediksi pakai teknisi yang benar
  - Date drift: rata-rata selisih hari prediksi vs aktual
  - Customer match rate

Usage:
  python3 kil/backend/scripts/backtest_scheduler.py
"""

import sys, os
from datetime import date, datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

import psycopg
from psycopg.rows import dict_row

LOCAL_PG = dict(
    host='127.0.0.1', port=5432,
    dbname='kil_enterprise', user='kil_ent', password='KilEnt2026!',
    row_factory=dict_row,
)


def fetch_actuals(cur, month_start: date, month_end: date) -> list:
    """Fetch real schedule_events for the month (status=scheduled/completed, no draft)."""
    cur.execute("""
        SELECT se.technician_id, t.name AS tech_name,
               se.client_id, c.name AS client_name,
               se.start_date, se.visit_type,
               TO_CHAR(se.start_datetime, 'HH24:MI') AS time_start
        FROM snc_schedule_events se
        JOIN snc_technicians t ON t.id = se.technician_id
        JOIN snc_clients     c ON c.id = se.client_id
        WHERE se.start_date BETWEEN %s AND %s
          AND se.schedule_status IN ('scheduled','completed')
        ORDER BY se.start_date
    """, (month_start, month_end))
    return cur.fetchall()


def fetch_predictions(cur, batch_id: int) -> list:
    """Fetch draft events from a batch."""
    cur.execute("""
        SELECT se.technician_id, t.name AS tech_name,
               se.client_id, c.name AS client_name,
               se.start_date, se.visit_type,
               TO_CHAR(se.start_datetime, 'HH24:MI') AS time_start
        FROM snc_schedule_events se
        JOIN snc_technicians t ON t.id = se.technician_id
        JOIN snc_clients     c ON c.id = se.client_id
        WHERE se.draft_batch_id = %s
          AND se.schedule_status = 'draft'
        ORDER BY se.start_date
    """, (batch_id,))
    return cur.fetchall()


def compute_metrics(actuals: list, predictions: list) -> dict:
    """
    Compute precision/recall/etc.
    Match key tiers (lebih ketat = lebih bagus):
      1. EXACT  : tech + client + date + time
      2. STRONG : tech + client + date
      3. CUSTOMER+DATE : client + date (sembarang tech)
      4. CUSTOMER+WEEK : client + same iso-week
      5. CUSTOMER : client appears in both
    """
    # Index actuals
    act_by_key = defaultdict(list)
    for a in actuals:
        act_by_key[(a['client_id'], a['start_date'])].append(a)
    act_by_client = defaultdict(list)
    for a in actuals:
        act_by_client[a['client_id']].append(a)
    act_by_week = defaultdict(list)
    for a in actuals:
        wk = a['start_date'].isocalendar()[1]
        act_by_week[(a['client_id'], wk)].append(a)

    actual_keys = {(a['technician_id'], a['client_id'], a['start_date']) for a in actuals}
    pred_keys   = {(p['technician_id'], p['client_id'], p['start_date']) for p in predictions}

    # Per-prediction match tier
    exact = strong = cust_date = cust_week = cust_only = miss = 0
    pred_tech_correct = 0
    pred_tech_wrong   = 0
    date_drifts = []

    for p in predictions:
        # Tier 1: exact (tech+client+date+time)
        matched_exact = any(
            a['technician_id'] == p['technician_id']
            and a['time_start'] == p['time_start']
            for a in act_by_key.get((p['client_id'], p['start_date']), [])
        )
        if matched_exact:
            exact += 1
            pred_tech_correct += 1
            continue

        # Tier 2: strong (tech+client+date)
        if (p['technician_id'], p['client_id'], p['start_date']) in actual_keys:
            strong += 1
            pred_tech_correct += 1
            continue

        # Tier 3: cust+date (sembarang tech)
        same_date = act_by_key.get((p['client_id'], p['start_date']), [])
        if same_date:
            cust_date += 1
            pred_tech_wrong += 1
            continue

        # Tier 4: cust+week (geser dalam minggu yang sama)
        wk = p['start_date'].isocalendar()[1]
        same_week = act_by_week.get((p['client_id'], wk), [])
        if same_week:
            cust_week += 1
            pred_tech_wrong += 1
            actual_d = same_week[0]['start_date']
            date_drifts.append((p['start_date'] - actual_d).days)
            continue

        # Tier 5: customer appears in actuals
        if act_by_client.get(p['client_id']):
            cust_only += 1
            pred_tech_wrong += 1
            actual_dates = [a['start_date'] for a in act_by_client[p['client_id']]]
            closest = min(actual_dates, key=lambda d: abs((d - p['start_date']).days))
            date_drifts.append((p['start_date'] - closest).days)
            continue

        miss += 1   # customer tidak ada di aktual = false positive penuh

    # Coverage: actuals yang ke-cover oleh predictions
    pred_by_client_date = defaultdict(list)
    for p in predictions:
        pred_by_client_date[(p['client_id'], p['start_date'])].append(p)
    pred_by_client = defaultdict(list)
    for p in predictions:
        pred_by_client[p['client_id']].append(p)
    pred_by_week = defaultdict(list)
    for p in predictions:
        wk = p['start_date'].isocalendar()[1]
        pred_by_week[(p['client_id'], wk)].append(p)

    actual_covered_exact = actual_covered_week = actual_uncovered = 0
    for a in actuals:
        if (a['client_id'], a['start_date']) in pred_by_client_date:
            actual_covered_exact += 1
        elif (a['client_id'], a['start_date'].isocalendar()[1]) in pred_by_week:
            actual_covered_week += 1
        else:
            actual_uncovered += 1

    total_pred = len(predictions)
    total_act  = len(actuals)
    return {
        'total_predictions': total_pred,
        'total_actuals':     total_act,
        # Precision tiers
        'exact':     exact,
        'strong':    strong,
        'cust_date': cust_date,
        'cust_week': cust_week,
        'cust_only': cust_only,
        'false_pos': miss,
        # Coverage
        'actual_covered_exact_date': actual_covered_exact,
        'actual_covered_same_week':  actual_covered_week,
        'actual_uncovered':          actual_uncovered,
        # Tech accuracy
        'tech_correct': pred_tech_correct,
        'tech_wrong':   pred_tech_wrong,
        # Date drift
        'avg_date_drift_days': round(sum(abs(d) for d in date_drifts)/len(date_drifts), 1) if date_drifts else 0,
        # Computed
        'precision_strong':  round((exact + strong) / total_pred * 100, 1) if total_pred else 0,
        'precision_loose':   round((exact + strong + cust_date + cust_week) / total_pred * 100, 1) if total_pred else 0,
        'recall_exact_date': round(actual_covered_exact / total_act * 100, 1) if total_act else 0,
        'recall_same_week':  round((actual_covered_exact + actual_covered_week) / total_act * 100, 1) if total_act else 0,
        'tech_accuracy':     round(pred_tech_correct / (pred_tech_correct + pred_tech_wrong) * 100, 1) if (pred_tech_correct + pred_tech_wrong) else 0,
    }


def print_report(m: dict, source: str, target: str):
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║       BACKTEST: source={source} → predict {target}              ║
╠══════════════════════════════════════════════════════════════════╣
║ VOLUME                                                            ║
║   Total prediksi  : {m['total_predictions']:6d}                                    ║
║   Total aktual    : {m['total_actuals']:6d}                                    ║
╠══════════════════════════════════════════════════════════════════╣
║ PRECISION (kualitas tiap prediksi)                                ║
║   EXACT (tech+client+date+time) : {m['exact']:4d} ({m['exact']/max(m['total_predictions'],1)*100:5.1f}%)         ║
║   STRONG (tech+client+date)     : {m['strong']:4d} ({m['strong']/max(m['total_predictions'],1)*100:5.1f}%)         ║
║   cust+date (tech beda)         : {m['cust_date']:4d} ({m['cust_date']/max(m['total_predictions'],1)*100:5.1f}%)         ║
║   cust+week (geser ≤6 hari)     : {m['cust_week']:4d} ({m['cust_week']/max(m['total_predictions'],1)*100:5.1f}%)         ║
║   cust only (tanggal jauh)      : {m['cust_only']:4d} ({m['cust_only']/max(m['total_predictions'],1)*100:5.1f}%)         ║
║   FALSE POSITIVE (no match)     : {m['false_pos']:4d} ({m['false_pos']/max(m['total_predictions'],1)*100:5.1f}%)         ║
║                                                                   ║
║   Precision STRONG (tech+date)  : {m['precision_strong']:5.1f}%                       ║
║   Precision LOOSE (cust+week)   : {m['precision_loose']:5.1f}%                       ║
╠══════════════════════════════════════════════════════════════════╣
║ RECALL (% aktual yang ke-cover)                                   ║
║   Covered exact date            : {m['actual_covered_exact_date']:4d} ({m['recall_exact_date']:5.1f}%)             ║
║   Covered same week             : {m['actual_covered_same_week']:4d}                          ║
║   UNCOVERED                     : {m['actual_uncovered']:4d}                          ║
║                                                                   ║
║   Recall exact date             : {m['recall_exact_date']:5.1f}%                       ║
║   Recall same week              : {m['recall_same_week']:5.1f}%                       ║
╠══════════════════════════════════════════════════════════════════╣
║ TECH ASSIGNMENT                                                   ║
║   Tech correct                  : {m['tech_correct']:4d}                          ║
║   Tech wrong                    : {m['tech_wrong']:4d}                          ║
║   Tech accuracy                 : {m['tech_accuracy']:5.1f}%                       ║
║                                                                   ║
║   Avg date drift (hari)         : {m['avg_date_drift_days']:5.1f}                        ║
╚══════════════════════════════════════════════════════════════════╝
""")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--month', default='2026-06', help='Target month (default 2026-06)')
    args = parser.parse_args()

    target_month = args.month
    year, month = int(target_month[:4]), int(target_month[5:7])
    import calendar as cal_mod
    _, num_days = cal_mod.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end   = date(year, month, num_days)

    conn = psycopg.connect(**LOCAL_PG)
    cur  = conn.cursor(row_factory=dict_row)

    # Find latest draft batch for target_month
    cur.execute("""
        SELECT id FROM snc_draft_batches
        WHERE target_month = %s ORDER BY id DESC LIMIT 1
    """, (target_month,))
    row = cur.fetchone()
    if not row:
        print(f"ERROR: Belum ada draft batch untuk {target_month}.")
        sys.exit(1)
    batch_id = row['id']

    actuals     = fetch_actuals(cur, month_start, month_end)
    predictions = fetch_predictions(cur, batch_id)

    metrics = compute_metrics(actuals, predictions)
    print_report(metrics, f'pola {target_month}', target_month)

    # Per-tech breakdown
    print("BREAKDOWN PER TEKNISI:")
    by_tech = defaultdict(lambda: {'pred': 0, 'act': 0})
    for p in predictions: by_tech[p['tech_name']]['pred'] += 1
    for a in actuals:     by_tech[a['tech_name']]['act']  += 1
    for tech in sorted(by_tech):
        d = by_tech[tech]
        diff = d['pred'] - d['act']
        flag = '✓' if abs(diff) <= 3 else ('⚠' if abs(diff) <= 8 else '✗')
        print(f"   {flag} {tech[:25]:25s} | pred={d['pred']:3d} | act={d['act']:3d} | diff={diff:+d}")

    conn.close()


if __name__ == '__main__':
    main()
