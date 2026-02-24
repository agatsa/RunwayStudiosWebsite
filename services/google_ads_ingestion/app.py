# services/google_ads_ingestion/app.py
"""
Google Ads Ingestion Service.

Scheduled by Cloud Scheduler — runs hourly via POST /cron/google/hourly.
Also supports on-demand backfill via POST /cron/google/backfill.

Responsibilities:
  1. For every active workspace that has a Google platform_connection:
     a. Fetch campaign / ad_group / keyword metrics via GAQL (GoogleConnector)
     b. Upsert to kpi_hourly (same table as Meta, same schema + Google columns)
     c. Fetch search terms → upsert google_search_terms
     d. Refresh Merchant Center product statuses → update merchant_center_products
  2. Honour CRON_TOKEN header (same shared secret as other crons)
  3. Idempotent — safe to re-run for the same window

Design note:
  We deliberately mirror the Meta ingestion service's interface so
  Cloud Scheduler can call both with identical job definitions.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone, timedelta, date
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Header, HTTPException, Request

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Google Ads Ingestion Service", version="1.0.0")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

CRON_TOKEN = os.getenv("CRON_TOKEN", "")


def _auth(x_cron_token: str = ""):
    if CRON_TOKEN and x_cron_token != CRON_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


def _get_active_google_workspaces(conn) -> list[dict]:
    """
    Return all workspaces that have an active Google platform_connection
    and a google_auth_tokens row (which carries the actual OAuth creds).
    """
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT
            w.id         AS workspace_id,
            w.name       AS workspace_name,
            w.timezone,
            w.currency,
            pc.id        AS conn_id,
            pc.account_id,
            pc.access_token,
            pc.customer_id,
            pc.merchant_id,
            pc.login_customer_id,
            gat.developer_token,
            gat.client_id,
            gat.client_secret,
            gat.refresh_token,
            gat.access_token  AS gat_access_token,
            gat.access_token_expiry,
            gat.merchant_id   AS gat_merchant_id
        FROM workspaces w
        JOIN platform_connections pc ON pc.workspace_id = w.id
            AND pc.platform = 'google'
            AND pc.is_active = TRUE
        JOIN google_auth_tokens gat ON gat.workspace_id = w.id
            AND gat.customer_id = COALESCE(pc.customer_id, gat.customer_id)
        WHERE w.is_active = TRUE
        ORDER BY w.id
        """
    )
    return [dict(r) for r in cur.fetchall()]


def _upsert_kpi_hourly(conn, rows: list[dict]):
    """Upsert a batch of MetricSnapshot dicts into kpi_hourly."""
    if not rows:
        return
    cur = conn.cursor()
    for row in rows:
        cur.execute(
            """
            INSERT INTO kpi_hourly (
                workspace_id, platform, account_id,
                entity_level, entity_id, entity_name,
                hour_ts,
                spend, impressions, clicks, conversions, revenue,
                ctr, cpm, cpc, roas,
                quality_score, search_impression_share,
                absolute_top_impression_pct, interaction_rate,
                raw_json
            ) VALUES (
                %(workspace_id)s, %(platform)s, %(account_id)s,
                %(entity_level)s, %(entity_id)s, %(entity_name)s,
                %(hour_ts)s,
                %(spend)s, %(impressions)s, %(clicks)s, %(conversions)s, %(revenue)s,
                %(ctr)s, %(cpm)s, %(cpc)s, %(roas)s,
                %(quality_score)s, %(search_impression_share)s,
                %(absolute_top_impression_pct)s, %(interaction_rate)s,
                %(raw_json)s
            )
            ON CONFLICT (workspace_id, platform, account_id, entity_level, entity_id, hour_ts)
            DO UPDATE SET
                spend       = EXCLUDED.spend,
                impressions = EXCLUDED.impressions,
                clicks      = EXCLUDED.clicks,
                conversions = EXCLUDED.conversions,
                revenue     = EXCLUDED.revenue,
                ctr         = EXCLUDED.ctr,
                cpm         = EXCLUDED.cpm,
                cpc         = EXCLUDED.cpc,
                roas        = EXCLUDED.roas,
                quality_score               = EXCLUDED.quality_score,
                search_impression_share     = EXCLUDED.search_impression_share,
                absolute_top_impression_pct = EXCLUDED.absolute_top_impression_pct,
                interaction_rate            = EXCLUDED.interaction_rate,
                raw_json    = EXCLUDED.raw_json,
                updated_at  = NOW()
            """,
            row,
        )
    conn.commit()


def _upsert_search_terms(conn, workspace_id: str, customer_id: str, terms: list[dict]):
    """Upsert search term performance rows."""
    if not terms:
        return
    cur = conn.cursor()
    for t in terms:
        cur.execute(
            """
            INSERT INTO google_search_terms (
                workspace_id, customer_id, campaign_id, ad_group_id,
                search_term, match_type, day,
                impressions, clicks, spend, conversions, revenue,
                ctr, avg_cpc, quality_score
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s
            )
            ON CONFLICT (workspace_id, customer_id, campaign_id, ad_group_id, search_term, day)
            DO UPDATE SET
                impressions  = EXCLUDED.impressions,
                clicks       = EXCLUDED.clicks,
                spend        = EXCLUDED.spend,
                conversions  = EXCLUDED.conversions,
                revenue      = EXCLUDED.revenue,
                ctr          = EXCLUDED.ctr,
                avg_cpc      = EXCLUDED.avg_cpc,
                quality_score = EXCLUDED.quality_score
            """,
            (
                workspace_id, customer_id,
                t.get("campaign_id", ""), t.get("ad_group_id", ""),
                t.get("search_term", ""), t.get("match_type"),
                t.get("day", date.today().isoformat()),
                t.get("impressions", 0), t.get("clicks", 0),
                t.get("spend", 0), t.get("conversions", 0), t.get("revenue", 0),
                t.get("ctr", 0), t.get("avg_cpc", 0), t.get("quality_score"),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Per-workspace ingestion
# ---------------------------------------------------------------------------

def _ingest_workspace(ws: dict, since: str, until: str, conn) -> dict:
    """
    Run full ingestion for one workspace.

    Returns a summary dict with counts of rows written.
    """
    from services.agent_swarm.connectors.google import GoogleConnector
    from services.agent_swarm.connectors.google_merchant import MerchantCenterConnector

    workspace_id = str(ws["workspace_id"])
    customer_id = ws.get("customer_id") or ""

    # Build the connection + workspace dicts that GoogleConnector expects
    connection = {
        "platform": "google",
        "account_id": customer_id,
        "access_token": ws.get("gat_access_token") or ws.get("access_token") or "",
        "customer_id": customer_id,
        "merchant_id": ws.get("gat_merchant_id") or ws.get("merchant_id") or "",
        "login_customer_id": ws.get("login_customer_id") or "",
        "developer_token": ws.get("developer_token", ""),
        "client_id": ws.get("client_id", ""),
        "client_secret": ws.get("client_secret", ""),
        "refresh_token": ws.get("refresh_token", ""),
        "access_token_expiry": ws.get("access_token_expiry"),
        "id": str(ws.get("conn_id", "")),
    }
    workspace_dict = {
        "id": workspace_id,
        "name": ws.get("workspace_name", ""),
        "timezone": ws.get("timezone", "Asia/Kolkata"),
        "currency": ws.get("currency", "INR"),
    }

    gc = GoogleConnector(connection, workspace_dict)
    summary = {
        "workspace_id": workspace_id,
        "workspace_name": ws.get("workspace_name"),
        "kpi_rows": 0,
        "search_term_rows": 0,
        "mc_status_refreshed": False,
        "errors": [],
    }

    # ── 1. Campaign-level KPIs ─────────────────────────────────────────
    try:
        snapshots = gc.fetch_metrics(since=since, until=until, entity_level="campaign")
        kpi_rows = []
        for s in snapshots:
            kpi_rows.append({
                "workspace_id": workspace_id,
                "platform": "google",
                "account_id": s.account_id,
                "entity_level": s.entity_level,
                "entity_id": s.entity_id,
                "entity_name": s.entity_name,
                "hour_ts": s.hour_ts,
                "spend": s.spend,
                "impressions": s.impressions,
                "clicks": s.clicks,
                "conversions": s.conversions,
                "revenue": s.revenue,
                "ctr": s.ctr,
                "cpm": s.cpm,
                "cpc": s.cpc,
                "roas": s.roas,
                "quality_score": s.raw_json.get("quality_score"),
                "search_impression_share": s.raw_json.get("search_impression_share"),
                "absolute_top_impression_pct": s.raw_json.get("absolute_top_impression_pct"),
                "interaction_rate": s.raw_json.get("interaction_rate"),
                "raw_json": json.dumps(s.raw_json),
            })
        _upsert_kpi_hourly(conn, kpi_rows)
        summary["kpi_rows"] += len(kpi_rows)
    except Exception as e:
        summary["errors"].append(f"campaign KPIs: {e}")

    # ── 2. Ad group-level KPIs ─────────────────────────────────────────
    try:
        snapshots = gc.fetch_metrics(since=since, until=until, entity_level="ad_group")
        kpi_rows = []
        for s in snapshots:
            kpi_rows.append({
                "workspace_id": workspace_id,
                "platform": "google",
                "account_id": s.account_id,
                "entity_level": s.entity_level,
                "entity_id": s.entity_id,
                "entity_name": s.entity_name,
                "hour_ts": s.hour_ts,
                "spend": s.spend,
                "impressions": s.impressions,
                "clicks": s.clicks,
                "conversions": s.conversions,
                "revenue": s.revenue,
                "ctr": s.ctr,
                "cpm": s.cpm,
                "cpc": s.cpc,
                "roas": s.roas,
                "quality_score": None,
                "search_impression_share": None,
                "absolute_top_impression_pct": None,
                "interaction_rate": None,
                "raw_json": json.dumps(s.raw_json),
            })
        _upsert_kpi_hourly(conn, kpi_rows)
        summary["kpi_rows"] += len(kpi_rows)
    except Exception as e:
        summary["errors"].append(f"ad_group KPIs: {e}")

    # ── 3. Search terms ────────────────────────────────────────────────
    try:
        terms = gc.fetch_search_terms(since=since, until=until)
        _upsert_search_terms(conn, workspace_id, customer_id, terms)
        summary["search_term_rows"] = len(terms)
    except Exception as e:
        summary["errors"].append(f"search terms: {e}")

    # ── 4. Merchant Center status refresh ─────────────────────────────
    merchant_id = ws.get("gat_merchant_id") or ws.get("merchant_id") or ""
    if merchant_id:
        try:
            mc = MerchantCenterConnector(gc)
            result = mc.refresh_product_statuses(workspace_id, db_conn=conn)
            summary["mc_status_refreshed"] = True
            summary["mc_approved"] = result.get("approved", 0)
            summary["mc_disapproved"] = result.get("disapproved", 0)
        except Exception as e:
            summary["errors"].append(f"MC status refresh: {e}")

    return summary


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "service": "google_ads_ingestion"}


@app.post("/cron/google/hourly")
def hourly_ingest(x_cron_token: str = Header(default="")):
    """
    Hourly ingestion for all active Google workspaces.
    Fetches yesterday + today (2-day window) to catch any late-arriving data.
    """
    _auth(x_cron_token)

    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=1)).isoformat()
    until = today.isoformat()

    return _run_ingestion(since=since, until=until)


@app.post("/cron/google/backfill")
def backfill_ingest(
    request_body: dict,
    x_cron_token: str = Header(default=""),
):
    """
    On-demand backfill for a custom date range.

    Body: { "since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "workspace_id": "optional-uuid" }
    """
    _auth(x_cron_token)

    since = request_body.get("since")
    until = request_body.get("until")
    workspace_id = request_body.get("workspace_id")

    if not since or not until:
        raise HTTPException(status_code=400, detail="since and until are required")

    return _run_ingestion(since=since, until=until, only_workspace_id=workspace_id)


@app.post("/merchant/sync")
def merchant_sync(
    request_body: dict,
    x_cron_token: str = Header(default=""),
):
    """
    Push all active workspace products to Merchant Center.
    Can be called via Cloud Scheduler daily or on-demand.

    Body: { "workspace_id": "optional — runs all if omitted" }
    """
    _auth(x_cron_token)

    workspace_id = request_body.get("workspace_id")
    return _run_merchant_sync(only_workspace_id=workspace_id)


@app.post("/merchant/refresh-statuses")
def merchant_refresh_statuses(
    request_body: dict = None,
    x_cron_token: str = Header(default=""),
):
    """
    Pull current approval statuses from Merchant Center and write back to DB.
    Run ~1 hour after a sync to pick up MC review results.
    """
    _auth(x_cron_token)
    workspace_id = (request_body or {}).get("workspace_id")
    return _run_status_refresh(only_workspace_id=workspace_id)


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------

def _run_ingestion(since: str, until: str, only_workspace_id: str = None) -> dict:
    conn = _get_conn()
    try:
        workspaces = _get_active_google_workspaces(conn)
        if only_workspace_id:
            workspaces = [w for w in workspaces if str(w["workspace_id"]) == only_workspace_id]

        results = []
        total_kpi = 0
        total_terms = 0
        errors = []

        for ws in workspaces:
            try:
                summary = _ingest_workspace(ws, since=since, until=until, conn=conn)
                total_kpi += summary.get("kpi_rows", 0)
                total_terms += summary.get("search_term_rows", 0)
                if summary.get("errors"):
                    errors.extend([
                        f"{summary['workspace_name']}: {e}"
                        for e in summary["errors"]
                    ])
                results.append(summary)
            except Exception as e:
                errors.append(f"workspace {ws.get('workspace_name')}: {e}")

        return {
            "status": "ok" if not errors else "partial",
            "since": since,
            "until": until,
            "workspaces_processed": len(workspaces),
            "total_kpi_rows": total_kpi,
            "total_search_term_rows": total_terms,
            "errors": errors,
            "details": results,
        }
    finally:
        conn.close()


def _run_merchant_sync(only_workspace_id: str = None) -> dict:
    from services.agent_swarm.connectors.google import GoogleConnector
    from services.agent_swarm.connectors.google_merchant import MerchantCenterConnector

    conn = _get_conn()
    try:
        workspaces = _get_active_google_workspaces(conn)
        if only_workspace_id:
            workspaces = [w for w in workspaces if str(w["workspace_id"]) == only_workspace_id]

        results = []
        errors = []

        for ws in workspaces:
            merchant_id = ws.get("gat_merchant_id") or ws.get("merchant_id") or ""
            if not merchant_id:
                continue

            workspace_id = str(ws["workspace_id"])
            connection = _build_connection_dict(ws)
            workspace_dict = _build_workspace_dict(ws)

            try:
                gc = GoogleConnector(connection, workspace_dict)
                mc = MerchantCenterConnector(gc)
                result = mc.sync_workspace_products(workspace_id, db_conn=conn)
                result["workspace_name"] = ws.get("workspace_name")
                results.append(result)
                if result.get("errors"):
                    errors.append(f"{ws.get('workspace_name')}: {result['errors']} errors")
            except Exception as e:
                errors.append(f"{ws.get('workspace_name')}: {e}")

        return {
            "status": "ok" if not errors else "partial",
            "workspaces_synced": len(results),
            "errors": errors,
            "details": results,
        }
    finally:
        conn.close()


def _run_status_refresh(only_workspace_id: str = None) -> dict:
    from services.agent_swarm.connectors.google import GoogleConnector
    from services.agent_swarm.connectors.google_merchant import MerchantCenterConnector

    conn = _get_conn()
    try:
        workspaces = _get_active_google_workspaces(conn)
        if only_workspace_id:
            workspaces = [w for w in workspaces if str(w["workspace_id"]) == only_workspace_id]

        total_updated = approved = disapproved = 0
        errors = []

        for ws in workspaces:
            merchant_id = ws.get("gat_merchant_id") or ws.get("merchant_id") or ""
            if not merchant_id:
                continue

            workspace_id = str(ws["workspace_id"])
            connection = _build_connection_dict(ws)
            workspace_dict = _build_workspace_dict(ws)

            try:
                gc = GoogleConnector(connection, workspace_dict)
                mc = MerchantCenterConnector(gc)
                result = mc.refresh_product_statuses(workspace_id, db_conn=conn)
                total_updated += result.get("updated", 0)
                approved += result.get("approved", 0)
                disapproved += result.get("disapproved", 0)
            except Exception as e:
                errors.append(f"{ws.get('workspace_name')}: {e}")

        return {
            "status": "ok" if not errors else "partial",
            "total_updated": total_updated,
            "approved": approved,
            "disapproved": disapproved,
            "errors": errors,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_connection_dict(ws: dict) -> dict:
    return {
        "platform": "google",
        "account_id": ws.get("customer_id", ""),
        "access_token": ws.get("gat_access_token") or ws.get("access_token") or "",
        "customer_id": ws.get("customer_id", ""),
        "merchant_id": ws.get("gat_merchant_id") or ws.get("merchant_id") or "",
        "login_customer_id": ws.get("login_customer_id") or "",
        "developer_token": ws.get("developer_token", ""),
        "client_id": ws.get("client_id", ""),
        "client_secret": ws.get("client_secret", ""),
        "refresh_token": ws.get("refresh_token", ""),
        "access_token_expiry": ws.get("access_token_expiry"),
        "id": str(ws.get("conn_id", "")),
    }


def _build_workspace_dict(ws: dict) -> dict:
    return {
        "id": str(ws["workspace_id"]),
        "name": ws.get("workspace_name", ""),
        "timezone": ws.get("timezone", "Asia/Kolkata"),
        "currency": ws.get("currency", "INR"),
    }
