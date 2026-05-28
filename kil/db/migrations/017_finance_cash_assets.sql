-- =============================================================
-- Migration 017: Finance Module — Cash, Bank & Fixed Assets
-- =============================================================

-- ══════════════════════════════════════════════════════════════
-- CASH & BANK MANAGEMENT
-- ══════════════════════════════════════════════════════════════

-- ── Bank Transactions ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_bank_transactions (
    id              BIGSERIAL    PRIMARY KEY,
    bank_account_id BIGINT       NOT NULL REFERENCES fin_bank_accounts(id),
    txn_date        DATE         NOT NULL,
    value_date      DATE,
    description     TEXT         NOT NULL,
    reference       VARCHAR(200),
    debit           NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit          NUMERIC(18,2) NOT NULL DEFAULT 0,
    running_balance NUMERIC(18,2),
    txn_type        VARCHAR(30),  -- TRANSFER_IN|TRANSFER_OUT|BANK_CHARGE|INTEREST|OTHER
    reconciled      BOOLEAN      NOT NULL DEFAULT FALSE,
    reconciled_at   TIMESTAMPTZ,
    journal_entry_id BIGINT      REFERENCES fin_journal_entries(id),
    source          VARCHAR(30)  NOT NULL DEFAULT 'MANUAL',  -- MANUAL|IMPORT|AUTO
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_bank_txn_acct  ON fin_bank_transactions(bank_account_id);
CREATE INDEX IF NOT EXISTS idx_fin_bank_txn_date  ON fin_bank_transactions(txn_date);
CREATE INDEX IF NOT EXISTS idx_fin_bank_txn_recon ON fin_bank_transactions(reconciled);

-- ── Bank Reconciliation Sessions ────────────────────────────
CREATE TABLE IF NOT EXISTS fin_bank_reconciliations (
    id              BIGSERIAL    PRIMARY KEY,
    bank_account_id BIGINT       NOT NULL REFERENCES fin_bank_accounts(id),
    period_id       BIGINT       NOT NULL REFERENCES fin_fiscal_periods(id),
    statement_date  DATE         NOT NULL,
    statement_balance NUMERIC(18,2) NOT NULL,
    gl_balance      NUMERIC(18,2) NOT NULL,
    reconciled_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    difference      NUMERIC(18,2) NOT NULL DEFAULT 0,
    status          VARCHAR(20)  NOT NULL DEFAULT 'IN_PROGRESS',  -- IN_PROGRESS|COMPLETE
    completed_by    VARCHAR(100),
    completed_at    TIMESTAMPTZ,
    notes           TEXT,
    created_by      VARCHAR(100) NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (bank_account_id, period_id)
);

-- ── Cash Flow Forecast ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_cash_forecasts (
    id              BIGSERIAL    PRIMARY KEY,
    forecast_date   DATE         NOT NULL,
    run_date        DATE         NOT NULL DEFAULT CURRENT_DATE,
    horizon_days    SMALLINT     NOT NULL DEFAULT 30,
    opening_balance NUMERIC(18,2) NOT NULL,
    ar_expected     NUMERIC(18,2) NOT NULL DEFAULT 0,  -- from AR due dates
    ap_expected     NUMERIC(18,2) NOT NULL DEFAULT 0,  -- from AP due dates
    payroll_expected NUMERIC(18,2) NOT NULL DEFAULT 0, -- estimated salary
    other_inflow    NUMERIC(18,2) NOT NULL DEFAULT 0,
    other_outflow   NUMERIC(18,2) NOT NULL DEFAULT 0,
    projected_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    low_cash_alert  BOOLEAN      NOT NULL DEFAULT FALSE,
    alert_threshold NUMERIC(18,2) NOT NULL DEFAULT 100000000,  -- 100M default
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Petty Cash ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_petty_cash (
    id              BIGSERIAL    PRIMARY KEY,
    txn_date        DATE         NOT NULL,
    txn_type        VARCHAR(20)  NOT NULL DEFAULT 'EXPENSE',  -- EXPENSE|REPLENISHMENT
    description     TEXT         NOT NULL,
    amount          NUMERIC(18,2) NOT NULL,
    expense_account VARCHAR(20)  REFERENCES fin_accounts(code),
    cost_center_id  BIGINT       REFERENCES fin_cost_centers(id),
    receipt_ref     VARCHAR(100),
    approved_by     VARCHAR(100),
    journal_entry_id BIGINT      REFERENCES fin_journal_entries(id),
    created_by      VARCHAR(100) NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Daily Cash Position View ─────────────────────────────────
CREATE OR REPLACE VIEW v_fin_cash_position AS
SELECT
    ba.id,
    ba.code,
    ba.name,
    ba.bank_name,
    ba.currency,
    ba.current_balance,
    ba.last_reconciled,
    COALESCE(
        (SELECT SUM(credit) - SUM(debit)
         FROM fin_bank_transactions bt
         WHERE bt.bank_account_id = ba.id
           AND bt.txn_date = CURRENT_DATE), 0
    ) AS today_net,
    ba.current_balance + COALESCE(
        (SELECT SUM(credit) - SUM(debit)
         FROM fin_bank_transactions bt
         WHERE bt.bank_account_id = ba.id
           AND bt.txn_date = CURRENT_DATE), 0
    ) AS today_balance
FROM fin_bank_accounts ba
WHERE ba.is_active = TRUE;

-- ══════════════════════════════════════════════════════════════
-- FIXED ASSETS
-- ══════════════════════════════════════════════════════════════

-- ── Depreciation Runs ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_depreciation_runs (
    id              BIGSERIAL    PRIMARY KEY,
    period_id       BIGINT       NOT NULL REFERENCES fin_fiscal_periods(id),
    run_date        DATE         NOT NULL DEFAULT CURRENT_DATE,
    total_assets    INTEGER      NOT NULL DEFAULT 0,
    total_depreciation NUMERIC(18,2) NOT NULL DEFAULT 0,
    status          VARCHAR(20)  NOT NULL DEFAULT 'DRAFT',  -- DRAFT|POSTED
    journal_entry_id BIGINT      REFERENCES fin_journal_entries(id),
    run_by          VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (period_id)
);

-- ── Depreciation Detail ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_depreciation_detail (
    id              BIGSERIAL    PRIMARY KEY,
    run_id          BIGINT       NOT NULL REFERENCES fin_depreciation_runs(id) ON DELETE CASCADE,
    asset_id        BIGINT       NOT NULL REFERENCES fin_assets(id),
    opening_book_value NUMERIC(18,2) NOT NULL,
    depreciation_amount NUMERIC(18,2) NOT NULL,
    accumulated_after NUMERIC(18,2) NOT NULL,
    closing_book_value NUMERIC(18,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fin_dep_detail_run ON fin_depreciation_detail(run_id);

-- ── Asset Physical Inventory ─────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_asset_inventory (
    id              BIGSERIAL    PRIMARY KEY,
    inventory_date  DATE         NOT NULL,
    asset_id        BIGINT       NOT NULL REFERENCES fin_assets(id),
    found           BOOLEAN      NOT NULL DEFAULT TRUE,
    condition       VARCHAR(30)  NOT NULL DEFAULT 'GOOD',  -- GOOD|FAIR|POOR|MISSING
    location_actual VARCHAR(200),
    notes           TEXT,
    inspected_by    VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Monthly Depreciation Calculator Function ─────────────────
CREATE OR REPLACE FUNCTION calc_monthly_depreciation(
    p_asset_id BIGINT,
    p_period_id BIGINT
) RETURNS NUMERIC AS $$
DECLARE
    v_cost          NUMERIC;
    v_salvage       NUMERIC;
    v_life          SMALLINT;
    v_method        VARCHAR;
    v_accumulated   NUMERIC;
    v_book_value    NUMERIC;
    v_monthly_dep   NUMERIC;
BEGIN
    SELECT purchase_cost, salvage_value, useful_life_months,
           depreciation_method, accumulated_depreciation, book_value
    INTO   v_cost, v_salvage, v_life, v_method, v_accumulated, v_book_value
    FROM   fin_assets
    WHERE  id = p_asset_id AND status = 'ACTIVE';

    IF NOT FOUND THEN RETURN 0; END IF;
    IF v_book_value <= v_salvage THEN RETURN 0; END IF;

    IF v_method = 'STRAIGHT_LINE' THEN
        v_monthly_dep := (v_cost - v_salvage) / v_life;
    ELSIF v_method = 'DECLINING_BALANCE' THEN
        v_monthly_dep := v_book_value * (2.0 / v_life);
    ELSE
        v_monthly_dep := (v_cost - v_salvage) / v_life;
    END IF;

    -- Don't depreciate below salvage value
    RETURN LEAST(v_monthly_dep, v_book_value - v_salvage);
END;
$$ LANGUAGE plpgsql;
