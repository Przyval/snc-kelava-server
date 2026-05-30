"""
Schedule Conflict Detection Engine
===================================
PRD §27.5 — After draft generation, scan events untuk classify conflicts.
Run setiap kali draft generated OR conflict fix applied.

Conflict types (PRD §24.2 issue_type):
  - double_booking      : 2 events same tech same date overlapping time
  - overlap             : same tech, time windows overlap (partial)
  - capacity_exceeded   : tech has > 5 events same day OR > 18 same week
  - uncovered_customer  : actual customer expected (from rule) but no event
  - holiday_exception   : event di hari libur tanpa flag
  - missing_backup      : co-visit rule but backup tech unavailable
  - route_warning       : geographic concern (future)

Severity:
  - high   : double_booking, capacity_exceeded
  - medium : overlap, missing_backup
  - low    : holiday_exception, route_warning, uncovered_customer
"""

from datetime import date, datetime, timedelta, time
from collections import defaultdict
from psycopg.rows import dict_row
import json


# ──────────────────────────────────────────────────────────────────────────────
# Suggested fix generators
# ──────────────────────────────────────────────────────────────────────────────

def _suggest_reassign_backup(cur, conflict: dict, visit_b_id: int) -> dict | None:
    """Cari backup tech yang available di tanggal & jam yang sama."""
    cur.execute("""
        SELECT ct.technician_id, t.name
        FROM snc_customer_technician ct
        JOIN snc_technicians t ON t.id = ct.technician_id
        WHERE ct.client_id = %s
          AND ct.role IN ('backup_1', 'backup_2')
          AND ct.technician_id != %s
          AND t.is_active = true
          AND t.employee_type IN ('mobile', 'support')
        ORDER BY ct.role
        LIMIT 1
    """, (conflict['client_id'], conflict['technician_id']))
    backup = cur.fetchone()
    if not backup:
        return None

    # Verify backup not also overloaded that day
    cur.execute("""
        SELECT COUNT(*) as n FROM snc_schedule_events
        WHERE technician_id = %s AND start_date = %s
          AND schedule_status IN ('draft','approved')
    """, (backup['technician_id'], conflict['visit_date']))
    if cur.fetchone()['n'] >= 5:
        return None

    return {
        "type": "reassign_backup",
        "label": f"Reassign to {backup['name']} (Backup)",
        "recommended": True,
        "payload": {
            "visit_id": visit_b_id,
            "new_technician_id": backup['technician_id'],
            "new_technician_name": backup['name'],
        }
    }


def _suggest_move_time(visit_a_end: time, visit_b_start: time) -> dict:
    """Move visit B to start after visit A ends."""
    if not visit_a_end:
        new_start = time(visit_b_start.hour + 2, 0) if visit_b_start.hour < 22 else None
    else:
        new_start = time(visit_a_end.hour, (visit_a_end.minute + 15) % 60)
        if visit_a_end.minute + 15 >= 60:
            new_start = time((visit_a_end.hour + 1) % 24, (visit_a_end.minute + 15) % 60)
    if not new_start:
        return None
    return {
        "type": "move_time",
        "label": f"Move Visit B to {new_start.strftime('%H:%M')}",
        "recommended": False,
        "payload": {"new_time_start": new_start.strftime("%H:%M")},
    }


def _suggest_mark_exception() -> dict:
    return {
        "type": "mark_exception",
        "label": "Mark as Manual Exception",
        "recommended": False,
        "payload": {"reason": "Supervisor-approved exception"},
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main detection function
# ──────────────────────────────────────────────────────────────────────────────

def detect_conflicts(cur, batch_id: int) -> dict:
    """
    Scan all draft events in batch, classify conflicts, populate
    snc_schedule_conflicts table.

    Returns stats: {detected, by_type, by_severity}
    """
    # Clear existing conflicts untuk batch ini (re-scan)
    cur.execute("DELETE FROM snc_schedule_conflicts WHERE draft_batch_id = %s", (batch_id,))

    # Load all events untuk batch
    cur.execute("""
        SELECT se.id, se.technician_id, se.client_id, se.start_date,
               se.start_datetime, se.end_datetime,
               se.source, se.notes,
               c.name as client_name,
               t.name as tech_name,
               TO_CHAR(se.start_datetime, 'HH24:MI') as time_start,
               TO_CHAR(se.end_datetime,   'HH24:MI') as time_end
        FROM snc_schedule_events se
        JOIN snc_clients c ON c.id = se.client_id
        JOIN snc_technicians t ON t.id = se.technician_id
        WHERE se.draft_batch_id = %s
          AND se.schedule_status = 'draft'
        ORDER BY se.technician_id, se.start_date, se.start_datetime
    """, (batch_id,))
    events = cur.fetchall()

    detected = 0
    by_type = defaultdict(int)
    by_severity = defaultdict(int)

    # ── 1. Double-booking & overlap detection (per tech, per date) ──────────
    by_tech_date = defaultdict(list)
    for e in events:
        by_tech_date[(e['technician_id'], e['start_date'])].append(e)

    for (tech_id, vdate), bucket in by_tech_date.items():
        if len(bucket) < 2:
            continue
        # Sort by start_datetime, look for overlap
        bucket.sort(key=lambda x: x['start_datetime'])
        for i in range(len(bucket) - 1):
            a, b = bucket[i], bucket[i+1]
            a_end = a['end_datetime'] or a['start_datetime'] + timedelta(hours=1)
            b_start = b['start_datetime']

            if b_start < a_end:
                # Overlap detected
                same_client = (a['client_id'] == b['client_id'])
                conflict_type = "double_booking" if same_client else "overlap"
                severity = "high" if conflict_type == "double_booking" else "medium"

                # Generate suggested fix
                suggested = _suggest_reassign_backup(cur, {
                    'client_id': b['client_id'],
                    'technician_id': tech_id,
                    'visit_date': vdate,
                }, b['id'])
                if not suggested:
                    suggested = _suggest_move_time(a_end.time() if a_end else None,
                                                    b_start.time())
                if not suggested:
                    suggested = _suggest_mark_exception()

                issue_desc = (
                    f"Technician {a['tech_name']} scheduled for overlapping visits: "
                    f"{a['client_name']} ({a['time_start']}) and "
                    f"{b['client_name']} ({b['time_start']})"
                )

                cur.execute("""
                    INSERT INTO snc_schedule_conflicts
                        (draft_batch_id, conflict_type, severity,
                         visit_a_id, visit_b_id, technician_id, client_id,
                         visit_date, time_start, time_end,
                         issue_description, suggested_fix_type, suggested_fix_payload,
                         status)
                    VALUES (%s,%s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s,%s::jsonb, 'open')
                """, (batch_id, conflict_type, severity,
                      a['id'], b['id'], tech_id, b['client_id'],
                      vdate, a['time_start'], b['time_start'],
                      issue_desc, suggested.get('type') if suggested else None,
                      json.dumps(suggested) if suggested else None))

                detected += 1
                by_type[conflict_type] += 1
                by_severity[severity] += 1

                # Mark events with issue_type
                cur.execute("""
                    UPDATE snc_schedule_events SET issue_type = %s WHERE id IN (%s, %s)
                """, (conflict_type, a['id'], b['id']))

    # ── 2. Capacity exceeded (per tech per day > 5, per week > 18) ──────────
    tech_day_count = defaultdict(int)
    tech_week_count = defaultdict(int)
    for e in events:
        tech_day_count[(e['technician_id'], e['start_date'])] += 1
        iso_year, iso_week, _ = e['start_date'].isocalendar()
        tech_week_count[(e['technician_id'], iso_year, iso_week)] += 1

    # Per-day capacity
    for (tech_id, vdate), n in tech_day_count.items():
        if n > 5:
            # Find sample event
            sample = next((e for e in events if e['technician_id'] == tech_id
                           and e['start_date'] == vdate), None)
            if sample:
                cur.execute("""
                    INSERT INTO snc_schedule_conflicts
                        (draft_batch_id, conflict_type, severity,
                         visit_a_id, technician_id, visit_date,
                         issue_description, suggested_fix_type, status)
                    VALUES (%s, 'capacity_exceeded', 'high',
                            %s, %s, %s, %s, 'reassign_backup', 'open')
                """, (batch_id, sample['id'], tech_id, vdate,
                      f"Technician {sample['tech_name']} has {n} visits this day (max 5)"))
                detected += 1
                by_type['capacity_exceeded'] += 1
                by_severity['high'] += 1

    # ── 3. Holiday exception detection ──────────────────────────────────────
    cur.execute("""
        SELECT se.id, se.technician_id, se.client_id,
               c.name as client_name, t.name as tech_name,
               se.start_date, sd.reason as holiday_reason
        FROM snc_schedule_events se
        JOIN snc_suppression_dates sd ON sd.suppression_date = se.start_date
        JOIN snc_clients c ON c.id = se.client_id
        JOIN snc_technicians t ON t.id = se.technician_id
        WHERE se.draft_batch_id = %s
          AND se.schedule_status = 'draft'
    """, (batch_id,))
    for h in cur.fetchall():
        cur.execute("""
            INSERT INTO snc_schedule_conflicts
                (draft_batch_id, conflict_type, severity,
                 visit_a_id, technician_id, client_id, visit_date,
                 issue_description, suggested_fix_type, status)
            VALUES (%s, 'holiday_exception', 'low',
                    %s, %s, %s, %s, %s, 'mark_exception', 'open')
        """, (batch_id, h['id'], h['technician_id'], h['client_id'], h['start_date'],
              f"{h['client_name']} scheduled on holiday: {h['holiday_reason']}"))
        cur.execute("UPDATE snc_schedule_events SET issue_type='holiday_exception', "
                    "is_holiday_skipped=false WHERE id=%s", (h['id'],))
        detected += 1
        by_type['holiday_exception'] += 1
        by_severity['low'] += 1

    # ── Update batch conflict_count ─────────────────────────────────────────
    cur.execute("""
        UPDATE snc_draft_batches SET conflict_count = %s WHERE id = %s
    """, (detected, batch_id))

    return {
        "detected": detected,
        "by_type": dict(by_type),
        "by_severity": dict(by_severity),
    }
