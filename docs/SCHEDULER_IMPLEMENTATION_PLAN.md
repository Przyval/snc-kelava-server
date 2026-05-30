# Scheduler Implementation Plan
**Target:** Push auto-draft scheduler dari 71% recall → 85-90% production-ready
**Owner:** Engineering
**Timeline:** 6 minggu (3 phase × 2 minggu)
**Start date:** 2026-05-30

---

## Executive Summary

Sistem v16 sudah mencapai **71.1% recall exact / 83.8% same-week** dengan algoritma pattern-based murni. Untuk mencapai production-ready (~85%), perlu:

1. **Phase 1 (Minggu 1-2):** Manual Recurring Rules + Customer Master UI → +10-15pp recall
2. **Phase 2 (Minggu 3-4):** Technician Availability + Churn Tracker → +5-8pp recall, -50% phantom
3. **Phase 3 (Minggu 5-6):** Pattern Library + Workflow Polish + Production Deploy

Total expected: **71% → 85-90% recall** dengan supervisor effort turun dari 4-6 jam ke 30-60 menit/bulan.

---

## Current State Assessment (v16, 2026-05-30)

### Metrik Backtest Real (Juni 2026 prediksi vs actual)
| Metrik | Value | Gap to target |
|---|---|---|
| Recall exact date | 71.1% | Target 85% = -14pp |
| Recall same week | 83.8% | Target 90% = -6pp |
| Precision STRONG | 56.8% | Target 75% = -18pp |
| Tech accuracy | 62.6% | Target 80% = -17pp |
| EXACT matches | 292/481 | Need +99 more |

### Bottleneck Source Analysis
| Issue | Events | % of misses | Fixable by |
|---|---|---|---|
| Customer phantom (stop Juni) | 55 | 35% | Phase 2 Churn Tracker |
| DOW shift Mei→Juni | 25 | 16% | Phase 1 Recurring Rules |
| Cadence anchor shift | 15 | 10% | Phase 1 Recurring Rules |
| Customer baru Juni | 8 | 5% | Phase 1 Recurring Rules (manual entry) |
| Tech mismatch tied case | 30 | 19% | Phase 1 Tech Ownership Editor |
| Multi-tech over-predict | ~25 | 16% | Phase 2 algorithm tuning |

---

## Architecture Decisions

### A1. Hybrid algorithm + manual rules
**Decision:** Manual recurring rules **override** pattern detection ketika ada.
**Rationale:** Pattern detection capture 80% predictable. Manual fills 20% edge cases + customer churn signals.
**Implementation:**
- Priority: `snc_recurring_rules` → `snc_schedule_patterns` → skip
- Generator checks manual rules FIRST per customer

### A2. Database append-only, no breaking schema
**Decision:** Tambah migrations 025-027, jangan modify existing tables.
**Rationale:** Production data integrity. Migration 023-024 sudah punya pattern tables.
**Implementation:**
- 025: `snc_recurring_rules` + `snc_recurring_rule_log`
- 026: `snc_technician_availability` + audit
- 027: `snc_customer_lifecycle_events` (churn/pause/resume)

### A3. UI: extend existing calendar.html, no separate app
**Decision:** Tab tambahan di Calendar UI: "Master Rules" + "Tech Availability" + "Customer Lifecycle"
**Rationale:** Single source of truth UX. Supervisor sudah familiar dengan Calendar.
**Implementation:**
- Alpine.js components di calendar.html
- Reuse existing `enterprise_bp` blueprint routes
- New API endpoints: `/api/v1/enterprise/recurring-rules`, `/tech-availability`, `/customer-lifecycle`

### A4. Pattern detection tetap auto-running monthly
**Decision:** Recurring rules **complement**, not replace, pattern detection.
**Rationale:** Pattern detection catch trend changes automatically. Rules lock specific predictable customers.
**Implementation:**
- Pattern detection runs nightly (cron)
- Rules applied at draft generation
- Conflict: rules win

---

## Phase 1 — Manual Recurring Rules & Master Editor
**Duration:** Minggu 1-2 (10 hari kerja)
**Expected impact:** +10-15pp recall, +15pp precision

### Scope
1. Database schema untuk recurring rules
2. API CRUD endpoints
3. UI Master Rules editor (form + table)
4. Generator integration: rules override patterns
5. Backtest validation

### Day-by-Day Plan

#### Day 1-2: Database Schema
- Migration `025_recurring_rules.sql`:

```sql
CREATE TABLE snc_recurring_rules (
    id                  SERIAL PRIMARY KEY,
    client_id           INTEGER NOT NULL REFERENCES snc_clients(id),
    primary_tech_id     INTEGER REFERENCES snc_technicians(id),
    backup_tech_1_id    INTEGER REFERENCES snc_technicians(id),
    backup_tech_2_id    INTEGER REFERENCES snc_technicians(id),

    frequency           VARCHAR(20) NOT NULL,   -- weekly|biweekly|monthly|custom
    weekdays            INTEGER[],              -- [0,3] = Mon+Thu
    week_pattern        VARCHAR(20),            -- 'all'|'1,3'|'2,4'|'cadence:YYYY-MM-DD'
    time_start          TIME NOT NULL,
    time_end            TIME,
    visit_type          VARCHAR(20),

    is_mandatory        BOOLEAN DEFAULT true,   -- override pattern detection
    suppress_holiday    BOOLEAN DEFAULT true,
    notes               TEXT,
    effective_start     DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_end       DATE,                   -- NULL = ongoing

    created_by          INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(client_id, effective_start)
);

CREATE INDEX idx_rr_client ON snc_recurring_rules(client_id);
CREATE INDEX idx_rr_active ON snc_recurring_rules(effective_start, effective_end);
CREATE INDEX idx_rr_tech ON snc_recurring_rules(primary_tech_id);

-- Audit log untuk track perubahan rule
CREATE TABLE snc_recurring_rule_log (
    id                  SERIAL PRIMARY KEY,
    rule_id             INTEGER REFERENCES snc_recurring_rules(id),
    action              VARCHAR(20),            -- created|updated|deactivated
    changed_fields      JSONB,
    changed_by          INTEGER,
    changed_at          TIMESTAMPTZ DEFAULT NOW()
);
```

**Validation:**
- ✓ Schema applies clean
- ✓ FK constraints work
- ✓ Index queries < 10ms

#### Day 3-4: API Endpoints
File: `kil/backend/legacy/api/recurring_rules.py`

```python
# Endpoints
GET    /api/v1/enterprise/recurring-rules            # list all active rules
GET    /api/v1/enterprise/recurring-rules?client_id=  # filter by client
GET    /api/v1/enterprise/recurring-rules/<id>       # get one
POST   /api/v1/enterprise/recurring-rules            # create
PUT    /api/v1/enterprise/recurring-rules/<id>      # update
DELETE /api/v1/enterprise/recurring-rules/<id>      # deactivate (soft)

# Helpers
GET    /api/v1/enterprise/recurring-rules/derive-from-pattern?client_id=
       # Generate suggested rule from latest detected pattern
       # Supervisor can review + accept
```

**Validation:**
- ✓ CRUD round-trip < 100ms
- ✓ Audit log auto-populated
- ✓ Rule activation/deactivation works
- ✓ derive-from-pattern returns valid rule structure

#### Day 5-7: UI Master Rules Editor
File: `kil/backend/legacy/web/enterprise/templates/enterprise/master_rules.html`

```
┌──────────────────────────────────────────────────────────────────┐
│ Master Recurring Rules                                  [+ New]  │
├──────────────────────────────────────────────────────────────────┤
│ Search: [____________] Filter: [Active ▼] [Frequency ▼]         │
├──────────────────────────────────────────────────────────────────┤
│ Customer       │ Freq    │ Day      │ Time   │ Primary    │ ⚙   │
├──────────────────────────────────────────────────────────────────┤
│ PT.SMB         │ Weekly  │ Senin    │ 08:00  │ Ananda     │ Edit │
│ AADK           │ Biweek  │ Jum 1,3  │ 09:00  │ Akbar      │ Edit │
│ BU.LILY        │ Weekly  │ Selasa   │ 08:00  │ Adam       │ Edit │
│ ...                                                              │
└──────────────────────────────────────────────────────────────────┘

Modal Edit Form:
┌──────────────────────────────────────────────────────────────────┐
│ Edit Recurring Rule: PT.SMB                              [X]    │
├──────────────────────────────────────────────────────────────────┤
│ Frequency  : [ Weekly ▼ ]                                        │
│ Weekdays   : [✓Sen] [Sel] [Rab] [Kam] [Jum] [Sab]                │
│ Week pat.  : [● All  ○ 1,3  ○ 2,4  ○ Cadence anchor]            │
│ Time start : [ 08:00 ]                                           │
│ Time end   : [ 10:00 ]                                           │
│ Visit type : [ PRC ▼ ]                                           │
│                                                                  │
│ Primary    : [ Ananda Almas ▼ ]                                  │
│ Backup 1   : [ Choirul Anam ▼ ]                                  │
│ Backup 2   : [ -- ▼ ]                                            │
│                                                                  │
│ ☑ Mandatory (override pattern detection)                         │
│ ☑ Suppress on holidays                                           │
│ Notes      : [ Pakuwon group, wajib ]                            │
│                                                                  │
│ Effective from: [2026-06-01]  End: [____ optional]               │
│                                                                  │
│       [ Cancel ]    [ Suggest from pattern ]    [ Save ]         │
└──────────────────────────────────────────────────────────────────┘
```

**Validation:**
- ✓ Form validation client + server
- ✓ "Suggest from pattern" populates form correctly
- ✓ Save → list updates immediately
- ✓ Mobile responsive
- ✓ Keyboard shortcuts: `n` = new, `e` = edit, `esc` = close

#### Day 8-9: Generator Integration
Modify `kil/backend/legacy/api/schedule_draft.py`:

```python
def generate_draft():
    # NEW: Load recurring rules pertama
    cur.execute("""
        SELECT * FROM snc_recurring_rules
        WHERE effective_start <= %s
          AND (effective_end IS NULL OR effective_end >= %s)
          AND is_mandatory = true
    """, (target_month_start, target_month_start))
    rules = cur.fetchall()
    rule_by_client = {r['client_id']: r for r in rules}

    # Process rules FIRST (override patterns)
    for rule in rules:
        # Generate events directly from rule
        # Skip pattern detection for this client+dow
        ...

    # Then process patterns for clients NOT in rules
    for p in patterns:
        if p['client_id'] in rule_by_client:
            continue  # rule already handled this
        # existing pattern logic
        ...
```

**Validation:**
- ✓ Rules override patterns correctly
- ✓ Conflict detection (rule + pattern at same DOW)
- ✓ Rule effective_start respected
- ✓ Backtest recall improves measurably

#### Day 10: Backtest + Validation
- Setup 30 recurring rules for top 30 customers (sample)
- Run backtest Juni 2026 with rules
- Compare v16 vs v17 (with rules)

**Success criteria:**
- ✓ Recall exact ≥ 75% (from 71.1%)
- ✓ Precision STRONG ≥ 60% (from 56.8%)
- ✓ Zero regression for non-rule customers

---

## Phase 2 — Technician Availability & Customer Lifecycle
**Duration:** Minggu 3-4
**Expected impact:** +5-8pp recall, -50% phantom predictions

### Scope
1. Technician availability calendar (cuti, off, dinas)
2. Customer lifecycle events (pause, cancel, resume)
3. Generator integration: skip on availability + churn

### Day-by-Day Plan

#### Day 11-12: Database Schema
Migration `026_tech_availability.sql`:

```sql
CREATE TABLE snc_technician_availability (
    id              SERIAL PRIMARY KEY,
    technician_id   INTEGER NOT NULL REFERENCES snc_technicians(id),
    date_from       DATE NOT NULL,
    date_to         DATE NOT NULL,
    status          VARCHAR(20) NOT NULL,   -- cuti|sakit|izin|dinas|off|libur
    reason          TEXT,
    backup_tech_id  INTEGER REFERENCES snc_technicians(id),  -- ganti siapa
    notes           TEXT,
    created_by      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CHECK (date_to >= date_from)
);

CREATE INDEX idx_ta_tech_dates ON snc_technician_availability(technician_id, date_from, date_to);
CREATE INDEX idx_ta_dates ON snc_technician_availability(date_from, date_to);
```

Migration `027_customer_lifecycle.sql`:

```sql
CREATE TABLE snc_customer_lifecycle_events (
    id                SERIAL PRIMARY KEY,
    client_id         INTEGER NOT NULL REFERENCES snc_clients(id),
    event_type        VARCHAR(20) NOT NULL,   -- pause|resume|cancel|new|reactivate
    effective_date    DATE NOT NULL,
    end_date          DATE,                   -- for pause: kapan resume
    reason            VARCHAR(50),            -- renovation|churn|seasonal|customer_request
    notes             TEXT,
    created_by        INTEGER,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cle_client ON snc_customer_lifecycle_events(client_id);
CREATE INDEX idx_cle_effective ON snc_customer_lifecycle_events(effective_date);

-- View untuk current customer status
CREATE VIEW snc_customer_current_status AS
SELECT DISTINCT ON (client_id)
    client_id,
    event_type,
    effective_date,
    end_date,
    reason
FROM snc_customer_lifecycle_events
WHERE effective_date <= CURRENT_DATE
ORDER BY client_id, effective_date DESC;
```

#### Day 13-14: API Endpoints

```python
# Tech availability
GET    /api/v1/enterprise/tech-availability?month=2026-06
POST   /api/v1/enterprise/tech-availability
PUT    /api/v1/enterprise/tech-availability/<id>
DELETE /api/v1/enterprise/tech-availability/<id>

# Customer lifecycle
GET    /api/v1/enterprise/customer-lifecycle?client_id=&status=
POST   /api/v1/enterprise/customer-lifecycle    # new event
GET    /api/v1/enterprise/customer-lifecycle/current?client_id=  # latest status
POST   /api/v1/enterprise/customer-lifecycle/bulk-tag           # multi-customer at once
```

#### Day 15-17: UI Components

**Tech Availability Calendar** (`tech_availability.html`):

```
┌──────────────────────────────────────────────────────────────────┐
│ Technician Availability                       Bulan: Juni 2026 ▼ │
├──────────────────────────────────────────────────────────────────┤
│              1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 ...    │
│ Akbar       [ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ]       │
│ Anam        [ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ][ ]       │
│ Mahrus      [ ][ ][ ][C][C][C][ ][ ][ ][ ][ ][ ][ ][ ][ ]       │
│             (C = cuti, S = sakit, D = dinas, O = OFF)            │
│                                                                  │
│ [ + Tambah Cuti/Off ]      Click cell untuk edit                │
└──────────────────────────────────────────────────────────────────┘

Modal:
┌──────────────────────────────────────────────────────────────────┐
│ Tambah Tech Availability                                         │
├──────────────────────────────────────────────────────────────────┤
│ Teknisi  : [ Moh. Mahrus ▼ ]                                     │
│ Status   : [ Cuti Tahunan ▼ ]                                    │
│ Tanggal  : [ 5 Juni ] → [ 7 Juni ]                              │
│ Backup   : [ Adam Abdillah ▼ ]   (auto-suggest from history)    │
│ Notes    : [ Pulang kampung lebaran ]                           │
│                                              [ Cancel ] [ Save ] │
└──────────────────────────────────────────────────────────────────┘
```

**Customer Lifecycle Tracker** (`customer_lifecycle.html`):

```
┌──────────────────────────────────────────────────────────────────┐
│ Customer Status Tracker                              [+ Bulk Tag]│
├──────────────────────────────────────────────────────────────────┤
│ Search: [______]  Filter: [All ▼]  [⚠ Phantom ▼] [⏸ Paused ▼]   │
├──────────────────────────────────────────────────────────────────┤
│ Customer       │ Status     │ Since     │ Reason             │ ⚙ │
├──────────────────────────────────────────────────────────────────┤
│ PCM            │ ⏸ Paused   │ 1 Jun     │ Renovation 3 bln   │ ⚙ │
│ SANTIKA        │ ✗ Cancel   │ 28 Mei    │ Switch competitor  │ ⚙ │
│ VASA           │ ⚠ Risk     │ -         │ Last visit 28 Mei  │ ⚙ │
│ BU INGGRIT     │ ✓ Active   │ 1 Jun     │ New customer       │ ⚙ │
└──────────────────────────────────────────────────────────────────┘

Phantom Alert Panel (auto-detect):
┌──────────────────────────────────────────────────────────────────┐
│ ⚠ Customer berpotensi phantom (predicted but no June activity)  │
├──────────────────────────────────────────────────────────────────┤
│ • PCM         pred=5 actual=0   [Tag Paused] [Keep Active]      │
│ • SANTIKA     pred=7 actual=0   [Tag Cancel] [Keep Active]      │
│ • ALBA        pred=5 actual=0   [Tag Paused] [Keep Active]      │
│ • ...                                                            │
└──────────────────────────────────────────────────────────────────┘
```

#### Day 18-19: Generator Integration

```python
# In generate_draft, additional filters:

# 1. Load tech unavailability untuk target month
cur.execute("""
    SELECT technician_id, date_from, date_to, backup_tech_id
    FROM snc_technician_availability
    WHERE (date_from, date_to) OVERLAPS (%s, %s)
""", (target_month_start, target_month_end))
tech_unavail = ...

# 2. Load customer lifecycle: skip paused/cancelled
cur.execute("""
    SELECT client_id FROM snc_customer_current_status
    WHERE event_type IN ('pause', 'cancel')
      AND (end_date IS NULL OR end_date >= %s)
""", (target_month_start,))
inactive_clients = ...

# In event generation:
for visit_date in target_dates:
    # Skip kalau tech tidak available
    if is_tech_unavailable(assigned_tech, visit_date):
        # Try backup
        if backup_available: assigned_tech = backup
        else: skip with reason 'tech_unavailable'

    # Skip kalau client paused/cancelled
    if client_id in inactive_clients:
        skip with reason 'client_inactive'
```

#### Day 20: Backtest + Validation

**Success criteria Phase 2:**
- ✓ Recall ≥ 78% (from 75% post-Phase 1)
- ✓ Precision ≥ 65% (from 60%)
- ✓ Phantom predictions cut 50%+
- ✓ Tech availability respected

---

## Phase 3 — Pattern Library, Workflow Polish, Production
**Duration:** Minggu 5-6
**Expected impact:** Production deploy + supervisor adoption

### Day-by-Day Plan

#### Day 21-22: Pattern Library Viewer
Show supervisor what algorithm detected:

```
┌──────────────────────────────────────────────────────────────────┐
│ Pattern Library — Detected from May 2026 data                   │
├──────────────────────────────────────────────────────────────────┤
│ [▼ Sort: Customer ▼]  [Filter: ⚠ Anomaly Only]                  │
├──────────────────────────────────────────────────────────────────┤
│ Customer       │ Detected pattern               │ Conf  │ Action │
├──────────────────────────────────────────────────────────────────┤
│ PT.SMB         │ Weekly Mon 08:00 Ananda       │ 1.00  │ ✓ Lock │
│ AADK           │ Biweekly Fri cadence:5/22     │ 1.00  │ ✓ Lock │
│ BU INGGRIT     │ ⚠ No history — new customer  │ -     │ + Add  │
│ AYAM BERKAT    │ ⚠ DOW shift Wed→Tue? check    │ 0.65  │ Review │
│ ...                                                              │
└──────────────────────────────────────────────────────────────────┘
```

#### Day 23-24: Draft Diff Viewer
Compare draft Juni vs aktual Mei:

```
┌──────────────────────────────────────────────────────────────────┐
│ Draft Diff — Juni 2026 vs Mei 2026                              │
├──────────────────────────────────────────────────────────────────┤
│ ✓ Same (340 events)         Customer recurring tanpa change      │
│ + New (25 events)           Customer baru / pattern baru        │
│ - Removed (45 events)       Customer churn / paused              │
│ ↔ Modified (90 events)      Beda tanggal/teknisi                │
│                                                                  │
│ [Expand details by type]                                         │
└──────────────────────────────────────────────────────────────────┘
```

#### Day 25-26: Excel Upload + Bulk Edit

**Excel Upload UI:**
- Drag-drop Excel jadwal bulanan
- Preview parsing result
- Confirm import → run pipeline auto

**Bulk Edit:**
- Multi-select events di calendar
- Action: reassign tech, change date, reject all
- Audit log per bulk action

#### Day 27: Production Deploy

**Pre-deploy checklist:**
- [ ] All migrations 025-027 applied di staging
- [ ] Backup production DB
- [ ] Run migrations production
- [ ] Deploy code via `make deploy`
- [ ] Smoke test 5 new endpoints
- [ ] Test create 1 recurring rule end-to-end
- [ ] Test tech availability lock
- [ ] Test phantom tagging
- [ ] Verify backtest re-runable di prod

**Rollback plan:**
- DB: `pg_dump` sebelum migration
- Code: `git revert` + redeploy

#### Day 28-30: Supervisor Training + UAT

**Training material:**
- Video walkthrough 15 menit setiap UI
- Cheatsheet 1 halaman
- FAQ doc

**UAT scenarios:**
1. Supervisor pick 10 customer → create recurring rules
2. Supervisor input tech cuti 3 hari → verify draft skip
3. Supervisor tag customer paused → verify dropped
4. Full month workflow end-to-end
5. Edge case: customer change rule mid-month

**Success criteria Phase 3:**
- ✓ All UI mobile responsive
- ✓ Supervisor approve draft < 60 menit
- ✓ Production stable 1 week post-deploy
- ✓ Recall production ≥ 80% (real measurement)

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Supervisor tidak konsisten input rules | High | High | Bulk import dari pattern + suggested rules + reminder |
| Recurring rules over-restrict (miss customer baru) | Med | Med | Hybrid: rules + pattern fallback |
| Tech availability data not maintained | High | Med | Weekly reminder + KPI tracking |
| Migration breaks production | Low | High | Staging test + DB backup + rollback ready |
| UI bug breaks Calendar | Med | High | Feature flag + gradual rollout |
| Performance degrades dengan 500+ rules | Low | Med | Index tuning + caching |
| Customer name mismatch antar Excel/Accurate | High | Med | Better fuzzy matcher + UI hint |

---

## Success Metrics

### Phase 1 Exit Criteria
- ≥ 50 recurring rules created for top customers
- Recall exact ≥ 75% on backtest
- Precision STRONG ≥ 60%
- All API endpoints < 200ms p95

### Phase 2 Exit Criteria
- ≥ 100 tech availability entries created
- ≥ 20 customer lifecycle events tagged
- Recall ≥ 78%
- Phantom reduction ≥ 50%

### Phase 3 Exit Criteria (Production)
- 1 month full supervisor workflow di production
- Draft approval time ≤ 60 minutes
- Customer complaint scheduling < 3/month
- Recall production measurement ≥ 80%
- 0 critical bugs in first week

### KPI Sustainable (Post-launch)
| KPI | Target | Frequency |
|---|---|---|
| Auto-draft recall vs actual | ≥ 80% | Monthly |
| Supervisor draft approve time | < 60 min | Monthly |
| Recurring rules coverage | ≥ 80 customers | Quarterly |
| Tech availability up-to-date | 100% by H-7 | Weekly |
| Customer churn signals timely | < 2 weeks lag | Monthly |
| System uptime | ≥ 99.5% | Monthly |
| Endpoint response p95 | < 500ms | Daily |

---

## Resource Requirements

### Engineering
- 1 backend developer (full-time 6 weeks)
- 0.5 frontend developer (Alpine.js + Tailwind)
- 0.25 DevOps (deploy + monitoring)

### Operations
- Supervisor terlibat dari Phase 1 untuk UAT
- 1 PIC dari operations sebagai single channel
- Training session: 2 jam di akhir Phase 3

### Infrastructure
- Existing PostgreSQL (kil_enterprise DB)
- No new servers needed
- Disk: +500MB untuk 1 year of logs
- DB connections: tidak nambah significantly

---

## Dependencies & Blockers

### Hard Dependencies
- [ ] SSH access ke production restored (saat ini timeout)
- [ ] Supervisor commitment 2 jam/minggu untuk Phase 1 UAT
- [ ] Backup pre-migration confirmed

### Soft Dependencies
- [ ] Holiday calendar 2026 SKB 3 Menteri resmi (untuk validate)
- [ ] Customer master cleanup 314 unmatched (nice-to-have, can defer)
- [ ] Area code data per customer (Phase 4 future)

---

## Out-of-Scope (Explicit)

### Tidak dikerjakan Phase 1-3
- ❌ Route optimization (geographic) — Phase 4
- ❌ ML-based prediction enhancement — needs more data history
- ❌ Mobile app for teknisi (sudah ada Flutter)
- ❌ Customer self-service portal — future
- ❌ Automated invoice generation — finance module separate
- ❌ Real-time chat with teknisi — separate FCM stream

---

## Open Questions (Need Decision)

1. ~~**Holiday calendar verification source?**~~ **DECIDED 2026-05-30: Manual input + validate SKB resmi Indonesia**
   - Implementation: Holiday Calendar Editor UI ditambah ke Phase 1
   - Source of truth: SKB 3 Menteri RI (PDF resmi)
   - Update cadence: Annual (Q4 untuk tahun depan)
   - Cuti customer-specific (mall tutup, hotel renovasi): per-customer suppression di Phase 2

2. ~~**Recurring rules permissions?**~~ **DECIDED 2026-05-30: Koordinator + Admin only**
   - Supervisor field tidak boleh edit rules (read-only)
   - Decorator: `@require_role(['koordinator', 'admin'])`

3. ~~**Pattern detection cadence?**~~ **DECIDED 2026-05-30: Daily cron 01:00 WIB**
   - File: `kil/backend/scripts/cron_pattern_detect.py`
   - Add to existing crontab: `0 1 * * *`
   - Always run for current_month, lookback 12 bulan
   - Email/notify supervisor on anomaly (e.g., new pattern, lost pattern)

4. ~~**Conflict resolution: rule vs pattern?**~~ **DECIDED 2026-05-30: Rule wins if mandatory=true**
   - Generator priority: `mandatory rule` → `pattern` → `optional rule` → skip
   - Conflict di same (client, dow) → rule wins
   - Conflict di different DOW → both kept (multi-DOW customer)

5. ~~**Backup tech selection logic?**~~ **DECIDED 2026-05-30: Historical pairing first**
   - User insight (2026-05-30): "Mostly yang ditempatkan di client inti naturally tidak berubah"
   - Algorithm: pakai `snc_customer_technician` (3-month ownership ranking) untuk primary/backup
   - Stable pairing prinsip: customer-tech relationship organic dan persistent
   - Workload fallback hanya kalau primary+backup_1+backup_2 semua unavailable
   - Tidak ada auto-rotation

---

## Appendix A: Tech Stack Used

- Backend: Flask + psycopg3
- DB: PostgreSQL 14 (kil_enterprise)
- Frontend: Alpine.js 3.x + Tailwind CDN + Chart.js
- Auth: JWT (existing)
- Deploy: Gunicorn + Nginx, systemd service
- Migration: Plain SQL files in `kil/db/migrations/`

## Appendix B: Existing Schema Reference

Already in production (migrations 012-024):
- `snc_schedule_events` (3,052 events)
- `snc_schedule_patterns` (500 patterns)
- `snc_technicians` (14 schedulable)
- `snc_clients` (579)
- `snc_customer_master` (579, 265 matched Accurate)
- `snc_customer_technician` (312 ownerships)
- `snc_suppression_dates` (26 holidays)
- `snc_draft_batches` (versioned drafts)

## Appendix C: API Inventory

Existing (production-ready):
- `POST /calendar/detect-patterns`
- `POST /calendar/generate-draft`
- `GET /calendar/draft`
- `POST /calendar/approve-draft`
- `DELETE /calendar/draft-event/<id>`
- `GET /calendar/patterns`
- `POST /calendar/reschedule`
- `POST /calendar/cancel`

To be added Phase 1-2:
- `/recurring-rules` CRUD
- `/tech-availability` CRUD
- `/customer-lifecycle` CRUD
- `/customer-lifecycle/current`
- `/customer-lifecycle/bulk-tag`

## Appendix D: Backtest Methodology

Untuk validate setiap phase:
1. Use `backtest_scheduler.py` (sudah ada)
2. Generate draft Juni dengan algorithm version baru
3. Compare vs `snc_schedule_events` actual Juni
4. Report: precision/recall per tier
5. Per-customer breakdown
6. Tech accuracy

Target validation cycles:
- After Phase 1 Day 10: re-backtest Juni
- After Phase 2 Day 20: re-backtest Juni + Mei (cross-validation)
- After Phase 3 Day 27: production Juli backtest (real)
