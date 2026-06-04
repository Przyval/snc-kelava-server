-- Migration 041: Dedup auto-seed multi-dow rules yang sudah replaced xlsx
-- ──────────────────────────────────────────────────────────────────────────
-- Pre-existing rules (id=1, 2, 10, ...) punya weekdays array panjang
-- (mis. BDG dow=[2,3,4]) dari auto-seed era awal. Sekarang xlsx koord
-- override dengan single-dow rules (dow=[2], [3], [4] terpisah).
--
-- Drop multi-dow rules jika TIAP dow-nya sudah punya single-dow rule
-- untuk client sama.

WITH multi_dow AS (
    SELECT id, client_id, weekdays
    FROM snc_recurring_rules
    WHERE array_length(weekdays, 1) > 1
      AND (effective_end IS NULL OR effective_end >= CURRENT_DATE)
),
covered AS (
    SELECT m.id
    FROM multi_dow m
    WHERE NOT EXISTS (
        SELECT 1 FROM unnest(m.weekdays) AS dow
        WHERE NOT EXISTS (
            SELECT 1 FROM snc_recurring_rules r2
            WHERE r2.client_id = m.client_id
              AND r2.id != m.id
              AND array_length(r2.weekdays, 1) = 1
              AND r2.weekdays[1] = dow
              AND (r2.effective_end IS NULL OR r2.effective_end >= CURRENT_DATE)
        )
    )
)
DELETE FROM snc_recurring_rules WHERE id IN (SELECT id FROM covered);

-- Drop optional rules yang overlap (same client + same dow) dengan mandatory
-- xlsx rules. xlsx adalah golden source — tidak butuh pattern-derived noise.
DELETE FROM snc_recurring_rules opt
USING snc_recurring_rules mand
WHERE opt.is_mandatory = false
  AND mand.is_mandatory = true
  AND opt.client_id = mand.client_id
  AND opt.weekdays && mand.weekdays
  AND (opt.effective_end IS NULL OR opt.effective_end >= CURRENT_DATE)
  AND (mand.effective_end IS NULL OR mand.effective_end >= CURRENT_DATE);
