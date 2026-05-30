-- Migration 029: Schedule Conflicts + Audit Log
-- PRD §24.3 + §24.4
-- Schedule Draft Calendar v1.0

-- ── Conflicts table ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS snc_schedule_conflicts (
    id                     SERIAL PRIMARY KEY,
    draft_batch_id         INTEGER NOT NULL,
    conflict_group_id      VARCHAR(50),

    -- Conflict classification
    conflict_type          VARCHAR(40) NOT NULL,    -- double_booking, overlap, capacity_exceeded,
                                                    -- uncovered_customer, holiday_exception,
                                                    -- missing_backup, route_warning
    severity               VARCHAR(10) NOT NULL,    -- high, medium, low

    -- Affected entities
    visit_a_id             INTEGER,                  -- snc_schedule_events.id
    visit_b_id             INTEGER,                  -- nullable: untuk capacity/uncovered
    technician_id          INTEGER,
    client_id              INTEGER,

    -- Time window
    visit_date             DATE NOT NULL,
    time_start             TIME,
    time_end               TIME,

    -- Issue & resolution
    issue_description      TEXT,
    suggested_fix_type     VARCHAR(40),              -- reassign_backup, move_time,
                                                     -- mark_exception, split_covisit, cancel
    suggested_fix_payload  JSONB,

    -- Status tracking
    status                 VARCHAR(20) DEFAULT 'open',  -- open, resolved, ignored, needs_manual_review
    resolved_by            INTEGER,
    resolved_at            TIMESTAMPTZ,
    resolution_notes       TEXT,

    created_at             TIMESTAMPTZ DEFAULT NOW(),
    updated_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sc_batch ON snc_schedule_conflicts(draft_batch_id);
CREATE INDEX IF NOT EXISTS idx_sc_status ON snc_schedule_conflicts(status);
CREATE INDEX IF NOT EXISTS idx_sc_date ON snc_schedule_conflicts(visit_date);
CREATE INDEX IF NOT EXISTS idx_sc_open ON snc_schedule_conflicts(draft_batch_id, status)
    WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_sc_tech ON snc_schedule_conflicts(technician_id);

COMMENT ON TABLE snc_schedule_conflicts IS
'Conflict detection per draft batch. PRD §17, §18, §24.3.
 Re-generated saat draft generate / fix apply.';

-- ── Audit log untuk schedule actions ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS snc_schedule_audit_log (
    id                  SERIAL PRIMARY KEY,
    draft_batch_id      INTEGER,
    event_id            INTEGER,                   -- snc_schedule_events.id
    conflict_id         INTEGER,                   -- snc_schedule_conflicts.id

    action              VARCHAR(40) NOT NULL,
    -- draft_generated, event_edited, conflict_detected, conflict_resolved,
    -- visit_approved, day_approved, clean_days_approved, schedule_published,
    -- publish_blocked, manual_exception_created, conflict_ignored

    old_value           JSONB,
    new_value           JSONB,
    reason              TEXT,
    changed_by          INTEGER DEFAULT 0,
    changed_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sal_batch ON snc_schedule_audit_log(draft_batch_id);
CREATE INDEX IF NOT EXISTS idx_sal_event ON snc_schedule_audit_log(event_id);
CREATE INDEX IF NOT EXISTS idx_sal_action ON snc_schedule_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_sal_when ON snc_schedule_audit_log(changed_at DESC);

-- ── Extend snc_schedule_events untuk PRD support ────────────────────────────
ALTER TABLE snc_schedule_events
    ADD COLUMN IF NOT EXISTS source           VARCHAR(20) DEFAULT 'pattern',  -- rule|pattern|manual
    ADD COLUMN IF NOT EXISTS issue_type       VARCHAR(40),
    ADD COLUMN IF NOT EXISTS conflict_group_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS rule_id          INTEGER,
    ADD COLUMN IF NOT EXISTS pattern_id       INTEGER,
    ADD COLUMN IF NOT EXISTS is_mandatory     BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS is_holiday_skipped BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS approved_at      TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS approved_by      INTEGER,
    ADD COLUMN IF NOT EXISTS published_at     TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_sse_source ON snc_schedule_events(source);
CREATE INDEX IF NOT EXISTS idx_sse_batch_date ON snc_schedule_events(draft_batch_id, start_date);

-- ── Extend snc_draft_batches untuk PRD support ──────────────────────────────
ALTER TABLE snc_draft_batches
    ADD COLUMN IF NOT EXISTS conflict_count   INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS approved_count   INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_count  INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS published_by     INTEGER;

-- Status expansion (existing has draft|approved, add more)
-- generated, in_review, partially_approved, approved, published, cancelled

-- ── Update existing draft events: tag source 'rule' kalau dari recurring_rules
-- (Rule rows have notes LIKE 'Rule | ...', Pattern rows have notes LIKE 'Draft v4 | ...')
UPDATE snc_schedule_events
SET source = CASE
    WHEN notes LIKE 'Rule |%' THEN 'rule'
    WHEN notes LIKE 'Auto-generated%' OR notes LIKE 'Draft v%' THEN 'pattern'
    ELSE COALESCE(source, 'pattern')
END
WHERE schedule_status = 'draft' AND source = 'pattern';

-- ── View: Calendar summary per-day (PRD §25.2) ──────────────────────────────
CREATE OR REPLACE VIEW snc_calendar_day_summary AS
SELECT
    se.draft_batch_id,
    se.start_date AS visit_date,
    COUNT(*) AS total_visits,
    COUNT(*) FILTER (WHERE se.source = 'rule') AS rule_count,
    COUNT(*) FILTER (WHERE se.source = 'pattern') AS pattern_count,
    COUNT(*) FILTER (WHERE se.source = 'manual') AS manual_count,
    COUNT(*) FILTER (WHERE se.schedule_status = 'draft') AS draft_count,
    COUNT(*) FILTER (WHERE se.schedule_status = 'approved') AS approved_count,
    COUNT(*) FILTER (WHERE se.schedule_status = 'scheduled' AND se.published_at IS NOT NULL) AS published_count,
    COUNT(*) FILTER (WHERE se.is_holiday_skipped) AS holiday_skipped_count,
    (SELECT COUNT(*) FROM snc_schedule_conflicts sc
     WHERE sc.draft_batch_id = se.draft_batch_id
       AND sc.visit_date = se.start_date
       AND sc.status = 'open') AS conflict_count
FROM snc_schedule_events se
WHERE se.draft_batch_id IS NOT NULL
GROUP BY se.draft_batch_id, se.start_date;
