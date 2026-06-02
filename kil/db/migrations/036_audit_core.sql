-- Migration 036: Audit core (PRD §11, §13, §14)
-- ──────────────────────────────────────────────────────────────────────────────

-- 1. snc_contracts (PRD §6.2) — Master kontrak customer
CREATE TABLE IF NOT EXISTS snc_contracts (
    id                BIGSERIAL PRIMARY KEY,
    customer_id       BIGINT NOT NULL REFERENCES snc_clients(id) ON DELETE CASCADE,
    contract_code     TEXT,
    contract_name     TEXT,
    contract_start    DATE,
    contract_end      DATE,
    service_type      TEXT,                       -- PRC, PC, RC, S-OUT
    visit_frequency   TEXT,                       -- weekly, biweekly, monthly, custom
    visits_per_period INT,                        -- e.g. 4 = 4 visits/month
    preferred_day     INT,                        -- 0=Mon..6=Sun
    preferred_time    TEXT,                       -- HH:MM
    is_active         BOOLEAN DEFAULT true,
    source            TEXT,                       -- 'accurate' | 'manual' | 'excel'
    notes             TEXT,
    created_by        INT,
    created_at        TIMESTAMPTZ DEFAULT now(),
    updated_at        TIMESTAMPTZ DEFAULT now(),
    updated_by        INT,
    CHECK (contract_end IS NULL OR contract_end >= contract_start)
);
CREATE INDEX IF NOT EXISTS idx_contracts_customer  ON snc_contracts (customer_id);
CREATE INDEX IF NOT EXISTS idx_contracts_active    ON snc_contracts (is_active, contract_end);

-- 2. Audit status tagging untuk snc_schedule_events
ALTER TABLE snc_schedule_events
    ADD COLUMN IF NOT EXISTS audit_status TEXT,       -- 'ok' | 'warning' | 'blocker' | 'resolved' | 'approved_exception'
    ADD COLUMN IF NOT EXISTS audit_reason TEXT,       -- 1-of-10 categories from PRD §9.3
    ADD COLUMN IF NOT EXISTS contract_id  BIGINT REFERENCES snc_contracts(id) ON DELETE SET NULL;

-- 3. Excel upload comparison
CREATE TABLE IF NOT EXISTS snc_excel_upload (
    id              BIGSERIAL PRIMARY KEY,
    filename        TEXT NOT NULL,
    target_month    TEXT NOT NULL,                -- YYYY-MM
    uploaded_by     INT NOT NULL,
    uploaded_at     TIMESTAMPTZ DEFAULT now(),
    raw_visit_count INT,                          -- total rows parsed
    parsed_payload  JSONB                         -- {visits: [...], errors: [...]}
);

CREATE TABLE IF NOT EXISTS snc_compare_results (
    id              BIGSERIAL PRIMARY KEY,
    upload_id       BIGINT REFERENCES snc_excel_upload(id) ON DELETE CASCADE,
    target_month    TEXT,
    -- comparison record
    excel_tech_id   BIGINT,
    excel_client_id BIGINT,
    excel_date      DATE,
    excel_time      TEXT,
    system_event_id BIGINT REFERENCES snc_schedule_events(id) ON DELETE SET NULL,
    -- classification (PRD §9.3)
    diff_category   TEXT NOT NULL,                -- 'same' | 'tech_diff_absence' | 'tech_diff_backup'
                                                  -- | 'system_added' | 'excel_only' | 'system_missing_no_rule'
                                                  -- | 'dup_excel' | 'dup_system' | 'manual' | 'unresolved'
    resolution      TEXT,                         -- 'pending' | 'accepted' | 'fixed' | 'ignored'
    resolved_by     INT,
    resolved_at     TIMESTAMPTZ,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_compare_upload   ON snc_compare_results (upload_id, diff_category);
CREATE INDEX IF NOT EXISTS idx_compare_pending  ON snc_compare_results (resolution) WHERE resolution = 'pending';

-- 4. Customer name aliases (for fuzzy matching review)
CREATE TABLE IF NOT EXISTS snc_client_aliases (
    id          BIGSERIAL PRIMARY KEY,
    client_id   BIGINT NOT NULL REFERENCES snc_clients(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL,
    source      TEXT,                             -- 'excel' | 'accurate' | 'manual'
    created_by  INT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (alias)
);
CREATE INDEX IF NOT EXISTS idx_aliases_client ON snc_client_aliases (client_id);

-- 5. Publish gate decisions log
CREATE TABLE IF NOT EXISTS snc_publish_gate_log (
    id            BIGSERIAL PRIMARY KEY,
    batch_id      BIGINT REFERENCES snc_draft_batches(id) ON DELETE CASCADE,
    target_month  TEXT,
    readiness_score INT,                          -- 0-100
    blockers_count  INT,
    warnings_count  INT,
    decision      TEXT NOT NULL,                  -- 'ready' | 'warning_publish' | 'needs_review' | 'not_ready' | 'override_publish'
    decided_by    INT,
    decided_at    TIMESTAMPTZ DEFAULT now(),
    notes         TEXT
);
