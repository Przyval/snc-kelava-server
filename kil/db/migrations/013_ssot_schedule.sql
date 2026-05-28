-- Migration 013: SSOT Schedule Schema
-- Replaces ad-hoc snc_road_plans usage with proper normalized tables
-- All SNC-owned scheduling data lives here; Kelava data stays read-only via kelava_db

-- ============================================================
-- MASTER DATA
-- ============================================================

CREATE TABLE IF NOT EXISTS snc_supervisors (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    phone       TEXT,
    email       TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Teknisi master — ties to Kelava p_user via kelava_p_user_id (no FK, cross-DB)
CREATE TABLE IF NOT EXISTS snc_technicians (
    id                  BIGSERIAL PRIMARY KEY,
    kelava_p_user_id    INTEGER UNIQUE,          -- p_user.id in Kelava DB
    name                TEXT NOT NULL,
    supervisor_id       BIGINT REFERENCES snc_supervisors(id),
    phone               TEXT,
    email               TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snc_technicians_kelava ON snc_technicians(kelava_p_user_id);

-- Client/outlet master — ties to Kelava m_customer optionally
CREATE TABLE IF NOT EXISTS snc_clients (
    id                  BIGSERIAL PRIMARY KEY,
    kelava_customer_id  INTEGER UNIQUE,          -- m_customer.id in Kelava DB, nullable
    name                TEXT NOT NULL,
    address             TEXT,
    area                TEXT,
    default_visit_type  TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snc_clients_kelava ON snc_clients(kelava_customer_id);
CREATE INDEX IF NOT EXISTS idx_snc_clients_name ON snc_clients(name);

-- Visit type lookup (PRC, PC, RC, S-OUT, etc.)
CREATE TABLE IF NOT EXISTS snc_visit_types (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    color       TEXT DEFAULT '#6b7280'
);

INSERT INTO snc_visit_types (code, name, color) VALUES
    ('PRC',   'Preventive / Renewal Check', '#3b82f6'),
    ('PC',    'Preventive Check',           '#8b5cf6'),
    ('RC',    'Regular Check',              '#10b981'),
    ('S-OUT', 'Special Service Out',        '#f59e0b')
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- PLANNING
-- ============================================================

-- SSOT: one row = one planned visit
CREATE TABLE IF NOT EXISTS snc_schedule_events (
    id                  BIGSERIAL PRIMARY KEY,
    technician_id       BIGINT NOT NULL REFERENCES snc_technicians(id),
    supervisor_id       BIGINT REFERENCES snc_supervisors(id),
    client_id           BIGINT NOT NULL REFERENCES snc_clients(id),
    visit_type          TEXT REFERENCES snc_visit_types(code),

    -- Use full datetime to handle midnight-crossing schedules correctly
    start_datetime      TIMESTAMPTZ NOT NULL,
    end_datetime        TIMESTAMPTZ,

    schedule_status     TEXT NOT NULL DEFAULT 'scheduled'
                        CHECK (schedule_status IN (
                            'draft','scheduled','completed',
                            'cancelled','rescheduled','no_show','pending_report'
                        )),

    -- Reschedule chain
    rescheduled_from_id BIGINT REFERENCES snc_schedule_events(id),
    reschedule_reason   TEXT,

    notes               TEXT,
    created_by          INTEGER,     -- enterprise_user id
    updated_by          INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sse_technician ON snc_schedule_events(technician_id);
CREATE INDEX IF NOT EXISTS idx_sse_client     ON snc_schedule_events(client_id);
CREATE INDEX IF NOT EXISTS idx_sse_start      ON snc_schedule_events(start_datetime);
CREATE INDEX IF NOT EXISTS idx_sse_status     ON snc_schedule_events(schedule_status);
CREATE INDEX IF NOT EXISTS idx_sse_start_date ON snc_schedule_events((start_datetime::date));

-- Technician day-level status (OFF, leave, sick, etc.)
CREATE TABLE IF NOT EXISTS snc_technician_day_status (
    id              BIGSERIAL PRIMARY KEY,
    technician_id   BIGINT NOT NULL REFERENCES snc_technicians(id),
    date            DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'off'
                    CHECK (status IN (
                        'working','off','leave','sick',
                        'standby','training','unavailable'
                    )),
    reason          TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (technician_id, date)
);

CREATE INDEX IF NOT EXISTS idx_stds_tech_date ON snc_technician_day_status(technician_id, date);

-- ============================================================
-- EXECUTION
-- ============================================================

-- Actual realization vs planned schedule
CREATE TABLE IF NOT EXISTS snc_visit_execution_logs (
    id                      BIGSERIAL PRIMARY KEY,
    schedule_event_id       BIGINT NOT NULL REFERENCES snc_schedule_events(id) ON DELETE CASCADE,
    actual_start_at         TIMESTAMPTZ,
    actual_end_at           TIMESTAMPTZ,
    result_status           TEXT NOT NULL DEFAULT 'pending'
                            CHECK (result_status IN (
                                'pending','completed','partial','failed'
                            )),
    issue_found             TEXT,
    action_taken            TEXT,
    photo_before_url        TEXT,
    photo_after_url         TEXT,
    technician_notes        TEXT,
    client_signature_url    TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_svel_schedule ON snc_visit_execution_logs(schedule_event_id);
