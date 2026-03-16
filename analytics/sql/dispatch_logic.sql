-- ===========================================================================
-- SanoCare Dispatch/Control Tower Logic v1.0
-- STEP 7: Idle Detection + Candidate Ranking for Ad-hoc Jobs
-- Generated: 2026-01-20
-- ===========================================================================

-- ===========================================================================
-- PART A: IDLE SLOT DETECTION
-- Definisi: Teknisi dianggap IDLE jika ada slot kosong dalam jadwal harian
-- ===========================================================================

-- Query: Find idle slots per tech per day
-- Logic: Gap antara checkout visit N dan checkin visit N+1
WITH tech_daily_timeline AS (
    SELECT 
        v.id_user as tech_id,
        v.check_in::date as visit_date,
        v.check_in,
        v.check_out,
        ROW_NUMBER() OVER (PARTITION BY v.id_user, v.check_in::date ORDER BY v.check_in) as visit_seq,
        LEAD(v.check_in) OVER (PARTITION BY v.id_user, v.check_in::date ORDER BY v.check_in) as next_checkin
    FROM t_visit v
    WHERE v.check_in >= CURRENT_DATE - 7
),
idle_slots AS (
    SELECT 
        tech_id,
        visit_date,
        check_out as slot_start,
        next_checkin as slot_end,
        EXTRACT(EPOCH FROM (next_checkin - check_out)) / 60 as idle_minutes
    FROM tech_daily_timeline
    WHERE check_out IS NOT NULL 
      AND next_checkin IS NOT NULL
      AND next_checkin > check_out
      AND EXTRACT(EPOCH FROM (next_checkin - check_out)) / 60 > 30 -- Min 30 min gap
)
SELECT 
    tech_id,
    visit_date,
    COUNT(*) as idle_slot_count,
    SUM(idle_minutes) as total_idle_minutes,
    AVG(idle_minutes) as avg_idle_minutes
FROM idle_slots
GROUP BY tech_id, visit_date
ORDER BY visit_date, total_idle_minutes DESC;

-- ===========================================================================
-- PART B: TECH AVAILABILITY STATUS (Real-time Query)
-- For: "Who is available RIGHT NOW?"
-- ===========================================================================

-- Current status per tech
WITH last_activity AS (
    SELECT 
        id_user as tech_id,
        MAX(check_in) as last_checkin,
        MAX(check_out) as last_checkout
    FROM t_visit
    WHERE check_in::date = CURRENT_DATE
    GROUP BY id_user
),
today_plan AS (
    SELECT 
        id_user as tech_id,
        COUNT(*) as total_plans_today,
        COUNT(v.id) as completed_today
    FROM t_road_plan rp
    LEFT JOIN t_visit v ON rp.id = v.id_road_plan
    WHERE rp.visit_date::date = CURRENT_DATE
      AND rp.is_cancel = false
    GROUP BY id_user
)
SELECT 
    u.id as tech_id,
    u.fullname as tech_name,
    COALESCE(tp.total_plans_today, 0) as scheduled_today,
    COALESCE(tp.completed_today, 0) as completed_today,
    COALESCE(tp.total_plans_today, 0) - COALESCE(tp.completed_today, 0) as remaining_today,
    la.last_checkin,
    la.last_checkout,
    CASE 
        WHEN la.last_checkout IS NULL AND la.last_checkin IS NOT NULL 
            THEN 'WORKING'
        WHEN la.last_checkout IS NOT NULL 
            AND EXTRACT(EPOCH FROM (NOW() - la.last_checkout)) / 60 < 60
            THEN 'TRAVELING/IDLE'
        WHEN COALESCE(tp.completed_today, 0) >= COALESCE(tp.total_plans_today, 0)
            THEN 'DONE_FOR_DAY'
        ELSE 'UNKNOWN'
    END as current_status
FROM p_user u
LEFT JOIN last_activity la ON u.id = la.tech_id
LEFT JOIN today_plan tp ON u.id = tp.tech_id
WHERE u.is_deleted = false
ORDER BY remaining_today DESC;

-- ===========================================================================
-- PART C: CANDIDATE RANKING FOR AD-HOC DISPATCH
-- Input: Target location (lat, lng) + Time Window
-- Output: Top 3 techs with scoring breakdown
-- ===========================================================================

-- Parameters (replace with actual values):
-- :target_lat = target location latitude
-- :target_lng = target location longitude
-- :time_window_start = earliest acceptable time (e.g., '18:00' for F&B)
-- :time_window_end = latest acceptable time (e.g., '22:00' for F&B)

WITH tech_last_location AS (
    SELECT 
        v.id_user as tech_id,
        v.latitude as last_lat,
        v.longitude as last_lng,
        v.check_in as last_seen,
        v.check_out
    FROM t_visit v
    WHERE v.check_in::date = CURRENT_DATE
      AND v.latitude IS NOT NULL
    ORDER BY v.id_user, v.check_in DESC
),
tech_location_dedup AS (
    SELECT DISTINCT ON (tech_id) *
    FROM tech_last_location
    ORDER BY tech_id, last_seen DESC
),
tech_load AS (
    SELECT 
        rp.id_user as tech_id,
        COUNT(*) as remaining_jobs
    FROM t_road_plan rp
    LEFT JOIN t_visit v ON rp.id = v.id_road_plan
    WHERE rp.visit_date::date = CURRENT_DATE
      AND rp.is_cancel = false
      AND v.id IS NULL
    GROUP BY rp.id_user
),
candidate_scores AS (
    SELECT 
        u.id as tech_id,
        u.fullname as tech_name,
        tloc.last_lat,
        tloc.last_lng,
        tloc.check_out,
        COALESCE(tl.remaining_jobs, 0) as remaining_jobs,
        
        -- Distance Score (Haversine approximation for nearby)
        -- Lower distance = Higher score (max 40 points)
        -- Formula: 40 - (distance_km * 2), capped at 0
        GREATEST(0, 40 - (
            SQRT(
                POWER((tloc.last_lat - (-7.2575)) * 111, 2) + 
                POWER((tloc.last_lng - (112.7521)) * 111 * COS(RADIANS(-7.2575)), 2)
            ) * 2
        )) as distance_score,
        
        -- Availability Score (max 30 points)
        -- Already checked out = 30, still working = 10, done for day = 20
        CASE 
            WHEN tloc.check_out IS NOT NULL THEN 30
            WHEN tloc.check_out IS NULL AND tloc.last_lat IS NOT NULL THEN 10
            ELSE 20
        END as availability_score,
        
        -- Workload Score (max 30 points)
        -- Lower remaining = Higher score
        GREATEST(0, 30 - (COALESCE(tl.remaining_jobs, 0) * 5)) as workload_score
        
    FROM p_user u
    LEFT JOIN tech_location_dedup tloc ON u.id = tloc.tech_id
    LEFT JOIN tech_load tl ON u.id = tl.tech_id
    WHERE u.is_deleted = false
)
SELECT 
    tech_id,
    tech_name,
    remaining_jobs,
    ROUND(distance_score::numeric, 1) as dist_score,
    availability_score as avail_score,
    workload_score as load_score,
    ROUND((distance_score + availability_score + workload_score)::numeric, 1) as total_score,
    -- Explainability
    CASE 
        WHEN distance_score >= 35 THEN 'Very Close'
        WHEN distance_score >= 25 THEN 'Close'
        WHEN distance_score >= 15 THEN 'Moderate'
        ELSE 'Far'
    END as proximity_reason,
    CASE 
        WHEN availability_score = 30 THEN 'Available (Checked Out)'
        WHEN availability_score = 20 THEN 'Free (Done for Day)'
        ELSE 'Busy (Working)'
    END as availability_reason
FROM candidate_scores
WHERE (distance_score + availability_score + workload_score) > 0
ORDER BY total_score DESC
LIMIT 3;

-- ===========================================================================
-- PART D: TIME WINDOW CONSTRAINTS (F&B vs Residential)
-- ===========================================================================

-- F&B Constraint: Visits should be after 18:00 (dinner prep)
-- Residential: Visits should be 09:00-17:00 (when people home)

-- Query: Check if tech is available in specific time window
-- Add to candidate_scores CTE:
/*
AND EXTRACT(HOUR FROM NOW()) BETWEEN 
    CASE 
        WHEN :customer_type = 'F&B' THEN 18 
        ELSE 9 
    END 
    AND 
    CASE 
        WHEN :customer_type = 'F&B' THEN 22 
        ELSE 17 
    END
*/

-- ===========================================================================
-- PART E: DISPATCH OUTPUT FORMAT
-- ===========================================================================

-- Final output structure for dispatch recommendation:
/*
{
    "request_id": "DISPATCH-20260120-001",
    "target_location": {"lat": -7.2575, "lng": 112.7521},
    "customer_type": "F&B",
    "time_window": "18:00-22:00",
    "recommendations": [
        {
            "rank": 1,
            "tech_id": 42,
            "tech_name": "Herryanto",
            "total_score": 85.0,
            "reasons": [
                "Very Close (3.2 km away)",
                "Available (Just finished last job)",
                "Light workload (1 remaining job)"
            ],
            "eta_minutes": 15
        },
        ...
    ]
}
*/
