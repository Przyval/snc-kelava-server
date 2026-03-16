# 📊 Insight Pack - January 2026

> **Generated:** 2026-01-13 12:23:19 WIB
> **Data Period:** Up to 2026-01-13
> **Leaderboard Month:** 2026-01

---

## 1. Executive Summary

### Key Metrics

| Metric | Count | Rate |
|--------|-------|------|
| Total Completed | 33,510 | - |
| On-Time (FAIR) | 25,982 | 77.5% |
| No Photo | 5,261 | 15.7% ⚠️ |
| Multi-day Duration | 3,431 | 10.2% ⚠️ |
| Suspect Time (21-23h) | 5,711 | 17.0% ⚠️ |

### Top 3 Operational Issues This Period

1. **No-Photo Compliance:** 5,261 visits without photos (15.7%)
2. **Suspect Time Entries:** 5,711 check-ins between 21:00-23:59 (17.0%)
3. **Multi-day Durations:** 3,431 visits with checkout weeks/months after check-in

### Top Performers - MOBILE Segment

| Rank | Technician | Score | Grade |
|------|------------|-------|-------|
| 1 | Andik Noroyan Fananiar | 98.57 | A |
| 2 | Ananda Almas | 97.71 | A |
| 3 | Moch Maulana | 95.83 | A |
| 4 | Akbar Rohmatulah | 95.68 | A |
| 5 | M. Abu Samsudin | 94.2 | A |

---

## 2. Root Cause Analysis

### Multi-day Duration ('Forgot to Checkout')

**Pattern:** Multi-day durations are NOT random - they cluster by specific technicians and customers.

**Top 5 Technicians with Multi-day Issues:**

| Technician | Segment | Count | Avg Days |
|------------|---------|-------|----------|
| Moh. Mahrus | MOBILE | 486 | 2.8 |
| Akbar Rohmatulah | MOBILE | 360 | 6.7 |
| Dwi Santoso | STATION | 225 | 16.2 |
| Syaiful Murryd | MOBILE | 194 | 12.1 |
| Rizal Darmawan | STATION | 181 | 1.7 |

**Top 5 Customers with Multi-day Issues:**

| Customer | Segment | Count | Techs Affected |
|----------|---------|-------|----------------|
| Pakuwon City Mall | STATION | 439 | 10 |
| Pakuwon City Mall 3 | STATION | 270 | 9 |
| SEKOLAH CIKAL SURABAYA | MOBILE | 129 | 6 |
| VASA HOTEL | STATION | 112 | 9 |
| SEKOLAH CIKAL SURABAYA | SUPPORT | 104 | 5 |

**By Segment:**

| Segment | Multi-day Count | % of Total |
|---------|-----------------|------------|
| MOBILE | 1826 | 53.2% |
| STATION | 1016 | 29.6% |
| SUPERVISOR | 299 | 8.7% |
| SUPPORT | 290 | 8.5% |

### No-Photo Compliance

**By Segment (key insight: SUPPORT/CHECKLIST has 100% no-photo - may be by design):**

| Segment | Completed | No Photo | Rate |
|---------|-----------|----------|------|
| SUPPORT | 2,750 | 2,750 | 100.0% ⚠️ |
| STATION | 8,071 | 1,591 | 19.7% |
| SUPERVISOR | 2,041 | 116 | 5.7% |
| MOBILE | 20,648 | 804 | 3.9% |
| OTHER | 0 | 0 | None% |

> **Recommendation:** If SUPPORT/CHECKLIST visits don't require photos by SOP, exclude them from photo compliance KPI.

### Suspect Time (21:00-23:59)

**Co-occurrence Analysis (are 21-23h entries just 'quick clicks'?):**

| Pattern | Count |
|---------|-------|
| suspect_time_only | 4,257 |
| suspect_AND_no_photo | 251 |
| suspect_AND_invalid_duration | 1,288 |
| suspect_AND_no_photo_AND_invalid_duration | 96 |

### Station Duration Justification

**Duration Percentiles by Segment (minutes):**

| Segment | P25 | P50 (Median) | P75 | P90 |
|---------|-----|--------------|-----|-----|
| MOBILE | 54.77 | 93.65 | 176.38 | 297.27 |
| STATION | 475.55 | 506.55 | 547.17 | 652.55 |
| SUPPORT | 73.7 | 169.47 | 490.68 | 521.7 |
| SUPERVISOR | 46.02 | 130.07 | 402.75 | 605.97 |

> **Key Finding:** STATION median duration is significantly higher than MOBILE. Using the same 5-480 min threshold would unfairly penalize STATION technicians. Segment-specific thresholds (STATION: 30-900 min) are appropriate.

---

## 3. Action Plan & Watchlist

### Immediate App/System Changes (High Impact)

| Priority | Change | Expected Impact |
|----------|--------|-----------------|
| 🔴 P1 | **Auto-checkout at 18:00** if visit still open | Eliminates multi-day duration issue |
| 🔴 P1 | **Block checkout if foto_count = 0** (for MOBILE/STATION) | Enforces photo compliance |
| 🟡 P2 | **'Open visit' indicator** - can't start new visit if one is open | Prevents forgot-checkout |
| 🟡 P2 | **Server-recorded timestamps** - prevent backdating check-in | Accurate on-time measurement |
| 🟢 P3 | **Reminder notification** 2 hours after check-in if no checkout | Nudge before auto-action |

### 30-Day Watchlist (Technicians Needing Attention)

| Technician | Issue | Count (30d) | Priority |
|------------|-------|-------------|----------|
| Choirul Anam | No Photo | 21 | 🔴 |
| Robby Anggoro | No Photo | 19 | 🔴 |
| Setyo Nugroho P R  | No Photo | 19 | 🔴 |
| Muchammad Bayu Agung Perm | Multi-day | 16 | 🟡 |
| Moh. Mahrus | Multi-day | 16 | 🟡 |
| I Wayan Rendy | Multi-day | 16 | 🟡 |
| Rizal Darmawan | Multi-day | 14 | 🟡 |
| Dwi Santoso | Multi-day | 13 | 🟡 |
| Andik Noroyan Fananiar | No Photo | 10 | 🔴 |
| M. Abu Samsudin | No Photo | 8 | 🔴 |

### SOP Clarifications Needed

1. **SUPPORT/CHECKLIST photo requirement:** Confirm if these visit types require photos. If not, exclude from photo compliance KPI.
2. **Night visits legitimacy:** Some customers (e.g., Bukit Darmo Golf) show high suspect time. Verify if night visits are part of their service contract.
3. **STATION visit definition:** Confirm if STATION visits can legitimately span 8-15 hours (current data shows this is common).

---

## ✅ Deliverables Generated

| File | Description |
|------|-------------|
| `multiday_rootcause_by_tech.csv` | Technicians with multi-day issues |
| `multiday_rootcause_by_customer.csv` | Customers with multi-day issues |
| `no_photo_watchlist_30d.csv` | 30-day no-photo watchlist |
| `no_photo_by_segment.csv` | No-photo rates by segment |
| `suspect_time_heatmap_by_tech.csv` | Suspect time analysis |
| `suspect_time_cooccurrence.csv` | Pattern co-occurrence |

**Step 4 Complete!** 🚀
