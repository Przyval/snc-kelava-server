# Ops Sign-Off: KPI Policy Decisions
> **Document Status:** PENDING APPROVAL  
> **Created:** 2026-01-13  
> **Required By:** 2026-01-17 (End of Week 1)

---

## Purpose

Three policy decisions are required from Operations before the KPI system can be finalized for bonus calculations and audit. These decisions will be locked into `kpi_config.yaml`.

---

## Decision 1: SUPPORT/CHECKLIST Photo Requirement

### Current State
- SUPPORT/CHECKLIST visits have **100% no-photo rate** (2,750 visits)
- This is either:
  - (A) **By design** — checklist tasks don't require photographic evidence
  - (B) **A gap** — photos should be required but app flow doesn't enforce it

### Question
**Do SUPPORT/CHECKLIST visits require photos?**

| Option | Impact on KPI | Impact on App |
|--------|---------------|---------------|
| ☐ **NO** (exempt) | SUPPORT excluded from photo KPI | No app change needed |
| ☐ **YES** (required) | SUPPORT penalized for no-photo | CR-002 must include SUPPORT |

### Approved Decision
**Decision:** _________________  
**Approved By:** _________________  
**Date:** _________________

---

## Decision 2: Night Visits (21:00-23:59) Legitimacy

### Current State
- **5,711 visits** (17%) have check-in time between 21:00-23:59
- Top customers with night visits:
  - Bukit Darmo Golf
  - Pakuwon City Mall
  - VASA Hotel

### Question
**Are night visits (21-23h) legitimate scheduled work, or "bulk submission at end of day"?**

| Option | Impact on KPI | Implementation |
|--------|---------------|----------------|
| ☐ **Mostly legitimate** | Keep FAIR mode lenient | Add customer whitelist for STRICT |
| ☐ **Mostly bulk submit** | Use STRICT v2 (penalize 21-23h) | Current implementation OK |
| ☐ **Mixed** | Create customer-specific rules | Whitelist: _________ |

### Approved Decision
**Decision:** _________________  
**Customer Whitelist (if any):** _________________  
**Approved By:** _________________  
**Date:** _________________

---

## Decision 3: STATION Visit Duration Definition

### Current State
- STATION visits have a **median duration of 507 minutes** (~8.5 hours)
- P90 duration is 653 minutes (~11 hours)
- Current threshold: 30-900 minutes (0.5 to 15 hours)

### Question
**Is it normal for STATION technicians to spend 8+ hours at a single location?**

| Option | Impact on KPI | Threshold |
|--------|---------------|-----------|
| ☐ **Yes, normal** | Current 30-900 min threshold is appropriate | No change |
| ☐ **No, too long** | Tighten threshold | New max: _____ minutes |
| ☐ **Depends on customer** | Create customer-specific SLAs | List: _________ |

### Context
- STATION visits are typically at fixed locations (malls, hotels)
- Examples: Pakuwon City Mall, VASA Hotel, Ciputra World

### Approved Decision
**Decision:** _________________  
**Threshold:** _________________  
**Approved By:** _________________  
**Date:** _________________

---

## Summary of Approved Policies

Once approved, these will be locked in `kpi_config.yaml`:

| Policy | Decision | Effective Date |
|--------|----------|----------------|
| SUPPORT photo requirement | ☐ Exempt / ☐ Required | _______ |
| Night visit treatment | ☐ Lenient / ☐ STRICT v2 | _______ |
| STATION duration threshold | _____ - _____ min | _______ |

---

## Signatures

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Operations Manager | | | |
| HR (Bonus Owner) | | | |
| Data/Analytics | | | |

---

> **Note:** After sign-off, update `analytics/kpi_config.yaml` with approved values and re-run pipeline to regenerate leaderboards with final definitions.
