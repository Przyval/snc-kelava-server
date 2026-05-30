-- Migration 031: Data Integrity Cleanup (from AUDIT A findings)
-- 1. Remove orphan conflicts (from deleted batches)
-- 2. Remove 8 legacy duplicate scheduled events (batch=NULL, kept oldest)
-- 3. Add FK cascade untuk prevent future orphans
-- 4. Add unique constraint untuk prevent future duplicates

-- ── Clean orphan conflicts ───────────────────────────────────────────────
DELETE FROM snc_schedule_conflicts sc
WHERE NOT EXISTS (
    SELECT 1 FROM snc_draft_batches db WHERE db.id = sc.draft_batch_id
);

-- ── Clean orphan audit log ────────────────────────────────────────────────
DELETE FROM snc_schedule_audit_log sal
WHERE sal.draft_batch_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM snc_draft_batches db WHERE db.id = sal.draft_batch_id
  );

-- ── Dedup legacy events (keep oldest id per duplicate) ───────────────────
WITH duplicates AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY technician_id, client_id, start_datetime, COALESCE(draft_batch_id, -1)
               ORDER BY id
           ) AS rn
    FROM snc_schedule_events
)
DELETE FROM snc_schedule_events
WHERE id IN (SELECT id FROM duplicates WHERE rn > 1);

-- ── Add FK constraints dengan CASCADE supaya orphan tidak terjadi lagi ──
-- snc_schedule_conflicts → snc_draft_batches
ALTER TABLE snc_schedule_conflicts
    DROP CONSTRAINT IF EXISTS snc_schedule_conflicts_draft_batch_id_fkey;
ALTER TABLE snc_schedule_conflicts
    ADD CONSTRAINT snc_schedule_conflicts_draft_batch_id_fkey
    FOREIGN KEY (draft_batch_id) REFERENCES snc_draft_batches(id)
    ON DELETE CASCADE;

-- snc_schedule_audit_log → snc_draft_batches
ALTER TABLE snc_schedule_audit_log
    DROP CONSTRAINT IF EXISTS snc_schedule_audit_log_draft_batch_id_fkey;
ALTER TABLE snc_schedule_audit_log
    ADD CONSTRAINT snc_schedule_audit_log_draft_batch_id_fkey
    FOREIGN KEY (draft_batch_id) REFERENCES snc_draft_batches(id)
    ON DELETE CASCADE;

-- ── Unique index untuk prevent future duplicate events ──────────────────
-- COALESCE expression wrapped in extra parens (required for non-function expressions in PG).
CREATE UNIQUE INDEX IF NOT EXISTS uq_snc_event_tech_client_dt_batch
    ON snc_schedule_events (technician_id, client_id, start_datetime,
                            (COALESCE(draft_batch_id, -1)));
