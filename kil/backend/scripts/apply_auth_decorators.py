#!/usr/bin/env python3
"""
Script to apply @require_auth decorator to all API route files.
This ensures SAP-grade security by protecting all endpoints.
"""

import re
from pathlib import Path

# API files to protect
API_FILES = [
    "kil/backend/legacy/api/ops.py",
    "kil/backend/legacy/api/operations_kelava.py",
    "kil/backend/legacy/api/exceptions.py",
    "kil/backend/legacy/api/invoice_lock.py",
    "kil/backend/legacy/api/completion_gate.py",
    "kil/backend/legacy/api/technicians.py",
    "kil/backend/legacy/api/technician_issues.py",
    "kil/backend/legacy/api/governance.py",
    "kil/backend/legacy/api/tracking.py",
    "kil/backend/legacy/api/calendar.py",
    "kil/backend/legacy/api/customers.py",
]


def apply_auth_decorator(file_path: Path):
    """Apply @require_auth decorator to all routes in a file."""
    print(f"Processing: {file_path}")

    with open(file_path, "r") as f:
        content = f.read()

    # Check if already has the import
    if "from core.security import require_auth" in content:
        print(f"  ✓ Already has import, skipping")
        return False

    # Add import after other imports
    import_pattern = r"(from flask import .*\n)"
    import_replacement = r"\1from core.security import require_auth\n"
    content = re.sub(import_pattern, import_replacement, content)

    # Find all route decorators and add @require_auth after them
    # Pattern: @blueprint.route(...)\ndef function_name
    route_pattern = r"(@[a-z_]+_bp\.route\([^\)]+\))\n(def [a-z_]+)"

    def add_decorator(match):
        route_decorator = match.group(1)
        function_def = match.group(2)
        # Check if @require_auth is already there
        if "@require_auth" in route_decorator:
            return match.group(0)
        return f"{route_decorator}\n@require_auth\n{function_def}"

    new_content = re.sub(route_pattern, add_decorator, content)

    # Count how many routes we protected
    routes_protected = new_content.count("@require_auth")

    if routes_protected > 0:
        with open(file_path, "w") as f:
            f.write(new_content)
        print(f"  ✓ Protected {routes_protected} routes")
        return True
    else:
        print(f"  ⚠ No routes found to protect")
        return False


def main():
    """Apply auth decorators to all API files."""
    base_path = Path(__file__).parent.parent.parent.parent
    print(f"Base path: {base_path}\n")

    protected_count = 0
    for api_file in API_FILES:
        file_path = base_path / api_file
        if not file_path.exists():
            print(f"⚠ File not found: {file_path}")
            continue

        if apply_auth_decorator(file_path):
            protected_count += 1

    print(f"\n✅ Protected routes in {protected_count}/{len(API_FILES)} files")
    print(
        "\nNext steps:"
    )
    print("1. Review changes: git diff kil/backend/legacy/api/")
    print("2. Run migrations: psql -f kil/db/migrations/001_auth_schema.sql")
    print("3. Start Supabase: docker-compose -f docker-compose.supabase.yml up -d")
    print("4. Test endpoints with authentication")


if __name__ == "__main__":
    main()
