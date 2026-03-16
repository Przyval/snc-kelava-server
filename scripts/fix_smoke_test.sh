#!/bin/bash
# ============================================================================
# Smoke Test Auto-Fix Script
# ============================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🔧 Starting Smoke Test Auto-Fix...${NC}"

# 1. Start Docker (macOS)
if ! docker info > /dev/null 2>&1; then
    echo "📦 Starting Docker Desktop..."
    open -a Docker
    echo "⏳ Waiting for Docker to start (may take 30-60s)..."
    while ! docker info > /dev/null 2>&1; do
        sleep 5
        echo -n "."
    done
    echo -e "\n${GREEN}✓ Docker is running${NC}"
else
    echo -e "${GREEN}✓ Docker is already running${NC}"
fi

# 2. Enable PostgreSQL Extensions (Needs Superuser)
echo -e "\n🔐 Enabling 'uuid-ossp' extension on PostgreSQL..."
echo -e "${RED}⚠️  Requires PostgreSQL Superuser Password (often empty or 'postgres')${NC}"
echo -n "Enter user for postgres (default: postgres): "
read PG_USER
PG_USER=${PG_USER:-postgres}

psql -h localhost -p 5433 -U $PG_USER -d sanocare -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; CREATE SCHEMA IF NOT EXISTS auth; GRANT ALL ON SCHEMA auth TO snc_read;'

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Extensions enabled${NC}"
else
    echo -e "${RED}✗ Failed to enable extensions. Check password.${NC}"
    exit 1
fi

# 3. Run Compatible Migration
echo -e "\n🔄 Running PG 10 Compatible Migration..."
psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/001_auth_schema_pg10_compatible.sql
psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/002_enable_rls.sql

# 4. Start Supabase
echo -e "\n🚀 Starting Supabase..."
docker-compose -f docker-compose.supabase.yml up -d

# 5. Verify
echo -e "\n✅ Verifying System..."
sleep 5
python3 kil/backend/scripts/verify_auth.py

echo -e "\n${GREEN}🎉 Fix Complete! System should be operational.${NC}"
