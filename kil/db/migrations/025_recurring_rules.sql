-- Migration 025: Manual Recurring Rules per Customer
-- Phase 1 Day 1 of Scheduler Implementation Plan
-- Purpose: Override pattern detection dengan recurring rules eksplisit
--          untuk Tier A/B customer yang predictable

-- ── Main table: Recurring rules per customer ─────────────────────────────────
CREATE TABLE IF NOT EXISTS snc_recurring_rules (
    id                  SERIAL PRIMARY KEY,
    client_id           INTEGER NOT NULL,

    -- Tech assignment (historical pairing — naturally stable)
    primary_tech_id     INTEGER,                  -- Required: main tech
    backup_tech_1_id    INTEGER,                  -- Optional: backup if primary unavailable
    backup_tech_2_id    INTEGER,                  -- Optional: second backup

    -- Frequency definition
    frequency           VARCHAR(20) NOT NULL,     -- weekly|biweekly|monthly|custom
    weekdays            INTEGER[] NOT NULL,       -- [0]=Mon only, [0,3]=Mon+Thu (multi-DOW)
    week_pattern        VARCHAR(50),              -- NULL for weekly, '1,3'/'2,4'/'1,3,5' for biweekly/monthly
                                                  -- 'cadence:YYYY-MM-DD' = projection anchor

    -- Time slot
    time_start          TIME NOT NULL,
    time_end            TIME,
    visit_type          VARCHAR(20),              -- PRC|PC|RC|S-OUT|MIST

    -- Behavior flags
    is_mandatory        BOOLEAN DEFAULT true,     -- true = override pattern detection
                                                  -- false = use as hint, pattern wins
    suppress_holiday    BOOLEAN DEFAULT true,     -- false = generate even on libur
    duration_minutes    INTEGER,                  -- Expected duration

    -- Operational metadata
    notes               TEXT,
    effective_start     DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_end       DATE,                     -- NULL = ongoing

    -- Audit
    created_by          INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_by          INTEGER,
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    -- Constraint: 1 active rule per (client, effective_start)
    UNIQUE(client_id, effective_start)
);

CREATE INDEX IF NOT EXISTS idx_rr_client ON snc_recurring_rules(client_id);
CREATE INDEX IF NOT EXISTS idx_rr_active ON snc_recurring_rules(effective_start, effective_end);
CREATE INDEX IF NOT EXISTS idx_rr_primary_tech ON snc_recurring_rules(primary_tech_id);
CREATE INDEX IF NOT EXISTS idx_rr_freq ON snc_recurring_rules(frequency) WHERE effective_end IS NULL;

-- ── Audit log: track perubahan rule (untuk debugging + accountability) ───────
CREATE TABLE IF NOT EXISTS snc_recurring_rule_log (
    id                  SERIAL PRIMARY KEY,
    rule_id             INTEGER,
    action              VARCHAR(20) NOT NULL,     -- created|updated|deactivated|reactivated
    changed_fields      JSONB,                    -- {"old": {...}, "new": {...}}
    reason              TEXT,
    changed_by          INTEGER,
    changed_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rrl_rule ON snc_recurring_rule_log(rule_id);
CREATE INDEX IF NOT EXISTS idx_rrl_changed_at ON snc_recurring_rule_log(changed_at);

-- ── View: Active rules dengan info customer + tech ──────────────────────────
CREATE OR REPLACE VIEW snc_active_recurring_rules AS
SELECT
    r.id,
    r.client_id,
    c.name AS client_name,
    r.primary_tech_id,
    t1.name AS primary_tech_name,
    r.backup_tech_1_id,
    t2.name AS backup_tech_1_name,
    r.backup_tech_2_id,
    t3.name AS backup_tech_2_name,
    r.frequency,
    r.weekdays,
    r.week_pattern,
    r.time_start,
    r.time_end,
    r.visit_type,
    r.is_mandatory,
    r.suppress_holiday,
    r.notes,
    r.effective_start,
    r.effective_end,
    r.created_at,
    r.updated_at
FROM snc_recurring_rules r
JOIN snc_clients c ON c.id = r.client_id
LEFT JOIN snc_technicians t1 ON t1.id = r.primary_tech_id
LEFT JOIN snc_technicians t2 ON t2.id = r.backup_tech_1_id
LEFT JOIN snc_technicians t3 ON t3.id = r.backup_tech_2_id
WHERE r.effective_start <= CURRENT_DATE
  AND (r.effective_end IS NULL OR r.effective_end >= CURRENT_DATE)
ORDER BY c.name;

COMMENT ON TABLE snc_recurring_rules IS
'Manual recurring rules untuk customer Tier A/B predictable.
 Override pattern detection bila is_mandatory=true.
 Stable tech pairing (historical) — primary+backup_1+backup_2.';

COMMENT ON COLUMN snc_recurring_rules.weekdays IS
'Array of weekday: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat.
 Multi-DOW supported: [0,3] = Mon+Thu setiap minggu.';

COMMENT ON COLUMN snc_recurring_rules.week_pattern IS
'Format options:
 - NULL atau "all" = weekly (semua minggu)
 - "1,3" = biweekly minggu ke-1 dan ke-3
 - "2,4" = biweekly minggu ke-2 dan ke-4
 - "1,3,5" = biweekly + minggu 5 jika ada
 - "cadence:YYYY-MM-DD" = anchor untuk projection (sama seperti pattern)';
