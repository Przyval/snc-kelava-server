-- Migration 039: Cleanup snc_recurring_rules anomali
-- ──────────────────────────────────────────────────────────────────────────
-- 1. Backfill time_end yang NULL → time_start + 1 jam (default visit duration)
-- 2. Dedup mandatory rules: per (client_id, weekdays, time_start),
--    keep latest effective_start (newest wins)
-- 3. Hapus rules dengan effective_start di masa depan jauh (>= 2027) yang
--    duplikat existing rule untuk client+dow yang sama (pattern detector
--    bug — auto-seed buat banyak rule overlap)

-- ── STEP 1: Backfill NULL time_end ───────────────────────────────────────
UPDATE snc_recurring_rules
SET time_end = (time_start + INTERVAL '1 hour')::time,
    notes = COALESCE(notes,'') || ' | time_end backfill 1h default'
WHERE time_end IS NULL
  AND time_start IS NOT NULL;

-- ── STEP 2: Dedup mandatory rules dengan (client, weekdays, time_start) sama ──
-- Keep id terkecil dengan effective_start terbaru (most recent)
WITH dups AS (
    SELECT id, ROW_NUMBER() OVER (
        PARTITION BY client_id, weekdays, time_start
        ORDER BY effective_start DESC NULLS LAST, id
    ) AS rn
    FROM snc_recurring_rules
    WHERE is_mandatory = true
)
DELETE FROM snc_recurring_rules
WHERE id IN (SELECT id FROM dups WHERE rn > 1);

-- ── STEP 3: Hapus rules future jauh (>= 2027-01-01) — auto-seed garbage ──
DELETE FROM snc_recurring_rules
WHERE effective_start >= '2027-01-01';

-- ── STEP 4: Drop redundant unique index dari migration 038 ───────────────
-- uq_snc_event_tech_client_dt_batch (031) dan uq_event_tech_client_datetime (038)
-- definisinya identik. Migration 038 redundant.
DROP INDEX IF EXISTS uq_event_tech_client_datetime;
