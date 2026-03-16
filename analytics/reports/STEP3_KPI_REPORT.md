# 📊 STEP 3.1: KPI Calculation Report (REFINED)

> **Generated:** 2026-01-13 11:39:55 WIB
> **Database:** /Users/michael/Downloads/Live SnC - Kelava Server/analytics/snc_analytics.db
> **Config:** /Users/michael/Downloads/Live SnC - Kelava Server/analytics/kpi_config.yaml
> **Version:** 3.1 - with segment-specific thresholds and STRICT/FAIR modes

---

## 1. Methodology (Refined)

### Changes from v3.0:

1. **scheduled_visits** now counted from all `stg_road_plan` records (not just those with check-in)
2. **no_photo count** is calculated from **completed visits only** (status='Selesai')
3. **Duration validity** uses segment-specific thresholds:

| Segment | Duration Range | Target Visits/Day |
|---------|----------------|-------------------|
| MOBILE | 5-480 min | 2.0 |
| STATION | 30-900 min | 1.0 |
| SUPPORT | 5-600 min | 1.5 |
| SUPERVISOR | 5-600 min | 1.5 |

### STRICT vs FAIR Mode Definitions

| Metric | FAIR Mode | STRICT Mode |
|--------|-----------|-------------|
| On-Time | actual_day = scheduled_day | + check_in hour 07:00-08:59 |
| Duration | Segment-specific thresholds | Global 5-480 min |
| Productivity | Segment-specific targets | Segment-specific targets |

---

## 2. Global KPI Summary (Corrected)

| Metric | FAIR | STRICT |
|--------|------|--------|
| Total Scheduled | 33,733 | - |
| Total Completed | 33,510 | - |
| Completion Rate | 99.34% | - |
| On-Time Rate | 77.03% | 14.51% |
| Duration Compliance | 79.84% (seg) | 63.8% (global) |
| Photo Compliance | 84.3% | - |

### Data Quality Issues (based on completed visits)

| Issue | Count |
|-------|-------|
| Multi-day Suspect | 3,431 |
| Suspect Time (21-23h) | 5,711 |
| No Photo (completed only) | 5,261 |

---

## 3. STRICT vs FAIR Delta Analysis

- Total technician-month records: **1,721**
- Grade changes (FAIR → STRICT): **1,391**
- Average score delta (FAIR - STRICT): **13.74** points
- Range: 0.0 to 35.0 points

### Top 10 Biggest Score Drops (FAIR → STRICT)

| Technician | Segment | FAIR Score | STRICT Score | Delta | Grade Change |
|------------|---------|------------|--------------|-------|--------------|
| Setyo Nugroho P R  | SUPPORT | 64.17 | 39.17 | +25.00 | D→F |
| Akbar Rohmatulah | SUPPORT | 76.67 | 56.67 | +20.00 | C→F |
| Suparman | MOBILE | 87.5 | 67.5 | +20.00 | B→D |
| Moch Maulana | MOBILE | 95.83 | 75.83 | +20.00 | A→C |
| Argantara Alif Saput | MOBILE | 75.0 | 55.0 | +20.00 | C→F |
| Ibad Qurthubi | SUPERVISOR | 100.0 | 80.0 | +20.00 | A→B |
| Maril dicky setiyawa | MOBILE | 85.12 | 65.12 | +20.00 | B→D |
| Nana Ruhdiana | SUPERVISOR | 91.67 | 71.67 | +20.00 | A→C |
| Sulistiono | STATION | 89.72 | 72.22 | +17.50 | B→C |
| Setyo Nugroho P R  | STATION | 69.1 | 52.22 | +16.88 | D→F |

---

## 4. Leaderboard - 2026-01 (FAIR Mode)

### MOBILE Segment

| Rank | Technician | Score | Grade | Completion | On-Time | Duration | Photo | Visits/Day |
|------|------------|-------|-------|------------|---------|----------|-------|------------|
| 1 | Andik Noroyan Fanani | 98.57 | A | 100.0% | 92.9% | 100.0% | 100.0% | 3.11 |
| 2 | Ananda Almas | 97.71 | A | 96.6% | 92.9% | 100.0% | 100.0% | 3.11 |
| 3 | Moch Maulana | 95.83 | A | 83.3% | 100.0% | 100.0% | 100.0% | 5.0 |
| 4 | Akbar Rohmatulah | 95.68 | A | 100.0% | 81.8% | 95.5% | 100.0% | 2.44 |
| 5 | M. Abu Samsudin | 94.2 | A | 94.4% | 82.4% | 94.1% | 100.0% | 2.43 |
| 6 | Bustomi | 93.33 | A | 100.0% | 66.7% | 100.0% | 100.0% | 3.0 |
| 7 | Dicky Darmawan | 91.43 | A | 100.0% | 75.0% | 100.0% | 100.0% | 1.71 |
| 8 | Choirul Anam | 87.54 | B | 96.3% | 65.4% | 69.2% | 100.0% | 2.89 |
| 9 | Suparman | 87.5 | B | 100.0% | 100.0% | 100.0% | 100.0% | 1.0 |
| 10 | I Wayan Rendy | 87.44 | B | 86.7% | 76.9% | 69.2% | 100.0% | 2.17 |

### STATION Segment

| Rank | Technician | Score | Grade | Completion | On-Time | Duration | Photo | Visits/Day |
|------|------------|-------|-------|------------|---------|----------|-------|------------|
| 1 | Robby Anggoro | 96.88 | A | 87.5% | 100.0% | 100.0% | 100.0% | 1.0 |
| 2 | Argantara Alif Saput | 90.0 | A | 100.0% | 80.0% | 80.0% | 80.0% | 1.25 |
| 3 | Sulistiono | 89.72 | B | 88.9% | 62.5% | 100.0% | 100.0% | 1.0 |
| 4 | Aldimas Fachrur Rozi | 87.01 | B | 91.7% | 45.5% | 100.0% | 100.0% | 1.22 |
| 5 | Rizal Darmawan | 71.33 | C | 83.3% | 30.0% | 30.0% | 100.0% | 1.0 |
| 6 | Setyo Nugroho P R  | 69.1 | D | 88.9% | 62.5% | 62.5% | 0.0% | 1.0 |
| 7 | Dwi Santoso | 64.17 | D | 26.7% | 50.0% | 50.0% | 100.0% | 1.0 |
| 8 | Muchammad Bayu Agung | 60.45 | D | 81.8% | 0.0% | 0.0% | 100.0% | 1.29 |
| 9 | Nur Imam Siswo Utomo | 0.0 | F | 0.0% | 0.0% | 0.0% | 0.0% | 0.0 |

---

## 5. Grade Distribution (FAIR vs STRICT)

### FAIR Mode

| Segment | A | B | C | D | F |
|---------|---|---|---|---|---|
| MOBILE | 7 | 8 | 4 | 1 | 1 |
| STATION | 2 | 2 | 1 | 3 | 1 |
| SUPPORT | 0 | 2 | 2 | 2 | 3 |
| SUPERVISOR | 2 | 3 | 0 | 1 | 0 |

### STRICT Mode

| Segment | A | B | C | D | F |
|---------|---|---|---|---|---|
| MOBILE | 0 | 5 | 7 | 7 | 2 |
| STATION | 0 | 1 | 3 | 2 | 3 |
| SUPPORT | 0 | 0 | 1 | 2 | 6 |
| SUPERVISOR | 0 | 1 | 3 | 2 | 0 |

---

## ✅ Step 3.1 Refinement Checklist

| Fix | Description | Status |
|-----|-------------|--------|
| 1 | Denominator from stg_road_plan | ✅ Corrected |
| 2 | No-photo basis clarified (completed only) | ✅ Documented |
| 3 | Segment-specific duration & productivity | ✅ Implemented |
| 4 | STRICT vs FAIR with real differences | ✅ Delta report created |
| 5 | Audit with dominant segment | ✅ Clean labels |

**Step 3.1 Complete!** 🚀
