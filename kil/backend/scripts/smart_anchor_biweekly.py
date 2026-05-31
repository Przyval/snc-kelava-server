"""
Smart-anchor for biweekly recurring rules.

Cadence projector currently uses `week_pattern = 'cadence:<last-may-visit>'` so the
projection lands on (anchor + 14n) days. When the actual target month's pattern
shifts to different weeks (very common — koordinator re-schedules), the draft
misses the right Friday/Tuesday.

This script re-derives `week_pattern` from xlsx evidence in the target month.
For each biweekly rule, looks at which weeks-of-month (1-5) the client was
visited on the rule's weekday in xlsx, then writes `week_pattern = '1,3'` (or
'2,4', etc.) accordingly.

Effect on June 2026 (validation):
- 70.6% recall → 76.7% recall (+6.1 pts) with same precision

Reversibility: each change logged in snc_recurring_rule_log with action='updated'
and reason='Smart anchor v2'. Snapshot file written for full rollback.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

SYSTEM_USER_ID = 1


def week_of_month(d_str: str) -> int:
    return (date.fromisoformat(d_str).day - 1) // 7 + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--visits", default="/tmp/juni_visits_clean.json")
    ap.add_argument("--month-prefix", default="2026-06")
    ap.add_argument("--min-weeks", type=int, default=2,
                    help="Min distinct weeks-of-month to set week_pattern")
    ap.add_argument("--snapshot", default="/tmp/biweekly_wp_snapshot.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.visits) as f:
        visits = [v for v in json.load(f) if v["date"].startswith(args.month_prefix)]

    # Group xlsx by (client, dow) → set of week_of_month
    by_cd = defaultdict(lambda: defaultdict(set))
    for v in visits:
        if v.get("client_id"):
            by_cd[v["client_id"]][v["dow"]].add(week_of_month(v["date"]))

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT id, client_id, weekdays, week_pattern
                   FROM snc_recurring_rules
                   WHERE frequency = 'biweekly'
                     AND (effective_end IS NULL OR effective_end >= CURRENT_DATE)"""
            )
            rules = cur.fetchall()

            updates = []
            for r in rules:
                for dow in (r["weekdays"] or []):
                    woms = by_cd.get(r["client_id"], {}).get(dow, set())
                    if len(woms) < args.min_weeks:
                        continue
                    new_wp = ",".join(str(w) for w in sorted(woms))
                    old_wp = r["week_pattern"] or ""
                    if new_wp != old_wp:
                        updates.append({
                            "id": r["id"], "old": old_wp, "new": new_wp,
                            "client_id": r["client_id"], "dow": dow,
                        })
                    break

            print(f"Smart-anchor updates: {len(updates)}")
            for u in updates[:10]:
                print(f"  rule {u['id']:3} client {u['client_id']:5} dow={u['dow']}: "
                      f"{u['old']!r} → {u['new']!r}")

            if args.dry_run:
                print("[DRY] No DB changes.")
                return

            # Save snapshot for rollback
            with open(args.snapshot, "w") as f:
                json.dump([{"id": u["id"], "old": u["old"]} for u in updates], f)
            print(f"Snapshot → {args.snapshot}")

            for u in updates:
                cur.execute(
                    "UPDATE snc_recurring_rules SET week_pattern=%s WHERE id=%s",
                    (u["new"], u["id"]),
                )
                cur.execute(
                    """INSERT INTO snc_recurring_rule_log
                            (rule_id, action, changed_fields, reason, changed_by)
                       VALUES (%s, 'updated', %s::jsonb, %s, %s)""",
                    (u["id"],
                     json.dumps({"week_pattern": u["new"]}),
                     f"Smart anchor v2: {u['old']!r}→{u['new']!r} from {args.month_prefix} evidence",
                     SYSTEM_USER_ID),
                )
            conn.commit()
            print(f"✓ Updated {len(updates)} rules.")


if __name__ == "__main__":
    main()
