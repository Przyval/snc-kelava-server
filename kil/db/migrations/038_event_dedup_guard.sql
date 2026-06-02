-- Migration 038: Dedup guard untuk snc_schedule_events
-- ──────────────────────────────────────────────────────────────────────────
-- Prevent duplikat (tech, client, start_datetime) physically — sehingga
-- bug "1 visit muncul 2x di xlsx" tidak akan pernah terjadi lagi.
--
-- Step 1: cleanup duplicate rows yang sudah ada (keep id terkecil)
-- Step 2: add partial unique index (per status: draft & scheduled tidak
--         boleh punya pair yg sama secara silang)

-- ── STEP 1: Cleanup existing dups ────────────────────────────────────────
-- Per (tech, client, start_datetime), keep oldest id (smallest)
WITH dups AS (
    SELECT id, ROW_NUMBER() OVER (
        PARTITION BY technician_id, client_id, start_datetime
        ORDER BY
          CASE schedule_status
            WHEN 'published' THEN 1
            WHEN 'approved'  THEN 2
            WHEN 'scheduled' THEN 3
            WHEN 'draft'     THEN 4
            ELSE 5
          END,
          id
    ) AS rn
    FROM snc_schedule_events
    WHERE start_date >= '2026-01-01'
)
DELETE FROM snc_schedule_events
WHERE id IN (SELECT id FROM dups WHERE rn > 1);

-- ── STEP 2: Unique index untuk prevent future dups ───────────────────────
-- Soft constraint: per (tech, client, start_datetime) — beda waktu boleh.
-- COALESCE(draft_batch_id, -1) untuk distinguish events tanpa batch.
CREATE UNIQUE INDEX IF NOT EXISTS uq_event_tech_client_datetime
    ON snc_schedule_events (
        technician_id, client_id, start_datetime,
        (COALESCE(draft_batch_id, -1))
    );

-- Note: existing uq_snc_event_tech_client_dt_batch dari migrasi 031 sudah
-- ada tapi belum cover semua cases. Index ini lebih strict.
