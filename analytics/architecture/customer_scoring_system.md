# Cara Sistem Menilai Customer (Safe & Care Ops)

## Tujuan
Sistem menilai customer untuk:
1. Menentukan **prioritas kerja hari ini** (P0–P3)
2. Menentukan **siapa owner** (Ops / Supervisor / Sales/CS)
3. Memberi **Suggested Action** yang konsisten dan bisa diaudit.

---

## A. Dua Layer Penilaian

### 1) Account Status (Relasi Kontrak & Risiko Operasional)
Account Status menjawab: **"Secara kontrak & SLA, posisi customer ini di mana?"**

*   **UNDER_SLA**: Kontrak aktif dan tidak telat terhadap jadwal layanan.
*   **AT_RISK**: Kontrak aktif tapi telat (recency_ratio > 1.0) / ada komplain terbuka.
*   **INACTIVE**: Tidak ada kontrak aktif dan belum masuk kategori dormant (masih baru/churn baru).
*   **DORMANT**: Tidak ada kontrak aktif dan tidak ada visit ≥ 60 hari.

### 2) RFM Segment (Nilai & Perilaku Bisnis)
RFM menjawab: **"Customer ini penting/berisiko dari sisi bisnis?"**
RFM dihitung sebagai R, F, M (skor 1–5).

#### R (Recency) = Kedisiplinan terhadap cycle
*   **Hitungan**: `recency_ratio = days_since_last_visit / expected_cycle_days`
*   **Skor**:
    *   ≤1.0 → R=5 (On-Time)
    *   1.0–1.5 → R=4
    *   1.5–2.0 → R=3
    *   2.0–3.0 → R=2
    *   > 3.0 → R=1 (Critical/Dormant)

#### F (Frequency) = Beban & dampak operasional
*   **Weekly** = 5
*   **Monthly** = 3
*   **Quarterly** = 2
*   **Ad-hoc** = 1

#### M (Monetary / Economic Weight) = Mahal kalau gagal
*   Gabungan nilai kontrak + kompleksitas layanan.
*   Skor 1–5 (5 = High Value / Complex Site like Factory/Hotel).

---

## B. Segment Operasional (Bahasa Kerja)
Sistem tidak menampilkan "Champion/Loyal", tetapi segment operasional:

*   **REVENUE_CORE**: R≥4, F≥4, M≥4 (High Value, High Frequency, On Track)
*   **STABLE_CORE**: R≥3, F≥3, M≥3 (Mid Value, On Track)
*   **REVENUE_RISK**: R≤2 dan M≥4 (High Value but Slipping/Dormant)
*   **GROWTH**: R≥3, F≤2, M≥3 (Good Recency, Low Frequency -> Upsell Candidate)
*   **LOW_VALUE**: M≤2 dan F≤2
*   **CHURNED**: R=1, F=1, M≤2

---

## C. Priority (P0–P3) dan "Suggested Action"
Priority ditentukan dari kombinasi **Account Status × Segment**, contoh:

### **P0 (CRITICAL)**
*   **Trigger**:
    *   Komplain terbuka pada segmen bernilai tinggi (Revenue Core/Risk).
    *   `AT_RISK` + `Revenue Core` + `missed_cycles ≥ 1`.
*   **Owner**: Ops Supervisor
*   **Action**: `🧯 Handle complaint` / `📞 Supervisor follow-up`

### **P1 (IMPORTANT)**
*   **Trigger**:
    *   `UNDER_SLA` + `Revenue Core` (Preventive Protection).
    *   `DORMANT` + `Revenue Risk` (Winback High Value).
*   **Owner**: Ops / Sales-CS
*   **Action**: `🛡️ Monitor SLA` / `↻ Winback call`

### **P2 (NORMAL)**
*   **Trigger**:
    *   Growth candidate (upsell).
    *   Standard operational visits.
*   **Owner**: Sales / Ops
*   **Action**: `💡 Offer Contract` / `📅 Schedule Visit`

### **P3 (BATCH ONLY)**
*   **Trigger**:
    *   Low value / churned dormant.
*   **Owner**: System
*   **Action**: `📦 Batch campaign only`

---

## D. Audit Trail
Setiap perubahan status/action dicatat sebagai event:
*   Siapa yang klik
*   Kapan
*   Rule apa yang memicu
*   Alasan sistem

Tujuan audit: Supervisor tidak bisa "tidak tahu", dan keputusan bisa dipertanggungjawabkan.
