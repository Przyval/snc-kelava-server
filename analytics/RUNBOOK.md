# SanoCare KPI Agent - Operating Runbook
> **Version:** 1.0  
> **Last Updated:** 2026-01-13  
> **Owner:** Data & Analytics Team

---

## Quick Reference

| Step | Name | Time | Output |
|------|------|------|--------|
| 0 | Preflight | 2 min | PREFLIGHT_CHECKLIST.md |
| 1 | Contract | Once | kpi_contract.md, kpi_config.yaml |
| 2 | Extract | 10 min | snc_analytics.db |
| 2.1 | DQ Baseline | 5 min | dq_baseline_report.md |
| 3 | Scoring | 3 min | leaderboard_*.csv |
| 3.2 | Acceptance | 1 min | acceptance_test_report.md |
| 4 | Insight Pack | 3 min | insight_pack_YYYY-MM.md |
| 5 | Action Plan | On demand | ops_action_plan.md |

---

## Step 0: Preflight & Safety

### Purpose
Ensure safe, read-only access with correct timezone before touching data.

### Checklist
- [ ] SSH tunnel to VPS active
- [ ] PostgreSQL connection via `snc_read` user
- [ ] Verify SELECT-only access (no INSERT/UPDATE/DELETE)
- [ ] Timezone set: `Asia/Jakarta`
- [ ] Check data freshness: `SELECT MAX(created_at) FROM t_visit`
- [ ] Create output folder: `runs/YYYY-MM-DDTHHMMZ/`

### Output
- `runs/{run_id}/PREFLIGHT_CHECKLIST.md`
- `runs/{run_id}/run_metadata.json`

---

## Step 1: KPI Contract

### Purpose
Lock definitions to prevent mid-analysis debates.

### Key Definitions
| Element | Definition |
|---------|------------|
| Grain | `t_road_plan.id` |
| Join | `t_visit.id_road_plan → t_road_plan.id` |
| Complete | `status = 'Selesai'` |
| Segments | MOBILE, STATION, SUPPORT, SUPERVISOR |
| On-Time FAIR | `actual_day = scheduled_day` |
| On-Time STRICT | `same_day AND NOT suspect_time (21-23h)` |
| Duration valid | Segment-specific (see config) |
| Photo required | **MOBILE, STATION, SPV** only |
| Photo exempt | **SUPPORT/CHECKLIST** (by SOP) |

### Output
- `analytics/reports/KPI_CONTRACT.md`
- `analytics/kpi_config.yaml`

---

## Step 2: Extraction & Staging

### Purpose
Pull minimal data to local DB for fast, repeatable queries.

### Scripts
```bash
python3 step2_etl.py
```

### Tables Created
| Table | Source | Rows (expected) |
|-------|--------|-----------------|
| stg_road_plan | road_plan_base.csv | 33,727 |
| stg_visit | visit_base.csv | 33,727 |
| stg_foto_count | foto_count_agg.csv | ~33K |
| dim_user | dim_user.csv | ~85 |
| dim_customer | dim_customer.csv | ~500 |

### Output
- `analytics/snc_analytics.db`
- `analytics/staging/*.csv`

---

## Step 2.1: Data Quality Baseline

### Purpose
Map data issues before scoring.

### Script
```bash
python3 step2_1_hotfix.py
```

### DQ Flags Computed
| Flag | Rule |
|------|------|
| is_valid_checkin | check_in_first IS NOT NULL |
| is_valid_checkout | check_out_last IS NOT NULL |
| is_valid_duration | 5 ≤ duration ≤ max (segment-specific) |
| is_suspect_time | check_in_hour IN (21, 22, 23) |
| is_multiday_suspect | duration > 1440 min |
| is_photo_compliant | foto_count ≥ 1 (where required) |

### Output
- `analytics/reports/STEP2_DATA_QUALITY_BASELINE.md`
- `dq_flags` table

---

## Step 3: KPI Calculation

### Purpose
Score technicians per month, per segment, per mode.

### Script
```bash
python3 step3_kpi_engine.py
python3 step3_1_patch.py    # Refinements
python3 step3_2_sanity.py   # Acceptance tests
```

### Scoring Weights
| KPI | Weight |
|-----|--------|
| Completion Rate | 25% |
| On-Time Rate | 20% |
| Duration Compliance | 15% |
| Photo Compliance | 15% |
| Productivity | 25% |

### Grade Scale
| Grade | Score |
|-------|-------|
| A | 90-100 |
| B | 80-89.99 |
| C | 70-79.99 |
| D | 60-69.99 |
| F | 0-59.99 |

### Output
- `kpi_user_monthly` table
- `leaderboard_fair_clean.csv`
- `leaderboard_strict_clean.csv`

---

## Step 3.2: Acceptance Tests

### Purpose
Gate before publish - fail fast if data is broken.

### Required Assertions
| Test | Expected |
|------|----------|
| total_road_plans | 33,727 |
| completed_visits | 33,510 |
| null_checkout | 217 |
| null_checkin | 7 |
| no_photo_raw | 5,452 |
| multiday_suspect | 3,431 |
| suspect_time | 5,711 |
| score > 100 | **0** |
| NULL grade | **0** |

### Fail Action
If ANY test fails: **STOP. Do not publish. Investigate.**

### Output
- `analytics/reports/kpi_acceptance_test_report.md`

---

## Step 4: Insight Pack

### Purpose
Transform tables into executive decisions.

### Script
```bash
python3 step4_insight_pack.py
```

### Contents
1. **Executive Summary**: Top 3 issues + impact
2. **Root Cause**: By technician, customer, segment
3. **Action Plan**: P1/P2/P3 changes
4. **Watchlist**: 30-day rolling

### Output
- `analytics/reports/insight_pack_YYYY-MM.md`
- `analytics/insights/*.csv`

---

## Step 5: Action Plan & App Changes

### Purpose
Translate insights into system improvements.

### Priority Matrix
| Priority | Change | Owner |
|----------|--------|-------|
| 🔴 P1 | Auto-checkout at 18:00 | Dev |
| 🔴 P1 | Block checkout if no photo (MOBILE/STATION) | Dev |
| 🟡 P2 | Open visit indicator | Dev |
| 🟡 P2 | Server-recorded timestamps | Dev |
| 🟢 P3 | 2-hour reminder notification | Dev |

### Output
- `analytics/reports/ops_action_plan.md`
- `analytics/reports/app_change_requests.md`

---

## Step 6: Automation Schedule

### Daily (18:30 WIB)
- Incremental extract (today's data)
- Refresh watchlist
- Alert if acceptance tests fail

### Weekly (Monday 08:00 WIB)
- Full refresh
- Generate weekly PDF summary
- Email to Ops/HR

### Monthly (1st, 09:00 WIB)
- Full month close
- FAIR leaderboard for bonus
- STRICT leaderboard for audit
- Archive to `runs/YYYY-MM/`

---

## Versioning Rules

### File Naming
```
{metric}_{mode}_{version}_{date}.csv
leaderboard_fair_v3_2026-01-13.csv
```

### Run Folder Structure
```
runs/
└── 2026-01-13T123000Z/
    ├── run_metadata.json
    ├── PREFLIGHT_CHECKLIST.md
    ├── leaderboard_fair.csv
    ├── leaderboard_strict.csv
    ├── insight_pack.md
    └── acceptance_test.md
```

### Never Overwrite
- Always create new version
- Archive previous to `archive/`

---

## Troubleshooting

### Score > 100
**Cause**: Productivity bonus exceeding cap  
**Fix**: Ensure `MIN(100, score)` applied

### NULL Grade
**Cause**: Score at exact boundary (e.g., 80.0000001)  
**Fix**: Use `>=` not `>` in grade assignment

### Acceptance Test Fail
**Action**: 
1. Check source CSV dates
2. Verify staging table counts
3. Check for schema changes
4. Review recent app deployments

---

## Contacts

| Role | Name | Action |
|------|------|--------|
| Data Owner | Analytics Team | Pipeline questions |
| Product | Dev Team | App change requests |
| Operations | Ops Manager | SOP clarifications |
