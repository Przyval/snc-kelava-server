"""
Reconcile existing recurring rules' weekdays against June xlsx actuals.

For each active rule whose June xlsx visits don't intersect rule.weekdays at all,
update rule.weekdays to the union of (rule_old_weekdays + xlsx_actual_weekdays).
Also downgrade frequency to weekly if the client was visited ≥3 distinct dates
on the same weekday in June.

Conservative: only modify if confidence is high (≥3 June visits with that DOW).

Reversibility: each modification logged in snc_recurring_rule_log with action='updated'
and reason='Reconcile from June 2026 xlsx — auto'.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

SYSTEM_USER_ID = 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--visits", default="/tmp/juni_visits_clean.json")
    ap.add_argument("--month-prefix", default="2026-06")
    ap.add_argument("--threshold", type=int, default=2,
                    help="Min distinct dates per DOW to count as strong evidence")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--user-id", type=int, default=SYSTEM_USER_ID)
    args = ap.parse_args()

    with open(args.visits) as f:
        visits = [v for v in json.load(f) if v["date"].startswith(args.month_prefix)]

    # Group xlsx by client → {dow: set(dates)}
    by_client_dow = defaultdict(lambda: defaultdict(set))
    for v in visits:
        if v.get("client_id"):
            by_client_dow[v["client_id"]][v["dow"]].add(v["date"])

    updates = []  # (rule_id, new_weekdays, new_frequency, reason)
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT id, client_id, weekdays, frequency, primary_tech_id
                FROM snc_recurring_rules
                WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
            """)
            rules = cur.fetchall()

            for r in rules:
                dow_dist = by_client_dow.get(r["client_id"], {})
                if not dow_dist:
                    continue
                rule_dows = set(r["weekdays"] or [])
                # Strong-evidence DOWs (≥threshold distinct dates in target month)
                strong = {dow for dow, dates in dow_dist.items() if len(dates) >= args.threshold}
                max_dates = max((len(dates) for dates in dow_dist.values()), default=0)

                # Decide new weekdays + frequency
                new_weekdays = sorted(rule_dows | strong) if strong else sorted(rule_dows)
                new_freq = r["frequency"]
                # Upgrade frequency based on evidence:
                # - any frequency with ≥3 distinct weeks of visits per DOW = weekly
                # - biweekly/monthly with 2 weeks = biweekly (keep)
                if max_dates >= 3 and r["frequency"] in ("biweekly", "monthly", "adhoc"):
                    new_freq = "weekly"

                # Skip if no change at all
                no_dow_change = strong.issubset(rule_dows)
                no_freq_change = new_freq == r["frequency"]
                if no_dow_change and no_freq_change:
                    continue

                updates.append({
                    "rule_id": r["id"],
                    "client_id": r["client_id"],
                    "old_weekdays": sorted(rule_dows),
                    "new_weekdays": new_weekdays,
                    "old_frequency": r["frequency"],
                    "new_frequency": new_freq,
                })

            print(f"Rules to update: {len(updates)}")
            for u in updates[:10]:
                print(f"  rule {u['rule_id']:3} client {u['client_id']:5}: "
                      f"weekdays {u['old_weekdays']} → {u['new_weekdays']}  "
                      f"freq {u['old_frequency']} → {u['new_frequency']}")

            if args.dry_run:
                print("\n[DRY RUN] No DB changes.")
                return

            for u in updates:
                # When upgrading to weekly, null out week_pattern (it would still
                # restrict projection to specific weeks otherwise).
                if u["new_frequency"] == "weekly":
                    cur.execute("""
                        UPDATE snc_recurring_rules
                        SET weekdays = %s, frequency = %s, week_pattern = NULL
                        WHERE id = %s
                    """, (u["new_weekdays"], u["new_frequency"], u["rule_id"]))
                else:
                    cur.execute("""
                        UPDATE snc_recurring_rules
                        SET weekdays = %s, frequency = %s
                        WHERE id = %s
                    """, (u["new_weekdays"], u["new_frequency"], u["rule_id"]))
                cur.execute("""
                    INSERT INTO snc_recurring_rule_log
                        (rule_id, action, changed_fields, reason, changed_by)
                    VALUES (%s, 'updated', %s::jsonb, %s, %s)
                """, (
                    u["rule_id"],
                    json.dumps({"weekdays": u["new_weekdays"], "frequency": u["new_frequency"]}),
                    f"Reconcile from June 2026 xlsx (old wd={u['old_weekdays']} freq={u['old_frequency']})",
                    args.user_id,
                ))
            conn.commit()
            print(f"\n✓ Updated {len(updates)} rules.")


if __name__ == "__main__":
    main()
