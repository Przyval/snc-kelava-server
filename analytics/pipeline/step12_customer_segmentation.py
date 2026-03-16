#!/usr/bin/env python3
"""
Step 12: EDA Chapter 4 - "The Sultan Finder" (Customer Segmentation)
=====================================================================
Uses R-F-E (Recency, Frequency, Engagement) logic + K-Means to segment customers.
Purpose: Identify VIPs ("Sultans"), Regulars, and Churn Risks ("Ghosts").

Metrics:
- Recency (R): Days since last visit.
- Frequency (F): Total visits in period.
- Engagement (E): Total technician-hours spent (Cost to Serve).

Outputs:
- analytics/dashboard_data/eda/customer_segments.csv
- analytics/dashboard_data/eda/images/customer_segments.png
"""

import sqlite3
import pandas as pd
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
OUTPUT_DIR_DATA = BASE_DIR / 'analytics/dashboard_data/eda'
OUTPUT_DIR_IMG = BASE_DIR / 'analytics/dashboard_data/eda/images'

os.makedirs(OUTPUT_DIR_DATA, exist_ok=True)
os.makedirs(OUTPUT_DIR_IMG, exist_ok=True)

sns.set_theme(style="whitegrid", context="talk")

def get_customer_features():
    conn = sqlite3.connect(DB_PATH)
    
    # R-F-E Query
    # Recency: Calculated relative to the MAX date in dataset (Snapshot logic)
    query = """
    SELECT 
        customer_id,
        customer_name,
        customer_city,
        COUNT(DISTINCT road_plan_id) as frequency_visits,
        SUM(duration_min_capped) / 60.0 as engagement_hours,
        MAX(visit_date) as last_visit_date
    FROM fact_visit_enriched
    WHERE is_complete = 1
      -- Exclude internal/test customers if needed
      AND customer_name NOT LIKE '%TEST%'
    GROUP BY customer_id, customer_name, customer_city
    HAVING frequency_visits > 1 -- Exclude one-off visits to reduce noise
    """
    
    df = pd.read_sql(query, conn)
    conn.close()
    
    # Calculate Recency
    df['last_visit_dt'] = pd.to_datetime(df['last_visit_date'])
    snapshot_date = df['last_visit_dt'].max()
    df['recency_days'] = (snapshot_date - df['last_visit_dt']).dt.days
    
    return df

def perform_clustering(df):
    # Features for clustering: Recency, Frequency, Engagement
    features = ['recency_days', 'frequency_visits', 'engagement_hours']
    X = df[features].copy()
    
    # Handle NaN
    X = X.fillna(0)
    
    # Log transform right-skewed data (Frequency & Engagement usually power law)
    # Adding +1 to handle zeros
    X_log = np.log1p(X)
    
    # Scale
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_log)
    
    # KMeans - 4 Clusters (Hypothesis: VIP, Regular, Low Value, Churn Risk)
    kmeans = KMeans(n_clusters=4, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(X_scaled)
    
    return df

def label_clusters(df):
    # Rule-based auto-labeling based on centroids to make sense of cluster IDs
    # We look at the mean of features for each cluster
    profile = df.groupby('cluster')[['recency_days', 'frequency_visits', 'engagement_hours']].mean()
    
    # Logic:
    # High Freq + High Eng = "The Sultan" (VIP)
    # High Recency (Long time ago) + Low Freq = "The Ghost" (Churn/Inactive)
    # High Freq + Low Eng = "Fast Food" (Frequent but quick checks)
    # Low Recency (Recent) + Avg Freq = "Regulars"
    
    # Sort clusters by Engagement (Hours) to find Sultans provided Freq is also high
    # This is a simplification, but helps consistency in color mapping
    
    # Let's map dynamically:
    # 1. Find cluster with max average engagement -> "The Sultan"
    # 2. Find cluster with max average recency -> "The Ghost (Churn Risk)"
    # 3. Find cluster with max frequency but low engagement -> "High Maintenance" or "Fast Active"
    # 4. Rest -> "Regulars"
    
    labels = {}
    
    # Sort indices
    sorted_eng = profile.sort_values('engagement_hours', ascending=False)
    sultan_idx = sorted_eng.index[0]
    labels[sultan_idx] = "The Sultan (VIP)"
    
    sorted_rec = profile.sort_values('recency_days', ascending=False)
    # Ensure we don't overwrite if same
    ghost_idx = -1
    for idx in sorted_rec.index:
        if idx not in labels:
            ghost_idx = idx
            break
    if ghost_idx != -1:
        labels[ghost_idx] = "The Ghost (Churn Risk)"
            
    # Remaining
    for idx in profile.index:
        if idx not in labels:
            # Check if high frequency
            if profile.loc[idx, 'frequency_visits'] > df['frequency_visits'].median():
                 labels[idx] = "High Freq Regular"
            else:
                 labels[idx] = "Standard Regular"
                 
    df['segment_label'] = df['cluster'].map(labels)
    return df

def plot_segments(df):
    plt.figure(figsize=(14, 8))
    
    sns.scatterplot(
        data=df, 
        x='engagement_hours', y='frequency_visits', 
        hue='segment_label', style='segment_label',
        palette='deep', s=100, alpha=0.8
    )
    
    # Log scale for better visualization of power law distributions
    plt.xscale('log')
    plt.yscale('log')
    
    plt.title('Customer Segmentation: "The Sultan" Finder (R-F-E)', fontsize=16, fontweight='bold')
    plt.xlabel('Total Engagement (Hours) - Log Scale')
    plt.ylabel('Visit Frequency - Log Scale')
    
    # Annotate Top 5 Sultans
    sultans = df[df['segment_label'] == "The Sultan (VIP)"].sort_values('engagement_hours', ascending=False).head(5)
    for _, row in sultans.iterrows():
         plt.text(row['engagement_hours'], row['frequency_visits'], 
                  row['customer_name'][:15], fontsize=9, fontweight='bold')

    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR_IMG / 'customer_segments.png', dpi=300)
    print("  -> customer_segments.png")

def save_segments(df):
    # Export clean list
    out_df = df[['customer_name', 'customer_city', 'segment_label', 'recency_days', 'frequency_visits', 'engagement_hours']]
    out_df = out_df.sort_values(['segment_label', 'engagement_hours'], ascending=[True, False])
    
    out_df.to_csv(OUTPUT_DIR_DATA / 'customer_segments.csv', index=False)
    print("  -> customer_segments.csv")
    
    # Print Summary profiles
    print("\nSegment Profiles (Averages):")
    print(df.groupby('segment_label')[['recency_days', 'frequency_visits', 'engagement_hours']].mean().round(1))

def main():
    print("Starting EDA Chapter 4: Customer Segmentation...")
    
    df = get_customer_features()
    print(f"Analyzing {len(df)} customers...")
    
    if len(df) < 10:
        print("Not enough customers for clustering.")
        return

    df_clustered = perform_clustering(df)
    df_labeled = label_clusters(df_clustered)
    
    plot_segments(df_labeled)
    save_segments(df_labeled)
    print("Segmentation Complete.")

if __name__ == '__main__':
    main()
