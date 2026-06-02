-- Migration 035: Extend snc_clients + audit log for Lokasi UI
-- ──────────────────────────────────────────────────────────────────────────

ALTER TABLE snc_clients
    ADD COLUMN IF NOT EXISTS deactivated_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deactivation_reason  TEXT,
    ADD COLUMN IF NOT EXISTS contact_person       TEXT,
    ADD COLUMN IF NOT EXISTS contact_phone        TEXT,
    ADD COLUMN IF NOT EXISTS notes                TEXT,
    ADD COLUMN IF NOT EXISTS updated_at           TIMESTAMPTZ DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_by           INT,
    ADD COLUMN IF NOT EXISTS created_by           INT;

CREATE TABLE IF NOT EXISTS snc_client_log (
    id              BIGSERIAL PRIMARY KEY,
    client_id       BIGINT REFERENCES snc_clients(id) ON DELETE CASCADE,
    action          TEXT NOT NULL,              -- 'created' | 'updated' | 'deactivated' | 'reactivated'
    changed_fields  JSONB,
    reason          TEXT,
    changed_by      INT NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_client_log_client
    ON snc_client_log (client_id, changed_at DESC);
