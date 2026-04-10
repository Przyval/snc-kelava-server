"""
Customers & Contracts Write API
=================================
Create and manage customers and contracts in SanoCare's own DB.
Reads merge SNC + Kelava; writes go to snc_customers / snc_contracts.
"""

from flask import Blueprint, jsonify, request
from core.security import require_auth

from kil.db.kelava_db import _get_local_pool, execute_kelava_query

customers_write_bp = Blueprint("customers_write", __name__)


def _dict_row(cursor, row):
    if row is None:
        return None
    return dict(zip([d[0] for d in cursor.description], row))


def _require_role(*roles):
    user = getattr(request, "_jwt_user", None)
    if user and user.get("role") not in roles:
        return jsonify({"error": "Forbidden"}), 403
    return None


# ── Customers — List (merged) ─────────────────────────────────────────────────


@customers_write_bp.route("/customers/all")
@require_auth
def list_customers_merged():
    """
    Merged customer list: Kelava active + SNC new.

    Query params:
        q: search by name (optional)
        limit: int (default 100)
        source: 'all' | 'kelava' | 'snc'
    """
    q = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 100)), 500)
    source = request.args.get("source", "all")

    results = []

    if source in ("all", "kelava"):
        where = "WHERE is_deleted = false AND id_client = 111"
        params: list = []
        if q:
            where += " AND name ILIKE %s"
            params.append(f"%{q}%")
        rows = execute_kelava_query(
            f"""
            SELECT id, name, address, new_city, new_province,
                   phone1, email, contact_person_name, status
            FROM m_customer {where}
            ORDER BY name LIMIT {limit}
            """,
            params or None,
        )
        for r in rows:
            results.append({**r, "source": "kelava"})

    if source in ("all", "snc"):
        where_snc = "WHERE is_deleted = false"
        params_snc: list = []
        if q:
            where_snc += " AND name ILIKE %s"
            params_snc.append(f"%{q}%")
        with _get_local_pool().connection() as conn:
            with conn.cursor(row_factory=_dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT id, name, address, new_city, new_province,
                           phone1, email, contact_person_name, status, created_at
                    FROM snc_customers {where_snc}
                    ORDER BY name LIMIT %s
                    """,
                    [*params_snc, limit],
                )
                for r in cur.fetchall():
                    results.append({
                        **r,
                        "source": "snc",
                        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    })

    results.sort(key=lambda x: (x.get("name") or "").lower())
    return jsonify({"total": len(results), "customers": results})


# ── Customers — Create ────────────────────────────────────────────────────────


@customers_write_bp.route("/customers/create", methods=["POST"])
@require_auth
def create_customer():
    """
    Create new customer in SNC DB.

    Body (JSON):
        name: string (required)
        address: string
        new_city: string
        new_province: string
        phone1: string
        email: string
        contact_person_name: string
        contact_person_phone: string
        segment: string ('Mobile' | 'Station')
        status: string (default 'Active')
    """
    guard = _require_role("admin", "koordinator")
    if guard:
        return guard

    data = request.get_json(force=True)
    user = getattr(request, "_jwt_user", {})

    if not data.get("name", "").strip():
        return jsonify({"error": "name is required"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row) as cur:
            cur.execute(
                """
                INSERT INTO snc_customers
                    (name, address, new_city, new_province, phone1, phone2,
                     email, contact_person_name, contact_person_phone,
                     segment, status, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, name, status, created_at
                """,
                (
                    data["name"].strip(),
                    data.get("address"),
                    data.get("new_city"),
                    data.get("new_province"),
                    data.get("phone1"),
                    data.get("phone2"),
                    data.get("email"),
                    data.get("contact_person_name"),
                    data.get("contact_person_phone"),
                    data.get("segment"),
                    data.get("status", "Active"),
                    user.get("id", 0),
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return jsonify({
        "message": "Customer created",
        "id": row["id"],
        "name": row["name"],
        "source": "snc",
    }), 201


# ── Customers — Update ────────────────────────────────────────────────────────


@customers_write_bp.route("/customers/snc/<int:customer_id>", methods=["PUT"])
@require_auth
def update_snc_customer(customer_id: int):
    """Update a SNC customer record."""
    guard = _require_role("admin", "koordinator")
    if guard:
        return guard

    data = request.get_json(force=True)
    allowed = {"name", "address", "new_city", "new_province", "phone1",
               "phone2", "email", "contact_person_name", "contact_person_phone",
               "segment", "status"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400

    set_clauses = [f"{k} = %s" for k in updates] + ["updated_at = NOW()"]
    params = list(updates.values()) + [customer_id]

    with _get_local_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE snc_customers SET {', '.join(set_clauses)} WHERE id = %s RETURNING id",
                params,
            )
            if cur.rowcount == 0:
                return jsonify({"error": "Not found"}), 404
        conn.commit()

    return jsonify({"message": "Updated", "id": customer_id})


# ── Contracts — List (merged) ─────────────────────────────────────────────────


@customers_write_bp.route("/contracts/all")
@require_auth
def list_contracts_merged():
    """
    Merged contracts: Kelava + SNC.

    Query params:
        customer_id: int (optional, Kelava ID)
        snc_customer_id: int (optional, SNC ID)
        active_only: bool (default true)
        expiring_days: int — contracts expiring within N days
    """
    kelava_cust_id = request.args.get("customer_id")
    snc_cust_id = request.args.get("snc_customer_id")
    active_only = request.args.get("active_only", "true").lower() == "true"
    expiring_days = request.args.get("expiring_days")

    results = []

    # Kelava contracts
    where_k = "WHERE 1=1"
    params_k: list = []
    if active_only:
        where_k += " AND k.is_active = 'YES'"
    if kelava_cust_id:
        where_k += " AND k.id_customer = %s"
        params_k.append(int(kelava_cust_id))
    if expiring_days:
        where_k += " AND k.end_date <= CURRENT_DATE + %s"
        params_k.append(int(expiring_days))

    kelava_rows = execute_kelava_query(
        f"""
        SELECT k.id, k.no_kontrak, k.start_date, k.end_date, k.is_active,
               k.id_customer AS customer_id,
               c.name AS customer_name, c.new_city,
               k.end_date - CURRENT_DATE AS days_remaining
        FROM m_customer_kontrak k
        JOIN m_customer c ON c.id = k.id_customer
        {where_k}
        ORDER BY k.end_date
        """,
        params_k or None,
    )
    for r in kelava_rows:
        results.append({
            **r,
            "source": "kelava",
            "start_date": r["start_date"].isoformat() if r.get("start_date") else None,
            "end_date": r["end_date"].isoformat() if r.get("end_date") else None,
        })

    # SNC contracts
    where_s = "WHERE 1=1"
    params_s: list = []
    if active_only:
        where_s += " AND c.is_active = 'YES'"
    if snc_cust_id:
        where_s += " AND c.snc_customer_id = %s"
        params_s.append(int(snc_cust_id))
    if kelava_cust_id:
        where_s += " AND c.kelava_customer_id = %s"
        params_s.append(int(kelava_cust_id))
    if expiring_days:
        where_s += " AND c.end_date <= CURRENT_DATE + %s"
        params_s.append(int(expiring_days))

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row) as cur:
            cur.execute(
                f"""
                SELECT c.id, c.no_kontrak, c.start_date, c.end_date,
                       c.is_active, c.nilai_kontrak, c.frekuensi_visit,
                       c.snc_customer_id, c.kelava_customer_id,
                       sc.name AS customer_name, sc.new_city,
                       c.end_date - CURRENT_DATE AS days_remaining
                FROM snc_contracts c
                LEFT JOIN snc_customers sc ON sc.id = c.snc_customer_id
                {where_s}
                ORDER BY c.end_date
                """,
                params_s or None,
            )
            for r in cur.fetchall():
                results.append({
                    **r,
                    "source": "snc",
                    "start_date": r["start_date"].isoformat() if r.get("start_date") else None,
                    "end_date": r["end_date"].isoformat() if r.get("end_date") else None,
                    "nilai_kontrak": float(r["nilai_kontrak"]) if r.get("nilai_kontrak") else None,
                })

    results.sort(key=lambda x: x.get("end_date") or "")
    return jsonify({"total": len(results), "contracts": results})


# ── Contracts — Create ────────────────────────────────────────────────────────


@customers_write_bp.route("/contracts/create", methods=["POST"])
@require_auth
def create_contract():
    """
    Create new service contract.

    Body (JSON):
        no_kontrak: string (required)
        start_date: YYYY-MM-DD (required)
        end_date: YYYY-MM-DD (required)
        snc_customer_id: int (SNC customer, optional)
        kelava_customer_id: int (Kelava customer, optional)
        nilai_kontrak: float (optional)
        frekuensi_visit: int (visits per month, default 1)
        notes: string (optional)
    """
    guard = _require_role("admin", "koordinator")
    if guard:
        return guard

    data = request.get_json(force=True)
    user = getattr(request, "_jwt_user", {})

    required = ["no_kontrak", "start_date", "end_date"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400

    if not data.get("snc_customer_id") and not data.get("kelava_customer_id"):
        return jsonify({"error": "Either snc_customer_id or kelava_customer_id required"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row) as cur:
            cur.execute(
                """
                INSERT INTO snc_contracts
                    (no_kontrak, start_date, end_date, snc_customer_id,
                     kelava_customer_id, nilai_kontrak, frekuensi_visit,
                     notes, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, no_kontrak, start_date, end_date
                """,
                (
                    data["no_kontrak"].strip(),
                    data["start_date"],
                    data["end_date"],
                    data.get("snc_customer_id"),
                    data.get("kelava_customer_id"),
                    data.get("nilai_kontrak"),
                    data.get("frekuensi_visit", 1),
                    data.get("notes"),
                    user.get("id", 0),
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return jsonify({
        "message": "Contract created",
        "id": row["id"],
        "no_kontrak": row["no_kontrak"],
        "start_date": row["start_date"].isoformat(),
        "end_date": row["end_date"].isoformat(),
        "source": "snc",
    }), 201


# ── Contracts — Renew ─────────────────────────────────────────────────────────


@customers_write_bp.route("/contracts/snc/<int:contract_id>/renew", methods=["POST"])
@require_auth
def renew_contract(contract_id: int):
    """
    Renew a SNC contract — deactivate old, create new with updated dates.

    Body: new_start_date, new_end_date, nilai_kontrak (optional)
    """
    guard = _require_role("admin", "koordinator")
    if guard:
        return guard

    data = request.get_json(force=True)
    user = getattr(request, "_jwt_user", {})

    if not data.get("new_start_date") or not data.get("new_end_date"):
        return jsonify({"error": "new_start_date and new_end_date required"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row) as cur:
            # Get existing contract
            cur.execute("SELECT * FROM snc_contracts WHERE id = %s", (contract_id,))
            old = cur.fetchone()
            if not old:
                return jsonify({"error": "Contract not found"}), 404

            # Deactivate old
            cur.execute(
                "UPDATE snc_contracts SET is_active = 'NO', updated_at = NOW() WHERE id = %s",
                (contract_id,),
            )

            # Create renewal
            cur.execute(
                """
                INSERT INTO snc_contracts
                    (no_kontrak, start_date, end_date, snc_customer_id,
                     kelava_customer_id, nilai_kontrak, frekuensi_visit,
                     notes, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, no_kontrak, end_date
                """,
                (
                    old["no_kontrak"] + "-R",
                    data["new_start_date"],
                    data["new_end_date"],
                    old["snc_customer_id"],
                    old["kelava_customer_id"],
                    data.get("nilai_kontrak", old.get("nilai_kontrak")),
                    old.get("frekuensi_visit", 1),
                    f"Renewal dari kontrak #{contract_id}",
                    user.get("id", 0),
                ),
            )
            new = cur.fetchone()
        conn.commit()

    return jsonify({
        "message": "Contract renewed",
        "old_contract_id": contract_id,
        "new_contract_id": new["id"],
        "no_kontrak": new["no_kontrak"],
        "end_date": new["end_date"].isoformat(),
    }), 201


# ── Contracts — Update / Deactivate ──────────────────────────────────────────


@customers_write_bp.route("/contracts/snc/<int:contract_id>", methods=["PUT"])
@require_auth
def update_contract(contract_id: int):
    """Update a SNC contract (dates, nilai, notes, is_active)."""
    guard = _require_role("admin", "koordinator")
    if guard:
        return guard

    data = request.get_json(force=True)
    allowed = {"no_kontrak", "start_date", "end_date", "is_active",
               "nilai_kontrak", "frekuensi_visit", "notes"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400

    set_clauses = [f"{k} = %s" for k in updates] + ["updated_at = NOW()"]
    params = list(updates.values()) + [contract_id]

    with _get_local_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE snc_contracts SET {', '.join(set_clauses)} WHERE id = %s RETURNING id",
                params,
            )
            if cur.rowcount == 0:
                return jsonify({"error": "Not found"}), 404
        conn.commit()

    return jsonify({"message": "Updated", "id": contract_id})
