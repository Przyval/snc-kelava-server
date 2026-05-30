-- Migration 032: Add ON DELETE CASCADE to snc_schedule_events → snc_draft_batches
-- Discovered during June 2026 draft regeneration: replacing an existing batch
-- failed with ForeignKeyViolation because schedule_events did not cascade-delete
-- with the batch. Migration 031 covered conflicts + audit log but missed events.

ALTER TABLE snc_schedule_events
    DROP CONSTRAINT IF EXISTS snc_schedule_events_draft_batch_id_fkey;
ALTER TABLE snc_schedule_events
    ADD CONSTRAINT snc_schedule_events_draft_batch_id_fkey
    FOREIGN KEY (draft_batch_id) REFERENCES snc_draft_batches(id)
    ON DELETE CASCADE;
