-- Migration 006: Contract Churn Reasons + Complaint Links
-- Meeting: "kontrak expired... ada reason-nya nggak? Belum. Karena belum nyambung ke komplain"

-- Contract churn/non-renewal reasons
CREATE TABLE IF NOT EXISTS contract_churn_reasons (
    id BIGSERIAL PRIMARY KEY,
    contract_id BIGINT NOT NULL,         -- m_customer_kontrak.id
    reason_category TEXT NOT NULL,        -- 'service_quality', 'price', 'competitor', 'business_closed', 'relocation', 'other'
    reason_detail TEXT,
    linked_complaint_ids BIGINT[],        -- array of complaint_tickets IDs
    decided_by BIGINT,                    -- enterprise_users.id
    decided_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_churn_contract ON contract_churn_reasons(contract_id);

-- Complaint tickets table (if not exists)
CREATE TABLE IF NOT EXISTS complaint_tickets (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL,         -- m_customer.id
    contract_id BIGINT,                  -- m_customer_kontrak.id (optional)
    title TEXT NOT NULL,
    description TEXT,
    severity TEXT DEFAULT 'medium',       -- 'low', 'medium', 'high', 'critical'
    status TEXT DEFAULT 'open',           -- 'open', 'in_progress', 'resolved', 'closed'
    category TEXT,                       -- 'service', 'billing', 'quality', 'scheduling', 'other'
    assigned_to BIGINT,                  -- p_user.id (technician)
    reported_by TEXT,                    -- free text: customer contact name
    resolution TEXT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by BIGINT,                  -- enterprise_users.id
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_complaint_customer ON complaint_tickets(customer_id);
CREATE INDEX IF NOT EXISTS idx_complaint_status ON complaint_tickets(status);
CREATE INDEX IF NOT EXISTS idx_complaint_contract ON complaint_tickets(contract_id);

-- KPI Monthly Archive (Phase 3.1)
CREATE TABLE IF NOT EXISTS kpi_monthly_archive (
    id BIGSERIAL PRIMARY KEY,
    technician_id BIGINT NOT NULL,       -- p_user.id
    year_month TEXT NOT NULL,            -- '2026-01', '2025-12' etc
    total_planned INT DEFAULT 0,
    total_completed INT DEFAULT 0,
    total_visits INT DEFAULT 0,
    active_days INT DEFAULT 0,
    visits_per_day NUMERIC(5,1) DEFAULT 0,
    completion_rate NUMERIC(5,1) DEFAULT 0,
    avg_duration_min NUMERIC(6,1) DEFAULT 0,
    on_time_rate NUMERIC(5,1) DEFAULT 0,
    grade TEXT,                          -- A/B/C/D
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(technician_id, year_month)
);

CREATE INDEX IF NOT EXISTS idx_kpi_archive_tech ON kpi_monthly_archive(technician_id);
CREATE INDEX IF NOT EXISTS idx_kpi_archive_month ON kpi_monthly_archive(year_month);
