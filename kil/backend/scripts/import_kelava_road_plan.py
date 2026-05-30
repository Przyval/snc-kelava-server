"""
Import t_road_plan + t_visit dari Kelava CSV → snc_schedule_events
=====================================================================
Tujuan: Kaya-kan training data dengan 1 tahun penuh 2025 (5,902 events
untuk 11 teknisi yang relevan), bukan hanya 6 bulan Excel 2026.

Sumber:
  data/db_export/t_road_plan.csv       (33,651 rows total)
  data/db_export/t_visit.csv           (check_in/check_out time)
  data/db_export/m_customer.csv        (nama customer)

Filter: 2025 + status='Selesai' + type='t_mobile' + tech in SHEET_MAP

Usage:
  python3 kil/backend/scripts/import_kelava_road_plan.py [--dry-run]
"""

import sys, os, csv, argparse, json
from datetime import datetime, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

import psycopg
from psycopg.rows import dict_row

EXPORT_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'db_export')

# Mapping kelava_p_user_id → already exists in snc_technicians
# Kita pakai 14 teknisi schedulable
KELAVA_TECH_IDS = {385, 379, 396, 399, 403, 389, 392, 391, 428, 459, 442, 407, 445}

LOCAL_PG = dict(
    host='127.0.0.1', port=5432,
    dbname='kil_enterprise', user='kil_ent', password='KilEnt2026!',
    row_factory=dict_row,
)


def normalize_name(name: str) -> str:
    if not name: return ''
    import re
    s = name.upper().strip()
    for p in ['PT.', 'PT ', 'CV.', 'CV ', 'UD.', 'UD ']:
        if s.startswith(p): s = s[len(p):].strip()
    s = re.sub(r'[^A-Z0-9\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def load_kelava_data():
    """Load t_road_plan + t_visit + m_customer dari CSV."""
    # m_customer: id → name
    customers = {}
    with open(os.path.join(EXPORT_DIR, 'm_customer.csv')) as f:
        for r in csv.DictReader(f):
            if r['id'] and r['name']:
                customers[r['id']] = r['name'].strip()

    # t_visit: id_road_plan → check_in time
    visit_times = {}
    with open(os.path.join(EXPORT_DIR, 't_visit.csv')) as f:
        for r in csv.DictReader(f):
            rp = r['id_road_plan']
            ci = r['check_in']
            co = r['check_out']
            if rp and ci:
                visit_times[rp] = (ci, co)

    # t_road_plan: filter
    plans = []
    with open(os.path.join(EXPORT_DIR, 't_road_plan.csv')) as f:
        for r in csv.DictReader(f):
            if not r['visit_date'].startswith('2025-'): continue
            if r['status'] != 'Selesai': continue
            if r['type'] != 't_mobile': continue
            if r['is_cancel'] == 't': continue
            if not r['id_user'] or int(r['id_user']) not in KELAVA_TECH_IDS: continue
            if not r['id_customer'] or r['id_customer'] not in customers: continue
            plans.append({
                'rp_id':        r['id'],
                'visit_date':   r['visit_date'],
                'id_user':      int(r['id_user']),
                'kelava_cust_id': r['id_customer'],
                'cust_name':    customers[r['id_customer']],
            })

    return plans, visit_times


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"Loading Kelava CSV dari {EXPORT_DIR}...")
    plans, visit_times = load_kelava_data()
    print(f"  {len(plans):,} road plans terfilter")
    print(f"  {len(visit_times):,} visit times tersedia")

    conn = psycopg.connect(**LOCAL_PG)
    cur  = conn.cursor(row_factory=dict_row)

    # Load tech mapping
    cur.execute("SELECT id, kelava_p_user_id FROM snc_technicians WHERE kelava_p_user_id IS NOT NULL")
    tech_map = {r['kelava_p_user_id']: r['id'] for r in cur.fetchall()}
    print(f"  {len(tech_map)} teknisi mapping (kelava_p_user_id → snc_technicians.id)")

    # Load existing snc_clients (by normalized name)
    cur.execute("SELECT id, name FROM snc_clients")
    clients = cur.fetchall()
    client_by_norm = {normalize_name(c['name']): c['id'] for c in clients}
    print(f"  {len(clients)} snc_clients existing")

    # Stats
    inserted, skipped_no_tech, skipped_no_client, skipped_dup, created_clients = 0, 0, 0, 0, 0
    no_time = 0

    for p in plans:
        # Map tech
        snc_tech_id = tech_map.get(p['id_user'])
        if not snc_tech_id:
            skipped_no_tech += 1
            continue

        # Map / create client
        norm = normalize_name(p['cust_name'])
        snc_client_id = client_by_norm.get(norm)
        if not snc_client_id:
            # Create new client
            if not args.dry_run:
                cur.execute("""
                    INSERT INTO snc_clients (name) VALUES (%s)
                    ON CONFLICT DO NOTHING RETURNING id
                """, (p['cust_name'],))
                row = cur.fetchone()
                if row:
                    snc_client_id = row['id']
                else:
                    cur.execute("SELECT id FROM snc_clients WHERE name=%s", (p['cust_name'],))
                    r = cur.fetchone()
                    snc_client_id = r['id'] if r else None
                if snc_client_id:
                    client_by_norm[norm] = snc_client_id
                    created_clients += 1
            else:
                created_clients += 1
                continue

        if not snc_client_id:
            skipped_no_client += 1
            continue

        # Determine time
        vt = visit_times.get(p['rp_id'])
        if vt:
            ci, co = vt
            try:
                start_dt = datetime.fromisoformat(ci.replace('+07', '+07:00')).replace(tzinfo=None)
                end_dt   = datetime.fromisoformat(co.replace('+07', '+07:00')).replace(tzinfo=None) if co else None
            except Exception:
                start_dt = datetime.fromisoformat(p['visit_date'].replace('+07', '+07:00')).replace(tzinfo=None)
                end_dt = None
        else:
            no_time += 1
            try:
                start_dt = datetime.fromisoformat(p['visit_date'].replace('+07', '+07:00')).replace(tzinfo=None)
            except Exception:
                continue
            end_dt = None

        start_date = start_dt.date()

        # Dedup check
        if not args.dry_run:
            cur.execute("""
                SELECT id FROM snc_schedule_events
                WHERE technician_id=%s AND client_id=%s AND start_datetime=%s
            """, (snc_tech_id, snc_client_id, start_dt))
            if cur.fetchone():
                skipped_dup += 1
                continue

            cur.execute("""
                INSERT INTO snc_schedule_events
                    (technician_id, client_id, start_datetime, end_datetime,
                     start_date, schedule_status, created_by)
                VALUES (%s,%s,%s,%s,%s, 'completed', 0)
            """, (snc_tech_id, snc_client_id, start_dt, end_dt, start_date))
        inserted += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Results:")
    print(f"  Inserted        : {inserted:,}")
    print(f"  Created clients : {created_clients}")
    print(f"  No time fallback: {no_time}")
    print(f"  Skipped no tech : {skipped_no_tech}")
    print(f"  Skipped no client: {skipped_no_client}")
    print(f"  Skipped duplicate: {skipped_dup}")


if __name__ == '__main__':
    main()
