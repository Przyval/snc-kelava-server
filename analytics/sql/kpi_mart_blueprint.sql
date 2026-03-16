-- ===========================================================================
-- SanoCare KPI Mart Blueprint v1.0
-- Generated: 2026-01-20
-- Status: READY FOR REVIEW (DO NOT EXECUTE CREATE IN PRODUCTION)
-- ===========================================================================

-- ===========================================================================
-- PART A: DIMENSION VIEWS
-- ===========================================================================

-- dim_tech: Teknisi master data
CREATE OR REPLACE VIEW dim_tech AS
SELECT 
    id as tech_id,
    fullname as tech_name,
    email,
    phone,
    id_outlet,
    id_client,
    is_deleted,
    CASE 
        WHEN is_deleted = true THEN 'INACTIVE'
        ELSE 'ACTIVE'
    END as status
FROM p_user
WHERE id IS NOT NULL;

-- dim_customer: Customer master with city
CREATE OR REPLACE VIEW dim_customer AS
SELECT 
    c.id as customer_id,
    c.name as customer_name,
    c.address,
    c.phone,
    c.id_city,
    city.name as city_name,
    c.id_client,
    c.is_deleted
FROM m_customer c
LEFT JOIN m_city city ON c.id_city = city.id;

-- ===========================================================================
-- PART B: AGGREGATION CTEs (MANDATORY BEFORE JOIN)
-- ===========================================================================

-- agg_road_plan_area: Pre-aggregate child tables to prevent explosion
-- Use this CTE pattern in every query touching t_road_plan_area
WITH agg_road_plan_area AS (
    SELECT 
        id_road_plan,
        COUNT(*) as area_count,
        COUNT(DISTINCT treatment_text) as treatment_type_count,
        STRING_AGG(DISTINCT treatment_text, '|') as treatment_list,
        -- Outcome aggregation from rekap JSON
        SUM(COALESCE((rekap->'tindakan cek'->>'count')::int, 0)) as total_tindakan_cek,
        SUM(COALESCE((rekap->'treatment cek'->>'count')::int, 0)) as total_treatment_cek,
        SUM(COALESCE((rekap->'treatment ganti'->>'count')::int, 0)) as total_treatment_ganti,
        SUM(COALESCE((rekap->'treatment tambah'->>'count')::int, 0)) as total_treatment_tambah,
        SUM(COALESCE((rekap->'kondisi umpan dimakan'->>'count')::int, 0)) as total_umpan_dimakan,
        SUM(COALESCE((rekap->'kondisi unit rusak'->>'count')::int, 0)) as total_unit_rusak,
        SUM(COALESCE((rekap->'kondisi unit hilang'->>'count')::int, 0)) as total_unit_hilang
    FROM t_road_plan_area
    GROUP BY id_road_plan
),

-- agg_road_plan_foto: Pre-aggregate foto count
agg_road_plan_foto AS (
    SELECT 
        id_road_plan,
        COUNT(*) as foto_count
    FROM t_road_plan_foto
    GROUP BY id_road_plan
),

-- agg_road_plan_subarea: Pre-aggregate subarea count
agg_road_plan_subarea AS (
    SELECT 
        rpa.id_road_plan,
        COUNT(*) as subarea_count
    FROM t_road_plan_subarea rps
    JOIN t_road_plan_area rpa ON rps.road_plan_area_id = rpa.id
    GROUP BY rpa.id_road_plan
)

-- ===========================================================================
-- PART C: FACT TABLES
-- ===========================================================================

-- fact_road_plan: 1 row per scheduled visit (plan)
-- Grain: id_road_plan
SELECT 
    rp.id as road_plan_id,
    rp.visit_date::date as plan_date,
    rp.id_user as tech_id,
    rp.id_customer,
    rp.id_kontrak as contract_id,
    rp.id_outlet,
    rp.status,
    rp.type as visit_type,
    rp.title,
    rp.is_cancel,
    rp.created_date,
    -- Aggregated child data (no explosion)
    COALESCE(ara.area_count, 0) as area_count,
    COALESCE(ara.treatment_type_count, 0) as treatment_type_count,
    ara.treatment_list,
    COALESCE(arf.foto_count, 0) as foto_count,
    COALESCE(ars.subarea_count, 0) as subarea_count,
    -- Outcome metrics
    COALESCE(ara.total_tindakan_cek, 0) as outcome_check_count,
    COALESCE(ara.total_treatment_ganti, 0) as outcome_replace_count,
    COALESCE(ara.total_umpan_dimakan, 0) as outcome_bait_eaten,
    COALESCE(ara.total_unit_rusak, 0) as outcome_unit_damaged
FROM t_road_plan rp
LEFT JOIN agg_road_plan_area ara ON rp.id = ara.id_road_plan
LEFT JOIN agg_road_plan_foto arf ON rp.id = arf.id_road_plan
LEFT JOIN agg_road_plan_subarea ars ON rp.id = ars.id_road_plan;

-- fact_visit: 1 row per actual check-in (realization)
-- Grain: visit_id
SELECT 
    v.id as visit_id,
    v.id_road_plan as road_plan_id,
    v.id_user as tech_id,
    v.id_customer,
    v.id_outlet,
    v.realization_date,
    -- Timestamps
    v.check_in,
    v.check_out,
    v.created_date,
    -- Duration calculation
    CASE 
        WHEN v.check_out IS NOT NULL 
        THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 
        ELSE NULL 
    END as duration_minutes,
    -- GPS
    v.latitude,
    v.longitude,
    v.latitude_o,
    v.longitude_o,
    -- Flags
    CASE WHEN v.check_out IS NOT NULL THEN 1 ELSE 0 END as has_checkout,
    CASE 
        WHEN EXTRACT(HOUR FROM v.check_in) < 9 THEN 1 
        ELSE 0 
    END as is_early_checkin,
    -- Link to plan for join
    v.id_road_plan
FROM t_visit v;

-- ===========================================================================
-- PART D: KPI LAYER QUERIES
-- ===========================================================================

-- KPI 1: Plan vs Actual (Completion Rate)
-- Use for: Daily/Weekly/Monthly completion dashboard
WITH plan_vs_actual AS (
    SELECT 
        rp.id as plan_id,
        rp.visit_date::date as plan_date,
        rp.id_user as tech_id,
        rp.is_cancel,
        CASE WHEN v.id IS NOT NULL THEN 1 ELSE 0 END as is_completed
    FROM t_road_plan rp
    LEFT JOIN t_visit v ON rp.id = v.id_road_plan
    WHERE rp.visit_date >= CURRENT_DATE - 30
      AND rp.is_cancel = false
)
SELECT 
    plan_date,
    COUNT(*) as total_planned,
    SUM(is_completed) as total_completed,
    ROUND(100.0 * SUM(is_completed) / NULLIF(COUNT(*), 0), 2) as completion_rate
FROM plan_vs_actual
GROUP BY plan_date
ORDER BY plan_date;

-- KPI 2: Technician Productivity (Visits per Day)
SELECT 
    v.id_user as tech_id,
    u.fullname as tech_name,
    v.check_in::date as visit_date,
    COUNT(*) as visits_completed,
    COUNT(CASE WHEN v.check_out IS NOT NULL THEN 1 END) as with_checkout,
    ROUND(AVG(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60), 2) as avg_duration_min
FROM t_visit v
JOIN p_user u ON v.id_user = u.id
WHERE v.check_in >= CURRENT_DATE - 30
GROUP BY v.id_user, u.fullname, v.check_in::date
ORDER BY visit_date DESC, visits_completed DESC;

-- KPI 3: Checkout Discipline Rate
SELECT 
    v.id_user as tech_id,
    u.fullname as tech_name,
    COUNT(*) as total_visits,
    COUNT(v.check_out) as with_checkout,
    ROUND(100.0 * COUNT(v.check_out) / NULLIF(COUNT(*), 0), 2) as checkout_rate_pct
FROM t_visit v
JOIN p_user u ON v.id_user = u.id
WHERE v.check_in >= CURRENT_DATE - 30
GROUP BY v.id_user, u.fullname
ORDER BY checkout_rate_pct ASC;

-- KPI 4: Outcome Summary (Treatment Activity)
SELECT 
    rp.visit_date::date as visit_date,
    SUM(COALESCE((ara.rekap->'tindakan cek'->>'count')::int, 0)) as total_checks,
    SUM(COALESCE((ara.rekap->'treatment ganti'->>'count')::int, 0)) as total_replacements,
    SUM(COALESCE((ara.rekap->'kondisi umpan dimakan'->>'count')::int, 0)) as total_bait_eaten
FROM t_road_plan rp
JOIN t_road_plan_area ara ON rp.id = ara.id_road_plan
WHERE rp.visit_date >= CURRENT_DATE - 30
GROUP BY rp.visit_date::date
ORDER BY visit_date;

-- ===========================================================================
-- PART E: VALIDATION CHECKSUMS (STEP 6)
-- ===========================================================================

-- Checksum 1: Visits per day volatility
SELECT 
    check_in::date as dt,
    COUNT(*) as visit_count
FROM t_visit
WHERE check_in >= CURRENT_DATE - 14
GROUP BY dt
ORDER BY dt;
-- RULE: Flag if any day has >3x the average or <0.3x the average

-- Checksum 2: Completion rate sanity
SELECT 
    rp.visit_date::date as dt,
    COUNT(*) as planned,
    COUNT(v.id) as completed,
    ROUND(100.0 * COUNT(v.id) / NULLIF(COUNT(*), 0), 2) as rate
FROM t_road_plan rp
LEFT JOIN t_visit v ON rp.id = v.id_road_plan
WHERE rp.visit_date >= CURRENT_DATE - 7
  AND rp.is_cancel = false
GROUP BY dt
ORDER BY dt;
-- RULE: Flag if rate < 50% on working days

-- Checksum 3: Duration outliers
SELECT 
    id as visit_id,
    EXTRACT(EPOCH FROM (check_out - check_in)) / 60 as duration_min
FROM t_visit
WHERE check_in >= CURRENT_DATE - 7
  AND check_out IS NOT NULL
  AND (
    EXTRACT(EPOCH FROM (check_out - check_in)) / 60 < 0
    OR EXTRACT(EPOCH FROM (check_out - check_in)) / 60 > 480
  );
-- RULE: Duration < 0 or > 8 hours = ANOMALY
