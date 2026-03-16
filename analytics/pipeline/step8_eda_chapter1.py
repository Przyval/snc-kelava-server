#!/usr/bin/env python3
"""
Step 8: EDA Chapter 1 - "The Baseline" (No Pandas Version)
==========================================================
Implements SOP-driven analysis to establish statistical baselines.
Uses native Python libraries (statistics, csv) to be environment-agnostic.

Outputs:
- analytics/dashboard_data/eda/baseline_duration.csv
- analytics/dashboard_data/eda/baseline_productivity.csv
- analytics/dashboard_data/eda/dist_checkin_hour.csv
- analytics/dashboard_data/eda/duration_by_dow_median.csv
- analytics/dashboard_data/eda/segment_counts.csv
"""

import sqlite3
import csv
import os
import math
import statistics
from collections import defaultdict
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
OUTPUT_DIR = BASE_DIR / 'analytics/dashboard_data/eda'

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def calculate_stats(data_list):
    """
    Calculates robust univariate statistics for a list of numbers.
    """
    if not data_list:
        return {}
    
    n = len(data_list)
    sorted_data = sorted(data_list)
    
    mean_val = statistics.mean(data_list)
    median_val = statistics.median(data_list)
    try:
        stdev_val = statistics.stdev(data_list) if n > 1 else 0.0
    except:
        stdev_val = 0.0

    # Percentiles
    def get_percentile(p):
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return d0 + d1

    p05 = get_percentile(0.05)
    p25 = get_percentile(0.25)
    p75 = get_percentile(0.75)
    p95 = get_percentile(0.95)
    
    # IQR
    iqr = p75 - p25
    
    # MAD (Median Absolute Deviation)
    median_diffs = [abs(x - median_val) for x in data_list]
    mad = statistics.median(median_diffs)
    
    return {
        'count': n,
        'mean': round(mean_val, 2),
        'median_p50': round(median_val, 2),
        'std_dev': round(stdev_val, 2),
        'iqr': round(iqr, 2),
        'mad': round(mad, 2),
        'p05': round(p05, 2),
        'p25': round(p25, 2),
        'p75': round(p75, 2),
        'p95': round(p95, 2),
        'min': min(data_list),
        'max': max(data_list)
    }

def dict_to_csv(data_dict, filename, key_label='Segment'):
    """Helper to write dictionary of stats to CSV"""
    filepath = OUTPUT_DIR / filename
    
    # Get all metric keys from the first entry
    first_key = list(data_dict.keys())[0]
    metrics = list(data_dict[first_key].keys())
    
    headers = [key_label] + metrics
    
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for key, stats in data_dict.items():
            row = [key] + [stats[m] for m in metrics]
            writer.writerow(row)
    print(f"  -> {filename}")

def main():
    print("Starting EDA Chapter 1 (Native Python)...")
    conn = get_db_connection()
    
    # 1. Load Data
    # ---------------------------------------------------------
    print("Loading data...")
    
    # Duration Data
    # Filter valid durations (exclude huge outliers > 24h for baseline calculation)
    query_visit = """
    SELECT 
        user_id, technician_name, segment,
        duration_min_raw,
        check_in_hour,
        strftime('%w', check_in_first) as day_of_week
    FROM fact_kpi_visit
    WHERE is_completed = 1 
      AND duration_min_raw IS NOT NULL
      AND duration_min_raw > 0 
      AND duration_min_raw < 1440 
    """
    
    # Store data in memory structures grouped by segment
    duration_data = defaultdict(list)
    checkin_data = defaultdict(lambda: defaultdict(int)) # segment -> hour -> count
    dow_duration_data = defaultdict(lambda: defaultdict(list)) # segment -> dow -> durations
    counts_data = defaultdict(int)

    cursor = conn.execute(query_visit)
    for row in cursor:
        seg = row['segment'] if row['segment'] else 'UNKNOWN'
        
        # Duration
        val = row['duration_min_raw']
        duration_data[seg].append(val)
        
        # Checkin Hour
        hr = row['check_in_hour']
        if hr is not None:
             checkin_data[seg][int(hr)] += 1
             
        # DOW
        dow = int(row['day_of_week']) # 0=Sun
        dow_duration_data[seg][dow].append(val)
        
        # Count
        counts_data[seg] += 1

    # Productivity Data
    query_prod = """
    SELECT 
        user_id, technician_name, segment, actual_day,
        COUNT(*) as visits_day
    FROM fact_kpi_visit
    WHERE is_completed = 1
    GROUP BY user_id, technician_name, segment, actual_day
    """
    prod_data = defaultdict(list)
    cursor = conn.execute(query_prod)
    for row in cursor:
        seg = row['segment'] if row['segment'] else 'UNKNOWN'
        prod_data[seg].append(row['visits_day'])

    # 2. Univariate: Duration (Unit: Visit)
    # ---------------------------------------------------------
    print("Calculating Duration Baselines...")
    duration_stats_result = {}
    for seg, values in duration_data.items():
        duration_stats_result[seg] = calculate_stats(values)
    dict_to_csv(duration_stats_result, 'baseline_duration.csv')

    # 3. Univariate: Productivity (Unit: Technician-Day)
    # ---------------------------------------------------------
    print("Calculating Productivity Baselines...")
    prod_stats_result = {}
    for seg, values in prod_data.items():
        prod_stats_result[seg] = calculate_stats(values)
    dict_to_csv(prod_stats_result, 'baseline_productivity.csv')

    # 4. Distribution: Check-in Hour
    # ---------------------------------------------------------
    print("Calculating Check-in Hour Distribution...")
    # Convert counts to percentages
    # Headers: Segment, 0, 1, ... 23
    csv_rows = []
    hours = list(range(24))
    
    with open(OUTPUT_DIR / 'dist_checkin_hour.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Segment'] + [str(h) for h in hours])
        
        for seg, hour_counts in checkin_data.items():
            total = sum(hour_counts.values())
            if total == 0: continue
            row = [seg]
            for h in hours:
                pct = round((hour_counts.get(h, 0) / total) * 100, 1)
                row.append(pct)
            writer.writerow(row)
    print("  -> dist_checkin_hour.csv")

    # 5. Bivariate: Duration by Day of Week
    # ---------------------------------------------------------
    print("Calculating Duration by Day of Week...")
    # Rows: Segment, Mon, Tue, ... Sun
    # Calculate MEDIAN duration for each
    day_map = {0: 'Sun', 1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri', 6: 'Sat'}
    ordered_days = [1, 2, 3, 4, 5, 6, 0] # Mon to Sun
    
    with open(OUTPUT_DIR / 'duration_by_dow_median.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        header = ['Segment'] + [day_map[d] for d in ordered_days]
        writer.writerow(header)
        
        for seg, dow_dict in dow_duration_data.items():
            row = [seg]
            for d in ordered_days:
                vals = dow_dict.get(d, [])
                if vals:
                    med = round(statistics.median(vals), 1)
                else:
                    med = 0
                row.append(med)
            writer.writerow(row)
    print("  -> duration_by_dow_median.csv")

    # 6. Categorical: Segment Counts
    # ---------------------------------------------------------
    total_visits = sum(counts_data.values())
    with open(OUTPUT_DIR / 'segment_counts.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Segment', 'Count', 'Percentage'])
        for seg, count in counts_data.items():
            pct = round((count / total_visits) * 100, 1)
            writer.writerow([seg, count, pct])
    print("  -> segment_counts.csv")

    print("EDA Complete. Artifacts in analytics/dashboard_data/eda/")
    conn.close()

if __name__ == '__main__':
    main()
