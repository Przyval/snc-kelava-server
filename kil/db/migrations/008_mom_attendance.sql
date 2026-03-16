-- Migration 008: MOM (Minutes of Meeting) + Fingerprint Attendance
-- Applied: 2026-03-02
-- Target: Kelava PostgreSQL 10

-- ═══════════════════════════════════════════════════════════
-- MOM (Minutes of Meeting)
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS meetings (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    meeting_date DATE NOT NULL DEFAULT CURRENT_DATE,
    location TEXT,
    participants TEXT[],
    audio_filename TEXT,
    audio_duration_sec INTEGER,
    transcript TEXT,
    summary_json JSONB,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meeting_action_items (
    id BIGSERIAL PRIMARY KEY,
    meeting_id BIGINT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    assignee TEXT,
    due_date DATE,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meeting_distributions (
    id BIGSERIAL PRIMARY KEY,
    meeting_id BIGINT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    recipient TEXT NOT NULL,
    sent_at TIMESTAMP,
    status TEXT DEFAULT 'pending',
    error_message TEXT
);

-- ═══════════════════════════════════════════════════════════
-- Fingerprint Attendance
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS attendance_devices (
    id BIGSERIAL PRIMARY KEY,
    device_sn TEXT NOT NULL UNIQUE,
    device_name TEXT NOT NULL,
    location TEXT,
    api_key TEXT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attendance_user_map (
    id BIGSERIAL PRIMARY KEY,
    device_sn TEXT NOT NULL,
    finger_user_id TEXT NOT NULL,
    finger_user_name TEXT,
    technician_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(device_sn, finger_user_id)
);

CREATE TABLE IF NOT EXISTS attendance_logs (
    id BIGSERIAL PRIMARY KEY,
    device_sn TEXT NOT NULL,
    finger_user_id TEXT NOT NULL,
    technician_id INTEGER,
    punch_time TIMESTAMP NOT NULL,
    punch_type TEXT DEFAULT 'check_in',
    verify_method TEXT,
    raw_payload JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attendance_logs_tech ON attendance_logs(technician_id, punch_time);

CREATE INDEX IF NOT EXISTS idx_attendance_logs_date ON attendance_logs(punch_time);

CREATE TABLE IF NOT EXISTS attendance_reminders (
    id BIGSERIAL PRIMARY KEY,
    technician_id INTEGER NOT NULL,
    reminder_date DATE NOT NULL,
    reminder_time TIME NOT NULL,
    channel TEXT DEFAULT 'whatsapp',
    status TEXT DEFAULT 'pending',
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(technician_id, reminder_date, reminder_time)
);
