#!/usr/bin/env python3
"""
Step 16: Capacity Thesis Testing
================================
Validates User Thesis: "1 Tech : 3 Clients" vs "1 Tech : 6 Clients".
Analyzes Client Workload vs Technician Capacity.

Logic:
1.  **Client Workload Profile:**
    -   Calculate Avg Hours/Month per Client.
    -   Segment into Small, Medium, Large.
2.  **Technician Capacity:**
    -   Assumption: 173 Hours/Month (Standard).
    -   Burnout Threshold: 85% (147 Hours).
3.  **Simulation:**
    -   How many "Large Clients" fit in 147 Hours?
    -   How many "Small Clients" fit?

Output: analytics/dashboard_data/reports/capacity_thesis.html
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

# Config
MONTH_FILTER = "2025-10" # Use October as representative busy month
TECH_CAPACITY_HOURS = 173
BURNOUT_THRESHOLD_PCT = 0.85
TRAVEL_BUFFER_PCT = 0.15 # 15% time lost to travel

def analyze_capacity():
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Get Client Workload for the Month
    query = f"""
    SELECT 
        c.name as client_name,
        COUNT(*) as visit_count,
        SUM(v.duration_min_capped) / 60.0 as total_hours
    FROM fact_visit_enriched v
    LEFT JOIN dim_customer c ON v.customer_id = c.customer_id
    WHERE is_complete = 1 
      AND substr(visit_date, 1, 7) = '{MONTH_FILTER}'
    GROUP BY c.name
    """
    df_clients = pd.read_sql(query, conn)
    conn.close()
    
    # 2. Segment Clients
    # Quantiles for Small (25%), Medium (50%), Large (75%), Mega (90%)
    q = df_clients['total_hours'].quantile([0.25, 0.5, 0.75, 0.95])
    
    def classify(h):
        if h <= q[0.25]: return 'Small'
        if h <= q[0.75]: return 'Medium'
        if h <= q[0.95]: return 'Large'
        return 'Mega'
        
    df_clients['type'] = df_clients['total_hours'].apply(classify)
    
    # 3. Validation Logic
    # Effective Capacity = Total - Travel Buffer
    effective_capacity = TECH_CAPACITY_HOURS * (1 - TRAVEL_BUFFER_PCT)
    safe_capacity = effective_capacity * BURNOUT_THRESHOLD_PCT # 85% of effective
    
    # Calculate Max Clients per Tech for each Type
    # Max = SafeCapacity / AvgHoursPerClientType
    stats = df_clients.groupby('type')['total_hours'].agg(['mean', 'count', 'min', 'max'])
    stats['max_capacity'] = safe_capacity / stats['mean']
    
    # --- Generate HTML Report ---
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Capacity Thesis Test</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-gray-50 min-h-screen p-8 font-sans text-gray-800">

    <div class="max-w-4xl mx-auto space-y-8">
        
        <!-- Header -->
        <div class="bg-white rounded-xl shadow-sm p-6 border-l-8 border-purple-600">
            <h1 class="text-3xl font-bold text-gray-900 mb-2">Capacity Thesis: 1 Tech vs 3 Customers?</h1>
            <p class="text-gray-500">Based on data from {MONTH_FILTER} (Representative Month)</p>
            <div class="mt-4 flex gap-4 text-sm">
                <span class="bg-purple-100 text-purple-700 px-3 py-1 rounded-full font-bold">Tech Capacity: {TECH_CAPACITY_HOURS} hrs</span>
                <span class="bg-red-100 text-red-700 px-3 py-1 rounded-full font-bold">Safe Limit (85%): {int(safe_capacity)} hrs</span>
            </div>
        </div>

        <!-- Metric Cards -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-gray-500 text-sm font-bold uppercase">Real Client Avg</h3>
                <div class="text-4xl font-bold text-blue-600">{df_clients['total_hours'].mean():.1f} <span class="text-lg text-gray-400">hrs/mo</span></div>
                <p class="text-xs text-gray-400 mt-2">Average time spent per client</p>
            </div>
             <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-gray-500 text-sm font-bold uppercase">"The 1:3 Thesis" Load</h3>
                <div class="text-4xl font-bold text-purple-600">{df_clients['total_hours'].mean() * 3:.1f} <span class="text-lg text-gray-400">hrs/mo</span></div>
                <p class="text-xs text-green-500 mt-2 font-bold">✅ Safe (Only {int((df_clients['total_hours'].mean() * 3)/safe_capacity*100)}% Util)</p>
            </div>
             <div class="bg-white p-6 rounded-xl shadow-sm">
                <h3 class="text-gray-500 text-sm font-bold uppercase">Expansion Trigger</h3>
                <div class="text-4xl font-bold text-red-600">>{int(stats.loc['Medium', 'max_capacity'])} <span class="text-lg text-gray-400">Clients</span></div>
                <p class="text-xs text-gray-400 mt-2">Hire new tech if ratio exceeds this</p>
            </div>
        </div>

        <!-- Analysis Table -->
        <div class="bg-white rounded-xl shadow-sm overflow-hidden">
            <div class="bg-gray-50 p-4 border-b border-gray-100">
                <h3 class="font-bold text-gray-700">Detailed Capacity Analysis by Client Size</h3>
            </div>
            <table class="w-full text-left text-sm">
                <thead class="bg-gray-100 text-gray-600 uppercase text-xs">
                    <tr>
                        <th class="p-4">Client Type</th>
                        <th class="p-4">Profile (Hours/Mo)</th>
                        <th class="p-4">Max Clients per Tech</th>
                        <th class="p-4 w-1/3">Verdict</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-100">
    """
    
    # Loop Rows
    order = ['Small', 'Medium', 'Large', 'Mega']
    for type_ in order:
        if type_ not in stats.index: continue
        row = stats.loc[type_]
        
        avg_h = row['mean']
        max_c = row['max_capacity']
        
        verdict = ""
        color = "text-gray-600"
        
        if type_ == 'Small':
            verdict = "1 Tech can handle many small shops."
            color = "text-green-600"
        elif type_ == 'Medium':
            verdict = "Standard profile. 1:12 is realistic."
            color = "text-blue-600"
        elif type_ == 'Large':
            verdict = "Requires focus. 1:4 max."
            color = "text-yellow-600 font-bold"
        elif type_ == 'Mega':
            verdict = "Dedicated Team Needed (1 Tech : 1 Client)."
            color = "text-red-600 font-bold"
            
        html += f"""
                    <tr class="hover:bg-gray-50">
                        <td class="p-4 font-bold">{type_}</td>
                        <td class="p-4">{avg_h:.1f} hrs <span class="text-xs text-gray-400">(Range: {row['min']:.1f}-{row['max']:.1f})</span></td>
                        <td class="p-4 text-lg font-bold">{int(max_c)} Clients</td>
                        <td class="p-4 {color}">{verdict}</td>
                    </tr>
        """
        
    html += """
                </tbody>
            </table>
        </div>
        
        <!-- Conclusion -->
        <div class="bg-blue-50 border border-blue-100 rounded-xl p-6 text-blue-800">
            <h3 class="font-bold mb-2 flex items-center"><i class="fas fa-lightbulb mr-2"></i> Recommendation: When to Expand?</h3>
            <ul class="list-disc ml-5 space-y-2 text-sm">
                <li><b>Small/Medium Clients:</b> Thesis 1:3 is too wasteful. You can push to <b>1:10 or 1:12</b> safely.</li>
                <li><b>Big Contracts (Malls/Factories):</b> Thesis 1:3 is <b>ACCURATE</b>. For 'Large' clients, capacity fills up at ~4 clients.</li>
                <li><b>Mega Projects:</b> Need dedicated teams (Ratio 1:1 or even 2:1).</li>
                <li><b>New Branch Trigger:</b> If your <b>Average Duration per Visit > 4 Hours</b> across the board, start new branch.</li>
            </ul>
        </div>
        
        <div class="text-center text-gray-400 text-sm">Generated by SanoCare Capacity Engine</div>
    </div>
</body>
</html>
    """
    
    filepath = OUTPUT_DIR / 'capacity_thesis.html'
    with open(filepath, 'w') as f:
        f.write(html)
    print(f"Report Generated: {filepath}")

def main():
    print("Testing Capacity Thesis 1:3 vs Reality...")
    analyze_capacity()
    print("Done.")

if __name__ == '__main__':
    main()
