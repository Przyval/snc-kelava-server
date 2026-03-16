#!/usr/bin/env python3
"""
Step 8: EDA Visualization Generator
===================================
Generates professional statistical plots for EDA Chapter 1.
Requires: pandas, matplotlib, seaborn

Outputs:
- analytics/dashboard_data/eda/images/duration_boxplot.png
- analytics/dashboard_data/eda/images/checkin_dist.png
- analytics/dashboard_data/eda/images/productivity_violin.png
"""

import matplotlib
matplotlib.use('Agg') # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import sqlite3
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
OUTPUT_DIR = BASE_DIR / 'analytics/dashboard_data/eda/images'

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Set professional style
sns.set_theme(style="whitegrid", context="talk")
plt.rcParams['figure.figsize'] = (12, 8)
plt.rcParams['font.family'] = 'sans-serif'

def get_data():
    conn = sqlite3.connect(DB_PATH)
    
    # Duration Data
    query_visit = """
    SELECT 
        segment,
        duration_min_raw,
        check_in_hour,
        strftime('%w', check_in_first) as day_of_week
    FROM fact_kpi_visit
    WHERE is_completed = 1 
      AND duration_min_raw > 0 
      AND duration_min_raw < 1440
      AND segment IN ('MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR')
    """
    df_visit = pd.read_sql(query_visit, conn)
    
    # Productivity Data
    query_prod = """
    SELECT 
        segment,
        visits_day
    FROM (
        SELECT 
            user_id, segment, actual_day, COUNT(*) as visits_day
        FROM fact_kpi_visit
        WHERE is_completed = 1
        GROUP BY user_id, segment, actual_day
    )
    WHERE segment IN ('MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR')
    """
    df_prod = pd.read_sql(query_prod, conn)
    
    conn.close()
    return df_visit, df_prod

def plot_duration_boxplot(df):
    plt.figure(figsize=(12, 6))
    
    # Order: Mobile, Station, Support, Supervisor
    order = ['MOBILE', 'STATION', 'SUPPORT', 'SUPERVISOR']
    colors = {'MOBILE': '#3b82f6', 'STATION': '#10b981', 'SUPPORT': '#f59e0b', 'SUPERVISOR': '#8b5cf6'}
    
    # Create Boxplot with Strip plot overlay
    ax = sns.boxplot(x="segment", y="duration_min_raw", data=df, order=order, palette=colors,
                     showfliers=False, whis=1.5, boxprops=dict(alpha=.7))
    
    # Add title and labels
    plt.title('Duration Distribution by Segment (The Two Worlds)', fontsize=16, fontweight='bold', pad=20)
    plt.ylabel('Duration (Minutes)', fontsize=12)
    plt.xlabel('Technician Segment', fontsize=12)
    
    # Add Reference Lines
    plt.axhline(y=94, color='#3b82f6', linestyle='--', alpha=0.5, label='Mobile Median (94m)')
    plt.axhline(y=506, color='#10b981', linestyle='--', alpha=0.5, label='Station Median (506m)')
    plt.legend(loc='upper right', frameon=True)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'duration_boxplot.png', dpi=300)
    print("  -> duration_boxplot.png")

def plot_checkin_distribution(df):
    plt.figure(figsize=(14, 7))
    
    # Filter only Mobile vs Station for clarity
    df_filtered = df[df['segment'].isin(['MOBILE', 'STATION'])]
    
    # KDE Plot (Kernel Density Estimate) - Smoothed Histogram
    sns.kdeplot(data=df_filtered, x="check_in_hour", hue="segment", 
                fill=True, common_norm=False, palette={'MOBILE': '#3b82f6', 'STATION': '#10b981'},
                alpha=0.3, linewidth=2.5)
    
    plt.title('Daily Check-in Rhythm: "Sprinter" vs "Marathoner"', fontsize=16, fontweight='bold', pad=20)
    plt.xlabel('Hour of Day (00:00 - 23:00)', fontsize=12)
    plt.ylabel('Density of Check-ins', fontsize=12)
    plt.xlim(0, 24)
    plt.xticks(range(0, 25, 2))
    
    # Annotate Peaks
    plt.annotate('Station Shift Start (07:00)', xy=(7, 0.15), xytext=(2, 0.18),
                 arrowprops=dict(facecolor='black', shrink=0.05, alpha=0.5))
    
    plt.annotate('Mobile "Late Sync" (21:00)', xy=(21, 0.05), xytext=(16, 0.08),
                 arrowprops=dict(facecolor='red', shrink=0.05))
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'checkin_dist.png', dpi=300)
    print("  -> checkin_dist.png")

def plot_productivity_violin(df):
    plt.figure(figsize=(12, 6))
    
    order = ['MOBILE', 'STATION']
    colors = {'MOBILE': '#3b82f6', 'STATION': '#10b981'}
    
    # Violin plot shows density + range
    sns.violinplot(x="segment", y="visits_day", data=df[df['segment'].isin(order)], 
                   palette=colors, inner="quartile", cut=0)
    
    plt.title('Daily Productivity Profile', fontsize=16, fontweight='bold', pad=20)
    plt.ylabel('Visits Completed per Day', fontsize=12)
    plt.xlabel(None)
    plt.yticks(range(0, 15)) # Limit y-axis as most are < 10
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'productivity_violin.png', dpi=300)
    print("  -> productivity_violin.png")

def main():
    print("Generatiing EDA Visualizations with Seaborn...")
    df_visit, df_prod = get_data()
    
    plot_duration_boxplot(df_visit)
    plot_checkin_distribution(df_visit)
    plot_productivity_violin(df_prod)
    
    print("Visualizations Generated in analytics/dashboard_data/eda/images/")

if __name__ == '__main__':
    main()
