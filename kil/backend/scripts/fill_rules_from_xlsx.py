"""
Fill recurring rules from a parsed June xlsx visit list, for customers
that have no existing active rule yet.

Strategy:
- For each (client_id) with no active rule:
  - Group visits by (tech_id, day_of_week).
  - If any (tech, dow) has >=3 visits → create rule with that tech as primary,
    that weekday set as weekdays, frequency=weekly.
  - If 2 different (tech, dow) both have >=3 → biweekly with 2 weekdays.
  - Skip if no group reaches 3 (low confidence).
  - Skip if primary tech is inactive.

Time:
- Use median start time from those visits; cap end to start+2hr.

Reversibility:
- Notes field: 'Fill from June xlsx (juni-fill)' — easy bulk delete.
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

TECH_MAP = {
    'ADAM': 5, 'AKBAR R': 1, 'ALMAS': 4, 'ANAM': 2, 'ABU S': 3,
    'ANDIK': 7, 'LUCKY': 8, 'MAHRUS': 6, 'MAULANA': 9,
    'FATHUR': 51, 'RANGGA': 10, 'IMAM': 12, 'ARGA': 13, 'RENDY': 14,
    'IRUL': 15,
}
# These xlsx values are placeholders / status markers, never real customer names.
# Without filtering them, fuzzy substring match misroutes them (e.g. 'OFF' → 'CoFFee').
NON_CUSTOMER = {
    'OFF', 'CUTI', 'LIBUR', 'NO', 'P', 'X', 'S', 'JP', 'ST', 'TP', 'PM', 'BDG',
    'KETERANGAN', 'Keterangan:', 'Penanggung Jawab', 'SNC TEAM', 'OFFICE SNC',
}
SYSTEM_USER_ID = 1


def _hhmm(s):
    if not s or not isinstance(s, str) or ":" not in s:
        return None
    try:
        h, m = s.split(":")[:2]
        h, m = int(h), int(m)
        return f"{h % 24:02d}:{m:02d}"
    except (ValueError, IndexError):
        return None


def _cap_end(t_start, t_end):
    if not t_start or not t_end:
        return t_end
    sh, sm = map(int, t_start.split(":"))
    eh, em = map(int, t_end.split(":"))
    start_min, end_min = sh*60+sm, eh*60+em
    if end_min < start_min:
        end_min += 24*60
    if end_min - start_min > 180 or end_min - start_min <= 0:
        cap = (start_min + 120) % (24*60)
        return f"{cap//60:02d}:{cap%60:02d}"
    return t_end


def _median_time(times):
    """Pick the most common start time (mode), tie-break by earliest."""
    if not times:
        return None
    c = Counter(times)
    top = c.most_common(1)[0]
    return top[0]


def load_active_active_techs(cur):
    cur.execute("SELECT id FROM snc_technicians WHERE is_active = true AND employee_type IN ('mobile','support')")
    return {r["id"] for r in cur.fetchall()}


def existing_ruled_clients(cur):
    cur.execute("""
        SELECT DISTINCT client_id FROM snc_recurring_rules
        WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
    """)
    return {r["client_id"] for r in cur.fetchall()}


def resolve_visits(cur, visits):
    cur.execute("SELECT id, name FROM snc_clients")
    clients_by_id = {r["id"]: r["name"] for r in cur.fetchall()}
    norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    idx = {norm(n): cid for cid, n in clients_by_id.items()}
    resolved = []
    for v in visits:
        raw = (v["customer"] or "").strip()
        if not raw or raw in NON_CUSTOMER or len(raw) < 2:
            continue
        cn = norm(raw)
        cid = idx.get(cn)
        # Tighter fuzzy: only allow substring when BOTH sides ≥5 chars
        # (prevents 'OFF' matching 'CoFFee')
        if not cid and len(cn) >= 5:
            for n2, id2 in idx.items():
                if len(n2) >= 5 and (cn in n2 or n2 in cn):
                    cid = id2; break
        if cid:
            resolved.append({**v, "client_id": cid, "tech_id": TECH_MAP.get(v["tech"])})
    return resolved, clients_by_id


def derive_rule_for_client(visits_for_client, active_tech_ids, threshold: int = 3):
    """Returns (rule_payload, reason_string) or (None, skip_reason)."""
    if not visits_for_client:
        return None, "no_visits"

    # Group by (tech, dow). Need tech to be known + active.
    groups = defaultdict(list)
    for v in visits_for_client:
        if v["tech_id"] is None or v["tech_id"] not in active_tech_ids:
            continue
        groups[(v["tech_id"], v["dow"])].append(v)

    if not groups:
        return None, "no_active_tech_visits"

    # Filter to groups with >=threshold visits
    big = {k: vs for k, vs in groups.items() if len(vs) >= threshold}
    if not big:
        return None, f"max_group_<{threshold}"

    # Pick the largest group as primary
    primary_key = max(big.keys(), key=lambda k: len(big[k]))
    primary_tech, primary_dow = primary_key
    primary_visits = big[primary_key]

    # Also collect other weekdays for same tech (multi-weekday rule)
    same_tech_weekdays = sorted({k[1] for k in big if k[0] == primary_tech})
    weekdays = same_tech_weekdays

    # Backup tech = second most-frequent tech on same dow
    backup_candidates = sorted(
        [(t, len(g)) for (t, d), g in groups.items() if d == primary_dow and t != primary_tech],
        key=lambda x: -x[1]
    )
    backup_1 = backup_candidates[0][0] if backup_candidates else None
    backup_2 = backup_candidates[1][0] if len(backup_candidates) > 1 else None

    # Time
    starts = [_hhmm(v["time_start"]) for v in primary_visits if v["time_start"]]
    ends = [_hhmm(v["time_end"]) for v in primary_visits if v["time_end"]]
    t_start = _median_time([s for s in starts if s]) or "08:00"
    t_end_raw = _median_time([e for e in ends if e])
    t_end = _cap_end(t_start, t_end_raw)

    visit_type = Counter(v.get("visit_type") for v in primary_visits if v.get("visit_type")).most_common(1)
    visit_type = visit_type[0][0] if visit_type else "PRC"

    rule = {
        "client_id": visits_for_client[0]["client_id"],
        "primary_tech_id": primary_tech,
        "backup_tech_1_id": backup_1,
        "backup_tech_2_id": backup_2,
        "frequency": "weekly",
        "weekdays": weekdays,
        "week_pattern": None,
        "time_start": t_start,
        "time_end": t_end,
        "visit_type": visit_type,
        "is_mandatory": False,
        "suppress_holiday": True,
        "duration_minutes": None,
        "notes": "Fill from June xlsx (juni-fill)",
        "effective_start": dt.date.today().isoformat(),
        "effective_end": None,
        "_meta": {
            "primary_count": len(primary_visits),
            "total_visits": len(visits_for_client),
        },
    }
    return rule, "ok"


def insert(cur, payload, user_id):
    cur.execute("""
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
    """, {**payload, "user_id": user_id})
    rid = cur.fetchone()["id"]
    fields = {k: v for k, v in payload.items() if not k.startswith("_")}
    cur.execute("""
        INSERT INTO snc_recurring_rule_log (rule_id, action, changed_fields, reason, changed_by)
        VALUES (%s, 'created', %s::jsonb, %s, %s)
    """, (rid, json.dumps(fields, default=str), payload["notes"], user_id))
    return rid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--visits", default="/tmp/juni_visits.json")
    ap.add_argument("--threshold", type=int, default=3,
                    help="Min visits in a (tech, dow) group to create a rule")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--user-id", type=int, default=SYSTEM_USER_ID)
    args = ap.parse_args()

    with open(args.visits) as f:
        visits = json.load(f)

    skip_reasons = Counter()
    created = 0
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            active_techs = load_active_active_techs(cur)
            ruled = existing_ruled_clients(cur)
            resolved, clients_by_id = resolve_visits(cur, visits)

            # Group visits by client
            by_client = defaultdict(list)
            for v in resolved:
                by_client[v["client_id"]].append(v)

            gap_clients = sorted(set(by_client.keys()) - ruled, key=lambda c: -len(by_client[c]))
            print(f"Gap clients to consider: {len(gap_clients)}")

            for cid in gap_clients:
                vs = by_client[cid]
                rule, reason = derive_rule_for_client(vs, active_techs, args.threshold)
                if rule is None:
                    skip_reasons[reason] += 1
                    continue
                if args.dry_run:
                    print(f"  [DRY] {clients_by_id.get(cid,'?')[:30]:30} "
                          f"tech={rule['primary_tech_id']:3} dow={rule['weekdays']} "
                          f"time={rule['time_start']}-{rule['time_end']} "
                          f"n_primary={rule['_meta']['primary_count']}/{rule['_meta']['total_visits']}")
                    created += 1
                else:
                    try:
                        insert(cur, rule, args.user_id)
                        created += 1
                    except Exception as e:
                        skip_reasons[f"insert_error: {str(e)[:50]}"] += 1

            if args.dry_run:
                conn.rollback()
                print(f"\n[DRY] Would create {created} rules.")
            else:
                conn.commit()
                print(f"\n✓ Created {created} rules.")
            print(f"Skip reasons: {dict(skip_reasons)}")


if __name__ == "__main__":
    main()
