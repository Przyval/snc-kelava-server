# Juni 2026 Pattern-Promote — Execution Results

Run: 2026-05-30 (local) — `bulk_promote_patterns.py` against `snc_schedule_patterns` source_month=2026-05.

## Outcome

| Metric | Before | After 0.85 | After 0.60 |
|---|---|---|---|
| Active rules | 23 | 152 | **199** |
| Customers ruled | 21 | 150 | 197 |
| June visit coverage | 11.2% | 52.2% | **58.7%** |
| Bulk-promoted rules | 0 | 129 | 166 |

**Coverage delta: +47.5 percentage points** in one execution. From "needs manual fill of 89% of June" to "auto-generate ~59% with 41% gap on high-volume / sporadic customers."

## Errors encountered + fixes applied

1. **`time "25:00" out of range`** — 10 patterns with overnight times caused INSERT failures. Root cause: cap logic added 2hr to start without modulo 24. Fixed in [bulk_promote_patterns.py:67](kil/backend/scripts/bulk_promote_patterns.py#L67) (`_cap_time_end` now handles overnight wrap + clamps via `% (24*60)`).
2. **IRUL nickname** — earlier audit substring-matched to Choirul Anam (false positive). Actual: `snc_technicians.id=15 'Irul'` exists separately, active, mobile. Audit doc needs update.

## Remaining 41% gap

Top 15 gap customers (still no rule after promote):

| Visits | Customer | Cause |
|---|---|---|
| 71 | Tanamera Coffee Trans Icon Mall | Daily/multi-tech; pattern detector mis-classified as monthly conf=0.45 |
| 18 | ACAII TP | Low-confidence pattern |
| 10 | CIKAL | Low-confidence |
| 7 | NICi PM 2 G | Same |
| 6 | EUROCHAIR, PCM | Same |
| 4 | CENTIMETER, PT Segar Berkah Abadi, MEDICELLE, BU FRANS, ALURA, VOILA.ID, VERT, KAWAI, BU INGGRIT | New / sporadic |

These need:
- **Tanamera-class** (10+ visits): manual multi-rule (one per weekday) via Master Rules Editor UI
- **Sporadic** (4-7 visits): either manual rule or accept as draft-time exception

## Reversibility

All 166 bulk-promoted rules have `notes LIKE 'Bulk promote from pattern source_month=2026-05%'`. To roll back:

```sql
DELETE FROM snc_recurring_rule_log
  WHERE rule_id IN (SELECT id FROM snc_recurring_rules WHERE notes LIKE 'Bulk promote%');
DELETE FROM snc_recurring_rules
  WHERE notes LIKE 'Bulk promote%';
```

## Next steps for full June readiness

1. **Manual rules** for top 5 gap customers (Tanamera, ACAII TP, CIKAL, NICi, EUROCHAIR) via UI → est. +20 pts coverage → ~79%
2. **Run pattern detection again** after manual rules are in, to catch newly-visible patterns
3. **Generate June draft** via `/enterprise/schedule-draft-calendar` with target_month=2026-06
4. **Validate vs xlsx** — compute recall by joining draft events to xlsx visits on (tech, date, client)

## Tech roster issues (still outstanding)

| Tech | Status | Action |
|---|---|---|
| IRUL (id=15) | ✓ active, exists | (Earlier audit was wrong about this) |
| RANGGA (id=10) | INACTIVE in DB | June xlsx has 23 visits → reactivate or reassign |
| IMAM (id=12) | INACTIVE | June xlsx has 2 visits → reactivate or skip |
| MULYASARI | Not in DB | June xlsx has 22 visits → add tech |
| PM Jogja | Branch label | Not a tech; 7 visits in xlsx are regional |
| PM SOLO | Branch label | Same; 8 visits |

These require HR / koordinator decisions before deploy.
