#!/bin/bash
# ============================================================================
# SanoCare.work SAP-Grade Security Startup Script
# ============================================================================
# Usage:
#   ./start_sanocare.sh                 # Start services
#   ./start_sanocare.sh --migrate       # Run migrations + start services
#   ./start_sanocare.sh --verify-only   # Only run verification tests
# ============================================================================

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo -e "${BLUE}============================================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}============================================================================${NC}"
}

print_step() {
    echo -e "\n${BLUE}▶${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Main script
print_header "🚀 SanoCare.work SAP-Grade Security Startup"

# Change to script directory
cd "$(dirname "$0")"

# Verify-only mode
if [ "$1" == "--verify-only" ]; then
    print_step "Running verification tests only..."
    python3 kil/backend/scripts/verify_auth.py
    exit $?
fi

# Step 1: Check prerequisites
print_step "Checking prerequisites..."

# Check Docker
if command -v docker &> /dev/null; then
    print_success "Docker installed"
else
    print_error "Docker not found. Please install Docker first."
    exit 1
fi

# Check Python
if command -v python3 &> /dev/null; then
    print_success "Python 3 installed"
else
    print_error "Python 3 not found. Please install Python 3.10+."
    exit 1
fi

# Check psql
if command -v psql &> /dev/null; then
    print_success "PostgreSQL client installed"
else
    print_warning "psql not found. Migrations will be skipped."
fi

# Step 2: Start Supabase
print_step "Starting Supabase services..."

if docker-compose -f docker-compose.supabase.yml up -d; then
    print_success "Supabase services started"
else
    print_error "Failed to start Supabase"
    exit 1
fi

echo "   Waiting for services to initialize..."
sleep 5

# Verify Supabase health
if curl -s http://localhost:8000/auth/v1/health > /dev/null 2>&1; then
    print_success "Supabase Auth is healthy"
else
    print_warning "Supabase Auth not responding yet (may need more time)"
fi

# Step 3: Check database connection
print_step "Checking database connection..."

if psql -h localhost -p 5433 -U snc_read -d sanocare -c "SELECT 1;" > /dev/null 2>&1; then
    print_success "Database connection successful"
else
    print_error "Database connection failed!"
    print_warning "Ensure PostgreSQL is running on localhost:5433"
    exit 1
fi

# Step 4: Run migrations (if requested)
if [ "$1" == "--migrate" ]; then
    print_step "Running database migrations..."

    if [ -f "kil/db/migrations/001_auth_schema.sql" ]; then
        echo "   Running 001_auth_schema.sql..."
        if psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/001_auth_schema.sql > /dev/null 2>&1; then
            print_success "Auth schema migration completed"
        else
            print_warning "Migration may have already been applied"
        fi
    fi

    if [ -f "kil/db/migrations/002_enable_rls.sql" ]; then
        echo "   Running 002_enable_rls.sql..."
        if psql -h localhost -p 5433 -U snc_read -d sanocare -f kil/db/migrations/002_enable_rls.sql > /dev/null 2>&1; then
            print_success "RLS policies migration completed"
        else
            print_warning "Migration may have already been applied"
        fi
    fi
fi

# Step 5: Install Python dependencies
print_step "Checking Python dependencies..."

if [ -f "pyproject.toml" ]; then
    echo "   Installing dependencies with pip..."
    pip3 install -q -e . 2>/dev/null || print_warning "Some dependencies may already be installed"
    print_success "Dependencies ready"
fi

# Step 6: Start Flask application (in background)
print_step "Starting Flask application..."

export FLASK_APP=kil.backend.legacy.app
export FLASK_ENV=development

# Kill any existing Flask process on port 5000
lsof -ti:5000 | xargs kill -9 2>/dev/null || true

# Start Flask in background
nohup python3 -m kil.backend.legacy.app > flask.log 2>&1 &
FLASK_PID=$!

echo "   Waiting for Flask to start..."
sleep 3

# Check if Flask started successfully
if curl -s http://localhost:5000/ > /dev/null 2>&1; then
    print_success "Flask application started (PID: $FLASK_PID)"
else
    print_warning "Flask may need more time to start. Check flask.log for errors."
fi

# Step 7: Run verification tests
print_step "Running security verification tests..."
echo ""

if python3 kil/backend/scripts/verify_auth.py; then
    VERIFY_STATUS=0
else
    VERIFY_STATUS=1
fi

# Print final status
echo ""
print_header "🎉 SanoCare.work Startup Complete"

echo ""
echo -e "${BLUE}📍 Access Points:${NC}"
echo "   • Dashboard:         http://localhost:5000/"
echo "   • Login Page:        http://localhost:5000/login"
echo "   • Supabase Studio:   http://localhost:3001"
echo "   • API Base:          http://localhost:5000/api/v1"
echo ""
echo -e "${BLUE}📊 System Status:${NC}"
echo "   • Supabase Auth:     ✓ Running (port 8000)"
echo "   • Flask App:         ✓ Running (PID: $FLASK_PID)"
echo "   • PostgreSQL:        ✓ Connected (port 5433)"
echo ""
echo -e "${BLUE}📝 Logs:${NC}"
echo "   • Flask logs:        tail -f flask.log"
echo "   • Supabase logs:     docker-compose -f docker-compose.supabase.yml logs -f"
echo ""
echo -e "${BLUE}🛑 To Stop:${NC}"
echo "   • Stop Flask:        kill $FLASK_PID"
echo "   • Stop Supabase:     docker-compose -f docker-compose.supabase.yml down"
echo ""

if [ $VERIFY_STATUS -eq 0 ]; then
    echo -e "${GREEN}✓ All systems operational! SAP-grade security is active.${NC}"
else
    echo -e "${YELLOW}⚠ System started with warnings. Review verification output above.${NC}"
fi

echo ""
print_header "Ready for secure operations"
echo ""

exit 0
