"""
Import data Accurate ke Finance module (kil_enterprise DB).
Sumber: data/accurate_finance/accurate_finance.db
Target: kil_enterprise (PostgreSQL)
"""
import sqlite3
import psycopg
from psycopg.rows import dict_row
import os
import calendar as cal
from datetime import date, timedelta

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "../../../data/accurate_finance/accurate_finance.db")

PG = dict(
    host=os.environ.get("LOCAL_ENT_HOST", "127.0.0.1"),
    port=int(os.environ.get("LOCAL_ENT_PORT", 5432)),
    dbname=os.environ.get("LOCAL_ENT_DB", "kil_enterprise"),
    user=os.environ.get("LOCAL_ENT_USER", "kil_ent"),
    password=os.environ.get("LOCAL_ENT_PASSWORD", "KilEnt2026!"),
)

IMPORT_YEARS = [2023, 2024, 2025, 2026]

def get_account_type(code):
    c = str(code).replace(".", "")
    if c.startswith("11010"): return "CASH"
    if c.startswith("1103"): return "AR"
    if c.startswith("210"): return "AP"
    if c[:1] in ("1",): return "ASSET"
    if c[:1] in ("2",): return "LIABILITY"
    if c[:1] in ("3",): return "EQUITY"
    if c[:1] in ("4",): return "REVENUE"
    if c[:1] in ("5",): return "COGS"
    return "EXPENSE"

def clean(v):
    if v is None: return 0.0
    try: return float(v)
    except: return 0.0

def next_entry_no(cur):
    r = cur.execute("SELECT COALESCE(MAX(CAST(NULLIF(regexp_replace(entry_no,'[^0-9]','','g'),'') AS BIGINT)),0)+1 AS n FROM fin_journal_entries").fetchone()
    return f"JE-IMPORT-{r['n']:06d}"

def run():
    print("Connecting...")
    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row
    pg  = psycopg.connect(**PG, row_factory=dict_row, autocommit=False)
    cur = pg.cursor()

    # ── 1. FISCAL PERIODS ──────────────────────────────────────────
    print("\n[1] Fiscal periods 2023–2026...")
    for yr in IMPORT_YEARS:
        for mo in range(1, 13):
            last = cal.monthrange(yr, mo)[1]
            s = date(yr, mo, 1); e = date(yr, mo, last)
            if yr < 2025:        st = "LOCKED"
            elif yr == 2025:     st = "CLOSED"
            elif mo <= 5:        st = "OPEN"
            else:                st = "FUTURE"
            cur.execute("""
                INSERT INTO fin_fiscal_periods (year, period, start_date, end_date, status)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (year,period) DO UPDATE SET status=EXCLUDED.status
            """, [yr, mo, s, e, st])
    pg.commit(); print("  OK")

    # ── 2. CHART OF ACCOUNTS ───────────────────────────────────────
    print("\n[2] Chart of accounts...")
    rows = src.execute("SELECT DISTINCT account_code, account_name FROM trial_balance ORDER BY account_code").fetchall()
    n = 0
    for r in rows:
        code = str(r["account_code"]).strip()
        name = str(r["account_name"]).strip()
        if not code or not name: continue
        atype  = get_account_type(code)
        level  = len(code.replace(".", ""))
        detail = level >= 6
        normal = "CREDIT" if atype in ("LIABILITY","EQUITY","REVENUE") else "DEBIT"
        # parent = first 4 digits if level > 4
        parent = None
        if level > 4:
            parent_code = code[:4]
            p = cur.execute("SELECT code FROM fin_accounts WHERE code=%s", [parent_code]).fetchone()
            parent = parent_code if p else None
        cur.execute("""
            INSERT INTO fin_accounts (code, name, account_type, normal_balance, level, is_detail, is_active, parent_code)
            VALUES (%s,%s,%s,%s,%s,%s,TRUE,%s)
            ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, account_type=EXCLUDED.account_type
        """, [code, name, atype, normal, min(level,4), detail, parent])
        n += 1
    pg.commit(); print(f"  {n} accounts")

    # ── 3. CUSTOMERS ───────────────────────────────────────────────
    print("\n[3] Customers from AR ledger...")
    rows = src.execute("SELECT DISTINCT customer_name FROM ar_ledger WHERE customer_name!='' ORDER BY customer_name").fetchall()
    n = 0
    for r in rows:
        nm = str(r["customer_name"]).strip()
        if not nm: continue
        cur.execute("""
            INSERT INTO fin_customers (customer_name, is_active)
            VALUES (%s, TRUE)
            ON CONFLICT (customer_name) DO NOTHING
        """, [nm]); n += 1
    pg.commit(); print(f"  {n} customers")

    # ── 4. VENDORS ─────────────────────────────────────────────────
    print("\n[4] Vendors from AP ledger...")
    rows = src.execute("SELECT DISTINCT vendor_name FROM ap_ledger WHERE vendor_name!='' ORDER BY vendor_name").fetchall()
    n = 0
    for r in rows:
        nm = str(r["vendor_name"]).strip()
        if not nm: continue
        cur.execute("""
            INSERT INTO fin_vendors (name, is_active)
            VALUES (%s, TRUE)
            ON CONFLICT (name) DO NOTHING
        """, [nm]); n += 1
    pg.commit(); print(f"  {n} vendors")

    # ── 5. SALES INVOICES ──────────────────────────────────────────
    print("\n[5] Sales invoices...")
    n = 0
    for yr in IMPORT_YEARS:
        rows = src.execute("""
            SELECT invoice_no, invoice_date, customer_name, total_amount
            FROM sales_invoices WHERE year=? ORDER BY invoice_date
        """, [yr]).fetchall()
        for r in rows:
            if not r["invoice_no"] or not r["invoice_date"]: continue
            amt = clean(r["total_amount"])
            if amt <= 0: continue
            nm = str(r["customer_name"]).strip()
            # ensure customer exists
            cur.execute("INSERT INTO fin_customers(customer_name,is_active) VALUES(%s,TRUE) ON CONFLICT DO NOTHING", [nm])
            try:
                inv_date = date.fromisoformat(str(r["invoice_date"])[:10])
            except: continue
            period = cur.execute(
                "SELECT id FROM fin_fiscal_periods WHERE year=%s AND period=%s",
                [inv_date.year, inv_date.month]
            ).fetchone()
            period_id = period["id"] if period else None
            due = inv_date + timedelta(days=30)
            status = "PAID" if yr < 2026 else "POSTED"
            paid = amt if status == "PAID" else 0
            cur.execute("""
                INSERT INTO fin_sales_invoices
                    (invoice_no, invoice_date, due_date, customer_name, period_id,
                     subtotal, dpp, total, paid_amount, outstanding, status, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'import_accurate')
                ON CONFLICT (invoice_no) DO NOTHING
            """, [r["invoice_no"], inv_date, due, nm, period_id,
                  amt, amt, amt, paid, amt-paid, status])
            n += 1
    pg.commit(); print(f"  {n} sales invoices")

    # ── 6. PURCHASE INVOICES ───────────────────────────────────────
    print("\n[6] Purchase invoices...")
    n = 0
    for yr in IMPORT_YEARS:
        rows = src.execute("""
            SELECT invoice_no, invoice_date, vendor_name, total_amount
            FROM purchase_invoices WHERE year=? ORDER BY invoice_date
        """, [yr]).fetchall()
        for r in rows:
            if not r["invoice_no"] or not r["invoice_date"]: continue
            amt = clean(r["total_amount"])
            if amt <= 0: continue
            nm = str(r["vendor_name"]).strip()
            vendor = cur.execute("SELECT id FROM fin_vendors WHERE name=%s", [nm]).fetchone()
            if not vendor:
                cur.execute("INSERT INTO fin_vendors(name,is_active) VALUES(%s,TRUE) RETURNING id", [nm])
                vendor = cur.fetchone()
            try:
                inv_date = date.fromisoformat(str(r["invoice_date"])[:10])
            except: continue
            period = cur.execute(
                "SELECT id FROM fin_fiscal_periods WHERE year=%s AND period=%s",
                [inv_date.year, inv_date.month]
            ).fetchone()
            period_id = period["id"] if period else None
            due = inv_date + timedelta(days=30)
            status = "PAID" if yr < 2026 else "RECEIVED"
            paid = amt if status == "PAID" else 0
            cur.execute("""
                INSERT INTO fin_purchase_invoices
                    (invoice_no, invoice_date, due_date, vendor_id, period_id,
                     subtotal, total_gross, total_net, paid_amount, outstanding, status, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'import_accurate')
                ON CONFLICT (invoice_no) DO NOTHING
            """, [r["invoice_no"], inv_date, due, vendor["id"], period_id,
                  amt, amt, amt, paid, amt-paid, status])
            n += 1
    pg.commit(); print(f"  {n} purchase invoices")

    # ── 7. JOURNAL ENTRIES (annual trial balance) ──────────────────
    print("\n[7] Journal entries from trial balance...")
    n = 0
    for yr in IMPORT_YEARS:
        memo = f"Trial Balance Import {yr} (Accurate)"
        if cur.execute("SELECT id FROM fin_journal_entries WHERE description=%s", [memo]).fetchone():
            print(f"  {yr}: skip (exists)"); continue
        period = cur.execute("SELECT id FROM fin_fiscal_periods WHERE year=%s AND period=1", [yr]).fetchone()
        if not period: continue
        rows = src.execute("""
            SELECT account_code, account_name, change_debit, change_credit
            FROM trial_balance WHERE year=? AND (change_debit>0 OR change_credit>0)
            ORDER BY account_code
        """, [yr]).fetchall()
        if not rows: continue
        total_dr = sum(clean(r["change_debit"]) for r in rows)
        eno = next_entry_no(cur)
        cur.execute("""
            INSERT INTO fin_journal_entries
                (entry_no, entry_date, period_id, description, entry_type,
                 total_debit, total_credit, status, created_by)
            VALUES (%s,%s,%s,%s,'MANUAL',%s,%s,'POSTED','import_accurate')
            RETURNING id
        """, [eno, date(yr, 1, 1), period["id"], memo, total_dr, total_dr])
        je_id = cur.fetchone()["id"]
        line_no = 1
        for r in rows:
            code = str(r["account_code"]).strip()
            dr = clean(r["change_debit"]); cr = clean(r["change_credit"])
            for amt, side in [(dr, "debit"), (cr, "credit")]:
                if amt <= 0: continue
                cur.execute("""
                    INSERT INTO fin_gl_lines
                        (journal_entry_id, line_no, account_code, debit, credit, description)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, [je_id, line_no, code,
                      amt if side=="debit" else 0,
                      amt if side=="credit" else 0,
                      r["account_name"]])
                line_no += 1
        pg.commit(); n += 1; print(f"  {yr}: {line_no-1} GL lines")
    print(f"  {n} journal entries created")

    # ── 8. COST CENTERS ────────────────────────────────────────────
    print("\n[8] Cost centers...")
    for code, name, ctype in [
        ("OPS","Operasional","DEPT"),
        ("ADM","Administrasi & Umum","DEPT"),
        ("SLS","Sales & Marketing","DEPT"),
        ("FIN","Finance & Accounting","DEPT"),
        ("HRD","Human Resources","DEPT"),
    ]:
        cur.execute("""
            INSERT INTO fin_cost_centers (code, name, center_type, is_active)
            VALUES (%s,%s,%s,TRUE) ON CONFLICT (code) DO NOTHING
        """, [code, name, ctype])
    pg.commit(); print("  5 cost centers")

    # ── 9. PROFIT CENTERS ──────────────────────────────────────────
    print("\n[9] Profit centers...")
    for code, name in [
        ("PRC","Pest Control Regular"),
        ("TC","Termite Control"),
        ("FUM","Fumigasi"),
        ("PROD","Penjualan Produk"),
    ]:
        cur.execute("""
            INSERT INTO fin_profit_centers (code, name, is_active)
            VALUES (%s,%s,TRUE) ON CONFLICT (code) DO NOTHING
        """, [code, name])
    pg.commit(); print("  4 profit centers")

    # ── SUMMARY ────────────────────────────────────────────────────
    print("\n" + "="*50)
    print("IMPORT SELESAI")
    print("="*50)
    for tbl in ["fin_accounts","fin_customers","fin_vendors",
                "fin_sales_invoices","fin_purchase_invoices",
                "fin_journal_entries","fin_fiscal_periods",
                "fin_cost_centers","fin_profit_centers"]:
        c = cur.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()["c"]
        print(f"  {tbl:<35} {c:>6,} rows")

    pg.close(); src.close()

if __name__ == "__main__":
    run()
