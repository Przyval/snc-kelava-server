#!/usr/bin/env python3
"""
Step 11: Interactive Map Visualization (Folium) - Enhanced
==========================================================
Generates an interactive HTML map with Yearly Filters, Legend, and Client Names.

Features:
- Yearly Filter: Toggle layers for 2023, 2024, 2025, etc.
- MarkerClusters: Groups points for performance, showing individual pins on zoom.
- Tooltips: Hover over pins to see Customer Name & Date.
- Legend: HTML Overlay explaining the map colors.

Outputs:
- analytics/dashboard_data/eda/map_interactive_enhanced.html
"""

import sqlite3
import pandas as pd
import folium
from folium.plugins import MarkerCluster, HeatMap
from branca.element import Template, MacroElement
import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
OUTPUT_DIR_DATA = BASE_DIR / 'analytics/dashboard_data/eda'

os.makedirs(OUTPUT_DIR_DATA, exist_ok=True)

def get_enhanced_spatial_data():
    conn = sqlite3.connect(DB_PATH)
    
    # Join stg_visit with dim_customer
    query = """
    SELECT 
        v.latitude,
        v.longitude,
        v.check_in,
        c.name as customer_name,
        v.visit_id
    FROM stg_visit v
    LEFT JOIN dim_customer c ON v.id_customer = c.customer_id
    WHERE v.latitude IS NOT NULL 
      AND v.longitude IS NOT NULL
      AND v.latitude != '' 
      AND v.longitude != ''
      AND CAST(v.latitude AS FLOAT) != 0
    """
    
    df = pd.read_sql(query, conn)
    conn.close()
    
    # Parse Dates via Pandas (Robust to various formats)
    df['check_in_dt'] = pd.to_datetime(df['check_in'], errors='coerce', utc=True)
    df['year_str'] = df['check_in_dt'].dt.year.astype('Int64').astype(str)
    
    df['lat'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['lng'] = pd.to_numeric(df['longitude'], errors='coerce')
    
    df = df.dropna(subset=['lat', 'lng', 'year_str'])
    
    # Filter bounds (Indonesia roughly)
    df = df[(df['lat'] > -11) & (df['lat'] < 6) & (df['lng'] > 95) & (df['lng'] < 141)]
    
    # Clean names
    df['customer_name'] = df['customer_name'].fillna("Unknown Client")
    
    return df

def add_legend(m):
    template = """
    {% macro html(this, kwargs) %}
    <div style="
        position: fixed; 
        bottom: 50px; left: 50px; width: 250px; height: 160px; 
        z-index:9999; font-size:14px;
        background-color: white;
        border: 2px solid grey;
        border-radius: 6px;
        padding: 10px;
        opacity: 0.9;">
        <b>Map Legend</b><br>
        &nbsp; <i class="fa fa-map-marker" style="color:blue"></i>&nbsp; Client Visit (Cluster)<br>
        &nbsp; <i class="fa fa-info-circle" style="color:red"></i>&nbsp; Zone Centroid (Basecamp)<br>
        &nbsp; <span style="background: linear-gradient(to right, blue, lime, red); padding: 0 50px;"></span><br>
        &nbsp; Heatmap: Low to High Density<br>
        <br>
        <small><i>Use the Layer Control (top-right)<br>to filter by Year.</i></small>
    </div>
    {% endmacro %}
    """
    macro = MacroElement()
    macro._template = Template(template)
    m.get_root().add_child(macro)

def generate_enhanced_map(df):
    # Center map on Mean
    center_lat = df['lat'].median()
    center_lng = df['lng'].median()

    # Base Map
    m = folium.Map(location=[center_lat, center_lng], zoom_start=11, tiles='CartoDB positron')

    # 1. Base Heatmap (All Time)
    # --------------------------
    # Put heatmap in a separate layer
    heat_layer = folium.FeatureGroup(name='Heatmap (All Time)', show=True)
    HeatMap(df[['lat', 'lng']].values.tolist(), radius=10, blur=15).add_to(heat_layer)
    heat_layer.add_to(m)

    # 2. Yearly Layers with MarkerClusters
    # ------------------------------------
    years = sorted(df['year_str'].dropna().unique())
    print(f"Years found: {years}")

    for year in years:
        year_df = df[df['year_str'] == year]
        if year_df.empty: continue
        
        # Create a Layer Group for this year
        # Note: If points are too many, markers might be slow. 
        # Using MarkerCluster automatically handles performance.
        layer_name = f"Visits {year} ({len(year_df)})"
        year_group = folium.FeatureGroup(name=layer_name, show=(year == years[-1])) # Only show latest year by default
        
        cluster = MarkerCluster().add_to(year_group)
        
        # Add Markers
        # Iterate row by row (Might take a few seconds for 10k rows)
        # Performance Optimization: Limit to top 5000 per year if massive? 
        # For 33k total spread across years, it should be manageable (~10k/year).
        for _, row in year_df.iterrows():
            folium.Marker(
                location=[row['lat'], row['lng']],
                popup=f"<b>{row['customer_name']}</b><br>{row['check_in']}",
                tooltip=f"{row['customer_name']}", # Hover text
                icon=folium.Icon(color='blue', icon='user', prefix='fa')
            ).add_to(cluster)
            
        year_group.add_to(m)

    # 3. Add Centroids (Static Layer)
    # -------------------------------
    centroid_file = OUTPUT_DIR_DATA / 'spatial_zones.csv'
    if centroid_file.exists():
        zones = pd.read_csv(centroid_file)
        centroid_layer = folium.FeatureGroup(name='Zone Centers (Basecamps)', show=True)
        for _, row in zones.iterrows():
            folium.Marker(
                location=[row['centroid_lat'], row['centroid_lng']],
                popup=f"<b>Zone {int(row['zone_id'])} Basecamp</b><br>Volume: {int(row['visit_count'])}",
                tooltip="Zone Centroid",
                icon=folium.Icon(color='red', icon='info-circle', prefix='fa')
            ).add_to(centroid_layer)
            folium.Circle(
                location=[row['centroid_lat'], row['centroid_lng']], radius=2000, color='red', fill=True, fill_opacity=0.05
            ).add_to(centroid_layer)
        centroid_layer.add_to(m)

    # 4. Controls & Legend
    # --------------------
    folium.LayerControl(collapsed=False).add_to(m)
    add_legend(m)

    # Save
    outfile = OUTPUT_DIR_DATA / 'map_interactive_enhanced.html'
    m.save(outfile)
    print(f"Enhanced Map generated at: {outfile}")
    return outfile

def main():
    print("Generating Enhanced Interactive Map...")
    df = get_enhanced_spatial_data()
    print(f"Loaded {len(df)} points with client names.")
    
    generate_enhanced_map(df)
    print("Done.")

if __name__ == '__main__':
    main()
