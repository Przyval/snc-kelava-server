#!/usr/bin/env python3
"""
Step 7: Dashboard JSON Generator
================================
Generates static JSON artifacts for the Enterprise Dashboard.
This decouples the frontend from the database.

Outputs:
- dashboard_stats.json
- leaderboard_full.json
- watchlist.json
- trends.json
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'analytics/snc_analytics.db')
OUTPUT_DIR = os.path.join(BASE_DIR, 'analytics/dashboard_data')

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def safe_pct(num, denom):
    return round(100.0 * num / denom, 1) if denom > 0 else 0.0

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Generating Dashboard JSONs...")
    conn = get_db()
    
    # 1. Executive Stats (dashboard_stats.json)
    # -----------------------------------------
    # Aggregate high-level metrics
    stats_query = """
        SELECT 
            COUNT(*) as total_visits,
            SUM(is_completed) as completed_visits,
            SUM(is_on_time_day) as on_time_visits,
            SUM(CASE WHEN is_completed=1 AND foto_count>0 THEN 1 ELSE 0 END) as with_photo,
            COUNT(DISTINCT user_id) as active_techs
        FROM fact_kpi_visit
    """
    row = conn.execute(stats_query).fetchone()
    
    # Get avg health score from leaderboard
    avg_score = conn.execute("SELECT AVG(score) FROM leaderboard_fair_clean").fetchone()[0] or 0
    
    stats_data = {
        "generated_at": datetime.now().isoformat(),
        "health_score": round(avg_score, 1),
        "total_visits": row['total_visits'],
        "coverage_ratio": safe_pct(row['completed_visits'], row['total_visits']),
        "on_time_rate": safe_pct(row['on_time_visits'], row['completed_visits']),
        "photo_compliance": safe_pct(row['with_photo'], row['completed_visits']),
        "active_technicians": row['active_techs']
    }
    
    with open(os.path.join(OUTPUT_DIR, 'dashboard_stats.json'), 'w') as f:
        json.dump(stats_data, f, indent=2)
    print("  -> dashboard_stats.json")

    # 2. Leaderboard Full (leaderboard_full.json)
    # -------------------------------------------
    # Detailed list for HR and Profile views
    leaderboard_data = []
    lb_rows = conn.execute("SELECT * FROM leaderboard_fair_clean ORDER BY score DESC").fetchall()
    
    for r in lb_rows:
        leaderboard_data.append({
            "rank": r['rank'],
            "id": r['user_id'],
            "name": r['technician_name'],
            "segment": r['segment'],
            # "branch": r['branch'], # Not in table
            "score": r['score'],
            "grade": r['grade'],
            "metrics": {
                "completion": r['completion_pct'],
                "on_time": r['on_time_pct'],
                "duration_compliance": r['duration_pct'], 
                "photo_compliance": r['photo_pct'],
                "productivity_avg": r['visits_per_day']
            }
        })
        
    with open(os.path.join(OUTPUT_DIR, 'leaderboard_full.json'), 'w') as f:
        json.dump(leaderboard_data, f, indent=2)
    print(f"  -> leaderboard_full.json ({len(leaderboard_data)} techs)")

    # 3. Watchlist (watchlist.json)
    # -----------------------------
    # Operational anomalies: No Photo, Suspect Time, Multi-day
    # Similar to actionable_watchlist.csv but structured
    
    watchlist_data = []
    
    # No Photo (Last 30 days, Mobile/Station/Spv)
    no_photo_rows = conn.execute("""
        SELECT technician_name, segment, count(*) as cnt
        FROM fact_kpi_visit
        WHERE is_completed=1 AND foto_count=0 
          AND segment IN ('MOBILE', 'STATION', 'SUPERVISOR')
          AND actual_day >= date('now', '-30 days')
        GROUP BY technician_name, segment
        ORDER BY cnt DESC LIMIT 20
    """).fetchall()
    
    for r in no_photo_rows:
        watchlist_data.append({
            "technician": r['technician_name'],
            "segment": r['segment'],
            "issue": "NO_PHOTO",
            "count": r['cnt'],
            "priority": "HIGH"
        })

    # Suspect Time
    suspect_rows = conn.execute("""
        SELECT technician_name, segment, count(*) as cnt
        FROM fact_kpi_visit
        WHERE is_suspect_time=1
          AND actual_day >= date('now', '-30 days')
        GROUP BY technician_name, segment
        ORDER BY cnt DESC LIMIT 20
    """).fetchall()

    for r in suspect_rows:
        watchlist_data.append({
            "technician": r['technician_name'],
            "segment": r['segment'],
            "issue": "SUSPECT_TIME",
            "count": r['cnt'],
            "priority": "MEDIUM"
        })
        
    with open(os.path.join(OUTPUT_DIR, 'watchlist.json'), 'w') as f:
        json.dump(watchlist_data, f, indent=2)
    print(f"  -> watchlist.json ({len(watchlist_data)} items)")

    # 4. Trends (trends.json)
    # -----------------------
    # Daily aggregation for charts
    trends_data = []
    trend_rows = conn.execute("""
        SELECT 
            actual_day,
            COUNT(*) as planned,
            SUM(is_completed) as completed,
            SUM(is_on_time_day) as on_time
        FROM fact_kpi_visit
        WHERE actual_day IS NOT NULL
        GROUP BY actual_day
        ORDER BY actual_day
    """).fetchall()
    
    for r in trend_rows:
        trends_data.append({
            "date": r['actual_day'],
            "planned": r['planned'],
            "completed": r['completed'],
            "on_time": r['on_time']
        })
        
    with open(os.path.join(OUTPUT_DIR, 'trends.json'), 'w') as f:
        json.dump(trends_data, f, indent=2)
    print(f"  -> trends.json ({len(trends_data)} days)")
    
    conn.close()
    print("Dashboard Data Generation Complete.")

if __name__ == '__main__':
    main()
