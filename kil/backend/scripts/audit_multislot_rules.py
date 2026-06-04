"""
Audit: enumerate semua client di master xlsx yang punya ≥2 entry rule
(multi-time-slot), lalu verify di DB rules-nya semua hadir.

Run after import_master_rules_xlsx.py untuk sanity check.
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import openpyxl
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row


def main():
    if len(sys.argv) < 2:
        print('Usage: audit_multislot_rules.py <xlsx_path>')
        sys.exit(1)

    wb = openpyxl.load_workbook(sys.argv[1], data_only=True)
    sh = wb['Kunjungan Client']

    by_client = defaultdict(list)
    for r in range(4, sh.max_row + 1):
        name = sh.cell(r, 2).value
        if not name or not isinstance(name, str):
            continue
        by_client[name.strip()].append({
            'freq': sh.cell(r, 3).value,
            'hari': sh.cell(r, 4).value,
            'jam':  sh.cell(r, 5).value,
            'ket':  sh.cell(r, 6).value,
        })

    multi = {n: rows for n, rows in by_client.items() if len(rows) > 1}
    print(f'Multi-slot clients: {len(multi)}')
    for n, rows in sorted(multi.items()):
        print(f'  {n}: {len(rows)} slot')

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as c:
            print('\n' + '═' * 70)
            print('Verifikasi DB — apakah semua slot ke-import?')
            print('═' * 70)
            all_ok = True
            for n, rows in sorted(multi.items()):
                c.execute("""
                    SELECT COUNT(*) AS n FROM snc_recurring_rules r
                    JOIN snc_clients c ON c.id = r.client_id
                    WHERE c.name ILIKE %s AND r.is_mandatory = true
                      AND (r.effective_end IS NULL OR r.effective_end >= CURRENT_DATE)
                """, (f'%{n.split()[0]}%',))
                got = c.fetchone()['n']
                status = '✓' if got >= len(rows) else '✗'
                if got < len(rows):
                    all_ok = False
                print(f'  {status} {n:25s} xlsx={len(rows)} db={got}')

            print()
            print('ALL OK' if all_ok else '⚠️  SOME MISSING — re-run import')


if __name__ == '__main__':
    main()
