#!/usr/bin/env python3
"""
Step 10: EDA Chapter 3 - "Spatial Intelligence"
===============================================
Uses K-Means clustering on GPS coordinates to Identify Operational Zones.
Focus: Finding geographical "Hotzones" and optimal basecamp locations (Centroids).

Requires: scikit-learn, pandas, seaborn, matplotlib

Outputs:
- analytics/dashboard_data/eda/spatial_zones.csv
- analytics/dashboard_data/eda/images/map_zones.png
- analytics/dashboard_data/eda/images/map_density.png
"""

import sqlite3
import pandas as pd
import numpy as np
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.cluster import KMeans
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
OUTPUT_DIR_DATA = BASE_DIR / 'analytics/dashboard_data/eda'
OUTPUT_DIR_IMG = BASE_DIR / 'analytics/dashboard_data/eda/images'

os.makedirs(OUTPUT_DIR_DATA, exist_ok=True)
os.makedirs(OUTPUT_DIR_IMG, exist_ok=True)

sns.set_theme(style="white", context="talk")

def get_spatial_data():
    conn = sqlite3.connect(DB_PATH)
    
    # Get Latitude/Longitude from raw visits
    # Filter out invalid coordinates (0,0) or empty
    query = """
    SELECT 
        visit_id,
        latitude,
        longitude,
        check_in
    FROM stg_visit
    WHERE latitude IS NOT NULL 
      AND longitude IS NOT NULL
      AND latitude != '' 
      AND longitude != ''
      AND CAST(latitude AS FLOAT) != 0
      AND CAST(longitude AS FLOAT) != 0
    """
    
    df = pd.read_sql(query, conn)
    conn.close()
    
    # Convert to float
    df['lat'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['lng'] = pd.to_numeric(df['longitude'], errors='coerce')
    
    # Drop parsing errors
    df = df.dropna(subset=['lat', 'lng'])
    
    # Simple filter for Indonesia/Surabaya roughly (Filter crazy outliers)
    # Java bounds roughly: Lat -8.9 to -5.9, Lng 105 to 115
    # Relaxed bounds for now to see what we have
    df = df[(df['lat'] > -11) & (df['lat'] < 6) & (df['lng'] > 95) & (df['lng'] < 141)]
    
    return df

def perform_spatial_clustering(df, n_clusters=5):
    X = df[['lat', 'lng']].copy()
    
    # KMeans
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df['zone_id'] = kmeans.fit_predict(X)
    
    # Get Centroids (Optimal Basecamps)
    centroids = kmeans.cluster_centers_
    
    return df, centroids

def plot_zone_map(df, centroids):
    plt.figure(figsize=(12, 10))
    
    # Scatter plot of visits colored by Zone
    sns.scatterplot(
        data=df, x='lng', y='lat', 
        hue='zone_id', palette='tab10', 
        s=10, alpha=0.6, legend='full'
    )
    
    # Plot Centroids (Big Red X)
    plt.scatter(
        centroids[:, 1], centroids[:, 0], 
        marker='X', s=200, c='red', 
        edgecolors='black', linewidths=2, zorder=10, label='Centroids (Opt. Basecamp)'
    )
    
    plt.title('Operational Zones Strategy (Spatial Clustering)', fontsize=16, fontweight='bold')
    plt.xlabel('Longitude')
    plt.ylabel('Latitude')
    plt.legend(loc='upper right')
    
    # Equal aspect ratio to map looks real
    plt.axis('equal')
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR_IMG / 'map_zones.png', dpi=300)
    print("  -> map_zones.png")

def plot_density_map(df):
    plt.figure(figsize=(12, 10))
    
    # Density / Heatmap
    sns.kdeplot(
        data=df, x='lng', y='lat', 
        fill=True, cmap='inferno', thresh=0.05, alpha=0.8
    )
    
    plt.title('Visit Density Heatmap (Hotzones)', fontsize=16, fontweight='bold')
    plt.axis('equal')
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR_IMG / 'map_density.png', dpi=300)
    print("  -> map_density.png")

def save_zone_info(df, centroids):
    # Cluster counts
    zone_counts = df['zone_id'].value_counts().reset_index()
    zone_counts.columns = ['zone_id', 'visit_count']
    zone_counts = zone_counts.sort_values('zone_id')
    
    # Add Centroid info
    zone_counts['centroid_lat'] = centroids[:, 0]
    zone_counts['centroid_lng'] = centroids[:, 1]
    
    print("\nZone Profiles:")
    print(zone_counts)
    
    zone_counts.to_csv(OUTPUT_DIR_DATA / 'spatial_zones.csv', index=False)
    print("  -> spatial_zones.csv")

def main():
    print("Starting EDA Chapter 3: Spatial Clustering...")
    
    df = get_spatial_data()
    print(f"Loaded {len(df)} valid GPS points.")
    
    if len(df) < 100:
        print("Not enough data for spatial clustering.")
        return

    # Use 5 Zones as discussed
    df_clustered, centroids = perform_spatial_clustering(df, n_clusters=5)
    
    plot_zone_map(df_clustered, centroids)
    plot_density_map(df_clustered)
    save_zone_info(df_clustered, centroids)
    
    print("Spatial Intelligence Complete.")

if __name__ == '__main__':
    main()
