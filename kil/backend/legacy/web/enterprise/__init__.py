"""
Enterprise Dashboard Web Routes
================================
Flask blueprint for enterprise dashboard pages.
"""

import os

from flask import Blueprint, render_template

enterprise_bp = Blueprint(
    "enterprise", __name__, template_folder="templates", static_folder="static"
)


@enterprise_bp.context_processor
def inject_env():
    return {"APP_ENV": os.environ.get("KIL_ENV", "PROD")}


@enterprise_bp.route("/")
@enterprise_bp.route("/executive")
def executive_summary():
    """Executive Summary Dashboard - main landing page."""
    return render_template("enterprise/executive.html")


@enterprise_bp.route("/operations")
def operations():
    """Operations Overview page."""
    return render_template("enterprise/operations.html")


@enterprise_bp.route("/technicians")
def technicians():
    """Technicians Leaderboard page."""
    return render_template("enterprise/technicians.html")


@enterprise_bp.route("/technicians/<int:tech_id>")
def technician_detail(tech_id: int):
    """Technician detail page."""
    return render_template("enterprise/technician_detail.html", tech_id=tech_id)


@enterprise_bp.route("/customers")
def customers():
    """Customer list page."""
    return render_template("enterprise/customers.html")


@enterprise_bp.route("/customers/<int:customer_id>")
def customer_detail(customer_id: int):
    """Customer 360 detail page."""
    return render_template("enterprise/customer_detail.html", customer_id=customer_id)


@enterprise_bp.route("/road-plans/<int:road_plan_id>")
def road_plan_detail(road_plan_id: int):
    """Road Plan detail page."""
    return render_template(
        "enterprise/road_plan_detail.html", road_plan_id=road_plan_id
    )


@enterprise_bp.route("/calendar")
def calendar():
    """Resource Calendar - Dispatch view."""
    return render_template("enterprise/calendar.html")


@enterprise_bp.route("/contracts")
def contracts():
    """Contract Management page."""
    return render_template("enterprise/contracts.html")


@enterprise_bp.route("/contracts/<int:contract_id>")
def contract_detail_page(contract_id: int):
    """Contract Detail page."""
    return render_template("enterprise/contract_detail_page.html", contract_id=contract_id)


@enterprise_bp.route("/winback")
def winback():
    """Winback Campaign Manager page."""
    return render_template("enterprise/winback.html")


@enterprise_bp.route("/winback/<int:campaign_id>")
def winback_detail(campaign_id: int):
    """Winback Campaign Detail page."""
    return render_template("enterprise/winback_detail.html", campaign_id=campaign_id)


@enterprise_bp.route("/audit")
def audit_trail():
    """Supervisory Action Log page."""
    return render_template("enterprise/audit_trail.html")


@enterprise_bp.route("/complaints")
def complaints():
    """Complaint Tracking page."""
    return render_template("enterprise/complaints.html")


@enterprise_bp.route("/punctuality")
def punctuality():
    """Punctuality Tracking page."""
    return render_template("enterprise/punctuality.html")


@enterprise_bp.route("/segments")
def segments():
    """Technician Segments management page."""
    return render_template("enterprise/segments.html")


@enterprise_bp.route("/supervisory")
def supervisory():
    """Supervisory Actions / Sidak page."""
    return render_template("enterprise/supervisory.html")


@enterprise_bp.route("/scheduling")
def scheduling():
    """Schedule Board (Plants vs Zombies) page."""
    return render_template("enterprise/scheduling.html")


@enterprise_bp.route("/login")
def login():
    """Enterprise Login page."""
    return render_template("enterprise/login.html")


@enterprise_bp.route("/verification")
def verification():
    """Photo & GPS Verification page."""
    return render_template("enterprise/verification.html")


@enterprise_bp.route("/pipeline")
def pipeline():
    """Sales Pipeline CRM page."""
    return render_template("enterprise/pipeline.html")


@enterprise_bp.route("/hubexo")
def hubexo_intel():
    """Hubexo Intelligence Dashboard page."""
    return render_template("enterprise/hubexo_intel.html")


@enterprise_bp.route("/briefing")
def briefing():
    """Daily Operational Briefing page."""
    return render_template("enterprise/briefing.html")


@enterprise_bp.route("/rapor")
def rapor_list():
    """Rapor Kinerja Teknisi - list all technicians with grades."""
    return render_template("enterprise/rapor.html")


@enterprise_bp.route("/technicians/<int:tech_id>/rapor")
def technician_rapor(tech_id: int):
    """Technician Report Card (Rapor) for HR."""
    return render_template("enterprise/technician_rapor.html", tech_id=tech_id)


@enterprise_bp.route("/kpi-archive")
def kpi_archive():
    """KPI History Archive page."""
    return render_template("enterprise/kpi_archive.html")


@enterprise_bp.route("/users")
def users_admin():
    """User Management admin page."""
    return render_template("enterprise/users.html")


@enterprise_bp.route("/mom")
def mom_list():
    """Notulen Rapat (MOM) list page."""
    return render_template("enterprise/mom.html")


@enterprise_bp.route("/mom/<int:meeting_id>")
def mom_detail(meeting_id: int):
    """MOM detail page."""
    return render_template("enterprise/mom_detail.html", meeting_id=meeting_id)


@enterprise_bp.route("/attendance")
def attendance_page():
    """Fingerprint Attendance dashboard page."""
    return render_template("enterprise/attendance.html")


@enterprise_bp.route("/health")
def health_dashboard():
    """System Health Monitor page."""
    return render_template("enterprise/health.html")


@enterprise_bp.route("/audit-log")
def audit_log_page():
    """Universal Audit Log page."""
    return render_template("enterprise/audit_log.html")


@enterprise_bp.route("/weekly-report")
def weekly_report_page():
    """Weekly Operations Report page."""
    return render_template("enterprise/weekly_report.html")


@enterprise_bp.route("/gps-live")
def gps_live_page():
    """GPS Live Map page."""
    return render_template("enterprise/gps_live.html")


@enterprise_bp.route("/wa-bot")
def wa_bot_page():
    """WhatsApp Bot Gateway page."""
    return render_template("enterprise/wa_bot.html")


@enterprise_bp.route("/trends")
def trends_page():
    """Performance Trends page."""
    return render_template("enterprise/trends.html")


@enterprise_bp.route("/notifications")
def notifications_page():
    """Notification Center page."""
    return render_template("enterprise/notifications.html")


@enterprise_bp.route("/daily-digest")
def daily_digest_page():
    """Daily Digest page."""
    return render_template("enterprise/daily_digest.html")


@enterprise_bp.route("/export")
def export_page():
    """Data Export page."""
    return render_template("enterprise/export.html")


@enterprise_bp.route("/accurate")
def accurate_page():
    """Accurate Accounting Export page."""
    return render_template("enterprise/accurate.html")


@enterprise_bp.route("/service-forms")
def service_forms_page():
    """Form Pelayanan Digital page."""
    return render_template("enterprise/service_form.html")


@enterprise_bp.route("/barcode")
def barcode_page():
    """QR/Barcode Unit Checklist page."""
    return render_template("enterprise/barcode.html")


@enterprise_bp.route("/watchlist")
def watchlist_page():
    """Priority Watchlist — P1/P2 + AT_RISK/OVERDUE customers."""
    return render_template("enterprise/watchlist.html")


@enterprise_bp.route("/lokasi")
def lokasi_page():
    """Lokasi (Customer) management — Kelava-style list."""
    return render_template("enterprise/lokasi.html")


@enterprise_bp.route("/swagger")
def swagger_ui():
    """Swagger UI — interactive API documentation powered by OpenAPI spec."""
    return render_template("enterprise/swagger.html")


@enterprise_bp.route("/api-explorer")
def api_explorer():
    """API Explorer — browse and call live API endpoints interactively."""
    return render_template("enterprise/api_explorer.html")
