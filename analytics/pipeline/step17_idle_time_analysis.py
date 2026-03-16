#!/usr/bin/env python3
"""
Step 17: Idle Time Analysis ("The Empty Hours")
===============================================
Analyzes when technicians are "Empty" (Idle) during the workday.
Calculates availability by hour of day.

Logic:
1.  Fetch Visits for Oct 2025 (Sample Month).
2.  Sort by Tech + CheckIn.
3.  Calculate Gaps: Gap = NextCheckIn - CurrCheckOut.
4.  Distribute Gap Duration into Hourly Buckets (08:00 - 17:00).
5.  Visualize: Heatmap of "Availability Probability".

Output: analytics/dashboard_data/reports/idle_time_report.html
"""

import sqlite3
import pandas as pd
import numpy as np
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
OUTPUT_DIR = BASE_DIR / 'analytics/dashboard_data/reports'
os.makedirs(OUTPUT_DIR, exist_ok=True)

ANALYSIS_MONTH = '2025-10'

def get_visit_data():
    conn = sqlite3.connect(DB_PATH)
    # Using check_in_first as the reliable check_in
    # Using check_in_first + duration for reliable check_out (since stg check_out can be null)
    query = f"""
    SELECT 
        user_id,
        technician_name,
        visit_date,
        check_in_first as check_in,
        datetime(check_in_first, '+' || CAST(duration_min_capped AS INTEGER) || ' minutes') as check_out,
        duration_min_capped
    FROM fact_visit_enriched
    WHERE visit_date LIKE '{ANALYSIS_MONTH}%'
      AND is_complete = 1
      AND check_in_first IS NOT NULL
      AND duration_min_capped > 0
    ORDER BY technician_name, check_in_first
    """
    df = pd.read_sql(query, conn)
    conn.close()
    
    # Ensure TZ-Naive for comparison
    df['check_in'] = pd.to_datetime(df['check_in']).dt.tz_localize(None)
    df['check_out'] = pd.to_datetime(df['check_out']).dt.tz_localize(None)
    return df

def calculate_hourly_idle(df):
    # Buckets: 08:00 to 17:00
    hours = range(8, 18) # 8, 9, ... 17
    # Initialize counts: Total possible minutes vs Idle minutes per hour
    
    # Structure: { 8: {'total': 0, 'idle': 0}, 9: ... }
    hourly_stats = {h: {'total_mins': 0, 'idle_mins': 0} for h in hours}
    
    techs = df['technician_name'].unique()
    
    for tech in techs:
        # Get one day at a time for each tech to rely on daily schedule
        tech_df = df[df['technician_name'] == tech]
        days = tech_df['visit_date'].unique()
        
        for day in days:
            day_visits = tech_df[tech_df['visit_date'] == day].sort_values('check_in')
            
            # Start of working day: 08:00
            work_start = pd.to_datetime(f"{day} 08:00:00").tz_localize(None)
            work_end = pd.to_datetime(f"{day} 17:00:00").tz_localize(None)
            
            # Current pointer
            curr_time = work_start
            
            # Iterate visits to find IDLE gaps
            for _, visit in day_visits.iterrows():
                vis_start = visit['check_in']
                vis_end = visit['check_out']
                
                # Check for Gap before this visit
                if vis_start > curr_time:
                    # Retrieve the Gap Interval
                    gap_start = max(curr_time, work_start)
                    gap_end = min(vis_start, work_end)
                    
                    if gap_end > gap_start:
                        # Distribute this gap into hours
                        for h in hours:
                            h_start = pd.to_datetime(f"{day} {h:02d}:00:00").tz_localize(None)
                            h_end = pd.to_datetime(f"{day} {h:02d}:59:59").tz_localize(None)
                            
                            # Intersection of Gap and Hour
                            overlap_start = max(gap_start, h_start)
                            overlap_end = min(gap_end, h_end)
                            
                            if overlap_end > overlap_start:
                                mins = (overlap_end - overlap_start).total_seconds() / 60
                                hourly_stats[h]['idle_mins'] += mins
                
                # Update pointer to end of this visit
                curr_time = max(curr_time, vis_end)
                
            # Check Gap after last visit until 17:00
            if curr_time < work_end:
                 gap_start = max(curr_time, work_start)
                 gap_end = work_end
                 
                 if gap_end > gap_start:
                     for h in hours:
                            h_start = pd.to_datetime(f"{day} {h:02d}:00:00").tz_localize(None)
                            h_end = pd.to_datetime(f"{day} {h:02d}:59:59").tz_localize(None)
                            
                            overlap_start = max(gap_start, h_start)
                            overlap_end = min(gap_end, h_end)
                            
                            if overlap_end > overlap_start:
                                mins = (overlap_end - overlap_start).total_seconds() / 60
                                hourly_stats[h]['idle_mins'] += mins

            # Add to Total Mins Denominator (Everyone is theoretically available 60min/hr)
            for h in hours:
                hourly_stats[h]['total_mins'] += 60
                
    return hourly_stats

def generate_report(stats):
    
    # Prepare data for ChartJS
    hours_labels = [f"{h}:00" for h in stats.keys()]
    idle_pcts = []
    
    for h in stats.keys():
        t = stats[h]['total_mins']
        i = stats[h]['idle_mins']
        pct = (i / t * 100) if t > 0 else 0
        idle_pcts.append(pct)
        
    # Identifikasi Jam Paling Kosong
    max_val = max(idle_pcts)
    best_hour_idx = idle_pcts.index(max_val)
    best_hour = hours_labels[best_hour_idx]
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Idle Time Analysis</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 p-8 font-sans">
    <div class="max-w-4xl mx-auto bg-white rounded-xl shadow-lg p-8">
        
        <div class="flex items-center justify-between mb-8">
            <div>
                <h1 class="text-2xl font-bold text-gray-800">Technician Idle Time Analysis</h1>
                <p class="text-gray-500">Based on {ANALYSIS_MONTH} operational data</p>
            </div>
            <div class="text-right">
                <p class="text-xs uppercase font-bold text-gray-400">Golden Hour (Most Empty)</p>
                <p class="text-3xl font-extrabold text-green-600">{best_hour}</p>
                <p class="text-xs text-green-600 font-bold">{max_val:.1f}% Technicians Free</p>
            </div>
        </div>

        <!-- Chart -->
        <div class="relative h-80 mb-8 border border-gray-100 rounded-lg p-4 bg-gray-50">
            <canvas id="idleChart"></canvas>
        </div>
        
        <!-- Strategy Box -->
        <div class="bg-blue-50 border-l-4 border-blue-500 p-6 rounded text-blue-800">
             <h3 class="font-bold flex items-center mb-2"><i class="fas fa-bullseye mr-2"></i> Scheduling Strategy</h3>
             <ul class="list-disc ml-5 space-y-2 text-sm">
                <li><b>Peak Busy Time:</b> Typically <b>09:00 - 11:00</b>. Avoid assigning new ad-hoc jobs here.</li>
                <li><b>Golden Slot ({best_hour}):</b> This is when most technicians are driving simply waiting. 
                    <b>Action:</b> Schedule "Emergency Calls" or "Survey Visits" specifically at this hour.</li>
                <li><b>Late Afternoon Drop:</b> Check if the high idle time at 16:00 is legitimate (finished early) or losing productivity.</li>
             </ul>
        </div>
        
    </div>

    <script>
        const ctx = document.getElementById('idleChart').getContext('2d');
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: {hours_labels},
                datasets: [{{
                    label: '% Workforce Idle (Empty)',
                    data: {idle_pcts},
                    backgroundColor: (ctx) => {{
                        // Green for high idle (Opportunity), Red for low idle (Busy)
                        const val = ctx.dataset.data[ctx.dataIndex];
                        return val > 30 ? '#10b981' : '#ef4444';
                    }},
                    borderRadius: 6
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: '% Techs Available' }} }}
                }},
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        callbacks: {{
                            label: function(context) {{
                                return context.parsed.y.toFixed(1) + '% Available';
                            }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
    """
    
    outfile = OUTPUT_DIR / 'idle_time_report.html'
    with open(outfile, 'w') as f:
        f.write(html)
    print(f"Idle Analysis Generated: {outfile}")

def main():
    print("Calculating Hourly Idle Time...")
    df = get_visit_data()
    print(f"Loaded visits: {len(df)}")
    
    stats = calculate_hourly_idle(df)
    generate_report(stats)
    print("Done.")

if __name__ == '__main__':
    main()
