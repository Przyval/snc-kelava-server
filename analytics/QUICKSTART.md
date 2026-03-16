# SanoCare KPI System - Quick Start Guide

## 1. Running the KPI Pipeline (Backend)
This Python pipeline extracts data, scores technicians, runs acceptance tests, and generates the dashboard JSONs.

**Prerequisites:**
- Python 3.9+
- Verified `kpi_config.yaml`
- SSH Tunnel active (if fetching fresh data)

**Run Full Pipeline:**
```bash
# From the root project directory
python3 run_kpi_pipeline.py
```

**Run Specific Steps:**
```bash
# Only generate Dashboard JSONs (skip ETL/Scoring)
python3 run_kpi_pipeline.py --step 7

# Dry run (verify without writing)
python3 run_kpi_pipeline.py --dry-run
```

**Output:**
- Artifacts: `runs/YYYY-MM-DDTHHMMZ/`
- Dashboard Data: `analytics/dashboard/public/data/` (Automatically updated)

---

## 2. Running the Dashboard (Frontend)
The professional React dashboard that visualizes the pipeline output.

**Prerequisites:**
- Node.js & npm

**Option A: Development Mode (Hot Reload)**
Best for viewing immediately or making UI changes.
```bash
cd analytics/dashboard
npm run dev
# Open http://localhost:5173
```

**Option B: Production Mode (Build & Preview)**
Simulates the real deployed environment.
```bash
cd analytics/dashboard
npm run build
npm run preview
# Open http://localhost:4173
```

---

## 3. "Closed Loop" Operational Flow

1.  **Daily 18:30**: `kpi_cron.sh` runs the pipeline.
2.  **Pipeline**: Scores data → Passes Iron Gate → Updates `dashboard/public/data/*.json`.
3.  **Dashboard**: Automatically reflects new data relative to the JSON files.
4.  **Users**: CEO/Ops/HR view the updated dashboard URL.
