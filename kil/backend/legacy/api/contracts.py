"""
Contract Management API
========================
SAP-Grade contract lifecycle management.
Handles contract listing, detail, renewal alerts, and area/subarea mapping.
"""

from datetime import datetime

from flask import Blueprint, g, jsonify, request
from core.security import require_auth, require_role

from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single
from kil.backend.legacy.api.audit_log import log_action

contracts_bp = Blueprint("contracts", __name__, url_prefix="/contracts")


def _auth_user_id() -> str | None:
    user = getattr(g, "user", None)
    return str(user.id) if user else None


def _fmt(row):
    """Format a row dict, converting date/datetime to ISO strings."""
    item = dict(row)
    for k, v in item.items():
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    return item


# ── Dashboard ────────────────────────────────────────────────


@contracts_bp.route("/dashboard", methods=["GET"])
@require_auth
def contract_dashboard():
    """
    Contract portfolio overview.
    Returns summary metrics, renewal pipeline, and expiry breakdown.
    """
    uid = _auth_user_id()

    stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) as total_contracts,
            COUNT(*) FILTER (
                WHERE UPPER(TRIM(COALESCE(is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
                  AND CURRENT_DATE BETWEEN start_date AND end_date
            ) as active_contracts,
            COUNT(*) FILTER (WHERE end_date < CURRENT_DATE) as expired_contracts,
            COUNT(*) FILTER (WHERE start_date > CURRENT_DATE) as future_contracts,
            COUNT(*) FILTER (
                WHERE end_date >= CURRENT_DATE
                  AND end_date <= CURRENT_DATE + INTERVAL '30 days'
            ) as expiring_30d,
            COUNT(*) FILTER (
                WHERE end_date >= CURRENT_DATE
                  AND end_date <= CURRENT_DATE + INTERVAL '60 days'
            ) as expiring_60d,
            COUNT(*) FILTER (
                WHERE end_date >= CURRENT_DATE
                  AND end_date <= CURRENT_DATE + INTERVAL '90 days'
            ) as expiring_90d,
            COUNT(DISTINCT id_customer) as unique_customers
        FROM m_customer_kontrak
        """,
        user_id=uid,
    )

    # Renewal pipeline (next 90 days with customer info)
    pipeline = execute_kelava_query(
        """
        SELECT
            k.id, k.no_kontrak, k.start_date, k.end_date,
            (k.end_date - CURRENT_DATE) as days_remaining,
            c.id as customer_id, c.name as customer_name, c.phone1,
            CASE
                WHEN (k.end_date - CURRENT_DATE) <= 30 THEN 'CRITICAL'
                WHEN (k.end_date - CURRENT_DATE) <= 60 THEN 'WARNING'
                ELSE 'UPCOMING'
            END as urgency
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        WHERE k.end_date >= CURRENT_DATE
          AND k.end_date <= CURRENT_DATE + INTERVAL '90 days'
          AND UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
        ORDER BY k.end_date ASC
        """,
        user_id=uid,
    )

    # Recently expired (last 90 days)
    recently_expired = execute_kelava_query(
        """
        SELECT
            k.id, k.no_kontrak, k.start_date, k.end_date,
            (CURRENT_DATE - k.end_date) as days_since_expired,
            c.id as customer_id, c.name as customer_name
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        WHERE k.end_date < CURRENT_DATE
          AND k.end_date >= CURRENT_DATE - INTERVAL '90 days'
        ORDER BY k.end_date DESC
        LIMIT 20
        """,
        user_id=uid,
    )

    return jsonify({
        "stats": _fmt(stats) if stats else {},
        "renewal_pipeline": [_fmt(r) for r in pipeline],
        "recently_expired": [_fmt(r) for r in recently_expired],
        "generated_at": datetime.now().isoformat(),
    })


# ── Contract List ────────────────────────────────────────────


@contracts_bp.route("", methods=["GET"])
@require_auth
def list_contracts():
    """
    List all contracts with search and filters.

    Query params:
        search: Search by contract name, customer name
        status: active, expired, expiring_30d, expiring_60d
        page, per_page: Pagination
    """
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 25)), 100)
    offset = (page - 1) * per_page
    uid = _auth_user_id()

    where_clauses = ["1=1"]
    params = []

    if search:
        where_clauses.append("(k.no_kontrak ILIKE %s OR c.name ILIKE %s)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern])

    if status_filter == "active":
        where_clauses.append("""
            UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
            AND CURRENT_DATE BETWEEN k.start_date AND k.end_date
        """)
    elif status_filter == "expired":
        where_clauses.append("k.end_date < CURRENT_DATE")
    elif status_filter == "expiring_30d":
        where_clauses.append("""
            k.end_date >= CURRENT_DATE
            AND k.end_date <= CURRENT_DATE + INTERVAL '30 days'
        """)
    elif status_filter == "expiring_60d":
        where_clauses.append("""
            k.end_date >= CURRENT_DATE
            AND k.end_date <= CURRENT_DATE + INTERVAL '60 days'
        """)

    where_sql = " AND ".join(where_clauses)
    params.extend([per_page, offset])

    contracts = execute_kelava_query(
        f"""
        SELECT
            k.id, k.no_kontrak, k.start_date, k.end_date, k.is_active,
            k.kode_akses, k.created_time,
            (k.end_date - CURRENT_DATE) as days_remaining,
            c.id as customer_id, c.name as customer_name, c.code as customer_code,
            c.phone1, c.address,
            CASE
                WHEN UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
                     AND CURRENT_DATE BETWEEN k.start_date AND k.end_date THEN 'ACTIVE'
                WHEN k.end_date < CURRENT_DATE THEN 'EXPIRED'
                WHEN k.start_date > CURRENT_DATE THEN 'FUTURE'
                ELSE 'INACTIVE'
            END as status_computed,
            CASE
                WHEN k.end_date >= CURRENT_DATE AND k.end_date <= CURRENT_DATE + INTERVAL '30 days' THEN 'CRITICAL'
                WHEN k.end_date >= CURRENT_DATE AND k.end_date <= CURRENT_DATE + INTERVAL '60 days' THEN 'WARNING'
                WHEN k.end_date >= CURRENT_DATE AND k.end_date <= CURRENT_DATE + INTERVAL '90 days' THEN 'UPCOMING'
                ELSE NULL
            END as renewal_urgency,
            (SELECT COUNT(*) FROM m_customer_kontrak_area ka WHERE ka.id_kontrak = k.id) as area_count
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        WHERE {where_sql}
        ORDER BY
            CASE
                WHEN CURRENT_DATE BETWEEN k.start_date AND k.end_date THEN 1
                WHEN k.end_date >= CURRENT_DATE THEN 2
                ELSE 3
            END,
            k.end_date ASC
        LIMIT %s OFFSET %s
        """,
        tuple(params),
        user_id=uid,
    )

    count_params = params[:-2]
    total = execute_kelava_query_single(
        f"""
        SELECT COUNT(*) as total
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        WHERE {where_sql}
        """,
        tuple(count_params) if count_params else None,
        user_id=uid,
    )

    return jsonify({
        "contracts": [_fmt(c) for c in contracts],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total["total"] if total else 0,
        },
        "generated_at": datetime.now().isoformat(),
    })


# ── Contract Detail ──────────────────────────────────────────


@contracts_bp.route("/<int:contract_id>", methods=["GET"])
@require_auth
def contract_detail(contract_id: int):
    """
    Full contract detail with areas, subareas, and service history.
    """
    uid = _auth_user_id()

    contract = execute_kelava_query_single(
        """
        SELECT
            k.*, c.name as customer_name, c.code as customer_code,
            c.phone1, c.address, c.email,
            (k.end_date - CURRENT_DATE) as days_remaining,
            CASE
                WHEN UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
                     AND CURRENT_DATE BETWEEN k.start_date AND k.end_date THEN 'ACTIVE'
                WHEN k.end_date < CURRENT_DATE THEN 'EXPIRED'
                WHEN k.start_date > CURRENT_DATE THEN 'FUTURE'
                ELSE 'INACTIVE'
            END as status_computed
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        WHERE k.id = %s
        """,
        (contract_id,),
        user_id=uid,
    )

    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    # Areas with treatments
    areas = execute_kelava_query(
        """
        SELECT
            ka.id, ka.area, ka.treatment, ka.treatment_text,
            (SELECT COUNT(*) FROM m_customer_kontrak_subarea ks WHERE ks.id_kontrak_area = ka.id) as subarea_count
        FROM m_customer_kontrak_area ka
        WHERE ka.id_kontrak = %s
        ORDER BY ka.area
        """,
        (contract_id,),
        user_id=uid,
    )

    # Subareas (all for this contract)
    subareas = execute_kelava_query(
        """
        SELECT
            ks.id, ks.id_kontrak_area, ks.kode_unit, ks.sub_area, ks.qr_code,
            ka.area as parent_area, ka.treatment_text
        FROM m_customer_kontrak_subarea ks
        JOIN m_customer_kontrak_area ka ON ka.id = ks.id_kontrak_area
        WHERE ka.id_kontrak = %s
        ORDER BY ka.area, ks.kode_unit
        """,
        (contract_id,),
        user_id=uid,
    )

    # Recent visits for this customer under contract period
    customer_id = contract["id_customer"]
    visits = execute_kelava_query(
        """
        SELECT
            v.id, v.realization_date, v.check_in, v.check_out,
            ROUND(EXTRACT(EPOCH FROM (v.check_out - v.check_in))::numeric / 60, 1) as duration_min,
            rp.status, rp.type as service_type,
            u.fullname as tech_name
        FROM t_visit v
        JOIN t_road_plan rp ON rp.id = v.id_road_plan
        LEFT JOIN p_user u ON u.id = rp.id_user
        WHERE rp.id_customer = %s
          AND v.realization_date >= %s
        ORDER BY v.realization_date DESC
        LIMIT 20
        """,
        (customer_id, contract["start_date"]),
        user_id=uid,
    )

    # Renewal log (from winback/governance if available)
    renewal_notes = execute_kelava_query(
        """
        SELECT *
        FROM contract_renewal_log
        WHERE contract_id = %s
        ORDER BY created_at DESC
        """,
        (contract_id,),
        user_id=uid,
    ) if _table_exists("contract_renewal_log") else []

    # Churn reasons
    churn_reasons = []
    if _table_exists("contract_churn_reasons"):
        churn_reasons = execute_kelava_query(
            """
            SELECT cr.*, eu.full_name as decided_by_name
            FROM contract_churn_reasons cr
            LEFT JOIN enterprise_users eu ON eu.id = cr.decided_by
            WHERE cr.contract_id = %s
            ORDER BY cr.decided_at DESC
            """,
            (contract_id,),
            user_id=uid,
        )

    # Customer complaints during contract period
    customer_complaints = execute_kelava_query(
        """
        SELECT
            co.id, co.complaint_date, co.severity, co.category,
            co.description, co.status, co.resolution_note,
            u_tech.fullname as technician_name
        FROM complaints co
        LEFT JOIN p_user u_tech ON u_tech.id = co.technician_id
        WHERE co.customer_id = %s
        ORDER BY co.complaint_date DESC
        LIMIT 20
        """,
        (customer_id,),
        user_id=uid,
    ) if _table_exists("complaints") else []

    return jsonify({
        "contract": _fmt(contract),
        "areas": [_fmt(a) for a in areas],
        "subareas": [_fmt(s) for s in subareas],
        "recent_visits": [_fmt(v) for v in visits],
        "renewal_notes": [_fmt(n) for n in renewal_notes],
        "churn_reasons": [_fmt(r) for r in churn_reasons],
        "customer_complaints": [_fmt(c) for c in customer_complaints],
        "generated_at": datetime.now().isoformat(),
    })


def _table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    result = execute_kelava_query_single(
        """
        SELECT COUNT(*) as cnt FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,),
    )
    return result and result["cnt"] > 0


# ── Renewal Management ───────────────────────────────────────


@contracts_bp.route("/<int:contract_id>/renewal-note", methods=["POST"])
@require_auth
def add_renewal_note(contract_id: int):
    """
    Add a renewal tracking note to a contract.
    Body: { action, note, next_follow_up? }
    Actions: RENEWAL_INITIATED, CUSTOMER_CONTACTED, QUOTE_SENT, RENEWAL_CONFIRMED, RENEWAL_DECLINED
    """
    data = request.json or {}
    action = data.get("action")
    note = data.get("note")
    next_follow_up = data.get("next_follow_up")
    uid = _auth_user_id()

    if not action or not note:
        return jsonify({"error": "action and note are required"}), 400

    valid_actions = {
        "RENEWAL_INITIATED", "CUSTOMER_CONTACTED", "QUOTE_SENT",
        "RENEWAL_CONFIRMED", "RENEWAL_DECLINED", "NOTE"
    }
    if action not in valid_actions:
        return jsonify({"error": f"Invalid action. Must be one of: {', '.join(sorted(valid_actions))}"}), 400

    # Ensure contract exists
    contract = execute_kelava_query_single(
        "SELECT id FROM m_customer_kontrak WHERE id = %s", (contract_id,), user_id=uid,
    )
    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    # Ensure renewal log table exists
    _ensure_renewal_log_table()

    # Insert note
    result = execute_kelava_query_single(
        """
        INSERT INTO contract_renewal_log
            (contract_id, action, note, next_follow_up, actor_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (contract_id, action, note, next_follow_up, uid),
        user_id=uid,
    )

    log_action("contracts", "create", "renewal_note", contract_id, f"{action}: {note}")
    return jsonify({
        "message": "Renewal note added",
        "note": _fmt(result) if result else {},
    }), 201


def _ensure_renewal_log_table():
    """Create contract_renewal_log if it doesn't exist."""
    if not _table_exists("contract_renewal_log"):
        execute_kelava_query("""
            CREATE TABLE IF NOT EXISTS contract_renewal_log (
                id BIGSERIAL PRIMARY KEY,
                contract_id INTEGER NOT NULL,
                action VARCHAR(50) NOT NULL,
                note TEXT,
                next_follow_up DATE,
                actor_id VARCHAR(100),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        execute_kelava_query(
            "CREATE INDEX IF NOT EXISTS idx_renewal_log_contract ON contract_renewal_log(contract_id)"
        )


# ── Renewal Alerts (Cron-friendly) ──────────────────────────


# ── Churn Reason Management ──────────────────────────────────


@contracts_bp.route("/<int:contract_id>/churn-reason", methods=["GET"])
@require_auth
def get_churn_reasons(contract_id: int):
    """Get churn/non-renewal reasons for a contract."""
    uid = _auth_user_id()

    reasons = execute_kelava_query(
        """
        SELECT
            cr.*,
            eu.full_name as decided_by_name
        FROM contract_churn_reasons cr
        LEFT JOIN enterprise_users eu ON eu.id = cr.decided_by
        WHERE cr.contract_id = %s
        ORDER BY cr.decided_at DESC
        """,
        (contract_id,),
        user_id=uid,
    )

    return jsonify({
        "contract_id": contract_id,
        "churn_reasons": [_fmt(r) for r in reasons],
        "generated_at": datetime.now().isoformat(),
    })


@contracts_bp.route("/<int:contract_id>/churn-reason", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def add_churn_reason(contract_id: int):
    """
    Add a churn/non-renewal reason to a contract.

    Body: {
        reason_category: "service_quality"|"price"|"competitor"|"business_closed"|"relocation"|"other",
        reason_detail?: string,
        linked_complaint_ids?: [int],
        notes?: string
    }
    """
    data = request.json or {}
    uid = _auth_user_id()
    user = getattr(g, "user", None)

    category = (data.get("reason_category") or "").lower()
    valid_categories = {
        "service_quality", "price", "competitor",
        "business_closed", "relocation", "other",
    }
    if category not in valid_categories:
        return jsonify({
            "error": f"reason_category must be one of: {', '.join(sorted(valid_categories))}"
        }), 400

    # Verify contract exists
    contract = execute_kelava_query_single(
        "SELECT id FROM m_customer_kontrak WHERE id = %s",
        (contract_id,),
        user_id=uid,
    )
    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    complaint_ids = data.get("linked_complaint_ids") or []

    result = execute_kelava_query_single(
        """
        INSERT INTO contract_churn_reasons
            (contract_id, reason_category, reason_detail, linked_complaint_ids,
             decided_by, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            contract_id,
            category,
            data.get("reason_detail"),
            complaint_ids if complaint_ids else None,
            user.id if user else None,
            data.get("notes"),
        ),
        user_id=uid,
    )

    log_action("contracts", "create", "churn_reason", contract_id, f"Churn: {category} - {data.get('reason_detail', '')}")
    return jsonify({
        "message": "Churn reason added",
        "churn_reason": _fmt(result) if result else {},
    }), 201


@contracts_bp.route("/<int:contract_id>/churn-reason/<int:reason_id>", methods=["DELETE"])
@require_auth
@require_role("admin", "koordinator")
def delete_churn_reason(contract_id: int, reason_id: int):
    """Delete a churn reason."""
    uid = _auth_user_id()

    execute_kelava_query(
        "DELETE FROM contract_churn_reasons WHERE id = %s AND contract_id = %s",
        (reason_id, contract_id),
        user_id=uid,
    )

    return jsonify({"message": "Churn reason deleted"})


# ── Linked Complaints ──────────────────────────────────────


@contracts_bp.route("/<int:contract_id>/complaints", methods=["GET"])
@require_auth
def contract_complaints(contract_id: int):
    """
    Get complaints related to this contract's customer.
    Used for renewal review — shows complaint history during contract period.
    """
    uid = _auth_user_id()

    # Get contract to find customer_id and dates
    contract = execute_kelava_query_single(
        "SELECT id, id_customer, start_date, end_date FROM m_customer_kontrak WHERE id = %s",
        (contract_id,),
        user_id=uid,
    )
    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    customer_id = contract["id_customer"]

    complaints = execute_kelava_query(
        """
        SELECT
            co.id, co.complaint_date, co.severity, co.category,
            co.description, co.status, co.resolution_note,
            co.resolved_at,
            u_tech.fullname as technician_name
        FROM complaints co
        LEFT JOIN p_user u_tech ON u_tech.id = co.technician_id
        WHERE co.customer_id = %s
        ORDER BY co.complaint_date DESC
        """,
        (customer_id,),
        user_id=uid,
    )

    return jsonify({
        "contract_id": contract_id,
        "customer_id": customer_id,
        "complaints": [_fmt(c) for c in complaints],
        "total": len(complaints),
        "by_severity": {
            "critical": sum(1 for c in complaints if c.get("severity") == "CRITICAL"),
            "major": sum(1 for c in complaints if c.get("severity") == "MAJOR"),
            "minor": sum(1 for c in complaints if c.get("severity") == "MINOR"),
        },
        "generated_at": datetime.now().isoformat(),
    })


# ── Renewal Alerts (Cron-friendly) ──────────────────────────


@contracts_bp.route("/alerts", methods=["GET"])
@require_auth
def renewal_alerts():
    """
    Get contracts requiring renewal action.
    Grouped by urgency tier.
    """
    uid = _auth_user_id()

    alerts = execute_kelava_query(
        """
        SELECT
            k.id, k.no_kontrak, k.start_date, k.end_date,
            (k.end_date - CURRENT_DATE) as days_remaining,
            c.id as customer_id, c.name as customer_name, c.phone1,
            CASE
                WHEN (k.end_date - CURRENT_DATE) <= 0 THEN 'EXPIRED'
                WHEN (k.end_date - CURRENT_DATE) <= 30 THEN 'CRITICAL'
                WHEN (k.end_date - CURRENT_DATE) <= 60 THEN 'WARNING'
                WHEN (k.end_date - CURRENT_DATE) <= 90 THEN 'UPCOMING'
                ELSE 'OK'
            END as urgency,
            -- Check if any renewal note exists
            EXISTS(
                SELECT 1 FROM contract_renewal_log rl
                WHERE rl.contract_id = k.id
            ) as has_renewal_activity
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        WHERE k.end_date >= CURRENT_DATE - INTERVAL '30 days'
          AND k.end_date <= CURRENT_DATE + INTERVAL '90 days'
          AND UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
        ORDER BY k.end_date ASC
        """,
        user_id=uid,
    ) if _table_exists("contract_renewal_log") else execute_kelava_query(
        """
        SELECT
            k.id, k.no_kontrak, k.start_date, k.end_date,
            (k.end_date - CURRENT_DATE) as days_remaining,
            c.id as customer_id, c.name as customer_name, c.phone1,
            CASE
                WHEN (k.end_date - CURRENT_DATE) <= 0 THEN 'EXPIRED'
                WHEN (k.end_date - CURRENT_DATE) <= 30 THEN 'CRITICAL'
                WHEN (k.end_date - CURRENT_DATE) <= 60 THEN 'WARNING'
                WHEN (k.end_date - CURRENT_DATE) <= 90 THEN 'UPCOMING'
                ELSE 'OK'
            END as urgency,
            FALSE as has_renewal_activity
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        WHERE k.end_date >= CURRENT_DATE - INTERVAL '30 days'
          AND k.end_date <= CURRENT_DATE + INTERVAL '90 days'
          AND UPPER(TRIM(COALESCE(k.is_active, ''))) IN ('YES','ACTIVE','Y','1','TRUE')
        ORDER BY k.end_date ASC
        """,
        user_id=uid,
    )

    return jsonify({
        "alerts": [_fmt(a) for a in alerts],
        "generated_at": datetime.now().isoformat(),
    })


# ── Contract Lifecycle Transitions ───────────────────────────


@contracts_bp.route("/<int:contract_id>/extend", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def extend_contract(contract_id: int):
    """
    Extend a contract's end date.
    Body: { new_end_date: "YYYY-MM-DD", note?: str }
    """
    data = request.json or {}
    new_end = data.get("new_end_date")
    note = data.get("note", "")
    uid = _auth_user_id()

    if not new_end:
        return jsonify({"error": "new_end_date is required (YYYY-MM-DD)"}), 400

    contract = execute_kelava_query_single(
        "SELECT id, end_date, no_kontrak FROM m_customer_kontrak WHERE id = %s",
        (contract_id,), user_id=uid,
    )
    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    old_end = contract["end_date"]
    execute_kelava_query(
        "UPDATE m_customer_kontrak SET end_date = %s WHERE id = %s",
        (new_end, contract_id), user_id=uid,
    )

    # Log renewal note
    _ensure_renewal_log_table()
    execute_kelava_query(
        """
        INSERT INTO contract_renewal_log (contract_id, action, note, actor_id)
        VALUES (%s, 'CONTRACT_EXTENDED', %s, %s)
        """,
        (contract_id, f"Extended from {old_end} to {new_end}. {note}".strip(), uid),
        user_id=uid,
    )

    log_action("contracts", "update", "contract", contract_id,
               f"Extended {contract['no_kontrak']} from {old_end} to {new_end}")

    return jsonify({"message": "Contract extended", "old_end_date": str(old_end), "new_end_date": new_end})


@contracts_bp.route("/<int:contract_id>/terminate", methods=["POST"])
@require_auth
@require_role("admin", "koordinator")
def terminate_contract(contract_id: int):
    """
    Early terminate a contract.
    Body: { reason_category: str, reason_detail?: str, note?: str }
    """
    data = request.json or {}
    reason_cat = data.get("reason_category", "other")
    reason_detail = data.get("reason_detail", "")
    note = data.get("note", "")
    uid = _auth_user_id()

    contract = execute_kelava_query_single(
        "SELECT id, end_date, no_kontrak FROM m_customer_kontrak WHERE id = %s",
        (contract_id,), user_id=uid,
    )
    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    # Set end_date to today (early termination)
    execute_kelava_query(
        "UPDATE m_customer_kontrak SET end_date = CURRENT_DATE, is_active = 'NO' WHERE id = %s",
        (contract_id,), user_id=uid,
    )

    # Add churn reason
    execute_kelava_query(
        """
        INSERT INTO contract_churn_reasons (contract_id, reason_category, reason_detail, decided_by, notes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (contract_id, reason_cat, reason_detail, uid, f"Early termination. {note}".strip()),
        user_id=uid,
    )

    _ensure_renewal_log_table()
    execute_kelava_query(
        """
        INSERT INTO contract_renewal_log (contract_id, action, note, actor_id)
        VALUES (%s, 'CONTRACT_TERMINATED', %s, %s)
        """,
        (contract_id, f"Terminated. Reason: {reason_cat} - {reason_detail}. {note}".strip(), uid),
        user_id=uid,
    )

    log_action("contracts", "status_change", "contract", contract_id,
               f"Terminated {contract['no_kontrak']}: {reason_cat}")

    return jsonify({"message": "Contract terminated", "effective_date": str(datetime.now().date())})


# ── Contract Health Score ────────────────────────────────────


@contracts_bp.route("/<int:contract_id>/health", methods=["GET"])
@require_auth
def contract_health(contract_id: int):
    """
    Calculate a contract health score based on visit completion,
    complaint frequency, and renewal engagement.
    """
    uid = _auth_user_id()

    contract = execute_kelava_query_single(
        """
        SELECT k.id, k.id_customer, k.start_date, k.end_date, k.no_kontrak,
               (k.end_date - CURRENT_DATE) AS days_remaining
        FROM m_customer_kontrak k WHERE k.id = %s
        """,
        (contract_id,), user_id=uid,
    )
    if not contract:
        return jsonify({"error": "Contract not found"}), 404

    cid = contract["id_customer"]

    # Visit completion rate (last 90 days)
    visit_stats = execute_kelava_query_single(
        """
        SELECT
            COUNT(*) AS total_planned,
            COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS completed,
            COUNT(*) FILTER (WHERE rp.status NOT IN ('Selesai', 'Berjalan')) AS missed
        FROM t_road_plan rp
        WHERE rp.id_customer = %s
          AND rp.visit_date >= CURRENT_DATE - INTERVAL '90 days'
        """,
        (cid,), user_id=uid,
    )

    # Complaint count (last 6 months)
    complaint_count = execute_kelava_query_single(
        """
        SELECT COUNT(*) AS cnt
        FROM complaint_tickets
        WHERE customer_id = %s AND created_at >= NOW() - INTERVAL '6 months'
        """,
        (cid,), user_id=uid,
    )

    # Calculate score (0-100)
    planned = (visit_stats["total_planned"] or 0) if visit_stats else 0
    completed = (visit_stats["completed"] or 0) if visit_stats else 0
    complaints = (complaint_count["cnt"] or 0) if complaint_count else 0

    visit_score = (completed / planned * 60) if planned > 0 else 60  # 60% weight
    complaint_penalty = min(complaints * 5, 30)  # Max 30 point penalty
    days_rem = contract["days_remaining"] or 0
    tenure_bonus = 10 if days_rem > 180 else (5 if days_rem > 90 else 0)

    health_score = max(0, min(100, round(visit_score - complaint_penalty + tenure_bonus)))

    health_grade = "A" if health_score >= 80 else "B" if health_score >= 60 else "C" if health_score >= 40 else "D"

    return jsonify({
        "contract_id": contract_id,
        "health_score": health_score,
        "health_grade": health_grade,
        "factors": {
            "visit_completion": {"planned": planned, "completed": completed, "score_contribution": round(visit_score, 1)},
            "complaints": {"count_6m": complaints, "penalty": complaint_penalty},
            "tenure": {"days_remaining": days_rem, "bonus": tenure_bonus},
        },
    })
