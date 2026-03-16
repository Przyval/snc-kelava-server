import getpass
import os
import sys

from sqlalchemy import create_engine, text

# Add parent dir to path to find config
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
from kil.backend.core.config import settings


def apply_migration():
    print("Locked & Loaded: Migration 002 (RLS & Audit)")
    print("============================================")

    # 1. Determine Credentials
    db_url = settings.DATABASE_URL
    print(f"Current DB URL: {db_url}")

    if "snc_read" in db_url:
        print(
            "\n[WARNING] Detected read-only user 'snc_read'. Migration will likely FAIL."
        )
        print("Please provide Admin credentials (or press Enter to try anyway).")

        user = input("Admin User (e.g. postgres/admin): ")
        if user:
            pwd = getpass.getpass("Admin Password: ")
            host = input("Host (default: localhost): ") or "localhost"
            port = input("Port (default: 5433): ") or "5433"
            dbname = input("Database (default: sanocare): ") or "sanocare"

            # Construct new URL
            # handle special chars in password if needed, but simple string valid here for now
            db_url = f"postgresql://{user}:{pwd}@{host}:{port}/{dbname}"

    # 2. Connect
    try:
        engine = create_engine(db_url)
        conn = engine.connect()
        print("\n[SUCCESS] Connected to database.")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        return

    # 3. Read SQL
    migration_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "kil/db/migrations/002_rls_and_audit.sql",
    )

    with open(migration_file, "r") as f:
        sql = f.read()

    # 4. Execute
    print(f"Applying {migration_file}...")
    try:
        # Split by statements? Or execute all?
        # SQLAlchemy execute(text()) might not handle multiple statements well in one go
        # unless autocommit is handled.
        # But for DDL it usually works if the driver supports it. psycopg2 does.
        # We need independent transaction.

        with conn.begin():
            conn.execute(text(sql))

        print(
            "[SUCCESS] Migration applied successfully! RLS and Audit Logs are active."
        )

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        # print(sql) # Debug
    finally:
        conn.close()


if __name__ == "__main__":
    apply_migration()
