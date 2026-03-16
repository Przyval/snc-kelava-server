#!/usr/bin/env python3
"""
Hubexo OSINT Enrichment Script
================================
Enriches Hubexo construction intelligence data with:
  1. Company domain discovery (from existing emails + web search)
  2. Email generation (name + domain → probable email)
  3. Project geocoding (Nominatim)
  4. Project classification (regex parse project_type)
  5. LinkedIn search URL generation

Each step is idempotent — safe to re-run.

Usage:
    python scripts/enrich_hubexo.py --all
    python scripts/enrich_hubexo.py --step company
    python scripts/enrich_hubexo.py --step email
    python scripts/enrich_hubexo.py --step geocode
    python scripts/enrich_hubexo.py --step classify
    python scripts/enrich_hubexo.py --step linkedin
"""

import argparse
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "kil" / "kil_analytics.db"

# Free email providers to exclude when inferring company domains
FREE_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.co.id", "hotmail.com", "outlook.com",
    "icloud.com", "mail.com", "ymail.com", "live.com", "aol.com",
    "protonmail.com", "zoho.com",
}

# Known domains for major Indonesian companies (fallback when web search fails)
KNOWN_DOMAINS: dict[str, str] = {
    "Lippo Karawaci Tbk PT": "lippokarawaci.co.id",
    "Acset Indonusa Tbk PT": "acset.co",
    "Toyota Astra Motor PT": "toyota.astra.co.id",
    "Lion Metal Works Tbk PT": "lionmetal.co.id",
    "Nusa Raya Cipta Tbk PT": "nusarayacipta.com",
    "Aedas Pte Ltd": "aedas.com",
    "Arup Singapore Pte Ltd": "arup.com",
    "Hyatt Hotels Corporation - Asia Pacific Head Office (Hong Kong)": "hyatt.com",
    "Surbana Jurong Private Limited": "surbanajurong.com",
    "NBBJ - Washington DC Office": "nbbj.com",
    "Bumi Serpong Damai Tbk PT (member of Sinar Mas Land)": "bfrj.co.id",
    "Ciputra Nugraha International PT": "ciputra.com",
    "Paramount Enterprise International PT (aka Paramount Land)": "paramount-land.com",
    "Paramount Enterprise International PT (aka Paramount Petals)": "paramount-land.com",
    "Unilever Indonesia Tbk PT - Cikarang Plant": "unilever.co.id",
    "Cisarua Mountain Dairy Tbk PT (Cimory Group)": "cimory.com",
    "Zamil Steel Building PT": "zamilsteel.com",
    "Indomarco Prismatama PT (member of Indomaret Group)": "indomaret.co.id",
    "Taisei Corporation - Indonesia Office": "taisei.co.jp",
    "Peri Indonesia PT": "peri.com",
    "Mitsubishi Estate Co,. Ltd": "mec.co.jp",
    "Mitsubishi Estate Indonesia PT (subsidiary of Mitsubishi Estate)": "mec.co.jp",
    "Pakubuwono Development PT": "pakubuwono.com",
    "Dayacipta Anekareksa PT - Workshop Office": "dayacipta.com",
    "Jangho Curtain Wall Indonesia PT": "jangho.com",
    "China State Construction Overseas Development Shanghai (CSCODS) PT (CSCEC Eighth Division 8) (subsidiaries of China State Construction Engineering Corporation (CSCEC))": "cscec.com",
    "Inhabit Group (member of Egis Group) - Jakarta Office": "egis-group.com",
    "Insada Perkasa Utama PT (aka Insada Integrated Design Team)": "insada.co.id",
    "Davy Sukamta & Partners PT": "davysukamta.co.id",
    "Mestika Dipta Ananta PT (subsidiary of Median Cipta Sentosa)": "median.co.id",
    "Saso Architecture": "saso.co.id",
    "Studio Air Putih": "studioairputih.com",
    "Hebsa Indonesia PT - Surabaya": "hebsa.co.id",
    "Siscom Technologies PT": "siscom.co.id",
    "Super Potato Co. Ltd": "superpotato.jp",
    "DP Design Pte Ltd": "dpdesign.com.sg",
    "The GA Group - London": "thegazette.co.uk",
    "TROP": "tropdesign.com",
}

# ── Schema ──────────────────────────────────────────────────────────────────

ENRICHMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrichment_companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL UNIQUE,
    company_name_clean TEXT,
    domain TEXT,
    domain_source TEXT,
    website_url TEXT,
    industry TEXT,
    parent_company TEXT,
    notes TEXT,
    enriched_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_enrich_co_name ON enrichment_companies(company_name);

CREATE TABLE IF NOT EXISTS enrichment_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    contact_name TEXT,
    company_name TEXT,
    email_generated TEXT,
    email_pattern TEXT,
    domain TEXT,
    confidence TEXT DEFAULT 'low',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_enrich_email_lead ON enrichment_emails(lead_id);

CREATE TABLE IF NOT EXISTS enrichment_geocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL UNIQUE,
    address_raw TEXT,
    lat REAL,
    lng REAL,
    geocode_source TEXT DEFAULT 'nominatim',
    geocode_quality TEXT,
    city TEXT,
    district TEXT,
    province TEXT,
    postal_code TEXT,
    geocoded_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_enrich_geo ON enrichment_geocodes(project_name);

CREATE TABLE IF NOT EXISTS enrichment_project_class (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name TEXT NOT NULL UNIQUE,
    project_type_raw TEXT,
    building_type TEXT,
    building_subtype TEXT,
    unit_count INTEGER,
    storey_count TEXT,
    building_count INTEGER,
    is_new_build INTEGER DEFAULT 1,
    pest_relevance TEXT DEFAULT 'medium',
    project_scale TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_enrich_class ON enrichment_project_class(project_name);

CREATE TABLE IF NOT EXISTS enrichment_linkedin_urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    contact_name TEXT,
    company_name TEXT,
    search_url TEXT,
    source TEXT DEFAULT 'generated',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_enrich_li ON enrichment_linkedin_urls(lead_id);

CREATE TABLE IF NOT EXISTS enrichment_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT DEFAULT (datetime('now')),
    step TEXT NOT NULL,
    records_processed INTEGER DEFAULT 0,
    records_enriched INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    duration_seconds REAL,
    notes TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection):
    conn.executescript(ENRICHMENT_SCHEMA)
    conn.commit()


# ── Helpers ─────────────────────────────────────────────────────────────────

def clean_company_name(name: str) -> str:
    """Strip PT, CV, Tbk, subsidiary info, etc. for search."""
    s = name
    # Remove parenthetical info
    s = re.sub(r"\(.*?\)", "", s)
    # Remove PT, CV, Tbk, Ltd, etc.
    s = re.sub(r"\b(PT|CV|Tbk|Ltd|Inc|Corp|Pte|LLC)\b\.?", "", s, flags=re.IGNORECASE)
    # Remove "aka" aliases
    s = re.sub(r"\baka\.?\s+\w+", "", s, flags=re.IGNORECASE)
    return s.strip().strip(",").strip()


def extract_parent_company(name: str) -> str | None:
    """Extract parent from patterns like '(subsidiary of X)' or '(member of X)'."""
    m = re.search(r"\((?:subsidiary|subsidiaries|member|part)\s+of\s+(.+?)\)", name, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(")")
    return None


def classify_industry(name: str) -> str:
    """Classify company by name patterns."""
    n = name.upper()
    if any(k in n for k in ("REALTY", "LAND", "PROPERTY", "RESIDENCES", "ESTATE")):
        return "developer"
    if any(k in n for k in ("KONSTRUKSI", "CONSTRUCTION", "BANGUN", "BUILDING")):
        return "contractor"
    if any(k in n for k in ("ARCHITECT", "DESIGN", "CONSULT", "ENGINEER")):
        return "consultant"
    if any(k in n for k in ("SURVEYOR", "QUANTITY")):
        return "qs"
    if any(k in n for k in ("STEEL", "METAL", "IRON", "BETON", "CONCRETE", "GLASS", "CURTAIN WALL")):
        return "supplier"
    return "other"


def parse_name_parts(full_name: str) -> tuple[str, str]:
    """Split Indonesian name into (first_name, last_name)."""
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0].lower(), ""
    return parts[0].lower(), parts[-1].lower()


def generate_email_candidates(first: str, last: str, domain: str) -> list[tuple[str, str]]:
    """Generate email candidates with pattern name. Returns [(email, pattern), ...]."""
    candidates = []
    if first and last:
        candidates.append((f"{first}.{last}@{domain}", "first.last"))
        candidates.append((f"{first}_{last}@{domain}", "first_last"))
        candidates.append((f"{first}{last}@{domain}", "firstlast"))
        candidates.append((f"{first[0]}{last}@{domain}", "flast"))
        candidates.append((f"{first}@{domain}", "first"))
    elif first:
        candidates.append((f"{first}@{domain}", "first"))
    return candidates


def web_search_domain(company_name: str) -> str | None:
    """Search DuckDuckGo for company website domain."""
    clean = clean_company_name(company_name)
    query = f"{clean} Indonesia official website"
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "SanoCare-KIL/1.0 (enrichment-bot)"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Extract URLs from DuckDuckGo results
        # Pattern: uddg= parameter in result links
        urls = re.findall(r'uddg=([^&"]+)', html)
        for encoded_url in urls[:5]:
            decoded = urllib.parse.unquote(encoded_url)
            # Extract domain
            m = re.match(r"https?://(?:www\.)?([^/]+)", decoded)
            if m:
                domain = m.group(1).lower()
                # Skip social media, directories, etc.
                skip = ("facebook.com", "linkedin.com", "instagram.com", "twitter.com",
                        "youtube.com", "wikipedia.org", "bloomberg.com", "crunchbase.com",
                        "glassdoor.com", "indeed.com", "google.com", "bing.com")
                if not any(domain.endswith(s) for s in skip):
                    return domain
    except Exception:
        pass
    return None


def geocode_nominatim(address: str) -> dict | None:
    """Geocode address via Nominatim (free, 1 req/sec)."""
    # Clean address for better geocoding
    clean = address
    clean = re.sub(r"Kelurahan\s+", "", clean)
    clean = re.sub(r"Kecamatan\s+", "", clean)
    clean = re.sub(r"Kabupaten\s+", "", clean)
    clean = re.sub(r",?\s*Special Capital Region of Jakarta,?\s*Indonesia", "", clean)
    clean = re.sub(r",?\s*Indonesia$", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip().rstrip(",")

    # Try progressively shorter addresses
    attempts = [clean]
    parts = [p.strip() for p in clean.split(",")]
    if len(parts) > 3:
        attempts.append(", ".join(parts[:3]))
    if len(parts) > 2:
        attempts.append(", ".join(parts[-3:]))
    if len(parts) > 1:
        attempts.append(", ".join(parts[-2:]))

    for attempt in attempts:
        url = (
            f"https://nominatim.openstreetmap.org/search?"
            f"q={urllib.parse.quote(attempt)}&format=json&countrycodes=id&limit=1"
        )
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "SanoCare-KIL/1.0 (geocoding)"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data:
                result = data[0]
                lat = float(result["lat"])
                lng = float(result["lon"])
                display = result.get("display_name", "")

                # Determine quality
                quality = "city"
                osm_type = result.get("type", "")
                if osm_type in ("building", "house", "amenity"):
                    quality = "exact"
                elif osm_type in ("road", "street", "residential"):
                    quality = "street"
                elif osm_type in ("suburb", "village", "neighbourhood"):
                    quality = "district"

                return {
                    "lat": lat, "lng": lng,
                    "quality": quality,
                    "display_name": display,
                }
            time.sleep(1.1)  # Rate limit
        except Exception:
            time.sleep(1.1)
            continue

    return None


# ── Step 1: Company Domain Discovery ───────────────────────────────────────

def step_company_enrichment(conn: sqlite3.Connection):
    """Discover company domains from existing emails + web search."""
    start = time.time()
    print("\n=== Step 1: Company Domain Discovery ===")

    # Get all unique companies from Hubexo construction leads
    companies = [
        dict(r) for r in conn.execute(
            "SELECT DISTINCT company_name FROM pipeline_leads WHERE channel = 'hubexo' AND company_name IS NOT NULL AND company_name != ''"
        ).fetchall()
    ]
    print(f"  {len(companies)} unique companies")

    # Get existing emails to infer domains
    email_map = {}
    for r in conn.execute(
        "SELECT DISTINCT company_name, pic_email FROM pipeline_leads WHERE channel = 'hubexo' AND pic_email IS NOT NULL AND pic_email != ''"
    ).fetchall():
        email = r["pic_email"].lower().strip()
        domain = email.split("@")[-1] if "@" in email else None
        if domain and domain not in FREE_DOMAINS:
            email_map[r["company_name"]] = domain

    print(f"  {len(email_map)} companies with known domains from emails")

    enriched = 0
    searched = 0
    failed = 0

    for comp in companies:
        name = comp["company_name"]
        clean = clean_company_name(name)
        parent = extract_parent_company(name)
        industry = classify_industry(name)

        # Check if already enriched
        existing = conn.execute(
            "SELECT id, domain FROM enrichment_companies WHERE company_name = ?", (name,)
        ).fetchone()
        if existing and existing["domain"]:
            enriched += 1
            continue

        # Tier 1: From existing email
        domain = email_map.get(name)
        source = "email_inferred" if domain else None

        # Tier 1.5: Known domains dictionary
        if not domain and name in KNOWN_DOMAINS:
            domain = KNOWN_DOMAINS[name]
            source = "known_dict"

        # Tier 2: Web search (DuckDuckGo — may be blocked)
        if not domain:
            searched += 1
            domain = web_search_domain(name)
            source = "web_search" if domain else None
            time.sleep(0.5)

        # Tier 3: Parent company fallback
        if not domain and parent:
            domain = email_map.get(parent) or KNOWN_DOMAINS.get(parent)
            source = "parent_fallback" if domain else None
            if not domain:
                time.sleep(0.3)

        website = f"https://www.{domain}" if domain else None

        if existing:
            conn.execute(
                """UPDATE enrichment_companies
                   SET domain=?, domain_source=?, website_url=?, industry=?,
                       parent_company=?, company_name_clean=?, enriched_at=?
                   WHERE company_name=?""",
                (domain, source, website, industry, parent, clean,
                 datetime.now().isoformat(), name),
            )
        else:
            conn.execute(
                """INSERT OR REPLACE INTO enrichment_companies
                   (company_name, company_name_clean, domain, domain_source, website_url,
                    industry, parent_company, enriched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, clean, domain, source, website, industry, parent,
                 datetime.now().isoformat()),
            )

        if domain:
            enriched += 1
            print(f"    ✓ {name[:50]:50s} → {domain} ({source})")
        else:
            failed += 1
            print(f"    ✗ {name[:50]:50s} → no domain found")

    conn.commit()
    duration = time.time() - start

    conn.execute(
        "INSERT INTO enrichment_log (step, records_processed, records_enriched, records_failed, duration_seconds) VALUES (?, ?, ?, ?, ?)",
        ("company_domain", len(companies), enriched, failed, round(duration, 1)),
    )
    conn.commit()

    print(f"\n  Done: {enriched} enriched, {failed} failed, {searched} web searches in {duration:.1f}s")


# ── Step 2: Email Generation ──────────────────────────────────────────────

def step_email_generation(conn: sqlite3.Connection):
    """Generate probable emails from contact name + company domain."""
    start = time.time()
    print("\n=== Step 2: Email Generation ===")

    # Get contacts without email but with name + company
    contacts = [
        dict(r) for r in conn.execute("""
            SELECT l.id, l.contact_name, l.company_name, l.pic_email
            FROM pipeline_leads l
            WHERE l.channel = 'hubexo'
              AND l.contact_name IS NOT NULL AND l.contact_name != ''
              AND l.company_name IS NOT NULL AND l.company_name != ''
        """).fetchall()
    ]

    # Get company domains
    domains = {}
    for r in conn.execute("SELECT company_name, domain FROM enrichment_companies WHERE domain IS NOT NULL").fetchall():
        domains[r["company_name"]] = r["domain"]

    # Detect email patterns from existing emails per domain
    known_patterns = {}
    for r in conn.execute(
        "SELECT company_name, pic_email FROM pipeline_leads WHERE channel='hubexo' AND pic_email IS NOT NULL AND pic_email != ''"
    ).fetchall():
        email = r["pic_email"].lower()
        domain = email.split("@")[-1] if "@" in email else ""
        if domain in FREE_DOMAINS:
            continue
        local = email.split("@")[0]
        if "." in local:
            known_patterns[domain] = "first.last"
        elif "_" in local:
            known_patterns[domain] = "first_last"
        else:
            known_patterns[domain] = "first"

    # Clear old generated emails
    conn.execute("DELETE FROM enrichment_emails")

    generated = 0
    skipped_has_email = 0
    skipped_no_domain = 0

    for c in contacts:
        lead_id = c["id"]
        name = c["contact_name"]
        company = c["company_name"]

        # Already has email
        if c["pic_email"]:
            skipped_has_email += 1
            conn.execute(
                """INSERT INTO enrichment_emails (lead_id, contact_name, company_name, email_generated, email_pattern, domain, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (lead_id, name, company, c["pic_email"], "existing", c["pic_email"].split("@")[-1], "high"),
            )
            continue

        domain = domains.get(company)
        if not domain:
            skipped_no_domain += 1
            continue

        first, last = parse_name_parts(name)
        if not first:
            continue

        # Use known pattern for this domain, or generate best candidate
        preferred_pattern = known_patterns.get(domain)
        candidates = generate_email_candidates(first, last, domain)

        if preferred_pattern:
            # Pick the matching pattern
            for email, pattern in candidates:
                if pattern == preferred_pattern:
                    conn.execute(
                        """INSERT INTO enrichment_emails (lead_id, contact_name, company_name, email_generated, email_pattern, domain, confidence)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (lead_id, name, company, email, pattern, domain, "medium"),
                    )
                    generated += 1
                    break
        elif candidates:
            # Default to first.last
            email, pattern = candidates[0]
            conn.execute(
                """INSERT INTO enrichment_emails (lead_id, contact_name, company_name, email_generated, email_pattern, domain, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (lead_id, name, company, email, pattern, domain, "low"),
            )
            generated += 1

    conn.commit()
    duration = time.time() - start

    conn.execute(
        "INSERT INTO enrichment_log (step, records_processed, records_enriched, records_failed, duration_seconds, notes) VALUES (?, ?, ?, ?, ?, ?)",
        ("email_gen", len(contacts), generated + skipped_has_email, skipped_no_domain,
         round(duration, 1), f"existing={skipped_has_email}, generated={generated}, no_domain={skipped_no_domain}"),
    )
    conn.commit()

    print(f"  {len(contacts)} contacts processed")
    print(f"  {skipped_has_email} already have email (marked as high confidence)")
    print(f"  {generated} emails generated")
    print(f"  {skipped_no_domain} skipped (no company domain)")
    print(f"  Done in {duration:.1f}s")


# ── Step 3: Project Geocoding ─────────────────────────────────────────────

def step_geocoding(conn: sqlite3.Connection):
    """Geocode unique project addresses via Nominatim."""
    start = time.time()
    print("\n=== Step 3: Project Geocoding ===")

    projects = [
        dict(r) for r in conn.execute("""
            SELECT DISTINCT name as project_name, project_address
            FROM pipeline_leads
            WHERE channel = 'hubexo' AND project_address IS NOT NULL AND project_address != ''
        """).fetchall()
    ]
    print(f"  {len(projects)} unique projects to geocode")

    geocoded = 0
    failed = 0

    for p in projects:
        name = p["project_name"]
        address = p["project_address"]

        # Check if already geocoded
        existing = conn.execute(
            "SELECT lat FROM enrichment_geocodes WHERE project_name = ?", (name,)
        ).fetchone()
        if existing and existing["lat"]:
            geocoded += 1
            continue

        result = geocode_nominatim(address)
        time.sleep(1.1)  # Nominatim rate limit

        if result:
            # Extract city/district/province from display_name
            parts = [p.strip() for p in result["display_name"].split(",")]
            city = parts[-3] if len(parts) >= 3 else None
            district = parts[-4] if len(parts) >= 4 else None
            province = parts[-2] if len(parts) >= 2 else None

            # Extract postal code from original address
            postal = None
            pm = re.search(r"\b(\d{5})\b", address)
            if pm:
                postal = pm.group(1)

            conn.execute(
                """INSERT OR REPLACE INTO enrichment_geocodes
                   (project_name, address_raw, lat, lng, geocode_quality, city, district, province, postal_code, geocoded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, address, result["lat"], result["lng"], result["quality"],
                 city, district, province, postal, datetime.now().isoformat()),
            )
            geocoded += 1
            print(f"    ✓ {name[:55]:55s} → {result['lat']:.4f}, {result['lng']:.4f} ({result['quality']})")
        else:
            # Insert with NULL lat/lng
            conn.execute(
                """INSERT OR REPLACE INTO enrichment_geocodes
                   (project_name, address_raw, geocode_quality, geocoded_at)
                   VALUES (?, ?, 'failed', ?)""",
                (name, address, datetime.now().isoformat()),
            )
            failed += 1
            print(f"    ✗ {name[:55]:55s} → FAILED")

    conn.commit()
    duration = time.time() - start

    conn.execute(
        "INSERT INTO enrichment_log (step, records_processed, records_enriched, records_failed, duration_seconds) VALUES (?, ?, ?, ?, ?)",
        ("geocode", len(projects), geocoded, failed, round(duration, 1)),
    )
    conn.commit()

    print(f"\n  Done: {geocoded} geocoded, {failed} failed in {duration:.1f}s")


# ── Step 4: Project Classification ────────────────────────────────────────

def step_classification(conn: sqlite3.Connection):
    """Classify projects by type, scale, and pest control relevance."""
    start = time.time()
    print("\n=== Step 4: Project Classification ===")

    projects = [
        dict(r) for r in conn.execute("""
            SELECT DISTINCT name as project_name, project_type
            FROM pipeline_leads
            WHERE channel = 'hubexo' AND project_type IS NOT NULL
        """).fetchall()
    ]

    classified = 0
    for p in projects:
        name = p["project_name"]
        ptype = p["project_type"]
        pt = ptype.upper()

        # Building type (order matters: check WAREHOUSE/SHOPHOUSE before HOUSE)
        if "FACTORY" in pt or "WAREHOUSE" in pt or "DISTRIBUTION" in pt:
            btype, bsub = "industrial", "factory" if "FACTORY" in pt else "warehouse"
        elif "SHOPHOUSE" in pt:
            btype, bsub = "commercial", "shophouse"
        elif any(k in pt for k in ("APARTMENT", "CONDOMINIUM")):
            btype, bsub = "residential", "apartment"
        elif any(k in pt for k in ("HOUSE", "RESIDENTIAL", "VILLA", "CLUSTER", "LIVIN")):
            btype, bsub = "residential", "houses"
        elif "OFFICE" in pt:
            btype, bsub = "commercial", "office"
        elif "HOTEL" in pt or "RESORT" in pt or "SERVICE" in pt:
            btype, bsub = "hospitality", "hotel"
        elif "RESTAURANT" in pt or "SHOPPING" in pt or "RETAIL" in pt:
            btype, bsub = "commercial", "retail"
        elif "HOSPITAL" in pt or "CLINIC" in pt:
            btype, bsub = "healthcare", "hospital"
        elif "POLICE" in pt or "STATION" in pt:
            btype, bsub = "infrastructure", "government"
        else:
            btype, bsub = "other", "other"

        # Unit count
        unit_match = re.search(r"\((\d+)\)", ptype)
        unit_count = int(unit_match.group(1)) if unit_match else 1

        # Storey count
        storey_match = re.search(r"(\d+(?:\s*[&,]\s*\d+)*)\s+(?:storey|level)", ptype, re.IGNORECASE)
        storey = storey_match.group(1) if storey_match else "1"
        if "single" in ptype.lower():
            storey = "1"

        # Building count
        bldg_match = re.search(r"(\d+)\s+buildings?", ptype, re.IGNORECASE)
        bldg_count = int(bldg_match.group(1)) if bldg_match else 1

        # New vs refurbishment
        is_new = 1 if "new" in ptype.lower() else 0
        if "refurbish" in ptype.lower() or "fitout" in ptype.lower():
            is_new = 0

        # Pest relevance
        if btype == "residential" and is_new:
            relevance = "high"
        elif btype in ("commercial", "hospitality") and is_new:
            relevance = "medium"
        elif btype == "industrial":
            relevance = "medium"
        elif not is_new:
            relevance = "low"
        else:
            relevance = "medium"

        # Scale
        if unit_count >= 100:
            scale = "mega"
        elif unit_count >= 20:
            scale = "large"
        elif unit_count >= 5:
            scale = "medium"
        else:
            scale = "small"

        conn.execute(
            """INSERT OR REPLACE INTO enrichment_project_class
               (project_name, project_type_raw, building_type, building_subtype,
                unit_count, storey_count, building_count, is_new_build,
                pest_relevance, project_scale)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, ptype, btype, bsub, unit_count, storey, bldg_count,
             is_new, relevance, scale),
        )
        classified += 1

        print(f"    {name[:50]:50s} → {btype}/{bsub} {unit_count}u {storey}s {'NEW' if is_new else 'REFURB'} [{relevance}] [{scale}]")

    conn.commit()
    duration = time.time() - start

    conn.execute(
        "INSERT INTO enrichment_log (step, records_processed, records_enriched, records_failed, duration_seconds) VALUES (?, ?, ?, ?, ?)",
        ("classify", len(projects), classified, 0, round(duration, 1)),
    )
    conn.commit()

    print(f"\n  Done: {classified} classified in {duration:.1f}s")


# ── Step 5: LinkedIn Search URLs ──────────────────────────────────────────

def step_linkedin_urls(conn: sqlite3.Connection):
    """Generate LinkedIn search URLs for contacts without LinkedIn profiles."""
    start = time.time()
    print("\n=== Step 5: LinkedIn Search URL Generation ===")

    contacts = [
        dict(r) for r in conn.execute("""
            SELECT id, contact_name, company_name, pic_linkedin
            FROM pipeline_leads
            WHERE channel = 'hubexo'
              AND contact_name IS NOT NULL AND contact_name != ''
        """).fetchall()
    ]

    conn.execute("DELETE FROM enrichment_linkedin_urls")

    generated = 0
    existing = 0

    for c in contacts:
        lead_id = c["id"]
        name = c["contact_name"]
        company = c["company_name"] or ""

        if c["pic_linkedin"]:
            # Already has LinkedIn
            conn.execute(
                """INSERT INTO enrichment_linkedin_urls (lead_id, contact_name, company_name, search_url, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (lead_id, name, company, c["pic_linkedin"], "existing"),
            )
            existing += 1
        else:
            clean_company = clean_company_name(company) if company else ""
            query = f"{name} {clean_company}".strip()
            search_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(query)}"
            conn.execute(
                """INSERT INTO enrichment_linkedin_urls (lead_id, contact_name, company_name, search_url, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (lead_id, name, company, search_url, "generated"),
            )
            generated += 1

    conn.commit()
    duration = time.time() - start

    conn.execute(
        "INSERT INTO enrichment_log (step, records_processed, records_enriched, records_failed, duration_seconds) VALUES (?, ?, ?, ?, ?)",
        ("linkedin", len(contacts), generated + existing, 0, round(duration, 1)),
    )
    conn.commit()

    print(f"  {existing} already have LinkedIn URL")
    print(f"  {generated} search URLs generated")
    print(f"  Done in {duration:.1f}s")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Enrich Hubexo construction data with OSINT")
    parser.add_argument("--all", action="store_true", help="Run all enrichment steps")
    parser.add_argument("--step", choices=["company", "email", "geocode", "classify", "linkedin"],
                        help="Run a specific step")
    args = parser.parse_args()

    if not args.all and not args.step:
        parser.print_help()
        return

    conn = get_conn()
    init_schema(conn)

    steps = {
        "company": step_company_enrichment,
        "email": step_email_generation,
        "geocode": step_geocoding,
        "classify": step_classification,
        "linkedin": step_linkedin_urls,
    }

    if args.all:
        for name, func in steps.items():
            func(conn)
    else:
        steps[args.step](conn)

    # Print summary
    print("\n" + "=" * 60)
    print("ENRICHMENT SUMMARY")
    print("=" * 60)

    for r in conn.execute("SELECT step, records_processed, records_enriched, records_failed FROM enrichment_log ORDER BY id DESC LIMIT 5").fetchall():
        print(f"  {r['step']:20s}  processed={r['records_processed']:>5}  enriched={r['records_enriched']:>5}  failed={r['records_failed']:>3}")

    # Email coverage
    total = conn.execute("SELECT COUNT(*) as n FROM pipeline_leads WHERE channel='hubexo'").fetchone()["n"]
    with_email = conn.execute(
        "SELECT COUNT(DISTINCT lead_id) as n FROM enrichment_emails WHERE email_generated IS NOT NULL"
    ).fetchone()["n"]
    print(f"\n  Email coverage: {with_email}/{total} ({round(100*with_email/total, 1)}%)")

    # Geocode coverage
    geocoded = conn.execute(
        "SELECT COUNT(*) as n FROM enrichment_geocodes WHERE lat IS NOT NULL"
    ).fetchone()["n"]
    projects = conn.execute(
        "SELECT COUNT(DISTINCT name) as n FROM pipeline_leads WHERE channel='hubexo'"
    ).fetchone()["n"]
    print(f"  Geocode coverage: {geocoded}/{projects} projects")

    # Company domain coverage
    with_domain = conn.execute(
        "SELECT COUNT(*) as n FROM enrichment_companies WHERE domain IS NOT NULL"
    ).fetchone()["n"]
    total_companies = conn.execute(
        "SELECT COUNT(*) as n FROM enrichment_companies"
    ).fetchone()["n"]
    print(f"  Company domains: {with_domain}/{total_companies}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
