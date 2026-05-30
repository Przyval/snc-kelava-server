-- Migration 030: Extend schedule_status CHECK constraint
-- BUG FIX: PRD §24.2 requires 'approved' status, existing constraint blocked it.

ALTER TABLE snc_schedule_events
    DROP CONSTRAINT IF EXISTS snc_schedule_events_schedule_status_check;

ALTER TABLE snc_schedule_events
    ADD CONSTRAINT snc_schedule_events_schedule_status_check
    CHECK (schedule_status = ANY (ARRAY[
        'draft'::text,
        'approved'::text,        -- NEW: approved but not published
        'scheduled'::text,        -- existing: published, visible to tech
        'completed'::text,
        'cancelled'::text,
        'rescheduled'::text,
        'no_show'::text,
        'pending_report'::text,
        'skipped'::text           -- NEW: explicitly skipped (e.g. holiday)
    ]));

-- Bug #3 fix: extend snc_draft_batches.status untuk include published/in_review/partially_approved
ALTER TABLE snc_draft_batches
    DROP CONSTRAINT IF EXISTS snc_draft_batches_status_check;

ALTER TABLE snc_draft_batches
    ADD CONSTRAINT snc_draft_batches_status_check
    CHECK (status = ANY (ARRAY[
        'draft'::text,
        'in_review'::text,
        'partially_approved'::text,
        'approved'::text,
        'published'::text,         -- NEW: final state
        'rejected'::text,
        'cancelled'::text
    ]));
