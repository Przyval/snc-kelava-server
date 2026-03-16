-- KIL Analytics Database Schema (PostgreSQL)
-- Optimized for concurrency and JSONB operations

-- 1. Sync State (Cursor Tracking)
CREATE TABLE IF NOT EXISTS sync_state (
    id SERIAL PRIMARY KEY,
    stream_name VARCHAR(50) NOT NULL UNIQUE,
    last_cursor BIGINT NOT NULL DEFAULT 0,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    row_count BIGINT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Outbox Events (Staging with Idempotency)
CREATE TABLE IF NOT EXISTS outbox_events (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,
    event_type VARCHAR(100) NOT NULL,
    source_system VARCHAR(50) NOT NULL,
    external_id VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, sent, failed
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events(status);
CREATE INDEX IF NOT EXISTS idx_outbox_created ON outbox_events(created_at);

-- 3. Normalized Events (Source of Truth)
CREATE TABLE IF NOT EXISTS events_norm (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    source_system VARCHAR(50) NOT NULL,
    external_id VARCHAR(100) NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE,
    payload JSONB NOT NULL,
    context JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (event_type, external_id)
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events_norm(event_type);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON events_norm(occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_payload ON events_norm USING gin (payload);

-- 4. Issues (Rule Engine Output)
CREATE TABLE IF NOT EXISTS issues (
    id BIGSERIAL PRIMARY KEY,
    issue_key VARCHAR(100) NOT NULL UNIQUE, -- Dedup key (e.g. photo_missing:123)
    issue_type VARCHAR(50) NOT NULL,        -- photo_missing, late_checkout
    severity VARCHAR(20) NOT NULL,          -- low, medium, high, critical
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'open',      -- open, resolved, ignored
    context JSONB,                          -- Snapshot data when issue created
    source_event_id BIGINT,                 -- Link to triggering event
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);
CREATE INDEX IF NOT EXISTS idx_issues_type ON issues(issue_type);

-- 5. Decision Log (Audit Trail)
CREATE TABLE IF NOT EXISTS decision_log (
    id BIGSERIAL PRIMARY KEY,
    decision_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(100),
    action_taken VARCHAR(50) NOT NULL,
    reason TEXT,
    actor VARCHAR(100) DEFAULT 'system',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Helper Tables for Rules
CREATE TABLE IF NOT EXISTS foto_cache (
    road_plan_id BIGINT PRIMARY KEY,
    foto_count INTEGER DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE
);

-- GPS Positions (Cache)
CREATE TABLE IF NOT EXISTS gps_positions (
    id SERIAL PRIMARY KEY,
    internal_id INTEGER NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_gps_internal_id_time ON gps_positions(internal_id, captured_at DESC);

-- Views

-- Active Issues
CREATE OR REPLACE VIEW v_open_issues AS
SELECT * 
FROM issues 
WHERE status = 'open' 
ORDER BY 
    CASE severity 
        WHEN 'critical' THEN 1 
        WHEN 'high' THEN 2 
        WHEN 'medium' THEN 3 
        ELSE 4 
    END,
    created_at DESC;

-- Daily Event Summary
CREATE OR REPLACE VIEW v_events_summary AS
SELECT 
    DATE(occurred_at AT TIME ZONE 'Asia/Jakarta') as event_date,
    event_type, 
    COUNT(*) as total
FROM events_norm
GROUP BY 1, 2
ORDER BY 1 DESC;

-- 7. Technician Issues (Escalation Policy Layer)
CREATE TABLE IF NOT EXISTS technician_issues (
    id BIGSERIAL PRIMARY KEY,
    technician_id INTEGER NOT NULL,
    issue_type VARCHAR(50) NOT NULL,           -- 'low_volume', 'slow_duration', 'low_completion', 'protocol_violation'
    severity VARCHAR(20) DEFAULT 'review',     -- 'review', 'warning', 'escalated'
    status VARCHAR(20) DEFAULT 'open',         -- 'open', 'resolved'
    context JSONB,                             -- Snapshot data when issue created
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    escalated_at TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution_type VARCHAR(30),               -- 'resolved', 'acknowledged', 'deferred', 'false_positive'
    resolution_note TEXT,
    resolved_by INTEGER,
    auto_escalated BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_tech_issues_tech ON technician_issues(technician_id);
CREATE INDEX IF NOT EXISTS idx_tech_issues_status ON technician_issues(status);
CREATE INDEX IF NOT EXISTS idx_tech_issues_severity ON technician_issues(severity);

-- 8. Issue Actions (Audit Trail for Escalation)
CREATE TABLE IF NOT EXISTS issue_actions (
    id BIGSERIAL PRIMARY KEY,
    issue_id BIGINT REFERENCES technician_issues(id) ON DELETE CASCADE,
    action_type VARCHAR(30) NOT NULL,          -- 'created', 'escalated', 'auto_escalated', 'resolved', 'note_added'
    actor_id INTEGER,
    actor_name VARCHAR(100),
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_issue_actions_issue ON issue_actions(issue_id);

-- View: Open Technician Issues by Severity
CREATE OR REPLACE VIEW v_technician_issues_open AS
SELECT 
    ti.*,
    t.name as technician_name,
    t.email as technician_email,
    EXTRACT(EPOCH FROM (NOW() - ti.created_at)) / 3600 as hours_open
FROM technician_issues ti
LEFT JOIN technicians t ON t.id = ti.technician_id
WHERE ti.status = 'open'
ORDER BY 
    CASE ti.severity 
        WHEN 'escalated' THEN 1 
        WHEN 'warning' THEN 2 
        WHEN 'review' THEN 3 
    END,
    ti.created_at DESC;
