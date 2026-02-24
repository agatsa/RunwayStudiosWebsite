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

    return {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "tenants_processed": len(all_results),
        "results": all_results,
    }


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


@app.post("/approval/respond")
async def handle_approval(request: Request):
    """
    Called by wa-bot when admin replies 'approve XXXXXXXX' or 'reject XXXXXXXX'.
    Executes or cancels the pending budget-governor action.
    Body: {action_id, decision, phone_number_id?}
    """
    body = await request.json()
    action_short_id = body.get("action_id", "").strip().lower()
    decision = body.get("decision", "").strip().lower()

    if not action_short_id or decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Invalid payload")

    from services.agent_swarm.db import get_conn
    from services.agent_swarm.agents.budget_governor import _auto_execute_action

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, entity_id, action_type, new_value, status
                FROM action_log
                WHERE id::text LIKE %s AND status='pending'
                ORDER BY ts DESC LIMIT 1
                """,
                (f"{action_short_id}%",),
            )
            row = cur.fetchone()

    if not row:
        return {"ok": False, "error": "Action not found or already resolved"}

    action_id, entity_id, action_type, new_value_raw, status = row

    if decision == "reject":
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE action_log SET status='rejected', approved_by='whatsapp' WHERE id=%s",
                    (action_id,),
                )
                cur.execute(
                    "UPDATE pending_approvals SET status='rejected', responded_at=NOW(), response='NO' WHERE action_log_id=%s",
                    (action_id,),
                )
        return {"ok": True, "decision": "rejected", "action_id": str(action_id)}

    import json as _json
    new_value = _json.loads(new_value_raw) if isinstance(new_value_raw, str) else (new_value_raw or {})
    success = _auto_execute_action(str(action_id), entity_id, action_type, new_value)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pending_approvals SET status=%s, responded_at=NOW(), response='YES' WHERE action_log_id=%s",
                ("approved" if success else "failed", action_id),
            )

    return {"ok": True, "decision": "approved", "executed": success, "action_id": str(action_id)}


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
            # Daily breakdown by platform
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
                  AND entity_level = 'ad'
                GROUP BY platform, DATE_TRUNC('day', hour_ts)::DATE
                ORDER BY date ASC, platform
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            daily = [dict(zip(cols, r)) for r in cur.fetchall()]

            # Platform-level totals
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
                  AND entity_level = 'ad'
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

    from datetime import datetime, timedelta
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    until = datetime.utcnow().strftime("%Y-%m-%d")

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

    client_id = cfg.GOOGLE_CLIENT_ID
    client_secret = cfg.GOOGLE_CLIENT_SECRET
    developer_token = cfg.GOOGLE_DEVELOPER_TOKEN

    if not client_id or not client_secret or not developer_token:
        raise HTTPException(
            status_code=500,
            detail=(
                "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_DEVELOPER_TOKEN "
                "must be set in the server environment"
            ),
        )

    # ── Auto-discover Google Ads customer IDs ────────────────────
    customer_id = None
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
        if ads_resp.status_code == 200:
            resource_names = ads_resp.json().get("resourceNames", [])
            if resource_names:
                # "customers/1234567890" → extract the ID
                customer_id = resource_names[0].split("/")[-1]
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
            # Save to google_auth_tokens (same schema as manual /google/connect)
            cur.execute(
                """
                INSERT INTO google_auth_tokens
                    (workspace_id, customer_id, developer_token,
                     client_id, client_secret, refresh_token, access_token)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (workspace_id, customer_id)
                DO UPDATE SET
                    developer_token = EXCLUDED.developer_token,
                    client_id       = EXCLUDED.client_id,
                    client_secret   = EXCLUDED.client_secret,
                    refresh_token   = EXCLUDED.refresh_token,
                    access_token    = EXCLUDED.access_token,
                    updated_at      = NOW()
                """,
                (
                    workspace_id, customer_id, developer_token,
                    client_id, client_secret, refresh_token, access_token,
                ),
            )

            # Auto-save YouTube channel ID to platform_connections if discovered
            if youtube_channel_id:
                cur.execute(
                    """
                    INSERT INTO platform_connections
                        (workspace_id, platform, account_id)
                    VALUES (%s, 'youtube', %s)
                    ON CONFLICT (workspace_id, platform)
                    DO UPDATE SET
                        account_id = EXCLUDED.account_id,
                        updated_at = NOW()
                    """,
                    (workspace_id, youtube_channel_id),
                )

    result: dict = {
        "ok": True,
        "workspace_id": workspace_id,
        "customer_id": customer_id,
    }
    if youtube_channel_id:
        result["youtube_channel_id"] = youtube_channel_id
    return result
