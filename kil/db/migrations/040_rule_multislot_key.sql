-- Migration 040: Multi-slot rule key
-- ──────────────────────────────────────────────────────────────────────────
-- Bug: ON CONFLICT (client_id, effective_start) collapse 2 rule beda jam
-- untuk client sama (mis. CG Kaliasin pagi+malam jadi 1).
-- Fix: ganti unique key supaya include weekdays + time_start + week_pattern.

-- ── STEP 1: Drop old constraint ──────────────────────────────────────────
ALTER TABLE snc_recurring_rules
  DROP CONSTRAINT IF EXISTS snc_recurring_rules_client_id_effective_start_key;

-- ── STEP 2: New unique index — beda slot waktu boleh coexist ─────────────
-- Key: (client, weekdays, time_start, week_pattern). effective_start tidak
-- masuk key — kalau update rule existing, in-place update; kalau betul-betul
-- baru (slot beda), insert.
CREATE UNIQUE INDEX uq_rule_client_dow_time_wp
  ON snc_recurring_rules (
    client_id, weekdays, time_start, COALESCE(week_pattern, '_'));
