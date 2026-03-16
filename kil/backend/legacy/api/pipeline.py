"""
Sales Pipeline API
==================
Read-only API for GetFound sales pipeline CRM data.
Data sourced from SQLite (imported from Google Sheets).
"""

import csv
import io
from datetime import datetime

from flask import Blueprint, jsonify, request, Response
from core.security import require_auth, require_role

from kil.db.pipeline_db import execute_pipeline_query, execute_pipeline_query_single

pipeline_bp = Blueprint("pipeline", __name__)


# ── GET /pipeline/funnel ────────────────────────────────────────────────────

@pipeline_bp.route("/pipeline/funnel")
@require_auth
@require_role("admin", "koordinator")
def pipeline_funnel():
    """Funnel counts per channel and overall, plus survey stats."""
    channel = request.args.get("channel")

    where = "1=1"
    params: list = []
    if channel:
        where = "channel = ?"
        params = [channel]

    funnel = execute_pipeline_query(
        f"""
        SELECT channel, funnel_stage, COUNT(*) as count
        FROM pipeline_leads
        WHERE {where}
        GROUP BY channel, funnel_stage
        ORDER BY channel,
            CASE funnel_stage
                WHEN 'prospect' THEN 1 WHEN 'outreach' THEN 2
                WHEN 'replied' THEN 3 WHEN 'pic_contacted' THEN 4
                WHEN 'meeting_booked' THEN 5 WHEN 'meeting_done' THEN 6
                WHEN 'closed_lost' THEN 7
            END
        """,
        tuple(params) if params else None,
    )

    totals = execute_pipeline_query(
        f"SELECT channel, COUNT(*) as total FROM pipeline_leads WHERE {where} GROUP BY channel",
        tuple(params) if params else None,
    )

    survey = execute_pipeline_query_single(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN survey_status = 'Completed' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN survey_status = 'Reschedule' THEN 1 ELSE 0 END) as reschedule,
            SUM(CASE WHEN survey_status = 'Cancelled' THEN 1 ELSE 0 END) as cancelled,
            SUM(CASE WHEN survey_status IS NULL OR survey_status = '' THEN 1 ELSE 0 END) as pending
        FROM pipeline_surveys
        """
    )

    # Aggregate cross-channel KPIs
    agg = execute_pipeline_query_single(
        f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN outreach_1st_date IS NOT NULL THEN 1 ELSE 0 END) as outreached,
            SUM(CASE WHEN replied_date IS NOT NULL OR pic_replied_date IS NOT NULL THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN meeting_booked_date IS NOT NULL THEN 1 ELSE 0 END) as meetings,
            SUM(CASE WHEN closed_lost_date IS NOT NULL THEN 1 ELSE 0 END) as closed_lost
        FROM pipeline_leads WHERE {where}
        """,
        tuple(params) if params else None,
    )

    last_import = execute_pipeline_query_single(
        "SELECT imported_at FROM pipeline_import_log ORDER BY id DESC LIMIT 1"
    )

    return jsonify({
        "funnel_by_channel": funnel,
        "channel_totals": totals,
        "survey": survey,
        "aggregate": agg,
        "last_import": last_import["imported_at"] if last_import else None,
        "generated_at": datetime.now().isoformat(),
    })


# ── GET /pipeline/leads ─────────────────────────────────────────────────────

@pipeline_bp.route("/pipeline/leads")
@require_auth
@require_role("admin", "koordinator")
def pipeline_leads():
    """Paginated lead list with search/filter/sort."""
    search = request.args.get("search", "").strip()
    channel = request.args.get("channel")
    stage = request.args.get("stage")
    closed_reason = request.args.get("closed_reason")
    sort = request.args.get("sort", "outreach_1st_date")
    order = request.args.get("order", "desc")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 50)), 200)
    offset = (page - 1) * per_page

    clauses = ["1=1"]
    params: list = []

    if search:
        clauses.append(
            "(name LIKE ? OR pic_name LIKE ? OR company_name LIKE ? OR contact_name LIKE ?)"
        )
        p = f"%{search}%"
        params.extend([p, p, p, p])
    if channel:
        clauses.append("channel = ?")
        params.append(channel)
    if stage:
        clauses.append("funnel_stage = ?")
        params.append(stage)
    if closed_reason:
        clauses.append("closed_lost_reason = ?")
        params.append(closed_reason)

    where = " AND ".join(clauses)

    allowed = {
        "name", "outreach_1st_date", "replied_date", "meeting_booked_date",
        "closed_lost_date", "channel", "funnel_stage", "rating",
    }
    if sort not in allowed:
        sort = "outreach_1st_date"
    direction = "ASC" if order.lower() == "asc" else "DESC"

    count_params = list(params)
    params.extend([per_page, offset])

    leads = execute_pipeline_query(
        f"""
        SELECT id, channel, name, link, phone, price_range, rating,
               contact_name, contact_title, company_name, project_type,
               pic_name, pic_title, pic_phone,
               outreach_channel, outreach_1st_date,
               replied_date, pic_replied_date,
               meeting_booked_date, meeting_date,
               meeting_result_status,
               closed_lost_date, closed_lost_reason,
               funnel_stage
        FROM pipeline_leads
        WHERE {where}
        ORDER BY {sort} {direction} NULLS LAST
        LIMIT ? OFFSET ?
        """,
        tuple(params),
    )

    total = execute_pipeline_query_single(
        f"SELECT COUNT(*) as total FROM pipeline_leads WHERE {where}",
        tuple(count_params) if count_params else None,
    )

    return jsonify({
        "leads": leads,
        "pagination": {"page": page, "per_page": per_page, "total": total["total"] if total else 0},
        "generated_at": datetime.now().isoformat(),
    })


# ── GET /pipeline/leads/<id> ────────────────────────────────────────────────

@pipeline_bp.route("/pipeline/leads/<int:lead_id>")
@require_auth
@require_role("admin", "koordinator")
def pipeline_lead_detail(lead_id: int):
    """Single lead detail."""
    lead = execute_pipeline_query_single(
        "SELECT * FROM pipeline_leads WHERE id = ?", (lead_id,)
    )
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    return jsonify({"lead": lead, "generated_at": datetime.now().isoformat()})


# ── GET /pipeline/sdr-performance ───────────────────────────────────────────

@pipeline_bp.route("/pipeline/sdr-performance")
@require_auth
@require_role("admin", "koordinator")
def sdr_performance():
    """SDR performance from Survey data."""
    sdr = execute_pipeline_query(
        """
        SELECT
            getfound_sdr as sdr_name,
            COUNT(*) as total_surveys,
            SUM(CASE WHEN survey_status = 'Completed' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN survey_status = 'Reschedule' THEN 1 ELSE 0 END) as reschedule,
            SUM(CASE WHEN survey_status = 'Cancelled' THEN 1 ELSE 0 END) as cancelled,
            SUM(CASE WHEN survey_status IS NULL OR survey_status = '' THEN 1 ELSE 0 END) as pending,
            ROUND(100.0 * SUM(CASE WHEN survey_status = 'Completed' THEN 1 ELSE 0 END)
                  / COUNT(*), 1) as completion_rate_pct
        FROM pipeline_surveys
        WHERE getfound_sdr IS NOT NULL AND getfound_sdr != ''
        GROUP BY getfound_sdr
        ORDER BY completed DESC
        """
    )

    # Survey breakdown by area
    by_area = execute_pipeline_query(
        """
        SELECT area, survey_status, COUNT(*) as count
        FROM pipeline_surveys
        WHERE area IS NOT NULL
        GROUP BY area, survey_status
        """
    )

    # Survey breakdown by industry
    by_industry = execute_pipeline_query(
        """
        SELECT industry, survey_status, COUNT(*) as count
        FROM pipeline_surveys
        WHERE industry IS NOT NULL
        GROUP BY industry, survey_status
        """
    )

    return jsonify({
        "sdr_survey_performance": sdr,
        "by_area": by_area,
        "by_industry": by_industry,
        "generated_at": datetime.now().isoformat(),
    })


# ── GET /pipeline/trends ────────────────────────────────────────────────────

@pipeline_bp.route("/pipeline/trends")
@require_auth
@require_role("admin", "koordinator")
def pipeline_trends():
    """Monthly outreach activity trends per channel."""
    monthly = execute_pipeline_query(
        """
        SELECT
            strftime('%Y-%m', outreach_1st_date) as month,
            channel,
            COUNT(*) as total,
            SUM(CASE WHEN replied_date IS NOT NULL THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN meeting_booked_date IS NOT NULL THEN 1 ELSE 0 END) as meetings,
            SUM(CASE WHEN closed_lost_date IS NOT NULL THEN 1 ELSE 0 END) as closed_lost
        FROM pipeline_leads
        WHERE outreach_1st_date IS NOT NULL
        GROUP BY month, channel
        ORDER BY month
        """
    )

    return jsonify({
        "monthly": monthly,
        "generated_at": datetime.now().isoformat(),
    })


# ── GET /pipeline/insights ──────────────────────────────────────────────────

@pipeline_bp.route("/pipeline/insights")
@require_auth
@require_role("admin", "koordinator")
def pipeline_insights():
    """Actionable insights: stale leads, hot prospects, closed lost analysis."""

    # Hot prospects: replied but no meeting yet
    hot = execute_pipeline_query(
        """
        SELECT id, channel, name, pic_name, contact_name, replied_date, funnel_stage
        FROM pipeline_leads
        WHERE (replied_date IS NOT NULL OR pic_replied_date IS NOT NULL)
          AND meeting_booked_date IS NULL
          AND closed_lost_date IS NULL
        ORDER BY replied_date DESC
        LIMIT 25
        """
    )

    # Stale leads: outreach done, no reply, >14 days old
    stale = execute_pipeline_query(
        """
        SELECT id, channel, name, pic_name, contact_name, outreach_1st_date, funnel_stage
        FROM pipeline_leads
        WHERE funnel_stage IN ('outreach', 'pic_contacted')
          AND replied_date IS NULL AND pic_replied_date IS NULL
          AND closed_lost_date IS NULL
          AND outreach_1st_date IS NOT NULL
          AND date(outreach_1st_date) < date('now', '-14 days')
        ORDER BY outreach_1st_date ASC
        LIMIT 25
        """
    )

    # Closed lost reason breakdown
    reasons = execute_pipeline_query(
        """
        SELECT closed_lost_reason, COUNT(*) as count,
               GROUP_CONCAT(DISTINCT channel) as channels
        FROM pipeline_leads
        WHERE closed_lost_reason IS NOT NULL AND closed_lost_reason != ''
        GROUP BY closed_lost_reason
        ORDER BY count DESC
        """
    )

    # Conversion rates by channel
    conversion = execute_pipeline_query(
        """
        SELECT
            channel,
            COUNT(*) as total,
            SUM(CASE WHEN outreach_1st_date IS NOT NULL THEN 1 ELSE 0 END) as outreached,
            SUM(CASE WHEN replied_date IS NOT NULL OR pic_replied_date IS NOT NULL THEN 1 ELSE 0 END) as replied,
            SUM(CASE WHEN meeting_booked_date IS NOT NULL THEN 1 ELSE 0 END) as meetings,
            ROUND(100.0 * SUM(CASE WHEN replied_date IS NOT NULL OR pic_replied_date IS NOT NULL THEN 1 ELSE 0 END)
                  / NULLIF(SUM(CASE WHEN outreach_1st_date IS NOT NULL THEN 1 ELSE 0 END), 0), 1)
                  as reply_rate_pct,
            ROUND(100.0 * SUM(CASE WHEN meeting_booked_date IS NOT NULL THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(*), 0), 1)
                  as meeting_rate_pct
        FROM pipeline_leads
        GROUP BY channel
        """
    )

    # Pending surveys
    pending_surveys = execute_pipeline_query(
        """
        SELECT * FROM pipeline_surveys
        WHERE survey_status IS NULL OR survey_status = ''
        ORDER BY meeting_booked_date DESC
        """
    )

    return jsonify({
        "hot_prospects": hot,
        "stale_leads": stale,
        "closed_lost_reasons": reasons,
        "conversion_by_channel": conversion,
        "pending_surveys": pending_surveys,
        "generated_at": datetime.now().isoformat(),
    })


# ══════════════════════════════════════════════════════════════════════════════
# HUBEXO ENRICHMENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════


@pipeline_bp.route("/pipeline/hubexo/enrichment-stats")
@require_auth
@require_role("admin", "koordinator")
def hubexo_enrichment_stats():
    """Coverage metrics for Hubexo enrichment KPI cards."""
    total_leads = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM pipeline_leads WHERE channel='hubexo'"
    )
    total_linkedin = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM pipeline_leads WHERE channel='hubexo_linkedin'"
    )

    # Company domains
    companies_total = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_companies"
    )
    companies_with_domain = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_companies WHERE domain IS NOT NULL"
    )

    # Email coverage
    emails_total = execute_pipeline_query_single(
        "SELECT COUNT(DISTINCT lead_id) as n FROM enrichment_emails WHERE email_generated IS NOT NULL"
    )
    emails_high = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_emails WHERE confidence='high'"
    )
    emails_medium = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_emails WHERE confidence='medium'"
    )
    emails_low = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_emails WHERE confidence='low'"
    )

    # Geocoding
    geocoded = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_geocodes WHERE lat IS NOT NULL"
    )
    geocode_total = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_geocodes"
    )

    # Classification
    high_relevance = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_project_class WHERE pest_relevance='high'"
    )
    projects_classified = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_project_class"
    )

    # LinkedIn URLs
    linkedin_total = execute_pipeline_query_single(
        "SELECT COUNT(*) as n FROM enrichment_linkedin_urls"
    )

    # Industry breakdown
    industry = execute_pipeline_query(
        "SELECT industry, COUNT(*) as count FROM enrichment_companies GROUP BY industry ORDER BY count DESC"
    )

    # Last enrichment run
    last_run = execute_pipeline_query_single(
        "SELECT run_at, step FROM enrichment_log ORDER BY id DESC LIMIT 1"
    )

    return jsonify({
        "total_leads": total_leads["n"] if total_leads else 0,
        "total_linkedin": total_linkedin["n"] if total_linkedin else 0,
        "companies": {
            "total": companies_total["n"] if companies_total else 0,
            "with_domain": companies_with_domain["n"] if companies_with_domain else 0,
        },
        "emails": {
            "total": emails_total["n"] if emails_total else 0,
            "high": emails_high["n"] if emails_high else 0,
            "medium": emails_medium["n"] if emails_medium else 0,
            "low": emails_low["n"] if emails_low else 0,
        },
        "geocoding": {
            "geocoded": geocoded["n"] if geocoded else 0,
            "total": geocode_total["n"] if geocode_total else 0,
        },
        "classification": {
            "high_relevance": high_relevance["n"] if high_relevance else 0,
            "classified": projects_classified["n"] if projects_classified else 0,
        },
        "linkedin_urls": linkedin_total["n"] if linkedin_total else 0,
        "industry_breakdown": industry,
        "last_enrichment": last_run["run_at"] if last_run else None,
        "generated_at": datetime.now().isoformat(),
    })


@pipeline_bp.route("/pipeline/hubexo/projects")
@require_auth
@require_role("admin", "koordinator")
def hubexo_projects():
    """Enriched project list with geo + classification."""
    projects = execute_pipeline_query(
        """
        SELECT
            pc.project_name,
            pc.project_type_raw,
            pc.building_type,
            pc.building_subtype,
            pc.unit_count,
            pc.storey_count,
            pc.is_new_build,
            pc.pest_relevance,
            pc.project_scale,
            g.lat, g.lng,
            g.city, g.district, g.province,
            g.geocode_quality,
            (SELECT COUNT(*) FROM pipeline_leads l
             WHERE l.channel='hubexo' AND l.name = pc.project_name) as contact_count,
            (SELECT COUNT(DISTINCT e.lead_id) FROM enrichment_emails e
             JOIN pipeline_leads l ON l.id = e.lead_id
             WHERE l.name = pc.project_name AND e.email_generated IS NOT NULL) as email_count
        FROM enrichment_project_class pc
        LEFT JOIN enrichment_geocodes g ON g.project_name = pc.project_name
        ORDER BY
            CASE pc.pest_relevance WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            pc.unit_count DESC
        """
    )
    return jsonify({"projects": projects, "generated_at": datetime.now().isoformat()})


@pipeline_bp.route("/pipeline/hubexo/companies")
@require_auth
@require_role("admin", "koordinator")
def hubexo_companies():
    """Enriched company directory."""
    companies = execute_pipeline_query(
        """
        SELECT
            ec.company_name,
            ec.company_name_clean,
            ec.domain,
            ec.domain_source,
            ec.website_url,
            ec.industry,
            ec.parent_company,
            (SELECT COUNT(*) FROM pipeline_leads l
             WHERE l.channel='hubexo' AND l.company_name = ec.company_name) as contact_count,
            (SELECT COUNT(DISTINCT e.lead_id) FROM enrichment_emails e
             JOIN pipeline_leads l ON l.id = e.lead_id
             WHERE l.company_name = ec.company_name AND e.email_generated IS NOT NULL) as email_count
        FROM enrichment_companies ec
        ORDER BY ec.industry, contact_count DESC
        """
    )
    return jsonify({"companies": companies, "generated_at": datetime.now().isoformat()})


@pipeline_bp.route("/pipeline/hubexo/contacts")
@require_auth
@require_role("admin", "koordinator")
def hubexo_contacts():
    """Enriched contact list with combined emails + LinkedIn."""
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 100)), 500)
    offset = (page - 1) * per_page
    relevance = request.args.get("relevance")

    where_extra = ""
    params: list = []
    if relevance:
        where_extra = "AND pc.pest_relevance = ?"
        params.append(relevance)

    contacts = execute_pipeline_query(
        f"""
        SELECT
            l.id, l.name as project_name, l.contact_name, l.contact_title,
            l.company_name, l.pic_phone, l.pic_email,
            l.project_type, l.project_stage, l.funnel_stage,
            l.outreach_1st_date, l.replied_date,
            e.email_generated, e.confidence as email_confidence,
            li.search_url as linkedin_url, li.source as linkedin_source,
            pc.pest_relevance, pc.project_scale, pc.building_type,
            ec.domain as company_domain, ec.industry
        FROM pipeline_leads l
        LEFT JOIN enrichment_emails e ON e.lead_id = l.id
        LEFT JOIN enrichment_linkedin_urls li ON li.lead_id = l.id
        LEFT JOIN enrichment_project_class pc ON pc.project_name = l.name
        LEFT JOIN enrichment_companies ec ON ec.company_name = l.company_name
        WHERE l.channel = 'hubexo' {where_extra}
        ORDER BY
            CASE pc.pest_relevance WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            CASE WHEN e.email_generated IS NOT NULL THEN 0 ELSE 1 END,
            l.contact_name
        LIMIT ? OFFSET ?
        """,
        tuple(params + [per_page, offset]),
    )

    total = execute_pipeline_query_single(
        f"""
        SELECT COUNT(*) as n FROM pipeline_leads l
        LEFT JOIN enrichment_project_class pc ON pc.project_name = l.name
        WHERE l.channel = 'hubexo' {where_extra}
        """,
        tuple(params) if params else None,
    )

    return jsonify({
        "contacts": contacts,
        "pagination": {"page": page, "per_page": per_page, "total": total["n"] if total else 0},
        "generated_at": datetime.now().isoformat(),
    })


@pipeline_bp.route("/pipeline/hubexo/map-data")
@require_auth
@require_role("admin", "koordinator")
def hubexo_map_data():
    """GeoJSON FeatureCollection for Leaflet.js map."""
    rows = execute_pipeline_query(
        """
        SELECT
            g.project_name, g.lat, g.lng, g.city, g.geocode_quality,
            pc.building_type, pc.unit_count, pc.pest_relevance, pc.project_scale,
            pc.is_new_build, pc.project_type_raw,
            (SELECT COUNT(*) FROM pipeline_leads l
             WHERE l.channel='hubexo' AND l.name = g.project_name) as contact_count,
            (SELECT COUNT(DISTINCT e.lead_id) FROM enrichment_emails e
             JOIN pipeline_leads l ON l.id = e.lead_id
             WHERE l.name = g.project_name AND e.email_generated IS NOT NULL) as email_count
        FROM enrichment_geocodes g
        LEFT JOIN enrichment_project_class pc ON pc.project_name = g.project_name
        WHERE g.lat IS NOT NULL
        """
    )

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
            "properties": {
                "name": r["project_name"],
                "city": r["city"],
                "building_type": r["building_type"],
                "unit_count": r["unit_count"],
                "pest_relevance": r["pest_relevance"],
                "project_scale": r["project_scale"],
                "is_new_build": r["is_new_build"],
                "project_type": r["project_type_raw"],
                "contact_count": r["contact_count"],
                "email_count": r["email_count"],
                "geocode_quality": r["geocode_quality"],
            },
        })

    return jsonify({
        "type": "FeatureCollection",
        "features": features,
    })


@pipeline_bp.route("/pipeline/hubexo/export")
@require_auth
@require_role("admin", "koordinator")
def hubexo_export():
    """CSV export of enriched Hubexo contacts for CRM import."""
    rows = execute_pipeline_query(
        """
        SELECT
            l.contact_name, l.contact_title, l.company_name,
            l.pic_phone, l.pic_email,
            e.email_generated, e.confidence as email_confidence,
            l.name as project_name, l.project_type, l.project_stage,
            pc.building_type, pc.unit_count, pc.pest_relevance, pc.project_scale,
            g.lat, g.lng, g.city,
            ec.domain as company_domain, ec.website_url, ec.industry,
            li.search_url as linkedin_search_url,
            l.outreach_1st_date, l.replied_date, l.funnel_stage
        FROM pipeline_leads l
        LEFT JOIN enrichment_emails e ON e.lead_id = l.id
        LEFT JOIN enrichment_linkedin_urls li ON li.lead_id = l.id
        LEFT JOIN enrichment_project_class pc ON pc.project_name = l.name
        LEFT JOIN enrichment_geocodes g ON g.project_name = l.name
        LEFT JOIN enrichment_companies ec ON ec.company_name = l.company_name
        WHERE l.channel = 'hubexo'
        ORDER BY
            CASE pc.pest_relevance WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            l.contact_name
        """
    )

    if not rows:
        return jsonify({"error": "No data to export"}), 404

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=hubexo_enriched_{datetime.now().strftime('%Y%m%d')}.csv"},
    )
