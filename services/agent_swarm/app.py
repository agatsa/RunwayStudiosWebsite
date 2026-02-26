# services/agent_swarm/app.py
"""
Agent Swarm FastAPI service — multi-tenant edition.
All endpoints accept an optional phone_number_id in the request body
to route to the correct client account. Falls back to env-var defaults
for backward compatibility.
"""
import os
import time
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from services.agent_swarm.config import (
    CRON_TOKEN, META_AD_ACCOUNT_ID, META_ADS_TOKEN, META_PAGE_ID, META_PIXEL_ID,
    WA_PHONE_NUMBER_ID, WA_REPORT_NUMBER, LANDING_PAGE_URL,
    TARGET_ROAS, MAX_CPA, DAILY_SPEND_CAP, APPROVAL_THRESHOLD, AD_TIMEZONE,
    META_GRAPH,
)
from services.agent_swarm.core.workspace import (
    get_workspace, get_workspace_by_wa, list_active_workspaces,
    resolve_workspace, require_auth, get_primary_connection, build_product_context,
)
from services.agent_swarm.agents.performance import analyze_account
from services.agent_swarm.agents.comment_intel import run_comment_intelligence
from services.agent_swarm.agents.creative_director import run_creative_director
from services.agent_swarm.agents.landing_page import run_landing_page_audit
from services.agent_swarm.agents.calendar_agent import get_upcoming_occasions
from services.agent_swarm.agents.budget_governor import run_budget_governor
from services.agent_swarm.agents.creative_generator import run_creative_generator
from services.agent_swarm.agents.moment_marketing import run_moment_marketing
from services.agent_swarm.reporter.whatsapp_hourly import generate_and_send_report

app = FastAPI(title="AI Agency — Agent Swarm", version="2.0.0")

PLATFORM = "meta"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# ── Tenant/Workspace resolution ────────────────────────────
# All resolution now delegates to core.workspace module.
# These thin wrappers keep backward compatibility with existing
# call sites inside this file during the migration period.

def _get_tenant(phone_number_id: str) -> dict | None:
    """Backward-compat: resolve workspace by WA phone_number_id."""
    return get_workspace_by_wa(phone_number_id)


def _default_tenant() -> dict:
    """Backward-compat: return env-var based workspace."""
    from services.agent_swarm.core.workspace import _env_workspace
    return _env_workspace()


def _resolve_tenant(body: dict) -> dict:
    """Backward-compat: resolve workspace from request body."""
    return resolve_workspace(body=body)


def _get_all_active_tenants() -> list[dict]:
    """Backward-compat: return all active workspaces."""
    try:
        workspaces = list_active_workspaces()
        return workspaces if workspaces else [_default_tenant()]
    except Exception as e:
        print(f"_get_all_active_tenants error: {e}")
        return [_default_tenant()]


# ── Auth helpers ───────────────────────────────────────────

def _auth(request: Request):
    """Validate X-Cron-Token for internal service-to-service calls."""
    require_auth(request)


def _admin_auth(request: Request):
    if not ADMIN_TOKEN:
        return
    token = request.headers.get("X-Admin-Token", "")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized — X-Admin-Token required")


def _account_id(workspace: dict = None) -> str:
    """Extract the primary Meta ad_account_id from a workspace dict."""
    conn = get_primary_connection(workspace or {}, "meta") if workspace else None
    acct = (conn or {}).get("ad_account_id") or META_AD_ACCOUNT_ID
    acct = (acct or "").strip().lstrip("_")
    if acct and not acct.startswith("act_") and acct.isdigit():
        acct = f"act_{acct}"
    return acct


# ── Health ────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "agent-swarm",
        "version": "2.0.0",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/admin/google-oauth-configured")
def google_oauth_configured():
    """Public endpoint — no auth required. Returns whether Google OAuth2 client is configured."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    configured = bool(client_id and client_id.strip().upper() != "PLACEHOLDER")
    return {"configured": configured}


# ── Admin: account management ─────────────────────────────

@app.post("/admin/account")
async def create_or_update_account(request: Request):
    """
    Register or update a client account.
    Protected by X-Admin-Token header.

    Body (all optional except name + wa_phone_number_id):
      name, wa_phone_number_id, wa_business_account_id,
      meta_access_token, fb_page_id, ad_account_id, pixel_id,
      admin_wa_id, product_context, landing_page_url,
      target_roas, max_cpa, daily_spend_cap, approval_threshold,
      currency, timezone
    """
    _admin_auth(request)
    body = await request.json()

    for required in ("name", "wa_phone_number_id"):
        if not body.get(required):
            raise HTTPException(status_code=400, detail=f"{required} is required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO accounts (
                    name, wa_phone_number_id, wa_business_account_id,
                    meta_access_token, fb_page_id, ad_account_id, pixel_id,
                    admin_wa_id, product_context, landing_page_url,
                    target_roas, max_cpa, daily_spend_cap, approval_threshold,
                    currency, timezone
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (wa_phone_number_id) DO UPDATE SET
                    name               = EXCLUDED.name,
                    meta_access_token  = COALESCE(EXCLUDED.meta_access_token,  accounts.meta_access_token),
                    fb_page_id         = COALESCE(EXCLUDED.fb_page_id,         accounts.fb_page_id),
                    ad_account_id      = COALESCE(EXCLUDED.ad_account_id,      accounts.ad_account_id),
                    pixel_id           = COALESCE(EXCLUDED.pixel_id,           accounts.pixel_id),
                    admin_wa_id        = COALESCE(EXCLUDED.admin_wa_id,        accounts.admin_wa_id),
                    product_context    = COALESCE(EXCLUDED.product_context,    accounts.product_context),
                    landing_page_url   = COALESCE(EXCLUDED.landing_page_url,   accounts.landing_page_url),
                    wa_business_account_id = COALESCE(EXCLUDED.wa_business_account_id, accounts.wa_business_account_id),
                    target_roas        = EXCLUDED.target_roas,
                    max_cpa            = EXCLUDED.max_cpa,
                    daily_spend_cap    = EXCLUDED.daily_spend_cap,
                    approval_threshold = EXCLUDED.approval_threshold,
                    currency           = EXCLUDED.currency,
                    timezone           = EXCLUDED.timezone
                RETURNING id
                """,
                (
                    body["name"],
                    body["wa_phone_number_id"],
                    body.get("wa_business_account_id"),
                    body.get("meta_access_token"),
                    body.get("fb_page_id"),
                    body.get("ad_account_id"),
                    body.get("pixel_id"),
                    body.get("admin_wa_id"),
                    body.get("product_context"),
                    body.get("landing_page_url"),
                    float(body.get("target_roas", 2.5)),
                    float(body.get("max_cpa", 500)),
                    float(body.get("daily_spend_cap", 20000)),
                    float(body.get("approval_threshold", 10000)),
                    body.get("currency", "INR"),
                    body.get("timezone", "Asia/Kolkata"),
                ),
            )
            row = cur.fetchone()

    # Clear workspace cache so next request gets fresh data
    from services.agent_swarm.core.workspace import invalidate_workspace_cache
    invalidate_workspace_cache(str(row[0]))

    return {
        "ok": True,
        "account_id": str(row[0]),
        "wa_phone_number_id": body["wa_phone_number_id"],
    }


@app.get("/admin/accounts")
async def list_accounts(request: Request):
    """List all registered client accounts."""
    _admin_auth(request)
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, wa_phone_number_id, ad_account_id,
                          admin_wa_id, active, created_at
                   FROM accounts ORDER BY created_at"""
            )
            rows = cur.fetchall()
    return {
        "accounts": [
            {
                "id": str(r[0]),
                "name": r[1],
                "wa_phone_number_id": r[2],
                "ad_account_id": r[3],
                "admin_wa_id": r[4],
                "active": r[5],
                "created_at": str(r[6]),
            }
            for r in rows
        ]
    }


@app.get("/account/by-phone/{phone_number_id}")
async def get_account_by_phone(phone_number_id: str, request: Request):
    """Look up workspace config by WA phone_number_id."""
    _auth(request)
    workspace = get_workspace_by_wa(phone_number_id)
    if not workspace:
        raise HTTPException(
            status_code=404,
            detail=f"No active workspace for phone_number_id={phone_number_id}",
        )
    return {"account": workspace}


# ── Workspace & Product Catalog endpoints ──────────────────

@app.post("/catalog/sync")
async def sync_product_catalog(request: Request):
    """
    Discover and sync products from a store URL.
    Auto-detects Shopify / WooCommerce / custom.
    Body: {workspace_id?, store_url, wc_key?, wc_secret?}
    """
    _auth(request)
    from services.agent_swarm.core.product_catalog import discover_and_sync
    body = await request.json()
    workspace = resolve_workspace(request, body)
    store_url = body.get("store_url") or workspace.get("store_url", "")
    if not store_url:
        raise HTTPException(status_code=400, detail="store_url is required")
    result = discover_and_sync(
        workspace_id=workspace["id"],
        store_url=store_url,
        wc_key=body.get("wc_key"),
        wc_secret=body.get("wc_secret"),
    )
    return {"ok": True, **result}


@app.get("/catalog/products")
async def get_catalog_products(request: Request, workspace_id: str = None):
    """Return full product catalog for a workspace."""
    _auth(request)
    from services.agent_swarm.core.workspace import get_workspace, _fetch_products
    ws_id = workspace_id or request.query_params.get("workspace_id")
    if not ws_id:
        workspace = resolve_workspace(request)
        ws_id = workspace["id"]
    products = _fetch_products(ws_id, active_only=False)
    return {"products": products, "count": len(products)}


@app.get("/workspace/list")
async def list_workspaces(request: Request):
    """List all active workspaces. Agency admin view."""
    _auth(request)
    workspaces = list_active_workspaces()
    return {
        "workspaces": [
            {"id": w["id"], "name": w["name"], "store_url": w["store_url"],
             "store_platform": w["store_platform"], "active": w["active"]}
            for w in workspaces
        ],
        "count": len(workspaces),
    }


# ── Hourly master run ──────────────────────────────────────

@app.post("/cron/hourly")
async def hourly_run(request: Request):
    """
    Master hourly cron: runs all agents for every active account.
    If phone_number_id is in body, runs for that tenant only (per-client scheduler mode).
    If no phone_number_id, runs for all active tenants (global scheduler mode).
    """
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    if body.get("phone_number_id"):
        tenants = [_resolve_tenant(body)]
    else:
        tenants = _get_all_active_tenants()
    hour_now = datetime.now(timezone.utc).hour
    all_results = []
    # Track which Meta ad accounts we've already run budget_governor + LP audit for,
    # so multiple tenant rows sharing the same Meta account don't trigger duplicate actions.
    _processed_meta_accounts: set = set()

    for tenant in tenants:
        account_id = _account_id(tenant)
        tenant_name = tenant.get("name", tenant.get("id", "?"))
        results = {}

        already_processed = account_id in _processed_meta_accounts

        try:
            perf = analyze_account(PLATFORM, account_id)
            results["performance"] = {
                "risk_level": perf.get("risk_level"),
                "causes": perf.get("causes"),
                "recommended_action": perf.get("recommended_action"),
            }
        except Exception as e:
            results["performance"] = {"error": str(e)}
            perf = None

        if not already_processed:
            try:
                gov = run_budget_governor(PLATFORM, account_id, perf, tenant=tenant)
                results["budget_governor"] = {
                    "actions_taken": gov.get("actions_taken"),
                    "actions_pending_approval": gov.get("actions_pending_approval"),
                    "today_spend": gov.get("today_spend"),
                }
            except Exception as e:
                results["budget_governor"] = {"error": str(e)}
        else:
            results["budget_governor"] = {"skipped": "duplicate Meta account — already processed"}

        if not already_processed:
            try:
                lp_url = tenant.get("landing_page_url") or None
                lp = run_landing_page_audit(url=lp_url)
                results["landing_page"] = {
                    "overall_score": lp.get("scores", {}).get("overall"),
                    "top_issues": (lp.get("issues") or [])[:2],
                }
            except Exception as e:
                results["landing_page"] = {"error": str(e)}
        else:
            results["landing_page"] = {"skipped": "duplicate Meta account"}

        _processed_meta_accounts.add(account_id)

        if not already_processed:
            try:
                ci = run_comment_intelligence(PLATFORM, account_id, tenant=tenant)
                results["comment_intel"] = {
                    "ads_processed": ci.get("ads_processed"),
                    "total_comments": ci.get("total_comments"),
                    "auto_replied": ci.get("auto_replied"),
                    "queued_for_review": ci.get("queued_for_review"),
                }
            except Exception as e:
                results["comment_intel"] = {"error": str(e)}

        if not already_processed:
            try:
                report = generate_and_send_report(PLATFORM, account_id, admin_wa_id=tenant.get("admin_wa_id"))
                results["whatsapp_report"] = {"sent": report.get("sent")}
            except Exception as e:
                results["whatsapp_report"] = {"error": str(e)}
        else:
            results["whatsapp_report"] = {"skipped": "duplicate Meta account"}

        all_results.append({
            "tenant": tenant_name,
            "account_id": account_id,
            "results": results,
        })

    # ── Google Ads ingestion (appended to every hourly run) ───────────────
    google_ingest_results = _run_google_ingestion_all()

    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "tenants_processed": len(all_results),
        "results": all_results,
        "google_ingestion": google_ingest_results,
    }


def _run_google_ingestion_all() -> dict:
    """
    Ingest Google Ads campaign + ad_group metrics into kpi_hourly
    for every workspace that has google_auth_tokens credentials.
    Fetches yesterday + today (2-day window) to catch late-arriving data.
    """
    import json as _json
    from datetime import date, timedelta

    today = date.today()
    since = (today - timedelta(days=1)).isoformat()
    until = today.isoformat()

    from services.agent_swarm.db import get_conn as _db
    # Find all workspaces with Google credentials
    try:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT workspace_id FROM google_auth_tokens")
                ws_ids = [str(r[0]) for r in cur.fetchall()]
    except Exception as e:
        return {"error": f"DB lookup failed: {e}", "workspaces": []}

    results = []
    for ws_id in ws_ids:
        r = _ingest_google_workspace(ws_id, since, until)
        results.append(r)
        print(f"[google_ingest] {ws_id}: {r.get('kpi_rows', 0)} rows, errors={r.get('errors')}")

    return {"since": since, "until": until, "workspaces": results}


def _ingest_google_workspace(workspace_id: str, since: str, until: str) -> dict:
    """Ingest Google Ads data for a single workspace into kpi_hourly."""
    import json as _json

    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        return {"workspace_id": workspace_id, "error": "no credentials", "kpi_rows": 0}

    from services.agent_swarm.db import get_conn as _db
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, timezone, currency FROM workspaces WHERE id = %s",
                (workspace_id,),
            )
            row = cur.fetchone()
    if not row:
        return {"workspace_id": workspace_id, "error": "workspace not found", "kpi_rows": 0}

    workspace_dict = {
        "id": str(row[0]),
        "name": row[1] or "",
        "timezone": row[2] or "Asia/Kolkata",
        "currency": row[3] or "INR",
    }

    from services.agent_swarm.connectors.google import GoogleConnector
    gc = GoogleConnector(conn_row, workspace_dict)

    total_rows = 0
    errors = []

    for entity_level in ("campaign", "ad_group"):
        try:
            snapshots = gc.fetch_metrics(since=since, until=until, entity_level=entity_level)
            if not snapshots:
                continue
            with _db() as conn:
                with conn.cursor() as cur:
                    for s in snapshots:
                        cur.execute(
                            """
                            INSERT INTO kpi_hourly (
                                workspace_id, platform, account_id,
                                entity_level, entity_id, entity_name,
                                hour_ts,
                                spend, impressions, clicks, conversions, revenue,
                                ctr, cpm, cpc, roas, raw_json
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s
                            )
                            ON CONFLICT (platform, account_id, entity_level, entity_id, hour_ts)
                            DO UPDATE SET
                                workspace_id = EXCLUDED.workspace_id,
                                entity_name  = EXCLUDED.entity_name,
                                spend        = EXCLUDED.spend,
                                impressions  = EXCLUDED.impressions,
                                clicks       = EXCLUDED.clicks,
                                conversions  = EXCLUDED.conversions,
                                revenue      = EXCLUDED.revenue,
                                ctr          = EXCLUDED.ctr,
                                cpm          = EXCLUDED.cpm,
                                cpc          = EXCLUDED.cpc,
                                roas         = EXCLUDED.roas,
                                raw_json     = EXCLUDED.raw_json,
                                updated_at   = NOW()
                            """,
                            (
                                workspace_id, s.platform, s.account_id,
                                s.entity_level, s.entity_id, s.entity_name,
                                s.hour_ts,
                                s.spend, s.impressions, s.clicks,
                                s.conversions, s.revenue,
                                s.ctr, s.cpm, s.cpc, s.roas,
                                _json.dumps(s.raw_json) if s.raw_json else None,
                            ),
                        )
                    total_rows += len(snapshots)
        except Exception as e:
            errors.append(f"{entity_level}: {e}")

    return {
        "workspace_id": workspace_id,
        "since": since,
        "until": until,
        "kpi_rows": total_rows,
        "errors": errors,
    }


@app.post("/cron/google/ingest")
async def google_ingest_endpoint(request: Request):
    """Manual trigger: ingest Google Ads data for all workspaces right now."""
    _auth(request)
    from datetime import date, timedelta
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    days_back = int(body.get("days_back", 1))
    today = date.today()
    since = (today - timedelta(days=days_back)).isoformat()
    until = today.isoformat()
    workspace_id = body.get("workspace_id")
    if workspace_id:
        result = _ingest_google_workspace(workspace_id, since, until)
        return {"ok": True, "result": result}
    return {"ok": True, **_run_google_ingestion_all()}


# ── LP Audit Cache — receives results from LP Auditor web tool ─────────────

@app.post("/api/lp-audit-save")
async def save_lp_audit(request: Request):
    """
    Receives a completed LP audit from the local LP Auditor web tool and
    stores it in lp_audit_cache so the sales strategist can reference it.
    Body: {phone_number_id?, site_url, score, grade, mobile_load_ms,
           desktop_load_ms, ctas_above_fold, price_visible, page_height_px,
           issues, competitor_summary, full_audit_json}
    """
    _auth(request)
    body = await request.json()
    tenant = _resolve_tenant(body)
    tenant_id = tenant["id"]

    from services.agent_swarm.db import get_conn
    import json as _json

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO lp_audit_cache
                      (tenant_id, site_url, score, grade, mobile_load_ms,
                       desktop_load_ms, ctas_above_fold, price_visible,
                       page_height_px, issues, competitor_summary, full_audit_json)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        tenant_id,
                        body.get("site_url", ""),
                        int(body.get("score", 0)),
                        body.get("grade", "D"),
                        body.get("mobile_load_ms"),
                        body.get("desktop_load_ms"),
                        int(body.get("ctas_above_fold", 0)),
                        bool(body.get("price_visible", False)),
                        body.get("page_height_px"),
                        _json.dumps(body.get("issues", [])),
                        _json.dumps(body.get("competitor_summary", [])),
                        _json.dumps(body.get("full_audit_json", {})),
                    ),
                )
        print(f"lp-audit-save: saved score={body.get('score')} for tenant={tenant_id}")
        return {"ok": True, "tenant_id": tenant_id}
    except Exception as e:
        print(f"lp-audit-save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Individual agent endpoints ─────────────────────────────

@app.post("/agent/performance")
async def agent_performance(request: Request):
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    tenant = _resolve_tenant(body)
    return analyze_account(PLATFORM, _account_id(tenant))


@app.post("/agent/comments")
async def agent_comments(request: Request):
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    tenant = _resolve_tenant(body)
    return run_comment_intelligence(PLATFORM, _account_id(tenant), tenant=tenant)


@app.post("/agent/creative")
async def agent_creative(request: Request):
    """Weekly creative director."""
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    tenant = _resolve_tenant(body)
    return run_creative_director(PLATFORM, _account_id(tenant))


@app.post("/agent/landing-page")
async def agent_landing_page(request: Request):
    _auth(request)
    return run_landing_page_audit()


@app.get("/agent/calendar")
async def agent_calendar(request: Request, horizon_days: int = 14):
    _auth(request)
    return get_upcoming_occasions(horizon_days)


@app.post("/agent/budget-governor")
async def agent_budget_governor(request: Request):
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    tenant = _resolve_tenant(body)
    return run_budget_governor(PLATFORM, _account_id(tenant), tenant=tenant)


@app.post("/cron/weekly")
async def weekly_run(request: Request):
    """Weekly: creative director + fresh creative generation for every active account.
    If phone_number_id is in body, runs for that tenant only (per-client scheduler mode).
    """
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    if body.get("phone_number_id"):
        tenants = [_resolve_tenant(body)]
    else:
        tenants = _get_all_active_tenants()
    all_results = []

    for tenant in tenants:
        try:
            account_id = _account_id(tenant)
            creative_dir = run_creative_director(PLATFORM, account_id)
            creatives = run_creative_generator(
                PLATFORM, account_id, trigger_reason="weekly_refresh", tenant=tenant,
            )
            all_results.append({
                "tenant": tenant.get("name", "?"),
                "creative_director": creative_dir,
                "creative_generator": creatives,
            })
        except Exception as e:
            all_results.append({"tenant": tenant.get("name", "?"), "error": str(e)})

    return {"ok": True, "tenants_processed": len(all_results), "results": all_results}


@app.post("/cron/creative-gen")
async def creative_gen(request: Request, background_tasks: BackgroundTasks):
    """
    On-demand: generate new ad creatives and send to WhatsApp for approval.
    Returns immediately — generation runs in background.
    Body: {phone_number_id?, trigger_reason?, daily_budget_inr?, product_id?, product_url?}
    """
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    tenant = _resolve_tenant(body)
    account_id = _account_id(tenant)
    trigger = body.get("trigger_reason", "manual")
    budget = float(body.get("daily_budget_inr", 300))
    product_id = body.get("product_id") or None
    product_url = body.get("product_url") or None
    # Allow per-campaign page and pixel override (user selects in WhatsApp flow)
    fb_page_id_override = body.get("fb_page_id") or None
    pixel_id_override = body.get("pixel_id") or None
    if fb_page_id_override or pixel_id_override:
        tenant = dict(tenant)
        if fb_page_id_override:
            tenant["fb_page_id"] = fb_page_id_override
        if pixel_id_override:
            tenant["pixel_id"] = pixel_id_override
    background_tasks.add_task(
        run_creative_generator, PLATFORM, account_id,
        trigger_reason=trigger, daily_budget_inr=budget,
        product_id=product_id, product_url=product_url, tenant=tenant,
    )
    return {
        "ok": True, "status": "started", "trigger": trigger,
        "daily_budget_inr": budget, "product_id": product_id,
        "product_url": product_url, "tenant_id": tenant["id"],
    }


@app.post("/report/now")
async def report_now(request: Request):
    """Trigger an on-demand WhatsApp report."""
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    tenant = _resolve_tenant(body)
    return generate_and_send_report(PLATFORM, _account_id(tenant), admin_wa_id=tenant.get("admin_wa_id"))


@app.post("/cron/daily-moment")
async def daily_moment(request: Request):
    """Daily moment marketing agent for every active account.
    If phone_number_id is in body, runs for that tenant only (per-client scheduler mode).
    """
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    if body.get("phone_number_id"):
        tenants = [_resolve_tenant(body)]
    else:
        tenants = _get_all_active_tenants()
    all_results = []

    for tenant in tenants:
        try:
            result = run_moment_marketing(PLATFORM, _account_id(tenant))
            all_results.append({"tenant": tenant.get("name", "?"), "result": result})
        except Exception as e:
            all_results.append({"tenant": tenant.get("name", "?"), "error": str(e)})

    return {"ok": True, "tenants_processed": len(all_results), "results": all_results}


# ── Product asset management ───────────────────────────────

@app.post("/product/upload")
async def upload_product_photo(request: Request):
    """
    Download a WhatsApp media item and upload to fal.ai CDN.
    Body: {media_id, phone_number_id?}
    Returns: {cdn_url}
    """
    _auth(request)
    body = await request.json()
    media_id = body.get("media_id", "")
    if not media_id:
        raise HTTPException(status_code=400, detail="media_id is required")

    from services.agent_swarm.agents.creative_generator import _download_wa_media_to_cdn
    cdn_url = _download_wa_media_to_cdn(media_id)
    return {"ok": True, "cdn_url": cdn_url}


@app.post("/product/asset")
async def save_product_asset(request: Request, background_tasks: BackgroundTasks):
    """
    Store a product reference image URL for a tenant.
    Runs Claude vision analysis, saves to DB, auto-generates 8 training
    variations, and starts LoRA training in background.

    Body: {asset_type, cdn_url, phone_number_id?, name?, product_url?}
    """
    _auth(request)
    body = await request.json()
    tenant = _resolve_tenant(body)
    tenant_id = tenant["id"]

    asset_type = body.get("asset_type", "").strip()
    cdn_url = body.get("cdn_url", "").strip()
    product_name = body.get("name", "").strip()
    product_url = body.get("product_url", "").strip()

    if not asset_type:
        raise HTTPException(status_code=400, detail="asset_type is required")
    if not cdn_url:
        raise HTTPException(status_code=400, detail="cdn_url is required")

    # Claude vision analysis
    analysis = {}
    try:
        from services.agent_swarm.agents.creative_generator import analyze_product_image
        analysis = analyze_product_image(cdn_url)
        print(f"Product analysis for {asset_type} (tenant={tenant_id}): {analysis}")
        if not product_name:
            ptype = analysis.get("product_type", "")
            product_name = ptype.replace("_", " ").title() if ptype else asset_type
    except Exception as e:
        print(f"Product vision analysis failed (non-fatal): {e}")

    if not product_name:
        product_name = asset_type

    product_description = (analysis or {}).get("product_description", "")

    from services.agent_swarm.db import get_conn
    import json as _json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO product_assets
                    (tenant_id, asset_type, cdn_url, metadata, name, image_urls, product_url, updated_at)
                VALUES (%s, %s, %s, %s, %s, ARRAY[%s::TEXT], %s, NOW())
                ON CONFLICT (tenant_id, asset_type) DO UPDATE
                    SET cdn_url     = EXCLUDED.cdn_url,
                        metadata    = EXCLUDED.metadata,
                        name        = COALESCE(NULLIF(EXCLUDED.name, ''), product_assets.name),
                        product_url = COALESCE(NULLIF(EXCLUDED.product_url, ''), product_assets.product_url),
                        image_urls  = CASE
                            WHEN %s = ANY(COALESCE(product_assets.image_urls, '{}'))
                            THEN product_assets.image_urls
                            ELSE COALESCE(product_assets.image_urls, '{}') || ARRAY[%s::TEXT]
                        END,
                        updated_at  = NOW()
                """,
                (
                    tenant_id, asset_type, cdn_url,
                    _json.dumps(analysis) if analysis else None,
                    product_name, cdn_url, product_url or None,
                    cdn_url, cdn_url,
                ),
            )

    from services.agent_swarm.agents.creative_generator import auto_generate_and_train
    background_tasks.add_task(
        auto_generate_and_train, asset_type, cdn_url, product_description,
        tenant_id, tenant.get("admin_wa_id", WA_REPORT_NUMBER),
    )

    return {"ok": True, "asset_type": asset_type, "name": product_name, "analysis": analysis}


def _product_rows_to_list(rows):
    return [
        {
            "asset_type": r[0],
            "cdn_url": r[1],
            "name": r[2] or r[0],
            "photo_count": len(r[3] or []) or (1 if r[1] else 0),
            "image_urls": r[3] or [],
            "lora_status": r[4] or "none",
            "lora_url": r[5],
            "lora_trigger_word": r[6],
            "placement_category": (r[7] or {}).get("placement_category", ""),
            "product_description": (r[7] or {}).get("product_description", ""),
            "product_url": r[8],
            "updated_at": str(r[9]),
        }
        for r in rows
    ]


@app.get("/product/asset")
async def list_product_assets(
    request: Request,
    phone_number_id: str = None,
):
    """List all stored product reference images for a tenant."""
    _auth(request)
    tenant = _get_tenant(phone_number_id or WA_PHONE_NUMBER_ID) or _default_tenant()
    tenant_id = tenant["id"]
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT asset_type, cdn_url, name, image_urls,
                          lora_status, lora_url, lora_trigger_word,
                          metadata, product_url, updated_at
                   FROM product_assets
                   WHERE tenant_id=%s
                   ORDER BY updated_at DESC""",
                (tenant_id,),
            )
            rows = cur.fetchall()
    return {"assets": _product_rows_to_list(rows)}


@app.get("/products/list")
async def list_products(
    request: Request,
    phone_number_id: str = None,
):
    """List all stored products for a tenant (used by wa-bot campaign flow)."""
    _auth(request)
    tenant = _get_tenant(phone_number_id or WA_PHONE_NUMBER_ID) or _default_tenant()
    tenant_id = tenant["id"]
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT asset_type, cdn_url, name, image_urls,
                          lora_status, lora_url, lora_trigger_word,
                          metadata, product_url, updated_at
                   FROM product_assets
                   WHERE tenant_id=%s
                   ORDER BY updated_at DESC""",
                (tenant_id,),
            )
            rows = cur.fetchall()
    return {"products": _product_rows_to_list(rows)}


@app.post("/products/train-lora")
async def train_lora_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Start LoRA training for a product in background.
    Body: {asset_type, phone_number_id?}
    """
    _auth(request)
    body = await request.json()
    tenant = _resolve_tenant(body)
    tenant_id = tenant["id"]
    asset_type = body.get("asset_type", "").strip()

    if not asset_type:
        raise HTTPException(status_code=400, detail="asset_type is required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, image_urls, cdn_url FROM product_assets WHERE tenant_id=%s AND asset_type=%s",
                (tenant_id, asset_type),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No product found for asset_type='{asset_type}' in this account",
        )

    name, image_urls, cdn_url = row
    all_urls = list(dict.fromkeys([u for u in (image_urls or []) if u] + ([cdn_url] if cdn_url else [])))
    if not all_urls:
        raise HTTPException(status_code=400, detail="No photos uploaded for this product yet")

    from services.agent_swarm.agents.creative_generator import train_product_lora
    background_tasks.add_task(
        train_product_lora, asset_type, tenant_id,
        tenant.get("admin_wa_id", WA_REPORT_NUMBER),
    )
    return {
        "ok": True,
        "status": "training_started",
        "asset_type": asset_type,
        "name": name or asset_type,
        "photo_count": len(all_urls),
    }


# ── Creative editing ───────────────────────────────────────

@app.post("/creative/pending")
async def get_pending_creative(request: Request):
    """Return most recent pending_approval creative ID for a tenant."""
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    tenant = _resolve_tenant(body)
    tenant_id = tenant["id"]
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM creative_queue
                WHERE status IN ('pending_approval', 'draft_copy') AND tenant_id=%s
                ORDER BY
                    CASE status WHEN 'draft_copy' THEN 0 ELSE 1 END,
                    created_at DESC
                LIMIT 1
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
    if not row:
        return {"creative_id": None}
    return {"creative_id": str(row[0])}


@app.post("/creative/generate-image")
async def generate_image_endpoint(request: Request):
    """
    Trigger image generation for a draft_copy creative (split flow).
    Called when user types 'confirm copy <id>'.
    Runs synchronously via asyncio.to_thread so Cloud Run keeps the container
    alive until generation completes (~30-90s).
    Body: {creative_id, phone_number_id?}
    """
    _auth(request)
    body = await request.json()
    tenant = _resolve_tenant(body)
    tenant_id = tenant["id"]
    short_id = (body.get("creative_id") or "").strip().lower()

    import asyncio
    from services.agent_swarm.db import get_conn

    if short_id:
        # Resolve short ID to full UUID
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id FROM creative_queue
                       WHERE id::text LIKE %s AND status='draft_copy'
                       ORDER BY created_at DESC LIMIT 1""",
                    (f"{short_id}%",),
                )
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft creative not found or already processed")
        creative_full_id = str(row[0])
    else:
        # Most recent draft_copy for this tenant
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id FROM creative_queue
                       WHERE status='draft_copy' AND tenant_id=%s
                       ORDER BY created_at DESC LIMIT 1""",
                    (tenant_id,),
                )
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No draft copy found for this account")
        creative_full_id = str(row[0])

    from services.agent_swarm.agents.creative_generator import generate_image_for_creative
    # Run synchronously — keeps container alive until image is ready and WA message sent
    result = await asyncio.to_thread(generate_image_for_creative, creative_full_id, tenant)

    return {"ok": result.get("ok", False), "status": "completed", "creative_id": creative_full_id[:8]}


@app.post("/creative/edit")
async def edit_creative_endpoint(request: Request):
    """
    Edit an existing pending creative in-place and resend WA preview.
    Body: {edit_type, phone_number_id?, creative_id?, instructions?, media_id?}
    Supports both 'pending_approval' and 'draft_copy' status creatives.
    """
    _auth(request)
    body = await request.json()
    tenant = _resolve_tenant(body)
    tenant_id = tenant["id"]
    edit_type = body.get("edit_type", "")
    creative_id = body.get("creative_id", "")
    instructions = body.get("instructions", "")
    media_id = body.get("media_id", "")

    if not edit_type:
        raise HTTPException(status_code=400, detail="edit_type is required")

    if not creative_id:
        from services.agent_swarm.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Prefer draft_copy (copy phase) over pending_approval (image phase)
                cur.execute(
                    """
                    SELECT id FROM creative_queue
                    WHERE status IN ('draft_copy', 'pending_approval') AND tenant_id=%s
                    ORDER BY
                        CASE status WHEN 'draft_copy' THEN 0 ELSE 1 END,
                        created_at DESC
                    LIMIT 1
                    """,
                    (tenant_id,),
                )
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No pending creative found")
        creative_id = str(row[0])

    from services.agent_swarm.agents.creative_generator import edit_creative
    return edit_creative(
        creative_id, edit_type, instructions, media_id,
        wa_report_number=tenant.get("admin_wa_id", WA_REPORT_NUMBER),
        tenant_id=tenant["id"],
    )


# ── Approval endpoints ─────────────────────────────────────

@app.post("/approval/creative")
async def handle_creative_approval(request: Request):
    """
    Called by wa-bot when admin replies 'approve creative XXXXXXXX'.
    On approve: publishes creative to Meta Ads using the tenant's credentials.
    Body: {creative_id, decision, phone_number_id?}
    """
    body = await request.json()
    short_id = body.get("creative_id", "").strip().lower()
    decision = body.get("decision", "").strip().lower()
    tenant = _resolve_tenant(body)

    if not short_id or decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Invalid payload")

    from services.agent_swarm.db import get_conn
    from services.agent_swarm.wa import send_text

    wa_report = tenant.get("admin_wa_id", WA_REPORT_NUMBER)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, angle, headline, status
                FROM creative_queue
                WHERE id::text LIKE %s AND status IN ('pending_approval', 'draft_copy')
                ORDER BY created_at DESC LIMIT 1
                """,
                (f"{short_id}%",),
            )
            row = cur.fetchone()

    if not row:
        return {"ok": False, "error": "Creative not found or already processed"}

    creative_db_id, angle, headline, status = row

    if decision == "reject":
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE creative_queue SET status='rejected', approved_by='whatsapp', updated_at=NOW() WHERE id=%s",
                    (creative_db_id,),
                )
        send_text(wa_report, f"❌ Creative '{angle}' rejected.")
        return {"ok": True, "decision": "rejected", "creative_id": str(creative_db_id)}

    # Cannot approve a draft_copy — image not yet generated
    if status == "draft_copy":
        send_text(
            wa_report,
            f"⚠️ Copy not yet confirmed for '{angle}'.\n"
            f"Type *confirm copy {short_id}* first to generate the image, then approve.",
        )
        return {"ok": False, "error": "Creative is in draft_copy state — confirm copy first"}

    send_text(wa_report, f"✅ Creative '{angle}' approved! Publishing to Meta now...")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE creative_queue SET status='publishing', approved_by='whatsapp', updated_at=NOW() WHERE id=%s",
                (creative_db_id,),
            )

    from services.agent_swarm.creative.meta_publisher import publish_creative
    result = publish_creative(str(creative_db_id), tenant=tenant)

    if result["ok"]:
        send_text(
            wa_report,
            f"🚀 *Ad Published!*\n"
            f"Campaign: {result.get('campaign_id')}\n"
            f"Budget: ₹{result.get('daily_budget_inr', 300)}/day (ACTIVE — campaign is live)\n"
            f"Creative: '{angle}' — {headline}",
        )
    else:
        send_text(
            wa_report,
            f"⚠️ Publish failed for '{angle}': {result.get('error', 'unknown error')[:200]}",
        )

    return result


def _launch_campaign_on_meta(workspace_id: str, new_value: dict, platform: str) -> dict:
    """
    Creates a PAUSED Meta Campaign + Ad Set from a create_campaign plan.
    Returns {ok, meta_campaign_id, meta_adset_id, campaign_name, adset_name, adset_error, error}.
    """
    import json as _json
    import requests as _requests
    from datetime import datetime, timezone
    from services.agent_swarm.db import get_conn

    concept = new_value.get("concept", {})
    brief   = new_value.get("brief", {})

    campaign_name = concept.get("headline") or brief.get("product_name") or "New Campaign"
    goal = brief.get("goal", "conversions")
    budget_daily = (
        brief.get("budget_daily")
        or concept.get("recommended_budget_daily")
        or 1000
    )

    GOAL_TO_OBJECTIVE = {
        "conversions": "OUTCOME_SALES",
        "awareness":   "OUTCOME_AWARENESS",
        "traffic":     "OUTCOME_TRAFFIC",
        "leads":       "OUTCOME_LEADS",
        "video_views": "OUTCOME_ENGAGEMENT",
    }
    objective = GOAL_TO_OBJECTIVE.get(goal, "OUTCOME_SALES")

    OBJECTIVE_ADSET_CONFIG = {
        "OUTCOME_SALES":      ("OFFSITE_CONVERSIONS", "IMPRESSIONS"),
        "OUTCOME_AWARENESS":  ("REACH",               "IMPRESSIONS"),
        "OUTCOME_TRAFFIC":    ("LINK_CLICKS",          "LINK_CLICKS"),
        "OUTCOME_LEADS":      ("LEAD_GENERATION",      "IMPRESSIONS"),
        "OUTCOME_ENGAGEMENT": ("POST_ENGAGEMENT",      "IMPRESSIONS"),
    }
    optimization_goal, billing_event = OBJECTIVE_ADSET_CONFIG.get(
        objective, ("REACH", "IMPRESSIONS")
    )

    # Get Meta connection for this workspace
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT ad_account_id, access_token, pixel_id
                   FROM platform_connections
                   WHERE workspace_id = %s AND platform = 'meta'
                   ORDER BY is_primary DESC LIMIT 1""",
                (workspace_id,),
            )
            meta_row = cur.fetchone()

    if not meta_row or not meta_row[0] or not meta_row[1]:
        return {"ok": False, "error": "No active Meta connection — connect Meta in Settings first"}

    ad_account_id, access_token, pixel_id = meta_row
    act_id = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
    META_API_VERSION = "v21.0"

    # ── Step 1: Create Campaign ───────────────────────────────────────────────
    camp_url = f"https://graph.facebook.com/{META_API_VERSION}/{act_id}/campaigns"
    camp_resp = _requests.post(
        camp_url,
        params={"access_token": access_token},
        data={
            "name": campaign_name,
            "objective": objective,
            "status": "PAUSED",
            "special_ad_categories": "[]",
            "is_adset_budget_sharing_enabled": "false",
        },
        timeout=15,
    )
    camp_data = camp_resp.json()
    print(f"[launch_meta] campaign status={camp_resp.status_code} body={_json.dumps(camp_data)}")

    if not camp_resp.ok or "error" in camp_data:
        err = camp_data.get("error", {})
        msg = err.get("error_user_msg") or err.get("message") or "Meta API error"
        code = err.get("code", "")
        sub  = err.get("error_subcode", "")
        return {"ok": False, "error": f"Campaign creation failed (code {code}/{sub}): {msg}"}

    meta_campaign_id = camp_data["id"]

    # ── Step 2: Create Ad Set ─────────────────────────────────────────────────
    adset_name = f"{campaign_name} — Ad Set"
    daily_budget_paise = max(int(float(budget_daily) * 100), 57600)  # INR paise, min ~₹576

    adset_payload = {
        "name": adset_name,
        "campaign_id": meta_campaign_id,
        "daily_budget": daily_budget_paise,
        "billing_event": billing_event,
        "optimization_goal": optimization_goal,
        "targeting": _json.dumps({"geo_locations": {"countries": ["IN"]}, "age_min": 25, "age_max": 55}),
        "status": "PAUSED",
        "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000"),
    }

    if optimization_goal == "OFFSITE_CONVERSIONS" and pixel_id:
        adset_payload["promoted_object"] = _json.dumps({
            "pixel_id": pixel_id,
            "custom_event_type": "PURCHASE",
        })
    elif optimization_goal == "OFFSITE_CONVERSIONS":
        # No pixel — fall back to REACH so the ad set doesn't get rejected
        adset_payload["optimization_goal"] = "REACH"
        adset_payload["billing_event"] = "IMPRESSIONS"

    adset_url = f"https://graph.facebook.com/{META_API_VERSION}/{act_id}/adsets"
    adset_resp = _requests.post(
        adset_url,
        params={"access_token": access_token},
        data=adset_payload,
        timeout=15,
    )
    adset_data = adset_resp.json()
    print(f"[launch_meta] adset status={adset_resp.status_code} body={_json.dumps(adset_data)}")

    meta_adset_id = None
    adset_error  = None
    if adset_resp.ok and "error" not in adset_data:
        meta_adset_id = adset_data.get("id")
    else:
        adset_error = adset_data.get("error", {}).get("message", "Ad set creation failed")

    return {
        "ok": True,
        "meta_campaign_id": meta_campaign_id,
        "meta_adset_id": meta_adset_id,
        "campaign_name": campaign_name,
        "adset_name": adset_name if meta_adset_id else None,
        "adset_error": adset_error,
    }


def _launch_campaign_on_google(workspace_id: str, new_value: dict) -> dict:
    """
    Creates a PAUSED Google Performance Max campaign from a create_campaign plan.
    Uses _get_google_conn_from_db (which reads google_auth_tokens) — no Meta API called.
    Returns {ok, google_campaign_id, campaign_name, note, error}.

    NOTE: Requires Google Ads developer token with Basic/Standard access.
          Returns an error if the token is still in Test status.
    """
    from services.agent_swarm.connectors.google import GoogleConnector
    from services.agent_swarm.connectors.base import CampaignSpec

    concept = new_value.get("concept", {})
    brief   = new_value.get("brief", {})
    campaign_name = concept.get("headline") or brief.get("product_name") or "New Campaign"
    budget_daily  = float(brief.get("budget_daily") or concept.get("recommended_budget_daily") or 1000)
    product_name  = brief.get("product_name") or campaign_name
    goal          = brief.get("goal", "conversions")

    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        return {"ok": False, "error": "No Google Ads connection — connect Google in Settings first"}
    if not conn_row.get("customer_id"):
        return {"ok": False, "error": "Google customer_id not found — reconnect Google in Settings"}

    workspace_obj = get_workspace(workspace_id) or {"id": workspace_id}
    spec = CampaignSpec(
        name=campaign_name,
        product_id="",
        product_name=product_name,
        product_url=brief.get("product_url") or "https://agatsaone.com",
        daily_budget_inr=budget_daily,
        objective=goal,
        headline=concept.get("headline") or campaign_name,
        primary_text=concept.get("body_copy") or "",
        description=concept.get("creative_direction") or "",
    )
    try:
        connector = GoogleConnector(conn_row, workspace_obj)
        result = connector.create_campaign(spec)
        if "error" in result:
            return {"ok": False, "error": result["error"]}
        return {
            "ok": True,
            "google_campaign_id": result.get("campaign_id"),
            "campaign_name": campaign_name,
            "note": "PAUSED Performance Max campaign created in Google Ads",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _generate_campaign_plan_from_action(workspace_id: str, action_type: str, ctx: dict, entity_id: str, platform: str) -> str | None:
    """
    Called after approving an ai_brief or new_creative action.
    Calls Claude to generate a campaign concept and inserts it into action_log
    as action_type='create_campaign' so it appears in the Campaign Planner.
    Returns the new plan_id (str) or None on failure.
    """
    import json as _json
    import anthropic as _anthropic
    from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    from services.agent_swarm.db import get_conn

    description = ctx.get("description") or ctx.get("detail") or ""
    entity_name = ctx.get("entity_name") or entity_id or "Campaign"
    suggested_value = ctx.get("suggested_value") or ""
    product_name = ctx.get("product_name") or entity_name
    budget_daily = int(ctx.get("budget_daily") or ctx.get("suggested_value") or 1000)
    channels = ctx.get("channels") or ([platform] if platform and platform != "all" else ["meta"])
    if isinstance(channels, str):
        channels = [channels]

    prompt = f"""You are an expert performance marketing strategist for an Indian health tech brand.
An AI system flagged this opportunity and the team has approved it:

Action type: {action_type.replace('_', ' ')}
Campaign/Entity: {entity_name}
Opportunity: {description}
{f'Suggested value: {suggested_value}' if suggested_value else ''}
Channels: {', '.join(channels)}

Generate a complete campaign concept as a JSON object with exactly these keys:
- headline: (string) Primary ad headline, max 40 chars
- body_copy: (string) 2-3 sentence ad body copy
- hook: (string) Opening hook for video/reel, 1 sentence
- creative_direction: (string) Visual/creative guidance, 2-3 sentences
- recommended_format: (string) e.g. "Carousel + Reel" or "Search + Display"
- kpi_targets: {{expected_roas: number, expected_cpa: number, expected_ctr: number}}
- rationale: (string) Why this approach for this opportunity

Return ONLY valid JSON, no markdown."""

    client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    concept = {}
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        concept = _json.loads(text[start:end]) if start != -1 else {}
    except Exception as e:
        concept = {
            "headline": f"Grow with {product_name}",
            "body_copy": f"Reach more customers with targeted {', '.join(channels)} ads. AI-optimised for maximum ROAS.",
            "hook": "Here's what your competitors don't want you to know...",
            "creative_direction": "Show real results. Use testimonials + product demo split-screen.",
            "recommended_format": "Video + Carousel",
            "kpi_targets": {"expected_roas": 2.5, "expected_cpa": 800, "expected_ctr": 2.0},
            "rationale": "Approved AI opportunity converted to campaign brief.",
            "error": str(e),
        }

    new_value = {
        "brief": {
            "product_name": product_name,
            "goal": "conversions",
            "budget_daily": budget_daily,
            "duration_days": 14,
            "channels": channels,
            "source_action": action_type,
            "source_description": description,
        },
        "concept": concept,
    }

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO action_log
                        (workspace_id, platform, account_id, entity_level, entity_id,
                         action_type, new_value, triggered_by, status)
                    VALUES (%s, %s, 'ai_approved', 'campaign', 'new',
                            'create_campaign', %s::jsonb, 'ai_approval', 'pending')
                    RETURNING id
                    """,
                    (workspace_id, channels[0] if channels else "meta", _json.dumps(new_value)),
                )
                plan_id = cur.fetchone()[0]
            conn.commit()
        return str(plan_id)
    except Exception:
        return None


@app.post("/approval/respond")
async def handle_approval(request: Request):
    """
    Called by wa-bot when admin replies 'approve XXXXXXXX' or 'reject XXXXXXXX',
    or by the dashboard UI with {action_id: full_uuid, decision: approve|reject}.

    Downstream actions on approve:
      - pause / resume / increase_budget / decrease_budget → Meta API execution
      - ai_brief / new_creative → Claude generates campaign concept → Campaign Planner
      - keyword_addition → mark approved, redirect to /google-ads
      - geographic_expansion / bid_adjustment → mark approved, redirect to /campaigns
      - review → mark approved, no redirect
    """
    body = await request.json()
    action_short_id = (body.get("action_id") or body.get("action_log_id") or "").strip().lower()
    decision_raw = body.get("decision") or body.get("response", "")
    decision = "approve" if str(decision_raw).upper() in ("APPROVE", "YES") else "reject"

    if not action_short_id or decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Invalid payload")

    from services.agent_swarm.db import get_conn
    from services.agent_swarm.agents.budget_governor import _auto_execute_action
    import json as _json

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, workspace_id, platform, entity_id, action_type, new_value, status
                FROM action_log
                WHERE id::text LIKE %s AND status='pending'
                ORDER BY ts DESC LIMIT 1
                """,
                (f"{action_short_id}%",),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Action not found or already resolved")

    action_id, workspace_id, platform, entity_id, action_type, new_value_raw, status = row
    new_value = _json.loads(new_value_raw) if isinstance(new_value_raw, str) else (new_value_raw or {})

    # If the user edited the body copy in the approval view, apply it before executing
    edited_body_copy = (body.get("edited_body_copy") or "").strip()
    if edited_body_copy and action_type == "create_campaign":
        if isinstance(new_value.get("concept"), dict):
            new_value["concept"]["body_copy"] = edited_body_copy
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE action_log SET new_value=%s::jsonb WHERE id=%s",
                    (_json.dumps(new_value), action_id),
                )

    if decision == "reject":
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE action_log SET status='rejected', approved_by='dashboard' WHERE id=%s",
                    (action_id,),
                )
                cur.execute(
                    "UPDATE pending_approvals SET status='rejected', responded_at=NOW(), response='NO' WHERE action_log_id=%s",
                    (action_id,),
                )
        return {"ok": True, "decision": "rejected", "action_id": str(action_id)}

    # ── Approve path ─────────────────────────────────────────────────────────
    EXECUTABLE_TYPES = {"pause", "resume", "increase_budget", "decrease_budget", "pause_campaign"}
    PLAN_TYPES = {"ai_brief", "new_creative"}
    redirect = None
    plan_id = None
    final_status = "approved"
    success = True
    launch_result = None
    execution_note = None

    if action_type in EXECUTABLE_TYPES:
        if platform == "google":
            # Use GoogleConnector for Google platform budget/pause/resume actions
            _gconn = _get_google_conn_from_db(str(workspace_id))
            if _gconn:
                _gws = get_workspace(str(workspace_id)) or {"id": str(workspace_id)}
                from services.agent_swarm.connectors.google import GoogleConnector as _GC
                try:
                    _gc = _GC(_gconn, _gws)
                    if action_type in ("pause", "pause_campaign"):
                        success = _gc.pause(str(entity_id))
                    elif action_type == "resume":
                        success = _gc.resume(str(entity_id))
                    elif action_type in ("increase_budget", "decrease_budget"):
                        _new_b = float((new_value or {}).get("daily_budget_inr", 0))
                        success = _gc.update_budget(str(entity_id), _new_b) if _new_b > 0 else False
                except Exception as _ge:
                    print(f"[approval] Google action error: {_ge}")
                    success = False
            else:
                success = False
                execution_note = "No Google Ads connection — connect Google in Settings"
            final_status = "executed" if success else "failed"
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE action_log SET status=%s, approved_by='dashboard', executed_at=NOW() WHERE id=%s",
                        (final_status, action_id),
                    )
        else:
            # Meta API execution — _auto_execute_action updates action_log internally
            success = _auto_execute_action(str(action_id), entity_id, action_type, new_value)
            final_status = "executed" if success else "failed"
        redirect = "/campaigns"

    elif action_type in PLAN_TYPES:
        # Generate a campaign concept via Claude and add to Campaign Planner
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE action_log SET status='approved', approved_by='dashboard', executed_at=NOW() WHERE id=%s",
                    (action_id,),
                )
        plan_id = _generate_campaign_plan_from_action(
            workspace_id=str(workspace_id),
            action_type=action_type,
            ctx=new_value if isinstance(new_value, dict) else {},
            entity_id=str(entity_id or ""),
            platform=platform or "meta",
        )
        final_status = "approved"
        redirect = f"/campaign-planner?ws={workspace_id}"

    elif action_type == "create_campaign":
        # Branch on platform: google → PMax via GoogleConnector, meta (default) → Meta Graph API
        _nv = new_value if isinstance(new_value, dict) else {}
        if (platform or "meta") == "google":
            launch_result = _launch_campaign_on_google(
                workspace_id=str(workspace_id),
                new_value=_nv,
            )
        else:
            launch_result = _launch_campaign_on_meta(
                workspace_id=str(workspace_id),
                new_value=_nv,
                platform=platform or "meta",
            )
        if launch_result.get("ok"):
            import json as _json2
            # Merge meta/google IDs back into new_value so publish-ad can use them later
            _nv_updated = dict(_nv)
            _nv_updated["meta_campaign_id"]  = launch_result.get("meta_campaign_id")
            _nv_updated["meta_adset_id"]     = launch_result.get("meta_adset_id")
            _nv_updated["google_campaign_id"]= launch_result.get("google_campaign_id")
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE action_log SET status='executed', new_value=%s::jsonb, approved_by='dashboard', executed_at=NOW() WHERE id=%s",
                        (_json2.dumps(_nv_updated), action_id),
                    )
            final_status = "executed"
            success = True
        else:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE action_log SET status='failed', approved_by='dashboard', executed_at=NOW() WHERE id=%s",
                        (action_id,),
                    )
            final_status = "failed"
            success = False
        redirect = "/campaigns"

    elif action_type == "keyword_addition":
        # Try to add the keyword via GoogleConnector; fall back to "approved" with a note
        if platform == "google" and entity_id:
            _gconn = _get_google_conn_from_db(str(workspace_id))
            if _gconn:
                _gws = get_workspace(str(workspace_id)) or {"id": str(workspace_id)}
                from services.agent_swarm.connectors.google import GoogleConnector as _GC
                try:
                    _gc = _GC(_gconn, _gws)
                    _kw = (
                        (new_value or {}).get("keyword")
                        or (new_value or {}).get("suggested_value")
                        or ""
                    ).strip()
                    if _kw:
                        _kr = _gc.add_keyword(str(entity_id), _kw)
                        if _kr.get("ok"):
                            final_status = "executed"
                            execution_note = f"Keyword \"{_kw}\" added to ad group in Google Ads"
                        else:
                            execution_note = "Approved — add manually in Google Ads (developer token pending approval)"
                    else:
                        execution_note = "Approved — add keywords manually in Google Ads → Campaigns"
                except Exception:
                    execution_note = "Approved — keyword queued for manual addition in Google Ads"
            else:
                execution_note = "Approved — connect Google Ads in Settings to auto-add keywords"
        else:
            execution_note = "Approved — add keywords manually in Google Ads"
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE action_log SET status=%s, approved_by='dashboard', executed_at=NOW() WHERE id=%s",
                    (final_status, action_id),
                )
        redirect = "/google-ads"

    else:
        # geographic_expansion, bid_adjustment, review, etc.
        if action_type == "bid_adjustment" and platform == "google" and entity_id:
            _gconn = _get_google_conn_from_db(str(workspace_id))
            if _gconn:
                _gws = get_workspace(str(workspace_id)) or {"id": str(workspace_id)}
                from services.agent_swarm.connectors.google import GoogleConnector as _GC
                try:
                    _gc = _GC(_gconn, _gws)
                    _bid_inr = float((new_value or {}).get("suggested_value") or (new_value or {}).get("new_bid_inr") or 0)
                    if _bid_inr > 0:
                        _br = _gc.adjust_bid(str(entity_id), int(_bid_inr * 1_000_000))
                        if _br.get("ok"):
                            final_status = "executed"
                            execution_note = f"Bid adjusted to ₹{_bid_inr:.2f} in Google Ads"
                        else:
                            execution_note = "Approved — update bid manually in Google Ads (developer token pending approval)"
                    else:
                        execution_note = "Approved — update bid manually in Google Ads"
                except Exception:
                    execution_note = "Approved — update bid manually in Google Ads"
            else:
                execution_note = "Approved — connect Google Ads in Settings to auto-adjust bids"
        elif action_type == "geographic_expansion":
            execution_note = "Approved — update geo targeting in Google Ads: Campaigns → Settings → Locations"
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE action_log SET status=%s, approved_by='dashboard', executed_at=NOW() WHERE id=%s",
                    (final_status, action_id),
                )
        redirect = "/campaigns"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pending_approvals SET status=%s, responded_at=NOW(), response='YES' WHERE action_log_id=%s",
                (final_status, action_id),
            )

    return {
        "ok": True,
        "decision": "approved",
        "executed": success,
        "status": final_status,
        "action_id": str(action_id),
        "redirect": redirect,
        "plan_id": plan_id,
        "platform": platform or "meta",
        # Populated only for create_campaign approvals
        "campaign_created": launch_result.get("ok") if launch_result else False,
        "campaign_name": launch_result.get("campaign_name") if launch_result else None,
        "adset_name": launch_result.get("adset_name") if launch_result else None,
        "google_campaign_id": launch_result.get("google_campaign_id") if launch_result else None,
        "launch_error": launch_result.get("error") if launch_result and not launch_result.get("ok") else None,
        # Populated for keyword/geo/bid actions
        "execution_note": execution_note,
    }


# ── Sales Intelligence Layer ────────────────────────────────

@app.post("/cron/sales-strategy")
async def sales_strategy(request: Request):
    """
    Full sales intelligence pipeline for ALL active tenants: deep FB analysis +
    competitor intel + LP audit → Claude Opus diagnosis → action plan → WhatsApp report.
    Runs every 6h via Cloud Scheduler. Runs synchronously (blocking) so Cloud Run
    does not kill it before completion. Cloud Scheduler timeout must be >= 10 min.
    Body: {phone_number_id?} — if provided, runs for that tenant only (manual trigger).
    """
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    import asyncio
    from services.agent_swarm.agents.sales_strategist import run_sales_strategy

    # If a specific phone_number_id is given, run for that tenant only
    if body.get("phone_number_id"):
        tenant = _resolve_tenant(body)
        account_id = _account_id(tenant)
        # Run synchronously in thread pool — blocks until complete so Cloud Run
        # keeps the container alive for the full duration of the pipeline.
        result = await asyncio.to_thread(run_sales_strategy, PLATFORM, account_id, tenant)
        return {
            "ok": True, "status": "completed", "mode": "single",
            "tenant_id": tenant["id"], "account_id": account_id,
            "result": result,
        }

    # Otherwise loop ALL active tenants sequentially
    tenants = _get_all_active_tenants()
    all_results = []
    for tenant in tenants:
        account_id = _account_id(tenant)
        try:
            result = await asyncio.to_thread(run_sales_strategy, PLATFORM, account_id, tenant)
            all_results.append({"tenant": tenant.get("name", "?"), "result": result})
        except Exception as e:
            all_results.append({"tenant": tenant.get("name", "?"), "error": str(e)})

    return {
        "ok": True, "status": "completed", "mode": "all_tenants",
        "tenants_processed": len(all_results),
        "results": all_results,
    }


@app.post("/cron/ugc-gen")
async def ugc_gen(request: Request):
    """
    Generate UGC video ads (HeyGen testimonial + Kling lifestyle).
    Runs synchronously via asyncio.to_thread — Cloud Run won't kill it.
    Body: {phone_number_id?}
    """
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    import asyncio
    from services.agent_swarm.agents.ugc_generator import run_ugc_generator

    tenant = _resolve_tenant(body)
    account_id = _account_id(tenant)
    budget = float(body.get("daily_budget_inr", 300))

    result = await asyncio.to_thread(run_ugc_generator, PLATFORM, account_id, tenant, budget)
    return {
        "ok": result.get("ok", False),
        "status": "completed",
        "videos_generated": result.get("videos_generated", 0),
        "results": result.get("results", []),
        "errors": result.get("errors", []),
    }


@app.post("/approval/video")
async def handle_video_approval(request: Request):
    """
    Called by wa-bot when admin replies 'approve video XXXXXXXX' or 'reject video XXXXXXXX'.
    On approve: upload video to Meta → create video ad campaign.
    Body: {video_id, decision, phone_number_id?}
    """
    body = await request.json()
    video_short_id = body.get("video_id", "").strip().lower()
    decision = body.get("decision", "").strip().lower()

    if not video_short_id or decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Invalid payload")

    tenant = _resolve_tenant(body)
    wa_report = tenant.get("admin_wa_id", WA_REPORT_NUMBER)

    from services.agent_swarm.db import get_conn
    from services.agent_swarm.wa import send_text

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, angle, headline, status
                   FROM video_queue
                   WHERE id::text LIKE %s AND status='pending_approval'
                   ORDER BY created_at DESC LIMIT 1""",
                (f"{video_short_id}%",),
            )
            row = cur.fetchone()

    if not row:
        return {"ok": False, "error": "Video not found or already processed"}

    video_db_id, angle, headline, status = row

    if decision == "reject":
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE video_queue SET status='rejected', updated_at=NOW() WHERE id=%s",
                    (video_db_id,),
                )
        send_text(wa_report, f"❌ Video '{angle}' rejected.", tenant)
        return {"ok": True, "decision": "rejected", "video_id": str(video_db_id)}

    send_text(wa_report, f"✅ Video '{angle}' approved! Uploading to Meta now...", tenant)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE video_queue SET status='publishing', updated_at=NOW() WHERE id=%s",
                (video_db_id,),
            )

    from services.agent_swarm.creative.meta_publisher import publish_video_ad
    result = publish_video_ad(str(video_db_id), tenant=tenant)

    if result["ok"]:
        send_text(
            wa_report,
            f"🚀 *Video Ad Published!*\n"
            f"Campaign: {result.get('campaign_id')}\n"
            f"Budget: ₹{result.get('daily_budget_inr', 300)}/day\n"
            f"Creative: '{angle}' — {headline}",
            tenant,
        )
    else:
        send_text(
            wa_report,
            f"⚠️ Publish failed for '{angle}': {result.get('error', 'unknown error')[:200]}",
            tenant,
        )

    return result


@app.post("/comment/reply")
async def handle_comment_reply(request: Request):
    """
    Called by wa-bot for: 'auto reply <id>', 'reply comment <id>: text', 'skip comment <id>'.
    Body: {comment_id, action, reply_text?, phone_number_id?}
      action: auto_reply | manual_reply | skip
    """
    body = await request.json()
    comment_short_id = (body.get("comment_id") or "").strip().lower()
    action = (body.get("action") or "").strip().lower()
    reply_text = (body.get("reply_text") or "").strip()
    tenant = _resolve_tenant(body)
    wa_report = tenant.get("admin_wa_id", WA_REPORT_NUMBER)

    if not comment_short_id or action not in ("auto_reply", "manual_reply", "skip"):
        raise HTTPException(status_code=400, detail="comment_id and valid action required")

    from services.agent_swarm.db import get_conn
    from services.agent_swarm.wa import send_text

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, comment_id, comment_text, commenter_name,
                          suggested_reply, status, ad_id
                   FROM comment_replies
                   WHERE id::text LIKE %s AND status='pending'
                   ORDER BY first_seen_at DESC LIMIT 1""",
                (f"{comment_short_id}%",),
            )
            row = cur.fetchone()

    if not row:
        send_text(wa_report, f"Comment {comment_short_id} not found or already handled.", tenant)
        return {"ok": False, "error": "Comment not found or already handled"}

    db_id, meta_comment_id, comment_text, commenter, suggested_reply, status, ad_id = row

    if action == "skip":
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE comment_replies SET status='skipped', updated_at=NOW() WHERE id=%s",
                    (db_id,),
                )
        send_text(wa_report, f"Skipped comment from {commenter}.", tenant)
        return {"ok": True, "action": "skipped"}

    # Determine final reply text
    final_reply = reply_text if action == "manual_reply" else suggested_reply
    if not final_reply:
        send_text(wa_report, "No reply text available. Use: reply comment <id>: your text", tenant)
        return {"ok": False, "error": "No reply text"}

    import asyncio
    from services.agent_swarm.creative.meta_publisher import post_comment_reply

    try:
        meta_reply_id = await asyncio.to_thread(post_comment_reply, meta_comment_id, final_reply, tenant)
        replied_by = "whatsapp_manual" if action == "manual_reply" else "whatsapp_auto"
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE comment_replies
                       SET status='replied', reply_text=%s, replied_at=NOW(),
                           replied_by=%s, meta_reply_id=%s, updated_at=NOW()
                       WHERE id=%s""",
                    (final_reply, replied_by, meta_reply_id, db_id),
                )
        send_text(
            wa_report,
            f"Replied to {commenter}:\n\"{final_reply}\"",
            tenant,
        )
        return {"ok": True, "action": action, "meta_reply_id": meta_reply_id}
    except Exception as e:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE comment_replies SET status='failed', updated_at=NOW() WHERE id=%s",
                    (db_id,),
                )
        send_text(wa_report, f"Failed to reply to comment: {str(e)[:150]}", tenant)
        return {"ok": False, "error": str(e)}


@app.post("/comment/pending")
async def list_pending_comments(request: Request):
    """Return pending comments for a tenant (for wa-bot to show summary)."""
    _auth(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    tenant = _resolve_tenant(body)
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, ad_id, commenter_name, comment_text,
                          objection_type, suggested_reply, first_seen_at
                   FROM comment_replies
                   WHERE platform=%s AND account_id=%s AND status='pending'
                   ORDER BY first_seen_at DESC LIMIT 20""",
                ("meta", _account_id(tenant)),
            )
            rows = cur.fetchall()
    return {
        "pending": [
            {
                "short_id": str(r[0])[:8],
                "ad_id": str(r[1])[:10] if r[1] else "",
                "commenter": r[2] or "Unknown",
                "text": (r[3] or "")[:120],
                "type": r[4],
                "suggested_reply": (r[5] or "")[:150],
                "seen_at": str(r[6]),
            }
            for r in rows
        ]
    }


@app.post("/strategy/chat")
async def strategy_chat(request: Request):
    """
    Conversational strategy endpoint. Routes unrecognized WhatsApp messages
    through Claude with full strategy context so users can discuss, ask questions,
    and get implementation guidance directly in WhatsApp.
    """
    _auth(request)
    body = await request.json()
    message = (body.get("message") or "").strip()
    phone_number_id = body.get("phone_number_id", "")

    if not message:
        return {"ok": False, "error": "message is required"}

    tenant = _resolve_tenant(body) if phone_number_id else _get_all_active_tenants()[0]
    if not tenant:
        return {"ok": False, "reply": "No account found. Contact support."}

    tenant_id = tenant.get("id") or _DEFAULT_TENANT_ID

    # Fetch latest strategy + actions from DB
    strategy_row = None
    actions = []
    try:
        from services.agent_swarm.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, diagnosis, competitive_insights, forecast,
                              whatsapp_summary, created_at
                       FROM sales_strategies
                       WHERE tenant_id=%s
                       ORDER BY created_at DESC LIMIT 1""",
                    (tenant_id,),
                )
                strategy_row = cur.fetchone()
                if strategy_row:
                    strategy_id = strategy_row[0]
                    cur.execute(
                        """SELECT id, tier, priority, action_type, title,
                                  description, estimated_revenue_impact, status
                           FROM strategy_actions
                           WHERE strategy_id=%s ORDER BY priority""",
                        (strategy_id,),
                    )
                    for r in cur.fetchall():
                        actions.append({
                            "short_id": str(r[0])[:8],
                            "tier": r[1], "priority": r[2],
                            "type": r[3], "title": r[4],
                            "description": r[5],
                            "impact": r[6], "status": r[7],
                        })
    except Exception as e:
        print(f"strategy_chat: DB fetch failed: {e}")

    if not strategy_row:
        return {
            "ok": True,
            "reply": (
                "📊 No strategy report yet — I haven't run a full analysis for your account.\n\n"
                "The Sales Intelligence report runs automatically every 6 hours. "
                "Or ask me anything about your ad performance and I'll help! 💬"
            ),
        }

    diag = strategy_row[1] or {}
    comp_insights = strategy_row[2] or ""
    forecast = strategy_row[3] or ""
    summary = strategy_row[4] or ""
    created_at = strategy_row[5]
    report_time = created_at.strftime("%d %b %Y, %I:%M %p") if created_at else "recently"

    pending_actions = [a for a in actions if a["status"] in ("pending", "approved")]
    action_summary = "\n".join(
        f"  [{a['short_id']}] {a['tier'].upper()} P{a['priority']}: {a['title']} "
        f"(status: {a['status']}, impact: {a.get('impact', '?')})"
        for a in actions[:10]
    )

    product_ctx = tenant.get("product_context", "")
    account_name = tenant.get("name", "your business")

    import anthropic as _anthropic
    from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = (
        f"You are the AI ads manager for *{account_name}*. "
        "You help the business owner manage their Facebook ads strategy directly via WhatsApp. "
        "Be conversational, concise, and WhatsApp-friendly (max 600 chars per reply, use emojis naturally). "
        "Be direct and actionable — this is a busy founder on their phone.\n\n"
        f"LATEST STRATEGY REPORT ({report_time}):\n"
        f"Summary: {summary}\n"
        f"Root cause: {(diag or {}).get('primary_root_cause', 'N/A')}\n"
        f"Forecast: {forecast}\n"
        f"Competitor insights: {comp_insights}\n\n"
        f"ALL ACTIONS:\n{action_summary or 'No actions yet.'}\n\n"
        f"Product: {product_ctx[:300]}\n\n"
        "RULES:\n"
        "- To approve an action: tell user to type `approve strategy <short_id>`\n"
        "- To reject: `reject strategy <short_id>`\n"
        "- If user asks what to do next: prioritize pending approval-tier actions first\n"
        "- If user asks to implement something: give them the exact command\n"
        "- If asked for more detail: expand on that specific action\n"
        "- If unrelated to ads/strategy: still help but gently refocus\n"
        "- Keep replies under 600 chars for WhatsApp"
    )

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": message}],
            system=system_prompt,
        )
        reply = resp.content[0].text.strip()
        return {"ok": True, "reply": reply}
    except Exception as e:
        print(f"strategy_chat: Claude call failed: {e}")
        return {
            "ok": True,
            "reply": "⚠️ Couldn't process that right now. Try again in a moment.",
        }


@app.post("/strategy/action/approve")
async def approve_strategy_action(request: Request):
    """
    Called by wa-bot when admin replies 'approve strategy XXXXXXXX'.
    Body: {action_id, decision, phone_number_id?}
    """
    body = await request.json()
    action_short_id = body.get("action_id", "").strip()
    decision = body.get("decision", "").strip().lower()
    if not action_short_id or decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Invalid payload")

    tenant = _resolve_tenant(body)
    account_id = _account_id(tenant)

    from services.agent_swarm.agents.sales_strategist import handle_strategy_approval
    return handle_strategy_approval(
        action_short_id,
        approved=(decision == "approve"),
        tenant=tenant,
        platform=PLATFORM,
        account_id=account_id,
    )


@app.post("/strategy/approve-by-numbers")
async def approve_strategy_by_numbers(request: Request):
    """
    Approve/reject strategy actions by priority number.
    Body: {numbers: [5,6,7,8], decision: 'approve'|'reject', phone_number_id?}
    """
    body = await request.json()
    numbers = [int(n) for n in body.get("numbers", [])]
    decision = body.get("decision", "approve").strip().lower()
    tenant = _resolve_tenant(body)
    account_id = _account_id(tenant)

    if not numbers:
        raise HTTPException(status_code=400, detail="numbers list is required")

    from services.agent_swarm.agents.sales_strategist import handle_strategy_approval_by_numbers
    result = handle_strategy_approval_by_numbers(
        numbers,
        approved=(decision == "approve"),
        tenant=tenant,
        platform=PLATFORM,
        account_id=account_id,
    )
    return result


@app.post("/strategy/bulk-approve")
async def bulk_approve_strategy(request: Request):
    """
    Bulk-approve all pending 'approval' tier actions for the latest strategy.
    Called by wa-bot when admin sends 'approve all strategy'.
    Body: {decision: 'approve', phone_number_id?}
    """
    body = await request.json()
    decision = body.get("decision", "approve").strip().lower()
    tenant = _resolve_tenant(body)
    tenant_id = tenant["id"]
    account_id = _account_id(tenant)

    from services.agent_swarm.db import get_conn
    from services.agent_swarm.agents.sales_strategist import handle_strategy_approval
    from services.agent_swarm.wa import send_text

    # Find all pending approval-tier actions for latest strategy
    pending = []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sa.id
                    FROM strategy_actions sa
                    JOIN sales_strategies ss ON ss.id = sa.strategy_id
                    WHERE sa.tenant_id = %s
                      AND sa.tier = 'approval'
                      AND sa.status = 'pending'
                    ORDER BY ss.created_at DESC, sa.priority ASC
                    LIMIT 20
                    """,
                    (tenant_id,),
                )
                pending = [str(row[0]) for row in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not pending:
        wa_num = tenant.get("admin_wa_id") or WA_REPORT_NUMBER
        send_text(wa_num, "✅ No pending approval actions to process.", tenant)
        return {"ok": True, "processed": 0}

    results = []
    for action_id in pending:
        short_id = action_id[:8]
        res = handle_strategy_approval(
            short_id,
            approved=(decision == "approve"),
            tenant=tenant,
            platform=PLATFORM,
            account_id=account_id,
        )
        results.append({"action_id": short_id, **res})

    approved_count = sum(1 for r in results if r.get("status") in ("executed", "approved", "rejected"))
    return {"ok": True, "processed": len(results), "results": results}


@app.get("/strategy/latest")
async def get_latest_strategy(
    request: Request,
    phone_number_id: str = None,
):
    """Return the latest sales strategy for a tenant."""
    _auth(request)
    tenant = _get_tenant(phone_number_id or WA_PHONE_NUMBER_ID) or _default_tenant()
    tenant_id = tenant["id"]
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, diagnosis, competitive_insights, forecast,
                       whatsapp_summary, status, created_at
                FROM sales_strategies
                WHERE tenant_id=%s
                ORDER BY created_at DESC LIMIT 1
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
    if not row:
        return {"strategy": None}
    strategy_id = str(row[0])
    # Fetch actions for this strategy
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tier, priority, action_type, title, status,
                       execute_result, LEFT(id::TEXT, 8) as short_id
                FROM strategy_actions
                WHERE strategy_id=%s
                ORDER BY priority
                """,
                (strategy_id,),
            )
            actions = [
                {
                    "tier": r[0], "priority": r[1], "action_type": r[2],
                    "title": r[3], "status": r[4], "result": r[5],
                    "short_id": r[6],
                }
                for r in cur.fetchall()
            ]
    return {
        "strategy": {
            "id": strategy_id,
            "diagnosis": row[1],
            "competitive_insights": row[2],
            "forecast": row[3],
            "summary": row[4],
            "status": row[5],
            "created_at": str(row[6]),
        },
        "actions": actions,
    }


# ── Google Ads endpoints ───────────────────────────────────────────────────

def _get_google_conn_from_db(workspace_id: str) -> dict | None:
    """
    Load Google credentials from google_auth_tokens and return a connection
    dict compatible with GoogleConnector (credentials in metadata).
    """
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT customer_id, merchant_id, developer_token,
                       client_id, client_secret, refresh_token,
                       access_token, login_customer_id
                FROM google_auth_tokens
                WHERE workspace_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    (customer_id, merchant_id, developer_token,
     client_id, client_secret, refresh_token,
     access_token, login_customer_id) = row
    return {
        "platform": "google",
        "account_id": customer_id,
        "customer_id": customer_id,
        "merchant_id": merchant_id,
        "login_customer_id": login_customer_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "is_primary": True,
        "metadata": {
            "developer_token": developer_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "customer_id": customer_id,
            "merchant_id": merchant_id,
            "login_customer_id": login_customer_id,
        },
    }


@app.post("/google/connect")
async def google_connect(request: Request):
    """
    Store / update Google Ads OAuth2 credentials for a workspace.

    Body:
    {
      "workspace_id": "uuid",
      "customer_id": "1234567890",          -- no dashes
      "merchant_id": "optional",
      "developer_token": "...",
      "client_id": "...",
      "client_secret": "...",
      "refresh_token": "...",
      "login_customer_id": "optional MCC"
    }
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    customer_id = body.get("customer_id", "").replace("-", "")
    if not workspace_id or not customer_id:
        raise HTTPException(status_code=400, detail="workspace_id and customer_id are required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO google_auth_tokens
                    (workspace_id, customer_id, merchant_id,
                     developer_token, client_id, client_secret,
                     refresh_token, login_customer_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (workspace_id, customer_id)
                DO UPDATE SET
                    merchant_id       = EXCLUDED.merchant_id,
                    developer_token   = EXCLUDED.developer_token,
                    client_id         = EXCLUDED.client_id,
                    client_secret     = EXCLUDED.client_secret,
                    refresh_token     = EXCLUDED.refresh_token,
                    login_customer_id = EXCLUDED.login_customer_id,
                    updated_at        = NOW()
                """,
                (
                    workspace_id, customer_id,
                    body.get("merchant_id") or None,
                    body.get("developer_token", ""),
                    body.get("client_id", ""),
                    body.get("client_secret", ""),
                    body.get("refresh_token", ""),
                    body.get("login_customer_id") or None,
                ),
            )
    return {"ok": True, "workspace_id": workspace_id, "customer_id": customer_id}


@app.get("/google/debug-customers")
async def google_debug_customers(request: Request, workspace_id: str = None):
    """
    Diagnostic: list all accessible Google Ads customers for a workspace
    and show which are manager (MCC) vs real ad accounts.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Google credentials found")

    import json as _json, requests as rq
    from services.agent_swarm import config as cfg
    from services.agent_swarm.connectors.google import GoogleConnector
    workspace = get_workspace(workspace_id) or {}

    gc = GoogleConnector(conn_row, workspace)
    try:
        access_token = gc._refresh_access_token()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {e}")

    developer_token = conn_row.get("metadata", {}).get("developer_token", "")

    # List all accessible customers
    ads_resp = rq.get(
        f"https://googleads.googleapis.com/{cfg.GOOGLE_ADS_API_VERSION}"
        "/customers:listAccessibleCustomers",
        headers={"Authorization": f"Bearer {access_token}", "developer-token": developer_token},
        timeout=15,
    )
    if not ads_resp.ok:
        raise HTTPException(status_code=502, detail=f"Google API error: {ads_resp.status_code} {ads_resp.text[:300]}")

    resource_names = ads_resp.json().get("resourceNames", [])
    candidates = [r.split("/")[-1] for r in resource_names]

    # Check each candidate — try both with and without login-customer-id headers
    details = []
    for cid in candidates:
        info = {"customer_id": cid, "tries": []}
        # Try 1: no login-customer-id
        # Try 2+: each other candidate as login-customer-id
        for login_cid in [None] + [c for c in candidates if c != cid]:
            hdr = {
                "Authorization": f"Bearer {access_token}",
                "developer-token": developer_token,
                "Content-Type": "application/json",
            }
            if login_cid:
                hdr["login-customer-id"] = login_cid
            try:
                qr = rq.post(
                    f"https://googleads.googleapis.com/{cfg.GOOGLE_ADS_API_VERSION}"
                    f"/customers/{cid}/googleAds:searchStream",
                    headers=hdr,
                    json={"query": "SELECT customer.id, customer.manager, customer.descriptive_name, customer.currency_code FROM customer LIMIT 1"},
                    timeout=10,
                )
                attempt = {"login_customer_id": login_cid, "status": qr.status_code}
                if qr.ok:
                    attempt["success"] = True
                    for line in qr.text.strip().splitlines():
                        try:
                            batch = _json.loads(line)
                            for result_row in batch.get("results", []):
                                cust = result_row.get("customer", {})
                                attempt["manager"] = cust.get("manager", None)
                                attempt["name"] = cust.get("descriptiveName", "")
                                attempt["currency"] = cust.get("currencyCode", "")
                        except Exception:
                            pass
                else:
                    # Parse Google Ads error code for diagnosis
                    try:
                        err_body = _json.loads(qr.text)
                        err_details = err_body[0].get("error", {}).get("details", []) if isinstance(err_body, list) else err_body.get("error", {}).get("details", [])
                        for d in err_details:
                            for e in d.get("errors", []):
                                err_code = e.get("errorCode", {})
                                if err_code:
                                    attempt["ads_error_code"] = err_code
                    except Exception:
                        attempt["raw_error"] = qr.text[:500]
                info["tries"].append(attempt)
                if qr.ok:
                    break  # found a working combo for this customer
            except Exception as ce:
                info["tries"].append({"login_customer_id": login_cid, "exception": str(ce)})
        details.append(info)

    current_id = conn_row.get("customer_id")
    return {
        "current_customer_id": current_id,
        "all_candidates": candidates,
        "details": details,
    }


@app.get("/google/accessible-customers")
async def google_accessible_customers(request: Request, workspace_id: str = None):
    """List all accessible Google Ads accounts for the account switcher UI."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Google credentials found")

    import json as _json, requests as rq
    from services.agent_swarm import config as cfg
    from services.agent_swarm.connectors.google import GoogleConnector
    workspace = get_workspace(workspace_id) or {}

    gc = GoogleConnector(conn_row, workspace)
    try:
        access_token = gc._refresh_access_token()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {e}")

    developer_token = conn_row.get("metadata", {}).get("developer_token", "") or cfg.GOOGLE_DEVELOPER_TOKEN

    # List accessible customers
    ads_resp = rq.get(
        f"https://googleads.googleapis.com/{cfg.GOOGLE_ADS_API_VERSION}/customers:listAccessibleCustomers",
        headers={"Authorization": f"Bearer {access_token}", "developer-token": developer_token},
        timeout=15,
    )
    if not ads_resp.ok:
        raise HTTPException(status_code=502, detail=f"Google API error: {ads_resp.status_code} {ads_resp.text[:300]}")

    resource_names = ads_resp.json().get("resourceNames", [])
    candidates = [r.split("/")[-1] for r in resource_names]

    current_cid = str(conn_row.get("customer_id") or "")
    accounts = []
    for cid in candidates:
        name = cid  # default — shown if GAQL fails (test token)
        is_manager = False
        # Try GAQL for descriptive name; fails gracefully with test developer token
        try:
            gaql_resp = rq.post(
                f"https://googleads.googleapis.com/{cfg.GOOGLE_ADS_API_VERSION}"
                f"/customers/{cid}/googleAds:searchStream",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "developer-token": developer_token,
                    "login-customer-id": cid,
                    "Content-Type": "application/json",
                },
                json={"query": "SELECT customer.id, customer.descriptive_name, customer.manager FROM customer LIMIT 1"},
                timeout=10,
            )
            if gaql_resp.status_code == 200:
                for line in gaql_resp.text.strip().splitlines():
                    try:
                        batch = _json.loads(line)
                        for result_row in batch.get("results", []):
                            customer = result_row.get("customer", {})
                            name = customer.get("descriptiveName", cid) or cid
                            is_manager = customer.get("manager", False)
                    except Exception:
                        pass
        except Exception:
            pass
        accounts.append({
            "customer_id": cid,
            "name": name,
            "is_manager": is_manager,
            "is_current": cid == current_cid,
        })

    return {"workspace_id": workspace_id, "current_customer_id": current_cid, "accounts": accounts}


@app.post("/google/select-customer")
async def google_select_customer(request: Request):
    """Update the active Google Ads customer_id for a workspace (account switcher)."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    customer_id = body.get("customer_id")
    if not workspace_id or not customer_id:
        raise HTTPException(status_code=400, detail="workspace_id and customer_id required")
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE google_auth_tokens SET customer_id=%s, updated_at=NOW() WHERE workspace_id=%s",
                (str(customer_id), workspace_id),
            )
        conn.commit()
    return {"ok": True, "customer_id": customer_id}


@app.post("/google/rediscover-customer")
async def google_rediscover_customer(request: Request):
    """
    Re-discover the correct Google Ads customer_id using the stored refresh token.
    Prefers non-manager (real ad) accounts over manager (MCC) accounts.
    Updates google_auth_tokens in the DB.
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Google credentials found")

    import json as _json, requests as rq
    from services.agent_swarm import config as cfg
    from services.agent_swarm.connectors.google import GoogleConnector
    workspace = get_workspace(workspace_id) or {}

    gc = GoogleConnector(conn_row, workspace)
    try:
        access_token = gc._refresh_access_token()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Token refresh failed: {e}")

    developer_token = conn_row.get("metadata", {}).get("developer_token", "")

    # List all accessible customers
    ads_resp = rq.get(
        f"https://googleads.googleapis.com/{cfg.GOOGLE_ADS_API_VERSION}"
        "/customers:listAccessibleCustomers",
        headers={"Authorization": f"Bearer {access_token}", "developer-token": developer_token},
        timeout=15,
    )
    if not ads_resp.ok:
        raise HTTPException(status_code=502, detail=f"Google API error: {ads_resp.status_code}")

    resource_names = ads_resp.json().get("resourceNames", [])
    candidates = [r.split("/")[-1] for r in resource_names]

    non_managers, managers = [], []
    for cid in candidates:
        try:
            qr = rq.post(
                f"https://googleads.googleapis.com/{cfg.GOOGLE_ADS_API_VERSION}"
                f"/customers/{cid}/googleAds:searchStream",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "developer-token": developer_token,
                    "Content-Type": "application/json",
                },
                json={"query": "SELECT customer.id, customer.manager, customer.descriptive_name FROM customer LIMIT 1"},
                timeout=10,
            )
            if qr.ok:
                for line in qr.text.strip().splitlines():
                    try:
                        batch = _json.loads(line)
                        for result_row in batch.get("results", []):
                            is_mgr = result_row.get("customer", {}).get("manager", False)
                            (managers if is_mgr else non_managers).append(cid)
                    except Exception:
                        pass
        except Exception:
            pass

    new_customer_id = (non_managers or managers or candidates[:1] or [None])[0]
    if not new_customer_id:
        raise HTTPException(status_code=422, detail="No accessible customer IDs found")

    old_customer_id = conn_row.get("customer_id")

    from services.agent_swarm.db import get_conn as _db
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE google_auth_tokens SET customer_id = %s, updated_at = NOW() WHERE workspace_id = %s",
                (new_customer_id, workspace_id),
            )

    return {
        "ok": True,
        "workspace_id": workspace_id,
        "old_customer_id": old_customer_id,
        "new_customer_id": new_customer_id,
        "all_candidates": candidates,
        "non_managers": non_managers,
        "managers": managers,
        "updated": old_customer_id != new_customer_id,
    }


@app.get("/google/campaigns")
async def google_list_campaigns(request: Request, workspace_id: str = None):
    """List active Google campaigns for a workspace."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        return {"campaigns": [], "error": "No Google connection configured"}

    from services.agent_swarm.connectors.google import GoogleConnector
    gc = GoogleConnector(conn_row, workspace)
    campaigns = gc.list_campaigns()
    return {"campaigns": campaigns}


@app.get("/google/campaign-insights/{campaign_id}")
async def google_campaign_insights(request: Request, campaign_id: str, workspace_id: str = None, days: int = 7):
    """Fetch per-campaign insights + AI suggestions for a Google campaign."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Google connection configured")

    import json
    from datetime import datetime, timedelta
    from services.agent_swarm.connectors.google import GoogleConnector
    gc = GoogleConnector(conn_row, workspace)

    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    until = datetime.utcnow().strftime("%Y-%m-%d")
    today = datetime.utcnow().strftime("%Y-%m-%d")

    snapshots = gc.fetch_metrics(since, until, entity_level="campaign")
    campaign_snaps = [s for s in snapshots if str(s.entity_id) == str(campaign_id)]

    # Aggregate totals
    spend_total = sum(s.spend for s in campaign_snaps)
    spend_today = sum(s.spend for s in campaign_snaps if s.hour_ts.startswith(today))
    impressions_total = sum(s.impressions for s in campaign_snaps)
    clicks_total = sum(s.clicks for s in campaign_snaps)
    conversions_total = sum(s.conversions for s in campaign_snaps)
    revenue_total = sum(s.revenue for s in campaign_snaps)
    roas_total = round(revenue_total / spend_total, 4) if spend_total > 0 else 0.0
    ctr_total = round(clicks_total / impressions_total * 100, 4) if impressions_total > 0 else 0.0

    # Daily spend for chart
    daily_map: dict[str, float] = {}
    for s in campaign_snaps:
        d = s.hour_ts[:10]
        daily_map[d] = daily_map.get(d, 0) + s.spend
    daily = [{"date": d, "spend": round(v, 2)} for d, v in sorted(daily_map.items())]

    # Claude AI suggestions
    suggestions = []
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = (
            f"Google Ads campaign '{campaign_id}' last {days} days:\n"
            f"Spend: ₹{spend_total:.0f}, ROAS: {roas_total:.2f}x, "
            f"Impressions: {impressions_total:,}, Clicks: {clicks_total:,}, "
            f"CTR: {ctr_total:.2f}%, Conversions: {conversions_total}, Revenue: ₹{revenue_total:.0f}\n"
            f"Target ROAS: 2.5x. Give exactly 3 short, actionable improvement suggestions. "
            f"Numbered list only, no extra text."
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        suggestions = [
            line.lstrip("0123456789.-) ").strip()
            for line in text.splitlines()
            if line.strip() and line[0].isdigit()
        ][:3]
    except Exception as e:
        print(f"Google campaign insights Claude error: {e}")

    return {
        "campaign_id": campaign_id,
        "spend_today": round(spend_today, 2),
        "spend_total": round(spend_total, 2),
        "impressions_total": impressions_total,
        "clicks_total": clicks_total,
        "conversions_total": conversions_total,
        "revenue_total": round(revenue_total, 2),
        "roas_total": roas_total,
        "ctr_total": ctr_total,
        "daily": daily,
        "suggestions": suggestions,
    }


@app.post("/google/campaign/pause")
async def google_pause_campaign(request: Request):
    """Pause a Google campaign or ad group."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    entity_id = body.get("entity_id")  # campaign resource name or numeric ID
    if not workspace_id or not entity_id:
        raise HTTPException(status_code=400, detail="workspace_id and entity_id required")

    workspace = get_workspace(workspace_id)
    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Google connection")

    from services.agent_swarm.connectors.google import GoogleConnector
    gc = GoogleConnector(conn_row, workspace)
    ok = gc.pause(entity_id)
    return {"ok": ok, "entity_id": entity_id}


@app.post("/google/campaign/resume")
async def google_resume_campaign(request: Request):
    """Resume a paused Google campaign."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    entity_id = body.get("entity_id")
    if not workspace_id or not entity_id:
        raise HTTPException(status_code=400, detail="workspace_id and entity_id required")

    workspace = get_workspace(workspace_id)
    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Google connection")

    from services.agent_swarm.connectors.google import GoogleConnector
    gc = GoogleConnector(conn_row, workspace)
    ok = gc.resume(entity_id)
    return {"ok": ok, "entity_id": entity_id}


@app.post("/google/campaign/budget")
async def google_update_budget(request: Request):
    """Update daily budget for a Google campaign."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    entity_id = body.get("entity_id")
    budget_inr = body.get("daily_budget_inr")
    if not workspace_id or not entity_id or budget_inr is None:
        raise HTTPException(status_code=400, detail="workspace_id, entity_id and daily_budget_inr required")

    workspace = get_workspace(workspace_id)
    conn_row = _get_google_conn_from_db(workspace_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Google connection")

    from services.agent_swarm.connectors.google import GoogleConnector
    gc = GoogleConnector(conn_row, workspace)
    ok = gc.update_budget(entity_id, float(budget_inr))
    return {"ok": ok, "entity_id": entity_id, "daily_budget_inr": budget_inr}


@app.post("/google/merchant/sync")
async def google_merchant_sync(request: Request):
    """
    Push all active products for a workspace to Google Merchant Center.
    Body: { "workspace_id": "uuid" }
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.connectors.google_merchant import get_merchant_connector
    mc = get_merchant_connector(workspace_id)
    if not mc:
        raise HTTPException(status_code=404, detail="No Merchant Center connection for this workspace")

    result = mc.sync_workspace_products(workspace_id)
    return result


@app.post("/google/merchant/refresh-statuses")
async def google_merchant_refresh_statuses(request: Request):
    """
    Pull current Merchant Center approval statuses and write back to DB.
    Body: { "workspace_id": "uuid" }
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.connectors.google_merchant import get_merchant_connector
    mc = get_merchant_connector(workspace_id)
    if not mc:
        raise HTTPException(status_code=404, detail="No Merchant Center connection for this workspace")

    result = mc.refresh_product_statuses(workspace_id)
    return result


@app.get("/google/merchant/disapprovals")
async def google_merchant_disapprovals(request: Request, workspace_id: str = None):
    """
    Return all disapproved products with reasons for a workspace.
    Useful for the dashboard and for WhatsApp alerts.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.connectors.google_merchant import get_merchant_connector
    mc = get_merchant_connector(workspace_id)
    if not mc:
        return {"disapproved": []}

    results = mc.get_disapproval_summary(workspace_id)
    return {"disapproved": results, "count": len(results)}


@app.get("/google/search-terms")
async def google_search_terms(
    request: Request,
    workspace_id: str = None,
    days: int = 7,
    limit: int = 50,
):
    """
    Return top search terms for a workspace (from google_search_terms table).
    Sorted by spend desc.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT search_term, campaign_id, ad_group_id, match_type,
                       SUM(impressions) AS impressions,
                       SUM(clicks)      AS clicks,
                       SUM(spend)       AS spend,
                       SUM(conversions) AS conversions,
                       AVG(ctr)         AS ctr,
                       AVG(avg_cpc)     AS avg_cpc
                FROM google_search_terms
                WHERE workspace_id = %s
                  AND day >= NOW() - INTERVAL '%s days'
                GROUP BY search_term, campaign_id, ad_group_id, match_type
                ORDER BY spend DESC
                LIMIT %s
                """,
                (workspace_id, days, limit),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"search_terms": rows, "workspace_id": workspace_id, "days": days}


@app.get("/google/performance-summary")
async def google_performance_summary(
    request: Request,
    workspace_id: str = None,
    days: int = 7,
):
    """
    Return aggregated Google Ads performance (spend, impressions, clicks,
    conversions, ROAS) for the last N days.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    entity_level,
                    entity_id,
                    entity_name,
                    SUM(spend)       AS spend,
                    SUM(impressions) AS impressions,
                    SUM(clicks)      AS clicks,
                    SUM(conversions) AS conversions,
                    SUM(revenue)     AS revenue,
                    CASE WHEN SUM(spend) > 0
                         THEN ROUND(SUM(revenue)::NUMERIC / SUM(spend), 4)
                         ELSE 0 END AS roas
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND platform = 'google'
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY entity_level, entity_id, entity_name
                ORDER BY spend DESC
                LIMIT 100
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"performance": rows, "workspace_id": workspace_id, "days": days}


# ── Dashboard API: KPI Summary ────────────────────────────

@app.get("/kpi/summary")
async def kpi_summary(
    request: Request,
    workspace_id: str = None,
    days: int = 7,
):
    """
    Powers dashboard summary cards and daily charts.
    Returns aggregated KPIs + daily breakdown (meta + google) for last N days.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Daily breakdown by platform.
            # Use the most granular entity_level available per platform to avoid
            # double-counting: Meta ingests at 'ad' level, Google at 'campaign'.
            cur.execute(
                """
                SELECT platform,
                       DATE_TRUNC('day', hour_ts)::DATE AS date,
                       SUM(spend)       AS spend,
                       SUM(impressions) AS impressions,
                       SUM(clicks)      AS clicks,
                       SUM(conversions) AS conversions,
                       SUM(revenue)     AS revenue,
                       CASE WHEN SUM(spend) > 0
                            THEN ROUND(SUM(revenue)::NUMERIC / SUM(spend), 4)
                            ELSE 0 END AS roas,
                       CASE WHEN SUM(impressions) > 0
                            THEN ROUND(SUM(clicks)::NUMERIC / SUM(impressions) * 100, 4)
                            ELSE 0 END AS ctr
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                  AND (
                    (platform = 'meta'   AND entity_level IN ('ad', 'campaign'))
                    OR (platform = 'google' AND entity_level = 'campaign')
                  )
                GROUP BY platform, DATE_TRUNC('day', hour_ts)::DATE
                ORDER BY date ASC, platform
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            daily = [dict(zip(cols, r)) for r in cur.fetchall()]

            # Platform-level totals — uses the same time window as the daily chart
            # so the filter buttons actually change the numbers shown.
            # For excel-upload Google data (stored with historical hour_ts), it will
            # naturally appear when the selected window covers those dates (e.g. 90d / 365d).
            cur.execute(
                """
                SELECT platform,
                       SUM(spend)       AS spend,
                       SUM(impressions) AS impressions,
                       SUM(clicks)      AS clicks,
                       SUM(conversions) AS conversions,
                       SUM(revenue)     AS revenue,
                       CASE WHEN SUM(spend) > 0
                            THEN ROUND(SUM(revenue)::NUMERIC / SUM(spend), 4)
                            ELSE 0 END AS roas,
                       CASE WHEN SUM(impressions) > 0
                            THEN ROUND(SUM(clicks)::NUMERIC / SUM(impressions) * 100, 4)
                            ELSE 0 END AS ctr
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                  AND (
                    (platform = 'meta'   AND entity_level IN ('ad', 'campaign'))
                    OR (platform = 'google' AND entity_level = 'campaign')
                  )
                GROUP BY platform
                """,
                (workspace_id, days),
            )
            cols2 = [d[0] for d in cur.description]
            platform_rows = [dict(zip(cols2, r)) for r in cur.fetchall()]

    platform_breakdown = {r["platform"]: {k: float(v or 0) for k, v in r.items() if k != "platform"} for r in platform_rows}
    totals = {
        "spend":       sum(float(r.get("spend") or 0) for r in platform_rows),
        "impressions": sum(float(r.get("impressions") or 0) for r in platform_rows),
        "clicks":      sum(float(r.get("clicks") or 0) for r in platform_rows),
        "conversions": sum(float(r.get("conversions") or 0) for r in platform_rows),
        "revenue":     sum(float(r.get("revenue") or 0) for r in platform_rows),
    }
    total_spend = totals["spend"]
    total_rev   = totals["revenue"]
    total_impr  = totals["impressions"]
    total_click = totals["clicks"]
    totals["roas"] = round(total_rev / total_spend, 4) if total_spend > 0 else 0
    totals["ctr"]  = round(total_click / total_impr * 100, 4) if total_impr > 0 else 0
    totals["platform_breakdown"] = platform_breakdown

    # Serialise dates to ISO strings for JSON
    for row in daily:
        if hasattr(row.get("date"), "isoformat"):
            row["date"] = row["date"].isoformat()
        for k, v in row.items():
            if k not in ("platform", "date") and v is not None:
                row[k] = float(v)

    return {"summary": totals, "daily": daily, "workspace_id": workspace_id, "days": days}


# ── Dashboard API: Actions / Approval Queue ───────────────

@app.get("/actions/list")
async def actions_list(
    request: Request,
    workspace_id: str = None,
    status: str = "pending",
    limit: int = 50,
):
    """
    Return action_log rows for the approval queue.
    status: 'pending' | 'approved' | 'rejected' | 'all'
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, platform, entity_level, entity_id, action_type,
                       old_value, new_value, triggered_by, status, ts,
                       executed_at, error
                FROM action_log
                WHERE workspace_id = %s
                  AND (%s = 'all' OR status = %s)
                ORDER BY ts DESC
                LIMIT %s
                """,
                (workspace_id, status, status, limit),
            )
            cols = [d[0] for d in cur.description]
            actions = []
            for r in cur.fetchall():
                row = dict(zip(cols, r))
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                actions.append(row)

    return {"actions": actions, "count": len(actions), "workspace_id": workspace_id}


# ── Dashboard API: Meta Campaigns ─────────────────────────

@app.get("/meta/campaigns")
async def meta_list_campaigns(request: Request, workspace_id: str = None):
    """
    List ACTIVE + PAUSED Meta campaigns for a workspace.
    Normalises daily_budget (paise) → daily_budget_inr (float INR).
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    conn_row = get_primary_connection(workspace, "meta")
    if not conn_row:
        return {"campaigns": [], "error": "No Meta connection configured"}

    from services.agent_swarm.connectors.meta import MetaConnector
    mc = MetaConnector(conn_row, workspace)

    active  = mc.list_campaigns("ACTIVE")
    paused  = mc.list_campaigns("PAUSED")
    seen    = set()
    campaigns = []
    for c in active + paused:
        if c.get("id") in seen:
            continue
        seen.add(c.get("id"))
        # daily_budget from Meta is in paise (1/100 INR)
        raw_budget = c.get("daily_budget")
        c["daily_budget_inr"] = round(int(raw_budget) / 100, 2) if raw_budget else None
        campaigns.append(c)

    return {"campaigns": campaigns, "workspace_id": workspace_id}


@app.post("/meta/campaign/pause")
async def meta_pause_campaign(request: Request):
    """Pause a Meta campaign or ad set."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    entity_id    = body.get("entity_id")
    if not workspace_id or not entity_id:
        raise HTTPException(status_code=400, detail="workspace_id and entity_id required")

    workspace = get_workspace(workspace_id)
    conn_row  = get_primary_connection(workspace or {}, "meta")
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Meta connection")

    from services.agent_swarm.connectors.meta import MetaConnector
    mc = MetaConnector(conn_row, workspace)
    ok = mc.pause(entity_id)
    return {"ok": ok, "entity_id": entity_id}


@app.post("/meta/campaign/resume")
async def meta_resume_campaign(request: Request):
    """Resume a paused Meta campaign or ad set."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    entity_id    = body.get("entity_id")
    if not workspace_id or not entity_id:
        raise HTTPException(status_code=400, detail="workspace_id and entity_id required")

    workspace = get_workspace(workspace_id)
    conn_row  = get_primary_connection(workspace or {}, "meta")
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Meta connection")

    from services.agent_swarm.connectors.meta import MetaConnector
    mc = MetaConnector(conn_row, workspace)
    ok = mc.resume(entity_id)
    return {"ok": ok, "entity_id": entity_id}


@app.post("/meta/campaign/budget")
async def meta_update_budget(request: Request):
    """Update daily budget for a Meta campaign or ad set."""
    _auth(request)
    body = await request.json()
    workspace_id   = body.get("workspace_id")
    entity_id      = body.get("entity_id")
    budget_inr     = body.get("daily_budget_inr")
    if not workspace_id or not entity_id or budget_inr is None:
        raise HTTPException(status_code=400, detail="workspace_id, entity_id and daily_budget_inr required")

    workspace = get_workspace(workspace_id)
    conn_row  = get_primary_connection(workspace or {}, "meta")
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Meta connection")

    from services.agent_swarm.connectors.meta import MetaConnector
    mc = MetaConnector(conn_row, workspace)
    ok = mc.update_budget(entity_id, float(budget_inr))
    return {"ok": ok, "entity_id": entity_id, "daily_budget_inr": budget_inr}


# -- Dashboard API: Campaign Insights + AI Suggestions ------------------------------------------

@app.get("/meta/campaign-insights/{campaign_id}")
async def meta_campaign_insights(
    request: Request,
    campaign_id: str,
    workspace_id: str = None,
    days: int = 7,
):
    """
    Returns campaign performance metrics from Meta Insights API + Claude AI suggestions.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    conn_row = get_primary_connection(workspace, "meta")
    if not conn_row:
        raise HTTPException(status_code=404, detail="No Meta connection")

    import re
    import json
    import requests as req
    from datetime import date, timedelta

    access_token = conn_row.get("access_token", "")
    today = date.today()
    since = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    until = today.strftime("%Y-%m-%d")

    # Campaign details
    camp_r = req.get(
        f"{META_GRAPH}/{campaign_id}",
        params={"access_token": access_token,
                "fields": "id,name,status,effective_status,daily_budget,objective,created_time"},
        timeout=15,
    )
    campaign = camp_r.json() if camp_r.ok else {"id": campaign_id, "name": "Unknown"}

    # Daily insights for the period
    insights_r = req.get(
        f"{META_GRAPH}/{campaign_id}/insights",
        params={
            "access_token": access_token,
            "fields": "spend,impressions,clicks,actions,action_values,ctr,date_start",
            "time_increment": "1",
            "time_range": json.dumps({"since": since, "until": until}),
            "level": "campaign",
        },
        timeout=20,
    )

    daily = []
    spend_total = impressions_total = clicks_total = conversions_total = revenue_total = 0.0

    if insights_r.ok:
        for row in insights_r.json().get("data", []):
            spend = float(row.get("spend", 0) or 0)
            impressions = int(row.get("impressions", 0) or 0)
            clicks = int(row.get("clicks", 0) or 0)
            ctr = float(row.get("ctr", 0) or 0)
            conversions = sum(
                int(a.get("value", 0) or 0)
                for a in (row.get("actions") or [])
                if a.get("action_type") in ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase")
            )
            revenue = sum(
                float(a.get("value", 0) or 0)
                for a in (row.get("action_values") or [])
                if a.get("action_type") in ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase")
            )
            roas = round(revenue / spend, 4) if spend > 0 else 0.0

            spend_total += spend
            impressions_total += impressions
            clicks_total += clicks
            conversions_total += conversions
            revenue_total += revenue

            daily.append({
                "date": row.get("date_start"),
                "spend": spend,
                "impressions": impressions,
                "clicks": clicks,
                "conversions": conversions,
                "revenue": revenue,
                "roas": roas,
                "ctr": ctr,
            })

    roas_total = round(revenue_total / spend_total, 4) if spend_total > 0 else 0.0
    ctr_total = round(clicks_total / impressions_total * 100, 4) if impressions_total > 0 else 0.0

    # Today's spend
    today_r = req.get(
        f"{META_GRAPH}/{campaign_id}/insights",
        params={"access_token": access_token,
                "fields": "spend,impressions,clicks",
                "date_preset": "today",
                "level": "campaign"},
        timeout=15,
    )
    spend_today = 0.0
    if today_r.ok:
        today_data = today_r.json().get("data", [])
        if today_data:
            spend_today = float(today_data[0].get("spend", 0) or 0)

    # Claude AI suggestions
    suggestions = []
    try:
        import anthropic as _anthropic
        _client = _anthropic.Anthropic()
        camp_name = campaign.get("name", "Unknown Campaign")
        camp_status = campaign.get("effective_status", "UNKNOWN")
        prompt = (
            f"You are an expert Meta Ads manager for Indian ecommerce brands.\n"
            f"Campaign: {camp_name}\nStatus: {camp_status}\n"
            f"Period: Last {days} days\n"
            f"Spend: \u20b9{spend_total:,.0f}\nImpressions: {impressions_total:,}\n"
            f"Clicks: {clicks_total:,}\nCTR: {ctr_total:.2f}%\n"
            f"Conversions: {int(conversions_total)}\nRevenue: \u20b9{revenue_total:,.0f}\n"
            f"ROAS: {roas_total:.2f}x\nToday's Spend: \u20b9{spend_today:,.0f}\n\n"
            "Provide exactly 3 specific, actionable optimization suggestions for this Meta campaign. "
            "Each suggestion must be 1-2 sentences, concrete, and immediately actionable. "
            "Focus on the Indian market and ecommerce context. "
            "Format your response ONLY as a JSON array: [\"suggestion1\", \"suggestion2\", \"suggestion3\"]"
        )
        msg = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            suggestions = json.loads(match.group())
    except Exception:
        suggestions = [
            f"Your CTR is {ctr_total:.2f}% \u2014 test new ad creatives with stronger hooks to push above 2%.",
            f"ROAS of {roas_total:.2f}x is below the 2.5x target \u2014 tighten your audience to high-intent buyers.",
            "Add a retargeting ad set targeting website visitors who viewed product pages but didn't purchase.",
        ]

    return {
        "campaign_id": campaign_id,
        "campaign": campaign,
        "spend_today": round(spend_today, 2),
        "spend_total": round(spend_total, 2),
        "impressions_total": int(impressions_total),
        "clicks_total": int(clicks_total),
        "conversions_total": int(conversions_total),
        "revenue_total": round(revenue_total, 2),
        "roas_total": roas_total,
        "ctr_total": ctr_total,
        "daily": daily,
        "suggestions": suggestions,
        "days": days,
    }


# -- Settings API: Platform Connections ---------------------------------------------------------

@app.get("/settings/connections")
async def settings_list_connections(request: Request, workspace_id: str = None):
    """List all platform connections for a workspace (Meta + Google)."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Meta / other platform_connections
            cur.execute(
                """
                SELECT platform, account_id, account_name, ad_account_id,
                       is_primary, connected_at,
                       CASE
                           WHEN platform = 'youtube'
                               THEN (account_id IS NOT NULL AND LENGTH(account_id) > 0)
                           ELSE (access_token IS NOT NULL AND LENGTH(access_token) > 0)
                       END AS has_token
                FROM platform_connections
                WHERE workspace_id = %s
                ORDER BY platform, connected_at DESC
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            connections = [dict(zip(cols, r)) for r in cur.fetchall()]

            # Google credentials (stored in google_auth_tokens)
            cur.execute(
                """
                SELECT customer_id, merchant_id, created_at
                FROM google_auth_tokens
                WHERE workspace_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (workspace_id,),
            )
            g_row = cur.fetchone()

    if g_row:
        google_conn = {
            "platform": "google",
            "account_id": g_row[0],
            "account_name": f"Google Ads ({g_row[0]})",
            "ad_account_id": g_row[1],   # merchant_id
            "is_primary": True,
            "connected_at": str(g_row[2]) if g_row[2] else None,
            "has_token": True,
        }
        # Replace any existing google row, or append
        connections = [c for c in connections if c["platform"] != "google"]
        connections.append(google_conn)

    return {"connections": connections, "workspace_id": workspace_id}


@app.post("/settings/meta-connect")
async def settings_meta_connect(request: Request):
    """
    Validate a Meta access token, fetch the user's ad accounts,
    and save the selected account to platform_connections.
    Step 1: POST {workspace_id, access_token}          -> returns {step: "select_account", ad_accounts: [...]}
    Step 2: POST {workspace_id, access_token, ad_account_id} -> returns {status: "connected"}
    """
    _auth(request)
    body = await request.json()
    workspace_id   = body.get("workspace_id")
    access_token   = body.get("access_token", "").strip()
    ad_account_id  = body.get("ad_account_id")

    if not workspace_id or not access_token:
        raise HTTPException(status_code=400, detail="workspace_id and access_token required")

    import requests as req

    # Validate token
    me_r = req.get(
        f"{META_GRAPH}/me",
        params={"access_token": access_token, "fields": "id,name"},
        timeout=10,
    )
    if not me_r.ok:
        err = me_r.json().get("error", {}).get("message", "Invalid token")
        raise HTTPException(status_code=400, detail=f"Meta token invalid: {err}")

    me = me_r.json()
    user_id   = me.get("id")
    user_name = me.get("name", "")

    # Fetch ad accounts
    accounts_r = req.get(
        f"{META_GRAPH}/me/adaccounts",
        params={"access_token": access_token,
                "fields": "id,name,account_id,account_status,currency",
                "limit": 50},
        timeout=10,
    )
    ad_accounts = accounts_r.json().get("data", []) if accounts_r.ok else []

    if not ad_account_id:
        # Step 1: return accounts for the UI to present
        return {
            "step": "select_account",
            "user_id": user_id,
            "user_name": user_name,
            "ad_accounts": ad_accounts,
        }

    # Step 2: save selected account
    if not ad_account_id.startswith("act_"):
        ad_account_id = f"act_{ad_account_id}"

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO platform_connections
                    (workspace_id, platform, account_id, account_name,
                     ad_account_id, access_token, is_primary)
                VALUES (%s, 'meta', %s, %s, %s, %s, true)
                ON CONFLICT (workspace_id, platform, account_id)
                DO UPDATE SET
                    account_name   = EXCLUDED.account_name,
                    ad_account_id  = EXCLUDED.ad_account_id,
                    access_token   = EXCLUDED.access_token,
                    is_primary     = true,
                    updated_at     = NOW()
                """,
                (workspace_id, user_id, user_name, ad_account_id, access_token),
            )
        conn.commit()

    return {"status": "connected", "ad_account_id": ad_account_id, "user_name": user_name}


@app.delete("/settings/disconnect/{platform}")
async def settings_disconnect(request: Request, platform: str):
    """Remove a platform connection for a workspace."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            if platform == "google":
                cur.execute(
                    "DELETE FROM google_auth_tokens WHERE workspace_id = %s",
                    (workspace_id,),
                )
            else:
                # covers 'meta', 'youtube', and any future platform
                cur.execute(
                    "DELETE FROM platform_connections WHERE workspace_id = %s AND platform = %s",
                    (workspace_id, platform),
                )
        conn.commit()

    return {"status": "disconnected", "platform": platform}


# ── YouTube endpoints ───────────────────────────────────────────────────────


def _get_youtube_channel_id_from_db(workspace_id: str) -> str | None:
    """Load the saved YouTube channel ID from platform_connections."""
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT account_id FROM platform_connections
                WHERE workspace_id = %s AND platform = 'youtube'
                ORDER BY connected_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
    return row[0] if row else None


def _get_youtube_connector(workspace_id: str):
    """
    Load YouTubeConnector for a workspace.
    Channel ID stored in platform_connections (required).
    OAuth2 credentials from google_auth_tokens (optional — needed for Analytics).
    API key used as fallback for public Data API calls.
    Returns (YouTubeConnector, workspace) or raises 404.
    """
    workspace = get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    channel_id = _get_youtube_channel_id_from_db(workspace_id)
    if not channel_id:
        raise HTTPException(
            status_code=404,
            detail="YouTube channel not connected — add your Channel ID in Settings",
        )

    # OAuth2 is optional — Analytics won't work without it but Data API will
    google_row = _get_google_conn_from_db(workspace_id) or {}
    conn_row = {**google_row, "youtube_channel_id": channel_id}

    from services.agent_swarm import config as cfg
    api_key = getattr(cfg, "YOUTUBE_API_KEY", "") or os.getenv("YOUTUBE_API_KEY", "")

    from services.agent_swarm.connectors.youtube import YouTubeConnector
    yc = YouTubeConnector(conn_row, workspace, api_key=api_key)
    return yc, workspace


@app.get("/youtube/status")
async def youtube_status(request: Request, workspace_id: str = None):
    """
    Lightweight connection status check — no OAuth2 required.
    Returns whether a YouTube channel ID is saved and whether Google OAuth2
    credentials are available (needed to call YouTube APIs).
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    channel_id = _get_youtube_channel_id_from_db(workspace_id)
    google_row = _get_google_conn_from_db(workspace_id) if channel_id else None
    return {
        "channel_connected":   bool(channel_id),
        "oauth_available":     bool(google_row),
        "analytics_available": bool(google_row),
        "channel_id":          channel_id,
    }


@app.post("/youtube/connect")
async def youtube_connect(request: Request):
    """
    Save a YouTube channel ID for a workspace.
    Stored in platform_connections — does NOT require Google Ads to be connected first.
    Body: { "workspace_id": "uuid", "youtube_channel_id": "UCxxxxxxxxxx" }
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    channel_id = (body.get("youtube_channel_id") or "").strip()
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    if not channel_id:
        raise HTTPException(status_code=400, detail="youtube_channel_id is required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO platform_connections
                    (workspace_id, platform, account_id, account_name, is_primary)
                VALUES (%s, 'youtube', %s, %s, true)
                ON CONFLICT (workspace_id, platform, account_id)
                DO UPDATE SET
                    account_name = EXCLUDED.account_name,
                    updated_at   = NOW()
                """,
                (workspace_id, channel_id, channel_id),
            )
        conn.commit()
    return {"ok": True, "workspace_id": workspace_id, "youtube_channel_id": channel_id}


@app.get("/youtube/channel-stats")
async def youtube_channel_stats(
    request: Request, workspace_id: str = None, days: int = 30
):
    """
    Fetch channel-level daily stats and upsert into youtube_channel_stats.
    Returns channel info + daily rows.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    yc, workspace = _get_youtube_connector(workspace_id)

    from datetime import datetime, timedelta, timezone as _tz
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    until = datetime.utcnow().strftime("%Y-%m-%d")

    # ── Cache check: return from DB if data is < 4 hours old ──────────────────
    try:
        from services.agent_swarm.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT MAX(updated_at) FROM youtube_channel_stats
                    WHERE workspace_id = %s
                    """,
                    (workspace_id,),
                )
                last_updated = cur.fetchone()[0]

        if last_updated and (datetime.now(_tz.utc) - last_updated.replace(tzinfo=_tz.utc)).total_seconds() < 14400:
            # Return cached data from DB
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT date, views, watch_time_minutes, subscribers_gained,
                               subscribers_lost, impressions, impression_ctr
                        FROM youtube_channel_stats
                        WHERE workspace_id = %s
                          AND date >= %s::date AND date <= %s::date
                        ORDER BY date
                        """,
                        (workspace_id, since, until),
                    )
                    cols = ["date", "views", "watch_time_minutes", "subscribers_gained",
                            "subscribers_lost", "impressions", "impression_ctr"]
                    cached_daily = [dict(zip(cols, r)) for r in cur.fetchall()]
                    for row in cached_daily:
                        if hasattr(row["date"], "strftime"):
                            row["date"] = row["date"].strftime("%Y-%m-%d")
                        row["impression_ctr"] = float(row["impression_ctr"] or 0)

            channel_info = yc.get_channel_info()  # lightweight API key call
            return {
                "channel": channel_info,
                "daily": cached_daily,
                "analytics_available": yc.has_oauth,
                "since": since,
                "until": until,
                "workspace_id": workspace_id,
                "from_cache": True,
            }
    except Exception as e:
        print(f"YouTube cache check error (non-fatal): {e}")
    # ── End cache check ────────────────────────────────────────────────────────

    # Channel info
    try:
        channel_info = yc.get_channel_info()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {e}")

    # Daily stats — requires OAuth2; skip gracefully if not available
    daily_rows: list = []
    analytics_available = yc.has_oauth
    if analytics_available:
        try:
            daily_rows = yc.fetch_channel_stats(since, until)
        except Exception as e:
            print(f"YouTube channel stats error (non-fatal): {e}")

    # Upsert to DB
    if daily_rows:
        try:
            from services.agent_swarm.db import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for row in daily_rows:
                        cur.execute(
                            """
                            INSERT INTO youtube_channel_stats
                                (workspace_id, channel_id, date, views, watch_time_minutes,
                                 subscribers_gained, subscribers_lost, impressions, impression_ctr)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (workspace_id, channel_id, date)
                            DO UPDATE SET
                                views              = EXCLUDED.views,
                                watch_time_minutes = EXCLUDED.watch_time_minutes,
                                subscribers_gained = EXCLUDED.subscribers_gained,
                                subscribers_lost   = EXCLUDED.subscribers_lost,
                                impressions        = EXCLUDED.impressions,
                                impression_ctr     = EXCLUDED.impression_ctr,
                                updated_at         = NOW()
                            """,
                            (
                                workspace_id,
                                channel_info["channel_id"],
                                row["date"],
                                row["views"],
                                row["watch_time_minutes"],
                                row["subscribers_gained"],
                                row["subscribers_lost"],
                                row["impressions"],
                                row["impression_ctr"],
                            ),
                        )
                conn.commit()
        except Exception as e:
            print(f"YouTube channel stats DB upsert error (non-fatal): {e}")

    return {
        "channel":             channel_info,
        "daily":               daily_rows,
        "analytics_available": analytics_available,
        "since":               since,
        "until":               until,
        "workspace_id":        workspace_id,
    }


@app.get("/youtube/videos")
async def youtube_videos(request: Request, workspace_id: str = None):
    """
    Fetch video catalog and upsert into youtube_videos.
    Returns video list.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    yc, workspace = _get_youtube_connector(workspace_id)

    # ── Cache check: return from DB if videos were refreshed < 4 hours ago ────
    try:
        from services.agent_swarm.db import get_conn
        from datetime import datetime, timezone as _tz2
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(updated_at) FROM youtube_videos WHERE workspace_id = %s",
                    (workspace_id,),
                )
                last_vid_update = cur.fetchone()[0]

        if last_vid_update and (datetime.now(_tz2.utc) - last_vid_update.replace(tzinfo=_tz2.utc)).total_seconds() < 14400:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT video_id, title, description, tags, thumbnail_url,
                               published_at, duration_seconds, view_count, like_count, comment_count
                        FROM youtube_videos
                        WHERE workspace_id = %s
                        ORDER BY view_count DESC LIMIT 50
                        """,
                        (workspace_id,),
                    )
                    cols = ["video_id","title","description","tags","thumbnail_url",
                            "published_at","duration_seconds","view_count","like_count","comment_count"]
                    cached_videos = [dict(zip(cols, r)) for r in cur.fetchall()]
                    for v in cached_videos:
                        if hasattr(v.get("published_at"), "isoformat"):
                            v["published_at"] = v["published_at"].isoformat()
            return {"videos": cached_videos, "count": len(cached_videos), "workspace_id": workspace_id, "from_cache": True}
    except Exception as e:
        print(f"YouTube videos cache check error (non-fatal): {e}")
    # ── End cache check ────────────────────────────────────────────────────────

    try:
        videos = yc.fetch_video_list(limit=50)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {e}")

    # Upsert to DB
    if videos:
        try:
            import json as _json
            from services.agent_swarm.db import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for v in videos:
                        cur.execute(
                            """
                            INSERT INTO youtube_videos
                                (workspace_id, video_id, title, description, tags,
                                 thumbnail_url, published_at, duration_seconds,
                                 view_count, like_count, comment_count)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (workspace_id, video_id)
                            DO UPDATE SET
                                title           = EXCLUDED.title,
                                description     = EXCLUDED.description,
                                tags            = EXCLUDED.tags,
                                thumbnail_url   = EXCLUDED.thumbnail_url,
                                duration_seconds = EXCLUDED.duration_seconds,
                                view_count      = EXCLUDED.view_count,
                                like_count      = EXCLUDED.like_count,
                                comment_count   = EXCLUDED.comment_count,
                                updated_at      = NOW()
                            """,
                            (
                                workspace_id,
                                v["video_id"],
                                v["title"],
                                v.get("description", ""),
                                v.get("tags") or [],
                                v.get("thumbnail_url"),
                                v.get("published_at"),
                                v.get("duration_seconds", 0),
                                v["view_count"],
                                v["like_count"],
                                v["comment_count"],
                            ),
                        )
                conn.commit()
        except Exception as e:
            print(f"YouTube videos DB upsert error (non-fatal): {e}")

    return {"videos": videos, "count": len(videos), "workspace_id": workspace_id}


@app.get("/youtube/video-insights/{video_id}")
async def youtube_video_insights(
    request: Request,
    video_id: str,
    workspace_id: str = None,
    days: int = 30,
):
    """
    Fetch per-video analytics + AI suggestions.
    Upserts daily rows into youtube_video_stats.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    yc, workspace = _get_youtube_connector(workspace_id)

    from datetime import datetime, timedelta
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    until = datetime.utcnow().strftime("%Y-%m-%d")

    try:
        daily_rows = yc.fetch_video_analytics(video_id, since, until)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"YouTube Analytics error: {e}")

    # Aggregate totals
    total_views = sum(r["views"] for r in daily_rows)
    total_watch_minutes = sum(r["watch_time_minutes"] for r in daily_rows)
    avg_view_pct = (
        sum(r["avg_view_percentage"] for r in daily_rows) / len(daily_rows)
        if daily_rows else 0
    )
    avg_ctr = (
        sum(r["impression_ctr"] for r in daily_rows) / len(daily_rows)
        if daily_rows else 0
    )
    avg_duration = (
        sum(r["avg_view_duration_seconds"] for r in daily_rows) / len(daily_rows)
        if daily_rows else 0
    )
    total_subs_gained = sum(r["subscribers_gained"] for r in daily_rows)

    # Upsert to DB
    if daily_rows:
        try:
            from services.agent_swarm.db import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for row in daily_rows:
                        cur.execute(
                            """
                            INSERT INTO youtube_video_stats
                                (workspace_id, video_id, date, views, watch_time_minutes,
                                 avg_view_duration_seconds, avg_view_percentage,
                                 impressions, impression_ctr, likes, shares, subscribers_gained)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (workspace_id, video_id, date)
                            DO UPDATE SET
                                views                    = EXCLUDED.views,
                                watch_time_minutes       = EXCLUDED.watch_time_minutes,
                                avg_view_duration_seconds = EXCLUDED.avg_view_duration_seconds,
                                avg_view_percentage      = EXCLUDED.avg_view_percentage,
                                impressions              = EXCLUDED.impressions,
                                impression_ctr           = EXCLUDED.impression_ctr,
                                likes                    = EXCLUDED.likes,
                                shares                   = EXCLUDED.shares,
                                subscribers_gained       = EXCLUDED.subscribers_gained,
                                updated_at               = NOW()
                            """,
                            (
                                workspace_id, video_id,
                                row["date"],
                                row["views"],
                                row["watch_time_minutes"],
                                row["avg_view_duration_seconds"],
                                row["avg_view_percentage"],
                                row["impressions"],
                                row["impression_ctr"],
                                row["likes"],
                                row["shares"],
                                row["subscribers_gained"],
                            ),
                        )
                conn.commit()
        except Exception as e:
            print(f"YouTube video stats DB upsert error (non-fatal): {e}")

    # Claude AI suggestions
    suggestions: list[str] = []
    try:
        import anthropic
        import re as _re
        client = anthropic.Anthropic()
        prompt = (
            f"YouTube video '{video_id}' last {days} days:\n"
            f"Views: {total_views:,}, Watch minutes: {total_watch_minutes:,}, "
            f"Avg view %: {avg_view_pct:.1f}%, CTR: {avg_ctr:.2f}%, "
            f"Avg duration: {avg_duration:.0f}s, Subscribers gained: {total_subs_gained}\n\n"
            f"Targets: CTR > 4%, avg view % > 35%.\n"
            f"Give exactly 3 short actionable improvement suggestions as a JSON array of strings. "
            f"Example: [\"Suggestion 1\",\"Suggestion 2\",\"Suggestion 3\"]. JSON only, no extra text."
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        # Parse JSON array
        match = _re.search(r'\[.*?\]', text, _re.DOTALL)
        if match:
            import json as _json
            suggestions = _json.loads(match.group(0))[:3]
    except Exception as e:
        print(f"YouTube video insights Claude error: {e}")

    return {
        "video_id": video_id,
        "total_views": total_views,
        "total_watch_minutes": total_watch_minutes,
        "avg_view_percentage": round(avg_view_pct, 2),
        "avg_ctr": round(avg_ctr, 2),
        "avg_duration_seconds": round(avg_duration),
        "subscribers_gained": total_subs_gained,
        "daily": daily_rows,
        "suggestions": suggestions,
        "workspace_id": workspace_id,
    }


@app.get("/youtube/growth-plan")
async def youtube_growth_plan(request: Request, workspace_id: str = None):
    """
    Generate a 5-step Claude growth plan based on channel data.
    Reads best/worst video from DB after a videos sync.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    yc, workspace = _get_youtube_connector(workspace_id)

    # Get channel info for context
    try:
        channel_info = yc.get_channel_info()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {e}")

    # Read best + worst videos from DB
    best_video = None
    worst_video = None
    try:
        from services.agent_swarm.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT video_id, title, view_count
                    FROM youtube_videos
                    WHERE workspace_id = %s
                    ORDER BY view_count DESC
                    LIMIT 1
                    """,
                    (workspace_id,),
                )
                r = cur.fetchone()
                if r:
                    best_video = {"video_id": r[0], "title": r[1], "view_count": r[2]}
                cur.execute(
                    """
                    SELECT video_id, title, view_count
                    FROM youtube_videos
                    WHERE workspace_id = %s AND view_count > 0
                    ORDER BY view_count ASC
                    LIMIT 1
                    """,
                    (workspace_id,),
                )
                r = cur.fetchone()
                if r:
                    worst_video = {"video_id": r[0], "title": r[1], "view_count": r[2]}
    except Exception as e:
        print(f"YouTube growth plan DB read error (non-fatal): {e}")

    # Claude growth plan
    steps: list[str] = []
    try:
        import anthropic
        client = anthropic.Anthropic()
        channel_name = channel_info.get("title", "your channel")
        subs = channel_info.get("subscriber_count", 0)
        views = channel_info.get("view_count", 0)
        best_info = f"Best video: \"{best_video['title']}\" ({best_video['view_count']:,} views)" if best_video else "No videos uploaded yet"
        worst_info = f"Needs improvement: \"{worst_video['title']}\" ({worst_video['view_count']:,} views)" if worst_video else ""
        prompt = (
            f"YouTube channel: {channel_name}\n"
            f"Subscribers: {subs:,} | Total views: {views:,}\n"
            f"{best_info}\n{worst_info}\n\n"
            f"You are a YouTube growth expert. Create an actionable 5-step growth plan "
            f"to increase views, subscribers, and sales for this health-tech brand. "
            f"Focus on: CTR optimization, retention hooks, SEO topics, upload schedule, "
            f"and cross-channel amplification to Meta Ads.\n"
            f"Give exactly 5 numbered steps. Each step: 1-2 sentences. Be specific and actionable. "
            f"Numbered list only, no headers."
        )
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        steps = [
            line.lstrip("0123456789.-) ").strip()
            for line in text.splitlines()
            if line.strip() and line[0].isdigit()
        ][:5]
    except Exception as e:
        print(f"YouTube growth plan Claude error: {e}")

    return {
        "channel": channel_info,
        "steps": steps,
        "workspace_id": workspace_id,
    }


@app.post("/google/oauth/save")
async def google_oauth_save(request: Request):
    """
    Called by the Next.js OAuth callback after the authorization-code exchange.
    Receives access_token + refresh_token, auto-discovers:
      - Google Ads customer_id  (via customers:listAccessibleCustomers)
      - YouTube channel_id       (via YouTube Data API channels?mine=true)
    Then saves credentials to google_auth_tokens and the YouTube channel to
    platform_connections.
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")

    if not workspace_id or not access_token or not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="workspace_id, access_token, and refresh_token are required",
        )

    from services.agent_swarm import config as cfg
    import requests as rq

    # Accept client credentials from request body (sent by dashboard callback)
    # so that agent-swarm doesn't need GOOGLE_CLIENT_ID/SECRET as its own env vars.
    def _is_real(v: str) -> bool:
        return bool(v and v.strip().upper() not in ("", "PLACEHOLDER"))

    client_id = cfg.GOOGLE_CLIENT_ID if _is_real(cfg.GOOGLE_CLIENT_ID) else body.get("client_id", "")
    client_secret = cfg.GOOGLE_CLIENT_SECRET if _is_real(cfg.GOOGLE_CLIENT_SECRET) else body.get("client_secret", "")
    developer_token = cfg.GOOGLE_DEVELOPER_TOKEN

    if not _is_real(client_id) or not _is_real(client_secret):
        raise HTTPException(
            status_code=500,
            detail=(
                "Google OAuth client credentials not found. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on the dashboard service."
            ),
        )

    if not _is_real(developer_token):
        raise HTTPException(
            status_code=500,
            detail=(
                "GOOGLE_DEVELOPER_TOKEN must be set in the agent-swarm environment. "
                "Get it from Google Ads → Tools → API Center → Developer Token."
            ),
        )

    # ── Auto-discover Google Ads customer IDs ────────────────────
    # Prefer non-manager (real ad account) over manager (MCC) accounts.
    # listAccessibleCustomers may return the MCC first — always check each
    # candidate with a GAQL query for customer.manager flag.
    customer_id = None
    import json as _json
    try:
        ads_resp = rq.get(
            f"https://googleads.googleapis.com/{cfg.GOOGLE_ADS_API_VERSION}"
            "/customers:listAccessibleCustomers",
            headers={
                "Authorization": f"Bearer {access_token}",
                "developer-token": developer_token,
            },
            timeout=15,
        )
        print(f"[oauth/save] Ads API status={ads_resp.status_code} body={ads_resp.text[:500]}")
        if ads_resp.status_code == 200:
            resource_names = ads_resp.json().get("resourceNames", [])
            candidates = [r.split("/")[-1] for r in resource_names]
            print(f"[oauth/save] accessible customers: {candidates}")
            non_managers, managers = [], []
            for cid in candidates:
                try:
                    qr = rq.post(
                        f"https://googleads.googleapis.com/{cfg.GOOGLE_ADS_API_VERSION}"
                        f"/customers/{cid}/googleAds:searchStream",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "developer-token": developer_token,
                            "Content-Type": "application/json",
                        },
                        json={"query": "SELECT customer.id, customer.manager, customer.descriptive_name FROM customer LIMIT 1"},
                        timeout=10,
                    )
                    if qr.ok:
                        for line in qr.text.strip().splitlines():
                            try:
                                batch = _json.loads(line)
                                for result_row in batch.get("results", []):
                                    cust = result_row.get("customer", {})
                                    is_mgr = cust.get("manager", False)
                                    name = cust.get("descriptiveName", cid)
                                    print(f"[oauth/save] cid={cid} name={name!r} manager={is_mgr}")
                                    (managers if is_mgr else non_managers).append(cid)
                            except Exception:
                                pass
                    else:
                        print(f"[oauth/save] cid={cid} GAQL {qr.status_code}: {qr.text[:200]}")
                except Exception as ce:
                    print(f"[oauth/save] cid={cid} check error: {ce}")
            customer_id = (non_managers or managers or candidates[:1] or [None])[0]
            print(f"[oauth/save] chosen customer_id={customer_id} non_managers={non_managers} managers={managers}")
    except Exception as e:
        print(f"[oauth/save] customer discovery error: {e}")

    # ── Auto-discover YouTube channel ID ─────────────────────────
    youtube_channel_id = None
    try:
        yt_resp = rq.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if yt_resp.status_code == 200:
            items = yt_resp.json().get("items", [])
            if items:
                youtube_channel_id = items[0]["id"]
    except Exception as e:
        print(f"[oauth/save] YouTube channel discovery error: {e}")

    # ── Auto-discover GA4 property ID ────────────────────────────
    ga4_property_id = None
    try:
        from services.agent_swarm.connectors.ga4 import GA4Connector
        ga4_property_id = GA4Connector.discover_property_id(access_token)
        print(f"[oauth/save] GA4 property_id={ga4_property_id}")
    except Exception as e:
        print(f"[oauth/save] GA4 property discovery error: {e}")

    if not customer_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "No Google Ads accounts found for this Google account. "
                "Make sure Google Ads is active before connecting."
            ),
        )

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Delete existing row for this workspace, then insert fresh.
            # Avoids ON CONFLICT which requires a DB-level UNIQUE constraint.
            cur.execute(
                "DELETE FROM google_auth_tokens WHERE workspace_id = %s",
                (workspace_id,),
            )
            cur.execute(
                """
                INSERT INTO google_auth_tokens
                    (workspace_id, customer_id, developer_token,
                     client_id, client_secret, refresh_token, access_token,
                     ga4_property_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    workspace_id, customer_id, developer_token,
                    client_id, client_secret, refresh_token, access_token,
                    ga4_property_id,
                ),
            )

            # Auto-save YouTube channel ID to platform_connections if discovered.
            # Clear stale YouTube data so the new channel loads fresh on next visit.
            if youtube_channel_id:
                cur.execute(
                    "DELETE FROM platform_connections WHERE workspace_id = %s AND platform = 'youtube'",
                    (workspace_id,),
                )
                cur.execute(
                    """
                    INSERT INTO platform_connections
                        (workspace_id, platform, account_id)
                    VALUES (%s, 'youtube', %s)
                    """,
                    (workspace_id, youtube_channel_id),
                )
                # Clear cached YouTube analytics so stale data from a previous
                # channel doesn't show until the new channel is fetched.
                for tbl in ("youtube_video_stats", "youtube_videos", "youtube_channel_stats", "youtube_growth_actions"):
                    cur.execute(f"DELETE FROM {tbl} WHERE workspace_id = %s", (workspace_id,))

    result: dict = {
        "ok": True,
        "workspace_id": workspace_id,
        "customer_id": customer_id,
    }
    if youtube_channel_id:
        result["youtube_channel_id"] = youtube_channel_id
    if ga4_property_id:
        result["ga4_property_id"] = ga4_property_id
    return result


# ── Excel KPI Upload ─────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert campaign name to a stable slug for entity_id."""
    import re
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text[:120]


@app.post("/upload/excel-kpis")
async def upload_excel_kpis(request: Request):
    """
    Upsert KPI rows from an Excel/CSV upload into kpi_hourly + entities_snapshot.
    Body: { workspace_id, platform, entity_level, rows: [{date, campaign_name, spend, ...}] }
    entity_level: "campaign" (default) | "ad_group" | "keyword" | "search_term"
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    platform = body.get("platform", "meta")
    entity_level = body.get("entity_level", "campaign")
    rows = body.get("rows", [])

    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if not rows:
        raise HTTPException(status_code=400, detail="No rows provided")
    if entity_level not in ("campaign", "ad_group", "keyword", "search_term", "geo", "device", "hour_of_day", "asset"):
        raise HTTPException(status_code=400, detail=f"Invalid entity_level: {entity_level}")

    from services.agent_swarm.db import get_conn
    from datetime import datetime, date as _date
    import json as _json

    upserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                # ── Date parsing ─────────────────────────────────────────────
                date_str = str(row.get("date", "")).strip()
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    hour_ts = dt.replace(hour=12)
                except ValueError:
                    # Use today as fallback for aggregate rows without dates
                    hour_ts = datetime.combine(_date.today(), datetime.min.time()).replace(hour=12)

                spend = float(row.get("spend") or 0)
                impressions = int(row.get("impressions") or 0)
                clicks = int(row.get("clicks") or 0)
                conversions = float(row.get("conversions") or 0)
                revenue = float(row.get("revenue") or 0)
                ctr = round(clicks / impressions * 100, 4) if impressions > 0 else 0.0
                cpm = round(spend / impressions * 1000, 4) if impressions > 0 else 0.0
                cpc = round(spend / clicks, 4) if clicks > 0 else 0.0
                roas = round(revenue / spend, 4) if spend > 0 else 0.0

                # ── Per-level entity resolution ───────────────────────────────
                extra_json = None
                qs = None

                if entity_level == "campaign":
                    campaign_name = str(row.get("campaign_name", "")).strip()
                    if not campaign_name:
                        continue
                    entity_id = _slugify(campaign_name)
                    entity_name = campaign_name

                elif entity_level == "ad_group":
                    campaign_name = str(row.get("campaign_name", "")).strip()
                    ad_group_name = str(row.get("ad_group_name", "")).strip()
                    if not campaign_name or not ad_group_name:
                        continue
                    campaign_id = _slugify(campaign_name)
                    entity_id = _slugify(campaign_name + "__" + ad_group_name)
                    entity_name = ad_group_name
                    extra_json = _json.dumps({
                        "campaign_id": campaign_id,
                        "campaign_name": campaign_name,
                        "ad_group_name": ad_group_name,
                    })

                elif entity_level == "keyword":
                    campaign_name = str(row.get("campaign_name", "")).strip()
                    ad_group_name = str(row.get("ad_group_name", "")).strip()
                    keyword = str(row.get("keyword", "")).strip()
                    match_type = str(row.get("match_type", "BROAD")).strip().upper() or "BROAD"
                    if not keyword:
                        continue
                    qs_raw = row.get("quality_score")
                    try:
                        qs = int(float(qs_raw)) if qs_raw not in (None, "", "--", " --") else None
                    except (ValueError, TypeError):
                        qs = None
                    imp_share = row.get("impression_share")
                    campaign_id = _slugify(campaign_name) if campaign_name else ""
                    ad_group_id = _slugify(campaign_name + "__" + ad_group_name) if ad_group_name else campaign_id
                    entity_id = _slugify(campaign_name + "__" + ad_group_name + "__" + keyword + "__" + match_type)
                    entity_name = keyword
                    extra_json = _json.dumps({
                        "campaign_id": campaign_id,
                        "ad_group_id": ad_group_id,
                        "ad_group_name": ad_group_name,
                        "keyword": keyword,
                        "match_type": match_type,
                        "quality_score": qs,
                        "impression_share": str(imp_share) if imp_share not in (None, "") else None,
                    })

                elif entity_level == "search_term":
                    search_term = str(row.get("search_term", "")).strip()
                    if not search_term:
                        continue
                    campaign_name = str(row.get("campaign_name", "")).strip()
                    campaign_id = _slugify(campaign_name) if campaign_name else ""
                    keyword = str(row.get("keyword", "")).strip()
                    match_type = str(row.get("match_type", "")).strip().upper()
                    ad_group_name = str(row.get("ad_group_name", "")).strip()
                    entity_id = _slugify(search_term[:100])
                    entity_name = search_term[:200]
                    extra_json = _json.dumps({
                        "campaign_id": campaign_id,
                        "campaign_name": campaign_name,
                        "search_term": search_term,
                        "keyword": keyword,
                        "match_type": match_type,
                        "ad_group_name": ad_group_name,
                    })

                elif entity_level == "geo":
                    region = str(row.get("region", "Unknown")).strip() or "Unknown"
                    campaign_name = str(row.get("campaign_name", "")).strip()
                    entity_id = _slugify(f"{campaign_name}__{region}")
                    entity_name = region
                    extra_json = _json.dumps({
                        "campaign_name": campaign_name,
                        "region": region,
                    })

                elif entity_level == "device":
                    device = str(row.get("device", "Unknown")).strip() or "Unknown"
                    campaign_name = str(row.get("campaign_name", "")).strip()
                    entity_id = _slugify(f"{campaign_name}__{device}")
                    entity_name = device
                    extra_json = _json.dumps({
                        "campaign_name": campaign_name,
                        "device": device,
                    })

                elif entity_level == "hour_of_day":
                    try:
                        hour = int(float(row.get("hour") or 0))
                    except (ValueError, TypeError):
                        hour = 0
                    day = str(row.get("day_of_week", "Monday")).strip() or "Monday"
                    campaign_name = str(row.get("campaign_name", "")).strip()
                    entity_id = f"{day[:3].lower()}_{hour:02d}"
                    entity_name = f"{day} {hour:02d}:00"
                    extra_json = _json.dumps({
                        "hour": hour,
                        "day_of_week": day,
                        "campaign_name": campaign_name,
                    })

                elif entity_level == "asset":
                    asset_text = str(row.get("asset_text", ""))[:200].strip()
                    if not asset_text:
                        continue
                    asset_type = str(row.get("asset_type", "Headline")).strip() or "Headline"
                    perf_label = str(row.get("performance_label", "N/A")).upper().strip() or "N/A"
                    campaign_name = str(row.get("campaign_name", "")).strip()
                    ad_group_name = str(row.get("ad_group_name", "")).strip()
                    entity_id = _slugify(f"{campaign_name}__{ad_group_name}__{asset_type}__{asset_text[:50]}")
                    entity_name = asset_text
                    # Override: assets have no spend/revenue metrics
                    spend = 0.0
                    revenue = 0.0
                    roas = 0.0
                    cpc = 0.0
                    extra_json = _json.dumps({
                        "campaign_name": campaign_name,
                        "ad_group_name": ad_group_name,
                        "asset_type": asset_type,
                        "performance_label": perf_label,
                    })

                else:
                    continue  # unknown level — skip

                # ── kpi_hourly upsert ─────────────────────────────────────────
                if extra_json is not None:
                    cur.execute(
                        """
                        INSERT INTO kpi_hourly
                            (workspace_id, platform, account_id, entity_level, entity_id,
                             entity_name, hour_ts, spend, impressions, clicks, conversions,
                             revenue, ctr, cpm, cpc, roas, quality_score, raw_json)
                        VALUES (%s,%s,'excel_upload',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb))
                        ON CONFLICT (platform, account_id, entity_level, entity_id, hour_ts)
                        DO UPDATE SET
                            spend = EXCLUDED.spend,
                            impressions = EXCLUDED.impressions,
                            clicks = EXCLUDED.clicks,
                            conversions = EXCLUDED.conversions,
                            revenue = EXCLUDED.revenue,
                            ctr = EXCLUDED.ctr,
                            cpm = EXCLUDED.cpm,
                            cpc = EXCLUDED.cpc,
                            roas = EXCLUDED.roas,
                            entity_name = EXCLUDED.entity_name,
                            quality_score = EXCLUDED.quality_score,
                            raw_json = EXCLUDED.raw_json
                        """,
                        (workspace_id, platform, entity_level, entity_id, entity_name, hour_ts,
                         spend, impressions, clicks, conversions, revenue,
                         ctr, cpm, cpc, roas, qs, extra_json),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO kpi_hourly
                            (workspace_id, platform, account_id, entity_level, entity_id,
                             entity_name, hour_ts, spend, impressions, clicks, conversions,
                             revenue, ctr, cpm, cpc, roas)
                        VALUES (%s,%s,'excel_upload',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (platform, account_id, entity_level, entity_id, hour_ts)
                        DO UPDATE SET
                            spend = EXCLUDED.spend,
                            impressions = EXCLUDED.impressions,
                            clicks = EXCLUDED.clicks,
                            conversions = EXCLUDED.conversions,
                            revenue = EXCLUDED.revenue,
                            ctr = EXCLUDED.ctr,
                            cpm = EXCLUDED.cpm,
                            cpc = EXCLUDED.cpc,
                            roas = EXCLUDED.roas,
                            entity_name = EXCLUDED.entity_name
                        """,
                        (workspace_id, platform, entity_level, entity_id, entity_name, hour_ts,
                         spend, impressions, clicks, conversions, revenue,
                         ctr, cpm, cpc, roas),
                    )

                # ── entities_snapshot upsert ──────────────────────────────────
                cur.execute(
                    """
                    INSERT INTO entities_snapshot
                        (workspace_id, platform, account_id, entity_level, entity_id, name, status)
                    VALUES (%s,%s,'excel_upload',%s,%s,%s,'ACTIVE')
                    ON CONFLICT (platform, entity_level, entity_id)
                    DO UPDATE SET name = EXCLUDED.name, workspace_id = EXCLUDED.workspace_id
                    """,
                    (workspace_id, platform, entity_level, entity_id, entity_name),
                )
                upserted += 1

        conn.commit()

    return {"ok": True, "rows_upserted": upserted, "entity_level": entity_level, "platform": platform}


# ── Auction Insights upload (separate table) ──────────────────────────────────

@app.post("/upload/auction-insights")
async def upload_auction_insights(request: Request):
    """
    Upload Auction Insights report to google_auction_insights table.
    Body: { workspace_id, rows: [{competitor_domain, campaign_name?, impression_share, overlap_rate, ...}] }
    Auto-detects account-level (no campaign_name) vs per-campaign rows.
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    rows = body.get("rows", [])

    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if not rows:
        raise HTTPException(status_code=400, detail="No rows provided")

    from services.agent_swarm.db import get_conn

    def _pct(val):
        """Parse percentage string like '32%' or decimal '0.32'."""
        if val is None:
            return None
        s = str(val).replace('%', '').strip()
        if s in ('', '--', ' --'):
            return None
        try:
            v = float(s)
            if v < 2:  # decimal fraction → convert to percentage
                v = v * 100
            return round(v, 2)
        except (ValueError, TypeError):
            return None

    upserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                competitor = str(row.get("competitor_domain", "")).strip()
                if not competitor:
                    continue
                campaign_name = str(row.get("campaign_name", "")).strip()

                cur.execute(
                    """
                    INSERT INTO google_auction_insights
                        (workspace_id, campaign_name, competitor_domain,
                         impression_share, overlap_rate, position_above_rate,
                         top_of_page_rate, abs_top_impression_pct, outranking_share,
                         uploaded_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (workspace_id, campaign_name, competitor_domain)
                    DO UPDATE SET
                        impression_share    = EXCLUDED.impression_share,
                        overlap_rate        = EXCLUDED.overlap_rate,
                        position_above_rate = EXCLUDED.position_above_rate,
                        top_of_page_rate    = EXCLUDED.top_of_page_rate,
                        abs_top_impression_pct = EXCLUDED.abs_top_impression_pct,
                        outranking_share    = EXCLUDED.outranking_share,
                        uploaded_at         = NOW()
                    """,
                    (
                        workspace_id, campaign_name, competitor,
                        _pct(row.get("impression_share")),
                        _pct(row.get("overlap_rate")),
                        _pct(row.get("position_above_rate")),
                        _pct(row.get("top_of_page_rate")),
                        _pct(row.get("abs_top_impression_pct")),
                        _pct(row.get("outranking_share")),
                    ),
                )
                upserted += 1
        conn.commit()

    return {"ok": True, "rows_upserted": upserted}


# ── GET endpoints for individual report types ─────────────────────────────────

@app.get("/upload/google-report-status")
async def upload_google_report_status(request: Request, workspace_id: str = None):
    """Return last upload date + has_data for each Google Ads report type."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    kpi_levels = ("campaign", "keyword", "search_term", "geo", "device", "hour_of_day", "asset")
    status: dict = {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            for level in kpi_levels:
                cur.execute(
                    """
                    SELECT MAX(hour_ts), COUNT(*)
                    FROM kpi_hourly
                    WHERE workspace_id = %s AND account_id = 'excel_upload' AND entity_level = %s
                    """,
                    (workspace_id, level),
                )
                last_ts, count = cur.fetchone()
                status[level] = {
                    "has_data": int(count or 0) > 0,
                    "last_upload_date": last_ts.isoformat() if last_ts else None,
                }

            # Auction insights from separate table
            cur.execute(
                "SELECT MAX(uploaded_at), COUNT(*) FROM google_auction_insights WHERE workspace_id = %s",
                (workspace_id,),
            )
            last_ts, count = cur.fetchone()
            status["auction_insight"] = {
                "has_data": int(count or 0) > 0,
                "last_upload_date": last_ts.isoformat() if last_ts else None,
            }

    return status


@app.get("/upload/google-geo")
async def upload_google_geo(request: Request, workspace_id: str = None, days: int = 365):
    """Return geographic breakdown from uploaded Geo report."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    entity_name AS region,
                    raw_json->>'campaign_name' AS campaign_name,
                    SUM(spend)       AS spend,
                    SUM(impressions) AS impressions,
                    SUM(clicks)      AS clicks,
                    SUM(conversions) AS conversions,
                    SUM(revenue)     AS revenue,
                    CASE WHEN SUM(spend) > 0
                         THEN ROUND(SUM(revenue)::NUMERIC / SUM(spend), 2) ELSE 0 END AS roas,
                    CASE WHEN SUM(conversions) > 0
                         THEN ROUND(SUM(spend)::NUMERIC / SUM(conversions), 2) ELSE NULL END AS cpa
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id   = 'excel_upload'
                  AND entity_level = 'geo'
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY entity_name, raw_json->>'campaign_name'
                ORDER BY spend DESC
                LIMIT 50
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                "SELECT MAX(hour_ts) FROM kpi_hourly WHERE workspace_id=%s AND account_id='excel_upload' AND entity_level='geo'",
                (workspace_id,),
            )
            last_upload = cur.fetchone()[0]

    geos = [
        {
            "region":        r["region"],
            "campaign_name": r["campaign_name"] or "",
            "spend":         float(r["spend"] or 0),
            "impressions":   int(r["impressions"] or 0),
            "clicks":        int(r["clicks"] or 0),
            "conversions":   float(r["conversions"] or 0),
            "revenue":       float(r["revenue"] or 0),
            "roas":          float(r["roas"] or 0),
            "cpa":           float(r["cpa"]) if r["cpa"] is not None else None,
        }
        for r in rows
    ]
    return {
        "has_data": len(geos) > 0,
        "last_upload_date": last_upload.isoformat() if last_upload else None,
        "geos": geos,
    }


@app.get("/upload/google-devices")
async def upload_google_devices(request: Request, workspace_id: str = None, days: int = 365):
    """Return device breakdown from uploaded Device report."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    entity_name AS device,
                    SUM(spend)       AS spend,
                    SUM(impressions) AS impressions,
                    SUM(clicks)      AS clicks,
                    SUM(conversions) AS conversions,
                    SUM(revenue)     AS revenue,
                    CASE WHEN SUM(spend) > 0
                         THEN ROUND(SUM(revenue)::NUMERIC / SUM(spend), 2) ELSE 0 END AS roas,
                    CASE WHEN SUM(conversions) > 0
                         THEN ROUND(SUM(spend)::NUMERIC / SUM(conversions), 2) ELSE NULL END AS cpa
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id   = 'excel_upload'
                  AND entity_level = 'device'
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY entity_name
                ORDER BY spend DESC
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                "SELECT MAX(hour_ts) FROM kpi_hourly WHERE workspace_id=%s AND account_id='excel_upload' AND entity_level='device'",
                (workspace_id,),
            )
            last_upload = cur.fetchone()[0]

    total_spend = sum(float(r["spend"] or 0) for r in rows)
    devices = [
        {
            "device":      r["device"],
            "spend":       float(r["spend"] or 0),
            "impressions": int(r["impressions"] or 0),
            "clicks":      int(r["clicks"] or 0),
            "conversions": float(r["conversions"] or 0),
            "revenue":     float(r["revenue"] or 0),
            "roas":        float(r["roas"] or 0),
            "cpa":         float(r["cpa"]) if r["cpa"] is not None else None,
            "spend_pct":   round(float(r["spend"] or 0) / total_spend * 100, 1) if total_spend > 0 else 0,
        }
        for r in rows
    ]
    return {
        "has_data": len(devices) > 0,
        "last_upload_date": last_upload.isoformat() if last_upload else None,
        "devices": devices,
    }


@app.get("/upload/google-time-of-day")
async def upload_google_time_of_day(request: Request, workspace_id: str = None, days: int = 365):
    """Return time-of-day slots from uploaded Time of Day report."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (raw_json->>'hour')::INT      AS hour,
                    raw_json->>'day_of_week'       AS day_of_week,
                    SUM(spend)       AS spend,
                    SUM(conversions) AS conversions,
                    SUM(clicks)      AS clicks,
                    SUM(impressions) AS impressions
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id   = 'excel_upload'
                  AND entity_level = 'hour_of_day'
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                  AND raw_json IS NOT NULL
                GROUP BY raw_json->>'hour', raw_json->>'day_of_week'
                ORDER BY raw_json->>'day_of_week', (raw_json->>'hour')::INT
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                "SELECT MAX(hour_ts) FROM kpi_hourly WHERE workspace_id=%s AND account_id='excel_upload' AND entity_level='hour_of_day'",
                (workspace_id,),
            )
            last_upload = cur.fetchone()[0]

    slots = [
        {
            "hour":        int(r["hour"] or 0),
            "day_of_week": r["day_of_week"] or "Monday",
            "spend":       float(r["spend"] or 0),
            "conversions": float(r["conversions"] or 0),
            "clicks":      int(r["clicks"] or 0),
            "impressions": int(r["impressions"] or 0),
        }
        for r in rows
    ]
    return {
        "has_data": len(slots) > 0,
        "last_upload_date": last_upload.isoformat() if last_upload else None,
        "slots": slots,
    }


@app.get("/upload/google-assets")
async def upload_google_assets(request: Request, workspace_id: str = None, days: int = 365):
    """Return Ad Asset (RSA) performance from uploaded asset report."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    entity_name                       AS asset_text,
                    raw_json->>'asset_type'           AS asset_type,
                    raw_json->>'performance_label'    AS performance_label,
                    raw_json->>'campaign_name'        AS campaign_name,
                    raw_json->>'ad_group_name'        AS ad_group_name,
                    SUM(impressions) AS impressions,
                    SUM(clicks)      AS clicks
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id   = 'excel_upload'
                  AND entity_level = 'asset'
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY entity_name,
                         raw_json->>'asset_type',
                         raw_json->>'performance_label',
                         raw_json->>'campaign_name',
                         raw_json->>'ad_group_name'
                ORDER BY
                    CASE raw_json->>'performance_label'
                        WHEN 'BEST' THEN 0
                        WHEN 'GOOD' THEN 1
                        WHEN 'LOW'  THEN 2
                        ELSE 3
                    END,
                    SUM(impressions) DESC
                LIMIT 100
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                "SELECT MAX(hour_ts) FROM kpi_hourly WHERE workspace_id=%s AND account_id='excel_upload' AND entity_level='asset'",
                (workspace_id,),
            )
            last_upload = cur.fetchone()[0]

    assets = [
        {
            "asset_text":        r["asset_text"] or "",
            "asset_type":        r["asset_type"] or "Headline",
            "performance_label": r["performance_label"] or "N/A",
            "campaign_name":     r["campaign_name"] or "",
            "ad_group_name":     r["ad_group_name"] or "",
            "impressions":       int(r["impressions"] or 0),
            "clicks":            int(r["clicks"] or 0),
        }
        for r in rows
    ]
    return {
        "has_data": len(assets) > 0,
        "last_upload_date": last_upload.isoformat() if last_upload else None,
        "assets": assets,
    }


@app.get("/upload/google-auction")
async def upload_google_auction(request: Request, workspace_id: str = None):
    """Return Auction Insights data."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    competitor_domain,
                    campaign_name,
                    impression_share,
                    overlap_rate,
                    position_above_rate,
                    top_of_page_rate,
                    abs_top_impression_pct,
                    outranking_share,
                    uploaded_at
                FROM google_auction_insights
                WHERE workspace_id = %s
                ORDER BY overlap_rate DESC NULLS LAST
                LIMIT 50
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                "SELECT MAX(uploaded_at) FROM google_auction_insights WHERE workspace_id = %s",
                (workspace_id,),
            )
            last_upload = cur.fetchone()[0]

    competitors = [
        {
            "competitor_domain":    r["competitor_domain"],
            "campaign_name":        r["campaign_name"] or "",
            "impression_share":     float(r["impression_share"])     if r["impression_share"]     is not None else None,
            "overlap_rate":         float(r["overlap_rate"])         if r["overlap_rate"]         is not None else None,
            "position_above_rate":  float(r["position_above_rate"])  if r["position_above_rate"]  is not None else None,
            "top_of_page_rate":     float(r["top_of_page_rate"])     if r["top_of_page_rate"]     is not None else None,
            "abs_top_impression_pct": float(r["abs_top_impression_pct"]) if r["abs_top_impression_pct"] is not None else None,
            "outranking_share":     float(r["outranking_share"])     if r["outranking_share"]     is not None else None,
        }
        for r in rows
    ]
    return {
        "has_data": len(competitors) > 0,
        "last_upload_date": last_upload.isoformat() if last_upload else None,
        "competitors": competitors,
    }


# ── Amazon Ads Upload ─────────────────────────────────────────────────────────

@app.post("/upload/amazon-ads")
async def upload_amazon_ads(request: Request):
    """
    Parse and store Amazon Advertising CSV rows (Sponsored Products / Sponsored Brands).
    Body: { workspace_id, rows: [{campaign_name, spend, impressions, clicks, orders, sales,
            acos, roas, date, ad_type, campaign_status}] }
    Stores in kpi_hourly with platform='amazon', account_id='amazon_upload', entity_level='campaign'.
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "").strip()
    rows = body.get("rows", [])
    ad_type = body.get("ad_type", "Sponsored Products")  # default

    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if not rows:
        raise HTTPException(status_code=400, detail="rows required")

    from services.agent_swarm.db import get_conn

    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for row in rows:
                campaign_name = str(row.get("campaign_name") or "Unknown Campaign").strip()
                entity_id = _slugify(campaign_name)
                entity_name = campaign_name

                # Parse date — Amazon reports may not have a date column (totals only)
                date_str = row.get("date") or row.get("day") or ""
                try:
                    from datetime import datetime as _dt
                    hour_ts = _dt.strptime(str(date_str).strip(), "%Y-%m-%d")
                except Exception:
                    hour_ts = _dt.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

                def _num(v):
                    if v is None or str(v).strip() in ("", "--", "N/A", "n/a"):
                        return 0.0
                    try:
                        return float(str(v).replace(",", "").replace("%", "").strip())
                    except Exception:
                        return 0.0

                spend       = _num(row.get("spend"))
                impressions = _num(row.get("impressions"))
                clicks      = _num(row.get("clicks"))
                conversions = _num(row.get("orders") or row.get("conversions"))
                revenue     = _num(row.get("sales") or row.get("revenue"))
                acos_val    = _num(row.get("acos"))
                roas_val    = _num(row.get("roas")) if _num(row.get("roas")) > 0 else (
                    round(revenue / spend, 4) if spend > 0 else 0.0
                )
                ctr_val     = round(clicks / impressions * 100, 4) if impressions > 0 else 0.0
                campaign_status = str(row.get("campaign_status") or row.get("status") or "ENABLED").upper().strip()
                row_ad_type = str(row.get("ad_type") or ad_type).strip()

                raw_json = {
                    "campaign_name": campaign_name,
                    "ad_type": row_ad_type,
                    "campaign_status": campaign_status,
                    "acos": acos_val,
                }

                cur.execute(
                    """
                    INSERT INTO kpi_hourly
                        (workspace_id, platform, account_id, entity_level, entity_id, entity_name,
                         hour_ts, spend, impressions, clicks, conversions, revenue, roas, ctr, raw_json)
                    VALUES (%s, 'amazon', 'amazon_upload', 'campaign', %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (platform, account_id, entity_level, entity_id, hour_ts)
                    DO UPDATE SET
                        spend       = EXCLUDED.spend,
                        impressions = EXCLUDED.impressions,
                        clicks      = EXCLUDED.clicks,
                        conversions = EXCLUDED.conversions,
                        revenue     = EXCLUDED.revenue,
                        roas        = EXCLUDED.roas,
                        ctr         = EXCLUDED.ctr,
                        raw_json    = EXCLUDED.raw_json,
                        entity_name = EXCLUDED.entity_name,
                        workspace_id= EXCLUDED.workspace_id
                    """,
                    (
                        workspace_id, entity_id, entity_name,
                        hour_ts, spend, impressions, clicks, conversions, revenue,
                        roas_val, ctr_val, json.dumps(raw_json),
                    ),
                )
                inserted += 1
        conn.commit()

    return {"inserted": inserted, "workspace_id": workspace_id}


@app.get("/marketplace/campaigns")
async def marketplace_campaigns(request: Request, workspace_id: str = None, days: int = 365):
    """Return Amazon Ads campaigns from uploaded data."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    entity_id,
                    MAX(entity_name)            AS name,
                    MAX(raw_json->>'ad_type')   AS ad_type,
                    MAX(raw_json->>'campaign_status') AS campaign_status,
                    SUM(spend)                  AS spend,
                    SUM(impressions)            AS impressions,
                    SUM(clicks)                 AS clicks,
                    SUM(conversions)            AS orders,
                    SUM(revenue)                AS sales,
                    CASE WHEN SUM(spend) > 0
                         THEN ROUND(SUM(revenue)::NUMERIC / SUM(spend), 4)
                         ELSE 0 END             AS roas,
                    CASE WHEN SUM(revenue) > 0
                         THEN ROUND(SUM(spend)::NUMERIC / SUM(revenue) * 100, 2)
                         ELSE 0 END             AS acos,
                    CASE WHEN SUM(impressions) > 0
                         THEN ROUND(SUM(clicks)::NUMERIC / SUM(impressions) * 100, 4)
                         ELSE 0 END             AS ctr,
                    CASE WHEN SUM(clicks) > 0
                         THEN ROUND(SUM(spend)::NUMERIC / SUM(clicks), 2)
                         ELSE 0 END             AS cpc
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND platform     = 'amazon'
                  AND account_id   = 'amazon_upload'
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY entity_id
                ORDER BY spend DESC
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                "SELECT MAX(hour_ts) FROM kpi_hourly WHERE workspace_id=%s AND platform='amazon' AND account_id='amazon_upload'",
                (workspace_id,),
            )
            last_upload = cur.fetchone()[0]

    campaigns = [
        {
            "id":               r["entity_id"],
            "name":             r["name"],
            "ad_type":          r["ad_type"] or "Sponsored Products",
            "campaign_status":  r["campaign_status"] or "ENABLED",
            "spend":            float(r["spend"] or 0),
            "impressions":      int(r["impressions"] or 0),
            "clicks":           int(r["clicks"] or 0),
            "orders":           float(r["orders"] or 0),
            "sales":            float(r["sales"] or 0),
            "roas":             float(r["roas"] or 0),
            "acos":             float(r["acos"] or 0),
            "ctr":              float(r["ctr"] or 0),
            "cpc":              float(r["cpc"] or 0),
        }
        for r in rows
    ]

    total_spend  = sum(c["spend"] for c in campaigns)
    total_sales  = sum(c["sales"] for c in campaigns)
    total_orders = sum(c["orders"] for c in campaigns)
    total_clicks = sum(c["clicks"] for c in campaigns)
    avg_roas     = round(total_sales / total_spend, 4) if total_spend > 0 else 0
    avg_acos     = round(total_spend / total_sales * 100, 2) if total_sales > 0 else 0

    return {
        "has_data":        len(campaigns) > 0,
        "last_upload_date": last_upload.isoformat() if last_upload else None,
        "campaigns":       campaigns,
        "summary": {
            "total_spend":   total_spend,
            "total_sales":   total_sales,
            "total_orders":  total_orders,
            "total_clicks":  total_clicks,
            "avg_roas":      avg_roas,
            "avg_acos":      avg_acos,
        },
    }


@app.get("/upload/campaigns")
async def upload_campaigns(request: Request, workspace_id: str = None, days: int = 365):
    """
    Return campaigns from excel-uploaded data (account_id='excel_upload').
    Groups by entity_id, returns aggregate KPIs.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    platform,
                    entity_id,
                    MAX(entity_name) AS name,
                    SUM(spend)       AS spend,
                    SUM(impressions) AS impressions,
                    SUM(clicks)      AS clicks,
                    SUM(conversions) AS conversions,
                    SUM(revenue)     AS revenue,
                    CASE WHEN SUM(spend) > 0
                         THEN ROUND(SUM(revenue)::NUMERIC / SUM(spend), 4)
                         ELSE 0 END AS roas,
                    CASE WHEN SUM(impressions) > 0
                         THEN ROUND(SUM(clicks)::NUMERIC / SUM(impressions) * 100, 4)
                         ELSE 0 END AS ctr,
                    CASE WHEN SUM(clicks) > 0
                         THEN ROUND(SUM(spend)::NUMERIC / SUM(clicks), 4)
                         ELSE 0 END AS cpc
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id = 'excel_upload'
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY platform, entity_id
                ORDER BY spend DESC
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    platforms = list({r["platform"] for r in rows})
    campaigns = [
        {
            "id": r["entity_id"],
            "name": r["name"],
            "status": "ACTIVE",
            "effective_status": "ACTIVE",
            "platform": r["platform"],
            "spend": float(r["spend"] or 0),
            "impressions": int(r["impressions"] or 0),
            "clicks": int(r["clicks"] or 0),
            "conversions": float(r["conversions"] or 0),
            "revenue": float(r["revenue"] or 0),
            "roas": float(r["roas"] or 0),
            "ctr": float(r["ctr"] or 0),
            "cpc": float(r["cpc"] or 0),
            "_source": "excel_upload",
        }
        for r in rows
    ]

    return {"campaigns": campaigns, "platforms": platforms, "source": "excel_upload"}


@app.get("/upload/campaign-insights/{entity_id}")
async def upload_campaign_insights(
    request: Request,
    entity_id: str,
    workspace_id: str = None,
    days: int = 365,
):
    """
    Per-campaign insights for an excel-uploaded campaign + Claude AI suggestions.
    Returns same shape as /meta/campaign-insights so CampaignDetailPanel renders unchanged.
    Default days=365 so historical reports (e.g. January export uploaded in February) always show.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import re
    import json
    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            # ── Daily campaign rows for chart ─────────────────────────────────
            cur.execute(
                """
                SELECT
                    DATE_TRUNC('day', hour_ts)::DATE AS date,
                    MAX(entity_name) AS name,
                    SUM(spend)       AS spend,
                    SUM(impressions) AS impressions,
                    SUM(clicks)      AS clicks,
                    SUM(conversions) AS conversions,
                    SUM(revenue)     AS revenue
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id = 'excel_upload'
                  AND entity_level = 'campaign'
                  AND entity_id = %s
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY DATE_TRUNC('day', hour_ts)::DATE
                ORDER BY date ASC
                """,
                (workspace_id, entity_id, days),
            )
            cols = [d[0] for d in cur.description]
            daily_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            # ── Ad groups for this campaign ───────────────────────────────────
            cur.execute(
                """
                SELECT entity_id, MAX(entity_name) AS name,
                       SUM(spend) AS spend, SUM(clicks) AS clicks,
                       SUM(conversions) AS conversions, SUM(revenue) AS revenue,
                       CASE WHEN SUM(spend)>0
                            THEN ROUND(SUM(revenue)::NUMERIC/SUM(spend),2) ELSE 0
                       END AS roas
                FROM kpi_hourly
                WHERE workspace_id = %s AND account_id = 'excel_upload'
                  AND entity_level = 'ad_group'
                  AND raw_json->>'campaign_id' = %s
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY entity_id ORDER BY spend DESC
                """,
                (workspace_id, entity_id, days),
            )
            ad_group_cols = [d[0] for d in cur.description]
            ad_group_rows = [dict(zip(ad_group_cols, r)) for r in cur.fetchall()]

            # ── Keywords for this campaign ────────────────────────────────────
            cur.execute(
                """
                SELECT entity_id, MAX(entity_name) AS keyword,
                       MAX(raw_json->>'match_type') AS match_type,
                       MAX(raw_json->>'ad_group_name') AS ad_group_name,
                       MAX(raw_json->>'quality_score') AS quality_score,
                       SUM(spend) AS spend, SUM(clicks) AS clicks,
                       SUM(conversions) AS conversions, SUM(impressions) AS impressions,
                       CASE WHEN SUM(clicks)>0
                            THEN ROUND(SUM(spend)::NUMERIC/SUM(clicks),2) ELSE 0
                       END AS cpc,
                       CASE WHEN SUM(impressions)>0
                            THEN ROUND(SUM(clicks)::NUMERIC/SUM(impressions)*100,2) ELSE 0
                       END AS ctr
                FROM kpi_hourly
                WHERE workspace_id = %s AND account_id = 'excel_upload'
                  AND entity_level = 'keyword'
                  AND raw_json->>'campaign_id' = %s
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY entity_id ORDER BY spend DESC LIMIT 50
                """,
                (workspace_id, entity_id, days),
            )
            kw_cols = [d[0] for d in cur.description]
            keyword_rows = [dict(zip(kw_cols, r)) for r in cur.fetchall()]

            # ── Search terms for this campaign ────────────────────────────────
            cur.execute(
                """
                SELECT entity_id, MAX(entity_name) AS search_term,
                       MAX(raw_json->>'keyword') AS keyword,
                       MAX(raw_json->>'match_type') AS match_type,
                       SUM(spend) AS spend, SUM(clicks) AS clicks,
                       SUM(conversions) AS conversions
                FROM kpi_hourly
                WHERE workspace_id = %s AND account_id = 'excel_upload'
                  AND entity_level = 'search_term'
                  AND raw_json->>'campaign_id' = %s
                  AND hour_ts >= NOW() - INTERVAL '%s days'
                GROUP BY entity_id ORDER BY spend DESC LIMIT 100
                """,
                (workspace_id, entity_id, days),
            )
            st_cols = [d[0] for d in cur.description]
            search_term_rows = [dict(zip(st_cols, r)) for r in cur.fetchall()]

    campaign_name = daily_rows[0]["name"] if daily_rows else entity_id

    spend_total = sum(float(r["spend"] or 0) for r in daily_rows)
    impressions_total = sum(int(r["impressions"] or 0) for r in daily_rows)
    clicks_total = sum(int(r["clicks"] or 0) for r in daily_rows)
    conversions_total = sum(float(r["conversions"] or 0) for r in daily_rows)
    revenue_total = sum(float(r["revenue"] or 0) for r in daily_rows)
    roas_total = round(revenue_total / spend_total, 4) if spend_total > 0 else 0.0
    ctr_total = round(clicks_total / impressions_total * 100, 4) if impressions_total > 0 else 0.0

    daily = [
        {
            "date": str(r["date"]),
            "spend": float(r["spend"] or 0),
            "impressions": int(r["impressions"] or 0),
            "clicks": int(r["clicks"] or 0),
            "conversions": float(r["conversions"] or 0),
            "revenue": float(r["revenue"] or 0),
            "roas": round(float(r["revenue"] or 0) / float(r["spend"]) if float(r["spend"] or 0) > 0 else 0, 4),
            "ctr": round(int(r["clicks"] or 0) / int(r["impressions"]) * 100 if int(r["impressions"] or 0) > 0 else 0, 4),
        }
        for r in daily_rows
    ]

    # Spend today
    from datetime import date as _date
    spend_today = 0.0
    today_str = _date.today().isoformat()
    for r in daily_rows:
        if str(r["date"]) == today_str:
            spend_today = float(r["spend"] or 0)

    # Build serialisable sub-entity lists
    ad_groups = [
        {
            "id": r["entity_id"],
            "name": r["name"],
            "spend": float(r["spend"] or 0),
            "clicks": int(r["clicks"] or 0),
            "conversions": float(r["conversions"] or 0),
            "revenue": float(r["revenue"] or 0),
            "roas": float(r["roas"] or 0),
        }
        for r in ad_group_rows
    ]

    keywords = [
        {
            "id": r["entity_id"],
            "keyword": r["keyword"],
            "match_type": r["match_type"] or "BROAD",
            "ad_group_name": r["ad_group_name"] or "",
            "quality_score": int(r["quality_score"]) if r["quality_score"] not in (None, "") else None,
            "spend": float(r["spend"] or 0),
            "clicks": int(r["clicks"] or 0),
            "conversions": float(r["conversions"] or 0),
            "impressions": int(r["impressions"] or 0),
            "cpc": float(r["cpc"] or 0),
            "ctr": float(r["ctr"] or 0),
        }
        for r in keyword_rows
    ]

    search_terms = [
        {
            "id": r["entity_id"],
            "search_term": r["search_term"],
            "keyword": r["keyword"] or "",
            "match_type": r["match_type"] or "",
            "spend": float(r["spend"] or 0),
            "clicks": int(r["clicks"] or 0),
            "conversions": float(r["conversions"] or 0),
        }
        for r in search_term_rows
    ]

    has_keyword_data = len(keywords) > 0
    has_search_term_data = len(search_terms) > 0

    # ── Claude AI suggestions ─────────────────────────────────────────────────
    suggestions = []
    try:
        import anthropic as _anthropic
        _client = _anthropic.Anthropic()

        # Build context sections
        ag_section = ""
        if ad_groups:
            lines = []
            for ag in ad_groups[:5]:
                roas_v = ag["roas"]
                emoji = "✅" if roas_v >= 2.5 else ("⚠️" if roas_v >= 1.0 else "🚨")
                lines.append(
                    f"  {emoji} {ag['name']}: spend ₹{ag['spend']:,.0f}, "
                    f"ROAS {roas_v:.2f}x, conv {int(ag['conversions'])}"
                )
            ag_section = "AD GROUPS:\n" + "\n".join(lines) + "\n\n"

        kw_section = ""
        if keywords:
            lines = []
            for kw in keywords[:10]:
                qs_str = f"QS:{kw['quality_score']}/10" if kw['quality_score'] is not None else "QS:—"
                lines.append(
                    f"  {kw['keyword']} [{kw['match_type']}] {qs_str}: "
                    f"spend ₹{kw['spend']:,.0f}, CPC ₹{kw['cpc']:.0f}, conv {int(kw['conversions'])}"
                )
            kw_section = "TOP KEYWORDS:\n" + "\n".join(lines) + "\n\n"

        wasted = [kw for kw in keywords if float(kw["spend"]) > 500 and int(kw["conversions"]) == 0]
        waste_section = ""
        if wasted:
            lines = [
                f"  '{kw['keyword']} [{kw['match_type']}]' — ₹{kw['spend']:,.0f} with 0 conversions"
                for kw in wasted[:5]
            ]
            waste_section = "WASTED SPEND (0 conv):\n" + "\n".join(lines) + "\n\n"

        st_section = ""
        if search_terms:
            lines = [
                f"  '{st['search_term']}' → [{st['keyword']}]: "
                f"spend ₹{st['spend']:,.0f}, conv {int(st['conversions'])}"
                for st in search_terms[:5]
            ]
            st_section = "SEARCH TERMS:\n" + "\n".join(lines) + "\n\n"

        prompt = (
            f"You are an expert Google Ads manager for Indian ecommerce brands.\n"
            f"Campaign: {campaign_name}\nPeriod: Last {days} days\n"
            f"Spend: ₹{spend_total:,.0f} | Impressions: {impressions_total:,} | "
            f"Clicks: {clicks_total:,} | CTR: {ctr_total:.2f}%\n"
            f"Conversions: {int(conversions_total)} | Revenue: ₹{revenue_total:,.0f} | "
            f"ROAS: {roas_total:.2f}x\n\n"
            f"{ag_section}{kw_section}{waste_section}{st_section}"
            "Provide exactly 3 specific, actionable optimization suggestions. "
            "Reference specific keyword names, ad groups, or search terms from the data above where relevant. "
            "Each suggestion must be 1-2 sentences, concrete, and immediately actionable. "
            "Format your response ONLY as a JSON array: [\"suggestion1\", \"suggestion2\", \"suggestion3\"]"
        )
        msg = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            suggestions = json.loads(match.group())
    except Exception:
        suggestions = [
            f"CTR is {ctr_total:.2f}% — test new creatives with stronger hooks to push above 2%.",
            f"ROAS of {roas_total:.2f}x is {'below' if roas_total < 2.5 else 'above'} the 2.5x target — "
            f"{'tighten your audience to high-intent buyers' if roas_total < 2.5 else 'consider scaling budget to high-performing ad sets'}.",
            "Add a retargeting segment for visitors who viewed product pages but didn't convert.",
        ]

    return {
        "campaign_id": entity_id,
        "campaign": {"id": entity_id, "name": campaign_name, "status": "ACTIVE", "effective_status": "ACTIVE"},
        "spend_today": round(spend_today, 2),
        "spend_total": round(spend_total, 2),
        "impressions_total": impressions_total,
        "clicks_total": clicks_total,
        "conversions_total": int(conversions_total),
        "revenue_total": round(revenue_total, 2),
        "roas_total": roas_total,
        "ctr_total": ctr_total,
        "daily": daily,
        "suggestions": suggestions,
        "days": days,
        "source": "excel_upload",
        "ad_groups": ad_groups,
        "keywords": keywords,
        "search_terms": search_terms,
        "has_keyword_data": has_keyword_data,
        "has_search_term_data": has_search_term_data,
    }


@app.get("/upload/google-intelligence")
async def upload_google_intelligence(request: Request, workspace_id: str = None):
    """
    Google Ads Intelligence: aggregates campaigns + keywords + search terms from
    excel-uploaded data. Falls back to inferring campaigns from keyword raw_json
    when no entity_level='campaign' rows exist (keyword-only exports).
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import re
    import json
    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            # ── Step 1: Try campaign-level rows first ─────────────────────────
            cur.execute(
                """
                SELECT entity_id,
                       MAX(entity_name) AS name,
                       SUM(spend)       AS spend,
                       SUM(impressions) AS impressions,
                       SUM(clicks)      AS clicks,
                       SUM(conversions) AS conversions,
                       SUM(revenue)     AS revenue,
                       MAX(hour_ts)     AS last_seen
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id = 'excel_upload'
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                GROUP BY entity_id
                ORDER BY SUM(spend) DESC
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            campaign_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            # ── Fallback: aggregate campaigns from keyword raw_json ───────────
            if not campaign_rows:
                cur.execute(
                    """
                    SELECT raw_json->>'campaign_id'        AS entity_id,
                           MAX(raw_json->>'campaign_name') AS name,
                           SUM(spend)       AS spend,
                           SUM(impressions) AS impressions,
                           SUM(clicks)      AS clicks,
                           SUM(conversions) AS conversions,
                           SUM(revenue)     AS revenue,
                           MAX(hour_ts)     AS last_seen
                    FROM kpi_hourly
                    WHERE workspace_id = %s
                      AND account_id = 'excel_upload'
                      AND entity_level = 'keyword'
                      AND hour_ts >= NOW() - INTERVAL '365 days'
                    GROUP BY raw_json->>'campaign_id'
                    ORDER BY SUM(spend) DESC
                    """,
                    (workspace_id,),
                )
                cols = [d[0] for d in cur.description]
                campaign_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            # ── No data at all ────────────────────────────────────────────────
            if not campaign_rows:
                cur.execute(
                    "SELECT MAX(hour_ts) FROM kpi_hourly WHERE workspace_id = %s AND account_id = 'excel_upload'",
                    (workspace_id,),
                )
                ts_row = cur.fetchone()
                return {
                    "has_data": False,
                    "last_upload_date": ts_row[0].strftime("%Y-%m-%d") if ts_row and ts_row[0] else None,
                    "total_spend": 0, "total_revenue": 0,
                    "total_conversions": 0, "total_clicks": 0,
                    "avg_roas": 0, "wasted_spend_total": 0,
                    "campaigns": [], "keywords": [], "search_terms": [], "action_plan": [],
                }

            # ── Step 2: Keywords (LIMIT 200, spend desc) ──────────────────────
            cur.execute(
                """
                SELECT entity_id,
                       MAX(entity_name)                AS keyword,
                       MAX(raw_json->>'campaign_id')   AS campaign_id,
                       MAX(raw_json->>'campaign_name') AS campaign_name,
                       MAX(raw_json->>'ad_group_name') AS ad_group_name,
                       MAX(raw_json->>'match_type')    AS match_type,
                       MAX(quality_score)              AS quality_score,
                       SUM(spend)                     AS spend,
                       SUM(clicks)                    AS clicks,
                       SUM(conversions)               AS conversions,
                       SUM(impressions)               AS impressions
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id = 'excel_upload'
                  AND entity_level = 'keyword'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                GROUP BY entity_id
                ORDER BY SUM(spend) DESC
                LIMIT 200
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            kw_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            # ── Step 3: Search terms (LIMIT 100) ──────────────────────────────
            cur.execute(
                """
                SELECT entity_id,
                       MAX(entity_name)             AS search_term,
                       MAX(raw_json->>'keyword')    AS keyword,
                       MAX(raw_json->>'match_type') AS match_type,
                       SUM(spend)                  AS spend,
                       SUM(conversions)            AS conversions,
                       SUM(clicks)                 AS clicks
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND account_id = 'excel_upload'
                  AND entity_level = 'search_term'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                GROUP BY entity_id
                ORDER BY SUM(spend) DESC
                LIMIT 100
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            st_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            # ── Last upload date ──────────────────────────────────────────────
            cur.execute(
                "SELECT MAX(hour_ts) FROM kpi_hourly WHERE workspace_id = %s AND account_id = 'excel_upload'",
                (workspace_id,),
            )
            ts_row = cur.fetchone()
            last_upload_date = ts_row[0].strftime("%Y-%m-%d") if ts_row and ts_row[0] else None

    # ── Build campaign objects with health scoring ─────────────────────────────
    campaigns = []
    for r in campaign_rows:
        spend = float(r["spend"] or 0)
        revenue = float(r["revenue"] or 0)
        conversions = float(r["conversions"] or 0)
        clicks = int(r["clicks"] or 0)
        impressions = int(r["impressions"] or 0)
        roas = round(revenue / spend, 2) if spend > 0 else 0
        ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0
        cpc = round(spend / clicks, 2) if clicks > 0 else 0

        if roas >= 2.5:
            health, health_reason = "good", f"ROAS {roas:.2f}x ≥ 2.5x target"
        elif spend > 0 and conversions == 0:
            health, health_reason = "critical", f"₹{spend:,.0f} spent, 0 conversions"
        elif roas < 1.0:
            health, health_reason = "critical", f"ROAS {roas:.2f}x — losing money"
        else:
            health, health_reason = "warning", f"ROAS {roas:.2f}x below 2.5x target"

        campaigns.append({
            "id": r["entity_id"] or "",
            "name": r["name"] or "Unknown Campaign",
            "spend": spend, "roas": roas, "conversions": conversions,
            "clicks": clicks, "ctr": ctr, "cpc": cpc,
            "health": health, "health_reason": health_reason,
        })

    # ── Build keyword objects ──────────────────────────────────────────────────
    keywords = []
    for r in kw_rows:
        spend = float(r["spend"] or 0)
        conversions = float(r["conversions"] or 0)
        clicks = int(r["clicks"] or 0)
        impressions = int(r["impressions"] or 0)
        cpc = round(spend / clicks, 2) if clicks > 0 else 0
        ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0
        keywords.append({
            "keyword": r["keyword"] or "",
            "campaign_name": r["campaign_name"] or "",
            "ad_group_name": r["ad_group_name"] or "",
            "match_type": r["match_type"] or "BROAD",
            "quality_score": int(r["quality_score"]) if r["quality_score"] is not None else None,
            "spend": spend, "clicks": clicks, "conversions": conversions,
            "cpc": cpc, "ctr": ctr,
            "is_wasted": spend > 200 and conversions == 0,
        })

    # ── Build search term objects ──────────────────────────────────────────────
    search_terms = []
    for r in st_rows:
        spend = float(r["spend"] or 0)
        conversions = float(r["conversions"] or 0)
        search_terms.append({
            "search_term": r["search_term"] or "",
            "keyword": r["keyword"] or "",
            "match_type": r["match_type"] or "",
            "spend": spend, "conversions": conversions,
            "is_negative_candidate": spend > 100 and conversions == 0,
        })

    # ── Summary metrics ────────────────────────────────────────────────────────
    total_spend = sum(c["spend"] for c in campaigns)
    total_revenue = sum(float(r["revenue"] or 0) for r in campaign_rows)
    total_conversions = sum(c["conversions"] for c in campaigns)
    total_clicks = sum(c["clicks"] for c in campaigns)
    avg_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0
    wasted_keywords = [kw for kw in keywords if kw["is_wasted"]]
    wasted_spend_total = sum(kw["spend"] for kw in wasted_keywords)

    return {
        "has_data": True,
        "last_upload_date": last_upload_date,
        "total_spend": round(total_spend, 2),
        "total_revenue": round(total_revenue, 2),
        "total_conversions": int(total_conversions),
        "total_clicks": total_clicks,
        "avg_roas": avg_roas,
        "wasted_spend_total": round(wasted_spend_total, 2),
        "campaigns": campaigns,
        "keywords": keywords,
        "search_terms": search_terms,
        "action_plan": [],  # fetched separately via /upload/google-action-plan
    }


@app.get("/upload/google-action-plan")
async def upload_google_action_plan(request: Request, workspace_id: str = None):
    """
    Separate endpoint for Claude AI action plan — called async from the client
    after the main intelligence page loads. Avoids blocking the initial page render.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import re
    import json
    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Get campaigns (try campaign-level first, fallback to keyword aggregation)
            cur.execute(
                """
                SELECT entity_id, MAX(entity_name) AS name,
                       SUM(spend) AS spend, SUM(conversions) AS conversions,
                       SUM(revenue) AS revenue
                FROM kpi_hourly
                WHERE workspace_id=%s AND account_id='excel_upload' AND entity_level='campaign'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                GROUP BY entity_id ORDER BY SUM(spend) DESC
                """, (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            camp_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            if not camp_rows:
                cur.execute(
                    """
                    SELECT raw_json->>'campaign_id' AS entity_id,
                           MAX(raw_json->>'campaign_name') AS name,
                           SUM(spend) AS spend, SUM(conversions) AS conversions,
                           SUM(revenue) AS revenue
                    FROM kpi_hourly
                    WHERE workspace_id=%s AND account_id='excel_upload' AND entity_level='keyword'
                      AND hour_ts >= NOW() - INTERVAL '365 days'
                    GROUP BY raw_json->>'campaign_id' ORDER BY SUM(spend) DESC
                    """, (workspace_id,),
                )
                cols = [d[0] for d in cur.description]
                camp_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            # Get top keywords for context
            cur.execute(
                """
                SELECT MAX(entity_name) AS keyword, MAX(raw_json->>'match_type') AS match_type,
                       MAX(quality_score) AS quality_score,
                       SUM(spend) AS spend, SUM(conversions) AS conversions
                FROM kpi_hourly
                WHERE workspace_id=%s AND account_id='excel_upload' AND entity_level='keyword'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                GROUP BY entity_id ORDER BY SUM(spend) DESC LIMIT 50
                """, (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            kw_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            # Get top negative candidate search terms
            cur.execute(
                """
                SELECT MAX(entity_name) AS search_term, SUM(spend) AS spend, SUM(conversions) AS conversions
                FROM kpi_hourly
                WHERE workspace_id=%s AND account_id='excel_upload' AND entity_level='search_term'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                GROUP BY entity_id HAVING SUM(spend) > 100 AND SUM(conversions) = 0
                ORDER BY SUM(spend) DESC LIMIT 10
                """, (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            neg_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not camp_rows:
        return {"action_plan": []}

    # Build summary
    total_spend = sum(float(r["spend"] or 0) for r in camp_rows)
    total_revenue = sum(float(r["revenue"] or 0) for r in camp_rows)
    total_conv = sum(float(r["conversions"] or 0) for r in camp_rows)
    avg_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0

    # Build prompt sections
    camp_lines = []
    for r in camp_rows[:8]:
        spend = float(r["spend"] or 0)
        revenue = float(r["revenue"] or 0)
        conv = float(r["conversions"] or 0)
        roas = round(revenue / spend, 2) if spend > 0 else 0
        emoji = "✅" if roas >= 2.5 else ("⚠️" if roas >= 1.0 else "🚨")
        camp_lines.append(f"  {emoji} {r['name']}: ₹{spend:,.0f} spend, ROAS {roas:.2f}x, {int(conv)} conv")

    wasted = [r for r in kw_rows if float(r["spend"] or 0) > 200 and float(r["conversions"] or 0) == 0]
    wasted_lines = [
        f"  '{r['keyword']} [{r['match_type'] or 'BROAD'}]' — ₹{float(r['spend']):,.0f} spent, 0 conv"
        for r in wasted[:10]
    ]
    low_qs = [r for r in kw_rows if r["quality_score"] is not None and int(r["quality_score"]) <= 3]
    low_qs_lines = [
        f"  '{r['keyword']} [{r['match_type'] or 'BROAD'}]' — QS:{r['quality_score']}/10, ₹{float(r['spend']):,.0f} spent"
        for r in low_qs[:5]
    ]
    neg_lines = [
        f"  '{r['search_term']}' — ₹{float(r['spend']):,.0f} wasted"
        for r in neg_rows[:5]
    ]

    sections = [
        "You are a Google Ads optimization expert for Indian brands.",
        "ACCOUNT SUMMARY (last 365 days):",
        f"Total Spend: ₹{total_spend:,.0f} | Total Conversions: {int(total_conv)} | Avg ROAS: {avg_roas:.2f}x",
        "", "CAMPAIGNS:",
    ] + (camp_lines or ["  No campaign data"])

    if wasted_lines:
        sections += ["", "WASTED SPEND KEYWORDS (spend > ₹200, 0 conversions):"] + wasted_lines
    if low_qs_lines:
        sections += ["", "LOW QUALITY SCORE KEYWORDS (QS ≤ 3):"] + low_qs_lines
    if neg_lines:
        sections += ["", "SEARCH TERMS TO CONSIDER AS NEGATIVES (spent > ₹100, 0 conv):"] + neg_lines

    sections += [
        "",
        "Provide 8-10 specific, immediately actionable recommendations covering:",
        "1) Campaigns to scale or pause (by exact name), 2) Keywords to pause or change match type,",
        "3) Negative keywords to add from the search terms list, 4) Budget reallocation between campaigns,",
        "5) Quality Score improvements, 6) Bid strategy suggestions, 7) Any quick wins.",
        "Be specific with numbers (spend amounts, ROAS values). Write each action as a complete sentence.",
        'Respond with ONLY a JSON array, nothing else. Example: ["Action one here.", "Action two here."]',
    ]

    action_plan = []
    try:
        import anthropic as _anthropic
        _client = _anthropic.Anthropic()
        msg = _client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": "\n".join(sections)}],
        )
        text = msg.content[0].text.strip()
        # Robust extraction: find outermost [ ... ] to avoid breaking on [BROAD]/[EXACT] inside strings
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1 and end > start:
            action_plan = json.loads(text[start:end + 1])
    except Exception:
        # Fallback: build rule-based plan
        if wasted:
            kw = wasted[0]
            action_plan.append(
                f"Pause '{kw['keyword']} [{kw['match_type'] or 'BROAD'}]' — ₹{float(kw['spend']):,.0f} spent with 0 conversions."
            )
        if low_qs:
            kw = low_qs[0]
            action_plan.append(
                f"Improve ad relevance for '{kw['keyword']}' — Quality Score {kw['quality_score']}/10. Align ad copy and landing page to the keyword intent."
            )
        if neg_rows:
            terms = ', '.join(f"'{r['search_term']}'" for r in neg_rows[:3])
            action_plan.append(f"Add as negative keywords: {terms} — these triggered clicks with zero conversions.")
        if avg_roas < 2.5 and total_spend > 0:
            action_plan.append(
                f"Overall ROAS {avg_roas:.2f}x is below 2.5x target. Shift budget from low-ROAS campaigns to the top performer."
            )
        best = max(camp_rows, key=lambda r: float(r.get("revenue") or 0) / max(float(r.get("spend") or 1), 1), default=None)
        if best:
            best_roas = round(float(best.get("revenue") or 0) / max(float(best.get("spend") or 1), 1), 2)
            action_plan.append(f"Increase daily budget for '{best['name']}' — your highest-ROAS campaign at {best_roas:.2f}x.")
        if not action_plan:
            action_plan = [f"ROAS: {avg_roas:.2f}x on ₹{total_spend:,.0f} spend. Review keyword match types and add negatives from Search Terms report."]

    return {"action_plan": action_plan}


# ── Meta campaign breakdown (frequency / placement / age-gender) ────────────

@app.get("/meta/campaign-breakdown/{campaign_id}")
async def meta_campaign_breakdown(
    campaign_id: str,
    request: Request,
    workspace_id: str = None,
):
    """
    Return the most recent fb_deep_insights row for the workspace.
    Fields: frequency[], placement[], age_gender[].
    Data is account-level (not per-campaign) but is contextualised per campaign panel.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT frequency, placement, age_gender, analysis_date
                FROM fb_deep_insights
                WHERE workspace_id = %s
                ORDER BY analysis_date DESC
                LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()

    if not row:
        return {
            "campaign_id": campaign_id,
            "has_data": False,
            "frequency": [],
            "placement": [],
            "age_gender": [],
        }

    frequency, placement, age_gender, analysis_date = row
    return {
        "campaign_id": campaign_id,
        "has_data": True,
        "analysis_date": analysis_date.isoformat() if analysis_date else None,
        "frequency": frequency or [],
        "placement": placement or [],
        "age_gender": age_gender or [],
    }


# ── Generic action log create ────────────────────────────────────────────────

@app.post("/actions/create")
async def create_action(request: Request):
    """
    Create a pending action in the action_log.
    Body: {workspace_id, platform, entity_id, entity_name, entity_level,
           action_type, description, suggested_value, triggered_by}
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    platform = body.get("platform", "meta")
    entity_id = body.get("entity_id", "manual")
    entity_name = body.get("entity_name", "")
    entity_level = body.get("entity_level", "campaign")
    action_type = body.get("action_type", "review")
    description = body.get("description", "")
    suggested_value = body.get("suggested_value")
    triggered_by = body.get("triggered_by", "dashboard_user")

    new_value = {"description": description, "entity_name": entity_name}
    if suggested_value is not None:
        new_value["suggested_value"] = suggested_value

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO action_log
                    (workspace_id, platform, account_id, entity_level, entity_id,
                     action_type, new_value, triggered_by, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, 'pending')
                RETURNING id, status, ts
                """,
                (
                    workspace_id, platform,
                    entity_id,  # account_id reused as entity ref
                    entity_level, entity_id,
                    action_type,
                    __import__("json").dumps(new_value),
                    triggered_by,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    action_id, status, ts = row
    return {
        "id": str(action_id),
        "status": status,
        "ts": ts.isoformat() if ts else None,
    }


# ── Search Trends (from kpi_hourly search_term data) ────────────────────────

@app.get("/search-trends")
async def search_trends(
    request: Request,
    workspace_id: str = None,
    days: int = 90,
):
    """
    Compute growth signals from kpi_hourly search_term data.
    Returns: [{term, volume, spend, ctr, growth_pct, signal}]
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import json as _json
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH base AS (
                    SELECT
                        COALESCE(entity_name, raw_json->>'search_term', raw_json->>'entity_name') AS term,
                        date_trunc('day', hour_ts) AS day,
                        SUM(COALESCE((raw_json->>'clicks')::numeric, 0)) AS clicks,
                        SUM(COALESCE((raw_json->>'spend')::numeric, 0)) AS spend,
                        SUM(COALESCE((raw_json->>'impressions')::numeric, 0)) AS imps,
                        SUM(COALESCE((raw_json->>'conversions')::numeric, 0)) AS convs
                    FROM kpi_hourly
                    WHERE workspace_id = %s
                      AND entity_level = 'search_term'
                      AND hour_ts >= NOW() - INTERVAL '90 days'
                    GROUP BY 1, 2
                ),
                periods AS (
                    SELECT
                        term,
                        SUM(CASE WHEN day >= NOW() - INTERVAL '30 days' THEN clicks ELSE 0 END) AS clicks_l30,
                        SUM(CASE WHEN day < NOW() - INTERVAL '30 days' THEN clicks ELSE 0 END) AS clicks_p30,
                        SUM(clicks) AS volume,
                        SUM(spend) AS spend,
                        SUM(imps) AS imps_total,
                        SUM(convs) AS convs_total
                    FROM base
                    GROUP BY 1
                    HAVING SUM(clicks) > 0
                )
                SELECT
                    term,
                    volume,
                    spend,
                    CASE WHEN imps_total > 0 THEN ROUND(volume::numeric / imps_total * 100, 2) ELSE 0 END AS ctr,
                    clicks_l30,
                    clicks_p30,
                    convs_total,
                    CASE
                        WHEN clicks_p30 = 0 AND clicks_l30 > 0 THEN 9999
                        WHEN clicks_p30 = 0 THEN 0
                        ELSE ROUND((clicks_l30 - clicks_p30)::numeric / clicks_p30 * 100, 1)
                    END AS growth_pct
                FROM periods
                ORDER BY volume DESC
                LIMIT 200
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    results = []
    for r in rows:
        growth = float(r["growth_pct"] or 0)
        if growth > 100:
            signal = "breakout"
        elif growth > 20:
            signal = "up"
        elif growth < -20:
            signal = "down"
        else:
            signal = "stable"
        results.append({
            "term": r["term"],
            "volume": int(r["volume"] or 0),
            "spend": float(r["spend"] or 0),
            "ctr": float(r["ctr"] or 0),
            "growth_pct": growth,
            "signal": signal,
            "conversions": int(r["convs_total"] or 0),
        })

    # Wasted spend: spend > 500, conversions = 0
    wasted = [r for r in results if r["spend"] > 500 and r["conversions"] == 0]
    rising = [r for r in results if r["signal"] in ("breakout", "up")]

    return {
        "has_data": len(results) > 0,
        "terms": results,
        "rising": rising,
        "wasted": wasted,
        "workspace_id": workspace_id,
    }


# ── Competitor Intel (from google_auction_insights) ──────────────────────────

@app.get("/competitor-intel")
async def competitor_intel(
    request: Request,
    workspace_id: str = None,
):
    """Return auction insight rows for the workspace."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT competitor_domain, campaign_name,
                       ROUND(AVG(impression_share)::numeric, 2) AS impression_share,
                       ROUND(AVG(overlap_rate)::numeric, 2) AS overlap_rate,
                       ROUND(AVG(position_above_rate)::numeric, 2) AS position_above_rate,
                       ROUND(AVG(top_of_page_rate)::numeric, 2) AS top_of_page_rate,
                       ROUND(AVG(outranking_share)::numeric, 2) AS outranking_share
                FROM google_auction_insights
                WHERE workspace_id = %s
                GROUP BY competitor_domain, campaign_name
                ORDER BY impression_share DESC NULLS LAST
                LIMIT 20
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    competitors = [
        {k: (float(v) if v is not None else None) if k not in ("competitor_domain", "campaign_name") else v
         for k, v in r.items()}
        for r in rows
    ]

    return {
        "has_data": len(competitors) > 0,
        "competitors": competitors,
        "workspace_id": workspace_id,
    }


@app.post("/competitor-intel/ai-analysis")
async def competitor_intel_ai(request: Request):
    """
    Generate a 4-point beat-them strategy using top auction insight competitors.
    Body: {workspace_id}
    Cached result served if generated today.
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import json as _json
    from services.agent_swarm.db import get_conn

    # Check for today's cached analysis
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT new_value FROM action_log
                WHERE workspace_id = %s
                  AND action_type = 'competitor_ai_analysis'
                  AND ts::date = CURRENT_DATE
                ORDER BY ts DESC LIMIT 1
                """,
                (workspace_id,),
            )
            cached = cur.fetchone()
            if cached and cached[0]:
                cached_data = cached[0] if isinstance(cached[0], dict) else _json.loads(cached[0])
                if "strategies" in cached_data:
                    return {"strategies": cached_data["strategies"], "from_cache": True}

    # Fetch top competitors
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT competitor_domain,
                       ROUND(AVG(impression_share)::numeric, 1) AS impression_share,
                       ROUND(AVG(overlap_rate)::numeric, 1) AS overlap_rate,
                       ROUND(AVG(position_above_rate)::numeric, 1) AS position_above_rate
                FROM google_auction_insights
                WHERE workspace_id = %s
                GROUP BY competitor_domain
                ORDER BY impression_share DESC NULLS LAST
                LIMIT 3
                """,
                (workspace_id,),
            )
            top = cur.fetchall()

    if not top:
        return {"strategies": [], "has_data": False}

    comp_lines = "\n".join(
        f"- {r[0]}: Imp Share {r[1]}%, Overlap {r[2]}%, Position Above {r[3]}%"
        for r in top
    )

    import anthropic as _anthropic
    from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""You are a Google Ads strategist. Based on auction insight data, generate 4 concrete, actionable counter-strategies.

Top competitors (from Google Auction Insights):
{comp_lines}

Output exactly 4 strategies as a JSON array of strings. Each strategy should be 1-2 sentences and highly specific.
Example format: ["Strategy 1 text.", "Strategy 2 text.", "Strategy 3 text.", "Strategy 4 text."]
Return ONLY the JSON array, no other text."""

    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        start, end = text.find("["), text.rfind("]")
        strategies = _json.loads(text[start:end + 1]) if start != -1 else [text]
    except Exception:
        strategies = [
            f"Bid aggressively against {top[0][0]} — they hold {top[0][1]}% impression share. Increase bids on your top keywords by 20%.",
            "Add competitor brand names as keywords with dedicated landing pages highlighting your advantages.",
            "Run RLSA campaigns targeting users who searched competitor terms — these are high-intent prospects.",
            "Analyse competitor ad copy and create ads emphasising your unique differentiators (price, accuracy, support).",
        ]

    # Cache result
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO action_log
                    (workspace_id, platform, account_id, entity_level, entity_id,
                     action_type, new_value, triggered_by, status)
                VALUES (%s, 'google', 'system', 'account', 'system',
                        'competitor_ai_analysis', %s::jsonb, 'ai', 'executed')
                """,
                (workspace_id, _json.dumps({"strategies": strategies})),
            )
        conn.commit()

    return {"strategies": strategies, "from_cache": False}


# ── Comments / Voice of Customer (from search terms) ────────────────────────

@app.get("/comments/insights")
async def comments_insights(
    request: Request,
    workspace_id: str = None,
):
    """
    Derive Voice of Customer signals from kpi_hourly search_term data.
    pain_terms: spend > ₹500 and conversions = 0 (objection/barrier signals)
    winning_terms: conversions > 0, sorted by conversion rate
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(entity_name, raw_json->>'search_term', raw_json->>'entity_name') AS term,
                    SUM(COALESCE((raw_json->>'spend')::numeric, 0)) AS spend,
                    SUM(COALESCE((raw_json->>'clicks')::numeric, 0)) AS clicks,
                    SUM(COALESCE((raw_json->>'conversions')::numeric, 0)) AS conversions,
                    SUM(COALESCE((raw_json->>'impressions')::numeric, 0)) AS impressions
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND entity_level = 'search_term'
                  AND hour_ts >= NOW() - INTERVAL '90 days'
                GROUP BY 1
                HAVING COALESCE(entity_name, raw_json->>'search_term', raw_json->>'entity_name') IS NOT NULL
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    pain_terms = []
    winning_terms = []

    for r in rows:
        spend = float(r["spend"] or 0)
        conversions = float(r["conversions"] or 0)
        clicks = float(r["clicks"] or 0)
        term = r["term"]

        if spend > 500 and conversions == 0:
            pain_terms.append({
                "term": term,
                "spend": spend,
                "clicks": int(clicks),
                "signal": "Customer Barrier",
                "insight": f"₹{spend:,.0f} spent with 0 conversions — likely an objection or irrelevant intent",
            })
        elif conversions > 0:
            conv_rate = conversions / clicks * 100 if clicks > 0 else 0
            winning_terms.append({
                "term": term,
                "spend": spend,
                "clicks": int(clicks),
                "conversions": int(conversions),
                "conv_rate": round(conv_rate, 2),
                "signal": "Resonating Message",
                "insight": f"{int(conversions)} conversions at {conv_rate:.1f}% CVR — this message resonates",
            })

    pain_terms.sort(key=lambda x: -x["spend"])
    winning_terms.sort(key=lambda x: -x["conv_rate"])

    return {
        "has_data": len(pain_terms) + len(winning_terms) > 0,
        "pain_terms": pain_terms[:20],
        "winning_terms": winning_terms[:20],
        "workspace_id": workspace_id,
    }


# ── Campaign Planner ─────────────────────────────────────────────────────────

@app.get("/campaign-planner/plans")
async def campaign_planner_plans(
    request: Request,
    workspace_id: str = None,
    limit: int = 20,
):
    """Return create_campaign actions from action_log for the workspace."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, action_type, new_value, triggered_by, status, ts
                FROM action_log
                WHERE workspace_id = %s
                  AND action_type = 'create_campaign'
                ORDER BY ts DESC
                LIMIT %s
                """,
                (workspace_id, limit),
            )
            cols = [d[0] for d in cur.description]
            plans = []
            for r in cur.fetchall():
                row = dict(zip(cols, r))
                row["id"] = str(row["id"])
                if row.get("ts"):
                    row["ts"] = row["ts"].isoformat()
                plans.append(row)

    return {"plans": plans, "count": len(plans), "workspace_id": workspace_id}


@app.post("/campaign-planner/create-brief")
async def campaign_planner_create_brief(request: Request):
    """
    Accept a campaign brief, call Claude to generate a concept,
    insert into action_log as a draft, and return the concept.
    Body: {workspace_id, product_name, product_price, audience_description,
           goal, budget_daily, duration_days, channels[]}
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    product_name = body.get("product_name", "")
    product_price = body.get("product_price", "")
    audience = body.get("audience_description", "")
    goal = body.get("goal", "conversions")
    budget_daily = body.get("budget_daily", 0)
    duration_days = body.get("duration_days", 14)
    channels = body.get("channels", ["meta"])

    import json as _json
    import anthropic as _anthropic
    from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

    prompt = f"""You are an expert performance marketing strategist for an Indian health tech brand.
Create a complete campaign concept for the following brief:

Product: {product_name} (Price: ₹{product_price})
Target Audience: {audience}
Campaign Goal: {goal}
Daily Budget: ₹{budget_daily}
Duration: {duration_days} days
Channels: {', '.join(channels)}

Generate a JSON object with exactly these keys:
- headline: (string) Primary ad headline, max 40 chars
- body_copy: (string) 2-3 sentence ad body copy
- hook: (string) Opening hook for video/reel, 1 sentence
- creative_direction: (string) Visual/creative guidance, 2-3 sentences
- recommended_format: (string) e.g. "Carousel + Reel" or "Search + Display"
- kpi_targets: {{expected_roas: number, expected_cpa: number, expected_ctr: number}}
- rationale: (string) Why this approach for this audience

Return ONLY valid JSON, no markdown."""

    client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    concept = {}
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        concept = _json.loads(text[start:end]) if start != -1 else {}
    except Exception as e:
        concept = {
            "headline": f"Discover {product_name}",
            "body_copy": f"Transform your health with {product_name}. Trusted by thousands of Indians.",
            "hook": "What if you could monitor your health anywhere, anytime?",
            "creative_direction": "Show the product in use by a relatable Indian family. Focus on ease and peace of mind.",
            "recommended_format": "Video + Carousel",
            "kpi_targets": {"expected_roas": 2.5, "expected_cpa": 800, "expected_ctr": 2.0},
            "rationale": "Benefit-led creative with social proof performs best in health tech category.",
            "error": str(e),
        }

    new_value = {
        "brief": {
            "product_name": product_name,
            "product_price": product_price,
            "audience_description": audience,
            "goal": goal,
            "budget_daily": budget_daily,
            "duration_days": duration_days,
            "channels": channels,
        },
        "concept": concept,
    }

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO action_log
                    (workspace_id, platform, account_id, entity_level, entity_id,
                     action_type, new_value, triggered_by, status)
                VALUES (%s, %s, 'manual', 'campaign', 'new',
                        'create_campaign', %s::jsonb, 'dashboard_user', 'pending')
                RETURNING id, ts
                """,
                (
                    workspace_id,
                    channels[0] if channels else "meta",
                    _json.dumps(new_value),
                ),
            )
            row = cur.fetchone()
        conn.commit()

    plan_id, ts = row
    return {
        "plan_id": str(plan_id),
        "concept": concept,
        "ts": ts.isoformat() if ts else None,
        "status": "pending",
    }


@app.post("/campaign-planner/generate-image")
async def campaign_planner_generate_image(request: Request):
    """
    Generate a creative image for a campaign plan using fal.ai Flux Pro.
    Saves the image URL back into the plan's new_value.concept.generated_image_url.
    Body: {plan_id, workspace_id}
    """
    _auth(request)
    body = await request.json()
    plan_id     = body.get("plan_id")
    workspace_id= body.get("workspace_id")
    if not plan_id or not workspace_id:
        raise HTTPException(status_code=400, detail="plan_id and workspace_id required")

    import json as _json
    from services.agent_swarm.db import get_conn

    # Load plan
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT new_value FROM action_log WHERE id=%s AND workspace_id=%s",
                (plan_id, workspace_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")

    nv = row[0] if isinstance(row[0], dict) else _json.loads(row[0] or "{}")
    concept = nv.get("concept", {})
    brief   = nv.get("brief", {})

    creative_direction = concept.get("creative_direction", "")
    headline           = concept.get("headline", "")
    product_name       = brief.get("product_name", "health tech product")

    if not creative_direction:
        raise HTTPException(status_code=400, detail="No creative_direction in plan — regenerate the brief first")

    # Build a rich image prompt from the creative brief
    prompt = (
        f"Professional Indian health tech advertisement creative. "
        f"Product: {product_name}. "
        f"{creative_direction} "
        f"No text overlays. No watermarks. No logos. "
        f"Clean, modern aesthetic. Warm aspirational lighting. "
        f"Real Indian people, relatable lifestyle setting. "
        f"Square format, suitable for Instagram and Facebook feed ads."
    )

    try:
        from services.agent_swarm.creative.image_gen import generate_ad_image
        image_url = generate_ad_image(prompt, size="square_hd")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {e}")

    # Store image URL back in plan
    nv_updated = dict(nv)
    nv_updated["concept"] = {**concept, "generated_image_url": image_url}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE action_log SET new_value=%s::jsonb WHERE id=%s",
                (_json.dumps(nv_updated), plan_id),
            )
        conn.commit()

    return {"ok": True, "image_url": image_url, "plan_id": plan_id}


@app.post("/campaign-planner/publish-ad")
async def campaign_planner_publish_ad(request: Request):
    """
    Create the actual Meta Ad (PAUSED) on an already-created Campaign + Ad Set.
    Requires the plan to have: meta_adset_id, concept.generated_image_url, concept.body_copy, concept.headline.
    Body: {plan_id, workspace_id}
    """
    _auth(request)
    body = await request.json()
    plan_id     = body.get("plan_id")
    workspace_id= body.get("workspace_id")
    if not plan_id or not workspace_id:
        raise HTTPException(status_code=400, detail="plan_id and workspace_id required")

    import json as _json
    import requests as _requests
    from services.agent_swarm.db import get_conn

    # Load plan
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT new_value FROM action_log WHERE id=%s AND workspace_id=%s",
                (plan_id, workspace_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")

    nv      = row[0] if isinstance(row[0], dict) else _json.loads(row[0] or "{}")
    concept = nv.get("concept", {})

    adset_id  = nv.get("meta_adset_id")
    image_url = concept.get("generated_image_url")
    body_copy = concept.get("body_copy", "")
    headline  = concept.get("headline", "Ad")

    if not adset_id:
        raise HTTPException(status_code=400, detail="No meta_adset_id — approve the plan in Decision Inbox first")
    if not image_url:
        raise HTTPException(status_code=400, detail="No generated image — click Generate Creative first")

    # Load Meta connection
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT ad_account_id, access_token, pixel_id
                   FROM platform_connections
                   WHERE workspace_id=%s AND platform='meta'
                   ORDER BY is_primary DESC LIMIT 1""",
                (workspace_id,),
            )
            meta_row = cur.fetchone()
    if not meta_row or not meta_row[1]:
        raise HTTPException(status_code=400, detail="No Meta connection found")

    ad_account_id, access_token, pixel_id = meta_row
    act_id = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
    META_API_VERSION = "v21.0"

    try:
        from services.agent_swarm.creative.meta_publisher import (
            upload_image_from_url, create_ad_creative,
        )
        tenant = {"meta_access_token": access_token, "pixel_id": pixel_id}

        # 1. Upload image to Meta
        image_hash = upload_image_from_url(image_url, act_id, tenant)

        # 2. Create Ad Creative
        creative_id = create_ad_creative(
            account_id=act_id,
            image_hash=image_hash,
            primary_text=body_copy,
            headline=headline,
            description="",
            cta="SHOP_NOW",
            tenant=tenant,
        )

        # 3. Create Ad as PAUSED
        ad_url = f"https://graph.facebook.com/{META_API_VERSION}/{act_id}/ads"
        ad_resp = _requests.post(
            ad_url,
            params={"access_token": access_token},
            data={
                "name": f"{headline[:40]} — Ad",
                "adset_id": adset_id,
                "creative": _json.dumps({"creative_id": creative_id}),
                "status": "PAUSED",
            },
            timeout=20,
        )
        ad_data = ad_resp.json()
        if not ad_resp.ok or "error" in ad_data:
            err = ad_data.get("error", {})
            raise RuntimeError(err.get("message", ad_resp.text[:200]))

        meta_ad_id = ad_data["id"]

        # Store ad_id back in plan
        nv_updated = dict(nv)
        nv_updated["meta_ad_id"] = meta_ad_id
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE action_log SET new_value=%s::jsonb WHERE id=%s",
                    (_json.dumps(nv_updated), plan_id),
                )
            conn.commit()

        return {
            "ok": True,
            "meta_ad_id": meta_ad_id,
            "creative_id": creative_id,
            "image_hash": image_hash,
            "note": "Ad created on Meta (PAUSED) — activate in Meta Ads Manager when ready",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ad creation failed: {e}")


# ── Campaign Planner — AI Auto-Generate (uses workspace context) ─────────────

@app.post("/campaign-planner/auto-generate")
async def campaign_planner_auto_generate(request: Request):
    """
    One-click AI campaign generation. No user input needed — Claude reads
    the workspace's products, recent KPIs and growth data to recommend
    a complete multi-platform campaign plan.
    Body: {workspace_id}
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import json as _json
    import anthropic as _anthropic
    from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    from services.agent_swarm.db import get_conn

    # Gather workspace context
    context_parts = []

    # 1. Products from catalog
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT name, description, price, product_url
                       FROM products WHERE workspace_id = %s
                       ORDER BY updated_at DESC LIMIT 5""",
                    (workspace_id,),
                )
                products = cur.fetchall()
        if products:
            context_parts.append("PRODUCTS IN CATALOG:\n" + "\n".join(
                f"- {p[0]}: {p[1][:120] if p[1] else ''} | Price: ₹{p[2] or '?'} | URL: {p[3] or '—'}"
                for p in products
            ))
    except Exception as e:
        print(f"Auto-generate products fetch error: {e}")

    # 2. Recent KPI performance (last 30 days)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT platform,
                           ROUND(SUM(COALESCE(spend,0))::numeric,0) AS spend,
                           ROUND(SUM(COALESCE(conversions,0))::numeric,0) AS convs,
                           ROUND(SUM(COALESCE(revenue,0))::numeric,0) AS revenue,
                           ROUND(SUM(COALESCE(clicks,0))::numeric,0) AS clicks
                    FROM kpi_hourly
                    WHERE workspace_id = %s
                      AND entity_level = 'campaign'
                      AND hour_ts >= NOW() - INTERVAL '30 days'
                    GROUP BY platform
                    """,
                    (workspace_id,),
                )
                kpis = cur.fetchall()
        if kpis:
            context_parts.append("RECENT KPI PERFORMANCE (30 days):\n" + "\n".join(
                f"- {k[0].upper()}: Spend ₹{k[1]:,.0f} | Conversions {k[2]} | Revenue ₹{k[3]:,.0f} | Clicks {k[4]:,.0f}"
                for k in kpis
            ))
    except Exception as e:
        print(f"Auto-generate KPI fetch error: {e}")

    # 3. Best-performing campaigns
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entity_name, platform,
                           ROUND(SUM(COALESCE(spend,0))::numeric,0) AS spend,
                           ROUND(SUM(COALESCE(conversions,0))::numeric,0) AS convs,
                           ROUND(CASE WHEN SUM(COALESCE(spend,0))>0
                                 THEN SUM(COALESCE(revenue,0))/SUM(COALESCE(spend,0))
                                 ELSE 0 END::numeric, 2) AS roas
                    FROM kpi_hourly
                    WHERE workspace_id = %s
                      AND entity_level = 'campaign'
                      AND hour_ts >= NOW() - INTERVAL '90 days'
                    GROUP BY entity_name, platform
                    HAVING SUM(COALESCE(spend,0)) > 100
                    ORDER BY roas DESC LIMIT 5
                    """,
                    (workspace_id,),
                )
                best = cur.fetchall()
        if best:
            context_parts.append("TOP PERFORMING CAMPAIGNS (90 days):\n" + "\n".join(
                f"- [{b[1]}] {b[0]}: Spend ₹{b[2]:,.0f} | Conversions {b[3]} | ROAS {b[4]}x"
                for b in best
            ))
    except Exception as e:
        print(f"Auto-generate best campaigns fetch error: {e}")

    workspace_context = "\n\n".join(context_parts) if context_parts else "No historical data available yet."

    prompt = f"""You are a senior performance marketing strategist for an Indian health tech brand.
Based on the workspace data below, generate a COMPLETE AI-recommended campaign plan to maximise growth.

{workspace_context}

Generate a JSON object with exactly these keys:
- headline: (string) Primary campaign headline, max 40 chars
- body_copy: (string) 2-3 sentence campaign rationale/copy
- hook: (string) Opening hook for video/reel, 1 sentence
- creative_direction: (string) Specific visual + messaging guidance, 2-3 sentences
- recommended_format: (string) e.g. "Meta Reels + Google Search + YouTube Pre-roll"
- recommended_channels: (array of strings) e.g. ["meta","google","youtube"]
- recommended_budget_daily: (number) INR daily budget recommendation based on current spend
- recommended_duration_days: (number) e.g. 30
- kpi_targets: {{expected_roas: number, expected_cpa: number, expected_ctr: number}}
- rationale: (string) Detailed reasoning — what to scale, what to fix, what's the growth lever
- growth_insights: (array of strings) 3-5 specific actionable insights from the data

Return ONLY valid JSON, no markdown."""

    client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    concept = {}
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        concept = _json.loads(text[start:end]) if start != -1 else {}
    except Exception as e:
        concept = {
            "headline": "Scale What's Working",
            "body_copy": "Based on your performance data, focus on increasing budget on top ROAS campaigns while testing new creatives.",
            "hook": "Your data shows a clear growth lever — here's how to unlock it.",
            "creative_direction": "Benefit-led video content with real user testimonials. Lead with the health outcome, not the product.",
            "recommended_format": "Meta Reels + Google Search",
            "recommended_channels": ["meta", "google"],
            "recommended_budget_daily": 5000,
            "recommended_duration_days": 30,
            "kpi_targets": {"expected_roas": 2.5, "expected_cpa": 600, "expected_ctr": 2.5},
            "rationale": "Double down on channels with proven ROAS > 2x while reducing spend on underperforming campaigns.",
            "growth_insights": [
                "Scale spend on campaigns with ROAS > 2x",
                "Pause campaigns with 0 conversions after 7 days",
                "Test video creative for awareness stage",
            ],
            "error": str(e),
        }

    new_value = {"concept": concept, "auto_generated": True, "context_used": bool(context_parts)}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO action_log
                    (workspace_id, platform, account_id, entity_level, entity_id,
                     action_type, new_value, triggered_by, status)
                VALUES (%s, 'meta', 'auto', 'campaign', 'new',
                        'create_campaign', %s::jsonb, 'ai_auto', 'pending')
                RETURNING id, ts
                """,
                (workspace_id, _json.dumps(new_value)),
            )
            row = cur.fetchone()
        conn.commit()

    plan_id, ts = row
    return {
        "plan_id": str(plan_id),
        "concept": concept,
        "ts": ts.isoformat() if ts else None,
        "status": "pending",
        "auto_generated": True,
        "context_used": bool(context_parts),
    }


# ── Campaign Planner — Launch (Campaign + Ad Set on Meta) ────────────────────

@app.post("/campaign-planner/launch")
async def campaign_planner_launch(request: Request):
    """
    Confirms a plan is in the approvals queue (no Meta API call happens here).
    Actual campaign creation on Meta happens when user Approves in Decision Inbox.
    Body: {plan_id, workspace_id}
    """
    _auth(request)
    body = await request.json()
    plan_id = body.get("plan_id")
    workspace_id = body.get("workspace_id")
    if not plan_id or not workspace_id:
        raise HTTPException(status_code=400, detail="plan_id and workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status FROM action_log WHERE id = %s AND workspace_id = %s",
                (plan_id, workspace_id),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Plan not found")

    return {
        "ok": True,
        "plan_id": str(row[0]),
        "status": row[1],
        "redirect": "/approvals",
        "message": "Plan is in your Decision Inbox — approve there to launch on Meta",
    }


# ── Organic Posts signals (Meta campaign CTR as content signals) ─────────────

@app.get("/organic-posts/signals")
async def organic_posts_signals(
    request: Request,
    workspace_id: str = None,
):
    """
    Return Meta campaign CTR signals and hour-of-day data.
    High CTR campaigns are proxies for engaging content themes.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Check if Meta is connected (live API or uploaded data)
            cur.execute(
                """
                SELECT COUNT(*) FROM platform_connections
                WHERE workspace_id = %s AND platform = 'meta'
                """,
                (workspace_id,),
            )
            meta_live_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*) FROM kpi_hourly
                WHERE workspace_id = %s AND (platform = 'meta' OR platform IS NULL)
                  AND entity_level = 'campaign'
                LIMIT 1
                """,
                (workspace_id,),
            )
            meta_upload_count = cur.fetchone()[0]

            meta_connected = (meta_live_count > 0) or (meta_upload_count > 0)

            # Top campaigns by CTR (Meta, last 365 days — covers uploaded historical data)
            cur.execute(
                """
                SELECT
                    COALESCE(entity_name, raw_json->>'campaign_name', raw_json->>'name') AS name,
                    SUM(COALESCE((raw_json->>'clicks')::numeric, 0)) AS clicks,
                    SUM(COALESCE((raw_json->>'impressions')::numeric, 0)) AS impressions,
                    SUM(COALESCE((raw_json->>'spend')::numeric, 0)) AS spend,
                    CASE
                        WHEN SUM(COALESCE((raw_json->>'impressions')::numeric, 0)) > 0
                        THEN ROUND(
                            SUM(COALESCE((raw_json->>'clicks')::numeric, 0)) /
                            SUM(COALESCE((raw_json->>'impressions')::numeric, 0)) * 100, 2
                        )
                        ELSE 0
                    END AS ctr
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND (platform = 'meta' OR platform IS NULL)
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                GROUP BY 1
                HAVING SUM(COALESCE((raw_json->>'impressions')::numeric, 0)) > 100
                ORDER BY ctr DESC
                LIMIT 10
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            top_campaigns = [dict(zip(cols, r)) for r in cur.fetchall()]

            # Best hours from hour_of_day entity level (365 days)
            cur.execute(
                """
                SELECT
                    COALESCE(entity_name, raw_json->>'hour', (raw_json->>'hour_of_day')) AS hour,
                    ROUND(AVG(COALESCE((raw_json->>'ctr')::numeric, 0)), 2) AS avg_ctr,
                    SUM(COALESCE((raw_json->>'conversions')::numeric, 0)) AS conversions
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND entity_level = 'hour_of_day'
                  AND hour_ts >= NOW() - INTERVAL '365 days'
                GROUP BY 1
                HAVING hour IS NOT NULL
                ORDER BY avg_ctr DESC
                LIMIT 5
                """,
                (workspace_id,),
            )
            cols2 = [d[0] for d in cur.description]
            best_hours = [dict(zip(cols2, r)) for r in cur.fetchall()]

    campaigns_clean = []
    for c in top_campaigns:
        campaigns_clean.append({
            "name": c["name"],
            "ctr": float(c["ctr"] or 0),
            "clicks": int(c["clicks"] or 0),
            "impressions": int(c["impressions"] or 0),
            "spend": float(c["spend"] or 0),
        })

    hours_clean = []
    for h in best_hours:
        hours_clean.append({
            "hour": h["hour"],
            "avg_ctr": float(h["avg_ctr"] or 0),
            "conversions": int(h["conversions"] or 0),
        })

    return {
        "meta_connected": meta_connected,
        "has_meta_data": len(campaigns_clean) > 0,
        "has_timing_data": len(hours_clean) > 0,
        "top_campaigns": campaigns_clean,
        "best_hours": hours_clean,
        "workspace_id": workspace_id,
    }


# ── KPI Summary for Awareness page blended CAC ──────────────────────────────

@app.get("/kpi/summary")
async def kpi_summary(
    request: Request,
    workspace_id: str = None,
    days: int = 365,
):
    """
    Aggregate spend + conversions across all platforms for blended CAC.
    Returns: {total_spend, total_conversions, blended_cac, total_revenue, blended_roas}
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    SUM(COALESCE((raw_json->>'spend')::numeric, 0)) AS total_spend,
                    SUM(COALESCE((raw_json->>'conversions')::numeric, 0)) AS total_conversions,
                    SUM(COALESCE((raw_json->>'revenue')::numeric, 0)) AS total_revenue
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - (%s * INTERVAL '1 day')
                """,
                (workspace_id, days),
            )
            row = cur.fetchone()

    total_spend = float(row[0] or 0)
    total_conversions = float(row[1] or 0)
    total_revenue = float(row[2] or 0)
    blended_cac = total_spend / total_conversions if total_conversions > 0 else None
    blended_roas = total_revenue / total_spend if total_spend > 0 else None

    return {
        "total_spend": total_spend,
        "total_conversions": int(total_conversions),
        "total_revenue": total_revenue,
        "blended_cac": round(blended_cac, 2) if blended_cac else None,
        "blended_roas": round(blended_roas, 2) if blended_roas else None,
        "workspace_id": workspace_id,
        "days": days,
    }


# ── GA4 Analytics ────────────────────────────────────────────────────────────

def _get_ga4_connector(workspace_id: str):
    """
    Load GA4 credentials from google_auth_tokens and return a GA4Connector.
    Raises HTTPException(400) if not connected or no property found.
    """
    from services.agent_swarm.connectors.ga4 import GA4Connector
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT access_token, refresh_token, client_id, client_secret, ga4_property_id
                FROM google_auth_tokens
                WHERE workspace_id = %s
                LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=400, detail="Google not connected for this workspace")
    access_token, refresh_token, client_id, client_secret, ga4_property_id = row
    if not ga4_property_id:
        raise HTTPException(
            status_code=400,
            detail="GA4 property not found. Reconnect Google (disconnect + reconnect in Settings) to auto-discover your GA4 property.",
        )
    return GA4Connector(
        access_token=access_token or "",
        refresh_token=refresh_token or "",
        property_id=ga4_property_id,
        client_id=client_id or "",
        client_secret=client_secret or "",
    )


@app.get("/ga4/status")
async def ga4_status(request: Request, workspace_id: str = None):
    """
    Return GA4 connection status for the workspace.
    If Google is connected but ga4_property_id is missing, attempt lazy discovery
    using the stored access token — so the user doesn't need to reconnect.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT access_token, refresh_token, client_id, client_secret,
                       ga4_property_id, updated_at
                FROM google_auth_tokens
                WHERE workspace_id = %s
                LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()

    if not row or not row[0]:
        return {"connected": False, "property_id": None, "has_property": False}

    access_token, refresh_token, client_id, client_secret, property_id, updated_at = row

    # ── Lazy GA4 property discovery ─────────────────────────────────────────
    # If Google is connected but we don't have the property_id yet, try to
    # discover it now (e.g. user connected before this feature was added).
    if not property_id and access_token:
        from services.agent_swarm.connectors.ga4 import GA4Connector
        from services.agent_swarm.db import get_conn as _gc
        try:
            # Try with stored access token first; if expired GA4Connector will
            # refresh it internally when the next API call is made.
            discovered = GA4Connector.discover_property_id(access_token)
            if not discovered and refresh_token and client_id and client_secret:
                # Refresh token and retry
                import requests as rq
                tr = rq.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id, "client_secret": client_secret,
                        "refresh_token": refresh_token, "grant_type": "refresh_token",
                    },
                    timeout=15,
                )
                if tr.ok:
                    new_token = tr.json().get("access_token", "")
                    discovered = GA4Connector.discover_property_id(new_token)
                    if discovered:
                        access_token = new_token  # use refreshed token below

            if discovered:
                property_id = discovered
                with _gc() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE google_auth_tokens SET ga4_property_id = %s WHERE workspace_id = %s",
                            (property_id, workspace_id),
                        )
                    conn.commit()
                print(f"[ga4/status] Lazy-discovered property_id={property_id} for workspace {workspace_id}")
        except Exception as e:
            print(f"[ga4/status] Lazy discovery failed: {e}")

    return {
        "connected": bool(access_token),
        "property_id": property_id,
        "has_property": bool(property_id),
        "last_synced": updated_at.isoformat() if updated_at else None,
    }


@app.get("/ga4/properties")
async def ga4_properties(request: Request, workspace_id: str = None):
    """List all GA4 properties available for the connected Google account."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.connectors.ga4 import GA4Connector
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT access_token, refresh_token, client_id, client_secret FROM google_auth_tokens WHERE workspace_id = %s LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()

    if not row or not row[0]:
        raise HTTPException(status_code=400, detail="Google not connected")

    access_token, refresh_token, client_id, client_secret = row

    # Try current token, refresh if it fails
    props = GA4Connector.list_all_properties(access_token)
    if not props and refresh_token and client_id and client_secret:
        import requests as rq
        tr = rq.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        }, timeout=15)
        if tr.ok:
            props = GA4Connector.list_all_properties(tr.json().get("access_token", ""))

    return {"properties": props, "count": len(props)}


@app.post("/ga4/set-property")
async def ga4_set_property(request: Request):
    """Manually set a GA4 property_id for the workspace."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    property_id = body.get("property_id")
    if not workspace_id or not property_id:
        raise HTTPException(status_code=400, detail="workspace_id and property_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE google_auth_tokens SET ga4_property_id = %s WHERE workspace_id = %s",
                (property_id, workspace_id),
            )
        conn.commit()
    return {"ok": True, "property_id": property_id}


@app.get("/ga4/overview")
async def ga4_overview(request: Request, workspace_id: str = None, days: int = 30):
    """Return GA4 session/user/conversion overview with period-over-period change."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        ga4 = _get_ga4_connector(workspace_id)
        return ga4.get_overview(days=days)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ga4/conversions")
async def ga4_conversions(request: Request, workspace_id: str = None, days: int = 30):
    """Return GA4 conversions grouped by event name."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        ga4 = _get_ga4_connector(workspace_id)
        return {"conversions": ga4.get_conversions(days=days), "days": days}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ga4/landing-pages")
async def ga4_landing_pages(request: Request, workspace_id: str = None, days: int = 30):
    """Return GA4 landing page data with drop-off percentages."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        ga4 = _get_ga4_connector(workspace_id)
        return {"landing_pages": ga4.get_landing_pages(days=days), "days": days}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ga4/traffic-sources")
async def ga4_traffic_sources(request: Request, workspace_id: str = None, days: int = 30):
    """Return GA4 traffic source breakdown."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        ga4 = _get_ga4_connector(workspace_id)
        return {"sources": ga4.get_traffic_sources(days=days), "days": days}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ga4/devices")
async def ga4_devices(request: Request, workspace_id: str = None, days: int = 30):
    """Return GA4 device category breakdown."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        ga4 = _get_ga4_connector(workspace_id)
        return {"devices": ga4.get_devices(days=days), "days": days}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ga4/geo")
async def ga4_geo(request: Request, workspace_id: str = None, days: int = 30):
    """Return GA4 geographic breakdown (country + city)."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        ga4 = _get_ga4_connector(workspace_id)
        return {"geo": ga4.get_geo(days=days), "days": days}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/migrate")
async def admin_migrate(request: Request):
    """
    One-time migration endpoint — runs safe idempotent ALTER TABLE statements.
    Protected by X-Admin-Token header.
    """
    token = request.headers.get("X-Admin-Token", "")
    if not token or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    from services.agent_swarm.db import get_conn
    results = []
    migrations = [
        "ALTER TABLE kpi_hourly ADD COLUMN IF NOT EXISTS entity_name TEXT",
        "ALTER TABLE google_auth_tokens ADD COLUMN IF NOT EXISTS ga4_property_id TEXT",
        """CREATE TABLE IF NOT EXISTS google_auction_insights (
            id                     BIGSERIAL PRIMARY KEY,
            workspace_id           UUID REFERENCES workspaces(id),
            campaign_name          TEXT NOT NULL DEFAULT '',
            competitor_domain      TEXT NOT NULL,
            impression_share       NUMERIC,
            overlap_rate           NUMERIC,
            position_above_rate    NUMERIC,
            top_of_page_rate       NUMERIC,
            abs_top_impression_pct NUMERIC,
            outranking_share       NUMERIC,
            uploaded_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, campaign_name, competitor_domain)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_auction_ws ON google_auction_insights(workspace_id)",
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            for sql in migrations:
                try:
                    cur.execute(sql)
                    results.append({"sql": sql, "ok": True})
                except Exception as e:
                    results.append({"sql": sql, "ok": False, "error": str(e)})
        conn.commit()
    return {"migrations": results}


# ── AI Daily Brief (Growth Engine — dashboard action items) ──────────────────

@app.get("/ai/daily-brief")
async def ai_daily_brief(
    request: Request,
    workspace_id: str = None,
):
    """
    Generate 4 specific, actionable growth opportunities using Claude.
    Analyzes real KPIs, campaigns, competitor intel, and GA4 data.
    Cached for 6 hours to avoid redundant Claude calls.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import json as _json
    import anthropic as _anthropic
    from datetime import timezone as _tz
    from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    from services.agent_swarm.db import get_conn

    # ── Check 6-hour cache ────────────────────────────────────────────────────
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT new_value, ts FROM action_log
                WHERE workspace_id = %s
                  AND triggered_by = 'ai_brief'
                  AND ts >= NOW() - INTERVAL '6 hours'
                ORDER BY ts DESC LIMIT 1
                """,
                (workspace_id,),
            )
            cached = cur.fetchone()

    if cached:
        try:
            payload = _json.loads(cached[0]) if isinstance(cached[0], str) else cached[0]
            opportunities = payload.get("opportunities", [])
            if opportunities:
                return {
                    "opportunities": opportunities,
                    "generated_at": cached[1].isoformat() if cached[1] else None,
                    "cached": True,
                }
        except Exception:
            pass  # fall through to regenerate

    # ── Gather context data ───────────────────────────────────────────────────
    context_parts = []

    with get_conn() as conn:
        with conn.cursor() as cur:
            # KPI summary: 7d
            cur.execute(
                """
                SELECT
                    SUM(spend) AS spend,
                    SUM(impressions) AS impressions,
                    SUM(clicks) AS clicks,
                    SUM(conversions) AS conversions,
                    SUM(revenue) AS revenue,
                    CASE WHEN SUM(spend)>0 THEN ROUND(SUM(revenue)/SUM(spend),2) ELSE 0 END AS roas,
                    CASE WHEN SUM(impressions)>0 THEN ROUND(SUM(clicks)/SUM(impressions)*100,2) ELSE 0 END AS ctr,
                    platform
                FROM kpi_hourly
                WHERE workspace_id = %s AND hour_ts >= NOW() - INTERVAL '7 days'
                GROUP BY platform
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            kpi_7d = [dict(zip(cols, r)) for r in rows]
            context_parts.append(f"KPI last 7 days by platform:\n{_json.dumps([{k: float(v) if isinstance(v, __builtins__.__class__) else v for k, v in r.items()} for r in kpi_7d], default=str)}")

            # Top 5 campaigns by spend (last 30d)
            cur.execute(
                """
                SELECT
                    COALESCE(entity_name, raw_json->>'campaign_name', 'Unknown') AS name,
                    platform,
                    SUM(spend) AS spend,
                    SUM(conversions) AS conversions,
                    CASE WHEN SUM(spend)>0 THEN ROUND(SUM(revenue)/SUM(spend),2) ELSE 0 END AS roas,
                    CASE WHEN SUM(impressions)>0 THEN ROUND(SUM(clicks)/SUM(impressions)*100,2) ELSE 0 END AS ctr
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '30 days'
                GROUP BY 1, 2
                HAVING SUM(spend) > 0
                ORDER BY spend DESC
                LIMIT 5
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            top_campaigns = [dict(zip(cols, r)) for r in rows]
            if top_campaigns:
                context_parts.append(f"Top campaigns last 30 days:\n{_json.dumps(top_campaigns, default=str)}")

            # Worst campaigns (low ROAS, still spending)
            cur.execute(
                """
                SELECT
                    COALESCE(entity_name, raw_json->>'campaign_name', 'Unknown') AS name,
                    platform,
                    SUM(spend) AS spend,
                    CASE WHEN SUM(spend)>0 THEN ROUND(SUM(revenue)/SUM(spend),2) ELSE 0 END AS roas
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND entity_level = 'campaign'
                  AND hour_ts >= NOW() - INTERVAL '7 days'
                GROUP BY 1, 2
                HAVING SUM(spend) > 500
                  AND (SUM(spend)=0 OR SUM(revenue)/SUM(spend) < 1.5)
                ORDER BY spend DESC
                LIMIT 3
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            weak_campaigns = [dict(zip(cols, r)) for r in rows]
            if weak_campaigns:
                context_parts.append(f"Underperforming campaigns (ROAS<1.5x, last 7 days):\n{_json.dumps(weak_campaigns, default=str)}")

            # Competitor intel (auction insights)
            cur.execute(
                """
                SELECT competitor_domain, impression_share, overlap_rate, position_above_rate
                FROM google_auction_insights
                WHERE workspace_id = %s
                ORDER BY impression_share DESC LIMIT 5
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            if rows:
                cols = [d[0] for d in cur.description]
                comps = [dict(zip(cols, r)) for r in rows]
                context_parts.append(f"Top Google competitors (auction insights):\n{_json.dumps(comps, default=str)}")

            # Recent search terms (high impressions, low conversions = opportunity)
            cur.execute(
                """
                SELECT
                    COALESCE(entity_name, raw_json->>'search_term') AS term,
                    SUM(COALESCE((raw_json->>'impressions')::numeric, 0)) AS impressions,
                    SUM(COALESCE((raw_json->>'clicks')::numeric, 0)) AS clicks,
                    SUM(COALESCE((raw_json->>'conversions')::numeric, 0)) AS conversions
                FROM kpi_hourly
                WHERE workspace_id = %s
                  AND entity_level = 'search_term'
                  AND hour_ts >= NOW() - INTERVAL '30 days'
                GROUP BY 1
                HAVING SUM(COALESCE((raw_json->>'impressions')::numeric, 0)) > 50
                ORDER BY impressions DESC
                LIMIT 10
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()
            if rows:
                cols = [d[0] for d in cur.description]
                terms = [dict(zip(cols, r)) for r in rows]
                context_parts.append(f"Top search terms last 30 days:\n{_json.dumps(terms, default=str)}")

            # GA4 traffic sources (if connected)
            cur.execute(
                "SELECT ga4_property_id FROM google_auth_tokens WHERE workspace_id=%s LIMIT 1",
                (workspace_id,),
            )
            ga4_row = cur.fetchone()
            if ga4_row and ga4_row[0]:
                try:
                    from services.agent_swarm.connectors.ga4 import GA4Connector
                    g_row = _get_google_conn_from_db(workspace_id)
                    if g_row:
                        ga4 = GA4Connector(
                            access_token=g_row["access_token"],
                            refresh_token=g_row.get("refresh_token", ""),
                            property_id=ga4_row[0],
                            client_id=g_row.get("client_id", ""),
                            client_secret=g_row.get("client_secret", ""),
                        )
                        overview = ga4.get_overview(days=7)
                        context_parts.append(
                            f"GA4 website last 7 days: sessions={overview.get('sessions')}, "
                            f"conversions={overview.get('conversions')}, revenue={overview.get('revenue')}, "
                            f"bounce_rate={overview.get('bounce_rate')}"
                        )
                except Exception:
                    pass

    context_str = "\n\n---\n\n".join(context_parts) if context_parts else "No performance data yet."

    prompt = f"""You are a senior growth strategist for an Indian D2C health brand.
Analyze this real marketing performance data and generate exactly 4 specific, actionable growth opportunities.

PERFORMANCE DATA:
{context_str}

Generate a JSON array of exactly 4 objects. Each object MUST have these exact keys:
- action_type: one of "increase_budget", "pause_campaign", "new_creative", "geographic_expansion", "keyword_addition", "bid_adjustment", "reduce_budget"
- title: max 6 words, action-focused (e.g. "Scale SanketLife Budget 25%")
- detail: exactly 2 sentences. First sentence: what the data shows (with specific numbers). Second sentence: what to do and why.
- expected_impact: "High", "Medium", or "Low"
- platform: "meta", "google", "youtube", or "all"
- entity_name: the specific campaign/keyword/product name this applies to, or "" if general

Prioritize: High-ROAS campaigns that can be scaled > Underperforming campaigns to pause > New keyword/creative opportunities.
Be specific with rupee amounts and percentages from the actual data.
Return ONLY the JSON array, no other text."""

    try:
        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        opportunities = _json.loads(raw.strip())
        if not isinstance(opportunities, list):
            opportunities = opportunities.get("opportunities", []) if isinstance(opportunities, dict) else []
    except Exception as e:
        # Fallback: return empty with error note
        return {
            "opportunities": [],
            "generated_at": None,
            "cached": False,
            "error": str(e)[:200],
        }

    # ── Cache the result for 6 hours ──────────────────────────────────────────
    cache_payload = _json.dumps({"opportunities": opportunities})
    import uuid as _uuid
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO action_log
                        (workspace_id, platform, account_id, entity_level, entity_id,
                         action_type, new_value, triggered_by, status)
                    VALUES (%s, 'all', 'ai_brief', 'brief', 'daily', 'ai_brief',
                            CAST(%s AS jsonb), 'ai_brief', 'executed')
                    """,
                    (workspace_id, cache_payload),
                )
            conn.commit()
    except Exception:
        pass  # cache failure is non-fatal

    from datetime import datetime as _datetime
    return {
        "opportunities": opportunities,
        "generated_at": _datetime.utcnow().isoformat(),
        "cached": False,
    }
