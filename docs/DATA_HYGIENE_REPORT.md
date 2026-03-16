# 🔍 SanoCare Database - Data Hygiene Report

> **Generated:** 2026-01-10 16:30 WIB  
> **Database:** sanocare @ app.kelava.id  
> **Analyst:** Antigravity via VPS 104.194.154.108

---

## 📊 Export Summary

| File | Size | Rows | Status |
|------|------|------|--------|
| `t_visit.csv` | 188 MB | 33,645 | ✅ |
| `t_road_plan_area.csv` | 9.3 MB | ~100K | ✅ |
| `t_notif.csv` | 7.2 MB | 13,346 | ✅ |
| `t_road_plan.csv` | 4.3 MB | 33,651 | ✅ |
| `m_customer.csv` | 287 KB | 1,301 | ✅ |
| `m_customer_kontrak_subarea.csv` | 138 KB | - | ✅ |
| `p_user.csv` | 18 KB | 85 | ✅ |
| `m_customer_kontrak_area.csv` | 10 KB | - | ✅ |
| `m_customer_kontrak.csv` | 5.7 KB | 75 | ✅ |
| `m_outlet.csv` | 688 B | 2 | ✅ |
| `m_client.csv` | 497 B | 2 | ✅ |

**Total Export: ~209 MB (11 files)**

---

## 🚨 Data Quality Issues Found

### CRITICAL (Requires Attention)

#### 1. Excessive NULL Values in Core Tables

| Table | Column | NULL Count | % NULL | Severity |
|-------|--------|------------|--------|----------|
| `m_customer` | id_segment | 1,301 | **100%** | 🔴 Critical |
| `m_customer` | id_city | 1,276 | **98%** | 🔴 Critical |
| `m_customer` | email | 884 | **68%** | 🟠 High |
| `t_road_plan` | id_kontrak | 30,892 | **92%** | 🟠 High |
| `t_visit` | id_customer | 33,642 | **99.9%** | 🟠 High |
| `t_visit` | check_out | 208 | **0.6%** | 🟡 Medium |

**Impact:**
- Cannot segment customers properly
- Cannot link visits to customers directly
- 92% road plans not linked to contracts

---

#### 2. Duration Anomalies (Visits > 12 Hours)

| Metric | Value |
|--------|-------|
| Visits > 12 hours | **4,927** |
| Percentage | **14.6%** |

**Possible Causes:**
- Technician forgot to check-out
- Check-out done next day
- System/app bug

**Recommendation:** Add business rule to auto-close visits after X hours or flag for review.

---

### MEDIUM (Monitor)

#### 3. Duplicate Customer Names

| Name | Count |
|------|-------|
| Rumah | 3 |
| BU HEILYN | 2 |
| Jakarta | 2 |
| Suwandi Sridjaja | 2 |
| PAK DJAJA | 2 |
| + 5 more... | 2 each |

**Recommendation:** Implement unique constraint or merge duplicates.

---

#### 4. Incomplete Visits (No Check-out)

| Metric | Value |
|--------|-------|
| Visits without check_out | **208** |
| Percentage | **0.6%** |

**Status:** These are likely "in-progress" visits or system issues.

---

### ✅ GOOD (No Issues)

| Check | Result |
|-------|--------|
| Orphaned road_plans (invalid user) | **0** ✅ |
| Orphaned road_plans (invalid customer) | **0** ✅ |
| Future visit dates | **0** ✅ |
| Visits before 2020 | **0** ✅ |
| Negative durations (checkout < checkin) | **0** ✅ |
| Invalid GPS coordinates | **1** ✅ |

---

## 📈 Data Completeness Matrix

```
TABLE: m_customer (1,301 rows)
├── id               ████████████████████ 100%
├── name             ████████████████████ 100%
├── address          ████████████████████  99%
├── phone1           ████████████████████  98%
├── email            ██████░░░░░░░░░░░░░░  32%
├── id_city          ░░░░░░░░░░░░░░░░░░░░   2%
└── id_segment       ░░░░░░░░░░░░░░░░░░░░   0%

TABLE: t_road_plan (33,651 rows)
├── id               ████████████████████ 100%
├── visit_date       ████████████████████ 100%
├── status           ████████████████████ 100%
├── id_user          ████████████████████ 100%
├── id_customer      ████████████████████ 100%
├── type             ████████████████████ 100%
└── id_kontrak       ██░░░░░░░░░░░░░░░░░░   8%

TABLE: t_visit (33,645 rows)
├── id               ████████████████████ 100%
├── check_in         ████████████████████ 100%
├── id_road_plan     ████████████████████ 100%
├── latitude/long    ████████████████████ 100%
├── check_out        ████████████████████  99%
└── id_customer      ░░░░░░░░░░░░░░░░░░░░   0%
```

---

## 🔧 Recommended Actions

### Priority 1 (Immediate)
1. **Fix `t_visit.id_customer`** - Link visits to customers via `t_road_plan`
2. **Review 4,927 visits > 12 hours** - Flag/close anomalous durations

### Priority 2 (Short-term)
3. **Populate `m_customer.id_city`** from address or geocoding
4. **Define customer segments** and populate `id_segment`
5. **Link road_plans to contracts** (`id_kontrak`)

### Priority 3 (Maintenance)
6. **Add check constraints** for duration limits
7. **Implement duplicate detection** for customers
8. **Auto-close visits** after business hours

---

## 📁 Export Location

```
/Users/michael/Downloads/Live SnC - Kelava Server/db_export/
├── m_client.csv
├── m_customer.csv
├── m_customer_kontrak.csv
├── m_customer_kontrak_area.csv
├── m_customer_kontrak_subarea.csv
├── m_outlet.csv
├── p_user.csv
├── t_notif.csv
├── t_road_plan.csv
├── t_road_plan_area.csv
└── t_visit.csv
```

---

## 📊 Quick Stats

| Metric | Value |
|--------|-------|
| Total tables analyzed | 154 |
| Core tables exported | 11 |
| Total export size | 209 MB |
| Critical issues | 2 |
| Medium issues | 2 |
| Data integrity score | **85/100** |

---

*Report generated automatically. Review recommendations with data owner before implementing changes.*
