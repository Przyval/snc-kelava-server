-- Migration 023: Scheduler Master Data
-- Customer master, technician ownership, suppression calendar, correction log

-- ── Customer Master ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS snc_customer_master (
    id                  SERIAL PRIMARY KEY,
    snc_client_id       INTEGER UNIQUE,            -- FK to snc_clients.id
    accurate_name       TEXT,                       -- nama di Accurate
    canonical_name      TEXT NOT NULL,              -- nama bersih yang dipakai
    customer_status     VARCHAR(20) NOT NULL DEFAULT 'active',  -- active|paused|cancelled
    invoice_frequency   VARCHAR(20),                -- weekly|biweekly|monthly|irregular
    avg_interval_days   NUMERIC(6,1),
    last_invoice_date   DATE,
    first_invoice_date  DATE,
    invoice_count_12m   INTEGER DEFAULT 0,
    total_revenue_12m   NUMERIC(15,2) DEFAULT 0,
    revenue_tier        CHAR(1),                   -- A|B|C
    area_code           VARCHAR(20),
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Customer → Technician Ownership ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS snc_customer_technician (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL,
    technician_id   INTEGER NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'primary',  -- primary|backup_1|backup_2
    confidence      NUMERIC(4,2) DEFAULT 1.0,               -- 0-1 from history
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id, role)
);

-- ── Suppression Calendar ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS snc_suppression_dates (
    id              SERIAL PRIMARY KEY,
    suppression_date DATE NOT NULL UNIQUE,
    reason          TEXT,
    scope           VARCHAR(50) DEFAULT 'all',  -- all|area:JS|area:SDA
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Seed hari libur nasional + cuti bersama 2026
INSERT INTO snc_suppression_dates (suppression_date, reason) VALUES
  ('2026-01-01', 'Tahun Baru Masehi'),
  ('2026-01-27', 'Isra Miraj'),
  ('2026-01-28', 'Cuti Bersama Isra Miraj'),
  ('2026-01-29', 'Cuti Bersama Imlek'),
  ('2026-01-30', 'Tahun Baru Imlek'),
  ('2026-03-20', 'Hari Raya Nyepi'),
  ('2026-03-21', 'Cuti Bersama Nyepi'),
  ('2026-03-31', 'Cuti Bersama Wafat Isa Almasih'),
  ('2026-04-01', 'Wafat Isa Almasih'),
  ('2026-04-02', 'Cuti Bersama Idul Fitri'),
  ('2026-04-03', 'Idul Fitri 1447H'),
  ('2026-04-04', 'Idul Fitri 1447H'),
  ('2026-04-05', 'Cuti Bersama Idul Fitri'),
  ('2026-04-06', 'Cuti Bersama Idul Fitri'),
  ('2026-05-01', 'Hari Buruh Internasional'),
  ('2026-05-14', 'Kenaikan Isa Almasih'),
  ('2026-05-23', 'Waisak'),
  ('2026-06-01', 'Hari Lahir Pancasila'),   -- ini kenapa minggu 1 Juni banyak yang skip!
  ('2026-06-17', 'Idul Adha 1447H'),
  ('2026-06-18', 'Cuti Bersama Idul Adha'),
  ('2026-07-09', 'Cuti Bersama'),
  ('2026-08-17', 'Kemerdekaan RI'),
  ('2026-08-27', 'Tahun Baru Hijriyah'),
  ('2026-11-05', 'Maulid Nabi Muhammad SAW'),
  ('2026-12-24', 'Cuti Bersama Natal'),
  ('2026-12-25', 'Hari Natal')
ON CONFLICT DO NOTHING;

-- ── Admin Correction Log ─────────────────────────────────────────────────────
-- Untuk mesin belajar dari koreksi supervisor
CREATE TABLE IF NOT EXISTS snc_draft_corrections (
    id              SERIAL PRIMARY KEY,
    draft_event_id  INTEGER,
    correction_type VARCHAR(20) NOT NULL,  -- approved|edited|rejected
    field_changed   VARCHAR(50),
    old_value       TEXT,
    new_value       TEXT,
    reason_code     VARCHAR(50),           -- HOLIDAY|TECH_OFF|CUSTOMER_REQUEST|...
    corrected_by    INTEGER DEFAULT 0,
    corrected_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── Add week_pattern column to snc_schedule_patterns ─────────────────────────
-- Stores biweekly pattern weeks e.g. '1,3' or '2,4'
ALTER TABLE snc_schedule_patterns
    ADD COLUMN IF NOT EXISTS week_pattern TEXT;

ALTER TABLE snc_schedule_patterns
    ADD COLUMN IF NOT EXISTS occurrence_count INTEGER DEFAULT 1;

ALTER TABLE snc_schedule_patterns
    ADD COLUMN IF NOT EXISTS recency_score NUMERIC(4,2) DEFAULT 1.0;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_snc_cm_client ON snc_customer_master(snc_client_id);
CREATE INDEX IF NOT EXISTS idx_snc_ct_client ON snc_customer_technician(client_id);
CREATE INDEX IF NOT EXISTS idx_snc_supp_date ON snc_suppression_dates(suppression_date);
