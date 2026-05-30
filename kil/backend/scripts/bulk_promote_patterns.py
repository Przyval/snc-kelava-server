"""
Bulk-promote high-confidence schedule patterns into Master Recurring Rules.

Usage:
    .venv/bin/python -m kil.backend.scripts.bulk_promote_patterns \
        --source-month 2026-05 --min-confidence 0.85 [--dry-run]

Strategy:
- For each (client_id) in snc_schedule_patterns with confidence >= cutoff,
  pick the *best* pattern (highest confidence × occurrence_count × freq priority),
  build a rule, INSERT into snc_recurring_rules.
- Skip clients that already have an active rule (avoid duplicates).
- Skip patterns where tech is inactive or wrong employee_type.
- Cap time_end to start+2hr when observed span > 3 hr (same logic as derive endpoint).
- Created rules default is_mandatory=False (soft, supervisor can promote).

Co-visit (backup) selection:
- Backup 1: highest-confidence other tech on same DOW for same client.
- Backup 2: second-highest. None if no other tech observed.

Audit:
- Logs each created rule in snc_recurring_rule_log with action='created',
  reason='Bulk promote from pattern source_month=YYYY-MM'.

Reversibility:
- Each created rule has a marker in `notes` field for easy rollback:
  DELETE FROM snc_recurring_rules WHERE notes LIKE 'Bulk promote%';
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row


FREQ_PRIORITY = {"weekly": 3, "biweekly": 2, "monthly": 1, "adhoc": 0}
DAYS_SHORT = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
SYSTEM_USER_ID = 1  # admin@sanocare.work


def _hhmm(t):
    if not t:
        return None
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    # Normalize overnight strings: "25:00" → "01:00", "24:00" → "00:00"
    if isinstance(t, str) and ":" in t:
        try:
            h, m = t.split(":")[:2]
            h, m = int(h), int(m)
            h = h % 24
            m = max(0, min(59, m))
            return f"{h:02d}:{m:02d}"
        except (ValueError, IndexError):
            pass
    return str(t)


def _cap_time_end(t_start_str: str, t_end_str: str | None) -> tuple[str | None, str | None]:
    """
    Cap end to start+2hr when span > 3hr. Returns (capped_end, raw_end).
    Handles overnight wrap (end < start ⇒ end + 24hr) and clamps cap to HH<24.
    """
    if not t_start_str or not t_end_str:
        return (t_end_str, t_end_str)
    sh, sm = map(int, t_start_str.split(":")[:2])
    eh, em = map(int, t_end_str.split(":")[:2])
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if end_min < start_min:
        end_min += 24 * 60  # overnight
    span_min = end_min - start_min
    if span_min > 180 or span_min <= 0:
        cap_min = (start_min + 120) % (24 * 60)
        capped = f"{cap_min // 60:02d}:{cap_min % 60:02d}"
        return (capped, t_end_str)
    return (t_end_str, t_end_str)


def fetch_promotable(cur, source_month: str, min_conf: float):
    """Return list of client_ids that have ≥1 promotable pattern AND no active rule yet."""
    cur.execute(
        """
        SELECT DISTINCT p.client_id
        FROM snc_schedule_patterns p
        JOIN snc_technicians t ON t.id = p.technician_id
        WHERE p.source_month = %s
          AND p.confidence >= %s
          AND t.is_active = true
          AND t.employee_type IN ('mobile', 'support')
          AND NOT EXISTS (
            SELECT 1 FROM snc_recurring_rules r
            WHERE r.client_id = p.client_id
              AND (r.effective_end IS NULL OR r.effective_end >= CURRENT_DATE)
          )
        """,
        (source_month, min_conf),
    )
    return [r["client_id"] for r in cur.fetchall()]


def build_rule_from_patterns(cur, client_id: int, source_month: str, min_conf: float):
    """Pick best pattern for client + assemble rule payload. Returns dict or None."""
    cur.execute(
        """
        SELECT p.*, t.name AS tech_name, t.is_active, t.employee_type
        FROM snc_schedule_patterns p
        JOIN snc_technicians t ON t.id = p.technician_id
        WHERE p.client_id = %s
          AND p.source_month = %s
          AND p.confidence >= %s
          AND t.is_active = true
          AND t.employee_type IN ('mobile', 'support')
        ORDER BY p.confidence DESC, p.occurrence_count DESC
        """,
        (client_id, source_month, min_conf),
    )
    patterns = cur.fetchall()
    if not patterns:
        return None

    best = max(
        patterns,
        key=lambda p: (
            FREQ_PRIORITY.get(p["frequency"], 0),
            p["occurrence_count"],
            float(p["confidence"]),
        ),
    )

    weekdays = sorted(
        {
            p["day_of_week"]
            for p in patterns
            if p["technician_id"] == best["technician_id"]
            and float(p["confidence"]) >= 0.85
        }
    )
    if not weekdays:
        weekdays = [best["day_of_week"]]

    same_dow_others = sorted(
        [
            p
            for p in patterns
            if p["day_of_week"] == best["day_of_week"]
            and p["technician_id"] != best["technician_id"]
        ],
        key=lambda p: -float(p["confidence"]),
    )
    backup_1 = same_dow_others[0] if same_dow_others else None
    backup_2 = same_dow_others[1] if len(same_dow_others) > 1 else None

    t_start = _hhmm(best["time_start"]) or "08:00"
    t_end_raw = _hhmm(best["time_end"])
    t_end, _ = _cap_time_end(t_start, t_end_raw)

    week_pattern = best["week_pattern"] if best["frequency"] != "weekly" else None

    return {
        "client_id": client_id,
        "primary_tech_id": best["technician_id"],
        "backup_tech_1_id": backup_1["technician_id"] if backup_1 else None,
        "backup_tech_2_id": backup_2["technician_id"] if backup_2 else None,
        "frequency": best["frequency"],
        "weekdays": weekdays,
        "week_pattern": week_pattern,
        "time_start": t_start,
        "time_end": t_end,
        "visit_type": best["visit_type"] or "PRC",
        "is_mandatory": False,
        "suppress_holiday": True,
        "duration_minutes": None,
        "notes": f"Bulk promote from pattern source_month={source_month} conf={float(best['confidence']):.2f}",
        "effective_start": dt.date.today().isoformat(),
        "effective_end": None,
        "_meta": {
            "tech_name": best["tech_name"],
            "confidence": float(best["confidence"]),
            "occurrence_count": best["occurrence_count"],
        },
    }


def insert_rule(cur, payload: dict, user_id: int) -> int:
    cur.execute(
        """
        INSERT INTO snc_recurring_rules
            (client_id, primary_tech_id, backup_tech_1_id, backup_tech_2_id,
             frequency, weekdays, week_pattern,
             time_start, time_end, visit_type,
             is_mandatory, suppress_holiday, duration_minutes,
             notes, effective_start, effective_end, created_by)
        VALUES (%(client_id)s, %(primary_tech_id)s, %(backup_tech_1_id)s, %(backup_tech_2_id)s,
                %(frequency)s, %(weekdays)s, %(week_pattern)s,
                %(time_start)s, %(time_end)s, %(visit_type)s,
                %(is_mandatory)s, %(suppress_holiday)s, %(duration_minutes)s,
                %(notes)s, %(effective_start)s, %(effective_end)s, %(user_id)s)
        RETURNING id
        """,
        {**payload, "user_id": user_id},
    )
    return cur.fetchone()["id"]


def log_creation(cur, rule_id: int, payload: dict, user_id: int):
    fields = {k: v for k, v in payload.items() if not k.startswith("_")}
    cur.execute(
        """
        INSERT INTO snc_recurring_rule_log
            (rule_id, action, changed_fields, reason, changed_by)
        VALUES (%s, 'created', %s::jsonb, %s, %s)
        """,
        (rule_id, json.dumps(fields, default=str), payload["notes"], user_id),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-month", default="2026-05")
    ap.add_argument("--min-confidence", type=float, default=0.85)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--user-id", type=int, default=SYSTEM_USER_ID)
    args = ap.parse_args()

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            promotable_ids = fetch_promotable(cur, args.source_month, args.min_confidence)
            print(
                f"Promotable clients (no active rule, conf≥{args.min_confidence}, "
                f"source={args.source_month}): {len(promotable_ids)}"
            )

            created = 0
            skipped = 0
            errors = []
            for cid in promotable_ids:
                payload = build_rule_from_patterns(
                    cur, cid, args.source_month, args.min_confidence
                )
                if not payload:
                    skipped += 1
                    continue

                if args.dry_run:
                    m = payload["_meta"]
                    print(
                        f"  [DRY] client {cid:5} → {m['tech_name']:25} "
                        f"{payload['frequency']:8} "
                        f"weekdays={payload['weekdays']} "
                        f"time={payload['time_start']}-{payload['time_end']}  "
                        f"conf={m['confidence']:.2f}  n={m['occurrence_count']}"
                    )
                    created += 1
                    continue

                try:
                    rid = insert_rule(cur, payload, args.user_id)
                    log_creation(cur, rid, payload, args.user_id)
                    created += 1
                except Exception as e:
                    errors.append({"client_id": cid, "error": str(e)})
                    skipped += 1

            if args.dry_run:
                conn.rollback()
                print(f"\n[DRY RUN] Would create {created} rules. No changes committed.")
            else:
                conn.commit()
                print(f"\n✓ Created {created} rules. Skipped {skipped}.")
                if errors:
                    print(f"⚠ Errors: {len(errors)}")
                    for e in errors[:5]:
                        print(f"  {e}")


if __name__ == "__main__":
    main()
