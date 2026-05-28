-- =============================================================
-- Migration 014: Finance Module — Master Data
-- Chart of Accounts, Customers (finance ext), Vendors, Cost Centers,
-- Profit Centers, Fixed Assets, Fiscal Periods, Bank Accounts
-- =============================================================

-- ── Chart of Accounts ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_accounts (
    code            VARCHAR(20)  PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    account_type    VARCHAR(30)  NOT NULL,  -- ASSET|LIABILITY|EQUITY|REVENUE|COGS|EXPENSE|NON_OP
    normal_balance  VARCHAR(6)   NOT NULL DEFAULT 'DEBIT',  -- DEBIT|CREDIT
    parent_code     VARCHAR(20)  REFERENCES fin_accounts(code),
    level           SMALLINT     NOT NULL DEFAULT 1,
    is_detail       BOOLEAN      NOT NULL DEFAULT TRUE,  -- only detail accounts get transactions
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    description     TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_accounts_type ON fin_accounts(account_type);
CREATE INDEX IF NOT EXISTS idx_fin_accounts_parent ON fin_accounts(parent_code);

-- ── Customer Finance Extension ───────────────────────────────
-- Extends existing m_customer (Kelava) with finance attributes
CREATE TABLE IF NOT EXISTS fin_customers (
    customer_name   VARCHAR(300) PRIMARY KEY,
    npwp            VARCHAR(30),
    address         TEXT,
    city            VARCHAR(100),
    credit_limit    NUMERIC(18,2) NOT NULL DEFAULT 0,
    payment_terms   SMALLINT     NOT NULL DEFAULT 30,  -- days
    ar_account      VARCHAR(20)  REFERENCES fin_accounts(code),
    sales_territory VARCHAR(100),
    customer_group  VARCHAR(100),  -- e.g. Pakuwon Group, Hotel, Hospital
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Vendors ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_vendors (
    id              BIGSERIAL    PRIMARY KEY,
    name            VARCHAR(300) NOT NULL UNIQUE,
    npwp            VARCHAR(30),
    address         TEXT,
    city            VARCHAR(100),
    bank_name       VARCHAR(100),
    bank_account    VARCHAR(50),
    bank_account_name VARCHAR(200),
    payment_terms   SMALLINT     NOT NULL DEFAULT 30,
    ap_account      VARCHAR(20)  REFERENCES fin_accounts(code),
    vendor_category VARCHAR(100),  -- Chemical Supplier|Service|Logistics|etc.
    pph23_subject   BOOLEAN      NOT NULL DEFAULT FALSE,
    pph23_rate      NUMERIC(5,2) NOT NULL DEFAULT 2.00,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_vendors_name ON fin_vendors(name);

-- ── Cost Centers ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_cost_centers (
    id              BIGSERIAL    PRIMARY KEY,
    code            VARCHAR(20)  NOT NULL UNIQUE,
    name            VARCHAR(200) NOT NULL,
    center_type     VARCHAR(30)  NOT NULL DEFAULT 'OPERATIONAL',  -- OPERATIONAL|ADMIN|SALES|MANAGEMENT
    responsible_user VARCHAR(100),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Profit Centers ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_profit_centers (
    id              BIGSERIAL    PRIMARY KEY,
    code            VARCHAR(20)  NOT NULL UNIQUE,
    name            VARCHAR(200) NOT NULL,
    service_type    VARCHAR(50),  -- PRC|TC|FUMIGASI|PRODUCT|DISINFECTANT
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Fixed Assets ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_assets (
    id              BIGSERIAL    PRIMARY KEY,
    asset_no        VARCHAR(50)  NOT NULL UNIQUE,
    description     VARCHAR(300) NOT NULL,
    category        VARCHAR(50)  NOT NULL,  -- VEHICLE|EQUIPMENT|FURNITURE|IT|BUILDING
    purchase_date   DATE         NOT NULL,
    purchase_cost   NUMERIC(18,2) NOT NULL,
    useful_life_months SMALLINT  NOT NULL DEFAULT 60,
    depreciation_method VARCHAR(20) NOT NULL DEFAULT 'STRAIGHT_LINE',
    salvage_value   NUMERIC(18,2) NOT NULL DEFAULT 0,
    accumulated_depreciation NUMERIC(18,2) NOT NULL DEFAULT 0,
    book_value      NUMERIC(18,2) NOT NULL,
    location        VARCHAR(200),
    cost_center_id  BIGINT       REFERENCES fin_cost_centers(id),
    asset_account   VARCHAR(20)  REFERENCES fin_accounts(code),
    accum_dep_account VARCHAR(20) REFERENCES fin_accounts(code),
    dep_exp_account VARCHAR(20)  REFERENCES fin_accounts(code),
    serial_no       VARCHAR(100),
    qr_code         VARCHAR(100),
    status          VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE|DISPOSED|FULLY_DEPRECIATED
    disposal_date   DATE,
    disposal_proceeds NUMERIC(18,2),
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fin_assets_category ON fin_assets(category);
CREATE INDEX IF NOT EXISTS idx_fin_assets_status ON fin_assets(status);

-- ── Bank Accounts ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_bank_accounts (
    id              BIGSERIAL    PRIMARY KEY,
    code            VARCHAR(20)  NOT NULL UNIQUE,
    name            VARCHAR(200) NOT NULL,
    bank_name       VARCHAR(100) NOT NULL,
    account_no      VARCHAR(50)  NOT NULL,
    currency        VARCHAR(3)   NOT NULL DEFAULT 'IDR',
    gl_account      VARCHAR(20)  REFERENCES fin_accounts(code),
    current_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    last_reconciled DATE,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Fiscal Periods ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_fiscal_periods (
    id              BIGSERIAL    PRIMARY KEY,
    year            SMALLINT     NOT NULL,
    period          SMALLINT     NOT NULL,  -- 1-12
    start_date      DATE         NOT NULL,
    end_date        DATE         NOT NULL,
    status          VARCHAR(10)  NOT NULL DEFAULT 'OPEN',  -- OPEN|CLOSED|LOCKED
    closed_by       VARCHAR(100),
    closed_at       TIMESTAMPTZ,
    UNIQUE (year, period)
);
CREATE INDEX IF NOT EXISTS idx_fin_periods_status ON fin_fiscal_periods(status);

-- ── Budgets ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_budgets (
    id              BIGSERIAL    PRIMARY KEY,
    year            SMALLINT     NOT NULL,
    period          SMALLINT     NOT NULL,
    account_code    VARCHAR(20)  NOT NULL REFERENCES fin_accounts(code),
    cost_center_id  BIGINT       REFERENCES fin_cost_centers(id),
    profit_center_id BIGINT      REFERENCES fin_profit_centers(id),
    amount          NUMERIC(18,2) NOT NULL DEFAULT 0,
    created_by      VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (year, period, account_code, cost_center_id)
);
CREATE INDEX IF NOT EXISTS idx_fin_budgets_year ON fin_budgets(year, period);

-- Seed: Chart of Accounts (Indonesian standard COA for services company)
INSERT INTO fin_accounts (code, name, account_type, normal_balance, level, is_detail) VALUES
-- ASET
('1000', 'ASET', 'ASSET', 'DEBIT', 1, FALSE),
  ('1100', 'Aset Lancar', 'ASSET', 'DEBIT', 2, FALSE),
    ('1101', 'Kas & Bank', 'ASSET', 'DEBIT', 3, FALSE),
      ('1101-01', 'Kas Kecil', 'ASSET', 'DEBIT', 4, TRUE),
      ('1101-02', 'BCA WISNU', 'ASSET', 'DEBIT', 4, TRUE),
      ('1101-03', 'BCA ALINDRA', 'ASSET', 'DEBIT', 4, TRUE),
      ('1101-04', 'OCBC', 'ASSET', 'DEBIT', 4, TRUE),
      ('1101-05', 'Paper.id', 'ASSET', 'DEBIT', 4, TRUE),
    ('1102', 'Piutang Usaha', 'ASSET', 'DEBIT', 3, TRUE),
    ('1103', 'Penyisihan Piutang Tak Tertagih', 'ASSET', 'CREDIT', 3, TRUE),
    ('1104', 'Uang Muka Pelanggan', 'ASSET', 'DEBIT', 3, TRUE),
    ('1105', 'Persediaan Bahan', 'ASSET', 'DEBIT', 3, TRUE),
    ('1106', 'Uang Muka Karyawan', 'ASSET', 'DEBIT', 3, TRUE),
    ('1107', 'Biaya Dibayar Dimuka', 'ASSET', 'DEBIT', 3, TRUE),
    ('1108', 'Pajak Dibayar Dimuka', 'ASSET', 'DEBIT', 3, FALSE),
      ('1108-01', 'PPn Masukan', 'ASSET', 'DEBIT', 4, TRUE),
      ('1108-02', 'PPh 23 Dibayar Dimuka', 'ASSET', 'DEBIT', 4, TRUE),
  ('1200', 'Aset Tidak Lancar', 'ASSET', 'DEBIT', 2, FALSE),
    ('1201', 'Kendaraan', 'ASSET', 'DEBIT', 3, TRUE),
    ('1201-A', 'Akumulasi Penyusutan Kendaraan', 'ASSET', 'CREDIT', 3, TRUE),
    ('1202', 'Peralatan', 'ASSET', 'DEBIT', 3, TRUE),
    ('1202-A', 'Akumulasi Penyusutan Peralatan', 'ASSET', 'CREDIT', 3, TRUE),
    ('1203', 'Inventaris Kantor', 'ASSET', 'DEBIT', 3, TRUE),
    ('1203-A', 'Akumulasi Penyusutan Inventaris', 'ASSET', 'CREDIT', 3, TRUE),
-- LIABILITAS
('2000', 'LIABILITAS', 'LIABILITY', 'CREDIT', 1, FALSE),
  ('2100', 'Liabilitas Jangka Pendek', 'LIABILITY', 'CREDIT', 2, FALSE),
    ('2101', 'Hutang Usaha', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2102', 'Hutang Gaji', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2103', 'Hutang THR', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2104', 'Hutang BPJS', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2105', 'Uang Muka Pelanggan (Kewajiban)', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2106', 'Hutang PPn Keluaran', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2107', 'Hutang PPh 23', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2108', 'Hutang PPh Final', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2109', 'Hutang Fee Marketing', 'LIABILITY', 'CREDIT', 3, TRUE),
    ('2110', 'Biaya YMH Dibayar', 'LIABILITY', 'CREDIT', 3, TRUE),
  ('2200', 'Liabilitas Jangka Panjang', 'LIABILITY', 'CREDIT', 2, FALSE),
    ('2201', 'Hutang Bank', 'LIABILITY', 'CREDIT', 3, TRUE),
-- EKUITAS
('3000', 'EKUITAS', 'EQUITY', 'CREDIT', 1, FALSE),
    ('3001', 'Modal Disetor', 'EQUITY', 'CREDIT', 2, TRUE),
    ('3002', 'Laba Ditahan', 'EQUITY', 'CREDIT', 2, TRUE),
    ('3003', 'Laba Tahun Berjalan', 'EQUITY', 'CREDIT', 2, TRUE),
    ('3004', 'Prive / Dividen', 'EQUITY', 'DEBIT', 2, TRUE),
-- PENDAPATAN
('4000', 'PENDAPATAN', 'REVENUE', 'CREDIT', 1, FALSE),
    ('4001', 'Penjualan Jasa PRC', 'REVENUE', 'CREDIT', 2, TRUE),
    ('4002', 'Penjualan Jasa TC', 'REVENUE', 'CREDIT', 2, TRUE),
    ('4003', 'Penjualan Jasa Disinfectant', 'REVENUE', 'CREDIT', 2, TRUE),
    ('4004', 'Penjualan Jasa Fumigasi', 'REVENUE', 'CREDIT', 2, TRUE),
    ('4005', 'Penjualan Produk', 'REVENUE', 'CREDIT', 2, TRUE),
    ('4006', 'Pendapatan Lainnya', 'REVENUE', 'CREDIT', 2, TRUE),
    ('4007', 'Retur Penjualan', 'REVENUE', 'DEBIT', 2, TRUE),
-- HPP
('5000', 'BEBAN POKOK PENJUALAN', 'COGS', 'DEBIT', 1, FALSE),
    ('5001', 'Pembelian Bahan Kimia', 'COGS', 'DEBIT', 2, TRUE),
    ('5002', 'Pemakaian Bahan Kimia', 'COGS', 'DEBIT', 2, TRUE),
    ('5003', 'HPP Produk', 'COGS', 'DEBIT', 2, TRUE),
-- BEBAN OPERASIONAL
('6000', 'BEBAN OPERASIONAL', 'EXPENSE', 'DEBIT', 1, FALSE),
  ('6100', 'Beban Personalia', 'EXPENSE', 'DEBIT', 2, FALSE),
    ('6101', 'Beban Gaji & Upah', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6102', 'Beban BPJS & Asuransi', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6103', 'Beban THR & KPI', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6104', 'Beban Transportasi Karyawan', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6105', 'Beban Katering & Makan', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6106', 'Beban Tunjangan Kesehatan', 'EXPENSE', 'DEBIT', 3, TRUE),
  ('6200', 'Beban Operasional Langsung', 'EXPENSE', 'DEBIT', 2, FALSE),
    ('6201', 'Beban Bensin & Kendaraan', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6202', 'Beban Perlengkapan Usaha', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6203', 'Beban Service & Pemeliharaan', 'EXPENSE', 'DEBIT', 3, TRUE),
  ('6300', 'Beban Penjualan', 'EXPENSE', 'DEBIT', 2, FALSE),
    ('6301', 'Beban Fee Marketing', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6302', 'Beban Entertainment & Iklan', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6303', 'Beban Pengembangan Usaha', 'EXPENSE', 'DEBIT', 3, TRUE),
  ('6400', 'Beban Umum & Administrasi', 'EXPENSE', 'DEBIT', 2, FALSE),
    ('6401', 'Beban Sewa Gedung', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6402', 'Beban Internet & Komunikasi', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6403', 'Beban Operasional Lainnya', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6404', 'Beban Penyisihan Piutang', 'EXPENSE', 'DEBIT', 3, TRUE),
  ('6500', 'Beban Penyusutan', 'EXPENSE', 'DEBIT', 2, FALSE),
    ('6501', 'Beban Penyusutan Kendaraan', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6502', 'Beban Penyusutan Peralatan', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6503', 'Beban Penyusutan Inventaris', 'EXPENSE', 'DEBIT', 3, TRUE),
  ('6600', 'Beban Pajak', 'EXPENSE', 'DEBIT', 2, FALSE),
    ('6601', 'Beban PPh Final', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6602', 'Beban PPh 23', 'EXPENSE', 'DEBIT', 3, TRUE),
    ('6603', 'Beban Retribusi & Sumbangan', 'EXPENSE', 'DEBIT', 3, TRUE),
-- NON-OPERASIONAL
('7000', 'PENDAPATAN & BEBAN NON-OPERASIONAL', 'NON_OP', 'CREDIT', 1, FALSE),
    ('7001', 'Pendapatan Bunga', 'NON_OP', 'CREDIT', 2, TRUE),
    ('7002', 'Pendapatan Diluar Usaha', 'NON_OP', 'CREDIT', 2, TRUE),
    ('7003', 'Beban Bunga Pinjaman', 'NON_OP', 'DEBIT', 2, TRUE),
    ('7004', 'Beban Administrasi Bank', 'NON_OP', 'DEBIT', 2, TRUE),
    ('7005', 'Beban Diluar Usaha Lainnya', 'NON_OP', 'DEBIT', 2, TRUE),
    ('7006', 'Laba/Rugi Disposisi Aset', 'NON_OP', 'CREDIT', 2, TRUE)
ON CONFLICT (code) DO NOTHING;

-- Update parent_codes
UPDATE fin_accounts SET parent_code = '1100' WHERE code IN ('1101','1102','1103','1104','1105','1106','1107','1108');
UPDATE fin_accounts SET parent_code = '1101' WHERE code IN ('1101-01','1101-02','1101-03','1101-04','1101-05');
UPDATE fin_accounts SET parent_code = '1108' WHERE code IN ('1108-01','1108-02');
UPDATE fin_accounts SET parent_code = '1200' WHERE code IN ('1201','1201-A','1202','1202-A','1203','1203-A');
UPDATE fin_accounts SET parent_code = '1000' WHERE code IN ('1100','1200');
UPDATE fin_accounts SET parent_code = '2000' WHERE code IN ('2100','2200');
UPDATE fin_accounts SET parent_code = '2100' WHERE code IN ('2101','2102','2103','2104','2105','2106','2107','2108','2109','2110');
UPDATE fin_accounts SET parent_code = '2200' WHERE code IN ('2201');
UPDATE fin_accounts SET parent_code = '3000' WHERE code IN ('3001','3002','3003','3004');
UPDATE fin_accounts SET parent_code = '4000' WHERE code IN ('4001','4002','4003','4004','4005','4006','4007');
UPDATE fin_accounts SET parent_code = '5000' WHERE code IN ('5001','5002','5003');
UPDATE fin_accounts SET parent_code = '6000' WHERE code IN ('6100','6200','6300','6400','6500','6600');
UPDATE fin_accounts SET parent_code = '6100' WHERE code IN ('6101','6102','6103','6104','6105','6106');
UPDATE fin_accounts SET parent_code = '6200' WHERE code IN ('6201','6202','6203');
UPDATE fin_accounts SET parent_code = '6300' WHERE code IN ('6301','6302','6303');
UPDATE fin_accounts SET parent_code = '6400' WHERE code IN ('6401','6402','6403','6404');
UPDATE fin_accounts SET parent_code = '6500' WHERE code IN ('6501','6502','6503');
UPDATE fin_accounts SET parent_code = '6600' WHERE code IN ('6601','6602','6603');
UPDATE fin_accounts SET parent_code = '7000' WHERE code IN ('7001','7002','7003','7004','7005','7006');

-- Seed: Cost Centers
INSERT INTO fin_cost_centers (code, name, center_type) VALUES
('CC-OPS',  'Operasional Lapangan', 'OPERATIONAL'),
('CC-ADM',  'Administrasi & Umum',  'ADMIN'),
('CC-SALES','Marketing & Penjualan', 'SALES'),
('CC-MGT',  'Manajemen',            'MANAGEMENT')
ON CONFLICT (code) DO NOTHING;

-- Seed: Profit Centers
INSERT INTO fin_profit_centers (code, name, service_type) VALUES
('PC-PRC',  'Pest & Rodent Control', 'PRC'),
('PC-TC',   'Termite Control',       'TC'),
('PC-DIS',  'Disinfectant',          'DISINFECTANT'),
('PC-FUM',  'Fumigasi',              'FUMIGASI'),
('PC-PROD', 'Penjualan Produk',      'PRODUCT')
ON CONFLICT (code) DO NOTHING;

-- Seed: Bank Accounts
INSERT INTO fin_bank_accounts (code, name, bank_name, account_no, gl_account) VALUES
('BCA-WSN',  'BCA WISNU',    'BCA', '1230123xxxxx', '1101-02'),
('BCA-ALN',  'BCA ALINDRA',  'BCA', '7640234xxxxx', '1101-03'),
('OCBC-ALN', 'OCBC',         'OCBC','xxxxxxxxxxxx', '1101-04'),
('PAPERID',  'Paper.id',     'Paper.id', '-',        '1101-05')
ON CONFLICT (code) DO NOTHING;

-- Seed: Fiscal Periods 2024-2026
INSERT INTO fin_fiscal_periods (year, period, start_date, end_date, status)
SELECT y, m,
       make_date(y, m, 1),
       (make_date(y, m, 1) + INTERVAL '1 month - 1 day')::DATE,
       CASE WHEN y < 2026 THEN 'CLOSED'
            WHEN y = 2026 AND m < 5 THEN 'CLOSED'
            WHEN y = 2026 AND m = 5 THEN 'OPEN'
            ELSE 'OPEN' END
FROM   generate_series(2024,2026) y, generate_series(1,12) m
ON CONFLICT (year, period) DO NOTHING;
