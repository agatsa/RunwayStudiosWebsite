# services/agent_swarm/app.py
"""
Agent Swarm FastAPI service — multi-tenant edition.
All endpoints accept an optional phone_number_id in the request body
to route to the correct client account. Falls back to env-var defaults
for backward compatibility.
"""
import os
import time
import json
import httpx
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

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
from services.agent_swarm.db import get_conn
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://runwaystudios.co",
        "https://www.runwaystudios.co",
        "https://app.runwaystudios.co",
        "https://dashboard-771420308292.asia-south1.run.app",
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

PLATFORM = "meta"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# ── Billing constants ─────────────────────────────────────
CREDIT_PACKS = {
    "100": {"credits": 100, "amount_paise": 79900},    # ₹799
    "250": {"credits": 250, "amount_paise": 149900},   # ₹1,499
    "600": {"credits": 600, "amount_paise": 299900},   # ₹2,999
}
FEATURE_COSTS = {
    "yt_competitor_intel": 20,
    "growth_os":           10,
    "video_ai_insights":    2,
    "campaign_brief":       3,
    "competitor_ai":        5,
    "growth_recipe_regen":  5,
    "ai_chat":              1,
}
PLAN_MONTHLY_CREDITS = {"free": 0, "starter": 150, "growth": 500, "agency": 2000}
PLAN_PRICES_MONTHLY  = {"starter": 199900, "growth": 499900,  "agency": 1199900}
PLAN_PRICES_YEARLY   = {"starter": 1999900, "growth": 4798800, "agency": 11199900}
VALID_PLANS          = {"free", "starter", "growth", "agency"}

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


# ── Billing helpers ───────────────────────────────────────

def _get_org_id_for_workspace(conn, workspace_id: str) -> str:
    """Look up org_id from workspace_id. Raises 404 if not found."""
    with conn.cursor() as cur:
        cur.execute("SELECT org_id FROM workspaces WHERE id = %s", (workspace_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return str(row[0])


def _check_and_deduct_credits(conn, org_id: str, workspace_id: str, required: int, feature: str) -> int:
    """Atomic credit deduction using SELECT FOR UPDATE.
    Returns new balance on success. Raises HTTP 402 if insufficient."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT credit_balance FROM organizations WHERE id = %s FOR UPDATE",
            (org_id,),
        )
        row = cur.fetchone()
        balance = row[0] if row else 0
        if not row or balance < required:
            raise HTTPException(status_code=402, detail={
                "error": "insufficient_credits",
                "required": required,
                "balance": balance,
                "feature": feature,
                "message": f"You need {required} credits but only have {balance}. Top up to continue.",
            })
        new_balance = balance - required
        cur.execute(
            "UPDATE organizations SET credit_balance = %s WHERE id = %s",
            (new_balance, org_id),
        )
        cur.execute(
            """INSERT INTO credit_ledger
               (org_id, workspace_id, amount, balance_after, type, feature, description)
               VALUES (%s, %s, %s, %s, 'feature_use', %s, %s)""",
            (org_id, workspace_id, -required, new_balance, feature,
             f"Used {required} credits for {feature}"),
        )
    conn.commit()
    return new_balance


def _grant_credits(conn, org_id: str, workspace_id, amount: int, credit_type: str,
                   feature: str = None, razorpay_payment_id: str = None, description: str = None) -> int:
    """Add credits to an org. Returns new balance."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE organizations SET credit_balance = credit_balance + %s WHERE id = %s RETURNING credit_balance",
            (amount, org_id),
        )
        new_balance = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO credit_ledger
               (org_id, workspace_id, amount, balance_after, type, feature, razorpay_payment_id, description)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (org_id, workspace_id, amount, new_balance, credit_type, feature,
             razorpay_payment_id, description or f"Granted {amount} credits"),
        )
    conn.commit()
    return new_balance


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


@app.post("/catalog/add-product")
async def add_product_manually(request: Request):
    """
    Manually add a single product to the catalog.
    Body: {workspace_id, name, description?, price_inr?, product_url?, sku?}
    """
    _auth(request)
    import json as _json
    from services.agent_swarm.db import get_conn
    body = await request.json()
    workspace_id = body.get("workspace_id")
    name         = (body.get("name") or "").strip()
    if not workspace_id or not name:
        raise HTTPException(status_code=400, detail="workspace_id and name required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO products
                    (workspace_id, name, description, price_inr, product_url, sku,
                     images, source_platform, source_product_id, active)
                VALUES (%s, %s, %s, %s, %s, %s, '[]'::jsonb, 'manual', %s, TRUE)
                RETURNING id
                """,
                (
                    workspace_id, name,
                    body.get("description") or None,
                    body.get("price_inr") or None,
                    body.get("product_url") or None,
                    body.get("sku") or None,
                    f"manual-{name.lower().replace(' ', '-')}",
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return {"ok": True, "product_id": str(row[0])}


@app.post("/catalog/import-shopify")
async def import_shopify_catalog(request: Request):
    """
    Import products + images from a Shopify (or WooCommerce) store into the products table.
    Body: {workspace_id, store_url?}  — store_url defaults to workspace.store_url
    """
    _auth(request)
    from services.agent_swarm.core.product_catalog import discover_and_sync
    body = await request.json()
    workspace = resolve_workspace(request, body)
    store_url = body.get("store_url") or workspace.get("store_url") or ""
    if not store_url:
        raise HTTPException(status_code=400, detail="store_url required — pass it in the body or set it on the workspace")
    result = discover_and_sync(
        workspace_id=workspace["id"],
        store_url=store_url,
    )
    return {"ok": True, **result}


@app.post("/catalog/scrape-url")
async def scrape_product_url(request: Request):
    """
    Scrape a single product page URL and save it to the catalog.
    Body: {workspace_id, url}
    Returns: {ok, product: {...}}
    """
    _auth(request)
    from services.agent_swarm.core.product_catalog import scrape_product_page
    body = await request.json()
    workspace = resolve_workspace(request, body)
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="url must start with http or https")
    try:
        product = scrape_product_page(workspace["id"], url)
        return {"ok": True, "product": product}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/catalog/debug-scrape")
async def debug_scrape_url(request: Request, url: str = None):
    """
    Debug endpoint — shows raw fetch results for each scrape strategy without saving anything.
    GET /catalog/debug-scrape?url=https://...
    """
    _auth(request)
    import requests as _rq
    from urllib.parse import urlparse as _up
    results: dict = {}

    if not url:
        return {"error": "pass ?url=..."}

    parsed = _up(url)
    path_no_qs = parsed.path.rstrip("/")

    # Strategy 1a: custom domain .json
    if "/products/" in url:
        json_url = f"{parsed.scheme}://{parsed.netloc}{path_no_qs}.json"
        try:
            r = _rq.get(json_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            results["json_custom"] = {
                "url": json_url, "status": r.status_code,
                "content_type": r.headers.get("content-type", ""),
                "body_preview": r.text[:600],
            }
        except Exception as e:
            results["json_custom"] = {"url": json_url, "error": str(e)}

        # Strategy 1b: myshopify.com .json
        host = parsed.netloc.lower()
        if "www." in host:
            host = host.replace("www.", "", 1)
        subdomain = host.split(".")[0]
        myshopify_url = f"https://{subdomain}.myshopify.com{path_no_qs}.json"
        try:
            r = _rq.get(myshopify_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            results["json_myshopify"] = {
                "url": myshopify_url, "status": r.status_code,
                "content_type": r.headers.get("content-type", ""),
                "body_preview": r.text[:600],
            }
        except Exception as e:
            results["json_myshopify"] = {"url": myshopify_url, "error": str(e)}

        # Strategy 1c: products.json list on myshopify domain, find by handle
        products_list_url = f"https://{subdomain}.myshopify.com/products.json?limit=250"
        try:
            r = _rq.get(products_list_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            results["products_list"] = {
                "url": products_list_url, "status": r.status_code,
                "content_type": r.headers.get("content-type", ""),
                "body_preview": r.text[:600],
            }
        except Exception as e:
            results["products_list"] = {"url": products_list_url, "error": str(e)}

    # Strategy 2: raw HTML fetch
    try:
        r = _rq.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        results["html"] = {
            "status": r.status_code,
            "body_preview": r.text[:1200],
        }
    except Exception as e:
        results["html"] = {"error": str(e)}

    return results


@app.delete("/catalog/product/{product_id}")
async def delete_catalog_product(request: Request, product_id: str):
    """
    Hard-delete a product from the catalog.
    Query param: workspace_id
    """
    _auth(request)
    from services.agent_swarm.core.product_catalog import delete_product
    workspace_id = request.query_params.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    deleted = delete_product(workspace_id, product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"ok": True, "deleted": product_id}


@app.post("/catalog/product-image")
async def add_product_image(request: Request):
    """
    Add or replace the primary image on a product.
    Accepts either a URL (image_url) or a base64-encoded file (image_b64 + filename).
    For base64 uploads, saves to GCS and returns the public URL.
    Body: {product_id, workspace_id, image_url?, image_b64?, filename?}
    """
    _auth(request)
    import json as _json
    from services.agent_swarm.db import get_conn

    body = await request.json()
    product_id   = body.get("product_id")
    workspace_id = body.get("workspace_id")
    image_url    = (body.get("image_url") or "").strip()
    image_b64    = body.get("image_b64")
    filename     = body.get("filename") or "product.jpg"

    if not product_id or not workspace_id:
        raise HTTPException(status_code=400, detail="product_id and workspace_id required")
    if not image_url and not image_b64:
        raise HTTPException(status_code=400, detail="Either image_url or image_b64 required")

    # If base64, upload to GCS
    if image_b64 and not image_url:
        try:
            import base64 as _b64
            import uuid as _uuid
            from google.cloud import storage as _gcs
            img_data = _b64.b64decode(image_b64)
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
            gcs_filename = f"product-images/{_uuid.uuid4().hex}.{ext}"
            bucket_name = "wa-agency-raw-wa-ai-agency"
            _gcs_client = _gcs.Client()
            bucket = _gcs_client.bucket(bucket_name)
            blob = bucket.blob(gcs_filename)
            content_type = "image/png" if ext == "png" else "image/jpeg"
            blob.upload_from_string(img_data, content_type=content_type)
            blob.make_public()
            image_url = blob.public_url
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Upload to GCS failed: {e}")

    # Prepend new image to the product's images array
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT images FROM products WHERE id=%s AND workspace_id=%s",
                (product_id, workspace_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Product not found")

            existing = row[0] if isinstance(row[0], list) else _json.loads(row[0] or "[]")
            new_image = {"url": image_url, "alt": "", "position": 0}
            # Put new image first, keep others, remove duplicates
            merged = [new_image] + [img for img in existing if img.get("url") != image_url]

            cur.execute(
                "UPDATE products SET images=%s::jsonb, updated_at=NOW() WHERE id=%s AND workspace_id=%s",
                (_json.dumps(merged), product_id, workspace_id),
            )
        conn.commit()

    return {"ok": True, "image_url": image_url, "product_id": product_id}


# ── Shopify App endpoints ───────────────────────────────────────────────────

@app.post("/shopify/save-connection")
async def shopify_save_connection(request: Request):
    """
    Called by Next.js callback after OAuth code exchange.
    Stores access token, syncs all products, registers webhooks.
    Body: {workspace_id, shop_domain, access_token, scope}
    """
    _auth(request)
    import json as _json
    from services.agent_swarm.db import get_conn
    from services.agent_swarm.connectors.shopify import ShopifyConnector
    from services.agent_swarm.core.product_catalog import sync_from_shopify_authenticated
    from services.agent_swarm.config import SHOPIFY_API_SECRET

    body = await request.json()
    workspace_id = body.get("workspace_id")
    shop_domain  = (body.get("shop_domain") or "").strip().lower()
    access_token = body.get("access_token")
    scope        = body.get("scope") or ""

    if not workspace_id or not shop_domain or not access_token:
        raise HTTPException(status_code=400, detail="workspace_id, shop_domain and access_token required")

    # Fetch shop info (name)
    connector = ShopifyConnector()
    try:
        shop_info = connector.get_shop_info(shop_domain, access_token)
        shop_name = shop_info.get("name") or shop_domain
    except Exception as e:
        print(f"get_shop_info failed: {e}")
        shop_name = shop_domain

    # Upsert shopify_connections
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO shopify_connections (workspace_id, shop_domain, access_token, scopes, shop_name)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (workspace_id, shop_domain)
                DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    scopes = EXCLUDED.scopes,
                    shop_name = EXCLUDED.shop_name,
                    installed_at = NOW()
                """,
                (workspace_id, shop_domain, access_token, scope, shop_name),
            )
        conn.commit()

    # Register webhooks
    webhook_base = "https://agent-swarm-771420308292.asia-south1.run.app/shopify/webhook"
    for topic in ("products/create", "products/update", "products/delete"):
        try:
            connector.register_webhook(shop_domain, access_token, topic, webhook_base)
        except Exception as e:
            print(f"Webhook registration failed for {topic}: {e}")

    # Sync all products
    try:
        products = sync_from_shopify_authenticated(workspace_id, shop_domain, access_token)
        products_synced = len(products)
        # Mark synced_at
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE shopify_connections SET synced_at=NOW() WHERE workspace_id=%s AND shop_domain=%s",
                    (workspace_id, shop_domain),
                )
            conn.commit()
    except Exception as e:
        print(f"Initial product sync failed: {e}")
        products_synced = 0

    return {"ok": True, "shop_domain": shop_domain, "shop_name": shop_name, "products_synced": products_synced}


@app.post("/shopify/webhook")
async def shopify_webhook(request: Request):
    """
    Receives real-time product events from Shopify.
    HMAC validated via X-Shopify-Hmac-Sha256 header.
    Handles: products/create, products/update, products/delete
    """
    import json as _json
    from services.agent_swarm.db import get_conn
    from services.agent_swarm.connectors.shopify import ShopifyConnector
    from services.agent_swarm.config import SHOPIFY_API_SECRET
    from services.agent_swarm.core.product_catalog import _upsert_shopify_product

    raw_body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256", "")
    topic       = request.headers.get("X-Shopify-Topic", "")
    shop_domain = request.headers.get("X-Shopify-Shop-Domain", "").lower()

    # Validate HMAC
    if SHOPIFY_API_SECRET:
        connector = ShopifyConnector()
        if not connector.verify_webhook_hmac(raw_body, hmac_header, SHOPIFY_API_SECRET):
            raise HTTPException(status_code=401, detail="HMAC validation failed")

    # Look up workspace
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workspace_id FROM shopify_connections WHERE shop_domain=%s LIMIT 1",
                (shop_domain,),
            )
            row = cur.fetchone()
    if not row:
        # Unknown store — return 200 to stop Shopify retrying
        return {"ok": True, "note": "unknown shop"}

    workspace_id = str(row[0])

    try:
        payload = _json.loads(raw_body)
    except Exception:
        return {"ok": True, "note": "invalid json"}

    if topic in ("products/create", "products/update"):
        store_url = f"https://{shop_domain}"
        _upsert_shopify_product(workspace_id, store_url, payload)
    elif topic == "products/delete":
        product_id = str(payload.get("id", ""))
        if product_id:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE products SET active=FALSE, updated_at=NOW() WHERE workspace_id=%s AND source_platform='shopify' AND source_product_id=%s",
                        (workspace_id, product_id),
                    )
                conn.commit()

    return {"ok": True}


@app.post("/shopify/sync")
async def shopify_sync(request: Request):
    """Manual full re-sync for a workspace. Body: {workspace_id}"""
    _auth(request)
    from services.agent_swarm.db import get_conn
    from services.agent_swarm.core.product_catalog import sync_from_shopify_authenticated

    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shop_domain, access_token FROM shopify_connections WHERE workspace_id=%s LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No Shopify connection found for this workspace")

    shop_domain, access_token = row
    products = sync_from_shopify_authenticated(workspace_id, shop_domain, access_token)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE shopify_connections SET synced_at=NOW() WHERE workspace_id=%s AND shop_domain=%s",
                (workspace_id, shop_domain),
            )
        conn.commit()

    return {"ok": True, "products_synced": len(products), "shop_domain": shop_domain}


@app.get("/shopify/status")
async def shopify_status(request: Request, workspace_id: str = None):
    """Returns Shopify connection status + stats for a workspace."""
    _auth(request)
    from services.agent_swarm.db import get_conn

    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shop_domain, shop_name, scopes, installed_at, synced_at FROM shopify_connections WHERE workspace_id=%s LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "SELECT COUNT(*) FROM products WHERE workspace_id=%s AND source_platform='shopify' AND active=TRUE",
                    (workspace_id,),
                )
                count_row = cur.fetchone()
                products_count = count_row[0] if count_row else 0

    if not row:
        return {"connected": False}

    shop_domain, shop_name, scopes, installed_at, synced_at = row
    return {
        "connected": True,
        "shop_domain": shop_domain,
        "shop_name": shop_name,
        "scopes": scopes,
        "installed_at": installed_at.isoformat() if installed_at else None,
        "synced_at": synced_at.isoformat() if synced_at else None,
        "products_count": products_count,
    }


@app.delete("/shopify/disconnect")
async def shopify_disconnect(request: Request):
    """Remove Shopify connection for a workspace. Body: {workspace_id}"""
    _auth(request)
    from services.agent_swarm.db import get_conn

    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM shopify_connections WHERE workspace_id=%s",
                (workspace_id,),
            )
        conn.commit()

    return {"ok": True}


@app.get("/workspace/list")
async def list_workspaces(request: Request):
    """List workspaces for the authenticated user.
    If X-Clerk-User-Id header is present, filters by that user's orgs only.
    Falls back to all-workspace listing for internal/cron calls using X-Internal-Token.
    """
    clerk_user_id = request.headers.get("X-Clerk-User-Id", "").strip()

    if clerk_user_id:
        # User-scoped: only return workspaces belonging to this Clerk user's org
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT w.id, w.name, w.store_url, w.store_platform, w.active,
                              w.workspace_type, w.onboarding_complete, w.onboarding_channels
                       FROM workspaces w
                       JOIN organizations o ON o.id = w.org_id
                       WHERE o.clerk_user_id = %s AND w.active = TRUE
                       ORDER BY w.created_at""",
                    (clerk_user_id,),
                )
                rows = cur.fetchall()
        workspaces = [
            {
                "id": str(r[0]), "name": r[1], "store_url": r[2],
                "store_platform": r[3], "active": r[4],
                "workspace_type": r[5] or "d2c",
                "onboarding_complete": r[6] if r[6] is not None else False,
                "onboarding_channels": r[7] or [],
            }
            for r in rows
        ]
    else:
        # Internal call (cron/admin) — return all active workspaces
        _auth(request)
        workspaces = [
            {
                "id": w["id"], "name": w["name"], "store_url": w["store_url"],
                "store_platform": w["store_platform"], "active": w["active"],
                "workspace_type": w.get("workspace_type", "d2c"),
                "onboarding_complete": w.get("onboarding_complete", False),
                "onboarding_channels": w.get("onboarding_channels", []),
            }
            for w in list_active_workspaces()
        ]

    return {"workspaces": workspaces, "count": len(workspaces)}


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

    # If execution failed, read the stored error from action_log
    exec_error = None
    if not success and final_status == "failed":
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT error FROM action_log WHERE id=%s", (action_id,))
                    _err_row = cur.fetchone()
                    if _err_row and _err_row[0]:
                        exec_error = _err_row[0]
        except Exception:
            pass

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
        # Error detail when execution fails (payment issue, ad account disabled, etc.)
        "exec_error": exec_error,
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
            # Normalize 'facebook' → 'meta' so old data stored under either name
            # is consolidated into one platform bucket.
            cur.execute(
                """
                SELECT CASE WHEN platform IN ('meta', 'facebook') THEN 'meta' ELSE platform END AS platform,
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
                  AND hour_ts >= NOW() - (%s * INTERVAL '1 day')
                  AND (
                    (platform IN ('meta', 'facebook') AND entity_level IN ('ad', 'campaign'))
                    OR (platform = 'google' AND entity_level = 'campaign')
                  )
                GROUP BY CASE WHEN platform IN ('meta', 'facebook') THEN 'meta' ELSE platform END,
                         DATE_TRUNC('day', hour_ts)::DATE
                ORDER BY date ASC, platform
                """,
                (workspace_id, days),
            )
            cols = [d[0] for d in cur.description]
            daily = [dict(zip(cols, r)) for r in cur.fetchall()]

            # Platform-level totals — same normalization for 'facebook' → 'meta'
            cur.execute(
                """
                SELECT CASE WHEN platform IN ('meta', 'facebook') THEN 'meta' ELSE platform END AS platform,
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
                  AND hour_ts >= NOW() - (%s * INTERVAL '1 day')
                  AND (
                    (platform IN ('meta', 'facebook') AND entity_level IN ('ad', 'campaign'))
                    OR (platform = 'google' AND entity_level = 'campaign')
                  )
                GROUP BY CASE WHEN platform IN ('meta', 'facebook') THEN 'meta' ELSE platform END
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
    result = mc.pause(entity_id)
    ok    = result.get("ok", False) if isinstance(result, dict) else bool(result)
    error = result.get("error")    if isinstance(result, dict) else None
    return {"ok": ok, "entity_id": entity_id, "error": error}


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
    result = mc.resume(entity_id)
    ok    = result.get("ok", False) if isinstance(result, dict) else bool(result)
    error = result.get("error")    if isinstance(result, dict) else None
    return {"ok": ok, "entity_id": entity_id, "error": error}


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
    from services.agent_swarm.core.workspace import invalidate_workspace_cache
    invalidate_workspace_cache(workspace_id)

    return {"status": "connected", "ad_account_id": ad_account_id, "user_name": user_name}


# ── Meta OAuth (Facebook Login flow) ─────────────────────────────────────────

@app.get("/meta/oauth/start")
async def meta_oauth_start(workspace_id: str, request: Request):
    """Return the Facebook OAuth dialog URL. Frontend redirects the user there."""
    from services.agent_swarm.config import FACEBOOK_APP_ID, META_OAUTH_REDIRECT_URI
    import urllib.parse

    if not FACEBOOK_APP_ID:
        raise HTTPException(status_code=500, detail="FACEBOOK_APP_ID not configured on server")

    params = {
        "client_id": FACEBOOK_APP_ID,
        "redirect_uri": META_OAUTH_REDIRECT_URI,
        "scope": "ads_management,ads_read,business_management",
        "state": workspace_id,
        "response_type": "code",
    }
    oauth_url = f"https://www.facebook.com/v21.0/dialog/oauth?" + urllib.parse.urlencode(params)
    return {"oauth_url": oauth_url}


@app.post("/meta/oauth/save")
async def meta_oauth_save(request: Request):
    """
    Exchange an OAuth code for a long-lived token.
    - If the user has exactly one active ad account: auto-saves to platform_connections.
    - If multiple accounts: stores a pending session and returns ad_accounts for selection.
    """
    from services.agent_swarm.config import FACEBOOK_APP_ID, FACEBOOK_APP_SECRET, META_OAUTH_REDIRECT_URI
    import requests as req, json as _json, secrets as _secrets
    from services.agent_swarm.db import get_conn

    body = await request.json()
    workspace_id = body.get("workspace_id", "").strip()
    code = body.get("code", "").strip()

    if not workspace_id or not code:
        raise HTTPException(status_code=400, detail="workspace_id and code required")

    # Step 1: Exchange code for short-lived token
    token_r = req.get(
        f"{META_GRAPH}/oauth/access_token",
        params={
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "redirect_uri": META_OAUTH_REDIRECT_URI,
            "code": code,
        },
        timeout=10,
    )
    if not token_r.ok:
        err = token_r.json().get("error", {}).get("message", token_r.text)
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {err}")
    short_token = token_r.json().get("access_token", "")

    # Step 2: Exchange for long-lived token (~60 days)
    ll_r = req.get(
        f"{META_GRAPH}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": FACEBOOK_APP_ID,
            "client_secret": FACEBOOK_APP_SECRET,
            "fb_exchange_token": short_token,
        },
        timeout=10,
    )
    long_token = ll_r.json().get("access_token", short_token) if ll_r.ok else short_token

    # Step 3: Get user info
    me_r = req.get(
        f"{META_GRAPH}/me",
        params={"access_token": long_token, "fields": "id,name"},
        timeout=10,
    )
    me = me_r.json() if me_r.ok else {}
    user_id = me.get("id", "")
    user_name = me.get("name", "")

    # Step 4: Fetch ad accounts
    accounts_r = req.get(
        f"{META_GRAPH}/me/adaccounts",
        params={
            "access_token": long_token,
            "fields": "id,name,account_id,account_status,currency",
            "limit": 50,
        },
        timeout=10,
    )
    ad_accounts = accounts_r.json().get("data", []) if accounts_r.ok else []

    with get_conn() as conn:
        # If exactly one active account, auto-save and finish
        active = [a for a in ad_accounts if a.get("account_status") == 1] or ad_accounts
        if len(active) == 1:
            acc = active[0]
            ad_account_id = acc["id"]
            if not ad_account_id.startswith("act_"):
                ad_account_id = f"act_{ad_account_id}"
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO platform_connections
                        (workspace_id, platform, account_id, account_name, ad_account_id, access_token, is_primary)
                       VALUES (%s, 'meta', %s, %s, %s, %s, true)
                       ON CONFLICT (workspace_id, platform, account_id)
                       DO UPDATE SET account_name=EXCLUDED.account_name,
                           ad_account_id=EXCLUDED.ad_account_id,
                           access_token=EXCLUDED.access_token,
                           is_primary=true, updated_at=NOW()""",
                    (workspace_id, user_id, user_name, ad_account_id, long_token),
                )
            conn.commit()
            from services.agent_swarm.core.workspace import invalidate_workspace_cache
            invalidate_workspace_cache(workspace_id)
            return {"status": "connected", "user_name": user_name, "ad_account_id": ad_account_id}

        # Multiple accounts: save pending session for the user to pick from
        session_id = _secrets.token_urlsafe(32)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO meta_oauth_sessions
                       (id, workspace_id, user_id, user_name, access_token, ad_accounts)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (workspace_id) DO UPDATE SET
                       id=EXCLUDED.id, user_id=EXCLUDED.user_id,
                       user_name=EXCLUDED.user_name, access_token=EXCLUDED.access_token,
                       ad_accounts=EXCLUDED.ad_accounts, created_at=NOW()""",
                (session_id, workspace_id, user_id, user_name, long_token, _json.dumps(ad_accounts)),
            )
        conn.commit()
        return {
            "status": "select_account",
            "session_id": session_id,
            "user_name": user_name,
            "ad_accounts": ad_accounts,
        }


@app.get("/meta/oauth/session")
async def meta_oauth_session(session_id: str, request: Request):
    """Return pending OAuth session data (user_name + ad_accounts) for the account picker."""
    from services.agent_swarm.db import get_conn
    import json as _json

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workspace_id, user_name, ad_accounts FROM meta_oauth_sessions WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    ad_accounts = row[2] if isinstance(row[2], list) else _json.loads(row[2])
    return {"workspace_id": str(row[0]), "user_name": row[1], "ad_accounts": ad_accounts}


@app.post("/meta/oauth/select-account")
async def meta_oauth_select_account(request: Request):
    """Complete the Meta OAuth flow by saving the chosen ad account from a pending session."""
    from services.agent_swarm.db import get_conn

    body = await request.json()
    session_id = body.get("session_id", "").strip()
    ad_account_id = body.get("ad_account_id", "").strip()

    if not session_id or not ad_account_id:
        raise HTTPException(status_code=400, detail="session_id and ad_account_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workspace_id, user_id, user_name, access_token FROM meta_oauth_sessions WHERE id = %s",
                (session_id,),
            )
            row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Session not found or expired")

        workspace_id = str(row[0])
        user_id = str(row[1])
        user_name = row[2]
        access_token = row[3]

        if not ad_account_id.startswith("act_"):
            ad_account_id = f"act_{ad_account_id}"

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO platform_connections
                       (workspace_id, platform, account_id, account_name, ad_account_id, access_token, is_primary)
                   VALUES (%s, 'meta', %s, %s, %s, %s, true)
                   ON CONFLICT (workspace_id, platform, account_id)
                   DO UPDATE SET account_name=EXCLUDED.account_name,
                       ad_account_id=EXCLUDED.ad_account_id,
                       access_token=EXCLUDED.access_token,
                       is_primary=true, updated_at=NOW()""",
                (workspace_id, user_id, user_name, ad_account_id, access_token),
            )
            # Clean up the pending session
            cur.execute("DELETE FROM meta_oauth_sessions WHERE id = %s", (session_id,))
        conn.commit()
        from services.agent_swarm.core.workspace import invalidate_workspace_cache
        invalidate_workspace_cache(workspace_id)

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

    # Try to fetch the real channel title to save as account_name
    channel_title = channel_id  # fallback to channel_id if fetch fails
    try:
        import os as _os
        from services.agent_swarm import config as _cfg
        _api_key = getattr(_cfg, "YOUTUBE_API_KEY", "") or _os.getenv("YOUTUBE_API_KEY", "")
        if _api_key:
            from services.agent_swarm.connectors.youtube import YouTubeConnector as _YTC
            _yc = _YTC({"youtube_channel_id": channel_id}, {}, api_key=_api_key)
            _info = _yc.get_channel_info()
            if _info.get("title"):
                channel_title = _info["title"]
    except Exception as _e:
        print(f"YouTube channel title fetch (non-fatal): {_e}")

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
                (workspace_id, channel_id, channel_title),
            )
        conn.commit()
    return {"ok": True, "workspace_id": workspace_id, "youtube_channel_id": channel_id, "channel_title": channel_title}


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

    # Keep account_name in platform_connections up to date with real channel title
    if channel_info.get("title"):
        try:
            from services.agent_swarm.db import get_conn as _gc
            with _gc() as _conn:
                with _conn.cursor() as _cur:
                    _cur.execute(
                        "UPDATE platform_connections SET account_name = %s WHERE workspace_id = %s AND platform = 'youtube'",
                        (channel_info["title"], workspace_id),
                    )
                _conn.commit()
        except Exception as _e:
            print(f"YouTube account_name update (non-fatal): {_e}")

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
                               published_at, duration_seconds, view_count, like_count, comment_count,
                               COALESCE(is_short, FALSE) as is_short
                        FROM youtube_videos
                        WHERE workspace_id = %s
                        ORDER BY view_count DESC LIMIT 50
                        """,
                        (workspace_id,),
                    )
                    cols = ["video_id","title","description","tags","thumbnail_url",
                            "published_at","duration_seconds","view_count","like_count","comment_count","is_short"]
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
                                 view_count, like_count, comment_count, is_short)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (workspace_id, video_id)
                            DO UPDATE SET
                                title            = EXCLUDED.title,
                                description      = EXCLUDED.description,
                                tags             = EXCLUDED.tags,
                                thumbnail_url    = EXCLUDED.thumbnail_url,
                                duration_seconds = EXCLUDED.duration_seconds,
                                view_count       = EXCLUDED.view_count,
                                like_count       = EXCLUDED.like_count,
                                comment_count    = EXCLUDED.comment_count,
                                is_short         = EXCLUDED.is_short,
                                updated_at       = NOW()
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
                                v.get("is_short", False),
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

    # Deduct credits before AI analysis
    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        _check_and_deduct_credits(conn, org_id, workspace_id,
                                  FEATURE_COSTS["video_ai_insights"], "video_ai_insights")

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

    # Look up is_short flag from DB (Shorts need different AI analysis)
    is_short = False
    try:
        from services.agent_swarm.db import get_conn as _gc_short
        with _gc_short() as _conn_s:
            with _conn_s.cursor() as _cur_s:
                _cur_s.execute(
                    "SELECT COALESCE(is_short, FALSE) FROM youtube_videos WHERE workspace_id = %s AND video_id = %s",
                    (workspace_id, video_id),
                )
                _r = _cur_s.fetchone()
                if _r:
                    is_short = bool(_r[0])
    except Exception as e:
        print(f"YouTube is_short lookup error (non-fatal): {e}")

    # Claude AI suggestions
    suggestions: list[str] = []
    try:
        import anthropic
        import re as _re
        client = anthropic.Anthropic()
        if is_short:
            short_note = (
                "IMPORTANT: This video is a YouTube Short (≤60 seconds with #shorts tag). "
                "Shorts ALWAYS show 100% drop-off at the end — that is NORMAL behavior because Shorts loop. "
                "Do NOT mention end drop-off as a problem. Focus suggestions on: "
                "hook strength in the first 1-3 seconds, Shorts-specific SEO (#shorts tags, trending sounds), "
                "posting frequency, and using Shorts to drive subscribers to long-form content.\n"
            )
        else:
            short_note = ""
        prompt = (
            f"{short_note}"
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

    # Audience retention curve (OAuth only — silently empty if unavailable)
    retention_curve: list[dict] = []
    try:
        retention_curve = yc.fetch_audience_retention(video_id)
    except Exception as e:
        print(f"YouTube retention fetch skipped: {e}")

    return {
        "video_id": video_id,
        "is_short": is_short,
        "total_views": total_views,
        "total_watch_minutes": total_watch_minutes,
        "avg_view_percentage": round(avg_view_pct, 2),
        "avg_ctr": round(avg_ctr, 2),
        "avg_duration_seconds": round(avg_duration),
        "subscribers_gained": total_subs_gained,
        "daily": daily_rows,
        "suggestions": suggestions,
        "retention_curve": retention_curve,
        "workspace_id": workspace_id,
    }


@app.get("/youtube/traffic-sources")
async def youtube_traffic_sources(request: Request, workspace_id: str = None, days: int = 30):
    """Real traffic source breakdown from YouTube Analytics API."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    yc, _ = _get_youtube_connector(workspace_id)
    from datetime import datetime, timedelta

    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    until = datetime.utcnow().strftime("%Y-%m-%d")

    try:
        rows = yc.fetch_traffic_sources(since, until)
    except PermissionError:
        return {"available": False, "sources": [], "reason": "oauth_required"}
    except Exception as e:
        return {"available": False, "sources": [], "reason": str(e)}

    _LABELS = {
        "YT_SEARCH":         "YouTube Search",
        "SUGGESTED":         "Suggested Videos",
        "BROWSE_FEATURES":   "Browse / Home Feed",
        "EXT_URL":           "External Sources",
        "NO_LINK_EMBEDDED":  "Embedded Player",
        "NOTIFICATION":      "Notifications",
        "CHANNEL":           "Channel Page",
        "ADVERTISING":       "YouTube Ads",
        "END_SCREEN":        "End Screens",
        "CAMPAIGN_CARD":     "Campaign Cards",
        "NO_LINK_OTHER":     "Other",
        "HASHTAGS":          "Hashtags",
        "PLAYLISTS":         "Playlists",
        "RELATED_VIDEO":     "Related Videos",
        "SUBSCRIBER":        "Subscribers",
    }
    total = sum(r["views"] for r in rows) or 1
    sources = [
        {
            "source":              _LABELS.get(r["source"], r["source"].replace("_", " ").title()),
            "source_type":         r["source"],
            "views":               r["views"],
            "watch_time_minutes":  r["watch_time_minutes"],
            "pct":                 round(r["views"] / total * 100, 1),
        }
        for r in rows if r["views"] > 0
    ]
    return {"available": True, "sources": sources, "since": since, "until": until}


@app.get("/youtube/upload-timing")
async def youtube_upload_timing(request: Request, workspace_id: str = None):
    """Analyse best upload times based on publish_at vs view_count from own video history."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    from collections import defaultdict

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT published_at AT TIME ZONE 'Asia/Kolkata' AS local_pub, view_count
                FROM youtube_videos
                WHERE workspace_id = %s
                  AND published_at IS NOT NULL
                  AND view_count > 0
                ORDER BY published_at
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

    if not rows:
        return {"available": False, "slots": [], "grid": [], "best_slots": []}

    _DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    slot_views: dict = defaultdict(list)
    for local_pub, view_count in rows:
        if local_pub:
            dow = local_pub.weekday()       # 0=Mon … 6=Sun
            hour_bucket = (local_pub.hour // 3) * 3   # 0,3,6,9,12,15,18,21
            slot_views[(dow, hour_bucket)].append(int(view_count or 0))

    max_avg = 1
    slot_list = []
    for (dow, hour), views in slot_views.items():
        avg = int(sum(views) / len(views))
        max_avg = max(max_avg, avg)
        slot_list.append({"day": dow, "day_name": _DAYS[dow], "hour": hour,
                          "avg_views": avg, "video_count": len(views)})

    slot_list.sort(key=lambda x: x["avg_views"], reverse=True)
    slot_map = {(s["day"], s["hour"]): s for s in slot_list}

    grid = [
        {
            "day": d,
            "day_name": _DAYS[d],
            "hour": h,
            "label": f"{h:02d}:00",
            "avg_views": slot_map.get((d, h), {}).get("avg_views", 0),
            "video_count": slot_map.get((d, h), {}).get("video_count", 0),
            "heat": round(slot_map.get((d, h), {}).get("avg_views", 0) / max_avg, 3),
        }
        for d in range(7)
        for h in [0, 3, 6, 9, 12, 15, 18, 21]
    ]
    return {"available": True, "best_slots": slot_list[:3], "grid": grid}


@app.get("/youtube/organic-opportunities")
async def youtube_organic_opportunities(request: Request, workspace_id: str = None):
    """Top organic videos ranked for paid promotion suitability."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.video_id, v.title, v.view_count, v.like_count,
                       v.comment_count, v.thumbnail_url, v.duration_seconds,
                       v.published_at,
                       COALESCE(AVG(s.avg_view_percentage), 0) AS avg_retention,
                       COALESCE(AVG(s.impression_ctr), 0)      AS avg_ctr
                FROM youtube_videos v
                LEFT JOIN youtube_video_stats s
                       ON s.video_id = v.video_id AND s.workspace_id = v.workspace_id
                WHERE v.workspace_id = %s
                  AND v.view_count > 0
                GROUP BY v.video_id, v.title, v.view_count, v.like_count,
                         v.comment_count, v.thumbnail_url, v.duration_seconds, v.published_at
                ORDER BY v.view_count DESC
                LIMIT 10
                """,
                (workspace_id,),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not rows:
        return {"available": False, "opportunities": []}

    max_views = max(r["view_count"] for r in rows) or 1
    opportunities = []
    for r in rows:
        view_score      = r["view_count"] / max_views
        ctr_score       = min(float(r["avg_ctr"]) / 10.0, 1.0)
        retention_score = min(float(r["avg_retention"]) / 50.0, 1.0)
        score = view_score * 0.6 + ctr_score * 0.2 + retention_score * 0.2

        views = r["view_count"]
        if views > 100_000:
            bmin, bmax = 25000, 75000
        elif views > 50_000:
            bmin, bmax = 15000, 40000
        elif views > 10_000:
            bmin, bmax = 8000, 20000
        else:
            bmin, bmax = 3000, 10000

        opportunities.append({
            "video_id":        r["video_id"],
            "title":           r["title"],
            "thumbnail_url":   r["thumbnail_url"],
            "view_count":      r["view_count"],
            "like_count":      r["like_count"],
            "avg_retention":   round(float(r["avg_retention"]), 1),
            "avg_ctr":         round(float(r["avg_ctr"]), 2),
            "duration_seconds": r["duration_seconds"],
            "score":           round(score, 3),
            "budget_min":      bmin,
            "budget_max":      bmax,
        })

    opportunities.sort(key=lambda x: x["score"], reverse=True)
    return {"available": True, "opportunities": opportunities[:5]}


@app.get("/youtube/growth-plan")
async def youtube_growth_plan(request: Request, workspace_id: str = None):
    """
    Generate a 5-step Claude growth plan. Plans are persisted in youtube_growth_plans
    (INSERT only — never overwritten). Plans generated < 24 hours ago are returned
    from cache to avoid burning Claude credits on every page load.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from datetime import datetime, timezone as _tz_gp
    import json as _json_gp

    yc, workspace = _get_youtube_connector(workspace_id)

    # Get channel info for context
    try:
        channel_info = yc.get_channel_info()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"YouTube API error: {e}")

    # ── Check cache: if a plan was created < 24h ago, return it ──────────────
    history_plans: list[dict] = []
    try:
        from services.agent_swarm.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, steps, created_at
                    FROM youtube_growth_plans
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC
                    LIMIT 6
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
        if rows:
            most_recent_id = str(rows[0][0])
            most_recent_steps = rows[0][1]  # JSONB → Python list
            most_recent_ts = rows[0][2]
            age_hours = (
                datetime.now(_tz_gp.utc) - most_recent_ts.replace(tzinfo=_tz_gp.utc)
            ).total_seconds() / 3600
            history_plans = [
                {"id": str(r[0]), "steps": r[1], "created_at": r[2].isoformat()}
                for r in rows[1:]
            ][:5]
            if age_hours < 24:
                return {
                    "channel": channel_info,
                    "steps": most_recent_steps,
                    "plan_id": most_recent_id,
                    "history": history_plans,
                    "workspace_id": workspace_id,
                    "from_cache": True,
                }
    except Exception as e:
        print(f"YouTube growth plan cache check error (non-fatal): {e}")
    # ── End cache check ───────────────────────────────────────────────────────

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
    subs = channel_info.get("subscriber_count", 0)
    views = channel_info.get("view_count", 0)
    try:
        import anthropic
        client = anthropic.Anthropic()
        channel_name = channel_info.get("title", "your channel")
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

    # Persist the new plan (INSERT only — never update existing)
    plan_id = ""
    if steps:
        try:
            from services.agent_swarm.db import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO youtube_growth_plans
                            (workspace_id, steps, subs_at_time, views_at_time)
                        VALUES (%s, %s::jsonb, %s, %s)
                        RETURNING id
                        """,
                        (workspace_id, _json_gp.dumps(steps), subs, views),
                    )
                    plan_id = str(cur.fetchone()[0])
                conn.commit()
            # Reload history (excluding the plan we just inserted)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, steps, created_at
                        FROM youtube_growth_plans
                        WHERE workspace_id = %s AND id != %s::uuid
                        ORDER BY created_at DESC
                        LIMIT 5
                        """,
                        (workspace_id, plan_id),
                    )
                    history_plans = [
                        {"id": str(r[0]), "steps": r[1], "created_at": r[2].isoformat()}
                        for r in cur.fetchall()
                    ]
        except Exception as e:
            print(f"YouTube growth plan DB save error (non-fatal): {e}")

    return {
        "channel": channel_info,
        "steps": steps,
        "plan_id": plan_id,
        "history": history_plans,
        "workspace_id": workspace_id,
    }


@app.post("/youtube/growth-plan/create-task")
async def youtube_growth_plan_create_task(request: Request):
    """Save a growth plan step as an actionable task in youtube_growth_actions."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    step_text = body.get("step_text", "").strip()
    plan_id = body.get("plan_id") or None
    lever = body.get("lever", "growth_plan")

    if not workspace_id or not step_text:
        raise HTTPException(status_code=400, detail="workspace_id and step_text required")

    try:
        from services.agent_swarm.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO youtube_growth_actions
                        (workspace_id, plan_id, lever, suggestion, status)
                    VALUES (%s, %s, %s, %s, 'suggested')
                    RETURNING id
                    """,
                    (workspace_id, plan_id, lever, step_text),
                )
                action_id = str(cur.fetchone()[0])
            conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    return {"ok": True, "action_id": action_id}


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

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            # If customer_id discovery failed, preserve the existing one from DB
            if not customer_id:
                cur.execute(
                    "SELECT customer_id FROM google_auth_tokens WHERE workspace_id=%s LIMIT 1",
                    (workspace_id,),
                )
                existing = cur.fetchone()
                customer_id = existing[0] if existing else None
                print(f"[oauth/save] customer_id discovery failed, preserved existing: {customer_id}")

            if not customer_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "No Google Ads accounts found for this Google account. "
                        "Make sure Google Ads is active before connecting."
                    ),
                )

            # Delete existing row for this workspace, then insert fresh.
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
                # Try to fetch real channel title via OAuth (we have it at this point)
                _yt_title = youtube_channel_id
                try:
                    from services.agent_swarm.connectors.youtube import YouTubeConnector as _YTCO
                    import os as _os2
                    from services.agent_swarm import config as _cfg2
                    _yt_api_key = getattr(_cfg2, "YOUTUBE_API_KEY", "") or _os2.getenv("YOUTUBE_API_KEY", "")
                    _yt_conn_row = {**google_row, "youtube_channel_id": youtube_channel_id}
                    _ytc = _YTCO(_yt_conn_row, {}, api_key=_yt_api_key)
                    _yt_info = _ytc.get_channel_info()
                    if _yt_info.get("title"):
                        _yt_title = _yt_info["title"]
                except Exception as _yte:
                    print(f"YouTube title fetch in oauth/save (non-fatal): {_yte}")
                cur.execute(
                    """
                    INSERT INTO platform_connections
                        (workspace_id, platform, account_id, account_name)
                    VALUES (%s, 'youtube', %s, %s)
                    """,
                    (workspace_id, youtube_channel_id, _yt_title),
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
                    # Skip Google Ads summary/subtotal rows that are NOT real campaigns
                    _name_lower = campaign_name.lower()
                    if (
                        _name_lower.startswith("total:")
                        or _name_lower.startswith("total :")
                        or _name_lower in ("enabled", "paused", "removed", "all enabled campaigns")
                    ):
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
                  AND hour_ts >= NOW() - (%s * INTERVAL '1 day')
                  AND entity_name NOT ILIKE 'Total%%'
                  AND entity_name NOT ILIKE '%%Account%%'
                  AND entity_name NOT IN ('(not set)', 'Unknown', '', 'Total')
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
            # Filter out Google Ads summary/subtotal rows (Total: Account, Enabled, Paused, etc.)
            # NOTE: %% escapes the % sign for psycopg2 (otherwise treated as param placeholder)
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
                  AND LOWER(entity_name) NOT LIKE 'total:%%'
                  AND LOWER(entity_name) NOT LIKE 'total :%%'
                  AND LOWER(entity_name) NOT IN ('enabled', 'paused', 'removed', 'all enabled campaigns')
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
                      AND LOWER(raw_json->>'campaign_name') NOT LIKE 'total:%%'
                      AND LOWER(raw_json->>'campaign_name') NOT IN ('enabled', 'paused', 'removed', '')
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

    # Deduct credits before calling Claude
    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        _check_and_deduct_credits(conn, org_id, workspace_id,
                                  FEATURE_COSTS["competitor_ai"], "competitor_ai")

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


# ── Comments — unified feed, sentiment, YouTube sync ─────────────────────────

_CATEGORY_SENTIMENT = {
    "positive":          "praise",
    "purchase_intent":   "praise",
    "price":             "concern",
    "trust":             "concern",
    "scam":              "concern",
    "delivery":          "concern",
    "feature_confusion": "question",
    "support":           "question",
    "other":             "neutral",
}

_CATEGORY_LABEL = {
    "positive":          "Praise",
    "purchase_intent":   "Purchase Intent",
    "price":             "Price Concern",
    "trust":             "Trust Issue",
    "scam":              "Spam / Scam",
    "feature_confusion": "Feature Question",
    "delivery":          "Delivery Concern",
    "support":           "Support Needed",
    "other":             "Other",
}

_CATEGORY_COLOR = {
    "positive":          "green",
    "purchase_intent":   "blue",
    "price":             "orange",
    "trust":             "red",
    "scam":              "red",
    "feature_confusion": "purple",
    "delivery":          "amber",
    "support":           "amber",
    "other":             "gray",
}


@app.get("/comments/sentiment")
async def comments_sentiment(request: Request, workspace_id: str = None):
    """
    Sentiment breakdown across Meta (comment_replies) + YouTube (youtube_comments).
    Returns: total, positive_pct, top_concern, unread, by_category[], by_source{}.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT objection_type AS category,
                       COUNT(*)::int  AS cnt,
                       COUNT(*) FILTER (WHERE status = 'pending')::int AS unread
                FROM comment_replies
                WHERE workspace_id = %s
                GROUP BY 1
                """,
                (workspace_id,),
            )
            meta_rows = cur.fetchall()

            cur.execute(
                """
                SELECT COALESCE(category, 'other') AS category,
                       COUNT(*)::int  AS cnt,
                       COUNT(*) FILTER (WHERE status = 'pending')::int AS unread
                FROM youtube_comments
                WHERE workspace_id = %s
                GROUP BY 1
                """,
                (workspace_id,),
            )
            yt_rows = cur.fetchall()

    combined: dict = {}
    meta_total = meta_praise = yt_total = yt_praise = total_unread = 0

    for category, cnt, ur in meta_rows:
        meta_total += cnt
        if _CATEGORY_SENTIMENT.get(category) == "praise":
            meta_praise += cnt
        combined[category] = combined.get(category, 0) + cnt
        total_unread += ur or 0

    for category, cnt, ur in yt_rows:
        yt_total += cnt
        if _CATEGORY_SENTIMENT.get(category) == "praise":
            yt_praise += cnt
        combined[category] = combined.get(category, 0) + cnt
        total_unread += ur or 0

    total = sum(combined.values())
    praise_count = sum(v for k, v in combined.items() if _CATEGORY_SENTIMENT.get(k) == "praise")
    positive_pct = round(praise_count / total * 100) if total > 0 else 0

    concern_cats = {k: v for k, v in combined.items()
                    if _CATEGORY_SENTIMENT.get(k) == "concern"}
    top_concern = max(concern_cats, key=lambda k: concern_cats[k]) if concern_cats else None

    by_category = [
        {
            "category": cat,
            "label":    _CATEGORY_LABEL.get(cat, cat),
            "color":    _CATEGORY_COLOR.get(cat, "gray"),
            "count":    cnt,
            "pct":      round(cnt / total * 100) if total > 0 else 0,
        }
        for cat, cnt in sorted(combined.items(), key=lambda x: -x[1])
        if cnt > 0
    ]

    return {
        "has_data":          total > 0,
        "total":             total,
        "positive_pct":      positive_pct,
        "top_concern":       top_concern,
        "top_concern_label": _CATEGORY_LABEL.get(top_concern or "", ""),
        "unread":            total_unread,
        "by_category":       by_category,
        "by_source": {
            "meta":    {"total": meta_total,  "positive_pct": round(meta_praise / meta_total * 100) if meta_total > 0 else 0},
            "youtube": {"total": yt_total,    "positive_pct": round(yt_praise / yt_total * 100) if yt_total > 0 else 0},
            "amazon":  {"total": 0},
        },
    }


@app.get("/comments/feed")
async def comments_feed(
    request: Request,
    workspace_id: str = None,
    source: str = "all",
    limit: int = 50,
    offset: int = 0,
    days: int = 0,        # 0 = all time; >0 = last N days
):
    """
    Unified comment feed: Meta (comment_replies) + YouTube (youtube_comments).
    source: all | meta | youtube
    days: 0 = all time, 7/30/90 = last N days
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn
    import datetime as dt

    # Build optional date clause
    date_filter_meta  = "AND (%s = 0 OR COALESCE(comment_created, first_seen_at) >= NOW() - (%s * INTERVAL '1 day'))"
    date_filter_yt    = "AND (%s = 0 OR published_at >= NOW() - (%s * INTERVAL '1 day'))"

    comments = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            if source in ("all", "meta"):
                cur.execute(
                    f"""
                    SELECT
                        id::text,
                        'meta'                                AS source,
                        COALESCE(ad_id, '')                   AS source_name,
                        COALESCE(commenter_name, 'Anonymous') AS author_name,
                        comment_text,
                        COALESCE(objection_type, 'other')     AS category,
                        CASE objection_type
                            WHEN 'positive'          THEN 'praise'
                            WHEN 'purchase_intent'   THEN 'praise'
                            WHEN 'price'             THEN 'concern'
                            WHEN 'trust'             THEN 'concern'
                            WHEN 'scam'              THEN 'concern'
                            WHEN 'delivery'          THEN 'concern'
                            WHEN 'feature_confusion' THEN 'question'
                            WHEN 'support'           THEN 'question'
                            ELSE                          'neutral'
                        END                                   AS sentiment,
                        COALESCE(like_count, 0)               AS like_count,
                        suggested_reply,
                        status,
                        COALESCE(comment_created, first_seen_at) AS published_at
                    FROM comment_replies
                    WHERE workspace_id = %s
                      {date_filter_meta}
                    ORDER BY COALESCE(comment_created, first_seen_at) DESC
                    LIMIT 500
                    """,
                    (workspace_id, days, days),
                )
                cols = [d[0] for d in cur.description]
                comments.extend(dict(zip(cols, row)) for row in cur.fetchall())

            if source in ("all", "youtube"):
                cur.execute(
                    f"""
                    SELECT
                        id::text,
                        'youtube'                             AS source,
                        COALESCE(video_title, video_id)       AS source_name,
                        COALESCE(author_name, 'Anonymous')    AS author_name,
                        comment_text,
                        COALESCE(category, 'other')           AS category,
                        COALESCE(sentiment, 'neutral')        AS sentiment,
                        COALESCE(like_count, 0)               AS like_count,
                        suggested_reply,
                        status,
                        published_at
                    FROM youtube_comments
                    WHERE workspace_id = %s
                      {date_filter_yt}
                    ORDER BY published_at DESC NULLS LAST
                    LIMIT 500
                    """,
                    (workspace_id, days, days),
                )
                cols = [d[0] for d in cur.description]
                comments.extend(dict(zip(cols, row)) for row in cur.fetchall())

    # Sort combined by published_at descending
    def _sort_key(c):
        p = c.get("published_at")
        if p is None:
            return dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        if isinstance(p, str):
            try:
                return dt.datetime.fromisoformat(p.replace("Z", "+00:00"))
            except Exception:
                return dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        if hasattr(p, 'tzinfo') and p.tzinfo is None:
            return p.replace(tzinfo=dt.timezone.utc)
        return p

    comments.sort(key=_sort_key, reverse=True)

    # Serialize datetime objects
    for c in comments:
        p = c.get("published_at")
        if p is not None and not isinstance(p, str):
            c["published_at"] = p.isoformat()

    total = len(comments)
    page = comments[offset: offset + limit]

    return {
        "comments": page,
        "total":    total,
        "has_more": offset + limit < total,
        "offset":   offset,
        "limit":    limit,
    }


@app.post("/comments/sync-youtube")
async def sync_youtube_comments(request: Request):
    """
    Fetch recent YouTube video comments, classify with Claude, store in youtube_comments.
    Body: { workspace_id: str }
    """
    _auth(request)
    body = await request.json()
    workspace_id = (body.get("workspace_id") or "").strip()
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    # Get YouTube connector
    try:
        yc, workspace = _get_youtube_connector(workspace_id)
    except HTTPException:
        return {"ok": False, "error": "YouTube not connected", "synced": 0}

    from services.agent_swarm.db import get_conn
    from datetime import datetime, timezone
    import anthropic as _anthropic
    import json as _json
    import re as _re

    # Get recent video IDs from youtube_videos table (last 20)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT video_id, COALESCE(title, video_id) AS title
                FROM youtube_videos
                WHERE workspace_id = %s
                ORDER BY published_at DESC NULLS LAST
                LIMIT 20
                """,
                (workspace_id,),
            )
            videos = [{"video_id": r[0], "title": r[1]} for r in cur.fetchall()]

    if not videos:
        return {"ok": True, "synced": 0, "message": "No YouTube videos found — connect your channel first"}

    # Fetch raw comments for each video (up to 100 per video)
    all_raw: list[dict] = []
    skipped_videos: list[str] = []      # videos where comments failed (disabled/error)
    empty_videos:   list[str] = []      # videos with 0 comments

    for video in videos:
        try:
            raw = yc.fetch_video_comments(video["video_id"], max_results=100, raise_on_error=True)
            if raw:
                for c in raw:
                    c["video_id"]    = video["video_id"]
                    c["video_title"] = video["title"]
                all_raw.extend(raw)
            else:
                empty_videos.append(video["title"])
        except Exception as e:
            err_str = str(e).lower()
            reason = "disabled" if ("commentsdisabled" in err_str or "403" in err_str) else "error"
            skipped_videos.append(f"{video['title']} ({reason})")

    if not all_raw:
        parts = []
        if skipped_videos:
            parts.append(f"{len(skipped_videos)} video(s) have comments disabled or restricted")
        if empty_videos:
            parts.append(f"{len(empty_videos)} video(s) have 0 public comments")
        detail = "; ".join(parts) if parts else "no public comments found"
        return {
            "ok": True, "synced": 0,
            "message": f"Checked {len(videos)} videos — {detail}",
            "skipped": skipped_videos,
            "empty": empty_videos,
        }

    # Dedup against already-stored comments
    seen_ids: set = set()
    if all_raw:
        comment_ids = [c["comment_id"] for c in all_raw]
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT comment_id FROM youtube_comments WHERE workspace_id = %s AND comment_id = ANY(%s)",
                    (workspace_id, comment_ids),
                )
                seen_ids = {r[0] for r in cur.fetchall()}

    new_comments = [c for c in all_raw if c["comment_id"] not in seen_ids]
    if not new_comments:
        return {"ok": True, "synced": 0, "message": "All comments already synced"}

    # Classify with Claude Haiku in batches of 20
    CATS = list(_CATEGORY_SENTIMENT.keys())
    product_ctx = (workspace or {}).get("product_context") or "Health-tech medical device brand"

    ai = _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    classified: list[dict] = []

    for i in range(0, len(new_comments), 20):
        batch = new_comments[i:i + 20]
        numbered = "\n".join(f"{j+1}. {c['comment_text'][:300]}" for j, c in enumerate(batch))
        prompt = (
            f"Product context: {product_ctx[:400]}\n\n"
            f"Classify each YouTube comment into ONE category: {', '.join(CATS)}\n"
            f"Also write a short friendly brand reply (max 120 chars).\n\n"
            f"Comments:\n{numbered}\n\n"
            f'Return JSON array ONLY: [{{"i":1,"category":"...","reply":"..."}}]'
        )
        try:
            resp = ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = resp.content[0].text.strip()
            match = _re.search(r"\[.*\]", raw_text, _re.DOTALL)
            if match:
                results = _json.loads(match.group())
                for res in results:
                    idx = int(res.get("i", 1)) - 1
                    if 0 <= idx < len(batch):
                        cat = res.get("category", "other")
                        if cat not in _CATEGORY_SENTIMENT:
                            cat = "other"
                        batch[idx]["category"]        = cat
                        batch[idx]["sentiment"]       = _CATEGORY_SENTIMENT[cat]
                        batch[idx]["suggested_reply"] = res.get("reply", "")
        except Exception:
            pass
        # Ensure defaults for any unclassified
        for c in batch:
            c.setdefault("category", "other")
            c.setdefault("sentiment", "neutral")
            c.setdefault("suggested_reply", "")
        classified.extend(batch)

    # Upsert into youtube_comments
    now = datetime.now(timezone.utc)
    inserted = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for c in classified:
                try:
                    cur.execute(
                        """
                        INSERT INTO youtube_comments
                            (workspace_id, video_id, video_title, comment_id,
                             author_name, comment_text, like_count, reply_count,
                             published_at, category, sentiment, suggested_reply, classified_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (workspace_id, comment_id) DO NOTHING
                        """,
                        (
                            workspace_id,
                            c.get("video_id", ""),
                            c.get("video_title", ""),
                            c["comment_id"],
                            c.get("author_name", "Anonymous"),
                            c["comment_text"],
                            c.get("like_count", 0),
                            c.get("reply_count", 0),
                            c.get("published_at"),
                            c["category"],
                            c["sentiment"],
                            c["suggested_reply"],
                            now,
                        ),
                    )
                    inserted += 1
                except Exception:
                    conn.rollback()
                    continue
        conn.commit()

    return {"ok": True, "synced": inserted, "total_fetched": len(all_raw), "workspace_id": workspace_id}


@app.get("/comments/trends")
async def comments_trends(
    request: Request,
    workspace_id: str = None,
    days: int = 30,
    source: str = "all",
):
    """
    Daily comment counts by category for the last N days.
    Used to plot comment-sentiment trend charts.
    days: 7 | 30 | 90 (clamped to 7–365)
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import datetime as dt
    from services.agent_swarm.db import get_conn

    days = max(7, min(int(days), 365))

    today = dt.date.today()
    date_list = [(today - dt.timedelta(days=i)) for i in range(days - 1, -1, -1)]
    date_strs  = [d.isoformat() for d in date_list]

    # {date_str: {category: count}}
    daily: dict = {d: {} for d in date_strs}

    with get_conn() as conn:
        with conn.cursor() as cur:
            if source in ("all", "meta"):
                cur.execute(
                    """
                    SELECT
                        (COALESCE(comment_created, first_seen_at)
                            AT TIME ZONE 'Asia/Kolkata')::date::text AS day,
                        COALESCE(objection_type, 'other')            AS category,
                        COUNT(*)::int                                AS cnt
                    FROM comment_replies
                    WHERE workspace_id = %s
                      AND COALESCE(comment_created, first_seen_at)
                              >= NOW() - (%s * INTERVAL '1 day')
                    GROUP BY 1, 2
                    """,
                    (workspace_id, days),
                )
                for day, cat, cnt in cur.fetchall():
                    if day in daily:
                        daily[day][cat] = daily[day].get(cat, 0) + cnt

            if source in ("all", "youtube"):
                cur.execute(
                    """
                    SELECT
                        (published_at AT TIME ZONE 'Asia/Kolkata')::date::text AS day,
                        COALESCE(category, 'other')                            AS category,
                        COUNT(*)::int                                          AS cnt
                    FROM youtube_comments
                    WHERE workspace_id = %s
                      AND published_at >= NOW() - (%s * INTERVAL '1 day')
                    GROUP BY 1, 2
                    """,
                    (workspace_id, days),
                )
                for day, cat, cnt in cur.fetchall():
                    if day in daily:
                        daily[day][cat] = daily[day].get(cat, 0) + cnt

    # Build chart_data list
    chart_data = []
    for d_str in date_strs:
        day_counts = daily[d_str]
        total      = sum(day_counts.values())
        dt_obj     = dt.datetime.strptime(d_str, "%Y-%m-%d")
        chart_data.append({
            "date":        d_str,
            "label":       dt_obj.strftime("%-d %b") if hasattr(dt_obj, "strftime") else d_str,
            "total":       total,
            "by_category": day_counts,
        })

    # Period-over-period change (first half vs second half)
    all_cats: set = set()
    for c in chart_data:
        all_cats.update(c["by_category"].keys())

    mid    = len(chart_data) // 2
    first  = chart_data[:mid]
    second = chart_data[mid:]

    period_change = {}
    for cat in all_cats:
        f = sum(d["by_category"].get(cat, 0) for d in first)
        s = sum(d["by_category"].get(cat, 0) for d in second)
        pct = round((s - f) / f * 100) if f > 0 else (100 if s > 0 else 0)
        period_change[cat] = {"first_half": f, "second_half": s, "change_pct": pct}

    # Category metadata for legend
    categories = [
        {
            "category": cat,
            "label":    _CATEGORY_LABEL.get(cat, cat),
            "color":    _CATEGORY_COLOR.get(cat, "gray"),
        }
        for cat in sorted(all_cats,
                          key=lambda c: -sum(d["by_category"].get(c, 0) for d in chart_data))
        if any(d["by_category"].get(cat, 0) > 0 for d in chart_data)
    ]

    return {
        "days":          days,
        "chart_data":    chart_data,
        "period_change": period_change,
        "categories":    categories,
        "total":         sum(d["total"] for d in chart_data),
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

    # Deduct credits before calling Claude
    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        _check_and_deduct_credits(conn, org_id, workspace_id,
                                  FEATURE_COSTS["campaign_brief"], "campaign_brief")

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
    Generate a creative image for a campaign plan.
    - If a matching product image is found in the catalog → IP-Adapter (product-faithful)
    - Otherwise → pure text-to-image (Flux Pro) fallback
    Saves the image URL + source back into plan's new_value.concept.
    Body: {plan_id, workspace_id}
    """
    _auth(request)
    body = await request.json()
    plan_id      = body.get("plan_id")
    workspace_id = body.get("workspace_id")
    if not plan_id or not workspace_id:
        raise HTTPException(status_code=400, detail="plan_id and workspace_id required")

    import json as _json
    from services.agent_swarm.db import get_conn

    # ── Load plan ─────────────────────────────────────────────────────────────
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
    brief   = nv.get("brief", {})

    creative_direction = concept.get("creative_direction", "")
    product_name       = brief.get("product_name") or concept.get("headline") or "health tech product"

    if not creative_direction:
        raise HTTPException(status_code=400, detail="No creative_direction in plan — regenerate the brief first")

    # ── Look up product image from catalog ───────────────────────────────────
    # 1. Try exact / fuzzy name match within this workspace
    # 2. Fall back to any product with images in this workspace
    product_image_url = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Fuzzy match: product name contains any word from plan's product_name
            cur.execute(
                """
                SELECT images FROM products
                WHERE workspace_id = %s
                  AND images != '[]'::jsonb
                  AND jsonb_array_length(images) > 0
                  AND name ILIKE %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (workspace_id, f"%{product_name.split()[0]}%"),
            )
            prod_row = cur.fetchone()

            if not prod_row:
                # Fallback: any product with images for this workspace
                cur.execute(
                    """
                    SELECT images FROM products
                    WHERE workspace_id = %s
                      AND images != '[]'::jsonb
                      AND jsonb_array_length(images) > 0
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (workspace_id,),
                )
                prod_row = cur.fetchone()

    if prod_row:
        images_list = prod_row[0] if isinstance(prod_row[0], list) else _json.loads(prod_row[0] or "[]")
        if images_list and isinstance(images_list[0], dict):
            product_image_url = images_list[0].get("url") or images_list[0].get("src")

    # ── Build prompt ──────────────────────────────────────────────────────────
    prompt = (
        f"Professional Indian health tech advertisement creative. "
        f"Product: {product_name}. "
        f"{creative_direction} "
        f"No text overlays. No watermarks. No logos. "
        f"Clean, modern aesthetic. Warm aspirational lighting. "
        f"Real Indian people, relatable lifestyle setting. "
        f"Square format, suitable for Instagram and Facebook feed ads."
    )

    # ── Generate ──────────────────────────────────────────────────────────────
    from services.agent_swarm.creative.image_gen import (
        generate_ad_image,
        generate_ad_image_ip_adapter,
    )

    generation_mode = "text_to_image"
    try:
        if product_image_url:
            # IP-Adapter: preserves actual product shape, colour, texture in the scene
            image_url = generate_ad_image_ip_adapter(
                prompt=prompt,
                product_image_url=product_image_url,
                ip_scale=0.75,
                size="square_hd",
            )
            generation_mode = "ip_adapter"
        else:
            image_url = generate_ad_image(prompt, size="square_hd")
    except Exception as e:
        # IP-Adapter failed (e.g. product image URL broken) → fall back to T2I
        if product_image_url:
            try:
                image_url = generate_ad_image(prompt, size="square_hd")
                generation_mode = "text_to_image_fallback"
            except Exception as e2:
                raise HTTPException(status_code=500, detail=f"Image generation failed: {e2}")
        else:
            raise HTTPException(status_code=500, detail=f"Image generation failed: {e}")

    # ── Persist back into plan ────────────────────────────────────────────────
    nv_updated = dict(nv)
    nv_updated["concept"] = {
        **concept,
        "generated_image_url":  image_url,
        "image_generation_mode": generation_mode,
        "product_reference_url": product_image_url,
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE action_log SET new_value=%s::jsonb WHERE id=%s",
                (_json.dumps(nv_updated), plan_id),
            )
        conn.commit()

    return {
        "ok":                  True,
        "image_url":           image_url,
        "plan_id":             plan_id,
        "generation_mode":     generation_mode,
        "product_image_used":  product_image_url,
    }


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
    Pulls from live Meta Insights API when connected, falls back to kpi_hourly upload data.
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import json as _json
    import requests as _req
    from datetime import date, timedelta
    from services.agent_swarm.db import get_conn as _gc

    workspace = get_workspace(workspace_id)
    conn_row = get_primary_connection(workspace or {}, "meta") if workspace else None
    meta_connected = conn_row is not None

    campaigns_clean = []
    hours_clean = []

    # ── 1. Live Meta API: account-level campaign insights ────────────────
    if conn_row:
        try:
            access_token = conn_row.get("access_token", "")
            raw_act = conn_row.get("ad_account_id", "")
            act_id = raw_act if raw_act.startswith("act_") else f"act_{raw_act}"
            since = (date.today() - timedelta(days=89)).strftime("%Y-%m-%d")
            until = date.today().strftime("%Y-%m-%d")

            r = _req.get(
                f"{META_GRAPH}/{act_id}/insights",
                params={
                    "access_token": access_token,
                    "level": "campaign",
                    "fields": "campaign_name,impressions,clicks,spend,ctr",
                    "time_range": _json.dumps({"since": since, "until": until}),
                    "limit": 50,
                },
                timeout=20,
            )
            if r.ok:
                for row in r.json().get("data", []):
                    impressions = int(row.get("impressions") or 0)
                    if impressions < 100:
                        continue
                    clicks = int(row.get("clicks") or 0)
                    campaigns_clean.append({
                        "name": row.get("campaign_name", "Unknown"),
                        "ctr": round(float(row.get("ctr") or 0), 2),
                        "clicks": clicks,
                        "impressions": impressions,
                        "spend": round(float(row.get("spend") or 0), 2),
                    })
                campaigns_clean.sort(key=lambda x: x["ctr"], reverse=True)
                campaigns_clean = campaigns_clean[:10]
        except Exception as e:
            print(f"Meta insights API error in organic_posts_signals: {e}")

    # ── 2. Fallback: kpi_hourly Excel-upload campaign data (Meta or unknown platform) ──
    if not campaigns_clean:
        try:
            with _gc() as conn:
                with conn.cursor() as cur:
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
                    for row in cur.fetchall():
                        campaigns_clean.append({
                            "name": row[0] or "Unknown",
                            "clicks": int(row[1] or 0),
                            "impressions": int(row[2] or 0),
                            "spend": float(row[3] or 0),
                            "ctr": float(row[4] or 0),
                        })
                    if not meta_connected and campaigns_clean:
                        meta_connected = True
        except Exception as e:
            print(f"kpi_hourly fallback error: {e}")

    # ── 3a. Best hours: Meta API hourly breakdown ─────────────────────────
    if conn_row:
        try:
            access_token = conn_row.get("access_token", "")
            raw_act = conn_row.get("ad_account_id", "")
            act_id2 = raw_act if raw_act.startswith("act_") else f"act_{raw_act}"
            since2 = (date.today() - timedelta(days=89)).strftime("%Y-%m-%d")
            until2 = date.today().strftime("%Y-%m-%d")
            r_hourly = _req.get(
                f"{META_GRAPH}/{act_id2}/insights",
                params={
                    "access_token": access_token,
                    "level": "account",
                    "fields": "impressions,clicks,ctr",
                    "breakdowns": "hourly_stats_aggregated_by_advertiser_time_zone",
                    "time_range": _json.dumps({"since": since2, "until": until2}),
                    "limit": 24,
                },
                timeout=20,
            )
            if r_hourly.ok:
                hour_rows = []
                for row in r_hourly.json().get("data", []):
                    impressions = int(row.get("impressions") or 0)
                    if impressions < 50:
                        continue
                    hour_str = row.get("hourly_stats_aggregated_by_advertiser_time_zone", "")
                    try:
                        hour_num = int(hour_str.split(":")[0])
                    except Exception:
                        continue
                    ctr = float(row.get("ctr") or 0)
                    if ctr <= 0:
                        continue
                    hour_rows.append({
                        "hour": str(hour_num),
                        "avg_ctr": round(ctr, 2),
                        "impressions": impressions,
                        "conversions": 0,
                        "source": "meta",
                    })
                hour_rows.sort(key=lambda x: x["avg_ctr"], reverse=True)
                hours_clean = hour_rows[:5]
        except Exception as e:
            print(f"Meta hourly breakdown error: {e}")

    # ── 3b. Fallback: kpi_hourly hour_of_day data ─────────────────────────
    if not hours_clean:
        try:
            with _gc() as conn:
                with conn.cursor() as cur:
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
                        HAVING COALESCE(entity_name, raw_json->>'hour', (raw_json->>'hour_of_day')) IS NOT NULL
                          AND AVG(COALESCE((raw_json->>'ctr')::numeric, 0)) > 0
                        ORDER BY avg_ctr DESC
                        LIMIT 5
                        """,
                        (workspace_id,),
                    )
                    for row in cur.fetchall():
                        hours_clean.append({
                            "hour": row[0],
                            "avg_ctr": float(row[1] or 0),
                            "conversions": int(row[2] or 0),
                            "source": "google",
                        })
        except Exception as e:
            print(f"hour_of_day fallback error: {e}")

    # ── 4. YouTube upload time correlation ────────────────────────────────
    youtube_upload_times = []
    try:
        with _gc() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        EXTRACT(HOUR FROM published_at AT TIME ZONE 'Asia/Kolkata')::int AS upload_hour,
                        COUNT(*) AS video_count,
                        ROUND(AVG(view_count)) AS avg_views,
                        ROUND(AVG(like_count)) AS avg_likes
                    FROM youtube_videos
                    WHERE workspace_id = %s
                      AND published_at IS NOT NULL
                      AND view_count > 0
                    GROUP BY 1
                    ORDER BY avg_views DESC
                    LIMIT 6
                    """,
                    (workspace_id,),
                )
                for row in cur.fetchall():
                    youtube_upload_times.append({
                        "hour": int(row[0]),
                        "video_count": int(row[1]),
                        "avg_views": int(row[2] or 0),
                        "avg_likes": int(row[3] or 0),
                    })
    except Exception as e:
        print(f"YouTube upload time query error: {e}")

    return {
        "meta_connected": meta_connected,
        "has_meta_data": len(campaigns_clean) > 0,
        "has_timing_data": len(hours_clean) > 0,
        "has_youtube_times": len(youtube_upload_times) > 0,
        "top_campaigns": campaigns_clean,
        "best_hours": hours_clean,
        "youtube_upload_times": youtube_upload_times,
        "workspace_id": workspace_id,
    }


# ── KPI Blended CAC (legacy awareness page helper) ───────────────────────────

@app.get("/kpi/blended-cac")
async def kpi_blended_cac(
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


# ── SEO / Google Search Console ──────────────────────────────────────────────

def _get_gsc_connector(workspace_id: str, site_url: str = ""):
    """Load GSC credentials from google_auth_tokens and return a GSCConnector."""
    from services.agent_swarm.connectors.gsc import GSCConnector
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT access_token, refresh_token, client_id, client_secret, gsc_site_url "
                "FROM google_auth_tokens WHERE workspace_id=%s LIMIT 1",
                (workspace_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Google not connected for this workspace")
    access_token, refresh_token, client_id, client_secret, stored_site = row
    return GSCConnector(
        access_token=access_token or "",
        refresh_token=refresh_token or "",
        client_id=client_id or "",
        client_secret=client_secret or "",
        site_url=site_url or stored_site or "",
    )


@app.get("/seo/status")
async def seo_status(request: Request, workspace_id: str = None):
    """Return GSC connection status + list of verified sites."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    # Check if Google is connected at all
    try:
        gsc = _get_gsc_connector(workspace_id)
    except HTTPException:
        return {"connected": False, "sites": [], "active_site": "", "workspace_id": workspace_id}

    # Try listing GSC sites — may fail if scope not granted or no verified sites
    sites = []
    gsc_error = None
    try:
        sites = gsc.list_sites()
    except Exception as e:
        gsc_error = str(e)

    # Auto-save default site
    site_url = gsc.site_url or (sites[0]["siteUrl"] if sites else "")
    if site_url and not gsc.site_url:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE google_auth_tokens SET gsc_site_url=%s WHERE workspace_id=%s",
                        (site_url, workspace_id),
                    )
        except Exception:
            pass

    return {
        "connected": True,  # Google OAuth is connected
        "gsc_ready": len(sites) > 0,  # GSC scope + verified sites available
        "gsc_error": gsc_error,
        "sites": [{"url": s["siteUrl"], "permission": s.get("permissionLevel", "")}
                  for s in sites],
        "active_site": site_url,
        "workspace_id": workspace_id,
    }


@app.get("/seo/keywords")
async def seo_keywords(request: Request, workspace_id: str = None,
                       days: int = 28, limit: int = 50, site_url: str = ""):
    """Top organic keywords with clicks, impressions, CTR, position."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        gsc = _get_gsc_connector(workspace_id, site_url)
        if not gsc.site_url:
            raise HTTPException(status_code=400,
                detail="No GSC site found. Connect Google Search Console first.")
        keywords = gsc.top_keywords(days=days, limit=limit)
        return {"keywords": keywords, "count": len(keywords),
                "days": days, "site": gsc.site_url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/seo/pages")
async def seo_pages(request: Request, workspace_id: str = None,
                    days: int = 28, limit: int = 50, site_url: str = ""):
    """Top pages by organic clicks."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        gsc = _get_gsc_connector(workspace_id, site_url)
        if not gsc.site_url:
            raise HTTPException(status_code=400,
                detail="No GSC site found. Connect Google Search Console first.")
        pages = gsc.top_pages(days=days, limit=limit)
        devices = gsc.device_breakdown(days=days)
        countries = gsc.country_breakdown(days=days, limit=10)
        return {"pages": pages, "devices": devices, "countries": countries,
                "days": days, "site": gsc.site_url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/seo/audit-url")
async def seo_audit_url(request: Request):
    """
    On-page SEO audit for any URL.
    Fetches with Jina/requests, then Claude grades and suggests improvements.
    """
    _auth(request)
    body = await request.json()
    url = (body.get("url") or "").strip()
    workspace_id = body.get("workspace_id", "")
    if not url or not workspace_id:
        raise HTTPException(status_code=400, detail="url and workspace_id required")
    if not url.startswith("http"):
        url = "https://" + url

    import requests as _req
    import re as _re
    import anthropic as _anthropic
    import json as _json
    from services.agent_swarm.config import ANTHROPIC_API_KEY as _AKEY, CLAUDE_MODEL as _MODEL
    from bs4 import BeautifulSoup as _BS
    from urllib.parse import urlparse as _up

    # Fetch page
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; RunwaySEO/1.0)",
        "Accept": "text/html,*/*",
    }
    try:
        r = _req.get(url, headers=headers, timeout=12, allow_redirects=True)
        html = r.text
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not fetch URL: {e}")

    soup = _BS(html, "lxml")

    # Extract key SEO signals
    title_tag  = (soup.find("title") or {}).get_text(strip=True) if soup.find("title") else ""
    meta_desc  = ""
    canonical  = ""
    h1s = [t.get_text(strip=True) for t in soup.find_all("h1")]
    h2s = [t.get_text(strip=True) for t in soup.find_all("h2")][:8]

    for meta in soup.find_all("meta"):
        if meta.get("name", "").lower() == "description":
            meta_desc = meta.get("content", "")
        if meta.get("property", "").lower() == "og:description" and not meta_desc:
            meta_desc = meta.get("content", "")

    can_tag = soup.find("link", rel="canonical")
    if can_tag:
        canonical = can_tag.get("href", "")

    imgs = soup.find_all("img")
    imgs_without_alt = sum(1 for i in imgs if not i.get("alt", "").strip())
    total_imgs = len(imgs)

    # Schema.org markup detection
    ld_types = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = _json.loads(script.string or "")
            items = ld if isinstance(ld, list) else ld.get("@graph", [ld])
            ld_types += [item.get("@type", "") for item in items if item.get("@type")]
        except Exception:
            pass

    word_count = len(soup.get_text(separator=" ").split())
    internal_links = len([a for a in soup.find_all("a", href=True)
                          if a["href"].startswith("/") or _up(url).netloc in a["href"]])

    # Jina fallback for JS-rendered pages (headless Shopify/SPAs)
    if word_count < 200:
        try:
            jina_r = _req.get(
                f"https://r.jina.ai/{url}",
                headers={"Accept": "text/markdown", "User-Agent": "RunwaySEO/1.0"},
                timeout=35,
            )
            if jina_r.ok and len(jina_r.text) > 200:
                jina_text = jina_r.text
                # Re-parse with Jina markdown content
                jina_soup = _BS(jina_text, "lxml")
                jina_wc = len(jina_text.split())
                if jina_wc > word_count:
                    # Extract H1/H2 from Jina markdown (## headings)
                    h1_lines = [l.lstrip("# ").strip() for l in jina_text.splitlines() if l.startswith("# ") and not l.startswith("## ")]
                    h2_lines = [l.lstrip("# ").strip() for l in jina_text.splitlines() if l.startswith("## ")][:8]
                    if h1_lines:
                        h1s = h1_lines
                    if h2_lines:
                        h2s = h2_lines
                    word_count = jina_wc
        except Exception:
            pass  # Jina timed out — use BS results as-is

    signals = {
        "title": title_tag,
        "title_length": len(title_tag),
        "meta_description": meta_desc,
        "meta_desc_length": len(meta_desc),
        "h1s": h1s,
        "h2s": h2s,
        "canonical": canonical,
        "images_total": total_imgs,
        "images_missing_alt": imgs_without_alt,
        "schema_types": ld_types,
        "word_count": word_count,
        "internal_links": internal_links,
    }

    # Claude audit
    client = _anthropic.Anthropic(api_key=_AKEY)
    prompt = f"""Audit this page's on-page SEO signals and return a JSON report.

URL: {url}
Page signals:
{_json.dumps(signals, indent=2)}

JSON structure (respond with ONLY the JSON object, no other text):
{{
  "overall_score": <integer 0-100>,
  "grade": "<A|B|C|D|F>",
  "summary": "<2 sentence overview>",
  "issues": [
    {{"severity": "critical", "title": "...", "detail": "...", "fix": "..."}},
    {{"severity": "warning", "title": "...", "detail": "...", "fix": "..."}}
  ],
  "strengths": ["...", "..."],
  "quick_wins": ["specific 1-sentence fix", "..."]
}}

Scoring guide:
- Title: ideal 50-60 chars with primary keyword (+20pts if good, -15 if missing/too short/too long)
- Meta description: 150-160 chars compelling (+10pts)
- H1: exactly one with keyword (+15pts, -20 if missing)
- Schema markup: Product/FAQ/Review (+10pts each)
- Alt text on all images (+5pts)
- Word count: 300+ product page (+10pts)
- Internal links: 3+ (+5pts)

Be specific — reference the actual title/meta text. Give concrete one-line fixes."""

    msg = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system="You are an expert SEO auditor. Always respond with valid JSON only. Never include explanatory text, markdown, or code fences. Start your response with { and end with }.",
        messages=[{"role": "user", "content": prompt}],
    )
    resp = msg.content[0].text.strip()
    print(f"[SEO audit] raw Claude resp (first 500): {resp[:500]}", flush=True)
    # Strip markdown fences if present
    if resp.startswith("```"):
        resp = _re.sub(r'^```[a-z]*\n?', '', resp).rstrip('`').strip()
    audit = None
    try:
        audit = _json.loads(resp)
    except Exception:
        pass
    if audit is None:
        try:
            m = _re.search(r'\{.*\}', resp, _re.DOTALL)
            if m:
                audit = _json.loads(m.group())
        except Exception:
            pass
    if audit is None:
        audit = {
            "overall_score": 0, "grade": "?",
            "summary": "Could not parse AI response — try again.",
            "issues": [], "strengths": [], "quick_wins": [],
        }

    return {"url": url, "signals": signals, "audit": audit}


@app.post("/seo/set-site")
async def seo_set_site(request: Request):
    """Save the active GSC site URL for a workspace."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    site_url = body.get("site_url", "")
    if not workspace_id or not site_url:
        raise HTTPException(status_code=400, detail="workspace_id and site_url required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE google_auth_tokens SET gsc_site_url=%s WHERE workspace_id=%s",
                (site_url, workspace_id),
            )
    return {"ok": True, "site_url": site_url}


@app.get("/seo/backlinks")
async def seo_backlinks_list(request: Request, workspace_id: str = None):
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, source_url, source_domain, target_url, anchor_text,
                       status, domain_authority, notes, created_at
                FROM seo_backlinks WHERE workspace_id=%s ORDER BY created_at DESC
            """, (workspace_id,))
            rows = cur.fetchall()
    return {"backlinks": [
        {"id": str(r[0]), "source_url": r[1], "source_domain": r[2] or "",
         "target_url": r[3] or "", "anchor_text": r[4] or "", "status": r[5] or "prospect",
         "domain_authority": r[6], "notes": r[7] or "",
         "created_at": r[8].isoformat() if r[8] else None}
        for r in rows
    ]}


@app.post("/seo/backlinks/add")
async def seo_backlinks_add(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    source_url = (body.get("source_url") or "").strip()
    if not workspace_id or not source_url:
        raise HTTPException(status_code=400, detail="workspace_id and source_url required")
    if not source_url.startswith("http"):
        source_url = "https://" + source_url
    import re as _re2
    m = _re2.match(r'https?://([^/]+)', source_url)
    source_domain = m.group(1) if m else source_url
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO seo_backlinks (workspace_id, source_url, source_domain, target_url, anchor_text, status, domain_authority, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, (workspace_id, source_url, source_domain,
                  body.get("target_url", ""), body.get("anchor_text", ""),
                  body.get("status", "prospect"), body.get("domain_authority") or None,
                  body.get("notes", "")))
            new_id = str(cur.fetchone()[0])
    return {"ok": True, "id": new_id}


@app.patch("/seo/backlinks/{backlink_id}")
async def seo_backlinks_update(backlink_id: str, request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    allowed = ("status", "notes", "anchor_text", "domain_authority", "target_url")
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return {"ok": True}
    set_clause = ", ".join(f"{k}=%s" for k in updates)
    values = list(updates.values()) + [backlink_id, workspace_id]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE seo_backlinks SET {set_clause}, updated_at=NOW() WHERE id=%s AND workspace_id=%s", values)
    return {"ok": True}


@app.delete("/seo/backlinks/{backlink_id}")
async def seo_backlinks_delete(backlink_id: str, request: Request):
    _auth(request)
    ws = request.query_params.get("workspace_id", "")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM seo_backlinks WHERE id=%s AND workspace_id=%s", (backlink_id, ws))
    return {"ok": True}


@app.post("/seo/offpage-analysis")
async def seo_offpage_analysis(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    import anthropic as _anthropic, json as _json, re as _re
    from services.agent_swarm.config import ANTHROPIC_API_KEY as _AKEY, CLAUDE_MODEL as _MODEL
    from services.agent_swarm.core.workspace import get_workspace
    ws = get_workspace(workspace_id)
    ws_type = (ws or {}).get("workspace_type", "d2c")
    ws_name = (ws or {}).get("name", "")
    products_context = ""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM products WHERE workspace_id=%s AND is_competitor=false LIMIT 5", (workspace_id,))
                prods = [r[0] for r in cur.fetchall()]
                products_context = ", ".join(prods)
    except Exception:
        pass
    active_site = body.get("active_site", "")
    client = _anthropic.Anthropic(api_key=_AKEY)
    prompt = f"""You are an expert SEO strategist for {ws_type} businesses in India.

Business: {ws_name}
Type: {ws_type}
Products: {products_context or "health/consumer products"}
Website: {active_site or "their website"}

Generate a comprehensive off-page SEO strategy. Return ONLY valid JSON:
{{
  "summary": "2-sentence overview of off-page SEO opportunity",
  "strategies": [
    {{
      "category": "Directory Listings|Guest Posts|PR & Press|Partnerships|Broken Link Building|Social Profiles|Forum & Community|Product Reviews",
      "priority": "high|medium|low",
      "title": "specific strategy name",
      "description": "exactly what to do",
      "targets": ["specific real website 1", "specific real website 2", "specific real website 3"],
      "effort": "1-2 hours|half day|1 week",
      "expected_impact": "concrete SEO impact"
    }}
  ],
  "quick_wins": [
    {{"action": "specific thing to do today", "target": "specific real website", "why": "SEO benefit"}}
  ],
  "outreach_template": "ready-to-send email template for requesting a backlink (personalizable)"
}}

Name REAL, specific websites relevant to this niche (health devices, India market). Include at least 6 strategies and 5 quick wins."""

    msg = client.messages.create(
        model=_MODEL, max_tokens=2048,
        system="You are an SEO strategist. Respond with valid JSON only. No markdown fences. Start with {",
        messages=[{"role": "user", "content": prompt}],
    )
    resp = msg.content[0].text.strip()
    if resp.startswith("```"):
        resp = _re.sub(r'^```[a-z]*\n?', '', resp).rstrip('`').strip()
    plan = None
    try:
        plan = _json.loads(resp)
    except Exception:
        m2 = _re.search(r'\{.*\}', resp, _re.DOTALL)
        if m2:
            try:
                plan = _json.loads(m2.group())
            except Exception:
                pass
    if not plan:
        raise HTTPException(status_code=500, detail="Could not generate plan")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO seo_offpage_plans (workspace_id, plan) VALUES (%s, %s::jsonb)", (workspace_id, _json.dumps(plan)))
    except Exception as e:
        print(f"seo_offpage_plans save error: {e}")
    return {"plan": plan, "workspace_id": workspace_id}


@app.get("/seo/offpage-analysis/latest")
async def seo_offpage_latest(request: Request, workspace_id: str = None):
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT plan, created_at FROM seo_offpage_plans WHERE workspace_id=%s ORDER BY created_at DESC LIMIT 1", (workspace_id,))
            row = cur.fetchone()
    if not row:
        return {"plan": None}
    return {"plan": row[0], "created_at": row[1].isoformat()}


@app.post("/seo/send-to-approvals")
async def seo_send_to_approvals(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    issue = body.get("issue", {})
    url = body.get("url", "")
    signals = body.get("signals", {})
    if not workspace_id or not issue:
        raise HTTPException(status_code=400, detail="workspace_id and issue required")
    import anthropic as _anthropic
    from services.agent_swarm.config import ANTHROPIC_API_KEY as _AKEY, CLAUDE_MODEL as _MODEL
    client = _anthropic.Anthropic(api_key=_AKEY)
    fix_prompt = f"""SEO issue to fix:
URL: {url}
Issue: {issue.get('title','')}
Detail: {issue.get('detail','')}
Current title: "{signals.get('title','')}"
Current meta: "{signals.get('meta_description','')}"
Current H1s: {signals.get('h1s',[])}

Write the EXACT implementation — copy-paste ready text. No explanation, just the fix.
===FIX===
[exact new title tag / meta description / H1 text / schema JSON / whatever is needed]
===END==="""
    msg = client.messages.create(model=_MODEL, max_tokens=512, messages=[{"role": "user", "content": fix_prompt}])
    resp = msg.content[0].text.strip()
    fix_content = resp
    if "===FIX===" in resp and "===END===" in resp:
        fix_content = resp.split("===FIX===")[1].split("===END===")[0].strip()
    action_text = f"SEO Fix — {issue.get('title','')}\n\nPage: {url}\nIssue: {issue.get('detail','')}\n\nImplement this:\n{fix_content}"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO action_log (workspace_id, action_type, description, status, triggered_by, new_value)
                VALUES (%s, 'seo_fix', %s, 'pending', 'seo_audit', %s) RETURNING id
            """, (workspace_id, f"SEO: {issue.get('title','')}", action_text))
            action_id = str(cur.fetchone()[0])
    return {"ok": True, "action_id": action_id, "fix_content": fix_content}


# ── SEO Shopify Automation ────────────────────────────────────────────────────

def _get_shopify_creds(workspace_id: str):
    """Get Shopify shop_domain + access_token for a workspace."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shop_domain, access_token FROM shopify_connections WHERE workspace_id=%s LIMIT 1",
                (workspace_id,)
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="Shopify not connected for this workspace")
    return row[0], row[1]


@app.get("/seo/shopify/scan")
async def seo_shopify_scan(request: Request, workspace_id: str = None):
    """Scan all Shopify products for SEO issues: missing meta, short titles, missing alt text."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    shop_domain, access_token = _get_shopify_creds(workspace_id)
    from services.agent_swarm.connectors.shopify import ShopifyConnector
    products = ShopifyConnector.get_products_seo(shop_domain, access_token)
    issues = []
    for p in products:
        pid = p["id"]
        title = p.get("title", "")
        seo_title = p.get("metafields_global_title_tag") or title
        seo_desc = p.get("metafields_global_description_tag") or ""
        images = p.get("images", [])
        imgs_missing_alt = [i for i in images if not (i.get("alt") or "").strip()]
        p_issues = []
        if len(seo_title) < 30 or len(seo_title) > 70:
            p_issues.append({"type": "seo_title", "severity": "warning",
                             "detail": f"SEO title is {len(seo_title)} chars (ideal 30-70): '{seo_title}'"})
        if len(seo_desc) < 100:
            p_issues.append({"type": "seo_desc", "severity": "critical",
                             "detail": f"Meta description is {len(seo_desc)} chars (ideal 140-160)"})
        if imgs_missing_alt:
            p_issues.append({"type": "alt_text", "severity": "warning",
                             "detail": f"{len(imgs_missing_alt)} of {len(images)} images missing alt text",
                             "image_ids": [i["id"] for i in imgs_missing_alt]})
        if p_issues:
            issues.append({
                "product_id": pid,
                "product_title": title,
                "handle": p.get("handle", ""),
                "seo_title": seo_title,
                "seo_desc": seo_desc,
                "issues": p_issues,
                "images": [{"id": i["id"], "src": i.get("src",""), "alt": i.get("alt","")} for i in images[:3]],
            })
    return {"products_scanned": len(products), "products_with_issues": len(issues), "issues": issues}


@app.post("/seo/shopify/push-fix")
async def seo_shopify_push_fix(request: Request):
    """Push an SEO fix (title/meta/alt) directly to Shopify."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    product_id = body.get("product_id")
    fix_type = body.get("fix_type")  # seo_title | seo_desc | alt_text
    value = body.get("value", "")
    image_id = body.get("image_id")
    if not workspace_id or not product_id or not fix_type:
        raise HTTPException(status_code=400, detail="workspace_id, product_id, fix_type required")
    shop_domain, access_token = _get_shopify_creds(workspace_id)
    from services.agent_swarm.connectors.shopify import ShopifyConnector
    try:
        if fix_type == "alt_text" and image_id:
            ShopifyConnector.update_image_alt(shop_domain, access_token, product_id, image_id, value)
        elif fix_type in ("seo_title", "seo_desc"):
            seo_title = value if fix_type == "seo_title" else None
            seo_desc = value if fix_type == "seo_desc" else None
            ShopifyConnector.update_product_seo(shop_domain, access_token, product_id, seo_title, seo_desc)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown fix_type: {fix_type}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "product_id": product_id, "fix_type": fix_type}


@app.post("/seo/shopify/fix-alts")
async def seo_shopify_fix_alts(request: Request):
    """AI generates alt text for ALL images missing it, then pushes to Shopify."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    shop_domain, access_token = _get_shopify_creds(workspace_id)
    from services.agent_swarm.connectors.shopify import ShopifyConnector
    import anthropic as _anthropic, json as _json
    from services.agent_swarm.config import ANTHROPIC_API_KEY as _AKEY, CLAUDE_MODEL as _MODEL
    products = ShopifyConnector.get_products_seo(shop_domain, access_token)
    client = _anthropic.Anthropic(api_key=_AKEY)
    fixed = 0
    errors = 0
    for p in products:
        images_missing = [i for i in p.get("images", []) if not (i.get("alt") or "").strip()]
        if not images_missing:
            continue
        # Generate alt texts in one Claude call for all images of this product
        prompt = f"""Product: {p.get('title','')}
Description: {(p.get('body_html','') or '')[:300]}

Generate concise, descriptive alt text (max 12 words each) for {len(images_missing)} product images.
Return ONLY a JSON array of strings, one per image, in order.
Example: ["Front view of EasyTouch glucose monitor in white", "Side view showing USB port"]"""
        try:
            msg = client.messages.create(model=_MODEL, max_tokens=512,
                system="Return valid JSON array only.",
                messages=[{"role": "user", "content": prompt}])
            alts = _json.loads(msg.content[0].text.strip())
            if not isinstance(alts, list):
                alts = [alts] * len(images_missing)
            for img, alt in zip(images_missing, alts):
                try:
                    ShopifyConnector.update_image_alt(shop_domain, access_token, p["id"], img["id"], str(alt))
                    fixed += 1
                except Exception:
                    errors += 1
        except Exception as e:
            print(f"[fix-alts] product {p['id']} error: {e}")
            errors += len(images_missing)
    return {"ok": True, "fixed": fixed, "errors": errors}


@app.post("/seo/shopify/generate-schema")
async def seo_shopify_generate_schema(request: Request):
    """Generate Product schema JSON-LD for a Shopify product."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    product_id = body.get("product_id")
    if not workspace_id or not product_id:
        raise HTTPException(status_code=400, detail="workspace_id and product_id required")
    shop_domain, access_token = _get_shopify_creds(workspace_id)
    import requests as _rq, json as _json
    from services.agent_swarm.connectors.shopify import _normalize_shop
    shop = _normalize_shop(shop_domain)
    headers = {"X-Shopify-Access-Token": access_token}
    r = _rq.get(f"https://{shop}/admin/api/2024-01/products/{product_id}.json", headers=headers, timeout=10)
    r.raise_for_status()
    p = r.json().get("product", {})
    variant = (p.get("variants") or [{}])[0]
    image = (p.get("images") or [{}])[0]
    schema = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": p.get("title", ""),
        "description": (p.get("body_html") or "").replace("<[^>]+>", ""),
        "image": image.get("src", ""),
        "sku": variant.get("sku", ""),
        "brand": {"@type": "Brand", "name": p.get("vendor", "")},
        "offers": {
            "@type": "Offer",
            "priceCurrency": "INR",
            "price": variant.get("price", "0"),
            "availability": "https://schema.org/InStock" if p.get("status") == "active" else "https://schema.org/OutOfStock",
            "url": f"https://{shop_domain}/products/{p.get('handle','')}"
        }
    }
    gtm_snippet = f"""<!-- GTM Custom HTML Tag — paste in Google Tag Manager -->
<script type="application/ld+json">
{_json.dumps(schema, indent=2)}
</script>"""
    return {"product_title": p.get("title"), "schema": schema, "gtm_snippet": gtm_snippet,
            "shopify_liquid": "{% comment %}Add to product.liquid theme file{% endcomment %}\n<script type=\"application/ld+json\">{{ product | json }}</script>"}


# ── SEO WordPress Connector ───────────────────────────────────────────────────

@app.post("/seo/wordpress/connect")
async def seo_wordpress_connect(request: Request):
    """Test WordPress REST API connection and save credentials."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    wp_url = (body.get("wp_url") or "").strip().rstrip("/")
    app_password = (body.get("app_password") or "").strip()
    wp_username = (body.get("wp_username") or "").strip()
    if not workspace_id or not wp_url or not app_password or not wp_username:
        raise HTTPException(status_code=400, detail="workspace_id, wp_url, wp_username, app_password required")
    if not wp_url.startswith("http"):
        wp_url = "https://" + wp_url
    import requests as _rq, base64 as _b64
    credentials = _b64.b64encode(f"{wp_username}:{app_password}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Content-Type": "application/json"}
    try:
        test = _rq.get(f"{wp_url}/wp-json/wp/v2/users/me", headers=headers, timeout=10)
        if test.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid username or application password")
        if not test.ok:
            raise HTTPException(status_code=400, detail=f"WordPress API error: {test.status_code}")
        user_info = test.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not connect to WordPress: {e}")
    # Save to platform_connections
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM platform_connections WHERE workspace_id=%s AND platform='wordpress'", (workspace_id,))
            cur.execute("""
                INSERT INTO platform_connections (workspace_id, platform, account_id, account_name, access_token, meta)
                VALUES (%s, 'wordpress', %s, %s, %s, %s::jsonb)
            """, (workspace_id, wp_url, user_info.get("name", wp_username),
                  app_password, json.dumps({"wp_url": wp_url, "wp_username": wp_username})))
    return {"ok": True, "wp_url": wp_url, "user": user_info.get("name", wp_username)}


@app.get("/seo/wordpress/status")
async def seo_wordpress_status(request: Request, workspace_id: str = None):
    """Check if WordPress is connected."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT account_id, account_name, meta FROM platform_connections
                WHERE workspace_id=%s AND platform='wordpress' LIMIT 1
            """, (workspace_id,))
            row = cur.fetchone()
    if not row:
        return {"connected": False}
    return {"connected": True, "wp_url": row[0], "user": row[1], "meta": row[2]}


@app.get("/seo/wordpress/scan")
async def seo_wordpress_scan(request: Request, workspace_id: str = None):
    """Scan WordPress posts and pages for SEO issues."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT account_id, access_token, meta FROM platform_connections
                WHERE workspace_id=%s AND platform='wordpress' LIMIT 1
            """, (workspace_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="WordPress not connected")
    wp_url, app_password, meta = row[0], row[1], row[2] or {}
    wp_username = meta.get("wp_username", "")
    import requests as _rq, base64 as _b64
    credentials = _b64.b64encode(f"{wp_username}:{app_password}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}"}
    issues = []
    for post_type in ["posts", "pages"]:
        try:
            r = _rq.get(f"{wp_url}/wp-json/wp/v2/{post_type}?per_page=20&status=publish&_fields=id,title,link,yoast_head_json,meta", headers=headers, timeout=15)
            if not r.ok:
                continue
            for post in r.json():
                pid = post["id"]
                title = post.get("title", {}).get("rendered", "")
                link = post.get("link", "")
                yoast = post.get("yoast_head_json") or {}
                seo_title = yoast.get("title") or title
                seo_desc = yoast.get("description") or ""
                p_issues = []
                if len(seo_title) < 30 or len(seo_title) > 70:
                    p_issues.append({"type": "seo_title", "severity": "warning", "detail": f"SEO title {len(seo_title)} chars (ideal 30-70)"})
                if len(seo_desc) < 100:
                    p_issues.append({"type": "seo_desc", "severity": "critical", "detail": f"Meta description {len(seo_desc)} chars (need 140-160)"})
                if p_issues:
                    issues.append({"post_id": pid, "post_type": post_type.rstrip("s"), "title": title,
                                   "link": link, "seo_title": seo_title, "seo_desc": seo_desc, "issues": p_issues})
        except Exception as e:
            print(f"[wp scan] {post_type} error: {e}")
    return {"issues": issues, "total": len(issues)}


@app.post("/seo/wordpress/push-fix")
async def seo_wordpress_push_fix(request: Request):
    """Push an SEO fix (title/meta) to a WordPress post via Yoast or WP meta."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id")
    post_id = body.get("post_id")
    fix_type = body.get("fix_type")  # seo_title | seo_desc
    value = body.get("value", "")
    post_type = body.get("post_type", "post")
    if not workspace_id or not post_id or not fix_type:
        raise HTTPException(status_code=400, detail="workspace_id, post_id, fix_type required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT account_id, access_token, meta FROM platform_connections WHERE workspace_id=%s AND platform='wordpress' LIMIT 1", (workspace_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="WordPress not connected")
    wp_url, app_password, meta = row[0], row[1], row[2] or {}
    wp_username = meta.get("wp_username", "")
    import requests as _rq, base64 as _b64
    credentials = _b64.b64encode(f"{wp_username}:{app_password}".encode()).decode()
    headers = {"Authorization": f"Basic {credentials}", "Content-Type": "application/json"}
    endpoint = "pages" if post_type == "page" else "posts"
    # Try Yoast SEO meta fields first, fall back to title
    meta_key = "_yoast_wpseo_title" if fix_type == "seo_title" else "_yoast_wpseo_metadesc"
    payload: dict = {"meta": {meta_key: value}}
    if fix_type == "seo_title":
        payload["title"] = value
    r = _rq.post(f"{wp_url}/wp-json/wp/v2/{endpoint}/{post_id}", headers=headers, json=payload, timeout=15)
    if not r.ok:
        raise HTTPException(status_code=500, detail=f"WordPress update failed: {r.status_code} {r.text[:200]}")
    return {"ok": True, "post_id": post_id, "fix_type": fix_type}


# ── AI Contextual Chat ─────────────────────────────────────────────────────────

@app.post("/chat")
async def ai_chat(request: Request):
    """
    Contextual AI chat — knows all workspace data (campaigns, YouTube, budget, etc.)
    Body: { workspace_id, message, history: [{role, content}] }
    Costs 1 credit per message.
    """
    body = await request.json()
    workspace_id = body.get("workspace_id")
    user_message  = (body.get("message") or "").strip()

    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if not user_message:
        raise HTTPException(status_code=400, detail="message required")

    # Deduct 1 credit
    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        _check_and_deduct_credits(conn, org_id, workspace_id, FEATURE_COSTS["ai_chat"], "ai_chat")

    # ── Gather workspace context ────────────────────────────────────────────────
    ctx_lines: list[str] = []
    ws_name = "this workspace"

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Workspace name + type
                cur.execute(
                    "SELECT name, workspace_type FROM workspaces WHERE id = %s",
                    (workspace_id,),
                )
                ws_row = cur.fetchone()
                ws_name = ws_row[0] if ws_row else "this workspace"
                ws_type = ws_row[1] if ws_row else "unknown"
                ctx_lines.append(f"Workspace: {ws_name} (type: {ws_type})")

                # Connected platforms
                cur.execute(
                    "SELECT platform, account_name, account_id FROM platform_connections WHERE workspace_id = %s AND is_active = TRUE",
                    (workspace_id,),
                )
                platforms = cur.fetchall()
                if platforms:
                    plat_strs = [f"{p[0]} ({p[1] or p[2]})" for p in platforms]
                    ctx_lines.append(f"Connected platforms: {', '.join(plat_strs)}")

                # Meta KPI totals — try workspace_id match first, fall back to all rows for this ws
                # Also try last 30 days if 7 days has no data
                for days in (7, 30):
                    cur.execute(
                        """
                        SELECT SUM(spend), SUM(revenue), SUM(clicks), SUM(impressions), SUM(conversions)
                        FROM kpi_hourly
                        WHERE (workspace_id = %s OR workspace_id IS NULL)
                          AND platform = 'meta'
                          AND recorded_at >= NOW() - INTERVAL '%s days'
                          AND entity_level = 'campaign'
                        """ % ('%s', days),
                        (workspace_id,),
                    )
                    meta = cur.fetchone()
                    if meta and meta[0] and float(meta[0]) > 0:
                        roas = round(float(meta[1] or 0) / float(meta[0]), 2) if float(meta[0]) > 0 else 0
                        ctr = round(float(meta[2] or 0) / float(meta[3] or 1) * 100, 2) if meta[3] else 0
                        ctx_lines.append(
                            f"Meta Ads ({days}d total): Spend ₹{float(meta[0]):,.0f}, "
                            f"Revenue ₹{float(meta[1] or 0):,.0f}, ROAS {roas}x, "
                            f"Clicks {int(meta[2] or 0):,}, Impressions {int(meta[3] or 0):,}, "
                            f"CTR {ctr}%, Conversions {int(meta[4] or 0):,}"
                        )
                        break

                # Per-campaign breakdown from kpi_hourly (top 10 by spend, last 30 days)
                cur.execute(
                    """
                    SELECT entity_name,
                           SUM(spend) as total_spend,
                           SUM(revenue) as total_revenue,
                           SUM(clicks) as total_clicks,
                           SUM(impressions) as total_impr,
                           SUM(conversions) as total_conv
                    FROM kpi_hourly
                    WHERE (workspace_id = %s OR workspace_id IS NULL)
                      AND platform = 'meta'
                      AND entity_level = 'campaign'
                      AND recorded_at >= NOW() - INTERVAL '30 days'
                      AND entity_name IS NOT NULL
                    GROUP BY entity_name
                    ORDER BY total_spend DESC
                    LIMIT 10
                    """,
                    (workspace_id,),
                )
                camp_rows = cur.fetchall()
                if camp_rows:
                    camp_lines = []
                    for c in camp_rows:
                        name, spend, rev, clicks, impr, conv = c
                        spend_f = float(spend or 0)
                        rev_f = float(rev or 0)
                        roas_c = round(rev_f / spend_f, 2) if spend_f > 0 else 0
                        ctr_c = round(float(clicks or 0) / float(impr or 1) * 100, 2) if impr else 0
                        camp_lines.append(
                            f"  • {name}: ₹{spend_f:,.0f} spend, ROAS {roas_c}x, "
                            f"CTR {ctr_c}%, {int(conv or 0)} conversions"
                        )
                    ctx_lines.append("Meta campaigns (last 30d by spend):\n" + "\n".join(camp_lines))
    except Exception as e:
        print(f"[chat] Context gathering error (non-fatal): {e}")

    # ── Live Meta fallback: pull directly from Meta API if kpi_hourly had no data ──
    _has_meta_db_data = any("Meta Ads" in l for l in ctx_lines)
    if not _has_meta_db_data:
        try:
            from services.agent_swarm.core.workspace import get_workspace as _gws, get_primary_connection as _gpc
            from services.agent_swarm.connectors.meta import MetaConnector as _MC
            import datetime as _dt2
            _ws_obj = _gws(workspace_id)
            _meta_conn = _gpc(_ws_obj, "meta") if _ws_obj else None
            if _meta_conn:
                _mc = _MC(_meta_conn, _ws_obj)
                _until = _dt2.date.today().isoformat()
                _since = (_dt2.date.today() - _dt2.timedelta(days=30)).isoformat()
                _snaps = _mc.fetch_metrics(_since, _until, entity_level="campaign")
                if _snaps:
                    # Aggregate by campaign name
                    _by_camp: dict = {}
                    for _s in _snaps:
                        _k = _s.entity_name
                        if _k not in _by_camp:
                            _by_camp[_k] = {"spend": 0.0, "revenue": 0.0, "clicks": 0, "impressions": 0, "conversions": 0}
                        _by_camp[_k]["spend"] += _s.spend
                        _by_camp[_k]["revenue"] += _s.revenue
                        _by_camp[_k]["clicks"] += _s.clicks
                        _by_camp[_k]["impressions"] += _s.impressions
                        _by_camp[_k]["conversions"] += _s.conversions
                    _total_spend = sum(v["spend"] for v in _by_camp.values())
                    _total_rev = sum(v["revenue"] for v in _by_camp.values())
                    _total_clicks = sum(v["clicks"] for v in _by_camp.values())
                    _total_impr = sum(v["impressions"] for v in _by_camp.values())
                    _total_conv = sum(v["conversions"] for v in _by_camp.values())
                    if _total_spend > 0:
                        _roas_t = round(_total_rev / _total_spend, 2)
                        _ctr_t = round(_total_clicks / max(_total_impr, 1) * 100, 2)
                        ctx_lines.append(
                            f"Meta Ads (30d total, live from API): Spend ₹{_total_spend:,.0f}, "
                            f"Revenue ₹{_total_rev:,.0f}, ROAS {_roas_t}x, "
                            f"Clicks {_total_clicks:,}, Impressions {_total_impr:,}, "
                            f"CTR {_ctr_t}%, Conversions {_total_conv:,}"
                        )
                    # Top 10 campaigns by spend
                    _sorted = sorted(_by_camp.items(), key=lambda x: x[1]["spend"], reverse=True)[:10]
                    _camp_lines = []
                    for _name, _v in _sorted:
                        _sp = _v["spend"]
                        _rv = _v["revenue"]
                        _rc = round(_rv / _sp, 2) if _sp > 0 else 0
                        _ct = round(_v["clicks"] / max(_v["impressions"], 1) * 100, 2)
                        _camp_lines.append(
                            f"  • {_name}: ₹{_sp:,.0f} spend, ROAS {_rc}x, "
                            f"CTR {_ct}%, {_v['conversions']} conversions"
                        )
                    if _camp_lines:
                        ctx_lines.append("Meta campaigns (last 30d, live from API):\n" + "\n".join(_camp_lines))
                else:
                    # No metrics data — at least list active campaigns
                    _active = _mc.list_campaigns("ACTIVE")
                    if _active:
                        _names = [c.get("name", "Unknown") for c in _active[:10]]
                        ctx_lines.append(f"Meta active campaigns ({len(_active)} total): {', '.join(_names)}")
                    ctx_lines.append("Meta Ads: Account connected but no spend data in last 30 days.")
        except Exception as _e:
            print(f"[chat] Live Meta fallback error (non-fatal): {_e}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:

                # YouTube channel stats
                cur.execute(
                    """
                    SELECT title, subscriber_count, view_count, video_count
                    FROM youtube_channels WHERE workspace_id = %s
                    LIMIT 1
                    """,
                    (workspace_id,),
                )
                yt_row = cur.fetchone()
                if yt_row:
                    ctx_lines.append(
                        f"YouTube: '{yt_row[0]}' — {yt_row[1]:,} subscribers, {yt_row[2]:,} lifetime views, "
                        f"{yt_row[3]} videos"
                    )

                # YouTube last 30d analytics
                cur.execute(
                    """
                    SELECT SUM(views), SUM(watch_time_minutes), SUM(subscribers_gained)
                    FROM youtube_channel_stats
                    WHERE workspace_id = %s AND date >= NOW() - INTERVAL '30 days'
                    """,
                    (workspace_id,),
                )
                yt_stats = cur.fetchone()
                if yt_stats and yt_stats[0]:
                    ctx_lines.append(
                        f"YouTube (30d): {int(yt_stats[0]):,} views, "
                        f"{int((yt_stats[1] or 0)/60):,}h watch time, "
                        f"+{int(yt_stats[2] or 0)} subscribers"
                    )

                # Pending approvals count
                cur.execute(
                    "SELECT COUNT(*) FROM action_log WHERE workspace_id = %s AND status = 'pending'",
                    (workspace_id,),
                )
                pending = cur.fetchone()[0]
                if pending:
                    ctx_lines.append(f"Pending approvals: {pending} actions waiting")

                # Latest Growth OS plan
                cur.execute(
                    """
                    SELECT generated_at FROM growth_os_plans
                    WHERE workspace_id = %s ORDER BY generated_at DESC LIMIT 1
                    """,
                    (workspace_id,),
                )
                gos = cur.fetchone()
                if gos and gos[0]:
                    import datetime as _dt
                    age_h = int((_dt.datetime.utcnow() - gos[0].replace(tzinfo=None)).total_seconds() / 3600)
                    ctx_lines.append(f"Latest Growth OS plan: generated {age_h}h ago")

                # Credit balance (org_id is the FK column on workspaces)
                cur.execute(
                    """
                    SELECT o.credit_balance, o.plan FROM organizations o
                    INNER JOIN workspaces w ON w.org_id = o.id
                    WHERE w.id = %s
                    """,
                    (workspace_id,),
                )
                billing = cur.fetchone()
                if billing:
                    ctx_lines.append(f"Credits remaining: {billing[0]} (plan: {billing[1]})")
    except Exception as e:
        print(f"[chat] Context gathering error (non-fatal): {e}")
        # Continue with whatever context we have — don't fail the whole chat

    context_block = "\n".join(ctx_lines) if ctx_lines else "No workspace data available yet."
    system_prompt = (
        f"You are ARIA, the AI Growth Advisor for Runway Studios — an intelligent marketing OS.\n"
        f"You are having a contextual conversation with the team at **{ws_name}**.\n\n"
        f"## Live Workspace Data (pulled fresh from the database right now)\n{context_block}\n\n"
        f"## Critical Instructions\n"
        f"- The data above is REAL, live data from the workspace's connected ad accounts. Use it directly.\n"
        f"- NEVER say you don't have data or ask the user to share metrics — it's all in the context above.\n"
        f"- NEVER say 'I don't have access to live data' — you do. It's in the Live Workspace Data section.\n"
        f"- If a metric isn't in the data above, say 'I don't see [metric] in the last 30 days' — don't ask them to provide it.\n"
        f"- Be direct, specific, and reference the actual numbers from above.\n"
        f"- Use Indian Rupees (₹) for monetary values.\n"
        f"- Format responses with bold for key numbers, bullet points for lists.\n"
        f"- Keep responses concise and actionable — no filler, no generic advice."
    )

    # Load last 40 messages from DB for full context
    messages = []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content FROM chat_messages
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC LIMIT 40
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
                for role, content in reversed(rows):
                    messages.append({"role": role, "content": content})
    except Exception as e:
        print(f"[chat] Failed to load history: {e}")
    messages.append({"role": "user", "content": user_message})

    import anthropic as _ac
    from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
    try:
        client = _ac.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            system=system_prompt,
            messages=messages,
        )
        reply = resp.content[0].text.strip()
    except Exception as e:
        print(f"[chat] Claude API error: {e}")
        raise HTTPException(status_code=500, detail=f"AI service unavailable: {str(e)[:100]}")

    # Save both messages to chat history
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chat_messages (workspace_id, role, content, credits_used) VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)",
                    (workspace_id, "user", user_message, 0,
                     workspace_id, "assistant", reply, 1),
                )
    except Exception as e:
        print(f"[chat] Failed to save history: {e}")  # non-fatal

    return {"reply": reply, "credits_used": 1}


@app.get("/chat/history")
async def chat_history(request: Request, workspace_id: str = None):
    """Return last 100 chat messages for a workspace."""
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content, created_at
                    FROM chat_messages
                    WHERE workspace_id = %s
                    ORDER BY created_at ASC
                    LIMIT 100
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
        return {"messages": [
            {"role": r[0], "content": r[1], "created_at": r[2].isoformat() if r[2] else None}
            for r in rows
        ]}
    except Exception as e:
        print(f"[chat/history] Error: {e}")
        return {"messages": []}


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
        """CREATE TABLE IF NOT EXISTS shopify_connections (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            shop_domain   TEXT NOT NULL,
            access_token  TEXT NOT NULL,
            scopes        TEXT,
            shop_name     TEXT,
            installed_at  TIMESTAMPTZ DEFAULT NOW(),
            synced_at     TIMESTAMPTZ,
            UNIQUE(workspace_id, shop_domain)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_shopify_workspace ON shopify_connections(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_shopify_domain ON shopify_connections(shop_domain)",
        # shopify_connections.shop_name — add if missing (safe ALTER)
        "ALTER TABLE shopify_connections ADD COLUMN IF NOT EXISTS shop_name TEXT",
        # shopify_connections: rename scope→scopes if old column name exists, else add scopes
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='shopify_connections' AND column_name='scope') THEN
                ALTER TABLE shopify_connections RENAME COLUMN scope TO scopes;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='shopify_connections' AND column_name='scopes') THEN
                ALTER TABLE shopify_connections ADD COLUMN scopes TEXT;
            END IF;
        END $$""",
        # shopify_connections: add installed_at / synced_at if missing from older table schema
        "ALTER TABLE shopify_connections ADD COLUMN IF NOT EXISTS installed_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE shopify_connections ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ",
        # v22 — YouTube comments + like_count on Meta comment_replies
        """CREATE TABLE IF NOT EXISTS youtube_comments (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            video_id        TEXT NOT NULL,
            video_title     TEXT,
            comment_id      TEXT NOT NULL,
            author_name     TEXT,
            comment_text    TEXT NOT NULL,
            like_count      INT  NOT NULL DEFAULT 0,
            reply_count     INT  NOT NULL DEFAULT 0,
            published_at    TIMESTAMPTZ,
            category        TEXT,
            sentiment       TEXT,
            suggested_reply TEXT,
            status          TEXT NOT NULL DEFAULT 'pending',
            classified_at   TIMESTAMPTZ,
            first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_yt_comments_uniq ON youtube_comments(workspace_id, comment_id)",
        "CREATE INDEX IF NOT EXISTS idx_yt_comments_ws ON youtube_comments(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_yt_comments_video ON youtube_comments(video_id)",
        "ALTER TABLE comment_replies ADD COLUMN IF NOT EXISTS like_count INT NOT NULL DEFAULT 0",
        # v22b — YouTube Shorts detection + growth plan history
        "ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS is_short BOOLEAN NOT NULL DEFAULT FALSE",
        """CREATE TABLE IF NOT EXISTS youtube_growth_plans (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            steps         JSONB NOT NULL,
            subs_at_time  INT,
            views_at_time BIGINT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_yt_growth_plans_ws ON youtube_growth_plans(workspace_id, created_at DESC)",
        "ALTER TABLE youtube_growth_actions ADD COLUMN IF NOT EXISTS plan_id UUID REFERENCES youtube_growth_plans(id)",
        # v23 — YouTube Competitor Intelligence (9-layer engine)
        """CREATE TABLE IF NOT EXISTS yt_competitor_channels (
            workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            channel_id       TEXT NOT NULL,
            channel_title    TEXT NOT NULL DEFAULT '',
            channel_handle   TEXT,
            subscriber_count BIGINT,
            similarity_score NUMERIC(6,4) NOT NULL DEFAULT 0,
            rank             INT NOT NULL DEFAULT 0,
            source           TEXT NOT NULL DEFAULT 'auto',
            discovered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_analyzed_at TIMESTAMPTZ,
            PRIMARY KEY (workspace_id, channel_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ytcc_ws ON yt_competitor_channels(workspace_id, rank)",
        """CREATE TABLE IF NOT EXISTS yt_competitor_videos (
            video_id         TEXT PRIMARY KEY,
            channel_id       TEXT NOT NULL,
            workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            title            TEXT NOT NULL DEFAULT '',
            description      TEXT,
            thumbnail_url    TEXT,
            published_at     TIMESTAMPTZ,
            duration_seconds INT NOT NULL DEFAULT 0,
            views            BIGINT NOT NULL DEFAULT 0,
            likes            BIGINT NOT NULL DEFAULT 0,
            comments         BIGINT NOT NULL DEFAULT 0,
            fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ytcv_ws_ch ON yt_competitor_videos(workspace_id, channel_id, published_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_ytcv_ch ON yt_competitor_videos(channel_id)",
        """CREATE TABLE IF NOT EXISTS yt_video_features (
            video_id          TEXT PRIMARY KEY REFERENCES yt_competitor_videos(video_id) ON DELETE CASCADE,
            workspace_id      UUID NOT NULL,
            channel_id        TEXT NOT NULL,
            age_days          INT NOT NULL DEFAULT 0,
            velocity          NUMERIC(12,4) NOT NULL DEFAULT 0,
            engagement_rate   NUMERIC(8,6) NOT NULL DEFAULT 0,
            comment_density   NUMERIC(8,6) NOT NULL DEFAULT 0,
            upload_gap_days   NUMERIC(8,2),
            duration_bucket   TEXT NOT NULL DEFAULT 'medium',
            is_breakout       BOOLEAN NOT NULL DEFAULT FALSE,
            computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ytvf_ws ON yt_video_features(workspace_id, channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_ytvf_breakout ON yt_video_features(workspace_id, is_breakout)",
        """CREATE TABLE IF NOT EXISTS yt_ai_features (
            video_id           TEXT PRIMARY KEY REFERENCES yt_competitor_videos(video_id) ON DELETE CASCADE,
            workspace_id       UUID NOT NULL,
            topic_cluster_id   INT,
            format_label       TEXT,
            format_structure   JSONB,
            format_energy      TEXT,
            title_patterns     JSONB,
            curiosity_score    INT,
            specificity_score  INT,
            thumb_face         BOOLEAN,
            thumb_text         BOOLEAN,
            thumb_emotion      TEXT,
            thumb_objects      JSONB,
            thumb_style        TEXT,
            thumb_readable_text TEXT,
            embedding_json     JSONB,
            labeled_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ytaif_ws ON yt_ai_features(workspace_id, topic_cluster_id)",
        "CREATE INDEX IF NOT EXISTS idx_ytaif_format ON yt_ai_features(workspace_id, format_label)",
        """CREATE TABLE IF NOT EXISTS yt_topic_clusters (
            id               BIGSERIAL PRIMARY KEY,
            workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            channel_id       TEXT NOT NULL,
            topic_cluster_id INT NOT NULL,
            topic_name       TEXT NOT NULL DEFAULT 'Uncategorized',
            subthemes        JSONB NOT NULL DEFAULT '[]',
            cluster_size     INT NOT NULL DEFAULT 0,
            avg_velocity     NUMERIC(12,4) NOT NULL DEFAULT 0,
            median_velocity  NUMERIC(12,4) NOT NULL DEFAULT 0,
            hit_rate         NUMERIC(5,2) NOT NULL DEFAULT 0,
            trs_score        INT NOT NULL DEFAULT 0,
            shelf_life       TEXT,
            half_life_weeks  INT,
            computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(workspace_id, channel_id, topic_cluster_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_yttc_ws ON yt_topic_clusters(workspace_id, avg_velocity DESC)",
        """CREATE TABLE IF NOT EXISTS yt_channel_profiles (
            workspace_id      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            channel_id        TEXT NOT NULL,
            median_velocity   NUMERIC(12,4) NOT NULL DEFAULT 0,
            p25_velocity      NUMERIC(12,4) NOT NULL DEFAULT 0,
            p75_velocity      NUMERIC(12,4) NOT NULL DEFAULT 0,
            p90_velocity      NUMERIC(12,4) NOT NULL DEFAULT 0,
            iqr               NUMERIC(12,4) NOT NULL DEFAULT 0,
            std_velocity      NUMERIC(12,4) NOT NULL DEFAULT 0,
            hit_rate          NUMERIC(5,2) NOT NULL DEFAULT 0,
            underperform_rate NUMERIC(5,2) NOT NULL DEFAULT 0,
            breakout_rate     NUMERIC(5,2) NOT NULL DEFAULT 0,
            risk_profile      TEXT NOT NULL DEFAULT 'medium_variance',
            cadence_pattern   TEXT,
            median_gap_days   NUMERIC(8,2),
            analyzed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(workspace_id, channel_id)
        )""",
        """CREATE TABLE IF NOT EXISTS yt_breakout_recipe (
            workspace_id   UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
            playbook_text  TEXT NOT NULL,
            top_features   JSONB NOT NULL DEFAULT '{}',
            p90_threshold  NUMERIC(12,4) NOT NULL DEFAULT 0,
            breakout_count INT NOT NULL DEFAULT 0,
            trained_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS yt_analysis_jobs (
            id                BIGSERIAL PRIMARY KEY,
            workspace_id      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            status            TEXT NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending','running','completed','failed')),
            started_at        TIMESTAMPTZ,
            completed_at      TIMESTAMPTZ,
            error             TEXT,
            channels_analyzed INT NOT NULL DEFAULT 0,
            videos_analyzed   INT NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_ytaj_ws ON yt_analysis_jobs(workspace_id, created_at DESC)",
        # v24 — Own-channel comparison + workspace-type-aware growth recipe
        "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS workspace_type TEXT DEFAULT 'd2c' CHECK (workspace_type IN ('d2c','creator','saas','agency','media'))",
        "ALTER TABLE yt_analysis_jobs ADD COLUMN IF NOT EXISTS phase TEXT DEFAULT 'competitor_analysis'",
        "ALTER TABLE yt_analysis_jobs ADD COLUMN IF NOT EXISTS channels_total INT NOT NULL DEFAULT 0",
        "ALTER TABLE yt_growth_recipe ADD COLUMN IF NOT EXISTS recipe_text TEXT",
        # v25 — Live discovery stream + confirmation step
        "ALTER TABLE yt_analysis_jobs ADD COLUMN IF NOT EXISTS discovery_log JSONB",
        "ALTER TABLE yt_analysis_jobs ADD COLUMN IF NOT EXISTS discovery_candidates JSONB",
        "ALTER TABLE yt_analysis_jobs ADD COLUMN IF NOT EXISTS own_topic_space JSONB",
        "ALTER TABLE yt_analysis_jobs ADD COLUMN IF NOT EXISTS discovery_status TEXT DEFAULT 'idle'",
        "ALTER TABLE yt_competitor_channels ADD COLUMN IF NOT EXISTS topic_space JSONB",
        """CREATE TABLE IF NOT EXISTS yt_own_channel_snapshot (
            workspace_id      UUID          NOT NULL,
            channel_id        TEXT          NOT NULL,
            video_id          TEXT          NOT NULL,
            title             TEXT,
            published_at      TIMESTAMPTZ,
            views             BIGINT        DEFAULT 0,
            likes             INT           DEFAULT 0,
            comments          INT           DEFAULT 0,
            duration_seconds  INT           DEFAULT 0,
            is_short          BOOL          DEFAULT FALSE,
            velocity          NUMERIC(12,4),
            engagement_rate   NUMERIC(8,4),
            format_label      TEXT,
            title_patterns    JSONB,
            thumb_face        BOOL,
            thumb_emotion     TEXT,
            thumb_text        BOOL,
            analyzed_at       TIMESTAMPTZ   DEFAULT NOW(),
            PRIMARY KEY (workspace_id, video_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_yt_own_snap_ws ON yt_own_channel_snapshot(workspace_id)",
        """CREATE TABLE IF NOT EXISTS yt_growth_recipe (
            workspace_id             UUID          PRIMARY KEY,
            own_video_count          INT           DEFAULT 0,
            own_velocity_avg         NUMERIC(12,4) DEFAULT 0,
            own_velocity_percentile  NUMERIC(5,2)  DEFAULT 0,
            content_gaps             JSONB,
            plan_15d                 TEXT,
            plan_30d                 TEXT,
            thumbnail_brief          TEXT,
            hooks_library            TEXT,
            emerging_topics          TEXT,
            generated_at             TIMESTAMPTZ   DEFAULT NOW()
        )""",
        # v26 — Growth OS unified action plan
        """CREATE TABLE IF NOT EXISTS growth_os_plans (
            id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
            workspace_id  UUID        REFERENCES workspaces(id),
            generated_at  TIMESTAMPTZ DEFAULT NOW(),
            plan_json     JSONB       NOT NULL,
            sources_used  JSONB
        )""",
        "CREATE INDEX IF NOT EXISTS idx_gos_ws ON growth_os_plans(workspace_id, generated_at DESC)",
        # v27 — Meta Ad Library competitor ads
        """CREATE TABLE IF NOT EXISTS meta_competitor_ads (
            id                   UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
            workspace_id         UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            competitor_page_id   TEXT        NOT NULL DEFAULT '',
            competitor_page_name TEXT        NOT NULL,
            ad_id                TEXT        NOT NULL,
            ad_copy              TEXT,
            headline             TEXT,
            snapshot_url         TEXT,
            media_type           TEXT,
            platforms            JSONB       DEFAULT '[]',
            delivery_start_date  DATE,
            last_fetched_at      TIMESTAMPTZ DEFAULT NOW(),
            is_active            BOOLEAN     DEFAULT TRUE,
            raw_json             JSONB,
            UNIQUE (workspace_id, ad_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_mca_ws ON meta_competitor_ads(workspace_id, competitor_page_name, delivery_start_date DESC)",
        # v27b — Meta Ad Library manual competitor pages
        """CREATE TABLE IF NOT EXISTS meta_competitor_pages (
            id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
            workspace_id UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            page_name    TEXT        NOT NULL,
            added_at     TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (workspace_id, page_name)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_mcp_ws ON meta_competitor_pages(workspace_id)",
        # v28 — Onboarding flow: track user type and selected channels
        "ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS onboarding_channels JSONB DEFAULT '[]'",
        # v29 — Credit-based billing system
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS credit_balance INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'free'",
        # v30 — Per-user workspace isolation
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS clerk_user_id TEXT",
        "CREATE INDEX IF NOT EXISTS idx_orgs_clerk_user ON organizations(clerk_user_id)",
        """CREATE TABLE IF NOT EXISTS credit_ledger (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id               UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id         UUID        REFERENCES workspaces(id) ON DELETE SET NULL,
            amount               INTEGER     NOT NULL,
            balance_after        INTEGER     NOT NULL,
            type                 TEXT        NOT NULL,
            feature              TEXT,
            razorpay_payment_id  TEXT,
            description          TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_credit_ledger_org  ON credit_ledger(org_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_credit_ledger_ws   ON credit_ledger(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_credit_ledger_type ON credit_ledger(type)",
        """CREATE TABLE IF NOT EXISTS billing_orders (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id               UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            razorpay_order_id    TEXT        UNIQUE NOT NULL,
            type                 TEXT        NOT NULL DEFAULT 'topup',
            credits              INTEGER     NOT NULL DEFAULT 0,
            amount_paise         INTEGER     NOT NULL,
            status               TEXT        NOT NULL DEFAULT 'pending',
            razorpay_payment_id  TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_billing_orders_org ON billing_orders(org_id)",
        "CREATE INDEX IF NOT EXISTS idx_billing_orders_rzp ON billing_orders(razorpay_order_id)",
        # v31 — Meta OAuth pending sessions (multi-account selection after OAuth)
        """CREATE TABLE IF NOT EXISTS meta_oauth_sessions (
            id           TEXT        PRIMARY KEY,
            workspace_id UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id      TEXT        NOT NULL DEFAULT '',
            user_name    TEXT,
            access_token TEXT        NOT NULL,
            ad_accounts  JSONB       NOT NULL DEFAULT '[]',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_meta_oauth_sessions_ws ON meta_oauth_sessions(workspace_id)",

        # ── v31 Email Marketing ──────────────────────────────────────────────
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email_plan TEXT NOT NULL DEFAULT 'none'",
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS monthly_emails_sent INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS email_month_reset DATE",
        """CREATE TABLE IF NOT EXISTS email_domains (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            domain           TEXT        NOT NULL,
            resend_domain_id TEXT,
            dns_records      JSONB       NOT NULL DEFAULT '[]',
            verified         BOOLEAN     NOT NULL DEFAULT FALSE,
            status           TEXT        NOT NULL DEFAULT 'pending',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, domain)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_email_domains_ws ON email_domains(workspace_id)",
        """CREATE TABLE IF NOT EXISTS email_lists (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id   UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name           TEXT        NOT NULL,
            description    TEXT,
            source         TEXT        NOT NULL DEFAULT 'manual',
            contact_count  INTEGER     NOT NULL DEFAULT 0,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_email_lists_ws ON email_lists(workspace_id)",
        """CREATE TABLE IF NOT EXISTS email_contacts (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id        UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            list_id             UUID        NOT NULL REFERENCES email_lists(id) ON DELETE CASCADE,
            email               TEXT        NOT NULL,
            first_name          TEXT,
            last_name           TEXT,
            tags                JSONB       NOT NULL DEFAULT '[]',
            custom_fields       JSONB       NOT NULL DEFAULT '{}',
            source              TEXT        NOT NULL DEFAULT 'manual',
            unsubscribed        BOOLEAN     NOT NULL DEFAULT FALSE,
            unsubscribed_at     TIMESTAMPTZ,
            unsubscribe_token   TEXT        UNIQUE NOT NULL,
            bounced             BOOLEAN     NOT NULL DEFAULT FALSE,
            bounce_type         TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workspace_id, list_id, email)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_email_contacts_ws    ON email_contacts(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_email_contacts_list  ON email_contacts(list_id)",
        "CREATE INDEX IF NOT EXISTS idx_email_contacts_token ON email_contacts(unsubscribe_token)",
        """CREATE TABLE IF NOT EXISTS email_campaigns (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id      UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            list_id           UUID        REFERENCES email_lists(id) ON DELETE SET NULL,
            domain_id         UUID        REFERENCES email_domains(id) ON DELETE SET NULL,
            name              TEXT        NOT NULL,
            subject           TEXT        NOT NULL,
            from_name         TEXT        NOT NULL,
            from_email        TEXT        NOT NULL,
            reply_to          TEXT,
            html_body         TEXT        NOT NULL,
            text_body         TEXT,
            status            TEXT        NOT NULL DEFAULT 'draft',
            scheduled_at      TIMESTAMPTZ,
            sent_at           TIMESTAMPTZ,
            total_recipients  INTEGER     NOT NULL DEFAULT 0,
            sent_count        INTEGER     NOT NULL DEFAULT 0,
            failed_count      INTEGER     NOT NULL DEFAULT 0,
            open_count        INTEGER     NOT NULL DEFAULT 0,
            click_count       INTEGER     NOT NULL DEFAULT 0,
            bounce_count      INTEGER     NOT NULL DEFAULT 0,
            unsub_count       INTEGER     NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_email_campaigns_ws ON email_campaigns(workspace_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_email_campaigns_st ON email_campaigns(status)",
        """CREATE TABLE IF NOT EXISTS email_events (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id      UUID        REFERENCES workspaces(id) ON DELETE CASCADE,
            campaign_id       UUID        REFERENCES email_campaigns(id) ON DELETE CASCADE,
            contact_id        UUID        REFERENCES email_contacts(id) ON DELETE SET NULL,
            resend_message_id TEXT,
            event_type        TEXT        NOT NULL,
            event_data        JSONB       NOT NULL DEFAULT '{}',
            occurred_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_email_events_campaign ON email_events(campaign_id, occurred_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_email_events_resend   ON email_events(resend_message_id)",
        """CREATE TABLE IF NOT EXISTS email_send_log (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id       UUID        NOT NULL REFERENCES email_campaigns(id) ON DELETE CASCADE,
            contact_id        UUID        NOT NULL REFERENCES email_contacts(id) ON DELETE CASCADE,
            resend_message_id TEXT,
            status            TEXT        NOT NULL DEFAULT 'pending',
            error             TEXT,
            sent_at           TIMESTAMPTZ,
            UNIQUE (campaign_id, contact_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_email_send_log_campaign ON email_send_log(campaign_id)",
        "CREATE INDEX IF NOT EXISTS idx_email_send_log_resend   ON email_send_log(resend_message_id)",

        # v32 — ARIA persistent chat history
        """CREATE TABLE IF NOT EXISTS chat_messages (
            id           BIGSERIAL   PRIMARY KEY,
            workspace_id UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            role         TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),
            content      TEXT        NOT NULL,
            credits_used INT         NOT NULL DEFAULT 0,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_ws ON chat_messages(workspace_id, created_at ASC)",

        # v33 — Products page (is_competitor, product_type, competitor_insights)
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_competitor BOOLEAN DEFAULT false",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS product_type TEXT DEFAULT 'product'",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS competitor_insights TEXT",

        # v34 — SEO / Google Search Console
        "ALTER TABLE google_auth_tokens ADD COLUMN IF NOT EXISTS gsc_site_url TEXT",

        # v35 SEO tables
        "CREATE TABLE IF NOT EXISTS seo_backlinks (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id UUID NOT NULL, source_url TEXT NOT NULL, source_domain TEXT DEFAULT '', target_url TEXT DEFAULT '', anchor_text TEXT DEFAULT '', status TEXT DEFAULT 'prospect', domain_authority INTEGER, notes TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())",
        "CREATE INDEX IF NOT EXISTS idx_seo_backlinks_ws ON seo_backlinks(workspace_id)",
        "CREATE TABLE IF NOT EXISTS seo_offpage_plans (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id UUID NOT NULL, plan JSONB NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())",
        "CREATE INDEX IF NOT EXISTS idx_seo_offpage_ws ON seo_offpage_plans(workspace_id)",
        # v36 App Growth tables
        """CREATE TABLE IF NOT EXISTS app_profiles (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            app_name         TEXT        NOT NULL DEFAULT '',
            bundle_id        TEXT        DEFAULT '',
            app_store_url    TEXT        DEFAULT '',
            play_store_url   TEXT        DEFAULT '',
            app_store_id     TEXT        DEFAULT '',
            play_package     TEXT        DEFAULT '',
            asc_key_id       TEXT        DEFAULT '',
            asc_issuer_id    TEXT        DEFAULT '',
            asc_private_key  TEXT        DEFAULT '',
            play_service_account JSONB,
            category         TEXT        DEFAULT '',
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            updated_at       TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(workspace_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_app_profiles_ws ON app_profiles(workspace_id)",
        """CREATE TABLE IF NOT EXISTS app_reviews (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            store            TEXT        NOT NULL CHECK (store IN ('appstore','playstore')),
            review_id        TEXT        NOT NULL,
            author           TEXT        DEFAULT '',
            rating           INT         NOT NULL DEFAULT 5,
            title            TEXT        DEFAULT '',
            body             TEXT        NOT NULL DEFAULT '',
            version          TEXT        DEFAULT '',
            sentiment        TEXT        DEFAULT '',
            category         TEXT        DEFAULT '',
            suggested_reply  TEXT        DEFAULT '',
            replied          BOOLEAN     NOT NULL DEFAULT FALSE,
            replied_at       TIMESTAMPTZ,
            review_date      TIMESTAMPTZ,
            fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(workspace_id, store, review_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_app_reviews_ws ON app_reviews(workspace_id, rating, review_date DESC)",
        """CREATE TABLE IF NOT EXISTS app_aso_keywords (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            keyword          TEXT        NOT NULL,
            store            TEXT        NOT NULL DEFAULT 'both',
            appstore_rank    INT,
            playstore_rank   INT,
            search_score     INT,
            notes            TEXT        DEFAULT '',
            added_at         TIMESTAMPTZ DEFAULT NOW(),
            checked_at       TIMESTAMPTZ,
            UNIQUE(workspace_id, keyword)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_aso_kw_ws ON app_aso_keywords(workspace_id)",
        """CREATE TABLE IF NOT EXISTS app_install_events (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            source           TEXT        NOT NULL DEFAULT 'organic',
            channel          TEXT        DEFAULT '',
            campaign_name    TEXT        DEFAULT '',
            campaign_id      TEXT        DEFAULT '',
            adset_name       TEXT        DEFAULT '',
            country          TEXT        DEFAULT '',
            platform         TEXT        DEFAULT '',
            installs         INT         NOT NULL DEFAULT 1,
            cost             NUMERIC(12,4) DEFAULT 0,
            event_date       DATE        NOT NULL DEFAULT CURRENT_DATE,
            raw_json         JSONB       DEFAULT '{}',
            received_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_app_installs_ws ON app_install_events(workspace_id, event_date DESC)",
        """CREATE TABLE IF NOT EXISTS app_growth_plans (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id     UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            plan_json        JSONB       NOT NULL,
            generated_at     TIMESTAMPTZ DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_app_gp_ws ON app_growth_plans(workspace_id, generated_at DESC)",
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


# ═══════════════════════════════════════════════════════════════════════════════
# APP GROWTH MODULE
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/app-growth/connect")
async def app_growth_connect(request: Request):
    """Save or update app profile + store credentials."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    fields = ["app_name","bundle_id","app_store_url","play_store_url",
              "app_store_id","play_package","asc_key_id","asc_issuer_id",
              "asc_private_key","category"]
    vals = {f: body.get(f, "") for f in fields}
    play_sa = body.get("play_service_account")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_profiles (workspace_id, app_name, bundle_id, app_store_url,
                    play_store_url, app_store_id, play_package, asc_key_id, asc_issuer_id,
                    asc_private_key, play_service_account, category)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (workspace_id) DO UPDATE SET
                    app_name=EXCLUDED.app_name, bundle_id=EXCLUDED.bundle_id,
                    app_store_url=EXCLUDED.app_store_url, play_store_url=EXCLUDED.play_store_url,
                    app_store_id=EXCLUDED.app_store_id, play_package=EXCLUDED.play_package,
                    asc_key_id=EXCLUDED.asc_key_id, asc_issuer_id=EXCLUDED.asc_issuer_id,
                    asc_private_key=EXCLUDED.asc_private_key,
                    play_service_account=EXCLUDED.play_service_account,
                    category=EXCLUDED.category, updated_at=NOW()
            """, (workspace_id, vals["app_name"], vals["bundle_id"], vals["app_store_url"],
                  vals["play_store_url"], vals["app_store_id"], vals["play_package"],
                  vals["asc_key_id"], vals["asc_issuer_id"], vals["asc_private_key"],
                  json.dumps(play_sa) if play_sa else None, vals["category"]))
    return {"ok": True}


@app.get("/app-growth/status")
async def app_growth_status(request: Request, workspace_id: str = None):
    """Return app profile + connection health."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT app_name, bundle_id, app_store_url, play_store_url,
                app_store_id, play_package, asc_key_id, asc_issuer_id, category, created_at
                FROM app_profiles WHERE workspace_id=%s""", (workspace_id,))
            row = cur.fetchone()
            # counts
            cur.execute("SELECT COUNT(*) FROM app_reviews WHERE workspace_id=%s", (workspace_id,))
            review_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM app_aso_keywords WHERE workspace_id=%s", (workspace_id,))
            kw_count = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(installs),0) FROM app_install_events WHERE workspace_id=%s AND event_date >= NOW()-INTERVAL '30 days'", (workspace_id,))
            installs_30d = cur.fetchone()[0]
    if not row:
        return {"connected": False, "review_count": 0, "kw_count": 0, "installs_30d": 0}
    return {
        "connected": True,
        "app_name": row[0], "bundle_id": row[1],
        "app_store_url": row[2], "play_store_url": row[3],
        "app_store_id": row[4], "play_package": row[5],
        "has_asc": bool(row[6] and row[7]),
        "has_play": False,
        "category": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
        "review_count": review_count,
        "kw_count": kw_count,
        "installs_30d": int(installs_30d),
    }


@app.get("/app-growth/reviews")
async def app_growth_reviews(request: Request, workspace_id: str = None,
                              store: str = "all", sentiment: str = "all",
                              rating: int = 0, limit: int = 50):
    """Return stored app reviews with filters."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    conditions = ["workspace_id=%s"]
    params: list = [workspace_id]
    if store != "all":
        conditions.append("store=%s"); params.append(store)
    if sentiment != "all":
        conditions.append("sentiment=%s"); params.append(sentiment)
    if rating > 0:
        conditions.append("rating=%s"); params.append(rating)
    where = " AND ".join(conditions)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT id, store, review_id, author, rating, title, body,
                version, sentiment, category, suggested_reply, replied, review_date
                FROM app_reviews WHERE {where} ORDER BY review_date DESC LIMIT %s""",
                params + [limit])
            rows = cur.fetchall()
            # rating distribution
            cur.execute("SELECT rating, COUNT(*) FROM app_reviews WHERE workspace_id=%s GROUP BY rating ORDER BY rating DESC", (workspace_id,))
            dist = {str(r[0]): r[1] for r in cur.fetchall()}
            cur.execute("SELECT ROUND(AVG(rating)::numeric,1) FROM app_reviews WHERE workspace_id=%s", (workspace_id,))
            avg_r = cur.fetchone()[0]
    reviews = [
        {"id": str(r[0]), "store": r[1], "review_id": r[2], "author": r[3],
         "rating": r[4], "title": r[5], "body": r[6], "version": r[7],
         "sentiment": r[8], "category": r[9], "suggested_reply": r[10],
         "replied": bool(r[11]),
         "review_date": r[12].isoformat() if r[12] else None}
        for r in rows
    ]
    return {"reviews": reviews, "rating_distribution": dist,
            "avg_rating": float(avg_r) if avg_r else None, "total": len(reviews)}


@app.post("/app-growth/reviews/add")
async def app_growth_reviews_add(request: Request):
    """Manually add a review (or batch import). Also AI-classifies it."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    reviews_in = body.get("reviews", [body])  # single or batch
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    added = 0
    for rv in reviews_in:
        body_text = rv.get("body", "")
        rating = int(rv.get("rating", 5))
        # AI classify
        sentiment, category, suggested_reply = "neutral", "general", ""
        try:
            msg = anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system='Respond ONLY with valid JSON. No explanation.',
                messages=[{"role":"user","content":
                    f'Review (rating {rating}/5): "{body_text[:400]}"\n'
                    'Return: {"sentiment":"positive|negative|neutral","category":"bug_report|feature_request|praise|complaint|general","suggested_reply":"<short friendly reply under 100 words>"}'}]
            )
            parsed = json.loads(msg.content[0].text.strip())
            sentiment = parsed.get("sentiment", sentiment)
            category = parsed.get("category", category)
            suggested_reply = parsed.get("suggested_reply", "")
        except Exception:
            if rating <= 2: sentiment = "negative"
            elif rating >= 4: sentiment = "positive"

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO app_reviews (workspace_id, store, review_id, author, rating,
                        title, body, version, sentiment, category, suggested_reply, review_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (workspace_id, store, review_id) DO NOTHING
                """, (workspace_id, rv.get("store","appstore"),
                      rv.get("review_id", str(uuid.uuid4())),
                      rv.get("author","Anonymous"), rating,
                      rv.get("title",""), body_text,
                      rv.get("version",""), sentiment, category, suggested_reply,
                      rv.get("review_date")))
                added += cur.rowcount
    return {"ok": True, "added": added}


@app.patch("/app-growth/reviews/{review_id}/reply")
async def app_growth_review_reply(review_id: str, request: Request):
    """Mark review as replied."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE app_reviews SET replied=true, replied_at=NOW() WHERE id=%s AND workspace_id=%s",
                        (review_id, workspace_id))
    return {"ok": True}


# ── ASO Keywords ──────────────────────────────────────────────────────────────

@app.get("/app-growth/aso/keywords")
async def aso_keywords_list(request: Request, workspace_id: str = None):
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, keyword, store, appstore_rank, playstore_rank,
                search_score, notes, added_at, checked_at
                FROM app_aso_keywords WHERE workspace_id=%s ORDER BY added_at DESC""", (workspace_id,))
            rows = cur.fetchall()
    return {"keywords": [
        {"id": str(r[0]), "keyword": r[1], "store": r[2],
         "appstore_rank": r[3], "playstore_rank": r[4],
         "search_score": r[5], "notes": r[6],
         "added_at": r[7].isoformat() if r[7] else None,
         "checked_at": r[8].isoformat() if r[8] else None}
        for r in rows
    ]}


@app.post("/app-growth/aso/keywords/add")
async def aso_keywords_add(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    keyword = (body.get("keyword") or "").strip()
    if not workspace_id or not keyword:
        raise HTTPException(status_code=400, detail="workspace_id and keyword required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO app_aso_keywords (workspace_id, keyword, store, notes)
                VALUES (%s,%s,%s,%s) ON CONFLICT (workspace_id, keyword) DO NOTHING""",
                (workspace_id, keyword, body.get("store","both"), body.get("notes","")))
    return {"ok": True}


@app.delete("/app-growth/aso/keywords/{kw_id}")
async def aso_keywords_delete(kw_id: str, request: Request):
    _auth(request)
    ws = request.query_params.get("workspace_id","")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM app_aso_keywords WHERE id=%s AND workspace_id=%s", (kw_id, ws))
    return {"ok": True}


@app.post("/app-growth/aso/analyze")
async def aso_analyze(request: Request):
    """Claude scores and rewrites ASO metadata."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    app_name = body.get("app_name", "")
    subtitle = body.get("subtitle", "")
    description = body.get("description", "")
    keywords_field = body.get("keywords_field", "")
    category = body.get("category", "")
    store = body.get("store", "appstore")

    prompt = f"""You are an expert App Store Optimization (ASO) consultant.

App: {app_name}
Store: {store}
Category: {category}
Current Subtitle/Short Description: {subtitle}
Current Description (first 500 chars): {description[:500]}
Current Keywords Field: {keywords_field}

Analyze and return JSON:
{{
  "score": <0-100 overall ASO score>,
  "issues": [
    {{"field": "title|subtitle|description|keywords", "severity": "high|medium|low",
      "issue": "...", "fix": "..."}}
  ],
  "optimized_subtitle": "<improved subtitle max 30 chars>",
  "optimized_keywords": "<comma-separated keywords max 100 chars total, no spaces after commas>",
  "optimized_description_opening": "<first 3 sentences of description — most important for conversion>",
  "top_keywords_to_target": ["kw1","kw2","kw3","kw4","kw5"],
  "competitor_gap": "<what keywords competitors likely rank for that you're missing>"
}}"""

    try:
        msg = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            system='Respond ONLY with valid JSON.',
            messages=[{"role":"user","content":prompt}]
        )
        result = json.loads(msg.content[0].text.strip())
    except Exception as e:
        result = {"score": 0, "issues": [], "error": str(e)}
    return result


# ── Install Attribution ───────────────────────────────────────────────────────

@app.post("/app-growth/attribution/webhook")
async def app_growth_attribution_webhook(request: Request):
    """
    AppsFlyer / Adjust / Branch webhook receiver.
    No auth — receives postbacks. Workspace resolved via query param or body.
    """
    workspace_id = request.query_params.get("workspace_id", "")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not workspace_id:
        workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        return {"ok": False, "error": "workspace_id required as query param"}

    # Normalise fields from AppsFlyer / Adjust / Branch formats
    source = body.get("media_source") or body.get("network") or body.get("channel") or "organic"
    campaign = body.get("campaign") or body.get("campaign_name") or ""
    campaign_id = body.get("campaign_id") or ""
    adset = body.get("adset") or body.get("adgroup") or ""
    country = body.get("country_code") or body.get("country") or ""
    platform = body.get("platform") or body.get("os") or ""
    cost = float(body.get("cost") or body.get("cost_usd") or 0)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO app_install_events
                (workspace_id, source, channel, campaign_name, campaign_id,
                 adset_name, country, platform, installs, cost, raw_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s::jsonb)""",
                (workspace_id, source, source, campaign, campaign_id,
                 adset, country, platform, cost, json.dumps(body)))
    return {"ok": True}


@app.get("/app-growth/attribution/funnel")
async def app_growth_attribution_funnel(request: Request, workspace_id: str = None, days: int = 30):
    """Return install funnel: by source, by campaign, by country, by platform."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            # by source
            cur.execute("""SELECT source, SUM(installs) as installs, SUM(cost) as spend
                FROM app_install_events WHERE workspace_id=%s AND event_date >= NOW()-%s::INTERVAL
                GROUP BY source ORDER BY installs DESC""",
                (workspace_id, f"{days} days"))
            by_source = [{"source": r[0], "installs": int(r[1]), "spend": float(r[2] or 0),
                          "cpi": round(float(r[2] or 0)/max(int(r[1]),1),2)} for r in cur.fetchall()]

            # by campaign
            cur.execute("""SELECT campaign_name, source, SUM(installs) as installs, SUM(cost) as spend
                FROM app_install_events WHERE workspace_id=%s AND event_date >= NOW()-%s::INTERVAL
                AND campaign_name != '' GROUP BY campaign_name, source ORDER BY installs DESC LIMIT 20""",
                (workspace_id, f"{days} days"))
            by_campaign = [{"campaign": r[0], "source": r[1], "installs": int(r[2]),
                            "spend": float(r[3] or 0),
                            "cpi": round(float(r[3] or 0)/max(int(r[2]),1),2)} for r in cur.fetchall()]

            # by country
            cur.execute("""SELECT country, SUM(installs) FROM app_install_events
                WHERE workspace_id=%s AND event_date >= NOW()-%s::INTERVAL AND country != ''
                GROUP BY country ORDER BY SUM(installs) DESC LIMIT 15""",
                (workspace_id, f"{days} days"))
            by_country = [{"country": r[0], "installs": int(r[1])} for r in cur.fetchall()]

            # by platform
            cur.execute("""SELECT platform, SUM(installs) FROM app_install_events
                WHERE workspace_id=%s AND event_date >= NOW()-%s::INTERVAL AND platform != ''
                GROUP BY platform ORDER BY SUM(installs) DESC""",
                (workspace_id, f"{days} days"))
            by_platform = [{"platform": r[0], "installs": int(r[1])} for r in cur.fetchall()]

            # daily trend
            cur.execute("""SELECT event_date, SUM(installs) FROM app_install_events
                WHERE workspace_id=%s AND event_date >= NOW()-%s::INTERVAL
                GROUP BY event_date ORDER BY event_date""",
                (workspace_id, f"{days} days"))
            daily = [{"date": r[0].isoformat(), "installs": int(r[1])} for r in cur.fetchall()]

            # totals
            cur.execute("""SELECT COALESCE(SUM(installs),0), COALESCE(SUM(cost),0)
                FROM app_install_events WHERE workspace_id=%s AND event_date >= NOW()-%s::INTERVAL""",
                (workspace_id, f"{days} days"))
            totals = cur.fetchone()

    total_installs = int(totals[0])
    total_spend = float(totals[1])
    return {
        "total_installs": total_installs,
        "total_spend": total_spend,
        "cpi": round(total_spend / max(total_installs, 1), 2),
        "by_source": by_source,
        "by_campaign": by_campaign,
        "by_country": by_country,
        "by_platform": by_platform,
        "daily": daily,
        "days": days,
    }


# ── App Growth Plan (AI) ──────────────────────────────────────────────────────

@app.post("/app-growth/growth-plan")
async def app_growth_plan_generate(request: Request):
    """Generate AI cross-channel app growth strategy."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    # Gather signals
    signals: dict = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            # app profile
            cur.execute("SELECT app_name, category, app_store_url, play_store_url FROM app_profiles WHERE workspace_id=%s", (workspace_id,))
            ap = cur.fetchone()
            signals["app_name"] = ap[0] if ap else "Unknown App"
            signals["category"] = ap[1] if ap else ""

            # reviews
            cur.execute("SELECT ROUND(AVG(rating)::numeric,1), COUNT(*) FROM app_reviews WHERE workspace_id=%s", (workspace_id,))
            rv = cur.fetchone()
            signals["avg_rating"] = float(rv[0]) if rv and rv[0] else None
            signals["review_count"] = int(rv[1]) if rv else 0

            cur.execute("SELECT sentiment, COUNT(*) FROM app_reviews WHERE workspace_id=%s GROUP BY sentiment", (workspace_id,))
            signals["sentiment_breakdown"] = {r[0]: r[1] for r in cur.fetchall()}

            # top review complaints
            cur.execute("SELECT body FROM app_reviews WHERE workspace_id=%s AND sentiment='negative' ORDER BY review_date DESC LIMIT 5", (workspace_id,))
            signals["top_complaints"] = [r[0][:100] for r in cur.fetchall()]

            # installs last 30d
            cur.execute("SELECT source, SUM(installs), SUM(cost) FROM app_install_events WHERE workspace_id=%s AND event_date>=NOW()-INTERVAL '30 days' GROUP BY source ORDER BY SUM(installs) DESC", (workspace_id,))
            signals["install_sources"] = [{"source":r[0],"installs":int(r[1]),"spend":float(r[2] or 0)} for r in cur.fetchall()]

            # ASO keywords
            cur.execute("SELECT keyword, appstore_rank, playstore_rank FROM app_aso_keywords WHERE workspace_id=%s LIMIT 20", (workspace_id,))
            signals["aso_keywords"] = [{"kw":r[0],"asc":r[1],"gp":r[2]} for r in cur.fetchall()]

            # Meta ad spend (app install campaigns)
            try:
                cur.execute("SELECT COALESCE(SUM(spend),0) FROM kpi_hourly WHERE workspace_id=%s AND recorded_at>=NOW()-INTERVAL '30 days'", (workspace_id,))
                signals["meta_spend_30d"] = float(cur.fetchone()[0])
            except Exception:
                signals["meta_spend_30d"] = 0

            # YouTube videos
            try:
                cur.execute("SELECT COUNT(*) FROM youtube_videos WHERE workspace_id=%s", (workspace_id,))
                signals["yt_video_count"] = int(cur.fetchone()[0])
            except Exception:
                signals["yt_video_count"] = 0

            # Email list size
            try:
                cur.execute("SELECT COUNT(*) FROM email_contacts WHERE workspace_id=%s AND unsubscribed=false", (workspace_id,))
                signals["email_list_size"] = int(cur.fetchone()[0])
            except Exception:
                signals["email_list_size"] = 0

    prompt = f"""You are an expert mobile app growth strategist. Generate a comprehensive 30-day cross-channel growth plan.

APP: {signals['app_name']} | Category: {signals['category']}

CURRENT METRICS:
- Avg Rating: {signals.get('avg_rating','N/A')} ({signals.get('review_count',0)} reviews)
- Sentiment: {signals.get('sentiment_breakdown',{})}
- Top complaints: {signals.get('top_complaints',[])}
- Installs last 30d by source: {signals.get('install_sources',[])}
- Meta ad spend 30d: ₹{signals.get('meta_spend_30d',0):,.0f}
- YouTube videos: {signals.get('yt_video_count',0)}
- Email list: {signals.get('email_list_size',0)} subscribers
- ASO keywords tracked: {len(signals.get('aso_keywords',[]))}

Return JSON:
{{
  "headline": "<one-line growth opportunity summary>",
  "priority_score": <1-10>,
  "actions": [
    {{
      "id": 1,
      "priority": "high|medium|low",
      "channel": "meta|google|youtube|email|aso|reviews|organic",
      "title": "<action title>",
      "description": "<what to do and why>",
      "expected_impact": "<e.g. +15% installs>",
      "effort": "low|medium|high",
      "timeframe": "<e.g. This week>"
    }}
  ],
  "aso_quick_wins": ["<win1>","<win2>","<win3>"],
  "review_action": "<what to do about reviews this week>",
  "channel_recommendations": {{
    "meta": "<recommendation>",
    "google_uac": "<recommendation>",
    "youtube": "<recommendation>",
    "email": "<recommendation>"
  }},
  "30_day_goal": "<measurable target e.g. reach 10,000 installs>"
}}

Generate 8-12 actions covering all channels."""

    try:
        msg = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            system='Respond ONLY with valid JSON.',
            messages=[{"role":"user","content":prompt}]
        )
        plan = json.loads(msg.content[0].text.strip())
    except Exception as e:
        plan = {"headline": "Unable to generate plan", "actions": [], "error": str(e)}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO app_growth_plans (workspace_id, plan_json) VALUES (%s,%s::jsonb)",
                        (workspace_id, json.dumps(plan)))
    return plan


@app.get("/app-growth/growth-plan/latest")
async def app_growth_plan_latest(request: Request, workspace_id: str = None):
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT plan_json, generated_at FROM app_growth_plans WHERE workspace_id=%s ORDER BY generated_at DESC LIMIT 1", (workspace_id,))
            row = cur.fetchone()
    if not row:
        return {"plan": None}
    plan = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return {"plan": plan, "generated_at": row[1].isoformat() if row[1] else None}


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


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  YouTube Competitor Intelligence — 9-Layer Engine Endpoints                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@app.post("/youtube/competitor-intel/analyze")
async def yt_ci_analyze(request: Request, background_tasks: BackgroundTasks):
    """Trigger competitor discovery phase (Phase 1 of 2).

    Creates a yt_analysis_jobs row immediately, starts live discovery in background.
    After discovery, sets discovery_status='awaiting_confirmation'.
    User calls /confirm-discovery to kick off Phase 2 (full 9-layer pipeline).
    """
    _auth(request)
    body         = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    # Deduct credits before running expensive analysis
    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        _check_and_deduct_credits(conn, org_id, workspace_id,
                                  FEATURE_COSTS["yt_competitor_intel"], "yt_competitor_intel")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Insert with discovery_status='discovering' immediately so polls never see 'idle'
            try:
                cur.execute(
                    """
                    INSERT INTO yt_analysis_jobs (workspace_id, status, discovery_status, created_at)
                    VALUES (%s, 'running', 'discovering', NOW())
                    RETURNING id
                    """,
                    (workspace_id,),
                )
            except Exception:
                conn.rollback()
                cur.execute(
                    """
                    INSERT INTO yt_analysis_jobs (workspace_id, status, created_at)
                    VALUES (%s, 'running', NOW())
                    RETURNING id
                    """,
                    (workspace_id,),
                )
            job_id = cur.fetchone()[0]
        conn.commit()

    from services.agent_swarm.core.yt_intelligence import run_discovery_phase
    background_tasks.add_task(run_discovery_phase, workspace_id, job_id)

    return {"job_id": job_id, "status": "running", "workspace_id": workspace_id}


@app.get("/youtube/competitor-intel/status")
async def yt_ci_status(request: Request, workspace_id: str = None):
    """Return the latest analysis job status for this workspace."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Try to select phase + channels_total columns (added in v24 migration)
            try:
                cur.execute(
                    """
                    SELECT id, status, started_at, completed_at, error,
                           channels_analyzed, videos_analyzed, created_at, phase,
                           channels_total
                    FROM yt_analysis_jobs
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
                has_extra = True
            except Exception:
                conn.rollback()
                cur.execute(
                    """
                    SELECT id, status, started_at, completed_at, error,
                           channels_analyzed, videos_analyzed, created_at
                    FROM yt_analysis_jobs
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
                has_extra = False

    if not row:
        return {"has_job": False, "status": None}

    channels_analyzed = row[5] or 0
    channels_total    = (row[9] if has_extra else 0) or channels_analyzed

    return {
        "has_job":           True,
        "job_id":            row[0],
        "status":            row[1],
        "started_at":        row[2].isoformat() if row[2] else None,
        "completed_at":      row[3].isoformat() if row[3] else None,
        "error":             row[4],
        "channels_analyzed": channels_analyzed,
        "videos_analyzed":   row[6],
        "created_at":        row[7].isoformat() if row[7] else None,
        "phase":             (row[8] if has_extra else None) or "competitor_analysis",
        "channels_total":    channels_total,
    }


@app.get("/youtube/competitor-intel/discovery-status")
async def yt_ci_discovery_status(request: Request, workspace_id: str = None):
    """Return live discovery log, candidates list, own_topic_space, and discovery_status."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT id, discovery_status, discovery_log, discovery_candidates,
                           own_topic_space
                    FROM yt_analysis_jobs
                    WHERE workspace_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                return {"has_job": False, "discovery_status": "idle"}

    if not row:
        return {"has_job": False, "discovery_status": "idle"}

    return {
        "has_job":             True,
        "job_id":              row[0],
        "discovery_status":    row[1] or "idle",
        "discovery_log":       row[2] or [],
        "discovery_candidates": row[3] or [],
        "own_topic_space":     row[4] or [],
    }


@app.post("/youtube/competitor-intel/confirm-discovery")
async def yt_ci_confirm_discovery(request: Request, background_tasks: BackgroundTasks):
    """Confirm competitor list and start Phase 2 deep analysis.

    Body: {
        workspace_id: str,
        confirmed_channel_ids: [str],   # auto-discovered channels the user keeps
        manual_channel_urls: [str]      # up to 3 URLs/handles to add
    }
    Removes de-selected auto channels, upserts manual ones, then kicks off run_analysis_phase.
    """
    _auth(request)
    body                  = await request.json()
    workspace_id          = body.get("workspace_id", "")
    confirmed_ids         = body.get("confirmed_channel_ids", [])
    manual_urls           = body.get("manual_channel_urls", [])[:3]  # hard cap at 3

    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import json as _json
    from services.agent_swarm.connectors.yt_competitor import (
        resolve_channel_id_from_handle, get_channel_meta, list_recent_video_ids, get_videos_details,
    )
    from services.agent_swarm.config import YOUTUBE_API_KEY as _YT_KEY
    from services.agent_swarm.core.yt_intelligence import _extract_topic_space

    with get_conn() as conn:
        # 1. Remove auto-discovered channels not in confirmed_ids
        with conn.cursor() as cur:
            cur.execute(
                "SELECT channel_id FROM yt_competitor_channels WHERE workspace_id = %s AND source = 'auto'",
                (workspace_id,),
            )
            existing_auto = [r[0] for r in cur.fetchall()]

        to_remove = [ch for ch in existing_auto if ch not in confirmed_ids]
        if to_remove:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM yt_competitor_channels WHERE workspace_id = %s AND channel_id = ANY(%s)",
                    (workspace_id, to_remove),
                )
            conn.commit()

        # 2. Resolve and upsert manual channels (with topic_space)
        manual_resolved = []
        for url in manual_urls:
            url = url.strip()
            if not url:
                continue
            # parse channel_id from URL or handle
            ch_id = None
            if "youtube.com/channel/" in url:
                ch_id = url.split("youtube.com/channel/")[-1].split("/")[0].split("?")[0]
            elif "youtube.com/@" in url:
                handle = url.split("youtube.com/@")[-1].split("/")[0].split("?")[0]
                ch_id = resolve_channel_id_from_handle(handle, _YT_KEY)
            elif url.startswith("@"):
                ch_id = resolve_channel_id_from_handle(url[1:], _YT_KEY)
            elif url.startswith("UC") and len(url) > 20:
                ch_id = url
            else:
                # try treating as a handle
                ch_id = resolve_channel_id_from_handle(url.lstrip("@"), _YT_KEY)

            if not ch_id:
                continue

            meta = get_channel_meta(ch_id, _YT_KEY)
            if not meta.get("title") or meta.get("title") == "Unknown":
                continue

            # compute topic_space for manual channel
            vid_ids = list_recent_video_ids(ch_id, 20, _YT_KEY)
            ch_vids = get_videos_details(vid_ids, _YT_KEY) if vid_ids else []
            ch_titles = [v["title"] for v in ch_vids if v.get("title")]
            topic_space = _extract_topic_space(ch_titles, n_keywords=10)

            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO yt_competitor_channels
                            (workspace_id, channel_id, channel_title, channel_handle,
                             subscriber_count, similarity_score, rank, source, discovered_at, topic_space)
                        VALUES (%s, %s, %s, %s, %s, 0, 99, 'manual', NOW(), %s)
                        ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                            channel_title    = EXCLUDED.channel_title,
                            channel_handle   = EXCLUDED.channel_handle,
                            subscriber_count = EXCLUDED.subscriber_count,
                            source           = 'manual',
                            topic_space      = EXCLUDED.topic_space
                        """,
                        (
                            workspace_id, ch_id,
                            meta.get("title", "")[:200],
                            meta.get("handle", ""),
                            meta.get("subscriber_count"),
                            _json.dumps(topic_space),
                        ),
                    )
                except Exception:
                    cur.execute(
                        """
                        INSERT INTO yt_competitor_channels
                            (workspace_id, channel_id, channel_title, channel_handle,
                             subscriber_count, similarity_score, rank, source, discovered_at)
                        VALUES (%s, %s, %s, %s, %s, 0, 99, 'manual', NOW())
                        ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                            channel_title    = EXCLUDED.channel_title,
                            channel_handle   = EXCLUDED.channel_handle,
                            subscriber_count = EXCLUDED.subscriber_count,
                            source           = 'manual'
                        """,
                        (
                            workspace_id, ch_id,
                            meta.get("title", "")[:200],
                            meta.get("handle", ""),
                            meta.get("subscriber_count"),
                        ),
                    )
            conn.commit()
            manual_resolved.append(ch_id)

        # 3. Get the latest job_id to use for analysis phase
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM yt_analysis_jobs WHERE workspace_id = %s ORDER BY created_at DESC LIMIT 1",
                (workspace_id,),
            )
            job_row = cur.fetchone()
        job_id = job_row[0] if job_row else None

    if not job_id:
        raise HTTPException(status_code=400, detail="No analysis job found — run /analyze first")

    from services.agent_swarm.core.yt_intelligence import run_analysis_phase
    background_tasks.add_task(run_analysis_phase, workspace_id, job_id)

    return {
        "started":          True,
        "job_id":           job_id,
        "confirmed_count":  len(confirmed_ids),
        "manual_added":     len(manual_resolved),
        "removed_count":    len(to_remove),
    }


@app.post("/youtube/competitor-intel/re-discover")
async def yt_ci_re_discover(request: Request, background_tasks: BackgroundTasks):
    """Re-run competitor discovery (Phase 1 only) without running the full analysis.

    Clears existing auto-discovered channels (keeps manual ones), then re-runs discovery.
    """
    _auth(request)
    body         = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        # Remove only auto-discovered channels
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM yt_competitor_channels WHERE workspace_id = %s AND source = 'auto'",
                (workspace_id,),
            )
        conn.commit()

        # Create a new job row — insert as 'discovering' immediately so polls never see 'idle'
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO yt_analysis_jobs (workspace_id, status, discovery_status, created_at)
                    VALUES (%s, 'running', 'discovering', NOW())
                    RETURNING id
                    """,
                    (workspace_id,),
                )
            except Exception:
                conn.rollback()
                cur.execute(
                    """
                    INSERT INTO yt_analysis_jobs (workspace_id, status, created_at)
                    VALUES (%s, 'running', NOW())
                    RETURNING id
                    """,
                    (workspace_id,),
                )
            job_id = cur.fetchone()[0]
        conn.commit()

    from services.agent_swarm.core.yt_intelligence import run_discovery_phase
    background_tasks.add_task(run_discovery_phase, workspace_id, job_id)

    return {"job_id": job_id, "status": "running", "workspace_id": workspace_id}


@app.get("/youtube/competitor-intel/competitors")
async def yt_ci_list_competitors(request: Request, workspace_id: str = None):
    """List registered competitor channels for this workspace."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT channel_id, channel_title, channel_handle, subscriber_count,
                           similarity_score, rank, source, discovered_at, last_analyzed_at,
                           topic_space
                    FROM yt_competitor_channels
                    WHERE workspace_id = %s
                    ORDER BY rank ASC
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
                has_topic_space = True
            except Exception:
                conn.rollback()
                cur.execute(
                    """
                    SELECT channel_id, channel_title, channel_handle, subscriber_count,
                           similarity_score, rank, source, discovered_at, last_analyzed_at
                    FROM yt_competitor_channels
                    WHERE workspace_id = %s
                    ORDER BY rank ASC
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
                has_topic_space = False

    return {
        "competitors": [
            {
                "channel_id":       r[0],
                "title":            r[1],
                "handle":           r[2],
                "subscriber_count": r[3],
                "similarity_score": float(r[4] or 0),
                "rank":             r[5],
                "source":           r[6],
                "discovered_at":    r[7].isoformat() if r[7] else None,
                "last_analyzed_at": r[8].isoformat() if r[8] else None,
                "topic_space":      (r[9] if has_topic_space else None) or [],
            }
            for r in rows
        ],
        "has_data": len(rows) > 0,
    }


@app.post("/youtube/competitor-intel/competitors")
async def yt_ci_add_competitor(request: Request):
    """Manually add a competitor channel by URL / handle / channel_id."""
    _auth(request)
    body         = await request.json()
    workspace_id = body.get("workspace_id", "")
    channel_url  = body.get("channel_url", "").strip()
    if not workspace_id or not channel_url:
        raise HTTPException(status_code=400, detail="workspace_id and channel_url required")

    from services.agent_swarm.connectors.yt_competitor import (
        resolve_channel_id_from_handle, get_channel_meta,
    )
    from services.agent_swarm.config import YOUTUBE_API_KEY

    ch_id = resolve_channel_id_from_handle(channel_url, YOUTUBE_API_KEY)
    if not ch_id:
        raise HTTPException(status_code=404, detail="Could not resolve YouTube channel")

    meta = get_channel_meta(ch_id, YOUTUBE_API_KEY)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO yt_competitor_channels
                    (workspace_id, channel_id, channel_title, channel_handle,
                     subscriber_count, similarity_score, rank, source)
                VALUES (%s, %s, %s, %s, %s, 0, 99, 'manual')
                ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                    channel_title = EXCLUDED.channel_title,
                    source        = 'manual'
                """,
                (
                    workspace_id, ch_id,
                    meta.get("title", "")[:200],
                    meta.get("handle", ""),
                    meta.get("subscriber_count"),
                ),
            )
        conn.commit()

    return {"ok": True, "channel_id": ch_id, "title": meta.get("title", "")}


@app.delete("/youtube/competitor-intel/competitors")
async def yt_ci_remove_competitor(request: Request):
    """Remove a competitor channel from this workspace."""
    _auth(request)
    body         = await request.json()
    workspace_id = body.get("workspace_id", "")
    channel_id   = body.get("channel_id", "")
    if not workspace_id or not channel_id:
        raise HTTPException(status_code=400, detail="workspace_id and channel_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Cascade-clean all analysis data for this channel in this workspace
            for tbl in ("yt_topic_clusters", "yt_channel_profiles"):
                cur.execute(
                    f"DELETE FROM {tbl} WHERE workspace_id = %s AND channel_id = %s",
                    (workspace_id, channel_id),
                )
            # Video-level tables keyed by video_id — delete via subquery
            for tbl in ("yt_ai_features", "yt_video_features"):
                cur.execute(
                    f"""DELETE FROM {tbl} WHERE video_id IN (
                        SELECT video_id FROM yt_competitor_videos
                        WHERE workspace_id = %s AND channel_id = %s
                    )""",
                    (workspace_id, channel_id),
                )
            cur.execute(
                "DELETE FROM yt_competitor_videos WHERE workspace_id = %s AND channel_id = %s",
                (workspace_id, channel_id),
            )
            cur.execute(
                "DELETE FROM yt_competitor_channels WHERE workspace_id = %s AND channel_id = %s",
                (workspace_id, channel_id),
            )
        conn.commit()

    return {"ok": True}


@app.get("/youtube/competitor-intel/topics")
async def yt_ci_topics(request: Request, workspace_id: str = None):
    """Layer 2: Topic clusters ranked by avg_velocity across all competitor channels."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tc.topic_name, tc.subthemes, tc.cluster_size, tc.avg_velocity,
                       tc.median_velocity, tc.hit_rate, tc.trs_score,
                       tc.shelf_life, tc.half_life_weeks, tc.channel_id,
                       cc.channel_title
                FROM yt_topic_clusters tc
                INNER JOIN yt_competitor_channels cc
                    ON cc.workspace_id = tc.workspace_id AND cc.channel_id = tc.channel_id
                WHERE tc.workspace_id = %s
                ORDER BY tc.avg_velocity DESC
                LIMIT 60
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

    return {
        "clusters": [
            {
                "topic_name":       r[0],
                "subthemes":        r[1] if isinstance(r[1], list) else [],
                "cluster_size":     r[2],
                "avg_velocity":     float(r[3] or 0),
                "median_velocity":  float(r[4] or 0),
                "hit_rate":         float(r[5] or 0),
                "trs_score":        r[6],
                "shelf_life":       r[7],
                "half_life_weeks":  r[8],
                "channel_id":       r[9],
                "channel_title":    r[10] or r[9],
            }
            for r in rows
        ],
        "has_data": len(rows) > 0,
    }


@app.get("/youtube/competitor-intel/formats")
async def yt_ci_formats(request: Request, workspace_id: str = None):
    """Layer 3: Format scaling scores — avg velocity and hit rate per format label."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Format → velocity aggregation
            cur.execute(
                """
                SELECT a.format_label,
                       COUNT(*) AS cnt,
                       AVG(f.velocity) AS avg_velocity,
                       PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.velocity) AS p75,
                       AVG(f.engagement_rate) AS avg_engagement
                FROM yt_ai_features a
                JOIN yt_video_features f ON f.video_id = a.video_id
                JOIN yt_competitor_videos v ON v.video_id = a.video_id
                JOIN yt_competitor_channels cc
                    ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
                WHERE f.workspace_id = %s AND a.format_label IS NOT NULL
                GROUP BY a.format_label
                ORDER BY avg_velocity DESC
                """,
                (workspace_id,),
            )
            fmt_rows = cur.fetchall()

            # Global p75 for hit_rate
            cur.execute(
                "SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY velocity) FROM yt_video_features WHERE workspace_id = %s",
                (workspace_id,),
            )
            p75_row   = cur.fetchone()
            global_p75 = float(p75_row[0] or 0) if p75_row else 0

            # Sample titles per format (top 3 by velocity)
            sample_titles: dict[str, list[str]] = {}
            for row in fmt_rows:
                fmt = row[0]
                cur.execute(
                    """
                    SELECT v.title FROM yt_ai_features a
                    JOIN yt_video_features f ON f.video_id = a.video_id
                    JOIN yt_competitor_videos v ON v.video_id = a.video_id
                    WHERE f.workspace_id = %s AND a.format_label = %s
                    ORDER BY f.velocity DESC LIMIT 3
                    """,
                    (workspace_id, fmt),
                )
                sample_titles[fmt] = [r[0] for r in cur.fetchall() if r[0]]

    results = []
    for row in fmt_rows:
        fmt, cnt, avg_vel, p75_fmt, avg_eng = row
        hit_rate = round(
            sum(1 for _ in range(int(cnt))) / max(cnt, 1) * 100, 1
        )  # simplified — p75_fmt vs global_p75
        hit_rate_actual = round(
            (float(p75_fmt or 0) > global_p75) * 100, 1
        ) if global_p75 > 0 else 0.0
        # avg_hit_rate: share of this format's videos above the global p75 velocity
        avg_hit_rate = round(
            (float(p75_fmt or 0) > global_p75) * 1.0, 2
        ) if global_p75 > 0 else 0.0
        results.append({
            "format_label":  fmt,
            "video_count":   int(cnt),
            "avg_velocity":  round(float(avg_vel or 0), 2),
            "avg_hit_rate":  avg_hit_rate,
            "sample_titles": sample_titles.get(fmt, []),
        })

    return {"formats": results, "has_data": len(results) > 0}


@app.get("/youtube/competitor-intel/title-patterns")
async def yt_ci_title_patterns(request: Request, workspace_id: str = None):
    """Layer 4: Title pattern velocity uplift vs baseline."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT AVG(velocity) FROM yt_video_features WHERE workspace_id = %s",
                (workspace_id,),
            )
            baseline_row     = cur.fetchone()
            baseline_avg_vel = float(baseline_row[0] or 0) if baseline_row else 0

            cur.execute(
                """
                SELECT a.title_patterns, f.velocity
                FROM yt_ai_features a
                JOIN yt_video_features f ON f.video_id = a.video_id
                JOIN yt_competitor_videos v ON v.video_id = a.video_id
                JOIN yt_competitor_channels cc
                    ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
                WHERE f.workspace_id = %s AND a.title_patterns IS NOT NULL
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

    # Aggregate per pattern
    from collections import defaultdict
    pattern_vels: dict = defaultdict(list)
    for title_patterns_raw, velocity in rows:
        patterns: list = title_patterns_raw if isinstance(title_patterns_raw, list) else []
        for pat in patterns:
            pattern_vels[pat].append(float(velocity or 0))

    results = []
    for pat, vels in pattern_vels.items():
        avg_vel     = sum(vels) / len(vels)
        uplift_pct  = round((avg_vel - baseline_avg_vel) / max(baseline_avg_vel, 0.01) * 100, 1)
        results.append({
            "pattern":      pat,
            "video_count":  len(vels),
            "avg_velocity": round(avg_vel, 2),
            "uplift_pct":   uplift_pct,
        })

    results.sort(key=lambda x: x["uplift_pct"], reverse=True)
    return {
        "patterns":        results,
        "baseline_avg_velocity": round(baseline_avg_vel, 2),
        "has_data":        len(results) > 0,
    }


@app.get("/youtube/competitor-intel/thumbnails")
async def yt_ci_thumbnails(request: Request, workspace_id: str = None):
    """Layer 5: Thumbnail psychology — face/text/emotion velocity analysis."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.thumb_face, a.thumb_text, a.thumb_emotion, a.thumb_style, f.velocity
                FROM yt_ai_features a
                JOIN yt_video_features f ON f.video_id = a.video_id
                JOIN yt_competitor_videos v ON v.video_id = a.video_id
                JOIN yt_competitor_channels cc
                    ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
                WHERE f.workspace_id = %s
                  AND a.thumb_face IS NOT NULL
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

    if not rows:
        return {"has_data": False, "face_vs_no_face": {}, "emotions": [], "top_combos": []}

    face_vels    = {"face": [], "no_face": []}
    emotion_vels: dict = {}
    style_vels:  dict  = {}
    combo_vels:  dict  = {}

    for thumb_face, thumb_text, thumb_emotion, thumb_style, velocity in rows:
        vel  = float(velocity or 0)
        key  = "face" if thumb_face else "no_face"
        face_vels[key].append(vel)

        if thumb_emotion:
            emotion_vels.setdefault(thumb_emotion, []).append(vel)
        if thumb_style:
            style_vels.setdefault(thumb_style, []).append(vel)

        # Combo: face+text+emotion
        combo = f"{'face' if thumb_face else 'no_face'}+{'text' if thumb_text else 'no_text'}+{thumb_emotion or 'unknown'}"
        combo_vels.setdefault(combo, []).append(vel)

    def _avg(lst: list) -> float:
        return round(sum(lst) / len(lst), 2) if lst else 0.0

    emotion_table = [
        {"emotion": e, "avg_velocity": _avg(v), "count": len(v)}
        for e, v in emotion_vels.items()
    ]
    emotion_table.sort(key=lambda x: x["avg_velocity"], reverse=True)

    combo_table = [
        {"combo": c, "avg_velocity": _avg(v), "count": len(v)}
        for c, v in combo_vels.items()
    ]
    combo_table.sort(key=lambda x: x["avg_velocity"], reverse=True)

    # Parse combo string "face+text+emotion" → structured dict for frontend
    def _parse_combo(c: dict) -> dict:
        parts = c["combo"].split("+")
        has_face = parts[0] == "face" if parts else False
        has_text = parts[1] == "text" if len(parts) > 1 else False
        emotion  = parts[2] if len(parts) > 2 else None
        return {
            "face":          has_face,
            "text":          has_text,
            "emotion":       emotion,
            "avg_velocity":  c["avg_velocity"],
            "count":         c["count"],
        }

    return {
        "face_vs_no_face": {
            "face_avg_velocity":    _avg(face_vels["face"]),
            "no_face_avg_velocity": _avg(face_vels["no_face"]),
            "face":                 len(face_vels["face"]),
            "no_face":              len(face_vels["no_face"]),
        },
        "emotion_breakdown": emotion_table,
        "top_combos":        [_parse_combo(c) for c in combo_table[:10]],
        "has_data":          True,
    }


@app.get("/youtube/competitor-intel/rhythm")
async def yt_ci_rhythm(request: Request, workspace_id: str = None):
    """Layer 6 + 8: Publishing cadence + pre-breakout momentum windows."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import statistics as _stat

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Channel cadence profiles
            cur.execute(
                """
                SELECT p.channel_id, cc.channel_title,
                       p.cadence_pattern, p.median_gap_days, p.breakout_rate, p.risk_profile
                FROM yt_channel_profiles p
                INNER JOIN yt_competitor_channels cc
                    ON cc.workspace_id = p.workspace_id AND cc.channel_id = p.channel_id
                WHERE p.workspace_id = %s
                ORDER BY p.breakout_rate DESC
                """,
                (workspace_id,),
            )
            profiles = cur.fetchall()

            # Pre-breakout cadence: for each breakout video, get gap of 3 prior uploads
            cur.execute(
                """
                SELECT v.channel_id, v.published_at, f.is_breakout, f.upload_gap_days
                FROM yt_competitor_videos v
                JOIN yt_video_features f ON f.video_id = v.video_id
                WHERE v.workspace_id = %s
                ORDER BY v.channel_id, v.published_at ASC
                """,
                (workspace_id,),
            )
            vid_rows = cur.fetchall()

    # Group by channel to find pre-breakout gaps
    from collections import defaultdict
    ch_vids: dict = defaultdict(list)
    for ch, pub_at, is_brk, gap in vid_rows:
        ch_vids[ch].append((pub_at, bool(is_brk), float(gap) if gap else None))

    pre_breakout_gaps: list[float] = []
    for ch, vids in ch_vids.items():
        for i, (pub_at, is_brk, gap) in enumerate(vids):
            if is_brk and i >= 3:
                prior = [vids[j][2] for j in range(max(0, i - 3), i) if vids[j][2] is not None]
                if prior:
                    pre_breakout_gaps.append(_stat.median(prior))

    pre_breakout_median = round(_stat.median(pre_breakout_gaps), 1) if pre_breakout_gaps else None

    return {
        "channels": [
            {
                "channel_id":       r[0],
                "channel_title":    r[1] or r[0],
                "cadence_pattern":  r[2],
                "median_gap_days":  float(r[3] or 0),
                "breakout_rate":    float(r[4] or 0),
                "risk_profile":     r[5],
            }
            for r in profiles
        ],
        "pre_breakout_median_gap_days": pre_breakout_median,
        "momentum_window": (
            f"Breakouts tend to follow ~{pre_breakout_median:.1f}-day upload gaps"
            if pre_breakout_median else None
        ),
        "has_data": len(profiles) > 0,
    }


@app.get("/youtube/competitor-intel/lifecycle")
async def yt_ci_lifecycle(request: Request, workspace_id: str = None):
    """Layer 7: Topic lifecycle — evergreen vs trend classification."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tc.topic_name, tc.shelf_life, tc.half_life_weeks, tc.avg_velocity,
                       tc.cluster_size, tc.channel_id, cc.channel_title
                FROM yt_topic_clusters tc
                INNER JOIN yt_competitor_channels cc
                    ON cc.workspace_id = tc.workspace_id AND cc.channel_id = tc.channel_id
                WHERE tc.workspace_id = %s AND tc.shelf_life IS NOT NULL
                ORDER BY tc.avg_velocity DESC
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

    def _to_dict(r) -> dict:
        return {
            "topic_name":       r[0],
            "shelf_life":       r[1],
            "half_life_weeks":  r[2],
            "avg_velocity":     float(r[3] or 0),
            "cluster_size":     r[4],
            "channel_id":       r[5],
            "channel_title":    r[6] or r[5],
        }

    evergreen = [_to_dict(r) for r in rows if r[1] == "evergreen"]
    trend     = [_to_dict(r) for r in rows if r[1] == "trend"]

    return {
        "evergreen_topics":  evergreen,
        "trend_topics":      trend,
        "topic_shelf_lives": [_to_dict(r) for r in rows],
        "has_data":          len(rows) > 0,
    }


@app.get("/youtube/competitor-intel/channels")
async def yt_ci_channels(request: Request, workspace_id: str = None):
    """Layer 8: Channel risk profiles — velocity distributions and cadence."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.channel_id, cc.channel_title, cc.subscriber_count,
                       p.median_velocity, p.p75_velocity, p.p90_velocity,
                       p.iqr, p.std_velocity,
                       p.hit_rate, p.underperform_rate, p.breakout_rate,
                       p.risk_profile, p.cadence_pattern, p.median_gap_days
                FROM yt_channel_profiles p
                INNER JOIN yt_competitor_channels cc
                    ON cc.workspace_id = p.workspace_id AND cc.channel_id = p.channel_id
                WHERE p.workspace_id = %s
                ORDER BY p.p90_velocity DESC
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

    return {
        "channels": [
            {
                "channel_id":       r[0],
                "channel_title":    r[1] or r[0],
                "subscriber_count": r[2],
                "median_velocity":  float(r[3] or 0),
                "p75_velocity":     float(r[4] or 0),
                "p90_velocity":     float(r[5] or 0),
                "iqr":              float(r[6] or 0),
                "std_velocity":     float(r[7] or 0),
                "hit_rate":         float(r[8] or 0),
                "underperform_rate": float(r[9] or 0),
                "breakout_rate":    float(r[10] or 0),
                "risk_profile":     r[11],
                "cadence_pattern":  r[12],
                "median_gap_days":  float(r[13] or 0),
            }
            for r in rows
        ],
        "has_data": len(rows) > 0,
    }


@app.get("/youtube/competitor-intel/breakout-recipe")
async def yt_ci_breakout_recipe(request: Request, workspace_id: str = None):
    """Layer 9: Breakout recipe — ML feature importances + Claude Sonnet playbook."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT playbook_text, top_features, p90_threshold, breakout_count, trained_at
                FROM yt_breakout_recipe
                WHERE workspace_id = %s
                """,
                (workspace_id,),
            )
            row = cur.fetchone()

    if not row:
        return {"has_data": False}

    return {
        "has_data":       True,
        "playbook_text":  row[0],
        "top_features":   row[1] if isinstance(row[1], dict) else {},
        "p90_threshold":  float(row[2] or 0),
        "breakout_count": row[3],
        "trained_at":     row[4].isoformat() if row[4] else None,
    }


# ── Own-channel comparison + Growth Recipe ───────────────────────────────────

@app.get("/youtube/competitor-intel/own-analysis")
async def yt_ci_own_analysis(request: Request, workspace_id: str = None):
    """Own-channel snapshot: velocities, formats, gaps vs competitors."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        # Own channel videos
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT video_id, title, views, velocity, engagement_rate,
                       format_label, title_patterns, thumb_face, thumb_emotion,
                       thumb_text, is_short, published_at
                FROM yt_own_channel_snapshot
                WHERE workspace_id = %s
                ORDER BY velocity DESC
                """,
                (workspace_id,),
            )
            own_rows = cur.fetchall()

        if not own_rows:
            # Check if we have a "not enough" record
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT own_video_count FROM yt_growth_recipe WHERE workspace_id = %s",
                    (workspace_id,),
                )
                nr = cur.fetchone()
            count = nr[0] if nr else 0
            return {
                "has_data": False,
                "not_enough_videos": True,
                "video_count": count,
                "message": f"Only {count} video{'s' if count != 1 else ''} found on your channel. Post at least 5 videos to unlock My Channel analysis.",
            }

        # Competitor percentiles
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.velocity),
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY f.velocity),
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.velocity),
                    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY f.velocity)
                FROM yt_video_features f
                JOIN yt_competitor_videos v ON v.video_id = f.video_id
                JOIN yt_competitor_channels cc
                    ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
                WHERE f.workspace_id = %s
                """,
                (workspace_id,),
            )
            prow = cur.fetchone()
        comp_p25 = float(prow[0] or 0) if prow else 0
        comp_p50 = float(prow[1] or 0) if prow else 0
        comp_p75 = float(prow[2] or 0) if prow else 0
        comp_p90 = float(prow[3] or 0) if prow else 0

        own_velocities = [float(r[3] or 0) for r in own_rows]
        own_avg_vel    = sum(own_velocities) / len(own_velocities) if own_velocities else 0

        from services.agent_swarm.core.yt_intelligence import _compute_percentile
        own_percentile = _compute_percentile(own_avg_vel, comp_p25, comp_p50, comp_p75, comp_p90)

        videos = [
            {
                "video_id":        r[0],
                "title":           r[1],
                "views":           r[2],
                "velocity":        float(r[3] or 0),
                "engagement_rate": float(r[4] or 0),
                "format_label":    r[5],
                "title_patterns":  r[6] if isinstance(r[6], list) else [],
                "thumb_face":      r[7],
                "thumb_emotion":   r[8],
                "thumb_text":      r[9],
                "is_short":        r[10],
                "published_at":    r[11].isoformat() if r[11] else None,
            }
            for r in own_rows
        ]

    return {
        "has_data":              True,
        "video_count":           len(videos),
        "own_avg_velocity":      round(own_avg_vel, 2),
        "own_velocity_percentile": round(min(own_percentile, 99), 1),
        "comp_p25":              round(comp_p25, 2),
        "comp_p50":              round(comp_p50, 2),
        "comp_p75":              round(comp_p75, 2),
        "comp_p90":              round(comp_p90, 2),
        "videos":                videos,
    }


@app.get("/youtube/competitor-intel/growth-recipe-v2")
async def yt_ci_growth_recipe_v2(request: Request, workspace_id: str = None):
    """Workspace-type-aware 15-day + 30-day growth recipe from yt_growth_recipe."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT own_video_count, own_velocity_avg, own_velocity_percentile,
                           content_gaps, plan_15d, plan_30d, thumbnail_brief,
                           hooks_library, emerging_topics, generated_at, recipe_text
                    FROM yt_growth_recipe
                    WHERE workspace_id = %s
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
                has_recipe_text = True
            except Exception:
                conn.rollback()
                cur.execute(
                    """
                    SELECT own_video_count, own_velocity_avg, own_velocity_percentile,
                           content_gaps, plan_15d, plan_30d, thumbnail_brief,
                           hooks_library, emerging_topics, generated_at
                    FROM yt_growth_recipe
                    WHERE workspace_id = %s
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
                has_recipe_text = False

        if not row:
            return {"has_data": False}

        # Also fetch workspace_type
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "SELECT workspace_type FROM workspaces WHERE id = %s",
                    (workspace_id,),
                )
                wt = cur.fetchone()
                workspace_type = (wt[0] or "d2c") if wt else "d2c"
            except Exception:
                conn.rollback()
                workspace_type = "d2c"

    recipe_text_val = row[10] if has_recipe_text else None

    # If plan_15d is None/empty → not enough videos yet
    if not row[4] and not recipe_text_val:
        return {
            "has_data":     True,
            "not_enough_videos": True,
            "video_count":  row[0],
            "message":      f"Only {row[0]} video{'s' if row[0] != 1 else ''} found. Post at least 5 videos to unlock your Growth Recipe.",
            "workspace_type": workspace_type,
        }

    return {
        "has_data":                True,
        "workspace_type":          workspace_type,
        "own_video_count":         row[0],
        "own_velocity_avg":        float(row[1] or 0),
        "own_velocity_percentile": float(row[2] or 0),
        "content_gaps":            row[3] if isinstance(row[3], dict) else {},
        "plan_15d":                row[4],
        "plan_30d":                row[5],
        "thumbnail_brief":         row[6],
        "hooks_library":           row[7],
        "emerging_topics":         row[8],
        "generated_at":            row[9].isoformat() if row[9] else None,
        "recipe_text":             recipe_text_val,   # full Claude response as fallback
    }


@app.patch("/workspace/type")
async def update_workspace_type(request: Request):
    """Set workspace_type for a workspace (d2c | creator | saas | agency | media)."""
    _auth(request)
    body          = await request.json()
    workspace_id  = body.get("workspace_id", "")
    workspace_type = body.get("workspace_type", "")

    VALID_TYPES = {"d2c", "creator", "saas", "agency", "media"}
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if workspace_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"workspace_type must be one of: {', '.join(sorted(VALID_TYPES))}")

    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "UPDATE workspaces SET workspace_type = %s WHERE id = %s",
                    (workspace_type, workspace_id),
                )
            except Exception:
                conn.rollback()
                raise HTTPException(status_code=500, detail="workspace_type column not found — run /admin/migrate first")
        conn.commit()

    return {"ok": True, "workspace_type": workspace_type}


@app.get("/workspace/get")
async def workspace_get_info(request: Request, workspace_id: str = None):
    """Return basic workspace info including workspace_type."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, workspace_type, onboarding_complete, store_url FROM workspaces WHERE id = %s",
                (workspace_id,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {
        "id":                  str(row[0]),
        "name":                row[1],
        "workspace_type":      row[2] or "d2c",
        "onboarding_complete": row[3],
        "store_url":           row[4],
    }


@app.patch("/workspace/complete-onboarding")
async def complete_onboarding(request: Request):
    """Mark onboarding complete and save workspace_type + channel preferences."""
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    workspace_type = body.get("workspace_type", "d2c")
    onboarding_channels = body.get("onboarding_channels", [])

    VALID_TYPES = {"d2c", "creator", "saas", "agency", "media"}
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if workspace_type not in VALID_TYPES:
        workspace_type = "d2c"

    import json as _json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE workspaces
                   SET onboarding_complete = TRUE,
                       workspace_type = %s,
                       onboarding_channels = %s
                   WHERE id = %s""",
                (workspace_type, _json.dumps(onboarding_channels), workspace_id),
            )
        conn.commit()

    return {"ok": True, "workspace_type": workspace_type}


@app.post("/youtube/competitor-intel/regenerate-recipe")
async def yt_ci_regenerate_recipe(request: Request, background_tasks: BackgroundTasks):
    """Re-generate growth recipe from existing intel (no full re-analysis needed).

    Useful when: user changes workspace_type, or wants a fresh recipe plan.
    Runs in background and returns immediately.
    """
    _auth(request)
    body         = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    # Deduct credits before re-generation
    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        _check_and_deduct_credits(conn, org_id, workspace_id,
                                  FEATURE_COSTS["growth_recipe_regen"], "growth_recipe_regen")

    async def _regen():
        from services.agent_swarm.db import get_conn as _gc
        from services.agent_swarm.core.yt_intelligence import generate_growth_recipe as _gen
        try:
            with _gc() as conn:
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            "SELECT workspace_type FROM workspaces WHERE id = %s",
                            (workspace_id,),
                        )
                        wt = cur.fetchone()
                        workspace_type = (wt[0] or "d2c") if wt else "d2c"
                    except Exception:
                        conn.rollback()
                        workspace_type = "d2c"
                _gen(workspace_id, workspace_type, conn)
        except Exception as e:
            print(f"[yt_intel] regenerate_recipe error: {e}")

    background_tasks.add_task(_regen)
    return {"ok": True, "message": "Growth recipe regeneration started — refresh in ~1 minute."}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Meta Ad Library — competitor ad intelligence                                 ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@app.post("/meta/ad-library/sync")
async def meta_ad_library_sync(request: Request):
    """Sync competitor ads from Meta Ad Library. Returns result directly."""
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    from services.agent_swarm.db import get_conn
    from services.agent_swarm.connectors.meta_ad_library import sync_workspace_ads
    with get_conn() as conn:
        result = sync_workspace_ads(workspace_id, conn)
    return result


@app.get("/meta/ad-library/ads")
async def meta_ad_library_get(workspace_id: str = ""):
    """Return stored competitor ads for a workspace."""
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    from services.agent_swarm.db import get_conn
    from services.agent_swarm.connectors.meta_ad_library import get_competitor_ads
    with get_conn() as conn:
        return get_competitor_ads(workspace_id, conn)


@app.get("/meta/competitor-pages")
async def meta_competitor_pages_list(workspace_id: str = ""):
    """List manually-added competitor page names for Meta Ad Library."""
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT page_name, added_at FROM meta_competitor_pages "
                "WHERE workspace_id=%s ORDER BY added_at ASC",
                (workspace_id,),
            )
            rows = cur.fetchall()
    return {"pages": [{"page_name": r[0], "added_at": r[1].isoformat()} for r in rows]}


@app.post("/meta/competitor-pages")
async def meta_competitor_pages_add(request: Request):
    """Add a competitor page name for Meta Ad Library monitoring."""
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    page_name = (body.get("page_name") or "").strip()
    if not workspace_id or not page_name:
        raise HTTPException(status_code=400, detail="workspace_id and page_name required")
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meta_competitor_pages (workspace_id, page_name) "
                "VALUES (%s, %s) ON CONFLICT (workspace_id, page_name) DO NOTHING",
                (workspace_id, page_name),
            )
        conn.commit()
    return {"status": "ok", "page_name": page_name}


@app.delete("/meta/competitor-pages")
async def meta_competitor_pages_delete(request: Request):
    """Remove a competitor page name."""
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    page_name = (body.get("page_name") or "").strip()
    if not workspace_id or not page_name:
        raise HTTPException(status_code=400, detail="workspace_id and page_name required")
    from services.agent_swarm.db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM meta_competitor_pages WHERE workspace_id=%s AND page_name=%s",
                (workspace_id, page_name),
            )
        conn.commit()
    return {"status": "ok"}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Growth OS — Unified Command Center                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@app.post("/growth-os/generate")
async def growth_os_generate(request: Request, background_tasks: BackgroundTasks):
    """Trigger async Growth OS plan generation for a workspace.

    Body: { "workspace_id": "..." }
    Returns immediately with plan_id; poll /growth-os/latest for result.
    """
    _auth(request)
    body = await request.json()
    workspace_id = (body.get("workspace_id") or "").strip()
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    # Deduct credits before generating AI plan
    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        _check_and_deduct_credits(conn, org_id, workspace_id,
                                  FEATURE_COSTS["growth_os"], "growth_os")

    import uuid as _uuid

    plan_id = str(_uuid.uuid4())

    async def _gen():
        from services.agent_swarm.db import get_conn as _gc
        from services.agent_swarm.core.growth_os import generate_action_plan as _gen_plan
        try:
            with _gc() as conn:
                _gen_plan(workspace_id, conn)
        except Exception as e:
            print(f"[growth_os] background generate error: {e}")

    background_tasks.add_task(_gen)
    return {"ok": True, "plan_id": plan_id, "status": "generating"}


@app.get("/growth-os/latest")
async def growth_os_latest(request: Request, workspace_id: str = None):
    """Return the latest Growth OS plan for a workspace.

    Query param: workspace_id
    """
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    from services.agent_swarm.db import get_conn as _gc
    import json as _json

    with _gc() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, generated_at, plan_json, sources_used
                FROM growth_os_plans
                WHERE workspace_id = %s
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()

    if not row:
        return {"plan_id": None, "generated_at": None, "actions": [], "sources_used": {}}

    plan_json = row[2] if isinstance(row[2], dict) else _json.loads(row[2] or "{}")
    sources_used = row[3] if isinstance(row[3], dict) else _json.loads(row[3] or "{}")

    return {
        "plan_id": str(row[0]),
        "generated_at": row[1].isoformat() if row[1] else None,
        "actions": plan_json.get("actions", []),
        "sources_used": sources_used,
    }


@app.post("/growth-os/send-to-approvals")
async def growth_os_send_to_approvals(request: Request):
    """Save selected Growth OS actions to the approvals queue.

    Body: { "workspace_id": "...", "actions": [...] }
    Returns list of created action_log ids.
    """
    _auth(request)
    body = await request.json()
    workspace_id = (body.get("workspace_id") or "").strip()
    actions = body.get("actions") or []
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if not isinstance(actions, list):
        raise HTTPException(status_code=400, detail="actions must be a list")

    from services.agent_swarm.db import get_conn as _gc
    from services.agent_swarm.core.growth_os import send_action_to_approvals as _send

    created_ids = []
    with _gc() as conn:
        for action in actions:
            aid = _send(workspace_id, action, conn)
            if aid:
                created_ids.append(aid)

    return {"ok": True, "created_count": len(created_ids), "action_ids": created_ids}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Admin — Data Management                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@app.post("/admin/clear-yt-data")
async def admin_clear_yt_data(request: Request):
    """Delete ALL YouTube Competitor Intelligence data for a workspace (all 9-layer tables).

    Use this to reset for fresh testing.
    Protected by X-Admin-Token header.
    Body: { "workspace_id": "..." }
    """
    _admin_auth(request)
    body         = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    tables = [
        "yt_ai_features",
        "yt_video_features",
        "yt_topic_clusters",
        "yt_competitor_videos",
        "yt_channel_profiles",
        "yt_breakout_recipe",
        "yt_own_channel_snapshot",
        "yt_growth_recipe",
        "yt_competitor_channels",
        "yt_analysis_jobs",
    ]

    deleted: dict[str, int] = {}
    with get_conn() as conn:
        for table in tables:
            try:
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM {table} WHERE workspace_id = %s", (workspace_id,))
                    deleted[table] = cur.rowcount
                conn.commit()
            except Exception as e:
                conn.rollback()
                deleted[table] = -1
                print(f"[admin] clear-yt-data: {table} error: {e}")

    return {"ok": True, "workspace_id": workspace_id, "deleted": deleted}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Billing — Credit System                                                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@app.get("/billing/status")
async def billing_status(request: Request, workspace_id: str = None):
    """Return org plan, credit balance, and recent ledger entries for a workspace."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        with conn.cursor() as cur:
            # Plan + credits from organizations
            cur.execute(
                "SELECT plan, credit_balance FROM organizations WHERE id = %s",
                (org_id,),
            )
            org_row = cur.fetchone()
            if not org_row:
                raise HTTPException(status_code=404, detail="Organization not found")
            plan, credit_balance = org_row[0], org_row[1]

            # Active subscription info
            cur.execute(
                """SELECT status, trial_ends_at, current_period_end
                   FROM subscriptions WHERE org_id = %s
                   ORDER BY created_at DESC LIMIT 1""",
                (org_id,),
            )
            sub = cur.fetchone()

            # Recent ledger (last 20 entries)
            try:
                cur.execute(
                    """SELECT amount, balance_after, type, feature, description, created_at
                       FROM credit_ledger WHERE org_id = %s
                       ORDER BY created_at DESC LIMIT 20""",
                    (org_id,),
                )
                ledger_rows = cur.fetchall()
                ledger = [
                    {
                        "amount": r[0], "balance_after": r[1], "type": r[2],
                        "feature": r[3], "description": r[4],
                        "created_at": r[5].isoformat() if r[5] else None,
                    }
                    for r in ledger_rows
                ]
            except Exception:
                ledger = []

    return {
        "plan": plan,
        "credit_balance": credit_balance,
        "subscription_status": sub[0] if sub else None,
        "trial_ends_at": sub[1].isoformat() if sub and sub[1] else None,
        "current_period_end": sub[2].isoformat() if sub and sub[2] else None,
        "recent_ledger": ledger,
        "credit_packs": CREDIT_PACKS,
        "feature_costs": FEATURE_COSTS,
        "plan_monthly_credits": PLAN_MONTHLY_CREDITS,
    }


@app.post("/billing/topup")
async def billing_topup(request: Request):
    """Create a Razorpay order for a credit top-up pack.
    Body: {workspace_id, pack: "100"|"250"|"600"}
    Returns Razorpay order details for frontend checkout.
    If RAZORPAY_KEY_ID is not set, returns a stub order for testing.
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    pack_key     = str(body.get("pack", "100"))
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if pack_key not in CREDIT_PACKS:
        raise HTTPException(status_code=400, detail=f"Invalid pack. Choose: {list(CREDIT_PACKS.keys())}")

    pack = CREDIT_PACKS[pack_key]
    import json as _json
    from services.agent_swarm.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)

        if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            import httpx as _httpx
            import base64 as _b64
            auth = _b64.b64encode(f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode()).decode()
            resp = _httpx.post(
                "https://api.razorpay.com/v1/orders",
                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
                json={"amount": pack["amount_paise"], "currency": "INR", "receipt": f"topup_{workspace_id[:8]}"},
                timeout=10,
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Razorpay error: {resp.text}")
            rzp_order = resp.json()
            rzp_order_id = rzp_order["id"]
        else:
            # Stub for testing without Razorpay credentials
            import uuid as _uuid
            rzp_order_id = f"stub_order_{_uuid.uuid4().hex[:12]}"

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO billing_orders
                   (org_id, razorpay_order_id, type, credits, amount_paise, status)
                   VALUES (%s, %s, 'topup', %s, %s, 'pending')""",
                (org_id, rzp_order_id, pack["credits"], pack["amount_paise"]),
            )
        conn.commit()

    return {
        "order_id": rzp_order_id,
        "amount_paise": pack["amount_paise"],
        "credits": pack["credits"],
        "razorpay_key_id": RAZORPAY_KEY_ID or "TEST_MODE",
        "currency": "INR",
    }


@app.post("/billing/topup-confirm")
async def billing_topup_confirm(request: Request):
    """Verify Razorpay payment and grant credits.
    Body: {workspace_id, razorpay_order_id, razorpay_payment_id, razorpay_signature}
    """
    _auth(request)
    body = await request.json()
    workspace_id        = body.get("workspace_id", "")
    razorpay_order_id   = body.get("razorpay_order_id", "")
    razorpay_payment_id = body.get("razorpay_payment_id", "")
    razorpay_signature  = body.get("razorpay_signature", "")
    if not workspace_id or not razorpay_order_id:
        raise HTTPException(status_code=400, detail="workspace_id and razorpay_order_id required")

    import hmac as _hmac, hashlib as _hs
    from services.agent_swarm.config import RAZORPAY_KEY_SECRET

    # Verify signature (skip for stub orders in test mode)
    if RAZORPAY_KEY_SECRET and not razorpay_order_id.startswith("stub_"):
        expected = _hmac.new(
            RAZORPAY_KEY_SECRET.encode(), f"{razorpay_order_id}|{razorpay_payment_id}".encode(), _hs.sha256
        ).hexdigest()
        if not _hmac.compare_digest(expected, razorpay_signature):
            raise HTTPException(status_code=400, detail="Invalid payment signature")

    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT credits, status FROM billing_orders WHERE razorpay_order_id = %s AND org_id = %s",
                (razorpay_order_id, org_id),
            )
            order = cur.fetchone()
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
            if order[1] == "paid":
                # Already processed (idempotent)
                cur.execute("SELECT credit_balance FROM organizations WHERE id = %s", (org_id,))
                bal = cur.fetchone()
                return {"ok": True, "new_balance": bal[0] if bal else 0, "already_processed": True}
            credits_to_add = order[0]
            cur.execute(
                "UPDATE billing_orders SET status='paid', razorpay_payment_id=%s, updated_at=NOW() WHERE razorpay_order_id=%s",
                (razorpay_payment_id, razorpay_order_id),
            )
        conn.commit()
        new_balance = _grant_credits(conn, org_id, workspace_id, credits_to_add, "topup",
                                     razorpay_payment_id=razorpay_payment_id,
                                     description=f"Top-up: {credits_to_add} credits via Razorpay")

    return {"ok": True, "credits_added": credits_to_add, "new_balance": new_balance}


@app.post("/billing/webhook")
async def billing_webhook(request: Request):
    """Razorpay webhook handler. Handles payment.captured event.
    Verifies X-Razorpay-Signature header.
    """
    import hmac as _hmac, hashlib as _hs, json as _json
    from services.agent_swarm.config import RAZORPAY_WEBHOOK_SECRET

    body_bytes = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")

    if RAZORPAY_WEBHOOK_SECRET and sig:
        expected = _hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), body_bytes, _hs.sha256).hexdigest()
        if not _hmac.compare_digest(expected, sig):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event = _json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if event.get("event") != "payment.captured":
        return {"ok": True, "skipped": True}

    payment = event.get("payload", {}).get("payment", {}).get("entity", {})
    rzp_payment_id = payment.get("id", "")
    rzp_order_id   = payment.get("order_id", "")
    if not rzp_order_id:
        return {"ok": True, "skipped": True}

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, org_id, credits, status FROM billing_orders WHERE razorpay_order_id = %s",
                (rzp_order_id,),
            )
            order = cur.fetchone()
        if not order or order[3] == "paid":
            return {"ok": True, "skipped": True, "reason": "not_found_or_already_paid"}
        _, org_id, credits_to_add, _ = order
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE billing_orders SET status='paid', razorpay_payment_id=%s, updated_at=NOW() WHERE razorpay_order_id=%s",
                (rzp_payment_id, rzp_order_id),
            )
        conn.commit()
        _grant_credits(conn, str(org_id), None, credits_to_add, "topup",
                       razorpay_payment_id=rzp_payment_id,
                       description=f"Top-up: {credits_to_add} credits via Razorpay webhook")

    return {"ok": True, "credits_added": credits_to_add}


@app.post("/billing/upgrade")
async def billing_upgrade(request: Request):
    """Return Razorpay payment link (or stub URL) for a plan upgrade.
    Body: {workspace_id, plan: "starter"|"growth"|"agency", period: "monthly"|"yearly"}
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    plan   = body.get("plan", "starter")
    period = body.get("period", "monthly")

    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    if plan not in VALID_PLANS or plan == "free":
        raise HTTPException(status_code=400, detail="plan must be starter|growth|agency")

    prices = PLAN_PRICES_YEARLY if period == "yearly" else PLAN_PRICES_MONTHLY
    amount_paise = prices.get(plan, 199900)

    from services.agent_swarm.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
        import httpx as _httpx, base64 as _b64
        auth = _b64.b64encode(f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode()).decode()
        resp = _httpx.post(
            "https://api.razorpay.com/v1/payment_links",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json={
                "amount": amount_paise, "currency": "INR",
                "description": f"Runway Studios {plan.title()} Plan ({period})",
                "callback_url": "https://app.runwaystudios.co/billing?upgraded=1",
                "callback_method": "get",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return {"payment_url": resp.json().get("short_url", ""), "plan": plan, "period": period}
    # Stub response when Razorpay not configured
    return {
        "payment_url": "https://razorpay.com",
        "plan": plan,
        "period": period,
        "stub": True,
        "message": "Set RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET to enable payments",
    }


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Admin — Client Dashboard                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@app.get("/admin/billing-dashboard")
async def admin_billing_dashboard(request: Request):
    """Super-admin view: all orgs with plan, credits, workspace count, last active.
    Protected by X-Admin-Token header.
    """
    _admin_auth(request)
    import json as _json

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    o.id,
                    o.name,
                    o.plan,
                    o.credit_balance,
                    o.clerk_user_id,
                    COUNT(DISTINCT w.id) AS workspace_count,
                    MAX(cl.created_at) AS last_credit_activity,
                    s.status AS subscription_status,
                    s.current_period_end
                FROM organizations o
                LEFT JOIN workspaces w ON w.org_id = o.id AND w.active = TRUE
                LEFT JOIN credit_ledger cl ON cl.org_id = o.id
                LEFT JOIN subscriptions s ON s.org_id = o.id
                GROUP BY o.id, o.name, o.plan, o.credit_balance, o.clerk_user_id, s.status, s.current_period_end
                ORDER BY o.created_at DESC
                """,
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            orgs = [dict(zip(cols, r)) for r in rows]

        # Convert non-serializable types
        for org in orgs:
            for k, v in org.items():
                if hasattr(v, "isoformat"):
                    org[k] = v.isoformat()

        # Summary stats
        total_orgs    = len(orgs)
        paying_orgs   = sum(1 for o in orgs if o.get("plan") != "free")
        total_credits = sum(o.get("credit_balance", 0) for o in orgs)
        mrr_estimate  = sum(
            PLAN_PRICES_MONTHLY.get(o.get("plan", "free"), 0) // 100
            for o in orgs
            if o.get("subscription_status") in ("active", "trialing")
        )

    return {
        "orgs": orgs,
        "summary": {
            "total_orgs": total_orgs,
            "paying_orgs": paying_orgs,
            "total_credits_outstanding": total_credits,
            "mrr_estimate_inr": mrr_estimate,
        },
    }


@app.post("/admin/add-credits")
async def admin_add_credits(request: Request):
    """Manually add credits to an organization.
    Body: {org_id, amount, reason}
    Protected by X-Admin-Token header.
    """
    _admin_auth(request)
    body   = await request.json()
    org_id = body.get("org_id", "")
    amount = int(body.get("amount", 0))
    reason = body.get("reason", "Admin grant")
    if not org_id or amount <= 0:
        raise HTTPException(status_code=400, detail="org_id and positive amount required")

    with get_conn() as conn:
        new_balance = _grant_credits(conn, org_id, None, amount, "admin_grant",
                                     description=f"Admin: {reason}")

    return {"ok": True, "org_id": org_id, "credits_added": amount, "new_balance": new_balance}


@app.post("/admin/set-plan")
async def admin_set_plan(request: Request):
    """Change an org's plan tier and optionally grant the monthly credit allocation.
    Body: {org_id, plan, grant_monthly_credits: true|false}
    Protected by X-Admin-Token header.
    """
    _admin_auth(request)
    body  = await request.json()
    org_id = body.get("org_id", "")
    plan   = body.get("plan", "free")
    grant  = body.get("grant_monthly_credits", True)
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id required")
    if plan not in VALID_PLANS:
        raise HTTPException(status_code=400, detail=f"plan must be one of {VALID_PLANS}")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE organizations SET plan = %s WHERE id = %s", (plan, org_id))
        conn.commit()
        credits_granted = 0
        if grant and PLAN_MONTHLY_CREDITS.get(plan, 0) > 0:
            credits_granted = PLAN_MONTHLY_CREDITS[plan]
            _grant_credits(conn, org_id, None, credits_granted, "admin_grant",
                           description=f"Plan set to {plan} — monthly credit allocation")

    return {"ok": True, "org_id": org_id, "plan": plan, "credits_granted": credits_granted}


@app.post("/admin/set-email-plan")
async def admin_set_email_plan(request: Request):
    """Set an org's email_plan. Body: {org_id, email_plan}. Plans: none/starter/pro/scale."""
    _admin_auth(request)
    body = await request.json()
    org_id = body.get("org_id", "")
    email_plan = body.get("email_plan", "starter")
    if not org_id:
        raise HTTPException(status_code=400, detail="org_id required")
    from services.agent_swarm.config import EMAIL_PLAN_LIMITS
    if email_plan not in EMAIL_PLAN_LIMITS:
        raise HTTPException(status_code=400, detail=f"email_plan must be one of {list(EMAIL_PLAN_LIMITS.keys())}")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE organizations SET email_plan=%s WHERE id=%s RETURNING id", (email_plan, org_id))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Org not found")
    return {"ok": True, "org_id": org_id, "email_plan": email_plan,
            "monthly_limit": EMAIL_PLAN_LIMITS[email_plan]}


@app.post("/admin/reset-onboarding")
async def admin_reset_onboarding(request: Request):
    """Reset onboarding_complete=false for a workspace (for testing).
    Body: {workspace_id}
    Protected by X-Admin-Token header.
    """
    _admin_auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE workspaces SET onboarding_complete = FALSE WHERE id = %s RETURNING id, name",
                (workspace_id,)
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"ok": True, "workspace_id": str(row[0]), "name": row[1]}


@app.post("/admin/claim-org")
async def admin_claim_org(request: Request):
    """Link a Clerk user ID to an existing org (for legacy migration).
    Body: {org_id, clerk_user_id}
    Protected by X-Admin-Token header.
    """
    _admin_auth(request)
    body          = await request.json()
    org_id        = body.get("org_id", "")
    clerk_user_id = body.get("clerk_user_id", "")
    if not org_id or not clerk_user_id:
        raise HTTPException(status_code=400, detail="org_id and clerk_user_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE organizations SET clerk_user_id = %s WHERE id = %s",
                (clerk_user_id, org_id),
            )
        conn.commit()

    return {"ok": True, "org_id": org_id, "clerk_user_id": clerk_user_id}


@app.post("/cron/billing/monthly-credits")
async def cron_billing_monthly_credits(request: Request):
    """Add monthly plan credits to all orgs on paid plans.
    Idempotent — checks credit_ledger for current month before adding.
    Protected by X-Cron-Token header.
    """
    _auth(request)
    import json as _json
    from datetime import datetime as _dt

    results = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, plan FROM organizations WHERE plan != 'free' AND plan IS NOT NULL"
            )
            orgs = cur.fetchall()

        for org_id, plan in orgs:
            monthly = PLAN_MONTHLY_CREDITS.get(plan, 0)
            if monthly <= 0:
                continue
            # Idempotent check: has monthly_plan credit been granted this calendar month?
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) FROM credit_ledger
                       WHERE org_id = %s AND type = 'monthly_plan'
                         AND created_at >= date_trunc('month', NOW())""",
                    (str(org_id),),
                )
                already = cur.fetchone()[0]
            if already > 0:
                results.append({"org_id": str(org_id), "plan": plan, "skipped": True})
                continue
            new_bal = _grant_credits(conn, str(org_id), None, monthly, "monthly_plan",
                                     description=f"Monthly credits for {plan} plan — {_dt.utcnow().strftime('%B %Y')}")
            results.append({"org_id": str(org_id), "plan": plan, "credits_added": monthly, "new_balance": new_bal})

    return {"ok": True, "processed": len(results), "results": results}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Workspace — Self-Serve Creation                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@app.post("/workspace/create")
async def workspace_create(request: Request):
    """Self-serve workspace + org creation. Grants 50 free signup credits.
    Body: {name, store_url?, workspace_type?}
    Returns: {workspace_id, org_id, credit_balance}
    """
    body = await request.json()
    name           = (body.get("name") or "").strip()
    store_url      = body.get("store_url", "")
    workspace_type = body.get("workspace_type", "d2c")
    clerk_user_id  = (body.get("clerk_user_id") or "").strip() or None
    if not name:
        raise HTTPException(status_code=400, detail="name required")

    import uuid as _uuid, re as _re
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Prevent duplicate org for same Clerk user
            if clerk_user_id:
                cur.execute(
                    "SELECT id FROM organizations WHERE clerk_user_id = %s LIMIT 1",
                    (clerk_user_id,),
                )
                existing = cur.fetchone()
                if existing:
                    raise HTTPException(status_code=409, detail="workspace_exists")
            # Create organization
            org_id = str(_uuid.uuid4())
            # Generate a unique slug from name + short id suffix
            base_slug = _re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'org'
            slug = f"{base_slug}-{org_id[:8]}"
            cur.execute(
                """INSERT INTO organizations (id, name, slug, plan, credit_balance, clerk_user_id)
                   VALUES (%s, %s, %s, 'free', 0, %s)""",
                (org_id, name, slug, clerk_user_id),
            )
            # Create workspace linked to org
            ws_id = str(_uuid.uuid4())
            cur.execute(
                """INSERT INTO workspaces (id, org_id, name, store_url, workspace_type, active)
                   VALUES (%s, %s, %s, %s, %s, TRUE)""",
                (ws_id, org_id, name, store_url or None, workspace_type),
            )
        conn.commit()
        # Grant 50 signup credits
        new_balance = _grant_credits(conn, org_id, ws_id, 50, "signup_grant",
                                     description="Welcome! 50 free credits to explore the platform")

    return {
        "ok": True,
        "workspace_id": ws_id,
        "org_id": org_id,
        "credit_balance": new_balance,
        "plan": "free",
    }


# ════════════════════════════════════════════════════════════════════════════
# EMAIL MARKETING MODULE
# ════════════════════════════════════════════════════════════════════════════

import hashlib as _hashlib
import time as _time


def _resend():
    from services.agent_swarm.connectors.resend import ResendConnector
    from services.agent_swarm.config import RESEND_API_KEY
    if not RESEND_API_KEY:
        raise HTTPException(status_code=503, detail="RESEND_API_KEY not configured")
    return ResendConnector(RESEND_API_KEY)


def _unsub_token(contact_id: str) -> str:
    from services.agent_swarm.config import EMAIL_UNSUB_SALT
    return _hashlib.sha256(f"{contact_id}{EMAIL_UNSUB_SALT}".encode()).hexdigest()


def _check_email_quota(conn, org_id: str, workspace_id: str, count: int):
    from services.agent_swarm.config import EMAIL_PLAN_LIMITS
    import datetime
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email_plan, monthly_emails_sent, email_month_reset, plan FROM organizations WHERE id=%s FOR UPDATE",
            (org_id,)
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Org not found")
    email_plan, used, reset_date, billing_plan = row[0], row[1], row[2], row[3]
    # Orgs on paid billing plans (growth/agency/pro) get starter email access if not explicitly set
    if (not email_plan or email_plan == "none") and billing_plan in ("growth", "agency", "pro", "scale"):
        email_plan = "starter"
        with conn.cursor() as cur2:
            cur2.execute("UPDATE organizations SET email_plan='starter' WHERE id=%s", (org_id,))
    plan = email_plan or "none"
    limit = EMAIL_PLAN_LIMITS.get(plan, 0)
    if limit == 0:
        raise HTTPException(status_code=402, detail={"error": "no_email_plan", "message": "Upgrade to an email plan to send campaigns."})
    import datetime as _dt
    now_month = _dt.date.today().replace(day=1)
    if reset_date is None or reset_date < now_month:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE organizations SET monthly_emails_sent=0, email_month_reset=%s WHERE id=%s",
                (now_month, org_id)
            )
        used = 0
    if used + count > limit:
        raise HTTPException(status_code=402, detail={
            "error": "email_quota_exceeded",
            "limit": limit, "used": used, "requested": count,
            "message": f"Monthly email limit reached ({used}/{limit}). Upgrade your email plan."
        })


# ── Domain management ────────────────────────────────────────────────────────

@app.post("/email/domain/add")
async def email_domain_add(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    domain = body.get("domain", "").strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
    if not workspace_id or not domain:
        raise HTTPException(status_code=400, detail="workspace_id and domain required")
    try:
        with get_conn() as conn:
            rc = _resend()
            data = rc.create_domain(domain)
            resend_id = data.get("id", "")
            dns_records = data.get("records", [])
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO email_domains (workspace_id, domain, resend_domain_id, dns_records, status)
                       VALUES (%s, %s, %s, %s, 'pending')
                       ON CONFLICT (workspace_id, domain) DO UPDATE
                         SET resend_domain_id=EXCLUDED.resend_domain_id,
                             dns_records=EXCLUDED.dns_records,
                             status='pending', verified=FALSE, updated_at=NOW()
                       RETURNING id""",
                    (workspace_id, domain, resend_id, json.dumps(dns_records))
                )
                row = cur.fetchone()
            return {"id": str(row[0]), "domain": domain, "dns_records": dns_records, "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email/domain/status")
async def email_domain_status(request: Request, workspace_id: str = None):
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, domain, resend_domain_id, dns_records, verified, status, created_at FROM email_domains WHERE workspace_id=%s ORDER BY created_at",
                (workspace_id,)
            )
            rows = cur.fetchall()
        domains = []
        rc = _resend() if rows else None
        for r in rows:
            dom_id, dom, resend_id, dns_recs, verified, status, created_at = r
            if not verified and resend_id and rc:
                try:
                    rd = rc.verify_domain(resend_id)  # triggers Resend DNS check then reads status
                    new_status = rd.get("status", status)
                    new_verified = new_status == "verified"
                    if new_status != status or new_verified != verified:
                        with conn.cursor() as cur2:
                            cur2.execute(
                                "UPDATE email_domains SET status=%s, verified=%s, updated_at=NOW() WHERE id=%s",
                                (new_status, new_verified, dom_id)
                            )
                        status, verified = new_status, new_verified
                except Exception:
                    pass
            domains.append({
                "id": str(dom_id), "domain": dom,
                "verified": verified, "status": status,
                "dns_records": dns_recs if isinstance(dns_recs, list) else [],
                "created_at": created_at.isoformat() if created_at else None,
            })
        return {"domains": domains}


@app.post("/email/domain/verify")
async def email_domain_verify(request: Request):
    _auth(request)
    body = await request.json()
    domain_id = body.get("domain_id", "")
    workspace_id = body.get("workspace_id", "")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT resend_domain_id FROM email_domains WHERE id=%s AND workspace_id=%s", (domain_id, workspace_id))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Domain not found")
        rc = _resend()
        # Trigger Resend to re-check DNS, then read updated status
        rd = rc.verify_domain(row[0])
        status = rd.get("status", "pending")
        verified = status == "verified"
        with conn.cursor() as cur:
            cur.execute("UPDATE email_domains SET status=%s, verified=%s, updated_at=NOW() WHERE id=%s", (status, verified, domain_id))
        return {"ok": True, "verified": verified, "status": status}


@app.post("/email/domain/check-dns")
async def email_domain_check_dns(request: Request):
    """
    For each expected DNS record (from Resend), do a live DNS lookup via
    Google DNS-over-HTTPS and report match/mismatch per record.
    """
    _auth(request)
    body = await request.json()
    domain_id = body.get("domain_id", "")
    workspace_id = body.get("workspace_id", "")
    if not domain_id or not workspace_id:
        raise HTTPException(status_code=400, detail="domain_id and workspace_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT resend_domain_id FROM email_domains WHERE id=%s AND workspace_id=%s",
                (domain_id, workspace_id)
            )
            row = cur.fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Domain not found")

    rc = _resend()
    rd = rc.get_domain(row[0])
    expected_records = rd.get("records", [])

    def _dns_lookup(name: str, rtype: str) -> list:
        try:
            import httpx as _httpx
            r = _httpx.get(
                "https://dns.google/resolve",
                params={"name": name, "type": rtype},
                timeout=5,
            )
            answers = r.json().get("Answer", [])
            # Strip trailing dots, lowercase for comparison
            return [a.get("data", "").rstrip(".").lower() for a in answers]
        except Exception:
            return []

    results = []
    for rec in expected_records:
        rtype  = rec.get("type", "TXT").upper()
        name   = rec.get("name", "")
        domain_name = rd.get("name", "")
        # Resend returns relative names (without the domain). Build FQDN.
        if name and domain_name and not name.endswith(domain_name):
            fqdn = f"{name}.{domain_name}"
        else:
            fqdn = name
        expected_val = rec.get("value", "").strip().rstrip(".")

        found_vals = _dns_lookup(fqdn, rtype)
        # Normalize expected for comparison
        expected_norm = expected_val.lower()
        if rtype == "TXT":
            # DNS returns quoted strings sometimes, strip quotes
            found_vals = [v.strip('"') for v in found_vals]
        matched = any(expected_norm in v.lower() or v.lower() in expected_norm for v in found_vals)

        results.append({
            "record": rec.get("record", rtype),
            "type": rtype,
            "name": name,
            "fqdn": fqdn,
            "expected": expected_val,
            "found": found_vals,
            "match": matched,
            "status": rec.get("status", "pending"),
        })

    all_match = all(r["match"] for r in results)
    return {"records": results, "all_match": all_match, "domain": rd.get("name")}


@app.get("/email/domain/debug")
async def email_domain_debug(request: Request, workspace_id: str = None):
    """Debug endpoint — shows raw DB record + Resend API status for each domain."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    results = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, domain, resend_domain_id, verified, status FROM email_domains WHERE workspace_id=%s",
                (workspace_id,)
            )
            rows = cur.fetchall()
    rc = _resend()
    for row in rows:
        dom_id, dom, resend_id, verified, status = row
        resend_data = None
        resend_error = None
        verify_trigger = None
        if resend_id:
            try:
                # 1. Try triggering verify
                vr = rc.session.post(f"{rc.BASE}/domains/{resend_id}/verify", timeout=15)
                verify_trigger = {"status_code": vr.status_code, "body": vr.text[:500]}
            except Exception as ex:
                verify_trigger = {"error": str(ex)}
            try:
                # 2. Read current domain status
                resend_data = rc.get_domain(resend_id)
            except Exception as ex:
                resend_error = str(ex)
        results.append({
            "domain": dom,
            "db_id": str(dom_id),
            "resend_domain_id": resend_id,
            "db_verified": verified,
            "db_status": status,
            "resend_verify_trigger": verify_trigger,
            "resend_current": resend_data,
            "resend_error": resend_error,
        })
    return {"domains": results}


@app.delete("/email/domain/remove")
async def email_domain_remove(request: Request):
    _auth(request)
    body = await request.json()
    domain_id = body.get("domain_id", "")
    workspace_id = body.get("workspace_id", "")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT resend_domain_id FROM email_domains WHERE id=%s AND workspace_id=%s", (domain_id, workspace_id))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Domain not found")
        try:
            _resend().delete_domain(row[0])
        except Exception:
            pass
        with conn.cursor() as cur:
            cur.execute("DELETE FROM email_domains WHERE id=%s AND workspace_id=%s", (domain_id, workspace_id))
        return {"ok": True}


# ── Contact lists ────────────────────────────────────────────────────────────

@app.post("/email/lists/create")
async def email_list_create(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    name = body.get("name", "").strip()
    description = body.get("description", "")
    if not workspace_id or not name:
        raise HTTPException(status_code=400, detail="workspace_id and name required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO email_lists (workspace_id, name, description) VALUES (%s,%s,%s) RETURNING id, created_at",
                (workspace_id, name, description)
            )
            row = cur.fetchone()
        return {"id": str(row[0]), "name": name, "description": description, "contact_count": 0, "created_at": row[1].isoformat()}


@app.get("/email/lists")
async def email_lists_get(request: Request, workspace_id: str = None):
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, source, contact_count, created_at FROM email_lists WHERE workspace_id=%s ORDER BY created_at DESC",
                (workspace_id,)
            )
            rows = cur.fetchall()
        return {"lists": [{"id": str(r[0]), "name": r[1], "description": r[2], "source": r[3], "contact_count": r[4], "created_at": r[5].isoformat()} for r in rows]}


@app.delete("/email/lists/{list_id}")
async def email_list_delete(request: Request, list_id: str):
    _auth(request)
    workspace_id = request.query_params.get("workspace_id", "")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM email_lists WHERE id=%s AND workspace_id=%s", (list_id, workspace_id))
        return {"ok": True}


@app.post("/email/lists/import-csv")
async def email_list_import_csv(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    list_id = body.get("list_id", "")
    rows = body.get("rows", [])
    if not workspace_id or not list_id or not rows:
        raise HTTPException(status_code=400, detail="workspace_id, list_id, rows required")

    imported = duplicates = 0
    errors = []
    import uuid as _uuid
    with get_conn() as conn:
        for row in rows:
            email = (row.get("email") or "").strip().lower()
            if not email or "@" not in email:
                errors.append({"email": email, "reason": "invalid email"})
                continue
            first_name = row.get("first_name") or row.get("First Name") or row.get("firstname") or ""
            last_name  = row.get("last_name")  or row.get("Last Name")  or row.get("lastname")  or ""
            known = {"email", "first_name", "last_name", "firstname", "lastname", "First Name", "Last Name"}
            custom = {k: v for k, v in row.items() if k not in known and v}
            contact_id = str(_uuid.uuid4())
            token = _unsub_token(contact_id)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO email_contacts
                           (id, workspace_id, list_id, email, first_name, last_name, custom_fields, source, unsubscribe_token)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,'csv',%s)
                           ON CONFLICT (workspace_id, list_id, email) DO UPDATE
                             SET first_name=EXCLUDED.first_name, last_name=EXCLUDED.last_name,
                                 custom_fields=EXCLUDED.custom_fields, updated_at=NOW()
                           RETURNING (xmax=0)""",
                        (contact_id, workspace_id, list_id, email, first_name, last_name, json.dumps(custom), token)
                    )
                    is_new = cur.fetchone()[0]
                if is_new:
                    imported += 1
                else:
                    duplicates += 1
            except Exception as e:
                errors.append({"email": email, "reason": str(e)})
                conn.rollback()
                continue

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE email_lists SET contact_count=(SELECT COUNT(*) FROM email_contacts WHERE list_id=%s AND NOT unsubscribed), updated_at=NOW() WHERE id=%s",
                (list_id, list_id)
            )
        return {"imported": imported, "duplicates": duplicates, "errors": errors}


@app.get("/email/contacts")
async def email_contacts_get(request: Request, workspace_id: str = None, list_id: str = None, page: int = 1, limit: int = 50):
    _auth(request)
    if not workspace_id or not list_id:
        raise HTTPException(status_code=400, detail="workspace_id and list_id required")
    offset = (page - 1) * limit
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM email_contacts WHERE workspace_id=%s AND list_id=%s", (workspace_id, list_id))
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT id, email, first_name, last_name, unsubscribed, bounced, source, created_at FROM email_contacts WHERE workspace_id=%s AND list_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (workspace_id, list_id, limit, offset)
            )
            rows = cur.fetchall()
    contacts = [{"id": str(r[0]), "email": r[1], "first_name": r[2], "last_name": r[3], "unsubscribed": r[4], "bounced": r[5], "source": r[6], "created_at": r[7].isoformat()} for r in rows]
    return {"contacts": contacts, "total": total, "page": page, "limit": limit}


# ── AI Email Composer ────────────────────────────────────────────────────────

@app.post("/email/scrape-product")
async def email_scrape_product(request: Request):
    """
    Scrape any product URL and return structured data.
    Tries in order: JSON-LD Product schema → Open Graph tags → meta/h1 fallbacks.
    Returns {name, description, price, currency, images[]}
    """
    _auth(request)
    body = await request.json()
    url = (body.get("url") or "").strip()
    workspace_id = body.get("workspace_id", "")
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    if not url.startswith("http"):
        url = "https://" + url

    import re as _re
    import requests as _requests
    from bs4 import BeautifulSoup as _BS
    from urllib.parse import urlparse as _urlparse

    # 0. Look up in our own products catalog first (most reliable)
    if workspace_id:
        try:
            url_handle = url.rstrip("/").split("/")[-1].split("?")[0].lower()
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT name, description, price_inr, images, key_features, unique_selling_prop
                           FROM products
                           WHERE workspace_id=%s AND (
                               product_url ILIKE %s OR
                               LOWER(source_product_id) LIKE %s OR
                               LOWER(name) LIKE %s
                           ) AND active=true
                           ORDER BY created_at DESC LIMIT 1""",
                        (workspace_id, f"%{url_handle}%", f"%{url_handle}%", f"%{url_handle.replace('-', ' ')}%")
                    )
                    prod_row = cur.fetchone()
            if prod_row:
                p_name, p_desc, p_price, p_images, p_features, p_usp = prod_row
                imgs = [i.get("url") for i in (p_images or []) if i.get("url")]
                # Build rich description from features + USP
                desc_parts = []
                if p_desc: desc_parts.append(p_desc)
                if p_usp: desc_parts.append(f"USP: {p_usp}")
                if p_features: desc_parts.append("Key features: " + ", ".join(p_features))
                return {
                    "name": p_name or "",
                    "description": " ".join(desc_parts),
                    "price": f"₹{int(p_price):,}" if p_price else "",
                    "currency": "INR",
                    "images": imgs[:6],
                }
        except Exception:
            pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    parsed_url = _urlparse(url)
    store_domain = parsed_url.netloc.lower().replace("www.", "")  # e.g. agatsaone.com

    # 1. Try Shopify Admin API if we have a stored token for this domain
    shopify_data = None
    if "/products/" in url:
        handle = parsed_url.path.rstrip("/").split("/products/")[-1].split("?")[0]
        # Check for stored Shopify connection matching this domain
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT access_token, shop_domain FROM shopify_connections WHERE shop_domain ILIKE %s OR shop_domain ILIKE %s LIMIT 1",
                        (f"%{store_domain}%", f"%{store_domain.split('.')[0]}%")
                    )
                    sc_row = cur.fetchone()
            if sc_row:
                admin_token, shop_domain_stored = sc_row
                api_url = f"https://{shop_domain_stored}/admin/api/2024-01/products.json?handle={handle}&fields=title,body_html,variants,images"
                r = _requests.get(api_url, headers={"X-Shopify-Access-Token": admin_token}, timeout=10)
                if r.ok:
                    prods = r.json().get("products", [])
                    if prods:
                        pj = prods[0]
                        imgs = [img.get("src", "") for img in pj.get("images", []) if img.get("src")]
                        variants = pj.get("variants", [{}])
                        price = variants[0].get("price", "") if variants else ""
                        shopify_data = {
                            "name": pj.get("title", ""),
                            "description": _BS(pj.get("body_html") or "", "lxml").get_text(separator=" ", strip=True),
                            "price": f"₹{price}" if price else "",
                            "currency": "INR",
                            "images": imgs[:6],
                        }
        except Exception:
            pass

    # 1b. Fallback: try public Shopify product.json (works for non-headless stores)
    if not shopify_data and "/products/" in url:
        try:
            json_url = _re.sub(r'\?.*$', '', url.rstrip('/')) + ".json"
            r = _requests.get(json_url, headers=headers, timeout=10)
            if r.ok and r.headers.get("content-type", "").startswith("application/json"):
                pj = r.json().get("product", {})
                if pj and pj.get("title"):
                    imgs = [img.get("src", "") for img in pj.get("images", []) if img.get("src")]
                    variants = pj.get("variants", [{}])
                    price = variants[0].get("price", "") if variants else ""
                    shopify_data = {
                        "name": pj.get("title", ""),
                        "description": _BS(pj.get("body_html") or "", "lxml").get_text(separator=" ", strip=True),
                        "price": price,
                        "currency": "INR",
                        "images": imgs[:6],
                    }
        except Exception:
            pass

    if shopify_data:
        return shopify_data

    # 2. Fetch the HTML page
    try:
        r = _requests.get(url, headers=headers, timeout=12, allow_redirects=True)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not fetch URL: {e}")

    soup = _BS(html, "lxml")

    # 3. Try JSON-LD Product schema
    name = description = price = currency = ""
    images = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            # handle @graph arrays
            items = ld if isinstance(ld, list) else ld.get("@graph", [ld])
            for item in items:
                if item.get("@type") in ("Product", "product"):
                    name = name or item.get("name", "")
                    description = description or item.get("description", "")
                    # images
                    img_field = item.get("image", [])
                    if isinstance(img_field, str):
                        images.append(img_field)
                    elif isinstance(img_field, list):
                        images += [i if isinstance(i, str) else i.get("url", "") for i in img_field]
                    elif isinstance(img_field, dict):
                        images.append(img_field.get("url", ""))
                    # price
                    offers = item.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    price = price or str(offers.get("price", ""))
                    currency = currency or offers.get("priceCurrency", "INR")
        except Exception:
            pass

    # 4. Open Graph fallbacks
    def og(prop):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        return (tag.get("content") or "").strip() if tag else ""

    name = name or og("og:title") or (soup.find("h1") or {}).get_text(strip=True)
    description = description or og("og:description") or og("description")
    if not images:
        og_img = og("og:image")
        skip_og = ("icon", "logo", "favicon", "badge", "1x1", "pixel")
        if og_img and not any(t in og_img.lower() for t in skip_og):
            images.append(og_img)

    # 5. Collect additional product images from page (look for product-image classes)
    if len(images) < 4:
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue
            # Make absolute
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                    src = f"{parsed_url.scheme}://{parsed_url.netloc}{src}"
            # Filter: skip tiny icons/logos, keep product-looking images
            skip_terms = ("icon", "logo", "badge", "flag", "pixel", "tracking", "1x1", "spinner", "loader", "avatar", "favicon")
            if any(t in src.lower() for t in skip_terms):
                continue
            w = img.get("width") or img.get("data-width") or ""
            if w and int(_re.sub(r'\D', '', str(w)) or 0) < 100:
                continue
            if src not in images:
                images.append(src)
            if len(images) >= 6:
                break

    # 6. Jina AI fallback — for JS-rendered / headless stores
    if not name or not images:
        try:
            import requests as _jreq
            jina_url = f"https://r.jina.ai/{url}"
            jr = _jreq.get(jina_url, headers={"Accept": "application/json", "X-No-Cache": "true"}, timeout=20)
            if jr.ok:
                jd = jr.json()
                jina_data = jd.get("data", {})
                if not name:
                    name = jina_data.get("title", "")
                if not description:
                    description = (jina_data.get("content") or "")[:800]
                if not images:
                    jina_imgs = jina_data.get("images", {})
                    skip_terms = ("icon", "logo", "badge", "favicon", "pixel", "tracking", "1x1")
                    for img_url in list(jina_imgs.keys()):
                        if not any(t in img_url.lower() for t in skip_terms):
                            images.append(img_url)
                        if len(images) >= 6:
                            break
        except Exception:
            pass

    return {
        "name": (name or "").strip(),
        "description": (description or "").strip(),
        "price": (price or "").strip(),
        "currency": currency or "INR",
        "images": [i for i in images if i][:6],
    }


@app.post("/email/campaign/compose-ai")
async def email_compose_ai(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id    = body.get("workspace_id", "")
    product_name    = body.get("product_name", "")
    product_description = body.get("product_description", "")
    product_price   = body.get("product_price", "")
    product_url     = body.get("product_url", "")
    campaign_context = body.get("campaign_context", "")   # "Holi sale, 20% off, Mar 20-25"
    goal            = body.get("goal", "drive_purchase")
    tone            = body.get("tone", "friendly")
    from_name       = body.get("from_name", "")
    cta_text        = body.get("cta_text", "Shop Now")
    product_images  = body.get("product_images", [])      # list of image URLs

    if not workspace_id or not product_name:
        raise HTTPException(status_code=400, detail="workspace_id and product_name required")

    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        _check_and_deduct_credits(conn, org_id, workspace_id, 3, "email_compose")

    import datetime as _dt
    current_year = _dt.date.today().year

    # ── Goal & Tone descriptions ──────────────────────────────────────────────
    goal_map = {
        "drive_purchase":  "Convert readers into buyers — focus on desire, benefits, and urgency",
        "product_launch":  "Announce a new product — build excitement, highlight what's new, create FOMO",
        "re_engage":       "Win back inactive subscribers — acknowledge the gap, offer a reason to return",
        "cart_recovery":   "Recover abandoned carts — remind, reassure (trust/returns), nudge to complete",
        "announce_offer":  "Announce a sale or limited-time offer — clear discount, deadline, CTA",
        "newsletter":      "Provide value and updates — informative tone, soft sell, keep them engaged",
    }
    tone_map = {
        "friendly":     "Warm, conversational, like a helpful friend. Contractions OK. Emoji sparingly.",
        "professional": "Polished, credible, business-like. No slang. Precise language.",
        "urgent":       "Time-sensitive, action-driven. Short sentences. Strong verbs. Deadline-forward.",
        "playful":      "Fun, punchy, maybe a bit cheeky. Light humor where appropriate.",
        "luxurious":    "Premium, aspirational, sensory. Evocative adjectives. Confidence, not pushy.",
    }

    # ── Images section for prompt ─────────────────────────────────────────────
    if product_images:
        hero_image = product_images[0]
        extra_images = product_images[1:3]
        img_instructions = f"""PRODUCT IMAGES PROVIDED — YOU MUST USE THEM:
- Hero image (place at top, full-width): {hero_image}
- Additional images (embed inline): {', '.join(extra_images) if extra_images else 'none'}

In the HTML, place the hero image immediately after the header bar as a full-width block:
<img src="{hero_image}" alt="{product_name}" style="width:100%;max-width:600px;height:auto;display:block;" />
Embed additional images between content sections where they add visual context."""
    else:
        img_instructions = """NO PRODUCT IMAGES PROVIDED.
Instead of leaving a blank space, design a visually rich hero block using a branded gradient background
(e.g. background: linear-gradient(135deg, #4F46E5, #7C3AED)) with the product name as large white headline text.
This makes the email look beautiful even without photos."""

    price_line = f"Price: {product_price}" if product_price else ""
    url_line   = f"Product URL: {product_url}" if product_url else ""

    prompt = f"""You are a world-class email marketing copywriter specialising in Indian D2C and health/wellness brands.
Your emails consistently achieve 40%+ open rates and 8%+ click-through rates.
Think step-by-step before writing. Read every input carefully.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRODUCT INFORMATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Name: {product_name}
{price_line}
{url_line}
Description:
{product_description or "(none provided — infer benefits from the product name and context)"}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAMPAIGN PURPOSE & CONTEXT  ← READ THIS CAREFULLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{campaign_context or "(No specific context provided — write a general promotional email for this product)"}

This context defines the REASON the email is being sent. If there is a sale, event, deadline, or specific
audience segment mentioned here, it must be prominently reflected in the subject line, headline, and body copy.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EMAIL PARAMETERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Goal: {goal_map.get(goal, goal)}
Tone: {tone_map.get(tone, tone)}
Sender / Brand name: {from_name or "the brand"}
CTA button text: "{cta_text}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMAGES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{img_instructions}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR DELIVERABLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. SUBJECT LINE
   - Maximum 52 characters (gets cut off on mobile beyond this)
   - Must be curiosity-driven OR benefit-driven OR urgency-driven based on the goal
   - If campaign context mentions a specific offer, date, or event — reference it
   - Avoid spam trigger words: free, winner, congratulations, !!!, ALL CAPS
   - A/B test mindset: write the single best option

2. PREHEADER TEXT
   - 80-90 characters
   - Complements (does NOT repeat) the subject line — creates a "1-2 punch" effect
   - Previewed by email clients below the subject in the inbox

3. HTML EMAIL — Complete, standalone, production-ready HTML
   STRUCTURE (follow exactly):
   a) Outer wrapper: <table width="100%" bgcolor="#f4f4f7">
   b) Inner container: <table width="600" style="max-width:600px;margin:0 auto;background:#ffffff">
   c) Header bar: brand name in a colored strip (#4F46E5 or brand-appropriate)
   d) Hero section: product image OR branded gradient block (per instructions above)
   e) Headline: compelling H1-style text (NOT just the product name — speak to the customer's pain/desire)
   f) Body copy: 2-3 short paragraphs following this copywriting arc:
      → Para 1: Identify the reader's problem or desire (empathy hook)
      → Para 2: Introduce the product as the solution with 2-3 specific benefits
      → Para 3: If there's a specific offer/context, highlight it with urgency
   g) Bullet points: 3 key product benefits with checkmark (✓) or bullet
   h) CTA button: large, centered, styled — background #4F46E5, white text, border-radius 8px, padding 16px 32px
      Link href="#" (user will replace with actual URL)
   i) If price provided, show it prominently near the CTA
   j) Social proof line (if applicable): e.g. "Trusted by 50,000+ customers"
   k) Footer: "{from_name}" | © {current_year} | <a href="{{{{UNSUBSCRIBE_URL}}}}">Unsubscribe</a>

   TECHNICAL RULES (non-negotiable for email client compatibility):
   - ALL CSS must be INLINE — no <style> blocks (Gmail, Outlook strip them)
   - Use <table> layouts for structure, not <div> with flexbox (Outlook doesn't support flexbox)
   - Images: always include width, height="auto", display:block, max-width:100%
   - Font stack: Arial, Helvetica, sans-serif (no Google Fonts — blocked by many email clients)
   - Line-height: 1.6 on body text for readability
   - Include {{{{UNSUBSCRIBE_URL}}}} exactly once in the footer

4. PLAIN TEXT VERSION
   Clean plain text. Include all key content. End with unsubscribe line: Unsubscribe: {{{{UNSUBSCRIBE_URL}}}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use EXACTLY these delimiters — do not use JSON or markdown fences.
The HTML section is large so we avoid JSON encoding issues.

===SUBJECT===
(subject line here)
===PREHEADER===
(preheader text here)
===HTML===
(full HTML email here)
===TEXT===
(plain text version here)
===END==="""

    import anthropic as _anthropic
    from services.agent_swarm.config import ANTHROPIC_API_KEY as _AKEY, CLAUDE_MODEL as _MODEL
    client = _anthropic.Anthropic(api_key=_AKEY)
    msg = client.messages.create(
        model=_MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()

    def _extract(raw_text: str, key: str, next_key: str) -> str:
        start_tag = f"==={key}==="
        end_tag   = f"==={next_key}==="
        s = raw_text.find(start_tag)
        e = raw_text.find(end_tag)
        if s == -1:
            return ""
        content = raw_text[s + len(start_tag): e if e != -1 else None]
        return content.strip()

    subject  = _extract(raw, "SUBJECT",  "PREHEADER")
    preheader = _extract(raw, "PREHEADER", "HTML")
    html_body = _extract(raw, "HTML",     "TEXT")
    text_body = _extract(raw, "TEXT",     "END")

    if not html_body:
        # Fallback: Claude may have used JSON despite instructions — try parsing
        try:
            import re as _re
            clean = raw
            if clean.startswith("```"):
                clean = _re.sub(r'^```[a-z]*\n?', '', clean).rstrip('`').strip()
            parsed = json.loads(clean)
            subject   = parsed.get("subject", subject)
            preheader = parsed.get("preheader", preheader)
            html_body = parsed.get("html_body", "")
            text_body = parsed.get("text_body", "")
        except Exception:
            pass

    if not html_body:
        raise HTTPException(status_code=500, detail="AI failed to generate email content — please try again")

    return {
        "subject":   subject,
        "preheader": preheader,
        "html_body": html_body,
        "text_body": text_body,
    }


# ── Campaign CRUD ────────────────────────────────────────────────────────────

@app.post("/email/campaign/create")
async def email_campaign_create(request: Request):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    list_id      = body.get("list_id", "")
    domain_id    = body.get("domain_id", "")
    name         = body.get("name", "").strip()
    subject      = body.get("subject", "").strip()
    from_name    = body.get("from_name", "").strip()
    from_email   = body.get("from_email", "").strip()
    reply_to     = body.get("reply_to", "")
    html_body    = body.get("html_body", "")
    text_body    = body.get("text_body", "")
    scheduled_at = body.get("scheduled_at")

    if not all([workspace_id, list_id, domain_id, name, subject, from_name, from_email, html_body]):
        raise HTTPException(status_code=400, detail="Missing required fields")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT verified FROM email_domains WHERE id=%s AND workspace_id=%s", (domain_id, workspace_id))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Domain not found")
        if not row[0]:
            raise HTTPException(status_code=400, detail="Domain not yet verified.")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM email_contacts WHERE list_id=%s AND NOT unsubscribed AND NOT bounced", (list_id,))
            total = cur.fetchone()[0]

        status = "scheduled" if scheduled_at else "draft"
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO email_campaigns
                   (workspace_id, list_id, domain_id, name, subject, from_name, from_email, reply_to, html_body, text_body, status, scheduled_at, total_recipients)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, created_at""",
                (workspace_id, list_id, domain_id, name, subject, from_name, from_email,
                 reply_to or None, html_body, text_body or None, status, scheduled_at or None, total)
            )
            row = cur.fetchone()
        return {"id": str(row[0]), "name": name, "status": status, "total_recipients": total, "created_at": row[1].isoformat()}


@app.get("/email/campaigns")
async def email_campaigns_list(request: Request, workspace_id: str = None, limit: int = 20, offset: int = 0):
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, subject, from_email, status, total_recipients, sent_count,
                          open_count, click_count, bounce_count, unsub_count, created_at, sent_at, scheduled_at
                   FROM email_campaigns WHERE workspace_id=%s ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                (workspace_id, limit, offset)
            )
            rows = cur.fetchall()
    campaigns = []
    for r in rows:
        sent = r[6] or 0
        campaigns.append({
            "id": str(r[0]), "name": r[1], "subject": r[2], "from_email": r[3],
            "status": r[4], "total_recipients": r[5], "sent_count": sent,
            "open_count": r[7], "click_count": r[8], "bounce_count": r[9], "unsub_count": r[10],
            "open_rate":  round(r[7] / sent * 100, 1) if sent else 0,
            "click_rate": round(r[8] / sent * 100, 1) if sent else 0,
            "created_at": r[11].isoformat() if r[11] else None,
            "sent_at":    r[12].isoformat() if r[12] else None,
            "scheduled_at": r[13].isoformat() if r[13] else None,
        })
    return {"campaigns": campaigns}


@app.get("/email/campaign/{campaign_id}/stats")
async def email_campaign_stats(request: Request, campaign_id: str, workspace_id: str = None):
    _auth(request)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, subject, from_email, status, total_recipients, sent_count,
                          open_count, click_count, bounce_count, unsub_count, sent_at
                   FROM email_campaigns WHERE id=%s AND workspace_id=%s""",
                (campaign_id, workspace_id)
            )
            c = cur.fetchone()
        if not c:
            raise HTTPException(status_code=404, detail="Campaign not found")
        sent = c[6] or 0
        summary = {
            "sent": sent, "opened": c[7], "clicked": c[8], "bounced": c[9], "unsubscribed": c[10],
            "open_rate":   round(c[7] / sent * 100, 1) if sent else 0,
            "click_rate":  round(c[8] / sent * 100, 1) if sent else 0,
            "bounce_rate": round(c[9] / sent * 100, 1) if sent else 0,
        }
        with conn.cursor() as cur:
            cur.execute(
                """SELECT date_trunc('hour', occurred_at),
                          SUM(CASE WHEN event_type='email.opened' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN event_type='email.clicked' THEN 1 ELSE 0 END)
                   FROM email_events WHERE campaign_id=%s GROUP BY 1 ORDER BY 1""",
                (campaign_id,)
            )
            timeline = [{"hour": r[0].isoformat(), "opens": int(r[1]), "clicks": int(r[2])} for r in cur.fetchall()]
        with conn.cursor() as cur:
            cur.execute(
                """SELECT event_data->>'click_url', COUNT(*) FROM email_events
                   WHERE campaign_id=%s AND event_type='email.clicked' AND event_data->>'click_url' IS NOT NULL
                   GROUP BY 1 ORDER BY 2 DESC LIMIT 10""",
                (campaign_id,)
            )
            top_links = [{"url": r[0], "click_count": int(r[1])} for r in cur.fetchall()]
        return {
            "campaign": {"id": str(c[0]), "name": c[1], "subject": c[2], "from_email": c[3],
                         "status": c[4], "total_recipients": c[5], "sent_count": sent,
                         "sent_at": c[11].isoformat() if c[11] else None},
            "summary": summary, "timeline": timeline, "top_links": top_links,
        }


@app.delete("/email/campaign/{campaign_id}")
async def email_campaign_delete(request: Request, campaign_id: str):
    _auth(request)
    workspace_id = request.query_params.get("workspace_id", "")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM email_campaigns WHERE id=%s AND workspace_id=%s", (campaign_id, workspace_id))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if row[0] not in ("draft", "failed"):
            raise HTTPException(status_code=400, detail="Only draft or failed campaigns can be deleted")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM email_campaigns WHERE id=%s", (campaign_id,))
        return {"ok": True}


# ── Campaign send (background) ────────────────────────────────────────────────

async def _send_campaign_bg(campaign_id: str, workspace_id: str, org_id: str):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT list_id, subject, from_name, from_email, reply_to, html_body, text_body FROM email_campaigns WHERE id=%s",
                    (campaign_id,)
                )
                c = cur.fetchone()
            if not c:
                return
            list_id, subject, from_name, from_email, reply_to, html_body, text_body = c

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, email, first_name, unsubscribe_token FROM email_contacts WHERE list_id=%s AND NOT unsubscribed AND NOT bounced",
                    (list_id,)
                )
                contacts = cur.fetchall()

            total = len(contacts)
            with conn.cursor() as cur:
                cur.execute("UPDATE email_campaigns SET status='sending', total_recipients=%s, updated_at=NOW() WHERE id=%s", (total, campaign_id))
            conn.commit()

            from_field = f"{from_name} <{from_email}>"
            rc = _resend()
            unsub_base = "https://app.runwaystudios.co/unsubscribe"
            sent_count = failed_count = 0

            for i, (contact_id, email, first_name, unsub_token) in enumerate(contacts):
                contact_html = html_body.replace("{{UNSUBSCRIBE_URL}}", f"{unsub_base}?token={unsub_token}")
                contact_txt  = (text_body or "").replace("{{UNSUBSCRIBE_URL}}", f"{unsub_base}?token={unsub_token}")
                try:
                    msg_id = rc.send_email(
                        to=email, from_=from_field, subject=subject,
                        html=contact_html, text=contact_txt or None,
                        reply_to=reply_to or None,
                    )
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO email_send_log (campaign_id, contact_id, resend_message_id, status, sent_at)
                               VALUES (%s,%s,%s,'sent',NOW())
                               ON CONFLICT (campaign_id, contact_id) DO UPDATE
                                 SET resend_message_id=EXCLUDED.resend_message_id, status='sent', sent_at=NOW()""",
                            (campaign_id, str(contact_id), msg_id)
                        )
                    sent_count += 1
                except Exception as e:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO email_send_log (campaign_id, contact_id, status, error)
                               VALUES (%s,%s,'failed',%s)
                               ON CONFLICT (campaign_id, contact_id) DO UPDATE SET status='failed', error=EXCLUDED.error""",
                            (campaign_id, str(contact_id), str(e))
                        )
                    failed_count += 1

                if (i + 1) % 50 == 0:
                    conn.commit()
                    _time.sleep(0.1)

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE email_campaigns SET status='sent', sent_count=%s, failed_count=%s, sent_at=NOW(), updated_at=NOW() WHERE id=%s",
                    (sent_count, failed_count, campaign_id)
                )
                cur.execute(
                    "UPDATE organizations SET monthly_emails_sent=monthly_emails_sent+%s WHERE id=%s",
                    (sent_count, org_id)
                )
    except Exception as e:
        print(f"_send_campaign_bg error: {e}")
        try:
            with get_conn() as conn2:
                with conn2.cursor() as cur:
                    cur.execute("UPDATE email_campaigns SET status='failed', updated_at=NOW() WHERE id=%s", (campaign_id,))
        except Exception:
            pass


@app.post("/email/campaign/send")
async def email_campaign_send(request: Request, background_tasks: BackgroundTasks):
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    campaign_id  = body.get("campaign_id", "")
    if not workspace_id or not campaign_id:
        raise HTTPException(status_code=400, detail="workspace_id and campaign_id required")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, list_id FROM email_campaigns WHERE id=%s AND workspace_id=%s", (campaign_id, workspace_id))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Campaign not found")
        if row[0] not in ("draft", "scheduled"):
            raise HTTPException(status_code=400, detail=f"Campaign is already {row[0]}")
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM email_contacts WHERE list_id=%s AND NOT unsubscribed AND NOT bounced", (row[1],))
            count = cur.fetchone()[0]
        _check_email_quota(conn, org_id, workspace_id, count)

    background_tasks.add_task(_send_campaign_bg, campaign_id, workspace_id, org_id)
    return {"ok": True, "campaign_id": campaign_id, "status": "sending", "recipients": count}


# ── Email quota ────────────────────────────────────────────────────────────────

@app.get("/email/quota")
async def email_quota_get(request: Request, workspace_id: str = None):
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    from services.agent_swarm.config import EMAIL_PLAN_LIMITS
    import datetime as _dt
    with get_conn() as conn:
        org_id = _get_org_id_for_workspace(conn, workspace_id)
        with conn.cursor() as cur:
            cur.execute("SELECT email_plan, monthly_emails_sent, email_month_reset FROM organizations WHERE id=%s", (org_id,))
            row = cur.fetchone()
    plan, used, reset_date = row
    limit = EMAIL_PLAN_LIMITS.get(plan, 0)
    now_month = _dt.date.today().replace(day=1)
    if reset_date is None or reset_date < now_month:
        used = 0
    next_reset = (_dt.date.today().replace(day=1) + _dt.timedelta(days=32)).replace(day=1)
    return {
        "email_plan": plan, "monthly_limit": limit,
        "monthly_used": used, "monthly_remaining": max(0, limit - used),
        "reset_date": next_reset.isoformat(), "can_send": limit > 0 and used < limit,
    }


# ── Email image upload ────────────────────────────────────────────────────────

@app.post("/email/upload-image")
async def email_upload_image(request: Request):
    """
    Upload an image for use in email campaigns.
    Accepts multipart/form-data with field 'file'.
    Returns { url: "https://..." }
    """
    _auth(request)
    import uuid as _uuid, base64 as _b64
    from google.cloud import storage as _gcs
    from fastapi import UploadFile
    import shutil

    form = await request.form()
    file_field = form.get("file")
    if not file_field:
        raise HTTPException(status_code=400, detail="file field required")

    filename = getattr(file_field, "filename", "image.jpg")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        raise HTTPException(status_code=400, detail="Unsupported image type")

    content_type_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
    content_type = content_type_map.get(ext, "image/jpeg")

    try:
        img_data = await file_field.read()
        gcs_path = f"email-images/{_uuid.uuid4().hex}.{ext}"
        bucket_name = "wa-agency-raw-wa-ai-agency"
        _gcs_client = _gcs.Client()
        bucket = _gcs_client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(img_data, content_type=content_type)
        blob.make_public()
        return {"url": blob.public_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


# ── Resend webhook ────────────────────────────────────────────────────────────

@app.post("/email/webhook")
async def email_webhook(request: Request):
    from services.agent_swarm.config import RESEND_WEBHOOK_SECRET
    from services.agent_swarm.connectors.resend import ResendConnector
    body = await request.body()
    if RESEND_WEBHOOK_SECRET:
        if not ResendConnector.verify_webhook(
            body,
            request.headers.get("svix-id", ""),
            request.headers.get("svix-timestamp", ""),
            request.headers.get("svix-signature", ""),
            RESEND_WEBHOOK_SECRET,
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = json.loads(body)
    event_type = event.get("type", "")
    data = event.get("data", {})
    msg_id = data.get("email_id") or data.get("message_id") or ""

    try:
        with get_conn() as conn:
            campaign_id = contact_id = workspace_id = None
            if msg_id:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT sl.campaign_id, sl.contact_id, ec.workspace_id
                           FROM email_send_log sl JOIN email_campaigns ec ON ec.id=sl.campaign_id
                           WHERE sl.resend_message_id=%s LIMIT 1""",
                        (msg_id,)
                    )
                    row = cur.fetchone()
                if row:
                    campaign_id, contact_id, workspace_id = str(row[0]), str(row[1]), str(row[2])

            if campaign_id:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO email_events (workspace_id, campaign_id, contact_id, resend_message_id, event_type, event_data) VALUES (%s,%s,%s,%s,%s,%s)",
                        (workspace_id, campaign_id, contact_id, msg_id, event_type, json.dumps(data))
                    )
                col = None
                if event_type == "email.opened":
                    col = "open_count"
                elif event_type == "email.clicked":
                    col = "click_count"
                elif event_type == "email.bounced":
                    col = "bounce_count"
                    if contact_id:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE email_contacts SET bounced=TRUE, bounce_type='hard' WHERE id=%s", (contact_id,))
                elif event_type in ("email.unsubscribed", "email.complained"):
                    col = "unsub_count"
                    if contact_id:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE email_contacts SET unsubscribed=TRUE, unsubscribed_at=NOW() WHERE id=%s", (contact_id,))
                if col:
                    with conn.cursor() as cur:
                        cur.execute(f"UPDATE email_campaigns SET {col}={col}+1 WHERE id=%s", (campaign_id,))
    except Exception as e:
        print(f"email_webhook error: {e}")
    return {"ok": True}


# ── Public unsubscribe (NO auth) ──────────────────────────────────────────────

@app.post("/unsubscribe")
async def public_unsubscribe(request: Request):
    body = await request.json()
    token = body.get("token", "").strip()
    if not token:
        return {"ok": True}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE email_contacts SET unsubscribed=TRUE, unsubscribed_at=NOW() WHERE unsubscribe_token=%s AND NOT unsubscribed RETURNING email",
                (token,)
            )
            row = cur.fetchone()
    if row:
        email = row[0]
        masked = email[0] + "***@" + email.split("@")[1]
        return {"ok": True, "email": masked}
    return {"ok": True}


# ── Public: Support Ticket ────────────────────────────────────────────────────

SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "info@runwaystudios.co")
RESEND_FROM_SUPPORT = os.getenv("RESEND_FROM_SUPPORT", "onboarding@resend.dev")

@app.post("/public/submit-ticket")
async def public_submit_ticket(request: Request):
    """No-auth endpoint — accepts support ticket from marketing website."""
    body = await request.json()
    name     = (body.get("name") or "").strip()
    email    = (body.get("email") or "").strip()
    company  = (body.get("company") or "").strip()
    category = (body.get("category") or "General").strip()
    priority = (body.get("priority") or "Normal").strip()
    message  = (body.get("message") or "").strip()

    if not name or not email or not message:
        raise HTTPException(status_code=400, detail="name, email and message are required")

    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
    if not RESEND_API_KEY:
        # Fallback: store in DB and return success
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO support_tickets (name, email, company, category, priority, message, created_at) VALUES (%s,%s,%s,%s,%s,%s,NOW()) ON CONFLICT DO NOTHING",
                    (name, email, company, category, priority, message)
                )
        return {"ok": True}

    from services.agent_swarm.connectors.resend import ResendConnector
    rc = ResendConnector(RESEND_API_KEY)
    html = f"""
<h2 style="color:#7c3aed">New Support Ticket — Runway Studios</h2>
<table style="border-collapse:collapse;width:100%;font-family:sans-serif;font-size:14px">
  <tr><td style="padding:8px;font-weight:600;color:#6b7280;width:120px">Name</td><td style="padding:8px">{name}</td></tr>
  <tr style="background:#f9fafb"><td style="padding:8px;font-weight:600;color:#6b7280">Email</td><td style="padding:8px"><a href="mailto:{email}">{email}</a></td></tr>
  <tr><td style="padding:8px;font-weight:600;color:#6b7280">Company</td><td style="padding:8px">{company or '—'}</td></tr>
  <tr style="background:#f9fafb"><td style="padding:8px;font-weight:600;color:#6b7280">Category</td><td style="padding:8px">{category}</td></tr>
  <tr><td style="padding:8px;font-weight:600;color:#6b7280">Priority</td><td style="padding:8px">{priority}</td></tr>
  <tr style="background:#f9fafb"><td style="padding:8px;font-weight:600;color:#6b7280">Message</td><td style="padding:8px;white-space:pre-wrap">{message}</td></tr>
</table>
<p style="margin-top:16px;font-size:12px;color:#9ca3af">Sent from runwaystudios.co support form</p>
"""
    try:
        rc.send_email(
            to=SUPPORT_EMAIL,
            from_=RESEND_FROM_SUPPORT,
            subject=f"[{priority}] [{category}] Support ticket from {name}",
            html=html,
            reply_to=email,
        )
    except Exception as ex:
        # Log but don't fail — user still gets success feedback
        import traceback; traceback.print_exc()

    # Also store in DB if table exists
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS support_tickets (
                        id SERIAL PRIMARY KEY,
                        name TEXT, email TEXT, company TEXT,
                        category TEXT, priority TEXT, message TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """,
                )
                cur.execute(
                    "INSERT INTO support_tickets (name,email,company,category,priority,message) VALUES (%s,%s,%s,%s,%s,%s)",
                    (name, email, company, category, priority, message)
                )
    except Exception:
        pass

    return {"ok": True}


# ── Email: Auto-DNS setup ─────────────────────────────────────────────────────

def _root_domain(domain: str) -> str:
    """Extract registrable root domain from a subdomain. e.g. mail.foo.com → foo.com"""
    parts = domain.strip().split(".")
    # Handle common second-level TLDs like co.in, co.uk
    if len(parts) >= 3 and parts[-2] in ("co", "com", "net", "org", "gov", "edu") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain


def _apply_godaddy_records(api_key: str, api_secret: str, domain: str, records: list) -> list:
    """Push DNS records to GoDaddy via their REST API. Returns list of {name, type, ok, error}."""
    root = _root_domain(domain)
    headers = {
        "Authorization": f"sso-key {api_key}:{api_secret}",
        "Content-Type": "application/json",
    }
    results = []
    for rec in records:
        rec_type = rec.get("type", "").upper()
        rec_name = rec.get("name", "")
        rec_value = rec.get("value", "")
        rec_ttl = int(rec.get("ttl") or 3600)
        priority = rec.get("priority")

        # Strip root domain from name if present (GoDaddy wants relative name)
        if rec_name.endswith(f".{root}"):
            rec_name = rec_name[: -(len(root) + 1)]
        elif rec_name == root:
            rec_name = "@"

        body = [{"data": rec_value, "ttl": rec_ttl}]
        if priority is not None:
            body[0]["priority"] = int(priority)

        url = f"https://api.godaddy.com/v1/domains/{root}/records/{rec_type}/{rec_name}"
        try:
            r = httpx.put(url, json=body, headers=headers, timeout=15)
            if r.ok:
                results.append({"name": rec_name, "type": rec_type, "ok": True})
            else:
                results.append({"name": rec_name, "type": rec_type, "ok": False,
                                 "error": r.text[:200]})
        except Exception as e:
            results.append({"name": rec_name, "type": rec_type, "ok": False, "error": str(e)})
    return results


def _apply_cloudflare_records(api_token: str, domain: str, records: list) -> list:
    """Push DNS records to Cloudflare via their REST API."""
    root = _root_domain(domain)
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    # Find zone ID for root domain
    try:
        z = httpx.get(
            f"https://api.cloudflare.com/client/v4/zones?name={root}&status=active",
            headers=headers, timeout=15
        )
        z.raise_for_status()
        zones = z.json().get("result", [])
        if not zones:
            return [{"ok": False, "error": f"Zone '{root}' not found in Cloudflare account. Check your API token has Zone:Edit permission."}]
        zone_id = zones[0]["id"]
    except Exception as e:
        return [{"ok": False, "error": f"Cloudflare zone lookup failed: {e}"}]

    # Fetch existing records to avoid duplicates
    try:
        ex = httpx.get(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?per_page=200",
            headers=headers, timeout=15
        )
        existing = {(r["type"], r["name"]): r["id"] for r in ex.json().get("result", [])}
    except Exception:
        existing = {}

    results = []
    for rec in records:
        rec_type = rec.get("type", "").upper()
        rec_name = rec.get("name", "")
        rec_value = rec.get("value", "")
        rec_ttl = int(rec.get("ttl") or 3600)
        priority = rec.get("priority")

        # Cloudflare wants FQDN name
        if rec_name == "@" or rec_name == root:
            fqdn = root
        elif rec_name.endswith(f".{root}"):
            fqdn = rec_name
        else:
            fqdn = f"{rec_name}.{root}"

        payload = {
            "type": rec_type,
            "name": fqdn,
            "content": rec_value,
            "ttl": rec_ttl,
            "proxied": False,
        }
        if priority is not None:
            payload["priority"] = int(priority)

        existing_id = existing.get((rec_type, fqdn))
        try:
            if existing_id:
                r = httpx.put(
                    f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{existing_id}",
                    json=payload, headers=headers, timeout=15
                )
            else:
                r = httpx.post(
                    f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
                    json=payload, headers=headers, timeout=15
                )
            data = r.json()
            if r.ok and data.get("success"):
                results.append({"name": fqdn, "type": rec_type, "ok": True})
            else:
                errors = data.get("errors", [])
                msg = errors[0].get("message", r.text[:200]) if errors else r.text[:200]
                results.append({"name": fqdn, "type": rec_type, "ok": False, "error": msg})
        except Exception as e:
            results.append({"name": fqdn, "type": rec_type, "ok": False, "error": str(e)})
    return results


@app.post("/email/domain/auto-dns")
async def email_domain_auto_dns(request: Request):
    """
    Automatically push DNS records to GoDaddy or Cloudflare.
    body: {workspace_id, domain_id, provider: 'godaddy'|'cloudflare',
           api_key?, api_secret?,   # GoDaddy
           api_token?               # Cloudflare
          }
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    domain_id = body.get("domain_id", "")
    provider = body.get("provider", "").lower()

    if not all([workspace_id, domain_id, provider]):
        raise HTTPException(status_code=400, detail="workspace_id, domain_id, provider required")
    if provider not in ("godaddy", "cloudflare"):
        raise HTTPException(status_code=400, detail="provider must be 'godaddy' or 'cloudflare'")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT domain, dns_records FROM email_domains WHERE id=%s AND workspace_id=%s",
                (domain_id, workspace_id)
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Domain not found")

    domain, dns_records = row
    if not dns_records:
        raise HTTPException(status_code=400, detail="No DNS records found — add the domain first")

    records = dns_records if isinstance(dns_records, list) else []

    with get_conn() as conn2:
        _ensure_dns_provider_table(conn2)
        saved_creds = _get_dns_creds(conn2, workspace_id, provider) or {}

    if provider == "godaddy":
        api_key    = body.get("api_key",    "").strip() or saved_creds.get("api_key",    "")
        api_secret = body.get("api_secret", "").strip() or saved_creds.get("api_secret", "")
        if not api_key or not api_secret:
            raise HTTPException(status_code=400, detail="GoDaddy credentials not found. Connect GoDaddy in the DNS Providers settings first.")
        results = _apply_godaddy_records(api_key, api_secret, domain, records)
    else:
        api_token = body.get("api_token", "").strip() or saved_creds.get("api_token", "")
        if not api_token:
            raise HTTPException(status_code=400, detail="Cloudflare credentials not found. Connect Cloudflare in the DNS Providers settings first.")
        results = _apply_cloudflare_records(api_token, domain, records)

    all_ok = all(r.get("ok") for r in results)
    return {"ok": all_ok, "results": results, "provider": provider, "domain": domain}


# ── DNS provider credential store ─────────────────────────────────────────────
# Allows workspaces to connect GoDaddy/Cloudflare once; credentials stored in
# workspace_dns_providers table and reused automatically on every domain add.

_DNS_PROVIDER_MIGRATION = """
CREATE TABLE IF NOT EXISTS workspace_dns_providers (
    workspace_id  UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider      TEXT        NOT NULL CHECK (provider IN ('godaddy','cloudflare')),
    credentials   JSONB       NOT NULL DEFAULT '{}',
    connected_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, provider)
)
"""


def _ensure_dns_provider_table(conn):
    with conn.cursor() as cur:
        cur.execute(_DNS_PROVIDER_MIGRATION)
    conn.commit()


def _get_dns_creds(conn, workspace_id: str, provider: str) -> dict | None:
    """Load saved credentials for a provider, or None if not connected."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT credentials FROM workspace_dns_providers WHERE workspace_id=%s AND provider=%s",
                (workspace_id, provider)
            )
            row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


@app.post("/email/dns-provider/connect")
async def dns_provider_connect(request: Request):
    """
    Save DNS provider credentials for a workspace.
    body: {workspace_id, provider: 'godaddy'|'cloudflare',
           api_key?, api_secret?,   # GoDaddy
           api_token?               # Cloudflare
          }
    Validates credentials before saving by attempting a lightweight API call.
    """
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    provider = body.get("provider", "").lower()

    if not workspace_id or provider not in ("godaddy", "cloudflare"):
        raise HTTPException(status_code=400, detail="workspace_id and provider ('godaddy'|'cloudflare') required")

    # Build credentials dict
    if provider == "godaddy":
        api_key    = body.get("api_key", "").strip()
        api_secret = body.get("api_secret", "").strip()
        if not api_key or not api_secret:
            raise HTTPException(status_code=400, detail="api_key and api_secret required for GoDaddy")
        # Validate: call /v1/domains to check credentials
        try:
            r = httpx.get(
                "https://api.godaddy.com/v1/domains?limit=1",
                headers={"Authorization": f"sso-key {api_key}:{api_secret}"},
                timeout=10,
            )
            if r.status_code == 401:
                raise HTTPException(status_code=400, detail="GoDaddy credentials are invalid. Check your API key and secret.")
            if r.status_code == 403:
                raise HTTPException(status_code=400, detail="GoDaddy has restricted their DNS API to reseller/partner accounts only — regular retail accounts always get 403, even with valid domains and keys. Workaround: add your domain to Cloudflare (free), point your GoDaddy nameservers to Cloudflare, then connect Cloudflare here instead.")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not reach GoDaddy API: {e}")
        creds = {"api_key": api_key, "api_secret": api_secret}

    else:  # cloudflare
        api_token = body.get("api_token", "").strip()
        if not api_token:
            raise HTTPException(status_code=400, detail="api_token required for Cloudflare")
        # Validate: call /user/tokens/verify
        try:
            r = httpx.get(
                "https://api.cloudflare.com/client/v4/user/tokens/verify",
                headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
                timeout=10,
            )
            data = r.json()
            if not data.get("success"):
                msgs = [e.get("message", "") for e in data.get("errors", [])]
                raise HTTPException(status_code=400, detail=f"Cloudflare token invalid: {'; '.join(msgs) or 'check your token'}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not reach Cloudflare API: {e}")
        creds = {"api_token": api_token}

    with get_conn() as conn:
        _ensure_dns_provider_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO workspace_dns_providers (workspace_id, provider, credentials, connected_at, updated_at)
                   VALUES (%s, %s, %s, NOW(), NOW())
                   ON CONFLICT (workspace_id, provider) DO UPDATE
                     SET credentials=EXCLUDED.credentials, updated_at=NOW()""",
                (workspace_id, provider, json.dumps(creds))
            )

    return {"ok": True, "provider": provider, "connected": True}


@app.get("/email/dns-provider/status")
async def dns_provider_status(request: Request, workspace_id: str = None):
    """Returns which providers are connected (no credentials exposed)."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        _ensure_dns_provider_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT provider, connected_at FROM workspace_dns_providers WHERE workspace_id=%s",
                (workspace_id,)
            )
            rows = cur.fetchall()
    return {"providers": [{"provider": r[0], "connected_at": r[1].isoformat()} for r in rows]}


@app.delete("/email/dns-provider/{provider}")
async def dns_provider_disconnect(request: Request, provider: str):
    """Remove saved credentials for a provider."""
    _auth(request)
    workspace_id = request.query_params.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        _ensure_dns_provider_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM workspace_dns_providers WHERE workspace_id=%s AND provider=%s",
                (workspace_id, provider)
            )
    return {"ok": True}


# ── Product Intelligence ──────────────────────────────────────────────────────

def _extract_with_claude(url: str, page_title: str, page_content: str, raw_images: list) -> dict:
    """Run Claude extraction on fetched page content."""
    import json as _json
    import re as _re
    import anthropic as _anthropic
    from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

    client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Extract structured product information from this webpage.

URL: {url}
Page Title: {page_title}
Page Content (first 3000 chars):
{page_content[:3000]}

Available Images: {_json.dumps(raw_images[:8])}

Return ONLY a JSON object with these exact fields:
{{
  "name": "product name",
  "description": "2-3 sentence product description focusing on benefits",
  "price": null_or_number,
  "mrp": null_or_number,
  "category": "product category",
  "brand": "brand name",
  "key_features": ["feature 1", "feature 2", "feature 3"],
  "unique_selling_prop": "main unique selling point in one sentence",
  "target_audience": "who this is for",
  "images": ["url1", "url2"]
}}

Rules:
- Return ONLY the JSON, no other text or markdown
- If this is a YouTube channel: set category="youtube_channel"
- Prices as plain numbers only (no currency symbols)
- Pick the best 4 product images from Available Images (skip icons/logos)
- Be concise and accurate"""

    msg = client.messages.create(model=CLAUDE_MODEL, max_tokens=1024,
                                  messages=[{"role": "user", "content": prompt}])
    resp_text = msg.content[0].text.strip()
    if resp_text.startswith("```"):
        resp_text = _re.sub(r'^```[a-z]*\n?', '', resp_text).rstrip('`').strip()
    try:
        extracted = _json.loads(resp_text)
    except Exception:
        m = _re.search(r'\{.*\}', resp_text, _re.DOTALL)
        extracted = _json.loads(m.group()) if m else {}

    images_from_claude = extracted.get("images") or raw_images[:4]
    return {
        "name": extracted.get("name") or page_title or "Unknown",
        "description": extracted.get("description") or "",
        "price": extracted.get("price"),
        "mrp": extracted.get("mrp"),
        "category": extracted.get("category") or "",
        "brand": extracted.get("brand") or "",
        "key_features": extracted.get("key_features") or [],
        "unique_selling_prop": extracted.get("unique_selling_prop") or "",
        "target_audience": extracted.get("target_audience") or "",
        "images": images_from_claude[:6],
    }


def _jina_fetch_and_extract(url: str) -> dict:
    """
    Multi-layer product scraper:
    1. BeautifulSoup (fast, server-rendered pages) → Claude
    2. Shopify public .json API (Shopify stores)
    3. Jina AI Reader (JS-rendered/headless stores, slower)
    """
    import requests as _req
    import json as _json
    import re as _re
    from bs4 import BeautifulSoup as _BS
    from urllib.parse import urlparse as _urlparse

    skip_img = ("icon", "logo", "badge", "favicon", "pixel", "tracking", "1x1", "spinner", "avatar")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    parsed = _urlparse(url)

    # ── Layer 1: Shopify public .json API ───────────────────────────────────
    if "/products/" in url:
        try:
            json_url = _re.sub(r'\?.*$', '', url.rstrip('/')) + ".json"
            rj = _req.get(json_url, headers=headers, timeout=8)
            if rj.ok and "application/json" in rj.headers.get("content-type", ""):
                pj = rj.json().get("product", {})
                if pj and pj.get("title"):
                    imgs = [i.get("src", "") for i in pj.get("images", [])
                            if i.get("src") and not any(t in i.get("src","").lower() for t in skip_img)]
                    variants = pj.get("variants", [{}])
                    price_raw = variants[0].get("price", "") if variants else ""
                    compare_raw = variants[0].get("compare_at_price", "") if variants else ""
                    body_text = _BS(pj.get("body_html") or "", "lxml").get_text(separator=" ", strip=True)
                    # Build feature list from tags
                    features = [t for t in pj.get("tags", []) if len(t) < 60][:5]
                    return {
                        "name": pj.get("title", ""),
                        "description": body_text[:500],
                        "price": float(price_raw) if price_raw else None,
                        "mrp": float(compare_raw) if compare_raw else None,
                        "category": pj.get("product_type", ""),
                        "brand": pj.get("vendor", ""),
                        "key_features": features,
                        "unique_selling_prop": "",
                        "target_audience": "",
                        "images": imgs[:6],
                    }
        except Exception:
            pass

    # ── Layer 2: BeautifulSoup HTML scraping ────────────────────────────────
    page_title = ""
    page_content = ""
    raw_images = []
    bs_ok = False
    try:
        r = _req.get(url, headers=headers, timeout=10, allow_redirects=True)
        if r.ok and "text/html" in r.headers.get("content-type", ""):
            soup = _BS(r.text, "lxml")
            page_title = soup.find("title") and soup.find("title").get_text(strip=True) or ""

            # JSON-LD extraction
            name_ld = desc_ld = ""
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    ld = _json.loads(script.string or "")
                    items = ld if isinstance(ld, list) else ld.get("@graph", [ld])
                    for item in items:
                        if item.get("@type") in ("Product", "product"):
                            name_ld = name_ld or item.get("name", "")
                            desc_ld = desc_ld or item.get("description", "")
                            img_f = item.get("image", [])
                            if isinstance(img_f, str): raw_images.append(img_f)
                            elif isinstance(img_f, list):
                                raw_images += [i if isinstance(i, str) else i.get("url","") for i in img_f]
                except Exception:
                    pass

            # OG fallbacks
            def og(p):
                t = soup.find("meta", property=p) or soup.find("meta", attrs={"name": p})
                return (t.get("content") or "").strip() if t else ""

            page_title = name_ld or og("og:title") or page_title
            og_desc = og("og:description") or og("description")
            page_content = desc_ld or og_desc or ""

            if not raw_images:
                og_img = og("og:image")
                if og_img and not any(t in og_img.lower() for t in skip_img):
                    raw_images.append(og_img)

            # Collect additional img tags
            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if not src: continue
                if src.startswith("//"): src = "https:" + src
                elif src.startswith("/"): src = f"{parsed.scheme}://{parsed.netloc}{src}"
                if any(t in src.lower() for t in skip_img): continue
                w = img.get("width") or ""
                if w and int(_re.sub(r'\D','',str(w)) or 0) < 80: continue
                if src not in raw_images: raw_images.append(src)
                if len(raw_images) >= 8: break

            # Check if we got useful content (not a JS shell)
            main_text = soup.get_text(separator=" ", strip=True)
            page_content = page_content or main_text[:1000]
            bs_ok = len(page_content) > 200 and bool(page_title)
    except Exception:
        pass

    if bs_ok:
        # Good HTML content — send to Claude
        filtered_imgs = [i for i in raw_images if i and not any(t in i.lower() for t in skip_img)]
        return _extract_with_claude(url, page_title, page_content, filtered_imgs[:8])

    # ── Layer 3: Jina AI Reader (JS-rendered / headless stores) ────────────
    try:
        jina_url = f"https://r.jina.ai/{url}"
        jr = _req.get(jina_url,
                      headers={"Accept": "application/json", "X-No-Cache": "true"},
                      timeout=35)
        if not jr.ok:
            raise ValueError(f"Could not read page (Jina status {jr.status_code})")
        jd = jr.json()
        jdata = jd.get("data", {})
        j_title = jdata.get("title", "") or page_title
        j_content = (jdata.get("content") or page_content or "")
        j_images_raw = jdata.get("images", {})
        j_images = [u for u in list(j_images_raw.keys())[:12]
                    if not any(t in u.lower() for t in skip_img)]
        if not j_title and not j_content:
            raise ValueError("Could not extract content from URL")
        return _extract_with_claude(url, j_title, j_content, j_images or raw_images)
    except ValueError:
        raise
    except Exception as e:
        # Timeout or network error
        if page_title:
            # We have SOME data from BS — extract what we can
            return _extract_with_claude(url, page_title, page_content, raw_images[:8])
        raise ValueError(f"Could not read page. The URL may be slow or JS-only. Try again shortly.")


@app.post("/products/fetch-url")
async def products_fetch_url(request: Request):
    """Fetch any product URL via Jina + Claude, upsert to products table."""
    _auth(request)
    body = await request.json()
    url = (body.get("url") or "").strip()
    workspace_id = body.get("workspace_id", "")
    is_competitor = bool(body.get("is_competitor", False))
    if not url or not workspace_id:
        raise HTTPException(status_code=400, detail="url and workspace_id required")
    if not url.startswith("http"):
        url = "https://" + url

    import json as _json
    try:
        ext = _jina_fetch_and_extract(url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not fetch: {e}")

    name = ext["name"]
    description = ext["description"]
    price = ext["price"]
    mrp = ext["mrp"]
    category = ext["category"]
    brand = ext["brand"]
    key_features = ext["key_features"]
    usp = ext["unique_selling_prop"]
    target_aud = ext["target_audience"]
    images_list = ext["images"]
    product_type = "youtube_channel" if category == "youtube_channel" else "product"
    images_json = [{"url": u, "alt": name, "position": i + 1} for i, u in enumerate(images_list)]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM products WHERE workspace_id=%s AND product_url=%s LIMIT 1",
                        (workspace_id, url))
            existing = cur.fetchone()
            if existing:
                product_id = str(existing[0])
                cur.execute(
                    """UPDATE products SET
                        name=%s, description=%s, price_inr=%s, mrp_inr=%s,
                        images=%s::jsonb, category=%s, brand=%s, key_features=%s::jsonb,
                        unique_selling_prop=%s, target_audience=%s,
                        is_competitor=%s, product_type=%s, last_synced_at=NOW(), updated_at=NOW()
                       WHERE id=%s""",
                    (name, description, float(price) if price else None,
                     float(mrp) if mrp else None,
                     _json.dumps(images_json), category, brand,
                     _json.dumps(key_features), usp, target_aud,
                     is_competitor, product_type, product_id)
                )
            else:
                cur.execute(
                    """INSERT INTO products
                        (workspace_id, name, description, price_inr, mrp_inr, product_url,
                         images, category, brand, key_features, unique_selling_prop,
                         target_audience, source_platform, is_competitor, product_type, last_synced_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s,%s,'url',%s,%s,NOW())
                       RETURNING id""",
                    (workspace_id, name, description,
                     float(price) if price else None,
                     float(mrp) if mrp else None,
                     url, _json.dumps(images_json),
                     category, brand, _json.dumps(key_features),
                     usp, target_aud, is_competitor, product_type)
                )
                product_id = str(cur.fetchone()[0])
    return {
        "id": product_id, "name": name, "description": description,
        "price_inr": float(price) if price else None,
        "images": images_list[:4], "key_features": key_features,
        "unique_selling_prop": usp, "is_competitor": is_competitor,
        "product_type": product_type, "product_url": url,
    }


@app.get("/products")
async def products_list_endpoint(request: Request, workspace_id: str = None):
    """List all products for a workspace (new product intelligence catalog)."""
    _auth(request)
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    import json as _json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, description, price_inr, mrp_inr, product_url,
                          images, category, brand, key_features, unique_selling_prop,
                          target_audience, source_platform, is_competitor, product_type,
                          last_synced_at, created_at, active
                   FROM products
                   WHERE workspace_id=%s AND active=true
                   ORDER BY is_competitor ASC, created_at DESC""",
                (workspace_id,)
            )
            rows = cur.fetchall()
    products = []
    for r in rows:
        (pid, pname, pdesc, pprice, pmrp, purl, pimages, pcat, pbrand, pfeats, pusp,
         ptarg, psrc, pcomp, ptype, psynced, pcreated, pactive) = r
        imgs_raw = pimages if isinstance(pimages, list) else (_json.loads(pimages) if pimages else [])
        feats_raw = pfeats if isinstance(pfeats, list) else (_json.loads(pfeats) if pfeats else [])
        products.append({
            "id": str(pid), "name": pname, "description": pdesc,
            "price_inr": float(pprice) if pprice else None,
            "mrp_inr": float(pmrp) if pmrp else None,
            "product_url": purl, "images": imgs_raw,
            "category": pcat, "brand": pbrand,
            "key_features": feats_raw, "unique_selling_prop": pusp,
            "target_audience": ptarg, "source_platform": psrc,
            "is_competitor": bool(pcomp), "product_type": ptype or "product",
            "last_synced_at": psynced.isoformat() if psynced else None,
            "created_at": pcreated.isoformat() if pcreated else None,
            "active": bool(pactive),
        })
    return {"products": products, "count": len(products)}


@app.delete("/products/{product_id}")
async def products_delete(request: Request, product_id: str):
    """Soft-delete a product."""
    _auth(request)
    workspace_id = request.query_params.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE products SET active=false, updated_at=NOW() WHERE id=%s AND workspace_id=%s",
                (product_id, workspace_id)
            )
    return {"ok": True}


@app.post("/products/{product_id}/resync")
async def products_resync(request: Request, product_id: str):
    """Re-scrape product URL with Jina + Claude and update."""
    _auth(request)
    body = await request.json()
    workspace_id = body.get("workspace_id", "")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id required")

    import json as _json
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT product_url, is_competitor FROM products WHERE id=%s AND workspace_id=%s",
                        (product_id, workspace_id))
            row = cur.fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Product not found or has no URL")

    url, is_competitor = row[0], bool(row[1])
    try:
        ext = _jina_fetch_and_extract(url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    images_json = [{"url": u, "alt": ext["name"], "position": i + 1}
                   for i, u in enumerate(ext["images"])]
    product_type = "youtube_channel" if ext["category"] == "youtube_channel" else "product"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE products SET
                    name=%s, description=%s, price_inr=%s, mrp_inr=%s,
                    images=%s::jsonb, category=%s, brand=%s, key_features=%s::jsonb,
                    unique_selling_prop=%s, target_audience=%s,
                    product_type=%s, last_synced_at=NOW(), updated_at=NOW()
                   WHERE id=%s AND workspace_id=%s""",
                (ext["name"], ext["description"],
                 float(ext["price"]) if ext["price"] else None,
                 float(ext["mrp"]) if ext["mrp"] else None,
                 _json.dumps(images_json), ext["category"], ext["brand"],
                 _json.dumps(ext["key_features"]),
                 ext["unique_selling_prop"], ext["target_audience"],
                 product_type, product_id, workspace_id)
            )
    return {"ok": True, "name": ext["name"]}
