-- ===========================================================================
-- KIL (Kelava Intelligence Layer) Database Schema v1.0
-- Generated: 2026-02-05
-- Database: SQLite
-- ===========================================================================

-- ===========================================================================
-- TABLE: sync_state
-- Purpose: Track ingestion cursors for incremental sync
-- ===========================================================================
CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_name TEXT NOT NULL UNIQUE,
    last_cursor INTEGER NOT NULL DEFAULT 0,
    last_sync_at TIMESTAMP,
    row_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ===========================================================================
-- TABLE: outbox_events
-- Purpose: Staging area for events with idempotency guarantee
-- ===========================================================================
CREATE TABLE IF NOT EXISTS outbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    source_system TEXT NOT NULL DEFAULT 'kelava',
    external_id TEXT NOT NULL,
    payload TEXT NOT NULL,  -- JSON
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, sent, failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox_events(status);
CREATE INDEX IF NOT EXISTS idx_outbox_event_type ON outbox_events(event_type);
CREATE INDEX IF NOT EXISTS idx_outbox_created_at ON outbox_events(created_at);

-- ===========================================================================
-- TABLE: events_norm
-- Purpose: Normalized event store (source of truth for KIL)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS events_norm (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source_system TEXT NOT NULL DEFAULT 'kelava',
    external_id TEXT NOT NULL,
    occurred_at TIMESTAMP NOT NULL,
    payload TEXT NOT NULL,  -- JSON
    context TEXT,  -- JSON (additional metadata)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Dedupe key
    UNIQUE(event_type, external_id)
);

CREATE INDEX IF NOT EXISTS idx_events_event_type ON events_norm(event_type);
CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events_norm(occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_external_id ON events_norm(external_id);

-- ===========================================================================
-- TABLE: issues
-- Purpose: Auto-generated issues from rule engine
-- ===========================================================================
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_key TEXT NOT NULL UNIQUE,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',  -- low, medium, high, critical
    title TEXT NOT NULL,
    description TEXT,
    context TEXT,  -- JSON (road_plan_id, tech_id, etc.)
    source_event_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    resolved_by TEXT,
    resolution_notes TEXT,
    FOREIGN KEY (source_event_id) REFERENCES events_norm(id)
);

CREATE INDEX IF NOT EXISTS idx_issues_type ON issues(issue_type);
CREATE INDEX IF NOT EXISTS idx_issues_severity ON issues(severity);
CREATE INDEX IF NOT EXISTS idx_issues_resolved ON issues(resolved_at);
CREATE INDEX IF NOT EXISTS idx_issues_created ON issues(created_at);

-- ===========================================================================
-- TABLE: decision_log
-- Purpose: Audit trail for all decisions made by KIL
-- ===========================================================================
CREATE TABLE IF NOT EXISTS decision_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_type TEXT NOT NULL,
    decision_key TEXT NOT NULL,
    input_data TEXT NOT NULL,  -- JSON
    output_data TEXT NOT NULL,  -- JSON
    confidence_score REAL,
    decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decided_by TEXT DEFAULT 'kil_engine'
);

CREATE INDEX IF NOT EXISTS idx_decision_type ON decision_log(decision_type);
CREATE INDEX IF NOT EXISTS idx_decision_time ON decision_log(decided_at);

-- ===========================================================================
-- TABLE: foto_cache
-- Purpose: Cache foto counts per road_plan for rule evaluation
-- ===========================================================================
CREATE TABLE IF NOT EXISTS foto_cache (
    road_plan_id INTEGER PRIMARY KEY,
    foto_count INTEGER NOT NULL DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ===========================================================================
-- SEED DATA: Initial sync_state cursors
-- ===========================================================================
INSERT OR IGNORE INTO sync_state (stream_name, last_cursor, row_count) VALUES
    ('road_plan', 0, 0),
    ('visit', 0, 0),
    ('photo', 0, 0);

-- ===========================================================================
-- VIEW: v_open_issues
-- Purpose: Quick access to unresolved issues
-- ===========================================================================
CREATE VIEW IF NOT EXISTS v_open_issues AS
SELECT 
    id,
    issue_key,
    issue_type,
    severity,
    title,
    context,
    created_at,
    ROUND((JULIANDAY('now') - JULIANDAY(created_at)) * 24, 1) as hours_open
FROM issues
WHERE resolved_at IS NULL
ORDER BY 
    CASE severity 
        WHEN 'critical' THEN 1 
        WHEN 'high' THEN 2 
        WHEN 'medium' THEN 3 
        ELSE 4 
    END,
    created_at;

-- ===========================================================================
-- VIEW: v_events_summary
-- Purpose: Daily event counts by type
-- ===========================================================================
CREATE VIEW IF NOT EXISTS v_events_summary AS
SELECT 
    DATE(occurred_at) as event_date,
    event_type,
    COUNT(*) as event_count
FROM events_norm
GROUP BY DATE(occurred_at), event_type
ORDER BY event_date DESC, event_type;
