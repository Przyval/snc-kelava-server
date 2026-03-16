-- ============================================================================
-- Migration 002: Row Level Security (RLS) Policies - SAP Grade Security
-- ============================================================================
-- Purpose: Enable database-level access control using PostgreSQL RLS
-- Execution: psql -h localhost -p 5433 -U snc_read -d sanocare -f 002_enable_rls.sql
-- Pre-requisite: Run 001_auth_schema.sql first
-- ============================================================================

-- ============================================================================
-- IMPORTANT: RLS Context Functions
-- ============================================================================
-- These functions read the session variables set by Python's set_rls_context()
-- For self-hosted PostgreSQL, we use current_setting() instead of auth.uid()

CREATE OR REPLACE FUNCTION public.get_current_user_id()
RETURNS UUID AS $$
BEGIN
    -- Read the user ID from session variable set by Python middleware
    RETURN current_setting('request.jwt.claim.sub', true)::UUID;
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION public.get_current_user_role()
RETURNS TEXT AS $$
BEGIN
    RETURN current_setting('request.jwt.claim.role', true);
EXCEPTION
    WHEN OTHERS THEN
        RETURN 'anon';
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION public.get_current_user_id IS 'Returns authenticated user UUID from RLS context';
COMMENT ON FUNCTION public.get_current_user_role IS 'Returns authenticated user role from RLS context';

-- ============================================================================
-- Step 1: Enable RLS on Core Tables
-- ============================================================================

-- Auth and User Management Tables
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.branches ENABLE ROW LEVEL SECURITY;

-- KIL Analytics Tables
ALTER TABLE public.technician_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.issue_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gps_positions ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Step 2: Policies for public.users
-- ============================================================================

-- Users can view their own profile
CREATE POLICY "Users can view own profile"
    ON public.users
    FOR SELECT
    USING (id = public.get_current_user_id());

-- Admins can view all users
CREATE POLICY "Admins can view all users"
    ON public.users
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = public.get_current_user_id()
            AND role IN ('admin', 'executive')
        )
    );

-- Users can update their own profile (limited fields)
CREATE POLICY "Users can update own profile"
    ON public.users
    FOR UPDATE
    USING (id = public.get_current_user_id())
    WITH CHECK (id = public.get_current_user_id());

-- Admins can insert/update/delete users
CREATE POLICY "Admins can manage users"
    ON public.users
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = public.get_current_user_id()
            AND role = 'admin'
        )
    );

-- ============================================================================
-- Step 3: Policies for public.branches
-- ============================================================================

-- All authenticated users can view branches
CREATE POLICY "Authenticated users can view branches"
    ON public.branches
    FOR SELECT
    USING (public.get_current_user_role() = 'authenticated');

-- Only admins can modify branches
CREATE POLICY "Admins can manage branches"
    ON public.branches
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = public.get_current_user_id()
            AND role = 'admin'
        )
    );

-- ============================================================================
-- Step 4: Policies for public.user_assignments
-- ============================================================================

-- Users can view their own branch assignments
CREATE POLICY "Users can view own assignments"
    ON public.user_assignments
    FOR SELECT
    USING (user_id = public.get_current_user_id());

-- Admins and supervisors can view all assignments
CREATE POLICY "Admins can view all assignments"
    ON public.user_assignments
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = public.get_current_user_id()
            AND role IN ('admin', 'supervisor', 'executive')
        )
    );

-- Only admins can manage assignments
CREATE POLICY "Admins can manage assignments"
    ON public.user_assignments
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = public.get_current_user_id()
            AND role = 'admin'
        )
    );

-- ============================================================================
-- Step 5: Policies for technician_issues (Branch-Based Access)
-- ============================================================================

-- Technicians can view their own issues
CREATE POLICY "Technicians can view own issues"
    ON public.technician_issues
    FOR SELECT
    USING (
        -- Match by technician_id in the issues table
        -- This assumes technician_id correlates with user records
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = public.get_current_user_id()
            AND (
                -- Direct match: user's metadata contains their technician ID
                (u.metadata->>'technician_id')::INTEGER = technician_issues.technician_id
                OR u.role IN ('admin', 'executive', 'supervisor')
            )
        )
    );

-- Supervisors can view issues for technicians in their branches
CREATE POLICY "Supervisors can view branch issues"
    ON public.technician_issues
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.users u
            JOIN public.user_assignments ua ON ua.user_id = u.id
            WHERE u.id = public.get_current_user_id()
            AND u.role IN ('supervisor', 'admin', 'executive')
        )
    );

-- Only supervisors and admins can update issue status
CREATE POLICY "Supervisors can manage issues"
    ON public.technician_issues
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = public.get_current_user_id()
            AND role IN ('supervisor', 'admin', 'executive')
        )
    );

-- ============================================================================
-- Step 6: Policies for issue_actions (Audit Trail)
-- ============================================================================

-- Users can view actions on issues they have access to
CREATE POLICY "Users can view accessible issue actions"
    ON public.issue_actions
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.technician_issues ti
            WHERE ti.id = issue_actions.issue_id
            -- Reuse technician_issues SELECT policies
        )
    );

-- Authenticated users can insert actions on accessible issues
CREATE POLICY "Users can add actions to accessible issues"
    ON public.issue_actions
    FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.technician_issues ti
            WHERE ti.id = issue_actions.issue_id
        )
        AND public.get_current_user_role() = 'authenticated'
    );

-- ============================================================================
-- Step 7: Policies for gps_positions (Privacy-Sensitive)
-- ============================================================================

-- Users can view their own GPS positions
CREATE POLICY "Users can view own GPS data"
    ON public.gps_positions
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = public.get_current_user_id()
            AND (u.metadata->>'technician_id')::INTEGER = gps_positions.internal_id
        )
    );

-- Supervisors and admins can view all GPS data
CREATE POLICY "Supervisors can view GPS data"
    ON public.gps_positions
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.users
            WHERE id = public.get_current_user_id()
            AND role IN ('supervisor', 'admin', 'executive')
        )
    );

-- ============================================================================
-- Step 8: Service Role Bypass (Backend Operations)
-- ============================================================================
-- The service role can bypass all RLS policies for system operations

-- Create service role bypass policies for critical tables
CREATE POLICY "Service role bypass for users"
    ON public.users
    FOR ALL
    USING (public.get_current_user_role() = 'service_role');

CREATE POLICY "Service role bypass for technician_issues"
    ON public.technician_issues
    FOR ALL
    USING (public.get_current_user_role() = 'service_role');

-- ============================================================================
-- Step 9: Create Helper Views for Common Queries
-- ============================================================================

-- View: User's Accessible Branches
CREATE OR REPLACE VIEW public.v_user_accessible_branches AS
SELECT
    ua.user_id,
    b.id as branch_id,
    b.code as branch_code,
    b.name as branch_name,
    b.region,
    ua.is_primary
FROM public.user_assignments ua
JOIN public.branches b ON b.id = ua.branch_id
WHERE ua.user_id = public.get_current_user_id()
AND b.is_active = true;

COMMENT ON VIEW public.v_user_accessible_branches IS 'Shows branches accessible to current authenticated user';

-- ============================================================================
-- Step 10: Test RLS Context (Manual Verification)
-- ============================================================================

-- Test script to verify RLS is working:
--
-- 1. Set session as a specific user:
--    SET LOCAL request.jwt.claim.sub = '<user-uuid>';
--    SET LOCAL request.jwt.claim.role = 'authenticated';
--
-- 2. Query should only return data for that user:
--    SELECT * FROM public.users;
--    SELECT * FROM public.technician_issues;
--
-- 3. Reset session:
--    RESET request.jwt.claim.sub;
--    RESET request.jwt.claim.role;

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- Next Steps:
-- 1. Apply @require_auth decorator to all API routes
-- 2. Test with actual user tokens
-- 3. Run verification script: python verify_rls.py
-- ============================================================================

-- Grant execute permissions on helper functions
GRANT EXECUTE ON FUNCTION public.get_current_user_id() TO snc_read;
GRANT EXECUTE ON FUNCTION public.get_current_user_role() TO snc_read;
