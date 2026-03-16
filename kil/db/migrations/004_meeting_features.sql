-- ============================================================================
-- Migration 004: Meeting Action Items (2026-02-19)
-- ============================================================================
-- Implements features discussed in ops meeting:
--   1. Technician Segments (Mobile/Station/Support/Supervisor)
--   2. Schedule Templates (recurring visit patterns)
--   3. Punctuality Tracking (lateness detection)
--   4. Supervisory Actions / Sidak (inspection mechanism)
--   5. Complaint Tracking (linked to technicians & customers)
--   6. Supervision Reports (QC form results)
-- ============================================================================

-- ============================================================================
-- 1. TECHNICIAN SEGMENTS
-- Each technician belongs to a segment with different KPI rules.
--   Mobile:     Must roam/keliling, visit multiple clients per day
--   Station:    In-charge at one location, zero lateness tolerance
--   Support:    40-42 effective hours/week, must be assigned to clients
--   Supervisor: New client install, audit accompaniment, sidak
-- ============================================================================

CREATE TABLE IF NOT EXISTS technician_segments (
    id BIGSERIAL PRIMARY KEY,
    technician_id INTEGER NOT NULL,  -- p_user.id
    segment VARCHAR(20) NOT NULL CHECK (segment IN ('MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR')),
    shift_type VARCHAR(20) DEFAULT 'MORNING',  -- MORNING, EVENING (Station only)
    weekly_hours_target NUMERIC(5,1) DEFAULT 40.0,  -- For Support: 40-42 hrs
    is_active BOOLEAN NOT NULL DEFAULT true,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(technician_id)
);

COMMENT ON TABLE technician_segments IS 'Technician role segments with segment-specific KPI rules';
COMMENT ON COLUMN technician_segments.segment IS 'MOBILE=keliling, STATION=satu tempat, SUPPORT=bantuan, SUPERVISOR=pengawas';
COMMENT ON COLUMN technician_segments.shift_type IS 'Shift pagi/sore - primarily for Station segment';

CREATE INDEX IF NOT EXISTS idx_tech_seg_tech ON technician_segments(technician_id);
CREATE INDEX IF NOT EXISTS idx_tech_seg_segment ON technician_segments(segment);

-- Segment KPI rules configuration
CREATE TABLE IF NOT EXISTS segment_kpi_rules (
    id BIGSERIAL PRIMARY KEY,
    segment VARCHAR(20) NOT NULL CHECK (segment IN ('MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR')),
    metric_name VARCHAR(50) NOT NULL,         -- e.g. 'visits_per_day', 'on_time_rate', 'effective_hours'
    metric_label VARCHAR(100) NOT NULL,        -- Display label
    weight NUMERIC(3,2) NOT NULL DEFAULT 1.0,  -- KPI weight (0.00-1.00)
    threshold_green NUMERIC(10,2),             -- Good threshold
    threshold_yellow NUMERIC(10,2),            -- Warning threshold
    threshold_red NUMERIC(10,2),               -- Critical threshold
    unit VARCHAR(20) DEFAULT 'count',          -- count, percent, minutes, hours
    description TEXT,
    UNIQUE(segment, metric_name)
);

COMMENT ON TABLE segment_kpi_rules IS 'Segment-specific KPI rules and thresholds';

-- Seed default KPI rules per segment
INSERT INTO segment_kpi_rules (segment, metric_name, metric_label, weight, threshold_green, threshold_yellow, threshold_red, unit, description)
VALUES
    -- MOBILE: focus on volume & punctuality
    ('MOBILE', 'visits_per_day',   'Kunjungan/Hari',    0.30, 4.0, 2.5, 1.5, 'count',   'Target kunjungan per hari kerja'),
    ('MOBILE', 'on_time_rate',     'Tepat Waktu %',     0.25, 90.0, 75.0, 60.0, 'percent', 'Persentase check-in tepat waktu (toleransi 30 menit untuk klien ke-2+)'),
    ('MOBILE', 'completion_rate',  'Penyelesaian %',     0.20, 95.0, 85.0, 70.0, 'percent', 'Persentase rencana kerja yang diselesaikan'),
    ('MOBILE', 'photo_compliance', 'Kepatuhan Foto %',   0.15, 95.0, 80.0, 60.0, 'percent', 'Persentase kunjungan dengan foto lengkap'),
    ('MOBILE', 'avg_duration',     'Rata-rata Durasi',   0.10, 60.0, 30.0, 15.0, 'minutes', 'Rata-rata durasi pengerjaan per kunjungan'),

    -- STATION: focus on discipline & consistency
    ('STATION', 'on_time_rate',     'Tepat Waktu %',     0.35, 100.0, 95.0, 90.0, 'percent', 'Zero tolerance - harus tepat waktu'),
    ('STATION', 'effective_hours',  'Jam Efektif/Hari',   0.25, 7.5, 6.0, 5.0, 'hours',   'Jam efektif kerja per hari (target 8 jam)'),
    ('STATION', 'completion_rate',  'Penyelesaian %',     0.20, 98.0, 90.0, 80.0, 'percent', 'Penyelesaian tugas harian'),
    ('STATION', 'photo_compliance', 'Kepatuhan Foto %',   0.20, 95.0, 85.0, 70.0, 'percent', 'Foto dokumentasi kerja'),

    -- SUPPORT: focus on utilization & client exposure
    ('SUPPORT', 'weekly_hours',      'Jam/Minggu',         0.30, 40.0, 35.0, 30.0, 'hours',   'Target 40-42 jam efektif per minggu'),
    ('SUPPORT', 'client_exposure',   'Ketemu Klien/Minggu', 0.25, 15.0, 10.0, 5.0, 'count',   'Frekuensi ketemu klien per minggu'),
    ('SUPPORT', 'utilization_rate',  'Utilisasi %',        0.25, 85.0, 70.0, 50.0, 'percent', 'Persentase jam produktif vs jam kerja'),
    ('SUPPORT', 'on_time_rate',      'Tepat Waktu %',      0.20, 90.0, 75.0, 60.0, 'percent', 'Ketepatan waktu check-in'),

    -- SUPERVISOR: focus on supervision quality & coverage
    ('SUPERVISOR', 'supervision_count', 'Supervisi/Bulan',    0.30, 20.0, 15.0, 10.0, 'count',   'Jumlah supervisi per bulan'),
    ('SUPERVISOR', 'sidak_count',       'Sidak/Bulan',        0.20, 8.0, 5.0, 3.0, 'count',     'Jumlah inspeksi mendadak per bulan'),
    ('SUPERVISOR', 'new_install',       'Dampingi Install',   0.20, 4.0, 2.0, 1.0, 'count',     'Pendampingan install klien baru per bulan'),
    ('SUPERVISOR', 'audit_accompany',   'Dampingi Audit',     0.15, 3.0, 2.0, 1.0, 'count',     'Pendampingan audit klien per bulan'),
    ('SUPERVISOR', 'issue_resolution',  'Resolusi Masalah %', 0.15, 90.0, 75.0, 60.0, 'percent', 'Persentase issue teknisi yang di-resolve')
ON CONFLICT (segment, metric_name) DO NOTHING;

-- ============================================================================
-- 2. SCHEDULE TEMPLATES (Recurring Visit Patterns)
-- "Plants vs Zombies" scheduling system.
-- Templates define recurring patterns; ops can override per-instance.
-- ============================================================================

CREATE TABLE IF NOT EXISTS schedule_templates (
    id BIGSERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,       -- m_customer.id
    technician_id INTEGER,              -- p_user.id (NULL = unassigned)
    day_of_week SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),  -- 0=Sunday, 1=Monday...
    scheduled_time TIME NOT NULL,       -- Expected check-in time
    visit_type VARCHAR(30) DEFAULT 'REGULAR',  -- REGULAR, MAINTENANCE, INSPECTION
    frequency VARCHAR(20) DEFAULT 'WEEKLY',    -- WEEKLY, BIWEEKLY, MONTHLY
    week_pattern SMALLINT DEFAULT 0,    -- For BIWEEKLY: 0=every, 1=odd weeks, 2=even weeks
    shift VARCHAR(10) DEFAULT 'PAGI',   -- PAGI, SORE, MALAM
    duration_estimate INTEGER DEFAULT 60,  -- Expected duration in minutes
    is_active BOOLEAN DEFAULT true,
    notes TEXT,
    source VARCHAR(20) DEFAULT 'MANUAL',  -- MANUAL, PATTERN_DETECTED, CONTRACT
    contract_id INTEGER,                -- Link to m_customer_kontrak.id
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE schedule_templates IS 'Recurring visit templates - base schedule yang bisa di-override';
COMMENT ON COLUMN schedule_templates.day_of_week IS '0=Minggu, 1=Senin, 2=Selasa, 3=Rabu, 4=Kamis, 5=Jumat, 6=Sabtu';
COMMENT ON COLUMN schedule_templates.source IS 'MANUAL=input operasional, PATTERN_DETECTED=AI baca pola, CONTRACT=dari kontrak';

CREATE INDEX IF NOT EXISTS idx_sched_tmpl_customer ON schedule_templates(customer_id);
CREATE INDEX IF NOT EXISTS idx_sched_tmpl_tech ON schedule_templates(technician_id);
CREATE INDEX IF NOT EXISTS idx_sched_tmpl_dow ON schedule_templates(day_of_week);
CREATE INDEX IF NOT EXISTS idx_sched_tmpl_active ON schedule_templates(is_active) WHERE is_active = true;

-- ============================================================================
-- 3. PUNCTUALITY TRACKING
-- Compare scheduled time vs actual check-in time.
-- Rules from meeting:
--   Station: 0 tolerance
--   Mobile klien pertama: 0 tolerance
--   Mobile klien ke-2+: toleransi 30 menit
-- ============================================================================

CREATE TABLE IF NOT EXISTS punctuality_records (
    id BIGSERIAL PRIMARY KEY,
    technician_id INTEGER NOT NULL,     -- p_user.id
    visit_date DATE NOT NULL,
    road_plan_id INTEGER,               -- t_road_plan.id
    customer_id INTEGER,                -- m_customer.id
    visit_sequence INTEGER DEFAULT 1,   -- 1=first visit of the day, 2=second...
    scheduled_time TIME,                -- From schedule_template or manual
    actual_checkin_time TIME,           -- From t_visit.check_in
    delta_minutes INTEGER,              -- actual - scheduled (negative = early, positive = late)
    tolerance_minutes INTEGER DEFAULT 0,  -- 0 for Station/first visit, 30 for Mobile 2nd+
    is_late BOOLEAN DEFAULT false,  -- Computed by trigger (PG10 compat)
    segment VARCHAR(20),                -- Denormalized from technician_segments
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(technician_id, visit_date, road_plan_id)
);

COMMENT ON TABLE punctuality_records IS 'Daily punctuality tracking - compared schedule vs actual check-in';
COMMENT ON COLUMN punctuality_records.tolerance_minutes IS 'Station=0, Mobile first=0, Mobile 2nd+=30';
COMMENT ON COLUMN punctuality_records.is_late IS 'Auto-computed: true if delta > tolerance';

CREATE INDEX IF NOT EXISTS idx_punct_tech ON punctuality_records(technician_id);
CREATE INDEX IF NOT EXISTS idx_punct_date ON punctuality_records(visit_date);
CREATE INDEX IF NOT EXISTS idx_punct_late ON punctuality_records(is_late) WHERE is_late = true;
CREATE INDEX IF NOT EXISTS idx_punct_segment ON punctuality_records(segment);

-- ============================================================================
-- 4. SUPERVISORY ACTIONS / SIDAK (Inspection Mechanism)
-- Supervisors can trigger sidak; system auto-schedules.
-- Technicians don't know when they'll be inspected.
-- ============================================================================

CREATE TABLE IF NOT EXISTS supervisory_actions (
    id BIGSERIAL PRIMARY KEY,
    action_type VARCHAR(30) NOT NULL CHECK (action_type IN (
        'SIDAK', 'SP_WARNING', 'COACHING', 'REVIEW',
        'NEW_CLIENT_INSTALL', 'AUDIT_ACCOMPANY', 'COMPLAINT_HANDLING'
    )),
    supervisor_id INTEGER NOT NULL,     -- p_user.id of supervisor
    target_technician_id INTEGER,       -- p_user.id (NULL for non-tech actions)
    target_customer_id INTEGER,         -- m_customer.id (for audit/install)
    scheduled_date DATE,
    scheduled_time TIME,
    actual_date DATE,
    status VARCHAR(20) DEFAULT 'SCHEDULED' CHECK (status IN (
        'SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'MISSED'
    )),
    priority VARCHAR(10) DEFAULT 'NORMAL' CHECK (priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')),
    trigger_reason TEXT,                -- Why this action was triggered
    findings TEXT,                      -- What was found during sidak
    follow_up_action TEXT,              -- Required follow-up
    follow_up_deadline DATE,
    created_by INTEGER,                 -- Who triggered this action
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE supervisory_actions IS 'Supervisory actions: sidak, SP, coaching, pendampingan audit/install';
COMMENT ON COLUMN supervisory_actions.trigger_reason IS 'Alasan: KPI rendah, anomali waktu, complain klien, dll';

CREATE INDEX IF NOT EXISTS idx_supv_action_type ON supervisory_actions(action_type);
CREATE INDEX IF NOT EXISTS idx_supv_action_supervisor ON supervisory_actions(supervisor_id);
CREATE INDEX IF NOT EXISTS idx_supv_action_target ON supervisory_actions(target_technician_id);
CREATE INDEX IF NOT EXISTS idx_supv_action_date ON supervisory_actions(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_supv_action_status ON supervisory_actions(status);

-- Supervisor calendar (auto-generated from supervisory_actions)
CREATE OR REPLACE VIEW v_supervisor_calendar AS
SELECT
    sa.id,
    sa.action_type,
    sa.supervisor_id,
    sa.target_technician_id,
    sa.target_customer_id,
    sa.scheduled_date,
    sa.scheduled_time,
    sa.status,
    sa.priority,
    sa.trigger_reason,
    u_sup.fullname as supervisor_name,
    u_tech.fullname as technician_name,
    c.name as customer_name
FROM supervisory_actions sa
LEFT JOIN p_user u_sup ON u_sup.id = sa.supervisor_id
LEFT JOIN p_user u_tech ON u_tech.id = sa.target_technician_id
LEFT JOIN m_customer c ON c.id = sa.target_customer_id
WHERE sa.status IN ('SCHEDULED', 'IN_PROGRESS')
ORDER BY
    CASE sa.priority
        WHEN 'URGENT' THEN 1
        WHEN 'HIGH' THEN 2
        WHEN 'NORMAL' THEN 3
        ELSE 4
    END,
    sa.scheduled_date,
    sa.scheduled_time;

-- ============================================================================
-- 5. COMPLAINT TRACKING
-- Linked to technicians & customers. Imported from Monday.com initially.
-- ============================================================================

CREATE TABLE IF NOT EXISTS complaints (
    id BIGSERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,       -- m_customer.id
    technician_id INTEGER,              -- p_user.id (assigned tech at time of complaint)
    complaint_date DATE NOT NULL DEFAULT CURRENT_DATE,
    severity VARCHAR(20) DEFAULT 'MINOR' CHECK (severity IN ('MINOR', 'MAJOR', 'CRITICAL')),
    category VARCHAR(50),               -- e.g. 'SERVICE_QUALITY', 'LATE', 'NO_SHOW', 'DAMAGE', 'RUDE'
    description TEXT NOT NULL,
    source VARCHAR(30) DEFAULT 'INTERNAL',  -- INTERNAL, CLIENT_DIRECT, MONDAY, EMAIL, PHONE
    status VARCHAR(20) DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')),
    assigned_to INTEGER,                -- p_user.id (who handles follow-up)
    resolution_note TEXT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolved_by INTEGER,                -- p_user.id
    follow_up_date DATE,
    follow_up_note TEXT,
    external_ref VARCHAR(100),          -- Monday.com ID or other external ref
    created_by INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE complaints IS 'Customer complaints linked to technicians - synced from Monday.com';

CREATE INDEX IF NOT EXISTS idx_complaint_customer ON complaints(customer_id);
CREATE INDEX IF NOT EXISTS idx_complaint_tech ON complaints(technician_id);
CREATE INDEX IF NOT EXISTS idx_complaint_status ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_complaint_date ON complaints(complaint_date);
CREATE INDEX IF NOT EXISTS idx_complaint_severity ON complaints(severity);

-- Complaint activity log
CREATE TABLE IF NOT EXISTS complaint_actions (
    id BIGSERIAL PRIMARY KEY,
    complaint_id BIGINT NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    action_type VARCHAR(30) NOT NULL,  -- 'created', 'assigned', 'note_added', 'escalated', 'resolved', 'closed'
    actor_id INTEGER,
    actor_name VARCHAR(100),
    note TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_complaint_act_complaint ON complaint_actions(complaint_id);

-- ============================================================================
-- 6. SUPERVISION REPORTS (QC Form Results)
-- Supervisor findings from field visits (sidak results).
-- ============================================================================

CREATE TABLE IF NOT EXISTS supervision_reports (
    id BIGSERIAL PRIMARY KEY,
    supervisory_action_id BIGINT REFERENCES supervisory_actions(id),  -- Link to sidak/supervision
    supervisor_id INTEGER NOT NULL,     -- p_user.id
    technician_id INTEGER NOT NULL,     -- p_user.id being supervised
    customer_id INTEGER,                -- m_customer.id where supervision occurred
    report_date DATE NOT NULL DEFAULT CURRENT_DATE,
    -- QC Checklist scores (1-5)
    score_appearance INTEGER CHECK (score_appearance BETWEEN 1 AND 5),      -- Penampilan
    score_punctuality INTEGER CHECK (score_punctuality BETWEEN 1 AND 5),    -- Ketepatan waktu
    score_procedure INTEGER CHECK (score_procedure BETWEEN 1 AND 5),        -- Prosedur kerja
    score_safety INTEGER CHECK (score_safety BETWEEN 1 AND 5),              -- Keselamatan
    score_communication INTEGER CHECK (score_communication BETWEEN 1 AND 5),-- Komunikasi
    score_documentation INTEGER CHECK (score_documentation BETWEEN 1 AND 5),-- Dokumentasi/foto
    overall_score NUMERIC(3,1) DEFAULT 0,  -- Computed by trigger (PG10 compat)
    findings TEXT,
    recommendations TEXT,
    follow_up_required BOOLEAN DEFAULT false,
    follow_up_deadline DATE,
    photos JSONB DEFAULT '[]',  -- Array of photo URLs
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE supervision_reports IS 'QC/supervision report results from field inspections';

CREATE INDEX IF NOT EXISTS idx_supv_report_supervisor ON supervision_reports(supervisor_id);
CREATE INDEX IF NOT EXISTS idx_supv_report_tech ON supervision_reports(technician_id);
CREATE INDEX IF NOT EXISTS idx_supv_report_date ON supervision_reports(report_date);

-- ============================================================================
-- 7. CUSTOMER AUDIT SCHEDULE
-- Track client audit schedules (3 months, 6 months, yearly).
-- ============================================================================

CREATE TABLE IF NOT EXISTS customer_audit_schedules (
    id BIGSERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,       -- m_customer.id
    audit_frequency VARCHAR(20) NOT NULL CHECK (audit_frequency IN ('QUARTERLY', 'SEMI_ANNUAL', 'ANNUAL')),
    next_audit_date DATE,
    last_audit_date DATE,
    certification_type VARCHAR(100),    -- e.g. 'ISO', 'HACCP', 'Internal'
    notes TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(customer_id, certification_type)
);

COMMENT ON TABLE customer_audit_schedules IS 'Client audit schedules - jadwal sertifikasi dari klien';

CREATE INDEX IF NOT EXISTS idx_cust_audit_customer ON customer_audit_schedules(customer_id);
CREATE INDEX IF NOT EXISTS idx_cust_audit_next ON customer_audit_schedules(next_audit_date);

-- ============================================================================
-- 8. COMPUTED COLUMN TRIGGERS (PG10 compatibility)
-- Replaces GENERATED ALWAYS AS STORED (requires PG12+)
-- ============================================================================

-- Punctuality: auto-compute is_late
CREATE OR REPLACE FUNCTION trg_punctuality_is_late()
RETURNS TRIGGER AS $$
BEGIN
    NEW.is_late := COALESCE(NEW.delta_minutes, 0) > COALESCE(NEW.tolerance_minutes, 0);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS punctuality_is_late_trigger ON punctuality_records;
CREATE TRIGGER punctuality_is_late_trigger
    BEFORE INSERT OR UPDATE ON punctuality_records
    FOR EACH ROW EXECUTE PROCEDURE trg_punctuality_is_late();

-- Supervision reports: auto-compute overall_score
CREATE OR REPLACE FUNCTION trg_supervision_overall_score()
RETURNS TRIGGER AS $$
BEGIN
    NEW.overall_score := (
        COALESCE(NEW.score_appearance, 0) +
        COALESCE(NEW.score_punctuality, 0) +
        COALESCE(NEW.score_procedure, 0) +
        COALESCE(NEW.score_safety, 0) +
        COALESCE(NEW.score_communication, 0) +
        COALESCE(NEW.score_documentation, 0)
    )::numeric / 6.0;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS supervision_overall_score_trigger ON supervision_reports;
CREATE TRIGGER supervision_overall_score_trigger
    BEFORE INSERT OR UPDATE ON supervision_reports
    FOR EACH ROW EXECUTE PROCEDURE trg_supervision_overall_score();

-- ============================================================================
-- 9. PERMISSIONS UPDATE
-- Add new module permissions for the new features.
-- ============================================================================

INSERT INTO enterprise_permissions (role, resource, action) VALUES
    -- Supervisor permissions for new modules
    ('supervisor', 'scheduling', 'read'),
    ('supervisor', 'scheduling', 'write'),
    ('supervisor', 'punctuality', 'read'),
    ('supervisor', 'supervisory_actions', 'read'),
    ('supervisor', 'supervisory_actions', 'write'),
    ('supervisor', 'complaints', 'read'),
    ('supervisor', 'complaints', 'write'),
    ('supervisor', 'supervision_reports', 'read'),
    ('supervisor', 'supervision_reports', 'write'),
    -- Viewer read access
    ('viewer', 'scheduling', 'read'),
    ('viewer', 'punctuality', 'read'),
    ('viewer', 'supervisory_actions', 'read'),
    ('viewer', 'complaints', 'read'),
    ('viewer', 'supervision_reports', 'read'),
    -- Technician limited access
    ('technician', 'scheduling', 'read'),
    ('technician', 'punctuality', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;

-- ============================================================================
-- Migration Complete
-- ============================================================================
