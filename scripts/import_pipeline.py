#!/usr/bin/env python3
"""
Import GetFound Sales Pipeline Data
=====================================
Reads spreadsheet.xlsx and imports into kil/kil_analytics.db.
Re-runnable: drops and recreates tables each run.

Usage:
    python scripts/import_pipeline.py [--xlsx /path/to/file.xlsx]
"""

import argparse
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import openpyxl

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "kil" / "kil_analytics.db"

# ── Schema DDL ──────────────────────────────────────────────────────────────

SCHEMA_SQL = """
DROP TABLE IF EXISTS pipeline_leads;
DROP TABLE IF EXISTS pipeline_surveys;
DROP TABLE IF EXISTS pipeline_import_log;

CREATE TABLE pipeline_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    name TEXT NOT NULL,
    link TEXT,
    phone TEXT,
    price_range TEXT,
    rating REAL,
    review_count INTEGER,
    contact_name TEXT,
    contact_title TEXT,
    connect_request_date TEXT,
    connected_date TEXT,
    project_type TEXT,
    project_stage TEXT,
    project_address TEXT,
    company_name TEXT,
    pic_name TEXT,
    pic_title TEXT,
    pic_phone TEXT,
    pic_email TEXT,
    pic_linkedin TEXT,
    outreach_channel TEXT,
    outreach_1st_date TEXT,
    outreach_2nd_date TEXT,
    outreach_3rd_date TEXT,
    outreach_notes TEXT,
    replied_date TEXT,
    replied_notes TEXT,
    pic_replied_date TEXT,
    meeting_booked_date TEXT,
    meeting_date TEXT,
    meeting_time TEXT,
    meeting_notes TEXT,
    meeting_result_date TEXT,
    meeting_result_status TEXT,
    meeting_result_notes TEXT,
    closed_lost_date TEXT,
    closed_lost_reason TEXT,
    closed_lost_notes TEXT,
    funnel_stage TEXT NOT NULL DEFAULT 'prospect',
    source_row INTEGER,
    imported_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_pipeline_channel ON pipeline_leads(channel);
CREATE INDEX idx_pipeline_funnel ON pipeline_leads(funnel_stage);
CREATE INDEX idx_pipeline_outreach ON pipeline_leads(outreach_1st_date);

CREATE TABLE pipeline_surveys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_name TEXT NOT NULL,
    google_maps_link TEXT,
    area TEXT,
    meeting_booked_date TEXT,
    industry TEXT,
    channel TEXT,
    pic_name TEXT,
    phone_number TEXT,
    role_position TEXT,
    getfound_sdr TEXT,
    survey_date TEXT,
    survey_time TEXT,
    snc_pic_name TEXT,
    survey_status TEXT,
    context TEXT,
    source_row INTEGER,
    imported_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE pipeline_import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at TEXT DEFAULT (datetime('now')),
    source_file TEXT,
    cold_call_count INTEGER DEFAULT 0,
    linkedin_count INTEGER DEFAULT 0,
    hubexo_count INTEGER DEFAULT 0,
    hubexo_linkedin_count INTEGER DEFAULT 0,
    survey_count INTEGER DEFAULT 0,
    duration_seconds REAL
);
"""


# ── Helpers ─────────────────────────────────────────────────────────────────

def safe_date(val) -> str | None:
    """Convert datetime to ISO string, filtering bogus values."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if 2024 <= val.year <= 2027:
            return val.strftime("%Y-%m-%d")
        return None
    s = str(val).strip()
    if not s or s.lower() in ("none", "no respon", "no response"):
        return None
    # Try parse common text formats
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            dt = datetime.strptime(s[:20], fmt)
            if 2024 <= dt.year <= 2027:
                return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def safe_str(val) -> str | None:
    """Strip whitespace, return None for empty."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "none":
        return None
    return s


def safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return f if 0 <= f <= 5.1 else None
    except (ValueError, TypeError):
        return None


def safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def safe_time(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%H:%M")
    s = str(val).strip()
    if not s or s.lower() == "none":
        return None
    return s


def cell(ws, row, col):
    """Get cell value by 1-indexed column."""
    return ws.cell(row=row, column=col).value


def compute_funnel_stage(row: dict) -> str:
    if row.get("closed_lost_date"):
        return "closed_lost"
    if row.get("meeting_result_date") or row.get("meeting_result_status"):
        return "meeting_done"
    if row.get("meeting_booked_date"):
        return "meeting_booked"
    if row.get("pic_replied_date"):
        return "replied"
    if row.get("replied_date"):
        return "replied"
    if row.get("pic_name"):
        return "pic_contacted"
    if row.get("outreach_1st_date"):
        return "outreach"
    return "prospect"


# ── Sheet Parsers ───────────────────────────────────────────────────────────

def parse_cold_call(ws) -> list[dict]:
    """Parse Cold Call sheet. Headers at row 3, data from row 4."""
    leads = []
    for r in range(4, ws.max_row + 1):
        name = safe_str(cell(ws, r, 2))
        if not name:
            continue
        row = {
            "channel": "cold_call",
            "name": name,
            "link": safe_str(cell(ws, r, 3)),
            "phone": safe_str(cell(ws, r, 4)),
            "price_range": safe_str(cell(ws, r, 5)),
            "rating": safe_float(cell(ws, r, 6)),
            "review_count": safe_int(cell(ws, r, 7)),
            # Outreach (cols 9-15)
            "outreach_1st_date": safe_date(cell(ws, r, 9)),
            "outreach_channel": safe_str(cell(ws, r, 10)),
            "outreach_2nd_date": safe_date(cell(ws, r, 11)),
            "outreach_3rd_date": safe_date(cell(ws, r, 13)),
            "outreach_notes": safe_str(cell(ws, r, 15)),
            # Admin replied (cols 16-18)
            "replied_date": safe_date(cell(ws, r, 16)),
            "replied_notes": safe_str(cell(ws, r, 18)),
            # PIC Contact (cols 19-22)
            "pic_name": safe_str(cell(ws, r, 19)),
            "pic_title": safe_str(cell(ws, r, 20)),
            "pic_phone": safe_str(cell(ws, r, 21)),
            "pic_email": safe_str(cell(ws, r, 22)),
            # PIC Replied (col 30)
            "pic_replied_date": safe_date(cell(ws, r, 30)),
            # Meeting Booked (cols 33-36)
            "meeting_booked_date": safe_date(cell(ws, r, 33)),
            "meeting_date": safe_date(cell(ws, r, 34)),
            "meeting_time": safe_time(cell(ws, r, 35)),
            "meeting_notes": safe_str(cell(ws, r, 36)),
            # Meeting Result (cols 37-39)
            "meeting_result_date": safe_date(cell(ws, r, 37)),
            "meeting_result_status": safe_str(cell(ws, r, 38)),
            "meeting_result_notes": safe_str(cell(ws, r, 39)),
            # Closed Lost (cols 40-42)
            "closed_lost_date": safe_date(cell(ws, r, 40)),
            "closed_lost_reason": safe_str(cell(ws, r, 41)),
            "closed_lost_notes": safe_str(cell(ws, r, 42)),
            "source_row": r,
        }
        row["funnel_stage"] = compute_funnel_stage(row)
        leads.append(row)
    return leads


def parse_linkedin(ws) -> list[dict]:
    """Parse LinkedIn sheet. Headers at row 3, data from row 4."""
    leads = []
    for r in range(4, ws.max_row + 1):
        name = safe_str(cell(ws, r, 2))
        if not name:
            continue
        row = {
            "channel": "linkedin",
            "name": name,
            "link": safe_str(cell(ws, r, 3)),
            "contact_name": safe_str(cell(ws, r, 4)),
            "contact_title": safe_str(cell(ws, r, 5)),
            "connect_request_date": safe_date(cell(ws, r, 6)),
            "connected_date": safe_date(cell(ws, r, 7)),
            # Outreach (cols 8-11)
            "outreach_1st_date": safe_date(cell(ws, r, 8)),
            "outreach_2nd_date": safe_date(cell(ws, r, 9)),
            "outreach_3rd_date": safe_date(cell(ws, r, 10)),
            "outreach_notes": safe_str(cell(ws, r, 11)),
            # Replied (cols 12-13)
            "replied_date": safe_date(cell(ws, r, 12)),
            "replied_notes": safe_str(cell(ws, r, 13)),
            # PIC Contact (cols 14-17)
            "pic_name": safe_str(cell(ws, r, 14)),
            "pic_title": safe_str(cell(ws, r, 15)),
            "pic_phone": safe_str(cell(ws, r, 16)),
            "pic_email": safe_str(cell(ws, r, 17)),
            # Meeting Booked (cols 18-21)
            "meeting_booked_date": safe_date(cell(ws, r, 18)),
            "meeting_date": safe_date(cell(ws, r, 19)),
            "meeting_time": safe_time(cell(ws, r, 20)),
            "meeting_notes": safe_str(cell(ws, r, 21)),
            # Meeting Result (cols 22-24)
            "meeting_result_date": safe_date(cell(ws, r, 22)),
            "meeting_result_status": safe_str(cell(ws, r, 23)),
            "meeting_result_notes": safe_str(cell(ws, r, 24)),
            # Closed Lost (cols 25-27)
            "closed_lost_date": safe_date(cell(ws, r, 25)),
            "closed_lost_reason": safe_str(cell(ws, r, 26)),
            "closed_lost_notes": safe_str(cell(ws, r, 27)),
            "source_row": r,
        }
        row["funnel_stage"] = compute_funnel_stage(row)
        leads.append(row)
    return leads


def _is_linkedin_row(ws, r: int) -> bool:
    """Detect if a Hubexo row belongs to the LinkedIn corporate section.
    LinkedIn section has a LinkedIn URL in column C (Project Name)."""
    col_c = safe_str(cell(ws, r, 3))
    if col_c and "linkedin.com" in col_c.lower():
        return True
    # Also detect: col D (Project Stage) is NOT Construction/Pre-Construction
    # AND col C looks like a URL
    if col_c and col_c.startswith("http"):
        return True
    return False


def parse_hubexo(ws) -> tuple[list[dict], list[dict]]:
    """Parse Hubexo sheet. Two sections with different column mappings:
    - Construction projects: standard Hubexo mapping
    - LinkedIn corporate (col C = LinkedIn URL): shifted columns

    Returns (construction_leads, linkedin_leads).
    """
    construction = []
    linkedin = []

    for r in range(4, ws.max_row + 1):
        if _is_linkedin_row(ws, r):
            # ── LinkedIn corporate outreach section ─────────────────────
            # Col B = Company, Col C = LinkedIn URL, Col D = Full Name,
            # Col E = Job Title, Col F = Conn Request, Col G = Connected,
            # Col H = 1st Outreach, Col I = Replied/Follow-up,
            # Col AD = Closed Lost Date, Col AE = Reason, Col AF = Notes
            company = safe_str(cell(ws, r, 2))
            li_url = safe_str(cell(ws, r, 3))
            full_name = safe_str(cell(ws, r, 4))
            title = safe_str(cell(ws, r, 5))
            if not company and not full_name:
                continue
            row = {
                "channel": "hubexo_linkedin",
                "name": company or full_name or "Unknown",
                "company_name": company,
                "contact_name": full_name,
                "contact_title": title,
                "pic_linkedin": li_url,
                "connect_request_date": safe_date(cell(ws, r, 6)),
                "connected_date": safe_date(cell(ws, r, 7)),
                "outreach_1st_date": safe_date(cell(ws, r, 8)),
                "replied_date": safe_date(cell(ws, r, 9)),
                # Sparse PIC data (cols 14-16 for some rows)
                "pic_name": safe_str(cell(ws, r, 14)),
                "pic_title": safe_str(cell(ws, r, 15)),
                "pic_phone": safe_str(cell(ws, r, 16)),
                # Closed Lost (cols 30-32, same position as construction)
                "closed_lost_date": safe_date(cell(ws, r, 30)),
                "closed_lost_reason": safe_str(cell(ws, r, 31)),
                "closed_lost_notes": safe_str(cell(ws, r, 32)),
                "source_row": r,
            }
            row["funnel_stage"] = compute_funnel_stage(row)
            linkedin.append(row)
        else:
            # ── Construction project section ────────────────────────────
            ptype = safe_str(cell(ws, r, 2))
            pname = safe_str(cell(ws, r, 3))
            if not ptype and not pname:
                continue
            name = pname or ptype or "Unknown"
            row = {
                "channel": "hubexo",
                "name": name,
                "project_type": ptype,
                "project_stage": safe_str(cell(ws, r, 4)),
                "project_address": safe_str(cell(ws, r, 5)),
                "contact_name": safe_str(cell(ws, r, 8)),  # Full Name (formula col)
                "company_name": safe_str(cell(ws, r, 9)),
                "contact_title": safe_str(cell(ws, r, 10)),
                "pic_phone": safe_str(cell(ws, r, 11)),
                "pic_email": safe_str(cell(ws, r, 12)),
                "pic_linkedin": safe_str(cell(ws, r, 13)),
                "connect_request_date": safe_date(cell(ws, r, 14)),
                "connected_date": safe_date(cell(ws, r, 15)),
                # Outreach (cols 16-20)
                "outreach_channel": safe_str(cell(ws, r, 16)),
                "outreach_1st_date": safe_date(cell(ws, r, 17)),
                "outreach_2nd_date": safe_date(cell(ws, r, 18)),
                "outreach_3rd_date": safe_date(cell(ws, r, 19)),
                "outreach_notes": safe_str(cell(ws, r, 20)),
                # Replied (cols 21-22)
                "replied_date": safe_date(cell(ws, r, 21)),
                "replied_notes": safe_str(cell(ws, r, 22)),
                # Meeting Booked (cols 23-26)
                "meeting_booked_date": safe_date(cell(ws, r, 23)),
                "meeting_date": safe_date(cell(ws, r, 24)),
                "meeting_time": safe_time(cell(ws, r, 25)),
                "meeting_notes": safe_str(cell(ws, r, 26)),
                # Meeting Result (cols 27-29)
                "meeting_result_date": safe_date(cell(ws, r, 27)),
                "meeting_result_status": safe_str(cell(ws, r, 28)),
                "meeting_result_notes": safe_str(cell(ws, r, 29)),
                # Closed Lost (cols 30-32)
                "closed_lost_date": safe_date(cell(ws, r, 30)),
                "closed_lost_reason": safe_str(cell(ws, r, 31)),
                "closed_lost_notes": safe_str(cell(ws, r, 32)),
                "source_row": r,
            }
            # Hubexo contact_name might be a formula string
            cn = row["contact_name"]
            if cn and cn.startswith("="):
                # Fallback to First Name (col 6)
                first = safe_str(cell(ws, r, 6))
                surname = safe_str(cell(ws, r, 7))
                row["contact_name"] = f"{first or ''} {surname or ''}".strip() or None
            row["funnel_stage"] = compute_funnel_stage(row)
            construction.append(row)

    return construction, linkedin


def parse_survey(ws) -> list[dict]:
    """Parse Survey sheet. Headers at row 2, data from row 3."""
    surveys = []
    for r in range(3, ws.max_row + 1):
        loc = safe_str(cell(ws, r, 2))
        if not loc:
            continue
        surveys.append({
            "location_name": loc,
            "google_maps_link": safe_str(cell(ws, r, 3)),
            "area": safe_str(cell(ws, r, 4)),
            "meeting_booked_date": safe_date(cell(ws, r, 5)),
            "industry": safe_str(cell(ws, r, 6)),
            "channel": safe_str(cell(ws, r, 7)),
            "pic_name": safe_str(cell(ws, r, 8)),
            "phone_number": safe_str(cell(ws, r, 9)),
            "role_position": safe_str(cell(ws, r, 10)),
            "getfound_sdr": safe_str(cell(ws, r, 11)),
            "survey_date": safe_date(cell(ws, r, 12)),
            "survey_time": safe_time(cell(ws, r, 13)),
            "snc_pic_name": safe_str(cell(ws, r, 14)),
            "survey_status": safe_str(cell(ws, r, 15)),
            "context": safe_str(cell(ws, r, 16)),
            "source_row": r,
        })
    return surveys


# ── Insert Logic ────────────────────────────────────────────────────────────

LEAD_COLUMNS = [
    "channel", "name", "link", "phone", "price_range", "rating", "review_count",
    "contact_name", "contact_title", "connect_request_date", "connected_date",
    "project_type", "project_stage", "project_address", "company_name",
    "pic_name", "pic_title", "pic_phone", "pic_email", "pic_linkedin",
    "outreach_channel", "outreach_1st_date", "outreach_2nd_date", "outreach_3rd_date",
    "outreach_notes", "replied_date", "replied_notes", "pic_replied_date",
    "meeting_booked_date", "meeting_date", "meeting_time", "meeting_notes",
    "meeting_result_date", "meeting_result_status", "meeting_result_notes",
    "closed_lost_date", "closed_lost_reason", "closed_lost_notes",
    "funnel_stage", "source_row",
]

SURVEY_COLUMNS = [
    "location_name", "google_maps_link", "area", "meeting_booked_date",
    "industry", "channel", "pic_name", "phone_number", "role_position",
    "getfound_sdr", "survey_date", "survey_time", "snc_pic_name",
    "survey_status", "context", "source_row",
]


def insert_leads(conn: sqlite3.Connection, leads: list[dict]):
    placeholders = ", ".join(["?"] * len(LEAD_COLUMNS))
    cols = ", ".join(LEAD_COLUMNS)
    sql = f"INSERT INTO pipeline_leads ({cols}) VALUES ({placeholders})"
    for lead in leads:
        values = tuple(lead.get(c) for c in LEAD_COLUMNS)
        conn.execute(sql, values)
    conn.commit()


def insert_surveys(conn: sqlite3.Connection, surveys: list[dict]):
    placeholders = ", ".join(["?"] * len(SURVEY_COLUMNS))
    cols = ", ".join(SURVEY_COLUMNS)
    sql = f"INSERT INTO pipeline_surveys ({cols}) VALUES ({placeholders})"
    for s in surveys:
        values = tuple(s.get(c) for c in SURVEY_COLUMNS)
        conn.execute(sql, values)
    conn.commit()


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import GetFound pipeline data")
    parser.add_argument("--xlsx", default="/tmp/spreadsheet.xlsx", help="Path to XLSX file")
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.exists():
        print(f"ERROR: File not found: {xlsx_path}")
        return

    start = time.time()
    print(f"Loading {xlsx_path} ...")

    import warnings
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(str(xlsx_path))

    print(f"  Sheets: {wb.sheetnames}")

    # Parse all sheets
    print("  Parsing Cold Call ...")
    cold_call = parse_cold_call(wb["Cold Call"])
    print(f"    → {len(cold_call)} leads")

    print("  Parsing LinkedIn ...")
    linkedin = parse_linkedin(wb["Linkedin"])
    print(f"    → {len(linkedin)} leads")

    print("  Parsing Hubexo ...")
    hubexo, hubexo_linkedin = parse_hubexo(wb["Hubexo"])
    print(f"    → {len(hubexo)} construction leads")
    print(f"    → {len(hubexo_linkedin)} LinkedIn corporate leads")

    print("  Parsing Survey ...")
    survey = parse_survey(wb["Survey"])
    print(f"    → {len(survey)} surveys")

    # Write to SQLite
    print(f"\nWriting to {DB_PATH} ...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA_SQL)

    insert_leads(conn, cold_call)
    insert_leads(conn, linkedin)
    insert_leads(conn, hubexo)
    insert_leads(conn, hubexo_linkedin)
    insert_surveys(conn, survey)

    duration = time.time() - start

    # Log import
    conn.execute(
        """INSERT INTO pipeline_import_log
           (source_file, cold_call_count, linkedin_count, hubexo_count, hubexo_linkedin_count, survey_count, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (str(xlsx_path), len(cold_call), len(linkedin), len(hubexo), len(hubexo_linkedin), len(survey), round(duration, 2)),
    )
    conn.commit()

    # Print summary
    total = conn.execute("SELECT COUNT(*) FROM pipeline_leads").fetchone()[0]
    survey_total = conn.execute("SELECT COUNT(*) FROM pipeline_surveys").fetchone()[0]

    print(f"\n  pipeline_leads:   {total} rows")
    print(f"  pipeline_surveys: {survey_total} rows")

    # Funnel stage distribution
    print("\n  Funnel stage distribution:")
    for row in conn.execute(
        "SELECT channel, funnel_stage, COUNT(*) as cnt FROM pipeline_leads GROUP BY channel, funnel_stage ORDER BY channel, cnt DESC"
    ):
        print(f"    {row[0]:12s} | {row[1]:16s} | {row[2]}")

    conn.close()
    print(f"\nDone in {duration:.1f}s")


if __name__ == "__main__":
    main()
