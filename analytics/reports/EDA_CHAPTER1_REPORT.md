# EDA Chapter 1: Baseline & Diagnosis Report
> **Data Source:** `snc_analytics.db` (33,727 Visits)  
> **Unit of Analysis:** Visit & Technician  
> **Generated:** 2026-01-13

---

## 1. Executive Summary
We analyzed 33k+ visits to establish statistical baselines for Operations.
**Key Finding:** "SanoCare has two distinct operational models running in parallel."
*   **MOBILE** technicians are "Sprinters": High volume (2.2 visits/day), short duration (93 min).
*   **STATION** technicians are "Marathoners": Low volume (1.1 visits/day), long duration (8.4 hours).
*   **Risk:** 23% of Mobile visits are >176 mins (P75), indicating potential inefficiency or multi-day errors.

---

## 2. Baseline Standards (The "New Normal")

Based on robust statistics (Median & IQR), these should be the operational targets.

### A. Duration (Time on Site)
*Avoid using Mean due to extreme outliers. Use Median.*

| Segment | Median (P50) | Normal Range (P25-P75) | "Too Fast" (<P5) | "Suspiciously Long" (>P95) |
|:---|:---:|:---:|:---:|:---:|
| **MOBILE** | **94 min** (1.5h) | 55 - 176 min | < 5 min | > 10.4 hours |
| **STATION** | **506 min** (8.4h) | 475 - 547 min | < 12 min | > 16.8 hours |
| **SUPERVISOR** | **122 min** (2h) | 45 - 396 min | < 10 min | > 13 hours |

**Insight:**
*   **Station consistency is incredible:** IQR is only 72 mins (tight variance), meaning they really do strict shifts.
*   **Mobile variance is huge:** IQR is 121 mins. This variability suggests inconsistent job sizing or travel issues.

### B. Productivity (Visits per Day)
*How many tickets does a human close?*

| Segment | Target (Median) | High Performer (P75) | Max Observed |
|:---|:---:|:---:|:---:|
| **MOBILE** | **2.0 visits** | 3.0 visits | 27 (Data Error/Bulk) |
| **STATION** | **1.0 visit** | 1.0 visit | 5 |

**Insight:**
*   Mobile technicians consistently hit 2 visits/day.
*   "Max 27 visits" confirms the bulk-upload behavior (The Night Owl issue).

---

## 3. Segment Composition

| Segment | Share of Volume |
|:---|:---:|
| **MOBILE** | **63%** |
| **STATION** | **24%** |
| SUPPORT | 8% |
| SUPERVISOR | 6% |

**Strategic Note:** 
Ops focuses heavily on scheduling Mobile techs (63%), but Station contracts likely yield higher steady revenue per tech. Ensure Station KPIs (Presence focus) don't get drowned out by Mobile KPIs (Quantity focus).

---

## 4. Anomalies & Events

From the statistical distribution, we flag the following as "Needs Investigation":
1.  **Mobile Visits > 10 Hours:** (P95 is 625 min). Any Mobile visit > 10h is likely a "Forgot Checkout".
2.  **Station Visits < 4 Hours:** (P5 is 12 min, P25 is 474 min). Station visits under 4 hours likely indicate missed shifts or very late check-ins.
3.  **Supervisors:** Their distribution is extremely skewed (Mean 247 vs Median 122). Some supervisors work 12h, others 1h. Is this expected?

---

## 5. Next Actions (Hypothesis to Test)

1.  **Refine Duration Alerts:**
    *   Set Mobile warning at 180 mins (3h).
    *   Set Station warning at < 450 mins (7.5h).
2.  **Productivity Bonus:**
    *   Reward Mobile techs hitting >3 visits/day (P75) without quality issues.
3.  **App Config:**
    *   The "Auto-checkout" rule (CR-001) should trigger at 18:00 for **Mobile** only. Station techs often work until mall closing (22:00).

*(Generated via `step8_eda_chapter1.py`)*
