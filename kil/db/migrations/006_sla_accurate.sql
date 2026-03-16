-- Migration 006: Complaint SLA + Accurate Export Log
-- Run: python scripts/apply_migration_006.py

-- Add SLA fields to complaint_tickets (if table exists)
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'complaint_tickets') THEN
        ALTER TABLE complaint_tickets
            ADD COLUMN IF NOT EXISTS sla_hours INTEGER DEFAULT 48,
            ADD COLUMN IF NOT EXISTS sla_deadline TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS sla_breached BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS resolution_notes TEXT;

        -- Backfill sla_deadline for existing open tickets
        UPDATE complaint_tickets
        SET sla_deadline = created_at + (sla_hours * INTERVAL '1 hour')
        WHERE sla_deadline IS NULL AND status NOT IN ('resolved', 'closed');

        -- Mark already-breached tickets
        UPDATE complaint_tickets
        SET sla_breached = TRUE
        WHERE sla_deadline IS NOT NULL
          AND sla_deadline < NOW()
          AND status NOT IN ('resolved', 'closed');
    END IF;
END $$;

-- Accurate export log table
CREATE TABLE IF NOT EXISTS enterprise_accurate_export_log (
    id BIGSERIAL PRIMARY KEY,
    exported_by INTEGER,
    export_month TEXT NOT NULL,
    row_count INTEGER DEFAULT 0,
    exported_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_accurate_export_month
    ON enterprise_accurate_export_log(export_month DESC);
