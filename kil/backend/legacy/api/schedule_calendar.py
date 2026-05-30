"""
Schedule Draft Calendar API
=============================
PRD §25 endpoints untuk Schedule Draft Calendar UI.

Endpoints:
  GET  /calendar/draft/<batch_id>/summary         per-day stats
  GET  /calendar/draft/<batch_id>/day?date=       selected day schedule
  GET  /calendar/draft/<batch_id>/conflicts       list all conflicts
  GET  /calendar/draft/<batch_id>/conflicts/<id>  conflict detail with suggested fixes
  POST /calendar/draft/<batch_id>/conflicts/<id>/apply-fix
  POST /calendar/draft/<batch_id>/detect-conflicts (re-scan)
  POST /calendar/draft/<batch_id>/approve-day
  POST /calendar/draft/<batch_id>/approve-clean-days
  POST /calendar/draft/<batch_id>/publish
  GET  /calendar/draft/<batch_id>/kpi             KPI cards data
  GET  /calendar/draft/<batch_id>/audit           audit log
"""

from datetime import date, datetime, timedelta
import calendar as cal_mod
import json

from flask import Blueprint, jsonify, request, g
from psycopg.rows import dict_row

from core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from kil.backend.legacy.api.conflict_detection import detect_conflicts

calendar_bp = Blueprint("schedule_calendar", __name__,
                         url_prefix="/api/v1/enterprise/calendar/draft")


def _audit_log(cur, batch_id: int, action: str, **kwargs):
    """Helper untuk write audit log."""
    cur.execute("""
        INSERT INTO snc_schedule_audit_log
            (draft_batch_id, event_id, conflict_id, action,
             old_value, new_value, reason, changed_by)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
    """, (
        batch_id,
        kwargs.get('event_id'),
        kwargs.get('conflict_id'),
        action,
        json.dumps(kwargs.get('old_value')) if kwargs.get('old_value') else None,
        json.dumps(kwargs.get('new_value')) if kwargs.get('new_value') else None,
        kwargs.get('reason'),
        kwargs.get('user_id', 0),
    ))


def _user_id():
    user = getattr(g, "current_user", None) or getattr(request, "_jwt_user", {})
    return user.get('id') if isinstance(user, dict) else getattr(user, 'id', 0)


# ─────────────────────────────────────────────────────────────────────────────
# GET /calendar/draft/<batch_id>/kpi — PRD §12
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/kpi", methods=["GET"])
@require_auth
def kpi(batch_id):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Total events
            cur.execute("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE source = 'rule') as rule_count,
                       COUNT(*) FILTER (WHERE source = 'pattern') as pattern_count,
                       COUNT(*) FILTER (WHERE source = 'manual') as manual_count,
                       COUNT(*) FILTER (WHERE schedule_status = 'approved') as approved_count,
                       COUNT(*) FILTER (WHERE published_at IS NOT NULL) as published_count,
                       COUNT(*) FILTER (WHERE issue_type IS NOT NULL) as conflicted_count
                FROM snc_schedule_events
                WHERE draft_batch_id = %s AND schedule_status IN ('draft','approved','scheduled')
            """, (batch_id,))
            stats = cur.fetchone()

            # Conflicts breakdown
            cur.execute("""
                SELECT conflict_type, COUNT(*) as n
                FROM snc_schedule_conflicts
                WHERE draft_batch_id = %s AND status = 'open'
                GROUP BY conflict_type
            """, (batch_id,))
            conflict_breakdown = {r['conflict_type']: r['n'] for r in cur.fetchall()}
            total_conflicts = sum(conflict_breakdown.values())

            # Active rules
            cur.execute("""
                SELECT COUNT(*) as n FROM snc_recurring_rules
                WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
            """)
            active_rules = cur.fetchone()['n']

            # Last month comparison
            cur.execute("""
                SELECT target_month FROM snc_draft_batches WHERE id = %s
            """, (batch_id,))
            tm = cur.fetchone()
            last_month_total = 0
            if tm:
                ty, tmo = tm['target_month'].split('-')
                ty, tmo = int(ty), int(tmo)
                last_mo = tmo - 1 if tmo > 1 else 12
                last_y = ty if tmo > 1 else ty - 1
                cur.execute("""
                    SELECT id FROM snc_draft_batches
                    WHERE target_month = %s
                    ORDER BY id DESC LIMIT 1
                """, (f"{last_y}-{last_mo:02d}",))
                lb = cur.fetchone()
                if lb:
                    cur.execute("""
                        SELECT COUNT(*) as n FROM snc_schedule_events
                        WHERE draft_batch_id = %s
                    """, (lb['id'],))
                    last_month_total = cur.fetchone()['n']

    # Publishable = approved + draft tanpa conflict
    publishable = stats['approved_count']
    if total_conflicts == 0:
        publishable = stats['total']

    return jsonify({
        "draft_visits": {
            "total":            stats['total'],
            "diff_vs_last":     stats['total'] - last_month_total,
            "last_month_total": last_month_total,
        },
        "rule_based": {
            "count":          stats['rule_count'],
            "percentage":     round(stats['rule_count'] / stats['total'] * 100, 1) if stats['total'] else 0,
            "active_rules":   active_rules,
        },
        "conflicts": {
            "total":        total_conflicts,
            "breakdown":    conflict_breakdown,
            "publish_blocked": total_conflicts > 0,
        },
        "publishable": {
            "count":     publishable,
            "total":     stats['total'],
            "percentage": round(publishable / stats['total'] * 100, 1) if stats['total'] else 0,
            "blocked":   total_conflicts > 0,
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /calendar/draft/<batch_id>/panels — PRD §20-23 (Daily Load, Rule Impact, Audit)
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/panels", methods=["GET"])
@require_auth
def panels(batch_id):
    """
    Returns 3 side panels in one call:
      - daily_load: Top N tech by visit count (scope: day/week/month)
      - rule_impact: Source breakdown for scope
      - audit_summary: Key audit metrics
    Query params:
      scope: day|week|month (default: month)
      date:  YYYY-MM-DD (required for day/week scope)
    """
    scope = request.args.get("scope", "month")
    target_date = request.args.get("date")

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Get batch target_month for default scope
            cur.execute("SELECT target_month FROM snc_draft_batches WHERE id=%s", (batch_id,))
            batch = cur.fetchone()
            if not batch:
                return jsonify({"error": "Batch not found"}), 404
            ty, tm = batch['target_month'].split('-')
            ty, tm = int(ty), int(tm)
            import calendar as _cal
            _, ndays = _cal.monthrange(ty, tm)
            month_start = date(ty, tm, 1)
            month_end   = date(ty, tm, ndays)

            # Determine date filter
            if scope == "day" and target_date:
                date_filter = "se.start_date = %s"
                date_params = [target_date]
            elif scope == "week" and target_date:
                from datetime import datetime as _dt
                d = _dt.strptime(target_date, "%Y-%m-%d").date()
                week_start = d - timedelta(days=d.weekday())
                week_end   = week_start + timedelta(days=6)
                date_filter = "se.start_date BETWEEN %s AND %s"
                date_params = [week_start, week_end]
            else:  # month
                date_filter = "se.start_date BETWEEN %s AND %s"
                date_params = [month_start, month_end]

            # ── 1. Daily Load — top 5 tech ─────────────────────────────────
            cur.execute(f"""
                SELECT t.id, t.name, COUNT(*) as visits
                FROM snc_schedule_events se
                JOIN snc_technicians t ON t.id = se.technician_id
                WHERE se.draft_batch_id = %s AND {date_filter}
                GROUP BY t.id, t.name
                ORDER BY visits DESC LIMIT 8
            """, [batch_id] + date_params)
            daily_load = cur.fetchall()
            max_visits = max((d['visits'] for d in daily_load), default=1)

            # ── 2. Rule Impact — source breakdown ──────────────────────────
            cur.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE source = 'rule') as rule_count,
                    COUNT(*) FILTER (WHERE source = 'pattern') as pattern_count,
                    COUNT(*) FILTER (WHERE source = 'manual') as manual_count,
                    COUNT(*) as total
                FROM snc_schedule_events se
                WHERE se.draft_batch_id = %s AND {date_filter}
                  AND se.schedule_status IN ('draft','approved','scheduled')
            """, [batch_id] + date_params)
            ri = cur.fetchone()
            total = ri['total'] or 1
            rule_impact = {
                "total":     ri['total'],
                "segments": [
                    {"label": "Rule",    "count": ri['rule_count'],
                     "pct": round(ri['rule_count']*100/total, 1), "color": "#F97316"},
                    {"label": "Pattern", "count": ri['pattern_count'],
                     "pct": round(ri['pattern_count']*100/total, 1), "color": "#3B82F6"},
                    {"label": "Manual",  "count": ri['manual_count'],
                     "pct": round(ri['manual_count']*100/total, 1), "color": "#6B7280"},
                ],
            }

            # ── 3. Audit Summary ────────────────────────────────────────────
            cur.execute(f"""
                SELECT COUNT(DISTINCT rule_id) as rules_triggered
                FROM snc_schedule_events se
                WHERE se.draft_batch_id = %s AND {date_filter}
                  AND rule_id IS NOT NULL
            """, [batch_id] + date_params)
            rules_triggered = cur.fetchone()['rules_triggered']

            cur.execute("""
                SELECT COUNT(*) as n FROM snc_recurring_rules
                WHERE effective_end IS NULL OR effective_end >= CURRENT_DATE
            """)
            active_rules = cur.fetchone()['n']

            cur.execute(f"""
                SELECT COUNT(*) as n FROM snc_schedule_conflicts sc
                JOIN snc_schedule_events se ON se.id = sc.visit_a_id
                WHERE sc.draft_batch_id = %s
                  AND sc.conflict_type = 'holiday_exception'
                  AND {date_filter}
            """, [batch_id] + date_params)
            holiday_exceptions = cur.fetchone()['n']

            cur.execute(f"""
                SELECT COUNT(DISTINCT sd.suppression_date) as n
                FROM snc_suppression_dates sd
                WHERE sd.suppression_date BETWEEN %s AND %s
            """, (date_params[0],
                  date_params[1] if len(date_params) > 1 else date_params[0]))
            holiday_dates = cur.fetchone()['n']

            cur.execute(f"""
                SELECT COUNT(*) as n FROM snc_schedule_conflicts sc
                WHERE sc.draft_batch_id = %s
                  AND sc.status = 'ignored'
            """, (batch_id,))
            exceptions_skipped = cur.fetchone()['n']

            # Uncovered customers: rules yang ada tapi tidak generate event di scope
            cur.execute(f"""
                SELECT COUNT(DISTINCT r.client_id) as n
                FROM snc_recurring_rules r
                WHERE (r.effective_end IS NULL OR r.effective_end >= CURRENT_DATE)
                  AND r.is_mandatory = true
                  AND NOT EXISTS (
                      SELECT 1 FROM snc_schedule_events se
                      WHERE se.draft_batch_id = %s
                        AND se.client_id = r.client_id
                        AND {date_filter}
                  )
            """, [batch_id] + date_params)
            uncovered = cur.fetchone()['n']

    return jsonify({
        "scope": scope,
        "daily_load": [
            {**dl, "pct": round(dl['visits']*100/max_visits, 1)}
            for dl in daily_load
        ],
        "rule_impact": rule_impact,
        "audit_summary": {
            "active_rules_applied":  active_rules,
            "rules_triggered":       rules_triggered,
            "exceptions_skipped":    exceptions_skipped,
            "holiday_skipped":       holiday_dates,
            "holiday_exceptions":    holiday_exceptions,
            "uncovered_customers":   uncovered,
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /calendar/draft/<batch_id>/summary — PRD §25.2 per-day stats
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/summary", methods=["GET"])
@require_auth
def summary(batch_id):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT target_month FROM snc_draft_batches WHERE id = %s
            """, (batch_id,))
            batch = cur.fetchone()
            if not batch:
                return jsonify({"error": "Batch not found"}), 404
            target_month = batch['target_month']

            cur.execute("""
                SELECT * FROM snc_calendar_day_summary
                WHERE draft_batch_id = %s
                ORDER BY visit_date
            """, (batch_id,))
            rows = cur.fetchall()

    days = []
    for r in rows:
        days.append({
            "date":            r['visit_date'].isoformat(),
            "total_visits":    r['total_visits'],
            "rule_count":      r['rule_count'],
            "pattern_count":   r['pattern_count'],
            "manual_count":    r['manual_count'],
            "conflict_count":  r['conflict_count'],
            "approved_count":  r['approved_count'],
            "published_count": r['published_count'],
            "holiday_skipped": r['holiday_skipped_count'],
        })
    return jsonify({"target_month": target_month, "days": days})


# ─────────────────────────────────────────────────────────────────────────────
# GET /calendar/draft/<batch_id>/day?date= — PRD §25.3 selected day
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/day", methods=["GET"])
@require_auth
def day_schedule(batch_id):
    target_date = request.args.get("date")
    if not target_date:
        return jsonify({"error": "date query param required (YYYY-MM-DD)"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT se.id, se.client_id, c.name as customer,
                       c.address as customer_address,
                       se.technician_id, t.name as technician,
                       TO_CHAR(se.start_datetime, 'HH24:MI') as time_start,
                       TO_CHAR(se.end_datetime,   'HH24:MI') as time_end,
                       se.source, se.schedule_status as status, se.issue_type,
                       se.visit_type, se.notes, se.is_mandatory,
                       se.rule_id, se.pattern_id, se.is_holiday_skipped
                FROM snc_schedule_events se
                JOIN snc_clients c ON c.id = se.client_id
                JOIN snc_technicians t ON t.id = se.technician_id
                WHERE se.draft_batch_id = %s AND se.start_date = %s
                ORDER BY se.start_datetime
            """, (batch_id, target_date))
            events = cur.fetchall()

            # Holiday info
            cur.execute("""
                SELECT reason FROM snc_suppression_dates WHERE suppression_date = %s
            """, (target_date,))
            holiday = cur.fetchone()

            # Count rules skipped karena libur ini
            holiday_skipped_count = 0
            if holiday:
                cur.execute("""
                    SELECT COUNT(*) as n FROM snc_recurring_rules r
                    WHERE r.suppress_holiday = true
                      AND (r.effective_end IS NULL OR r.effective_end >= %s)
                      AND r.effective_start <= %s
                """, (target_date, target_date))
                holiday_skipped_count = cur.fetchone()['n']

    return jsonify({
        "date":                target_date,
        "holiday":             holiday['reason'] if holiday else None,
        "holiday_skipped_count": holiday_skipped_count,
        "events":              events,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /calendar/draft/<batch_id>/detect-conflicts — manual re-scan
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/detect-conflicts", methods=["POST"])
@require_auth
def detect_conflicts_endpoint(batch_id):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            stats = detect_conflicts(cur, batch_id)
            _audit_log(cur, batch_id, "conflict_detected",
                       user_id=_user_id(), reason="Manual re-scan",
                       new_value=stats)
            conn.commit()
    return jsonify(stats)


# ─────────────────────────────────────────────────────────────────────────────
# GET /calendar/draft/<batch_id>/conflicts — PRD §25.4 list
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/conflicts", methods=["GET"])
@require_auth
def list_conflicts(batch_id):
    status_filter = request.args.get("status", "open")
    conflict_type = request.args.get("type")
    severity = request.args.get("severity")

    where = ["draft_batch_id = %s"]
    params = [batch_id]
    if status_filter and status_filter != "all":
        where.append("status = %s"); params.append(status_filter)
    if conflict_type:
        where.append("conflict_type = %s"); params.append(conflict_type)
    if severity:
        where.append("severity = %s"); params.append(severity)

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                SELECT c.*, t.name as technician_name, cl.name as client_name
                FROM snc_schedule_conflicts c
                LEFT JOIN snc_technicians t ON t.id = c.technician_id
                LEFT JOIN snc_clients cl ON cl.id = c.client_id
                WHERE {' AND '.join(where)}
                ORDER BY c.visit_date, c.severity DESC
            """, params)
            conflicts = cur.fetchall()

    # Serialize
    for c in conflicts:
        c['visit_date'] = c['visit_date'].isoformat() if c['visit_date'] else None
        if c.get('time_start'):
            c['time_start'] = c['time_start'].strftime("%H:%M")
        if c.get('time_end'):
            c['time_end'] = c['time_end'].strftime("%H:%M")
        for f in ['created_at', 'updated_at', 'resolved_at']:
            if c.get(f):
                c[f] = c[f].isoformat()

    return jsonify({"total": len(conflicts), "conflicts": conflicts})


# ─────────────────────────────────────────────────────────────────────────────
# GET /calendar/draft/<batch_id>/conflicts/<id> — PRD §25.5 detail
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/conflicts/<int:conflict_id>", methods=["GET"])
@require_auth
def conflict_detail(batch_id, conflict_id):
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT c.*, t.name as technician_name, t.employee_type,
                       cl.name as client_name
                FROM snc_schedule_conflicts c
                LEFT JOIN snc_technicians t ON t.id = c.technician_id
                LEFT JOIN snc_clients cl ON cl.id = c.client_id
                WHERE c.id = %s AND c.draft_batch_id = %s
            """, (conflict_id, batch_id))
            conflict = cur.fetchone()
            if not conflict:
                return jsonify({"error": "Conflict not found"}), 404

            # Load affected visits
            visits = []
            for vid_key in ['visit_a_id', 'visit_b_id']:
                vid = conflict.get(vid_key)
                if not vid: continue
                cur.execute("""
                    SELECT se.id, se.source,
                           TO_CHAR(se.start_datetime, 'HH24:MI') as time_start,
                           TO_CHAR(se.end_datetime,   'HH24:MI') as time_end,
                           c.name as customer, t.name as technician,
                           se.schedule_status as status, se.notes
                    FROM snc_schedule_events se
                    JOIN snc_clients c ON c.id = se.client_id
                    JOIN snc_technicians t ON t.id = se.technician_id
                    WHERE se.id = %s
                """, (vid,))
                v = cur.fetchone()
                if v: visits.append(v)

    suggested_fixes = []
    if conflict.get('suggested_fix_payload'):
        try:
            suggested_fixes.append(conflict['suggested_fix_payload'])
        except Exception:
            pass

    return jsonify({
        "id":                conflict['id'],
        "type":              conflict['conflict_type'],
        "severity":          conflict['severity'],
        "status":            conflict['status'],
        "visit_date":        conflict['visit_date'].isoformat() if conflict['visit_date'] else None,
        "technician": {
            "id":   conflict['technician_id'],
            "name": conflict['technician_name'],
            "type": conflict['employee_type'],
        },
        "visits":            visits,
        "issue":             conflict['issue_description'],
        "suggested_fixes":   suggested_fixes,
        "resolution_notes":  conflict.get('resolution_notes'),
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /calendar/draft/<batch_id>/conflicts/<id>/apply-fix — PRD §25.6
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/conflicts/<int:conflict_id>/apply-fix", methods=["POST"])
@require_auth
def apply_fix(batch_id, conflict_id):
    data = request.get_json() or {}
    fix_type = data.get("fix_type")
    payload = data.get("payload", {})
    reason = data.get("reason", "Applied via UI")
    user_id = _user_id()

    if not fix_type:
        return jsonify({"error": "fix_type required"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT * FROM snc_schedule_conflicts
                WHERE id = %s AND draft_batch_id = %s
            """, (conflict_id, batch_id))
            conflict = cur.fetchone()
            if not conflict:
                return jsonify({"error": "Conflict not found"}), 404
            if conflict['status'] != 'open':
                return jsonify({"error": "Conflict already resolved"}), 400

            # Apply fix
            if fix_type == "reassign_backup":
                visit_id = payload.get("visit_id")
                new_tech_id = payload.get("new_technician_id")
                if not visit_id or not new_tech_id:
                    return jsonify({"error": "visit_id + new_technician_id required"}), 400
                cur.execute("""
                    UPDATE snc_schedule_events
                    SET technician_id = %s, issue_type = NULL,
                        notes = COALESCE(notes, '') || ' | Reassigned via fix'
                    WHERE id = %s
                """, (new_tech_id, visit_id))

            elif fix_type == "move_time":
                visit_id = payload.get("visit_id") or conflict['visit_b_id']
                new_time = payload.get("new_time_start")
                if not new_time:
                    return jsonify({"error": "new_time_start required"}), 400
                cur.execute("""
                    UPDATE snc_schedule_events
                    SET start_datetime = start_date + %s::time,
                        issue_type = NULL
                    WHERE id = %s
                """, (new_time, visit_id))

            elif fix_type == "mark_exception":
                visit_id = payload.get("visit_id") or conflict['visit_a_id']
                cur.execute("""
                    UPDATE snc_schedule_events SET issue_type = NULL,
                        notes = COALESCE(notes, '') || ' | Manual exception: ' || %s
                    WHERE id = %s
                """, (reason, visit_id))

            elif fix_type == "cancel":
                visit_id = payload.get("visit_id") or conflict['visit_b_id']
                cur.execute("""
                    UPDATE snc_schedule_events
                    SET schedule_status = 'cancelled', issue_type = NULL
                    WHERE id = %s
                """, (visit_id,))

            else:
                return jsonify({"error": f"Unknown fix_type: {fix_type}"}), 400

            # Mark conflict resolved
            cur.execute("""
                UPDATE snc_schedule_conflicts
                SET status = 'resolved', resolved_by = %s, resolved_at = NOW(),
                    resolution_notes = %s
                WHERE id = %s
            """, (user_id, reason, conflict_id))

            # Re-scan conflicts untuk batch (cheap karena bersift incremental)
            stats = detect_conflicts(cur, batch_id)

            _audit_log(cur, batch_id, "conflict_resolved",
                       conflict_id=conflict_id, user_id=user_id, reason=reason,
                       new_value={"fix_type": fix_type, "payload": payload})

            conn.commit()

    return jsonify({
        "success":             True,
        "conflict_status":     "resolved",
        "remaining_conflicts": stats['detected'],
        "recalculated":        True,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /calendar/draft/<batch_id>/approve-day — PRD §25.7
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/approve-day", methods=["POST"])
@require_auth
def approve_day(batch_id):
    data = request.get_json() or {}
    target_date = data.get("date")
    mode = data.get("mode", "clean_only")
    user_id = _user_id()

    if not target_date:
        return jsonify({"error": "date required"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Skip approve untuk events yang punya issue_type
            cur.execute("""
                UPDATE snc_schedule_events
                SET schedule_status = 'approved',
                    approved_by = %s, approved_at = NOW()
                WHERE draft_batch_id = %s AND start_date = %s
                  AND schedule_status = 'draft'
                  AND (issue_type IS NULL OR %s = 'all')
                RETURNING id
            """, (user_id, batch_id, target_date, mode))
            approved = cur.fetchall()

            # Count skipped
            cur.execute("""
                SELECT COUNT(*) as n FROM snc_schedule_events
                WHERE draft_batch_id = %s AND start_date = %s
                  AND schedule_status = 'draft' AND issue_type IS NOT NULL
            """, (batch_id, target_date))
            skipped = cur.fetchone()['n']

            _audit_log(cur, batch_id, "day_approved",
                       user_id=user_id, reason=f"Day {target_date} clean_only={mode}",
                       new_value={"date": target_date, "approved_count": len(approved),
                                  "skipped": skipped})
            conn.commit()

    return jsonify({
        "approved_count":      len(approved),
        "skipped_conflicts":   skipped,
        "message":             f"Approved {len(approved)} clean visits for {target_date}",
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /calendar/draft/<batch_id>/approve-clean-days — PRD §25.8
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/approve-clean-days", methods=["POST"])
@require_auth
def approve_clean_days(batch_id):
    user_id = _user_id()

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Hari dengan 0 conflict
            cur.execute("""
                SELECT DISTINCT se.start_date
                FROM snc_schedule_events se
                WHERE se.draft_batch_id = %s
                  AND se.schedule_status = 'draft'
                  AND NOT EXISTS (
                      SELECT 1 FROM snc_schedule_conflicts sc
                      WHERE sc.draft_batch_id = se.draft_batch_id
                        AND sc.visit_date = se.start_date
                        AND sc.status = 'open'
                  )
            """, (batch_id,))
            clean_days = [r['start_date'] for r in cur.fetchall()]

            # Approve all events on clean days that don't have issue
            cur.execute("""
                UPDATE snc_schedule_events
                SET schedule_status = 'approved',
                    approved_by = %s, approved_at = NOW()
                WHERE draft_batch_id = %s
                  AND schedule_status = 'draft'
                  AND issue_type IS NULL
                  AND start_date = ANY(%s)
                RETURNING id
            """, (user_id, batch_id, clean_days))
            approved = cur.fetchall()

            # Count remaining conflict days
            cur.execute("""
                SELECT COUNT(*) as n FROM snc_schedule_conflicts
                WHERE draft_batch_id = %s AND status = 'open'
            """, (batch_id,))
            remaining = cur.fetchone()['n']

            _audit_log(cur, batch_id, "clean_days_approved",
                       user_id=user_id,
                       reason=f"Bulk approve clean days",
                       new_value={"days_approved": len(clean_days),
                                  "events_approved": len(approved)})
            conn.commit()

    return jsonify({
        "approved_count":         len(approved),
        "skipped_conflict_days":  remaining,
        "clean_days":             [d.isoformat() for d in clean_days],
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /calendar/draft/<batch_id>/publish — PRD §25.9
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/publish", methods=["POST"])
@require_auth
def publish_schedule(batch_id):
    data = request.get_json() or {}
    if not data.get("confirm"):
        return jsonify({"error": "confirm required"}), 400

    user_id = _user_id()

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # AC-08: backend MUST block if conflicts > 0
            cur.execute("""
                SELECT COUNT(*) as n FROM snc_schedule_conflicts
                WHERE draft_batch_id = %s AND status = 'open'
            """, (batch_id,))
            remaining = cur.fetchone()['n']
            if remaining > 0:
                _audit_log(cur, batch_id, "publish_blocked",
                           user_id=user_id,
                           reason=f"{remaining} conflicts unresolved")
                conn.commit()
                return jsonify({
                    "error":   "publish_blocked",
                    "message": f"Resolve {remaining} conflicts before publishing",
                }), 400

            # Publish all approved events
            cur.execute("""
                UPDATE snc_schedule_events
                SET schedule_status = 'scheduled',
                    published_at = NOW()
                WHERE draft_batch_id = %s
                  AND schedule_status = 'approved'
                RETURNING id
            """, (batch_id,))
            published = cur.fetchall()

            # Update batch
            cur.execute("""
                UPDATE snc_draft_batches
                SET status = 'published',
                    published_count = %s,
                    published_at = NOW(),
                    published_by = %s
                WHERE id = %s
            """, (len(published), user_id, batch_id))

            _audit_log(cur, batch_id, "schedule_published",
                       user_id=user_id,
                       new_value={"published_count": len(published)})
            conn.commit()

    return jsonify({
        "success":         True,
        "published_count": len(published),
        "published_at":    datetime.now().isoformat(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /calendar/draft/<batch_id>/audit — audit log
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/<int:batch_id>/audit", methods=["GET"])
@require_auth
def get_audit(batch_id):
    limit = min(int(request.args.get("limit", 100)), 500)
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT * FROM snc_schedule_audit_log
                WHERE draft_batch_id = %s
                ORDER BY changed_at DESC
                LIMIT %s
            """, (batch_id, limit))
            log = cur.fetchall()
    for e in log:
        e['changed_at'] = e['changed_at'].isoformat()
    return jsonify({"log": log})


# ─────────────────────────────────────────────────────────────────────────────
# GET /calendar/draft/latest — convenience: get latest batch
# ─────────────────────────────────────────────────────────────────────────────

@calendar_bp.route("/latest", methods=["GET"])
@require_auth
def latest_batch():
    target_month = request.args.get("target_month")
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if target_month:
                cur.execute("""
                    SELECT * FROM snc_draft_batches WHERE target_month = %s
                    ORDER BY id DESC LIMIT 1
                """, (target_month,))
            else:
                cur.execute("""
                    SELECT * FROM snc_draft_batches ORDER BY id DESC LIMIT 1
                """)
            batch = cur.fetchone()
    if not batch:
        return jsonify({"batch": None}), 404
    for f in ['generated_at', 'approved_at', 'published_at']:
        if batch.get(f):
            batch[f] = batch[f].isoformat()
    return jsonify({"batch": batch})
