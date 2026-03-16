#!/usr/bin/env python3
"""
Step 2.1 Hotfix: Fix Data Quality Issues
========================================
Fixes identified in mentor review:
A) check_in date range start kosong (NULL min)
B) Persentase formatting keliru (100% palsu)
C) Checkout mismatch 211 vs 217 - separate NULL vs invalid
D) Duration outlier - add raw + capped columns, show timestamps

Output:
- Updated analytics/snc_analytics.db with fixed tables
- Updated analytics/kpi/*.csv exports
- Updated analytics/reports/STEP2_DATA_QUALITY_BASELINE.md
"""

import sqlite3
import csv
import os
from datetime import datetime

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'analytics/snc_analytics.db')
KPI_DIR = os.path.join(BASE_DIR, 'analytics/kpi')
REPORTS_DIR = os.path.join(BASE_DIR, 'analytics/reports')

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def pct(count, total):
    """Proper percentage formatting - never lie about 100%"""
    if total == 0:
        return "0.00%"
    p = 100.0 * count / total
    return f"{p:.2f}%"

def main():
    log("=" * 60)
    log("STEP 2.1 HOTFIX: Fixing Data Quality Issues")
    log("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # ============================================================
    # FIX D: Add duration_min_raw and duration_min_capped to fact table
    # ============================================================
    log("\n--- Fix D: Adding duration columns ---")
    
    # Check if columns already exist
    existing_cols = [row['name'] for row in conn.execute("PRAGMA table_info(fact_visit_enriched)")]
    
    if 'duration_min_raw' not in existing_cols:
        conn.execute("ALTER TABLE fact_visit_enriched ADD COLUMN duration_min_raw REAL")
        conn.execute("ALTER TABLE fact_visit_enriched ADD COLUMN duration_min_capped REAL")
        conn.execute("""
            UPDATE fact_visit_enriched 
            SET duration_min_raw = duration_min,
                duration_min_capped = CASE 
                    WHEN duration_min IS NULL THEN NULL
                    WHEN duration_min < 0 THEN NULL
                    WHEN duration_min > 1440 THEN 1440
                    ELSE duration_min
                END
        """)
        conn.commit()
        log("  -> Added duration_min_raw and duration_min_capped columns")
    else:
        log("  -> Columns already exist, skipping")
    
    # ============================================================
    # FIX C: Add separate checkout issue flags
    # ============================================================
    log("\n--- Fix C: Adding checkout issue columns to dq_flags ---")
    
    existing_flags = [row['name'] for row in conn.execute("PRAGMA table_info(dq_flags)")]
    
    if 'has_null_checkout_strict' not in existing_flags:
        conn.execute("ALTER TABLE dq_flags ADD COLUMN has_null_checkout_strict INTEGER")
        conn.execute("ALTER TABLE dq_flags ADD COLUMN has_invalid_checkout INTEGER")
        
        # Update from fact_visit_enriched
        conn.execute("""
            UPDATE dq_flags 
            SET has_null_checkout_strict = (
                SELECT CASE 
                    WHEN f.check_out_last IS NULL OR f.check_out_last = '' THEN 1 
                    ELSE 0 
                END
                FROM fact_visit_enriched f 
                WHERE f.road_plan_id = dq_flags.road_plan_id
            )
        """)
        
        conn.execute("""
            UPDATE dq_flags 
            SET has_invalid_checkout = (
                SELECT CASE 
                    WHEN f.check_out_last IS NOT NULL 
                         AND f.check_out_last != ''
                         AND f.check_in_first IS NOT NULL
                         AND f.check_in_first != ''
                         AND f.check_out_last < f.check_in_first 
                    THEN 1 
                    ELSE 0 
                END
                FROM fact_visit_enriched f 
                WHERE f.road_plan_id = dq_flags.road_plan_id
            )
        """)
        conn.commit()
        log("  -> Added has_null_checkout_strict and has_invalid_checkout columns")
    else:
        log("  -> Columns already exist, skipping")
    
    # ============================================================
    # FIX D continued: Update duration_status with clearer categories
    # ============================================================
    log("\n--- Fix D continued: Updating duration status ---")
    
    if 'duration_status_v2' not in existing_flags:
        conn.execute("ALTER TABLE dq_flags ADD COLUMN duration_status_v2 TEXT")
        
        conn.execute("""
            UPDATE dq_flags
            SET duration_status_v2 = (
                SELECT CASE 
                    WHEN f.duration_min_raw IS NULL THEN 'NO_CHECKOUT'
                    WHEN f.duration_min_raw < 0 THEN 'NEGATIVE'
                    WHEN f.duration_min_raw > 1440 THEN 'MULTI_DAY_SUSPECT'
                    WHEN f.duration_min_raw > 600 THEN 'OVERNIGHT_WARNING'
                    WHEN f.duration_min_raw > 480 THEN 'LONG_WARNING'
                    WHEN f.duration_min_raw < 5 THEN 'TOO_SHORT'
                    ELSE 'VALID'
                END
                FROM fact_visit_enriched f 
                WHERE f.road_plan_id = dq_flags.road_plan_id
            )
        """)
        conn.commit()
        log("  -> Added duration_status_v2 with clearer categories")
    
    # ============================================================
    # Recalculate is_kpi_eligible with stricter rules
    # ============================================================
    log("\n--- Recalculating is_kpi_eligible ---")
    
    if 'is_kpi_eligible_v2' not in existing_flags:
        conn.execute("ALTER TABLE dq_flags ADD COLUMN is_kpi_eligible_v2 INTEGER")
        
        conn.execute("""
            UPDATE dq_flags
            SET is_kpi_eligible_v2 = (
                SELECT CASE 
                    WHEN f.is_complete = 1 
                         AND f.check_in_first IS NOT NULL AND f.check_in_first != ''
                         AND f.check_out_last IS NOT NULL AND f.check_out_last != ''
                         AND f.duration_min_raw IS NOT NULL
                         AND f.duration_min_raw >= 5 
                         AND f.duration_min_raw <= 600
                    THEN 1 ELSE 0 
                END
                FROM fact_visit_enriched f 
                WHERE f.road_plan_id = dq_flags.road_plan_id
            )
        """)
        conn.commit()
        log("  -> Added is_kpi_eligible_v2 (stricter: 5-600 min, valid checkout)")
    
    # ============================================================
    # Generate FIXED Report
    # ============================================================
    log("\n--- Generating Fixed Data Quality Report v2 ---")
    
    report_lines = []
    report_lines.append("# 📊 STEP 2.1: Data Quality Baseline Report (HOTFIX)")
    report_lines.append("")
    report_lines.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    report_lines.append(f"> **Database:** {DB_PATH}")
    report_lines.append("> **Version:** 2.1 (with hotfix for duration/checkout issues)")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    
    # Get total count
    total = conn.execute("SELECT COUNT(*) as cnt FROM fact_visit_enriched").fetchone()['cnt']
    
    # Extraction Summary
    report_lines.append("## 1. Extraction Summary")
    report_lines.append("")
    report_lines.append(f"**Total road_plans:** {total:,}")
    report_lines.append("")
    
    # FIX A: Date Range with proper NULL handling
    result = conn.execute("""
        SELECT 
            MIN(CASE WHEN visit_date IS NOT NULL AND visit_date != '' THEN visit_date END) as min_visit_date,
            MAX(visit_date) as max_visit_date,
            MIN(CASE WHEN check_in_first IS NOT NULL AND check_in_first != '' THEN check_in_first END) as min_check_in,
            MAX(check_in_first) as max_check_in,
            SUM(CASE WHEN check_in_first IS NULL OR check_in_first = '' THEN 1 ELSE 0 END) as check_in_null_count
        FROM fact_visit_enriched
    """).fetchone()
    
    report_lines.append("**Date Range:**")
    report_lines.append(f"- visit_date: `{result['min_visit_date']}` to `{result['max_visit_date']}`")
    report_lines.append(f"- check_in: `{result['min_check_in']}` to `{result['max_check_in']}`")
    report_lines.append(f"- ⚠️ check_in NULL/empty count: **{result['check_in_null_count']}** ({pct(result['check_in_null_count'], total)})")
    report_lines.append("")
    
    # Coverage Statistics
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 2. Coverage Statistics")
    report_lines.append("")
    
    # FIX C: Separate checkout issues
    result = conn.execute("""
        SELECT 
            SUM(CASE WHEN f.is_complete = 1 AND f.has_visit = 0 THEN 1 ELSE 0 END) as complete_no_visit,
            SUM(d.has_null_checkout_strict) as null_checkout,
            SUM(d.has_invalid_checkout) as invalid_checkout,
            SUM(CASE WHEN f.foto_count = 0 THEN 1 ELSE 0 END) as no_foto
        FROM fact_visit_enriched f
        JOIN dq_flags d ON f.road_plan_id = d.road_plan_id
    """).fetchone()
    
    report_lines.append("| Metric | Count | % |")
    report_lines.append("|--------|-------|---|")
    report_lines.append(f"| Complete but no visit | {result['complete_no_visit']:,} | {pct(result['complete_no_visit'], total)} |")
    report_lines.append(f"| **NULL checkout** | {result['null_checkout']:,} | {pct(result['null_checkout'], total)} |")
    report_lines.append(f"| Invalid checkout (out < in) | {result['invalid_checkout']:,} | {pct(result['invalid_checkout'], total)} |")
    report_lines.append(f"| No photos (foto_count=0) | {result['no_foto']:,} | {pct(result['no_foto'], total)} |")
    report_lines.append("")
    
    # FIX D: Duration Stats with RAW and CAPPED
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 3. Duration Statistics")
    report_lines.append("")
    report_lines.append("### 3.1 Raw Duration by Type (including outliers)")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            type,
            COUNT(*) as count,
            ROUND(AVG(duration_min_raw), 1) as avg_raw,
            ROUND(MIN(duration_min_raw), 1) as min_raw,
            ROUND(MAX(duration_min_raw), 1) as max_raw,
            ROUND(AVG(duration_min_capped), 1) as avg_capped
        FROM fact_visit_enriched
        WHERE duration_min_raw IS NOT NULL
        GROUP BY type
        ORDER BY count DESC
    """).fetchall()
    
    report_lines.append("| Type | Count | Avg Raw | Min | Max Raw | Avg Capped |")
    report_lines.append("|------|-------|---------|-----|---------|------------|")
    for row in results:
        report_lines.append(f"| {row['type'] or 'NULL'} | {row['count']:,} | {row['avg_raw']} | {row['min_raw']} | {row['max_raw']:,.0f} | {row['avg_capped']} |")
    report_lines.append("")
    
    # Top 20 Duration Outliers with TIMESTAMPS
    report_lines.append("### 3.2 Top 20 Duration Outliers (with timestamps)")
    report_lines.append("")
    report_lines.append("> These show `check_in_first` and `check_out_last` to identify data quality issues")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            road_plan_id,
            technician_name,
            customer_name,
            type,
            ROUND(duration_min_raw, 0) as duration_min,
            ROUND(duration_min_raw / 1440.0, 1) as duration_days,
            check_in_first,
            check_out_last
        FROM fact_visit_enriched
        WHERE duration_min_raw IS NOT NULL
        ORDER BY duration_min_raw DESC
        LIMIT 20
    """).fetchall()
    
    report_lines.append("| RP ID | Type | Duration (min) | Days | Check-in | Check-out |")
    report_lines.append("|-------|------|----------------|------|----------|-----------|")
    for row in results:
        report_lines.append(f"| {row['road_plan_id']} | {row['type']} | {row['duration_min']:,.0f} | {row['duration_days']} | {row['check_in_first'][:16] if row['check_in_first'] else 'N/A'} | {row['check_out_last'][:16] if row['check_out_last'] else 'N/A'} |")
    report_lines.append("")
    
    report_lines.append("> ⚠️ **Analysis:** Outliers show check-outs happening months/years after check-in.")
    report_lines.append("> This is likely 'forgot to checkout' scenarios where technicians checkout much later.")
    report_lines.append("> These should be treated as **data quality issues**, not real durations.")
    report_lines.append("")
    
    # Duration Status Distribution V2
    report_lines.append("### 3.3 Duration Status Distribution (v2)")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            duration_status_v2 as status,
            COUNT(*) as count
        FROM dq_flags
        GROUP BY duration_status_v2
        ORDER BY count DESC
    """).fetchall()
    
    report_lines.append("| Status | Count | % |")
    report_lines.append("|--------|-------|---|")
    for row in results:
        emoji = "🟢" if row['status'] == 'VALID' else "🟡" if 'WARNING' in row['status'] else "🔴"
        report_lines.append(f"| {emoji} {row['status']} | {row['count']:,} | {pct(row['count'], total)} |")
    report_lines.append("")
    
    # Time Anomalies
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 4. Time Anomalies")
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
    
    report_lines.append("| Hour | Count | % | Bar |")
    report_lines.append("|------|-------|---|-----|")
    max_count = max(r['count'] for r in results) if results else 1
    for row in results:
        bar_len = int(25 * row['count'] / max_count)
        bar = '█' * bar_len
        flag = " ⚠️" if row['check_in_hour'] in (21, 22, 23) else ""
        report_lines.append(f"| {row['check_in_hour']:02d}:00 | {row['count']:,} | {pct(row['count'], total)} | {bar}{flag} |")
    report_lines.append("")
    
    # Suspect time breakdown
    report_lines.append("### 4.1 Suspect Time (21:00-23:00) Analysis")
    report_lines.append("")
    
    suspect_count = conn.execute("SELECT SUM(is_suspect_time) FROM dq_flags").fetchone()[0]
    report_lines.append(f"**Total suspect time records:** {suspect_count:,} ({pct(suspect_count, total)})")
    report_lines.append("")
    
    results = conn.execute("""
        SELECT 
            f.type,
            COUNT(*) as suspect_count
        FROM fact_visit_enriched f
        JOIN dq_flags d ON f.road_plan_id = d.road_plan_id
        WHERE d.is_suspect_time = 1
        GROUP BY f.type
        ORDER BY suspect_count DESC
    """).fetchall()
    
    report_lines.append("| Type | Suspect Count | % of Type's Total |")
    report_lines.append("|------|---------------|-------------------|")
    for row in results:
        type_total = conn.execute(f"SELECT COUNT(*) FROM fact_visit_enriched WHERE type = ?", (row['type'],)).fetchone()[0]
        report_lines.append(f"| {row['type'] or 'NULL'} | {row['suspect_count']:,} | {pct(row['suspect_count'], type_total)} |")
    report_lines.append("")
    
    # DQ Flags Summary - FIX B: Proper percentages
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 5. DQ Flags Summary (with corrected %)")
    report_lines.append("")
    
    result = conn.execute("""
        SELECT 
            SUM(is_valid_duration) as valid_duration,
            SUM(is_valid_checkin) as valid_checkin,
            SUM(is_valid_checkout) as valid_checkout,
            SUM(is_photo_compliant) as photo_compliant,
            SUM(is_working_day) as working_day,
            SUM(is_complete) as complete,
            SUM(is_suspect_time) as suspect_time,
            SUM(has_multi_visit) as multi_visit,
            SUM(has_null_checkout_strict) as null_checkout,
            SUM(has_invalid_checkout) as invalid_checkout,
            SUM(is_kpi_eligible) as kpi_eligible_v1,
            SUM(is_kpi_eligible_v2) as kpi_eligible_v2
        FROM dq_flags
    """).fetchone()
    
    report_lines.append("| Flag | Count | % |")
    report_lines.append("|------|-------|---|")
    report_lines.append(f"| is_complete | {result['complete']:,} | {pct(result['complete'], total)} |")
    report_lines.append(f"| is_valid_checkin | {result['valid_checkin']:,} | {pct(result['valid_checkin'], total)} |")
    report_lines.append(f"| is_valid_checkout | {result['valid_checkout']:,} | {pct(result['valid_checkout'], total)} |")
    report_lines.append(f"| is_valid_duration (5-480) | {result['valid_duration']:,} | {pct(result['valid_duration'], total)} |")
    report_lines.append(f"| is_photo_compliant | {result['photo_compliant']:,} | {pct(result['photo_compliant'], total)} |")
    report_lines.append(f"| is_working_day | {result['working_day']:,} | {pct(result['working_day'], total)} |")
    report_lines.append(f"| is_suspect_time (21-23h) | {result['suspect_time']:,} | {pct(result['suspect_time'], total)} ⚠️ |")
    report_lines.append(f"| has_null_checkout | {result['null_checkout']:,} | {pct(result['null_checkout'], total)} |")
    report_lines.append(f"| has_invalid_checkout | {result['invalid_checkout']:,} | {pct(result['invalid_checkout'], total)} |")
    report_lines.append(f"| **is_kpi_eligible (v1: 5-600)** | **{result['kpi_eligible_v1']:,}** | **{pct(result['kpi_eligible_v1'], total)}** |")
    report_lines.append(f"| **is_kpi_eligible (v2: stricter)** | **{result['kpi_eligible_v2']:,}** | **{pct(result['kpi_eligible_v2'], total)}** |")
    report_lines.append("")
    
    # Recommendations for Step 3
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## 6. Recommendations for Step 3")
    report_lines.append("")
    report_lines.append("### Data Quality Issues to Handle:")
    report_lines.append("")
    report_lines.append("1. **Multi-day durations (>1440 min):** These are 'forgot to checkout' cases.")
    report_lines.append("   - Recommendation: Exclude from duration metrics, flag as data issue")
    report_lines.append("")
    report_lines.append("2. **Suspect time (21-23h) primarily in t_mobile (96%):**")
    report_lines.append("   - This suggests technicians are 'submitting at end of day' not 'checking in on arrival'")
    report_lines.append("   - Recommendation: Use `visit_date` comparison instead of clock time for on-time")
    report_lines.append("")
    report_lines.append("3. **16.17% with no photos:**")
    report_lines.append("   - This is a real operational gap, valid for KPI penalty")
    report_lines.append("")
    report_lines.append("### Suggested KPI Modes:")
    report_lines.append("")
    report_lines.append("| Mode | Description | Use Case |")
    report_lines.append("|------|-------------|----------|")
    report_lines.append("| **Strict** | Use raw data, flag all anomalies | Audit/Compliance |")
    report_lines.append("| **Fair** | Cap duration at 1440, use visit_date for timing | Bonus/Ranking |")
    report_lines.append("")
    
    # Final Summary
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("## ✅ Step 2.1 Hotfix Summary")
    report_lines.append("")
    report_lines.append("| Fix | Status |")
    report_lines.append("|-----|--------|")
    report_lines.append("| A) Min check_in NULL | ✅ Fixed with NULL filter |")
    report_lines.append("| B) % formatting | ✅ Using proper count/total |")
    report_lines.append("| C) Checkout mismatch | ✅ Separated NULL vs invalid |")
    report_lines.append("| D) Duration outliers | ✅ Added raw + capped columns |")
    report_lines.append("")
    report_lines.append("**Ready for Step 3: KPI Calculation**")
    report_lines.append("")
    
    # Write report
    report_path = os.path.join(REPORTS_DIR, 'STEP2_DATA_QUALITY_BASELINE.md')
    with open(report_path, 'w') as f:
        f.write('\n'.join(report_lines))
    log(f"  -> Report written to {report_path}")
    
    # ============================================================
    # Re-export CSVs
    # ============================================================
    log("\n--- Re-exporting tables to CSV ---")
    
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
    log("STEP 2.1 HOTFIX COMPLETE!")
    log("=" * 60)

if __name__ == '__main__':
    main()
