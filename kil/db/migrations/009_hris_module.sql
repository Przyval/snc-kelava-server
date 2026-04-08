-- Migration 009: HRIS Module — Centralized HR Information System
-- ================================================================
-- Consolidates KPI Mobile, KPI Station, Absensi, Lembur, Kunjungan,
-- Complain, and Grooming tracking into a single database.
-- Lives in LOCAL enterprise DB (not Kelava).

-- ── 1. Employee Master ──────────────────────────────────────────
-- Single source of truth for all employees (maps to Kelava p_user)

CREATE TABLE IF NOT EXISTS hris_employees (
    id              BIGSERIAL PRIMARY KEY,
    p_user_id       INTEGER,                    -- FK to Kelava p_user.id (nullable for non-Kelava staff)
    full_name       VARCHAR(256) NOT NULL,
    jabatan         VARCHAR(100),               -- Teknisi Mobile, Teknisi Station, Supervisor, etc.
    employee_type   VARCHAR(50) NOT NULL DEFAULT 'station',  -- mobile, station, support, office
    site_assignment VARCHAR(100),               -- TP, PCM, PM, JP, Vasa, Suprama (station only)
    supervisor_name VARCHAR(256),
    supervisor_id   BIGINT,                     -- self-ref to hris_employees.id
    is_active       BOOLEAN NOT NULL DEFAULT true,
    join_date       DATE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hris_emp_puser ON hris_employees(p_user_id) WHERE p_user_id IS NOT NULL;

-- ── 2. KPI Templates ───────────────────────────────────────────
-- Defines the KPI framework (indicators + weights) per employee type

CREATE TABLE IF NOT EXISTS hris_kpi_templates (
    id              BIGSERIAL PRIMARY KEY,
    employee_type   VARCHAR(50) NOT NULL,        -- mobile, station
    category_no     INTEGER NOT NULL,            -- 1=Kedisiplinan, 2=Complain, etc.
    category_name   VARCHAR(100) NOT NULL,
    sub_category    VARCHAR(100),                -- Administrasi, Waktu, Kinerja (nullable)
    indicator       TEXT NOT NULL,               -- Full indicator text
    bobot           NUMERIC(5,4) NOT NULL,       -- Weight (0.05 = 5%)
    scoring_type    VARCHAR(20) NOT NULL DEFAULT 'binary', -- binary, proportional, scaled
    is_active       BOOLEAN NOT NULL DEFAULT true,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 3. Monthly KPI Scores ───────────────────────────────────────
-- Actual scores per employee per month per indicator

CREATE TABLE IF NOT EXISTS hris_kpi_scores (
    id              BIGSERIAL PRIMARY KEY,
    employee_id     BIGINT NOT NULL REFERENCES hris_employees(id),
    template_id     BIGINT NOT NULL REFERENCES hris_kpi_templates(id),
    period_year     INTEGER NOT NULL,
    period_month    INTEGER NOT NULL,            -- 1-12
    keterangan      TEXT,                        -- Free-text notes (e.g., "4 cancel", "Kuku panjang")
    raw_value       NUMERIC(10,2),               -- Raw number (count, score 0-5, etc.)
    score_pct       NUMERIC(5,4) NOT NULL,       -- Actual score (0.0000 to bobot max)
    scored_by       VARCHAR(256),                -- Who entered the score
    scored_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(employee_id, template_id, period_year, period_month)
);

-- ── 4. Monthly Attendance Summary ───────────────────────────────

CREATE TABLE IF NOT EXISTS hris_attendance_monthly (
    id              BIGSERIAL PRIMARY KEY,
    employee_id     BIGINT NOT NULL REFERENCES hris_employees(id),
    period_year     INTEGER NOT NULL,
    period_month    INTEGER NOT NULL,
    kehadiran_pct   VARCHAR(10),                 -- "100%", "50%", "0%"
    prestasi_score  NUMERIC(3,1) DEFAULT 0,      -- 0 or 1
    grooming_pct    VARCHAR(10),                 -- "50%", "0%"
    grooming_pass   BOOLEAN DEFAULT true,
    complain_pct    VARCHAR(10),                 -- "50%", "0%"
    complain_pass   BOOLEAN DEFAULT true,
    jumlah_kunjungan INTEGER DEFAULT 0,          -- Visit count (mobile only)
    total_menit     INTEGER DEFAULT 0,           -- Total visit minutes
    jam_lembur      NUMERIC(6,1) DEFAULT 0,
    hari_bonus      NUMERIC(4,1) DEFAULT 0,
    hari_setengah   NUMERIC(4,1) DEFAULT 0,
    hari_efektif    NUMERIC(4,1) DEFAULT 0,
    hari_perhitungan NUMERIC(4,1) DEFAULT 0,
    hari_sakit      INTEGER DEFAULT 0,
    hari_cuti       INTEGER DEFAULT 0,
    hari_izin       INTEGER DEFAULT 0,
    hari_kosong     INTEGER DEFAULT 0,
    hari_libur      INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(employee_id, period_year, period_month)
);

-- ── 5. Daily Attendance ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hris_attendance_daily (
    id              BIGSERIAL PRIMARY KEY,
    employee_id     BIGINT NOT NULL REFERENCES hris_employees(id),
    attend_date     DATE NOT NULL,
    status          VARCHAR(10) NOT NULL,         -- H (hadir/√), X (absent), C (cuti), S (sakit), I (izin), K (kosong), L (libur)
    is_late         BOOLEAN DEFAULT false,
    late_minutes    INTEGER DEFAULT 0,
    check_in_time   TIME,
    check_out_time  TIME,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(employee_id, attend_date)
);

-- ── 6. Overtime (Lembur) ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hris_overtime (
    id              BIGSERIAL PRIMARY KEY,
    employee_id     BIGINT NOT NULL REFERENCES hris_employees(id),
    overtime_date   DATE NOT NULL,
    area            VARCHAR(256),                 -- Location/site
    jam_range       VARCHAR(50),                  -- "15:00-17:00"
    duration_hours  NUMERIC(4,1) NOT NULL,
    acc_spv         VARCHAR(256),
    acc_personalia  VARCHAR(256),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 7. Grooming Violations ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS hris_grooming (
    id              BIGSERIAL PRIMARY KEY,
    employee_id     BIGINT NOT NULL REFERENCES hris_employees(id),
    period_year     INTEGER NOT NULL,
    period_month    INTEGER NOT NULL,
    temuan          TEXT NOT NULL,                 -- Finding description
    lampiran_url    VARCHAR(512),                  -- Photo evidence URL
    pic             VARCHAR(256),                  -- Person who reported
    acc_personalia  VARCHAR(256),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── 8. Complaint Records ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hris_complaints (
    id              BIGSERIAL PRIMARY KEY,
    employee_id     BIGINT NOT NULL REFERENCES hris_employees(id),
    period_year     INTEGER NOT NULL,
    period_month    INTEGER NOT NULL,
    complaint_date  DATE,
    client_name     VARCHAR(256),
    hama            VARCHAR(256),                  -- Pest type
    complaint_text  TEXT,
    tim_fu          VARCHAR(256),                  -- Follow-up team
    fu_date         DATE,
    days_to_resolve INTEGER,
    tindakan        TEXT,                           -- Action taken
    status          VARCHAR(50),                    -- Open, Closed
    complaint_type  VARCHAR(50),                    -- Major, Minor
    close_date      DATE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ─────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_kpi_scores_emp_period ON hris_kpi_scores(employee_id, period_year, period_month);
CREATE INDEX IF NOT EXISTS idx_attendance_monthly_emp ON hris_attendance_monthly(employee_id, period_year, period_month);
CREATE INDEX IF NOT EXISTS idx_attendance_daily_emp ON hris_attendance_daily(employee_id, attend_date);
CREATE INDEX IF NOT EXISTS idx_overtime_emp ON hris_overtime(employee_id, overtime_date);
CREATE INDEX IF NOT EXISTS idx_grooming_emp ON hris_grooming(employee_id, period_year, period_month);
CREATE INDEX IF NOT EXISTS idx_complaints_emp ON hris_complaints(employee_id, period_year, period_month);
