#!/usr/bin/env python3
"""
Step 13: Technician Personal Report Cards
=========================================
Generates individual HTML dashboards for each technician.
Focus: Personal feedback loop, Job composition (Rodent vs Insect), Monthly Trends.

Inputs:
- snc_analytics.db
- analytics/dashboard_data/eda/technician_personas.csv (for Badges)

Outputs:
- analytics/dashboard_data/personal_reports/report_{tech_cleanup}.html
"""

import sqlite3
import pandas as pd
import os
import re
from pathlib import Path
from datetime import datetime

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
PERSONA_CSV = BASE_DIR / 'analytics/dashboard_data/eda/technician_personas.csv'
OUTPUT_DIR = BASE_DIR / 'analytics/dashboard_data/personal_reports'

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_tech_data():
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Main Visits Data (Using fact_visit_enriched for treatment_list)
    query = """
    SELECT 
        technician_name,
        visit_date,
        strftime('%Y-%m', visit_date) as month_year,
        treatment_list,
        -- Need to re-calculate STRICT v2 on time from raw data since we switched table
        CASE 
            WHEN is_complete = 1 
             AND visit_date = strftime('%Y-%m-%d', check_in_first)
             AND (strftime('%H', check_in_first) < '2100')
            THEN 1 ELSE 0 END as is_on_time_strict_v2,
        is_complete as is_completed
    FROM fact_visit_enriched
    WHERE is_complete = 1
    """
    df = pd.read_sql(query, conn)
    
    # 2. Get Scores/Grades (Latest Month)
    query_scores = """
    SELECT 
        technician_name,
        score as final_score,
        grade
    FROM leaderboard_fair_clean
    """
    df_scores = pd.read_sql(query_scores, conn)
    
    conn.close()
    return df, df_scores

def get_personas():
    if PERSONA_CSV.exists():
        return pd.read_csv(PERSONA_CSV)
    return pd.DataFrame() # Empty if not found

def categorize_job(treatment_str):
    if not isinstance(treatment_str, str):
        return "General"
    
    t = treatment_str.upper()
    
    # Priority logic (if mixed, pick dominant)
    if any(x in t for x in ['RAT', 'TRAP', 'GLUE', 'MOUSE', 'RODENT', 'BOX']):
        return "Rodent Control"
    if any(x in t for x in ['FLY', 'INSECT', 'GEL', 'SPRAY', 'FOG', 'MOSQUITO', 'TERMITE']):
        return "Insect Control"
    if any(x in t for x in ['MIST', 'DISINFECT', 'VIRUS', 'BACTERIA']):
        return "Disinfection"
        
    return "General / Inspection"

def generate_html_for_tech(tech_name, df_tech, score_info, persona_info):
    # Clean filename
    filename = re.sub(r'[^a-zA-Z0-9]', '_', tech_name).lower() + ".html"
    filepath = OUTPUT_DIR / filename
    
    # --- Statistics ---
    total_visits = len(df_tech)
    on_time_pct = (df_tech['is_on_time_strict_v2'].sum() / total_visits * 100) if total_visits > 0 else 0
    
    # Monthly Trend (Last 6 months)
    monthly_counts = df_tech.groupby('month_year').size().sort_index().tail(6)
    labels_trend = list(monthly_counts.index)
    data_trend = list(monthly_counts.values)
    
    # Job Composition
    df_tech['job_type'] = df_tech['treatment_list'].apply(categorize_job)
    job_counts = df_tech['job_type'].value_counts()
    labels_job = list(job_counts.index)
    data_job = list(job_counts.values)
    
    # Persona/Badge
    badge_html = ""
    if not persona_info.empty:
        p_row = persona_info[persona_info['technician_name'] == tech_name]
        if not p_row.empty:
            cluster_id = p_row.iloc[0]['cluster']
            # Map cluster ID to meaningful name (based on Step 9 findings)
            # 0=Workhorse, 1=Station, 2=Anomaly, 3=Underperformer (Approx based on previous run)
            # Ideally we save labels in CSV, but for now we fallback or show generic
            badge_name = f"Cluster {cluster_id}"
            badge_color = "bg-purple-100 text-purple-800"
            
            # Simple heuristic mapping for demo
            if cluster_id == 0: badge_name = "The Workhorse 🐎"; badge_color="bg-blue-100 text-blue-800"
            elif cluster_id == 1: badge_name = "Station Keeper 🛡️"; badge_color="bg-green-100 text-green-800"
            elif cluster_id == 2: badge_name = "Needs Review ⚠️"; badge_color="bg-red-100 text-red-800"
            
            badge_html = f'<span class="px-3 py-1 rounded-full text-sm font-bold {badge_color} border ml-2">{badge_name}</span>'

    # Score/Grade
    current_grade = "N/A"
    current_score = 0
    if not score_info.empty:
        s_row = score_info[score_info['technician_name'] == tech_name]
        if not s_row.empty:
            current_grade = s_row.iloc[0]['grade']
            current_score = s_row.iloc[0]['final_score']
            
    grade_color = "text-gray-500"
    if current_grade == 'A': grade_color = "text-green-600"
    elif current_grade == 'B': grade_color = "text-blue-600"
    elif current_grade == 'C': grade_color = "text-yellow-600"
    elif current_grade == 'D': grade_color = "text-orange-600"
    elif current_grade == 'E': grade_color = "text-red-600"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Report Card: {tech_name}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-gray-50 min-h-screen p-4 md:p-8">

    <div class="max-w-4xl mx-auto">
        <!-- Header Profile -->
        <div class="bg-white rounded-2xl shadow-sm p-6 mb-6 flex flex-col md:flex-row items-center justify-between">
            <div class="flex items-center mb-4 md:mb-0">
                <div class="h-16 w-16 bg-blue-600 rounded-full flex items-center justify-center text-white text-2xl font-bold">
                    {tech_name[0]}
                </div>
                <div class="ml-4">
                    <h1 class="text-2xl font-bold text-gray-900">{tech_name}</h1>
                    <div class="flex items-center mt-1">
                        <span class="text-gray-500 text-sm">Technician Report Card</span>
                        {badge_html}
                    </div>
                </div>
            </div>
            <div class="text-center md:text-right">
                <p class="text-sm text-gray-500 uppercase tracking-widest">Current Grade</p>
                <h2 class="text-5xl font-extrabold {grade_color}">{current_grade}</h2>
                <p class="text-sm font-medium text-gray-400">Score: {current_score:.1f}</p>
            </div>
        </div>

        <!-- KPI Stats Grid -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div class="bg-white p-4 rounded-xl shadow-sm border-l-4 border-blue-500">
                <p class="text-xs text-gray-500 font-bold uppercase">Total Visits</p>
                <p class="text-2xl font-bold text-gray-800">{total_visits}</p>
            </div>
            <div class="bg-white p-4 rounded-xl shadow-sm border-l-4 border-green-500">
                <p class="text-xs text-gray-500 font-bold uppercase">On-Time %</p>
                <p class="text-2xl font-bold text-gray-800">{on_time_pct:.1f}%</p>
            </div>
            <div class="bg-white p-4 rounded-xl shadow-sm border-l-4 border-purple-500">
                <p class="text-xs text-gray-500 font-bold uppercase">Top Skill</p>
                <p class="text-lg font-bold text-gray-800 truncate">{labels_job[0] if labels_job else '-'}</p>
            </div>
                <div class="bg-white p-4 rounded-xl shadow-sm border-l-4 border-yellow-500">
                <p class="text-xs text-gray-500 font-bold uppercase">Avg Month</p>
                <p class="text-2xl font-bold text-gray-800">{int(sum(data_trend)/len(data_trend)) if data_trend else 0}</p>
            </div>
        </div>

        <!-- Charts Area -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            <!-- Job Composition -->
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-bold text-gray-800 mb-4"><i class="fas fa-chart-pie mr-2 text-blue-500"></i>Job Composition</h3>
                <div class="relative h-64">
                    <canvas id="jobChart"></canvas>
                </div>
                <p class="text-xs text-gray-400 mt-4 text-center">Based on equipment used (e.g., Traps vs Sprays)</p>
            </div>

            <!-- Monthly Trend -->
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-lg font-bold text-gray-800 mb-4"><i class="fas fa-chart-line mr-2 text-green-500"></i>Monthly Activity</h3>
                <div class="relative h-64">
                    <canvas id="trendChart"></canvas>
                </div>
                 <p class="text-xs text-gray-400 mt-4 text-center">Is your performance going up or down?</p>
            </div>
        </div>
        
        <div class="mt-8 text-center text-gray-400 text-sm">
            <p>Generated by SanoCare AI • Confidential Personal Report</p>
        </div>
    </div>

    <script>
        // Job Composition Chart
        const ctxJob = document.getElementById('jobChart').getContext('2d');
        new Chart(ctxJob, {{
            type: 'doughnut',
            data: {{
                labels: {labels_job},
                datasets: [{{
                    data: {data_job},
                    backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#6366f1'],
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ position: 'bottom' }}
                }}
            }}
        }});

        // Trend Chart
        const ctxTrend = document.getElementById('trendChart').getContext('2d');
        new Chart(ctxTrend, {{
            type: 'bar',
            data: {{
                labels: {labels_trend},
                datasets: [{{
                    label: 'Visits Completed',
                    data: {data_trend},
                    backgroundColor: '#10b981',
                    borderRadius: 5
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    legend: {{ display: false }}
                }},
                scales: {{
                    y: {{ beginAtZero: true }}
                }}
            }}
        }});
    </script>
</body>
</html>
    """
    
    with open(filepath, 'w') as f:
        f.write(html)

def main():
    print("Generating Personal Reports...")
    
    df, df_scores = get_tech_data()
    df_personas = get_personas()
    
    techs = df['technician_name'].unique()
    print(f"Found {len(techs)} technicians.")
    
    for tech in techs:
        # Filter data for this tech
        df_tech = df[df['technician_name'] == tech].copy()
        if len(df_tech) < 5: continue # Skip if too little data
        
        generate_html_for_tech(tech, df_tech, df_scores, df_personas)
        
    print(f"Reports generated in {OUTPUT_DIR}")

if __name__ == '__main__':
    main()
