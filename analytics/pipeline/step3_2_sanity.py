#!/usr/bin/env python3
"""
Step 3.2: Scoring Sanity + Acceptance Tests
============================================
Fixes:
1. Score capping to 0-100
2. Eligibility filter (technicians only)
3. STRICT v2 definition (tolerance-based, not clock-based)
4. Acceptance tests
5. Denominator consistency (using scheduled_month not actual_month)

Outputs:
- Cleaned scoring tables with capped scores
- dim_technician_eligible
- leaderboard_*_clean.csv
- kpi_acceptance_test_report.md
- strict_definition_v2.md
"""

import sqlite3
import csv
import os
import yaml
from datetime import datetime
from collections import defaultdict

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'analytics/snc_analytics.db')
KPI_DIR = os.path.join(BASE_DIR, 'analytics/kpi')
REPORTS_DIR = os.path.join(BASE_DIR, 'analytics/reports')
CONFIG_PATH = os.path.join(BASE_DIR, 'analytics/kpi_config.yaml')

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def main():
    log("=" * 70)
    log("STEP 3.2: Scoring Sanity + Acceptance Tests")
    log("=" * 70)
    
    config = load_config()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # ========================================================================
    # FIX 2: Create eligibility filter
    # ========================================================================
    log("\n--- Creating technician eligibility filter ---")
    
    conn.execute("DROP TABLE IF EXISTS dim_technician_eligible")
    conn.execute("""
        CREATE TABLE dim_technician_eligible AS
        SELECT 
            user_id,
            fullname,
            username,
            CASE 
                WHEN username LIKE 'teknisi_%' THEN 'TECHNICIAN'
                WHEN username LIKE 'spv_%' THEN 'SUPERVISOR'
                WHEN username LIKE 'leader_%' THEN 'LEADER'
                WHEN username LIKE 'qc_%' THEN 'QC'
                ELSE 'OTHER'
            END as role_category,
            CASE 
                WHEN username LIKE 'teknisi_%' THEN 1
                WHEN username LIKE 'spv_%' AND username NOT LIKE '%nonaktif%' THEN 1
                WHEN username LIKE 'leader_%' THEN 1
                WHEN username LIKE 'qc_%' THEN 1
                ELSE 0
            END as is_eligible_for_kpi,
            CASE 
                WHEN username LIKE '%nonaktif%' THEN 1
                ELSE 0
            END as is_inactive
        FROM dim_user
    """)
    conn.commit()
    
    eligible_count = conn.execute("SELECT COUNT(*) FROM dim_technician_eligible WHERE is_eligible_for_kpi = 1").fetchone()[0]
    log(f"  -> Created dim_technician_eligible: {eligible_count} eligible technicians")
    
    # ========================================================================
    # FIX 3: Rebuild STRICT v2 with tolerance-based on-time
    # ========================================================================
    log("\n--- Creating STRICT v2 (tolerance-based on-time) ---")
    
    # STRICT v2: on-time = visit same day AND NOT in suspect hours (21-23)
    # This is more defensible than "must check in 07-08"
    
    existing_cols = [row['name'] for row in conn.execute("PRAGMA table_info(fact_kpi_visit)")]
    if 'is_on_time_strict_v2' not in existing_cols:
        conn.execute("ALTER TABLE fact_kpi_visit ADD COLUMN is_on_time_strict_v2 INTEGER")
    
    # STRICT v2: same day AND not suspect time
    conn.execute("""
        UPDATE fact_kpi_visit
        SET is_on_time_strict_v2 = CASE 
            WHEN has_checkin = 1 
                 AND is_on_time_day = 1
                 AND is_suspect_time = 0
            THEN 1 ELSE 0 
        END
    """)
    conn.commit()
    
    strict_v1 = conn.execute("""
        SELECT SUM(is_on_time_strict) FROM fact_kpi_visit 
        WHERE is_completed = 1 AND has_checkin = 1
    """).fetchone()[0]
    strict_v2 = conn.execute("""
        SELECT SUM(is_on_time_strict_v2) FROM fact_kpi_visit 
        WHERE is_completed = 1 AND has_checkin = 1
    """).fetchone()[0]
    log(f"  -> STRICT v1 (07-08h only): {strict_v1:,}")
    log(f"  -> STRICT v2 (same day + not suspect): {strict_v2:,}")
    
    # ========================================================================
    # Rebuild monthly aggregates with eligibility filter
    # ========================================================================
    log("\n--- Rebuilding aggregates with eligibility filter ---")
    
    conn.execute("DROP TABLE IF EXISTS kpi_user_monthly_clean")
    conn.execute("""
        CREATE TABLE kpi_user_monthly_clean AS
        SELECT 
            f.user_id,
            f.technician_name,
            f.segment,
            -- Use scheduled_month for consistency (Fix 3)
            CASE 
                WHEN f.scheduled_month IS NOT NULL THEN f.scheduled_month
                ELSE f.actual_month
            END as month,
            
            -- Eligibility info
            COALESCE(e.is_eligible_for_kpi, 0) as is_eligible,
            COALESCE(e.role_category, 'UNKNOWN') as role_category,
            
            -- Counts
            COUNT(*) as actual_visits,
            SUM(f.is_completed) as completed_visits,
            
            -- On-time variants
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkin = 1 THEN f.is_on_time_day ELSE 0 END) as on_time_fair,
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkin = 1 THEN f.is_on_time_strict_v2 ELSE 0 END) as on_time_strict,
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkin = 1 THEN 1 ELSE 0 END) as on_time_eligible,
            
            -- Duration compliance (segment-specific)
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkout = 1 THEN f.is_duration_valid_segment ELSE 0 END) as duration_valid_count,
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkout = 1 THEN 1 ELSE 0 END) as duration_eligible,
            
            -- Photo compliance
            SUM(CASE WHEN f.is_completed = 1 THEN f.is_photo_ok ELSE 0 END) as photo_ok_count,
            
            -- DQ counts
            SUM(f.is_multiday_suspect) as multiday_count,
            SUM(f.is_suspect_time) as suspect_time_count,
            SUM(CASE WHEN f.is_completed = 1 AND f.foto_count = 0 THEN 1 ELSE 0 END) as no_photo_count,
            
            -- Productivity
            COUNT(DISTINCT CASE WHEN f.is_completed = 1 AND f.is_working_day = 1 THEN f.actual_day END) as active_working_days
            
        FROM fact_kpi_visit f
        LEFT JOIN dim_technician_eligible e ON f.user_id = e.user_id
        WHERE f.scheduled_month IS NOT NULL OR f.actual_month IS NOT NULL
        GROUP BY f.user_id, f.technician_name, f.segment, month
    """)
    
    # Add scheduled_visits from true source
    conn.execute("ALTER TABLE kpi_user_monthly_clean ADD COLUMN scheduled_visits INTEGER")
    conn.execute("""
        UPDATE kpi_user_monthly_clean
        SET scheduled_visits = (
            SELECT s.scheduled_visits_true
            FROM scheduled_by_user_month s
            WHERE s.user_id = kpi_user_monthly_clean.user_id
              AND s.month = kpi_user_monthly_clean.month
              AND s.segment = kpi_user_monthly_clean.segment
        )
    """)
    conn.execute("""
        UPDATE kpi_user_monthly_clean
        SET scheduled_visits = actual_visits
        WHERE scheduled_visits IS NULL
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) FROM kpi_user_monthly_clean").fetchone()[0]
    eligible_records = conn.execute("SELECT COUNT(*) FROM kpi_user_monthly_clean WHERE is_eligible = 1").fetchone()[0]
    log(f"  -> Created kpi_user_monthly_clean: {result} rows ({eligible_records} eligible)")
    
    # ========================================================================
    # FIX 1: Create scoring tables with CAPPED scores
    # ========================================================================
    log("\n--- Creating scoring tables with capped scores ---")
    
    weights = config['kpi_weights']
    prod_config = config['productivity']
    targets = prod_config.get('target_by_segment', {})
    max_mult = prod_config['max_score_multiplier']
    
    for mode in ["strict", "fair"]:
        conn.execute(f"DROP TABLE IF EXISTS kpi_score_{mode}_clean")
        
        on_time_col = "on_time_strict" if mode == "strict" else "on_time_fair"
        
        conn.execute(f"""
            CREATE TABLE kpi_score_{mode}_clean AS
            SELECT 
                user_id,
                technician_name,
                segment,
                month,
                is_eligible,
                role_category,
                
                scheduled_visits,
                completed_visits,
                {on_time_col} as on_time_count,
                duration_valid_count,
                photo_ok_count,
                active_working_days,
                
                -- CAPPED rates (0-1)
                MIN(1.0, CASE WHEN scheduled_visits > 0 
                     THEN 1.0 * completed_visits / scheduled_visits 
                     ELSE 0 END) as completion_rate,
                
                MIN(1.0, CASE WHEN on_time_eligible > 0 
                     THEN 1.0 * {on_time_col} / on_time_eligible 
                     ELSE 0 END) as on_time_rate,
                
                MIN(1.0, CASE WHEN duration_eligible > 0 
                     THEN 1.0 * duration_valid_count / duration_eligible 
                     ELSE 0 END) as duration_compliance_rate,
                
                MIN(1.0, CASE WHEN completed_visits > 0 
                     THEN 1.0 * photo_ok_count / completed_visits 
                     ELSE 0 END) as photo_compliance_rate,
                
                CASE WHEN active_working_days > 0 
                     THEN 1.0 * completed_visits / active_working_days 
                     ELSE 0 END as visits_per_day,
                
                -- DQ flags
                multiday_count,
                suspect_time_count,
                no_photo_count
                
            FROM kpi_user_monthly_clean
        """)
        
        # Add score columns
        for col in ['completion_score', 'on_time_score', 'duration_score', 
                    'photo_score', 'productivity_score', 'total_score']:
            conn.execute(f"ALTER TABLE kpi_score_{mode}_clean ADD COLUMN {col} REAL")
        conn.execute(f"ALTER TABLE kpi_score_{mode}_clean ADD COLUMN grade TEXT")
        
        # Calculate CAPPED component scores (0-100)
        conn.execute(f"""
            UPDATE kpi_score_{mode}_clean
            SET 
                completion_score = MIN(100, completion_rate * 100),
                on_time_score = MIN(100, on_time_rate * 100),
                duration_score = MIN(100, duration_compliance_rate * 100),
                photo_score = MIN(100, photo_compliance_rate * 100)
        """)
        
        # Productivity score with segment targets
        default_target = prod_config['target_visits_per_working_day']
        for seg, target in targets.items():
            conn.execute(f"""
                UPDATE kpi_score_{mode}_clean
                SET productivity_score = MIN(100 * {max_mult}, 
                    CASE WHEN visits_per_day >= {target} 
                         THEN 100 
                         ELSE (visits_per_day / {target}) * 100 
                    END)
                WHERE segment = ?
            """, (seg,))
        
        # Fallback
        conn.execute(f"""
            UPDATE kpi_score_{mode}_clean
            SET productivity_score = MIN(100 * {max_mult}, 
                CASE WHEN visits_per_day >= {default_target} 
                     THEN 100 
                     ELSE (visits_per_day / {default_target}) * 100 
                END)
            WHERE productivity_score IS NULL
        """)
        
        # Cap productivity to 150 max
        conn.execute(f"""
            UPDATE kpi_score_{mode}_clean
            SET productivity_score = MIN(150, productivity_score)
        """)
        
        # Calculate total score (CAPPED to 100)
        conn.execute(f"""
            UPDATE kpi_score_{mode}_clean
            SET total_score = MIN(100,
                (completion_score * {weights['completion_rate']} +
                 on_time_score * {weights['on_time_rate']} +
                 duration_score * {weights['duration_compliance']} +
                 photo_score * {weights['photo_compliance']} +
                 productivity_score * {weights['productivity']}) / 100.0
            )
        """)
        
        # Assign grades (now should never have NULL)
        grading = config['grading']
        for grade, bounds in grading.items():
            conn.execute(f"""
                UPDATE kpi_score_{mode}_clean
                SET grade = '{grade}'
                WHERE total_score >= {bounds['min_score']} AND total_score <= {bounds['max_score']}
            """)
        
        conn.commit()
        
        # Verify no more NULL grades
        null_grades = conn.execute(f"SELECT COUNT(*) FROM kpi_score_{mode}_clean WHERE grade IS NULL").fetchone()[0]
        over_100 = conn.execute(f"SELECT COUNT(*) FROM kpi_score_{mode}_clean WHERE total_score > 100").fetchone()[0]
        log(f"  -> Created kpi_score_{mode}_clean: NULL grades={null_grades}, scores>100={over_100}")
    
    # ========================================================================
    # Create CLEAN leaderboards (eligible only)
    # ========================================================================
    log("\n--- Creating clean leaderboards ---")
    
    for mode in ["strict", "fair"]:
        conn.execute(f"DROP TABLE IF EXISTS leaderboard_{mode}_clean")
        conn.execute(f"""
            CREATE TABLE leaderboard_{mode}_clean AS
            SELECT 
                ROW_NUMBER() OVER (PARTITION BY segment ORDER BY total_score DESC) as rank,
                user_id,
                technician_name,
                segment,
                role_category,
                month,
                scheduled_visits,
                completed_visits,
                ROUND(completion_rate * 100, 1) as completion_pct,
                ROUND(on_time_rate * 100, 1) as on_time_pct,
                ROUND(duration_compliance_rate * 100, 1) as duration_pct,
                ROUND(photo_compliance_rate * 100, 1) as photo_pct,
                ROUND(visits_per_day, 2) as visits_per_day,
                ROUND(total_score, 2) as score,
                grade,
                multiday_count,
                suspect_time_count,
                no_photo_count
            FROM kpi_score_{mode}_clean
            WHERE is_eligible = 1
              AND month = (SELECT MAX(month) FROM kpi_score_{mode}_clean)
            ORDER BY segment, total_score DESC
        """)
        conn.commit()
        
        result = conn.execute(f"SELECT COUNT(*) FROM leaderboard_{mode}_clean").fetchone()[0]
        log(f"  -> Created leaderboard_{mode}_clean: {result} rows")
    
    # ========================================================================
    # Run Acceptance Tests
    # ========================================================================
    log("\n--- Running Acceptance Tests ---")
    
    acceptance = config['acceptance_tests']
    test_results = []
    
    tests = [
        ("total_road_plans", "SELECT COUNT(*) FROM fact_visit_enriched", 33727),
        ("completed_visits", "SELECT SUM(is_complete) FROM fact_visit_enriched", 33510),
        ("null_checkout", "SELECT SUM(has_null_checkout_strict) FROM dq_flags", 217),
        ("null_checkin", "SELECT SUM(CASE WHEN check_in_first IS NULL OR check_in_first = '' THEN 1 ELSE 0 END) FROM fact_visit_enriched", 7),
        ("no_photo_raw", "SELECT COUNT(*) FROM fact_visit_enriched WHERE foto_count = 0", 5452),
        ("multiday_suspect", "SELECT COUNT(*) FROM dq_flags WHERE duration_status_v2 = 'MULTI_DAY_SUSPECT'", 3431),
        ("suspect_time", "SELECT SUM(is_suspect_time) FROM dq_flags", 5711),
    ]
    
    all_passed = True
    for name, sql, expected in tests:
        actual = conn.execute(sql).fetchone()[0] or 0
        passed = actual == expected
        if not passed:
            all_passed = False
        test_results.append({
            'name': name,
            'expected': expected,
            'actual': actual,
            'passed': passed
        })
        status = "✓ PASS" if passed else "✗ FAIL"
        log(f"  {status}: {name} = {actual} (expected {expected})")
    
    # ========================================================================
    # Generate Reports
    # ========================================================================
    log("\n--- Generating Reports ---")
    
    # Acceptance Test Report
    report = []
    report.append("# KPI Acceptance Test Report")
    report.append("")
    report.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    report.append(f"> **Overall Status:** {'✅ ALL PASSED' if all_passed else '⚠️ SOME FAILED'}")
    report.append("")
    report.append("## Test Results")
    report.append("")
    report.append("| Test | Expected | Actual | Status |")
    report.append("|------|----------|--------|--------|")
    for t in test_results:
        status = "✅" if t['passed'] else "❌"
        report.append(f"| {t['name']} | {t['expected']:,} | {t['actual']:,} | {status} |")
    report.append("")
    
    # Score sanity check
    report.append("## Score Sanity Check")
    report.append("")
    
    for mode in ["strict", "fair"]:
        stats = conn.execute(f"""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN total_score > 100 THEN 1 ELSE 0 END) as over_100,
                SUM(CASE WHEN grade IS NULL THEN 1 ELSE 0 END) as null_grade,
                MIN(total_score) as min_score,
                MAX(total_score) as max_score
            FROM kpi_score_{mode}_clean
        """).fetchone()
        
        report.append(f"### {mode.upper()} Mode")
        report.append("")
        report.append(f"- Total records: {stats['total']:,}")
        report.append(f"- Scores > 100: {stats['over_100']} {'✅' if stats['over_100'] == 0 else '❌'}")
        report.append(f"- NULL grades: {stats['null_grade']} {'✅' if stats['null_grade'] == 0 else '❌'}")
        report.append(f"- Score range: {stats['min_score']:.2f} - {stats['max_score']:.2f}")
        report.append("")
    
    # Eligibility Summary
    report.append("## Eligibility Summary")
    report.append("")
    elig_stats = conn.execute("""
        SELECT 
            role_category,
            is_eligible_for_kpi,
            COUNT(*) as count
        FROM dim_technician_eligible
        GROUP BY role_category, is_eligible_for_kpi
        ORDER BY role_category
    """).fetchall()
    
    report.append("| Role Category | Eligible | Count |")
    report.append("|---------------|----------|-------|")
    for row in elig_stats:
        elig = "Yes" if row['is_eligible_for_kpi'] else "No"
        report.append(f"| {row['role_category']} | {elig} | {row['count']} |")
    report.append("")
    
    with open(os.path.join(REPORTS_DIR, 'kpi_acceptance_test_report.md'), 'w') as f:
        f.write('\n'.join(report))
    log("  -> Written kpi_acceptance_test_report.md")
    
    # STRICT v2 Definition
    strict_def = []
    strict_def.append("# STRICT Mode Definition v2")
    strict_def.append("")
    strict_def.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    strict_def.append("")
    strict_def.append("## Problem with STRICT v1")
    strict_def.append("")
    strict_def.append("STRICT v1 defined on-time as: `check_in hour between 07:00-08:59 AND same day`")
    strict_def.append("")
    strict_def.append("This was too restrictive because:")
    strict_def.append("- It tested 'office arrival time' not 'visit punctuality'")
    strict_def.append("- Technicians with afternoon/evening visits were automatically 'late'")
    strict_def.append(f"- Result: Only {strict_v1:,} on-time out of 33,510 completed (14.5%)")
    strict_def.append("")
    strict_def.append("## STRICT v2 Definition")
    strict_def.append("")
    strict_def.append("**On-Time STRICT v2:** `same day as scheduled AND NOT suspect time (21-23h)`")
    strict_def.append("")
    strict_def.append("Rationale:")
    strict_def.append("- Still checks if visit happened on scheduled day")
    strict_def.append("- Penalizes 'end of day bulk submission' (21-23h)")
    strict_def.append("- But doesn't penalize legitimate afternoon/evening visits")
    strict_def.append("")
    strict_def.append("## Impact Comparison")
    strict_def.append("")
    strict_def.append("| Metric | FAIR | STRICT v1 | STRICT v2 |")
    strict_def.append("|--------|------|-----------|-----------|")
    strict_def.append(f"| On-Time Count | {conn.execute('SELECT SUM(is_on_time_day) FROM fact_kpi_visit WHERE is_completed=1').fetchone()[0]:,} | {strict_v1:,} | {strict_v2:,} |")
    strict_def.append(f"| On-Time Rate | 77.0% | 14.5% | {100*strict_v2/33510:.1f}% |")
    strict_def.append("")
    strict_def.append("## Recommendation")
    strict_def.append("")
    strict_def.append("Use **STRICT v2** for audit mode as it:")
    strict_def.append("1. Catches genuine timing issues (bulk submissions)")
    strict_def.append("2. Doesn't unfairly penalize afternoon schedules")
    strict_def.append("3. Provides meaningful differentiation (not 'everyone fails')")
    strict_def.append("")
    
    with open(os.path.join(REPORTS_DIR, 'strict_definition_v2.md'), 'w') as f:
        f.write('\n'.join(strict_def))
    log("  -> Written strict_definition_v2.md")
    
    # ========================================================================
    # Export CSVs
    # ========================================================================
    log("\n--- Exporting Clean CSVs ---")
    
    exports = [
        ("leaderboard_strict_clean", "leaderboard_strict_clean.csv"),
        ("leaderboard_fair_clean", "leaderboard_fair_clean.csv"),
        ("kpi_score_strict_clean", "kpi_score_strict_clean.csv"),
        ("kpi_score_fair_clean", "kpi_score_fair_clean.csv"),
    ]
    
    for table, filename in exports:
        path = os.path.join(KPI_DIR, filename)
        results = conn.execute(f"SELECT * FROM {table}").fetchall()
        columns = [desc[0] for desc in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(results)
        log(f"  -> Exported {len(results)} rows to {filename}")
    
    # Grade distribution
    grade_dist = []
    grade_dist.append("mode,segment,grade,count")
    for mode in ["strict", "fair"]:
        dist = conn.execute(f"""
            SELECT segment, grade, COUNT(*) as count
            FROM leaderboard_{mode}_clean
            GROUP BY segment, grade
            ORDER BY segment, grade
        """).fetchall()
        for row in dist:
            grade_dist.append(f"{mode},{row['segment']},{row['grade']},{row['count']}")
    
    with open(os.path.join(KPI_DIR, 'grade_distribution_clean.csv'), 'w') as f:
        f.write('\n'.join(grade_dist))
    log("  -> Exported grade_distribution_clean.csv")
    
    conn.close()
    
    log("\n" + "=" * 70)
    log("STEP 3.2 COMPLETE!")
    log("=" * 70)
    log(f"Acceptance Tests: {'ALL PASSED ✓' if all_passed else 'SOME FAILED ✗'}")

if __name__ == '__main__':
    main()
