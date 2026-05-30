"""
Recurring Rules API — Phase 1
==============================
Manual rules per customer untuk override pattern detection.

Endpoints:
  GET    /recurring-rules                  List rules (filter: client_id, active_only, frequency, tech)
  GET    /recurring-rules/<id>             Get single rule with full context
  POST   /recurring-rules                  Create rule (koordinator/admin only)
  PUT    /recurring-rules/<id>             Update rule
  DELETE /recurring-rules/<id>             Soft-deactivate (set effective_end=today)
  GET    /recurring-rules/derive/<client_id>   Suggest rule dari pattern detected
  GET    /recurring-rules/log              Audit log (filter: rule_id, since)
  POST   /recurring-rules/bulk-import      Create banyak rules sekaligus
  GET    /recurring-rules/stats            Coverage stats (berapa customer punya rule)

Decisions locked 2026-05-30:
  - Permissions: Koordinator + Admin (field supervisor read-only)
  - Backup tech: Historical pairing (stable, no auto-rotation)
  - Conflict: Rule wins if is_mandatory=true
"""

from datetime import date, datetime
from flask import Blueprint, jsonify, request, g
from core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

recurring_rules_bp = Blueprint("recurring_rules", __name__,
                                url_prefix="/api/v1/enterprise/recurring-rules")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require_koordinator_or_admin():
    """Return (user_id, role) or (None, error_response)."""
    user = getattr(g, "current_user", None) or getattr(request, "_jwt_user", {})
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
    user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", 0)
    if role not in ("admin", "koordinator"):
        return None, (jsonify({"error": "Forbidden", "detail": "Koordinator atau Admin only"}), 403)
    return user_id, None


def _validate_rule_payload(data: dict) -> tuple[dict | None, str | None]:
    """Validate rule fields. Returns (cleaned, error) tuple."""
    if not data:
        return None, "Empty body"

    required = ["client_id", "primary_tech_id", "frequency", "weekdays", "time_start"]
    for f in required:
        if f not in data or data[f] in (None, "", []):
            return None, f"Missing required field: {f}"

    valid_freqs = ["weekly", "biweekly", "monthly", "custom"]
    if data["frequency"] not in valid_freqs:
        return None, f"Invalid frequency. Must be one of: {valid_freqs}"

    weekdays = data["weekdays"]
    if not isinstance(weekdays, list) or not all(isinstance(w, int) and 0 <= w <= 6 for w in weekdays):
        return None, "weekdays must be array of integers 0-6 (Mon=0..Sun=6)"

    return {
        "client_id":        int(data["client_id"]),
        "primary_tech_id":  int(data["primary_tech_id"]),
        "backup_tech_1_id": int(data["backup_tech_1_id"]) if data.get("backup_tech_1_id") else None,
        "backup_tech_2_id": int(data["backup_tech_2_id"]) if data.get("backup_tech_2_id") else None,
        "frequency":        data["frequency"],
        "weekdays":         weekdays,
        "week_pattern":     data.get("week_pattern"),
        "time_start":       data["time_start"],
        "time_end":         data.get("time_end"),
        "visit_type":       data.get("visit_type"),
        "is_mandatory":     bool(data.get("is_mandatory", True)),
        "suppress_holiday": bool(data.get("suppress_holiday", True)),
        "duration_minutes": data.get("duration_minutes"),
        "notes":            data.get("notes"),
        "effective_start":  data.get("effective_start") or date.today().isoformat(),
        "effective_end":    data.get("effective_end"),
    }, None


def _log_change(cur, rule_id: int, action: str, changed_fields: dict,
                reason: str, user_id: int):
    """Insert audit log entry."""
    import json
    cur.execute("""
        INSERT INTO snc_recurring_rule_log
            (rule_id, action, changed_fields, reason, changed_by)
        VALUES (%s, %s, %s::jsonb, %s, %s)
    """, (rule_id, action, json.dumps(changed_fields), reason, user_id))


# ─────────────────────────────────────────────────────────────────────────────
# GET /recurring-rules — list with filters
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("", methods=["GET"])
@require_auth
def list_rules():
    """
    Query params:
      client_id     filter by customer
      active_only   true/false (default true)
      frequency     weekly|biweekly|monthly|custom
      tech_id       primary or backup
      search        client name LIKE
      limit         default 100
      offset        default 0
    """
    client_id = request.args.get("client_id", type=int)
    active_only = request.args.get("active_only", "true").lower() == "true"
    frequency = request.args.get("frequency")
    tech_id = request.args.get("tech_id", type=int)
    search = request.args.get("search", "").strip()
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))

    where = ["1=1"]
    params = []
    if client_id:
        where.append("r.client_id = %s")
        params.append(client_id)
    if active_only:
        where.append("(r.effective_end IS NULL OR r.effective_end >= CURRENT_DATE)")
    if frequency:
        where.append("r.frequency = %s")
        params.append(frequency)
    if tech_id:
        where.append("(r.primary_tech_id = %s OR r.backup_tech_1_id = %s OR r.backup_tech_2_id = %s)")
        params.extend([tech_id, tech_id, tech_id])
    if search:
        where.append("c.name ILIKE %s")
        params.append(f"%{search}%")

    sql = f"""
        SELECT r.*, c.name as client_name,
               t1.name as primary_tech_name,
               t2.name as backup_tech_1_name,
               t3.name as backup_tech_2_name
        FROM snc_recurring_rules r
        JOIN snc_clients c ON c.id = r.client_id
        LEFT JOIN snc_technicians t1 ON t1.id = r.primary_tech_id
        LEFT JOIN snc_technicians t2 ON t2.id = r.backup_tech_1_id
        LEFT JOIN snc_technicians t3 ON t3.id = r.backup_tech_2_id
        WHERE {' AND '.join(where)}
        ORDER BY c.name
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rules = cur.fetchall()
            # Count
            count_sql = f"""
                SELECT COUNT(*) as n FROM snc_recurring_rules r
                JOIN snc_clients c ON c.id=r.client_id
                WHERE {' AND '.join(where[:len(where)])}
            """
            cur.execute(count_sql, params[:-2])
            total = cur.fetchone()["n"]

    # Serialize
    days_short = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    for r in rules:
        r["weekdays_display"] = "+".join(days_short[d] for d in (r["weekdays"] or []))
        # Convert time/date to strings for JSON
        if r.get("time_start"):
            r["time_start"] = r["time_start"].strftime("%H:%M")
        if r.get("time_end"):
            r["time_end"] = r["time_end"].strftime("%H:%M")
        for f in ["effective_start", "effective_end", "created_at", "updated_at"]:
            if r.get(f):
                r[f] = r[f].isoformat() if hasattr(r[f], "isoformat") else str(r[f])

    return jsonify({
        "total": total,
        "limit": limit,
        "offset": offset,
        "rules": rules,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /recurring-rules/<id> — single rule
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/<int:rule_id>", methods=["GET"])
@require_auth
def get_rule(rule_id):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT r.*, c.name as client_name,
                       t1.name as primary_tech_name,
                       t2.name as backup_tech_1_name,
                       t3.name as backup_tech_2_name
                FROM snc_recurring_rules r
                JOIN snc_clients c ON c.id = r.client_id
                LEFT JOIN snc_technicians t1 ON t1.id = r.primary_tech_id
                LEFT JOIN snc_technicians t2 ON t2.id = r.backup_tech_1_id
                LEFT JOIN snc_technicians t3 ON t3.id = r.backup_tech_2_id
                WHERE r.id = %s
            """, (rule_id,))
            rule = cur.fetchone()
            if not rule:
                return jsonify({"error": "Rule not found"}), 404

            # Recent log
            cur.execute("""
                SELECT * FROM snc_recurring_rule_log
                WHERE rule_id = %s
                ORDER BY changed_at DESC LIMIT 10
            """, (rule_id,))
            log = cur.fetchall()

    # Serialize
    days_short = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    rule["weekdays_display"] = "+".join(days_short[d] for d in (rule["weekdays"] or []))
    if rule.get("time_start"):
        rule["time_start"] = rule["time_start"].strftime("%H:%M")
    if rule.get("time_end"):
        rule["time_end"] = rule["time_end"].strftime("%H:%M")
    for f in ["effective_start", "effective_end", "created_at", "updated_at"]:
        if rule.get(f):
            rule[f] = rule[f].isoformat() if hasattr(rule[f], "isoformat") else str(rule[f])
    for entry in log:
        entry["changed_at"] = entry["changed_at"].isoformat()

    return jsonify({"rule": rule, "audit_log": log})


# ─────────────────────────────────────────────────────────────────────────────
# POST /recurring-rules — create
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("", methods=["POST"])
@require_auth
def create_rule():
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden

    cleaned, error = _validate_rule_payload(request.get_json() or {})
    if error:
        return jsonify({"error": error}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            try:
                cur.execute("""
                    INSERT INTO snc_recurring_rules
                        (client_id, primary_tech_id, backup_tech_1_id, backup_tech_2_id,
                         frequency, weekdays, week_pattern,
                         time_start, time_end, visit_type,
                         is_mandatory, suppress_holiday, duration_minutes,
                         notes, effective_start, effective_end, created_by)
                    VALUES (%(client_id)s, %(primary_tech_id)s, %(backup_tech_1_id)s, %(backup_tech_2_id)s,
                            %(frequency)s, %(weekdays)s, %(week_pattern)s,
                            %(time_start)s, %(time_end)s, %(visit_type)s,
                            %(is_mandatory)s, %(suppress_holiday)s, %(duration_minutes)s,
                            %(notes)s, %(effective_start)s, %(effective_end)s, %(user_id)s)
                    RETURNING id
                """, {**cleaned, "user_id": user_id})
                rule_id = cur.fetchone()["id"]
                _log_change(cur, rule_id, "created", cleaned,
                            "Created via API", user_id)
                conn.commit()
            except Exception as e:
                conn.rollback()
                return jsonify({"error": "Database error", "detail": str(e)}), 500

    return jsonify({"id": rule_id, "message": "Rule created"}), 201


# ─────────────────────────────────────────────────────────────────────────────
# PUT /recurring-rules/<id> — update
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/<int:rule_id>", methods=["PUT"])
@require_auth
def update_rule(rule_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden

    data = request.get_json() or {}
    reason = data.pop("reason", "Updated via API")

    # Only update provided fields
    allowed = ["primary_tech_id", "backup_tech_1_id", "backup_tech_2_id",
               "frequency", "weekdays", "week_pattern",
               "time_start", "time_end", "visit_type",
               "is_mandatory", "suppress_holiday", "duration_minutes",
               "notes", "effective_start", "effective_end"]
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    set_clauses = [f"{k} = %s" for k in updates.keys()]
    set_clauses.append("updated_by = %s")
    set_clauses.append("updated_at = NOW()")
    params = list(updates.values()) + [user_id, rule_id]

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT * FROM snc_recurring_rules WHERE id = %s", (rule_id,))
            old = cur.fetchone()
            if not old:
                return jsonify({"error": "Rule not found"}), 404

            try:
                sql = f"UPDATE snc_recurring_rules SET {', '.join(set_clauses)} WHERE id = %s"
                cur.execute(sql, params)
                _log_change(cur, rule_id, "updated",
                            {"old": {k: str(old.get(k)) for k in updates}, "new": updates},
                            reason, user_id)
                conn.commit()
            except Exception as e:
                conn.rollback()
                return jsonify({"error": "Database error", "detail": str(e)}), 500

    return jsonify({"id": rule_id, "message": "Rule updated", "fields": list(updates.keys())})


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /recurring-rules/<id> — soft deactivate
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/<int:rule_id>", methods=["DELETE"])
@require_auth
def deactivate_rule(rule_id):
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden

    reason = (request.get_json() or {}).get("reason", "Deactivated via API")

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, effective_end FROM snc_recurring_rules WHERE id = %s", (rule_id,))
            old = cur.fetchone()
            if not old:
                return jsonify({"error": "Rule not found"}), 404
            if old["effective_end"] and old["effective_end"] < date.today():
                return jsonify({"error": "Rule already deactivated"}), 400

            cur.execute("""
                UPDATE snc_recurring_rules
                SET effective_end = CURRENT_DATE, updated_by = %s, updated_at = NOW()
                WHERE id = %s
            """, (user_id, rule_id))
            _log_change(cur, rule_id, "deactivated", {"effective_end": str(date.today())},
                        reason, user_id)
            conn.commit()

    return jsonify({"id": rule_id, "message": "Rule deactivated"})


# ─────────────────────────────────────────────────────────────────────────────
# GET /recurring-rules/derive/<client_id> — suggest from pattern
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/derive/<int:client_id>", methods=["GET"])
@require_auth
def derive_from_pattern(client_id):
    """
    Suggest a rule from detected patterns for this client.
    Returns a draft rule that supervisor can review + accept.
    """
    source_month = request.args.get("source_month", "2026-05")

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT c.id, c.name FROM snc_clients c WHERE c.id = %s
            """, (client_id,))
            client = cur.fetchone()
            if not client:
                return jsonify({"error": "Client not found"}), 404

            cur.execute("""
                SELECT p.*, t.name as tech_name, t.is_active, t.employee_type
                FROM snc_schedule_patterns p
                JOIN snc_technicians t ON t.id = p.technician_id
                WHERE p.client_id = %s AND p.source_month = %s
                  AND t.is_active = true
                  AND t.employee_type IN ('mobile', 'support')
                ORDER BY p.confidence DESC, p.occurrence_count DESC
            """, (client_id, source_month))
            patterns = cur.fetchall()

    if not patterns:
        return jsonify({
            "client": client,
            "suggestion": None,
            "message": "No pattern detected for this client"
        })

    # Pick best frequency
    freq_priority = {"weekly": 3, "biweekly": 2, "monthly": 1, "adhoc": 0}
    best = max(patterns, key=lambda p: (freq_priority.get(p["frequency"], 0),
                                          p["occurrence_count"], p["confidence"]))

    # Collect weekdays for primary tech
    weekdays = sorted({p["day_of_week"] for p in patterns
                       if p["technician_id"] == best["technician_id"]
                       and float(p["confidence"]) >= 0.85})
    if not weekdays:
        weekdays = [best["day_of_week"]]

    # Backup tech: same DOW different tech, sorted by confidence
    same_dow = sorted(
        [p for p in patterns
         if p["day_of_week"] == best["day_of_week"]
         and p["technician_id"] != best["technician_id"]],
        key=lambda p: -float(p["confidence"])
    )
    backup_1 = same_dow[0] if same_dow else None
    backup_2 = same_dow[1] if len(same_dow) > 1 else None

    days_short = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    return jsonify({
        "client": {"id": client["id"], "name": client["name"]},
        "suggestion": {
            "client_id":        client_id,
            "primary_tech_id":  best["technician_id"],
            "primary_tech_name": best["tech_name"],
            "backup_tech_1_id": backup_1["technician_id"] if backup_1 else None,
            "backup_tech_1_name": backup_1["tech_name"] if backup_1 else None,
            "backup_tech_2_id": backup_2["technician_id"] if backup_2 else None,
            "backup_tech_2_name": backup_2["tech_name"] if backup_2 else None,
            "frequency":        best["frequency"],
            "weekdays":         weekdays,
            "weekdays_display": "+".join(days_short[d] for d in weekdays),
            "week_pattern":     best["week_pattern"] if best["frequency"] != "weekly" else None,
            "time_start":       best["time_start"],
            "time_end":         best["time_end"],
            "visit_type":       best["visit_type"],
            "is_mandatory":     False,  # default to soft, supervisor must explicitly set
            "suppress_holiday": True,
        },
        "pattern_meta": {
            "confidence":       float(best["confidence"]),
            "occurrence_count": best["occurrence_count"],
            "recency_score":    float(best["recency_score"] or 0),
            "source_month":     source_month,
        },
        "alternative_patterns": len(patterns) - 1,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /recurring-rules/log — audit trail
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/log", methods=["GET"])
@require_auth
def get_log():
    rule_id = request.args.get("rule_id", type=int)
    since = request.args.get("since")
    limit = min(int(request.args.get("limit", 100)), 500)

    where = ["1=1"]
    params = []
    if rule_id:
        where.append("rl.rule_id = %s")
        params.append(rule_id)
    if since:
        where.append("rl.changed_at >= %s")
        params.append(since)
    params.append(limit)

    sql = f"""
        SELECT rl.*, c.name as client_name
        FROM snc_recurring_rule_log rl
        LEFT JOIN snc_recurring_rules r ON r.id = rl.rule_id
        LEFT JOIN snc_clients c ON c.id = r.client_id
        WHERE {' AND '.join(where)}
        ORDER BY rl.changed_at DESC
        LIMIT %s
    """
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            log = cur.fetchall()
    for e in log:
        e["changed_at"] = e["changed_at"].isoformat()
    return jsonify({"log": log})


# ─────────────────────────────────────────────────────────────────────────────
# GET /recurring-rules/stats — coverage stats
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/stats", methods=["GET"])
@require_auth
def get_stats():
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Total active rules
            cur.execute("""
                SELECT COUNT(*) as n FROM snc_recurring_rules
                WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
            """)
            active_rules = cur.fetchone()["n"]

            # Customer coverage
            cur.execute("""
                SELECT COUNT(DISTINCT client_id) as covered FROM snc_recurring_rules
                WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
            """)
            covered = cur.fetchone()["covered"]

            cur.execute("SELECT COUNT(*) as total FROM snc_clients")
            total_clients = cur.fetchone()["total"]

            # By frequency
            cur.execute("""
                SELECT frequency, COUNT(*) as n FROM snc_recurring_rules
                WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
                GROUP BY frequency ORDER BY n DESC
            """)
            by_freq = cur.fetchall()

            # By tech (primary)
            cur.execute("""
                SELECT t.name as tech, COUNT(*) as n
                FROM snc_recurring_rules r
                JOIN snc_technicians t ON t.id = r.primary_tech_id
                WHERE r.effective_end IS NULL OR r.effective_end >= CURRENT_DATE
                GROUP BY t.name ORDER BY n DESC
            """)
            by_tech = cur.fetchall()

            # Mandatory vs optional
            cur.execute("""
                SELECT is_mandatory, COUNT(*) as n FROM snc_recurring_rules
                WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
                GROUP BY is_mandatory
            """)
            by_type = cur.fetchall()

    return jsonify({
        "active_rules":   active_rules,
        "customers_covered": covered,
        "total_customers": total_clients,
        "coverage_pct":   round(covered / total_clients * 100, 1) if total_clients else 0,
        "by_frequency":   by_freq,
        "by_tech":        by_tech,
        "by_type":        [{"is_mandatory": r["is_mandatory"], "n": r["n"]} for r in by_type],
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /recurring-rules/technicians — list snc_technicians (for UI dropdowns)
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/technicians", methods=["GET"])
@require_auth
def list_technicians_for_rules():
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT id, name, kelava_p_user_id, is_active
                FROM snc_technicians
                WHERE is_active = true OR is_active IS NULL
                ORDER BY name
            """)
            rows = cur.fetchall()
    return jsonify({"technicians": rows})


# ─────────────────────────────────────────────────────────────────────────────
# GET /recurring-rules/clients — list snc_clients (for UI dropdowns)
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/clients", methods=["GET"])
@require_auth
def list_clients_for_rules():
    search = request.args.get("search", "").strip()
    has_pattern = request.args.get("has_pattern", "").lower() == "true"
    where = ["1=1"]
    params = []
    if search:
        where.append("c.name ILIKE %s")
        params.append(f"%{search}%")
    if has_pattern:
        # Only customers detected in any draft pattern run
        where.append("""EXISTS (
            SELECT 1 FROM snc_schedule_patterns dp
            WHERE dp.client_id = c.id
        )""")

    sql = f"""
        SELECT c.id, c.name, c.address
        FROM snc_clients c
        WHERE {' AND '.join(where)}
        ORDER BY c.name
        LIMIT 1000
    """
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return jsonify({"clients": rows})


# ─────────────────────────────────────────────────────────────────────────────
# POST /recurring-rules/bulk-import — create many at once
# ─────────────────────────────────────────────────────────────────────────────

@recurring_rules_bp.route("/bulk-import", methods=["POST"])
@require_auth
def bulk_import():
    """
    Body: { "rules": [ {...rule1...}, {...rule2...} ] }
    Returns: { created: N, failed: N, errors: [...] }
    """
    user_id, forbidden = _require_koordinator_or_admin()
    if forbidden:
        return forbidden

    data = request.get_json() or {}
    rules_in = data.get("rules", [])
    if not isinstance(rules_in, list) or not rules_in:
        return jsonify({"error": "rules array required"}), 400

    created = 0
    failed = 0
    errors = []

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            for i, r in enumerate(rules_in):
                cleaned, error = _validate_rule_payload(r)
                if error:
                    failed += 1
                    errors.append({"index": i, "error": error})
                    continue
                try:
                    cur.execute("""
                        INSERT INTO snc_recurring_rules
                            (client_id, primary_tech_id, backup_tech_1_id, backup_tech_2_id,
                             frequency, weekdays, week_pattern,
                             time_start, time_end, visit_type,
                             is_mandatory, suppress_holiday, duration_minutes,
                             notes, effective_start, effective_end, created_by)
                        VALUES (%(client_id)s, %(primary_tech_id)s, %(backup_tech_1_id)s, %(backup_tech_2_id)s,
                                %(frequency)s, %(weekdays)s, %(week_pattern)s,
                                %(time_start)s, %(time_end)s, %(visit_type)s,
                                %(is_mandatory)s, %(suppress_holiday)s, %(duration_minutes)s,
                                %(notes)s, %(effective_start)s, %(effective_end)s, %(user_id)s)
                        ON CONFLICT (client_id, effective_start) DO NOTHING
                        RETURNING id
                    """, {**cleaned, "user_id": user_id})
                    res = cur.fetchone()
                    if res:
                        _log_change(cur, res["id"], "created", cleaned,
                                    "Bulk import", user_id)
                        created += 1
                    else:
                        failed += 1
                        errors.append({"index": i, "error": "duplicate (client + effective_start)"})
                except Exception as e:
                    failed += 1
                    errors.append({"index": i, "error": str(e)[:200]})

            conn.commit()

    return jsonify({
        "created": created,
        "failed":  failed,
        "errors":  errors[:50],
    })
