-- ============================================================
-- Migration 019: Finance Controlling (CO) Module
-- Cost Center P&L, Budget vs Actual, Variance, Profitability
-- ============================================================

-- ── Internal Orders (project/event tracking) ──────────────────
CREATE TABLE IF NOT EXISTS fin_internal_orders (
    id              BIGSERIAL PRIMARY KEY,
    order_no        VARCHAR(20) UNIQUE NOT NULL,
    description     TEXT NOT NULL,
    cost_center_id  BIGINT REFERENCES fin_cost_centers(id),
    profit_center_id BIGINT REFERENCES fin_profit_centers(id),
    responsible_user VARCHAR(100),
    budget_amount   NUMERIC(18,2) DEFAULT 0,
    start_date      DATE,
    end_date        DATE,
    status          VARCHAR(20) DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED','CANCELLED')),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    created_by      VARCHAR(100)
);

-- ── Budget Lines (per account per cost center per period) ──────
-- fin_budgets already exists from migration 014
-- Add profit_center_id column if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='fin_budgets' AND column_name='profit_center_id'
    ) THEN
        ALTER TABLE fin_budgets ADD COLUMN profit_center_id BIGINT REFERENCES fin_profit_centers(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='fin_budgets' AND column_name='internal_order_id'
    ) THEN
        ALTER TABLE fin_budgets ADD COLUMN internal_order_id BIGINT REFERENCES fin_internal_orders(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='fin_budgets' AND column_name='description'
    ) THEN
        ALTER TABLE fin_budgets ADD COLUMN description TEXT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='fin_budgets' AND column_name='created_by'
    ) THEN
        ALTER TABLE fin_budgets ADD COLUMN created_by VARCHAR(100);
        ALTER TABLE fin_budgets ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
END$$;

-- ── Cost Allocations (overhead → profit centers) ───────────────
CREATE TABLE IF NOT EXISTS fin_cost_allocations (
    id                  BIGSERIAL PRIMARY KEY,
    period_id           BIGINT REFERENCES fin_fiscal_periods(id),
    from_cost_center_id BIGINT REFERENCES fin_cost_centers(id),
    to_profit_center_id BIGINT REFERENCES fin_profit_centers(id),
    account_code        VARCHAR(20),
    amount              NUMERIC(18,2) NOT NULL,
    allocation_key      VARCHAR(50),  -- REVENUE_SHARE | HEADCOUNT | MANUAL
    allocation_pct      NUMERIC(8,4),
    description         TEXT,
    journal_entry_id    BIGINT REFERENCES fin_journal_entries(id),
    created_by          VARCHAR(100),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ── Budget Revisions (audit trail of budget changes) ───────────
CREATE TABLE IF NOT EXISTS fin_budget_revisions (
    id              BIGSERIAL PRIMARY KEY,
    budget_id       BIGINT REFERENCES fin_budgets(id),
    old_amount      NUMERIC(18,2),
    new_amount      NUMERIC(18,2),
    revision_reason TEXT,
    revised_by      VARCHAR(100),
    revised_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Variance Explanations (mgmt commentary) ────────────────────
CREATE TABLE IF NOT EXISTS fin_variance_notes (
    id              BIGSERIAL PRIMARY KEY,
    period_id       BIGINT REFERENCES fin_fiscal_periods(id),
    cost_center_id  BIGINT REFERENCES fin_cost_centers(id),
    account_code    VARCHAR(20),
    variance_amount NUMERIC(18,2),
    variance_pct    NUMERIC(8,2),
    explanation     TEXT NOT NULL,
    action_required TEXT,
    status          VARCHAR(20) DEFAULT 'OPEN' CHECK (status IN ('OPEN','RESOLVED')),
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── View: Budget vs Actual (per cost center, per period) ───────
CREATE OR REPLACE VIEW v_fin_budget_vs_actual_detail AS
SELECT
    fp.year,
    fp.period AS month,
    cc.name                                         AS cost_center,
    COALESCE(b.account_code, gl.account_code)       AS account_code,
    fa.name                                         AS account_name,
    COALESCE(b.amount, 0)                           AS budget,
    COALESCE(gl.actual, 0)                          AS actual,
    COALESCE(gl.actual, 0) - COALESCE(b.amount, 0) AS variance,
    CASE
        WHEN COALESCE(b.amount, 0) = 0 THEN NULL
        ELSE ROUND(
            (COALESCE(gl.actual, 0) - COALESCE(b.amount, 0))
            / ABS(b.amount) * 100, 2
        )
    END                                             AS variance_pct
FROM fin_fiscal_periods fp
CROSS JOIN fin_cost_centers cc
LEFT JOIN fin_budgets b
    ON  b.year = fp.year
    AND b.period = fp.period
    AND b.cost_center_id = cc.id
LEFT JOIN (
    SELECT
        gl.cost_center_id,
        gl.account_code,
        fp2.year,
        fp2.period,
        SUM(gl.debit - gl.credit) AS actual
    FROM   fin_gl_lines gl
    JOIN   fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status = 'POSTED'
    JOIN   fin_fiscal_periods fp2 ON fp2.id = je.period_id
    GROUP  BY gl.cost_center_id, gl.account_code, fp2.year, fp2.period
) gl ON gl.cost_center_id = cc.id
     AND gl.account_code = b.account_code
     AND gl.year = fp.year
     AND gl.period = fp.period
LEFT JOIN fin_accounts fa ON fa.code = COALESCE(b.account_code, gl.account_code)
WHERE (b.amount IS NOT NULL OR gl.actual IS NOT NULL);

-- ── View: Cost Center Summary (YTD actual vs budget) ───────────
CREATE OR REPLACE VIEW v_fin_cost_center_ytd AS
SELECT
    cc.id                           AS cost_center_id,
    cc.name                         AS cost_center,
    cc.type                         AS center_type,
    SUM(COALESCE(b.amount,0))       AS budget_ytd,
    SUM(COALESCE(gl.actual,0))      AS actual_ytd,
    SUM(COALESCE(gl.actual,0))
        - SUM(COALESCE(b.amount,0)) AS variance_ytd
FROM fin_cost_centers cc
LEFT JOIN fin_budgets b
    ON b.cost_center_id = cc.id
    AND b.year = EXTRACT(YEAR FROM CURRENT_DATE)
    AND b.period <= EXTRACT(MONTH FROM CURRENT_DATE)
LEFT JOIN (
    SELECT
        gl.cost_center_id,
        SUM(gl.debit - gl.credit) AS actual
    FROM   fin_gl_lines gl
    JOIN   fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status = 'POSTED'
    JOIN   fin_fiscal_periods fp ON fp.id = je.period_id
    WHERE  fp.year = EXTRACT(YEAR FROM CURRENT_DATE)
    AND    fp.period <= EXTRACT(MONTH FROM CURRENT_DATE)
    GROUP  BY gl.cost_center_id
) gl ON gl.cost_center_id = cc.id
GROUP BY cc.id, cc.name, cc.type
ORDER BY actual_ytd DESC;

-- ── View: Profit Center P&L ────────────────────────────────────
CREATE OR REPLACE VIEW v_fin_profit_center_pl AS
SELECT
    pc.id                                           AS profit_center_id,
    pc.name                                         AS profit_center,
    pc.service_type,
    fp.year,
    fp.period                                       AS month,
    SUM(CASE WHEN fa.account_type = 'REVENUE'
        THEN ABS(gl.credit - gl.debit) ELSE 0 END) AS revenue,
    SUM(CASE WHEN fa.account_type = 'COGS'
        THEN gl.debit - gl.credit ELSE 0 END)       AS cogs,
    SUM(CASE WHEN fa.account_type = 'EXPENSE'
        THEN gl.debit - gl.credit ELSE 0 END)       AS opex,
    SUM(CASE WHEN fa.account_type = 'REVENUE'
        THEN ABS(gl.credit - gl.debit) ELSE 0 END)
    - SUM(CASE WHEN fa.account_type IN ('COGS','EXPENSE')
        THEN gl.debit - gl.credit ELSE 0 END)       AS net_profit
FROM fin_profit_centers pc
LEFT JOIN fin_gl_lines gl ON gl.profit_center_id = pc.id
LEFT JOIN fin_journal_entries je
    ON je.id = gl.journal_entry_id AND je.status = 'POSTED'
LEFT JOIN fin_fiscal_periods fp ON fp.id = je.period_id
LEFT JOIN fin_accounts fa ON fa.code = gl.account_code
GROUP BY pc.id, pc.name, pc.service_type, fp.year, fp.period;

-- Seed default internal order sequences
SELECT setval('fin_internal_orders_id_seq', 1, false) WHERE NOT EXISTS (SELECT 1 FROM fin_internal_orders);
