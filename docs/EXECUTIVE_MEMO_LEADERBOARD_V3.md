# 📋 EXECUTIVE MEMO: Technician Leaderboard V3

> **To:** Management / Direksi  
> **From:** Data Analytics Team  
> **Date:** 2026-01-10  
> **Subject:** Persetujuan Implementasi Technician Leaderboard  
> **Status:** ✅ LAYAK PRODUKSI (dengan guardrails)

---

## 1. Executive Summary

**Technician Leaderboard** adalah sistem skor 0–100 untuk mengukur performa teknisi lapangan secara **adil, transparan, dan audit-able**.

| Keputusan | Status |
|-----------|--------|
| Data quality | ✅ Tervalidasi |
| Formula scoring | ✅ Disetujui |
| Guardrails | ✅ Ditetapkan |
| **Rekomendasi** | **GO untuk Pilot** |

---

## 2. Scoring Formula (V3 Final)

```
Score = 35% Completion + 20% Schedule Discipline + 25% Productivity + 10% Duration + 10% Photo
```

| Komponen | Bobot | Definisi | Rata-rata |
|----------|-------|----------|-----------|
| **Completion Rate** | 35% | Penugasan selesai | 99.5% |
| **Schedule Discipline** | 20% | Dikerjakan di hari yang dijadwalkan | 82.3% |
| **Productivity** | 25% | Visits per day worked | 2.4 |
| **Duration Efficiency** | 10% | Median durasi dalam range optimal | 105 min |
| **Photo Compliance** | 10% | % penugasan dengan foto bukti | 90.1% |

---

## 3. Top 5 Performers

| Rank | Nama | Score | Kekuatan Utama |
|------|------|-------|----------------|
| 1 | Andik Noroyan F. | **97.7** | Schedule 94%, Foto 89% |
| 2 | Akbar Rohmatulah | **96.2** | Completion 100%, VPD tinggi |
| 3 | Ananda Almas | **95.5** | Foto 99%, Schedule 89% |
| 4 | Choirul Anam | **95.2** | VPD tertinggi (3.54) |
| 5 | Moh. Mahrus | **94.7** | Balanced semua metrik |

**Distribusi Grade:**
- Grade A (≥85): **13 teknisi**
- Grade B (75-84): **7 teknisi**
- Grade C/D: sisanya

---

## 4. ⚠️ Guardrails (Wajib Sebelum Go-Live)

### 4.1 Off-Hours Scheduling

**Temuan:** Beberapa teknisi memiliki >60% jadwal di luar jam kerja (18:00-08:00).

| Teknisi | Off-Hours % | Catatan |
|---------|-------------|---------|
| Dicky Darmawan | 68.8% | Perlu investigasi |
| Mahesa Ramadhan | 68.8% | Perlu investigasi |
| Dwi Santoso | 65.5% | Perlu investigasi |

**Kebijakan yang direkomendasikan:**
- Tag jadwal sebagai `business_hours` vs `off_hours`
- Default leaderboard hanya `business_hours`
- Off-hours dipantau 1-2 bulan sebelum dimasukkan scoring

### 4.2 Minimum Sample Size

- **Qualify untuk ranking:** `total_assigned >= 20`
- Di bawah threshold: tampilkan "Data Insufficient"

### 4.3 Duration Edge Cases

- **< 5 menit:** Exclude dari durasi (gaming suspect)
- **> 480 menit:** Cap at 480 (checkout hygiene issue)
- Tetap dihitung completion jika check_out ada

### 4.4 Dual Score Track

- `score_raw`: Internal untuk audit & debug
- `score_public`: Yang dipublikasikan

---

## 5. Pilot Mode (Direkomendasikan)

| Minggu | Aksi | Tujuan |
|--------|------|--------|
| **Week 1** | Publish ke Supervisor saja | Kalibrasi & feedback |
| **Week 2** | Publish ke Teknisi + FAQ | Edukasi & penerimaan |
| **Week 3+** | Pakai untuk keputusan | Reward/coaching berbasis data |

> **Prinsip:** Pilot untuk kalibrasi, bukan mengadili.

---

## 6. Key Insights untuk Direksi

### Insight 1: Schedule Discipline = Isu Operasional Nyata

Jadwal tervalidasi memiliki jam (bukan midnight). Artinya ketidakpatuhan jadwal adalah **masalah operasional**, bukan kesalahan data.

**Implikasi:** Perbaiki sistem scheduling/komunikasi, bukan menghukum teknisi.

### Insight 2: Durasi Mentah Menipu

| Statistik | Nilai |
|-----------|-------|
| Average | 1,539 menit |
| **Median (p50)** | **169 menit** |
| p90 | 1,457 menit |

Long-tail distortion karena lupa check-out. Solusi: pakai median.

### Insight 3: Foto = Aset Budaya Kualitas

- Coverage: 84%
- Rata-rata: 17 foto/visit
- Ini bukti kerja yang **sulit dimanipulasi**

---

## 7. Request for Approval

☐ Setuju implementasi Pilot (2 minggu)  
☐ Setuju guardrails di atas  
☐ Catatan/modifikasi: _______________

**Signature:** _______________  
**Date:** _______________

---

## Lampiran

1. [Data Quality Validation Report](./DATA_QUALITY_VALIDATION_REPORT.md)
2. [Technical Specification V3](./TECHNICIAN_LEADERBOARD_SPEC_V2.md)
3. [Dashboard Production](./TECHNICIAN_LEADERBOARD_V3_PRODUCTION.html)
