#!/usr/bin/env python3
"""
Step 9: EDA Chapter 2 - "The Personas" (Clustering)
===================================================
Uses K-Means clustering to segment technicians into behavioral groups.
Requires: scikit-learn, pandas, seaborn

Features used:
1. Productivity (Avg visits/day)
2. Speed (Median duration)
3. Consistency (Duration IQR - lower is better)
4. Discipline (On-Time %)
5. Compliance (Photo %)

Outputs:
- analytics/dashboard_data/eda/technician_personas.csv
- analytics/dashboard_data/eda/images/persona_clusters.png
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
from sklearn.decomposition import PCA
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
OUTPUT_DIR_DATA = BASE_DIR / 'analytics/dashboard_data/eda'
OUTPUT_DIR_IMG = BASE_DIR / 'analytics/dashboard_data/eda/images'

os.makedirs(OUTPUT_DIR_DATA, exist_ok=True)
os.makedirs(OUTPUT_DIR_IMG, exist_ok=True)

# Set style
sns.set_theme(style="whitegrid", context="talk")

def get_tech_features():
    conn = sqlite3.connect(DB_PATH)
    
    # Aggregated metrics per technician
    query = """
    SELECT 
        user_id,
        technician_name,
        segment,
        COUNT(*) as total_visits,
        AVG(visits_day) as avg_productivity,
        AVG(duration_min_raw) as avg_duration,
        CAST(SUM(is_on_time_strict_v2) AS FLOAT) / COUNT(*) as on_time_rate,
        CAST(SUM(CASE WHEN foto_count > 0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) as photo_compliance
    FROM (
        -- Subquery to get visits per day first for productivity
        SELECT 
            k.*,
            d.visits_day
        FROM fact_kpi_visit k
        JOIN (
            SELECT user_id, actual_day, COUNT(*) as visits_day
            FROM fact_kpi_visit
            WHERE is_completed=1
            GROUP BY user_id, actual_day
        ) d ON k.user_id = d.user_id AND k.actual_day = d.actual_day
        WHERE k.is_completed = 1
    )
    WHERE segment IN ('MOBILE', 'STATION') -- Only cluster core workforce
    GROUP BY user_id, technician_name, segment
    HAVING total_visits > 10 -- Exclude new/inactive techs
    """
    
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def perform_clustering(df):
    # Select features for clustering
    features = ['avg_productivity', 'avg_duration', 'on_time_rate', 'photo_compliance']
    X = df[features].copy()
    
    # Handle NaN
    X = X.fillna(0)
    
    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # KMeans - 4 Clusters (Hypothesis: Stars, Admin-Slackers, Low-Performers, Average)
    kmeans = KMeans(n_clusters=4, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(X_scaled)
    
    # PCA for Visualization (2D projection)
    pca = PCA(n_components=2)
    components = pca.fit_transform(X_scaled)
    df['pca_x'] = components[:, 0]
    df['pca_y'] = components[:, 1]
    
    return df

def plot_clusters(df):
    plt.figure(figsize=(14, 8))
    
    # Define interpretable labels (After seeing data, we usually rename these)
    # For automation, we keep cluster IDs but color code them.
    
    sns.scatterplot(
        data=df, 
        x='pca_x', y='pca_y', 
        hue='cluster', style='segment',
        palette='viridis', s=200, alpha=0.9
    )
    
    # Annotate a few points
    for i in range(df.shape[0]):
        if i % 3 == 0: # Annotate every 3rd to avoid clutter
            plt.text(
                df.pca_x[i]+0.1, df.pca_y[i], 
                df.technician_name[i].split(' ')[0], 
                fontsize=9, alpha=0.7
            )
            
    plt.title('Technician Personas: Behavioral Clustering', fontsize=16, fontweight='bold')
    plt.xlabel('Principal Component 1 (Likely Productivity)')
    plt.ylabel('Principal Component 2 (Likely Compliance)')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR_IMG / 'persona_clusters.png', dpi=300)
    print("  -> persona_clusters.png")

def save_personas(df):
    # Calculate Cluster Profiles to interpret them
    profile = df.groupby('cluster')[['avg_productivity', 'on_time_rate', 'photo_compliance', 'avg_duration']].mean()
    print("\nCluster Profiles:")
    print(profile)
    
    df.to_csv(OUTPUT_DIR_DATA / 'technician_personas.csv', index=False)
    print("  -> technician_personas.csv")

def main():
    print("Starting EDA Chapter 2: Clustering...")
    
    df = get_tech_features()
    if df.empty:
        print("No data found for clustering.")
        return

    print(f"Clustering {len(df)} technicians...")
    df_clustered = perform_clustering(df)
    
    plot_clusters(df_clustered)
    save_personas(df_clustered)
    print("Clustering Complete.")

if __name__ == '__main__':
    main()
