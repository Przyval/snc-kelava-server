-- Migration 033: Customer suppression dates
-- ──────────────────────────────────────────────────────────────────────────
-- Tabel terpisah untuk per-customer "tutup sementara" (renovasi, libur,
-- event). Berbeda dengan snc_suppression_dates (global holiday scope='all').
--
-- UI: /enterprise/lokasi-libur — "Lokasi Libur Sementara"

CREATE TABLE IF NOT EXISTS snc_client_suppression_dates (
    id           BIGSERIAL PRIMARY KEY,
    client_id    BIGINT NOT NULL REFERENCES snc_clients(id) ON DELETE CASCADE,
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL,
    reason       TEXT,                          -- 'lebaran', 'renovasi', 'event', 'other'
    notes        TEXT,
    created_by   INT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by   INT,
    CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_client_supp_client_date
    ON snc_client_suppression_dates (client_id, start_date, end_date);

CREATE INDEX IF NOT EXISTS idx_client_supp_range
    ON snc_client_suppression_dates (start_date, end_date);

CREATE TABLE IF NOT EXISTS snc_client_suppression_log (
    id              BIGSERIAL PRIMARY KEY,
    suppression_id  BIGINT REFERENCES snc_client_suppression_dates(id) ON DELETE CASCADE,
    client_id       BIGINT,                     -- denormalized for history after suppression deleted
    action          TEXT NOT NULL,              -- 'created' | 'updated' | 'deleted'
    changed_fields  JSONB,
    reason          TEXT,
    changed_by      INT NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_client_supp_log_client
    ON snc_client_suppression_log (client_id, changed_at DESC);
