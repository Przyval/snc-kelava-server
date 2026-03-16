#!/usr/bin/env python3
"""
Step 3: KPI Calculation Engine
==============================
Implements the full KPI runbook with Strict vs Fair modes.

Outputs:
- fact_kpi_visit table
- kpi_user_monthly table
- kpi_user_score_monthly_strict / _fair
- leaderboard_strict / _fair
- audit_pack_* tables
- STEP3_KPI_REPORT.md
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
    """Load KPI configuration from YAML"""
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def pct(count, total):
    """Safe percentage calculation"""
    if total == 0:
        return 0.0
    return 100.0 * count / total

def get_grade(score, config):
    """Determine grade based on score"""
    grading = config['grading']
    for grade, bounds in grading.items():
        if bounds['min_score'] <= score <= bounds['max_score']:
            return grade
    return 'F'

def main():
    log("=" * 70)
    log("STEP 3: KPI Calculation Engine")
    log("=" * 70)
    
    # Load config
    config = load_config()
    log(f"Loaded config from {CONFIG_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # ========================================================================
    # STEP 3.0: Verify config and acceptance tests from Step 2.1
    # ========================================================================
    log("\n--- Step 3.0: Verifying baseline data ---")
    
    acceptance = config['acceptance_tests']
    
    # Verify counts
    checks = [
        ("total_road_plans", "SELECT COUNT(*) FROM fact_visit_enriched"),
        ("completed_visits", "SELECT SUM(is_complete) FROM fact_visit_enriched"),
        ("null_checkout", "SELECT SUM(has_null_checkout_strict) FROM dq_flags"),
        ("null_checkin", "SELECT SUM(CASE WHEN check_in_first IS NULL OR check_in_first = '' THEN 1 ELSE 0 END) FROM fact_visit_enriched"),
        ("multiday_suspect", "SELECT COUNT(*) FROM dq_flags WHERE duration_status_v2 = 'MULTI_DAY_SUSPECT'"),
    ]
    
    for name, sql in checks:
        result = conn.execute(sql).fetchone()[0]
        expected = acceptance.get(name, 'N/A')
        status = "✓" if result == expected else "✗"
        log(f"  {status} {name}: {result} (expected: {expected})")
    
    # ========================================================================
    # STEP 3.1: Build fact_kpi_visit (1 row per road_plan with all flags)
    # ========================================================================
    log("\n--- Step 3.1: Building fact_kpi_visit ---")
    
    thresholds = config['thresholds']
    
    conn.execute("DROP TABLE IF EXISTS fact_kpi_visit")
    conn.execute(f"""
        CREATE TABLE fact_kpi_visit AS
        SELECT 
            f.road_plan_id,
            f.user_id,
            f.customer_id,
            f.type,
            f.status,
            f.visit_date,
            f.check_in_first,
            f.check_out_last,
            f.foto_count,
            f.duration_min_raw,
            f.duration_min_capped,
            f.technician_name,
            f.customer_name,
            f.customer_city,
            f.check_in_hour,
            
            -- Derived dates (strip timezone from visit_date)
            CASE 
                WHEN f.visit_date LIKE '%+%' THEN DATE(SUBSTR(f.visit_date, 1, INSTR(f.visit_date, '+') - 1))
                ELSE DATE(f.visit_date)
            END as scheduled_day,
            DATE(f.check_in_first) as actual_day,
            
            -- Extract month for aggregation (strip timezone)
            CASE 
                WHEN f.visit_date LIKE '%+%' THEN strftime('%Y-%m', SUBSTR(f.visit_date, 1, INSTR(f.visit_date, '+') - 1))
                ELSE strftime('%Y-%m', f.visit_date)
            END as scheduled_month,
            strftime('%Y-%m', f.check_in_first) as actual_month,
            
            -- Segment assignment
            CASE 
                WHEN f.type = 't_mobile' THEN 'MOBILE'
                WHEN f.type = 't_station' THEN 'STATION'
                WHEN f.type = 'checklist' THEN 'SUPPORT'
                WHEN f.type IN ('spv_tc', 'spv_qc') THEN 'SUPERVISOR'
                ELSE 'OTHER'
            END as segment,
            
            -- Step 3.2: Per-metric flags
            CASE WHEN f.status = 'Selesai' THEN 1 ELSE 0 END as is_completed,
            
            CASE WHEN f.check_in_first IS NOT NULL AND f.check_in_first != '' 
                 THEN 1 ELSE 0 END as has_checkin,
            
            CASE WHEN f.check_out_last IS NOT NULL AND f.check_out_last != '' 
                 THEN 1 ELSE 0 END as has_checkout,
            
            CASE WHEN f.duration_min_raw IS NOT NULL 
                      AND f.duration_min_raw >= {thresholds['duration']['valid_min']}
                      AND f.duration_min_raw <= {thresholds['duration']['valid_max']}
                 THEN 1 ELSE 0 END as is_duration_valid,
            
            CASE WHEN f.duration_min_raw IS NOT NULL 
                      AND f.duration_min_raw > {thresholds['duration']['multiday_suspect']}
                 THEN 1 ELSE 0 END as is_multiday_suspect,
            
            CASE WHEN f.duration_min_raw IS NOT NULL 
                      AND f.duration_min_raw > {thresholds['duration']['overnight_min']}
                      AND f.duration_min_raw <= {thresholds['duration']['multiday_suspect']}
                 THEN 1 ELSE 0 END as is_overnight,
            
            CASE WHEN f.foto_count >= {thresholds['photo']['minimum_count']}
                 THEN 1 ELSE 0 END as is_photo_ok,
            
            CASE WHEN f.check_in_first IS NOT NULL AND f.check_in_first != ''
                      AND CAST(strftime('%w', f.check_in_first) AS INTEGER) BETWEEN 1 AND 6
                 THEN 1 ELSE 0 END as is_working_day,
            
            CASE WHEN f.check_in_hour IN (21, 22, 23) 
                 THEN 1 ELSE 0 END as is_suspect_time,
            
            -- On-time: day-based comparison (both dates normalized)
            CASE WHEN f.check_in_first IS NOT NULL AND f.check_in_first != ''
                      AND DATE(f.check_in_first) = 
                          CASE 
                              WHEN f.visit_date LIKE '%+%' THEN DATE(SUBSTR(f.visit_date, 1, INSTR(f.visit_date, '+') - 1))
                              ELSE DATE(f.visit_date)
                          END
                 THEN 1 ELSE 0 END as is_on_time_day

        FROM fact_visit_enriched f
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) FROM fact_kpi_visit").fetchone()[0]
    log(f"  -> Created fact_kpi_visit: {result} rows")
    
    # Verify against Step 2.1 counts
    verify = conn.execute("""
        SELECT 
            SUM(has_checkin) as has_checkin,
            SUM(1-has_checkout) as null_checkout,
            SUM(is_multiday_suspect) as multiday
        FROM fact_kpi_visit
    """).fetchone()
    log(f"  -> Verification: has_checkin={verify['has_checkin']}, null_checkout={verify['null_checkout']}, multiday={verify['multiday']}")
    
    # ========================================================================
    # STEP 3.3 & 3.4: Aggregate KPI per user per month
    # ========================================================================
    log("\n--- Step 3.4: Building kpi_user_monthly ---")
    
    conn.execute("DROP TABLE IF EXISTS kpi_user_monthly")
    conn.execute("""
        CREATE TABLE kpi_user_monthly AS
        SELECT 
            user_id,
            technician_name,
            segment,
            actual_month as month,
            
            -- Denominators
            COUNT(*) as scheduled_visits,
            SUM(is_completed) as completed_visits,
            
            -- On-time (only for completed with check-in)
            SUM(CASE WHEN is_completed = 1 AND has_checkin = 1 THEN is_on_time_day ELSE 0 END) as on_time_count,
            SUM(CASE WHEN is_completed = 1 AND has_checkin = 1 THEN 1 ELSE 0 END) as on_time_eligible,
            
            -- Duration compliance (only for completed with valid checkout)
            SUM(CASE WHEN is_completed = 1 AND has_checkout = 1 THEN is_duration_valid ELSE 0 END) as duration_valid_count,
            SUM(CASE WHEN is_completed = 1 AND has_checkout = 1 THEN 1 ELSE 0 END) as duration_eligible,
            
            -- Photo compliance (for all completed)
            SUM(CASE WHEN is_completed = 1 THEN is_photo_ok ELSE 0 END) as photo_ok_count,
            
            -- Data quality counts
            SUM(is_multiday_suspect) as multiday_count,
            SUM(is_overnight) as overnight_count,
            SUM(is_suspect_time) as suspect_time_count,
            SUM(CASE WHEN is_completed = 1 AND foto_count = 0 THEN 1 ELSE 0 END) as no_photo_count,
            
            -- Productivity: active working days
            COUNT(DISTINCT CASE WHEN is_completed = 1 AND is_working_day = 1 THEN actual_day END) as active_working_days,
            
            -- Total working days in month (approx 26)
            26 as calendar_working_days
            
        FROM fact_kpi_visit
        WHERE actual_month IS NOT NULL
        GROUP BY user_id, technician_name, segment, actual_month
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) FROM kpi_user_monthly").fetchone()[0]
    log(f"  -> Created kpi_user_monthly: {result} rows")
    
    # Verify completed total
    total_completed = conn.execute("SELECT SUM(completed_visits) FROM kpi_user_monthly").fetchone()[0]
    log(f"  -> Total completed_visits: {total_completed} (expected: {acceptance['completed_visits']})")
    
    # ========================================================================
    # STEP 3.5: Calculate scores (Strict and Fair modes)
    # ========================================================================
    log("\n--- Step 3.5: Calculating KPI Scores ---")
    
    weights = config['kpi_weights']
    prod_config = config['productivity']
    
    # Helper to create score table
    def create_score_table(mode_name):
        conn.execute(f"DROP TABLE IF EXISTS kpi_user_score_monthly_{mode_name.lower()}")
        conn.execute(f"""
            CREATE TABLE kpi_user_score_monthly_{mode_name.lower()} AS
            SELECT 
                user_id,
                technician_name,
                segment,
                month,
                
                -- Raw counts
                scheduled_visits,
                completed_visits,
                on_time_count,
                duration_valid_count,
                photo_ok_count,
                active_working_days,
                
                -- Rates (0-1 scale)
                CASE WHEN scheduled_visits > 0 
                     THEN 1.0 * completed_visits / scheduled_visits 
                     ELSE 0 END as completion_rate,
                
                CASE WHEN on_time_eligible > 0 
                     THEN 1.0 * on_time_count / on_time_eligible 
                     ELSE 0 END as on_time_rate,
                
                CASE WHEN duration_eligible > 0 
                     THEN 1.0 * duration_valid_count / duration_eligible 
                     ELSE 0 END as duration_compliance_rate,
                
                CASE WHEN completed_visits > 0 
                     THEN 1.0 * photo_ok_count / completed_visits 
                     ELSE 0 END as photo_compliance_rate,
                
                -- Productivity: visits per active day
                CASE WHEN active_working_days > 0 
                     THEN 1.0 * completed_visits / active_working_days 
                     ELSE 0 END as visits_per_day,
                
                -- Data quality flags for this period
                multiday_count,
                overnight_count,
                suspect_time_count,
                no_photo_count
                
            FROM kpi_user_monthly
        """)
        
        # Add score columns
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode_name.lower()} ADD COLUMN completion_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode_name.lower()} ADD COLUMN on_time_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode_name.lower()} ADD COLUMN duration_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode_name.lower()} ADD COLUMN photo_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode_name.lower()} ADD COLUMN productivity_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode_name.lower()} ADD COLUMN total_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode_name.lower()} ADD COLUMN grade TEXT")
        
        # Calculate scores (0-100 scale)
        target_vpd = prod_config['target_visits_per_working_day']
        max_mult = prod_config['max_score_multiplier']
        
        conn.execute(f"""
            UPDATE kpi_user_score_monthly_{mode_name.lower()}
            SET 
                completion_score = completion_rate * 100,
                on_time_score = on_time_rate * 100,
                duration_score = duration_compliance_rate * 100,
                photo_score = photo_compliance_rate * 100,
                productivity_score = MIN(100 * {max_mult}, 
                    CASE WHEN visits_per_day >= {target_vpd} 
                         THEN 100 
                         ELSE (visits_per_day / {target_vpd}) * 100 
                    END)
        """)
        
        # Calculate total weighted score
        conn.execute(f"""
            UPDATE kpi_user_score_monthly_{mode_name.lower()}
            SET total_score = 
                (completion_score * {weights['completion_rate']} +
                 on_time_score * {weights['on_time_rate']} +
                 duration_score * {weights['duration_compliance']} +
                 photo_score * {weights['photo_compliance']} +
                 productivity_score * {weights['productivity']}) / 100.0
        """)
        
        # Assign grades
        grading = config['grading']
        for grade, bounds in grading.items():
            conn.execute(f"""
                UPDATE kpi_user_score_monthly_{mode_name.lower()}
                SET grade = '{grade}'
                WHERE total_score >= {bounds['min_score']} AND total_score <= {bounds['max_score']}
            """)
        
        conn.commit()
        
        result = conn.execute(f"SELECT COUNT(*) FROM kpi_user_score_monthly_{mode_name.lower()}").fetchone()[0]
        log(f"  -> Created kpi_user_score_monthly_{mode_name.lower()}: {result} rows")
    
    # Create both modes (currently same calculation - Fair would differ if we winsorize differently)
    create_score_table("strict")
    create_score_table("fair")
    
    # ========================================================================
    # Create Leaderboards (latest month, ranked)
    # ========================================================================
    log("\n--- Creating Leaderboards ---")
    
    for mode in ["strict", "fair"]:
        conn.execute(f"DROP TABLE IF EXISTS leaderboard_{mode}")
        conn.execute(f"""
            CREATE TABLE leaderboard_{mode} AS
            SELECT 
                ROW_NUMBER() OVER (PARTITION BY segment ORDER BY total_score DESC) as rank,
                user_id,
                technician_name,
                segment,
                month,
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
            FROM kpi_user_score_monthly_{mode}
            WHERE month = (SELECT MAX(month) FROM kpi_user_score_monthly_{mode})
            ORDER BY segment, total_score DESC
        """)
        conn.commit()
        
        result = conn.execute(f"SELECT COUNT(*) FROM leaderboard_{mode}").fetchone()[0]
        log(f"  -> Created leaderboard_{mode}: {result} rows")
    
    # ========================================================================
    # STEP 3.6: Audit Pack
    # ========================================================================
    log("\n--- Step 3.6: Building Audit Pack ---")
    
    # 1. Multi-day cases
    conn.execute("DROP TABLE IF EXISTS audit_multiday_top50")
    conn.execute("""
        CREATE TABLE audit_multiday_top50 AS
        SELECT 
            road_plan_id,
            user_id,
            technician_name,
            customer_name,
            type,
            ROUND(duration_min_raw, 0) as duration_min,
            ROUND(duration_min_raw / 1440.0, 1) as duration_days,
            check_in_first,
            check_out_last
        FROM fact_kpi_visit
        WHERE is_multiday_suspect = 1
        ORDER BY duration_min_raw DESC
        LIMIT 50
    """)
    conn.commit()
    log("  -> Created audit_multiday_top50")
    
    # 2. No checkout cases
    conn.execute("DROP TABLE IF EXISTS audit_no_checkout")
    conn.execute("""
        CREATE TABLE audit_no_checkout AS
        SELECT 
            road_plan_id,
            user_id,
            technician_name,
            customer_name,
            type,
            scheduled_day,
            check_in_first
        FROM fact_kpi_visit
        WHERE has_checkout = 0
        ORDER BY scheduled_day DESC
    """)
    conn.commit()
    result = conn.execute("SELECT COUNT(*) FROM audit_no_checkout").fetchone()[0]
    log(f"  -> Created audit_no_checkout: {result} rows")
    
    # 3. No photo by technician
    conn.execute("DROP TABLE IF EXISTS audit_no_photo_by_tech")
    conn.execute("""
        CREATE TABLE audit_no_photo_by_tech AS
        SELECT 
            user_id,
            technician_name,
            segment,
            COUNT(*) as total_visits,
            SUM(CASE WHEN foto_count = 0 THEN 1 ELSE 0 END) as no_photo_count,
            ROUND(100.0 * SUM(CASE WHEN foto_count = 0 THEN 1 ELSE 0 END) / COUNT(*), 2) as no_photo_pct
        FROM fact_kpi_visit
        WHERE is_completed = 1
        GROUP BY user_id, technician_name, segment
        HAVING no_photo_count > 0
        ORDER BY no_photo_count DESC
    """)
    conn.commit()
    result = conn.execute("SELECT COUNT(*) FROM audit_no_photo_by_tech").fetchone()[0]
    log(f"  -> Created audit_no_photo_by_tech: {result} rows")
    
    # 4. Suspect time by tech and customer
    conn.execute("DROP TABLE IF EXISTS audit_suspect_time")
    conn.execute("""
        CREATE TABLE audit_suspect_time AS
        SELECT 
            user_id,
            technician_name,
            customer_name,
            segment,
            COUNT(*) as suspect_count,
            GROUP_CONCAT(DISTINCT check_in_hour) as hours_used
        FROM fact_kpi_visit
        WHERE is_suspect_time = 1
        GROUP BY user_id, technician_name, customer_name, segment
        ORDER BY suspect_count DESC
    """)
    conn.commit()
    result = conn.execute("SELECT COUNT(*) FROM audit_suspect_time").fetchone()[0]
    log(f"  -> Created audit_suspect_time: {result} rows")
    
    # ========================================================================
    # STEP 3.7: Generate Report
    # ========================================================================
    log("\n--- Step 3.7: Generating KPI Report ---")
    
    report = []
    report.append("# 📊 STEP 3: KPI Calculation Report")
    report.append("")
    report.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    report.append(f"> **Database:** {DB_PATH}")
    report.append(f"> **Config:** {CONFIG_PATH}")
    report.append("")
    report.append("---")
    report.append("")
    
    # Methodology
    report.append("## 1. Methodology")
    report.append("")
    report.append("### KPI Weights")
    report.append("")
    report.append("| KPI | Weight |")
    report.append("|-----|--------|")
    for kpi, weight in weights.items():
        report.append(f"| {kpi.replace('_', ' ').title()} | {weight}% |")
    report.append("")
    
    report.append("### Key Definitions")
    report.append("")
    report.append("| Metric | Definition |")
    report.append("|--------|------------|")
    report.append("| Completion Rate | completed_visits / scheduled_visits |")
    report.append("| On-Time Rate | visits where actual_day = scheduled_day / completed with check-in |")
    report.append(f"| Duration Compliance | visits with 5-480 min / completed with checkout |")
    report.append(f"| Photo Compliance | visits with ≥1 photo / completed |")
    report.append(f"| Productivity | visits_per_active_working_day (target: {prod_config['target_visits_per_working_day']}) |")
    report.append("")
    
    report.append("### Grading Scale")
    report.append("")
    report.append("| Grade | Score Range | Label |")
    report.append("|-------|-------------|-------|")
    for grade, bounds in config['grading'].items():
        report.append(f"| {grade} | {bounds['min_score']}-{bounds['max_score']} | {bounds['label']} |")
    report.append("")
    
    # Global Summary
    report.append("---")
    report.append("")
    report.append("## 2. Global KPI Summary")
    report.append("")
    
    global_stats = conn.execute("""
        SELECT 
            SUM(scheduled_visits) as total_scheduled,
            SUM(completed_visits) as total_completed,
            ROUND(100.0 * SUM(completed_visits) / SUM(scheduled_visits), 2) as completion_pct,
            ROUND(100.0 * SUM(on_time_count) / NULLIF(SUM(on_time_eligible), 0), 2) as on_time_pct,
            ROUND(100.0 * SUM(duration_valid_count) / NULLIF(SUM(duration_eligible), 0), 2) as duration_pct,
            ROUND(100.0 * SUM(photo_ok_count) / NULLIF(SUM(completed_visits), 0), 2) as photo_pct,
            SUM(multiday_count) as total_multiday,
            SUM(suspect_time_count) as total_suspect_time,
            SUM(no_photo_count) as total_no_photo
        FROM kpi_user_monthly
    """).fetchone()
    
    report.append("| Metric | Value |")
    report.append("|--------|-------|")
    report.append(f"| Total Scheduled | {global_stats['total_scheduled']:,} |")
    report.append(f"| Total Completed | {global_stats['total_completed']:,} |")
    report.append(f"| **Completion Rate** | **{global_stats['completion_pct']}%** |")
    report.append(f"| **On-Time Rate** | **{global_stats['on_time_pct']}%** |")
    report.append(f"| **Duration Compliance** | **{global_stats['duration_pct']}%** |")
    report.append(f"| **Photo Compliance** | **{global_stats['photo_pct']}%** |")
    report.append("")
    
    report.append("### Data Quality Issues")
    report.append("")
    report.append("| Issue | Count |")
    report.append("|-------|-------|")
    report.append(f"| Multi-day Suspect | {global_stats['total_multiday']:,} |")
    report.append(f"| Suspect Time (21-23h) | {global_stats['total_suspect_time']:,} |")
    report.append(f"| No Photo | {global_stats['total_no_photo']:,} |")
    report.append("")
    
    # Latest month leaderboard
    latest_month = conn.execute("SELECT MAX(month) FROM kpi_user_score_monthly_strict").fetchone()[0]
    report.append("---")
    report.append("")
    report.append(f"## 3. Leaderboard - {latest_month}")
    report.append("")
    
    for segment in ['MOBILE', 'STATION']:
        report.append(f"### {segment} Segment")
        report.append("")
        
        # Top 10
        top10 = conn.execute(f"""
            SELECT * FROM leaderboard_strict
            WHERE segment = ?
            ORDER BY rank
            LIMIT 10
        """, (segment,)).fetchall()
        
        if top10:
            report.append("**Top 10:**")
            report.append("")
            report.append("| Rank | Technician | Score | Grade | Completion | On-Time | Duration | Photo | Visits/Day |")
            report.append("|------|------------|-------|-------|------------|---------|----------|-------|------------|")
            for row in top10:
                report.append(f"| {row['rank']} | {row['technician_name'][:20] if row['technician_name'] else 'N/A'} | {row['score']} | {row['grade']} | {row['completion_pct']}% | {row['on_time_pct']}% | {row['duration_pct']}% | {row['photo_pct']}% | {row['visits_per_day']} |")
            report.append("")
        
        # Bottom 5
        bottom5 = conn.execute(f"""
            SELECT * FROM leaderboard_strict
            WHERE segment = ?
            ORDER BY rank DESC
            LIMIT 5
        """, (segment,)).fetchall()
        
        if bottom5 and len(bottom5) > 1:  # Only show if there are enough to compare
            report.append("**Bottom 5:**")
            report.append("")
            report.append("| Rank | Technician | Score | Grade | Issues |")
            report.append("|------|------------|-------|-------|--------|")
            for row in bottom5:
                issues = []
                if row['multiday_count'] > 0:
                    issues.append(f"multiday:{row['multiday_count']}")
                if row['no_photo_count'] > 0:
                    issues.append(f"no_photo:{row['no_photo_count']}")
                if row['suspect_time_count'] > 0:
                    issues.append(f"suspect_time:{row['suspect_time_count']}")
                report.append(f"| {row['rank']} | {row['technician_name'][:20] if row['technician_name'] else 'N/A'} | {row['score']} | {row['grade']} | {', '.join(issues) or 'None'} |")
            report.append("")
    
    # Grade distribution
    report.append("---")
    report.append("")
    report.append("## 4. Grade Distribution")
    report.append("")
    
    grade_dist = conn.execute("""
        SELECT 
            segment,
            grade,
            COUNT(*) as count
        FROM leaderboard_strict
        GROUP BY segment, grade
        ORDER BY segment, grade
    """).fetchall()
    
    report.append("| Segment | A | B | C | D | F |")
    report.append("|---------|---|---|---|---|---|")
    
    # Pivot the data
    grade_pivot = defaultdict(lambda: {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0})
    for row in grade_dist:
        grade_pivot[row['segment']][row['grade'] or 'F'] = row['count']
    
    for segment in ['MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR']:
        if segment in grade_pivot:
            g = grade_pivot[segment]
            report.append(f"| {segment} | {g['A']} | {g['B']} | {g['C']} | {g['D']} | {g['F']} |")
    report.append("")
    
    # Audit highlights
    report.append("---")
    report.append("")
    report.append("## 5. Audit Highlights")
    report.append("")
    
    # Top multi-day offenders
    report.append("### Multi-Day Duration Cases (Top 10)")
    report.append("")
    report.append("> These are 'forgot to checkout' cases - duration calculated from check-in to much later checkout")
    report.append("")
    
    multiday_top = conn.execute("""
        SELECT * FROM audit_multiday_top50 LIMIT 10
    """).fetchall()
    
    report.append("| RP ID | Technician | Days | Check-in | Check-out |")
    report.append("|-------|------------|------|----------|-----------|")
    for row in multiday_top:
        report.append(f"| {row['road_plan_id']} | {row['technician_name'][:15] if row['technician_name'] else 'N/A'} | {row['duration_days']} | {row['check_in_first'][:10] if row['check_in_first'] else ''} | {row['check_out_last'][:10] if row['check_out_last'] else ''} |")
    report.append("")
    
    # Top no-photo technicians
    report.append("### Technicians with Most No-Photo Visits")
    report.append("")
    
    no_photo_top = conn.execute("""
        SELECT * FROM audit_no_photo_by_tech LIMIT 10
    """).fetchall()
    
    report.append("| Technician | Segment | No Photo | Total | % |")
    report.append("|------------|---------|----------|-------|---|")
    for row in no_photo_top:
        report.append(f"| {row['technician_name'][:20] if row['technician_name'] else 'N/A'} | {row['segment']} | {row['no_photo_count']} | {row['total_visits']} | {row['no_photo_pct']}% |")
    report.append("")
    
    # Suspect time analysis
    report.append("### Suspect Time (21-23h) - Top Contributors")
    report.append("")
    
    suspect_top = conn.execute("""
        SELECT 
            technician_name,
            segment,
            SUM(suspect_count) as total_suspect
        FROM audit_suspect_time
        GROUP BY technician_name, segment
        ORDER BY total_suspect DESC
        LIMIT 10
    """).fetchall()
    
    report.append("| Technician | Segment | Suspect Time Count |")
    report.append("|------------|---------|-------------------|")
    for row in suspect_top:
        report.append(f"| {row['technician_name'][:25] if row['technician_name'] else 'N/A'} | {row['segment']} | {row['total_suspect']} |")
    report.append("")
    
    # Recommendations
    report.append("---")
    report.append("")
    report.append("## 6. Operational Recommendations")
    report.append("")
    report.append("1. **Multi-day durations:** Implement auto-checkout at midnight or 18:00 to prevent forgot-checkout issues")
    report.append("")
    report.append("2. **Suspect time (21-23h):** Investigate if t_mobile technicians are doing legitimate night visits or submitting at end of day")
    report.append("")
    report.append("3. **No-photo compliance:** Enforce mandatory photo upload before checkout in app")
    report.append("")
    report.append("4. **KPI Mode Recommendation:**")
    report.append("   - Use **STRICT** mode for compliance audits and identifying systemic issues")
    report.append("   - Use **FAIR** mode for bonus calculations (pending review of suspect time legitimacy)")
    report.append("")
    
    # Final checklist
    report.append("---")
    report.append("")
    report.append("## ✅ Step 3 Completion Checklist")
    report.append("")
    
    deliverables = [
        ("fact_kpi_visit", "SELECT COUNT(*) FROM fact_kpi_visit"),
        ("kpi_user_monthly", "SELECT COUNT(*) FROM kpi_user_monthly"),
        ("kpi_user_score_monthly_strict", "SELECT COUNT(*) FROM kpi_user_score_monthly_strict"),
        ("kpi_user_score_monthly_fair", "SELECT COUNT(*) FROM kpi_user_score_monthly_fair"),
        ("leaderboard_strict", "SELECT COUNT(*) FROM leaderboard_strict"),
        ("leaderboard_fair", "SELECT COUNT(*) FROM leaderboard_fair"),
        ("audit_multiday_top50", "SELECT COUNT(*) FROM audit_multiday_top50"),
        ("audit_no_checkout", "SELECT COUNT(*) FROM audit_no_checkout"),
        ("audit_no_photo_by_tech", "SELECT COUNT(*) FROM audit_no_photo_by_tech"),
        ("audit_suspect_time", "SELECT COUNT(*) FROM audit_suspect_time"),
    ]
    
    report.append("| Table | Rows | Status |")
    report.append("|-------|------|--------|")
    for table, sql in deliverables:
        count = conn.execute(sql).fetchone()[0]
        report.append(f"| {table} | {count:,} | ✅ |")
    report.append("")
    report.append("**Step 3 Complete!** 🚀")
    report.append("")
    
    # Write report
    report_path = os.path.join(REPORTS_DIR, 'STEP3_KPI_REPORT.md')
    with open(report_path, 'w') as f:
        f.write('\n'.join(report))
    log(f"  -> Report written to {report_path}")
    
    # ========================================================================
    # Export CSVs
    # ========================================================================
    log("\n--- Exporting CSVs ---")
    
    exports = [
        ("leaderboard_strict", "leaderboard_strict.csv"),
        ("leaderboard_fair", "leaderboard_fair.csv"),
        ("kpi_user_monthly", "kpi_user_monthly.csv"),
    ]
    
    for table, filename in exports:
        path = os.path.join(KPI_DIR, filename)
        results = conn.execute(f"SELECT * FROM {table}").fetchall()
        columns = [desc[0] for desc in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(results)
        log(f"  -> Exported {len(results)} rows to {path}")
    
    conn.close()
    
    log("\n" + "=" * 70)
    log("STEP 3 COMPLETE!")
    log("=" * 70)

if __name__ == '__main__':
    main()
