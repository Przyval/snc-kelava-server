-- ============================================================
-- Winback Engine Schema v1.0
-- SAP-Grade Campaign Management for Customer Recovery
-- ============================================================
-- Deploy: psql -h localhost -p 5433 -U snc_read -d sanocare -f winback_engine_v1.sql
-- ============================================================

-- 1. Winback Campaigns (Batch-level tracking)
CREATE TABLE IF NOT EXISTS winback_campaigns (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    target_segment VARCHAR(50),        -- CHURNED, DORMANT, LOW_VALUE, MIXED
    status VARCHAR(20) DEFAULT 'DRAFT', -- DRAFT, ACTIVE, COMPLETED, CANCELLED
    created_by INTEGER,                 -- p_user.id
    assigned_team VARCHAR(50),          -- SALES, SALES_CS, OPS
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_campaigns_status ON winback_campaigns(status);
CREATE INDEX IF NOT EXISTS idx_wb_campaigns_created ON winback_campaigns(created_at DESC);

-- 2. Winback Entries (Per-customer tracking within a campaign)
CREATE TABLE IF NOT EXISTS winback_entries (
    id BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL REFERENCES winback_campaigns(id) ON DELETE CASCADE,
    id_customer INTEGER NOT NULL,       -- m_customer.id
    assigned_to INTEGER,                -- p_user.id (Sales rep)
    status VARCHAR(30) DEFAULT 'PENDING',
        -- PENDING     → not yet contacted
        -- CONTACTED   → called/visited, awaiting response
        -- INTERESTED  → customer showed interest
        -- WON         → reactivated (new visit/contract scheduled)
        -- LOST        → customer declined
        -- NO_RESPONSE → no answer after max attempts
    priority VARCHAR(5),                -- from v_customer_priority_action
    rfm_segment VARCHAR(30),            -- snapshot at time of campaign creation
    days_dormant INTEGER,               -- snapshot
    last_visit_date DATE,               -- snapshot
    value_monthly NUMERIC(15,2),        -- snapshot
    contact_attempts INTEGER DEFAULT 0,
    contact_note TEXT,                  -- latest contact note
    contact_date TIMESTAMP WITH TIME ZONE,
    outcome_note TEXT,
    outcome_date TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(campaign_id, id_customer)
);

CREATE INDEX IF NOT EXISTS idx_wb_entries_campaign ON winback_entries(campaign_id);
CREATE INDEX IF NOT EXISTS idx_wb_entries_status ON winback_entries(status);
CREATE INDEX IF NOT EXISTS idx_wb_entries_customer ON winback_entries(id_customer);
CREATE INDEX IF NOT EXISTS idx_wb_entries_assigned ON winback_entries(assigned_to);

-- 3. Winback Activity Log (Immutable audit trail)
CREATE TABLE IF NOT EXISTS winback_activity_log (
    id BIGSERIAL PRIMARY KEY,
    entry_id BIGINT REFERENCES winback_entries(id) ON DELETE CASCADE,
    campaign_id BIGINT REFERENCES winback_campaigns(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,       -- CREATED, STATUS_CHANGE, NOTE_ADDED, ASSIGNED, CONTACT_ATTEMPT
    previous_status VARCHAR(30),
    new_status VARCHAR(30),
    actor_id INTEGER,
    actor_name VARCHAR(200),
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wb_activity_entry ON winback_activity_log(entry_id);
CREATE INDEX IF NOT EXISTS idx_wb_activity_campaign ON winback_activity_log(campaign_id);

-- 4. Summary View: Campaign Statistics
CREATE OR REPLACE VIEW v_winback_campaign_stats AS
SELECT
    c.id as campaign_id,
    c.name,
    c.status,
    c.target_segment,
    c.assigned_team,
    c.created_at,
    c.started_at,
    c.completed_at,
    COUNT(e.id) as total_entries,
    COUNT(e.id) FILTER (WHERE e.status = 'PENDING') as pending_count,
    COUNT(e.id) FILTER (WHERE e.status = 'CONTACTED') as contacted_count,
    COUNT(e.id) FILTER (WHERE e.status = 'INTERESTED') as interested_count,
    COUNT(e.id) FILTER (WHERE e.status = 'WON') as won_count,
    COUNT(e.id) FILTER (WHERE e.status = 'LOST') as lost_count,
    COUNT(e.id) FILTER (WHERE e.status = 'NO_RESPONSE') as no_response_count,
    ROUND(
        100.0 * COUNT(e.id) FILTER (WHERE e.status = 'WON')
        / NULLIF(COUNT(e.id), 0), 1
    ) as win_rate_pct,
    ROUND(
        100.0 * COUNT(e.id) FILTER (WHERE e.status IN ('CONTACTED','INTERESTED','WON','LOST','NO_RESPONSE'))
        / NULLIF(COUNT(e.id), 0), 1
    ) as contact_rate_pct,
    COALESCE(SUM(e.value_monthly) FILTER (WHERE e.status = 'WON'), 0) as recovered_value_monthly
FROM winback_campaigns c
LEFT JOIN winback_entries e ON e.campaign_id = c.id
GROUP BY c.id, c.name, c.status, c.target_segment, c.assigned_team,
         c.created_at, c.started_at, c.completed_at;

-- 5. View: Winback-eligible customers (not already in an active campaign)
CREATE OR REPLACE VIEW v_winback_eligible AS
SELECT
    pa.customer_id,
    pa.name,
    pa.rfm_segment,
    pa.account_status,
    pa.priority,
    pa.days_since_last_visit,
    pa.value_monthly,
    pa.has_active_contract,
    pa.suggested_action,
    pa.owner
FROM v_customer_priority_action pa
WHERE pa.rfm_segment IN ('CHURNED', 'LOW_VALUE', 'DORMANT')
   OR pa.account_status IN ('DORMANT', 'INACTIVE')
   -- Exclude customers already in an ACTIVE campaign
   AND pa.customer_id NOT IN (
       SELECT we.id_customer
       FROM winback_entries we
       JOIN winback_campaigns wc ON wc.id = we.campaign_id
       WHERE wc.status = 'ACTIVE'
         AND we.status NOT IN ('WON', 'LOST', 'NO_RESPONSE')
   );
