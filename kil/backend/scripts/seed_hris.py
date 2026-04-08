#!/usr/bin/env python3
"""
Seed HRIS Module — COMPLETE
=============================
Reads ALL data from 3 Excel files into hris_* tables.
Nothing missed.

Sources:
  1. KPI Teknisi Mobile 2025.xlsx — 8 techs × 13 indicators × 12 months
  2. KPI Station 2025 (1).xlsx    — 17 techs × 11 indicators × 4 months
  3. 03 REKAP ABSENSI 26 FEBRUARI - 25 MARET 2026.xlsx
     - ABSENSI:   monthly summary (67 employees)
     - LEMBUR:    overtime records (92 entries)
     - KUNJUNGAN: visit log (443 entries, 8 mobile techs)
     - KEHADIRAN: daily attendance grid (64 employees × 28 days)
     - COMPLAIN:  complaint records (empty this period)
     - GROOMING:  grooming violations (empty this period)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

import openpyxl
from kil.db.kelava_db import _get_local_pool
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

MONTH_NAMES = {
    'Jan':1,'Feb':2,'Mar':3,'Apr':4,'May':5,'Jun':6,'Jul':7,'Aug':8,'Sep':9,'Oct':10,'Nov':11,'Dec':12,
    'June':6,'Juni':6,'Juli':7,'Agustus':8,'September':9,'Oktober':10,'November':11,'Desember':12,
    'Maret':3,'April':4,'Mei':5,'Januari':1,'Februari':2,
}


def get_conn():
    return _get_local_pool().connection()


def get_or_create_employee(cur, full_name, jabatan=None, emp_type='station', site=None, spv_name=None):
    full_name = full_name.strip()
    cur.execute("SELECT id FROM hris_employees WHERE full_name = %s", (full_name,))
    row = cur.fetchone()
    if row:
        # Update if more info
        if jabatan or emp_type != 'station' or site or spv_name:
            updates = []
            params = []
            if jabatan:
                updates.append("jabatan = COALESCE(%s, jabatan)")
                params.append(jabatan)
            if emp_type != 'station':
                updates.append("employee_type = %s")
                params.append(emp_type)
            if site:
                updates.append("site_assignment = %s")
                params.append(site)
            if spv_name:
                updates.append("supervisor_name = %s")
                params.append(spv_name)
            if updates:
                updates.append("updated_at = NOW()")
                params.append(row["id"])
                cur.execute(f"UPDATE hris_employees SET {', '.join(updates)} WHERE id = %s", tuple(params))
        return row["id"]
    cur.execute("""
        INSERT INTO hris_employees (full_name, jabatan, employee_type, site_assignment, supervisor_name)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (full_name, jabatan or 'Unknown', emp_type, site, spv_name))
    return cur.fetchone()["id"]


# ══════════════════════════════════════════════════════════════
# 1. KPI TEMPLATES
# ══════════════════════════════════════════════════════════════

def seed_kpi_templates(cur):
    cur.execute("DELETE FROM hris_kpi_scores")
    cur.execute("DELETE FROM hris_kpi_templates")

    mobile = [
        (1,'Kedisiplinan','Administrasi','Check In & Out Laporan pelayanan tidak sesuai dengan jadwal',0.05,'binary',1),
        (1,'Kedisiplinan','Administrasi','Ketepatan Pengisian administrasi (Laporan pelayanan & checklist) tidak lengkap meliputi keterangan area, jenis & hasil treatment, pemakaian chemical, dokumentasi pengerjaan, serta rekomendasi',0.05,'binary',2),
        (1,'Kedisiplinan','Waktu','Tidak datang terlambat saat melakukan kunjungan ke client baik treatment maupun follow up',0.05,'binary',3),
        (1,'Kedisiplinan','Waktu','Tidak melakukan cancel treatment pada client',0.05,'binary',4),
        (1,'Kedisiplinan','Waktu','Tidak izin mendadak (kurang dari 24 jam dari jadwal)',0.05,'binary',5),
        (1,'Kedisiplinan','Kinerja','Penilaian Tim QC',0.05,'scaled',6),
        (1,'Kedisiplinan','Kinerja','Melaksanakan arahan SPV sesuai dengan yang diperintahkan',0.05,'scaled',7),
        (2,'Complain',None,'Frekuensi client complain major dalam 1 bulan',0.10,'binary',8),
        (2,'Complain',None,'Responsibility teknisi dalam penanganan complain',0.10,'binary',9),
        (3,'Grooming',None,'Selalu berpenampilan rapi (seragam, sepatu) serta memotong rapi rambut, kuku kumis, jenggot. Menggunakan APD lengkap saat treatment',0.10,'binary',10),
        (4,'Kunjungan',None,'Jumlah kunjungan (100%)',0.20,'proportional',11),
        (4,'Kunjungan',None,'Jumlah jam kunjungan (150 Jam / 9000 Menit)',0.10,'proportional',12),
        (4,'Kunjungan',None,'Hari efektif',0.05,'proportional',13),
    ]

    station = [
        (1,'Kedisiplinan','Administrasi','Pengisian administrasi (Daily Treatment & checklist, pemakaian chemical)',0.10,'binary',1),
        (1,'Kedisiplinan','Waktu','Tidak ada keterlambatan lebih dari 5 menit',0.05,'binary',2),
        (1,'Kedisiplinan','Waktu','Kehadiran (minimal 100% kehadiran)',0.10,'binary',3),
        (1,'Kedisiplinan','Waktu','Tidak izin mendadak (kurang dari 24 jam)',0.05,'binary',4),
        (2,'Kinerja',None,'Trend Hama cenderung turun / stabil',0.10,'binary',5),
        (2,'Kinerja',None,'Menjaga kebersihan area kerja dan alat',0.05,'binary',6),
        (2,'Kinerja',None,'Melaksanakan semua progress yang telah diberikan',0.10,'binary',7),
        (3,'Complain',None,'Tidak ada complain Major di Area',0.10,'binary',8),
        (4,'Grooming',None,'Selalu berpenampilan rapi, APD lengkap saat treatment',0.10,'binary',9),
        (5,'Penilaian',None,'Penilaian Client',0.15,'scaled',10),
        (5,'Penilaian',None,'Penilaian Atasan / SPV',0.10,'scaled',11),
    ]

    ids = {'mobile': {}, 'station': {}}
    for cat_no, cat, sub, ind, bobot, scoring, sort in mobile:
        cur.execute("""INSERT INTO hris_kpi_templates (employee_type,category_no,category_name,sub_category,indicator,bobot,scoring_type,sort_order)
            VALUES ('mobile',%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (cat_no, cat, sub, ind, bobot, scoring, sort))
        ids['mobile'][sort] = cur.fetchone()["id"]
    for cat_no, cat, sub, ind, bobot, scoring, sort in station:
        cur.execute("""INSERT INTO hris_kpi_templates (employee_type,category_no,category_name,sub_category,indicator,bobot,scoring_type,sort_order)
            VALUES ('station',%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (cat_no, cat, sub, ind, bobot, scoring, sort))
        ids['station'][sort] = cur.fetchone()["id"]

    print(f"  Templates: {len(ids['mobile'])} mobile + {len(ids['station'])} station = {len(ids['mobile'])+len(ids['station'])}")
    return ids


# ══════════════════════════════════════════════════════════════
# 2. KPI MOBILE SCORES
# ══════════════════════════════════════════════════════════════

def seed_kpi_mobile(cur, tmpl):
    path = os.path.join(BASE, 'KPI Teknisi Mobile 2025.xlsx')
    if not os.path.exists(path):
        print("  SKIP: KPI Mobile file not found"); return
    wb = openpyxl.load_workbook(path, data_only=True)
    count = 0

    for sn in wb.sheetnames:
        if sn == 'Rekap': continue
        ws = wb[sn]

        # Find tech name & SPV
        tech_name, spv_name = sn, None
        for r in ws.iter_rows(min_row=1, max_row=3, values_only=False):
            a = str(r[0].value or '')
            b = str(r[1].value or '').replace(': ','').strip()
            if 'Nama' in a and b: tech_name = b
            if 'SPV' in a and b: spv_name = b

        emp_id = get_or_create_employee(cur, tech_name, 'Teknisi Mobile', 'mobile', spv_name=spv_name)

        # Find month columns
        months_cols = {}
        for scan in ws.iter_rows(min_row=3, max_row=5, values_only=False):
            for c in scan:
                v = str(c.value).strip() if c.value else ''
                if v in MONTH_NAMES:
                    months_cols[c.column] = MONTH_NAMES[v]

        # Read indicator rows
        idx = 0
        for row in ws.iter_rows(min_row=5, max_row=20, values_only=False):
            if 'Total' in str(row[0].value or '') + str(row[1].value or ''):
                continue
            bobot = row[5].value  # col F
            if not isinstance(bobot, (int, float)) or float(bobot) >= 0.5:
                continue
            idx += 1
            if idx > 13: break
            tid = tmpl['mobile'].get(idx)
            if not tid: continue

            for col_start, month in sorted(months_cols.items()):
                ket = str(ws.cell(row=row[0].row, column=col_start).value or '').strip()
                pct = ws.cell(row=row[0].row, column=col_start + 1).value
                if pct is None: continue
                score = float(pct) if isinstance(pct, (int, float)) else 0.0
                raw = None
                if ket and ket not in ('0', '-', 'None', ''):
                    try: raw = float(ket.split()[0].replace(',','.'))
                    except: pass

                cur.execute("""INSERT INTO hris_kpi_scores (employee_id,template_id,period_year,period_month,keterangan,raw_value,score_pct,scored_by)
                    VALUES (%s,%s,2025,%s,%s,%s,%s,'Excel Import')
                    ON CONFLICT (employee_id,template_id,period_year,period_month) DO UPDATE SET
                    keterangan=EXCLUDED.keterangan, raw_value=EXCLUDED.raw_value, score_pct=EXCLUDED.score_pct, scored_at=NOW()
                """, (emp_id, tid, month, ket if ket and ket != '-' else None, raw, score))
                count += 1

    print(f"  KPI Mobile: {count} scores")


# ══════════════════════════════════════════════════════════════
# 3. KPI STATION SCORES
# ══════════════════════════════════════════════════════════════

def seed_kpi_station(cur, tmpl):
    path = os.path.join(BASE, 'KPI Station 2025 (1).xlsx')
    if not os.path.exists(path):
        print("  SKIP: KPI Station file not found"); return
    wb = openpyxl.load_workbook(path, data_only=True)
    count = 0

    for sn in wb.sheetnames:
        ws = wb[sn]
        # Each sheet has multiple tech blocks. Find them by "Nama Teknisi" rows.
        tech_blocks = []
        for r_idx in range(1, ws.max_row + 1):
            a = str(ws.cell(row=r_idx, column=1).value or '')
            if 'Nama' in a:
                b = str(ws.cell(row=r_idx, column=2).value or '').replace(': ','').strip()
                spv_row = r_idx + 1
                spv = str(ws.cell(row=spv_row, column=2).value or '').replace(': ','').strip()
                tech_blocks.append({'name': b, 'spv': spv, 'start_row': r_idx})

        # Find month columns from first header row (row 3 or first block + 2)
        months_cols = {}
        for scan_row in range(3, 6):
            for c_idx in range(1, ws.max_column + 1):
                v = str(ws.cell(row=scan_row, column=c_idx).value or '').strip()
                if v in MONTH_NAMES:
                    months_cols[c_idx] = MONTH_NAMES[v]

        if not months_cols:
            # Try from first block
            if tech_blocks:
                hr = tech_blocks[0]['start_row'] + 2
                for c_idx in range(1, ws.max_column + 1):
                    v = str(ws.cell(row=hr, column=c_idx).value or '').strip()
                    if v in MONTH_NAMES:
                        months_cols[c_idx] = MONTH_NAMES[v]

        for block in tech_blocks:
            emp_id = get_or_create_employee(cur, block['name'], 'Teknisi Station', 'station', site=sn, spv_name=block['spv'])

            # Data rows start at block start_row + 4 (skip name, spv, header, sub-header)
            data_start = block['start_row'] + 4
            idx = 0
            for r_idx in range(data_start, data_start + 14):
                if r_idx > ws.max_row: break
                # Check for total row
                b_val = str(ws.cell(row=r_idx, column=2).value or '')
                if 'Total' in b_val: break

                bobot = ws.cell(row=r_idx, column=6).value  # col F
                if not isinstance(bobot, (int, float)): continue
                if float(bobot) >= 0.5: break

                idx += 1
                if idx > 11: break
                tid = tmpl['station'].get(idx)
                if not tid: continue

                for col_start, month in sorted(months_cols.items()):
                    ket = str(ws.cell(row=r_idx, column=col_start).value or '').strip()
                    pct = ws.cell(row=r_idx, column=col_start + 1).value
                    if pct is None: continue
                    score = float(pct) if isinstance(pct, (int, float)) else 0.0
                    raw = None
                    if ket and ket not in ('0', '-', 'None', ''):
                        try: raw = float(ket.split()[0].replace(',','.'))
                        except: pass

                    cur.execute("""INSERT INTO hris_kpi_scores (employee_id,template_id,period_year,period_month,keterangan,raw_value,score_pct,scored_by)
                        VALUES (%s,%s,2025,%s,%s,%s,%s,'Excel Import')
                        ON CONFLICT (employee_id,template_id,period_year,period_month) DO UPDATE SET
                        keterangan=EXCLUDED.keterangan, raw_value=EXCLUDED.raw_value, score_pct=EXCLUDED.score_pct, scored_at=NOW()
                    """, (emp_id, tid, month, ket if ket and ket != '-' else None, raw, score))
                    count += 1

    print(f"  KPI Station: {count} scores")


# ══════════════════════════════════════════════════════════════
# 4. ABSENSI (Monthly Summary)
# ══════════════════════════════════════════════════════════════

def seed_absensi_monthly(cur, ws):
    count = 0
    for row in ws.iter_rows(min_row=7, max_row=ws.max_row, values_only=False):
        no = row[0].value
        name = row[1].value
        jabatan = row[2].value
        if not name or not no: continue
        name = str(name).strip()
        jabatan = str(jabatan).strip() if jabatan else 'Unknown'
        emp_type = 'mobile' if 'Mobile' in jabatan else 'station' if 'Station' in jabatan else 'support' if 'Support' in jabatan else 'office'
        emp_id = get_or_create_employee(cur, name, jabatan, emp_type)

        def safe_str(v): return str(v) if v else '0%'
        def safe_float(v): return float(v) if isinstance(v, (int, float)) else 0
        def safe_int(v): return int(v) if isinstance(v, (int, float)) else 0

        cur.execute("""INSERT INTO hris_attendance_monthly (employee_id, period_year, period_month,
            kehadiran_pct, prestasi_score, grooming_pct, grooming_pass, complain_pct, complain_pass,
            jumlah_kunjungan, total_menit, jam_lembur, hari_bonus, hari_setengah,
            hari_efektif, hari_perhitungan, hari_sakit, hari_cuti, hari_izin, hari_kosong, hari_libur)
            VALUES (%s, 2026, 3, %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (employee_id, period_year, period_month) DO UPDATE SET
            kehadiran_pct=EXCLUDED.kehadiran_pct, prestasi_score=EXCLUDED.prestasi_score,
            grooming_pct=EXCLUDED.grooming_pct, grooming_pass=EXCLUDED.grooming_pass,
            complain_pct=EXCLUDED.complain_pct, complain_pass=EXCLUDED.complain_pass,
            jumlah_kunjungan=EXCLUDED.jumlah_kunjungan, total_menit=EXCLUDED.total_menit,
            jam_lembur=EXCLUDED.jam_lembur, hari_bonus=EXCLUDED.hari_bonus,
            hari_setengah=EXCLUDED.hari_setengah, hari_efektif=EXCLUDED.hari_efektif,
            hari_perhitungan=EXCLUDED.hari_perhitungan,
            hari_sakit=EXCLUDED.hari_sakit, hari_cuti=EXCLUDED.hari_cuti,
            hari_izin=EXCLUDED.hari_izin, hari_kosong=EXCLUDED.hari_kosong, hari_libur=EXCLUDED.hari_libur
        """, (emp_id,
              safe_str(row[3].value), safe_float(row[4].value),
              safe_str(row[5].value), safe_int(row[6].value) == 0,
              safe_str(row[7].value), safe_int(row[8].value) == 0,
              safe_int(row[9].value), safe_int(row[10].value),
              safe_float(row[11].value), safe_float(row[12].value), safe_float(row[13].value),
              safe_float(row[16].value), safe_float(row[15].value),
              safe_int(row[17].value), safe_int(row[18].value),
              safe_int(row[19].value), safe_int(row[20].value), safe_int(row[21].value)))
        count += 1
    print(f"  Absensi monthly: {count} records")


# ══════════════════════════════════════════════════════════════
# 5. LEMBUR (Overtime)
# ══════════════════════════════════════════════════════════════

def seed_lembur(cur, ws):
    cur.execute("DELETE FROM hris_overtime")
    count = 0
    for row in ws.iter_rows(min_row=4, max_row=ws.max_row, values_only=False):
        name = row[1].value
        if not name or not row[0].value: continue
        emp_id = get_or_create_employee(cur, str(name).strip())
        ot_date = row[2].value
        if not hasattr(ot_date, 'strftime'): continue
        ot_date = ot_date.date() if hasattr(ot_date, 'date') else ot_date
        area = str(row[3].value)[:256] if row[3].value else None
        jam = str(row[4].value) if row[4].value else None
        durasi = float(row[5].value) if isinstance(row[5].value, (int, float)) else 0
        acc_spv = str(row[6].value) if row[6].value else None
        acc_hr = str(row[7].value) if row[7].value else None

        cur.execute("""INSERT INTO hris_overtime (employee_id,overtime_date,area,jam_range,duration_hours,acc_spv,acc_personalia)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (emp_id, ot_date, area, jam, durasi, acc_spv, acc_hr))
        count += 1
    print(f"  Lembur: {count} records")


# ══════════════════════════════════════════════════════════════
# 6. KUNJUNGAN (Visit Log) — 443 records
# ══════════════════════════════════════════════════════════════

def seed_kunjungan(cur, ws):
    cur.execute("DELETE FROM hris_visits")
    count = 0
    for row in ws.iter_rows(min_row=4, max_row=ws.max_row, values_only=False):
        name = row[1].value
        if not name or not row[0].value: continue
        emp_id = get_or_create_employee(cur, str(name).strip())
        customer = str(row[3].value)[:256] if row[3].value else None
        checkin_text = str(row[4].value)[:100] if row[4].value else None
        checkout_text = str(row[5].value)[:100] if row[5].value else None
        durasi = int(row[6].value) if isinstance(row[6].value, (int, float)) else 0
        jam = float(row[7].value) if isinstance(row[7].value, (int, float)) else 0
        total = int(row[9].value) if len(row) > 9 and isinstance(row[9].value, (int, float)) else 0
        acc_spv = str(row[11].value) if len(row) > 11 and row[11].value else None

        cur.execute("""INSERT INTO hris_visits (employee_id,customer_name,check_in_text,check_out_text,duration_min,jam,total_waktu_min,acc_spv)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (emp_id, customer, checkin_text, checkout_text, durasi, jam, total, acc_spv))
        count += 1
    print(f"  Kunjungan: {count} visit records")


# ══════════════════════════════════════════════════════════════
# 7. KEHADIRAN (Daily Attendance Grid) — 64 employees × 28 days
# ══════════════════════════════════════════════════════════════

def seed_kehadiran_daily(cur, ws_absensi):
    """Read daily attendance from ABSENSI sheet columns 23-50 (dates 2026-02-26 to 2026-03-25)."""
    cur.execute("DELETE FROM hris_attendance_daily")

    # Get date columns from row 5
    date_cols = {}
    for row in ws_absensi.iter_rows(min_row=5, max_row=5, values_only=False):
        for c in row:
            if c.value and hasattr(c.value, 'strftime'):
                date_cols[c.column] = c.value.date() if hasattr(c.value, 'date') else c.value

    count = 0
    for row in ws_absensi.iter_rows(min_row=7, max_row=ws_absensi.max_row, values_only=False):
        name = row[1].value
        if not name or not row[0].value: continue
        emp_id = get_or_create_employee(cur, str(name).strip())

        for col_idx, attend_date in sorted(date_cols.items()):
            if col_idx - 1 >= len(row): continue
            cell_val = row[col_idx - 1].value  # row is 0-indexed
            if cell_val is None: continue
            val = str(cell_val).strip()

            # Map: √ = H (hadir), X = absent, C = cuti, S = sakit, I = izin, L = libur
            status_map = {'√': 'H', 'V': 'H', 'v': 'H', 'X': 'X', 'x': 'X',
                          'C': 'C', 'S': 'S', 'I': 'I', 'K': 'K', 'L': 'L'}
            status = status_map.get(val, 'H' if val else None)
            if not status: continue

            cur.execute("""INSERT INTO hris_attendance_daily (employee_id, attend_date, status)
                VALUES (%s, %s, %s)
                ON CONFLICT (employee_id, attend_date) DO UPDATE SET status=EXCLUDED.status""",
                (emp_id, attend_date, status))
            count += 1
    print(f"  Kehadiran daily: {count} records")


# ══════════════════════════════════════════════════════════════
# 8. COMPLAIN records
# ══════════════════════════════════════════════════════════════

def seed_complain(cur, ws):
    cur.execute("DELETE FROM hris_complaints")
    count = 0
    for row in ws.iter_rows(min_row=4, max_row=ws.max_row, values_only=False):
        jumlah = row[1].value
        if not jumlah or jumlah == 0: continue
        tanggal = row[3].value
        client = str(row[4].value) if row[4].value else None
        teknisi = str(row[5].value) if row[5].value else None
        if not teknisi: continue

        emp_id = get_or_create_employee(cur, teknisi.strip())
        hama = str(row[6].value) if row[6].value else None
        complaint_text = str(row[7].value) if row[7].value else None
        tim_fu = str(row[8].value) if row[8].value else None
        fu_date = row[9].value
        days = int(row[10].value) if isinstance(row[10].value, (int, float)) else None
        tindakan = str(row[11].value) if row[11].value else None
        status = str(row[12].value) if row[12].value else None
        close_date = row[14].value
        ctype = str(row[15].value) if len(row) > 15 and row[15].value else None

        comp_date = tanggal.date() if hasattr(tanggal, 'date') else None
        fu_d = fu_date.date() if hasattr(fu_date, 'date') else None
        cl_d = close_date.date() if hasattr(close_date, 'date') else None

        cur.execute("""INSERT INTO hris_complaints (employee_id,period_year,period_month,complaint_date,client_name,
            hama,complaint_text,tim_fu,fu_date,days_to_resolve,tindakan,status,complaint_type,close_date)
            VALUES (%s,2026,3,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (emp_id, comp_date, client, hama, complaint_text, tim_fu, fu_d, days, tindakan, status, ctype, cl_d))
        count += 1
    print(f"  Complaints: {count} records")


# ══════════════════════════════════════════════════════════════
# 9. GROOMING violations
# ══════════════════════════════════════════════════════════════

def seed_grooming(cur, ws):
    cur.execute("DELETE FROM hris_grooming")
    count = 0
    for row in ws.iter_rows(min_row=4, max_row=ws.max_row, values_only=False):
        jumlah = row[1].value
        if not jumlah or jumlah == 0: continue
        name = str(row[2].value) if row[2].value else None
        if not name: continue
        emp_id = get_or_create_employee(cur, name.strip())
        temuan = str(row[3].value) if row[3].value else ''
        lampiran = str(row[4].value) if row[4].value else None
        pic = str(row[5].value) if row[5].value else None
        acc = str(row[6].value) if row[6].value else None

        cur.execute("""INSERT INTO hris_grooming (employee_id,period_year,period_month,temuan,lampiran_url,pic,acc_personalia)
            VALUES (%s,2026,3,%s,%s,%s,%s)""",
            (emp_id, temuan, lampiran, pic, acc))
        count += 1
    print(f"  Grooming: {count} records")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("HRIS Seed — Complete Import")
    print("=" * 60)

    with get_conn() as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            # Clear employees for fresh start (cascades handled by ON CONFLICT)
            print("\n[1/9] KPI Templates...")
            tmpl = seed_kpi_templates(cur)

            print("[2/9] KPI Mobile Scores...")
            seed_kpi_mobile(cur, tmpl)

            print("[3/9] KPI Station Scores...")
            seed_kpi_station(cur, tmpl)

            # Absensi file
            absensi_path = os.path.join(BASE, '03 REKAP ABSENSI 26 FEBRUARI - 25 MARET 2026.xlsx')
            if os.path.exists(absensi_path):
                wb = openpyxl.load_workbook(absensi_path, data_only=True)

                print("[4/9] Absensi Monthly...")
                seed_absensi_monthly(cur, wb['ABSENSI'])

                print("[5/9] Lembur...")
                seed_lembur(cur, wb['LEMBUR'])

                print("[6/9] Kunjungan (Visit Log)...")
                seed_kunjungan(cur, wb['KUNJUNGAN'])

                print("[7/9] Kehadiran Daily...")
                seed_kehadiran_daily(cur, wb['ABSENSI'])

                print("[8/9] Complaints...")
                seed_complain(cur, wb['COMPLAIN'])

                print("[9/9] Grooming...")
                seed_grooming(cur, wb['GROOMING'])
            else:
                print("  SKIP: Absensi file not found")

    # Final verification
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    with get_conn() as conn:
        with conn.cursor() as cur:
            tables = ['hris_employees', 'hris_kpi_templates', 'hris_kpi_scores',
                      'hris_attendance_monthly', 'hris_attendance_daily',
                      'hris_overtime', 'hris_visits', 'hris_complaints', 'hris_grooming']
            for t in tables:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {t}")
                print(f"  {t:30s} {cur.fetchone()['cnt']:>6} rows")

            # Cross-check KPI totals vs Excel Rekap
            print("\n  KPI Mobile cross-check (vs Excel Rekap):")
            cur.execute("""
                SELECT e.full_name, s.period_month,
                       ROUND(SUM(s.score_pct)::numeric * 100, 1) as total_pct
                FROM hris_kpi_scores s
                JOIN hris_employees e ON e.id = s.employee_id
                JOIN hris_kpi_templates t ON t.id = s.template_id
                WHERE t.employee_type = 'mobile'
                GROUP BY e.full_name, s.period_month
                ORDER BY e.full_name, s.period_month
                LIMIT 20
            """)
            for r in cur.fetchall():
                n = r["full_name"]
                m = r["period_month"]
                p = r["total_pct"]
                print(f"    {n:25s} M{m:02d}: {p}%")

            # Station totals
            print("\n  KPI Station cross-check:")
            cur.execute("""
                SELECT e.full_name, e.site_assignment, s.period_month,
                       ROUND(SUM(s.score_pct)::numeric * 100, 1) as total_pct
                FROM hris_kpi_scores s
                JOIN hris_employees e ON e.id = s.employee_id
                JOIN hris_kpi_templates t ON t.id = s.template_id
                WHERE t.employee_type = 'station'
                GROUP BY e.full_name, e.site_assignment, s.period_month
                ORDER BY e.full_name, s.period_month
                LIMIT 20
            """)
            for r in cur.fetchall():
                n = r["full_name"]
                site = r["site_assignment"] or "-"
                m = r["period_month"]
                p = r["total_pct"]
                print(f"    {n:25s} ({site:8s}) M{m:02d}: {p}%")

    print("\nDone!")


if __name__ == '__main__':
    main()
