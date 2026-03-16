"""
Pipeline Database Queries
=========================
SQLite queries for the sales pipeline CRM data.
Uses kil/kil_analytics.db.
"""

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "kil" / "kil_analytics.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def execute_pipeline_query(sql: str, params: tuple | None = None) -> list[dict]:
    """Execute a query and return list of dicts."""
    conn = _get_conn()
    try:
        cursor = conn.execute(sql, params or ())
        if cursor.description:
            return [dict(row) for row in cursor.fetchall()]
        return []
    finally:
        conn.close()


def execute_pipeline_query_single(sql: str, params: tuple | None = None) -> dict | None:
    """Execute a query expecting a single row."""
    rows = execute_pipeline_query(sql, params)
    return rows[0] if rows else None
