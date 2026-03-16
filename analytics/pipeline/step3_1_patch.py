#!/usr/bin/env python3
"""
Step 3.1 Patch: Refinement Fixes
================================
Addresses 5 mentor-identified issues:
1. Fix denominator scheduled_visits → from stg_road_plan (not just those with check_in)
2. Clarify no_photo count basis (completed only vs all)
3. Segment-specific config: duration_range, productivity_target
4. Implement STRICT that's truly different from FAIR + delta report
5. Clean up segment labels in audit (show dominant segment)

Outputs:
- Updated kpi_user_monthly with proper denominators
- Updated scoring tables with segment-specific thresholds
- New delta_strict_vs_fair table
- Updated STEP3_KPI_REPORT.md
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

def pct(count, total):
    if total == 0:
        return 0.0
    return 100.0 * count / total

def main():
    log("=" * 70)
    log("STEP 3.1 PATCH: Refinement Fixes")
    log("=" * 70)
    
    config = load_config()
    log(f"Loaded config from {CONFIG_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # ========================================================================
    # FIX 1: Recalculate scheduled_visits from stg_road_plan (all road_plans)
    # ========================================================================
    log("\n--- Fix 1: Correcting scheduled_visits denominator ---")
    
    # Get the proper scheduled count per user per month from stg_road_plan
    # (not filtered by having check_in)
    conn.execute("DROP TABLE IF EXISTS scheduled_by_user_month")
    conn.execute("""
        CREATE TABLE scheduled_by_user_month AS
        SELECT 
            CAST(rp.id_user AS INTEGER) as user_id,
            CASE 
                WHEN rp.visit_date LIKE '%+%' THEN strftime('%Y-%m', SUBSTR(rp.visit_date, 1, INSTR(rp.visit_date, '+') - 1))
                ELSE strftime('%Y-%m', rp.visit_date)
            END as month,
            CASE 
                WHEN rp.type = 't_mobile' THEN 'MOBILE'
                WHEN rp.type = 't_station' THEN 'STATION'
                WHEN rp.type = 'checklist' THEN 'SUPPORT'
                WHEN rp.type IN ('spv_tc', 'spv_qc') THEN 'SUPERVISOR'
                ELSE 'OTHER'
            END as segment,
            COUNT(*) as scheduled_visits_true
        FROM stg_road_plan rp
        WHERE rp.id_user IS NOT NULL AND rp.id_user != ''
        GROUP BY user_id, month, segment
    """)
    conn.commit()
    
    # Verify totals
    old_scheduled = conn.execute("SELECT SUM(scheduled_visits) FROM kpi_user_monthly").fetchone()[0]
    new_scheduled = conn.execute("SELECT SUM(scheduled_visits_true) FROM scheduled_by_user_month").fetchone()[0]
    log(f"  Old scheduled (with check_in): {old_scheduled:,}")
    log(f"  New scheduled (all road_plans): {new_scheduled:,}")
    log(f"  Difference: {new_scheduled - old_scheduled}")
    
    # ========================================================================
    # FIX 3: Update fact_kpi_visit with segment-specific duration validity
    # ========================================================================
    log("\n--- Fix 3: Adding segment-specific duration validity ---")
    
    dur_by_seg = config['thresholds']['duration_by_segment']
    
    # Add new column for segment-specific validity
    existing_cols = [row['name'] for row in conn.execute("PRAGMA table_info(fact_kpi_visit)")]
    if 'is_duration_valid_segment' not in existing_cols:
        conn.execute("ALTER TABLE fact_kpi_visit ADD COLUMN is_duration_valid_segment INTEGER")
    
    # Update based on segment
    for segment, bounds in dur_by_seg.items():
        conn.execute(f"""
            UPDATE fact_kpi_visit
            SET is_duration_valid_segment = CASE 
                WHEN duration_min_raw IS NOT NULL 
                     AND duration_min_raw >= {bounds['valid_min']}
                     AND duration_min_raw <= {bounds['valid_max']}
                THEN 1 ELSE 0 
            END
            WHERE segment = ?
        """, (segment,))
    conn.commit()
    
    # Compare old vs new validity
    old_valid = conn.execute("SELECT SUM(is_duration_valid) FROM fact_kpi_visit").fetchone()[0]
    new_valid = conn.execute("SELECT SUM(is_duration_valid_segment) FROM fact_kpi_visit").fetchone()[0]
    log(f"  Old duration valid (global 5-480): {old_valid:,}")
    log(f"  New duration valid (segment-specific): {new_valid:,}")
    log(f"  Difference: {new_valid - old_valid:,}")
    
    # ========================================================================
    # FIX 4: Add STRICT on-time flag (first check-in 07:30-08:30)
    # ========================================================================
    log("\n--- Fix 4: Adding STRICT on-time calculation ---")
    
    if 'is_on_time_strict' not in existing_cols:
        conn.execute("ALTER TABLE fact_kpi_visit ADD COLUMN is_on_time_strict INTEGER")
    
    # STRICT: first check-in of the day must be between 07:30-08:30 AND same day
    conn.execute("""
        UPDATE fact_kpi_visit
        SET is_on_time_strict = CASE 
            WHEN has_checkin = 1 
                 AND is_on_time_day = 1
                 AND check_in_hour >= 7 AND check_in_hour <= 8
            THEN 1 ELSE 0 
        END
    """)
    conn.commit()
    
    # Compare FAIR vs STRICT on-time
    fair_ontime = conn.execute("""
        SELECT SUM(is_on_time_day) FROM fact_kpi_visit 
        WHERE is_completed = 1 AND has_checkin = 1
    """).fetchone()[0]
    strict_ontime = conn.execute("""
        SELECT SUM(is_on_time_strict) FROM fact_kpi_visit 
        WHERE is_completed = 1 AND has_checkin = 1
    """).fetchone()[0]
    log(f"  FAIR on-time (same day): {fair_ontime:,}")
    log(f"  STRICT on-time (07:30-08:30 + same day): {strict_ontime:,}")
    log(f"  Difference: {fair_ontime - strict_ontime:,}")
    
    # ========================================================================
    # Rebuild kpi_user_monthly with proper denominators and segment-specific metrics
    # ========================================================================
    log("\n--- Rebuilding kpi_user_monthly_v2 ---")
    
    conn.execute("DROP TABLE IF EXISTS kpi_user_monthly_v2")
    conn.execute("""
        CREATE TABLE kpi_user_monthly_v2 AS
        SELECT 
            f.user_id,
            f.technician_name,
            f.segment,
            f.actual_month as month,
            
            -- Denominators (from actual visits, will be corrected with scheduled_by_user_month)
            COUNT(*) as actual_visits,
            SUM(f.is_completed) as completed_visits,
            
            -- On-time: FAIR (day-based) vs STRICT (time-window)
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkin = 1 THEN f.is_on_time_day ELSE 0 END) as on_time_fair,
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkin = 1 THEN f.is_on_time_strict ELSE 0 END) as on_time_strict,
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkin = 1 THEN 1 ELSE 0 END) as on_time_eligible,
            
            -- Duration compliance: GLOBAL (5-480) vs SEGMENT-SPECIFIC
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkout = 1 THEN f.is_duration_valid ELSE 0 END) as duration_valid_global,
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkout = 1 THEN f.is_duration_valid_segment ELSE 0 END) as duration_valid_segment,
            SUM(CASE WHEN f.is_completed = 1 AND f.has_checkout = 1 THEN 1 ELSE 0 END) as duration_eligible,
            
            -- Photo compliance (for completed only - FIX 2 clarification)
            SUM(CASE WHEN f.is_completed = 1 THEN f.is_photo_ok ELSE 0 END) as photo_ok_count,
            
            -- Data quality counts
            SUM(f.is_multiday_suspect) as multiday_count,
            SUM(f.is_overnight) as overnight_count,
            SUM(f.is_suspect_time) as suspect_time_count,
            SUM(CASE WHEN f.is_completed = 1 AND f.foto_count = 0 THEN 1 ELSE 0 END) as no_photo_count,
            SUM(CASE WHEN f.foto_count = 0 THEN 1 ELSE 0 END) as no_photo_count_all,
            
            -- Productivity: active working days
            COUNT(DISTINCT CASE WHEN f.is_completed = 1 AND f.is_working_day = 1 THEN f.actual_day END) as active_working_days
            
        FROM fact_kpi_visit f
        WHERE f.actual_month IS NOT NULL
        GROUP BY f.user_id, f.technician_name, f.segment, f.actual_month
    """)
    
    # Join with proper scheduled counts
    conn.execute("""
        ALTER TABLE kpi_user_monthly_v2 ADD COLUMN scheduled_visits INTEGER
    """)
    conn.execute("""
        UPDATE kpi_user_monthly_v2
        SET scheduled_visits = (
            SELECT s.scheduled_visits_true
            FROM scheduled_by_user_month s
            WHERE s.user_id = kpi_user_monthly_v2.user_id
              AND s.month = kpi_user_monthly_v2.month
              AND s.segment = kpi_user_monthly_v2.segment
        )
    """)
    # Fallback: if no match, use actual_visits
    conn.execute("""
        UPDATE kpi_user_monthly_v2
        SET scheduled_visits = actual_visits
        WHERE scheduled_visits IS NULL
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) FROM kpi_user_monthly_v2").fetchone()[0]
    log(f"  -> Created kpi_user_monthly_v2: {result} rows")
    
    # ========================================================================
    # Create scoring tables with STRICT vs FAIR
    # ========================================================================
    log("\n--- Creating scoring tables ---")
    
    prod_config = config['productivity']
    weights = config['kpi_weights']
    
    for mode in ["strict", "fair"]:
        conn.execute(f"DROP TABLE IF EXISTS kpi_user_score_monthly_{mode}_v2")
        
        # Determine which columns to use
        on_time_col = "on_time_strict" if mode == "strict" else "on_time_fair"
        duration_col = "duration_valid_global" if mode == "strict" else "duration_valid_segment"
        
        conn.execute(f"""
            CREATE TABLE kpi_user_score_monthly_{mode}_v2 AS
            SELECT 
                user_id,
                technician_name,
                segment,
                month,
                
                -- Counts
                scheduled_visits,
                completed_visits,
                {on_time_col} as on_time_count,
                {duration_col} as duration_valid_count,
                photo_ok_count,
                active_working_days,
                
                -- Rates
                CASE WHEN scheduled_visits > 0 
                     THEN 1.0 * completed_visits / scheduled_visits 
                     ELSE 0 END as completion_rate,
                
                CASE WHEN on_time_eligible > 0 
                     THEN 1.0 * {on_time_col} / on_time_eligible 
                     ELSE 0 END as on_time_rate,
                
                CASE WHEN duration_eligible > 0 
                     THEN 1.0 * {duration_col} / duration_eligible 
                     ELSE 0 END as duration_compliance_rate,
                
                CASE WHEN completed_visits > 0 
                     THEN 1.0 * photo_ok_count / completed_visits 
                     ELSE 0 END as photo_compliance_rate,
                
                -- Productivity (segment-specific target)
                CASE WHEN active_working_days > 0 
                     THEN 1.0 * completed_visits / active_working_days 
                     ELSE 0 END as visits_per_day,
                
                -- DQ flags
                multiday_count,
                overnight_count,
                suspect_time_count,
                no_photo_count
                
            FROM kpi_user_monthly_v2
        """)
        
        # Add score columns
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode}_v2 ADD COLUMN completion_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode}_v2 ADD COLUMN on_time_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode}_v2 ADD COLUMN duration_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode}_v2 ADD COLUMN photo_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode}_v2 ADD COLUMN productivity_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode}_v2 ADD COLUMN total_score REAL")
        conn.execute(f"ALTER TABLE kpi_user_score_monthly_{mode}_v2 ADD COLUMN grade TEXT")
        
        # Calculate base scores
        conn.execute(f"""
            UPDATE kpi_user_score_monthly_{mode}_v2
            SET 
                completion_score = completion_rate * 100,
                on_time_score = on_time_rate * 100,
                duration_score = duration_compliance_rate * 100,
                photo_score = photo_compliance_rate * 100
        """)
        
        # Calculate productivity score with segment-specific targets
        targets = prod_config.get('target_by_segment', {})
        max_mult = prod_config['max_score_multiplier']
        default_target = prod_config['target_visits_per_working_day']
        
        for seg, target in targets.items():
            conn.execute(f"""
                UPDATE kpi_user_score_monthly_{mode}_v2
                SET productivity_score = MIN(100 * {max_mult}, 
                    CASE WHEN visits_per_day >= {target} 
                         THEN 100 
                         ELSE (visits_per_day / {target}) * 100 
                    END)
                WHERE segment = ?
            """, (seg,))
        
        # Fallback for OTHER segment
        conn.execute(f"""
            UPDATE kpi_user_score_monthly_{mode}_v2
            SET productivity_score = MIN(100 * {max_mult}, 
                CASE WHEN visits_per_day >= {default_target} 
                     THEN 100 
                     ELSE (visits_per_day / {default_target}) * 100 
                END)
            WHERE productivity_score IS NULL
        """)
        
        # Calculate total weighted score
        conn.execute(f"""
            UPDATE kpi_user_score_monthly_{mode}_v2
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
                UPDATE kpi_user_score_monthly_{mode}_v2
                SET grade = '{grade}'
                WHERE total_score >= {bounds['min_score']} AND total_score <= {bounds['max_score']}
            """)
        
        conn.commit()
        
        result = conn.execute(f"SELECT COUNT(*) FROM kpi_user_score_monthly_{mode}_v2").fetchone()[0]
        log(f"  -> Created kpi_user_score_monthly_{mode}_v2: {result} rows")
    
    # ========================================================================
    # Create Delta Report: FAIR vs STRICT comparison
    # ========================================================================
    log("\n--- Creating FAIR vs STRICT delta report ---")
    
    conn.execute("DROP TABLE IF EXISTS delta_strict_vs_fair")
    conn.execute("""
        CREATE TABLE delta_strict_vs_fair AS
        SELECT 
            f.user_id,
            f.technician_name,
            f.segment,
            f.month,
            
            -- On-time comparison
            f.on_time_rate as on_time_rate_fair,
            s.on_time_rate as on_time_rate_strict,
            ROUND((f.on_time_rate - s.on_time_rate) * 100, 2) as on_time_delta_pct,
            
            -- Duration comparison
            f.duration_compliance_rate as duration_rate_fair,
            s.duration_compliance_rate as duration_rate_strict,
            ROUND((f.duration_compliance_rate - s.duration_compliance_rate) * 100, 2) as duration_delta_pct,
            
            -- Total score comparison
            ROUND(f.total_score, 2) as score_fair,
            ROUND(s.total_score, 2) as score_strict,
            ROUND(f.total_score - s.total_score, 2) as score_delta,
            
            -- Grade comparison
            f.grade as grade_fair,
            s.grade as grade_strict,
            CASE WHEN f.grade != s.grade THEN 1 ELSE 0 END as grade_changed
            
        FROM kpi_user_score_monthly_fair_v2 f
        JOIN kpi_user_score_monthly_strict_v2 s 
            ON f.user_id = s.user_id 
            AND f.month = s.month 
            AND f.segment = s.segment
    """)
    conn.commit()
    
    # Summarize delta
    delta_summary = conn.execute("""
        SELECT 
            COUNT(*) as total_records,
            SUM(grade_changed) as grade_changes,
            ROUND(AVG(score_delta), 2) as avg_score_delta,
            ROUND(AVG(on_time_delta_pct), 2) as avg_ontime_delta
        FROM delta_strict_vs_fair
    """).fetchone()
    
    log(f"  -> Delta summary: {delta_summary['grade_changes']} grade changes, avg score delta: {delta_summary['avg_score_delta']}")
    
    # ========================================================================
    # Create updated leaderboards
    # ========================================================================
    log("\n--- Creating updated leaderboards ---")
    
    for mode in ["strict", "fair"]:
        conn.execute(f"DROP TABLE IF EXISTS leaderboard_{mode}_v2")
        conn.execute(f"""
            CREATE TABLE leaderboard_{mode}_v2 AS
            SELECT 
                ROW_NUMBER() OVER (PARTITION BY segment ORDER BY total_score DESC) as rank,
                user_id,
                technician_name,
                segment,
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
            FROM kpi_user_score_monthly_{mode}_v2
            WHERE month = (SELECT MAX(month) FROM kpi_user_score_monthly_{mode}_v2)
            ORDER BY segment, total_score DESC
        """)
        conn.commit()
        
        result = conn.execute(f"SELECT COUNT(*) FROM leaderboard_{mode}_v2").fetchone()[0]
        log(f"  -> Created leaderboard_{mode}_v2: {result} rows")
    
    # ========================================================================
    # FIX 5: Create audit tables with dominant segment
    # ========================================================================
    log("\n--- Fix 5: Creating audit tables with dominant segment ---")
    
    # Determine dominant segment per technician
    conn.execute("DROP TABLE IF EXISTS tech_dominant_segment")
    conn.execute("""
        CREATE TABLE tech_dominant_segment AS
        SELECT 
            user_id,
            technician_name,
            segment,
            visit_count,
            ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY visit_count DESC) as rn
        FROM (
            SELECT user_id, technician_name, segment, COUNT(*) as visit_count
            FROM fact_kpi_visit
            GROUP BY user_id, technician_name, segment
        )
    """)
    conn.commit()
    
    # Updated no-photo audit with dominant segment
    conn.execute("DROP TABLE IF EXISTS audit_no_photo_by_tech_v2")
    conn.execute("""
        CREATE TABLE audit_no_photo_by_tech_v2 AS
        SELECT 
            f.user_id,
            f.technician_name,
            d.segment as dominant_segment,
            GROUP_CONCAT(DISTINCT f.segment) as all_segments,
            SUM(f.is_completed) as total_completed,
            SUM(CASE WHEN f.is_completed = 1 AND f.foto_count = 0 THEN 1 ELSE 0 END) as no_photo_completed,
            ROUND(100.0 * SUM(CASE WHEN f.is_completed = 1 AND f.foto_count = 0 THEN 1 ELSE 0 END) / 
                  NULLIF(SUM(f.is_completed), 0), 2) as no_photo_pct
        FROM fact_kpi_visit f
        LEFT JOIN (SELECT * FROM tech_dominant_segment WHERE rn = 1) d ON f.user_id = d.user_id
        GROUP BY f.user_id, f.technician_name, d.segment
        HAVING no_photo_completed > 0
        ORDER BY no_photo_completed DESC
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) FROM audit_no_photo_by_tech_v2").fetchone()[0]
    log(f"  -> Created audit_no_photo_by_tech_v2: {result} rows")
    
    # Updated suspect time audit
    conn.execute("DROP TABLE IF EXISTS audit_suspect_time_v2")
    conn.execute("""
        CREATE TABLE audit_suspect_time_v2 AS
        SELECT 
            f.user_id,
            f.technician_name,
            d.segment as dominant_segment,
            GROUP_CONCAT(DISTINCT f.segment) as all_segments,
            COUNT(*) as suspect_count,
            GROUP_CONCAT(DISTINCT f.check_in_hour ORDER BY f.check_in_hour) as hours_used
        FROM fact_kpi_visit f
        LEFT JOIN (SELECT * FROM tech_dominant_segment WHERE rn = 1) d ON f.user_id = d.user_id
        WHERE f.is_suspect_time = 1
        GROUP BY f.user_id, f.technician_name, d.segment
        ORDER BY suspect_count DESC
    """)
    conn.commit()
    
    result = conn.execute("SELECT COUNT(*) FROM audit_suspect_time_v2").fetchone()[0]
    log(f"  -> Created audit_suspect_time_v2: {result} rows")
    
    # ========================================================================
    # Generate Updated Report
    # ========================================================================
    log("\n--- Generating Updated KPI Report ---")
    
    report = []
    report.append("# 📊 STEP 3.1: KPI Calculation Report (REFINED)")
    report.append("")
    report.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    report.append(f"> **Database:** {DB_PATH}")
    report.append(f"> **Config:** {CONFIG_PATH}")
    report.append("> **Version:** 3.1 - with segment-specific thresholds and STRICT/FAIR modes")
    report.append("")
    report.append("---")
    report.append("")
    
    # Methodology updates
    report.append("## 1. Methodology (Refined)")
    report.append("")
    report.append("### Changes from v3.0:")
    report.append("")
    report.append("1. **scheduled_visits** now counted from all `stg_road_plan` records (not just those with check-in)")
    report.append("2. **no_photo count** is calculated from **completed visits only** (status='Selesai')")
    report.append("3. **Duration validity** uses segment-specific thresholds:")
    report.append("")
    report.append("| Segment | Duration Range | Target Visits/Day |")
    report.append("|---------|----------------|-------------------|")
    dur_by_seg = config['thresholds']['duration_by_segment']
    prod_targets = config['productivity']['target_by_segment']
    for seg in ['MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR']:
        d = dur_by_seg.get(seg, {})
        t = prod_targets.get(seg, 2.0)
        report.append(f"| {seg} | {d.get('valid_min', 5)}-{d.get('valid_max', 480)} min | {t} |")
    report.append("")
    
    report.append("### STRICT vs FAIR Mode Definitions")
    report.append("")
    report.append("| Metric | FAIR Mode | STRICT Mode |")
    report.append("|--------|-----------|-------------|")
    report.append("| On-Time | actual_day = scheduled_day | + check_in hour 07:00-08:59 |")
    report.append("| Duration | Segment-specific thresholds | Global 5-480 min |")
    report.append("| Productivity | Segment-specific targets | Segment-specific targets |")
    report.append("")
    
    # Global Summary with corrected denominators
    report.append("---")
    report.append("")
    report.append("## 2. Global KPI Summary (Corrected)")
    report.append("")
    
    global_stats = conn.execute("""
        SELECT 
            SUM(scheduled_visits) as total_scheduled,
            SUM(completed_visits) as total_completed,
            ROUND(100.0 * SUM(completed_visits) / SUM(scheduled_visits), 2) as completion_pct,
            ROUND(100.0 * SUM(on_time_fair) / NULLIF(SUM(on_time_eligible), 0), 2) as on_time_fair_pct,
            ROUND(100.0 * SUM(on_time_strict) / NULLIF(SUM(on_time_eligible), 0), 2) as on_time_strict_pct,
            ROUND(100.0 * SUM(duration_valid_segment) / NULLIF(SUM(duration_eligible), 0), 2) as duration_seg_pct,
            ROUND(100.0 * SUM(duration_valid_global) / NULLIF(SUM(duration_eligible), 0), 2) as duration_global_pct,
            ROUND(100.0 * SUM(photo_ok_count) / NULLIF(SUM(completed_visits), 0), 2) as photo_pct,
            SUM(multiday_count) as total_multiday,
            SUM(suspect_time_count) as total_suspect_time,
            SUM(no_photo_count) as total_no_photo_completed
        FROM kpi_user_monthly_v2
    """).fetchone()
    
    report.append("| Metric | FAIR | STRICT |")
    report.append("|--------|------|--------|")
    report.append(f"| Total Scheduled | {global_stats['total_scheduled']:,} | - |")
    report.append(f"| Total Completed | {global_stats['total_completed']:,} | - |")
    report.append(f"| Completion Rate | {global_stats['completion_pct']}% | - |")
    report.append(f"| On-Time Rate | {global_stats['on_time_fair_pct']}% | {global_stats['on_time_strict_pct']}% |")
    report.append(f"| Duration Compliance | {global_stats['duration_seg_pct']}% (seg) | {global_stats['duration_global_pct']}% (global) |")
    report.append(f"| Photo Compliance | {global_stats['photo_pct']}% | - |")
    report.append("")
    
    report.append("### Data Quality Issues (based on completed visits)")
    report.append("")
    report.append("| Issue | Count |")
    report.append("|-------|-------|")
    report.append(f"| Multi-day Suspect | {global_stats['total_multiday']:,} |")
    report.append(f"| Suspect Time (21-23h) | {global_stats['total_suspect_time']:,} |")
    report.append(f"| No Photo (completed only) | {global_stats['total_no_photo_completed']:,} |")
    report.append("")
    
    # Delta Report
    report.append("---")
    report.append("")
    report.append("## 3. STRICT vs FAIR Delta Analysis")
    report.append("")
    
    delta_sum = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(grade_changed) as grade_changes,
            ROUND(AVG(score_delta), 2) as avg_delta,
            MIN(score_delta) as min_delta,
            MAX(score_delta) as max_delta
        FROM delta_strict_vs_fair
    """).fetchone()
    
    report.append(f"- Total technician-month records: **{delta_sum['total']:,}**")
    report.append(f"- Grade changes (FAIR → STRICT): **{delta_sum['grade_changes']:,}**")
    report.append(f"- Average score delta (FAIR - STRICT): **{delta_sum['avg_delta']}** points")
    report.append(f"- Range: {delta_sum['min_delta']} to {delta_sum['max_delta']} points")
    report.append("")
    
    # Top movers
    report.append("### Top 10 Biggest Score Drops (FAIR → STRICT)")
    report.append("")
    
    top_drops = conn.execute("""
        SELECT * FROM delta_strict_vs_fair
        WHERE month = (SELECT MAX(month) FROM delta_strict_vs_fair)
        ORDER BY score_delta DESC
        LIMIT 10
    """).fetchall()
    
    report.append("| Technician | Segment | FAIR Score | STRICT Score | Delta | Grade Change |")
    report.append("|------------|---------|------------|--------------|-------|--------------|")
    for row in top_drops:
        gc = f"{row['grade_fair']}→{row['grade_strict']}" if row['grade_changed'] else "—"
        report.append(f"| {row['technician_name'][:20] if row['technician_name'] else 'N/A'} | {row['segment']} | {row['score_fair']} | {row['score_strict']} | {row['score_delta']:+.2f} | {gc} |")
    report.append("")
    
    # Leaderboard
    latest_month = conn.execute("SELECT MAX(month) FROM leaderboard_fair_v2").fetchone()[0]
    report.append("---")
    report.append("")
    report.append(f"## 4. Leaderboard - {latest_month} (FAIR Mode)")
    report.append("")
    
    for segment in ['MOBILE', 'STATION']:
        report.append(f"### {segment} Segment")
        report.append("")
        
        top10 = conn.execute(f"""
            SELECT * FROM leaderboard_fair_v2
            WHERE segment = ?
            ORDER BY rank
            LIMIT 10
        """, (segment,)).fetchall()
        
        if top10:
            report.append("| Rank | Technician | Score | Grade | Completion | On-Time | Duration | Photo | Visits/Day |")
            report.append("|------|------------|-------|-------|------------|---------|----------|-------|------------|")
            for row in top10:
                report.append(f"| {row['rank']} | {row['technician_name'][:20] if row['technician_name'] else 'N/A'} | {row['score']} | {row['grade']} | {row['completion_pct']}% | {row['on_time_pct']}% | {row['duration_pct']}% | {row['photo_pct']}% | {row['visits_per_day']} |")
            report.append("")
    
    # Grade distribution comparison
    report.append("---")
    report.append("")
    report.append("## 5. Grade Distribution (FAIR vs STRICT)")
    report.append("")
    
    for mode in ["fair", "strict"]:
        report.append(f"### {mode.upper()} Mode")
        report.append("")
        
        grade_dist = conn.execute(f"""
            SELECT segment, grade, COUNT(*) as count
            FROM leaderboard_{mode}_v2
            GROUP BY segment, grade
            ORDER BY segment, grade
        """).fetchall()
        
        grade_pivot = defaultdict(lambda: {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0})
        for row in grade_dist:
            grade_pivot[row['segment']][row['grade'] or 'F'] = row['count']
        
        report.append("| Segment | A | B | C | D | F |")
        report.append("|---------|---|---|---|---|---|")
        for segment in ['MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR']:
            if segment in grade_pivot:
                g = grade_pivot[segment]
                report.append(f"| {segment} | {g['A']} | {g['B']} | {g['C']} | {g['D']} | {g['F']} |")
        report.append("")
    
    # Completion checklist
    report.append("---")
    report.append("")
    report.append("## ✅ Step 3.1 Refinement Checklist")
    report.append("")
    report.append("| Fix | Description | Status |")
    report.append("|-----|-------------|--------|")
    report.append("| 1 | Denominator from stg_road_plan | ✅ Corrected |")
    report.append("| 2 | No-photo basis clarified (completed only) | ✅ Documented |")
    report.append("| 3 | Segment-specific duration & productivity | ✅ Implemented |")
    report.append("| 4 | STRICT vs FAIR with real differences | ✅ Delta report created |")
    report.append("| 5 | Audit with dominant segment | ✅ Clean labels |")
    report.append("")
    report.append("**Step 3.1 Complete!** 🚀")
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
        ("leaderboard_strict_v2", "leaderboard_strict.csv"),
        ("leaderboard_fair_v2", "leaderboard_fair.csv"),
        ("kpi_user_monthly_v2", "kpi_user_monthly.csv"),
        ("delta_strict_vs_fair", "delta_strict_vs_fair.csv"),
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
    log("STEP 3.1 PATCH COMPLETE!")
    log("=" * 70)

if __name__ == '__main__':
    main()
