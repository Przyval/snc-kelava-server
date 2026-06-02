"""
Compare Excel (uploaded) vs current draft for a target month.
PRD §9, §14.5

POST /audit/compare/upload      — upload xlsx, parse, classify diff vs draft
GET  /audit/compare/<upload_id> — fetch compare results (with filters)
PUT  /audit/compare/<row_id>    — update resolution
POST /audit/compare/<row_id>/resolve — quick resolve action
"""

import io
import json
import re
from collections import defaultdict
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request

from kil.backend.core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

compare_bp = Blueprint("audit_compare", __name__, url_prefix="/api/v1/enterprise/audit/compare")

NON_CUSTOMER = {'OFF','CUTI','LIBUR','NO','P','X','S','JP','ST','TP','PM','BDG',
                'KETERANGAN','Keterangan:','Penanggung Jawab','SNC TEAM','OFFICE SNC',
                'OFFICE HCI'}
TECH_MAP_BY_SHEET = {
    'ADAM': 5, 'AKBAR R': 1, 'ALMAS': 4, 'ANAM': 2, 'ABU S': 3,
    'ANDIK': 7, 'LUCKY': 8, 'MAHRUS': 6, 'MAULANA': 9,
    'FATHUR': 51, 'RANGGA': 10, 'IMAM': 12, 'ARGA': 13, 'RENDY': 14, 'IRUL': 15,
    'MULYASARI': 15,  # Note: maps to same id as Irul historically; user may correct
}


def _require_koord():
    user = getattr(g, "current_user", None) or getattr(request, "_jwt_user", {})
    role = user.get("role") if isinstance(user, dict) else getattr(user, "role", None)
    uid = user.get("id") if isinstance(user, dict) else getattr(user, "id", 0)
    if role not in ("admin", "koordinator"):
        return None, (jsonify({"error": "Forbidden"}), 403)
    return uid, None


def _parse_xlsx(file_bytes: bytes) -> tuple[list, list]:
    """Parse uploaded xlsx to list of {date, tech_sheet, customer, time_start, time_end, type}."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    visits, errors = [], []
    DOW_LABELS = {'SENIN','SELASA','RABU','KAMIS','JUMAT','SABTU','MINGGU'}

    def parse_tr(s):
        if not s or not isinstance(s, str): return (None, None)
        s = s.strip().replace(' ','').replace('.',':')
        m = re.match(r'(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})', s)
        if not m: return (None, None)
        return (f"{int(m[1])%24:02d}:{m[2]}", f"{int(m[3])%24:02d}:{m[4]}")

    for sn in wb.sheetnames:
        sheet_key = sn.strip().upper()
        ws = wb[sn]
        date_cols = {}
        for r in range(1, ws.max_row + 1):
            row = [ws.cell(r, c).value for c in range(1, min(ws.max_column+1, 25))]
            dates_in_row = [(c, v) for c, v in enumerate(row, 1) if isinstance(v, datetime)]
            if dates_in_row:
                date_cols = {c: v.date() for c, v in dates_in_row}
                continue
            if not date_cols:
                continue
            for col, dt in date_cols.items():
                name = ws.cell(r, col).value
                time_s = ws.cell(r, col + 1).value
                type_s = ws.cell(r, col + 2).value
                if name and isinstance(name, str) and name.strip() and name.strip().upper() not in DOW_LABELS and name.strip() not in NON_CUSTOMER:
                    t_start, t_end = parse_tr(time_s)
                    visits.append({
                        'tech_sheet': sheet_key,
                        'customer': name.strip(),
                        'date': dt.isoformat(),
                        'time_start': t_start,
                        'time_end': t_end,
                        'visit_type': (type_s or '').strip() if type_s else None,
                    })
    return visits, errors


def _resolve_clients_techs(cur, visits: list) -> list:
    """Add client_id + tech_id to each visit via fuzzy + sheet map."""
    cur.execute("SELECT id, name FROM snc_clients")
    rows = cur.fetchall()
    norm = lambda s: re.sub(r'[^a-z0-9]','',s.lower())
    idx = {norm(r['name']): r['id'] for r in rows}
    # Also alias lookup
    cur.execute("SELECT alias, client_id FROM snc_client_aliases")
    alias_idx = {norm(r['alias']): r['client_id'] for r in cur.fetchall()}

    resolved = []
    for v in visits:
        cn = norm(v['customer'])
        cid = alias_idx.get(cn) or idx.get(cn)
        if not cid and len(cn) >= 5:
            for n2, id2 in idx.items():
                if len(n2) >= 5 and (cn in n2 or n2 in cn):
                    cid = id2; break
        tid = TECH_MAP_BY_SHEET.get(v['tech_sheet'].strip())
        resolved.append({**v, 'client_id': cid, 'tech_id': tid})
    return resolved


def _classify(excel_visits: list, system_events: list) -> list:
    """
    Classify each diff into one of 10 categories (PRD §9.3):
      same | tech_diff_absence | tech_diff_backup | system_added | excel_only
      system_missing_no_rule | dup_excel | dup_system | manual | unresolved
    """
    # Build lookups by (client_id, date)
    sys_by_cd = defaultdict(list)
    for e in system_events:
        sys_by_cd[(e['client_id'], e['start_date'])].append(e)
    excel_by_cd = defaultdict(list)
    for v in excel_visits:
        if v.get('client_id') and v.get('date'):
            excel_by_cd[(v['client_id'], v['date'])].append(v)

    results = []
    matched_event_ids = set()

    # Walk excel visits
    for (cid, dstr), e_list in excel_by_cd.items():
        try:
            d = date.fromisoformat(dstr)
        except (ValueError, TypeError):
            continue
        sys_list = [e for e in sys_by_cd.get((cid, d), []) if e['id'] not in matched_event_ids]
        # Dup in Excel?
        if len(e_list) > 1:
            for ev in e_list:
                results.append({**ev, 'system_event_id': None, 'diff_category': 'dup_excel'})
            continue
        ev = e_list[0]
        if not sys_list:
            results.append({**ev, 'system_event_id': None, 'diff_category': 'excel_only'})
            continue
        # Try match by tech first
        matched = None
        for se in sys_list:
            if ev.get('tech_id') and se['technician_id'] == ev['tech_id']:
                matched = se
                break
        if matched:
            matched_event_ids.add(matched['id'])
            results.append({**ev, 'system_event_id': matched['id'], 'diff_category': 'same'})
        else:
            # Different tech → assume backup/reassignment
            se = sys_list[0]
            matched_event_ids.add(se['id'])
            results.append({**ev, 'system_event_id': se['id'], 'diff_category': 'tech_diff_backup'})

    # Walk remaining system events (not matched by Excel)
    for e in system_events:
        if e['id'] in matched_event_ids:
            continue
        sys_by_cd_count = len(sys_by_cd.get((e['client_id'], e['start_date']), []))
        cat = 'dup_system' if sys_by_cd_count > 1 else 'system_added'
        results.append({
            'tech_sheet': e.get('tech_name', ''),
            'customer': e.get('client_name', ''),
            'date': e['start_date'].isoformat(),
            'time_start': e['start_datetime'].strftime('%H:%M') if e['start_datetime'] else None,
            'time_end': e['end_datetime'].strftime('%H:%M') if e['end_datetime'] else None,
            'visit_type': e.get('visit_type'),
            'client_id': e['client_id'],
            'tech_id': e['technician_id'],
            'system_event_id': e['id'],
            'diff_category': cat,
        })
    return results


# ─────────────────────────────────────────────────────────────────────────────

@compare_bp.route("/upload", methods=["POST"])
@require_auth
def upload_xlsx():
    user_id, forbidden = _require_koord()
    if forbidden:
        return forbidden
    if 'file' not in request.files:
        return jsonify({"error": "File xlsx wajib"}), 400
    f = request.files['file']
    target_month = (request.form.get('target_month') or '').strip()
    if not target_month:
        return jsonify({"error": "target_month wajib"}), 400
    try:
        datetime.strptime(target_month + '-01', '%Y-%m-%d')
    except ValueError:
        return jsonify({"error": "Format target_month YYYY-MM"}), 400

    try:
        file_bytes = f.read()
        visits, errors = _parse_xlsx(file_bytes)
    except Exception as e:
        return jsonify({"error": "Gagal parse xlsx", "detail": str(e)}), 400

    # Filter to target month
    visits = [v for v in visits if v['date'].startswith(target_month)]

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            resolved = _resolve_clients_techs(cur, visits)

            # Load current system events for that month
            cur.execute("""
                SELECT se.id, se.technician_id, se.client_id,
                       se.start_date, se.start_datetime, se.end_datetime,
                       se.visit_type, t.name AS tech_name, c.name AS client_name
                FROM snc_schedule_events se
                JOIN snc_technicians t ON t.id = se.technician_id
                JOIN snc_clients c ON c.id = se.client_id
                WHERE TO_CHAR(se.start_date,'YYYY-MM') = %s
                  AND se.schedule_status IN ('draft','scheduled','approved','published')
            """, (target_month,))
            sys_events = cur.fetchall()

            # Insert upload record
            cur.execute("""
                INSERT INTO snc_excel_upload
                    (filename, target_month, uploaded_by, raw_visit_count, parsed_payload)
                VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id
            """, (f.filename, target_month, user_id, len(visits),
                  json.dumps({'visits': visits, 'errors': errors})))
            upload_id = cur.fetchone()['id']

            # Classify + insert compare results
            results = _classify(resolved, sys_events)
            for r in results:
                cur.execute("""
                    INSERT INTO snc_compare_results
                        (upload_id, target_month, excel_tech_id, excel_client_id,
                         excel_date, excel_time, system_event_id, diff_category, resolution)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """, (upload_id, target_month, r.get('tech_id'), r.get('client_id'),
                      r.get('date'), r.get('time_start'),
                      r.get('system_event_id'), r['diff_category']))
            conn.commit()

    summary = defaultdict(int)
    for r in results:
        summary[r['diff_category']] += 1

    return jsonify({
        'upload_id': upload_id,
        'target_month': target_month,
        'parsed_visits': len(visits),
        'system_events': len(sys_events),
        'compare_rows': len(results),
        'summary': dict(summary),
        'message': f'{len(results)} rows of comparison saved',
    }), 201


@compare_bp.route("/list", methods=["GET"])
@require_auth
def list_uploads():
    target_month = request.args.get('target_month', '').strip()
    where, params = ["1=1"], []
    if target_month:
        where.append("target_month = %s")
        params.append(target_month)
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                SELECT id, filename, target_month, uploaded_by, uploaded_at, raw_visit_count
                FROM snc_excel_upload
                WHERE {' AND '.join(where)}
                ORDER BY uploaded_at DESC LIMIT 50
            """, params)
            rows = cur.fetchall()
    for r in rows:
        r['uploaded_at'] = r['uploaded_at'].isoformat()
    return jsonify({'uploads': rows})


@compare_bp.route("/<int:upload_id>", methods=["GET"])
@require_auth
def get_compare(upload_id):
    category = request.args.get('category', '').strip()
    resolution = request.args.get('resolution', '').strip()
    where, params = ["upload_id = %s"], [upload_id]
    if category:
        where.append("diff_category = %s"); params.append(category)
    if resolution:
        where.append("resolution = %s"); params.append(resolution)
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"""
                SELECT cr.*,
                       c.name AS client_name,
                       t.name AS tech_name,
                       se.start_datetime, se.technician_id AS sys_tech_id,
                       st.name AS sys_tech_name
                FROM snc_compare_results cr
                LEFT JOIN snc_clients c ON c.id = cr.excel_client_id
                LEFT JOIN snc_technicians t ON t.id = cr.excel_tech_id
                LEFT JOIN snc_schedule_events se ON se.id = cr.system_event_id
                LEFT JOIN snc_technicians st ON st.id = se.technician_id
                WHERE {' AND '.join(where)}
                ORDER BY cr.diff_category, cr.excel_date
                LIMIT 1000
            """, params)
            rows = cur.fetchall()
            # Summary
            cur.execute("""
                SELECT diff_category, resolution, COUNT(*) AS n
                FROM snc_compare_results
                WHERE upload_id = %s
                GROUP BY diff_category, resolution
            """, (upload_id,))
            summary_rows = cur.fetchall()
    summary = defaultdict(lambda: defaultdict(int))
    for r in summary_rows:
        summary[r['diff_category']][r['resolution']] = r['n']

    for r in rows:
        if r.get('excel_date'):
            r['excel_date'] = r['excel_date'].isoformat()
        if r.get('start_datetime'):
            r['start_datetime'] = r['start_datetime'].isoformat()
        if r.get('resolved_at'):
            r['resolved_at'] = r['resolved_at'].isoformat()
    return jsonify({'rows': rows, 'summary': dict(summary)})


@compare_bp.route("/row/<int:row_id>/resolve", methods=["POST"])
@require_auth
def resolve_row(row_id):
    user_id, forbidden = _require_koord()
    if forbidden:
        return forbidden
    data = request.get_json() or {}
    resolution = (data.get('resolution') or 'accepted').strip()
    notes = data.get('notes')
    if resolution not in ('pending', 'accepted', 'fixed', 'ignored'):
        return jsonify({"error": "Resolution invalid"}), 400
    with _get_local_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE snc_compare_results
                SET resolution=%s, resolved_by=%s, resolved_at=now(), notes=%s
                WHERE id=%s
            """, (resolution, user_id, notes, row_id))
            conn.commit()
    return jsonify({'id': row_id, 'resolution': resolution})
