"""
Kelava Live Database Connection
================================
Connection-pooled access to the live SanoCare/Kelava PostgreSQL database.
Includes a lightweight TTL cache for read-heavy dashboard queries.

Auto-routing: queries touching enterprise_* tables are transparently
routed to the local PostgreSQL instance, eliminating the dependency on
Kelava for authentication and user management.
"""

import hashlib
import logging
import os
import re
import threading
import time
from pathlib import Path

import psycopg

from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Load environment variables
PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger(__name__)

# ── Kelava Connection Pool ───────────────────────────────────

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _conninfo() -> str:
    host = os.getenv("KELAVA_HOST", "localhost")
    port = os.getenv("KELAVA_PORT", "5433")
    database = os.getenv("KELAVA_DB", "sanocare")
    user = os.getenv("KELAVA_USER", "snc_read")
    password = os.getenv("KELAVA_PASSWORD", "")
    return (
        f"host={host} port={port} dbname={database} "
        f"user={user} password={password} "
        f"options='-c statement_timeout=30000'"
    )


def _get_pool() -> ConnectionPool:
    """Get or create the Kelava connection pool (lazy singleton)."""
    global _pool  # noqa: PLW0603
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        _pool = ConnectionPool(
            conninfo=_conninfo(),
            min_size=2,
            max_size=8,
            kwargs={"row_factory": dict_row, "autocommit": True},
            timeout=10,
            reconnect_timeout=60,
        )
        return _pool


def get_kelava_connection():
    """Get a connection from the Kelava pool (context-manager aware)."""
    return _get_pool().connection()


# ── Local Enterprise DB Pool ─────────────────────────────────
# enterprise_* tables live here — no dependency on Kelava connectivity.

_local_pool: ConnectionPool | None = None
_local_pool_lock = threading.Lock()

# Route ALL enterprise_* tables to local DB (none of them exist in Kelava)
_ENTERPRISE_TABLES = re.compile(r"\benterprise_\w+", re.IGNORECASE)


def _local_conninfo() -> str:
    host = os.getenv("LOCAL_ENT_HOST", "127.0.0.1")
    port = os.getenv("LOCAL_ENT_PORT", "5432")
    database = os.getenv("LOCAL_ENT_DB", "kil_enterprise")
    user = os.getenv("LOCAL_ENT_USER", "kil_ent")
    password = os.getenv("LOCAL_ENT_PASSWORD", "KilEnt2026!")
    return (
        f"host={host} port={port} dbname={database} "
        f"user={user} password={password} "
        f"options='-c statement_timeout=15000'"
    )


def _get_local_pool() -> ConnectionPool:
    """Get or create the local enterprise DB pool (lazy singleton)."""
    global _local_pool  # noqa: PLW0603
    if _local_pool is not None:
        return _local_pool
    with _local_pool_lock:
        if _local_pool is not None:
            return _local_pool
        _local_pool = ConnectionPool(
            conninfo=_local_conninfo(),
            min_size=2,
            max_size=6,
            kwargs={"row_factory": dict_row, "autocommit": True},
            timeout=5,
        )
        return _local_pool


def _is_enterprise_query(sql: str) -> bool:
    """Return True if this SQL touches enterprise_* tables (routes to local DB)."""
    return bool(_ENTERPRISE_TABLES.search(sql))


# ── Kelava Circuit Breaker ───────────────────────────────────
# Tracks Kelava DB health — avoids 3s timeout storms when DB is known down.

_kelava_cb = {"last_failure": 0.0}
_kelava_failure_lock = threading.Lock()
_KELAVA_COOLDOWN = 30.0  # Skip Kelava queries for 30s after a failure


def kelava_is_reachable() -> bool:
    """Return False quickly if Kelava failed recently (circuit breaker)."""
    with _kelava_failure_lock:
        return (time.time() - _kelava_cb["last_failure"]) > _KELAVA_COOLDOWN


def _mark_kelava_failure():
    with _kelava_failure_lock:
        _kelava_cb["last_failure"] = time.time()


def _mark_kelava_success():
    with _kelava_failure_lock:
        _kelava_cb["last_failure"] = 0.0


def reset_circuit_breaker():
    """Manually reset circuit breaker (e.g. after Kelava DB comes back online)."""
    _mark_kelava_success()


# ── TTL Cache ───────────────────────────────────────────────

_cache: dict[str, tuple[float, list]] = {}
_cache_lock = threading.Lock()

# Default 60s TTL — dashboard data doesn't change every second
DEFAULT_CACHE_TTL = 60


def _cache_key(sql: str, params: tuple | None) -> str:
    raw = sql + repr(params)
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_get(key: str) -> list | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[0] < DEFAULT_CACHE_TTL:
            return entry[1]
        if entry:
            del _cache[key]
    return None


def _cache_set(key: str, rows: list):
    with _cache_lock:
        # Evict stale entries when cache grows
        _MAX_CACHE_ENTRIES = 200
        if len(_cache) > _MAX_CACHE_ENTRIES:
            now = time.time()
            stale = [k for k, (t, _) in _cache.items() if now - t > DEFAULT_CACHE_TTL]
            for k in stale:
                del _cache[k]
        _cache[key] = (time.time(), rows)


# ── Query Functions ─────────────────────────────────────────


def _set_rls_context(cur, user_id: str, role: str = "authenticated"):
    """Set RLS context on the current connection using set_config()."""
    try:
        cur.execute(
            "SELECT set_config('request.jwt.claim.sub', %s, true)",
            [str(user_id)],
        )
        cur.execute(
            "SELECT set_config('request.jwt.claim.role', %s, true)",
            [role],
        )
    except Exception:
        pass


def execute_kelava_query(
    sql: str,
    params: tuple | None = None,
    user_id: str | None = None,
    cache_ttl: int | None = None,
) -> list:
    """
    Execute a query against Kelava database using the connection pool.
    Queries touching enterprise_* tables are auto-routed to the local DB.

    Args:
        sql: SQL query string
        params: Optional query parameters
        user_id: Optional auth user ID for RLS context (Kelava only)
        cache_ttl: Cache TTL in seconds. None = use default (60s for SELECT).
                   Set to 0 to bypass cache (for writes).
    """
    # Auto-route enterprise_* table queries to local DB
    if _is_enterprise_query(sql):
        return _execute_local(sql, params)

    # Circuit breaker: fast-fail if Kelava was recently unreachable
    if not kelava_is_reachable():
        raise Exception("Kelava DB unreachable (circuit breaker open)")

    is_read = sql.strip().upper().startswith("SELECT")

    # Check cache for reads
    if is_read and cache_ttl != 0:
        key = _cache_key(sql, params)
        cached = _cache_get(key)
        if cached is not None:
            return cached

    try:
        with _get_pool().connection() as conn:
            with conn.cursor() as cur:
                if user_id:
                    _set_rls_context(cur, user_id)
                cur.execute(sql, params)
                if cur.description:
                    rows = cur.fetchall()
                else:
                    rows = []
        _mark_kelava_success()
    except psycopg.OperationalError:
        # Connection-level failure (timeout, network, auth) → open circuit breaker
        _mark_kelava_failure()
        raise
    except Exception:
        # SQL-level failure (bad query, missing table, permission denied) →
        # Kelava IS reachable, do NOT open circuit breaker
        raise

    # Cache reads
    if is_read and cache_ttl != 0 and rows is not None:
        _cache_set(_cache_key(sql, params), rows)

    return rows


def _execute_local(sql: str, params: tuple | None = None) -> list:
    """Execute a query against the local enterprise PostgreSQL."""
    with _get_local_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                return cur.fetchall()
            return []


def execute_kelava_query_single(
    sql: str,
    params: tuple | None = None,
    user_id: str | None = None,
    cache_ttl: int | None = None,
) -> dict | None:
    """Execute a query expecting a single row result."""
    rows = execute_kelava_query(sql, params, user_id=user_id, cache_ttl=cache_ttl)
    return rows[0] if rows else None


def test_connection() -> dict:
    """Test the database connection and return status."""
    try:
        with _get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT NOW() as server_time, "
                    "current_database() as db_name"
                )
                result = cur.fetchone()
                cur.execute(
                    "SELECT COUNT(*) as table_count "
                    "FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                tables = cur.fetchone()

        return {
            "status": "connected",
            "server_time": str(result["server_time"]),
            "database": result["db_name"],
            "table_count": tables["table_count"],
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "hint": (
                "Ensure SSH tunnel is running: "
                "ssh -N -L 5433:app.kelava.id:5432 "
                "root@104.194.154.108"
            ),
        }


if __name__ == "__main__":
    print("Testing Kelava connection...")
    result = test_connection()
    print(result)
