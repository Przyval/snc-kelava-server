-- Migration 010: Road Plans Write Layer
-- Tabel jadwal kunjungan yang dimiliki SanoCare (bukan read-only dari Kelava)
-- Digunakan saat koordinator membuat jadwal baru via portal/app kita
-- Saat transisi: jadwal lama tetap dibaca dari Kelava t_road_plan
-- Saat full migration: semua jadwal pindah ke sini

CREATE TABLE IF NOT EXISTS snc_road_plans (
    id                  BIGSERIAL PRIMARY KEY,
    -- Link ke Kelava (nullable — NULL berarti jadwal baru dari SNC)
    kelava_road_plan_id INTEGER,

    -- Core fields (mirip t_road_plan Kelava)
    visit_date          TIMESTAMPTZ NOT NULL,
    status              VARCHAR(50)  NOT NULL DEFAULT 'Baru',
                        -- 'Baru' | 'Berjalan' | 'Selesai' | 'Requested' | 'Cancelled'
    is_cancel           BOOLEAN NOT NULL DEFAULT false,
    visit_type          VARCHAR(50)  NOT NULL DEFAULT 'visit',

    -- References (p_user_id = Kelava ID, not enterprise_users.id)
    p_user_id           INTEGER NOT NULL,       -- FK conceptual → p_user.id (Kelava)
    customer_id         INTEGER NOT NULL,       -- FK conceptual → m_customer.id (Kelava)
    kontrak_id          INTEGER,                -- FK conceptual → m_customer_kontrak.id

    -- Scheduling metadata
    title               VARCHAR(256),
    remarks             TEXT,
    no_ra               VARCHAR(50),

    -- Audit
    created_by          INTEGER NOT NULL,       -- enterprise_users.id
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snc_road_plans_visit_date ON snc_road_plans(visit_date);
CREATE INDEX IF NOT EXISTS idx_snc_road_plans_p_user ON snc_road_plans(p_user_id);
CREATE INDEX IF NOT EXISTS idx_snc_road_plans_customer ON snc_road_plans(customer_id);
CREATE INDEX IF NOT EXISTS idx_snc_road_plans_status ON snc_road_plans(status);

-- Visit realisasi untuk jadwal dari SNC (mirip t_visit Kelava)
CREATE TABLE IF NOT EXISTS snc_visits (
    id              BIGSERIAL PRIMARY KEY,
    road_plan_id    BIGINT REFERENCES snc_road_plans(id) ON DELETE CASCADE,
    -- juga bisa link ke Kelava road plan
    kelava_road_plan_id INTEGER,

    p_user_id       INTEGER NOT NULL,
    customer_id     INTEGER,

    check_in        TIMESTAMPTZ,
    check_out       TIMESTAMPTZ,
    latitude        NUMERIC,
    longitude       NUMERIC,
    latitude_out    NUMERIC,
    longitude_out   NUMERIC,
    remarks         TEXT,
    additional_data JSONB,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snc_visits_road_plan ON snc_visits(road_plan_id);
CREATE INDEX IF NOT EXISTS idx_snc_visits_p_user ON snc_visits(p_user_id);
CREATE INDEX IF NOT EXISTS idx_snc_visits_check_in ON snc_visits(check_in);

-- Foto kunjungan (mirip t_road_plan_foto Kelava)
CREATE TABLE IF NOT EXISTS snc_visit_photos (
    id              BIGSERIAL PRIMARY KEY,
    visit_id        BIGINT REFERENCES snc_visits(id) ON DELETE CASCADE,
    road_plan_id    BIGINT,
    foto_url        VARCHAR(512) NOT NULL,
    stage           VARCHAR(50) NOT NULL DEFAULT 'visit', -- 'checkin' | 'checkout' | 'visit'
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- FCM tokens untuk push notification ke teknisi
CREATE TABLE IF NOT EXISTS snc_fcm_tokens (
    id              BIGSERIAL PRIMARY KEY,
    enterprise_user_id INTEGER NOT NULL REFERENCES enterprise_users(id) ON DELETE CASCADE,
    p_user_id       INTEGER,
    fcm_token       VARCHAR(512) NOT NULL,
    device_platform VARCHAR(20) DEFAULT 'android', -- 'android' | 'ios'
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(enterprise_user_id)
);
