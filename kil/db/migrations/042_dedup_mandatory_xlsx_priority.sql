-- Migration 042: xlsx master rules > pre-existing mandatory rules
-- ──────────────────────────────────────────────────────────────────────────
-- Bug: Tristar id=3 (auto-seed `weekly` mandatory) override xlsx id=2865
-- (biweekly wp=1,3). Generate fire 4× pagi instead of 2× alternating.
--
-- Fix: jika ada xlsx-tagged mandatory rule untuk (client, weekdays, time_start),
-- delete mandatory rule LAIN dengan key sama yang notes-nya BUKAN
-- "Master rule dari xlsx koord".

DELETE FROM snc_recurring_rules old
USING snc_recurring_rules xlsx
WHERE old.is_mandatory = true
  AND xlsx.is_mandatory = true
  AND xlsx.notes ILIKE '%Master rule dari xlsx koord%'
  AND old.id != xlsx.id
  AND old.client_id = xlsx.client_id
  AND old.weekdays = xlsx.weekdays
  AND old.time_start = xlsx.time_start
  AND (old.notes IS NULL OR old.notes NOT ILIKE '%Master rule dari xlsx koord%')
  AND (old.effective_end IS NULL OR old.effective_end >= CURRENT_DATE);
