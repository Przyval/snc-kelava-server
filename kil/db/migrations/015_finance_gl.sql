-- =============================================================
-- Migration 015: Finance Module — General Ledger
-- Journal Entries, GL Line Items, Account Balances
-- =============================================================

-- ── Journal Entries ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_journal_entries (
    id              BIGSERIAL    PRIMARY KEY,
    entry_no        VARCHAR(30)  NOT NULL UNIQUE,  -- JE-2026-05-00001
    entry_date      DATE         NOT NULL,
    period_id       BIGINT       NOT NULL REFERENCES fin_fiscal_periods(id),
    reference       VARCHAR(100),
    description     TEXT         NOT NULL,
    entry_type      VARCHAR(30)  NOT NULL DEFAULT 'MANUAL',
    -- MANUAL|AUTO_AR|AUTO_AP|AUTO_PAYROLL|AUTO_DEPRECIATION|AUTO_BANK|REVERSAL
    total_debit     NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_credit    NUMERIC(18,2) NOT NULL DEFAULT 0,
    status          VARCHAR(20)  NOT NULL DEFAULT 'DRAFT',
    -- DRAFT|PENDING_APPROVAL|APPROVED|POSTED|REVERSED
    reversal_of_id  BIGINT       REFERENCES fin_journal_entries(id),
    reversed_by_id  BIGINT       REFERENCES fin_journal_entries(id),
    source_module   VARCHAR(30),  -- AR|AP|BANK|ASSET|PAYROLL
    source_id       BIGINT,       -- FK to source document
    created_by      VARCHAR(100) NOT NULL,
    approved_by     VARCHAR(100),
    approved_at     TIMESTAMPTZ,
    posted_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_je_date       ON fin_journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_fin_je_period     ON fin_journal_entries(period_id);
CREATE INDEX IF NOT EXISTS idx_fin_je_status     ON fin_journal_entries(status);
CREATE INDEX IF NOT EXISTS idx_fin_je_type       ON fin_journal_entries(entry_type);
CREATE INDEX IF NOT EXISTS idx_fin_je_source     ON fin_journal_entries(source_module, source_id);

-- ── GL Line Items ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_gl_lines (
    id              BIGSERIAL    PRIMARY KEY,
    journal_entry_id BIGINT      NOT NULL REFERENCES fin_journal_entries(id) ON DELETE CASCADE,
    line_no         SMALLINT     NOT NULL DEFAULT 1,
    account_code    VARCHAR(20)  NOT NULL REFERENCES fin_accounts(code),
    cost_center_id  BIGINT       REFERENCES fin_cost_centers(id),
    profit_center_id BIGINT      REFERENCES fin_profit_centers(id),
    debit           NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit          NUMERIC(18,2) NOT NULL DEFAULT 0,
    description     TEXT,
    customer_name   VARCHAR(300) REFERENCES fin_customers(customer_name),
    vendor_id       BIGINT       REFERENCES fin_vendors(id),
    asset_id        BIGINT       REFERENCES fin_assets(id),
    currency        VARCHAR(3)   NOT NULL DEFAULT 'IDR',
    exchange_rate   NUMERIC(12,4) NOT NULL DEFAULT 1,
    amount_foreign  NUMERIC(18,2),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_gl_je         ON fin_gl_lines(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_fin_gl_account    ON fin_gl_lines(account_code);
CREATE INDEX IF NOT EXISTS idx_fin_gl_customer   ON fin_gl_lines(customer_name);
CREATE INDEX IF NOT EXISTS idx_fin_gl_vendor     ON fin_gl_lines(vendor_id);

-- ── Account Balances (Period Summary) ───────────────────────
-- Pre-computed for fast reporting; rebuilt on period close
CREATE TABLE IF NOT EXISTS fin_account_balances (
    id              BIGSERIAL    PRIMARY KEY,
    period_id       BIGINT       NOT NULL REFERENCES fin_fiscal_periods(id),
    account_code    VARCHAR(20)  NOT NULL REFERENCES fin_accounts(code),
    cost_center_id  BIGINT       REFERENCES fin_cost_centers(id),
    opening_debit   NUMERIC(18,2) NOT NULL DEFAULT 0,
    opening_credit  NUMERIC(18,2) NOT NULL DEFAULT 0,
    period_debit    NUMERIC(18,2) NOT NULL DEFAULT 0,
    period_credit   NUMERIC(18,2) NOT NULL DEFAULT 0,
    closing_debit   NUMERIC(18,2) NOT NULL DEFAULT 0,
    closing_credit  NUMERIC(18,2) NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (period_id, account_code, cost_center_id)
);
CREATE INDEX IF NOT EXISTS idx_fin_balances_period ON fin_account_balances(period_id);
CREATE INDEX IF NOT EXISTS idx_fin_balances_account ON fin_account_balances(account_code);

-- ── Recurring Journal Templates ──────────────────────────────
CREATE TABLE IF NOT EXISTS fin_recurring_templates (
    id              BIGSERIAL    PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    frequency       VARCHAR(20)  NOT NULL DEFAULT 'MONTHLY',  -- MONTHLY|QUARTERLY|YEARLY
    next_run_date   DATE         NOT NULL,
    last_run_date   DATE,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fin_recurring_lines (
    id              BIGSERIAL    PRIMARY KEY,
    template_id     BIGINT       NOT NULL REFERENCES fin_recurring_templates(id) ON DELETE CASCADE,
    line_no         SMALLINT     NOT NULL,
    account_code    VARCHAR(20)  NOT NULL REFERENCES fin_accounts(code),
    cost_center_id  BIGINT       REFERENCES fin_cost_centers(id),
    debit           NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit          NUMERIC(18,2) NOT NULL DEFAULT 0,
    description     TEXT
);

-- ── Entry Number Sequence Helper ─────────────────────────────
CREATE SEQUENCE IF NOT EXISTS fin_je_seq START 1;

CREATE OR REPLACE FUNCTION next_journal_entry_no(p_year INT, p_month INT)
RETURNS TEXT AS $$
DECLARE
    seq_val BIGINT;
BEGIN
    seq_val := nextval('fin_je_seq');
    RETURN 'JE-' || p_year || '-' || LPAD(p_month::TEXT, 2, '0') || '-' || LPAD(seq_val::TEXT, 5, '0');
END;
$$ LANGUAGE plpgsql;

-- ── GL Integrity Constraint ──────────────────────────────────
-- Enforce debit = credit on posted entries
CREATE OR REPLACE FUNCTION check_je_balance()
RETURNS TRIGGER AS $$
DECLARE
    total_dr NUMERIC;
    total_cr NUMERIC;
BEGIN
    IF NEW.status = 'POSTED' THEN
        SELECT COALESCE(SUM(debit),0), COALESCE(SUM(credit),0)
        INTO   total_dr, total_cr
        FROM   fin_gl_lines
        WHERE  journal_entry_id = NEW.id;

        IF ABS(total_dr - total_cr) > 0.01 THEN
            RAISE EXCEPTION 'Journal entry % is unbalanced: debit=% credit=%',
                NEW.entry_no, total_dr, total_cr;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_je_balance ON fin_journal_entries;
CREATE TRIGGER trg_je_balance
    BEFORE UPDATE ON fin_journal_entries
    FOR EACH ROW EXECUTE FUNCTION check_je_balance();

-- ── Audit Log for GL ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_audit_log (
    id              BIGSERIAL    PRIMARY KEY,
    table_name      VARCHAR(100) NOT NULL,
    record_id       BIGINT       NOT NULL,
    action          VARCHAR(20)  NOT NULL,  -- INSERT|UPDATE|DELETE
    old_data        JSONB,
    new_data        JSONB,
    changed_by      VARCHAR(100) NOT NULL,
    changed_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ip_address      VARCHAR(50)
);
CREATE INDEX IF NOT EXISTS idx_fin_audit_table   ON fin_audit_log(table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_fin_audit_changed ON fin_audit_log(changed_at);
