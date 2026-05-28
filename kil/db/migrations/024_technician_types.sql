-- Migration 024: Technician employee types & contract management

ALTER TABLE snc_technicians
    ADD COLUMN IF NOT EXISTS employee_type    VARCHAR(30),   -- Mobile|Support|Station|Termite
    ADD COLUMN IF NOT EXISTS contract_expiry  DATE,
    ADD COLUMN IF NOT EXISTS join_date        DATE,
    ADD COLUMN IF NOT EXISTS id_card          VARCHAR(50),
    ADD COLUMN IF NOT EXISTS gender           VARCHAR(10),
    ADD COLUMN IF NOT EXISTS monday_id        VARCHAR(30);   -- item ID dari Monday.com

-- Index untuk filter cepat di generator
CREATE INDEX IF NOT EXISTS idx_snc_tech_type ON snc_technicians(employee_type);
CREATE INDEX IF NOT EXISTS idx_snc_tech_contract ON snc_technicians(contract_expiry);
