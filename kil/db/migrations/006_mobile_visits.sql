-- Migration 006: Mobile Visits Table
-- =====================================
-- Stores check-in/check-out data from the SNC Flutter mobile app.
-- This is our own operational table, independent of Kelava's t_visit.
-- Supports the "replace Kelava" long-term vision.

CREATE TABLE IF NOT EXISTS mobile_visits (
    id                BIGSERIAL PRIMARY KEY,
    road_plan_id      INTEGER,               -- ref to Kelava t_road_plan.id (nullable for manual visits)
    user_id           INTEGER NOT NULL,      -- enterprise_users.id
    customer_id       INTEGER,               -- m_customer.id
    check_in          TIMESTAMPTZ,
    check_out         TIMESTAMPTZ,
    latitude_in       NUMERIC(10, 7),
    longitude_in      NUMERIC(10, 7),
    latitude_out      NUMERIC(10, 7),
    longitude_out     NUMERIC(10, 7),
    remarks           TEXT,
    photo_count       INTEGER DEFAULT 0,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mobile_visits_user ON mobile_visits (user_id);
CREATE INDEX IF NOT EXISTS idx_mobile_visits_road_plan ON mobile_visits (road_plan_id);
CREATE INDEX IF NOT EXISTS idx_mobile_visits_checkin ON mobile_visits (check_in);
CREATE INDEX IF NOT EXISTS idx_mobile_visits_customer ON mobile_visits (customer_id);

-- Add approved_by / approved_at / rejection_reason to supervisory_actions if missing
ALTER TABLE supervisory_actions ADD COLUMN IF NOT EXISTS approved_by INTEGER;
ALTER TABLE supervisory_actions ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE supervisory_actions ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
