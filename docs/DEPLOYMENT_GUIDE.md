# SanoCare.work SAP-Grade Security Deployment Guide

## 🎯 Overview

This guide walks you through deploying the complete authentication and Row-Level Security (RLS) system for SanoCare.work.

**Architecture**: Supabase Auth + PostgreSQL RLS + Flask @require_auth

---

## ✅ Prerequisites

- [x] Docker & Docker Compose installed
- [x] PostgreSQL 12+ running (localhost:5433)
- [x] Python 3.10+
- [x] Access to `sanocare` database

---

## 📋 Deployment Steps

### Step 1: Start Supabase (Self-Hosted)

```bash
# Start Supabase services
docker-compose -f docker-compose.supabase.yml up -d

# Verify services are running
docker ps | grep supabase

# Expected output:
# - supabase-kong (port 8000)
# - supabase-auth (internal)
# - supabase-studio (port 3001)
# - supabase-meta (internal)
```

**Supabase Studio**: http://localhost:3001
**Supabase API**: http://localhost:8000

---

### Step 2: Run Database Migrations

```bash
# Connect to PostgreSQL and run migrations
cd kil/db/migrations

# Migration 1: Create auth schema, users, branches, user_assignments
psql -h localhost -p 5433 -U snc_read -d sanocare -f 001_auth_schema.sql

# Migration 2: Enable RLS and create policies
psql -h localhost -p 5433 -U snc_read -d sanocare -f 002_enable_rls.sql
```

**Verify migrations**:
```sql
-- Check tables exist
\dt public.users
\dt public.branches
\dt public.user_assignments
\dt auth.users

-- Check RLS is enabled
SELECT tablename, rowsecurity FROM pg_tables WHERE tablename = 'users';
```

---

### Step 3: Create Test Users

**Option A**: Via Supabase Studio (Recommended)
1. Open http://localhost:3001
2. Go to Authentication → Users
3. Click "Add User"
4. Create users:
   - **Admin**: admin@sanocare.work (role: admin)
   - **Supervisor**: supervisor@sanocare.work (role: supervisor)
   - **Technician**: tech@sanocare.work (role: technician)

**Option B**: Via SQL
```sql
-- This will trigger the handle_new_user() function automatically
INSERT INTO auth.users (email, encrypted_password, email_confirmed_at, raw_user_meta_data)
VALUES (
    'admin@sanocare.work',
    crypt('AdminPassword123!', gen_salt('bf')),
    NOW(),
    '{"full_name": "System Administrator", "role": "admin"}'::jsonb
);
```

---

### Step 4: Assign Users to Branches

```sql
-- Get user IDs
SELECT id, email FROM public.users;

-- Assign admin to HQ
INSERT INTO public.user_assignments (user_id, branch_id, is_primary)
SELECT u.id, b.id, true
FROM public.users u
CROSS JOIN public.branches b
WHERE u.email = 'admin@sanocare.work' AND b.code = 'HQ';

-- Assign technician to JKT-01
INSERT INTO public.user_assignments (user_id, branch_id, is_primary)
SELECT u.id, b.id, true
FROM public.users u
CROSS JOIN public.branches b
WHERE u.email = 'tech@sanocare.work' AND b.code = 'JKT-01';
```

---

### Step 5: Start Flask Application

```bash
# From project root
export FLASK_APP=kil.backend.legacy.app
export FLASK_ENV=development

# Start Flask server
flask run --host=0.0.0.0 --port=5000

# Or using Python directly
python -m kil.backend.legacy.app
```

**Verify Flask is running**: http://localhost:5000/health

---

### Step 6: Verify Authentication System

```bash
# Run verification script
python kil/backend/scripts/verify_auth.py
```

**Expected output**:
```
✓ Supabase Auth service is running
✓ auth schema exists
✓ public.users table exists
✓ public.branches table exists
✓ public.user_assignments table exists
✓ RLS enabled on public.users
✓ Endpoint correctly rejects unauthenticated requests

✓ All checks passed! SAP-grade security is operational.
```

---

## 🧪 Testing the Security Model

### Test 1: Login via Web UI

1. Open http://localhost:5000/login
2. Enter credentials: `admin@sanocare.work` / `AdminPassword123!`
3. Should redirect to dashboard (/)

### Test 2: API Call Without Auth (Should Fail)

```bash
curl http://localhost:5000/api/v1/executive/kpis

# Expected: {"error":"Missing Authorization Header","code":"AUTH_001"}
```

### Test 3: API Call With Auth (Should Succeed)

```bash
# First, get access token by logging in
# Then use it in API calls:

curl http://localhost:5000/api/v1/executive/kpis \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN_HERE"

# Expected: JSON response with KPI data
```

### Test 4: Row-Level Security Test

```sql
-- Set session as technician user
SET LOCAL request.jwt.claim.sub = '<tech-user-uuid>';
SET LOCAL request.jwt.claim.role = 'authenticated';

-- Query should only return data for assigned branches
SELECT * FROM public.technician_issues;

-- Reset
RESET request.jwt.claim.sub;
RESET request.jwt.claim.role;
```

---

## 🚀 Quick Start Script

Save as `start_sanocare.sh`:

```bash
#!/bin/bash
# SanoCare SAP-Grade Security Startup Script

echo "🚀 Starting SanoCare.work with SAP-Grade Security..."

# 1. Start Supabase
echo "📦 Starting Supabase services..."
docker-compose -f docker-compose.supabase.yml up -d
sleep 5

# 2. Check database connection
echo "🗄️  Checking database connection..."
psql -h localhost -p 5433 -U snc_read -d sanocare -c "SELECT 1;" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Database connected"
else
    echo "✗ Database connection failed!"
    exit 1
fi

# 3. Run migrations (if needed)
if [ "$1" == "--migrate" ]; then
    echo "🔧 Running database migrations..."
    psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/001_auth_schema.sql
    psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/002_enable_rls.sql
fi

# 4. Start Flask
echo "🌐 Starting Flask application..."
export FLASK_APP=kil.backend.legacy.app
export FLASK_ENV=development
flask run --host=0.0.0.0 --port=5000 &

sleep 3

# 5. Verify
echo "✅ Running verification tests..."
python kil/backend/scripts/verify_auth.py

echo ""
echo "🎉 SanoCare.work is running!"
echo ""
echo "📍 Access Points:"
echo "   - Dashboard:       http://localhost:5000"
echo "   - Login Page:      http://localhost:5000/login"
echo "   - Supabase Studio: http://localhost:3001"
echo ""
```

Make it executable:
```bash
chmod +x start_sanocare.sh
./start_sanocare.sh --migrate
```

---

## 🔒 Security Checklist

- [x] All API routes protected with @require_auth (45 routes)
- [x] RLS enabled on sensitive tables
- [x] RLS context set in middleware
- [x] JWT tokens verified on every request
- [x] Session management with auto-refresh
- [x] Branch-level data isolation via RLS policies
- [x] Service role for backend operations
- [x] Automatic user profile creation on signup

---

## 📊 System Architecture

```
┌─────────────────┐
│   Frontend      │
│   (Browser)     │
└────────┬────────┘
         │ JWT Token in Header
         ▼
┌─────────────────┐
│  Flask Middleware│
│  @require_auth  │ ← Verifies JWT with Supabase
└────────┬────────┘
         │ set_rls_context(user_id)
         ▼
┌─────────────────┐
│   PostgreSQL    │
│   with RLS      │ ← Database enforces access rules
└─────────────────┘
```

---

## 🛠️ Troubleshooting

### Issue: Supabase not starting
```bash
# Check logs
docker-compose -f docker-compose.supabase.yml logs

# Restart services
docker-compose -f docker-compose.supabase.yml down
docker-compose -f docker-compose.supabase.yml up -d
```

### Issue: 401 Unauthorized on all requests
- Check `.env` has correct `SUPABASE_URL` and `SUPABASE_ANON_KEY`
- Verify Supabase is running: `curl http://localhost:8000/auth/v1/health`
- Check Flask logs for errors

### Issue: RLS blocking all queries
- Ensure `set_rls_context()` is called in middleware
- Check session variables are set:
  ```sql
  SHOW request.jwt.claim.sub;
  SHOW request.jwt.claim.role;
  ```

---

## 📚 Next Steps

1. **Production Deployment**:
   - Change JWT secret in docker-compose.supabase.yml
   - Use production Supabase URL (not localhost)
   - Enable SSL for API and database
   - Set up email SMTP for password recovery

2. **Monitoring**:
   - Set up logging for auth failures
   - Monitor RLS policy performance
   - Track session expiry and refreshes

3. **Advanced Features**:
   - Multi-factor authentication (MFA)
   - OAuth providers (Google, Microsoft)
   - API rate limiting
   - Role-based access control (RBAC) enhancements

---

## 📞 Support

For issues or questions:
- Check [docs/auth-roadmap.md](docs/auth-roadmap.md) for implementation details
- Run verification: `python kil/backend/scripts/verify_auth.py`
- Review audit: See plan file at `.claude/plans/`

---

**Status**: ✅ SAP-Grade Security Implementation Complete

**Security Model**: Supabase Auth + PostgreSQL RLS + Flask Middleware
**Routes Protected**: 45 API endpoints
**RLS Tables**: users, technician_issues, gps_positions, user_assignments
