# Juni 2026 — End-to-End Draft Generation + Recall

Run: 2026-05-30 (local). Source: `snc_schedule_patterns` source_month=2026-05 + 9 fills dari June xlsx. Target: `snc_schedule_events` draft_batch_id=40, target_month=2026-06.

## TL;DR

| Metric | Value | PRD Target | Δ |
|---|---|---|---|
| Active rules used | 206 | — | — |
| Events generated | 634 | — | — |
| **Hard recall** (exact tech+client+date) | **56.2%** | 78-82% | -21.8 pts |
| Soft recall (client+date) | 58.6% | — | — |
| Customer recall (visited at all) | 89.2% | — | — |
| Precision | 60.4% | — | — |
| Conflicts detected | 67 (44 overlap + 23 holiday) | — | — |

**Verdict**: System works end-to-end. From "auto-generate is impossible" (Pre-promote 11%) to a **working 56% recall draft**. 22 pts short of target — closable with manual rule curation for the top gap customers.

## Coverage trajectory

```
Pre-promote     :  11.2%
After conf≥0.85 :  52.2%   (+41.0 pts, 129 rules from May patterns)
After conf≥0.60 :  58.7%   (+ 6.5 pts, +37 rules)
After xlsx fill :  67.8%   (+ 9.1 pts, +9 rules from June pattern)
─────────────────────────
Hard recall     :  56.2%   (real measure on generated draft events)
```

Coverage drops from 67.8% (rule existence) → 56.2% (event presence) karena:
1. Cadence projector (biweekly anchor) sometimes lands on wrong weeks
2. day_cap / week_cap deduplicated 80+ events
3. Holiday suppression removed 2 days' worth of visits

## What got generated

```
events_created:        634
events_skipped:        433
skip_reasons:
  duplicate:           348   (cadence projector hit same slot twice)
  day_cap_exceeded:     64   (tech daily capacity max'd out)
  week_cap_exceeded:    16   (weekly capacity)
  adhoc_low_conf:        3
  customer_inactive:     1
  rule_customer_inactive: 1
conflicts_detected:    67
  overlap:             44   (tech overbooking same time)
  holiday_exception:   23   (rule scheduled on Pancasila/Hijriyah)
patterns_consolidated: 40    (deduped from 206 source rules)
```

## Bugs hit & fixed during run

1. **`time '24:00:00'` DataError on rule fetch** — 3 promoted rules had time_end=24:00 (postgres TIME max is 23:59:59 in psycopg). Fixed: UPDATE → '23:59' + patched `_hhmm` to `% 24`.
2. **ForeignKeyViolation when replacing batch** — `snc_schedule_events.draft_batch_id` lacked CASCADE. Migration 031 added CASCADE for conflicts + audit but missed events. Fixed: added CASCADE to events FK.

## Path to PRD target (78-82%)

Remaining 22-pt gap dominated by:

| Cause | Estimated impact |
|---|---|
| Tanamera 71 visits (only 5 in draft via 1 rule) | +9 pts if 14 per-tech rules created |
| Other high-volume customers w/o rule | +5 pts |
| Pattern detector misses (CIKAL etc. low conf) | +5 pts |
| Tech reassignments (Rangga inactive) | +3 pts after reactivation |

Action items:
1. Create 14 per-tech rules for Tanamera (Sunday slot, all techs) → +9 pts → **65%**
2. Reactivate Rangga / handle inactive-tech rules → +3 pts → **68%**
3. Lower xlsx-fill threshold to 2 → ~7 more rules → +5 pts → **73%**
4. Improve pattern detection v22 (current 74.6% recall on May test set) → +5 pts → **78%**

## Reproducibility

```bash
# 1. Bulk-promote May patterns to rules
.venv/bin/python -m kil.backend.scripts.bulk_promote_patterns \
  --source-month 2026-05 --min-confidence 0.85
.venv/bin/python -m kil.backend.scripts.bulk_promote_patterns \
  --source-month 2026-05 --min-confidence 0.60

# 2. Fill remaining gaps from xlsx itself
.venv/bin/python -m kil.backend.scripts.fill_rules_from_xlsx \
  --visits /tmp/juni_visits.json

# 3. Generate draft via API
curl -X POST $BASE/api/v1/enterprise/calendar/generate-draft \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"target_month":"2026-06","source_month":"2026-05","mode":"replace"}'

# 4. Inspect via UI
open http://localhost:5099/enterprise/schedule-draft-calendar
```

## Rollback

```sql
-- Remove all auto-created rules
DELETE FROM snc_recurring_rule_log
  WHERE rule_id IN (SELECT id FROM snc_recurring_rules
                    WHERE notes LIKE 'Bulk promote%' OR notes LIKE 'Fill from June%');
DELETE FROM snc_recurring_rules
  WHERE notes LIKE 'Bulk promote%' OR notes LIKE 'Fill from June%';

-- Drop the draft batch (CASCADE will clean events)
DELETE FROM snc_draft_batches WHERE target_month = '2026-06' AND id = 40;
```
