-- ============================================================
-- Migration 020: Finance Asset Management Module
-- Asset Register, Depreciation, Disposal, Physical Inventory
-- ============================================================

-- ── Extend fin_assets with full AM fields ─────────────────────
DO $$
BEGIN
    -- Add columns if they don't already exist (fin_assets created in 014)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='asset_no') THEN
        ALTER TABLE fin_assets ADD COLUMN asset_no VARCHAR(30) UNIQUE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='serial_no') THEN
        ALTER TABLE fin_assets ADD COLUMN serial_no VARCHAR(100);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='brand') THEN
        ALTER TABLE fin_assets ADD COLUMN brand VARCHAR(100);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='model') THEN
        ALTER TABLE fin_assets ADD COLUMN model VARCHAR(100);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='condition') THEN
        ALTER TABLE fin_assets ADD COLUMN condition VARCHAR(20) DEFAULT 'GOOD'
            CHECK (condition IN ('EXCELLENT','GOOD','FAIR','POOR'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='vendor_id') THEN
        ALTER TABLE fin_assets ADD COLUMN vendor_id BIGINT REFERENCES fin_vendors(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='purchase_invoice_id') THEN
        ALTER TABLE fin_assets ADD COLUMN purchase_invoice_id BIGINT REFERENCES fin_purchase_invoices(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='salvage_value') THEN
        ALTER TABLE fin_assets ADD COLUMN salvage_value NUMERIC(18,2) DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='current_book_value') THEN
        ALTER TABLE fin_assets ADD COLUMN current_book_value NUMERIC(18,2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='accumulated_depreciation') THEN
        ALTER TABLE fin_assets ADD COLUMN accumulated_depreciation NUMERIC(18,2) DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='depreciation_account') THEN
        ALTER TABLE fin_assets ADD COLUMN depreciation_account VARCHAR(20) DEFAULT '6101';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='accumulated_depreciation_account') THEN
        ALTER TABLE fin_assets ADD COLUMN accumulated_depreciation_account VARCHAR(20) DEFAULT '1502';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='asset_account') THEN
        ALTER TABLE fin_assets ADD COLUMN asset_account VARCHAR(20) DEFAULT '1501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='qr_code') THEN
        ALTER TABLE fin_assets ADD COLUMN qr_code TEXT;  -- base64 QR or reference
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='photo_url') THEN
        ALTER TABLE fin_assets ADD COLUMN photo_url TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='notes') THEN
        ALTER TABLE fin_assets ADD COLUMN notes TEXT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_assets' AND column_name='created_by') THEN
        ALTER TABLE fin_assets ADD COLUMN created_by VARCHAR(100);
        ALTER TABLE fin_assets ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
        ALTER TABLE fin_assets ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
END$$;

-- Update book values for existing assets
UPDATE fin_assets
SET current_book_value = purchase_cost - accumulated_depreciation
WHERE current_book_value IS NULL;

-- ── Asset Location History ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_asset_movements (
    id              BIGSERIAL PRIMARY KEY,
    asset_id        BIGINT NOT NULL REFERENCES fin_assets(id),
    movement_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    from_location   TEXT,
    to_location     TEXT NOT NULL,
    from_cc_id      BIGINT REFERENCES fin_cost_centers(id),
    to_cc_id        BIGINT REFERENCES fin_cost_centers(id),
    from_user       VARCHAR(100),
    to_user         VARCHAR(100),
    reason          TEXT,
    approved_by     VARCHAR(100),
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Asset Disposal ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_asset_disposals (
    id                  BIGSERIAL PRIMARY KEY,
    asset_id            BIGINT NOT NULL REFERENCES fin_assets(id) UNIQUE,
    disposal_date       DATE NOT NULL,
    disposal_type       VARCHAR(20) NOT NULL CHECK (disposal_type IN ('SALE','WRITE_OFF','DONATION','LOSS')),
    sale_amount         NUMERIC(18,2) DEFAULT 0,
    book_value_at_disposal NUMERIC(18,2) NOT NULL,
    gain_loss           NUMERIC(18,2),  -- positive = gain, negative = loss
    buyer_name          TEXT,
    reference           VARCHAR(100),
    journal_entry_id    BIGINT REFERENCES fin_journal_entries(id),
    approved_by         VARCHAR(100),
    notes               TEXT,
    created_by          VARCHAR(100),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Physical Inventory Scan Log ───────────────────────────────
CREATE TABLE IF NOT EXISTS fin_asset_scans (
    id              BIGSERIAL PRIMARY KEY,
    scan_session_id VARCHAR(50),
    asset_id        BIGINT REFERENCES fin_assets(id),
    scanned_at      TIMESTAMPTZ DEFAULT NOW(),
    scanned_by      VARCHAR(100),
    location_found  TEXT,
    condition_found VARCHAR(20),
    photo_url       TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS fin_inventory_sessions (
    id              BIGSERIAL PRIMARY KEY,
    session_code    VARCHAR(50) UNIQUE NOT NULL,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    conducted_by    VARCHAR(100),
    total_assets    INT DEFAULT 0,
    assets_found    INT DEFAULT 0,
    assets_missing  INT DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'OPEN' CHECK (status IN ('OPEN','COMPLETED')),
    notes           TEXT
);

-- ── Depreciation Schedule (per asset, pre-computed) ───────────
CREATE TABLE IF NOT EXISTS fin_depreciation_schedule (
    id              BIGSERIAL PRIMARY KEY,
    asset_id        BIGINT NOT NULL REFERENCES fin_assets(id),
    period_year     INT NOT NULL,
    period_month    INT NOT NULL,
    opening_value   NUMERIC(18,2),
    depreciation    NUMERIC(18,2),
    closing_value   NUMERIC(18,2),
    is_posted       BOOLEAN DEFAULT FALSE,
    journal_entry_id BIGINT REFERENCES fin_journal_entries(id),
    UNIQUE (asset_id, period_year, period_month)
);

-- ── View: Asset Register with Current Status ──────────────────
CREATE OR REPLACE VIEW v_fin_asset_register AS
SELECT
    a.id,
    a.asset_no,
    a.description,
    a.category,
    a.brand,
    a.model,
    a.serial_no,
    a.location,
    cc.name                 AS cost_center,
    a.purchase_date,
    a.purchase_cost,
    a.useful_life_months,
    a.depreciation_method,
    a.salvage_value,
    a.accumulated_depreciation,
    GREATEST(a.purchase_cost - a.accumulated_depreciation - a.salvage_value, 0)
                            AS net_book_value,
    a.condition,
    a.is_disposed,
    CASE
        WHEN a.is_disposed THEN 'DISPOSED'
        WHEN a.purchase_date + (a.useful_life_months || ' months')::INTERVAL < CURRENT_DATE THEN 'FULLY_DEPRECIATED'
        ELSE 'ACTIVE'
    END                     AS asset_status,
    -- Months remaining
    GREATEST(0,
        a.useful_life_months -
        EXTRACT(MONTH FROM AGE(CURRENT_DATE, a.purchase_date))::INT -
        EXTRACT(YEAR FROM AGE(CURRENT_DATE, a.purchase_date))::INT * 12
    )                       AS months_remaining
FROM fin_assets a
LEFT JOIN fin_cost_centers cc ON cc.id = a.cost_center_id;

-- ── View: Depreciation Forecast (next 12 months) ──────────────
CREATE OR REPLACE VIEW v_fin_depreciation_forecast AS
SELECT
    a.id            AS asset_id,
    a.asset_no,
    a.description,
    a.category,
    gs.month_offset,
    DATE_TRUNC('month', CURRENT_DATE) + (gs.month_offset || ' months')::INTERVAL AS forecast_month,
    CASE a.depreciation_method
        WHEN 'STRAIGHT_LINE' THEN
            ROUND(
                (a.purchase_cost - a.salvage_value) / NULLIF(a.useful_life_months, 0), 2
            )
        WHEN 'DECLINING_BALANCE' THEN
            ROUND(
                GREATEST(a.purchase_cost - a.accumulated_depreciation - a.salvage_value, 0)
                * 2.0 / NULLIF(a.useful_life_months, 0), 2
            )
        ELSE 0
    END             AS monthly_depreciation
FROM fin_assets a
CROSS JOIN generate_series(0, 11) AS gs(month_offset)
WHERE NOT a.is_disposed
  AND a.purchase_date + (a.useful_life_months || ' months')::INTERVAL > CURRENT_DATE;
