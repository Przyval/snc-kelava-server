#!/usr/bin/env python3
"""
Step 12: Customer Segmentation HTML Generator
=============================================
Generates a standalone HTML report for Customer Segmentation.
Features:
- Executive Summary Cards
- Interactive Table (Search/Sort)
- Professional Styling

Outputs:
- analytics/dashboard_data/eda/customer_segments.html
"""

import pandas as pd
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / 'analytics/dashboard_data/eda'
CSV_PATH = OUTPUT_DIR / 'customer_segments.csv'

def generate_html_report():
    if not CSV_PATH.exists():
        print("CSV not found!")
        return

    df = pd.read_csv(CSV_PATH)
    
    # Calculate Summary Stats
    summary = df['segment_label'].value_counts()
    
    sultan_count = summary.get('The Sultan (VIP)', 0)
    ghost_count = summary.get('The Ghost (Churn Risk)', 0)
    regular_count = len(df) - sultan_count - ghost_count
    
    # Generate HTML content
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SanoCare Customer Segmentation</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    
    <!-- DataTables -->
    <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.11.5/css/jquery.dataTables.css">
    <script type="text/javascript" charset="utf8" src="https://code.jquery.com/jquery-3.5.1.js"></script>
    <script type="text/javascript" charset="utf8" src="https://cdn.datatables.net/1.11.5/js/jquery.dataTables.js"></script>

    <style>
        .dataTables_wrapper .dataTables_length, .dataTables_wrapper .dataTables_filter, .dataTables_wrapper .dataTables_info, .dataTables_wrapper .dataTables_processing, .dataTables_wrapper .dataTables_paginate {{
            color: #4b5563;
            margin-bottom: 10px;
            margin-top: 10px;
        }}
        table.dataTable thead th {{
            padding: 12px 10px;
            background-color: #f3f4f6;
            color: #374151;
        }}
        table.dataTable tbody td {{
            padding: 10px 10px;
        }}
        /* Row Colors */
        .row-sultan {{ background-color: #fef3c7 !important; }}
        .row-ghost {{ background-color: #f3f4f6 !important; color: #9ca3af; }}
    </style>
</head>
<body class="bg-gray-50 min-h-screen p-8 text-gray-800">

    <!-- Header -->
    <div class="max-w-7xl mx-auto mb-8">
        <h1 class="text-3xl font-bold text-gray-900 mb-2">
            <i class="fas fa-users-cog text-blue-600 mr-2"></i> Customer Segmentation Analysis
        </h1>
        <p class="text-gray-600">AI-driven classification of {len(df)} customers based on operational engagement.</p>
    </div>

    <!-- Stats Cards -->
    <div class="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <!-- Sultan Card -->
        <div class="bg-white rounded-xl shadow-sm border border-yellow-200 p-6 flex items-center">
            <div class="p-4 rounded-full bg-yellow-100 text-yellow-600 mr-4">
                <i class="fas fa-crown text-2xl"></i>
            </div>
            <div>
                <p class="text-sm text-gray-500 font-medium">VIP Clients (Sultans)</p>
                <h3 class="text-3xl font-bold text-gray-900">{sultan_count}</h3>
                <p class="text-xs text-yellow-600">High Engagement & Frequency</p>
            </div>
        </div>

        <!-- Ghost Card -->
        <div class="bg-white rounded-xl shadow-sm border border-red-200 p-6 flex items-center">
            <div class="p-4 rounded-full bg-red-100 text-red-600 mr-4">
                <i class="fas fa-ghost text-2xl"></i>
            </div>
            <div>
                <p class="text-sm text-gray-500 font-medium">Churn Risk (Ghosts)</p>
                <h3 class="text-3xl font-bold text-gray-900">{ghost_count}</h3>
                <p class="text-xs text-red-600">Inactive > 1 Year</p>
            </div>
        </div>

        <!-- Regular Card -->
        <div class="bg-white rounded-xl shadow-sm border border-blue-200 p-6 flex items-center">
            <div class="p-4 rounded-full bg-blue-100 text-blue-600 mr-4">
                <i class="fas fa-user-check text-2xl"></i>
            </div>
            <div>
                <p class="text-sm text-gray-500 font-medium">Active Regulars</p>
                <h3 class="text-3xl font-bold text-gray-900">{regular_count}</h3>
                <p class="text-xs text-blue-600">Steady Operational Flow</p>
            </div>
        </div>
    </div>

    <!-- Main Table -->
    <div class="max-w-7xl mx-auto bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
        <div class="p-6 border-b border-gray-100">
            <h2 class="text-lg font-semibold text-gray-900">Detailed Client List</h2>
        </div>
        <div class="p-6">
            <table id="clientTable" class="display w-full text-sm text-left">
                <thead>
                    <tr>
                        <th>Customer Name</th>
                        <th>City</th>
                        <th>Segment</th>
                        <th>Recency (Days)</th>
                        <th>Frequency (Visits)</th>
                        <th>Engagement (Hours)</th>
                    </tr>
                </thead>
                <tbody>
    """

    # Add Rows
    for _, row in df.iterrows():
        segment = row['segment_label']
        
        # Badge Styling
        badge_class = "bg-gray-100 text-gray-800"
        row_class = ""
        icon = ""
        
        if "Sultan" in segment:
            badge_class = "bg-yellow-100 text-yellow-800 border border-yellow-200"
            row_class = "row-sultan"
            icon = '<i class="fas fa-crown mr-1"></i>'
        elif "Ghost" in segment:
            badge_class = "bg-red-100 text-red-800 border border-red-200"
            row_class = "row-ghost"
            icon = '<i class="fas fa-ghost mr-1"></i>'
        elif "High Freq" in segment:
            badge_class = "bg-blue-100 text-blue-800"
            icon = '<i class="fas fa-sync mr-1"></i>'
        
        city = row['customer_city'] if pd.notna(row['customer_city']) else '-'
        
        html_content += f"""
                    <tr class="{row_class}">
                        <td class="font-medium">{row['customer_name']}</td>
                        <td>{city}</td>
                        <td><span class="px-2 py-1 rounded-full text-xs font-semibold {badge_class}">{icon}{segment}</span></td>
                        <td>{int(row['recency_days'])}</td>
                        <td>{int(row['frequency_visits'])}</td>
                        <td>{float(row['engagement_hours']):.1f}</td>
                    </tr>
        """

    html_content += """
                </tbody>
            </table>
        </div>
    </div>

    <!-- Footer -->
    <div class="max-w-7xl mx-auto mt-8 text-center text-gray-400 text-sm">
        <p>Generated by SanoCare AI Analytics • EDA Chapter 4</p>
    </div>

    <script>
        $(document).ready(function() {
            $('#clientTable').DataTable({
                "pageLength": 25,
                "order": [[ 5, "desc" ]] // Sort by Engagement descending by default
            });
        });
    </script>
</body>
</html>
    """

    outfile = OUTPUT_DIR / 'customer_segments.html'
    with open(outfile, 'w') as f:
        f.write(html_content)
    
    print(f"HTML Report generated: {outfile}")

if __name__ == '__main__':
    generate_html_report()
