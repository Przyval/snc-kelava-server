-- Migration 011: Customer & Contract Write Layer
-- SanoCare-owned tables for new customers & contracts.
-- Existing Kelava data stays read-only in m_customer / m_customer_kontrak.
-- New entries go here; app merges both sources.

-- ── Customers ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS snc_customers (
    id                    BIGSERIAL PRIMARY KEY,
    kelava_customer_id    INTEGER UNIQUE,     -- set when synced to Kelava

    -- Core identity
    name                  VARCHAR(256) NOT NULL,
    code                  VARCHAR(50),
    status                VARCHAR(50) NOT NULL DEFAULT 'Active',

    -- Contact
    address               TEXT,
    new_city              VARCHAR(100),
    new_province          VARCHAR(100),
    phone1                VARCHAR(30),
    phone2                VARCHAR(30),
    email                 VARCHAR(256),
    contact_person_name   VARCHAR(256),
    contact_person_phone  VARCHAR(30),

    -- Classification
    segment               VARCHAR(50),        -- 'Mobile' | 'Station' | etc
    id_sales              INTEGER,            -- p_user.id (sales rep)

    -- Audit
    created_by            INTEGER NOT NULL,   -- enterprise_users.id
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted            BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_snc_customers_name ON snc_customers(name);
CREATE INDEX IF NOT EXISTS idx_snc_customers_status ON snc_customers(status);
CREATE INDEX IF NOT EXISTS idx_snc_customers_kelava ON snc_customers(kelava_customer_id);

-- ── Contracts ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS snc_contracts (
    id                  BIGSERIAL PRIMARY KEY,
    kelava_contract_id  INTEGER UNIQUE,      -- set when synced to Kelava

    -- Customer reference (either SNC or Kelava customer)
    snc_customer_id     BIGINT REFERENCES snc_customers(id),
    kelava_customer_id  INTEGER,             -- m_customer.id

    -- Contract details
    no_kontrak          VARCHAR(256) NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    is_active           VARCHAR(10) NOT NULL DEFAULT 'YES',

    -- Coverage
    nilai_kontrak       NUMERIC(15,2),       -- contract value (IDR)
    frekuensi_visit     INTEGER DEFAULT 1,   -- visits per month
    notes               TEXT,

    -- Audit
    created_by          INTEGER NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT snc_contracts_customer_check
        CHECK (snc_customer_id IS NOT NULL OR kelava_customer_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_snc_contracts_snc_customer ON snc_contracts(snc_customer_id);
CREATE INDEX IF NOT EXISTS idx_snc_contracts_kelava_customer ON snc_contracts(kelava_customer_id);
CREATE INDEX IF NOT EXISTS idx_snc_contracts_active ON snc_contracts(is_active);
CREATE INDEX IF NOT EXISTS idx_snc_contracts_end_date ON snc_contracts(end_date);

-- ── Contract Areas (same structure as Kelava) ────────────

CREATE TABLE IF NOT EXISTS snc_contract_areas (
    id              BIGSERIAL PRIMARY KEY,
    contract_id     BIGINT NOT NULL REFERENCES snc_contracts(id) ON DELETE CASCADE,
    area            VARCHAR(256) NOT NULL,
    treatment_id    INTEGER,
    treatment_text  VARCHAR(256)
);

CREATE TABLE IF NOT EXISTS snc_contract_subareas (
    id              BIGSERIAL PRIMARY KEY,
    area_id         BIGINT NOT NULL REFERENCES snc_contract_areas(id) ON DELETE CASCADE,
    sub_area        VARCHAR(256) NOT NULL,
    kode_unit       VARCHAR(50)
);
