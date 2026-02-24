# services/ingestion_service/storage/postgres.py
import json
import os
import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional

# -----------------------------------------
# Connection / Pool (Cloud Run safe)
# -----------------------------------------

_POOL: SimpleConnectionPool | None = None


def _get_dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return dsn


def _get_pool() -> SimpleConnectionPool:
    """
    Create a small connection pool per Cloud Run container.
    Cloud Run can scale horizontally, so keep this conservative.
    """
    global _POOL
    if _POOL is None:
        dsn = _get_dsn()

        # These env vars are optional; defaults are Cloud Run-safe.
        maxconn = int(os.getenv("PG_POOL_MAX", "3"))
        connect_timeout = int(os.getenv("PG_CONNECT_TIMEOUT", "10"))
        keepalives_idle = int(os.getenv("PG_KEEPALIVES_IDLE", "30"))
        keepalives_interval = int(os.getenv("PG_KEEPALIVES_INTERVAL", "10"))
        keepalives_count = int(os.getenv("PG_KEEPALIVES_COUNT", "5"))
        app_name = os.getenv("PG_APP_NAME", "ingestion-service")

        _POOL = SimpleConnectionPool(
            minconn=1,
            maxconn=maxconn,
            dsn=dsn,
            connect_timeout=connect_timeout,
            keepalives=1,
            keepalives_idle=keepalives_idle,
            keepalives_interval=keepalives_interval,
            keepalives_count=keepalives_count,
            application_name=app_name,
        )
    return _POOL


@contextmanager
def get_conn():
    """
    Context-managed connection that:
    - gets a pooled connection
    - commits on success
    - rollbacks on error
    - returns connection back to pool
    """
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


# -----------------------------------------
# Sync State
# -----------------------------------------

def ensure_sync_state(platform: str, account_id: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_state(platform, account_id, last_success_end)
                VALUES (%s, %s, NULL)
                ON CONFLICT (platform, account_id) DO NOTHING
                """,
                (platform, account_id),
            )


def get_last_success_end(platform: str, account_id: str) -> Optional[datetime]:
    ensure_sync_state(platform, account_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_success_end FROM sync_state WHERE platform=%s AND account_id=%s",
                (platform, account_id),
            )
            row = cur.fetchone()
            return row[0] if row else None


def update_last_success_end(platform: str, account_id: str, last_success_end: datetime):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sync_state
                SET last_success_end=%s, updated_at=NOW()
                WHERE platform=%s AND account_id=%s
                """,
                (last_success_end, platform, account_id),
            )


# -----------------------------------------
# Sync Runs
# -----------------------------------------

def create_sync_run(
    platform: str,
    account_id: str,
    request_id: str,
    window_start: datetime,
    window_end: datetime,
) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sync_runs(platform, account_id, request_id, window_start, window_end, status)
                VALUES (%s, %s, %s, %s, %s, 'running')
                RETURNING id
                """,
                (platform, account_id, request_id, window_start, window_end),
            )
            return str(cur.fetchone()[0])


def mark_sync_run_success(run_id: str, raw_gcs_path: str, stats: Dict[str, Any]):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sync_runs
                SET status='success',
                    finished_at=NOW(),
                    raw_gcs_path=%s,
                    stats=%s
                WHERE id=%s
                """,
                (raw_gcs_path, json.dumps(stats), run_id),
            )


def mark_sync_run_failed(run_id: str, error: str, stats: Dict[str, Any] | None = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sync_runs
                SET status='failed',
                    finished_at=NOW(),
                    error=%s,
                    stats=%s
                WHERE id=%s
                """,
                (error, json.dumps(stats or {}), run_id),
            )


# -----------------------------------------
# Upserts
# -----------------------------------------

def upsert_entities_snapshot(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO entities_snapshot(platform, entity_level, entity_id, account_id, name, status, raw_json)
                VALUES %s
                ON CONFLICT (platform, entity_level, entity_id)
                DO UPDATE SET
                  account_id=EXCLUDED.account_id,
                  name=EXCLUDED.name,
                  status=EXCLUDED.status,
                  raw_json=EXCLUDED.raw_json,
                  updated_at=NOW()
                """,
                [
                    (
                        r["platform"],
                        r["entity_level"],
                        r["entity_id"],
                        r["account_id"],
                        r.get("name"),
                        r.get("status"),
                        json.dumps(r.get("raw_json") or {}),
                    )
                    for r in rows
                ],
            )


def upsert_kpi_hourly(rows: list[dict]):
    if not rows:
        return
    
    uniq = {}
    for r in rows:
        k = (r["platform"], r["account_id"], r["entity_level"], r["entity_id"], r["hour_ts"])
        uniq[k] = r
    rows = list(uniq.values())

    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO kpi_hourly(
                  platform, account_id, entity_level, entity_id, hour_ts,
                  spend, impressions, clicks, ctr, cpm, cpc, conversions, revenue, roas,
                  raw_json
                )
                VALUES %s
                ON CONFLICT (platform, account_id, entity_level, entity_id, hour_ts)
                DO UPDATE SET
                  spend=EXCLUDED.spend,
                  impressions=EXCLUDED.impressions,
                  clicks=EXCLUDED.clicks,
                  ctr=EXCLUDED.ctr,
                  cpm=EXCLUDED.cpm,
                  cpc=EXCLUDED.cpc,
                  conversions=EXCLUDED.conversions,
                  revenue=EXCLUDED.revenue,
                  roas=EXCLUDED.roas,
                  raw_json=EXCLUDED.raw_json,
                  updated_at=NOW()
                """,
                [
                    (
                        r["platform"],
                        r["account_id"],
                        r["entity_level"],
                        r["entity_id"],
                        r["hour_ts"],
                        r.get("spend"),
                        r.get("impressions"),
                        r.get("clicks"),
                        r.get("ctr"),
                        r.get("cpm"),
                        r.get("cpc"),
                        r.get("conversions"),
                        r.get("revenue"),
                        r.get("roas"),
                        json.dumps(r.get("raw_json") or {}),
                    )
                    for r in rows
                ],
            )

def upsert_daily_kpis(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO daily_kpis(
                  platform, account_id, entity_level, entity_id, day,
                  spend, impressions, clicks, conversions, revenue, roas, ctr, cpm, cpc
                )
                VALUES %s
                ON CONFLICT (platform, account_id, entity_level, entity_id, day)
                DO UPDATE SET
                  spend=EXCLUDED.spend,
                  impressions=EXCLUDED.impressions,
                  clicks=EXCLUDED.clicks,
                  conversions=EXCLUDED.conversions,
                  revenue=EXCLUDED.revenue,
                  roas=EXCLUDED.roas,
                  ctr=EXCLUDED.ctr,
                  cpm=EXCLUDED.cpm,
                  cpc=EXCLUDED.cpc,
                  updated_at=NOW()
                """,
                [
                    (
                        r["platform"],
                        r["account_id"],
                        r.get("entity_level", "account"),
                        r.get("entity_id", "account"),
                        r["day"],
                        r.get("spend"),
                        r.get("impressions"),
                        r.get("clicks"),
                        r.get("conversions"),
                        r.get("revenue"),
                        r.get("roas"),
                        r.get("ctr"),
                        r.get("cpm"),
                        r.get("cpc"),
                    )
                    for r in rows
                ],
            )


def insert_alerts(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO alerts(
                  platform, account_id, entity_level, entity_id, ts,
                  alert_type, severity, summary, details
                )
                VALUES %s
                """,
                [
                    (
                        r["platform"],
                        r["account_id"],
                        r["entity_level"],
                        r["entity_id"],
                        r["ts"],
                        r["alert_type"],
                        r["severity"],
                        r["summary"],
                        json.dumps(r.get("details") or {}),
                    )
                    for r in rows
                ],
            )