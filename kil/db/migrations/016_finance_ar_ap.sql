-- =============================================================
-- Migration 016: Finance Module — AR & AP
-- =============================================================

-- ══════════════════════════════════════════════════════════════
-- ACCOUNTS RECEIVABLE
-- ══════════════════════════════════════════════════════════════

-- ── Sales Invoices ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_sales_invoices (
    id              BIGSERIAL    PRIMARY KEY,
    invoice_no      VARCHAR(50)  NOT NULL UNIQUE,  -- INV-2026-05-00001
    invoice_date    DATE         NOT NULL,
    due_date        DATE         NOT NULL,
    customer_name   VARCHAR(300) NOT NULL REFERENCES fin_customers(customer_name),
    service_type    VARCHAR(20),  -- PRC|TC|FUMIGASI|PRODUCT|DISINFECTANT
    profit_center_id BIGINT      REFERENCES fin_profit_centers(id),
    subtotal        NUMERIC(18,2) NOT NULL DEFAULT 0,
    discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    dpp             NUMERIC(18,2) NOT NULL DEFAULT 0,  -- Dasar Pengenaan Pajak
    ppn_rate        NUMERIC(5,2) NOT NULL DEFAULT 11.00,
    ppn_amount      NUMERIC(18,2) NOT NULL DEFAULT 0,
    total           NUMERIC(18,2) NOT NULL DEFAULT 0,
    paid_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,
    outstanding     NUMERIC(18,2) NOT NULL DEFAULT 0,
    status          VARCHAR(20)  NOT NULL DEFAULT 'DRAFT',
    -- DRAFT|POSTED|PARTIAL|PAID|CANCELLED|OVERDUE
    payment_terms   SMALLINT     NOT NULL DEFAULT 30,
    contract_ref    VARCHAR(100),
    description     TEXT,
    internal_notes  TEXT,
    journal_entry_id BIGINT      REFERENCES fin_journal_entries(id),
    period_id       BIGINT       REFERENCES fin_fiscal_periods(id),
    created_by      VARCHAR(100) NOT NULL,
    approved_by     VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_si_customer   ON fin_sales_invoices(customer_name);
CREATE INDEX IF NOT EXISTS idx_fin_si_date       ON fin_sales_invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_fin_si_due        ON fin_sales_invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_fin_si_status     ON fin_sales_invoices(status);
CREATE INDEX IF NOT EXISTS idx_fin_si_period     ON fin_sales_invoices(period_id);

-- ── Invoice Line Items ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_invoice_lines (
    id              BIGSERIAL    PRIMARY KEY,
    invoice_id      BIGINT       NOT NULL REFERENCES fin_sales_invoices(id) ON DELETE CASCADE,
    line_no         SMALLINT     NOT NULL,
    description     TEXT         NOT NULL,
    quantity        NUMERIC(12,2) NOT NULL DEFAULT 1,
    unit            VARCHAR(30),
    unit_price      NUMERIC(18,2) NOT NULL,
    total_price     NUMERIC(18,2) NOT NULL,
    revenue_account VARCHAR(20)  REFERENCES fin_accounts(code),
    profit_center_id BIGINT      REFERENCES fin_profit_centers(id)
);

-- ── AR Payments / Receipts ───────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_ar_payments (
    id              BIGSERIAL    PRIMARY KEY,
    receipt_no      VARCHAR(50)  NOT NULL UNIQUE,
    payment_date    DATE         NOT NULL,
    customer_name   VARCHAR(300) NOT NULL REFERENCES fin_customers(customer_name),
    bank_account_id BIGINT       REFERENCES fin_bank_accounts(id),
    payment_method  VARCHAR(30)  NOT NULL DEFAULT 'TRANSFER',  -- TRANSFER|CASH|CHEQUE
    gross_amount    NUMERIC(18,2) NOT NULL,
    bank_charge     NUMERIC(18,2) NOT NULL DEFAULT 0,
    net_amount      NUMERIC(18,2) NOT NULL,
    reference       VARCHAR(200),  -- bank transfer ref / cheque no
    notes           TEXT,
    journal_entry_id BIGINT      REFERENCES fin_journal_entries(id),
    created_by      VARCHAR(100) NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_pmt_customer  ON fin_ar_payments(customer_name);
CREATE INDEX IF NOT EXISTS idx_fin_pmt_date      ON fin_ar_payments(payment_date);

-- ── Payment Allocations ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_ar_allocations (
    id              BIGSERIAL    PRIMARY KEY,
    payment_id      BIGINT       NOT NULL REFERENCES fin_ar_payments(id) ON DELETE CASCADE,
    invoice_id      BIGINT       NOT NULL REFERENCES fin_sales_invoices(id),
    allocated_amount NUMERIC(18,2) NOT NULL,
    allocation_date DATE         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (payment_id, invoice_id)
);
CREATE INDEX IF NOT EXISTS idx_fin_alloc_invoice ON fin_ar_allocations(invoice_id);

-- ── Dunning (Penagihan) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_dunning_runs (
    id              BIGSERIAL    PRIMARY KEY,
    run_date        DATE         NOT NULL,
    customer_name   VARCHAR(300) NOT NULL REFERENCES fin_customers(customer_name),
    dunning_level   SMALLINT     NOT NULL DEFAULT 1,  -- 1=Reminder 2=Warning 3=Final
    total_outstanding NUMERIC(18,2) NOT NULL,
    overdue_days    SMALLINT,
    letter_generated BOOLEAN     NOT NULL DEFAULT FALSE,
    letter_sent_at  TIMESTAMPTZ,
    sent_via        VARCHAR(30),  -- EMAIL|WHATSAPP|MANUAL
    response_notes  TEXT,
    invoice_ids     BIGINT[],
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_dunning_customer ON fin_dunning_runs(customer_name);

-- ── Bad Debt Provision ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_bad_debt_provisions (
    id              BIGSERIAL    PRIMARY KEY,
    period_id       BIGINT       NOT NULL REFERENCES fin_fiscal_periods(id),
    customer_name   VARCHAR(300) NOT NULL REFERENCES fin_customers(customer_name),
    invoice_id      BIGINT       REFERENCES fin_sales_invoices(id),
    outstanding     NUMERIC(18,2) NOT NULL,
    overdue_days    SMALLINT     NOT NULL,
    provision_rate  NUMERIC(5,2) NOT NULL,  -- %
    provision_amount NUMERIC(18,2) NOT NULL,
    journal_entry_id BIGINT      REFERENCES fin_journal_entries(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (period_id, customer_name, invoice_id)
);

-- ── Invoice Number Sequence ───────────────────────────────────
CREATE SEQUENCE IF NOT EXISTS fin_inv_seq START 1;
CREATE OR REPLACE FUNCTION next_invoice_no(p_year INT, p_month INT)
RETURNS TEXT AS $$
DECLARE seq_val BIGINT;
BEGIN
    seq_val := nextval('fin_inv_seq');
    RETURN 'INV-' || p_year || '-' || LPAD(p_month::TEXT, 2, '0') || '-' || LPAD(seq_val::TEXT, 5, '0');
END;
$$ LANGUAGE plpgsql;

-- ── AR Outstanding Update Trigger ────────────────────────────
CREATE OR REPLACE FUNCTION update_invoice_outstanding()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE fin_sales_invoices
    SET    paid_amount  = (SELECT COALESCE(SUM(allocated_amount),0) FROM fin_ar_allocations WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id)),
           outstanding  = total - (SELECT COALESCE(SUM(allocated_amount),0) FROM fin_ar_allocations WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id)),
           status       = CASE
               WHEN total - (SELECT COALESCE(SUM(allocated_amount),0) FROM fin_ar_allocations WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id)) <= 0 THEN 'PAID'
               WHEN (SELECT COALESCE(SUM(allocated_amount),0) FROM fin_ar_allocations WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id)) > 0 THEN 'PARTIAL'
               ELSE status
           END,
           updated_at   = NOW()
    WHERE  id = COALESCE(NEW.invoice_id, OLD.invoice_id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_outstanding ON fin_ar_allocations;
CREATE TRIGGER trg_update_outstanding
    AFTER INSERT OR UPDATE OR DELETE ON fin_ar_allocations
    FOR EACH ROW EXECUTE FUNCTION update_invoice_outstanding();


-- ══════════════════════════════════════════════════════════════
-- ACCOUNTS PAYABLE
-- ══════════════════════════════════════════════════════════════

-- ── Purchase Invoices ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_purchase_invoices (
    id              BIGSERIAL    PRIMARY KEY,
    invoice_no      VARCHAR(50)  NOT NULL UNIQUE,  -- PI-2026-05-00001 (internal)
    vendor_invoice_no VARCHAR(100),                -- vendor's own invoice number
    invoice_date    DATE         NOT NULL,
    due_date        DATE         NOT NULL,
    vendor_id       BIGINT       NOT NULL REFERENCES fin_vendors(id),
    cost_center_id  BIGINT       REFERENCES fin_cost_centers(id),
    subtotal        NUMERIC(18,2) NOT NULL DEFAULT 0,
    ppn_amount      NUMERIC(18,2) NOT NULL DEFAULT 0,
    pph23_amount    NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_gross     NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_net       NUMERIC(18,2) NOT NULL DEFAULT 0,  -- gross - pph23
    paid_amount     NUMERIC(18,2) NOT NULL DEFAULT 0,
    outstanding     NUMERIC(18,2) NOT NULL DEFAULT 0,
    status          VARCHAR(20)  NOT NULL DEFAULT 'RECEIVED',
    -- RECEIVED|APPROVED|PARTIAL|PAID|CANCELLED
    description     TEXT,
    attachment_url  TEXT,
    journal_entry_id BIGINT      REFERENCES fin_journal_entries(id),
    period_id       BIGINT       REFERENCES fin_fiscal_periods(id),
    created_by      VARCHAR(100) NOT NULL,
    approved_by     VARCHAR(100),
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_pi_vendor     ON fin_purchase_invoices(vendor_id);
CREATE INDEX IF NOT EXISTS idx_fin_pi_date       ON fin_purchase_invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_fin_pi_due        ON fin_purchase_invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_fin_pi_status     ON fin_purchase_invoices(status);

-- ── Purchase Invoice Lines ───────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_purchase_lines (
    id              BIGSERIAL    PRIMARY KEY,
    invoice_id      BIGINT       NOT NULL REFERENCES fin_purchase_invoices(id) ON DELETE CASCADE,
    line_no         SMALLINT     NOT NULL,
    description     TEXT         NOT NULL,
    quantity        NUMERIC(12,2) NOT NULL DEFAULT 1,
    unit            VARCHAR(30),
    unit_price      NUMERIC(18,2) NOT NULL,
    total_price     NUMERIC(18,2) NOT NULL,
    expense_account VARCHAR(20)  REFERENCES fin_accounts(code),
    cost_center_id  BIGINT       REFERENCES fin_cost_centers(id)
);

-- ── AP Payments ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_ap_payments (
    id              BIGSERIAL    PRIMARY KEY,
    payment_no      VARCHAR(50)  NOT NULL UNIQUE,
    payment_date    DATE         NOT NULL,
    vendor_id       BIGINT       NOT NULL REFERENCES fin_vendors(id),
    bank_account_id BIGINT       REFERENCES fin_bank_accounts(id),
    payment_method  VARCHAR(30)  NOT NULL DEFAULT 'TRANSFER',
    gross_amount    NUMERIC(18,2) NOT NULL,
    pph23_withheld  NUMERIC(18,2) NOT NULL DEFAULT 0,
    net_amount      NUMERIC(18,2) NOT NULL,
    reference       VARCHAR(200),
    notes           TEXT,
    journal_entry_id BIGINT      REFERENCES fin_journal_entries(id),
    created_by      VARCHAR(100) NOT NULL,
    approved_by     VARCHAR(100),
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_ap_pmt_vendor ON fin_ap_payments(vendor_id);
CREATE INDEX IF NOT EXISTS idx_fin_ap_pmt_date   ON fin_ap_payments(payment_date);

-- ── AP Payment Allocations ───────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_ap_allocations (
    id              BIGSERIAL    PRIMARY KEY,
    payment_id      BIGINT       NOT NULL REFERENCES fin_ap_payments(id) ON DELETE CASCADE,
    invoice_id      BIGINT       NOT NULL REFERENCES fin_purchase_invoices(id),
    allocated_amount NUMERIC(18,2) NOT NULL,
    allocation_date DATE         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (payment_id, invoice_id)
);

-- ── PPh 23 Withholding Certificates ──────────────────────────
CREATE TABLE IF NOT EXISTS fin_pph23_certificates (
    id              BIGSERIAL    PRIMARY KEY,
    cert_no         VARCHAR(50)  NOT NULL UNIQUE,
    period_year     SMALLINT     NOT NULL,
    period_month    SMALLINT     NOT NULL,
    vendor_id       BIGINT       NOT NULL REFERENCES fin_vendors(id),
    payment_id      BIGINT       REFERENCES fin_ap_payments(id),
    gross_amount    NUMERIC(18,2) NOT NULL,
    pph23_rate      NUMERIC(5,2) NOT NULL DEFAULT 2.00,
    pph23_amount    NUMERIC(18,2) NOT NULL,
    issued_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Sequences
CREATE SEQUENCE IF NOT EXISTS fin_pi_seq START 1;
CREATE OR REPLACE FUNCTION next_purchase_invoice_no(p_year INT, p_month INT)
RETURNS TEXT AS $$
DECLARE seq_val BIGINT;
BEGIN
    seq_val := nextval('fin_pi_seq');
    RETURN 'PI-' || p_year || '-' || LPAD(p_month::TEXT, 2, '0') || '-' || LPAD(seq_val::TEXT, 5, '0');
END;
$$ LANGUAGE plpgsql;

CREATE SEQUENCE IF NOT EXISTS fin_pmt_seq START 1;
CREATE OR REPLACE FUNCTION next_payment_no(p_prefix TEXT, p_year INT, p_month INT)
RETURNS TEXT AS $$
DECLARE seq_val BIGINT;
BEGIN
    seq_val := nextval('fin_pmt_seq');
    RETURN p_prefix || '-' || p_year || '-' || LPAD(p_month::TEXT, 2, '0') || '-' || LPAD(seq_val::TEXT, 5, '0');
END;
$$ LANGUAGE plpgsql;

-- AP Outstanding trigger
CREATE OR REPLACE FUNCTION update_pi_outstanding()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE fin_purchase_invoices
    SET    paid_amount  = (SELECT COALESCE(SUM(allocated_amount),0) FROM fin_ap_allocations WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id)),
           outstanding  = total_net - (SELECT COALESCE(SUM(allocated_amount),0) FROM fin_ap_allocations WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id)),
           status       = CASE
               WHEN total_net - (SELECT COALESCE(SUM(allocated_amount),0) FROM fin_ap_allocations WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id)) <= 0 THEN 'PAID'
               WHEN (SELECT COALESCE(SUM(allocated_amount),0) FROM fin_ap_allocations WHERE invoice_id = COALESCE(NEW.invoice_id, OLD.invoice_id)) > 0 THEN 'PARTIAL'
               ELSE status END,
           updated_at   = NOW()
    WHERE  id = COALESCE(NEW.invoice_id, OLD.invoice_id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_pi_outstanding ON fin_ap_allocations;
CREATE TRIGGER trg_update_pi_outstanding
    AFTER INSERT OR UPDATE OR DELETE ON fin_ap_allocations
    FOR EACH ROW EXECUTE FUNCTION update_pi_outstanding();
