"""
Gunicorn configuration for KIL Enterprise API
===============================================
"""

import logging

workers = 3
bind = "0.0.0.0:5002"
timeout = 120
worker_class = "sync"
accesslog = "/root/kil-server/access.log"
errorlog = "/root/kil-server/error.log"
loglevel = "info"

log = logging.getLogger(__name__)


def post_fork(server, worker):
    """
    Pre-warm Kelava DB connection pool in each worker after fork.
    This prevents the circuit breaker from tripping on the very first request
    (which would cause 30s of degraded service on fresh deploys).
    """
    import sys

    sys.path.insert(0, "/root/kil-server")
    sys.path.insert(0, "/root/kil-server/kil/backend")

    try:
        from kil.db.kelava_db import _get_pool, _mark_kelava_success

        pool = _get_pool()
        # Try to establish a connection, verify it works
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        _mark_kelava_success()
        server.log.info(f"[worker {worker.pid}] Kelava pool pre-warmed")
    except Exception as e:
        server.log.warning(
            f"[worker {worker.pid}] Kelava pool pre-warm failed (non-fatal): {e}"
        )
        # Don't crash the worker — it will retry on first request
