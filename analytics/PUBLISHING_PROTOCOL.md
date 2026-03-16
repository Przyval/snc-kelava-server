# KPI Publishing Protocol
> **Standard Operating Procedure for Monthly KPI Release**  
> **Target Audience:** Ops Manager, HR Manager, CEO  
> **Frequency:** Monthly (1st working day)

---

## 1. Principles

1.  **Single Source of Truth**: All numbers must come from a specific **Run ID** (e.g., `runs/2026-01-01T090000Z`). Never pull ad-hoc numbers from database queries.
2.  **Dual Mode Distribution**:
    *   **FAIR Mode** → HR & Technicians (Bonus & Ranking)
    *   **STRICT Mode** → Operations & Supervisors (Audit & Process Improvement)
3.  **Iron Gate Rule**: Never publish if `acceptance_test_report.md` has failures.

---

## 2. Release Schedule

| Day | Action | Owner | Output |
|-----|--------|-------|--------|
| M-2 | **Dry Run** | Data Team | Check for data gaps, DQ flags |
| M-1 | **Final Run** | Data Team | Generated Run Folder |
| M+1 | **Review** | Ops Manager | Sign-off on "Fairness" |
| M+1 | **Publish** | HR/Data | Email & Dashboard Update |

---

## 3. Distribution Channels

### Channel A: HR & Technicians (Bonus)
**Source File:** `leaderboard_fair_clean.csv`  
**Key Metrics:** Total Score, Grade (A-F), Productivity  
**Note:** Use this for calculating monthly performance bonuses.

**Email Template:**
> **Subject:** KPI Report - [Month YYYY] - Official Ranking
>
> Dear Team,
>
> Attached is the finalized KPI leaderboard for [Month YYYY].
>
> **Summary:**
> *   **Top Performer (Mobile):** [Name from Executive Summary]
> *   **Top Performer (Station):** [Name from Executive Summary]
> *   **Global On-Time Rate:** [FAIR Rate]%
>
> **Bonus Eligibility:**
> *   Grades A & B: Eligible for performance bonus
> *   Grade C: Base salary only
> *   Grade D/F: Performance review required
>
> **Reference Run ID:** [Run ID]

### Channel B: Operations (Audit)
**Source File:** `leaderboard_strict_clean.csv` & `insight_pack.md`  
**Key Metrics:** STRICT On-Time, No-Photo Count, Suspect Time  
**Note:** Use this for coaching sessions and SOP enforcement.

**Email Template:**
> **Subject:** [AUDIT] Operational Issues Report - [Month YYYY]
>
> Dear Ops Team,
>
> This is the audit view (STRICT mode) for [Month YYYY].
>
> **Critical Issues:**
> 1.  **No-Photo Violation:** [Count] visits (Target: 0)
> 2.  **Suspect Time (21-23h):** [Count] visits
> 3.  **Multi-day Open Visits:** [Count] visits
>
> **Action Required:**
> *   Review the attached `actionable_watchlist.csv` with supervisors.
> *   Addresses the 3 systemic issues listed in the Insight Pack.
>
> **Reference Run ID:** [Run ID]

---

## 4. Handling Disputes

If a technician disputes their score:
1.  Check `run_metadata.json` to confirm config version used.
2.  Check `dq_flags` for that specific user.
3.  **Do not manually edit CSV.**
4.  If error is valid (e.g., app bug), fix data in `stg_` or adjust `kpi_config.yaml`, then **Re-Run Pipeline** to generate new Run ID.

---

## 5. Archival

*   Store `runs/{run_id}` folder indefinitely.
*   Tag the "Official Release" run folder (e.g., rename to `runs/2026-01_OFFICIAL`).
