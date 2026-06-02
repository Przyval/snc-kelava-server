-- Migration 037: Absence Cascade
-- ──────────────────────────────────────────────────────────────────────────
-- PRD: Cascade waterfall ketika teknisi mobile cuti:
--   Level 1: Support tech (specialty match) cover same day
--   Level 2: Self-reschedule (mobile tetap pegang, geser hari ±7)
--   Level 3: Manual needed (no compatible option)

-- Event-level audit columns
ALTER TABLE snc_schedule_events
    ADD COLUMN IF NOT EXISTS original_start_date    DATE,
    ADD COLUMN IF NOT EXISTS original_technician_id BIGINT,
    ADD COLUMN IF NOT EXISTS reschedule_level       INT;   -- 1=backup, 2=self, 3=manual

-- Cascade decisions log (1 row per visit decision)
CREATE TABLE IF NOT EXISTS snc_absence_cascade_log (
    id                  BIGSERIAL PRIMARY KEY,
    absence_id          BIGINT REFERENCES snc_technician_day_status(id) ON DELETE CASCADE,
    original_event_id   BIGINT,                 -- snc_schedule_events.id (may be deleted later)
    new_event_id        BIGINT REFERENCES snc_schedule_events(id) ON DELETE SET NULL,
    cascade_level       INT NOT NULL,            -- 1 | 2 | 3
    decision            TEXT NOT NULL,           -- 'backup_assigned' | 'rescheduled' | 'manual_needed' | 'reverted'
    rationale           TEXT,                    -- "Fathur Rozek (general), load 0/5"
    original_tech_id    BIGINT,                  -- snapshot
    original_date       DATE,
    original_visit_type TEXT,
    original_client_id  BIGINT,
    new_tech_id         BIGINT,
    new_date            DATE,
    auto_applied        BOOLEAN DEFAULT false,
    decided_by          INT,
    decided_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cascade_log_absence
    ON snc_absence_cascade_log (absence_id, decided_at);

CREATE INDEX IF NOT EXISTS idx_cascade_log_orig_event
    ON snc_absence_cascade_log (original_event_id);
