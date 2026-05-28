-- =============================================================
-- Migration 018: Finance Module — Reporting Views
-- P&L, Balance Sheet, AR Aging, AP Aging, Cash Flow
-- =============================================================

-- ── AR Aging View (Real-time) ────────────────────────────────
CREATE OR REPLACE VIEW v_fin_ar_aging AS
SELECT
    si.customer_name,
    fc.customer_group,
    fc.payment_terms,
    si.id                                       AS invoice_id,
    si.invoice_no,
    si.invoice_date,
    si.due_date,
    si.total,
    si.paid_amount,
    si.outstanding,
    CURRENT_DATE - si.due_date                  AS days_overdue,
    CASE
        WHEN CURRENT_DATE - si.due_date <= 0    THEN 'CURRENT'
        WHEN CURRENT_DATE - si.due_date <= 30   THEN '1-30'
        WHEN CURRENT_DATE - si.due_date <= 60   THEN '31-60'
        WHEN CURRENT_DATE - si.due_date <= 90   THEN '61-90'
        WHEN CURRENT_DATE - si.due_date <= 180  THEN '91-180'
        WHEN CURRENT_DATE - si.due_date <= 365  THEN '181-365'
        ELSE '>365'
    END                                         AS aging_bucket,
    CASE
        WHEN CURRENT_DATE - si.due_date <= 0    THEN 1
        WHEN CURRENT_DATE - si.due_date <= 30   THEN 2
        WHEN CURRENT_DATE - si.due_date <= 60   THEN 3
        WHEN CURRENT_DATE - si.due_date <= 90   THEN 4
        WHEN CURRENT_DATE - si.due_date <= 180  THEN 5
        WHEN CURRENT_DATE - si.due_date <= 365  THEN 6
        ELSE 7
    END                                         AS bucket_order
FROM fin_sales_invoices si
LEFT JOIN fin_customers fc ON fc.customer_name = si.customer_name
WHERE si.status NOT IN ('PAID', 'CANCELLED')
  AND si.outstanding > 0;

-- ── AR Aging Summary Per Customer ───────────────────────────
CREATE OR REPLACE VIEW v_fin_ar_aging_summary AS
SELECT
    customer_name,
    customer_group,
    SUM(outstanding)                                    AS total_outstanding,
    SUM(CASE WHEN aging_bucket = 'CURRENT' THEN outstanding ELSE 0 END) AS current_amt,
    SUM(CASE WHEN aging_bucket = '1-30'    THEN outstanding ELSE 0 END) AS days_1_30,
    SUM(CASE WHEN aging_bucket = '31-60'   THEN outstanding ELSE 0 END) AS days_31_60,
    SUM(CASE WHEN aging_bucket = '61-90'   THEN outstanding ELSE 0 END) AS days_61_90,
    SUM(CASE WHEN aging_bucket = '91-180'  THEN outstanding ELSE 0 END) AS days_91_180,
    SUM(CASE WHEN aging_bucket = '181-365' THEN outstanding ELSE 0 END) AS days_181_365,
    SUM(CASE WHEN aging_bucket = '>365'    THEN outstanding ELSE 0 END) AS days_over_365,
    MAX(days_overdue)                                   AS max_days_overdue,
    COUNT(*)                                            AS invoice_count
FROM v_fin_ar_aging
GROUP BY customer_name, customer_group;

-- ── AP Aging View ────────────────────────────────────────────
CREATE OR REPLACE VIEW v_fin_ap_aging AS
SELECT
    pi.id                                        AS invoice_id,
    pi.invoice_no,
    pi.vendor_invoice_no,
    pi.invoice_date,
    pi.due_date,
    v.name                                       AS vendor_name,
    v.vendor_category,
    pi.total_net,
    pi.paid_amount,
    pi.outstanding,
    CURRENT_DATE - pi.due_date                   AS days_overdue,
    CASE
        WHEN CURRENT_DATE - pi.due_date <= 0    THEN 'CURRENT'
        WHEN CURRENT_DATE - pi.due_date <= 30   THEN '1-30'
        WHEN CURRENT_DATE - pi.due_date <= 60   THEN '31-60'
        WHEN CURRENT_DATE - pi.due_date <= 90   THEN '61-90'
        ELSE '>90'
    END                                          AS aging_bucket
FROM fin_purchase_invoices pi
JOIN fin_vendors v ON v.id = pi.vendor_id
WHERE pi.status NOT IN ('PAID','CANCELLED')
  AND pi.outstanding > 0;

-- ── GL Balance Sheet Accounts ────────────────────────────────
CREATE OR REPLACE VIEW v_fin_gl_balances AS
SELECT
    gl.account_code,
    fa.name                                     AS account_name,
    fa.account_type,
    fa.normal_balance,
    fa.parent_code,
    fa.level,
    fp.year,
    fp.period,
    fp.start_date,
    fp.end_date,
    SUM(gl.debit)                               AS period_debit,
    SUM(gl.credit)                              AS period_credit,
    SUM(gl.debit) - SUM(gl.credit)              AS net_movement
FROM fin_gl_lines gl
JOIN fin_journal_entries je ON je.id = gl.journal_entry_id AND je.status = 'POSTED'
JOIN fin_fiscal_periods fp   ON fp.id = je.period_id
JOIN fin_accounts fa         ON fa.code = gl.account_code
GROUP BY gl.account_code, fa.name, fa.account_type, fa.normal_balance, fa.parent_code, fa.level,
         fp.year, fp.period, fp.start_date, fp.end_date;

-- ── Collection Forecast (30/60/90 day) ──────────────────────
CREATE OR REPLACE VIEW v_fin_collection_forecast AS
SELECT
    CASE
        WHEN due_date <= CURRENT_DATE + 30  THEN '0-30 days'
        WHEN due_date <= CURRENT_DATE + 60  THEN '31-60 days'
        WHEN due_date <= CURRENT_DATE + 90  THEN '61-90 days'
        ELSE '90+ days'
    END                                         AS horizon,
    customer_name,
    COUNT(*)                                    AS invoice_count,
    SUM(outstanding)                            AS expected_amount
FROM fin_sales_invoices
WHERE status NOT IN ('PAID','CANCELLED')
  AND outstanding > 0
  AND due_date >= CURRENT_DATE
GROUP BY 1, 2
ORDER BY 1, 4 DESC;

-- ── Payment Obligation Forecast ──────────────────────────────
CREATE OR REPLACE VIEW v_fin_payment_forecast AS
SELECT
    CASE
        WHEN due_date <= CURRENT_DATE + 7   THEN '0-7 days'
        WHEN due_date <= CURRENT_DATE + 14  THEN '8-14 days'
        WHEN due_date <= CURRENT_DATE + 30  THEN '15-30 days'
        ELSE '30+ days'
    END                                         AS horizon,
    v.name                                      AS vendor_name,
    COUNT(*)                                    AS invoice_count,
    SUM(pi.outstanding)                         AS expected_payment
FROM fin_purchase_invoices pi
JOIN fin_vendors v ON v.id = pi.vendor_id
WHERE pi.status NOT IN ('PAID','CANCELLED')
  AND pi.outstanding > 0
  AND pi.due_date >= CURRENT_DATE
GROUP BY 1, 2
ORDER BY 1, 4 DESC;

-- ── Customer Profitability ───────────────────────────────────
CREATE OR REPLACE VIEW v_fin_customer_profitability AS
SELECT
    si.customer_name,
    fc.customer_group,
    fp.year,
    fp.period,
    COUNT(si.id)                                AS invoice_count,
    SUM(si.subtotal)                            AS revenue,
    SUM(si.paid_amount)                         AS collected,
    SUM(si.outstanding)                         AS uncollected,
    CASE WHEN SUM(si.subtotal) > 0
         THEN ROUND(SUM(si.paid_amount) * 100.0 / SUM(si.subtotal), 1)
         ELSE 0 END                             AS collection_rate_pct
FROM fin_sales_invoices si
JOIN fin_fiscal_periods fp   ON fp.id = si.period_id
LEFT JOIN fin_customers fc   ON fc.customer_name = si.customer_name
WHERE si.status != 'CANCELLED'
GROUP BY si.customer_name, fc.customer_group, fp.year, fp.period;

-- ── Budget vs Actual ─────────────────────────────────────────
CREATE OR REPLACE VIEW v_fin_budget_vs_actual AS
SELECT
    b.year,
    b.period,
    b.account_code,
    fa.name                                     AS account_name,
    fa.account_type,
    cc.name                                     AS cost_center,
    b.amount                                    AS budget,
    COALESCE(SUM(gl.debit - gl.credit), 0)      AS actual,
    b.amount - COALESCE(SUM(gl.debit - gl.credit), 0) AS variance,
    CASE WHEN b.amount != 0
         THEN ROUND((b.amount - COALESCE(SUM(gl.debit - gl.credit), 0)) * 100.0 / ABS(b.amount), 1)
         ELSE NULL END                          AS variance_pct
FROM fin_budgets b
JOIN fin_accounts fa     ON fa.code = b.account_code
LEFT JOIN fin_cost_centers cc ON cc.id = b.cost_center_id
LEFT JOIN fin_gl_lines gl ON gl.account_code = b.account_code
    AND gl.cost_center_id IS NOT DISTINCT FROM b.cost_center_id
LEFT JOIN fin_journal_entries je ON je.id = gl.journal_entry_id
    AND je.status = 'POSTED'
LEFT JOIN fin_fiscal_periods fp ON fp.id = je.period_id
    AND fp.year = b.year AND fp.period = b.period
GROUP BY b.year, b.period, b.account_code, fa.name, fa.account_type, cc.name, b.amount;

-- ── Month-End Close Checklist View ───────────────────────────
CREATE OR REPLACE VIEW v_fin_close_checklist AS
WITH current_period AS (
    SELECT id, year, period FROM fin_fiscal_periods WHERE status = 'OPEN' ORDER BY year, period LIMIT 1
),
recon_status AS (
    SELECT COUNT(*) AS reconciled_count FROM fin_bank_reconciliations br
    JOIN current_period cp ON br.period_id = cp.id WHERE br.status = 'COMPLETE'
),
unposted_je AS (
    SELECT COUNT(*) AS cnt FROM fin_journal_entries je
    JOIN current_period cp ON je.period_id = cp.id WHERE je.status IN ('DRAFT','PENDING_APPROVAL')
),
unapplied_pmts AS (
    SELECT COUNT(*) AS cnt FROM fin_ar_payments p
    WHERE NOT EXISTS (SELECT 1 FROM fin_ar_allocations a WHERE a.payment_id = p.id)
    AND p.payment_date >= (SELECT start_date FROM fin_fiscal_periods fp JOIN current_period cp ON fp.id = cp.id)
),
dep_run AS (
    SELECT COUNT(*) AS cnt FROM fin_depreciation_runs dr
    JOIN current_period cp ON dr.period_id = cp.id WHERE dr.status = 'POSTED'
)
SELECT
    cp.year, cp.period,
    r.reconciled_count >= (SELECT COUNT(*) FROM fin_bank_accounts WHERE is_active) AS bank_recon_done,
    uj.cnt = 0                                  AS no_unposted_journals,
    up.cnt = 0                                  AS all_payments_applied,
    d.cnt > 0                                   AS depreciation_posted
FROM current_period cp, recon_status r, unposted_je uj, unapplied_pmts up, dep_run d;
