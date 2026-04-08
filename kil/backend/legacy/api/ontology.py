"""
Ontology Resolver API
======================
Palantir-style semantic data layer for SanoCare entities.

Wraps existing Kelava DB views to expose typed objects with
derived properties and traversable links.

Object types: customer, technician
Endpoints:
    GET /ontology/objects/customer/{id}     → full customer object
    GET /ontology/objects/technician/{id}   → full technician object
    GET /ontology/search?q=...&types=...    → cross-object search
    GET /ontology/schema                    → type definitions
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from core.security import require_auth
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

ontology_bp = Blueprint("ontology", __name__, url_prefix="/ontology")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt(row):
    if not row:
        return None
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


def _safe(val, default=None):
    return val if val is not None else default


# ── Schema Definition ─────────────────────────────────────────────────────────

SCHEMA = {
    "customer": {
        "description": "SanoCare client with active or past pest control contract",
        "source_tables": ["m_customer", "v_customer_rfm_segment", "v_customer_priority_action"],
        "properties": {
            "name": "string",
            "code": "string",
            "address": "string",
            "phone": "string",
            "rfm_segment": "enum[CHAMPIONS, STABLE_CORE, AT_RISK, LOW_VALUE, INACTIVE]",
            "account_status": "enum[UNDER_SLA, AT_RISK, OVERDUE, INACTIVE]",
            "r_score": "int[1-5]",
            "f_score": "int[1-5]",
            "m_score": "int[1-5]",
            "rfm_vector": "string",
            "days_since_last_visit": "int",
            "service_frequency": "string",
            "expected_cycle_days": "int",
            "has_active_contract": "bool",
            "value_monthly": "decimal",
            "open_complaint": "bool",
            "priority": "enum[P1, P2, P3]",
            "suggested_action": "string",
            "ui_badge": "enum[URGENT, HIGH, NORMAL, LOW]",
            "reason": "string",
        },
        "links": {
            "contracts": "contract[]",
            "recent_visits": "visit[]",
            "assigned_technicians": "technician[]",
            "verification_flags": "flag[]",
            "photos": "photo[]",
        },
    },
    "technician": {
        "description": "Field technician executing pest control visits",
        "source_tables": ["p_user", "enterprise_users", "v_tech_verification_score"],
        "properties": {
            "name": "string",
            "email": "string",
            "role": "string",
            "compliance_pct": "decimal",
            "total_visits_30d": "int",
            "no_photo_visits": "int",
            "no_gps_visits": "int",
            "gps_drift_visits": "int",
            "too_short_visits": "int",
            "avg_photos_per_visit": "decimal",
            "selesai_this_month": "int",
            "planned_this_month": "int",
            "efficiency_pct": "decimal",
        },
        "links": {
            "recent_visits": "visit[]",
            "flagged_visits": "flag[]",
            "current_road_plans": "road_plan[]",
        },
    },
}


@ontology_bp.route("/schema", methods=["GET"])
@require_auth
def schema():
    """Return the ontology schema — object types and their properties/links."""
    return jsonify({"schema": SCHEMA, "version": "1.0", "generated_at": datetime.now().isoformat()})


# ── Customer Object ───────────────────────────────────────────────────────────

@ontology_bp.route("/objects/customer/<int:customer_id>", methods=["GET"])
@require_auth
def customer_object(customer_id):
    """
    Full customer ontology object.
    Merges: m_customer + v_customer_rfm_segment + v_customer_priority_action
    + linked contracts, recent visits, assigned techs, verification flags.
    """
    # Base + RFM + Priority (all from the richest view)
    base = execute_kelava_query_single(
        """
        SELECT
            c.id, c.code, c.name, c.address, c.phone1 AS phone,
            c.contact_person_name, c.contact_person_phone, c.credit_limit,
            -- RFM derived (v_customer_rfm_segment)
            rfm.service_frequency, rfm.expected_cycle_days,
            rfm.last_completed_visit_at, rfm.has_active_contract,
            rfm.value_monthly, rfm.open_complaint, rfm.days_since_last_visit,
            rfm.recency_ratio, rfm.missed_cycles, rfm.account_status,
            rfm.r_score, rfm.f_score, rfm.m_score, rfm.rfm_vector, rfm.rfm_segment,
            -- Priority action (v_customer_priority_action)
            pa.priority, pa.owner, pa.suggested_action, pa.ui_badge, pa.reason
        FROM m_customer c
        LEFT JOIN v_customer_rfm_segment rfm ON rfm.customer_id = c.id
        LEFT JOIN v_customer_priority_action pa ON pa.customer_id = c.id
        WHERE c.id = %s
        """,
        (customer_id,),
    )

    if not base:
        return jsonify({"error": "Customer not found"}), 404

    # Contracts
    contracts = execute_kelava_query(
        """
        SELECT k.id, k.no_kontrak, k.start_date, k.end_date, k.is_active,
               (k.end_date - CURRENT_DATE) AS days_to_expire
        FROM m_customer_kontrak k
        WHERE k.id_customer = %s
        ORDER BY k.end_date DESC
        """,
        (customer_id,),
    )

    # Recent visits (last 15) with verification flags
    recent_visits = execute_kelava_query(
        """
        SELECT
            v.id AS visit_id, rp.visit_date::date AS tanggal,
            u.fullname AS technician_name, u.id AS technician_id,
            rp.type, rp.status,
            v.check_in, v.check_out,
            ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60) AS duration_min,
            vv.photo_count, vv.drift_meters,
            vv.flag_no_photo, vv.flag_gps_drift, vv.flag_too_short, vv.flag_too_long
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        LEFT JOIN v_visit_verification vv ON vv.road_plan_id = rp.id
        WHERE rp.id_customer = %s
          AND rp.status = 'Selesai'
        ORDER BY rp.visit_date DESC
        LIMIT 15
        """,
        (customer_id,),
    )

    # Assigned technicians (90d)
    assigned_techs = execute_kelava_query(
        """
        SELECT u.id, u.fullname AS name, COUNT(*) AS visit_count,
               MAX(rp.visit_date::date) AS last_visit
        FROM t_road_plan rp
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.id_customer = %s
          AND rp.visit_date::date >= CURRENT_DATE - INTERVAL '90 days'
          AND rp.status = 'Selesai'
        GROUP BY u.id, u.fullname
        ORDER BY visit_count DESC
        LIMIT 5
        """,
        (customer_id,),
    )

    # Photos (last 10)
    photos = execute_kelava_query(
        """
        SELECT f.id, f.path, rp.visit_date::date AS tanggal
        FROM t_road_plan_foto f
        JOIN t_road_plan rp ON rp.id = f.id_road_plan
        WHERE rp.id_customer = %s
        ORDER BY rp.visit_date DESC
        LIMIT 10
        """,
        (customer_id,),
    )

    b = _fmt(base)

    return jsonify({
        "type": "customer",
        "id": customer_id,
        "properties": {
            "name": b.get("name"),
            "code": b.get("code"),
            "address": b.get("address"),
            "phone": b.get("phone"),
            "contact_person": b.get("contact_person_name"),
            "contact_phone": b.get("contact_person_phone"),
            # RFM Intelligence
            "rfm_segment": b.get("rfm_segment"),
            "rfm_vector": b.get("rfm_vector"),
            "r_score": b.get("r_score"),
            "f_score": b.get("f_score"),
            "m_score": b.get("m_score"),
            "account_status": b.get("account_status"),
            "service_frequency": b.get("service_frequency"),
            "expected_cycle_days": b.get("expected_cycle_days"),
            "days_since_last_visit": b.get("days_since_last_visit"),
            "last_completed_visit_at": b.get("last_completed_visit_at"),
            "has_active_contract": b.get("has_active_contract"),
            "value_monthly": float(b.get("value_monthly") or 0),
            "open_complaint": b.get("open_complaint"),
            "recency_ratio": float(b.get("recency_ratio") or 0),
            "missed_cycles": b.get("missed_cycles"),
            # Priority Action
            "priority": b.get("priority"),
            "suggested_action": b.get("suggested_action"),
            "ui_badge": b.get("ui_badge"),
            "reason": b.get("reason"),
            "owner": b.get("owner"),
        },
        "links": {
            "contracts": [_fmt(r) for r in (contracts or [])],
            "recent_visits": [_fmt(r) for r in (recent_visits or [])],
            "assigned_technicians": [_fmt(r) for r in (assigned_techs or [])],
            "photos": [_fmt(r) for r in (photos or [])],
        },
        "generated_at": datetime.now().isoformat(),
    })


# ── Technician Object ─────────────────────────────────────────────────────────

@ontology_bp.route("/objects/technician/<int:tech_id>", methods=["GET"])
@require_auth
def technician_object(tech_id):
    """
    Full technician ontology object.
    Merges: p_user + enterprise_users + v_tech_verification_score
    + recent visits, flagged visits, today's road plans.
    """
    # Kelava query: p_user + verification view (no enterprise_* tables — avoids local DB routing)
    base = execute_kelava_query_single(
        """
        SELECT u.id, u.fullname AS name, u.email,
               vs.total_visits, vs.no_photo_visits, vs.no_gps_visits,
               vs.gps_drift_visits, vs.too_short_visits,
               vs.compliance_pct, vs.avg_photos_per_visit
        FROM p_user u
        LEFT JOIN v_tech_verification_score vs ON vs.technician_id = u.id
        WHERE u.id = %s
        """,
        (tech_id,),
    )

    # Local DB query: enterprise_users role/status (separate connection)
    ent_user = execute_kelava_query_single(
        "SELECT role, is_active FROM enterprise_users WHERE p_user_id = %s",
        (tech_id,),
    )

    if not base:
        return jsonify({"error": "Technician not found"}), 404

    # This month KPIs
    month_kpi = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'Selesai') AS selesai,
            COUNT(*) AS planned,
            ROUND(AVG(
                CASE WHEN v.check_in IS NOT NULL AND v.check_out IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60
                END
            )::numeric, 1) AS avg_duration_min
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_user = %s
          AND rp.visit_date::date >= DATE_TRUNC('month', CURRENT_DATE)
          AND COALESCE(rp.is_cancel, false) = false
        """,
        (tech_id,),
    )

    # Recent visits (last 20) with verification flags
    recent_visits = execute_kelava_query(
        """
        SELECT
            rp.id AS road_plan_id, rp.visit_date::date AS tanggal,
            c.name AS customer_name, c.id AS customer_id,
            rp.type, rp.status, rp.no_ra,
            v.check_in, v.check_out,
            ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60) AS duration_min,
            vv.photo_count, vv.drift_meters,
            vv.flag_no_photo, vv.flag_gps_drift, vv.flag_too_short, vv.flag_too_long
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        LEFT JOIN v_visit_verification vv ON vv.road_plan_id = rp.id
        WHERE rp.id_user = %s
        ORDER BY rp.visit_date DESC
        LIMIT 20
        """,
        (tech_id,),
    )

    # Today's road plans
    today_plans = execute_kelava_query(
        """
        SELECT rp.id, rp.status, rp.type,
               c.name AS customer_name, c.id AS customer_id,
               v.check_in, v.check_out
        FROM t_road_plan rp
        JOIN m_customer c ON c.id = rp.id_customer
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_user = %s
          AND rp.visit_date::date = CURRENT_DATE
          AND COALESCE(rp.is_cancel, false) = false
        ORDER BY v.check_in NULLS LAST
        """,
        (tech_id,),
    )

    # Flagged visits (last 30 days)
    flagged = execute_kelava_query(
        """
        SELECT vv.visit_id, vv.road_plan_id, vv.customer_name,
               vv.realization_date, vv.duration_minutes,
               vv.drift_meters, vv.photo_count,
               vv.flag_no_photo, vv.flag_gps_drift,
               vv.flag_too_short, vv.flag_too_long
        FROM v_visit_verification vv
        WHERE vv.technician_id = %s
          AND vv.realization_date >= CURRENT_DATE - INTERVAL '30 days'
          AND (vv.flag_no_photo OR vv.flag_gps_drift OR vv.flag_too_short OR vv.flag_too_long)
        ORDER BY vv.realization_date DESC
        LIMIT 10
        """,
        (tech_id,),
    )

    b = _fmt(base)
    eu = _fmt(ent_user) or {}
    kpi = _fmt(month_kpi) or {}
    selesai = kpi.get("selesai") or 0
    planned = kpi.get("planned") or 0

    return jsonify({
        "type": "technician",
        "id": tech_id,
        "properties": {
            "name": b.get("name"),
            "email": b.get("email"),
            "role": eu.get("role"),
            "is_active": eu.get("is_active"),
            # Verification score (from v_tech_verification_score)
            "total_visits_30d": b.get("total_visits") or 0,
            "compliance_pct": float(b.get("compliance_pct") or 0),
            "no_photo_visits": b.get("no_photo_visits") or 0,
            "no_gps_visits": b.get("no_gps_visits") or 0,
            "gps_drift_visits": b.get("gps_drift_visits") or 0,
            "too_short_visits": b.get("too_short_visits") or 0,
            "avg_photos_per_visit": float(b.get("avg_photos_per_visit") or 0),
            # This-month KPIs
            "selesai_this_month": selesai,
            "planned_this_month": planned,
            "efficiency_pct": round(selesai / planned * 100, 1) if planned > 0 else 0,
            "avg_duration_min": float(kpi.get("avg_duration_min") or 0),
        },
        "links": {
            "recent_visits": [_fmt(r) for r in (recent_visits or [])],
            "today_plans": [_fmt(r) for r in (today_plans or [])],
            "flagged_visits": [_fmt(r) for r in (flagged or [])],
        },
        "generated_at": datetime.now().isoformat(),
    })


# ── Cross-Object Search ───────────────────────────────────────────────────────

@ontology_bp.route("/search", methods=["GET"])
@require_auth
def search():
    """
    Cross-object search across customers and technicians.
    ?q=keyword&types=customer,technician&limit=10
    """
    q = request.args.get("q", "").strip()
    types = request.args.get("types", "customer,technician").split(",")
    limit = min(int(request.args.get("limit", 10)), 50)

    if len(q) < 2:
        return jsonify({"results": [], "query": q})

    results = []
    pattern = f"%{q.lower()}%"

    if "customer" in types:
        customers = execute_kelava_query(
            """
            SELECT c.id, c.name, c.code, c.address,
                   rfm.rfm_segment, rfm.account_status, rfm.days_since_last_visit,
                   pa.priority, pa.ui_badge
            FROM m_customer c
            LEFT JOIN v_customer_rfm_segment rfm ON rfm.customer_id = c.id
            LEFT JOIN v_customer_priority_action pa ON pa.customer_id = c.id
            WHERE LOWER(c.name) LIKE %s OR LOWER(c.code) LIKE %s
            ORDER BY
                CASE pa.priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                c.name
            LIMIT %s
            """,
            (pattern, pattern, limit),
        )
        for r in (customers or []):
            results.append({
                "type": "customer",
                "id": r["id"],
                "label": r["name"],
                "sublabel": r.get("code"),
                "badge": r.get("rfm_segment"),
                "status": r.get("account_status"),
                "priority": r.get("priority"),
                "url": f"/enterprise/customers/{r['id']}",
            })

    if "technician" in types:
        # Kelava only — no enterprise_* tables to avoid local DB routing
        technicians = execute_kelava_query(
            """
            SELECT u.id, u.fullname AS name, u.email,
                   vs.compliance_pct, vs.total_visits
            FROM p_user u
            LEFT JOIN v_tech_verification_score vs ON vs.technician_id = u.id
            WHERE LOWER(u.fullname) LIKE %s OR LOWER(u.email) LIKE %s
            ORDER BY u.fullname
            LIMIT %s
            """,
            (pattern, pattern, limit),
        )
        for r in (technicians or []):
            results.append({
                "type": "technician",
                "id": r["id"],
                "label": r["name"],
                "sublabel": r.get("email"),
                "badge": f"{round(float(r['compliance_pct'] or 0))}% compliance",
                "url": f"/enterprise/technicians/{r['id']}",
            })

    return jsonify({
        "query": q,
        "total": len(results),
        "results": results,
        "generated_at": datetime.now().isoformat(),
    })
