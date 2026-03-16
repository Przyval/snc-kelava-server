#!/usr/bin/env python3
"""
Step 14 (Live Tracking V3): search, Connectors, and Activity
============================================================
Features:
1.  **Search Bar:** Filter map to show only one technician.
    -   Implemented via CSS Injection + Helper JS.
    -   Dropdown list populated dynamically.
2.  **Movement Lines:**
    -   Draws lines between Visit A and Visit B.
    -   Visualizes "Travel Activity".
3.  **Enhanced Popups:** 30-Day stats embedded.

Output: analytics/dashboard_data/eda/live_tracking_final.html
"""

import sqlite3
import pandas as pd
import folium
from folium.plugins import TimestampedGeoJson
import os
import re
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'analytics/snc_analytics.db'
OUTPUT_DIR = BASE_DIR / 'analytics/dashboard_data/eda'
os.makedirs(OUTPUT_DIR, exist_ok=True)

SIMULATION_DATE = '2025-10-06'

def get_30day_stats(end_date_str):
    conn = sqlite3.connect(DB_PATH)
    query = f"""
    SELECT 
        u.fullname as tech_name,
        COUNT(*) as total_visits_30d,
        AVG(CASE 
            WHEN v.is_complete = 1 
             AND substr(v.check_in_first, 1, 10) = substr(v.visit_date, 1, 10)
             AND strftime('%H', v.check_in_first) < '21' 
            THEN 1 ELSE 0 END) * 100 as on_time_pct,
        AVG(v.duration_min_capped) as avg_duration
    FROM fact_visit_enriched v
    LEFT JOIN dim_user u ON v.user_id = u.user_id
    WHERE v.visit_date BETWEEN date('{end_date_str}', '-30 days') AND '{end_date_str}'
    GROUP BY u.fullname
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df.set_index('tech_name')

def get_tracking_data():
    conn = sqlite3.connect(DB_PATH)
    query = f"""
    SELECT 
        v.visit_id,
        u.fullname as tech_name,
        c.name as client_name,
        v.check_in,
        v.check_out,
        v.latitude,
        v.longitude
    FROM stg_visit v
    LEFT JOIN dim_user u ON v.id_user = u.user_id
    LEFT JOIN dim_customer c ON v.id_customer = c.customer_id
    WHERE v.latitude IS NOT NULL 
      AND v.longitude IS NOT NULL
      AND v.latitude != ''
      AND substr(v.check_in, 1, 10) = '{SIMULATION_DATE}'
    ORDER BY u.fullname, v.check_in
    """
    df = pd.read_sql(query, conn)
    conn.close()
    
    df['check_in_dt'] = pd.to_datetime(df['check_in'], errors='coerce', utc=True)
    df['check_out_dt'] = pd.to_datetime(df['check_out'], errors='coerce', utc=True)
    
    mask_null_out = df['check_out_dt'].isnull()
    df.loc[mask_null_out, 'check_out_dt'] = df.loc[mask_null_out, 'check_in_dt'] + pd.Timedelta(hours=1)
    
    df['lat'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['lng'] = pd.to_numeric(df['longitude'], errors='coerce')
    df = df.dropna(subset=['lat', 'lng', 'check_in_dt'])
    
    return df

def create_slug(name):
    """Create a safe CSS class name from tech name"""
    if not isinstance(name, str): return "tech-unknown"
    return "tech-" + re.sub(r'[^a-zA-Z0-9]', '-', name).lower()

def generate_simulation(df, stats_df):
    if df.empty: return

    # Base Map
    m = folium.Map(location=[-7.2575, 112.7521], zoom_start=12, tiles='CartoDB positron')

    features = []
    unique_techs = sorted(df['tech_name'].unique())
    
    # Process by Technician to draw connecting lines
    for tech in unique_techs:
        tech_df = df[df['tech_name'] == tech].sort_values('check_in_dt')
        tech_slug = create_slug(tech)
        
        # Color from Hash
        colors = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue', 'darkgreen', 'black']
        color = colors[abs(hash(tech)) % len(colors)]
        
        # 1. Generate Visit Points
        for i, row in tech_df.iterrows():
            client = row['client_name']
            
            # Stats
            visits_30d, ontime_30d, dur_30d = 0, 0, 0
            if tech in stats_df.index:
                s = stats_df.loc[tech]
                visits_30d, ontime_30d, dur_30d = int(s['total_visits_30d']), float(s['on_time_pct']), float(s['avg_duration'])

            # Popup
            popup_html = f"""
            <div style="width:220px; font-family:sans-serif;">
                <div style="background-color:{color}; color:white; padding:10px;">
                    <h4 style="margin:0;">{tech}</h4>
                    <small>@ {client}</small>
                </div>
                <div style="padding:10px; border:1px solid #ddd;">
                    <table style="width:100%; font-size:12px;">
                        <tr><td>30d Visits:</td><td align="right"><b>{visits_30d}</b></td></tr>
                        <tr><td>On-Time:</td><td align="right" style="color:{'green' if ontime_30d>90 else 'red'}"><b>{ontime_30d:.1f}%</b></td></tr>
                    </table>
                </div>
            </div>
            """

            start_time = row['check_in_dt'].strftime('%Y-%m-%dT%H:%M:%S')
            end_time = row['check_out_dt'].strftime('%Y-%m-%dT%H:%M:%S')
            
            # Point Feature
            feat = {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [row['lng'], row['lat']]},
                'properties': {
                    'time': start_time,
                    'times': [start_time, end_time],
                    'style': {'className': tech_slug}, # For filtering
                    'icon': 'circle',
                    'icon_style': {
                        'color': color,
                        'fillColor': color,
                        'fillOpacity': 0.8,
                        'radius': 8,
                        'className': tech_slug # For CSS Filtering
                    },
                    'popup': popup_html
                }
            }
            features.append(feat)

        # 2. Generate Connecting Lines (Travel Path)
        # Connect Visit N (Checkout) -> Visit N+1 (Checkin)
        for i in range(len(tech_df) - 1):
            curr = tech_df.iloc[i]
            next_v = tech_df.iloc[i+1]
            
            # Line valid from Current Checkout to Next Checkin (Travel Time)
            t_start = curr['check_out_dt']
            t_end = next_v['check_in_dt']
            
            if t_end > t_start: # Valid interval
                line_feat = {
                    'type': 'Feature',
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': [
                            [curr['lng'], curr['lat']],
                            [next_v['lng'], next_v['lat']]
                        ]
                    },
                    'properties': {
                        'time': t_start.strftime('%Y-%m-%dT%H:%M:%S'),
                        'times': [t_start.strftime('%Y-%m-%dT%H:%M:%S'), t_end.strftime('%Y-%m-%dT%H:%M:%S')],
                        'style': {
                            'color': color,
                            'weight': 3,
                            'opacity': 0.6,
                            'className': tech_slug # For CSS Filtering
                        }
                    }
                }
                features.append(line_feat)

    # Add TimeDimension Layer
    TimestampedGeoJson(
        {'type': 'FeatureCollection', 'features': features},
        period='PT5M',
        add_last_point=False,
        max_speed=20,
        loop_button=True,
        date_options='YYYY-MM-DD HH:mm',
        duration='P1D'
    ).add_to(m)

    # --- INJECT CUSTOM SEARCH CONTROL ---
    
    # 1. Build Dropdown Options
    options_html = '<option value="all">Show All Technicians</option>'
    for tech in unique_techs:
        slug = create_slug(tech)
        options_html += f'<option value="{slug}">{tech}</option>'

    # 2. Custom CSS & JS for Filtering
    custom_ui = f"""
    <div id="search-control" style="
        position: fixed; 
        top: 20px; left: 60px; 
        z-index: 9999; 
        background: white; 
        padding: 10px; 
        border-radius: 8px; 
        box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        font-family: sans-serif;
    ">
        <label for="tech-select" style="display:block; font-size:12px; font-weight:bold; margin-bottom:5px; color:#555;">Filter Technician:</label>
        <select id="tech-select" style="padding:5px; width:200px; border:1px solid #ccc; border-radius:4px;">
            {options_html}
        </select>
    </div>

    <!-- Dynamic Style Tag for Filtering -->
    <style id="tech-filter-style"></style>

    <script>
        document.getElementById('tech-select').addEventListener('change', function(e) {{
            var selectedSlug = e.target.value;
            var styleTag = document.getElementById('tech-filter-style');
            
            if (selectedSlug === 'all') {{
                // Reset Grid
                styleTag.innerHTML = ''; 
            }} else {{
                // Hide everyone else
                // We use opacity: 0.05 for others to create "ghost" effect, or display:none
                // Leaflet markers are usually images or divs.
                // SVG Paths (lines) use 'stroke' classes.
                
                var css = `
                    /* Dim everything by default */
                    .leaflet-interactive {{ opacity: 0.1 !important; stroke-opacity: 0.1 !important; fill-opacity: 0.1 !important; pointer-events: none; }}
                    .leaflet-marker-icon {{ opacity: 0.1 !important; }}
                    
                    /* Highlight Selected */
                    path.${{selectedSlug}}, circle.${{selectedSlug}} {{ 
                        opacity: 1 !important; 
                        stroke-opacity: 1 !important; 
                        fill-opacity: 0.8 !important; 
                        stroke-width: 4px !important;
                        pointer-events: auto !important;
                    }}
                    .leaflet-marker-icon.${{selectedSlug}} {{ 
                        opacity: 1 !important; 
                        z-index: 9999 !important;
                        transform: scale(1.2);
                        pointer-events: auto !important;
                    }}
                `;
                styleTag.innerHTML = css;
            }}
        }});
    </script>
    """
    
    m.get_root().html.add_child(folium.Element(custom_ui))

    outfile = OUTPUT_DIR / 'live_tracking_final.html'
    m.save(outfile)
    print(f"Simulation generated: {outfile}")

def main():
    print("Generating Final Live Tracking (V3)...")
    stats_df = get_30day_stats(SIMULATION_DATE)
    df = get_tracking_data()
    generate_simulation(df, stats_df)
    print("Done.")

if __name__ == '__main__':
    main()
