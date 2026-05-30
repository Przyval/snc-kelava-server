# Re-Audit terhadap Jadwal Teknisi Juni 2026

**Source**: `06. JADWAL TEKNISI JUNI 2026.xlsx`
**Date**: 2026-05-30
**Status**: ⚠️ **BLOCKER** — system tidak siap auto-generate June. Coverage hanya 11%.

---

## TL;DR

| Metric | Value | Verdict |
|---|---|---|
| June visits dalam xlsx | 746 | — |
| Resolved ke `snc_clients` | 712 (95%) | OK |
| **Covered by active rule** | **80 (11.2%)** | ❌ **BLOCKER** |
| Customers tanpa rule | 198 | ❌ Gap massive |
| High-conf May patterns belum dipromote | **176** | 🎯 Quick win |
| Tech mismatch / inactive | 4 issues | ⚠️ Fix sebelum deploy |
| Customer missing dari snc_clients | 7 real | ⚠️ Add ke master |
| Holiday gap | 0 critical | ✓ OK |

**Conclusion**: Jangan apply rule-based draft untuk June dulu. Jalankan **bulk-promote 176 high-confidence patterns** ke recurring rules, baru re-generate draft. Estimated coverage setelah itu: **~75-85%** (sesuai target PRD).

---

## A. Tech Roster Issues

| XLSX Sheet | Match | snc_tech | Status | Action |
|---|---|---|---|---|
| ADAM | ✓ | id=5 Adam Abdillah | active | OK |
| AKBAR R | ✓ | id=1 Akbar Rohmatulah | active | OK |
| ALMAS | ✓ | id=4 Ananda Almas | active | OK |
| ANAM | ✓ | id=2 Choirul Anam | active | OK |
| ABU S | ✓ | id=3 M. Abu Samsudin | active | OK |
| ANDIK | ✓ | id=7 Andik N. Fananiar | active | OK |
| LUCKY | ✓ | id=8 Lucky Adi Putra | active | OK |
| MAHRUS | ✓ | id=6 Moh. Mahrus | active | OK |
| MAULANA | ✓ | id=9 Moch Maulana | active | OK |
| ARGA | ✓ | id=13 Argantara | station | OK |
| FATHUR | ✓ | id=51 Fathur Rozek | support | OK |
| RENDY | ✓ | id=14 I Wayan Rendy | active | OK |
| **IMAM** | ✓ | id=12 Nur Imam Siswo Utomo | **INACTIVE** | Reactivate atau reassign 2 visit |
| **RANGGA** | ✓ | id=10 Rangga | **INACTIVE** | Reactivate (23 visit assigned!) |
| **IRUL** | ❌ | (false-matched ke Choirul Anam by substring) | ??? | Klarifikasi — Irul nickname siapa? Kemungkinan tech baru |
| **MULYASARI** | ❌ | unmatched | ??? | Add ke snc_technicians |
| **PM Jogja** | ❌ | unmatched | bukan tech | Branch label, skip atau add sebagai location-based assignment |
| **PM SOLO** | ❌ | unmatched | bukan tech | Same as PM Jogja |

**Actions sebelum deploy June**:
1. UPDATE `snc_technicians` SET is_active=true WHERE id IN (10, 12) — atau konfirmasi reassign
2. INSERT `snc_technicians` (name='Mulyasari', employee_type='mobile', is_active=true)
3. Klarifikasi siapa IRUL — bisa jadi tech baru atau nickname Choirul Anam (Anam = "Anam Choirul" / "Irul Choirul"?)
4. PM Jogja/SOLO = branch tag; bukan tech individual → either skip atau buat 2 tech khusus regional

---

## B. Customer Master Data Gaps

| XLSX Name | Status |
|---|---|
| G. PAKUWON | Missing — possibly "GENESIS PAKUWON" or similar |
| ISTANA D | Missing — Istana Daun? |
| JOY LEARNING | Missing — daycare/sekolah |
| JP | Ambiguous (could be abbreviation) |
| OFFICE HCI | Missing — internal office? |
| PAK RONNY | Missing — personal name |
| PT.SURYA T.L | Missing — "PT Surya T.L"? |
| VOILA21 | Missing — likely a venue |
| OFFICE SNC | NOT customer (internal team) — skip |
| SNC TEAM | NOT customer (internal) — skip |
| KETERANGAN / Keterangan: | NOT customer (note row) — skip |
| Penanggung Jawab | NOT customer (signature row) — skip |
| CUTI | NOT customer (leave marker) — skip |

**Actions**: 7 real customers perlu di-add ke `snc_clients` (semua via lokasi/customer UI, atau bulk SQL insert).

---

## C. Coverage Gap — Critical

**11.2% rule coverage** = 89% of June schedule akan tetap manual.

Top 10 customers visited tapi tanpa rule:

| Visits | Customer |
|---|---|
| 71 | **Tanamera Coffee & Roastery Trans Icon Mall** — daily routine? |
| 23 | ACAII TP |
| 12 | GRAHA PADEL |
| 12 | EL GRANDE |
| 10 | CIKAL |
| 9 | NICi PM 2 G |
| 8 | PLATINUM PADEL |
| 7 | ALMA |
| 7 | HOME GROUND PADEL |
| 6 | EUROCHAIR |

→ 198 unique customers visited June tanpa rule.

### Pattern-promotion quick win

```sql
-- Already in pattern table dari deteksi May:
patterns source_month=2026-05  → 505 patterns, 357 unique clients
clients with confidence >= 0.85: 160
clients with confidence >= 0.60: 197
clients NOT YET covered by rule (≥0.6): 176
```

**Action**: Run bulk-promote dengan filter `confidence >= 0.85`. Expected: +160 rules ditambahkan otomatis = ~80% coverage target tercapai.

Endpoint sudah tersedia: `POST /api/v1/enterprise/recurring-rules/bulk-import` dengan payload dari derive output. Bisa juga buat script `kil/backend/scripts/bulk_promote_patterns.py`.

---

## D. Holiday Coverage

| Date | Holiday | In DB | Visits scheduled |
|---|---|---|---|
| 2026-06-01 (Sen) | Hari Lahir Pancasila | ✓ | **13 visits** — supervisor sengaja kerja libur, atau xlsx tidak respect holiday |
| 2026-06-16 (Sel) | Tahun Baru Islam 1448H | ✓ | **14 visits** — sama |

Note: Idul Adha 1447H jatuh 2026-05-27 (Rabu), bukan Juni. Tidak ada gap holiday Juni.

**Action**: Klarifikasi ke koordinator — apakah 13+14 visits di hari libur memang disengaja (commercial tetap buka)? Kalau ya, set `suppress_holiday=false` per rule. Kalau tidak, conflict_detection akan flag mereka sebagai `holiday_exception`.

---

## E. Recommended Execution Order

### Phase 1 — Data prep (1-2 hari)
1. **Reactivate** `snc_technicians` id 10 (Rangga), id 12 (Imam) — atau reassign 25 visits ke mobile pool
2. **Add** 1 tech (Mulyasari) + klarifikasi IRUL
3. **Add** 7 missing customers ke `snc_clients`
4. Decide PM Jogja/SOLO handling (likely separate region label)

### Phase 2 — Rule bootstrapping (script-driven)
5. Write `kil/backend/scripts/bulk_promote_patterns.py`:
   - Loop semua `snc_schedule_patterns` source_month='2026-05' confidence >= 0.85
   - Call `/recurring-rules/derive/<client_id>` → accept as soft rule
   - Skip clients yang sudah punya active rule
   - Target: +160 rules
6. Verify total active rules ≈ 180

### Phase 3 — Generate June draft (UI-driven)
7. Buka `/enterprise/schedule-draft-calendar` → set target_month=2026-06
8. Click "Generate Draft" → backend pakai rules + cadence projection
9. Review conflict panel, fix via Backup → Move Time → Mark Exception
10. Approve clean days → Publish

### Phase 4 — Reconcile vs xlsx (validation)
11. Compare generated draft vs xlsx June actuals
12. Target recall ≥ 78% (PRD goal)
13. Document remaining mismatches as data quality issues

---

## F. Risk Register

| Risk | Mitigation |
|---|---|
| Bulk-promote pollutes ruleset with low-quality patterns | Hard cutoff confidence≥0.85; supervisor can deactivate via UI |
| Reactivating Rangga/Imam masks an HR decision | Confirm dengan HR sebelum SET is_active=true |
| Tanamera (71 visits) butuh complex multi-rule | May need 2 rules per week, biweekly Sat, etc. |
| IRUL false-match merusak pattern history | Fix nickname mapping di `snc_technicians.aliases` (perlu kolom baru) |

---

## G. Tools / Helper Scripts To Build

- [ ] `kil/backend/scripts/bulk_promote_patterns.py` — auto-create rules from high-conf patterns
- [ ] `kil/backend/scripts/import_juni_actuals.py` — load xlsx visits as "ground truth" for recall measurement
- [ ] `kil/backend/scripts/reconcile_draft_vs_actuals.py` — compute recall % after each draft gen

These would close the loop: Pattern → Rule → Draft → Compare-to-Actuals.
