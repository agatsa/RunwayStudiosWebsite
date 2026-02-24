# services/agent_swarm/core/workspace.py
"""
Central workspace/tenant resolver for the Runway Studios platform.

Every agent, endpoint, and service calls this module to look up
the workspace, its platform connections, and its product catalog.
Replaces the fragmented _get_tenant / _resolve_tenant patterns
scattered across app.py and the agents.

Key concepts
────────────
  Organization  — the company that signed up (e.g. "Agatsa Health")
  Workspace     — one brand being managed (org can have many)
  PlatformConn  — one ad account on one platform (workspace can have many)
  Product       — one item in the product catalog (workspace can have many)

Lookup hierarchy (in order):
  1. workspace_id  (UUID) — most explicit, fastest
  2. wa_phone_number_id   — legacy path, WhatsApp bot entry point
  3. org_id + first active workspace — fallback for API calls with only org context
"""

import time
from typing import Optional
from fastapi import Request, HTTPException

from services.agent_swarm.db import get_conn
from services.agent_swarm.config import (
    WA_PHONE_NUMBER_ID, META_ADS_TOKEN, META_AD_ACCOUNT_ID,
    META_PAGE_ID, META_PIXEL_ID, WA_ACCESS_TOKEN, WA_REPORT_NUMBER,
    DAILY_SPEND_CAP, APPROVAL_THRESHOLD, AD_TIMEZONE, CRON_TOKEN,
)


# ── In-memory cache (TTL = 5 minutes) ─────────────────────────────────────

_WORKSPACE_CACHE: dict[str, dict] = {}
_CACHE_TTL = 300  # seconds


def _cache_key(lookup_type: str, value: str) -> str:
    return f"{lookup_type}:{value}"


def _get_cached(key: str) -> Optional[dict]:
    entry = _WORKSPACE_CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    return None


def _set_cached(key: str, data: dict):
    _WORKSPACE_CACHE[key] = {"data": data, "ts": time.time()}


def invalidate_workspace_cache(workspace_id: str):
    """Call after updating workspace credentials to clear stale cache."""
    keys_to_delete = [k for k in _WORKSPACE_CACHE if workspace_id in k]
    for k in keys_to_delete:
        del _WORKSPACE_CACHE[k]


# ── DB helpers ────────────────────────────────────────────────────────────

def _row_to_workspace(row) -> dict:
    """Convert DB row tuple from _fetch_workspace query to workspace dict."""
    return {
        "id":                   str(row[0]),
        "org_id":               str(row[1]),
        "name":                 row[2],
        "store_url":            row[3],
        "store_platform":       row[4],
        "timezone":             row[5] or AD_TIMEZONE,
        "currency":             row[6] or "INR",
        "wa_phone_number_id":   row[7],
        "wa_access_token":      row[8] or WA_ACCESS_TOKEN,
        "notification_wa_number": row[9] or WA_REPORT_NUMBER,
        "telegram_chat_id":     row[10],
        "telegram_enabled":     bool(row[11]),
        "daily_spend_cap":      float(row[12] or DAILY_SPEND_CAP),
        "approval_threshold":   float(row[13] or APPROVAL_THRESHOLD),
        "active":               bool(row[14]),
        "onboarding_complete":  bool(row[15]),
        # Populated separately by get_workspace() with platform connections
        "connections":          {},   # {platform: [conn, ...]}
        "products":             [],
    }


_WORKSPACE_SELECT = """
    SELECT id, org_id, name, store_url, store_platform,
           timezone, currency, wa_phone_number_id, wa_access_token,
           notification_wa_number, telegram_chat_id, telegram_enabled,
           daily_spend_cap, approval_threshold, active, onboarding_complete
    FROM workspaces
"""


def _fetch_platform_connections(workspace_id: str) -> dict:
    """
    Returns {platform: [conn_dict, ...]} with primary connection first.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, platform, account_id, account_name,
                       access_token, refresh_token, token_expires_at,
                       ad_account_id, page_id, pixel_id, mcc_id,
                       is_primary, metadata
                FROM platform_connections
                WHERE workspace_id = %s
                ORDER BY platform, is_primary DESC, connected_at
                """,
                (workspace_id,),
            )
            rows = cur.fetchall()

    connections: dict[str, list] = {}
    for r in rows:
        conn_dict = {
            "id":               str(r[0]),
            "platform":         r[1],
            "account_id":       r[2],
            "account_name":     r[3],
            "access_token":     r[4],
            "refresh_token":    r[5],
            "token_expires_at": r[6],
            "ad_account_id":    r[7],
            "page_id":          r[8],
            "pixel_id":         r[9],
            "mcc_id":           r[10],
            "is_primary":       bool(r[11]),
            "metadata":         r[12] or {},
        }
        connections.setdefault(r[1], []).append(conn_dict)
    return connections


def _fetch_products(workspace_id: str, active_only: bool = True) -> list[dict]:
    """Returns list of product dicts for the workspace."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, description, price_inr, mrp_inr,
                       product_url, images, sku, category,
                       ad_context, target_audience, key_features,
                       unique_selling_prop, gtin, mpn,
                       google_product_category, brand,
                       source_platform, source_product_id, active
                FROM products
                WHERE workspace_id = %s
                  AND (%s = FALSE OR active = TRUE)
                ORDER BY created_at
                """,
                (workspace_id, active_only),
            )
            rows = cur.fetchall()

    return [
        {
            "id":                       str(r[0]),
            "name":                     r[1],
            "description":              r[2],
            "price_inr":                float(r[3]) if r[3] else None,
            "mrp_inr":                  float(r[4]) if r[4] else None,
            "product_url":              r[5],
            "images":                   r[6] or [],
            "sku":                      r[7],
            "category":                 r[8],
            "ad_context":               r[9],
            "target_audience":          r[10],
            "key_features":             r[11] or [],
            "unique_selling_prop":      r[12],
            "gtin":                     r[13],
            "mpn":                      r[14],
            "google_product_category":  r[15],
            "brand":                    r[16],
            "source_platform":          r[17],
            "source_product_id":        r[18],
            "active":                   bool(r[19]),
        }
        for r in rows
    ]


# ── Public API ────────────────────────────────────────────────────────────

def get_workspace(workspace_id: str, include_products: bool = True) -> Optional[dict]:
    """
    Fetch a workspace by its UUID.
    Includes platform_connections and (optionally) products.
    Returns None if not found.
    """
    cache_key = _cache_key("id", workspace_id)
    cached = _get_cached(cache_key)
    if cached:
        return cached

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                _WORKSPACE_SELECT + " WHERE id = %s AND active = TRUE",
                (workspace_id,),
            )
            row = cur.fetchone()

    if not row:
        return None

    workspace = _row_to_workspace(row)
    workspace["connections"] = _fetch_platform_connections(workspace_id)
    if include_products:
        workspace["products"] = _fetch_products(workspace_id)

    _set_cached(cache_key, workspace)
    return workspace


def get_workspace_by_wa(phone_number_id: str) -> Optional[dict]:
    """
    Look up workspace by WhatsApp phone_number_id.
    Used by main.py for incoming WhatsApp messages.
    """
    cache_key = _cache_key("wa", phone_number_id)
    cached = _get_cached(cache_key)
    if cached:
        return cached

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                _WORKSPACE_SELECT + " WHERE wa_phone_number_id = %s AND active = TRUE LIMIT 1",
                (phone_number_id,),
            )
            row = cur.fetchone()

    if not row:
        # Fall back to env-var-based default workspace
        return _env_workspace()

    workspace_id = str(row[0])
    workspace = _row_to_workspace(row)
    workspace["connections"] = _fetch_platform_connections(workspace_id)
    workspace["products"] = _fetch_products(workspace_id)

    _set_cached(cache_key, workspace)
    _set_cached(_cache_key("id", workspace_id), workspace)
    return workspace


def list_active_workspaces() -> list[dict]:
    """
    Return all active workspaces (used by hourly cron to process every tenant).
    Does NOT populate products/connections for performance — callers fetch on demand.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                _WORKSPACE_SELECT + " WHERE active = TRUE ORDER BY created_at",
            )
            rows = cur.fetchall()
    return [_row_to_workspace(r) for r in rows]


def get_primary_connection(workspace: dict, platform: str) -> Optional[dict]:
    """
    Return the primary platform connection for a given platform.
    Falls back to first available connection if no primary is set.
    """
    conns = workspace.get("connections", {}).get(platform, [])
    if not conns:
        return None
    primary = [c for c in conns if c["is_primary"]]
    return primary[0] if primary else conns[0]


def get_all_connections(workspace: dict, platform: str) -> list[dict]:
    """Return all connections for a platform (for multi-account support)."""
    return workspace.get("connections", {}).get(platform, [])


def build_product_context(workspace: dict, product_id: str = None) -> str:
    """
    Build a Claude-ready product context string for ad generation.
    If product_id given, returns context for that product only.
    Otherwise returns a combined context for all active products.
    Replaces the hardcoded PRODUCT_CONTEXT env var.
    """
    products = workspace.get("products", [])
    if not products:
        return "No product catalog available for this workspace."

    if product_id:
        products = [p for p in products if p["id"] == product_id]
        if not products:
            return "Product not found."

    lines = []
    for p in products:
        lines.append(f"Product: {p['name']}")
        if p.get("description"):
            lines.append(f"Description: {p['description']}")
        if p.get("price_inr"):
            price_line = f"Price: ₹{p['price_inr']:,.0f}"
            if p.get("mrp_inr") and p["mrp_inr"] > p["price_inr"]:
                price_line += f" (MRP ₹{p['mrp_inr']:,.0f})"
            lines.append(price_line)
        if p.get("product_url"):
            lines.append(f"URL: {p['product_url']}")
        if p.get("key_features"):
            lines.append(f"Key features: {', '.join(p['key_features'])}")
        if p.get("unique_selling_prop"):
            lines.append(f"USP: {p['unique_selling_prop']}")
        if p.get("target_audience"):
            lines.append(f"Target audience: {p['target_audience']}")
        if p.get("ad_context"):
            lines.append(f"Ad context: {p['ad_context']}")
        lines.append("")

    store_url = workspace.get("store_url", "")
    if store_url:
        lines.append(f"Store: {store_url}")

    return "\n".join(lines).strip()


# ── Fallback: env-var workspace (for dev / missing DB) ───────────────────

def _env_workspace() -> dict:
    """
    Construct a minimal workspace dict from env vars.
    Used as fallback when DB is unavailable or no workspace row exists.
    Preserves backward compatibility with the original single-tenant setup.
    """
    from services.agent_swarm.config import (
        PRODUCT_CONTEXT, LANDING_PAGE_URL,
    )
    return {
        "id":                   "00000000-0000-0000-0000-000000000001",
        "org_id":               "00000000-0000-0000-0000-000000000001",
        "name":                 "Default Workspace",
        "store_url":            LANDING_PAGE_URL,
        "store_platform":       "unknown",
        "timezone":             AD_TIMEZONE,
        "currency":             "INR",
        "wa_phone_number_id":   WA_PHONE_NUMBER_ID,
        "wa_access_token":      WA_ACCESS_TOKEN,
        "notification_wa_number": WA_REPORT_NUMBER,
        "telegram_chat_id":     None,
        "telegram_enabled":     False,
        "daily_spend_cap":      DAILY_SPEND_CAP,
        "approval_threshold":   APPROVAL_THRESHOLD,
        "active":               True,
        "onboarding_complete":  True,
        "connections": {
            "meta": [{
                "id":           "00000000-0000-0000-0000-000000000002",
                "platform":     "meta",
                "account_id":   META_AD_ACCOUNT_ID,
                "account_name": "Default Meta Account",
                "access_token": META_ADS_TOKEN,
                "ad_account_id": META_AD_ACCOUNT_ID,
                "page_id":      META_PAGE_ID,
                "pixel_id":     META_PIXEL_ID,
                "is_primary":   True,
                "metadata":     {},
            }]
        },
        "products": [
            {
                "id":           "00000000-0000-0000-0000-000000000003",
                "name":         "Product",
                "ad_context":   PRODUCT_CONTEXT,
                "product_url":  LANDING_PAGE_URL,
                "active":       True,
            }
        ],
    }


# ── Request resolver (used by FastAPI endpoints) ──────────────────────────

def resolve_workspace(request: Request = None, body: dict = None) -> dict:
    """
    Resolves workspace from a FastAPI request + body.
    Priority:
      1. body.workspace_id
      2. body.phone_number_id  (legacy WhatsApp path)
      3. query param ?workspace_id
      4. query param ?phone_number_id
      5. env-var fallback

    Raises HTTP 404 if explicitly specified but not found.
    """
    body = body or {}

    # 1 — explicit workspace_id
    ws_id = body.get("workspace_id")
    if not ws_id and request:
        ws_id = request.query_params.get("workspace_id")
    if ws_id:
        ws = get_workspace(ws_id)
        if not ws:
            raise HTTPException(status_code=404, detail=f"Workspace {ws_id} not found")
        return ws

    # 2 — WhatsApp phone_number_id (legacy)
    phone_id = body.get("phone_number_id")
    if not phone_id and request:
        phone_id = request.query_params.get("phone_number_id")
    if phone_id:
        ws = get_workspace_by_wa(phone_id)
        if ws:
            return ws

    # 3 — fallback to env vars
    return _env_workspace()


def require_auth(request: Request):
    """
    Validate X-Cron-Token header for internal service-to-service calls.
    Raises HTTP 401 if token missing or wrong.
    """
    if not CRON_TOKEN:
        return  # no token configured = dev mode, allow all
    token = request.headers.get("X-Cron-Token", "")
    if token != CRON_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
