"""
Customers API
==============
API endpoints for customer data and Customer 360 view.
Connects to Kelava live database.
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

customers_bp = Blueprint("customers", __name__)


def _auth_user_id() -> str | None:
    """Get authenticated user ID from Flask g context, or None."""
    user = getattr(g, "user", None)
    return str(user.id) if user else None


@customers_bp.route("/customers")
@require_auth
def customers_list():
    """
    Get paginated list of customers with search and filters.

    Query params:
        search: Search by name, code, phone
        segment_id: Filter by segment
        status_filter: Smart filter (under_sla, at_risk, dormant, high_frequency)
        page, per_page: Pagination
    """
    search = request.args.get("search", "").strip()
    segment_id = request.args.get("segment_id")
    status_filter = request.args.get("status_filter", "").strip()
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 25)), 100)
    offset = (page - 1) * per_page

    # New Filters (Phase 11)
    priority = request.args.get("priority")
    segment = request.args.get("segment")
    owner = request.args.get("owner")
    contract = request.args.get("contract")  # active, no_contract
    overdue = request.args.get("overdue")  # 7, 30, 90
    frequency = request.args.get("frequency")

    # Build query
    where_clauses = ["1=1"]
    params = []

    if search:
        where_clauses.append("""
            (c.name ILIKE %s OR c.code ILIKE %s OR c.phone1 ILIKE %s)
        """)
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    if segment_id:
        where_clauses.append("c.id_segment = %s")
        params.append(int(segment_id))

    # Phase 11 Filter Logic
    if priority:
        where_clauses.append("pa.priority = %s")
        params.append(priority)

    if segment:
        where_clauses.append("pa.rfm_segment = %s")
        params.append(segment)

    if owner:
        where_clauses.append("pa.owner ILIKE %s")
        params.append(f"{owner}%")

    if frequency:
        where_clauses.append("pa.service_frequency = %s")
        params.append(frequency)

    if contract:
        if contract == "active":
            where_clauses.append("pa.has_active_contract = true")
        elif contract == "no_contract":
            where_clauses.append(
                "(pa.has_active_contract = false OR pa.has_active_contract IS NULL)"
            )

    if overdue:
        try:
            days = int(overdue)
            where_clauses.append("pa.days_since_last_visit >= %s")
            params.append(days)
        except ValueError:
            pass

    where_sql = " AND ".join(where_clauses)
    params.extend([per_page, offset])
    uid = _auth_user_id()

    customers = execute_kelava_query(
        f"""
        SELECT 
            c.id,
            c.code,
            c.name,
            c.address,
            c.phone1,
            c.email,
            -- Action Engine Fields (Phase 10)
            pa.service_frequency,
            pa.expected_cycle_days,
            pa.has_active_contract,
            pa.value_monthly,
            pa.days_since_last_visit,
            pa.account_status,            
            -- Priority & Action
            pa.priority,
            pa.owner as owner_hint,
            pa.suggested_action as suggested_action_label,
            pa.ui_badge,
            pa.reason,
            pa.rfm_segment as business_signal
        FROM m_customer c
        LEFT JOIN v_customer_priority_action pa ON pa.customer_id = c.id
        WHERE {where_sql}
        ORDER BY 
            CASE pa.priority 
                WHEN 'P0' THEN 1 
                WHEN 'P1' THEN 2 
                WHEN 'P2' THEN 3 
                ELSE 4 
            END ASC,
            c.name ASC
        LIMIT %s OFFSET %s
    """,
        tuple(params),
        user_id=uid,
    )

    # Get total count for pagination
    count_params = params[:-2]  # Remove limit/offset
    total_result = execute_kelava_query_single(
        f"""
        SELECT COUNT(*) as total
        FROM m_customer c
        LEFT JOIN v_customer_priority_action pa ON pa.customer_id = c.id
        WHERE {where_sql}
    """,
        tuple(count_params) if count_params else None,
        user_id=uid,
    )

    # Format with SAP-grade derived fields
    formatted = []
    for row in customers:
        customer = dict(row)

        # 1. Smart Status (Map from View)
        # ------------------------------------------
        # The view gives us 'account_status' and 'days_since_last_visit'.
        # We map strict view statuses to the UI "Accusative" labels.

        # Safe get with default for days_since_last_visit
        days_since = customer.get("days_since_last_visit")
        if days_since is None:
            days_since = 9999

        ac_status = customer.get("account_status", "UNKNOWN")

        smart_status = {"label": ac_status, "color": "slate", "icon": "○"}

        if ac_status == "AT_RISK":
            smart_status = {"label": "At Risk", "color": "amber", "icon": "⚠️"}
        elif ac_status == "UNDER_SLA":
            smart_status = {"label": "Under SLA", "color": "emerald", "icon": "✓"}
        elif ac_status == "DORMANT":
            smart_status = {
                "label": f"Dormant {days_since}d",
                "color": "slate",
                "icon": "💤",
            }
        elif ac_status == "INACTIVE":
            smart_status = {"label": "Inactive", "color": "slate", "icon": "○"}

        # Override for Overdue based on logic if needed, or trust the view.
        # Let's trust the view's 'reason' or calculate specific days just for the badge label.
        if days_since != 9999 and days_since > 30 and ac_status == "AT_RISK":
            smart_status["label"] = f"Overdue {days_since - 30}d"
            smart_status["color"] = "red"
            smart_status["icon"] = "⚠️"

        # Handling for 'Never Visited' case
        if days_since == 9999:
            smart_status = {"label": "Never Visited", "color": "slate", "icon": "⚪"}

        customer["smart_status"] = smart_status

        # 2. Priority Object
        # ------------------------------------------
        p_level = customer.get("priority", "P3")
        p_color = "slate"
        if p_level == "P0":
            p_color = "red"
        elif p_level == "P1":
            p_color = "amber"
        elif p_level == "P2":
            p_color = "emerald"

        customer["priority"] = {"level": p_level, "color": p_color}

        # 3. Suggested Action Object
        # ------------------------------------------
        action_label = customer.get("suggested_action_label")
        if not action_label:
            action_label = "View Details"

        action_type = "view"

        # Simple mapping for button styling based on text
        # Using safe strings for comparison
        action_label_str = str(action_label)
        if "Winback" in action_label_str:
            action_type = "sales"
        elif "Protect" in action_label_str:
            action_type = "urgent"
        elif "complaint" in action_label_str.lower():
            action_type = "urgent"
        elif "Schedule" in action_label_str:
            action_type = "ops"

        customer["suggested_action"] = {"label": action_label, "type": action_type}

        # 4. Misc Format
        if days_since == 9999:
            customer["days_ago"] = None
        else:
            customer["days_ago"] = days_since

        # Ensure other fields are present for UI
        if not customer.get("visit_frequency"):
            customer["visit_frequency"] = customer.get("service_frequency", "Ad-hoc")

        # Ensure active_contracts is int
        if customer.get("active_contracts") is None:
            customer["active_contracts"] = (
                1 if customer.get("has_active_contract") else 0
            )
        elif isinstance(customer.get("active_contracts"), bool):
            customer["active_contracts"] = 1 if customer["active_contracts"] else 0

        formatted.append(customer)

    # Apply smart status filter (post-processing)
    if status_filter:
        if status_filter == "under_sla":
            formatted = [
                c
                for c in formatted
                if c.get("active_contracts", 0) > 0
                and c.get("days_ago") is not None
                and c.get("days_ago", 9999) <= 45
            ]
        elif status_filter == "at_risk":
            formatted = [c for c in formatted if c.get("business_signal") == "AT_RISK"]
        elif status_filter == "dormant":
            formatted = [
                c
                for c in formatted
                if c.get("days_ago") is None or c.get("days_ago", 0) >= 60
            ]
        elif status_filter == "high_frequency":
            formatted = [
                c
                for c in formatted
                if c.get("visit_frequency") in ("Weekly", "Monthly")
            ]

    # CSV export support
    if request.args.get("format") == "csv":
        from kil.backend.legacy.api.export_utils import rows_to_csv_response
        csv_rows = []
        for c in formatted:
            csv_rows.append({
                "id": c.get("id"),
                "code": c.get("code"),
                "name": c.get("name"),
                "address": c.get("address"),
                "phone": c.get("phone1"),
                "email": c.get("email"),
                "priority": c.get("priority", {}).get("level", ""),
                "status": c.get("smart_status", {}).get("label", ""),
                "segment": c.get("business_signal", ""),
                "days_since_visit": c.get("days_ago"),
                "suggested_action": c.get("suggested_action", {}).get("label", ""),
            })
        return rows_to_csv_response(csv_rows, "customers_export.csv")

    return jsonify(
        {
            "filters": {
                "search": search,
                "segment_id": segment_id,
                "status_filter": status_filter,
            },
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": len(formatted)
                if status_filter
                else (total_result["total"] if total_result else 0),
            },
            "customers": formatted,
            "generated_at": datetime.now().isoformat(),
        }
    )


@customers_bp.route("/customers/<int:customer_id>")
@require_auth
def customer_detail(customer_id: int):
    """
    SAP-Grade Account Control View.

    Returns comprehensive account status, rule-engine derived metrics,
    operational flags, service execution log, and supervisory actions.
    """
    uid = _auth_user_id()

    # Basic customer info (m_segment doesn't exist, skip segment lookup)
    customer = execute_kelava_query_single(
        """
        SELECT
            c.id, c.code, c.name, c.address,
            c.phone1, c.phone2, c.email,
            c.credit_limit, c.payment_term,
            NULL as segment_name
        FROM m_customer c
        WHERE c.id = %s
    """,
        (customer_id,),
        user_id=uid,
    )

    if not customer:
        return jsonify({"error": "Customer not found"}), 404

    # Active contracts with frequency info
    contracts = execute_kelava_query(
        """
        SELECT
            k.id, k.no_kontrak, k.start_date, k.end_date, k.is_active,
            (k.end_date - CURRENT_DATE) as days_remaining,
            CASE
                WHEN UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE') AND CURRENT_DATE BETWEEN k.start_date AND k.end_date THEN 'active'
                WHEN k.start_date > CURRENT_DATE THEN 'future'
                ELSE 'expired'
            END as status_computed
        FROM m_customer_kontrak k
        WHERE k.id_customer = %s
        ORDER BY k.end_date DESC
    """,
        (customer_id,),
        user_id=uid,
    )

    # Get primary active contract for SLA calculations
    active_contract = next(
        (c for c in contracts if c["status_computed"] == "active"), None
    )

    # Days since last visit
    last_visit_info = execute_kelava_query_single(
        """
        SELECT 
            MAX(v.realization_date) as last_visit_date,
            CURRENT_DATE - MAX(v.realization_date)::date as days_since_visit
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        WHERE rp.id_customer = %s
    """,
        (customer_id,),
        user_id=uid,
    )
    days_since_visit = (
        last_visit_info["days_since_visit"]
        if last_visit_info and last_visit_info["days_since_visit"]
        else 9999
    )
    last_visit_date = last_visit_info["last_visit_date"] if last_visit_info else None

    # Visit stats (30 days)
    visit_stats_30d = execute_kelava_query_single(
        """
        SELECT 
            COUNT(*) as total_visits,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') as completed_visits,
            COUNT(*) FILTER (WHERE v.id IS NULL OR rp.status != 'Selesai') as missed_visits,
            ROUND(AVG(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 1) as avg_duration
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_customer = %s
          AND rp.visit_date::date >= CURRENT_DATE - INTERVAL '30 days'
          AND COALESCE(rp.is_cancel, false) = false
    """,
        (customer_id,),
        user_id=uid,
    )

    # Visit stats (90 days) for compliance
    visit_stats_90d = execute_kelava_query_single(
        """
        SELECT 
            COUNT(*) as total_visits,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') as completed_visits,
            COUNT(*) FILTER (WHERE EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60 > 180) as long_duration_count
        FROM t_road_plan rp
        LEFT JOIN t_visit v ON v.id_road_plan = rp.id
        WHERE rp.id_customer = %s
          AND rp.visit_date::date >= CURRENT_DATE - INTERVAL '90 days'
          AND COALESCE(rp.is_cancel, false) = false
    """,
        (customer_id,),
        user_id=uid,
    )

    # Assigned technicians
    assigned_techs = execute_kelava_query(
        """
        SELECT DISTINCT u.id, u.fullname, COUNT(*) as visit_count
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        JOIN p_user u ON u.id = rp.id_user
        WHERE rp.id_customer = %s
          AND v.realization_date >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY u.id, u.fullname
        ORDER BY visit_count DESC
        LIMIT 5
    """,
        (customer_id,),
        user_id=uid,
    )

    # Governance State (Phase 8)
    governance = execute_kelava_query_single(
        "SELECT * FROM operational_governance WHERE id_customer = %s",
        (customer_id,),
        user_id=uid,
    )
    if not governance:
        governance = {"review_status": "OPEN", "escalation_level": "WATCH"}

    # Service Execution Log (recent visits with variance detection)
    service_log = execute_kelava_query(
        """
        SELECT 
            v.id,
            v.realization_date,
            v.check_in,
            v.check_out,
            ROUND((EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60)::numeric, 1) as duration_min,
            rp.no_ra,
            rp.type as service_type,
            rp.status,
            u.id as tech_id,
            u.fullname as tech_name
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        LEFT JOIN p_user u ON u.id = rp.id_user
        WHERE rp.id_customer = %s
        ORDER BY v.realization_date DESC, v.check_in DESC
        LIMIT 20
    """,
        (customer_id,),
        user_id=uid,
    )

    # ========== RULE ENGINE ==========

    # 1. Account Status (ACTIVE / DORMANT)
    account_status = "DORMANT" if days_since_visit > 120 else "ACTIVE"

    # 2. Contract Status
    contract_status = "CONTRACTED" if active_contract else "AD-HOC"

    # 3. Service Status (UNDER_SLA / AT_RISK / OVERDUE)
    sla_window = 3  # days tolerance
    if active_contract and active_contract.get("frequency"):
        # Parse frequency (e.g., "2x / month" -> 15 days between visits)
        freq = active_contract.get("frequency", "")
        if "2x" in str(freq).lower() or "2" in str(freq):
            expected_interval = 15
        elif "4x" in str(freq).lower() or "weekly" in str(freq).lower():
            expected_interval = 7
        else:
            expected_interval = 30  # default monthly

        overdue_days = days_since_visit - expected_interval
        if overdue_days <= sla_window:
            service_status = "UNDER_SLA"
        elif overdue_days <= sla_window + 7:
            service_status = "AT_RISK"
        else:
            service_status = "OVERDUE"
    else:
        # No contract - use simple logic
        if days_since_visit <= 45:
            service_status = "UNDER_SLA"
        elif days_since_visit <= 60:
            service_status = "AT_RISK"
        else:
            service_status = "OVERDUE"

    # 4. Data Quality
    data_issues = []
    if not customer.get("phone1") and not customer.get("email"):
        data_issues.append("MISSING_CONTACT_CHANNEL")
    if active_contract is None and contract_status == "CONTRACTED":
        data_issues.append("MISSING_CONTRACT_DOCUMENT")
    data_quality_status = "FLAGGED" if data_issues else "OK"

    # 5. Risk Score Calculation
    risk_points = 0
    if service_status == "AT_RISK":
        risk_points += 2
    elif service_status == "OVERDUE":
        risk_points += 4

    # Low compliance
    total_visits_90d = visit_stats_90d["total_visits"] if visit_stats_90d else 0
    completed_90d = visit_stats_90d["completed_visits"] if visit_stats_90d else 0
    compliance_pct = round(
        (completed_90d / total_visits_90d * 100) if total_visits_90d > 0 else 100, 1
    )
    if compliance_pct < 85:
        risk_points += 2

    # Long duration trend
    long_duration_count = (
        visit_stats_90d["long_duration_count"] if visit_stats_90d else 0
    )
    if long_duration_count >= 3:
        risk_points += 2
    if long_duration_count >= 6:
        risk_points += 2  # additional for critical

    # Data issues
    risk_points += min(len(data_issues), 3)

    # 6. Risk Level
    if risk_points >= 8:
        risk_level = "HIGH"
    elif risk_points >= 4:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # 7. Operational Health
    if risk_level == "HIGH":
        operational_health = "ATTENTION"
    elif risk_level == "MEDIUM":
        operational_health = "WATCH"
    else:
        operational_health = "OK"

    # 8. Operational Flags (auto-generated)
    operational_flags = []
    if long_duration_count >= 3:
        operational_flags.append(
            {
                "code": "REPEATED_LONG_DURATION",
                "severity": "CRITICAL" if long_duration_count >= 6 else "WARNING",
                "message": f"Repeated long duration ({long_duration_count}x in 90 days)",
            }
        )

    missed_visits = visit_stats_30d["missed_visits"] if visit_stats_30d else 0
    if missed_visits >= 2:
        operational_flags.append(
            {
                "code": "REPEATED_MISSED_VISITS",
                "severity": "WARNING",
                "message": f"Multiple missed visits ({missed_visits}x in 30 days)",
            }
        )

    if service_status == "OVERDUE":
        operational_flags.append(
            {
                "code": "SLA_BREACH",
                "severity": "CRITICAL",
                "message": f"Visit gap exceeded SLA ({days_since_visit} days since last visit)",
            }
        )
    elif service_status == "AT_RISK":
        operational_flags.append(
            {
                "code": "SLA_AT_RISK",
                "severity": "WARNING",
                "message": f"Approaching SLA deadline ({days_since_visit} days since last visit)",
            }
        )

    # Format helpers
    def format_row(row):
        item = dict(row)
        for key, value in item.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        return item

    # Add variance flags to service log
    formatted_log = []
    for visit in service_log:
        v = format_row(visit)
        variance = []
        duration = v.get("duration_min")
        if duration:
            if duration > 180:
                variance.append("LONG_DURATION")
            elif duration < 15:
                variance.append("SHORT_VISIT")
        if v.get("status") != "Selesai":
            variance.append("INCOMPLETE")
        v["variance"] = variance
        formatted_log.append(v)

    # Next visit calculation
    next_visit_date = None
    if last_visit_date and active_contract:
        freq = active_contract.get("frequency", "")
        if "2x" in str(freq).lower():
            interval = 15
        elif "4x" in str(freq).lower() or "weekly" in str(freq).lower():
            interval = 7
        else:
            interval = 30
        from datetime import timedelta as td

        next_visit_date = (
            (last_visit_date + td(days=interval)).isoformat()
            if last_visit_date
            else None
        )

    # Build response
    return jsonify(
        {
            "customer": format_row(customer),
            "account_status": {
                "status": account_status,
                "contract_status": contract_status,
                "service_status": service_status,
                "risk": risk_level,
                "governance": {
                    "review_status": governance.get("review_status", "OPEN"),
                    "escalation_level": governance.get("escalation_level", "WATCH"),
                },
                "data_quality": {"status": data_quality_status, "issues": data_issues},
            },
            "summary_cards": {
                "service_status": {
                    "label": service_status,
                    "next_visit_date": next_visit_date,
                    "days_since_visit": days_since_visit
                    if days_since_visit != 9999
                    else None,
                },
                "visit_compliance": {
                    "compliance_pct": compliance_pct,
                    "missed_count": missed_visits,
                    "rescheduled_count": 0,
                },
                "activity_30d": {
                    "visits": visit_stats_30d["total_visits"] if visit_stats_30d else 0,
                    "avg_duration_min": float(visit_stats_30d["avg_duration"] or 0)
                    if visit_stats_30d
                    else 0,
                    "within_expected_range": (visit_stats_30d["total_visits"] or 0) >= 2
                    if visit_stats_30d
                    else False,
                },
                "assigned_resources": {
                    "count": len(assigned_techs),
                    "primary_name": assigned_techs[0]["fullname"]
                    if assigned_techs
                    else None,
                    "primary_id": assigned_techs[0]["id"] if assigned_techs else None,
                },
                "data_quality": {"status": data_quality_status, "issues": data_issues},
            },
            "health_strip": {
                "operational_health": operational_health,
                "financial_health": "N/A",
                "data_integrity": data_quality_status,
            },
            "operational_flags": operational_flags,
            "service_execution_log": formatted_log,
            "contracts": [format_row(c) for c in contracts],
            "contract_policy": {
                "contract_type": "Monthly" if active_contract else "Ad-hoc",
                "frequency": active_contract.get("frequency")
                if active_contract
                else None,
                "sla_window_days": sla_window,
                "start_date": active_contract["start_date"].isoformat()
                if active_contract and active_contract.get("start_date")
                else None,
                "end_date": active_contract["end_date"].isoformat()
                if active_contract and active_contract.get("end_date")
                else None,
            }
            if active_contract
            else None,
            "assigned_technicians": [format_row(t) for t in assigned_techs],
            "generated_at": datetime.now().isoformat(),
        }
    )


@customers_bp.route("/customers/<int:customer_id>/visits")
@require_auth
def customer_visits(customer_id: int):
    """
    Get paginated visit history for a customer.
    """
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)
    offset = (page - 1) * per_page

    visits = execute_kelava_query(
        """
        SELECT
            v.id,
            v.realization_date,
            v.check_in,
            v.check_out,
            ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in)) / 60, 1) as duration_min,
            rp.id as road_plan_id,
            rp.no_ra,
            rp.type,
            rp.status,
            u.id as tech_id,
            u.fullname as tech_name
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        LEFT JOIN p_user u ON u.id = rp.id_user
        WHERE rp.id_customer = %s
        ORDER BY v.realization_date DESC, v.check_in DESC
        LIMIT %s OFFSET %s
    """,
        (customer_id, per_page, offset),
        user_id=_auth_user_id(),
    )

    # Format
    formatted = []
    for row in visits:
        visit = dict(row)
        for key, value in visit.items():
            if hasattr(value, "isoformat"):
                visit[key] = value.isoformat()
        formatted.append(visit)

    return jsonify(
        {
            "customer_id": customer_id,
            "page": page,
            "per_page": per_page,
            "visits": formatted,
            "generated_at": datetime.now().isoformat(),
        }
    )


@customers_bp.route("/customers/<int:customer_id>/contracts")
@require_auth
def customer_contracts(customer_id: int):
    """
    Get all contracts for a customer.
    """
    contracts = execute_kelava_query(
        """
        SELECT 
            k.id,
            k.no_kontrak,
            k.start_date,
            k.end_date,
            k.is_active,
            k.kode_akses,
            (k.end_date - CURRENT_DATE) as days_remaining,
            CASE 
                WHEN CURRENT_DATE > k.end_date THEN 'expired'
                WHEN CURRENT_DATE BETWEEN k.start_date AND k.end_date THEN 'active'
                ELSE 'future'
            END as status_computed
        FROM m_customer_kontrak k
        WHERE k.id_customer = %s
        ORDER BY k.end_date DESC
    """,
        (customer_id,),
        user_id=_auth_user_id(),
    )

    # Format dates
    formatted = []
    for row in contracts:
        contract = dict(row)
        if contract.get("start_date"):
            contract["start_date"] = contract["start_date"].isoformat()
        if contract.get("end_date"):
            contract["end_date"] = contract["end_date"].isoformat()
        formatted.append(contract)

    return jsonify(
        {
            "customer_id": customer_id,
            "count": len(formatted),
            "contracts": formatted,
            "generated_at": datetime.now().isoformat(),
        }
    )


@customers_bp.route("/customers/segments")
@require_auth
def customer_segments():
    """
    Get list of customer segments for filtering.
    Note: m_segment table doesn't exist so returning empty list.
    """
    return jsonify(
        {
            "segments": [],
            "generated_at": datetime.now().isoformat(),
        }
    )
