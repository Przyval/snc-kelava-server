# Authentication Roadmap: "SAP Grade" Security

This document outlines the step-by-step strategy to implement **Supabase Authentication** with **PostgreSQL Row Level Security (RLS)** in the Kelava ERP system.

## Strategy Overview
We are moving from "Application-Side Security" (Python `if` statements) to "Kernel-Side Security" (Database Policies).
- **Identity Provider**: Supabase Auth (Handles Login, MFA, JWT generation).
- **Enforcement Point**: PostgreSQL RLS (Enforces data access rules per row).
- **Backend Role**: Validate JWT and set the RLS Context.

---

## Phase 1: Foundation & Setup
**Goal**: Get the environment ready to verify identities.

1.  [x] **Supabase Project Setup**
    - **Option A** (Cloud): Create project at [app.supabase.com](https://app.supabase.com)
    - **Option B** (Self-Hosted): Use `docker-compose.supabase.yml` for local deployment
      ```bash
      docker-compose -f docker-compose.supabase.yml up -d
      ```
    - Disable "Email Confirmations" for development speed (optional).
    - Copy **both** keys to `.env`:
      - `SUPABASE_ANON_KEY` - For frontend/client-side auth (public, rate-limited)
      - `SUPABASE_SERVICE_ROLE_KEY` - For backend operations (bypasses RLS, keep secret!)

2.  [x] **Helper Modules**
    - `core/config.py`: Load env vars safely. ✅ DONE
    - `core/security.py`: Initialize Supabase Client. ✅ DONE

3.  [x] **Flask Middleware**
    - Create `@require_auth` decorator. ✅ DONE
    - Logic:
        1. Extract `Authorization: Bearer <token>` header. ✅
        2. Verify token signature with Supabase. ✅
        3. Inject `user` object into Flask `g` (global context). ✅
        4. **Set RLS Context** in PostgreSQL session. ✅ DONE (via `set_rls_context()`)

---

## Phase 2: Database Integration (The "Shim")
**Goal**: Sync Supabase Users with our internal User table.

**Migration File**: `kil/db/migrations/001_auth_schema.sql` ✅ CREATED

1.  [ ] **Create Auth Schema**
    ```bash
    psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/001_auth_schema.sql
    ```

2.  [x] **Create Branches Table** ✅ (in migration)
    ```sql
    CREATE TABLE public.branches (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL,
        code TEXT UNIQUE NOT NULL,
        region TEXT,
        is_active BOOLEAN DEFAULT true,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    ```

3.  [x] **Create Users Table with Auth Link** ✅ (in migration)
    ```sql
    CREATE TABLE public.users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        auth_user_id UUID UNIQUE REFERENCES auth.users(id),
        email TEXT NOT NULL UNIQUE,
        full_name TEXT,
        role TEXT NOT NULL DEFAULT 'technician',
        default_branch_id UUID REFERENCES public.branches(id),
        metadata JSONB DEFAULT '{}'::jsonb
    );
    ```

4.  [x] **Create User Assignments Table** ✅ (in migration)
    ```sql
    CREATE TABLE public.user_assignments (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID REFERENCES public.users(id),
        branch_id UUID REFERENCES public.branches(id),
        is_primary BOOLEAN DEFAULT false,
        UNIQUE(user_id, branch_id)
    );
    ```

5.  [x] **Profile Trigger (Automated Sync)** ✅ (in migration)
    - Automatically creates `public.users` record when user signs up via Supabase
    ```sql
    CREATE OR REPLACE FUNCTION public.handle_new_user()
    RETURNS TRIGGER AS $$
    BEGIN
      INSERT INTO public.users (id, auth_user_id, email, full_name, role)
      VALUES (NEW.id, NEW.id, NEW.email,
              COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.email),
              COALESCE(NEW.raw_user_meta_data->>'role', 'technician'));
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql SECURITY DEFINER;

    CREATE TRIGGER on_auth_user_created
      AFTER INSERT ON auth.users
      FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
    ```

---

## Phase 3: "SAP Grade" Security (RLS)
**Goal**: Make it impossible to leak data, even if the API code has bugs.

**Migration File**: `kil/db/migrations/002_enable_rls.sql` ✅ CREATED

1.  [x] **Context Setter (Python)** ✅ DONE
    - Function `set_rls_context()` exists in `core/db.py` ✅
    - **WIRED** into `@require_auth` decorator ✅
    - Sets PostgreSQL session variables before any queries run

2.  [ ] **Apply RLS Migration**
    ```bash
    psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/002_enable_rls.sql
    ```

3.  [x] **Helper Functions** ✅ (in migration)
    ```sql
    -- For self-hosted PostgreSQL (NOT Supabase-hosted DB)
    CREATE FUNCTION public.get_current_user_id() RETURNS UUID AS $$
    BEGIN
        RETURN current_setting('request.jwt.claim.sub', true)::UUID;
    END;
    $$ LANGUAGE plpgsql STABLE;
    ```

4.  [x] **Define Policies (SQL)** ✅ (in migration)
    - **Branch-Based Access Policy Example**:
    ```sql
    -- ⚠️ Use get_current_user_id() for self-hosted, NOT auth.uid()
    CREATE POLICY "View Branch Orders" ON work_orders
    FOR SELECT USING (
      branch_id IN (
        SELECT branch_id FROM user_assignments
        WHERE user_id = public.get_current_user_id()
      )
    );
    ```

    > **Note**: The migration includes policies for:
    > - `public.users` (own profile + admin access)
    > - `public.technician_issues` (own issues + supervisor access)
    > - `public.gps_positions` (privacy-sensitive location data)
    > - Service role bypass for backend operations

---

## Phase 4: Frontend Integration
**Goal**: User interfaces for login and session management.

1.  [ ] **Install Supabase JS Client**
    ```bash
    cd analytics/dashboard
    npm install @supabase/supabase-js
    ```

2.  [ ] **Create Supabase Client** (`src/auth/SupabaseClient.js`)
    ```js
    import { createClient } from '@supabase/supabase-js'

    const supabaseUrl = process.env.REACT_APP_SUPABASE_URL
    const supabaseAnonKey = process.env.REACT_APP_SUPABASE_ANON_KEY

    export const supabase = createClient(supabaseUrl, supabaseAnonKey)
    ```

3.  [ ] **Update Login Page**
    - Wire existing `login.html` to Supabase auth
    - Handle email/password or OAuth (Google, GitHub)
    - Store session in localStorage

4.  [ ] **Add Auth Headers to API Calls**
    ```js
    const { data: { session } } = await supabase.auth.getSession()

    fetch('/api/v1/enterprise/customers', {
      headers: {
        'Authorization': `Bearer ${session.access_token}`
      }
    })
    ```

5.  [ ] **Apply @require_auth to Legacy Routes** 🔴 CRITICAL
    - Currently **ALL API routes are unprotected**
    - Apply decorator to files in `kil/backend/legacy/api/`:
      - `enterprise.py` (customer, technician endpoints)
      - `executive.py` (KPI dashboards)
      - `operations.py` (ops summaries)
      - `technicians.py` (technician management)
      - And ~10 more route files

---

## Phase 5: Verification & Testing
**Goal**: Prove the security model works end-to-end.

1.  [ ] **Run Migration Scripts**
    ```bash
    psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/001_auth_schema.sql
    psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/002_enable_rls.sql
    ```

2.  [ ] **Start Supabase (Self-Hosted)**
    ```bash
    docker-compose -f docker-compose.supabase.yml up -d
    # Access Supabase Studio: http://localhost:3001
    ```

3.  [ ] **Create Test Users**
    - Create 2 users in Supabase Studio
    - Assign to different branches via `user_assignments`

4.  **Positive Test**: Log in as "Technician A", verify you can see your data.

5.  **Negative Test (The "SAP Test")**:
    - Log in as "Technician A"
    - Try to access Technician B's data via API
    - **Expected**: Returns `404` or empty list (NOT `403`)
    - Database should act as if the record *does not exist*

6.  **SQL Injection Test**:
    - Try malicious tokens in Authorization header
    - Verify token validation blocks invalid JWTs

7.  **Token Expiry Test**:
    - Use expired JWT (wait 1 hour or modify token)
    - Verify returns `401 Unauthorized`

---

## Implementation Status Summary

| Phase | Component | Status |
|-------|-----------|--------|
| Phase 1 | Supabase Setup | ✅ Docker Compose Ready |
| Phase 1 | Config & Security Modules | ✅ Complete |
| Phase 1 | @require_auth Decorator | ✅ Complete |
| Phase 1 | RLS Context Wiring | ✅ Complete |
| Phase 2 | Database Schema | ✅ Migration Created |
| Phase 2 | Branches & Assignments | ✅ Migration Created |
| Phase 2 | Profile Trigger | ✅ Migration Created |
| Phase 3 | RLS Policies | ✅ Migration Created |
| Phase 3 | Helper Functions | ✅ Migration Created |
| Phase 4 | Apply Decorators to Routes | 🔴 TODO |
| Phase 4 | Frontend Supabase Client | 🔴 TODO |
| Phase 5 | Run Migrations | 🔴 TODO |
| Phase 5 | Verification Tests | 🔴 TODO |

**Next Critical Step**: Apply `@require_auth` to all legacy API routes (Phase 4, step 5)
