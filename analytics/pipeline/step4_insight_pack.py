#!/usr/bin/env python3
"""
Step 4: Insight Pack - Root Cause + Actionable Watchlist
=========================================================
Generates:
4.1 - Multi-day / Forgot checkout analysis
4.2 - No-photo compliance watchlist
4.3 - Suspect time (21-23h) analysis
4.4 - Station duration justification
4.5 - Executive Insight Pack summary

Outputs:
- multiday_rootcause_*.csv
- no_photo_watchlist_30d.csv
- suspect_time_*.csv
- station_duration_summary.md
- insight_pack_2026-01.md
"""

import sqlite3
import csv
import os
from datetime import datetime, timedelta
from collections import defaultdict

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'analytics/snc_analytics.db')
KPI_DIR = os.path.join(BASE_DIR, 'analytics/kpi')
REPORTS_DIR = os.path.join(BASE_DIR, 'analytics/reports')
INSIGHT_DIR = os.path.join(BASE_DIR, 'analytics/insights')

os.makedirs(INSIGHT_DIR, exist_ok=True)

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def pct(a, b):
    return round(100 * a / b, 1) if b > 0 else 0

def main():
    log("=" * 70)
    log("STEP 4: Insight Pack - Root Cause Analysis")
    log("=" * 70)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Get current date for recency filters
    latest_date = conn.execute("SELECT MAX(actual_day) FROM fact_kpi_visit").fetchone()[0]
    log(f"Latest data date: {latest_date}")
    
    # Calculate date thresholds
    # For 30-day: last month
    # For 90-day: last 3 months
    date_30d = "2025-12-14"  # approximate 30 days before 2026-01-13
    date_90d = "2025-10-15"  # approximate 90 days before 2026-01-13
    
    # ========================================================================
    # STEP 4.1: Multi-day / Forgot Checkout Root Cause
    # ========================================================================
    log("\n--- Step 4.1: Multi-day Root Cause Analysis ---")
    
    # Top technicians with multi-day (all-time)
    multiday_by_tech = conn.execute("""
        SELECT 
            f.user_id,
            f.technician_name,
            f.segment,
            COUNT(*) as multiday_count,
            MIN(f.check_in_first) as first_occurrence,
            MAX(f.check_in_first) as last_occurrence,
            ROUND(AVG(f.duration_min_raw / 1440.0), 1) as avg_days
        FROM fact_kpi_visit f
        WHERE f.is_multiday_suspect = 1
        GROUP BY f.user_id, f.technician_name, f.segment
        ORDER BY multiday_count DESC
    """).fetchall()
    
    with open(os.path.join(INSIGHT_DIR, 'multiday_rootcause_by_tech.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['user_id', 'technician_name', 'segment', 'multiday_count', 
                        'first_occurrence', 'last_occurrence', 'avg_days'])
        for row in multiday_by_tech:
            writer.writerow([row['user_id'], row['technician_name'], row['segment'],
                           row['multiday_count'], row['first_occurrence'], 
                           row['last_occurrence'], row['avg_days']])
    log(f"  -> Exported multiday_rootcause_by_tech.csv ({len(multiday_by_tech)} technicians)")
    
    # Top customers with multi-day
    multiday_by_customer = conn.execute("""
        SELECT 
            f.customer_name,
            f.customer_city,
            f.segment,
            COUNT(*) as multiday_count,
            COUNT(DISTINCT f.user_id) as affected_technicians,
            MAX(f.check_in_first) as last_occurrence
        FROM fact_kpi_visit f
        WHERE f.is_multiday_suspect = 1
        GROUP BY f.customer_name, f.customer_city, f.segment
        ORDER BY multiday_count DESC
        LIMIT 50
    """).fetchall()
    
    with open(os.path.join(INSIGHT_DIR, 'multiday_rootcause_by_customer.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['customer_name', 'customer_city', 'segment', 'multiday_count',
                        'affected_technicians', 'last_occurrence'])
        for row in multiday_by_customer:
            writer.writerow([row['customer_name'], row['customer_city'], row['segment'],
                           row['multiday_count'], row['affected_technicians'], row['last_occurrence']])
    log(f"  -> Exported multiday_rootcause_by_customer.csv")
    
    # Multi-day by segment summary
    multiday_by_segment = conn.execute("""
        SELECT 
            segment,
            COUNT(*) as multiday_count,
            COUNT(DISTINCT user_id) as affected_technicians,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct_of_total
        FROM fact_kpi_visit
        WHERE is_multiday_suspect = 1
        GROUP BY segment
        ORDER BY multiday_count DESC
    """).fetchall()
    
    # ========================================================================
    # STEP 4.2: No-Photo Compliance
    # ========================================================================
    log("\n--- Step 4.2: No-Photo Compliance Analysis ---")
    
    # No-photo rate by segment
    no_photo_by_segment = conn.execute("""
        SELECT 
            segment,
            SUM(is_completed) as total_completed,
            SUM(CASE WHEN is_completed = 1 AND foto_count = 0 THEN 1 ELSE 0 END) as no_photo_count,
            ROUND(100.0 * SUM(CASE WHEN is_completed = 1 AND foto_count = 0 THEN 1 ELSE 0 END) / 
                  NULLIF(SUM(is_completed), 0), 1) as no_photo_rate
        FROM fact_kpi_visit
        GROUP BY segment
        ORDER BY no_photo_rate DESC
    """).fetchall()
    
    with open(os.path.join(INSIGHT_DIR, 'no_photo_by_segment.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['segment', 'total_completed', 'no_photo_count', 'no_photo_rate_pct'])
        for row in no_photo_by_segment:
            writer.writerow([row['segment'], row['total_completed'], 
                           row['no_photo_count'], row['no_photo_rate']])
    log(f"  -> Exported no_photo_by_segment.csv")
    
    # 30-day watchlist - technicians with most no-photo visits
    no_photo_watchlist = conn.execute(f"""
        SELECT 
            f.user_id,
            f.technician_name,
            f.segment,
            COUNT(*) as no_photo_count,
            MAX(f.actual_day) as last_occurrence,
            GROUP_CONCAT(DISTINCT f.customer_name) as customers_affected
        FROM fact_kpi_visit f
        WHERE f.is_completed = 1 
          AND f.foto_count = 0
          AND f.actual_day >= '{date_30d}'
        GROUP BY f.user_id, f.technician_name, f.segment
        ORDER BY no_photo_count DESC
        LIMIT 30
    """).fetchall()
    
    with open(os.path.join(INSIGHT_DIR, 'no_photo_watchlist_30d.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['user_id', 'technician_name', 'segment', 'no_photo_count_30d',
                        'last_occurrence', 'top_customers'])
        for row in no_photo_watchlist:
            # Truncate customers list to top 3
            customers = row['customers_affected'] or ''
            top_customers = ', '.join(customers.split(',')[:3])
            writer.writerow([row['user_id'], row['technician_name'], row['segment'],
                           row['no_photo_count'], row['last_occurrence'], top_customers])
    log(f"  -> Exported no_photo_watchlist_30d.csv ({len(no_photo_watchlist)} technicians)")
    
    # Top customers with no-photo
    no_photo_by_customer = conn.execute("""
        SELECT 
            customer_name,
            customer_city,
            segment,
            COUNT(*) as no_photo_count,
            COUNT(DISTINCT user_id) as affected_technicians
        FROM fact_kpi_visit
        WHERE is_completed = 1 AND foto_count = 0
        GROUP BY customer_name, customer_city, segment
        ORDER BY no_photo_count DESC
        LIMIT 30
    """).fetchall()
    
    with open(os.path.join(INSIGHT_DIR, 'no_photo_by_customer.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['customer_name', 'customer_city', 'segment', 'no_photo_count', 'affected_technicians'])
        for row in no_photo_by_customer:
            writer.writerow([row['customer_name'], row['customer_city'], row['segment'],
                           row['no_photo_count'], row['affected_technicians']])
    log(f"  -> Exported no_photo_by_customer.csv")
    
    # ========================================================================
    # STEP 4.3: Suspect Time Analysis (21-23h)
    # ========================================================================
    log("\n--- Step 4.3: Suspect Time Analysis ---")
    
    # Heatmap by technician
    suspect_by_tech = conn.execute("""
        SELECT 
            f.user_id,
            f.technician_name,
            f.segment,
            SUM(f.is_suspect_time) as suspect_count,
            SUM(f.is_completed) as total_completed,
            ROUND(100.0 * SUM(f.is_suspect_time) / NULLIF(SUM(f.is_completed), 0), 1) as suspect_rate,
            GROUP_CONCAT(DISTINCT f.check_in_hour) as hours_used
        FROM fact_kpi_visit f
        WHERE f.is_completed = 1
        GROUP BY f.user_id, f.technician_name, f.segment
        HAVING suspect_count > 0
        ORDER BY suspect_rate DESC
    """).fetchall()
    
    with open(os.path.join(INSIGHT_DIR, 'suspect_time_heatmap_by_tech.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['user_id', 'technician_name', 'segment', 'suspect_count', 
                        'total_completed', 'suspect_rate_pct', 'hours_used'])
        for row in suspect_by_tech:
            writer.writerow([row['user_id'], row['technician_name'], row['segment'],
                           row['suspect_count'], row['total_completed'], 
                           row['suspect_rate'], row['hours_used']])
    log(f"  -> Exported suspect_time_heatmap_by_tech.csv ({len(suspect_by_tech)} technicians)")
    
    # Top customers with suspect time
    suspect_by_customer = conn.execute("""
        SELECT 
            customer_name,
            customer_city,
            segment,
            COUNT(*) as suspect_count,
            COUNT(DISTINCT user_id) as affected_technicians
        FROM fact_kpi_visit
        WHERE is_suspect_time = 1
        GROUP BY customer_name, customer_city, segment
        ORDER BY suspect_count DESC
        LIMIT 30
    """).fetchall()
    
    with open(os.path.join(INSIGHT_DIR, 'suspect_time_top_customers.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['customer_name', 'customer_city', 'segment', 'suspect_count', 'affected_technicians'])
        for row in suspect_by_customer:
            writer.writerow([row['customer_name'], row['customer_city'], row['segment'],
                           row['suspect_count'], row['affected_technicians']])
    log(f"  -> Exported suspect_time_top_customers.csv")
    
    # Co-occurrence analysis
    cooccurrence = conn.execute("""
        SELECT 
            'suspect_time_only' as pattern,
            COUNT(*) as count
        FROM fact_kpi_visit
        WHERE is_suspect_time = 1 AND foto_count > 0 AND is_duration_valid_segment = 1
        UNION ALL
        SELECT 
            'suspect_AND_no_photo',
            COUNT(*)
        FROM fact_kpi_visit
        WHERE is_suspect_time = 1 AND foto_count = 0
        UNION ALL
        SELECT 
            'suspect_AND_invalid_duration',
            COUNT(*)
        FROM fact_kpi_visit
        WHERE is_suspect_time = 1 AND is_duration_valid_segment = 0 AND has_checkout = 1
        UNION ALL
        SELECT 
            'suspect_AND_no_photo_AND_invalid_duration',
            COUNT(*)
        FROM fact_kpi_visit
        WHERE is_suspect_time = 1 AND foto_count = 0 AND is_duration_valid_segment = 0
    """).fetchall()
    
    with open(os.path.join(INSIGHT_DIR, 'suspect_time_cooccurrence.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['pattern', 'count'])
        for row in cooccurrence:
            writer.writerow([row['pattern'], row['count']])
    log(f"  -> Exported suspect_time_cooccurrence.csv")
    
    # ========================================================================
    # STEP 4.4: Station Duration Justification
    # ========================================================================
    log("\n--- Step 4.4: Station Duration Analysis ---")
    
    # Duration distribution by segment
    duration_stats = conn.execute("""
        SELECT 
            segment,
            COUNT(*) as total_with_duration,
            ROUND(MIN(duration_min_raw), 0) as min_duration,
            ROUND(AVG(duration_min_raw), 0) as avg_duration,
            ROUND(MAX(duration_min_raw), 0) as max_duration
        FROM fact_kpi_visit
        WHERE duration_min_raw IS NOT NULL 
          AND duration_min_raw > 0 
          AND duration_min_raw <= 1440
        GROUP BY segment
        ORDER BY avg_duration DESC
    """).fetchall()
    
    # Calculate approximate percentiles using NTILE
    percentiles_by_segment = {}
    for seg in ['MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR']:
        pct_data = conn.execute(f"""
            WITH ranked AS (
                SELECT 
                    duration_min_raw,
                    NTILE(100) OVER (ORDER BY duration_min_raw) as percentile
                FROM fact_kpi_visit
                WHERE segment = ?
                  AND duration_min_raw IS NOT NULL 
                  AND duration_min_raw > 0 
                  AND duration_min_raw <= 1440
            )
            SELECT 
                percentile,
                MAX(duration_min_raw) as max_duration_in_bucket
            FROM ranked
            WHERE percentile IN (25, 50, 75, 90, 95)
            GROUP BY percentile
        """, (seg,)).fetchall()
        percentiles_by_segment[seg] = {row['percentile']: row['max_duration_in_bucket'] for row in pct_data}
    
    # Top STATION customers (example of "legitimately long" visits)
    station_long_customers = conn.execute("""
        SELECT 
            customer_name,
            customer_city,
            COUNT(*) as visit_count,
            ROUND(AVG(duration_min_raw), 0) as avg_duration,
            ROUND(MAX(duration_min_raw), 0) as max_duration
        FROM fact_kpi_visit
        WHERE segment = 'STATION'
          AND duration_min_raw IS NOT NULL 
          AND duration_min_raw > 0 
          AND duration_min_raw <= 1440
        GROUP BY customer_name, customer_city
        ORDER BY avg_duration DESC
        LIMIT 10
    """).fetchall()
    
    # ========================================================================
    # STEP 4.5: Generate Insight Pack Document
    # ========================================================================
    log("\n--- Step 4.5: Generating Insight Pack ---")
    
    # Get latest leaderboard data
    latest_month = conn.execute("SELECT MAX(month) FROM leaderboard_fair_clean").fetchone()[0]
    
    # Build the insight pack
    pack = []
    pack.append("# 📊 Insight Pack - January 2026")
    pack.append("")
    pack.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB")
    pack.append(f"> **Data Period:** Up to {latest_date}")
    pack.append(f"> **Leaderboard Month:** {latest_month}")
    pack.append("")
    pack.append("---")
    pack.append("")
    
    # Page 1: Executive Summary
    pack.append("## 1. Executive Summary")
    pack.append("")
    
    # Get key stats
    summary_stats = conn.execute("""
        SELECT 
            COUNT(*) as total_visits,
            SUM(is_completed) as completed,
            SUM(is_multiday_suspect) as multiday,
            SUM(CASE WHEN is_completed = 1 AND foto_count = 0 THEN 1 ELSE 0 END) as no_photo,
            SUM(is_suspect_time) as suspect_time,
            SUM(is_on_time_day) as on_time_fair
        FROM fact_kpi_visit
    """).fetchone()
    
    pack.append("### Key Metrics")
    pack.append("")
    pack.append("| Metric | Count | Rate |")
    pack.append("|--------|-------|------|")
    pack.append(f"| Total Completed | {summary_stats['completed']:,} | - |")
    pack.append(f"| On-Time (FAIR) | {summary_stats['on_time_fair']:,} | {pct(summary_stats['on_time_fair'], summary_stats['completed'])}% |")
    pack.append(f"| No Photo | {summary_stats['no_photo']:,} | {pct(summary_stats['no_photo'], summary_stats['completed'])}% ⚠️ |")
    pack.append(f"| Multi-day Duration | {summary_stats['multiday']:,} | {pct(summary_stats['multiday'], summary_stats['completed'])}% ⚠️ |")
    pack.append(f"| Suspect Time (21-23h) | {summary_stats['suspect_time']:,} | {pct(summary_stats['suspect_time'], summary_stats['completed'])}% ⚠️ |")
    pack.append("")
    
    # Top 3 Issues
    pack.append("### Top 3 Operational Issues This Period")
    pack.append("")
    pack.append(f"1. **No-Photo Compliance:** {summary_stats['no_photo']:,} visits without photos ({pct(summary_stats['no_photo'], summary_stats['completed'])}%)")
    pack.append(f"2. **Suspect Time Entries:** {summary_stats['suspect_time']:,} check-ins between 21:00-23:59 ({pct(summary_stats['suspect_time'], summary_stats['completed'])}%)")
    pack.append(f"3. **Multi-day Durations:** {summary_stats['multiday']:,} visits with checkout weeks/months after check-in")
    pack.append("")
    
    # Top performers
    pack.append("### Top Performers - MOBILE Segment")
    pack.append("")
    top_mobile = conn.execute("""
        SELECT technician_name, score, grade, completion_pct, on_time_pct, photo_pct
        FROM leaderboard_fair_clean
        WHERE segment = 'MOBILE'
        ORDER BY rank
        LIMIT 5
    """).fetchall()
    
    pack.append("| Rank | Technician | Score | Grade |")
    pack.append("|------|------------|-------|-------|")
    for i, row in enumerate(top_mobile, 1):
        pack.append(f"| {i} | {row['technician_name'][:25]} | {row['score']} | {row['grade']} |")
    pack.append("")
    
    # Page 2: Root Cause Analysis
    pack.append("---")
    pack.append("")
    pack.append("## 2. Root Cause Analysis")
    pack.append("")
    
    # Multi-day analysis
    pack.append("### Multi-day Duration ('Forgot to Checkout')")
    pack.append("")
    pack.append("**Pattern:** Multi-day durations are NOT random - they cluster by specific technicians and customers.")
    pack.append("")
    
    pack.append("**Top 5 Technicians with Multi-day Issues:**")
    pack.append("")
    pack.append("| Technician | Segment | Count | Avg Days |")
    pack.append("|------------|---------|-------|----------|")
    for row in multiday_by_tech[:5]:
        pack.append(f"| {row['technician_name'][:25]} | {row['segment']} | {row['multiday_count']} | {row['avg_days']} |")
    pack.append("")
    
    pack.append("**Top 5 Customers with Multi-day Issues:**")
    pack.append("")
    pack.append("| Customer | Segment | Count | Techs Affected |")
    pack.append("|----------|---------|-------|----------------|")
    for row in multiday_by_customer[:5]:
        pack.append(f"| {(row['customer_name'] or 'N/A')[:25]} | {row['segment']} | {row['multiday_count']} | {row['affected_technicians']} |")
    pack.append("")
    
    pack.append("**By Segment:**")
    pack.append("")
    pack.append("| Segment | Multi-day Count | % of Total |")
    pack.append("|---------|-----------------|------------|")
    for row in multiday_by_segment:
        pack.append(f"| {row['segment']} | {row['multiday_count']} | {row['pct_of_total']}% |")
    pack.append("")
    
    # No-photo analysis
    pack.append("### No-Photo Compliance")
    pack.append("")
    pack.append("**By Segment (key insight: SUPPORT/CHECKLIST has 100% no-photo - may be by design):**")
    pack.append("")
    pack.append("| Segment | Completed | No Photo | Rate |")
    pack.append("|---------|-----------|----------|------|")
    for row in no_photo_by_segment:
        flag = " ⚠️" if (row['no_photo_rate'] or 0) > 50 else ""
        pack.append(f"| {row['segment']} | {row['total_completed']:,} | {row['no_photo_count']:,} | {row['no_photo_rate']}%{flag} |")
    pack.append("")
    
    pack.append("> **Recommendation:** If SUPPORT/CHECKLIST visits don't require photos by SOP, exclude them from photo compliance KPI.")
    pack.append("")
    
    # Suspect time
    pack.append("### Suspect Time (21:00-23:59)")
    pack.append("")
    pack.append("**Co-occurrence Analysis (are 21-23h entries just 'quick clicks'?):**")
    pack.append("")
    pack.append("| Pattern | Count |")
    pack.append("|---------|-------|")
    for row in cooccurrence:
        pack.append(f"| {row['pattern']} | {row['count']:,} |")
    pack.append("")
    
    # Station duration
    pack.append("### Station Duration Justification")
    pack.append("")
    pack.append("**Duration Percentiles by Segment (minutes):**")
    pack.append("")
    pack.append("| Segment | P25 | P50 (Median) | P75 | P90 |")
    pack.append("|---------|-----|--------------|-----|-----|")
    for seg in ['MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR']:
        p = percentiles_by_segment.get(seg, {})
        pack.append(f"| {seg} | {p.get(25, 'N/A')} | {p.get(50, 'N/A')} | {p.get(75, 'N/A')} | {p.get(90, 'N/A')} |")
    pack.append("")
    
    pack.append("> **Key Finding:** STATION median duration is significantly higher than MOBILE. Using the same 5-480 min threshold would unfairly penalize STATION technicians. Segment-specific thresholds (STATION: 30-900 min) are appropriate.")
    pack.append("")
    
    # Page 3: Action Plan
    pack.append("---")
    pack.append("")
    pack.append("## 3. Action Plan & Watchlist")
    pack.append("")
    
    pack.append("### Immediate App/System Changes (High Impact)")
    pack.append("")
    pack.append("| Priority | Change | Expected Impact |")
    pack.append("|----------|--------|-----------------|")
    pack.append("| 🔴 P1 | **Auto-checkout at 18:00** if visit still open | Eliminates multi-day duration issue |")
    pack.append("| 🔴 P1 | **Block checkout if foto_count = 0** (for MOBILE/STATION) | Enforces photo compliance |")
    pack.append("| 🟡 P2 | **'Open visit' indicator** - can't start new visit if one is open | Prevents forgot-checkout |")
    pack.append("| 🟡 P2 | **Server-recorded timestamps** - prevent backdating check-in | Accurate on-time measurement |")
    pack.append("| 🟢 P3 | **Reminder notification** 2 hours after check-in if no checkout | Nudge before auto-action |")
    pack.append("")
    
    pack.append("### 30-Day Watchlist (Technicians Needing Attention)")
    pack.append("")
    pack.append("| Technician | Issue | Count (30d) | Priority |")
    pack.append("|------------|-------|-------------|----------|")
    
    watchlist_items = []
    for row in no_photo_watchlist[:5]:
        watchlist_items.append((row['technician_name'], 'No Photo', row['no_photo_count'], '🔴'))
    
    # Add multiday watchlist
    multiday_30d = conn.execute(f"""
        SELECT technician_name, COUNT(*) as cnt
        FROM fact_kpi_visit
        WHERE is_multiday_suspect = 1 AND check_in_first >= '{date_30d}'
        GROUP BY technician_name
        ORDER BY cnt DESC
        LIMIT 5
    """).fetchall()
    for row in multiday_30d:
        watchlist_items.append((row['technician_name'], 'Multi-day', row['cnt'], '🟡'))
    
    for name, issue, count, priority in sorted(watchlist_items, key=lambda x: -x[2])[:10]:
        pack.append(f"| {name[:25]} | {issue} | {count} | {priority} |")
    pack.append("")
    
    pack.append("### SOP Clarifications Needed")
    pack.append("")
    pack.append("1. **SUPPORT/CHECKLIST photo requirement:** Confirm if these visit types require photos. If not, exclude from photo compliance KPI.")
    pack.append("2. **Night visits legitimacy:** Some customers (e.g., Bukit Darmo Golf) show high suspect time. Verify if night visits are part of their service contract.")
    pack.append("3. **STATION visit definition:** Confirm if STATION visits can legitimately span 8-15 hours (current data shows this is common).")
    pack.append("")
    
    pack.append("---")
    pack.append("")
    pack.append("## ✅ Deliverables Generated")
    pack.append("")
    pack.append("| File | Description |")
    pack.append("|------|-------------|")
    pack.append("| `multiday_rootcause_by_tech.csv` | Technicians with multi-day issues |")
    pack.append("| `multiday_rootcause_by_customer.csv` | Customers with multi-day issues |")
    pack.append("| `no_photo_watchlist_30d.csv` | 30-day no-photo watchlist |")
    pack.append("| `no_photo_by_segment.csv` | No-photo rates by segment |")
    pack.append("| `suspect_time_heatmap_by_tech.csv` | Suspect time analysis |")
    pack.append("| `suspect_time_cooccurrence.csv` | Pattern co-occurrence |")
    pack.append("")
    pack.append("**Step 4 Complete!** 🚀")
    pack.append("")
    
    # Write insight pack
    with open(os.path.join(REPORTS_DIR, 'insight_pack_2026-01.md'), 'w') as f:
        f.write('\n'.join(pack))
    log(f"  -> Written insight_pack_2026-01.md")
    
    # Also save to insights directory
    with open(os.path.join(INSIGHT_DIR, 'insight_pack_2026-01.md'), 'w') as f:
        f.write('\n'.join(pack))
    
    # ========================================================================
    # Create actionable watchlist CSV
    # ========================================================================
    with open(os.path.join(INSIGHT_DIR, 'actionable_watchlist.csv'), 'w', newline='') as csvf:
        writer = csv.writer(csvf)
        writer.writerow(['technician_name', 'issue_type', 'count_30d', 'priority', 'action_needed'])
        for row in no_photo_watchlist[:10]:
            writer.writerow([row['technician_name'], 'NO_PHOTO', row['no_photo_count'], 
                           'HIGH', 'Coaching on photo requirement'])
        for row in multiday_30d[:10]:
            writer.writerow([row['technician_name'], 'MULTIDAY_DURATION', row['cnt'],
                           'MEDIUM', 'Reminder about checkout'])
    log(f"  -> Written actionable_watchlist.csv")
    
    conn.close()
    
    log("\n" + "=" * 70)
    log("STEP 4 COMPLETE!")
    log("=" * 70)

if __name__ == '__main__':
    main()
