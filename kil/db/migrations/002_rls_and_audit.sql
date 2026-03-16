-- ============================================================================
-- Migration 002: RLS and Audit Logs (The Fortress & The Vault)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Audit Logging System
-- ----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name TEXT NOT NULL,
    record_id UUID,
    action TEXT NOT NULL, -- INSERT, UPDATE, DELETE
    old_data JSONB,
    new_data JSONB,
    actor_id UUID, -- The user performing the action (from app.current_user_id)
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Revoke modification rights on audit logs to ensure immutability
REVOKE UPDATE, DELETE ON audit.logs FROM public;

-- Function to handle audit logging via Triggers
CREATE OR REPLACE FUNCTION audit.log_change()
RETURNS TRIGGER AS $$
DECLARE
    current_user_id UUID;
BEGIN
    -- Try to get the application user ID from the session variable
    BEGIN
        current_user_id := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    EXCEPTION WHEN OTHERS THEN
        current_user_id := NULL;
    END;

    IF (TG_OP = 'DELETE') THEN
        INSERT INTO audit.logs (table_name, record_id, action, old_data, actor_id)
        VALUES (TG_TABLE_NAME, OLD.id, 'DELETE', row_to_json(OLD)::jsonb, current_user_id);
        RETURN OLD;
    ELSIF (TG_OP = 'UPDATE') THEN
        INSERT INTO audit.logs (table_name, record_id, action, old_data, new_data, actor_id)
        VALUES (TG_TABLE_NAME, NEW.id, 'UPDATE', row_to_json(OLD)::jsonb, row_to_json(NEW)::jsonb, current_user_id);
        RETURN NEW;
    ELSIF (TG_OP = 'INSERT') THEN
        INSERT INTO audit.logs (table_name, record_id, action, new_data, actor_id)
        VALUES (TG_TABLE_NAME, NEW.id, 'INSERT', row_to_json(NEW)::jsonb, current_user_id);
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ----------------------------------------------------------------------------
-- 2. Row Level Security (RLS) - Base Policies
-- ----------------------------------------------------------------------------

-- Helper function to get current user role safely
CREATE OR REPLACE FUNCTION auth.current_role() RETURNS TEXT AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_user_role', true), '');
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- Helper function to get current user ID safely
CREATE OR REPLACE FUNCTION auth.uid() RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_user_id', true), '')::UUID;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- Enable RLS
ALTER TABLE public.branches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_assignments ENABLE ROW LEVEL SECURITY;

-- Policy: Admin Bypass
-- Admins can do everything.
CREATE POLICY admin_all_branches ON public.branches
    FOR ALL
    TO public
    USING (auth.current_role() = 'admin');

CREATE POLICY admin_all_assignments ON public.user_assignments
    FOR ALL
    TO public
    USING (auth.current_role() = 'admin');

-- Policy: User Assignment Visibility
-- Users can see their own assignments.
CREATE POLICY view_own_assignments ON public.user_assignments
    FOR SELECT
    TO public
    USING (user_id = auth.uid());

-- Policy: Branch Visibility via Assignment
-- Users can see branches they are assigned to.
CREATE POLICY view_assigned_branches ON public.branches
    FOR SELECT
    TO public
    USING (
        id IN (
            SELECT branch_id 
            FROM public.user_assignments 
            WHERE user_id = auth.uid()
        )
    );

-- ----------------------------------------------------------------------------
-- 3. Apply Audit Triggers to Critical Tables
-- ----------------------------------------------------------------------------
DROP TRIGGER IF EXISTS audit_branches_changes ON public.branches;
CREATE TRIGGER audit_branches_changes
    AFTER INSERT OR UPDATE OR DELETE ON public.branches
    FOR EACH ROW EXECUTE PROCEDURE audit.log_change();

DROP TRIGGER IF EXISTS audit_assignments_changes ON public.user_assignments;
CREATE TRIGGER audit_assignments_changes
    AFTER INSERT OR UPDATE OR DELETE ON public.user_assignments
    FOR EACH ROW EXECUTE PROCEDURE audit.log_change();
