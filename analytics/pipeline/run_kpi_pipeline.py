#!/usr/bin/env python3
"""
SanoCare KPI Agent - Master Runner
===================================
Executes Steps 0-5 sequentially with quality gates.
Step 3.2 (Acceptance Tests) is the iron gate: fail = stop.

Usage:
  python3 run_kpi_pipeline.py                    # Full run
  python3 run_kpi_pipeline.py --step 4           # Start from Step 4
  python3 run_kpi_pipeline.py --dry-run          # Validate only, no writes

Output:
  runs/{run_id}/...  # All artifacts versioned by run
"""

import os
import sys
import json
import sqlite3
import csv
import yaml
import shutil
import argparse
from datetime import datetime
from pathlib import Path

# ============================================================
# Configuration
# ============================================================
BASE_DIR = Path(__file__).parent
ANALYTICS_DIR = BASE_DIR / 'analytics'
CONFIG_PATH = ANALYTICS_DIR / 'kpi_config.yaml'
DB_PATH = ANALYTICS_DIR / 'snc_analytics.db'

# ============================================================
# Utilities
# ============================================================
def log(msg, level='INFO'):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] [{level}] {msg}")

def create_run_folder():
    """Create versioned run folder"""
    run_id = datetime.now().strftime('%Y-%m-%dT%H%M%SZ')
    run_dir = BASE_DIR / 'runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def save_run_metadata(run_dir, run_id, config):
    """Save run metadata for reproducibility"""
    metadata = {
        'run_id': run_id,
        'timestamp': datetime.now().isoformat(),
        'config_path': str(CONFIG_PATH),
        'db_path': str(DB_PATH),
        'python_version': sys.version,
        'acceptance_tests': config.get('acceptance_tests', {})
    }
    with open(run_dir / 'run_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    return metadata

def fail_run(run_dir, reason):
    """Mark run as failed and stop"""
    with open(run_dir / 'FAILURE_NOTES.md', 'w') as f:
        f.write(f"# Run Failed\n\n")
        f.write(f"**Timestamp:** {datetime.now().isoformat()}\n")
        f.write(f"**Reason:** {reason}\n")
    log(f"RUN FAILED: {reason}", 'ERROR')
    sys.exit(1)

# ============================================================
# Step 0: Preflight & Safety
# ============================================================
def step_0_preflight(run_dir, config):
    log("=" * 60)
    log("STEP 0: Preflight & Safety")
    log("=" * 60)
    
    checks = []
    
    # Check 1: Config exists
    if CONFIG_PATH.exists():
        checks.append(('Config file exists', 'PASS', str(CONFIG_PATH)))
    else:
        checks.append(('Config file exists', 'FAIL', 'Not found'))
        fail_run(run_dir, "Config file not found")
    
    # Check 2: Database exists
    if DB_PATH.exists():
        db_size = DB_PATH.stat().st_size / (1024*1024)
        checks.append(('Database exists', 'PASS', f'{db_size:.1f} MB'))
    else:
        checks.append(('Database exists', 'FAIL', 'Not found'))
        fail_run(run_dir, "Database not found - run step2_etl.py first")
    
    # Check 3: Database connectivity
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row_count = conn.execute("SELECT COUNT(*) FROM fact_visit_enriched").fetchone()[0]
        checks.append(('Database queryable', 'PASS', f'{row_count:,} rows'))
        conn.close()
    except Exception as e:
        checks.append(('Database queryable', 'FAIL', str(e)))
        fail_run(run_dir, f"Database error: {e}")
    
    # Check 4: Timezone in config
    tz = config.get('general', {}).get('timezone', 'NOT SET')
    if tz == 'Asia/Jakarta':
        checks.append(('Timezone', 'PASS', tz))
    else:
        checks.append(('Timezone', 'WARN', f'Expected Asia/Jakarta, got {tz}'))
    
    # Write preflight report
    report = ["# Preflight Checklist\n"]
    report.append(f"> **Run ID:** {run_dir.name}")
    report.append(f"> **Timestamp:** {datetime.now().isoformat()}\n")
    report.append("| Check | Status | Details |")
    report.append("|-------|--------|---------|")
    for check, status, details in checks:
        emoji = "✅" if status == 'PASS' else "⚠️" if status == 'WARN' else "❌"
        report.append(f"| {check} | {emoji} {status} | {details} |")
    
    with open(run_dir / 'PREFLIGHT_CHECKLIST.md', 'w') as f:
        f.write('\n'.join(report))
    
    log("  -> Preflight complete")
    return True

# ============================================================
# Step 1: KPI Contract Lock
# ============================================================
def step_1_contract(run_dir, config):
    log("=" * 60)
    log("STEP 1: KPI Contract Lock")
    log("=" * 60)
    
    # Copy config to run folder
    shutil.copy(CONFIG_PATH, run_dir / 'kpi_config.yaml')
    
    # Copy contract if exists
    contract_path = ANALYTICS_DIR / 'reports' / 'KPI_CONTRACT.md'
    if contract_path.exists():
        shutil.copy(contract_path, run_dir / 'KPI_CONTRACT.md')
    
    log("  -> Contract locked")
    return True

# ============================================================
# Step 2 & 2.1: Already done by step2_etl.py / step2_1_hotfix.py
# ============================================================
def step_2_verify_staging(run_dir, config):
    log("=" * 60)
    log("STEP 2: Verify Staging Data")
    log("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    expected = config.get('acceptance_tests', {})
    
    # Verify key counts
    road_plans = conn.execute("SELECT COUNT(*) FROM fact_visit_enriched").fetchone()[0]
    expected_rp = expected.get('total_road_plans', 33727)
    
    if road_plans != expected_rp:
        log(f"  WARNING: road_plans={road_plans}, expected={expected_rp}", 'WARN')
    else:
        log(f"  ✓ road_plans={road_plans}")
    
    conn.close()
    log("  -> Staging verified")
    return True

# ============================================================
# Step 3: KPI Engine (uses existing scoring tables)
# ============================================================
def step_3_scoring(run_dir, config):
    log("=" * 60)
    log("STEP 3: KPI Scoring")
    log("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Export leaderboards to run folder
    for mode in ['fair', 'strict']:
        table = f'leaderboard_{mode}_clean'
        try:
            results = conn.execute(f"SELECT * FROM {table}").fetchall()
            columns = [desc[0] for desc in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
            
            csv_path = run_dir / f'leaderboard_{mode}_clean.csv'
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                writer.writerows(results)
            
            log(f"  -> Exported {table}: {len(results)} rows")
        except Exception as e:
            log(f"  WARNING: Could not export {table}: {e}", 'WARN')
    
    conn.close()
    return True

# ============================================================
# Step 3.2: Acceptance Tests (IRON GATE)
# ============================================================
def step_3_2_acceptance(run_dir, config):
    log("=" * 60)
    log("STEP 3.2: ACCEPTANCE TESTS (IRON GATE)")
    log("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    expected = config.get('acceptance_tests', {})
    
    tests = [
        ("total_road_plans", "SELECT COUNT(*) FROM fact_visit_enriched", expected.get('total_road_plans', 33727)),
        ("completed_visits", "SELECT SUM(is_complete) FROM fact_visit_enriched", expected.get('completed_visits', 33510)),
        ("null_checkout", "SELECT SUM(has_null_checkout_strict) FROM dq_flags", expected.get('null_checkout', 217)),
        ("null_checkin", "SELECT SUM(CASE WHEN check_in_first IS NULL OR check_in_first = '' THEN 1 ELSE 0 END) FROM fact_visit_enriched", expected.get('null_checkin', 7)),
        ("no_photo_raw", "SELECT COUNT(*) FROM fact_visit_enriched WHERE foto_count = 0", expected.get('no_photo', 5452)),
        ("multiday_suspect", "SELECT COUNT(*) FROM dq_flags WHERE duration_status_v2 = 'MULTI_DAY_SUSPECT'", expected.get('multiday_suspect', 3431)),
        ("suspect_time", "SELECT SUM(is_suspect_time) FROM dq_flags", expected.get('suspect_time', 5711)),
    ]
    
    # Score sanity tests
    score_tests = [
        ("score_over_100_fair", "SELECT COUNT(*) FROM kpi_score_fair_clean WHERE total_score > 100", 0),
        ("score_over_100_strict", "SELECT COUNT(*) FROM kpi_score_strict_clean WHERE total_score > 100", 0),
        ("null_grade_fair", "SELECT COUNT(*) FROM kpi_score_fair_clean WHERE grade IS NULL", 0),
        ("null_grade_strict", "SELECT COUNT(*) FROM kpi_score_strict_clean WHERE grade IS NULL", 0),
    ]
    
    all_tests = tests + score_tests
    results = []
    all_passed = True
    
    for name, sql, expected_val in all_tests:
        try:
            actual = conn.execute(sql).fetchone()[0] or 0
            passed = actual == expected_val
            if not passed:
                all_passed = False
            results.append({
                'name': name,
                'expected': expected_val,
                'actual': actual,
                'passed': passed
            })
            status = "✓ PASS" if passed else "✗ FAIL"
            log(f"  {status}: {name} = {actual} (expected {expected_val})")
        except Exception as e:
            results.append({
                'name': name,
                'expected': expected_val,
                'actual': f'ERROR: {e}',
                'passed': False
            })
            all_passed = False
            log(f"  ✗ ERROR: {name} - {e}", 'ERROR')
    
    conn.close()
    
    # Write report
    report = ["# Acceptance Test Report\n"]
    report.append(f"> **Run ID:** {run_dir.name}")
    report.append(f"> **Status:** {'✅ ALL PASSED' if all_passed else '❌ FAILED'}\n")
    report.append("| Test | Expected | Actual | Status |")
    report.append("|------|----------|--------|--------|")
    for r in results:
        emoji = "✅" if r['passed'] else "❌"
        report.append(f"| {r['name']} | {r['expected']} | {r['actual']} | {emoji} |")
    
    with open(run_dir / 'acceptance_test_report.md', 'w') as f:
        f.write('\n'.join(report))
    
    if not all_passed:
        fail_run(run_dir, "Acceptance tests failed - see acceptance_test_report.md")
    
    log("  -> ALL ACCEPTANCE TESTS PASSED ✓")
    return True

# ============================================================
# Step 4: Insight Pack
# ============================================================
def step_4_insights(run_dir, config):
    log("=" * 60)
    log("STEP 4: Insight Pack")
    log("=" * 60)
    
    # Copy insight pack if exists
    insight_src = ANALYTICS_DIR / 'reports' / 'insight_pack_2026-01.md'
    if insight_src.exists():
        shutil.copy(insight_src, run_dir / 'insight_pack.md')
    
    # Copy insights folder
    insights_src = ANALYTICS_DIR / 'insights'
    insights_dst = run_dir / 'insights'
    if insights_src.exists():
        shutil.copytree(insights_src, insights_dst, dirs_exist_ok=True)
    
    log("  -> Insights exported")
    return True

# ============================================================
# Step 5: Action Plan
# ============================================================
def step_5_action_plan(run_dir, config):
    log("=" * 60)
    log("STEP 5: Action Plan")
    log("=" * 60)
    
    # Copy action plan files
    for filename in ['ops_action_plan_q1_2026.md', 'app_change_requests.md']:
        src = ANALYTICS_DIR / 'reports' / filename
        if src.exists():
            shutil.copy(src, run_dir / filename)
    
    log("  -> Action plan exported")
    return True

# ============================================================
# Step 7: Dashboard Data
# ============================================================
def step_7_dashboard_data(run_dir, config):
    log("=" * 60)
    log("STEP 7: Dashboard Data Generation")
    log("=" * 60)
    
    # Run the generation script
    # For now, we import the main function from step7 or just run it via subprocess to be safe/lazy
    # Importing is better validation
    try:
        import step7_dashboard_json
        step7_dashboard_json.main()
        
        # Copy the dashboard_data folder to the run folder for versioning
        src_dir = ANALYTICS_DIR / 'dashboard_data'
        dst_dir = run_dir / 'dashboard_data'
        if src_dir.exists():
            shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
            log(f"  -> Dashboard artifacts versioned to {dst_dir}")
            
    except Exception as e:
        log(f"  ERROR generating dashboard data: {e}", 'ERROR')
        raise e

    return True

# ============================================================
# Main Runner
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='SanoCare KPI Pipeline Runner')
    parser.add_argument('--step', type=int, default=0, help='Start from step N')
    parser.add_argument('--dry-run', action='store_true', help='Validate only')
    args = parser.parse_args()
    
    log("=" * 60)
    log("SANOCARE KPI PIPELINE - MASTER RUNNER")
    log("=" * 60)
    
    # Create run folder
    run_id, run_dir = create_run_folder()
    log(f"Run ID: {run_id}")
    log(f"Output: {run_dir}")
    
    # Load config
    config = load_config()
    save_run_metadata(run_dir, run_id, config)
    
    # Execute steps
    steps = [
        (0, "Preflight", step_0_preflight),
        (1, "Contract Lock", step_1_contract),
        (2, "Verify Staging", step_2_verify_staging),
        (3, "KPI Scoring", step_3_scoring),
        (3.2, "Acceptance Tests", step_3_2_acceptance),
        (4, "Insight Pack", step_4_insights),
        (5, "Action Plan", step_5_action_plan),
        (7, "Dashboard Data", step_7_dashboard_data),
    ]

    
    for step_num, step_name, step_func in steps:
        if step_num < args.step:
            log(f"Skipping Step {step_num}: {step_name}")
            continue
        
        if args.dry_run:
            log(f"[DRY RUN] Would execute Step {step_num}: {step_name}")
            continue
        
        try:
            step_func(run_dir, config)
        except Exception as e:
            fail_run(run_dir, f"Step {step_num} ({step_name}) failed: {e}")
    
    # Success
    log("")
    log("=" * 60)
    log("PIPELINE COMPLETE ✓")
    log("=" * 60)
    log(f"Output: {run_dir}")
    
    # Write final summary
    summary = [
        "# Run Summary\n",
        f"**Run ID:** {run_id}",
        f"**Status:** ✅ SUCCESS",
        f"**Timestamp:** {datetime.now().isoformat()}\n",
        "## Outputs",
        "- `PREFLIGHT_CHECKLIST.md`",
        "- `kpi_config.yaml`",
        "- `KPI_CONTRACT.md`",
        "- `leaderboard_fair_clean.csv`",
        "- `leaderboard_strict_clean.csv`",
        "- `acceptance_test_report.md`",
        "- `insight_pack.md`",
        "- `insights/*.csv`",
        "- `ops_action_plan_q1_2026.md`",
        "- `app_change_requests.md`",
    ]
    
    with open(run_dir / 'RUN_SUMMARY.md', 'w') as f:
        f.write('\n'.join(summary))

if __name__ == '__main__':
    main()
