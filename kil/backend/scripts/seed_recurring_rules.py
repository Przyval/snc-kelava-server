"""
Seed Sample Recurring Rules
============================
Auto-generate recurring rules from existing patterns for top 30 customers.
Supervisor can then edit/verify via UI.

Strategi:
- Ambil pattern dengan conf >= 0.9, occurrence_count >= 8
- Pilih pattern terbaik per customer (1 customer = 1 rule)
- Multi-DOW customers: gabung weekdays array
- Set is_mandatory=false (supervisor harus eksplisit accept)

Usage:
  python3 kil/backend/scripts/seed_recurring_rules.py [--dry-run] [--top N]
"""

import sys, os, argparse
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

import psycopg
from psycopg.rows import dict_row
from collections import defaultdict

LOCAL_PG = dict(
    host='127.0.0.1', port=5432,
    dbname='kil_enterprise', user='kil_ent', password='KilEnt2026!',
    row_factory=dict_row,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--top', type=int, default=30, help='Top N customers by visit count')
    parser.add_argument('--source-month', default='2026-05')
    args = parser.parse_args()

    conn = psycopg.connect(**LOCAL_PG)
    cur = conn.cursor(row_factory=dict_row)

    # ── Step 1: Load top customers by total Mei + Apr visits ────────────────
    cur.execute("""
        SELECT c.id, c.name, COUNT(*) as visits
        FROM snc_schedule_events se
        JOIN snc_clients c ON c.id=se.client_id
        WHERE se.start_date BETWEEN '2026-04-01' AND '2026-05-31'
          AND se.schedule_status='scheduled'
        GROUP BY c.id, c.name
        ORDER BY visits DESC
        LIMIT %s
    """, (args.top,))
    top_customers = cur.fetchall()
    print(f"Top {len(top_customers)} customers by Apr-Mei visit count:")
    for c in top_customers[:10]:
        print(f"   {c['visits']:3d} visits | {c['name']}")
    print()

    # ── Step 2: Untuk setiap customer, ambil patterns ───────────────────────
    seeded = 0
    skipped = 0

    for cust in top_customers:
        cid = cust['id']

        cur.execute("""
            SELECT p.*, t.name as tech_name, t.is_active as tech_active,
                   t.employee_type, t.contract_expiry
            FROM snc_schedule_patterns p
            JOIN snc_technicians t ON t.id=p.technician_id
            WHERE p.client_id=%s AND p.source_month=%s
              AND p.confidence >= 0.85
              AND p.recency_score >= 0.8
              AND p.occurrence_count >= 6
              AND t.is_active = true
              AND t.employee_type IN ('mobile', 'support')
            ORDER BY p.confidence DESC, p.occurrence_count DESC
        """, (cid, args.source_month))
        patterns = cur.fetchall()

        if not patterns:
            skipped += 1
            continue

        # Pick best frequency: weekly > biweekly > monthly
        freq_priority = {'weekly': 3, 'biweekly': 2, 'monthly': 1, 'adhoc': 0}
        best_pattern = max(patterns, key=lambda p: (freq_priority.get(p['frequency'], 0),
                                                     p['occurrence_count'], p['confidence']))

        frequency = best_pattern['frequency']
        primary_tech = best_pattern['technician_id']

        # Collect weekdays — all DOWs dengan pattern conf >= 0.85 untuk tech ini
        weekdays = sorted({p['day_of_week'] for p in patterns
                          if p['technician_id'] == primary_tech
                          and float(p['confidence']) >= 0.85})

        # Backup tech: pattern lain di DOW yang sama
        same_dow_patterns = [p for p in patterns if p['day_of_week'] == best_pattern['day_of_week']
                            and p['technician_id'] != primary_tech]
        backup_1 = same_dow_patterns[0]['technician_id'] if same_dow_patterns else None
        backup_2 = same_dow_patterns[1]['technician_id'] if len(same_dow_patterns) > 1 else None

        # Week pattern: from best_pattern
        week_pattern = best_pattern['week_pattern']
        if frequency == 'weekly':
            week_pattern = None  # weekly = all weeks

        # Time
        time_start = best_pattern['time_start']
        time_end = best_pattern['time_end']
        visit_type = best_pattern['visit_type']

        # Notes (auto-generated context)
        notes = (f"Auto-seed from {args.source_month} pattern | "
                 f"{best_pattern['occurrence_count']} visits | "
                 f"conf={best_pattern['confidence']:.2f}")

        if args.dry_run:
            days = ['Sen','Sel','Rab','Kam','Jum','Sab','Min']
            wd_str = '+'.join(days[d] for d in weekdays)
            print(f"   WOULD SEED: {cust['name'][:25]:25s} | {frequency:8s} {wd_str:15s} {time_start} | "
                  f"primary={best_pattern['tech_name']}")
        else:
            try:
                cur.execute("""
                    INSERT INTO snc_recurring_rules
                        (client_id, primary_tech_id, backup_tech_1_id, backup_tech_2_id,
                         frequency, weekdays, week_pattern, time_start, time_end,
                         visit_type, is_mandatory, suppress_holiday, notes,
                         effective_start, created_by)
                    VALUES (%s,%s,%s,%s, %s,%s,%s, %s,%s, %s, FALSE, TRUE, %s, %s, 0)
                    ON CONFLICT (client_id, effective_start) DO NOTHING
                """, (cid, primary_tech, backup_1, backup_2,
                      frequency, weekdays, week_pattern,
                      time_start, time_end, visit_type,
                      notes, date(2026, 6, 1)))
                if cur.rowcount > 0:
                    seeded += 1
            except Exception as e:
                print(f"   ERROR for {cust['name']}: {e}")

    if not args.dry_run:
        conn.commit()

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Result:")
    print(f"   Customers processed : {len(top_customers)}")
    print(f"   Rules seeded        : {seeded}")
    print(f"   Skipped (no pattern): {skipped}")

    conn.close()


if __name__ == '__main__':
    main()
