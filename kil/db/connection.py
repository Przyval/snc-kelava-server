import os
import sqlite3
from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row

# Project Root
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "kil" / "config" / "settings.yaml"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_db_connection():
    config = load_config()
    db_config = config["database"]

    if db_config.get("type") == "postgres":
        return get_postgres_connection(db_config)
    else:
        # Fallback to SQLite (legacy) if not specified or explicit sqlite
        path = db_config.get("kil_db", "kil/kil_analytics.db")
        return get_sqlite_connection(path)


def get_postgres_connection(config):
    conn = psycopg.connect(
        host=config["host"],
        port=config["port"],
        dbname=config["name"],
        user=config["user"],
        password=config["password"],
        row_factory=dict_row,
        autocommit=False,
    )
    return conn


def get_sqlite_connection(db_path):
    # Resolve absolute path
    if not os.path.isabs(db_path):
        real_path = PROJECT_ROOT / db_path
    else:
        real_path = db_path

    conn = sqlite3.connect(str(real_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(force: bool = False):
    config = load_config()
    db_type = config["database"].get("type", "sqlite")

    print(f"🛠 Initializing KIL Database ({db_type})...")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if db_type == "postgres":
            schema_path = PROJECT_ROOT / "kil" / "db" / "kil_schema_pg.sql"
            with open(schema_path, "r") as f:
                schema_sql = f.read()
            cursor.execute(schema_sql)
            conn.commit()
            print(f"✓ Schema applied from {schema_path.name}")

            # Seed sync_state
            streams = ["road_plan", "visit", "photo"]
            for stream in streams:
                cursor.execute(
                    """
                    INSERT INTO sync_state (stream_name, last_cursor)
                    VALUES (%s, 0)
                    ON CONFLICT (stream_name) DO NOTHING
                """,
                    (stream,),
                )
            conn.commit()
            print(f"✓ Sync streams seeded: {streams}")

        else:
            # SQLite Init logic (Preserved)
            schema_path = PROJECT_ROOT / "kil" / "db" / "kil_schema.sql"
            with open(schema_path, "r") as f:
                schema_sql = f.read()
            cursor.executescript(schema_sql)

            streams = ["road_plan", "visit", "photo"]
            for stream in streams:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO sync_state (stream_name, last_cursor)
                    VALUES (?, 0)
                """,
                    (stream,),
                )
            conn.commit()
            print(f"✓ Schema applied from {schema_path.name}")

    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        raise
    finally:
        conn.close()


def verify_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Simple check depending on DB
    # ... logic ...
    return {"status": "ok"}
