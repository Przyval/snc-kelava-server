#!/usr/bin/env python3
"""
KIL Backend API Server
======================
Flask application for KIL operational intelligence API.
"""

import logging
import os
import sys
from pathlib import Path

# Add project root to path (for kil.* imports)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
# Add kil/backend/ to path (for core.security imports used by API modules)
sys.path.insert(0, str(PROJECT_ROOT / "kil" / "backend"))

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv(PROJECT_ROOT / ".env")

# Structured logging — visible in journalctl and cron.log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

from kil.backend.legacy.api.calendar import calendar_bp
from kil.backend.legacy.api.completion_gate import completion_gate_bp
from kil.backend.legacy.api.customers import customers_bp
from kil.backend.legacy.api.executive import executive_bp
from kil.backend.legacy.api.operations_kelava import operations_bp
from kil.backend.legacy.api.ops import ops_bp
from kil.backend.legacy.api.technicians import technicians_bp
from kil.backend.legacy.web import web_bp
from kil.backend.legacy.web.enterprise import enterprise_bp
from kil.db.connection import init_db

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload


# ── Security: CORS & Headers ──────────────────────────────
@app.after_request
def security_headers(response):
    origin = request.headers.get("Origin", "")
    allowed_origins = {
        "https://safencare.work",
        "http://localhost:5173",
        "http://localhost:5001",
    }
    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        from flask import make_response
        resp = make_response()
        return resp

# Register blueprints
# Original KIL API
app.register_blueprint(ops_bp, url_prefix="/api/v1")
app.register_blueprint(web_bp, url_prefix="/")

# Enterprise API (Kelava live data)
app.register_blueprint(executive_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(operations_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(technicians_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(customers_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(calendar_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(completion_gate_bp, url_prefix="/api/v1/enterprise")

# Exception Queue
from kil.backend.legacy.api.exceptions import exceptions_bp
from kil.backend.legacy.api.invoice_lock import invoice_lock_bp
from kil.backend.legacy.api.technician_issues import bp as technician_issues_bp

app.register_blueprint(exceptions_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(invoice_lock_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(technician_issues_bp)

from kil.backend.legacy.api.governance import governance_bp
from kil.backend.legacy.api.winback import winback_bp
from kil.backend.legacy.api.contracts import contracts_bp
from kil.backend.legacy.api.audit_trail import audit_bp

app.register_blueprint(governance_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(winback_bp, url_prefix="/api/v1/enterprise/winback")
app.register_blueprint(contracts_bp, url_prefix="/api/v1/enterprise/contracts")
app.register_blueprint(audit_bp, url_prefix="/api/v1/enterprise/audit")


from kil.backend.legacy.api.tracking import tracking_bp
from kil.backend.legacy.api.auth import auth_api_bp
from kil.backend.legacy.api.user_management import user_mgmt_bp
from kil.backend.legacy.api.verification import verification_bp

app.register_blueprint(tracking_bp, url_prefix="/api/v1/enterprise")
app.register_blueprint(auth_api_bp, url_prefix="/api/v1/auth")
app.register_blueprint(user_mgmt_bp, url_prefix="/api/v1/enterprise/users")
app.register_blueprint(verification_bp, url_prefix="/api/v1/enterprise/verification")

# Meeting Features (2026-02-19): Segments, Punctuality, Scheduling, Supervisory, Complaints
from kil.backend.legacy.api.segments import segments_bp
from kil.backend.legacy.api.punctuality import punctuality_bp
from kil.backend.legacy.api.scheduling import scheduling_bp
from kil.backend.legacy.api.supervisory import supervisory_bp
from kil.backend.legacy.api.complaints import complaints_bp

app.register_blueprint(segments_bp, url_prefix="/api/v1/enterprise/segments")
app.register_blueprint(punctuality_bp, url_prefix="/api/v1/enterprise/punctuality")
app.register_blueprint(scheduling_bp, url_prefix="/api/v1/enterprise/scheduling")
app.register_blueprint(supervisory_bp, url_prefix="/api/v1/enterprise/supervisory")
app.register_blueprint(complaints_bp, url_prefix="/api/v1/enterprise/complaints")

# Staff Photos
from kil.backend.legacy.api.staff_photos import staff_photos_bp
app.register_blueprint(staff_photos_bp, url_prefix="/api/v1/enterprise")

# Daily Briefing
from kil.backend.legacy.api.briefing import briefing_bp
app.register_blueprint(briefing_bp, url_prefix="/api/v1/enterprise/briefing")

# Sales Pipeline CRM
from kil.backend.legacy.api.pipeline import pipeline_bp
app.register_blueprint(pipeline_bp, url_prefix="/api/v1/enterprise")

# MOM (Minutes of Meeting)
from kil.backend.legacy.api.mom import mom_bp
app.register_blueprint(mom_bp, url_prefix="/api/v1/enterprise/mom")

# Fingerprint Attendance
from kil.backend.legacy.api.attendance import attendance_bp
app.register_blueprint(attendance_bp, url_prefix="/api/v1/enterprise")

# Schedule Templates
from kil.backend.legacy.api.schedule_templates import schedule_tpl_bp
app.register_blueprint(schedule_tpl_bp, url_prefix="/api/v1/enterprise/schedule-templates")

# Customer Satisfaction Score (CSAT)
from kil.backend.legacy.api.csat import csat_bp
app.register_blueprint(csat_bp, url_prefix="/api/v1/enterprise/csat")

# GPS Live Map
from kil.backend.legacy.api.gps_live import gps_live_bp
app.register_blueprint(gps_live_bp, url_prefix="/api/v1/enterprise/gps-live")

# WhatsApp Bot Gateway
from kil.backend.legacy.api.wa_bot import wa_bot_bp
app.register_blueprint(wa_bot_bp, url_prefix="/api/v1/enterprise/wa-bot")

# Weekly Report
from kil.backend.legacy.api.weekly_report import weekly_report_bp
app.register_blueprint(weekly_report_bp, url_prefix="/api/v1/enterprise/weekly-report")

# Health Check & Monitoring
from kil.backend.legacy.api.health import health_bp
app.register_blueprint(health_bp, url_prefix="/api/v1/enterprise/health")

# Universal Audit Log
from kil.backend.legacy.api.audit_log import audit_log_bp
app.register_blueprint(audit_log_bp, url_prefix="/api/v1/enterprise/audit-log")

# Export System (CSV downloads)
from kil.backend.legacy.api.export import export_bp
app.register_blueprint(export_bp, url_prefix="/api/v1/enterprise/export")

# Performance Trends
from kil.backend.legacy.api.trends import trends_bp
app.register_blueprint(trends_bp, url_prefix="/api/v1/enterprise/trends")

# Notification Center
from kil.backend.legacy.api.notifications import notif_bp
app.register_blueprint(notif_bp, url_prefix="/api/v1/enterprise/notifications")

# Daily Digest
from kil.backend.legacy.api.daily_digest import daily_digest_bp
app.register_blueprint(daily_digest_bp, url_prefix="/api/v1/enterprise/daily-digest")

# Dashboard Stats Widget
from kil.backend.legacy.api.dashboard_stats import dashboard_stats_bp
app.register_blueprint(dashboard_stats_bp, url_prefix="/api/v1/enterprise/dashboard-stats")

# Mobile API (SNC Flutter App)
from kil.backend.legacy.api.mobile import mobile_bp
app.register_blueprint(mobile_bp)

# API Documentation
from kil.backend.legacy.api.api_docs import api_docs_bp
app.register_blueprint(api_docs_bp)  # routes defined in module: /api/v1/openapi.json, /api/v1/docs

# ── Meeting Features Phase 2 (2026-03-11) ─────────────────────

# Breadcrumb GPS Tracking (high-frequency trail)
from kil.backend.legacy.api.breadcrumb import breadcrumb_bp
app.register_blueprint(breadcrumb_bp, url_prefix="/api/v1/mobile/breadcrumb")

# GPS Drift Detection & Auto-Sidak
from kil.backend.legacy.api.drift_detection import drift_bp
app.register_blueprint(drift_bp, url_prefix="/api/v1/enterprise/drift")

# Face Verification Attendance
from kil.backend.legacy.api.face_attendance import face_attendance_bp
app.register_blueprint(face_attendance_bp, url_prefix="/api/v1/mobile/face-attendance")

# QR/Barcode Unit Checklist
from kil.backend.legacy.api.barcode_checklist import barcode_bp
app.register_blueprint(barcode_bp, url_prefix="/api/v1/enterprise/barcode")

# Schedule Auto-Generator + Drag-and-Drop
from kil.backend.legacy.api.schedule_generator import schedule_gen_bp
app.register_blueprint(schedule_gen_bp, url_prefix="/api/v1/enterprise/schedule-gen")

# Auto-Draft Schedule Generator
from kil.backend.legacy.api.schedule_draft import draft_bp
app.register_blueprint(draft_bp)

# Manual Recurring Rules (Phase 1)
from kil.backend.legacy.api.recurring_rules import recurring_rules_bp
app.register_blueprint(recurring_rules_bp)

# Lokasi Master (snc_clients CRUD)
from kil.backend.legacy.api.snc_lokasi import snc_lokasi_bp
app.register_blueprint(snc_lokasi_bp)

# Lokasi Libur Sementara (customer suppression)
from kil.backend.legacy.api.client_suppression import libur_bp
app.register_blueprint(libur_bp)

# Teknisi Tidak Masuk (tech availability)
from kil.backend.legacy.api.tech_availability import availability_bp
app.register_blueprint(availability_bp)

# Schedule Diff (compare 2 months)
from kil.backend.legacy.api.schedule_diff import diff_bp
app.register_blueprint(diff_bp)

# Audit (readiness, blockers, layers, publish gate)
from kil.backend.legacy.api.audit import audit_bp
app.register_blueprint(audit_bp)

# Audit Compare (Excel upload + side-by-side)
from kil.backend.legacy.api.audit_compare import compare_bp
app.register_blueprint(compare_bp)

# Schedule Draft Calendar (Phase 1 PRD §25)
from kil.backend.legacy.api.schedule_calendar import calendar_bp as draft_calendar_bp
app.register_blueprint(draft_calendar_bp)

# Chemical Usage Tracking
from kil.backend.legacy.api.chemical_tracking import chemical_bp
app.register_blueprint(chemical_bp, url_prefix="/api/v1/enterprise/chemicals")

# Daily KPI Rapor
from kil.backend.legacy.api.daily_rapor import daily_rapor_bp
app.register_blueprint(daily_rapor_bp, url_prefix="/api/v1/enterprise/rapor")

# Digital Service Form
from kil.backend.legacy.api.service_form import service_form_bp
app.register_blueprint(service_form_bp, url_prefix="/api/v1/enterprise/service-form")

# Client Portal (shareable read-only links)
from kil.backend.legacy.api.client_portal import client_portal_bp
app.register_blueprint(client_portal_bp, url_prefix="/api/v1/enterprise/client-portal")

# Accurate Accounting Export
from kil.backend.legacy.api.accurate_export import accurate_bp
app.register_blueprint(accurate_bp, url_prefix="/api/v1/enterprise/accurate")

# Ontology Layer (Palantir-style semantic data layer)
from kil.backend.legacy.api.ontology import ontology_bp
app.register_blueprint(ontology_bp, url_prefix="/api/v1/enterprise/ontology")

# Priority Watchlist (P1/P2 + AT_RISK/OVERDUE customers)
from kil.backend.legacy.api.watchlist import watchlist_bp
app.register_blueprint(watchlist_bp, url_prefix="/api/v1/enterprise")

# Lokasi (Customer Management — Kelava-compatible)
from kil.backend.legacy.api.lokasi import lokasi_bp
app.register_blueprint(lokasi_bp, url_prefix="/api/v1/enterprise")

# Scheduling Write — koordinator create/update/cancel road plans
from kil.backend.legacy.api.scheduling_write import scheduling_write_bp
app.register_blueprint(scheduling_write_bp, url_prefix="/api/v1/enterprise")

# Customers & Contracts Write — merged read + SNC write layer
from kil.backend.legacy.api.customers_write import customers_write_bp
app.register_blueprint(customers_write_bp, url_prefix="/api/v1/enterprise")

# ── Finance Module (SAP-grade GL/AR/AP/Cash/CO/AM/Tax/Audit) ─
from kil.backend.legacy.api.finance.gl import gl_bp
from kil.backend.legacy.api.finance.ar import ar_bp
from kil.backend.legacy.api.finance.ap import ap_bp
from kil.backend.legacy.api.finance.cash import cash_bp
from kil.backend.legacy.api.finance.reports import reports_bp
from kil.backend.legacy.api.finance.controlling import co_bp
from kil.backend.legacy.api.finance.assets import am_bp
from kil.backend.legacy.api.finance.tax import tax_bp
from kil.backend.legacy.api.finance.audit import audit_fin_bp

app.register_blueprint(gl_bp)
app.register_blueprint(ar_bp)
app.register_blueprint(ap_bp)
app.register_blueprint(cash_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(co_bp)
app.register_blueprint(am_bp)
app.register_blueprint(tax_bp)
app.register_blueprint(audit_fin_bp)

# Enterprise Web Dashboard
app.register_blueprint(enterprise_bp, url_prefix="/enterprise")


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found", "code": 404}), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed", "code": 405}), 405


@app.errorhandler(Exception)
def handle_exception(e):
    """Catch-all: log unhandled exceptions, return clean 500."""
    log.exception("Unhandled exception on %s %s: %s", request.method, request.path, e)
    return jsonify({"error": "Internal server error", "type": type(e).__name__}), 500


@app.route("/health")
def health():
    """Health check endpoint (quick liveness probe)."""
    return jsonify({"status": "healthy", "service": "kil-api", "version": "2.2.0"})


def main():
    """Run the Flask development server."""
    # Initialize database — non-fatal: app runs without local schema
    try:
        init_db()
    except Exception as e:
        log.warning("init_db() failed (non-fatal, app continues): %s", e)

    # Get config
    host = os.environ.get("KIL_API_HOST", "0.0.0.0")
    port = int(os.environ.get("KIL_API_PORT", 5001))
    debug = os.environ.get("KIL_API_DEBUG", "false").lower() == "true"

    print(f"🚀 KIL API starting on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
