-- Migration 034: Tech availability — extend existing snc_technician_day_status
-- ──────────────────────────────────────────────────────────────────────────
-- Tabel snc_technician_day_status sudah ada (id, technician_id, date, status,
-- reason, notes, created_at). Tambah field untuk:
--   - half_day_period: 'morning' | 'afternoon' | NULL
--   - backup_tech_id: pengganti
--   - created_by / updated_*
--   - UNIQUE (technician_id, date)

ALTER TABLE snc_technician_day_status
    ADD COLUMN IF NOT EXISTS half_day_period TEXT,
    ADD COLUMN IF NOT EXISTS backup_tech_id  BIGINT REFERENCES snc_technicians(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_by      INT,
    ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMPTZ DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_by      INT;

-- Unique constraint: 1 record per (tech, date)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'snc_tech_status_unique'
    ) THEN
        ALTER TABLE snc_technician_day_status
            ADD CONSTRAINT snc_tech_status_unique UNIQUE (technician_id, date);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tech_status_date_not_avail
    ON snc_technician_day_status (date)
    WHERE status != 'available';

CREATE TABLE IF NOT EXISTS snc_tech_status_log (
    id               BIGSERIAL PRIMARY KEY,
    tech_status_id   BIGINT REFERENCES snc_technician_day_status(id) ON DELETE CASCADE,
    technician_id    BIGINT,                     -- denormalized
    date             DATE,                       -- denormalized
    action           TEXT NOT NULL,              -- 'created' | 'updated' | 'deleted'
    changed_fields   JSONB,
    reason           TEXT,
    changed_by       INT NOT NULL,
    changed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tech_status_log_tech
    ON snc_tech_status_log (technician_id, changed_at DESC);
