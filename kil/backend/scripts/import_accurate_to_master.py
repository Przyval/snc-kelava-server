"""
Import Accurate Finance data → snc_customer_master + snc_customer_technician

Sources:
  1. accurate_finance.db  → customer status, invoice frequency, revenue tier
  2. snc_schedule_events  → technician ownership (who visits each client most)

Usage:
  python3 kil/backend/scripts/import_accurate_to_master.py [--dry-run]
"""

import sys, os, re, sqlite3, argparse
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

import psycopg
from psycopg.rows import dict_row

ACCURATE_DB = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'data', 'accurate_finance', 'accurate_finance.db'
)

LOCAL_PG = dict(
    host='127.0.0.1', port=5432,
    dbname='kil_enterprise', user='kil_ent', password='KilEnt2026!',
    row_factory=dict_row,
)

TODAY = date.today()
ACTIVE_CUTOFF = TODAY - timedelta(days=90)    # invoice dalam 90 hari = aktif
PAUSED_CUTOFF = TODAY - timedelta(days=180)   # 90-180 hari = paused
# Lebih dari 180 hari tidak ada invoice = cancelled


def _normalize(name: str) -> str:
    """Bersihkan nama untuk fuzzy matching."""
    if not name:
        return ''
    s = name.upper().strip()
    # Hapus prefix legal
    for p in ['PT.', 'PT ', 'CV.', 'CV ', 'UD.', 'UD ', 'TOKO ', 'YAYASAN ']:
        if s.startswith(p):
            s = s[len(p):].strip()
    # Hapus karakter non-alphanumeric
    s = re.sub(r'[^A-Z0-9\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _invoice_frequency(avg_interval: float) -> str:
    """Konversi rata-rata interval invoice → frekuensi."""
    if avg_interval is None:
        return 'irregular'
    if avg_interval <= 10:
        return 'weekly'
    if avg_interval <= 18:
        return 'biweekly'
    if avg_interval <= 35:
        return 'monthly'
    if avg_interval <= 60:
        return 'bimonthly'
    return 'irregular'


def _revenue_tier(total_12m: float) -> str:
    """Tier revenue: A = top, B = mid, C = low."""
    if total_12m >= 20_000_000:
        return 'A'
    if total_12m >= 5_000_000:
        return 'B'
    return 'C'


def load_accurate_customers() -> dict:
    """
    Query accurate_finance.db → dict keyed by normalized name.
    Returns: { normalized_name: { accurate_name, status, frequency, ... } }
    """
    conn = sqlite3.connect(ACCURATE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cutoff_12m = (TODAY - timedelta(days=365)).isoformat()

    cur.execute("""
        SELECT
            customer_name,
            COUNT(*) as total_count,
            MIN(invoice_date) as first_date,
            MAX(invoice_date) as last_date,
            SUM(CASE WHEN invoice_date >= ? THEN total_amount ELSE 0 END) as rev_12m,
            AVG(CASE WHEN lag_date IS NOT NULL
                     THEN julianday(invoice_date) - julianday(lag_date)
                END) as avg_interval
        FROM (
            SELECT customer_name, invoice_date, total_amount,
                   LAG(invoice_date) OVER (
                       PARTITION BY customer_name ORDER BY invoice_date
                   ) as lag_date
            FROM sales_invoices
            WHERE year >= 2024
        ) t
        GROUP BY customer_name
        HAVING total_count >= 2
        ORDER BY customer_name
    """, (cutoff_12m,))

    result = {}
    for r in cur.fetchall():
        name = r['customer_name']
        last_d = date.fromisoformat(r['last_date']) if r['last_date'] else None
        if last_d is None:
            status = 'cancelled'
        elif last_d >= ACTIVE_CUTOFF:
            status = 'active'
        elif last_d >= PAUSED_CUTOFF:
            status = 'paused'
        else:
            status = 'cancelled'

        avg_int = r['avg_interval']
        freq = _invoice_frequency(avg_int)
        rev_12m = r['rev_12m'] or 0

        key = _normalize(name)
        result[key] = {
            'accurate_name': name,
            'customer_status': status,
            'invoice_frequency': freq,
            'avg_interval_days': round(avg_int, 1) if avg_int else None,
            'last_invoice_date': last_d,
            'first_invoice_date': date.fromisoformat(r['first_date']) if r['first_date'] else None,
            'invoice_count_12m': r['total_count'],
            'total_revenue_12m': round(rev_12m, 2),
            'revenue_tier': _revenue_tier(rev_12m),
        }

    conn.close()
    return result


def derive_technician_ownership(cur) -> dict:
    """
    From snc_schedule_events (last 3 months), find dominant technician per client.
    Returns: { client_id: [(technician_id, visit_count), ...] sorted desc }
    """
    three_months_ago = (TODAY - timedelta(days=90)).isoformat()
    cur.execute("""
        SELECT client_id, technician_id, COUNT(*) as visits
        FROM snc_schedule_events
        WHERE start_date >= %s
          AND schedule_status IN ('scheduled', 'completed')
        GROUP BY client_id, technician_id
        ORDER BY client_id, visits DESC
    """, (three_months_ago,))
    rows = cur.fetchall()

    ownership = {}
    for r in rows:
        cid = r['client_id']
        if cid not in ownership:
            ownership[cid] = []
        ownership[cid].append((r['technician_id'], r['visits']))
    return ownership


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f"\nLoading Accurate customers from {ACCURATE_DB}...")
    accurate = load_accurate_customers()
    print(f"  {len(accurate)} customers loaded from Accurate")

    conn = psycopg.connect(**LOCAL_PG)
    cur = conn.cursor(row_factory=dict_row)

    # Load all snc_clients
    cur.execute("SELECT id, name FROM snc_clients ORDER BY name")
    clients = cur.fetchall()
    print(f"  {len(clients)} snc_clients in local DB")

    # Derive technician ownership
    ownership = derive_technician_ownership(cur)
    print(f"  Ownership computed for {len(ownership)} clients")

    if args.dry_run:
        print("\n=== DRY RUN — no writes ===")

    master_upserted = 0
    master_matched = 0
    master_unmatched = 0
    tech_upserted = 0

    for client in clients:
        client_id = client['id']
        client_name = client['name']
        norm = _normalize(client_name)

        # Try to find match in Accurate
        match = accurate.get(norm)

        # Fallback: partial match (client name contained in accurate name or vice versa)
        if not match:
            for acc_key, acc_val in accurate.items():
                if len(norm) >= 4 and (norm in acc_key or acc_key in norm):
                    match = acc_val
                    break

        if match:
            master_matched += 1
            # Determine status — if matched, use Accurate status
            status = match['customer_status']
            accurate_name = match['accurate_name']
            freq = match['invoice_frequency']
            avg_int = match['avg_interval_days']
            last_inv = match['last_invoice_date']
            first_inv = match['first_invoice_date']
            count_12m = match['invoice_count_12m']
            rev_12m = match['total_revenue_12m']
            tier = match['revenue_tier']
        else:
            master_unmatched += 1
            # No Accurate match → assume active (has schedule events), irregular
            status = 'active'
            accurate_name = None
            freq = 'irregular'
            avg_int = None
            last_inv = None
            first_inv = None
            count_12m = 0
            rev_12m = 0
            tier = 'C'

        if not args.dry_run:
            cur.execute("""
                INSERT INTO snc_customer_master
                    (snc_client_id, accurate_name, canonical_name, customer_status,
                     invoice_frequency, avg_interval_days, last_invoice_date,
                     first_invoice_date, invoice_count_12m, total_revenue_12m,
                     revenue_tier, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (snc_client_id) DO UPDATE SET
                    accurate_name      = EXCLUDED.accurate_name,
                    customer_status    = EXCLUDED.customer_status,
                    invoice_frequency  = EXCLUDED.invoice_frequency,
                    avg_interval_days  = EXCLUDED.avg_interval_days,
                    last_invoice_date  = EXCLUDED.last_invoice_date,
                    invoice_count_12m  = EXCLUDED.invoice_count_12m,
                    total_revenue_12m  = EXCLUDED.total_revenue_12m,
                    revenue_tier       = EXCLUDED.revenue_tier,
                    updated_at         = NOW()
            """, (client_id, accurate_name, client_name, status,
                  freq, avg_int, last_inv, first_inv, count_12m, rev_12m, tier))
        master_upserted += 1

        # Upsert technician ownership from schedule history
        tech_list = ownership.get(client_id, [])
        roles = ['primary', 'backup_1', 'backup_2']
        total_visits = sum(v for _, v in tech_list) or 1
        for i, (tech_id, visits) in enumerate(tech_list[:3]):
            role = roles[i]
            conf = round(visits / total_visits, 2)
            if not args.dry_run:
                cur.execute("""
                    INSERT INTO snc_customer_technician
                        (client_id, technician_id, role, confidence)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT (client_id, role) DO UPDATE SET
                        technician_id = EXCLUDED.technician_id,
                        confidence    = EXCLUDED.confidence
                """, (client_id, tech_id, role, conf))
            tech_upserted += 1

    if not args.dry_run:
        conn.commit()

    conn.close()

    print(f"\n{'DRY RUN ' if args.dry_run else ''}Results:")
    print(f"  Customer master upserted : {master_upserted}")
    print(f"    Matched to Accurate    : {master_matched}")
    print(f"    Unmatched (active def) : {master_unmatched}")
    print(f"  Technician ownership     : {tech_upserted}")

    # Print sample
    if args.dry_run:
        print("\nSample matches:")
        for client in clients[:10]:
            norm = _normalize(client['name'])
            match = accurate.get(norm)
            status = match['customer_status'] if match else '?'
            freq = match['invoice_frequency'] if match else '?'
            print(f"  [{status:10s}|{freq:10s}] {client['name']}")


if __name__ == '__main__':
    main()
