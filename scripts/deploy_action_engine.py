import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kil.db.kelava_db import execute_kelava_query


def deploy_views():
    sql_path = os.path.join(
        os.path.dirname(__file__), "../kil/backend/db/schema/action_engine_v1.sql"
    )

    print(f"Reading SQL from {sql_path}...")
    with open(sql_path, "r") as f:
        sql_content = f.read()

    # Split by semicolon, but be careful (basic split for now)
    # The views are defined with CREATE OR REPLACE VIEW, so they should be safe to run individually
    statements = sql_content.split(";")

    for statement in statements:
        stmt = statement.strip()
        if stmt:
            print(f"Executing statement starting with: {stmt[:50]}...")
            try:
                execute_kelava_query(stmt)
                print("Success.")
            except Exception as e:
                print(f"Error executing statement: {e}")
                # We continue, as some might fail if dependent views don't exist yet (though order should be correct)


if __name__ == "__main__":
    deploy_views()
