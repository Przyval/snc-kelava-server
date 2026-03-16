"""
Apply Migration 005: Koordinator Role & Approval Workflow
=========================================================
Run: python scripts/apply_migration_005.py [--dry-run]
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    dry_run = "--dry-run" in sys.argv

    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "kil", "db", "migrations", "005_koordinator_role.sql",
    )

    with open(migration_path) as f:
        sql = f.read()

    # Split into individual statements, stripping leading comment lines from each
    raw_parts = [s.strip() for s in sql.split(";") if s.strip()]
    statements = []
    for part in raw_parts:
        # Strip leading comment lines to get to the actual SQL
        lines = part.split("\n")
        sql_lines = []
        found_sql = False
        for line in lines:
            if not found_sql and line.strip().startswith("--"):
                continue
            if not found_sql and not line.strip():
                continue
            found_sql = True
            sql_lines.append(line)
        cleaned = "\n".join(sql_lines).strip()
        if cleaned:
            statements.append(cleaned)

    if dry_run:
        print("=== DRY RUN - Migration 005 ===")
        for i, stmt in enumerate(statements, 1):
            print(f"\n-- Statement {i}:")
            print(stmt[:200] + "..." if len(stmt) > 200 else stmt)
        print(f"\nTotal: {len(statements)} statements")
        return

    from kil.db.kelava_db import execute_kelava_query

    print("=== Applying Migration 005: Koordinator Role ===")

    for i, stmt in enumerate(statements, 1):
        try:
            execute_kelava_query(stmt)
            desc = stmt[:80].replace("\n", " ")
            print(f"  [{i}] OK: {desc}...")
        except Exception as e:
            err_str = str(e)
            if "already exists" in err_str or "duplicate" in err_str.lower():
                print(f"  [{i}] SKIP (already exists)")
            else:
                print(f"  [{i}] ERROR: {e}")
                raise

    print("\nMigration 005 applied successfully!")


if __name__ == "__main__":
    main()
