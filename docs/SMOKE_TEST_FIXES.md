# Smoke Test Fix Guide

## Option A: Auto-Fix (Recommended)
Run the automated repair script which handles Docker startup and Database compatibility patching.

```bash
./fix_smoke_test.sh
```

**What it does:**
1.  Checks if Docker is running; starts it if not.
2.  Connects to Postgres (prompts for password) to enable `uuid-ossp`.
3.  Runs the PG-10 compatible migration script (`001_auth_schema_pg10_compatible.sql`).
4.  Starts the Supabase containers.

## Option B: Manual Fix

### 1. Enable PostgreSQL Extensions
Login as superuser (postgres):
```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS auth;
GRANT ALL ON SCHEMA auth TO snc_read;
```

### 2. Run Compatible Migration
```bash
psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/001_auth_schema_pg10_compatible.sql
```

### 3. Start Supabase
```bash
open -a Docker
# Wait for Docker to start...
docker-compose -f docker-compose.supabase.yml up -d
```
