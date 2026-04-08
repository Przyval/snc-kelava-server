# Kelava Live Database — Complete Agent Guide

> **For AI agents and developers** who need to query SanoCare's operational data.  
> Last verified: 2026-04-08 · Database: PostgreSQL 10 on `172.104.188.76:5432`

---

## 1. Connection

### From production server (safencare.work)
```
Host:     172.104.188.76
Port:     5432
Database: sanocare
User:     snc_read
Password: SnCR3aD2026&
```
> **CRITICAL**: Always use the IP `172.104.188.76`, never `app.kelava.id`.  
> `app.kelava.id` goes through Cloudflare — port 5432 is blocked there.

### From local dev machine (SSH tunnel)
```bash
# Open tunnel (run once, stays in background)
ssh -f -N -L 5433:172.104.188.76:5432 root@104.194.154.108

# Then connect via localhost:5433
PGPASSWORD='SnCR3aD2026&' psql -h 127.0.0.1 -p 5433 -U snc_read -d sanocare
```

### From Python (psycopg3 — already configured in project)
```python
from kil.db.kelava_db import execute_kelava_query, execute_kelava_query_single

# Read-only SELECT — returns list of dicts
rows = execute_kelava_query(
    "SELECT id, name, status FROM m_customer WHERE is_deleted = false LIMIT %s",
    (50,)
)

# Single row
row = execute_kelava_query_single(
    "SELECT id, fullname FROM p_user WHERE id = %s",
    (392,)
)
```
> Never use f-strings for query params. Always use `%s` placeholders (psycopg3 style).

### From API (live, authenticated)
```
Base URL: https://safencare.work
Auth:     Authorization: Bearer <JWT>
Login:    POST /api/v1/auth/login
          Body: {"login": "admin@sanocare.work", "password": "SanoCare2026!"}
```

---

## 2. Permissions

- `snc_read` has **SELECT** on all 209 tables in the `public` schema
- **READ ONLY** — no INSERT, UPDATE, DELETE
- PostgreSQL 10 — no `gen_random_uuid()`, no `FILTER` syntax on old PG features
- Whitelist: only IP `104.194.154.108` (production server) can connect directly

---

## 3. Core Tables — With Data (use these)

### 3.1 `t_road_plan` — 37,237 rows
Scheduled visits. The central operational table.

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `visit_date` | TIMESTAMPTZ | **Use `visit_date::date`** for date comparison |
| `status` | varchar | `'Selesai'` `'Berjalan'` `'Baru'` `'Requested'` — **Indonesian, not English** |
| `is_cancel` | boolean | `true` = cancelled. Use `COALESCE(is_cancel, false) = false` |
| `id_user` | integer | FK → `p_user.id` (technician) |
| `id_customer` | integer | FK → `m_customer.id` |
| `id_kontrak` | integer | FK → `m_customer_kontrak.id` (nullable) |
| `id_client` | integer | FK → `m_client.id` (always 111 for SanoCare) |
| `id_outlet` | integer | FK → `m_outlet.id` |
| `type` | varchar | `'visit'` (default) |
| `no_ra` | varchar | Auto-generated RA number |
| `created_date` | TIMESTAMPTZ | When scheduled |

**Sample query:**
```sql
SELECT rp.id, rp.visit_date::date, rp.status, rp.is_cancel,
       c.name AS customer, u.fullname AS technician
FROM t_road_plan rp
JOIN m_customer c ON c.id = rp.id_customer
JOIN p_user u ON u.id = rp.id_user
WHERE rp.visit_date::date = CURRENT_DATE
  AND COALESCE(rp.is_cancel, false) = false
ORDER BY rp.visit_date;
```

---

### 3.2 `t_visit` — 37,229 rows
Actual visit check-ins/check-outs with GPS.

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `id_road_plan` | integer | FK → `t_road_plan.id` |
| `id_user` | integer | FK → `p_user.id` |
| `id_customer` | integer | FK → `m_customer.id` |
| `check_in` | TIMESTAMPTZ | Arrival time |
| `check_out` | TIMESTAMPTZ | Departure time (NULL if still on-site) |
| `latitude` | NUMERIC | GPS lat — **not TEXT, no TRIM needed** |
| `longitude` | NUMERIC | GPS lng |
| `latitude_o` | NUMERIC | GPS lat at checkout |
| `longitude_o` | NUMERIC | GPS lng at checkout |
| `created_date` | TIMESTAMPTZ | **Not `created_at`** |
| `additional_data` | JSONB | Extra metadata from mobile app |
| `meta_data` | JSON | Distance/accuracy data |

**Sample — duration in minutes:**
```sql
SELECT v.id,
       EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60 AS duration_min,
       v.latitude, v.longitude,
       c.name AS customer, u.fullname AS technician
FROM t_visit v
JOIN m_customer c ON c.id = v.id_customer
JOIN p_user u ON u.id = v.id_user
WHERE v.check_in::date BETWEEN '2026-03-01' AND '2026-03-31'
  AND v.check_out IS NOT NULL
  AND EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60 BETWEEN 1 AND 480;
```

---

### 3.3 `m_customer` — 1,377 rows
Customer master data.

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `name` | varchar | Customer name — **NOT `nama_customer`** |
| `code` | varchar | Customer code |
| `address` | varchar | Street address |
| `new_city` | varchar | City (text, not FK) |
| `new_province` | varchar | Province |
| `status` | varchar | Customer status |
| `phone1` | varchar | Primary phone |
| `contact_person_name` | varchar | PIC name |
| `contact_person_phone` | varchar | PIC phone |
| `email` | varchar | |
| `id_segment` | integer | FK → `m_customer_segment.id` |
| `id_sales` | integer | FK → `p_user.id` (sales rep) |
| `is_deleted` | boolean | Filter with `WHERE is_deleted = false` |
| `id_client` | integer | Always 111 (SanoCare) |
| `created_date` | TIMESTAMPTZ | |

> `m_customer` has **NO latitude/longitude columns**.  
> Location comes from `t_visit.latitude/longitude`.

**Sample — active customers:**
```sql
SELECT id, name, address, new_city, phone1, contact_person_name
FROM m_customer
WHERE is_deleted = false
  AND id_client = 111
ORDER BY name;
```

---

### 3.4 `m_customer_kontrak` — 75 rows
Service contracts.

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `id_customer` | integer | FK → `m_customer.id` — **NOT `customer_id`** |
| `no_kontrak` | varchar | Contract number — **NOT `nomor_kontrak`** |
| `start_date` | date | Contract start |
| `end_date` | date | Contract end |
| `is_active` | varchar | `'YES'` or `'NO'` — **VARCHAR, not boolean** |
| `created_time` | TIMESTAMPTZ | |

> Has **NO `harga_kontrak`** column.

**Sample — active contracts expiring within 90 days:**
```sql
SELECT k.no_kontrak, c.name AS customer,
       k.start_date, k.end_date,
       k.end_date - CURRENT_DATE AS days_remaining
FROM m_customer_kontrak k
JOIN m_customer c ON c.id = k.id_customer
WHERE k.is_active = 'YES'
  AND k.end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 90
ORDER BY k.end_date;
```

---

### 3.5 `p_user` — 101 rows
All users (technicians + admin).

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `fullname` | varchar | Name — **NOT `nama`** |
| `email` | varchar | |
| `username` | varchar | |
| `phone` | varchar | |
| `is_deleted` | boolean | Filter with `= false` |
| `id_outlet` | integer | Default 85 |

**Sample:**
```sql
SELECT id, fullname, email, phone
FROM p_user
WHERE is_deleted = false OR is_deleted IS NULL
ORDER BY fullname;
```

---

### 3.6 `t_road_plan_foto` — 557,137 rows
Visit photos (largest table).

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `id_road_plan` | integer | FK → `t_road_plan.id` |
| `foto` | varchar | Photo filename/path |
| `type` | varchar | Photo type/category |
| `created_date` | TIMESTAMPTZ | |

---

### 3.7 `t_road_plan_area` — 14,484 rows
Areas within each visit (e.g., Toilet, Gudang, Kitchen).

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `id_road_plan` | integer | FK → `t_road_plan.id` |
| `area` | varchar | Area name (e.g., "RING I", "Gudang") |
| `treatment` | integer | FK → `m_road_plan_treatment.id` |
| `treatment_text` | varchar | Treatment name text |
| `rekap` | JSONB | Summary data |

---

### 3.8 `t_road_plan_subarea` — 100,337 rows
Sub-areas/units within each area (e.g., specific trap locations).

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `road_plan_area_id` | integer | FK → `t_road_plan_area.id` |
| `kode_unit` | varchar | Unit code |
| `sub_area` | varchar | Sub-area name |

**Sample — full area hierarchy for a visit:**
```sql
SELECT rp.id AS road_plan_id, rp.visit_date::date,
       c.name AS customer,
       ra.area, ra.treatment_text,
       rsa.kode_unit, rsa.sub_area
FROM t_road_plan rp
JOIN m_customer c ON c.id = rp.id_customer
JOIN t_road_plan_area ra ON ra.id_road_plan = rp.id
LEFT JOIN t_road_plan_subarea rsa ON rsa.road_plan_area_id = ra.id
WHERE rp.id = 40964;
```

---

### 3.9 `m_customer_kontrak_area` — 301 rows
Areas covered per contract.

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `id_kontrak` | integer | FK → `m_customer_kontrak.id` |
| `area` | varchar | Area name |

### 3.10 `m_customer_kontrak_subarea` — 1,801 rows
Sub-areas per contract area.

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer | PK |
| `id_kontrak_area` | integer | FK → `m_customer_kontrak_area.id` |
| `sub_area` | varchar | |

---

## 4. Reference / Lookup Tables

### `m_jenis_pengendalian` — 9 rows (pest control method types)
```
id | kode | nama
 1 | I    | Inspeksi
 2 | RS   | Spraying
 3 | CF   | Pengembunan
 4 | MST  | Misting
 5 | BAIT | Umpan
 6 | TRAP | Perangkap
 7 | HF   | Hot Fogging
 8 | VAC  | Vacumming
 9 | LRV  | Larasida
```

### `m_temuan` — 12 rows (pest/finding types)
```
id | nama_temuan        | status
 2 | Nyamuk             | Active
 3 | Lalat              | Active
 5 | Tikus              | Active
 6 | Ular               | Active
 7 | Serangga (Lainnya) | Inactive
```

### `m_road_plan_treatment` — 9 rows (unit types)
```
id | prefix | tipe | treatment
 1 | BB     | RC   | BLACK BOX
 2 | FC     | PC   | FLY CATCHER
 3 | IFK    | PC   | INSECT KILLER
 5 | MT     | RC   | MASSAL TRAP
 6 | ST     | RC   | SINGLE TRAP
```

### `m_karyawan_organization` — 19 rows
Employee org chart (supervisor relationships).
```sql
SELECT ko.*, u.fullname AS employee, sup.fullname AS supervisor
FROM m_karyawan_organization ko
JOIN p_user u ON u.id = ko.id_user
LEFT JOIN p_user sup ON sup.id = ko.id_supervisor;
```

### `m_customer_segment` — small
Customer segments (Mobile, Station, etc.).
```sql
SELECT id, name FROM m_customer_segment;
```

### Geographic reference (read-only, rarely needed)
- `m_kelurahan` — 83,613 rows (village level)
- `m_kecamatan` — 7,270 rows (sub-district)
- `m_city` — 514 rows
- `m_province` — 34 rows
- `m_area` — 4 rows

---

## 5. Empty / Unused Tables (Kelava features SanoCare doesn't use)

These exist in schema but have 0 data — skip them:
- `t_invoice`, `t_invoice_detail`, `t_payment` — invoicing module
- `t_sales_order`, `t_sales_order_line`, `t_sales_order_delivery` — POS/sales
- `t_ticket`, `t_ticket_log` — helpdesk ticketing
- `t_opportunity`, `t_opportunity_file`, `t_opportunity_timeline` — CRM
- `m_product`, `m_product_outlet`, `t_product_outlet_stock` — product catalog
- `t_event`, `t_event_assign` — events module
- `m_outlet_*` — multi-outlet features (SanoCare = single outlet)
- `chemical_catalog`, `chemical_usage_logs` — chemical tracking (not yet in use)

---

## 6. Common Patterns

### 6.1 Date filtering
```sql
-- Exact date (visit_date is TIMESTAMPTZ)
WHERE rp.visit_date::date = '2026-04-08'

-- Date range
WHERE rp.visit_date::date BETWEEN '2026-03-01' AND '2026-03-31'

-- This month
WHERE DATE_TRUNC('month', rp.visit_date) = DATE_TRUNC('month', CURRENT_DATE)

-- Today
WHERE rp.visit_date::date = CURRENT_DATE
```

### 6.2 Status values (Indonesian — exact match required)
```sql
-- t_road_plan.status values:
WHERE rp.status = 'Selesai'    -- completed
WHERE rp.status = 'Berjalan'   -- in progress
WHERE rp.status = 'Baru'       -- new/not started
WHERE rp.status = 'Requested'  -- pending approval
```

### 6.3 Cancel-safe filtering
```sql
-- Always use COALESCE — is_cancel can be NULL
WHERE COALESCE(rp.is_cancel, false) = false   -- not cancelled
WHERE COALESCE(rp.is_cancel, false) = true    -- cancelled
```

### 6.4 Active contracts
```sql
-- is_active is VARCHAR 'YES'/'NO', NOT boolean
WHERE k.is_active = 'YES'
```

### 6.5 Technician performance query
```sql
WITH stats AS (
    SELECT
        rp.id_user,
        COUNT(*) AS total_planned,
        COUNT(*) FILTER (WHERE rp.status = 'Selesai') AS total_completed,
        COUNT(DISTINCT rp.visit_date::date) AS active_days,
        ROUND(
            COUNT(*) FILTER (WHERE rp.status = 'Selesai')::numeric
            / NULLIF(COUNT(*), 0) * 100, 1
        ) AS completion_rate_pct
    FROM t_road_plan rp
    WHERE rp.visit_date::date BETWEEN %s AND %s
      AND COALESCE(rp.is_cancel, false) = false
    GROUP BY rp.id_user
)
SELECT u.id, u.fullname, s.total_planned, s.total_completed,
       s.active_days, s.completion_rate_pct
FROM stats s
JOIN p_user u ON u.id = s.id_user
ORDER BY s.completion_rate_pct DESC;
```

### 6.6 Visit duration (cap at 8 hours to exclude outliers)
```sql
SELECT
    AVG(LEAST(EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60, 480)) AS avg_duration_min
FROM t_visit v
WHERE v.check_in::date BETWEEN %s AND %s
  AND v.check_out IS NOT NULL
  AND EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60 BETWEEN 1 AND 480;
```

### 6.7 Full visit summary (most useful join)
```sql
SELECT
    rp.id,
    rp.visit_date::date,
    rp.status,
    rp.is_cancel,
    c.id   AS customer_id,
    c.name AS customer_name,
    c.address,
    c.new_city,
    u.id   AS technician_id,
    u.fullname AS technician_name,
    k.no_kontrak,
    k.end_date AS contract_end,
    v.check_in,
    v.check_out,
    EXTRACT(EPOCH FROM (v.check_out - v.check_in))/60 AS duration_min,
    v.latitude,
    v.longitude
FROM t_road_plan rp
JOIN m_customer c    ON c.id = rp.id_customer
JOIN p_user u        ON u.id = rp.id_user
LEFT JOIN m_customer_kontrak k ON k.id = rp.id_kontrak
LEFT JOIN t_visit v  ON v.id_road_plan = rp.id
WHERE rp.visit_date::date = CURRENT_DATE
ORDER BY rp.visit_date;
```

---

## 7. Critical Column Gotchas (burn these in)

| ❌ Wrong | ✅ Correct | Table |
|---------|-----------|-------|
| `customer_id` | `id_customer` | `t_road_plan`, `m_customer_kontrak` |
| `user_id` | `id_user` | `t_road_plan`, `t_visit` |
| `nama_customer` | `name` | `m_customer` |
| `nama` | `fullname` | `p_user` |
| `nomor_kontrak` | `no_kontrak` | `m_customer_kontrak` |
| `created_at` | `created_date` | `t_visit` |
| `is_active = true` | `is_active = 'YES'` | `m_customer_kontrak` |
| `status = 'Visited'` | `status = 'Selesai'` | `t_road_plan` |
| `is_cancel = false` | `COALESCE(is_cancel, false) = false` | `t_road_plan` |
| `harga_kontrak` | *(does not exist)* | `m_customer_kontrak` |
| `c.latitude` | *(does not exist on m_customer)* | use `t_visit.latitude` |
| `TRIM(v.latitude)` | `v.latitude` (it's NUMERIC) | `t_visit` |

---

## 8. Tables Owned by SanoCare (snc_read created, in same DB)

These are SanoCare-specific tables, also readable. They live in the same `sanocare` database:

| Table | Purpose |
|-------|---------|
| `enterprise_users` | SanoCare portal users (87 rows) |
| `enterprise_permissions` | Role-based permissions |
| `enterprise_auth_log` | Login history |
| `enterprise_refresh_tokens` | JWT refresh tokens |
| `enterprise_notifications` | In-app notifications |
| `technician_segments` | Mobile/Station/Support/Supervisor classification |
| `technician_issues` | Known tech issues |
| `verification_flags` | Photo/GPS verification results |
| `schedule_templates` | Visit schedule templates |
| `segment_kpi_rules` | KPI rules per segment |
| `kpi_monthly_archive` | Archived KPI scores |
| `universal_audit_log` | Audit trail |
| `supervisory_actions` | Sidak/QC records |
| `meetings` | MOM data |
| `winback_campaigns` | Win-back campaigns |
| `drift_alerts` | Anomaly alerts |
| `gps_breadcrumbs` | High-frequency GPS trail |
| `complaint_tickets` | Complaint tracking |
| `attendance_logs` | Fingerprint attendance |
| `daily_digests` | Daily digest cache |

> These tables use `_get_local_pool()` in the codebase, not `execute_kelava_query()`.  
> However they live in the same physical DB so `snc_read` can also SELECT them directly.

---

## 9. API Endpoints (read from live server)

Instead of querying DB directly, agents can call the REST API:

```bash
# Login
TOKEN=$(curl -s -X POST https://safencare.work/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"login":"admin@sanocare.work","password":"SanoCare2026!"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Technician leaderboard
curl -H "Authorization: Bearer $TOKEN" \
  "https://safencare.work/api/v1/enterprise/technicians/leaderboard?limit=50"

# Today's visits
curl -H "Authorization: Bearer $TOKEN" \
  "https://safencare.work/api/v1/enterprise/executive/today-visits"

# Customer list
curl -H "Authorization: Bearer $TOKEN" \
  "https://safencare.work/api/v1/enterprise/customers?limit=100"

# Contracts expiring soon
curl -H "Authorization: Bearer $TOKEN" \
  "https://safencare.work/api/v1/enterprise/contracts?days=90"

# Full OpenAPI spec (289 endpoints)
curl "https://safencare.work/api/v1/openapi.json"

# All endpoints list
curl "https://safencare.work/api/v1/docs"
```

**Swagger UI** (interactive, try-it-out):  
→ `https://safencare.work/enterprise/swagger` (login required)

**API Explorer** (browse + live call):  
→ `https://safencare.work/enterprise/api-explorer` (login required)

---

## 10. Constraints & Limits

| Rule | Detail |
|------|--------|
| Access | SELECT only — no write |
| PostgreSQL version | PG 10 — no `gen_random_uuid()`, `FILTER` clause works |
| IP whitelist | Only `104.194.154.108` can connect directly |
| Local dev | Must use SSH tunnel (port 5433) |
| Max pool size | 5 connections per pool (configured in `kelava_db.py`) |
| Largest table | `t_road_plan_foto` — 557K rows, avoid full scans |
| NULL trap | `is_cancel` can be NULL — always COALESCE |
| Timezone | All timestamps are `+07:00` (WIB) |
| Client ID | SanoCare's `id_client = 111` in all Kelava tables |

---

## 11. Quick Reference Schema Map

```
p_user (101)
  └── t_road_plan (37K) ─────────────────────────┐
        ├── t_road_plan_foto (557K)                │
        ├── t_road_plan_area (14K)                 │
        │     └── t_road_plan_subarea (100K)       │
        └── t_visit (37K)                          │
              └── t_visit_data (0, unused)         │
                                                   │
m_customer (1.4K) ──────────────────────────── joins
  └── m_customer_kontrak (75)
        ├── m_customer_kontrak_area (301)
        │     └── m_customer_kontrak_subarea (1.8K)
        └── [links to t_road_plan via id_kontrak]

Lookup tables:
  m_jenis_pengendalian (9)   — pest control methods
  m_temuan (12)              — pest/finding types
  m_road_plan_treatment (9)  — unit types
  m_customer_segment (small) — Mobile/Station segments
  m_karyawan_organization    — employee org chart
```
