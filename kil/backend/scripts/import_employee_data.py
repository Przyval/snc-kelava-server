"""
Import Data Karyawan SNC dari Excel → snc_technicians

Apa yang dilakukan:
  1. Baca Excel karyawan
  2. Dedup snc_technicians (hapus duplikat Fathur/Irul/Rangga)
  3. Upsert employee_type, contract_expiry, join_date ke teknisi yang sudah ada
  4. Insert teknisi baru (Support/Mobile) yang belum ada di snc_technicians
  5. Set is_active=false untuk kontrak yang expired

Usage:
  python3 kil/backend/scripts/import_employee_data.py [--dry-run]
"""

import sys, os, re, argparse
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

try:
    import openpyxl
except ImportError:
    print("ERROR: pip install openpyxl"); sys.exit(1)

import psycopg
from psycopg.rows import dict_row

XLSX = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'Data_Karyawan_SNC_1779960293.xlsx'
)
LOCAL_PG = dict(
    host='127.0.0.1', port=5432,
    dbname='kil_enterprise', user='kil_ent', password='KilEnt2026!',
    row_factory=dict_row,
)
TODAY = date.today()

# Jabatan → employee_type mapping
JABATAN_MAP = {
    'Teknisi Mobile':  'mobile',
    'Teknisi Support': 'support',
    'Teknisi Station': 'station',
    'Teknisi Termite': 'termite',
    'Support':         'support',
    'Driver':          'driver',
    'Leader':          'leader',
    'Office':          'office',
    'Direksi':         'management',
    'Security':        'security',
}

# Teknisi yang perlu jadwal lapangan
SCHEDULABLE_TYPES = {'mobile', 'support'}


def _normalize_name(name: str) -> str:
    """Normalisasi nama untuk fuzzy match."""
    return re.sub(r'\s+', ' ', str(name).strip().upper())


def read_excel(path: str) -> list:
    """Baca Excel karyawan → list of dicts."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    employees = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        name = row[0]
        jabatan = row[5]
        if not name or not jabatan or name == 'Name':
            continue
        join_raw     = row[2]
        contract_raw = row[19]
        monday_id    = row[32]
        gender       = row[13]

        join_date = join_raw.date() if hasattr(join_raw, 'date') else None
        contract_exp = contract_raw.date() if hasattr(contract_raw, 'date') else None

        emp_type = JABATAN_MAP.get(jabatan, 'other')
        is_active = contract_exp is None or contract_exp >= TODAY

        employees.append({
            'name':           str(name).strip(),
            'name_norm':      _normalize_name(name),
            'jabatan':        jabatan,
            'employee_type':  emp_type,
            'join_date':      join_date,
            'contract_expiry': contract_exp,
            'is_active':      is_active,
            'gender':         gender,
            'monday_id':      str(monday_id) if monday_id else None,
        })
    return employees


def dedup_technicians(cur, dry_run: bool) -> int:
    """
    Hapus duplikat snc_technicians (Fathur/Irul/Rangga punya 3 rows masing-masing).
    Pertahankan row dengan kelava_p_user_id (jika ada), atau id terkecil.
    Update FK di snc_schedule_events sebelum hapus.
    """
    cur.execute("""
        SELECT name, COUNT(*) as cnt, ARRAY_AGG(id ORDER BY
            CASE WHEN kelava_p_user_id IS NOT NULL THEN 0 ELSE 1 END, id
        ) as ids
        FROM snc_technicians
        GROUP BY name
        HAVING COUNT(*) > 1
    """)
    dups = cur.fetchall()
    total_removed = 0

    for row in dups:
        ids      = row['ids']           # [keep, remove, remove, ...]
        keep_id  = ids[0]
        drop_ids = ids[1:]
        print(f"  Dedup '{row['name']}': keep id={keep_id}, drop {drop_ids}")

        if not dry_run:
            # Re-point FK di snc_schedule_events
            cur.execute("""
                UPDATE snc_schedule_events
                SET technician_id = %s
                WHERE technician_id = ANY(%s)
            """, (keep_id, drop_ids))
            # Re-point FK di snc_schedule_patterns
            cur.execute("""
                UPDATE snc_schedule_patterns
                SET technician_id = %s
                WHERE technician_id = ANY(%s)
            """, (keep_id, drop_ids))
            # Re-point FK di snc_customer_technician
            cur.execute("""
                UPDATE snc_customer_technician
                SET technician_id = %s
                WHERE technician_id = ANY(%s)
                  AND NOT EXISTS (
                      SELECT 1 FROM snc_customer_technician ct2
                      WHERE ct2.client_id    = snc_customer_technician.client_id
                        AND ct2.technician_id = %s
                        AND ct2.role          = snc_customer_technician.role
                  )
            """, (keep_id, drop_ids, keep_id))
            # Hapus sisa duplikat
            cur.execute("""
                DELETE FROM snc_customer_technician WHERE technician_id = ANY(%s)
            """, (drop_ids,))
            cur.execute("""
                DELETE FROM snc_technicians WHERE id = ANY(%s)
            """, (drop_ids,))
        total_removed += len(drop_ids)

    return total_removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"\nMembaca {XLSX}...")
    employees = read_excel(XLSX)
    print(f"  {len(employees)} karyawan dibaca")

    by_type = {}
    for e in employees:
        t = e['employee_type']
        by_type[t] = by_type.get(t, 0) + 1
    for t, n in sorted(by_type.items()):
        print(f"    {t:15s}: {n}")

    conn = psycopg.connect(**LOCAL_PG)
    cur  = conn.cursor(row_factory=dict_row)

    # ── Step 1: Dedup ───────────────────────────────────────────────────────
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Step 1: Dedup snc_technicians...")
    removed = dedup_technicians(cur, args.dry_run)
    print(f"  Duplikat dihapus: {removed}")
    if not args.dry_run:
        conn.commit()

    # ── Step 2: Load existing technicians ───────────────────────────────────
    cur.execute("SELECT id, name, kelava_p_user_id FROM snc_technicians ORDER BY name")
    db_techs = {_normalize_name(r['name']): r for r in cur.fetchall()}
    print(f"\nStep 2: {len(db_techs)} teknisi unik di DB setelah dedup")

    # ── Step 3: Upsert employee data ────────────────────────────────────────
    print(f"\nStep 3: Update data karyawan...")
    updated = 0
    inserted = 0

    for emp in employees:
        norm = emp['name_norm']

        if norm in db_techs:
            # Update kolom baru
            tech_id = db_techs[norm]['id']
            if not args.dry_run:
                cur.execute("""
                    UPDATE snc_technicians SET
                        employee_type    = %s,
                        contract_expiry  = %s,
                        join_date        = %s,
                        gender           = %s,
                        monday_id        = %s,
                        is_active        = %s
                    WHERE id = %s
                """, (
                    emp['employee_type'], emp['contract_expiry'],
                    emp['join_date'], emp['gender'], emp['monday_id'],
                    emp['is_active'], tech_id
                ))
            updated += 1
            print(f"  UPDATE: {emp['name']:35s} | {emp['employee_type']:10s} | active={emp['is_active']} | exp={emp['contract_expiry']}")

        elif emp['employee_type'] in SCHEDULABLE_TYPES:
            # Teknisi baru yang perlu dijadwalkan — insert
            if not args.dry_run:
                cur.execute("""
                    INSERT INTO snc_technicians
                        (name, employee_type, contract_expiry, join_date,
                         gender, monday_id, is_active)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                """, (
                    emp['name'], emp['employee_type'], emp['contract_expiry'],
                    emp['join_date'], emp['gender'], emp['monday_id'],
                    emp['is_active']
                ))
            inserted += 1
            print(f"  INSERT: {emp['name']:35s} | {emp['employee_type']:10s} | active={emp['is_active']} | exp={emp['contract_expiry']}")
        else:
            print(f"  SKIP:   {emp['name']:35s} | {emp['employee_type']:10s} (non-schedulable)")

    if not args.dry_run:
        conn.commit()

    conn.close()

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Selesai:")
    print(f"  Updated  : {updated}")
    print(f"  Inserted : {inserted} (teknisi baru schedulable)")
    print(f"  Deduped  : {removed} duplikat dihapus")

    # Summary kontrak hampir habis
    print(f"\nKontrak habis dalam 60 hari:")
    cutoff = date(TODAY.year, TODAY.month + 2 if TODAY.month <= 10 else (TODAY.month - 10), TODAY.day)
    for e in employees:
        if e['contract_expiry'] and TODAY <= e['contract_expiry'] <= cutoff:
            days_left = (e['contract_expiry'] - TODAY).days
            print(f"  ⚠ {e['name']:35s} | exp: {e['contract_expiry']} ({days_left} hari lagi)")


if __name__ == '__main__':
    main()
