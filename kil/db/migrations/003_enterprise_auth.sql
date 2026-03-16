-- ============================================================================
-- Migration 003: Enterprise Authentication (PG10 Compatible)
-- ============================================================================
-- Standalone JWT auth - no Supabase/external dependency required.
-- Uses BIGSERIAL (not UUID) for PG10 compatibility.
-- Designed to work with snc_read user privileges.
-- ============================================================================

-- Step 1: Enterprise Users table
-- Links to existing p_user for backwards compatibility
-- ============================================================================
CREATE TABLE IF NOT EXISTS enterprise_users (
    id BIGSERIAL PRIMARY KEY,
    p_user_id INTEGER,  -- Soft link to legacy p_user.id (no FK - permission constraint)
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(200) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_login_at TIMESTAMP WITH TIME ZONE,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE enterprise_users IS 'Enterprise dashboard users with standalone JWT auth';
COMMENT ON COLUMN enterprise_users.role IS 'Role: admin, supervisor, viewer, technician';
COMMENT ON COLUMN enterprise_users.p_user_id IS 'Link to legacy p_user table for backwards compatibility';
COMMENT ON COLUMN enterprise_users.password_hash IS 'bcrypt hashed password';

CREATE INDEX IF NOT EXISTS idx_eu_email ON enterprise_users(email);
CREATE INDEX IF NOT EXISTS idx_eu_role ON enterprise_users(role);
CREATE INDEX IF NOT EXISTS idx_eu_p_user_id ON enterprise_users(p_user_id);

-- Step 2: Refresh tokens table (for JWT refresh flow)
-- ============================================================================
CREATE TABLE IF NOT EXISTS enterprise_refresh_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES enterprise_users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    user_agent TEXT,
    ip_address VARCHAR(45)
);

COMMENT ON TABLE enterprise_refresh_tokens IS 'JWT refresh tokens for session management';

CREATE INDEX IF NOT EXISTS idx_ert_user_id ON enterprise_refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_ert_token ON enterprise_refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_ert_expires ON enterprise_refresh_tokens(expires_at);

-- Step 3: Auth audit log (login attempts, password changes, etc.)
-- ============================================================================
CREATE TABLE IF NOT EXISTS enterprise_auth_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES enterprise_users(id),
    action VARCHAR(50) NOT NULL,
    success BOOLEAN NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    detail TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE enterprise_auth_log IS 'Immutable audit log of all auth events';

CREATE INDEX IF NOT EXISTS idx_eal_user_id ON enterprise_auth_log(user_id);
CREATE INDEX IF NOT EXISTS idx_eal_action ON enterprise_auth_log(action);
CREATE INDEX IF NOT EXISTS idx_eal_created ON enterprise_auth_log(created_at DESC);

-- Step 4: Role permissions mapping
-- ============================================================================
CREATE TABLE IF NOT EXISTS enterprise_permissions (
    id BIGSERIAL PRIMARY KEY,
    role VARCHAR(50) NOT NULL,
    resource VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    UNIQUE(role, resource, action)
);

COMMENT ON TABLE enterprise_permissions IS 'RBAC permission matrix - which role can do what';

-- Insert default permission matrix
INSERT INTO enterprise_permissions (role, resource, action) VALUES
    -- Admin: full access
    ('admin', '*', '*'),
    -- Supervisor: read all, write operational
    ('supervisor', 'executive', 'read'),
    ('supervisor', 'operations', 'read'),
    ('supervisor', 'operations', 'write'),
    ('supervisor', 'technicians', 'read'),
    ('supervisor', 'technicians', 'write'),
    ('supervisor', 'customers', 'read'),
    ('supervisor', 'customers', 'write'),
    ('supervisor', 'contracts', 'read'),
    ('supervisor', 'contracts', 'write'),
    ('supervisor', 'winback', 'read'),
    ('supervisor', 'winback', 'write'),
    ('supervisor', 'calendar', 'read'),
    ('supervisor', 'calendar', 'write'),
    ('supervisor', 'audit', 'read'),
    ('supervisor', 'audit', 'write'),
    -- Viewer: read-only access to all modules
    ('viewer', 'executive', 'read'),
    ('viewer', 'operations', 'read'),
    ('viewer', 'technicians', 'read'),
    ('viewer', 'customers', 'read'),
    ('viewer', 'contracts', 'read'),
    ('viewer', 'winback', 'read'),
    ('viewer', 'calendar', 'read'),
    ('viewer', 'audit', 'read'),
    -- Technician: limited access
    ('technician', 'operations', 'read'),
    ('technician', 'calendar', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Step 5: Cleanup - drop orphaned function from failed migration attempt
-- ============================================================================
DROP FUNCTION IF EXISTS public.handle_new_user();

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- Next: Seed admin user via Python script (kil/backend/scripts/seed_users.py)
-- ============================================================================
