-- Action & Decision Engine Views (Phase 10)
-- Version: 2026-02-10
-- Adapted for Kelava Schema

-- 1. Base Metrics View
CREATE OR REPLACE VIEW v_customer_service_metrics AS
WITH last_completed AS (
    SELECT
        rp.id_customer,
        MAX(v.realization_date) as last_completed_visit_at
    FROM t_visit v
    JOIN t_road_plan rp ON rp.id = v.id_road_plan
    WHERE rp.status = 'Selesai'
    GROUP BY rp.id_customer
),
active_contract AS (
    SELECT
        k.id_customer,
        BOOL_OR(UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE') AND CURRENT_DATE BETWEEN k.start_date AND k.end_date) as has_active_contract,
        MAX(CASE WHEN UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE') THEN k.end_date END) as active_contract_end,
        -- Default value if no column exists, or use logic
        MAX(CASE WHEN UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE') THEN 5000000 ELSE 0 END) as value_monthly
    FROM m_customer_kontrak k
    GROUP BY k.id_customer
),
open_complaint AS (
    SELECT
        og.id_customer,
        BOOL_OR(og.review_status = 'OPEN') as open_complaint
    FROM operational_governance og
    GROUP BY og.id_customer
),
visit_freq AS (
    SELECT
        rp.id_customer,
        COUNT(*) as visits_30d
    FROM t_visit v
    JOIN t_road_plan rp ON rp.id = v.id_road_plan
    WHERE v.realization_date >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY rp.id_customer
)
SELECT
    c.id as customer_id,
    c.name,
    -- c.created_at removed as it does not exist in m_customer
    CASE
        WHEN vf.visits_30d >= 3 THEN 'WEEKLY'
        WHEN vf.visits_30d >= 1 THEN 'MONTHLY'
        ELSE 'AD_HOC'
    END as service_frequency,
    CASE
        WHEN vf.visits_30d >= 3 THEN 7
        WHEN vf.visits_30d >= 1 THEN 30
        ELSE 30
    END as expected_cycle_days,
    lc.last_completed_visit_at,
    COALESCE(ac.has_active_contract, FALSE) as has_active_contract,
    COALESCE(ac.value_monthly, 0) as value_monthly,
    COALESCE(oc.open_complaint, FALSE) as open_complaint,
    GREATEST(
        0,
        FLOOR(EXTRACT(EPOCH FROM (NOW() - COALESCE(lc.last_completed_visit_at, NOW() - INTERVAL '999 days'))) / 86400)
    )::int as days_since_last_visit
FROM m_customer c
LEFT JOIN last_completed lc ON lc.id_customer = c.id
LEFT JOIN active_contract ac ON ac.id_customer = c.id
LEFT JOIN open_complaint oc ON oc.id_customer = c.id
LEFT JOIN visit_freq vf ON vf.id_customer = c.id;

-- 2. Account Status View
CREATE OR REPLACE VIEW v_customer_account_status AS
SELECT
    m.*,
    (m.days_since_last_visit::numeric / NULLIF(m.expected_cycle_days, 0)) as recency_ratio,
    GREATEST(0, FLOOR((m.days_since_last_visit::numeric / NULLIF(m.expected_cycle_days, 0)) - 1))::int as missed_cycles,
    CASE
        WHEN m.has_active_contract = FALSE AND m.days_since_last_visit >= 60 THEN 'DORMANT'
        WHEN m.has_active_contract = FALSE THEN 'INACTIVE'
        WHEN m.open_complaint = TRUE THEN 'AT_RISK'
        WHEN (m.days_since_last_visit::numeric / NULLIF(m.expected_cycle_days, 0)) > 1.0 THEN 'AT_RISK'
        ELSE 'UNDER_SLA'
    END as account_status
FROM v_customer_service_metrics m;

-- 3. RF Scores View
CREATE OR REPLACE VIEW v_customer_rf_scores AS
SELECT
    a.*,
    CASE
        WHEN a.recency_ratio <= 1.0 THEN 5
        WHEN a.recency_ratio <= 1.5 THEN 4
        WHEN a.recency_ratio <= 2.0 THEN 3
        WHEN a.recency_ratio <= 3.0 THEN 2
        ELSE 1
    END as r_score,
    CASE a.service_frequency
        WHEN 'WEEKLY' THEN 5
        WHEN 'MONTHLY' THEN 3
        WHEN 'QUARTERLY' THEN 2
        WHEN 'AD_HOC' THEN 1
        ELSE 2
    END as f_score
FROM v_customer_account_status a;

-- 4. M Score View (Simulated Complexity)
CREATE OR REPLACE VIEW v_customer_m_score AS
SELECT
    r.*,
    -- Simulating value score based on hardcoded ranges
    CASE
        WHEN r.value_monthly >= 15000000 THEN 5
        WHEN r.value_monthly >= 8000000  THEN 4
        WHEN r.value_monthly >= 3000000  THEN 3
        WHEN r.value_monthly >= 1000000  THEN 2
        ELSE 1
    END as value_score,
    -- Simulating complexity score (using name keywords as proxy for missing column)
    CASE
        WHEN r.name ILIKE '%HOTEL%' OR r.name ILIKE '%PABRIK%' OR r.name ILIKE '%INDUSTRY%' THEN 5
        WHEN r.name ILIKE '%OFFICE%' OR r.name ILIKE '%RESTORAN%' OR r.name ILIKE '%RUMAH SAKIT%' THEN 3
        ELSE 2
    END as complexity_score
FROM v_customer_rf_scores r;

-- 5. RFM Segment View
CREATE OR REPLACE VIEW v_customer_rfm_segment AS
WITH scored AS (
    SELECT 
        *,
        -- Weighted M Score (70% Value + 30% Complexity)
        ROUND(
            (0.7 * value_score) + (0.3 * complexity_score), 1
        ) as m_raw
    FROM v_customer_m_score
),
final_m AS (
    SELECT
        *,
        CASE
            WHEN m_raw >= 4.5 THEN 5
            WHEN m_raw >= 3.5 THEN 4
            WHEN m_raw >= 2.5 THEN 3
            WHEN m_raw >= 1.5 THEN 2
            ELSE 1
        END as m_score
    FROM scored
)
SELECT
    m.*,
    (m.r_score::text || '-' || m.f_score::text || '-' || m.m_score::text) as rfm_vector,
    CASE
        -- Tier 1: High-value, high-engagement, on-track
        WHEN m.r_score >= 4 AND m.f_score >= 4 AND m.m_score >= 4 THEN 'REVENUE_CORE'
        -- Tier 2: High-value but slipping (MUST check before STABLE_CORE)
        WHEN m.r_score <= 2 AND m.m_score >= 4 THEN 'REVENUE_RISK'
        -- Tier 3: Mid-value, on-track
        WHEN m.r_score >= 3 AND m.f_score >= 3 AND m.m_score >= 3 THEN 'STABLE_CORE'
        -- Tier 4: Good recency, low frequency, mid+ value - upsell target
        WHEN m.r_score >= 3 AND m.f_score <= 2 AND m.m_score >= 3 THEN 'GROWTH'
        -- Tier 5: Dead accounts (no recency + no frequency)
        WHEN m.r_score = 1 AND m.f_score = 1 THEN 'CHURNED'
        -- Tier 6: Low monetary value (regardless of frequency)
        WHEN m.m_score <= 2 THEN 'LOW_VALUE'
        -- Fallback: Has some signals but does not fit above
        ELSE 'GROWTH'
    END as rfm_segment
FROM final_m m;

-- 6. Priority & Action View (Final Interface)
-- Priority cascade: P0 > P1 > P3 > P2 (P3 checked before P2 catch-all)
CREATE OR REPLACE VIEW v_customer_priority_action AS
SELECT
    s.*,
    CASE
        -- P0: CRITICAL - immediate supervisor attention
        WHEN s.open_complaint = TRUE AND s.rfm_segment IN ('REVENUE_CORE','REVENUE_RISK') THEN 'P0'
        WHEN s.account_status = 'AT_RISK' AND s.rfm_segment = 'REVENUE_CORE' AND s.missed_cycles >= 1 THEN 'P0'
        -- P1: IMPORTANT - proactive protection / winback
        WHEN s.account_status = 'DORMANT' AND s.rfm_segment = 'REVENUE_RISK' THEN 'P1'
        WHEN s.account_status = 'UNDER_SLA' AND s.rfm_segment = 'REVENUE_CORE' THEN 'P1'
        WHEN s.open_complaint = TRUE THEN 'P1'
        -- P3: LOW - batch only (MUST check before P2 catch-all)
        WHEN s.rfm_segment IN ('LOW_VALUE', 'CHURNED') THEN 'P3'
        -- P2: NORMAL - standard ops / growth
        ELSE 'P2'
    END as priority,

    CASE
        WHEN s.open_complaint = TRUE AND s.rfm_segment IN ('REVENUE_CORE','REVENUE_RISK') THEN 'OPS_SUPERVISOR'
        WHEN s.account_status = 'AT_RISK' AND s.rfm_segment = 'REVENUE_CORE' AND s.missed_cycles >= 1 THEN 'OPS_SUPERVISOR'
        WHEN s.account_status = 'DORMANT' AND s.rfm_segment = 'REVENUE_RISK' THEN 'SALES_CS'
        WHEN s.account_status = 'UNDER_SLA' AND s.rfm_segment = 'REVENUE_CORE' THEN 'OPS'
        WHEN s.open_complaint = TRUE THEN 'OPS'
        WHEN s.rfm_segment = 'GROWTH' THEN 'SALES'
        WHEN s.rfm_segment IN ('LOW_VALUE', 'CHURNED') THEN 'SYSTEM'
        ELSE 'OPS'
    END as owner,

    CASE
        WHEN s.open_complaint = TRUE AND s.rfm_segment IN ('REVENUE_CORE','REVENUE_RISK') THEN '🧯 Handle complaint + assign senior tech'
        WHEN s.account_status = 'AT_RISK' AND s.rfm_segment = 'REVENUE_CORE' AND s.missed_cycles >= 1 THEN '📞 Supervisor follow-up + reschedule'
        WHEN s.account_status = 'DORMANT' AND s.rfm_segment = 'REVENUE_RISK' THEN '↻ Winback call + offer reactivation'
        WHEN s.account_status = 'UNDER_SLA' AND s.rfm_segment = 'REVENUE_CORE' THEN '🛡️ Monitor SLA (early warning)'
        WHEN s.open_complaint = TRUE THEN '📋 Handle complaint'
        WHEN s.rfm_segment = 'GROWTH' THEN '💡 Offer monthly/quarterly contract'
        WHEN s.rfm_segment IN ('LOW_VALUE', 'CHURNED') AND s.account_status = 'DORMANT' THEN '📦 Batch campaign only'
        WHEN s.rfm_segment IN ('LOW_VALUE', 'CHURNED') THEN '📦 Low priority - batch review'
        WHEN s.account_status = 'AT_RISK' THEN '📅 Schedule visit urgently'
        ELSE '📅 Schedule visit'
    END as suggested_action,

    CASE
        WHEN (s.open_complaint = TRUE AND s.rfm_segment IN ('REVENUE_CORE','REVENUE_RISK')) OR (s.account_status = 'AT_RISK' AND s.rfm_segment = 'REVENUE_CORE' AND s.missed_cycles >= 1) THEN 'CRITICAL'
        WHEN (s.account_status = 'UNDER_SLA' AND s.rfm_segment = 'REVENUE_CORE') THEN 'PROTECT'
        WHEN (s.account_status = 'DORMANT' AND s.rfm_segment = 'REVENUE_RISK') THEN 'WINBACK'
        WHEN s.rfm_segment = 'GROWTH' THEN 'GROWTH'
        WHEN s.rfm_segment IN ('LOW_VALUE', 'CHURNED') THEN 'LOW'
        ELSE 'NORMAL'
    END as ui_badge,

    CASE
        WHEN s.open_complaint = TRUE THEN 'Open complaint'
        WHEN s.missed_cycles >= 1 THEN ('Missed ' || s.missed_cycles || ' cycle(s)')
        WHEN s.account_status = 'DORMANT' THEN ('Dormant ' || s.days_since_last_visit || 'd')
        WHEN s.account_status = 'INACTIVE' AND s.has_active_contract = FALSE THEN 'No active contract'
        WHEN s.account_status = 'AT_RISK' THEN 'Approaching SLA deadline'
        WHEN s.account_status = 'UNDER_SLA' THEN 'On track'
        ELSE 'On track'
    END as reason
FROM v_customer_rfm_segment s;
