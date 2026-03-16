#!/usr/bin/env python3
"""
Step 2 ETL Script: Build Local Analytics Warehouse
================================================
Loads CSV extracts into SQLite and builds fact_visit_enriched + dq_flags tables.

Output:
- analytics/snc_analytics.db (SQLite, compatible alternative to DuckDB)
- analytics/kpi/fact_visit_enriched.parquet (if pyarrow available, else CSV)
- analytics/kpi/dq_flags.parquet
- analytics/reports/STEP2_DATA_QUALITY_BASELINE.md
"""

import sqlite3
import csv
import os
from datetime import datetime
from collections import defaultdict

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STAGING_DIR = os.path.join(BASE_DIR, 'analytics/staging')
DB_PATH = os.path.join(BASE_DIR, 'analytics/snc_analytics.db')
KPI_DIR = os.path.join(BASE_DIR, 'analytics/kpi')
REPORTS_DIR = os.path.join(BASE_DIR, 'analytics/reports')

os.makedirs(KPI_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def load_csv_to_table(conn, csv_path, table_name, create_sql=None):
    """Load CSV file into SQLite table"""
    log(f"Loading {csv_path} -> {table_name}")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        
        # Create table if SQL provided
        if create_sql:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.execute(create_sql)
        else:
            # Auto-create table with TEXT columns
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            cols = ', '.join([f'"{h}" TEXT' for h in headers])
            conn.execute(f"CREATE TABLE {table_name} ({cols})")
        
        # Insert rows
        placeholders = ', '.join(['?' for _ in headers])
        insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"
        
        rows = list(reader)
        conn.executemany(insert_sql, rows)
        conn.commit()
        
        log(f"  -> Loaded {len(rows)} rows")
        return len(rows)

def main():
    log("=" * 60)
    log("STEP 2: Building Local Analytics Warehouse")
    log("=" * 60)
    
    # Connect to SQLite
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # ============================================================
    # 2.2 Load CSVs to Staging Tables
    # ============================================================
    log("\n--- 2.2 Loading CSVs to Staging Tables ---")
    
    row_counts = {}
    
    # Load road_plan_base
    row_counts['stg_road_plan'] = load_csv_to_table(
        conn, 
        os.path.join(STAGING_DIR, 'road_plan_base.csv'),
        'stg_road_plan'
    )
    
    # Load visit_base
    row_counts['stg_visit'] = load_csv_to_table(
        conn,
        os.path.join(STAGING_DIR, 'visit_base.csv'),
        'stg_visit'
    )
    
    # Load foto_count_agg
    row_counts['stg_foto_count'] = load_csv_to_table(
        conn,
        os.path.join(STAGING_DIR, 'foto_count_agg.csv'),
        'stg_foto_count'
    )
    
    # Load area_agg
    row_counts['stg_area_agg'] = load_csv_to_table(
        conn,
        os.path.join(STAGING_DIR, 'area_agg.csv'),
        'stg_area_agg'
    )
    
    # Load subarea_agg
    row_counts['stg_subarea_agg'] = load_csv_to_table(
        conn,
        os.path.join(STAGING_DIR, 'subarea_agg.csv'),
        'stg_subarea_agg'
    )
    
    # Load dim_user
    row_counts['dim_user'] = load_csv_to_table(
        conn,
        os.path.join(STAGING_DIR, 'dim_user.csv'),
        'dim_user'
    )
    
    # Load dim_customer
    row_counts['dim_customer'] = load_csv_to_table(
        conn,
        os.path.join(STAGING_DIR, 'dim_customer.csv'),
        'dim_customer'
    )
    
    # Load dim_kontrak
    row_counts['dim_kontrak'] = load_csv_to_table(
        conn,
        os.path.join(STAGING_DIR, 'dim_kontrak.csv'),
        'dim_kontrak'
    )
    
    # DQ Check: road_plan uniqueness
    log("\n--- DQ Check: road_plan uniqueness ---")
    result = conn.execute("""
        SELECT 
            COUNT(*) as total_rows,
            COUNT(DISTINCT road_plan_id) as unique_road_plans
        FROM stg_road_plan
    """).fetchone()
    log(f"  Total rows: {result['total_rows']}, Unique road_plans: {result['unique_road_plans']}")
    assert result['total_rows'] == result['unique_road_plans'], "FAIL: Duplicate road_plan_ids found!"
    log("  ✓ PASS: No duplicate road_plan_ids")
    
    # ============================================================
    # 2.3 Resolve Visit per Road Plan (anti double counting)
    # ============================================================
    log("\n--- 2.3 Resolving Visit per Road Plan ---")
    
    # First, create a normalized view of timestamps (strip timezone suffix)
    # PostgreSQL format: 2026-01-02 22:05:56+07 -> 2026-01-02 22:05:56
    conn.execute("""
        CREATE TABLE visit_normalized AS
        SELECT 
            visit_id,
            road_plan_id,
            id_user,
            id_customer,
            -- Normalize check_in: strip timezone suffix like +07
            CASE 
                WHEN check_in LIKE '%+%' THEN SUBSTR(check_in, 1, INSTR(check_in, '+') - 1)
                WHEN check_in LIKE '%-%' AND LENGTH(check_in) > 19 
                     AND check_in NOT LIKE '%-%-% %:%:%' THEN SUBSTR(check_in, 1, 19)
                ELSE check_in
            END as check_in_norm,
            -- Normalize check_out: strip timezone suffix
            CASE 
                WHEN check_out LIKE '%+%' THEN SUBSTR(check_out, 1, INSTR(check_out, '+') - 1)
                WHEN check_out LIKE '%-%' AND LENGTH(check_out) > 19 
                     AND check_out NOT LIKE '%-%-% %:%:%' THEN SUBSTR(check_out, 1, 19)
                ELSE check_out
            END as check_out_norm,
            check_in as check_in_orig,
            check_out as check_out_orig
        FROM stg_visit
        WHERE road_plan_id IS NOT NULL AND road_plan_id != ''
    """)
    conn.commit()
    
    conn.execute("""
        CREATE TABLE visit_agg AS
        SELECT 
            road_plan_id,
            COUNT(*) as visit_count,
            MIN(check_in_norm) as check_in_first,
            MAX(check_out_norm) as check_out_last,
            SUM(CASE WHEN check_out_norm IS NULL OR check_out_norm = '' THEN 1 ELSE 0 END) as null_checkout_count,
            -- Duration calculation (in minutes) using normalized timestamps
            CASE 
                WHEN MAX(check_out_norm) IS NOT NULL AND MAX(check_out_norm) != '' 
                     AND MIN(check_in_norm) IS NOT NULL AND MIN(check_in_norm) != ''
                THEN ROUND((julianday(MAX(check_out_norm)) - julianday(MIN(check_in_norm))) * 24 * 60, 2)
                ELSE NULL
            END as duration_min
        FROM visit_normalized
        GROUP BY road_plan_id
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) as cnt FROM visit_agg").fetchone()
    log(f"  -> Created visit_agg: {result['cnt']} unique road_plans with visits")
    
    # Check multi-visit road_plans
    result = conn.execute("""
        SELECT COUNT(*) as cnt FROM visit_agg WHERE visit_count > 1
    """).fetchone()
    log(f"  -> Road plans with multiple visits: {result['cnt']}")
    
    # ============================================================
    # 2.4 Build fact_visit_enriched (1 row per road_plan_id)
    # ============================================================
    log("\n--- 2.4 Building fact_visit_enriched ---")
    
    conn.execute("""
        CREATE TABLE fact_visit_enriched AS
        SELECT 
            -- Identifiers
            rp.road_plan_id,
            CAST(rp.id_user AS INTEGER) as user_id,
            CAST(rp.id_customer AS INTEGER) as customer_id,
            CAST(rp.id_kontrak AS INTEGER) as kontrak_id,
            
            -- Scheduling
            rp.visit_date,
            rp.status,
            rp.type,
            rp.title,
            rp.no_ra,
            rp.is_cancel,
            
            -- Actual (from visit_agg)
            va.check_in_first,
            va.check_out_last,
            va.duration_min,
            COALESCE(va.visit_count, 0) as visit_count,
            COALESCE(va.null_checkout_count, 0) as null_checkout_count,
            
            -- Evidence
            COALESCE(CAST(fc.foto_count AS INTEGER), 0) as foto_count,
            COALESCE(CAST(aa.area_count AS INTEGER), 0) as area_count,
            COALESCE(CAST(aa.treatment_type_count AS INTEGER), 0) as treatment_type_count,
            aa.treatment_list,
            
            -- Derived: visit_day
            CASE 
                WHEN va.check_in_first IS NOT NULL AND va.check_in_first != ''
                THEN DATE(va.check_in_first)
                ELSE NULL
            END as visit_day,
            
            -- Derived: weekday (0=Sun, 1=Mon, ..., 6=Sat)
            CASE 
                WHEN va.check_in_first IS NOT NULL AND va.check_in_first != ''
                THEN CAST(strftime('%w', va.check_in_first) AS INTEGER)
                ELSE NULL
            END as weekday,
            
            -- Derived: is_working_day (Mon-Sat = 1-6)
            CASE 
                WHEN va.check_in_first IS NOT NULL AND va.check_in_first != ''
                     AND CAST(strftime('%w', va.check_in_first) AS INTEGER) BETWEEN 1 AND 6
                THEN 1
                ELSE 0
            END as is_working_day,
            
            -- Derived: is_complete
            CASE WHEN rp.status = 'Selesai' THEN 1 ELSE 0 END as is_complete,
            
            -- Derived: has_visit
            CASE WHEN va.road_plan_id IS NOT NULL THEN 1 ELSE 0 END as has_visit,
            
            -- Derived: check_in_hour
            CASE 
                WHEN va.check_in_first IS NOT NULL AND va.check_in_first != ''
                THEN CAST(strftime('%H', va.check_in_first) AS INTEGER)
                ELSE NULL
            END as check_in_hour,
            
            -- User/Customer info
            u.fullname as technician_name,
            c.name as customer_name,
            c.new_city as customer_city,
            
            -- Kontrak info
            k.no_kontrak
            
        FROM stg_road_plan rp
        LEFT JOIN visit_agg va ON rp.road_plan_id = va.road_plan_id
        LEFT JOIN stg_foto_count fc ON rp.road_plan_id = fc.road_plan_id
        LEFT JOIN stg_area_agg aa ON rp.road_plan_id = aa.road_plan_id
        LEFT JOIN dim_user u ON rp.id_user = u.user_id
        LEFT JOIN dim_customer c ON rp.id_customer = c.customer_id
        LEFT JOIN dim_kontrak k ON rp.id_kontrak = k.kontrak_id
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) as cnt FROM fact_visit_enriched").fetchone()
    log(f"  -> Created fact_visit_enriched: {result['cnt']} rows")
    
    # ============================================================
    # 2.5 Generate DQ Flags
    # ============================================================
    log("\n--- 2.5 Generating DQ Flags ---")
    
    conn.execute("""
        CREATE TABLE dq_flags AS
        SELECT 
            road_plan_id,
            
            -- is_valid_duration (5-480 minutes)
            CASE 
                WHEN duration_min IS NOT NULL 
                     AND duration_min >= 5 
                     AND duration_min <= 480 
                THEN 1 ELSE 0 
            END as is_valid_duration,
            
            -- is_valid_checkin
            CASE 
                WHEN check_in_first IS NOT NULL AND check_in_first != '' 
                THEN 1 ELSE 0 
            END as is_valid_checkin,
            
            -- is_valid_checkout
            CASE 
                WHEN check_out_last IS NOT NULL AND check_out_last != ''
                     AND check_in_first IS NOT NULL AND check_in_first != ''
                     AND check_out_last >= check_in_first
                THEN 1 ELSE 0 
            END as is_valid_checkout,
            
            -- is_photo_compliant (foto_count >= 1)
            CASE WHEN foto_count >= 1 THEN 1 ELSE 0 END as is_photo_compliant,
            
            -- is_working_day
            is_working_day,
            
            -- is_complete
            is_complete,
            
            -- is_suspect_time (check_in hour in 21-23)
            CASE 
                WHEN check_in_hour IN (21, 22, 23) 
                THEN 1 ELSE 0 
            END as is_suspect_time,
            
            -- has_multi_visit
            CASE WHEN visit_count > 1 THEN 1 ELSE 0 END as has_multi_visit,
            
            -- has_null_checkout
            CASE WHEN null_checkout_count > 0 THEN 1 ELSE 0 END as has_null_checkout,
            
            -- Duration traffic light
            CASE 
                WHEN duration_min IS NULL THEN 'SUSPECT_NO_CHECKOUT'
                WHEN duration_min < 0 THEN 'SUSPECT_NEGATIVE'
                WHEN duration_min > 600 THEN 'SUSPECT_OVERNIGHT'
                WHEN duration_min = 0 THEN 'WARNING_ZERO'
                WHEN duration_min < 5 THEN 'WARNING_TOO_SHORT'
                WHEN duration_min > 480 THEN 'WARNING_LONG'
                ELSE 'VALID'
            END as duration_status,
            
            -- Overall KPI eligible
            CASE 
                WHEN is_complete = 1 
                     AND check_in_first IS NOT NULL AND check_in_first != ''
                     AND duration_min IS NOT NULL
                     AND duration_min >= 5 AND duration_min <= 600
                THEN 1 ELSE 0 
            END as is_kpi_eligible
            
        FROM fact_visit_enriched
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) as cnt FROM dq_flags").fetchone()
    log(f"  -> Created dq_flags: {result['cnt']} rows")
    
    # ============================================================
    # 2.6 Generate Data Quality Baseline Report
    # ============================================================
    log("\n--- 2.6 Generating Data Quality Baseline Report ---")
    
    report_lines = []
    report_lines.append("# 📊 STEP 2: Data Quality Baseline Report")
    report_lines.append("")
    report_lines.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    report_lines.append(f"> **Database:** {DB_PATH}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    
    # Extraction Summary
    report_lines.append("## 1. Extraction Summary")
    report_lines.append("")
    report_lines.append("| Table | Rows | Size |")
    report_lines.append("|-------|------|------|")
    for table, count in row_counts.items():
        csv_name = table.replace('stg_', '').replace('dim_', 'dim_') + '.csv'
        if table.startswith('stg_'):
            csv_name = table.replace('stg_', '') 
            if csv_name == 'road_plan':
                csv_name = 'road_plan_base'
            elif csv_name == 'visit':
                csv_name = 'visit_base'
            elif csv_name == 'foto_count':
                csv_name = 'foto_count_agg'
            csv_name += '.csv'
        else:
            csv_name = table + '.csv'
        
        csv_path = os.path.join(STAGING_DIR, csv_name)
        size = os.path.getsize(csv_path) if os.path.exists(csv_path) else 0
        size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/1024/1024:.1f} MB"
        report_lines.append(f"| {table} | {count:,} | {size_str} |")
    report_lines.append("")
    
    # Date Range
    result = conn.execute("""
        SELECT 
            MIN(visit_date) as min_visit_date,
            MAX(visit_date) as max_visit_date,
            MIN(check_in_first) as min_check_in,
            MAX(check_in_first) as max_check_in
        FROM fact_visit_enriched
    """).fetchone()
    report_lines.append("**Date Range:**")
    report_lines.append(f"- visit_date: `{result['min_visit_date']}` to `{result['max_visit_date']}`")
    report_lines.append(f"- check_in: `{result['min_check_in']}` to `{result['max_check_in']}`")
    report_lines.append("")
    
    # Coverage Statistics
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 2. Coverage Statistics")
    report_lines.append("")
    
    # Road plan without visit
    result = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN f.is_complete = 1 AND f.has_visit = 0 THEN 1 ELSE 0 END) as complete_no_visit,
            SUM(CASE WHEN f.has_visit = 1 AND d.is_valid_checkout = 0 THEN 1 ELSE 0 END) as visit_no_checkout,
            SUM(CASE WHEN f.foto_count = 0 THEN 1 ELSE 0 END) as no_foto
        FROM fact_visit_enriched f
        JOIN dq_flags d ON f.road_plan_id = d.road_plan_id
    """).fetchone()
    
    total = result['total']
    report_lines.append("| Metric | Count | % |")
    report_lines.append("|--------|-------|---|")
    report_lines.append(f"| Complete but no visit | {result['complete_no_visit']:,} | {100*result['complete_no_visit']/total:.2f}% |")
    report_lines.append(f"| Has visit but no checkout | {result['visit_no_checkout']:,} | {100*result['visit_no_checkout']/total:.2f}% |")
    report_lines.append(f"| No photos (foto_count=0) | {result['no_foto']:,} | {100*result['no_foto']/total:.2f}% |")
    report_lines.append("")
    
    # Duration Stats by Type
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 3. Duration Statistics by Type")
    report_lines.append("")
    
    # Using SQLite window functions for percentiles (approximate with NTILE)
    results = conn.execute("""
        WITH duration_data AS (
            SELECT 
                type,
                duration_min,
                ROW_NUMBER() OVER (PARTITION BY type ORDER BY duration_min) as rn,
                COUNT(*) OVER (PARTITION BY type) as cnt
            FROM fact_visit_enriched
            WHERE duration_min IS NOT NULL AND duration_min > 0 AND duration_min < 1440
        )
        SELECT 
            type,
            COUNT(*) as count,
            ROUND(AVG(duration_min), 1) as avg_min,
            MIN(duration_min) as min_min,
            MAX(duration_min) as max_min
        FROM duration_data
        GROUP BY type
        ORDER BY count DESC
    """).fetchall()
    
    report_lines.append("| Type | Count | Avg (min) | Min | Max |")
    report_lines.append("|------|-------|-----------|-----|-----|")
    for row in results:
        report_lines.append(f"| {row['type'] or 'NULL'} | {row['count']:,} | {row['avg_min']} | {row['min_min']:.0f} | {row['max_min']:.0f} |")
    report_lines.append("")
    
    # Top 20 Duration Outliers
    report_lines.append("### Top 20 Duration Outliers")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            road_plan_id,
            technician_name,
            customer_name,
            type,
            ROUND(duration_min, 1) as duration_min,
            check_in_first,
            check_out_last
        FROM fact_visit_enriched
        WHERE duration_min IS NOT NULL
        ORDER BY duration_min DESC
        LIMIT 20
    """).fetchall()
    
    report_lines.append("| RP ID | Technician | Customer | Type | Duration (min) |")
    report_lines.append("|-------|------------|----------|------|----------------|")
    for row in results:
        report_lines.append(f"| {row['road_plan_id']} | {row['technician_name'][:20] if row['technician_name'] else 'N/A'} | {row['customer_name'][:20] if row['customer_name'] else 'N/A'} | {row['type']} | {row['duration_min']:,.0f} |")
    report_lines.append("")
    
    # Time Anomalies
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 4. Time Anomalies (Check-in Hour Distribution)")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            check_in_hour,
            COUNT(*) as count
        FROM fact_visit_enriched
        WHERE check_in_hour IS NOT NULL
        GROUP BY check_in_hour
        ORDER BY check_in_hour
    """).fetchall()
    
    report_lines.append("| Hour | Count | Bar |")
    report_lines.append("|------|-------|-----|")
    max_count = max(r['count'] for r in results) if results else 1
    for row in results:
        bar_len = int(30 * row['count'] / max_count)
        bar = '█' * bar_len
        flag = " ⚠️" if row['check_in_hour'] in (21, 22, 23) else ""
        report_lines.append(f"| {row['check_in_hour']:02d}:00 | {row['count']:,} | {bar}{flag} |")
    report_lines.append("")
    
    # Suspect time by type and top customers
    report_lines.append("### Suspect Time (21:00-23:00) by Type")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            f.type,
            COUNT(*) as suspect_count,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as pct
        FROM fact_visit_enriched f
        JOIN dq_flags d ON f.road_plan_id = d.road_plan_id
        WHERE d.is_suspect_time = 1
        GROUP BY f.type
        ORDER BY suspect_count DESC
    """).fetchall()
    
    report_lines.append("| Type | Suspect Count | % of Suspect |")
    report_lines.append("|------|---------------|--------------|")
    for row in results:
        report_lines.append(f"| {row['type'] or 'NULL'} | {row['suspect_count']:,} | {row['pct']:.1f}% |")
    report_lines.append("")
    
    report_lines.append("### Top 10 Customers with Suspect Time")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            f.customer_name,
            COUNT(*) as suspect_count
        FROM fact_visit_enriched f
        JOIN dq_flags d ON f.road_plan_id = d.road_plan_id
        WHERE d.is_suspect_time = 1
        GROUP BY f.customer_name
        ORDER BY suspect_count DESC
        LIMIT 10
    """).fetchall()
    
    report_lines.append("| Customer | Suspect Count |")
    report_lines.append("|----------|---------------|")
    for row in results:
        report_lines.append(f"| {row['customer_name'] or 'N/A'} | {row['suspect_count']:,} |")
    report_lines.append("")
    
    # Double-count Risk
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 5. Double-Count Risk (Multi-Visit Road Plans)")
    report_lines.append("")
    
    result = conn.execute("""
        SELECT 
            COUNT(*) as total_road_plans,
            SUM(CASE WHEN visit_count > 1 THEN 1 ELSE 0 END) as multi_visit_count,
            ROUND(100.0 * SUM(CASE WHEN visit_count > 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as pct
        FROM fact_visit_enriched
        WHERE visit_count > 0
    """).fetchone()
    
    report_lines.append(f"- Total road_plans with visits: **{result['total_road_plans']:,}**")
    report_lines.append(f"- Road plans with visit_count > 1: **{result['multi_visit_count']:,}** ({result['pct']}%)")
    report_lines.append("")
    
    report_lines.append("### Top 20 Road Plans with Most Visits")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            road_plan_id,
            visit_count,
            technician_name,
            customer_name,
            type,
            check_in_first,
            check_out_last
        FROM fact_visit_enriched
        WHERE visit_count > 1
        ORDER BY visit_count DESC
        LIMIT 20
    """).fetchall()
    
    report_lines.append("| RP ID | Visits | Technician | Customer | Type |")
    report_lines.append("|-------|--------|------------|----------|------|")
    for row in results:
        report_lines.append(f"| {row['road_plan_id']} | {row['visit_count']} | {row['technician_name'][:15] if row['technician_name'] else 'N/A'} | {row['customer_name'][:15] if row['customer_name'] else 'N/A'} | {row['type']} |")
    report_lines.append("")
    
    # DQ Flags Summary
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 6. DQ Flags Summary")
    report_lines.append("")
    
    result = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(is_valid_duration) as valid_duration,
            SUM(is_valid_checkin) as valid_checkin,
            SUM(is_valid_checkout) as valid_checkout,
            SUM(is_photo_compliant) as photo_compliant,
            SUM(is_working_day) as working_day,
            SUM(is_complete) as complete,
            SUM(is_suspect_time) as suspect_time,
            SUM(has_multi_visit) as multi_visit,
            SUM(has_null_checkout) as null_checkout,
            SUM(is_kpi_eligible) as kpi_eligible
        FROM dq_flags
    """).fetchone()
    
    total = result['total']
    report_lines.append("| Flag | Count | % |")
    report_lines.append("|------|-------|---|")
    report_lines.append(f"| is_complete | {result['complete']:,} | {100*result['complete']/total:.1f}% |")
    report_lines.append(f"| is_valid_checkin | {result['valid_checkin']:,} | {100*result['valid_checkin']/total:.1f}% |")
    report_lines.append(f"| is_valid_checkout | {result['valid_checkout']:,} | {100*result['valid_checkout']/total:.1f}% |")
    report_lines.append(f"| is_valid_duration | {result['valid_duration']:,} | {100*result['valid_duration']/total:.1f}% |")
    report_lines.append(f"| is_photo_compliant | {result['photo_compliant']:,} | {100*result['photo_compliant']/total:.1f}% |")
    report_lines.append(f"| is_working_day | {result['working_day']:,} | {100*result['working_day']/total:.1f}% |")
    report_lines.append(f"| is_suspect_time | {result['suspect_time']:,} | {100*result['suspect_time']/total:.1f}% ⚠️ |")
    report_lines.append(f"| has_multi_visit | {result['multi_visit']:,} | {100*result['multi_visit']/total:.1f}% |")
    report_lines.append(f"| has_null_checkout | {result['null_checkout']:,} | {100*result['null_checkout']/total:.1f}% |")
    report_lines.append(f"| **is_kpi_eligible** | **{result['kpi_eligible']:,}** | **{100*result['kpi_eligible']/total:.1f}%** |")
    report_lines.append("")
    
    # Duration Status Distribution
    report_lines.append("### Duration Status Distribution")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            duration_status,
            COUNT(*) as count,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as pct
        FROM dq_flags
        GROUP BY duration_status
        ORDER BY count DESC
    """).fetchall()
    
    report_lines.append("| Status | Count | % |")
    report_lines.append("|--------|-------|---|")
    for row in results:
        emoji = "🟢" if row['duration_status'] == 'VALID' else "🟡" if 'WARNING' in row['duration_status'] else "🔴"
        report_lines.append(f"| {emoji} {row['duration_status']} | {row['count']:,} | {row['pct']}% |")
    report_lines.append("")
    
    # Final Summary
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## ✅ Step 2 Completion Checklist")
    report_lines.append("")
    report_lines.append("| Deliverable | Status |")
    report_lines.append("|-------------|--------|")
    report_lines.append(f"| analytics/snc_analytics.db | ✅ Created |")
    report_lines.append(f"| fact_visit_enriched table | ✅ {result['total']:,} rows |")
    report_lines.append(f"| dq_flags table | ✅ {result['total']:,} rows |")
    report_lines.append(f"| This report | ✅ Generated |")
    report_lines.append("")
    report_lines.append("**Ready for Step 3: KPI Calculation**")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("*Generated by Step 2 ETL Script*")
    
    # Write report
    report_path = os.path.join(REPORTS_DIR, 'STEP2_DATA_QUALITY_BASELINE.md')
    with open(report_path, 'w') as f:
        f.write('\n'.join(report_lines))
    log(f"  -> Report written to {report_path}")
    
    # ============================================================
    # Export to CSV (since parquet may not be available)
    # ============================================================
    log("\n--- Exporting tables to CSV ---")
    
    # Export fact_visit_enriched
    fact_path = os.path.join(KPI_DIR, 'fact_visit_enriched.csv')
    results = conn.execute("SELECT * FROM fact_visit_enriched").fetchall()
    columns = [desc[0] for desc in conn.execute("SELECT * FROM fact_visit_enriched LIMIT 0").description]
    with open(fact_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(results)
    log(f"  -> Exported {len(results)} rows to {fact_path}")
    
    # Export dq_flags
    dq_path = os.path.join(KPI_DIR, 'dq_flags.csv')
    results = conn.execute("SELECT * FROM dq_flags").fetchall()
    columns = [desc[0] for desc in conn.execute("SELECT * FROM dq_flags LIMIT 0").description]
    with open(dq_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(results)
    log(f"  -> Exported {len(results)} rows to {dq_path}")
    
    conn.close()
    
    log("\n" + "=" * 60)
    log("STEP 2 COMPLETE!")
    log("=" * 60)
    log(f"Database: {DB_PATH}")
    log(f"Fact table: {fact_path}")
    log(f"DQ flags: {dq_path}")
    log(f"Report: {report_path}")

if __name__ == '__main__':
    main()
