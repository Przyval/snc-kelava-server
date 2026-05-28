-- ============================================================
-- Migration 022: Finance Audit & Compliance Module
-- Document Management, SoD Controls, Month-End Close, Approval Workflow
-- ============================================================

-- ── Document Attachments (link files to any finance record) ───
CREATE TABLE IF NOT EXISTS fin_documents (
    id              BIGSERIAL PRIMARY KEY,
    doc_type        VARCHAR(30) NOT NULL
                        CHECK (doc_type IN (
                            'SALES_INVOICE','PURCHASE_INVOICE','JOURNAL_ENTRY',
                            'AR_PAYMENT','AP_PAYMENT','BANK_STATEMENT','ASSET_PHOTO',
                            'CONTRACT','TAX_FAKTUR','BUKTI_POTONG','SPT','OTHER'
                        )),
    reference_id    BIGINT NOT NULL,    -- ID of the linked record
    filename        VARCHAR(255) NOT NULL,
    original_name   VARCHAR(255) NOT NULL,
    file_size       INT,                -- bytes
    mime_type       VARCHAR(100),
    storage_path    TEXT NOT NULL,      -- local path or S3 key
    description     TEXT,
    uploaded_by     VARCHAR(100),
    uploaded_at     TIMESTAMPTZ DEFAULT NOW(),
    is_deleted      BOOLEAN DEFAULT FALSE,
    deleted_at      TIMESTAMPTZ,
    deleted_by      VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_fin_docs_ref ON fin_documents(doc_type, reference_id);
CREATE INDEX IF NOT EXISTS idx_fin_docs_uploaded ON fin_documents(uploaded_by, uploaded_at DESC);

-- ── Approval Queue (SoD-compliant approval workflow) ──────────
CREATE TABLE IF NOT EXISTS fin_approval_queue (
    id              BIGSERIAL PRIMARY KEY,
    module          VARCHAR(30) NOT NULL
                        CHECK (module IN ('JE','AR_INVOICE','AP_INVOICE','AR_PAYMENT','AP_PAYMENT','BUDGET','DISPOSAL')),
    record_id       BIGINT NOT NULL,
    record_ref      VARCHAR(50),        -- human-readable: JE-2026-05-00012
    description     TEXT,
    amount          NUMERIC(18,2),
    submitted_by    VARCHAR(100) NOT NULL,
    submitted_at    TIMESTAMPTZ DEFAULT NOW(),
    required_role   VARCHAR(50),        -- finance_manager | direktur
    status          VARCHAR(20) DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','APPROVED','REJECTED','RECALLED')),
    reviewed_by     VARCHAR(100),
    reviewed_at     TIMESTAMPTZ,
    review_notes    TEXT
);

CREATE INDEX IF NOT EXISTS idx_fin_approval_status ON fin_approval_queue(status, module);

-- ── SoD Violation Log (attempted policy breaches) ─────────────
CREATE TABLE IF NOT EXISTS fin_sod_violations (
    id              BIGSERIAL PRIMARY KEY,
    user_email      VARCHAR(255) NOT NULL,
    attempted_action VARCHAR(100) NOT NULL,
    record_module   VARCHAR(30),
    record_id       BIGINT,
    violation_rule  TEXT NOT NULL,      -- e.g. "Cannot approve own submission"
    blocked_at      TIMESTAMPTZ DEFAULT NOW(),
    ip_address      VARCHAR(45)
);

-- ── Month-End Close Checklist Instances ───────────────────────
CREATE TABLE IF NOT EXISTS fin_close_checklist_instances (
    id              BIGSERIAL PRIMARY KEY,
    period_id       BIGINT NOT NULL REFERENCES fin_fiscal_periods(id),
    checklist_item  VARCHAR(100) NOT NULL,
    sequence_no     INT DEFAULT 0,
    assigned_to     VARCHAR(100),
    target_date     DATE,
    status          VARCHAR(20) DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','IN_PROGRESS','DONE','SKIPPED')),
    completed_by    VARCHAR(100),
    completed_at    TIMESTAMPTZ,
    notes           TEXT,
    UNIQUE (period_id, checklist_item)
);

-- ── Populate checklist items for current open period ──────────
INSERT INTO fin_close_checklist_instances
    (period_id, checklist_item, sequence_no, target_date)
SELECT
    fp.id,
    item,
    seq,
    fp.end_date + seq
FROM fin_fiscal_periods fp
CROSS JOIN (VALUES
    (1, 'Bank reconciliation — semua rekening'),
    (2, 'AR: match semua pembayaran ke invoice'),
    (3, 'AP: posting semua invoice yang diterima'),
    (4, 'Recurring entries (gaji, sewa, depreciation)'),
    (5, 'Accruals (biaya yang belum ada invoice)'),
    (6, 'Intercompany reconciliation'),
    (7, 'Review AR aging & flag bad debt'),
    (8, 'Trial balance review'),
    (9, 'P&L review by manager'),
    (10,'Lock period')
) AS t(seq, item)
WHERE fp.status = 'OPEN'
ON CONFLICT DO NOTHING;

-- ── Reconciliation Packages (for KAP/auditor) ─────────────────
CREATE TABLE IF NOT EXISTS fin_audit_packages (
    id              BIGSERIAL PRIMARY KEY,
    package_no      VARCHAR(30) UNIQUE NOT NULL,
    period_year     INT NOT NULL,
    period_type     VARCHAR(10) NOT NULL CHECK (period_type IN ('MONTHLY','QUARTERLY','ANNUAL')),
    period_from     DATE NOT NULL,
    period_to       DATE NOT NULL,
    status          VARCHAR(20) DEFAULT 'DRAFT'
                        CHECK (status IN ('DRAFT','SUBMITTED','ACCEPTED','QUERIES_RAISED')),
    total_assets    NUMERIC(18,2),
    total_revenue   NUMERIC(18,2),
    net_profit      NUMERIC(18,2),
    auditor_name    TEXT,
    submitted_at    TIMESTAMPTZ,
    notes           TEXT,
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Finance Audit Trail (fine-grained: every value change) ────
-- (complementing the general fin_audit_log from migration 015)
CREATE TABLE IF NOT EXISTS fin_field_changes (
    id              BIGSERIAL PRIMARY KEY,
    table_name      VARCHAR(50) NOT NULL,
    record_id       BIGINT NOT NULL,
    field_name      VARCHAR(100) NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    changed_by      VARCHAR(100),
    changed_at      TIMESTAMPTZ DEFAULT NOW(),
    change_reason   TEXT
);

CREATE INDEX IF NOT EXISTS idx_fin_field_changes ON fin_field_changes(table_name, record_id, changed_at DESC);

-- ── View: Pending Approvals Dashboard ─────────────────────────
CREATE OR REPLACE VIEW v_fin_pending_approvals AS
SELECT
    aq.id,
    aq.module,
    aq.record_ref,
    aq.description,
    aq.amount,
    aq.submitted_by,
    aq.submitted_at,
    aq.required_role,
    EXTRACT(EPOCH FROM (NOW() - aq.submitted_at))/3600 AS hours_pending
FROM fin_approval_queue aq
WHERE aq.status = 'PENDING'
ORDER BY aq.submitted_at;

-- ── View: Compliance Dashboard ────────────────────────────────
CREATE OR REPLACE VIEW v_fin_compliance_dashboard AS
SELECT
    'close_checklist'                               AS category,
    COUNT(*) FILTER (WHERE status='PENDING')        AS open_count,
    COUNT(*) FILTER (WHERE status='DONE')           AS done_count,
    COUNT(*)                                        AS total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status='DONE') / NULLIF(COUNT(*),0), 0) AS pct_done
FROM fin_close_checklist_instances
WHERE period_id IN (
    SELECT id FROM fin_fiscal_periods WHERE status='OPEN'
)
UNION ALL
SELECT
    'pending_approvals',
    COUNT(*),
    0,
    COUNT(*),
    0
FROM fin_approval_queue WHERE status='PENDING'
UNION ALL
SELECT
    'unreconciled_bank',
    COUNT(*),
    0,
    COUNT(*),
    0
FROM fin_bank_transactions WHERE NOT reconciled
UNION ALL
SELECT
    'tax_overdue',
    COUNT(*),
    0,
    COUNT(*),
    0
FROM fin_tax_calendar WHERE status='PENDING' AND deadline < CURRENT_DATE;

-- ── View: SoD Summary ─────────────────────────────────────────
CREATE OR REPLACE VIEW v_fin_sod_summary AS
SELECT
    user_email,
    COUNT(*)                            AS total_violations,
    MAX(blocked_at)                     AS last_violation,
    array_agg(DISTINCT attempted_action ORDER BY attempted_action) AS actions_attempted
FROM fin_sod_violations
WHERE blocked_at > NOW() - INTERVAL '90 days'
GROUP BY user_email
ORDER BY total_violations DESC;
