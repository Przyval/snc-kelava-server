"""
Export jadwal teknisi ke Excel dengan format yang sama dengan
file historical di Jadwal Teknisi/ folder.

Layout per sheet (1 sheet per teknisi):
  Row 1: TEKNISI : <NAME>  |  JADWAL TEKNISI BULAN <X> <YEAR>
  Row 2: SUPERVISOR : <NAME>
  Row 3: TOTAL KUNJUNGAN : <N>
  Row 4: JAM EFEKTIF : <H>
  Row 5: SENIN | SELASA | RABU | KAMIS | JUMAT | SABTU | MINGGU
         (merged 3-col per day)
  Row 6: [date] [date] [date] [date] [date] [date] [date]
  Row 7-N: customer rows (per day: name, time, type)
  Repeat blocks per minggu in source month.

Usage (CLI):
    python -m kil.backend.scripts.export_jadwal_xlsx 2026-07 > out.xlsx

Usage (programmatic):
    from kil.backend.scripts.export_jadwal_xlsx import export_jadwal
    xlsx_bytes = export_jadwal('2026-07', batch_id=42)
"""
import argparse
import calendar
import io
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from kil.db.kelava_db import _get_local_pool
from psycopg.rows import dict_row

# SanoCare branding logo (370×62 RGBA PNG)
LOGO_PATH = Path(__file__).resolve().parents[2] / 'backend' / 'legacy' / 'web' / 'enterprise' / 'static' / 'img' / 'logo_snc.png'

BULAN_ID = ['', 'JANUARI', 'FEBRUARI', 'MARET', 'APRIL', 'MEI', 'JUNI',
            'JULI', 'AGUSTUS', 'SEPTEMBER', 'OKTOBER', 'NOVEMBER', 'DESEMBER']

# Order sheet output sesuai SHEET_MAP di importer
SHEET_ORDER = [
    ('AKBAR R',   'Akbar Rohmatulah'),
    ('ANAM',      'Choirul Anam'),
    ('ABU S',     'M. Abu Samsudin'),
    ('ALMAS',     'Ananda Almas'),
    ('ADAM',      'Adam Abdillah'),
    ('MAHRUS',    'Moh. Mahrus'),
    ('ANDIK',     'Andik Noroyan Fananiar'),
    ('LUCKY',     'Lucky Adi Putra'),
    ('MAULANA',   'Moch Maulana'),
    ('RANGGA',    'Rangga'),
    ('FATHUR',    'Fathur Rozek'),
    ('IMAM',      'Nur Imam Siswo Utomo'),
    ('ARGA',      'Argantara Alif Saputra'),
    ('RENDY',     'I Wayan Rendy'),
    ('IRUL',      'Irul'),
    ('MULYASARI', 'Muliyasari'),
]

# Layout config
DAYS = ['SENIN', 'SELASA', 'RABU', 'KAMIS', 'JUMAT', 'SABTU', 'MINGGU']
SUBCOLS_PER_DAY = 3  # name, time, type
TOTAL_COLS = len(DAYS) * SUBCOLS_PER_DAY  # 21


# ─────────────────────────────────────────────────────────────────────────────
# Styling
# ─────────────────────────────────────────────────────────────────────────────

THIN = Side(border_style='thin', color='B0B0B0')
BORDER = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)

STYLE_TITLE = {
    'font': Font(name='Calibri', bold=True, size=14, color='EA580C'),  # SanoCare orange
    'alignment': Alignment(horizontal='center', vertical='center'),
}
STYLE_HEADER_LABEL = {
    'font': Font(name='Calibri', bold=True, size=11),
    'alignment': Alignment(horizontal='left'),
}
STYLE_DOW = {
    'font': Font(name='Calibri', bold=True, size=11),
    'fill': PatternFill('solid', fgColor='FFE699'),
    'alignment': Alignment(horizontal='center', vertical='center'),
    'border': BORDER,
}
STYLE_DATE = {
    'font': Font(name='Calibri', bold=True, size=10),
    'fill': PatternFill('solid', fgColor='FFF2CC'),
    'alignment': Alignment(horizontal='center', vertical='center'),
    'border': BORDER,
    'number_format': 'd-mmm-yy',
}
STYLE_CUSTOMER = {
    'font': Font(name='Calibri', bold=True, size=10),
    'alignment': Alignment(horizontal='left', vertical='center', wrap_text=False),
    'border': BORDER,
}
STYLE_TIME = {
    'font': Font(name='Calibri', size=10),
    'alignment': Alignment(horizontal='center', vertical='center'),
    'border': BORDER,
}
STYLE_TYPE = {
    'font': Font(name='Calibri', italic=True, size=10),
    'alignment': Alignment(horizontal='center', vertical='center'),
    'border': BORDER,
}
STYLE_OFF = {
    'font': Font(name='Calibri', bold=True, size=10, color='D32F2F'),
    'alignment': Alignment(horizontal='center', vertical='center'),
    'border': BORDER,
}


def _apply_style(cell, style: dict):
    if 'font' in style: cell.font = style['font']
    if 'fill' in style: cell.fill = style['fill']
    if 'alignment' in style: cell.alignment = style['alignment']
    if 'border' in style: cell.border = style['border']
    if 'number_format' in style: cell.number_format = style['number_format']


def _fmt_time_range(start_dt, end_dt) -> str:
    """Format datetime as 'HH.MM-HH.MM' for xlsx (dot separator)."""
    if not start_dt:
        return ''
    s = start_dt.strftime('%H.%M')
    if not end_dt:
        return s
    e = end_dt.strftime('%H.%M')
    return f"{s}-{e}"


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def _load_data(cur, target_month: str, batch_id: int | None,
               status_filter: list[str] | None) -> dict:
    """
    Returns:
      {
        'month': '2026-07',
        'year': 2026, 'month_num': 7,
        'events_by_tech': {tech_id: [event_dict, ...]},
        'tech_info': {tech_id: {'name','supervisor_name','kelava_p_user_id'}},
        'suppressed_dates': set([date,...]),       # global holidays
        'tech_off_dates': {tech_id: {date: status}},  # cuti/sakit/training
      }
    """
    year, mnum = map(int, target_month.split('-'))
    _, ndays = calendar.monthrange(year, mnum)
    mstart, mend = date(year, mnum, 1), date(year, mnum, ndays)

    # Batch resolution
    if batch_id is None:
        cur.execute(
            "SELECT id FROM snc_draft_batches WHERE target_month = %s "
            "ORDER BY id DESC LIMIT 1", (target_month,))
        row = cur.fetchone()
        batch_id = row['id'] if row else None

    statuses = status_filter or ['draft', 'scheduled', 'approved', 'published']

    # Events
    if batch_id:
        cur.execute("""
            SELECT se.id, se.technician_id, se.client_id,
                   se.visit_type, se.start_datetime, se.end_datetime,
                   se.start_date, se.schedule_status,
                   t.name AS tech_name, t.kelava_p_user_id,
                   c.name AS client_name,
                   s.name AS supervisor_name
            FROM snc_schedule_events se
            JOIN snc_technicians t ON t.id = se.technician_id
            JOIN snc_clients c ON c.id = se.client_id
            LEFT JOIN snc_supervisors s ON s.id = t.supervisor_id
            WHERE (se.draft_batch_id = %s OR se.start_date BETWEEN %s AND %s)
              AND se.schedule_status = ANY(%s)
            ORDER BY se.technician_id, se.start_date, se.start_datetime
        """, (batch_id, mstart, mend, statuses))
    else:
        cur.execute("""
            SELECT se.id, se.technician_id, se.client_id,
                   se.visit_type, se.start_datetime, se.end_datetime,
                   se.start_date, se.schedule_status,
                   t.name AS tech_name, t.kelava_p_user_id,
                   c.name AS client_name,
                   s.name AS supervisor_name
            FROM snc_schedule_events se
            JOIN snc_technicians t ON t.id = se.technician_id
            JOIN snc_clients c ON c.id = se.client_id
            LEFT JOIN snc_supervisors s ON s.id = t.supervisor_id
            WHERE se.start_date BETWEEN %s AND %s
              AND se.schedule_status = ANY(%s)
            ORDER BY se.technician_id, se.start_date, se.start_datetime
        """, (mstart, mend, statuses))
    events = cur.fetchall()

    events_by_tech = defaultdict(list)
    tech_info = {}
    for e in events:
        tid = e['technician_id']
        events_by_tech[tid].append(e)
        if tid not in tech_info:
            tech_info[tid] = {
                'name': e['tech_name'],
                'supervisor_name': e['supervisor_name'] or '',
                'kelava_p_user_id': e['kelava_p_user_id'],
            }

    # Suppression: global holidays
    cur.execute("""
        SELECT suppression_date FROM snc_suppression_dates
        WHERE suppression_date BETWEEN %s AND %s
    """, (mstart, mend))
    suppressed = {r['suppression_date'] for r in cur.fetchall()}

    # Tech off/sick/training dates
    cur.execute("""
        SELECT technician_id, date, status FROM snc_technician_day_status
        WHERE date BETWEEN %s AND %s AND status IN ('off','sick','training')
    """, (mstart, mend))
    tech_off = defaultdict(dict)
    for r in cur.fetchall():
        tech_off[r['technician_id']][r['date']] = r['status']

    return {
        'month': target_month, 'year': year, 'month_num': mnum,
        'batch_id': batch_id,
        'mstart': mstart, 'mend': mend,
        'events_by_tech': events_by_tech,
        'tech_info': tech_info,
        'suppressed_dates': suppressed,
        'tech_off_dates': tech_off,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Week grouping helper
# ─────────────────────────────────────────────────────────────────────────────

def _weeks_of_month(year: int, month_num: int) -> list[list[date]]:
    """
    Returns list of week-blocks. Each block = list of 7 dates (Mon..Sun) where
    dates outside month are still included for layout consistency.

    Use ISO week (Mon-start). First week includes the 1st of month.
    """
    _, ndays = calendar.monthrange(year, month_num)
    first = date(year, month_num, 1)
    last = date(year, month_num, ndays)
    # Find Monday on/before 1st of month
    mon = first - timedelta(days=first.weekday())
    weeks = []
    cur = mon
    while cur <= last:
        block = [cur + timedelta(days=i) for i in range(7)]
        weeks.append(block)
        cur += timedelta(days=7)
    return weeks


# ─────────────────────────────────────────────────────────────────────────────
# Per-sheet rendering
# ─────────────────────────────────────────────────────────────────────────────

def _render_tech_sheet(ws, sheet_name: str, real_tech_name: str,
                       tech_info: dict, tech_events: list,
                       year: int, month_num: int,
                       tech_off_dates: dict, suppressed_dates: set,
                       only_week: int | None = None):
    """Render single tech sheet. If only_week=1..5, only that week-block."""
    bulan_label = BULAN_ID[month_num]
    title = f'JADWAL TEKNISI BULAN {bulan_label} {year}'
    supervisor = tech_info.get('supervisor_name', '') or 'FAHMI'
    total_visits = len(tech_events)
    # JAM EFEKTIF: sum durasi events (hours)
    jam_efektif = 0
    for e in tech_events:
        if e['start_datetime'] and e['end_datetime']:
            dur = (e['end_datetime'] - e['start_datetime']).total_seconds() / 3600
            jam_efektif += dur
    jam_efektif = round(jam_efektif, 1)

    # ── Embed SanoCare logo (top-right) ──
    try:
        if LOGO_PATH.exists():
            img = XlImage(str(LOGO_PATH))
            # Scale to ~120px wide for header
            scale = 120 / img.width
            img.width  = int(img.width * scale)
            img.height = int(img.height * scale)
            img.anchor = 'O1'  # column O, row 1 = top-right area
            ws.add_image(img)
            # Increase row 1-2 height to fit logo
            ws.row_dimensions[1].height = 22
            ws.row_dimensions[2].height = 22
    except Exception:
        pass  # logo optional, don't fail export if image library missing

    # ── Row 1: TEKNISI : <NAME>  |  TITLE ──
    ws.cell(1, 1, 'TEKNISI').font = STYLE_HEADER_LABEL['font']
    ws.cell(1, 3, f': {real_tech_name}').font = Font(name='Calibri', size=11)
    ws.cell(1, 7, title)
    _apply_style(ws.cell(1, 7), STYLE_TITLE)
    ws.merge_cells(start_row=1, start_column=7, end_row=1, end_column=14)

    # ── Row 2-4 ──
    ws.cell(2, 1, 'SUPERVISOR').font = STYLE_HEADER_LABEL['font']
    ws.cell(2, 3, f': {supervisor}').font = Font(name='Calibri', size=11)
    ws.cell(3, 1, 'TOTAL KUNJUNGAN').font = STYLE_HEADER_LABEL['font']
    ws.cell(3, 3, f': {total_visits}').font = Font(name='Calibri', size=11)
    ws.cell(4, 1, 'JAM EFEKTIF').font = STYLE_HEADER_LABEL['font']
    ws.cell(4, 3, f': {jam_efektif}').font = Font(name='Calibri', size=11)

    # ── Group events by date ──
    events_by_date = defaultdict(list)
    for e in tech_events:
        events_by_date[e['start_date']].append(e)

    # ── Render weekly blocks ──
    weeks = _weeks_of_month(year, month_num)
    if only_week and 1 <= only_week <= len(weeks):
        weeks = [weeks[only_week - 1]]
    cur_row = 6  # start after header rows (5 blank)

    for week in weeks:
        # DOW header row
        for di, dname in enumerate(DAYS):
            col = di * SUBCOLS_PER_DAY + 1
            cell = ws.cell(cur_row, col, dname)
            _apply_style(cell, STYLE_DOW)
            # Merge 3 cols per day
            ws.merge_cells(start_row=cur_row, start_column=col,
                           end_row=cur_row, end_column=col + SUBCOLS_PER_DAY - 1)
        cur_row += 1

        # Date row
        for di, d in enumerate(week):
            col = di * SUBCOLS_PER_DAY + 1
            cell = ws.cell(cur_row, col)
            if d.month == month_num:
                cell.value = d
                _apply_style(cell, STYLE_DATE)
            else:
                cell.fill = PatternFill('solid', fgColor='F0F0F0')
                cell.border = BORDER
            ws.merge_cells(start_row=cur_row, start_column=col,
                           end_row=cur_row, end_column=col + SUBCOLS_PER_DAY - 1)
        cur_row += 1

        # Customer rows: find max event count this week
        max_evts = max(
            (len(events_by_date.get(d, [])) for d in week),
            default=0
        )
        # Min 3 rows per block for visual consistency
        n_rows = max(max_evts, 3)

        for ri in range(n_rows):
            for di, d in enumerate(week):
                col = di * SUBCOLS_PER_DAY + 1
                if d.month != month_num:
                    # Out-of-month: just border
                    for sc in range(SUBCOLS_PER_DAY):
                        ws.cell(cur_row, col + sc).border = BORDER
                    continue
                # Skip global holiday
                if d in suppressed_dates and ri == 0:
                    ws.cell(cur_row, col, 'LIBUR').font = Font(name='Calibri', bold=True, color='9C27B0')
                    ws.cell(cur_row, col).alignment = Alignment(horizontal='center')
                    ws.cell(cur_row, col).border = BORDER
                    for sc in range(1, SUBCOLS_PER_DAY):
                        ws.cell(cur_row, col + sc).border = BORDER
                    continue
                # Skip tech off
                tid = tech_info.get('_id', None)  # we'll handle below
                evts = events_by_date.get(d, [])
                if ri < len(evts):
                    e = evts[ri]
                    ws.cell(cur_row, col, e['client_name'])
                    _apply_style(ws.cell(cur_row, col), STYLE_CUSTOMER)
                    ws.cell(cur_row, col + 1, _fmt_time_range(e['start_datetime'], e['end_datetime']))
                    _apply_style(ws.cell(cur_row, col + 1), STYLE_TIME)
                    ws.cell(cur_row, col + 2, e.get('visit_type') or '')
                    _apply_style(ws.cell(cur_row, col + 2), STYLE_TYPE)
                else:
                    for sc in range(SUBCOLS_PER_DAY):
                        ws.cell(cur_row, col + sc).border = BORDER
            cur_row += 1

        # Blank separator row
        cur_row += 1

    # Column widths
    for di in range(len(DAYS)):
        col_name = get_column_letter(di * SUBCOLS_PER_DAY + 1)
        col_time = get_column_letter(di * SUBCOLS_PER_DAY + 2)
        col_type = get_column_letter(di * SUBCOLS_PER_DAY + 3)
        ws.column_dimensions[col_name].width = 18
        ws.column_dimensions[col_time].width = 12
        ws.column_dimensions[col_type].width = 7

    # Freeze top 5 rows
    ws.freeze_panes = 'A6'


def _render_off_overlay(ws, tech_id: int, year: int, month_num: int,
                        tech_off_dates: dict):
    """After main rendering, overlay OFF markers on tech-unavailable dates."""
    off_for_tech = tech_off_dates.get(tech_id, {})
    if not off_for_tech:
        return
    weeks = _weeks_of_month(year, month_num)
    cur_row = 6
    for week in weeks:
        cur_row += 1  # DOW row
        cur_row += 1  # date row
        # Customer rows start here. Find row count actually rendered.
        # Easier: look at first customer row only and inject OFF
        max_evts = 3  # min rows per block (matches render logic)
        # Override first row of any OFF day with red OFF text
        for di, d in enumerate(week):
            if d in off_for_tech:
                col = di * SUBCOLS_PER_DAY + 1
                status = off_for_tech[d].upper()
                label = {'OFF': 'CUTI', 'SICK': 'SAKIT', 'TRAINING': 'TRAINING'}.get(status, status)
                # Place at first customer row of this block
                ws.cell(cur_row, col, label)
                _apply_style(ws.cell(cur_row, col), STYLE_OFF)
        cur_row += max_evts + 1  # advance past customer rows + blank


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────

def export_jadwal(
    target_month: str,
    batch_id: int | None = None,
    status_filter: list[str] | None = None,
    only_tech_id: int | None = None,
    only_week: int | None = None,  # 1-5 = filter to specific week-of-month
) -> bytes:
    """
    Export jadwal teknisi for target_month as xlsx bytes.

    Optional filters:
      only_tech_id : export 1 teknisi saja (single-sheet workbook)
      only_week    : 1-5, export hanya 1 minggu (saved sheet jadi pendek)
    """
    with _get_local_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            data = _load_data(cur, target_month, batch_id, status_filter)

    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Build name → tech_id lookup from DB
    name_to_id = {info['name']: tid for tid, info in data['tech_info'].items()}

    for sheet_name, real_name in SHEET_ORDER:
        tid = name_to_id.get(real_name)
        if only_tech_id and tid != only_tech_id:
            continue
        events = data['events_by_tech'].get(tid, []) if tid else []

        ws = wb.create_sheet(title=sheet_name)
        tech_info = (data['tech_info'].get(tid, {}) if tid
                     else {'name': real_name, 'supervisor_name': 'FAHMI'})
        _render_tech_sheet(
            ws, sheet_name, real_name, tech_info, events,
            data['year'], data['month_num'],
            data['tech_off_dates'], data['suppressed_dates'],
            only_week=only_week,
        )
        if tid:
            _render_off_overlay(ws, tid, data['year'], data['month_num'],
                                data['tech_off_dates'])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('target_month', help='YYYY-MM, e.g. 2026-07')
    ap.add_argument('--batch-id', type=int, default=None)
    ap.add_argument('--output', '-o', default=None,
                    help='Output path. Default = "JADWAL TEKNISI <BULAN> <YEAR>.xlsx"')
    args = ap.parse_args()

    xlsx = export_jadwal(args.target_month, batch_id=args.batch_id)

    if args.output:
        out = args.output
    else:
        y, m = map(int, args.target_month.split('-'))
        out = f'JADWAL TEKNISI {BULAN_ID[m]} {y}.xlsx'
    with open(out, 'wb') as f:
        f.write(xlsx)
    print(f'✓ {out}  ({len(xlsx):,} bytes)')


if __name__ == '__main__':
    main()
