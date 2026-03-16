#!/usr/bin/env python3
"""
Step 13 (Demo): Herryanto - Rodent Specialist Scenario (Enhanced V2)
====================================================================
Generates a DEMO report for 'Herryanto' with:
1. High Rodent Workload
2. Declining Visit Trend
3. Discipline Heatmap
4. Pest Catch Volume
5. [NEW] Complaint & Client Feedback Section
   - Complaint Severity (Minor/Major)
   - "Top Complaining Clients" (Watchlist)

Output: analytics/dashboard_data/personal_reports/herryanto_demo.html
"""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / 'analytics/dashboard_data/personal_reports'
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_demo_report():
    tech_name = "Herryanto"
    filename = "herryanto_demo.html"
    filepath = OUTPUT_DIR / filename
    
    # --- Data ---
    current_grade = "B"
    current_score = 82.5
    total_visits = 142
    on_time_pct = 94.2
    
    # Charts
    labels_job = ["Rodent Control", "Insect Control", "General", "Disinfection"]
    data_job = [120, 15, 5, 2]
    
    labels_trend = ["Aug", "Sep", "Oct", "Nov", "Dec", "Jan"]
    data_trend = [130, 145, 150, 140, 110, 85] 
    data_catch = [450, 480, 510, 490, 380, 210] 

    # 5. [NEW] Complaints Data
    # 2 Major, 1 Minor
    complaint_stats = {"Major": 2, "Minor": 1}
    
    # Client Sentiment List (Who complains?)
    # Status: Happy (Green), Neutral (Gray), Angry (Red)
    client_feedback = [
        {"name": "Gudang Garam Unit 1", "status": "Angry", "issue": "Major: Kabel Server Putus Digigit (Jan 12)", "sentiment": 10},
        {"name": "McDonalds Basuki Rahmat", "status": "Angry", "issue": "Major: Ada Tikus di Dining Area (Jan 05)", "sentiment": 10},
        {"name": "Hotel Majapahit", "status": "Neutral", "issue": "Minor: Trap belum diganti 3 hari", "sentiment": 50},
        {"name": "RS Siloam", "status": "Happy", "issue": "No Issue - Catch Rate High", "sentiment": 90},
        {"name": "BCA Diponegoro", "status": "Happy", "issue": "No Issue", "sentiment": 95},
    ]

    # Calendar (Simplified Generation)
    days_in_jan = 31
    calendar_html = ""
    weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    for day in weekdays: calendar_html += f'<div class="text-xs text-gray-400 font-bold text-center py-1">{day}</div>'
    for _ in range(4): calendar_html += "<div></div>" # Offset
    for i in range(1, 32):
        status = "ontime"
        if i in [5, 12, 19, 29]: status = "late"
        color = "bg-green-100 text-green-700" if status == "ontime" else "bg-red-100 text-red-700 font-bold"
        calendar_html += f'<div class="h-8 border rounded flex items-center justify-center text-xs {color}">{i}</div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Report: {tech_name}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
</head>
<body class="bg-gray-100 min-h-screen p-4 font-sans text-gray-800">

    <div class="max-w-6xl mx-auto space-y-6">
        
        <!-- HEADER -->
        <div class="bg-white rounded-xl shadow-sm p-6 flex flex-col md:flex-row items-center justify-between border-t-4 border-blue-600">
            <div class="flex items-center">
                <div class="h-16 w-16 bg-blue-600 rounded-full flex items-center justify-center text-white text-2xl font-bold">{tech_name[0]}</div>
                <div class="ml-4">
                    <h1 class="text-2xl font-bold">{tech_name}</h1>
                    <span class="bg-purple-100 text-purple-700 px-2 py-0.5 rounded text-xs font-bold border border-purple-200">The Rat Hunter 🐀</span>
                </div>
            </div>
            <div class="text-right">
                <div class="text-4xl font-extrabold text-blue-600">{current_grade} <span class="text-lg text-gray-400 font-normal">({current_score})</span></div>
                <div class="text-xs text-gray-500 uppercase">Performance Grade</div>
            </div>
        </div>

        <!-- NEW SECTION: COMPLAINT ALERT -->
        <div class="bg-white rounded-xl shadow-sm overflow-hidden border border-red-100">
            <div class="bg-red-50 p-4 border-b border-red-100 flex justify-between items-center">
                <h3 class="text-red-700 font-bold flex items-center"><i class="fas fa-exclamation-circle mr-2"></i> Client Complaints (Jan 2026)</h3>
                <span class="bg-red-200 text-red-800 px-3 py-1 rounded-full text-xs font-bold">{complaint_stats['Major']} Major, {complaint_stats['Minor']} Minor</span>
            </div>
            <div class="p-0">
                <table class="w-full text-left text-sm">
                    <thead class="bg-gray-50 text-gray-500">
                        <tr>
                            <th class="p-4">Client Name</th>
                            <th class="p-4">Status</th>
                            <th class="p-4">Issue Reported</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-100">
    """
    
    # Loop Clients
    for client in client_feedback:
        icon = "😐"
        status_color = "text-gray-500"
        
        if client['status'] == 'Angry': 
            icon = "😡"
            status_color = "text-red-600 font-bold bg-red-50 px-2 py-1 rounded"
        elif client['status'] == 'Happy':
            icon = "😁"
            status_color = "text-green-600 font-bold bg-green-50 px-2 py-1 rounded"
            
        html += f"""
                        <tr class="hover:bg-gray-50">
                            <td class="p-4 font-medium">{client['name']}</td>
                            <td class="p-4"><span class="{status_color}">{icon} {client['status']}</span></td>
                            <td class="p-4 text-gray-600">{client['issue']}</td>
                        </tr>
        """

    html += """
                    </tbody>
                </table>
                <div class="p-3 bg-yellow-50 text-yellow-800 text-xs text-center border-t border-yellow-100">
                    💡 <b>Tip:</b> Prioritize visits to "Gudang Garam" & "McDonalds" next week to fix issues.
                </div>
            </div>
        </div>

        <!-- MAIN GRID -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            
            <!-- Catch Volume -->
            <div class="bg-white p-5 rounded-xl shadow-sm border border-gray-100">
                <h4 class="text-xs font-bold text-gray-400 uppercase mb-4">🐀 Monthly Catches</h4>
                <div class="h-40"><canvas id="catchChart"></canvas></div>
                <p class="text-xs text-center text-red-500 mt-2 font-bold">▼ 50% Drop in Jan</p>
            </div>

            <!-- Visit Trend -->
            <div class="bg-white p-5 rounded-xl shadow-sm border border-gray-100">
                <h4 class="text-xs font-bold text-gray-400 uppercase mb-4">📉 Visit Volume</h4>
                <div class="h-40"><canvas id="trendChart"></canvas></div>
                <p class="text-xs text-center text-gray-500 mt-2">Target: 140/mo</p>
            </div>

            <!-- Discipline Heatmap -->
            <div class="bg-white p-5 rounded-xl shadow-sm border border-gray-100">
                <h4 class="text-xs font-bold text-gray-400 uppercase mb-4">🗓️ Check-In Punctuality</h4>
                <div class="grid grid-cols-7 gap-1">
                    """ + calendar_html + """
                </div>
                <p class="text-xs text-center text-gray-400 mt-2">Green=OnTime, Red=Late</p>
            </div>
        </div>

    </div>

    <script>
        const common = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } };
        
        new Chart(document.getElementById('catchChart'), {
            type: 'bar',
            data: {
                labels: ['Aug','Sep','Oct','Nov','Dec','Jan'],
                datasets: [{ 
                    data: [450,480,510,490,380,210], 
                    backgroundColor: ['#d1d5db','#d1d5db','#d1d5db','#d1d5db','#f59e0b','#ef4444'],
                    borderRadius: 4
                }]
            },
            options: common
        });

        new Chart(document.getElementById('trendChart'), {
            type: 'line',
            data: {
                labels: ['Aug','Sep','Oct','Nov','Dec','Jan'],
                datasets: [{ 
                    data: [130,145,150,140,110,85], 
                    borderColor: '#2563eb', borderWidth: 2, tension: 0.4, pointRadius: 0
                }]
            },
            options: { ...common, scales: { x: {display:false}, y: {display:false} } }
        });
    </script>
</body>
</html>
    """
    
    with open(filepath, 'w') as f:
        f.write(html)
    print(f"Generated Enhanced V2 Report: {filepath}")

if __name__ == '__main__':
    generate_demo_report()
