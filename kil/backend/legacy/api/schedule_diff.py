"""
Schedule Diff API — compare 2 months (or 2 batches) side-by-side.

Output kategori:
  - added     : event yang ada di TO tapi tidak di FROM (visit baru bulan TO)
  - removed   : event yang ada di FROM tapi tidak di TO (visit hilang)
  - reassigned: same (client, date) tapi tech berbeda
  - retimed   : same (client, date, tech) tapi start_time berbeda

GET /api/v1/enterprise/calendar/diff?from=2026-06&to=2026-07
"""

from collections import defaultdict
from datetime import datetime

from flask import Blueprint, jsonify, request

from kil.backend.core.security import require_auth
from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

diff_bp = Blueprint("schedule_diff", __name__, url_prefix="/api/v1/enterprise")


def _load_month_events(cur, month: str) -> dict:
    """
    Load events for a month, return dict keyed by (client_id, start_date)
    with list of events (untuk handle multi-tech co-visit + multi-event/day).
    """
    cur.execute("""
        SELECT se.id, se.technician_id, se.client_id, se.start_date,
               se.start_datetime, se.end_datetime, se.visit_type,
               se.schedule_status,
               t.name AS tech_name, c.name AS client_name
        FROM snc_schedule_events se
        JOIN snc_technicians t ON t.id = se.technician_id
        JOIN snc_clients c ON c.id = se.client_id
        WHERE TO_CHAR(se.start_date, 'YYYY-MM') = %s
          AND se.schedule_status IN ('draft', 'scheduled', 'approved', 'published')
    """, (month,))
    rows = cur.fetchall()
    by_cd = defaultdict(list)
    for r in rows:
        by_cd[(r['client_id'], r['start_date'])].append(r)
    return by_cd


@diff_bp.route("/calendar/diff", methods=["GET"])
@require_auth
def calendar_diff():
    from_m = request.args.get("from", "").strip()
    to_m   = request.args.get("to", "").strip()
    if not from_m or not to_m:
        return jsonify({"error": "Param 'from' dan 'to' wajib (format YYYY-MM)"}), 400
    try:
        datetime.strptime(from_m + '-01', '%Y-%m-%d')
        datetime.strptime(to_m + '-01', '%Y-%m-%d')
    except ValueError:
        return jsonify({"error": "Format bulan harus YYYY-MM"}), 400

    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            from_events = _load_month_events(cur, from_m)
            to_events = _load_month_events(cur, to_m)

    # Build comparison anchored on (client_id, day_of_month) — kalau Juli punya
    # same DOM (e.g. tgl 5) yang Juni juga ada → kemungkinan recurrence yang sama
    from_by_client_dom = defaultdict(list)
    for (cid, sd), evs in from_events.items():
        from_by_client_dom[(cid, sd.day)].extend([(sd, e) for e in evs])

    to_by_client_dom = defaultdict(list)
    for (cid, sd), evs in to_events.items():
        to_by_client_dom[(cid, sd.day)].extend([(sd, e) for e in evs])

    added, removed, reassigned, retimed = [], [], [], []
    seen_from_ids = set()

    def _ev_dict(sd, e):
        return {
            'client_id': e['client_id'], 'client_name': e['client_name'],
            'tech_name': e['tech_name'],
            'date': sd.isoformat(),
            'time': (e['start_datetime'].strftime('%H:%M')
                     if e['start_datetime'] else None),
        }

    # Walk TO events, try match in FROM by (client, dom)
    for (cid, dom), to_pairs in to_by_client_dom.items():
        from_pairs = list(from_by_client_dom.get((cid, dom), []))

        for sd_to, ev_to in to_pairs:
            # Find from event with same tech (best match — same recurrence)
            match_idx = None
            for idx, (sd_from, ev_from) in enumerate(from_pairs):
                if (ev_from['id'] not in seen_from_ids
                    and ev_from['technician_id'] == ev_to['technician_id']):
                    match_idx = idx
                    break
            if match_idx is not None:
                sd_from, ev_from = from_pairs[match_idx]
                seen_from_ids.add(ev_from['id'])
                # Same tech → check if time differs = retimed
                ts_to = ev_to['start_datetime'].time() if ev_to['start_datetime'] else None
                ts_from = ev_from['start_datetime'].time() if ev_from['start_datetime'] else None
                if ts_to != ts_from and ts_to and ts_from:
                    retimed.append({
                        'client_id': cid, 'client_name': ev_to['client_name'],
                        'tech_name': ev_to['tech_name'],
                        'from_date': sd_from.isoformat(),
                        'from_time': ts_from.strftime('%H:%M'),
                        'to_date': sd_to.isoformat(),
                        'to_time': ts_to.strftime('%H:%M'),
                    })
                continue

            # No same-tech match. Try any unmatched from event (different tech) = reassigned
            match_idx = None
            for idx, (sd_from, ev_from) in enumerate(from_pairs):
                if ev_from['id'] not in seen_from_ids:
                    match_idx = idx
                    break
            if match_idx is not None:
                sd_from, ev_from = from_pairs[match_idx]
                seen_from_ids.add(ev_from['id'])
                reassigned.append({
                    'client_id': cid, 'client_name': ev_to['client_name'],
                    'from_tech': ev_from['tech_name'], 'to_tech': ev_to['tech_name'],
                    'from_date': sd_from.isoformat(),
                    'to_date': sd_to.isoformat(),
                })
            else:
                added.append(_ev_dict(sd_to, ev_to))

    # Unmatched FROM events = removed
    for (cid, sd), evs in from_events.items():
        for e in evs:
            if e['id'] not in seen_from_ids:
                removed.append(_ev_dict(sd, e))

    # Summary
    total_from = sum(len(v) for v in from_events.values())
    total_to   = sum(len(v) for v in to_events.values())
    return jsonify({
        'from_month': from_m,
        'to_month': to_m,
        'summary': {
            'total_from':  total_from,
            'total_to':    total_to,
            'added':       len(added),
            'removed':     len(removed),
            'reassigned':  len(reassigned),
            'retimed':     len(retimed),
            'unchanged':   total_to - len(added) - len(reassigned) - len(retimed),
        },
        'added':      added[:200],
        'removed':    removed[:200],
        'reassigned': reassigned[:200],
        'retimed':    retimed[:200],
    })
