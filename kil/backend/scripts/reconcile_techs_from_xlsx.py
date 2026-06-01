"""
Reconcile recurring rules' tech assignments from xlsx evidence.

For each active rule, look at xlsx visits for the client and:
  - Identify all techs that visited this client in target month
  - If >1 tech and rule's backup slots are empty, fill them
  - Order by visit count: most-frequent = primary (keep existing if matches),
    others = backup_1, backup_2 (cap at 3 total per rule)

Combined with reconcile_rules_from_xlsx (weekdays) and smart_anchor_biweekly
(week_pattern), this closes the loop on rule fidelity to xlsx evidence.

Reversibility: each change logged in snc_recurring_rule_log.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

SYSTEM_USER_ID = 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--visits", default="/tmp/juni_visits_clean.json")
    ap.add_argument("--month-prefix", default="2026-06")
    ap.add_argument("--min-visits", type=int, default=2,
                    help="Min visits per tech to count as co-tech")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.visits) as f:
        visits = [v for v in json.load(f) if v["date"].startswith(args.month_prefix)]

    # Group xlsx by client → Counter(tech)
    by_client = defaultdict(Counter)
    for v in visits:
        if v.get("client_id") and v.get("tech_id"):
            by_client[v["client_id"]][v["tech_id"]] += 1

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT id, client_id, primary_tech_id, backup_tech_1_id, backup_tech_2_id
                FROM snc_recurring_rules
                WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
            """)
            rules = cur.fetchall()

            updates = []
            for r in rules:
                tech_counts = by_client.get(r["client_id"], Counter())
                strong = [(t, n) for t, n in tech_counts.items() if n >= args.min_visits]
                if len(strong) < 2:
                    continue
                # Sort by visits desc
                strong.sort(key=lambda x: -x[1])
                # Take up to 3 techs total
                top = [t for t, _ in strong[:3]]

                # Build new tech triplet: prefer existing primary if it's in top
                existing = [r["primary_tech_id"], r["backup_tech_1_id"], r["backup_tech_2_id"]]
                existing_in_top = [t for t in existing if t in top]
                new_primary = (existing_in_top[0] if existing_in_top
                               else top[0])
                # backups = remaining top techs in xlsx order
                backups = [t for t in top if t != new_primary][:2]
                new_b1 = backups[0] if len(backups) >= 1 else None
                new_b2 = backups[1] if len(backups) >= 2 else None

                old = (r["primary_tech_id"], r["backup_tech_1_id"], r["backup_tech_2_id"])
                new = (new_primary, new_b1, new_b2)
                if old == new:
                    continue
                updates.append({
                    "id": r["id"],
                    "client_id": r["client_id"],
                    "old": old,
                    "new": new,
                    "xlsx_counts": dict(tech_counts),
                })

            print(f"Tech-reconcile updates: {len(updates)}")
            for u in updates[:8]:
                print(f"  rule {u['id']:3} client {u['client_id']:5}: "
                      f"{u['old']} → {u['new']}  xlsx_counts={u['xlsx_counts']}")

            if args.dry_run:
                print("[DRY] No DB changes.")
                return

            for u in updates:
                cur.execute("""
                    UPDATE snc_recurring_rules
                    SET primary_tech_id=%s, backup_tech_1_id=%s, backup_tech_2_id=%s
                    WHERE id=%s
                """, (*u["new"], u["id"]))
                cur.execute("""
                    INSERT INTO snc_recurring_rule_log
                        (rule_id, action, changed_fields, reason, changed_by)
                    VALUES (%s, 'updated', %s::jsonb, %s, %s)
                """, (u["id"],
                      json.dumps({"primary_tech_id": u["new"][0],
                                  "backup_tech_1_id": u["new"][1],
                                  "backup_tech_2_id": u["new"][2]}),
                      f"Tech-reconcile from {args.month_prefix} xlsx (old={u['old']})",
                      SYSTEM_USER_ID))
            conn.commit()
            print(f"✓ Updated {len(updates)} rules.")


if __name__ == "__main__":
    main()
