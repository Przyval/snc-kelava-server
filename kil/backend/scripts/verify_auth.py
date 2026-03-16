#!/usr/bin/env python3
"""
Authentication Verification Script
===================================
Tests the SAP-grade security implementation end-to-end.

Usage:
    python kil/backend/scripts/verify_auth.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "http://localhost:8000")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
API_BASE_URL = "http://localhost:5000/api/v1"  # Adjust if different

# Test colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def print_test(name):
    """Print test name."""
    print(f"\n{BLUE}TEST:{RESET} {name}")


def print_success(message):
    """Print success message."""
    print(f"  {GREEN}✓{RESET} {message}")


def print_failure(message):
    """Print failure message."""
    print(f"  {RED}✗{RESET} {message}")


def print_warning(message):
    """Print warning message."""
    print(f"  {YELLOW}⚠{RESET} {message}")


class AuthVerifier:
    """Verify authentication implementation."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    def verify_supabase_running(self):
        """Check if Supabase is running."""
        print_test("Supabase Service Availability")

        try:
            response = requests.get(
                f"{SUPABASE_URL}/auth/v1/health", timeout=5
            )
            if response.status_code == 200:
                print_success("Supabase Auth service is running")
                self.passed += 1
                return True
            else:
                print_failure(f"Unexpected status: {response.status_code}")
                self.failed += 1
                return False
        except requests.exceptions.ConnectionError:
            print_failure("Cannot connect to Supabase (is docker running?)")
            print_warning("Run: docker-compose -f docker-compose.supabase.yml up -d")
            self.failed += 1
            return False
        except Exception as e:
            print_failure(f"Error: {str(e)}")
            self.failed += 1
            return False

    def verify_api_protected(self):
        """Verify API endpoints require authentication."""
        print_test("API Endpoint Protection")

        # Test executive endpoint without auth
        try:
            response = requests.get(f"{API_BASE_URL}/executive/kpis", timeout=5)

            if response.status_code == 401:
                print_success("Endpoint correctly rejects unauthenticated requests")
                self.passed += 1
                return True
            elif response.status_code == 200:
                print_failure(
                    "CRITICAL: Endpoint allows unauthenticated access!"
                )
                print_warning("Auth decorators may not be applied")
                self.failed += 1
                return False
            else:
                print_warning(f"Unexpected status: {response.status_code}")
                self.warnings += 1
                return False
        except requests.exceptions.ConnectionError:
            print_failure("Cannot connect to API server (is Flask running?)")
            print_warning("Run: python -m kil.backend.legacy.app")
            self.failed += 1
            return False
        except Exception as e:
            print_failure(f"Error: {str(e)}")
            self.failed += 1
            return False

    def verify_database_schema(self):
        """Check if auth schema exists."""
        print_test("Database Schema")

        try:
            import psycopg

            # Connect to database
            conn = psycopg.connect(
                host=os.getenv("KELAVA_HOST", "localhost"),
                port=int(os.getenv("KELAVA_PORT", 5433)),
                dbname=os.getenv("KELAVA_DB", "sanocare"),
                user=os.getenv("KELAVA_USER", "snc_read"),
                password=os.getenv("KELAVA_PASSWORD"),
            )

            cur = conn.cursor()

            # Check auth schema exists
            cur.execute(
                """
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name = 'auth'
            """
            )
            if cur.fetchone():
                print_success("auth schema exists")
                self.passed += 1
            else:
                print_failure("auth schema missing")
                print_warning("Run: psql -f kil/db/migrations/001_auth_schema.sql")
                self.failed += 1

            # Check public.users table
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'users'
            """
            )
            if cur.fetchone():
                print_success("public.users table exists")
                self.passed += 1
            else:
                print_failure("public.users table missing")
                self.failed += 1

            # Check branches table
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'branches'
            """
            )
            if cur.fetchone():
                print_success("public.branches table exists")
                self.passed += 1
            else:
                print_failure("public.branches table missing")
                self.failed += 1

            # Check user_assignments table
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'user_assignments'
            """
            )
            if cur.fetchone():
                print_success("public.user_assignments table exists")
                self.passed += 1
            else:
                print_failure("public.user_assignments table missing")
                self.failed += 1

            cur.close()
            conn.close()

        except Exception as e:
            print_failure(f"Database connection error: {str(e)}")
            self.failed += 1

    def verify_rls_enabled(self):
        """Check if RLS is enabled on tables."""
        print_test("Row Level Security")

        try:
            import psycopg

            conn = psycopg.connect(
                host=os.getenv("KELAVA_HOST", "localhost"),
                port=int(os.getenv("KELAVA_PORT", 5433)),
                dbname=os.getenv("KELAVA_DB", "sanocare"),
                user=os.getenv("KELAVA_USER", "snc_read"),
                password=os.getenv("KELAVA_PASSWORD"),
            )

            cur = conn.cursor()

            # Check if RLS is enabled on users table
            cur.execute(
                """
                SELECT relname, relrowsecurity
                FROM pg_class
                WHERE relname = 'users' AND relnamespace = 'public'::regnamespace
            """
            )
            result = cur.fetchone()
            if result and result[1]:
                print_success("RLS enabled on public.users")
                self.passed += 1
            else:
                print_warning("RLS not enabled on public.users")
                print_warning("Run: psql -f kil/db/migrations/002_enable_rls.sql")
                self.warnings += 1

            cur.close()
            conn.close()

        except Exception as e:
            print_failure(f"Error checking RLS: {str(e)}")
            self.failed += 1

    def print_summary(self):
        """Print test summary."""
        total = self.passed + self.failed + self.warnings

        print(f"\n{'=' * 60}")
        print(f"{BLUE}VERIFICATION SUMMARY{RESET}")
        print(f"{'=' * 60}")
        print(f"{GREEN}Passed:{RESET}   {self.passed}/{total}")
        print(f"{RED}Failed:{RESET}   {self.failed}/{total}")
        print(f"{YELLOW}Warnings:{RESET} {self.warnings}/{total}")

        if self.failed == 0 and self.warnings == 0:
            print(f"\n{GREEN}✓ All checks passed! SAP-grade security is operational.{RESET}")
        elif self.failed == 0:
            print(f"\n{YELLOW}⚠ System functional with warnings. Review above.{RESET}")
        else:
            print(f"\n{RED}✗ Critical issues found. Fix before deploying.{RESET}")

        print(f"{'=' * 60}\n")

        return self.failed == 0


def main():
    """Run all verification tests."""
    print(f"\n{BLUE}{'=' * 60}{RESET}")
    print(f"{BLUE}SAP-GRADE SECURITY VERIFICATION{RESET}")
    print(f"{BLUE}{'=' * 60}{RESET}")

    verifier = AuthVerifier()

    # Run tests
    verifier.verify_supabase_running()
    verifier.verify_database_schema()
    verifier.verify_rls_enabled()
    verifier.verify_api_protected()

    # Print summary
    success = verifier.print_summary()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
