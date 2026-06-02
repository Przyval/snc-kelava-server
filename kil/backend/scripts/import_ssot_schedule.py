"""
Import jadwal teknisi dari Excel ke SSOT schema (snc_schedule_events).
Menggantikan import_excel_schedule.py lama.

Usage:
  python3 kil/backend/scripts/import_ssot_schedule.py <path_to_xlsx> [--dry-run]

Steps:
  1. Baca semua sheet Excel
  2. Upsert supervisors, technicians, clients
  3. Buat import_batch record
  4. Insert schedule_events, catat errors ke import_errors
  5. Print summary
"""

import sys
import os
import re
import argparse
from datetime import date as _date_cls, datetime, timedelta, time

# Indonesian month names → number (used for filename-based date repair)
_BULAN_MAP = {
    'januari': 1, 'january': 1, 'jan': 1,
    'februari': 2, 'february': 2, 'feb': 2,
    'maret': 3, 'march': 3, 'mar': 3,
    'april': 4, 'apr': 4,
    'mei': 5, 'may': 5,
    'juni': 6, 'june': 6, 'jun': 6,
    'juli': 7, 'july': 7, 'jul': 7,
    'agustus': 8, 'august': 8, 'agust': 8, 'aug': 8,
    'september': 9, 'sept': 9, 'sep': 9,
    'oktober': 10, 'october': 10, 'okt': 10, 'oct': 10,
    'november': 11, 'nov': 11,
    'desember': 12, 'december': 12, 'des': 12, 'dec': 12,
}


def filename_year_month(filename: str) -> tuple[int | None, int | None]:
    """
    Extract (year, month) from xlsx filename like 'JADWAL TEKNISI JANUARI 2026'.
    Returns (None, None) if not parseable.
    """
    lower = filename.lower()
    year_match = re.search(r'\b(20\d{2})\b', lower)
    year = int(year_match.group(1)) if year_match else None
    month = None
    for name, num in _BULAN_MAP.items():
        if re.search(rf'\b{name}\b', lower):
            month = num
            break
    return year, month


def repair_date(cell_date: _date_cls, src_year: int, src_month: int) -> _date_cls:
    """
    If xlsx cell has wrong year/month (Excel epoch glitch: 1900-01-XX), remap
    the day-of-month into the source year/month. Otherwise return as-is.
    """
    if not src_year or not src_month:
        return cell_date
    # Trust dates that are in or adjacent to source month
    if cell_date.year == src_year and abs(cell_date.month - src_month) <= 1:
        return cell_date
    # Trust dates within the source month exactly
    if cell_date.year == src_year and cell_date.month == src_month:
        return cell_date
    # Otherwise remap day-of-month onto source year/month
    day = max(1, min(cell_date.day, 28))  # clamp to 28 to avoid Feb overflow
    try:
        return _date_cls(src_year, src_month, day)
    except ValueError:
        return _date_cls(src_year, src_month, 28)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

try:
    import openpyxl
except ImportError:
    print("ERROR: pip install openpyxl")
    sys.exit(1)

import psycopg
from psycopg.rows import dict_row

# ──────────────────────────────────────────────
# Sheet → technician mapping
# Tambah/edit di sini kalau ada sheet baru atau nama beda
# ──────────────────────────────────────────────
SHEET_MAP = {
    'AKBAR R':   {'name': 'Akbar Rohmatulah',        'p_user_id': 385, 'supervisor': 'Fahmi'},
    'ANAM':      {'name': 'Choirul Anam',             'p_user_id': 379, 'supervisor': 'Fahmi'},
    'ABU S':     {'name': 'M. Abu Samsudin',          'p_user_id': 396, 'supervisor': 'Fahmi'},
    'ALMAS ':    {'name': 'Ananda Almas',             'p_user_id': 399, 'supervisor': 'Fahmi'},
    'ADAM':      {'name': 'Adam Abdillah',            'p_user_id': 403, 'supervisor': 'Fahmi'},
    'MAHRUS':    {'name': 'Moh. Mahrus',              'p_user_id': 389, 'supervisor': 'Fahmi'},
    'ANDIK':     {'name': 'Andik Noroyan Fananiar',   'p_user_id': 392, 'supervisor': 'Fahmi'},
    'LUCKY':     {'name': 'Lucky Adi Putra',          'p_user_id': 391, 'supervisor': 'Fahmi'},
    'MAULANA':   {'name': 'Moch Maulana',             'p_user_id': 428, 'supervisor': 'Fahmi'},
    'RANGGA':    {'name': 'Rangga',                   'p_user_id': None, 'supervisor': 'Fahmi'},
    'FATHUR':    {'name': 'Fathur',                   'p_user_id': None, 'supervisor': 'Fahmi'},
    'IMAM':      {'name': 'Nur Imam Siswo Utomo',     'p_user_id': 459, 'supervisor': 'Fahmi'},
    'ARGA':      {'name': 'Argantara Alif Saputra',   'p_user_id': 442, 'supervisor': 'Fahmi'},
    'RENDY':     {'name': 'I Wayan Rendy',            'p_user_id': 407, 'supervisor': 'Fahmi'},
    'IRUL':      {'name': 'Irul',                     'p_user_id': None, 'supervisor': 'Fahmi'},
    'MULYASARI': {'name': 'Muliyasari',               'p_user_id': 445, 'supervisor': 'Fahmi'},
    'PM Jogja ': {'name': 'PM Jogja',                 'p_user_id': None, 'supervisor': None, 'skip': True},
    'PM SOLO':   {'name': 'PM Solo',                  'p_user_id': None, 'supervisor': None, 'skip': True},
}

def connect():
    return psycopg.connect(
        host='127.0.0.1', port=5432,
        dbname='kil_enterprise', user='kil_ent', password='KilEnt2026!',
        row_factory=dict_row,
    )

def parse_time_str(val):
    """'13.00' or '13:00' → time object. Returns None if invalid."""
    if not val:
        return None
    val = str(val).strip().replace('.', ':')
    try:
        h, m = val.split(':')[:2]
        h, m = int(h), int(m)
        if h == 24:
            h = 0
        return time(h % 24, m)
    except Exception:
        return None

def parse_time_range(val):
    """'13.00-15.00' → (time_start, time_end). Both may be None."""
    if not val or str(val).strip() in ('-', 'OFF', ''):
        return None, None
    val = str(val).strip()
    if '-' in val:
        parts = val.split('-', 1)
        return parse_time_str(parts[0]), parse_time_str(parts[1])
    return None, None

def make_datetimes(visit_date, start_t, end_t):
    """
    Returns (start_datetime, end_datetime).
    Handles midnight crossings: if end < start, end is next day.
    """
    if start_t is None:
        start_dt = datetime.combine(visit_date, time(8, 0))
    else:
        start_dt = datetime.combine(visit_date, start_t)

    if end_t is None:
        end_dt = None
    else:
        end_dt = datetime.combine(visit_date, end_t)
        # Midnight crossing: e.g. start 23:00 end 00:30
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

    return start_dt, end_dt

def parse_sheet(ws, src_year: int | None = None, src_month: int | None = None):
    """
    Parse one sheet. Returns list of:
    {date, customer_name, start_time, end_time, visit_type, row_number}

    If src_year/src_month given, dates outside that month are repaired (handles
    the Excel epoch glitch where some sheets store dates as 1900-01-XX).
    """
    rows = list(ws.iter_rows(values_only=True))
    visits = []
    errors = []
    i = 0
    while i < len(rows):
        row = rows[i] if rows[i] else ()
        first = str(row[0] or '').strip().upper() if row else ''
        if first in ('SENIN', 'SENIN '):
            if i + 1 >= len(rows):
                break
            date_row = rows[i + 1] or ()
            day_dates = {}
            for col_idx, day_idx in [(0, 0), (3, 1), (6, 2), (9, 3), (12, 4)]:
                cell = date_row[col_idx] if col_idx < len(date_row) else None
                if isinstance(cell, datetime):
                    d = cell.date()
                    if src_year and src_month:
                        d = repair_date(d, src_year, src_month)
                    day_dates[day_idx] = d
            j = i + 2
            while j < len(rows):
                jrow = rows[j] or ()
                jfirst = str(jrow[0] or '').strip().upper() if jrow else ''
                if jfirst in ('SENIN', 'SENIN '):
                    break
                for day_idx, col_start in enumerate(range(0, 15, 3)):
                    if day_idx not in day_dates:
                        continue
                    if col_start >= len(jrow):
                        continue
                    raw = jrow[col_start]
                    if isinstance(raw, datetime):
                        # Date object leaked into customer cell — skip
                        continue
                    cust = str(raw or '').strip()
                    if not cust or cust in ('-', 'OFF', ''):
                        continue
                    time_raw = str(jrow[col_start + 1] if col_start + 1 < len(jrow) else '') or ''
                    svc_raw  = str(jrow[col_start + 2] if col_start + 2 < len(jrow) else '') or ''
                    t_start, t_end = parse_time_range(time_raw)
                    svc = svc_raw.strip() if svc_raw.strip() not in ('-', '') else None

                    # Validation
                    if time_raw and t_start is None and time_raw not in ('-', ''):
                        errors.append({
                            'row': j + 1,
                            'cell': f'col{col_start+1}',
                            'error_type': 'invalid_time',
                            'raw': time_raw,
                        })

                    visits.append({
                        'date': day_dates[day_idx],
                        'customer_name': cust,
                        'start_time': t_start,
                        'end_time': t_end,
                        'visit_type': svc,
                        'row_number': j + 1,
                    })
                j += 1
            i = j
        else:
            i += 1
    return visits, errors

def upsert_supervisor(cur, name):
    if not name:
        return None
    cur.execute(
        "INSERT INTO snc_supervisors (name) VALUES (%s) "
        "ON CONFLICT DO NOTHING RETURNING id", (name,)
    )
    row = cur.fetchone()
    if row:
        return row['id']
    cur.execute("SELECT id FROM snc_supervisors WHERE name = %s", (name,))
    return cur.fetchone()['id']

def upsert_technician(cur, tech_info, supervisor_id):
    p_uid = tech_info.get('p_user_id')
    name  = tech_info['name']
    if p_uid:
        cur.execute(
            "INSERT INTO snc_technicians (kelava_p_user_id, name, supervisor_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (kelava_p_user_id) DO UPDATE SET name=EXCLUDED.name, supervisor_id=EXCLUDED.supervisor_id "
            "RETURNING id", (p_uid, name, supervisor_id)
        )
    else:
        cur.execute(
            "INSERT INTO snc_technicians (name, supervisor_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING RETURNING id", (name, supervisor_id)
        )
        if not cur.fetchone():
            cur.execute("SELECT id FROM snc_technicians WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row['id']
    cur.execute("SELECT id FROM snc_technicians WHERE name = %s", (name,))
    r = cur.fetchone()
    return r['id'] if r else None

def upsert_client(cur, name):
    cur.execute(
        "INSERT INTO snc_clients (name) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id", (name,)
    )
    row = cur.fetchone()
    if row:
        return row['id']
    cur.execute("SELECT id FROM snc_clients WHERE name = %s", (name,))
    r = cur.fetchone()
    return r['id'] if r else None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('xlsx', help='Path to Excel file')
    parser.add_argument('--dry-run', action='store_true', help='Parse only, no DB writes')
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.xlsx, read_only=True, data_only=True)
    file_name = os.path.basename(args.xlsx)
    # Source month from filename (used to repair Excel epoch glitches)
    src_year, src_month = filename_year_month(file_name)
    month = (f"{src_year:04d}-{src_month:02d}"
             if src_year and src_month else None)

    all_visits = []
    all_errors = []

    # Parse all sheets first
    print(f"\nParsing {file_name}  (source month from filename: {month or 'unknown'})...")
    for sheet_name in wb.sheetnames:
        tech_info = SHEET_MAP.get(sheet_name)
        if not tech_info:
            print(f"  SKIP '{sheet_name}' — not in SHEET_MAP")
            continue
        if tech_info.get('skip'):
            print(f"  SKIP '{sheet_name}' — marked skip (PM)")
            continue
        ws = wb[sheet_name]
        visits, errors = parse_sheet(ws, src_year, src_month)
        for v in visits:
            v['sheet_name'] = sheet_name
            v['tech_info']  = tech_info
            all_visits.append(v)
        for e in errors:
            e['source_sheet'] = sheet_name
            all_errors.append(e)
        print(f"  '{sheet_name}': {len(visits)} visits, {len(errors)} errors")

    # Fallback: if filename didn't yield month, derive from data (most-common month)
    if not month and all_visits:
        from collections import Counter
        c = Counter(v['date'].strftime('%Y-%m') for v in all_visits)
        month = c.most_common(1)[0][0]

    total = len(all_visits)
    print(f"\nTotal: {total} visits, {len(all_errors)} parse errors")

    if args.dry_run:
        print("DRY RUN — no DB writes.")
        return

    conn = connect()
    cur = conn.cursor()

    # Create import batch
    cur.execute(
        "INSERT INTO snc_import_batches (file_name, month, imported_by, total_rows) "
        "VALUES (%s, %s, 'system', %s) RETURNING id",
        (file_name, month, total)
    )
    batch_id = cur.fetchone()['id']
    conn.commit()

    # Upsert supervisors cache
    sup_cache = {}
    tech_cache = {}
    client_cache = {}

    # Pre-seed supervisors and technicians from sheet map
    for sheet_name, tech_info in SHEET_MAP.items():
        if tech_info.get('skip'):
            continue
        sup_name = tech_info.get('supervisor')
        if sup_name and sup_name not in sup_cache:
            sup_cache[sup_name] = upsert_supervisor(cur, sup_name)
        sup_id = sup_cache.get(sup_name)
        tech_key = tech_info['name']
        if tech_key not in tech_cache:
            tid = upsert_technician(cur, tech_info, sup_id)
            tech_cache[tech_key] = tid
            # Upsert sheet mapping
            cur.execute(
                "INSERT INTO snc_import_sheet_mappings (sheet_name, technician_id, technician_name_normalized) "
                "VALUES (%s, %s, %s) ON CONFLICT (sheet_name) DO UPDATE "
                "SET technician_id=EXCLUDED.technician_id, technician_name_normalized=EXCLUDED.technician_name_normalized",
                (sheet_name.strip(), tid, tech_info['name'])
            )
    conn.commit()
    print("Supervisors and technicians seeded.")

    # Insert schedule_events
    ok = 0
    err = 0
    for v in all_visits:
        tech_name = v['tech_info']['name']
        tech_id   = tech_cache.get(tech_name)
        if not tech_id:
            all_errors.append({'source_sheet': v['sheet_name'], 'row': v['row_number'],
                                'error_type': 'unknown_technician', 'raw': tech_name})
            err += 1
            continue

        # Upsert client
        cname = v['customer_name']
        if cname not in client_cache:
            client_cache[cname] = upsert_client(cur, cname)
        client_id = client_cache[cname]

        start_dt, end_dt = make_datetimes(v['date'], v['start_time'], v['end_time'])
        start_date = start_dt.date()

        # Supervisor
        sup_name = v['tech_info'].get('supervisor')
        sup_id   = sup_cache.get(sup_name) if sup_name else None

        # Dedup check: same tech + client + date + start_time
        cur.execute(
            "SELECT id FROM snc_schedule_events "
            "WHERE technician_id = %s AND client_id = %s AND start_date = %s AND start_datetime = %s "
            "LIMIT 1",
            (tech_id, client_id, start_date, start_dt)
        )
        if cur.fetchone():
            continue  # duplicate, skip silently

        cur.execute(
            """INSERT INTO snc_schedule_events
               (technician_id, supervisor_id, client_id, visit_type,
                start_datetime, end_datetime, start_date, schedule_status, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'scheduled', 0)""",
            (tech_id, sup_id, client_id,
             v['visit_type'] or None, start_dt, end_dt, start_date)
        )
        ok += 1

    # Log parse errors to import_errors table
    for e in all_errors:
        cur.execute(
            "INSERT INTO snc_import_errors (batch_id, source_sheet, row_number, cell_reference, error_type, raw_value) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (batch_id, e.get('source_sheet'), e.get('row'), e.get('cell'),
             e.get('error_type'), e.get('raw'))
        )

    # Update batch status
    status = 'success' if err == 0 else 'partial'
    cur.execute(
        "UPDATE snc_import_batches SET status=%s, ok_rows=%s, error_rows=%s WHERE id=%s",
        (status, ok, err + len(all_errors), batch_id)
    )
    conn.commit()
    conn.close()

    print(f"\nBatch #{batch_id} — {status.upper()}")
    print(f"  Inserted : {ok}")
    print(f"  Errors   : {err + len(all_errors)}")
    if all_errors:
        print("\nParse errors:")
        for e in all_errors[:10]:
            print(f"  [{e.get('source_sheet')} row {e.get('row')}] {e.get('error_type')}: {e.get('raw')}")

if __name__ == '__main__':
    main()
