# services/agent_swarm/db.py
import json
import os
import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from typing import Any

_POOL: SimpleConnectionPool | None = None


def _get_pool() -> SimpleConnectionPool:
    global _POOL
    if _POOL is None:
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set")
        _POOL = SimpleConnectionPool(
            minconn=1,
            maxconn=int(os.getenv("PG_POOL_MAX", "3")),
            dsn=dsn,
            connect_timeout=int(os.getenv("PG_CONNECT_TIMEOUT", "10")),
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
            application_name="agent-swarm",
        )
    return _POOL


@contextmanager
def get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def fetchall_dict(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetchone_dict(cur) -> dict | None:
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None
