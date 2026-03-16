# STRICT Mode Definition v2

> **Generated:** 2026-01-13 11:53:48 WIB

## Problem with STRICT v1

STRICT v1 defined on-time as: `check_in hour between 07:00-08:59 AND same day`

This was too restrictive because:
- It tested 'office arrival time' not 'visit punctuality'
- Technicians with afternoon/evening visits were automatically 'late'
- Result: Only 4,862 on-time out of 33,510 completed (14.5%)

## STRICT v2 Definition

**On-Time STRICT v2:** `same day as scheduled AND NOT suspect time (21-23h)`

Rationale:
- Still checks if visit happened on scheduled day
- Penalizes 'end of day bulk submission' (21-23h)
- But doesn't penalize legitimate afternoon/evening visits

## Impact Comparison

| Metric | FAIR | STRICT v1 | STRICT v2 |
|--------|------|-----------|-----------|
| On-Time Count | 25,812 | 4,862 | 22,976 |
| On-Time Rate | 77.0% | 14.5% | 68.6% |

## Recommendation

Use **STRICT v2** for audit mode as it:
1. Catches genuine timing issues (bulk submissions)
2. Doesn't unfairly penalize afternoon schedules
3. Provides meaningful differentiation (not 'everyone fails')
