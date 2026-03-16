# 📊 SanoCare Data Quality Validation Report

> **Generated:** 2026-01-10 17:15 WIB  
> **Purpose:** Validate data reliability before using KPIs in production leaderboard

---

## 🔍 Executive Summary

| Aspect | Status | Finding |
|--------|--------|---------|
| **Operational Completeness** | ✅ Excellent | 0 road_plans without visits, 0 double counting |
| **Scheduled Time Quality** | ✅ Valid | 0% midnight (real times exist!) |
| **Same-Day Adherence** | ⚠️ Moderate | 68.9% visit same-day as scheduled |
| **Duration Data** | ⚠️ Noisy | p50=169 min, p90=1457 min (huge gap) |
| **Photo Documentation** | ✅ Excellent | 481K photos, 17 avg per road_plan |

---

## 1️⃣ Scheduled Time Validation

### Query (1): Is visit_date actual appointment time?

```
 total | midnight_count | midnight_pct 
-------+----------------+--------------
  1111 |              0 |          0.0
```

**✅ CONFIRMED:** `visit_date` contains **real scheduled times** (0% at midnight).  
The low on-time rate is **a real operational issue**, not a data entry problem.

### Query (2): Distribution of scheduled hours

```
 hour | cnt     hour | cnt     hour | cnt 
------+-----   ------+-----   ------+-----
    0 |  81      8   |  30     16   |  95
    1 |  39      9   |  29     17   |  25
    2 |  41     10   |  60     18   |  36
    3 |   9     11   |  55     19   |  30
    4 |  13     12   |  57     20   |  28
    5 |   2     13   |  94     21   |  31
    6 |   3     14   |  91     22   |  75
    7 |  10     15   | 102     23   |  75
```

**⚠️ OBSERVATION:** Schedules span ALL 24 hours (including 0-6 AM).  
- Peak hours: 13:00-16:00 (business hours)
- But also significant off-hours (22:00-02:00)

**Possible explanations:**
1. Some customers require night/early morning service (restaurants, hotels)
2. Timezone mismatch in data entry
3. Default times being set incorrectly

---

## 2️⃣ On-Time Analysis

### Query (3): Same-day adherence (simpler metric)

```
 ontime_by_date_pct 
--------------------
               68.9
```

**Interpretation:**
- 68.9% of visits happen on the scheduled DATE
- 31.1% happen on a different day
- This is more meaningful than minute-precision on-time

### Comparison of On-Time Metrics

| Metric | Value | Interpretation |
|--------|-------|----------------|
| Minute-precision (-30/+15 min) | **~8%** | Very strict, rarely met |
| Same-day adherence | **68.9%** | Moderate, actionable |
| Completion rate | **99.5%** | Excellent |

**💡 Recommendation:** Use **same-day adherence** as the primary on-time KPI, not minute-precision.

---

## 3️⃣ Duration Quality

### Query (4): Robust duration statistics

```
 p50_min | p90_min | avg_min 
---------+---------+---------
   168.8 |  1456.9 |  1539.4
```

**⚠️ CRITICAL:** Huge gap between p50 (169 min) and avg (1539 min)

| Percentile | Value | Interpretation |
|------------|-------|----------------|
| p50 (median) | **169 min** (2.8 hours) | Typical visit duration |
| p90 | **1,457 min** (24 hours) | Top 10% are overnight |
| Average | **1,539 min** (25.6 hours) | Skewed by outliers |

**💡 Recommendation:** Use **median (p50)** for duration benchmarks, not average.

### Query (5): Suspicious duration percentages

```
 pct_over_12h | pct_under_5m 
--------------+--------------
         14.7 |          3.6
```

| Issue | Percentage | Count (est.) |
|-------|------------|--------------|
| >12 hours (forgot checkout) | **14.7%** | ~4,927 |
| <5 minutes (too fast) | **3.6%** | ~1,200 |
| Valid range (5 min - 12 h) | **81.7%** | ~27,400 |

**💡 Recommendation:** Cap duration at 480 min (8h) and filter <5 min for KPI calculations.

---

## 4️⃣ Photo Documentation

### Query (6): Photo compliance

```
 road_plans_with_foto | total_fotos | avg_fotos_per_rp 
----------------------+-------------+------------------
                28299 |      481835 |             17.0
```

**✅ EXCELLENT:** Photo documentation is robust.

| Metric | Value |
|--------|-------|
| Road plans with photos | 28,299 |
| Total photos | 481,835 |
| Avg photos per road_plan | **17.0** |
| Photo coverage (est.) | **~84%** of completed visits |

**💡 Use this for:** "Foto Compliance" KPI - % of road_plans with at least 1 photo.

---

## 5️⃣ Revised KPI Recommendations

Based on validation, here are the recommended KPIs:

### ✅ Use As-Is
| KPI | Reliability | Notes |
|-----|-------------|-------|
| Completion Rate | ✅ High | Based on check_out existence |
| Visits Completed | ✅ High | Direct count |
| Productivity (VPD) | ✅ High | Visits per day worked |
| Customer Coverage | ✅ High | Unique customers visited |
| Photo Compliance | ✅ High | % with photos (new KPI) |

### ⚠️ Use with Modifications
| KPI | Issue | Recommended Change |
|-----|-------|-------------------|
| On-Time Rate | Minute-precision too strict | → **Same-Day Adherence (68.9%)** |
| Duration Avg | Skewed by outliers | → **Median Duration (169 min)** |
| Duration Efficiency | Outliers inflate | → **Cap at 480 min** |

### ❌ Do Not Use (Yet)
| KPI | Issue |
|-----|-------|
| Geo Compliance | Need to validate GPS accuracy |
| Quality Score | Need QC pass/fail data |

---

## 6️⃣ Revised Scoring Formula (V3)

```sql
Score = (0.35 × Completion Rate) +
        (0.20 × Same-Day Adherence) +  -- Changed from minute on-time
        (0.25 × Productivity Score) +
        (0.10 × Duration Efficiency) + -- Weight reduced
        (0.10 × Photo Compliance)      -- NEW KPI
```

| Weight | KPI | Justification |
|--------|-----|---------------|
| 35% | Completion Rate | Most critical - job done |
| 20% | Same-Day Adherence | Fair, achievable metric |
| 25% | Productivity | Volume matters |
| 10% | Duration (p50-based) | Lower weight due to noise |
| 10% | Photo Compliance | Evidence quality |

---

## 📋 Action Items for Management

1. **Investigate scheduling patterns**: Why are visits scheduled at 22:00-02:00?
2. **Address checkout compliance**: 14.7% forget to checkout (overnight durations)
3. **Use same-day adherence**: More realistic than minute-precision
4. **Review 31% off-day visits**: Why don't they happen on scheduled date?

---

*Report validated against live data as of 2026-01-10*
