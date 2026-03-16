# 📊 Technician Leaderboard - Technical Specification V2

> **Version:** 2.0 (Corrected)  
> **Date:** 2026-01-10  
> **Changes:** Assigned-first approach, proper on-time definition, visit rollup

---

## ⚠️ Key Corrections from V1

| Issue | V1 (Wrong) | V2 (Correct) |
|-------|------------|--------------|
| **Total Assigned** | Counted from t_visit (realized) | Counted from t_road_plan (assigned) |
| **Completion Rate** | visits/visits = always ~100% | completed/assigned = true rate |
| **On-Time Definition** | Any check_in ≤ scheduled = on-time | Must be within -30/+15 min window |
| **Double Counting** | Possible if >1 visit per road_plan | Rollup to 1 row per road_plan |

### Impact of Corrections

| Metric | V1 (Inflated) | V2 (Real) |
|--------|---------------|-----------|
| Top On-Time Rate | 100% | **33.1%** |
| Top Score | 100.0 | **77.1** |
| Grade A Count | 8 | **0** |
| Grade C Count | 0 | **8** |

> **Insight:** Teknisi hampir semua datang **di luar window on-time** (terlalu awal atau terlalu telat). Ini adalah issue operasional yang perlu perhatian!

---

## 1️⃣ DATA VERIFICATION (Audit-Ready)

### A. Road Plans Without Any Visit
```sql
SELECT
  COUNT(*) AS road_plan_total,
  COUNT(vr.road_plan_id) AS road_plan_with_visit,
  COUNT(*) - COUNT(vr.road_plan_id) AS road_plan_without_visit
FROM (SELECT id FROM t_road_plan 
      WHERE visit_date >= CURRENT_DATE - INTERVAL '30 days'
      AND COALESCE(is_cancel,false)=false) rp
LEFT JOIN (SELECT DISTINCT id_road_plan FROM t_visit) vr ON vr.road_plan_id = rp.id;
```
**Result:** 1,111 total, 1,111 with visit, **0 without visit** ✅

### B. Multiple Visits per Road Plan (Double Counting Check)
```sql
SELECT id_road_plan, COUNT(*) AS visit_cnt
FROM t_visit WHERE id_road_plan IS NOT NULL
GROUP BY id_road_plan HAVING COUNT(*) > 1 LIMIT 10;
```
**Result:** **0 rows** - No double counting issue ✅

### C. Duration Outliers (>12 hours)
```sql
SELECT COUNT(*) AS visits_over_12h FROM t_visit
WHERE check_in IS NOT NULL AND check_out IS NOT NULL
AND (check_out - check_in) > INTERVAL '12 hours';
```
**Result:** **4,927 visits** (14.6%) - Confirmed, capped at 480 min in scoring

---

## 2️⃣ CORRECTED KPI DEFINITIONS

### KPI 1: Completion Rate (FIXED)
| Attribute | Definition |
|-----------|------------|
| **Formula** | `(road_plans with check_out) / (total assigned road_plans) × 100` |
| **Basis** | t_road_plan (assigned), not t_visit (realized) |
| **Excludes** | Cancelled road_plans (`is_cancel = true`) |

### KPI 2: On-Time Rate (FIXED)
| Attribute | Definition |
|-----------|------------|
| **Formula** | `(visits within time window) / (visits with check_in) × 100` |
| **Early Grace** | 30 minutes before scheduled |
| **Late Grace** | 15 minutes after scheduled |
| **Window** | `scheduled_ts - 30min ≤ check_in ≤ scheduled_ts + 15min` |

### KPI 3: Duration (FIXED)
| Attribute | Definition |
|-----------|------------|
| **Formula** | `AVG(last_check_out - first_check_in)` per road_plan |
| **Anti-Gaming Min** | 5 minutes (too fast = suspicious) |
| **Cap Max** | 480 minutes (8 hours) |
| **Rollup** | Uses first check_in, last check_out per road_plan |

---

## 3️⃣ CORRECTED SCORING

### Formula (0-100)
```
Score = (0.35 × Completion Rate) +
        (0.25 × On-Time Rate) +
        (0.25 × Productivity Score) +
        (0.15 × Duration Efficiency)

Where:
- Productivity Score = MIN(100, visits_per_day / 3.0 × 100)
- Duration Efficiency:
  - 60-240 min → 100
  - 30-360 min → 80
  - else → 60
```

### Grade Thresholds
| Grade | Score Range | Current Count |
|-------|-------------|---------------|
| A | ≥ 90 | 0 |
| B | 80-89 | 0 |
| C | 70-79 | 8 |
| D | 60-69 | 24 |
| F | < 60 | 9 |

---

## 4️⃣ CORRECTED SQL (Assigned-First)

```sql
-- TECHNICIAN LEADERBOARD V2 (ASSIGNED-FIRST)
WITH params AS (
  SELECT
    DATE '2025-01-01' AS start_date,
    DATE '2026-02-01' AS end_date,
    30::int AS early_grace_min,
    15::int AS late_grace_min,
    5::int AS min_duration_min,
    480::int AS max_duration_min,
    20::int AS min_assigned_to_rank
),

-- Base: ALL assigned road_plans (not just visited ones)
road_plan_base AS (
  SELECT
    rp.id AS road_plan_id,
    rp.visit_date AS scheduled_ts,
    rp.type AS visit_type,
    rp.id_user AS technician_id,
    rp.id_customer
  FROM t_road_plan rp, params p
  WHERE rp.visit_date >= p.start_date
    AND rp.visit_date < p.end_date
    AND COALESCE(rp.is_cancel, false) = false
),

-- Rollup: 1 row per road_plan (anti-double-counting)
visit_rollup AS (
  SELECT
    v.id_road_plan AS road_plan_id,
    MIN(v.check_in) AS first_check_in,
    MAX(v.check_out) AS last_check_out
  FROM t_visit v
  WHERE v.id_road_plan IS NOT NULL
  GROUP BY v.id_road_plan
),

-- Fact: LEFT JOIN (includes unvisited road_plans)
fact AS (
  SELECT
    rpb.*,
    u.fullname AS technician_name,
    vr.first_check_in AS check_in,
    vr.last_check_out AS check_out,
    CASE WHEN vr.last_check_out IS NOT NULL THEN 1 ELSE 0 END AS is_completed,
    -- Duration (capped)
    CASE
      WHEN vr.first_check_in IS NOT NULL AND vr.last_check_out IS NOT NULL
      THEN LEAST(EXTRACT(EPOCH FROM (vr.last_check_out - vr.first_check_in))/60.0, 
                 (SELECT max_duration_min FROM params))
      ELSE NULL
    END AS duration_min,
    -- On-time: within early/late grace window
    CASE
      WHEN vr.first_check_in IS NULL OR rpb.scheduled_ts IS NULL THEN NULL
      ELSE (
        EXTRACT(EPOCH FROM (rpb.scheduled_ts - vr.first_check_in))/60.0 <= 
          (SELECT early_grace_min FROM params)
        AND
        EXTRACT(EPOCH FROM (vr.first_check_in - rpb.scheduled_ts))/60.0 <= 
          (SELECT late_grace_min FROM params)
      )
    END AS is_ontime
  FROM road_plan_base rpb
  JOIN p_user u ON u.id = rpb.technician_id
  LEFT JOIN visit_rollup vr ON vr.road_plan_id = rpb.road_plan_id
),

agg AS (
  SELECT
    technician_id,
    technician_name,
    COUNT(*) AS total_assigned,
    SUM(is_completed) AS visits_completed,
    COUNT(*) - SUM(is_completed) AS unvisited,
    ROUND(100.0 * SUM(is_completed) / NULLIF(COUNT(*),0), 1) AS completion_rate,
    ROUND(100.0 * SUM(CASE WHEN is_ontime THEN 1 ELSE 0 END)
      / NULLIF(SUM(CASE WHEN is_ontime IS NOT NULL THEN 1 ELSE 0 END), 0), 1) AS ontime_rate,
    ROUND(AVG(CASE WHEN duration_min >= 5 THEN duration_min END)::numeric, 1) AS avg_duration_min,
    COUNT(DISTINCT DATE(check_in)) AS days_active,
    COUNT(DISTINCT id_customer) AS unique_customers,
    ROUND(SUM(is_completed)::numeric / NULLIF(COUNT(DISTINCT DATE(check_in)), 0), 2) AS visits_per_day
  FROM fact
  GROUP BY technician_id, technician_name
),

scored AS (
  SELECT
    a.*,
    ROUND(
      (0.35 * COALESCE(a.completion_rate,0)) +
      (0.25 * COALESCE(a.ontime_rate,0)) +
      (0.25 * LEAST(100, COALESCE(a.visits_per_day,0) / 3.0 * 100)) +
      (0.15 * CASE
        WHEN a.avg_duration_min BETWEEN 60 AND 240 THEN 100
        WHEN a.avg_duration_min BETWEEN 30 AND 360 THEN 80
        ELSE 60
      END)
    , 1) AS composite_score,
    (a.total_assigned >= (SELECT min_assigned_to_rank FROM params)) AS is_qualified
  FROM agg a
)

SELECT
  RANK() OVER (ORDER BY composite_score DESC, completion_rate DESC, visits_completed DESC) AS rank,
  technician_name,
  total_assigned,
  visits_completed,
  unvisited,
  completion_rate || '%' AS completion,
  ontime_rate || '%' AS ontime,
  avg_duration_min || ' min' AS duration,
  visits_per_day AS vpd,
  composite_score AS score,
  CASE 
    WHEN composite_score >= 90 THEN 'A'
    WHEN composite_score >= 80 THEN 'B'
    WHEN composite_score >= 70 THEN 'C'
    WHEN composite_score >= 60 THEN 'D'
    ELSE 'F'
  END AS grade
FROM scored
WHERE is_qualified = true
ORDER BY rank;
```

---

## 5️⃣ TOP PERFORMERS (V2 Corrected)

| Rank | Technician | Assigned | Completed | Completion | On-Time | Duration | VPD | Score | Grade |
|------|------------|----------|-----------|------------|---------|----------|-----|-------|-------|
| 1 | Ananda Almas | 814 | 814 | 100.0% | 15.6% | 107 min | 2.78 | 77.1 | C |
| 2 | Suparman | 884 | 882 | 99.8% | 6.8% | 175 min | 3.05 | 76.6 | C |
| 3 | Akbar Rohmatulah | 913 | 913 | 100.0% | 5.3% | 130 min | 3.07 | 76.3 | C |
| 4 | Moh. Mahrus | 882 | 878 | 99.5% | 5.7% | 164 min | 3.18 | 76.3 | C |
| 5 | Choirul Anam | 1059 | 1058 | 99.9% | 2.2% | 153 min | 3.77 | 75.5 | C |

---

## 6️⃣ KEY INSIGHTS FOR MANAGEMENT

### 🚨 On-Time Issue (Critical)
- Average on-time rate: **~8%** (across all technicians)
- Best performer: **33.1%** (I Wayan Rendy)
- Most technicians arrive **outside the scheduled window**

### Possible Causes:
1. Unrealistic scheduling (jadwal tidak memperhitungkan travel time)
2. Teknisi tidak melihat jadwal (komunikasi issue)
3. Visit_date di db tidak akurat (data entry issue)

### Recommended Actions:
1. Review how `visit_date` is set - apakah ini slot waktu atau tanggal saja?
2. Widen grace window jika memang operasional "by appointment, not by hour"
3. Add travel time buffer to scheduling algorithm

---

*V2 - Corrected for fairness and accuracy*
