# 📊 Technician Leaderboard - Technical Specification

> **Version:** 1.0  
> **Date:** 2026-01-10  
> **Author:** Antigravity (Data Engineer + Analytics Engineer)  
> **Database:** PostgreSQL @ app.kelava.id (via VPS tunnel)

---

## 1️⃣ ENTITY DEFINITIONS & LOGICAL ERD

### Core Entities

```
┌─────────────────┐         ┌─────────────────┐
│    p_user       │         │   m_customer    │
│   (Technician)  │         │   (Pelanggan)   │
├─────────────────┤         ├─────────────────┤
│ id (PK)         │         │ id (PK)         │
│ fullname        │         │ name            │
│ username        │         │ address         │
│ phone           │         │ id_city         │
│ akses_kode      │         │ status          │
│ id_client (FK)  │         │ id_client (FK)  │
│ is_deleted      │         │ is_deleted      │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │ id_user                   │ id_customer
         ▼                           ▼
┌─────────────────────────────────────────────┐
│              t_road_plan                     │
│            (Jadwal Kunjungan)                │
├─────────────────────────────────────────────┤
│ id (PK)                                      │
│ visit_date (scheduled timestamp)             │
│ status (Baru/Requested/Berjalan/Selesai)    │
│ type (t_mobile/t_station/checklist/spv_*)   │
│ id_user (FK → p_user)                        │
│ id_customer (FK → m_customer)                │
│ id_outlet (FK → m_outlet)                    │
│ id_kontrak (FK → m_customer_kontrak)         │
│ is_cancel                                    │
│ created_date                                 │
└──────────────────┬──────────────────────────┘
                   │ id_road_plan
                   ▼
┌─────────────────────────────────────────────┐
│                t_visit                       │
│           (Realisasi Kunjungan)              │
├─────────────────────────────────────────────┤
│ id (PK)                                      │
│ id_road_plan (FK → t_road_plan)              │
│ id_user (FK → p_user)                        │
│ check_in (actual timestamp)                  │
│ check_out (actual timestamp)                 │
│ latitude, longitude (GPS check-in)           │
│ latitude_o, longitude_o (GPS check-out)      │
│ meta_distance (JSON - distance data)         │
│ additional_data (JSONB - extra info)         │
│ realization_date                             │
│ remarks                                      │
└─────────────────────────────────────────────┘
```

### Join Keys (Implicit - No FK Constraints)

| From | To | Join Key | Confidence |
|------|----|----------|------------|
| `t_visit` | `t_road_plan` | `t_visit.id_road_plan = t_road_plan.id` | ✅ High |
| `t_road_plan` | `p_user` | `t_road_plan.id_user = p_user.id` | ✅ High |
| `t_visit` | `p_user` | `t_visit.id_user = p_user.id` | ✅ High |
| `t_road_plan` | `m_customer` | `t_road_plan.id_customer = m_customer.id` | ✅ High |

### Technician Definition

```sql
-- "Technician" = p_user who has at least 1 road_plan assigned
-- Filter: is_deleted = false (if applicable)
-- Scope: id_user appears in t_road_plan
```

---

## 2️⃣ KPI DEFINITIONS

### MVP KPIs (v1.0)

#### KPI 1: Visits Completed
| Attribute | Definition |
|-----------|------------|
| **Name** | `visits_completed` |
| **Definition** | Count of visits where technician completed the job |
| **SQL** | `COUNT(*) WHERE check_out IS NOT NULL` |
| **Formula** | `SUM(CASE WHEN check_out IS NOT NULL THEN 1 ELSE 0 END)` |
| **NULL Handling** | Exclude visits without check_out |
| **Anti-Gaming** | Must have valid check_out timestamp; minimum duration threshold (>5 min) |
| **Interpretation** | Higher = more productive. Normalize by days worked for fairness. |

#### KPI 2: Completion Rate
| Attribute | Definition |
|-----------|------------|
| **Name** | `completion_rate` |
| **Definition** | % of assigned road_plans that are completed |
| **SQL** | `completed / assigned * 100` |
| **Formula** | `(COUNT(visit.check_out IS NOT NULL) / COUNT(road_plan.id)) * 100` |
| **NULL Handling** | Exclude cancelled road_plans (`is_cancel = true`) |
| **Anti-Gaming** | Include all assigned road_plans, not just visited ones |
| **Interpretation** | 100% = perfect. <90% needs investigation. |

#### KPI 3: Average Visit Duration
| Attribute | Definition |
|-----------|------------|
| **Name** | `avg_duration_min` |
| **Definition** | Average time spent on each visit |
| **SQL** | `AVG(EXTRACT(EPOCH FROM (check_out - check_in))/60)` |
| **Formula** | `SUM(duration) / COUNT(completed_visits)` |
| **NULL Handling** | Only include visits with both check_in AND check_out |
| **Anti-Gaming** | Cap at 480 min (8 hours); exclude outliers >8h |
| **Expected Range** | t_mobile: 90-130 min, t_station: 200-260 min |
| **Interpretation** | Compare to service type benchmark. Too fast = rushed, too slow = inefficient. |

#### KPI 4: On-Time Arrival Rate
| Attribute | Definition |
|-----------|------------|
| **Name** | `ontime_rate` |
| **Definition** | % of visits where check_in is within tolerance of scheduled time |
| **SQL** | See below |
| **Formula** | `COUNT(delay <= 15 min) / COUNT(has_check_in) * 100` |
| **Tolerance** | 15 minutes late is acceptable |
| **NULL Handling** | Exclude if no check_in or no visit_date |
| **Anti-Gaming** | Use server timestamp, not client-submitted time |
| **Interpretation** | >90% = excellent, <75% = needs improvement |

#### KPI 5: Customer Coverage
| Attribute | Definition |
|-----------|------------|
| **Name** | `unique_customers` |
| **Definition** | Number of distinct customers visited |
| **SQL** | `COUNT(DISTINCT road_plan.id_customer)` |
| **NULL Handling** | Exclude NULL customer references |
| **Anti-Gaming** | N/A - based on assignment |
| **Interpretation** | Higher = broader coverage. Compare to territory size. |

### V2 KPIs (Future)

| KPI | Definition | Data Source |
|-----|------------|-------------|
| `geo_compliance` | % check-ins within 100m of customer location | `t_visit.lat/long` vs `m_customer` geocoding |
| `photo_compliance` | % visits with photo documentation | `t_road_plan_foto` count per road_plan |
| `quality_score` | Supervisor QC pass rate | `spv_qc` type inspections |
| `revisit_rate` | % customers requiring repeat visit | Same customer within 7 days |

---

## 3️⃣ SCORING & RANKING SYSTEM

### Composite Score Formula (0-100)

```
SCORE = (W1 × completion_rate_normalized) +
        (W2 × ontime_rate_normalized) +
        (W3 × productivity_score) +
        (W4 × duration_efficiency)

Where:
- W1 = 0.35 (Completion Rate - most important)
- W2 = 0.25 (On-Time Rate)
- W3 = 0.25 (Productivity = visits per day worked)
- W4 = 0.15 (Duration Efficiency)
```

### Weight Justification

| Weight | KPI | Rationale |
|--------|-----|-----------|
| **35%** | Completion Rate | Core job = complete all assignments |
| **25%** | On-Time Rate | Customer satisfaction depends on punctuality |
| **25%** | Productivity | Volume matters for operational capacity |
| **15%** | Duration Efficiency | Quality vs speed balance |

### Normalization Rules

```sql
-- Normalize to 0-100 scale using percentile ranking
completion_rate_score = completion_rate  -- already 0-100

ontime_rate_score = ontime_rate  -- already 0-100

productivity_score = LEAST(100, (visits_per_day / target_per_day) * 100)
  -- Target: 3 visits/day for t_mobile, 2 for t_station

duration_efficiency = CASE
    WHEN avg_duration BETWEEN benchmark*0.8 AND benchmark*1.2 THEN 100
    WHEN avg_duration < benchmark*0.5 THEN 50  -- too fast = poor quality
    WHEN avg_duration > benchmark*2 THEN 60   -- too slow = inefficient
    ELSE 80
END
```

### Tie-Breaker Rules

1. **Primary:** Completion Rate (higher wins)
2. **Secondary:** On-Time Rate (higher wins)
3. **Tertiary:** Total Visits Completed (higher wins)
4. **Final:** Alphabetical by name

### Fairness Normalization

```sql
-- Technician with 10 visits shouldn't beat technician with 100 visits
-- Minimum threshold: 20 visits in period to qualify for ranking
-- For rates: apply only if sample size ≥ 20

qualified = (total_assigned >= 20)
```

---

## 4️⃣ SQL QUERIES

### A. Visit Fact Base (CTE)

```sql
-- ============================================
-- VISIT FACT BASE
-- Consolidated view of visits with all metrics
-- ============================================

WITH visit_fact AS (
    SELECT 
        -- IDs
        v.id AS visit_id,
        rp.id AS road_plan_id,
        u.id AS technician_id,
        u.fullname AS technician_name,
        rp.id_customer,
        c.name AS customer_name,
        
        -- Timestamps
        rp.visit_date AS scheduled_ts,
        v.check_in,
        v.check_out,
        v.realization_date,
        rp.created_date AS plan_created,
        
        -- Type & Status
        rp.type AS visit_type,
        rp.status AS plan_status,
        COALESCE(rp.is_cancel, false) AS is_cancelled,
        
        -- Derived: Completion
        CASE 
            WHEN v.check_out IS NOT NULL THEN true 
            ELSE false 
        END AS visit_completed,
        
        -- Derived: Duration (capped at 8 hours for sanity)
        CASE 
            WHEN v.check_out IS NOT NULL 
                AND EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60 BETWEEN 1 AND 480
            THEN ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60, 1)
            ELSE NULL 
        END AS duration_minutes,
        
        -- Derived: Check-in Delay
        CASE 
            WHEN v.check_in IS NOT NULL AND rp.visit_date IS NOT NULL
            THEN ROUND(EXTRACT(EPOCH FROM (v.check_in - rp.visit_date))/60, 1)
            ELSE NULL 
        END AS checkin_delay_minutes,
        
        -- Derived: On-Time (within 15 min)
        CASE 
            WHEN v.check_in IS NOT NULL AND rp.visit_date IS NOT NULL
                AND EXTRACT(EPOCH FROM (v.check_in - rp.visit_date))/60 <= 15
            THEN true
            ELSE false 
        END AS is_ontime,
        
        -- GPS
        v.latitude,
        v.longitude,
        
        -- Period helpers
        DATE(v.check_in) AS visit_date_actual,
        DATE_TRUNC('week', v.check_in) AS visit_week,
        DATE_TRUNC('month', v.check_in) AS visit_month
        
    FROM t_visit v
    INNER JOIN t_road_plan rp ON v.id_road_plan = rp.id
    INNER JOIN p_user u ON rp.id_user = u.id
    LEFT JOIN m_customer c ON rp.id_customer = c.id
    WHERE rp.is_cancel IS NOT TRUE
)
SELECT * FROM visit_fact;
```

### B. Technician Leaderboard Query

```sql
-- ============================================
-- TECHNICIAN LEADERBOARD
-- Aggregated KPIs per technician
-- ============================================

WITH visit_fact AS (
    SELECT 
        v.id AS visit_id,
        rp.id AS road_plan_id,
        u.id AS technician_id,
        u.fullname AS technician_name,
        rp.type AS visit_type,
        rp.status AS plan_status,
        COALESCE(rp.is_cancel, false) AS is_cancelled,
        v.check_in,
        v.check_out,
        rp.visit_date AS scheduled_ts,
        rp.id_customer,
        
        -- Completion flag
        CASE WHEN v.check_out IS NOT NULL THEN 1 ELSE 0 END AS is_completed,
        
        -- Duration (capped)
        CASE 
            WHEN v.check_out IS NOT NULL 
                AND EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60 BETWEEN 5 AND 480
            THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60
            ELSE NULL 
        END AS duration_min,
        
        -- On-time flag
        CASE 
            WHEN v.check_in IS NOT NULL 
                AND rp.visit_date IS NOT NULL
                AND EXTRACT(EPOCH FROM (v.check_in - rp.visit_date))/60 <= 15
            THEN 1 ELSE 0 
        END AS is_ontime
        
    FROM t_visit v
    INNER JOIN t_road_plan rp ON v.id_road_plan = rp.id
    INNER JOIN p_user u ON rp.id_user = u.id
    WHERE v.check_in >= '2025-01-01'  -- Adjust period
      AND rp.is_cancel IS NOT TRUE
),

technician_kpis AS (
    SELECT
        technician_id,
        technician_name,
        
        -- KPI 1: Visits Completed
        SUM(is_completed) AS visits_completed,
        
        -- KPI 2: Total Assigned
        COUNT(*) AS total_assigned,
        
        -- KPI 3: Completion Rate
        ROUND(100.0 * SUM(is_completed) / NULLIF(COUNT(*), 0), 1) AS completion_rate,
        
        -- KPI 4: On-Time Rate
        ROUND(100.0 * SUM(is_ontime) / NULLIF(SUM(CASE WHEN check_in IS NOT NULL THEN 1 ELSE 0 END), 0), 1) AS ontime_rate,
        
        -- KPI 5: Average Duration
        ROUND(AVG(duration_min)::numeric, 1) AS avg_duration_min,
        
        -- KPI 6: Days Worked
        COUNT(DISTINCT DATE(check_in)) AS days_worked,
        
        -- KPI 7: Unique Customers
        COUNT(DISTINCT id_customer) AS unique_customers,
        
        -- KPI 8: Visits per Day
        ROUND(SUM(is_completed)::numeric / NULLIF(COUNT(DISTINCT DATE(check_in)), 0), 1) AS visits_per_day

    FROM visit_fact
    GROUP BY technician_id, technician_name
),

scored AS (
    SELECT
        *,
        
        -- Composite Score (0-100)
        ROUND(
            (0.35 * COALESCE(completion_rate, 0)) +
            (0.25 * COALESCE(ontime_rate, 0)) +
            (0.25 * LEAST(100, COALESCE(visits_per_day, 0) * 33.3)) +  -- target 3/day = 100
            (0.15 * CASE 
                WHEN avg_duration_min BETWEEN 90 AND 150 THEN 100
                WHEN avg_duration_min BETWEEN 60 AND 200 THEN 80
                ELSE 60
            END)
        , 1) AS composite_score,
        
        -- Qualified (min 20 visits)
        CASE WHEN total_assigned >= 20 THEN true ELSE false END AS is_qualified

    FROM technician_kpis
)

SELECT
    RANK() OVER (ORDER BY composite_score DESC, completion_rate DESC, visits_completed DESC) AS rank,
    technician_id,
    technician_name,
    visits_completed,
    total_assigned,
    completion_rate,
    ontime_rate,
    avg_duration_min,
    days_worked,
    unique_customers,
    visits_per_day,
    composite_score,
    is_qualified,
    
    -- Grade
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

### C. Weekly Leaderboard (Parameterized)

```sql
-- ============================================
-- WEEKLY LEADERBOARD
-- Pass week start date as parameter
-- ============================================

WITH week_visits AS (
    SELECT 
        u.id AS technician_id,
        u.fullname AS technician_name,
        v.check_in,
        v.check_out,
        rp.visit_date,
        rp.id_customer,
        rp.type
    FROM t_visit v
    INNER JOIN t_road_plan rp ON v.id_road_plan = rp.id
    INNER JOIN p_user u ON rp.id_user = u.id
    WHERE DATE(v.check_in) >= DATE_TRUNC('week', CURRENT_DATE)  -- Current week
      AND DATE(v.check_in) < DATE_TRUNC('week', CURRENT_DATE) + INTERVAL '7 days'
      AND COALESCE(rp.is_cancel, false) = false
),

weekly_kpis AS (
    SELECT
        technician_id,
        technician_name,
        COUNT(*) AS visits_completed,
        COUNT(DISTINCT id_customer) AS customers_visited,
        COUNT(DISTINCT DATE(check_in)) AS days_active,
        ROUND(AVG(
            CASE 
                WHEN check_out IS NOT NULL 
                    AND EXTRACT(EPOCH FROM (check_out - check_in))/60 BETWEEN 5 AND 480
                THEN EXTRACT(EPOCH FROM (check_out - check_in))/60
            END
        )::numeric, 0) AS avg_duration
    FROM week_visits
    WHERE check_out IS NOT NULL
    GROUP BY technician_id, technician_name
)

SELECT
    RANK() OVER (ORDER BY visits_completed DESC) AS rank,
    technician_name,
    visits_completed,
    customers_visited,
    days_active,
    avg_duration || ' min' AS avg_duration,
    ROUND(visits_completed::numeric / NULLIF(days_active, 0), 1) AS visits_per_day
FROM weekly_kpis
ORDER BY rank;
```

### D. Daily Operations Summary

```sql
-- ============================================
-- DAILY OPERATIONS SUMMARY
-- For management morning briefing
-- ============================================

SELECT
    DATE(v.check_in) AS visit_date,
    COUNT(*) AS total_visits,
    COUNT(CASE WHEN v.check_out IS NOT NULL THEN 1 END) AS completed,
    COUNT(DISTINCT rp.id_user) AS technicians_active,
    COUNT(DISTINCT rp.id_customer) AS customers_served,
    ROUND(AVG(
        CASE 
            WHEN v.check_out IS NOT NULL 
                AND EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60 BETWEEN 5 AND 480
            THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60
        END
    )::numeric, 0) AS avg_duration_min
FROM t_visit v
INNER JOIN t_road_plan rp ON v.id_road_plan = rp.id
WHERE DATE(v.check_in) >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY DATE(v.check_in)
ORDER BY visit_date DESC;
```

---

## 5️⃣ DATA QUALITY NOTES

### Known Issues to Handle

| Issue | Impact | Mitigation |
|-------|--------|------------|
| 4,927 visits >12 hours | Skews duration avg | Cap at 480 min |
| 208 visits no check_out | Incomplete data | Exclude from rates |
| 99% t_visit.id_customer NULL | Can't link directly | Join via t_road_plan |
| 92% t_road_plan.id_kontrak NULL | Can't link to contract | Use customer as proxy |

### Benchmark Durations by Type

| Type | Expected Duration | Source |
|------|------------------|--------|
| `t_mobile` | 90-130 min | Data analysis (111 avg) |
| `t_station` | 200-260 min | Data analysis (231 avg) |
| `checklist` | 110-150 min | Data analysis (131 avg) |
| `spv_tc` | 120-170 min | Data analysis (144 avg) |
| `spv_qc` | 80-130 min | Data analysis (105 avg) |

---

## 6️⃣ IMPLEMENTATION CHECKLIST

- [ ] Run leaderboard query via VPS
- [ ] Export results to CSV
- [ ] Build HTML dashboard
- [ ] Add period selector (daily/weekly/monthly)
- [ ] Add drill-down per technician
- [ ] Schedule auto-refresh (cron)

---

*End of Specification*
