#!/usr/bin/env python3
"""
Smoke Test Suite for KIL Enterprise API
=========================================
Tests all critical endpoints. Run after every deploy.

Usage:
    python3 kil/backend/scripts/smoke_test.py [--base-url URL]
"""

import sys
import json
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "kil" / "backend"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def run_smoke_tests(base_url=None):
    """Run all smoke tests."""
    if base_url:
        return _test_remote(base_url)
    else:
        return _test_local()


def _test_remote(base_url):
    """Run tests against a live HTTP server using requests."""
    try:
        import requests
    except ImportError:
        print("ERROR: 'requests' package not installed. Run: pip install requests")
        return 1

    base_url = base_url.rstrip("/")
    results = []

    def req(method, path, **kwargs):
        return requests.request(method, base_url + path, timeout=15, **kwargs)

    # Health (no auth)
    _test_http(results, "health", lambda: req("GET", "/health"), 200)

    # Login
    login_r = req("POST", "/api/v1/auth/login", json={
        "email": "admin@sanocare.work",
        "password": "SanoCare2026!",
    })
    _test_http(results, "login", lambda: login_r, 200)

    token = ""
    if login_r.status_code == 200:
        token = login_r.json().get("access_token", "")
    h = {"Authorization": f"Bearer {token}"}

    # Core endpoints
    endpoints = [
        ("dashboard-stats", "GET", "/api/v1/enterprise/dashboard-stats"),
        ("executive", "GET", "/api/v1/enterprise/executive/kpis"),
        ("operations", "GET", "/api/v1/enterprise/operations/workload"),
        ("technicians", "GET", "/api/v1/enterprise/technicians/leaderboard"),
        ("customers", "GET", "/api/v1/enterprise/customers"),
        ("health-status", "GET", "/api/v1/enterprise/health/status"),
        ("health-ping", "GET", "/api/v1/enterprise/health/ping"),
        ("gps-positions", "GET", "/api/v1/enterprise/gps-live/positions"),
        ("auth-reject", "GET", "/api/v1/enterprise/dashboard-stats"),  # no token → 401
    ]
    for name, method, path in endpoints[:-1]:
        _test_http(results, name, lambda m=method, p=path: req(m, p, headers=h), 200)
    # Rejected request
    _test_http(results, "auth-reject", lambda: req("GET", "/api/v1/enterprise/dashboard-stats"), 401)

    return _report(results)


def _test_http(results, name, fn, expected_status):
    """Run a single remote test."""
    try:
        r = fn()
        passed = r.status_code == expected_status
        results.append({"name": name, "passed": passed, "status": r.status_code, "expected": expected_status})
        icon = "PASS" if passed else "FAIL"
        print(f"  [{icon}] {name}: {r.status_code} (expected {expected_status})")
    except Exception as e:
        results.append({"name": name, "passed": False, "error": str(e)})
        print(f"  [FAIL] {name}: {e}")


def _test_local():
    """Run tests against Flask test client."""
    from kil.backend.legacy.app import app

    results = []
    with app.test_client() as c:
        # Health check (no auth)
        _test(results, "health", lambda: c.get("/health"), 200)

        # Login
        login_r = c.post("/api/v1/auth/login", json={
            "email": "admin@sanocare.work",
            "password": "SanoCare2026!",
        })
        _test(results, "login", lambda: login_r, 200)

        token = json.loads(login_r.data).get("access_token", "")
        h = {"Authorization": f"Bearer {token}"}

        # API Docs
        _test(results, "api-docs", lambda: c.get("/api/v1/docs", headers=h), 200)

        # Dashboard stats
        _test(results, "dashboard-stats", lambda: c.get("/api/v1/enterprise/dashboard-stats", headers=h), 200)

        # Executive KPIs
        _test(results, "executive", lambda: c.get("/api/v1/enterprise/executive/kpis", headers=h), 200)

        # Operations workload
        _test(results, "operations", lambda: c.get("/api/v1/enterprise/operations/workload", headers=h), 200)

        # Technicians leaderboard
        _test(results, "technicians", lambda: c.get("/api/v1/enterprise/technicians/leaderboard", headers=h), 200)

        # Customers
        _test(results, "customers", lambda: c.get("/api/v1/enterprise/customers", headers=h), 200)

        # Calendar schedule
        _test(results, "calendar", lambda: c.get("/api/v1/enterprise/calendar/schedule?start=2026-03-01&end=2026-03-31", headers=h), 200)

        # Contracts
        _test(results, "contracts", lambda: c.get("/api/v1/enterprise/contracts", headers=h), 200)

        # Trends
        _test(results, "trends-weekly", lambda: c.get("/api/v1/enterprise/trends/weekly?weeks=4", headers=h), 200)

        # Export listing
        _test(results, "export-list", lambda: c.get("/api/v1/enterprise/export", headers=h), 200)

        # Notifications summary
        _test(results, "notif-summary", lambda: c.get("/api/v1/enterprise/notifications/summary", headers=h), 200)

        # Daily digest preview
        _test(results, "digest-preview", lambda: c.get("/api/v1/enterprise/daily-digest/preview", headers=h), 200)

        # Weekly report history
        _test(results, "weekly-history", lambda: c.get("/api/v1/enterprise/weekly-report/history", headers=h), 200)

        # GPS live positions
        _test(results, "gps-positions", lambda: c.get("/api/v1/enterprise/gps-live/positions", headers=h), 200)

        # Completion gate stats
        _test(results, "completion-gate", lambda: c.get("/api/v1/enterprise/completion-gate/stats", headers=h), 200)

        # Complaints
        _test(results, "complaints", lambda: c.get("/api/v1/enterprise/complaints", headers=h), 200)

        # Punctuality daily
        _test(results, "punctuality", lambda: c.get("/api/v1/enterprise/punctuality/daily?date=2026-03-10", headers=h), 200)

        # Segments
        _test(results, "segments", lambda: c.get("/api/v1/enterprise/segments", headers=h), 200)

        # Scheduling
        _test(results, "scheduling", lambda: c.get("/api/v1/enterprise/scheduling/board?start=2026-03-10&end=2026-03-16", headers=h), 200)

        # Health monitor
        _test(results, "health-monitor", lambda: c.get("/api/v1/enterprise/health/status", headers=h), 200)

        # Auth - invalid token
        _test(results, "auth-reject", lambda: c.get("/api/v1/enterprise/dashboard-stats", headers={"Authorization": "Bearer invalid"}), 401)

        # Mobile dashboard
        _test(results, "mobile-dashboard", lambda: c.get("/api/v1/mobile/dashboard", headers=h), 200)

        # ── Phase 2 Features (2026-03-11) ──────────────────

        # Breadcrumb GPS - live positions
        _test(results, "breadcrumb-live", lambda: c.get("/api/v1/mobile/breadcrumb/live", headers=h), 200)

        # GPS Drift Detection - configs
        _test(results, "drift-configs", lambda: c.get("/api/v1/enterprise/drift/config", headers=h), 200)

        # GPS Drift Detection - alerts
        _test(results, "drift-alerts", lambda: c.get("/api/v1/enterprise/drift/alerts", headers=h), 200)

        # GPS Drift Detection - scores
        _test(results, "drift-scores", lambda: c.get("/api/v1/enterprise/drift/scores", headers=h), 200)

        # Face Attendance - today board
        _test(results, "face-attendance", lambda: c.get("/api/v1/mobile/face-attendance/today", headers=h), 200)

        # Barcode Checklist - units (needs customer_id param)
        _test(results, "barcode-units", lambda: c.get("/api/v1/enterprise/barcode/units?customer_id=1", headers=h), 200)

        # Schedule Generator - gaps
        _test(results, "schedule-gaps", lambda: c.get("/api/v1/enterprise/schedule-gen/gaps", headers=h), 200)

        # Chemical Tracking - catalog
        _test(results, "chemical-catalog", lambda: c.get("/api/v1/enterprise/chemicals/catalog", headers=h), 200)

        # Chemical Tracking - usage summary
        _test(results, "chemical-summary", lambda: c.get("/api/v1/enterprise/chemicals/summary", headers=h), 200)

        # Daily KPI Rapor - leaderboard
        _test(results, "rapor-leaderboard", lambda: c.get("/api/v1/enterprise/rapor/leaderboard", headers=h), 200)

        # Service Form - list
        _test(results, "service-forms", lambda: c.get("/api/v1/enterprise/service-form", headers=h), 200)

        # Client Portal - token list
        _test(results, "portal-tokens", lambda: c.get("/api/v1/enterprise/client-portal/tokens", headers=h), 200)

    return _report(results)


def _test(results, name, fn, expected_status):
    """Run a single test."""
    try:
        r = fn()
        status = r.status_code
        passed = status == expected_status
        results.append({
            "name": name,
            "passed": passed,
            "status": status,
            "expected": expected_status,
        })
        icon = "PASS" if passed else "FAIL"
        print(f"  [{icon}] {name}: {status} (expected {expected_status})")
    except Exception as e:
        results.append({"name": name, "passed": False, "error": str(e)})
        print(f"  [FAIL] {name}: {e}")


def _report(results):
    """Print summary."""
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    failed = total - passed

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} PASS, {failed} FAIL")

    if failed:
        print("\nFailed tests:")
        for r in results:
            if not r["passed"]:
                print(f"  - {r['name']}: got {r.get('status', 'ERROR')} (expected {r.get('expected', '?')})")

    print(f"{'='*50}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", help="Remote base URL to test against")
    args = parser.parse_args()

    sys.exit(run_smoke_tests(args.base_url))
