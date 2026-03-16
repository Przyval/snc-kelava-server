-- ============================================================================
-- Verification Engine: Photo & GPS Anomaly Detection
-- ============================================================================
-- PG10 compatible. Creates anomaly flagging tables and verification views.
-- ============================================================================

-- Step 1: Verification flags table (stores flagged anomalies)
CREATE TABLE IF NOT EXISTS verification_flags (
    id BIGSERIAL PRIMARY KEY,
    visit_id INTEGER NOT NULL,
    road_plan_id INTEGER,
    technician_id INTEGER NOT NULL,
    customer_id INTEGER,
    flag_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'warning',
    detail TEXT,
    gps_checkin_lat DOUBLE PRECISION,
    gps_checkin_lng DOUBLE PRECISION,
    gps_checkout_lat DOUBLE PRECISION,
    gps_checkout_lng DOUBLE PRECISION,
    drift_meters DOUBLE PRECISION,
    photo_count INTEGER DEFAULT 0,
    resolved BOOLEAN NOT NULL DEFAULT false,
    resolved_by VARCHAR(200),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution_note TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE verification_flags IS 'Flagged anomalies from Photo & GPS verification engine';

CREATE INDEX IF NOT EXISTS idx_vf_visit ON verification_flags(visit_id);
CREATE INDEX IF NOT EXISTS idx_vf_tech ON verification_flags(technician_id);
CREATE INDEX IF NOT EXISTS idx_vf_type ON verification_flags(flag_type);
CREATE INDEX IF NOT EXISTS idx_vf_severity ON verification_flags(severity);
CREATE INDEX IF NOT EXISTS idx_vf_created ON verification_flags(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_vf_unresolved ON verification_flags(resolved) WHERE resolved = false;

-- Step 2: View - Visit verification summary (enriched with photo + GPS data)
CREATE OR REPLACE VIEW v_visit_verification AS
SELECT
    v.id as visit_id,
    v.id_road_plan as road_plan_id,
    v.id_user as technician_id,
    pu.fullname as technician_name,
    v.id_customer as customer_id,
    mc.name as customer_name,
    v.check_in,
    v.check_out,
    EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60.0 as duration_minutes,
    v.latitude as checkin_lat,
    v.longitude as checkin_lng,
    v.latitude_o as checkout_lat,
    v.longitude_o as checkout_lng,
    -- Haversine-approximated drift in meters (check-in vs check-out)
    CASE WHEN v.latitude IS NOT NULL AND v.latitude != 0
              AND v.latitude_o IS NOT NULL AND v.latitude_o != 0
         THEN 111320.0 * SQRT(
              POWER(v.latitude - v.latitude_o, 2) +
              POWER((v.longitude - v.longitude_o) * COS(RADIANS(v.latitude)), 2)
         )
         ELSE NULL
    END as drift_meters,
    -- Photo count for this visit's road plan
    COALESCE(pc.cnt, 0) as photo_count,
    -- Flag indicators
    CASE WHEN COALESCE(pc.cnt, 0) = 0 THEN true ELSE false END as flag_no_photo,
    CASE WHEN v.latitude IS NULL OR v.latitude = 0 THEN true ELSE false END as flag_no_gps,
    CASE WHEN v.latitude IS NOT NULL AND v.latitude != 0
              AND v.latitude_o IS NOT NULL AND v.latitude_o != 0
              AND 111320.0 * SQRT(
                  POWER(v.latitude - v.latitude_o, 2) +
                  POWER((v.longitude - v.longitude_o) * COS(RADIANS(v.latitude)), 2)
              ) > 500
         THEN true ELSE false END as flag_gps_drift,
    CASE WHEN v.check_out IS NOT NULL
              AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) < 300
         THEN true ELSE false END as flag_too_short,
    CASE WHEN v.check_out IS NOT NULL
              AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) > 28800
         THEN true ELSE false END as flag_too_long,
    v.realization_date
FROM t_visit v
LEFT JOIN p_user pu ON pu.id = v.id_user
LEFT JOIN m_customer mc ON mc.id = v.id_customer
LEFT JOIN (
    SELECT id_road_plan, COUNT(*) as cnt FROM t_road_plan_foto GROUP BY id_road_plan
) pc ON pc.id_road_plan = v.id_road_plan;

COMMENT ON VIEW v_visit_verification IS 'Enriched visit data with photo counts and GPS anomaly flags';

-- Step 3: View - Technician verification scorecard
CREATE OR REPLACE VIEW v_tech_verification_score AS
SELECT
    v.id_user as technician_id,
    pu.fullname as technician_name,
    COUNT(*) as total_visits,
    SUM(CASE WHEN COALESCE(pc.cnt, 0) = 0 THEN 1 ELSE 0 END) as no_photo_visits,
    SUM(CASE WHEN v.latitude IS NULL OR v.latitude = 0 THEN 1 ELSE 0 END) as no_gps_visits,
    SUM(CASE WHEN v.latitude IS NOT NULL AND v.latitude != 0
                  AND v.latitude_o IS NOT NULL AND v.latitude_o != 0
                  AND 111320.0 * SQRT(
                      POWER(v.latitude - v.latitude_o, 2) +
                      POWER((v.longitude - v.longitude_o) * COS(RADIANS(v.latitude)), 2)
                  ) > 500
             THEN 1 ELSE 0 END) as gps_drift_visits,
    SUM(CASE WHEN v.check_out IS NOT NULL
                  AND EXTRACT(EPOCH FROM (v.check_out - v.check_in)) < 300
             THEN 1 ELSE 0 END) as too_short_visits,
    ROUND(
        100.0 * (
            COUNT(*) -
            SUM(CASE WHEN COALESCE(pc.cnt, 0) = 0 THEN 1 ELSE 0 END) -
            SUM(CASE WHEN v.latitude IS NULL OR v.latitude = 0 THEN 1 ELSE 0 END)
        ) / NULLIF(COUNT(*), 0),
        1
    ) as compliance_pct,
    AVG(COALESCE(pc.cnt, 0)) as avg_photos_per_visit
FROM t_visit v
LEFT JOIN p_user pu ON pu.id = v.id_user
LEFT JOIN (
    SELECT id_road_plan, COUNT(*) as cnt FROM t_road_plan_foto GROUP BY id_road_plan
) pc ON pc.id_road_plan = v.id_road_plan
WHERE v.check_in > NOW() - INTERVAL '30 days'
GROUP BY v.id_user, pu.fullname
ORDER BY compliance_pct ASC;

COMMENT ON VIEW v_tech_verification_score IS '30-day technician compliance scorecard for photo & GPS verification';
