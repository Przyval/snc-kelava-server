"""
Deep import Accurate data → Finance module (tahap 2).
- AR payments dari sales_receipts (6,873 records)
- AR aging snapshot dari aging_piutang_26mei2026.csv (119 customers)
- Account balances dari trial balance (closing per tahun)
- Sales by customer → credit_limit
"""
import sqlite3, psycopg, csv, os
from psycopg.rows import dict_row
from datetime import date

SQLITE  = "/Users/michael/Downloads/Live SnC - Kelava Server/data/accurate_finance/accurate_finance.db"
AGING_CSV = "/Users/michael/Downloads/Live SnC - Kelava Server/data/aging_piutang_26mei2026.csv"

PG = dict(
    host=os.environ.get("LOCAL_ENT_HOST", "127.0.0.1"),
    port=int(os.environ.get("LOCAL_ENT_PORT", 5432)),
    dbname=os.environ.get("LOCAL_ENT_DB", "kil_enterprise"),
    user=os.environ.get("LOCAL_ENT_USER", "kil_ent"),
    password=os.environ.get("LOCAL_ENT_PASSWORD", "KilEnt2026!"),
)

IMPORT_YEARS = [2023, 2024, 2025, 2026]

def clean(v):
    if v is None: return 0.0
    try: return float(str(v).replace(",","").strip())
    except: return 0.0

def run():
    src = sqlite3.connect(SQLITE)
    src.row_factory = sqlite3.Row
    pg  = psycopg.connect(**PG, row_factory=dict_row, autocommit=False)
    cur = pg.cursor()

    # ── 1. AR PAYMENTS dari sales_receipts ────────────────────────
    print("\n[1] AR Payments dari sales_receipts...")
    n = skip = 0
    for yr in IMPORT_YEARS:
        rows = src.execute("""
            SELECT receipt_no, receipt_date, customer_name, amount
            FROM sales_receipts WHERE year=? ORDER BY receipt_date
        """, [yr]).fetchall()
        for r in rows:
            if not r["receipt_no"] or not r["receipt_date"]: continue
            amt = clean(r["amount"])
            if amt <= 0: continue
            nm = str(r["customer_name"]).strip()
            if not nm: continue
            cur.execute("INSERT INTO fin_customers(customer_name,is_active) VALUES(%s,TRUE) ON CONFLICT DO NOTHING", [nm])
            try:
                pay_date = date.fromisoformat(str(r["receipt_date"])[:10])
            except: continue
            result = cur.execute("""
                INSERT INTO fin_ar_payments
                    (receipt_no, payment_date, customer_name,
                     gross_amount, net_amount, payment_method, created_by)
                VALUES (%s,%s,%s,%s,%s,'TRANSFER','import_accurate')
                ON CONFLICT (receipt_no) DO NOTHING
            """, [r["receipt_no"], pay_date, nm, amt, amt])
            n += result.rowcount
    pg.commit()
    print(f"  {n} AR payments imported")

    # ── 2. DUNNING dari aging CSV ──────────────────────────────────
    print("\n[2] AR Aging / Dunning dari CSV (26 Mei 2026)...")
    n = 0
    with open(AGING_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nm = str(row.get("Pelanggan","")).strip()
            if not nm or nm.lower().startswith("total"): continue
            total = clean(row.get("Total", 0))
            if total <= 0: continue
            est_days = int(clean(row.get("Est.Hari", 0)))
            cur.execute("INSERT INTO fin_customers(customer_name,is_active) VALUES(%s,TRUE) ON CONFLICT DO NOTHING", [nm])
            cur.execute("""
                INSERT INTO fin_dunning_runs
                    (run_date, customer_name, dunning_level, total_outstanding, overdue_days, created_by)
                VALUES ('2026-05-26', %s,
                        CASE WHEN %s > 365 THEN 4 WHEN %s > 180 THEN 3 WHEN %s > 90 THEN 2 ELSE 1 END,
                        %s, %s, 'import_accurate')
                ON CONFLICT DO NOTHING
            """, [nm, est_days, est_days, est_days, total, est_days])
            n += 1
    pg.commit()
    print(f"  {n} dunning records (aging snapshot)")

    # ── 3. ACCOUNT BALANCES dari trial balance ────────────────────
    print("\n[3] Account balances (closing per tahun)...")
    n = 0
    for yr in IMPORT_YEARS:
        rows = src.execute("""
            SELECT account_code, opening_debit, opening_credit,
                   change_debit, change_credit, closing_debit, closing_credit
            FROM trial_balance WHERE year=? ORDER BY account_code
        """, [yr]).fetchall()
        period = cur.execute(
            "SELECT id FROM fin_fiscal_periods WHERE year=%s AND period=12", [yr]
        ).fetchone()
        if not period: continue
        period_id = period["id"]
        for r in rows:
            code = str(r["account_code"]).strip()
            acc = cur.execute("SELECT code FROM fin_accounts WHERE code=%s", [code]).fetchone()
            if not acc: continue
            cur.execute("""
                INSERT INTO fin_account_balances
                    (period_id, account_code, opening_debit, opening_credit,
                     period_debit, period_credit, closing_debit, closing_credit)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (period_id, account_code, cost_center_id) DO UPDATE
                    SET closing_debit=EXCLUDED.closing_debit,
                        closing_credit=EXCLUDED.closing_credit,
                        period_debit=EXCLUDED.period_debit,
                        period_credit=EXCLUDED.period_credit
            """, [period_id, code,
                  clean(r["opening_debit"]), clean(r["opening_credit"]),
                  clean(r["change_debit"]), clean(r["change_credit"]),
                  clean(r["closing_debit"]), clean(r["closing_credit"])])
            n += 1
    pg.commit()
    print(f"  {n} account balance records")

    # ── 4. SALES BY CUSTOMER → credit_limit ──────────────────────
    print("\n[4] Update credit_limit dari sales volume...")
    n = 0
    for yr in [2024, 2025]:
        rows = src.execute("SELECT customer_name, sales_amount FROM sales_by_customer WHERE year=?", [yr]).fetchall()
        for r in rows:
            nm = str(r["customer_name"]).strip()
            amt = clean(r["sales_amount"])
            if not nm or amt <= 0: continue
            cur.execute("INSERT INTO fin_customers(customer_name,is_active) VALUES(%s,TRUE) ON CONFLICT DO NOTHING", [nm])
            cur.execute("""
                UPDATE fin_customers
                SET credit_limit = GREATEST(credit_limit, %s)
                WHERE customer_name = %s
            """, [amt * 0.3, nm])
            n += 1
    pg.commit()
    print(f"  {n} credit_limit updates")

    # ── 5. UPDATE outstanding di sales_invoices ───────────────────
    print("\n[5] Recalculate outstanding invoices...")
    n = cur.execute("""
        UPDATE fin_sales_invoices
        SET outstanding = total - paid_amount,
            status = CASE
                WHEN paid_amount >= total THEN 'PAID'
                WHEN paid_amount > 0 THEN 'PARTIAL'
                WHEN invoice_date < CURRENT_DATE - 30 THEN 'OVERDUE'
                ELSE 'POSTED'
            END
        WHERE status NOT IN ('CANCELLED','VOID')
    """).rowcount
    pg.commit()
    print(f"  {n} invoices recalculated")

    # ── SUMMARY ───────────────────────────────────────────────────
    print("\n" + "="*50)
    print("DEEP IMPORT SELESAI")
    print("="*50)
    for tbl, col in [
        ("fin_ar_payments","id"), ("fin_dunning_runs","id"),
        ("fin_account_balances","id"), ("fin_customers","customer_name"),
        ("fin_sales_invoices","id"),
    ]:
        c = cur.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()["c"]
        print(f"  {tbl:<35} {c:>7,} rows")

    pg.close(); src.close()

if __name__ == "__main__":
    run()
