-- Migration 005: Koordinator Role & Approval Workflow
-- =======================================================
-- Adds koordinator role permissions and PENDING_APPROVAL status
-- for supervisory actions (sidak/SP require koordinator approval).
--
-- PG10 compatible. Run on Kelava DB as snc_read user.

-- 1. Insert koordinator permissions
INSERT INTO enterprise_permissions (role, resource, action) VALUES
    ('koordinator', 'executive', 'read'),
    ('koordinator', 'operations', 'read'),
    ('koordinator', 'operations', 'write'),
    ('koordinator', 'technicians', 'read'),
    ('koordinator', 'technicians', 'write'),
    ('koordinator', 'customers', 'read'),
    ('koordinator', 'customers', 'write'),
    ('koordinator', 'scheduling', 'read'),
    ('koordinator', 'scheduling', 'write'),
    ('koordinator', 'punctuality', 'read'),
    ('koordinator', 'punctuality', 'write'),
    ('koordinator', 'supervisory_actions', 'read'),
    ('koordinator', 'supervisory_actions', 'write'),
    ('koordinator', 'complaints', 'read'),
    ('koordinator', 'complaints', 'write'),
    ('koordinator', 'contracts', 'read'),
    ('koordinator', 'contracts', 'write'),
    ('koordinator', 'audit', 'read'),
    ('koordinator', 'audit', 'write'),
    ('koordinator', 'verification', 'read'),
    ('koordinator', 'verification', 'write'),
    ('koordinator', 'segments', 'read'),
    ('koordinator', 'segments', 'write'),
    ('koordinator', 'winback', 'read'),
    ('koordinator', 'winback', 'write')
ON CONFLICT (role, resource, action) DO NOTHING;

-- 2. Add PENDING_APPROVAL to supervisory_actions status
-- Drop and recreate the constraint (PG10 compatible)
ALTER TABLE supervisory_actions DROP CONSTRAINT IF EXISTS supervisory_actions_status_check;
ALTER TABLE supervisory_actions ADD CONSTRAINT supervisory_actions_status_check
    CHECK (status IN ('PENDING_APPROVAL', 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'MISSED'));

-- Done
