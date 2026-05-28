-- ============================================================
-- Migration 021: Finance Tax Compliance Module
-- PPN Faktur Pajak, PPh23 Bukti Potong, SPT Masa
-- ============================================================

-- ── PPN — Faktur Pajak (VAT Invoices) ─────────────────────────
CREATE TABLE IF NOT EXISTS fin_ppn_faktur (
    id                  BIGSERIAL PRIMARY KEY,
    faktur_no           VARCHAR(30) UNIQUE NOT NULL,  -- 000.000-YY.XXXXXXXX
    faktur_type         VARCHAR(10) DEFAULT 'KELUARAN'
                            CHECK (faktur_type IN ('KELUARAN','MASUKAN')),
    faktur_date         DATE NOT NULL,
    period_year         INT NOT NULL,
    period_month        INT NOT NULL,
    -- Seller / Buyer
    seller_npwp         VARCHAR(20),
    seller_name         TEXT,
    buyer_npwp          VARCHAR(20),
    buyer_name          TEXT,
    buyer_address       TEXT,
    -- Amounts
    dpp                 NUMERIC(18,2) NOT NULL,   -- Dasar Pengenaan Pajak
    ppn_rate            NUMERIC(5,2) DEFAULT 11.00,
    ppn_amount          NUMERIC(18,2) NOT NULL,
    -- Links
    sales_invoice_id    BIGINT REFERENCES fin_sales_invoices(id),
    purchase_invoice_id BIGINT REFERENCES fin_purchase_invoices(id),
    -- Status
    status              VARCHAR(20) DEFAULT 'DRAFT'
                            CHECK (status IN ('DRAFT','REPORTED','AMENDED','CANCELLED')),
    efaktur_ref         VARCHAR(50),  -- DJP reference number after upload
    uploaded_at         TIMESTAMPTZ,
    notes               TEXT,
    created_by          VARCHAR(100),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ppn_faktur_period ON fin_ppn_faktur(period_year, period_month);
CREATE INDEX IF NOT EXISTS idx_ppn_faktur_type   ON fin_ppn_faktur(faktur_type);

-- ── PPh 23 — Withholding Tax Certificates ─────────────────────
-- fin_pph23_certificates already exists from migration 016
-- Extend it with additional fields needed for bukti potong
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_pph23_certificates' AND column_name='bukti_potong_no') THEN
        ALTER TABLE fin_pph23_certificates ADD COLUMN bukti_potong_no VARCHAR(30);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_pph23_certificates' AND column_name='income_type') THEN
        ALTER TABLE fin_pph23_certificates ADD COLUMN income_type VARCHAR(100) DEFAULT 'Jasa';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_pph23_certificates' AND column_name='gross_amount') THEN
        ALTER TABLE fin_pph23_certificates ADD COLUMN gross_amount NUMERIC(18,2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_pph23_certificates' AND column_name='pph23_rate') THEN
        ALTER TABLE fin_pph23_certificates ADD COLUMN pph23_rate NUMERIC(5,2) DEFAULT 2.00;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_pph23_certificates' AND column_name='payment_date') THEN
        ALTER TABLE fin_pph23_certificates ADD COLUMN payment_date DATE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_pph23_certificates' AND column_name='ap_payment_id') THEN
        ALTER TABLE fin_pph23_certificates ADD COLUMN ap_payment_id BIGINT REFERENCES fin_ap_payments(id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_pph23_certificates' AND column_name='status') THEN
        ALTER TABLE fin_pph23_certificates ADD COLUMN status VARCHAR(20) DEFAULT 'ISSUED'
            CHECK (status IN ('ISSUED','SENT','ACKNOWLEDGED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='fin_pph23_certificates' AND column_name='created_by') THEN
        ALTER TABLE fin_pph23_certificates ADD COLUMN created_by VARCHAR(100);
        ALTER TABLE fin_pph23_certificates ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();
    END IF;
END$$;

-- ── SPT Masa (Monthly Tax Return Summary) ─────────────────────
CREATE TABLE IF NOT EXISTS fin_spt_masa (
    id              BIGSERIAL PRIMARY KEY,
    spt_type        VARCHAR(20) NOT NULL CHECK (spt_type IN ('PPN','PPH23','PPH21','PPH4A2')),
    period_year     INT NOT NULL,
    period_month    INT NOT NULL,
    -- Amounts
    total_dpp       NUMERIC(18,2) DEFAULT 0,
    total_tax       NUMERIC(18,2) DEFAULT 0,
    tax_paid        NUMERIC(18,2) DEFAULT 0,
    kurang_bayar    NUMERIC(18,2) DEFAULT 0,  -- underpaid
    lebih_bayar     NUMERIC(18,2) DEFAULT 0,  -- overpaid
    -- Filing
    status          VARCHAR(20) DEFAULT 'DRAFT'
                        CHECK (status IN ('DRAFT','FILED','AMENDED')),
    filing_date     DATE,
    payment_date    DATE,
    ntpn            VARCHAR(30),  -- tax payment reference
    notes           TEXT,
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (spt_type, period_year, period_month)
);

-- ── PPh Final 0.5% (UMKM threshold) ───────────────────────────
CREATE TABLE IF NOT EXISTS fin_pph_final (
    id              BIGSERIAL PRIMARY KEY,
    period_year     INT NOT NULL,
    period_month    INT NOT NULL,
    gross_revenue   NUMERIC(18,2) NOT NULL,
    pph_rate        NUMERIC(5,3) DEFAULT 0.500,
    pph_amount      NUMERIC(18,2) NOT NULL,
    payment_date    DATE,
    ntpn            VARCHAR(30),
    status          VARCHAR(20) DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','PAID')),
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (period_year, period_month)
);

-- ── Tax Calendar (deadline tracking) ──────────────────────────
CREATE TABLE IF NOT EXISTS fin_tax_calendar (
    id              BIGSERIAL PRIMARY KEY,
    period_year     INT NOT NULL,
    period_month    INT NOT NULL,
    tax_type        VARCHAR(20) NOT NULL,
    obligation      VARCHAR(100) NOT NULL,  -- e.g. "Setor PPN", "Lapor SPT Masa PPN"
    deadline        DATE NOT NULL,
    is_payment      BOOLEAN DEFAULT FALSE,
    is_reporting    BOOLEAN DEFAULT TRUE,
    status          VARCHAR(20) DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','DONE','OVERDUE')),
    completed_at    TIMESTAMPTZ,
    completed_by    VARCHAR(100),
    notes           TEXT
);

-- Seed tax calendar for 2026
INSERT INTO fin_tax_calendar (period_year, period_month, tax_type, obligation, deadline, is_payment, is_reporting)
SELECT
    2026,
    m,
    type,
    obligation,
    deadline,
    is_pmt,
    is_rpt
FROM (VALUES
    (1,'PPN','Setor PPN Masa Jan 2026',       DATE '2026-02-28', TRUE, FALSE),
    (1,'PPN','Lapor SPT Masa PPN Jan 2026',   DATE '2026-03-31', FALSE, TRUE),
    (1,'PPH23','Setor PPh23 Jan 2026',         DATE '2026-02-10', TRUE, FALSE),
    (1,'PPH23','Lapor SPT PPh23 Jan 2026',     DATE '2026-03-20', FALSE, TRUE),
    (2,'PPN','Setor PPN Masa Feb 2026',        DATE '2026-03-31', TRUE, FALSE),
    (2,'PPN','Lapor SPT Masa PPN Feb 2026',    DATE '2026-04-30', FALSE, TRUE),
    (2,'PPH23','Setor PPh23 Feb 2026',         DATE '2026-03-10', TRUE, FALSE),
    (2,'PPH23','Lapor SPT PPh23 Feb 2026',     DATE '2026-04-20', FALSE, TRUE),
    (3,'PPN','Setor PPN Masa Mar 2026',        DATE '2026-04-30', TRUE, FALSE),
    (3,'PPN','Lapor SPT Masa PPN Mar 2026',    DATE '2026-05-31', FALSE, TRUE),
    (3,'PPH23','Setor PPh23 Mar 2026',         DATE '2026-04-10', TRUE, FALSE),
    (3,'PPH23','Lapor SPT PPh23 Mar 2026',     DATE '2026-05-20', FALSE, TRUE),
    (4,'PPN','Setor PPN Masa Apr 2026',        DATE '2026-05-31', TRUE, FALSE),
    (4,'PPN','Lapor SPT Masa PPN Apr 2026',    DATE '2026-06-30', FALSE, TRUE),
    (4,'PPH23','Setor PPh23 Apr 2026',         DATE '2026-05-10', TRUE, FALSE),
    (4,'PPH23','Lapor SPT PPh23 Apr 2026',     DATE '2026-06-20', FALSE, TRUE),
    (5,'PPN','Setor PPN Masa Mei 2026',        DATE '2026-06-30', TRUE, FALSE),
    (5,'PPN','Lapor SPT Masa PPN Mei 2026',    DATE '2026-07-31', FALSE, TRUE),
    (5,'PPH23','Setor PPh23 Mei 2026',         DATE '2026-06-10', TRUE, FALSE),
    (5,'PPH23','Lapor SPT PPh23 Mei 2026',     DATE '2026-07-20', FALSE, TRUE),
    (6,'PPN','Setor PPN Masa Jun 2026',        DATE '2026-07-31', TRUE, FALSE),
    (6,'PPN','Lapor SPT Masa PPN Jun 2026',    DATE '2026-08-31', FALSE, TRUE),
    (6,'PPH23','Setor PPh23 Jun 2026',         DATE '2026-07-10', TRUE, FALSE),
    (6,'PPH23','Lapor SPT PPh23 Jun 2026',     DATE '2026-08-20', FALSE, TRUE)
) AS t(m, type, obligation, deadline, is_pmt, is_rpt)
ON CONFLICT DO NOTHING;

-- ── Views ──────────────────────────────────────────────────────

-- PPN monthly summary
CREATE OR REPLACE VIEW v_fin_ppn_summary AS
SELECT
    period_year,
    period_month,
    SUM(CASE WHEN faktur_type='KELUARAN' THEN ppn_amount ELSE 0 END) AS ppn_keluaran,
    SUM(CASE WHEN faktur_type='MASUKAN'  THEN ppn_amount ELSE 0 END) AS ppn_masukan,
    SUM(CASE WHEN faktur_type='KELUARAN' THEN ppn_amount ELSE 0 END)
        - SUM(CASE WHEN faktur_type='MASUKAN' THEN ppn_amount ELSE 0 END) AS ppn_kurang_bayar,
    COUNT(*) AS total_faktur,
    SUM(dpp) AS total_dpp
FROM fin_ppn_faktur
WHERE status != 'CANCELLED'
GROUP BY period_year, period_month
ORDER BY period_year, period_month;

-- PPh23 monthly summary
CREATE OR REPLACE VIEW v_fin_pph23_monthly AS
SELECT
    c.period_year,
    c.period_month,
    COUNT(*) AS total_certificates,
    SUM(c.gross_amount) AS total_gross,
    SUM(c.pph23_amount) AS total_pph23,
    SUM(CASE WHEN c.status='SENT' THEN 1 ELSE 0 END) AS sent_count,
    SUM(CASE WHEN c.status='ACKNOWLEDGED' THEN 1 ELSE 0 END) AS acknowledged_count
FROM fin_pph23_certificates c
GROUP BY c.period_year, c.period_month
ORDER BY c.period_year, c.period_month;

-- Tax calendar overdue check
CREATE OR REPLACE VIEW v_fin_tax_overdue AS
SELECT *
FROM fin_tax_calendar
WHERE status = 'PENDING'
  AND deadline < CURRENT_DATE
ORDER BY deadline;
