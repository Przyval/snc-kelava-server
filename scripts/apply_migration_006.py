"""
Apply Migration 006: Complaint SLA + Accurate Export Log
=========================================================
Run: python scripts/apply_migration_006.py [--dry-run]
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    dry_run = "--dry-run" in sys.argv

    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "kil", "db", "migrations", "006_sla_accurate.sql",
    )

    with open(migration_path) as f:
        sql = f.read()

    # The migration contains a DO $$ block and two standalone DDL statements.
    # We split on ";" but must reassemble the DO $$ ... END $$; block intact
    # because it contains internal semicolons.
    # Strategy: detect the DO $$ block as one chunk, then split the rest normally.

    statements = _split_statements(sql)

    if dry_run:
        print("=== DRY RUN - Migration 006 ===")
        for i, stmt in enumerate(statements, 1):
            preview = stmt[:200] + "..." if len(stmt) > 200 else stmt
            print(f"\n-- Statement {i}:")
            print(preview)
        print(f"\nTotal: {len(statements)} statements")
        return

    from kil.db.kelava_db import execute_kelava_query

    print("=== Applying Migration 006: Complaint SLA + Accurate Export Log ===")

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

    print("\nMigration 006 applied successfully!")


def _split_statements(sql: str) -> list:
    """
    Split SQL into executable statements, keeping DO $$ ... END $$; intact.
    Strips comment-only leading lines from each statement.
    """
    statements = []
    current = []
    inside_dollar_block = False

    for line in sql.splitlines():
        stripped = line.strip()

        # Track entry/exit of dollar-quoted blocks (DO $$ ... END $$)
        if not inside_dollar_block and stripped.upper().startswith("DO $$"):
            inside_dollar_block = True
            current.append(line)
            continue

        if inside_dollar_block:
            current.append(line)
            # End of block: line is "END $$;" or "END $$" (with optional trailing ;)
            if stripped.upper().startswith("END $$"):
                inside_dollar_block = False
                block = "\n".join(current).strip()
                if block:
                    statements.append(_strip_leading_comments(block))
                current = []
            continue

        # Normal line: accumulate until ";"
        current.append(line)
        if ";" in stripped:
            chunk = "\n".join(current).strip()
            if chunk:
                cleaned = _strip_leading_comments(chunk)
                if cleaned:
                    statements.append(cleaned)
            current = []

    # Flush any remaining content
    if current:
        chunk = "\n".join(current).strip()
        if chunk:
            cleaned = _strip_leading_comments(chunk)
            if cleaned:
                statements.append(cleaned)

    return statements


def _strip_leading_comments(stmt: str) -> str:
    """Remove leading comment/blank lines, return first real SQL onward."""
    lines = stmt.split("\n")
    sql_lines = []
    found_sql = False
    for line in lines:
        if not found_sql and line.strip().startswith("--"):
            continue
        if not found_sql and not line.strip():
            continue
        found_sql = True
        sql_lines.append(line)
    return "\n".join(sql_lines).strip()


if __name__ == "__main__":
    main()
