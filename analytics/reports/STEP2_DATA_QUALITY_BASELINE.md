# 📊 STEP 2.1: Data Quality Baseline Report (HOTFIX)

> **Generated:** 2026-01-13 11:22:34 WIB
> **Database:** /Users/michael/Downloads/Live SnC - Kelava Server/analytics/snc_analytics.db
> **Version:** 2.1 (with hotfix for duration/checkout issues)

---

## 1. Extraction Summary

**Total road_plans:** 33,727

**Date Range:**
- visit_date: `2021-12-28 17:17:09+07` to `2026-01-13 10:57:15+07`
- check_in: `2021-12-28 17:01:51` to `2026-01-13 10:42:41`
- ⚠️ check_in NULL/empty count: **7** (0.02%)

---

## 2. Coverage Statistics

| Metric | Count | % |
|--------|-------|---|
| Complete but no visit | 0 | 0.00% |
| **NULL checkout** | 217 | 0.64% |
| Invalid checkout (out < in) | 0 | 0.00% |
| No photos (foto_count=0) | 5,452 | 16.17% |

---

## 3. Duration Statistics

### 3.1 Raw Duration by Type (including outliers)

| Type | Count | Avg Raw | Min | Max Raw | Avg Capped |
|------|-------|---------|-----|---------|------------|
| t_mobile | 20,648 | 1157.6 | 0.5 | 315,173 | 272.9 |
| t_station | 8,071 | 1786.0 | 0.1 | 425,229 | 616.2 |
| checklist | 2,750 | 2254.1 | 0.0 | 153,684 | 389.7 |
| spv_tc | 1,837 | 3444.4 | 1.3 | 570,540 | 408.2 |
| spv_qc | 204 | 3985.4 | 2.9 | 111,539 | 550.6 |

### 3.2 Top 20 Duration Outliers (with timestamps)

> These show `check_in_first` and `check_out_last` to identify data quality issues

| RP ID | Type | Duration (min) | Days | Check-in | Check-out |
|-------|------|----------------|------|----------|-----------|
| 10638 | spv_tc | 570,541 | 396.2 | 2023-11-03 09:47 | 2024-12-03 14:48 |
| 10641 | spv_tc | 570,530 | 396.2 | 2023-11-03 09:57 | 2024-12-03 14:47 |
| 10643 | spv_tc | 570,485 | 396.2 | 2023-11-03 10:41 | 2024-12-03 14:47 |
| 3759 | t_station | 425,229 | 295.3 | 2022-09-05 16:29 | 2023-06-27 23:38 |
| 3795 | t_station | 422,358 | 293.3 | 2022-09-07 16:22 | 2023-06-27 23:40 |
| 3845 | t_station | 417,315 | 289.8 | 2022-09-11 04:28 | 2023-06-27 23:43 |
| 25195 | t_station | 410,520 | 285.1 | 2025-03-01 17:28 | 2025-12-11 19:28 |
| 25209 | t_station | 408,896 | 284.0 | 2025-03-02 20:33 | 2025-12-11 19:29 |
| 25287 | t_station | 406,293 | 282.1 | 2025-03-04 15:57 | 2025-12-11 19:29 |
| 20222 | spv_tc | 391,194 | 271.7 | 2024-10-12 10:35 | 2025-07-11 02:29 |
| 13888 | spv_tc | 383,304 | 266.2 | 2024-03-12 10:24 | 2024-12-03 14:49 |
| 4755 | t_mobile | 315,173 | 218.9 | 2022-11-12 14:42 | 2023-06-19 11:35 |
| 18097 | spv_tc | 270,451 | 187.8 | 2024-08-07 20:42 | 2025-02-11 16:13 |
| 3582 | spv_tc | 234,966 | 163.2 | 2022-08-23 15:30 | 2023-02-02 19:36 |
| 17473 | spv_tc | 200,440 | 139.2 | 2024-07-17 10:06 | 2024-12-03 14:46 |
| 4387 | spv_tc | 174,153 | 120.9 | 2022-10-19 14:00 | 2023-02-17 12:33 |
| 6053 | t_station | 173,766 | 120.7 | 2023-02-08 10:37 | 2023-06-09 02:43 |
| 7268 | spv_tc | 171,453 | 119.1 | 2023-04-27 12:30 | 2023-08-24 14:03 |
| 918 | t_mobile | 170,032 | 118.1 | 2021-12-30 14:16 | 2022-04-27 16:08 |
| 923 | t_mobile | 168,764 | 117.2 | 2021-12-31 08:26 | 2022-04-27 13:10 |

> ⚠️ **Analysis:** Outliers show check-outs happening months/years after check-in.
> This is likely 'forgot to checkout' scenarios where technicians checkout much later.
> These should be treated as **data quality issues**, not real durations.

### 3.3 Duration Status Distribution (v2)

| Status | Count | % |
|--------|-------|---|
| 🟢 VALID | 21,381 | 63.39% |
| 🟡 LONG_WARNING | 5,310 | 15.74% |
| 🔴 MULTI_DAY_SUSPECT | 3,431 | 10.17% |
| 🟡 OVERNIGHT_WARNING | 2,188 | 6.49% |
| 🔴 TOO_SHORT | 1,200 | 3.56% |
| 🔴 NO_CHECKOUT | 217 | 0.64% |

---

## 4. Time Anomalies

| Hour | Count | % | Bar |
|------|-------|---|-----|
| 00:00 | 334 | 0.99% | ██ |
| 01:00 | 148 | 0.44% | █ |
| 02:00 | 68 | 0.20% |  |
| 03:00 | 22 | 0.07% |  |
| 04:00 | 23 | 0.07% |  |
| 05:00 | 21 | 0.06% |  |
| 06:00 | 1,167 | 3.46% | ████████ |
| 07:00 | 3,105 | 9.21% | ███████████████████████ |
| 08:00 | 2,264 | 6.71% | █████████████████ |
| 09:00 | 2,768 | 8.21% | █████████████████████ |
| 10:00 | 2,715 | 8.05% | ████████████████████ |
| 11:00 | 2,027 | 6.01% | ███████████████ |
| 12:00 | 2,289 | 6.79% | █████████████████ |
| 13:00 | 2,157 | 6.40% | ████████████████ |
| 14:00 | 2,381 | 7.06% | ██████████████████ |
| 15:00 | 1,864 | 5.53% | ██████████████ |
| 16:00 | 936 | 2.78% | ███████ |
| 17:00 | 529 | 1.57% | ████ |
| 18:00 | 723 | 2.14% | █████ |
| 19:00 | 949 | 2.81% | ███████ |
| 20:00 | 1,519 | 4.50% | ███████████ |
| 21:00 | 3,269 | 9.69% | █████████████████████████ ⚠️ |
| 22:00 | 1,692 | 5.02% | ████████████ ⚠️ |
| 23:00 | 750 | 2.22% | █████ ⚠️ |

### 4.1 Suspect Time (21:00-23:00) Analysis

**Total suspect time records:** 5,711 (16.93%)

| Type | Suspect Count | % of Type's Total |
|------|---------------|-------------------|
| t_mobile | 5,480 | 26.50% |
| t_station | 152 | 1.86% |
| checklist | 35 | 1.26% |
| spv_qc | 31 | 13.90% |
| spv_tc | 13 | 0.70% |

---

## 5. DQ Flags Summary (with corrected %)

| Flag | Count | % |
|------|-------|---|
| is_complete | 33,510 | 99.36% |
| is_valid_checkin | 33,720 | 99.98% |
| is_valid_checkout | 33,510 | 99.36% |
| is_valid_duration (5-480) | 21,381 | 63.39% |
| is_photo_compliant | 28,275 | 83.83% |
| is_working_day | 31,808 | 94.31% |
| is_suspect_time (21-23h) | 5,711 | 16.93% ⚠️ |
| has_null_checkout | 217 | 0.64% |
| has_invalid_checkout | 0 | 0.00% |
| **is_kpi_eligible (v1: 5-600)** | **26,691** | **79.14%** |
| **is_kpi_eligible (v2: stricter)** | **26,691** | **79.14%** |

---

## 6. Recommendations for Step 3

### Data Quality Issues to Handle:

1. **Multi-day durations (>1440 min):** These are 'forgot to checkout' cases.
   - Recommendation: Exclude from duration metrics, flag as data issue

2. **Suspect time (21-23h) primarily in t_mobile (96%):**
   - This suggests technicians are 'submitting at end of day' not 'checking in on arrival'
   - Recommendation: Use `visit_date` comparison instead of clock time for on-time

3. **16.17% with no photos:**
   - This is a real operational gap, valid for KPI penalty

### Suggested KPI Modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Strict** | Use raw data, flag all anomalies | Audit/Compliance |
| **Fair** | Cap duration at 1440, use visit_date for timing | Bonus/Ranking |

---

## ✅ Step 2.1 Hotfix Summary

| Fix | Status |
|-----|--------|
| A) Min check_in NULL | ✅ Fixed with NULL filter |
| B) % formatting | ✅ Using proper count/total |
| C) Checkout mismatch | ✅ Separated NULL vs invalid |
| D) Duration outliers | ✅ Added raw + capped columns |

**Ready for Step 3: KPI Calculation**
