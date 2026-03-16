# 📋 KPI Contract - SanoCare Technician Performance

> **Version:** 1.1  
> **Created:** 2026-01-13  
> **Updated:** 2026-01-13 (4 critical patches)  
> **Status:** ✅ ACTIVE  
> **Owner:** Analytics Team

---

## 🎯 Purpose

Dokumen ini mendefinisikan **kontrak metrik** untuk KPI teknisi SanoCare. Semua pihak (Ops, HR, Management) harus menyepakati definisi ini **sebelum** perhitungan dilakukan untuk menghindari perdebatan interpretasi.

---

## 1. Unit Analisis Utama

| Parameter | Definisi |
|-----------|----------|
| **Primary Key** | `t_road_plan.id` (road_plan_id) |
| **Grain** | 1 baris = 1 kunjungan terjadwal |
| **Relasi Visit** | `t_road_plan.id` → `t_visit.id_road_plan` (0..N) |

```
┌─────────────────┐     0..N     ┌─────────────────┐
│   t_road_plan   │─────────────▶│     t_visit     │
│  (jadwal)       │              │  (realisasi)    │
└─────────────────┘              └─────────────────┘
         │
         │ 1:N
         ▼
┌─────────────────┐
│ t_road_plan_area│
│ t_road_plan_foto│
└─────────────────┘
```

> [!IMPORTANT]
> **Relasi 0..N Explanation:**
> - **0** = Road plan ada, tapi visit belum/tidak pernah terjadi
> - **1** = Normal case (1 jadwal = 1 realisasi)
> - **N** = Multiple attempts untuk 1 road_plan (re-visit, retry)
>
> **Resolution Rule untuk N > 1:**
> ```sql
> -- Jika visit_count > 1 untuk 1 road_plan:
> -- • check_in  = MIN(check_in)   -- earliest attempt
> -- • check_out = MAX(check_out)  -- latest completion
> -- • visit_count disimpan sebagai flag untuk anomaly detection
> ```

---

## 2. Tanggal Acuan KPI

### 2.1 Tanggal Jadwal (Scheduled Date)

| Field | Table | Deskripsi |
|-------|-------|-----------|
| `visit_date` | `t_road_plan` | Tanggal yang dijadwalkan untuk kunjungan |

**Usage:** Untuk menghitung **ketepatan jadwal** dan **scheduling compliance**.

### 2.2 Tanggal Realisasi (Actual Date)

| Field | Table | Deskripsi | Prioritas |
|-------|-------|-----------|-----------|
| `check_in` | `t_visit` | Timestamp masuk lokasi | **PRIMARY** ✅ |
| `realization_date` | `t_visit` | Tanggal realisasi (derived) | Secondary |

**Keputusan:** Gunakan `t_visit.check_in` sebagai sumber kebenaran untuk waktu realisasi.

**Justifikasi dari Data:**
- 99.99% visits memiliki `check_in` (33,719 dari 33,720)
- `realization_date` hanya ada pada visits yang sudah `Selesai` (33,510)
- `check_in` lebih granular (timestamp vs date)

---

## 3. Status Kunjungan

### 3.1 Status Mapping (`t_road_plan.status`)

| Status DB | Label | KPI Eligible | Count | Pct |
|-----------|-------|--------------|-------|-----|
| `Selesai` | ✅ Selesai | **YES** | 33,510 | 99.36% |
| `Berjalan` | 🔄 Dalam Proses | NO | 209 | 0.62% |
| `Requested` | 📝 Diminta | NO | 4 | 0.01% |
| `Baru` | 🆕 Baru | NO | 3 | 0.01% |

**Rule:** Hanya status `Selesai` yang dihitung dalam KPI.

### 3.2 Tipe Kunjungan (`t_road_plan.type`)

| Type | Label | Segment | Count |
|------|-------|---------|-------|
| `t_mobile` | Mobile Technician | MOBILE | 20,680 |
| `t_station` | Station Technician | STATION | 8,188 |
| `checklist` | Checklist | SUPPORT | 2,767 |
| `spv_tc` | Supervisor TC | SUPERVISOR | 1,864 |
| `spv_qc` | Supervisor QC | SUPERVISOR | 223 |
| _(empty)_ | Unknown | EXCLUDE | 4 |

**Rule:** 
- KPI utama hitung terpisah untuk **MOBILE** dan **STATION**
- Tipe `checklist`, `spv_tc`, `spv_qc` memiliki KPI terpisah

---

## 4. Working Hours Definition

### 4.1 Hari Kerja

| Parameter | Definisi |
|-----------|----------|
| **Hari Kerja** | Senin – Sabtu |
| **Hari Libur** | Minggu |
| **Catatan** | Libur nasional belum di-exclude (phase 2) |

**Data Validasi:**
```
Senin:  5,893 visits
Selasa: 5,469 visits
Rabu:   5,320 visits
Kamis:  5,331 visits
Jumat:  5,301 visits
Sabtu:  4,493 visits
Minggu: 1,912 visits ← Ada aktivitas, tapi minoritas
```

### 4.2 Jam Kerja

| Parameter | Definisi |
|-----------|----------|
| **Jam Kerja Standar** | 08:00 – 17:00 WIB |
| **Toleransi Check-in** | ± 30 menit |
| **Early Check-in** | Valid mulai 07:30 WIB |
| **Late Check-in** | Flagged jika > 08:30 WIB (untuk visit pertama hari itu) |

### 4.3 On-Time Rate: Definisi Operasional 🕐

> [!IMPORTANT]
> **On-Time hanya berlaku untuk FIRST VISIT of the day per teknisi.**
> Visit ke-2, ke-3, dst tidak dihitung untuk on-time KPI.

**Implementasi Step-by-Step:**

```sql
-- Step 1: Tentukan visit_day per check_in
visit_day = DATE(check_in AT TIME ZONE 'Asia/Jakarta')

-- Step 2: Identify first visit per (user_id, visit_day)
WITH ranked_visits AS (
    SELECT 
        v.*,
        ROW_NUMBER() OVER (
            PARTITION BY v.id_user, DATE(v.check_in AT TIME ZONE 'Asia/Jakarta')
            ORDER BY v.check_in ASC
        ) as visit_rank_of_day
    FROM t_visit v
)
SELECT * FROM ranked_visits WHERE visit_rank_of_day = 1

-- Step 3: Calculate is_on_time for first visit only
is_first_visit_on_time = CASE
    WHEN visit_rank_of_day = 1 
         AND EXTRACT(HOUR FROM check_in AT TIME ZONE 'Asia/Jakarta') * 60 
            + EXTRACT(MINUTE FROM check_in AT TIME ZONE 'Asia/Jakarta')
            BETWEEN 450 AND 510  -- 07:30 (450 min) to 08:30 (510 min)
    THEN TRUE
    ELSE FALSE
END
```

**On-Time Window:**
| Waktu | Status |
|-------|--------|
| < 07:30 | ⚠️ Too Early (valid tapi tidak ideal) |
| 07:30 - 08:30 | ✅ ON TIME |
| > 08:30 | ❌ LATE |

**Data Validasi (Check-in by Hour):**
```
06:00-06:59:  1,167 ← Early birds
07:00-07:59:  3,105 ← Normal start
08:00-08:59:  2,264 
09:00-09:59:  2,768
...
21:00-21:59:  3,269 ← Anomali tinggi (perlu investigasi)
```

> [!WARNING]
> Ada anomali check-in jam 21:00-23:00 yang tinggi. Kemungkinan:
> - Data entry di akhir hari
> - Kunjungan malam untuk customer tertentu
> - Bug aplikasi
> 
> **Action:** Flag untuk data quality review di Step 2.

---

## 5. Duration Definition

### 5.1 Formula

```sql
duration_minutes = EXTRACT(EPOCH FROM (check_out - check_in)) / 60
```

### 5.2 Duration Validity Traffic Light 🚦

| Status | Condition | Action | Color |
|--------|-----------|--------|-------|
| **VALID** | 5 ≤ duration ≤ 480 | ✅ Include in KPI | 🟢 Green |
| **WARNING** | duration = 0 | ⚠️ Flag, include with note | 🟡 Yellow |
| **WARNING** | 0 < duration < 5 | ⚠️ Flag, include with note | 🟡 Yellow |
| **WARNING** | 480 < duration ≤ 600 | ⚠️ Flag, include with note | 🟡 Yellow |
| **SUSPECT** | duration > 600 | 🚨 Exclude from KPI, review | 🔴 Red |
| **SUSPECT** | duration < 0 | 🚨 Exclude (data error) | 🔴 Red |
| **SUSPECT** | check_out IS NULL | 🚨 Exclude (incomplete) | 🔴 Red |

```sql
-- Duration Status Implementation
duration_status = CASE
    WHEN check_out IS NULL THEN 'SUSPECT_NO_CHECKOUT'
    WHEN duration_min < 0 THEN 'SUSPECT_NEGATIVE'
    WHEN duration_min > 600 THEN 'SUSPECT_OVERNIGHT'
    WHEN duration_min = 0 THEN 'WARNING_ZERO'
    WHEN duration_min < 5 THEN 'WARNING_TOO_SHORT'
    WHEN duration_min > 480 THEN 'WARNING_LONG'
    ELSE 'VALID'
END
```

### 5.3 Duration Distribution (dari data aktual)

| Bucket | Range (menit) | Count | Status |
|--------|---------------|-------|--------|
| Instant | 0 | - | 🟡 WARNING |
| Very Short | 1-4 | - | 🟡 WARNING |
| Short | 5-50 | 5,451 | 🟢 VALID |
| Normal | 50-200 | 12,511 | 🟢 VALID |
| Long | 200-480 | 5,506 | 🟢 VALID |
| Extended | 481-600 | 6,038 | 🟡 WARNING |
| Overnight | >600 | 2,188 | 🔴 SUSPECT |

---

## 6. Evidence Requirements

### 6.1 Photo Evidence (`t_road_plan_foto`)

| Parameter | V1 Threshold | Future |
|-----------|--------------|--------|
| **Minimum foto per visit** | **≥ 1 foto** | Dinaikkan per kontrak |
| **Typical range** | 7-20 foto | - |

> [!IMPORTANT]
> **WAJIB: LEFT JOIN untuk Photo Count**
> 
> Stats "Min: 1 foto" bisa menipu jika query hanya INNER JOIN (road_plan yang punya foto).
> Untuk compliance yang akurat, **HARUS** pakai LEFT JOIN:
> ```sql
> SELECT 
>     rp.id,
>     COALESCE(f.foto_count, 0) as foto_count  -- 0 jika tidak ada foto!
> FROM t_road_plan rp
> LEFT JOIN (
>     SELECT id_road_plan, COUNT(*) as foto_count
>     FROM t_road_plan_foto
>     GROUP BY id_road_plan
> ) f ON rp.id = f.id_road_plan
> ```

**Data Validasi (untuk road_plan yang PUNYA foto):**
```
Photo Statistics per Road Plan:
- Min:    1 foto
- P25:    7 foto
- Median: 12 foto
- P75:    20 foto
- Max:    204 foto
```

### 6.2 Photo Compliance Flag

```sql
-- HARUS pakai COALESCE untuk handle NULL!
photo_compliance = CASE 
    WHEN COALESCE(foto_count, 0) >= 1 THEN 'COMPLIANT'
    ELSE 'NON-COMPLIANT'
END

-- Jangan pernah:
-- WHEN foto_count >= 1  -- ini akan MISS road_plan tanpa foto!
```

### 6.3 Future Enhancement (V2)

| Customer Type | Min Photos Required |
|---------------|---------------------|
| Rumah | 3 |
| Resto/Café | 5 |
| Hotel | 10 |
| Industri | 15 |

---

## 7. KPI Metrics Summary

### 7.1 Core KPIs (V1)

| # | KPI Name | Formula | Weight |
|---|----------|---------|--------|
| 1 | **Completion Rate** | `completed_visits / scheduled_visits × 100%` | 25% |
| 2 | **On-Time Rate** | `on_time_visits / completed_visits × 100%` | 20% |
| 3 | **Duration Compliance** | `valid_duration_visits / completed_visits × 100%` | 15% |
| 4 | **Photo Compliance** | `visits_with_photos / completed_visits × 100%` | 15% |
| 5 | **Productivity** | `completed_visits / working_days` | 25% |

### 7.2 Derived Metrics

| Metric | Formula |
|--------|---------|
| **Avg Duration** | `SUM(duration_min) / COUNT(visits)` |
| **Visits per Day** | `COUNT(visits) / COUNT(DISTINCT working_days)` |
| **Coverage** | `COUNT(DISTINCT customers_visited) / total_customers` |

---

## 8. Grading Scale (Preview)

| Grade | Score Range | Label |
|-------|-------------|-------|
| A | 90-100 | Excellent |
| B | 75-89 | Good |
| C | 60-74 | Satisfactory |
| D | 40-59 | Needs Improvement |
| F | < 40 | Unsatisfactory |

*Detail grading formula akan didefinisikan di Step 3.*

---

## 9. Data Quality Flags

Setiap record akan mendapat flag untuk data quality:

```sql
-- DQ Flags (bitmask or separate columns)
is_valid_duration    -- duration between 5-480 min
is_valid_checkin     -- checkin within working hours
is_valid_checkout    -- checkout exists and after checkin  
is_photo_compliant   -- foto_count >= 1
is_working_day       -- not Sunday
is_complete          -- status = 'Selesai'
```

---

## 10. Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-13 | Initial contract based on live data analysis |
| 1.1 | 2026-01-13 | **4 Critical Patches:** (1) Fixed 0..N relationship with resolution rules, (2) Photo compliance LEFT JOIN + COALESCE, (3) Duration traffic light 🚦, (4) On-time operational definition |

---

## ✅ Sign-Off

```
[ ] Operations Manager    Date: ___________
[ ] HR Manager            Date: ___________
[ ] IT/Data Team          Date: ___________
```

---

*Document generated by Runbook Agent - Step 1.1*
