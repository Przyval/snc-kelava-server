-- Migration 012: Calendar Reschedule Write Layer
-- Tracks which Kelava road plans have been rescheduled/cancelled from the dashboard.
-- When koordinator reschedules a visit, we:
--   1. INSERT into snc_kelava_cancellations (soft-cancel the original Kelava entry)
--   2. INSERT into snc_road_plans with kelava_road_plan_id (the replacement)
--   3. calendar/schedule merges both sources, filtering out cancelled Kelava entries.

CREATE TABLE IF NOT EXISTS snc_kelava_cancellations (
    id                   BIGSERIAL PRIMARY KEY,
    kelava_road_plan_id  INTEGER NOT NULL UNIQUE,
    reason               TEXT,
    new_snc_road_plan_id BIGINT,        -- NULL = cancelled outright, set = rescheduled
    created_by           INTEGER,       -- enterprise_users.id
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snc_kelava_canc_rp
    ON snc_kelava_cancellations(kelava_road_plan_id);
