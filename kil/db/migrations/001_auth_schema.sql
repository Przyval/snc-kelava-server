-- ============================================================================
-- Migration 001: Authentication Schema for SAP-Grade Security
-- ============================================================================
-- Purpose: Create auth schema and link Supabase Auth with application users
-- Execution: psql -h localhost -p 5433 -U snc_read -d sanocare -f 001_auth_schema.sql
-- ============================================================================

-- Step 1: Create auth schema (required by Supabase GoTrue)
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS auth;

-- Grant permissions for auth schema
GRANT USAGE ON SCHEMA auth TO snc_read;
GRANT ALL ON SCHEMA auth TO snc_read;

-- Step 2: Create auth.users table (Supabase Auth manages this)
-- ============================================================================
-- Note: This table will be managed by Supabase GoTrue service
-- We create it here to establish the schema for self-hosted setup

CREATE TABLE IF NOT EXISTS auth.users (
    instance_id UUID,
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aud VARCHAR(255),
    role VARCHAR(255),
    email VARCHAR(255) UNIQUE,
    encrypted_password VARCHAR(255),
    email_confirmed_at TIMESTAMPTZ,
    invited_at TIMESTAMPTZ,
    confirmation_token VARCHAR(255),
    confirmation_sent_at TIMESTAMPTZ,
    recovery_token VARCHAR(255),
    recovery_sent_at TIMESTAMPTZ,
    email_change_token_new VARCHAR(255),
    email_change VARCHAR(255),
    email_change_sent_at TIMESTAMPTZ,
    last_sign_in_at TIMESTAMPTZ,
    raw_app_meta_data JSONB,
    raw_user_meta_data JSONB,
    is_super_admin BOOLEAN,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    phone VARCHAR(15) UNIQUE,
    phone_confirmed_at TIMESTAMPTZ,
    phone_change VARCHAR(15),
    phone_change_token VARCHAR(255),
    phone_change_sent_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ GENERATED ALWAYS AS (
        LEAST(email_confirmed_at, phone_confirmed_at)
    ) STORED,
    email_change_token_current VARCHAR(255),
    email_change_confirm_status SMALLINT,
    banned_until TIMESTAMPTZ,
    reauthentication_token VARCHAR(255),
    reauthentication_sent_at TIMESTAMPTZ,
    is_sso_user BOOLEAN DEFAULT false NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS users_instance_id_idx ON auth.users (instance_id);
CREATE INDEX IF NOT EXISTS users_email_idx ON auth.users (email);

-- Step 3: Create branches table (Organizational hierarchy)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.branches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    code TEXT UNIQUE NOT NULL,  -- e.g., "JKT-01", "BDG-02"
    region TEXT,
    address TEXT,
    phone VARCHAR(20),
    manager_name TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE public.branches IS 'Branch/outlet locations for SanoCare operations';
COMMENT ON COLUMN public.branches.code IS 'Unique branch code identifier';

-- Insert default branches (customize as needed)
INSERT INTO public.branches (code, name, region, is_active) VALUES
    ('HQ', 'Head Office', 'Jakarta', true),
    ('JKT-01', 'Jakarta Branch 1', 'Jakarta', true),
    ('BDG-01', 'Bandung Branch 1', 'West Java', true)
ON CONFLICT (code) DO NOTHING;

-- Step 4: Create public.users table (Application users)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT,
    phone VARCHAR(20),
    role TEXT NOT NULL DEFAULT 'technician',  -- technician, supervisor, admin
    default_branch_id UUID REFERENCES public.branches(id),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_auth_id ON public.users(auth_user_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON public.users(role);

COMMENT ON TABLE public.users IS 'Application user profiles linked to Supabase Auth';
COMMENT ON COLUMN public.users.auth_user_id IS 'Links to auth.users(id) from Supabase';
COMMENT ON COLUMN public.users.role IS 'User role: technician, supervisor, admin, executive';

-- Step 5: Create user_assignments table (Multi-branch access)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.user_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES public.branches(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    assigned_by UUID REFERENCES public.users(id),
    is_primary BOOLEAN DEFAULT false,  -- Primary assignment

    UNIQUE(user_id, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_user_assignments_user ON public.user_assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_user_assignments_branch ON public.user_assignments(branch_id);

COMMENT ON TABLE public.user_assignments IS 'Maps users to branches they can access';
COMMENT ON COLUMN public.user_assignments.is_primary IS 'Primary branch for the user';

-- Step 6: Create handle_new_user() trigger function
-- ============================================================================
-- This automatically creates a public.users record when a user signs up via Supabase

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.users (id, auth_user_id, email, full_name, role)
    VALUES (
        NEW.id,
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email),
        COALESCE(NEW.raw_user_meta_data->>'role', 'technician')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Create trigger on auth.users
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

COMMENT ON FUNCTION public.handle_new_user IS 'Auto-creates public.users profile when Supabase user signs up';

-- Step 7: Create updated_at trigger function
-- ============================================================================
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to tables
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE TRIGGER update_branches_updated_at BEFORE UPDATE ON public.branches
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- Step 8: Grant permissions
-- ============================================================================
GRANT SELECT, INSERT, UPDATE ON auth.users TO snc_read;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.users TO snc_read;
GRANT SELECT, INSERT, UPDATE ON public.branches TO snc_read;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_assignments TO snc_read;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA auth TO snc_read;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO snc_read;

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- Next Steps:
-- 1. Run migration 002_enable_rls.sql to enable Row Level Security
-- 2. Backfill existing users from p_user table if needed
-- 3. Start Supabase: docker-compose -f docker-compose.supabase.yml up -d
-- ============================================================================
