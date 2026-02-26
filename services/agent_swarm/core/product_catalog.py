# services/agent_swarm/core/product_catalog.py
"""
Product catalog discovery and sync service.

Given a store URL, automatically detects the platform and populates
the `products` table for the workspace.

Supported platforms:
  1. Shopify   — uses public /products.json endpoint (no auth needed)
  2. WooCommerce — uses WooCommerce REST API v3
  3. Custom/Unknown — Claude reads the page and extracts product data

Called during:
  - Onboarding (client enters store URL for the first time)
  - Manual re-sync from the dashboard
  - Scheduled weekly sync to pick up price/inventory changes
"""

import json
import re
from urllib.parse import urlparse

import requests as _requests
import anthropic

from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from services.agent_swarm.db import get_conn
from services.agent_swarm.core.workspace import invalidate_workspace_cache


# ── Platform detection ────────────────────────────────────────────────────

def detect_platform(store_url: str) -> str:
    """
    Detect the e-commerce platform for a given store URL.
    Returns: 'shopify' | 'woocommerce' | 'custom'
    """
    url = store_url.rstrip("/")

    # Check Shopify: /products.json always returns 200 on Shopify stores
    try:
        r = _requests.get(f"{url}/products.json?limit=1", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if "products" in data:
                return "shopify"
    except Exception:
        pass

    # Check WooCommerce: /wp-json/wc/v3/products returns 200 with valid auth
    # (Even without auth it returns 401, which still means WooCommerce is present)
    try:
        r = _requests.get(f"{url}/wp-json/wc/v3/products", timeout=10)
        if r.status_code in (200, 401, 403):
            if "woocommerce" in r.headers.get("X-WC-Store-API-Nonce", "").lower() or \
               r.status_code == 401:
                # Check wp-json route exists at all
                wp = _requests.get(f"{url}/wp-json/", timeout=10)
                if wp.status_code == 200 and "wp/v2" in wp.text:
                    return "woocommerce"
    except Exception:
        pass

    return "custom"


# ── Shopify sync ──────────────────────────────────────────────────────────

def sync_from_shopify(workspace_id: str, store_url: str) -> list[dict]:
    """
    Fetch all products from a Shopify store via the public /products.json API.
    Upserts into the products table.
    Returns list of synced product dicts.
    """
    url = store_url.rstrip("/")
    synced = []
    page = 1
    limit = 250  # Shopify max per page

    while True:
        try:
            r = _requests.get(
                f"{url}/products.json",
                params={"limit": limit, "page": page},
                timeout=20,
            )
            if not r.ok:
                print(f"Shopify products.json failed: {r.status_code} — {r.text[:200]}")
                break
            data = r.json()
            products = data.get("products", [])
            if not products:
                break

            for p in products:
                synced_product = _upsert_shopify_product(workspace_id, store_url, p)
                if synced_product:
                    synced.append(synced_product)

            if len(products) < limit:
                break
            page += 1

        except Exception as e:
            print(f"Shopify sync error on page {page}: {e}")
            break

    # Mark products that no longer exist in Shopify as inactive
    if synced:
        active_source_ids = [p["source_product_id"] for p in synced]
        _deactivate_removed_products(workspace_id, "shopify", active_source_ids)

    invalidate_workspace_cache(workspace_id)
    print(f"Shopify sync complete: {len(synced)} products for workspace {workspace_id}")
    return synced


def _upsert_shopify_product(workspace_id: str, store_url: str, p: dict) -> dict | None:
    """Parse a Shopify product object and upsert into products table."""
    try:
        product_id = str(p["id"])
        title = p.get("title", "")
        description = _strip_html(p.get("body_html", "") or "")

        # Price: use first variant's price
        variants = p.get("variants", [])
        price_inr = None
        mrp_inr = None
        sku = None
        if variants:
            v = variants[0]
            try:
                price_inr = float(v.get("price") or 0) or None
            except (ValueError, TypeError):
                pass
            try:
                compare = v.get("compare_at_price")
                if compare:
                    mrp_inr = float(compare)
            except (ValueError, TypeError):
                pass
            sku = v.get("sku")

        # Product URL
        handle = p.get("handle", "")
        product_url = f"{store_url.rstrip('/')}/products/{handle}" if handle else None

        # Images
        images = [
            {"url": img["src"], "alt": img.get("alt", ""), "position": img.get("position", 0)}
            for img in p.get("images", [])
            if img.get("src")
        ]

        # Category from product type
        category = p.get("product_type", "") or None
        brand = p.get("vendor", "") or None

        # Tags → key features (use Shopify tags as seed)
        tags = [t.strip() for t in (p.get("tags") or "").split(",") if t.strip()]

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO products (
                        workspace_id, name, description, price_inr, mrp_inr,
                        product_url, images, sku, category, brand,
                        key_features, source_platform, source_product_id,
                        active, last_synced_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
                    ON CONFLICT (workspace_id, source_platform, source_product_id)
                    DO UPDATE SET
                        name            = EXCLUDED.name,
                        description     = EXCLUDED.description,
                        price_inr       = EXCLUDED.price_inr,
                        mrp_inr         = EXCLUDED.mrp_inr,
                        product_url     = EXCLUDED.product_url,
                        images          = EXCLUDED.images,
                        sku             = EXCLUDED.sku,
                        category        = EXCLUDED.category,
                        brand           = EXCLUDED.brand,
                        active          = TRUE,
                        last_synced_at  = NOW(),
                        updated_at      = NOW()
                    RETURNING id
                    """,
                    (
                        workspace_id, title, description or None,
                        price_inr, mrp_inr,
                        product_url, json.dumps(images),
                        sku, category, brand,
                        json.dumps(tags),
                        "shopify", product_id,
                    ),
                )
                row = cur.fetchone()
                internal_id = str(row[0]) if row else None

        return {
            "id": internal_id,
            "name": title,
            "price_inr": price_inr,
            "product_url": product_url,
            "source_platform": "shopify",
            "source_product_id": product_id,
        }

    except Exception as e:
        print(f"Error upserting Shopify product {p.get('id')}: {e}")
        return None


# ── WooCommerce sync ──────────────────────────────────────────────────────

def sync_from_woocommerce(
    workspace_id: str,
    store_url: str,
    consumer_key: str,
    consumer_secret: str,
) -> list[dict]:
    """
    Fetch products from WooCommerce REST API v3.
    Requires consumer key + secret from WooCommerce → Settings → Advanced → REST API.
    """
    url = store_url.rstrip("/")
    synced = []
    page = 1
    per_page = 100

    while True:
        try:
            r = _requests.get(
                f"{url}/wp-json/wc/v3/products",
                params={"per_page": per_page, "page": page, "status": "publish"},
                auth=(consumer_key, consumer_secret),
                timeout=20,
            )
            if not r.ok:
                print(f"WooCommerce API error: {r.status_code} — {r.text[:200]}")
                break
            products = r.json()
            if not products:
                break

            for p in products:
                synced_product = _upsert_woocommerce_product(workspace_id, store_url, p)
                if synced_product:
                    synced.append(synced_product)

            if len(products) < per_page:
                break
            page += 1

        except Exception as e:
            print(f"WooCommerce sync error on page {page}: {e}")
            break

    if synced:
        active_source_ids = [p["source_product_id"] for p in synced]
        _deactivate_removed_products(workspace_id, "woocommerce", active_source_ids)

    invalidate_workspace_cache(workspace_id)
    print(f"WooCommerce sync complete: {len(synced)} products for workspace {workspace_id}")
    return synced


def _upsert_woocommerce_product(workspace_id: str, store_url: str, p: dict) -> dict | None:
    try:
        product_id = str(p["id"])
        title = p.get("name", "")
        description = _strip_html(p.get("description") or p.get("short_description") or "")
        price_inr = float(p.get("price") or 0) or None
        regular_price = p.get("regular_price")
        mrp_inr = float(regular_price) if regular_price else None
        sku = p.get("sku") or None
        product_url = p.get("permalink") or None
        category = (p.get("categories") or [{}])[0].get("name") if p.get("categories") else None
        brand = None  # WooCommerce doesn't have native brand, may be in attributes

        images = [
            {"url": img["src"], "alt": img.get("alt", ""), "position": i}
            for i, img in enumerate(p.get("images", []))
            if img.get("src")
        ]

        tags = [t.get("name", "") for t in (p.get("tags") or []) if t.get("name")]

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO products (
                        workspace_id, name, description, price_inr, mrp_inr,
                        product_url, images, sku, category, brand,
                        key_features, source_platform, source_product_id,
                        active, last_synced_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
                    ON CONFLICT (workspace_id, source_platform, source_product_id)
                    DO UPDATE SET
                        name = EXCLUDED.name, description = EXCLUDED.description,
                        price_inr = EXCLUDED.price_inr, mrp_inr = EXCLUDED.mrp_inr,
                        product_url = EXCLUDED.product_url, images = EXCLUDED.images,
                        active = TRUE, last_synced_at = NOW(), updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        workspace_id, title, description or None,
                        price_inr, mrp_inr, product_url,
                        json.dumps(images), sku, category, brand,
                        json.dumps(tags), "woocommerce", product_id,
                    ),
                )
                row = cur.fetchone()
                internal_id = str(row[0]) if row else None

        return {"id": internal_id, "name": title, "price_inr": price_inr,
                "product_url": product_url, "source_platform": "woocommerce",
                "source_product_id": product_id}

    except Exception as e:
        print(f"WooCommerce product upsert error: {e}")
        return None


# ── Claude-powered extraction for custom/unknown sites ────────────────────

def extract_via_claude(workspace_id: str, store_url: str) -> list[dict]:
    """
    For custom or unknown sites: fetch the page HTML and ask Claude
    to extract product information. Best-effort — may miss products
    on heavily JS-rendered pages.
    """
    try:
        r = _requests.get(store_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        html = r.text[:15000]  # Claude context limit guard
    except Exception as e:
        print(f"Failed to fetch {store_url}: {e}")
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""
You are a product catalog extractor.

Below is HTML from a store page at {store_url}.
Extract ALL products you can find and return a JSON array.

For each product extract:
- name (string, required)
- description (string)
- price_inr (number, the selling price in INR — look for ₹ symbol)
- mrp_inr (number, the original/crossed-out price if shown)
- product_url (string, full URL to the product page)
- images (array of image URLs you can find)
- sku (string)
- category (string)
- key_features (array of short strings)

Return ONLY valid JSON array. If no products found, return [].

HTML:
{html}
"""
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Extract JSON from response
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            print("Claude returned no JSON array")
            return []
        products_data = json.loads(match.group(0))
    except Exception as e:
        print(f"Claude extraction error: {e}")
        return []

    synced = []
    for p in products_data:
        if not p.get("name"):
            continue
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO products (
                            workspace_id, name, description, price_inr, mrp_inr,
                            product_url, images, key_features,
                            source_platform, active, last_synced_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'custom',TRUE,NOW())
                        ON CONFLICT DO NOTHING
                        RETURNING id
                        """,
                        (
                            workspace_id,
                            p["name"],
                            p.get("description"),
                            p.get("price_inr"),
                            p.get("mrp_inr"),
                            p.get("product_url"),
                            json.dumps(p.get("images", [])),
                            json.dumps(p.get("key_features", [])),
                        ),
                    )
                    row = cur.fetchone()
            synced.append({"id": str(row[0]) if row else None, "name": p["name"]})
        except Exception as e:
            print(f"Error inserting Claude-extracted product: {e}")

    invalidate_workspace_cache(workspace_id)
    print(f"Claude extraction complete: {len(synced)} products for workspace {workspace_id}")
    return synced


# ── Authenticated Shopify sync (Admin API — works even when /products.json blocked) ──

def sync_from_shopify_authenticated(
    workspace_id: str,
    shop_domain: str,
    access_token: str,
) -> list[dict]:
    """
    Fetch all products using the Shopify Admin REST API (requires OAuth token).
    Works for stores that block the public /products.json endpoint.
    Upserts into products table with source_platform='shopify'.
    """
    from services.agent_swarm.connectors.shopify import ShopifyConnector
    connector = ShopifyConnector()
    raw_products = connector.get_all_products(shop_domain, access_token)

    store_url = f"https://{shop_domain}"
    synced = []
    for p in raw_products:
        result = _upsert_shopify_product(workspace_id, store_url, p)
        if result:
            synced.append(result)

    # Deactivate products no longer in Shopify
    if synced:
        active_source_ids = [p["source_product_id"] for p in synced]
        _deactivate_removed_products(workspace_id, "shopify", active_source_ids)

    invalidate_workspace_cache(workspace_id)
    print(f"Shopify authenticated sync: {len(synced)} products for workspace {workspace_id}")
    return synced


# ── Unified entry point ───────────────────────────────────────────────────

def discover_and_sync(
    workspace_id: str,
    store_url: str,
    wc_key: str = None,
    wc_secret: str = None,
) -> dict:
    """
    Main entry point. Detects platform and runs appropriate sync.
    Returns: {platform, products_synced, products: [...]}
    """
    # Check for stored Shopify OAuth token first (works for stores behind CDN/Cloudflare)
    try:
        from services.agent_swarm.db import get_conn as _gc
        with _gc() as _conn:
            with _conn.cursor() as _cur:
                _cur.execute(
                    "SELECT shop_domain, access_token FROM shopify_connections WHERE workspace_id=%s LIMIT 1",
                    (workspace_id,),
                )
                _row = _cur.fetchone()
        if _row:
            _shop_domain, _access_token = _row
            products = sync_from_shopify_authenticated(workspace_id, _shop_domain, _access_token)
            with _gc() as _conn:
                with _conn.cursor() as _cur:
                    _cur.execute(
                        "UPDATE shopify_connections SET synced_at=NOW() WHERE workspace_id=%s AND shop_domain=%s",
                        (workspace_id, _shop_domain),
                    )
                _conn.commit()
            return {"platform": "shopify", "needs_credentials": False,
                    "products_synced": len(products), "products": products}
    except Exception as _e:
        print(f"Shopify token lookup failed: {_e}")

    platform = detect_platform(store_url)
    print(f"Detected platform: {platform} for {store_url}")

    if platform == "shopify":
        products = sync_from_shopify(workspace_id, store_url)
    elif platform == "woocommerce":
        if not wc_key or not wc_secret:
            # WooCommerce needs API credentials — return a request for them
            return {
                "platform": "woocommerce",
                "needs_credentials": True,
                "message": "WooCommerce detected. Please provide API key and secret from WooCommerce → Settings → Advanced → REST API",
            }
        products = sync_from_woocommerce(workspace_id, store_url, wc_key, wc_secret)
    else:
        products = extract_via_claude(workspace_id, store_url)

    # Update workspace store_platform
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE workspaces SET store_platform=%s, store_url=%s, updated_at=NOW() WHERE id=%s",
                (platform, store_url, workspace_id),
            )

    return {
        "platform": platform,
        "needs_credentials": False,
        "products_synced": len(products),
        "products": products,
    }


# ── URL scraper (single product page) ────────────────────────────────────

def scrape_product_page(workspace_id: str, url: str) -> dict:
    """
    Scrape a single product page URL and upsert into the products table.
    Strategy:
      1. Shopify .json endpoint (append .json to product URL)
      2. Open Graph / meta tags from page HTML
      3. Claude extraction fallback
    Returns the upserted product dict with at least {id, name, images}.
    Raises ValueError if scraping fails or no meaningful data found.
    """
    url = url.strip().rstrip("/")

    # ── 1. Try Shopify .json (works on any Shopify-hosted product URL) ────
    if "/products/" in url:
        json_url = url.split("?")[0]  # strip query params first
        if not json_url.endswith(".json"):
            json_url = json_url + ".json"
        try:
            r = _requests.get(json_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                data = r.json()
                p = data.get("product")
                if p and p.get("title"):
                    # Extract base store URL
                    from urllib.parse import urlparse as _up
                    parsed = _up(url)
                    store_url = f"{parsed.scheme}://{parsed.netloc}"
                    result = _upsert_scraped_product(workspace_id, url, p, "shopify_json")
                    if result:
                        return result
        except Exception as e:
            print(f"Shopify .json scrape failed for {url}: {e}")

    # ── 2. Fetch HTML and extract OG tags ─────────────────────────────────
    try:
        r = _requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        html = r.text
    except Exception as e:
        raise ValueError(f"Could not fetch URL: {e}")

    og = _extract_og_tags(html)

    # If OG gives us at least a title + image, use it
    if og.get("title") and og.get("images"):
        result = _upsert_scraped_product(workspace_id, url, og, "og_tags")
        if result:
            return result

    # ── 3. Claude extraction fallback ─────────────────────────────────────
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""You are extracting product info from a single product page.
URL: {url}

Below is the page HTML (truncated). Extract the product details and return ONLY a JSON object.

Required fields:
- title (string, required)
- description (string)
- price_inr (number — the selling price in INR, look for ₹ symbol)
- mrp_inr (number — the MRP / original crossed-out price if shown)
- images (array of absolute image URLs — product photos only, not icons/logos)
- sku (string)
- category (string)
- key_features (array of short bullet strings)

Return ONLY valid JSON object, no markdown fences.

HTML:
{html[:12000]}"""

    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown fences if present
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        p = json.loads(raw)
        if not p.get("title"):
            raise ValueError("Claude could not extract product title from this page")
        result = _upsert_scraped_product(workspace_id, url, p, "claude")
        if result:
            return result
    except json.JSONDecodeError:
        pass
    except ValueError:
        raise
    except Exception as e:
        print(f"Claude scrape fallback error: {e}")

    raise ValueError("Could not extract product data from this URL")


def _extract_og_tags(html: str) -> dict:
    """Extract Open Graph and meta product tags from HTML."""
    import re as _re

    def _meta(prop: str) -> str | None:
        m = _re.search(
            rf'<meta[^>]+(?:property|name)=["\'](?:og:|product:)?{_re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            html, _re.IGNORECASE
        )
        if m:
            return m.group(1).strip()
        # Also try content before property (some sites reverse the order)
        m = _re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:|product:)?{_re.escape(prop)}["\']',
            html, _re.IGNORECASE
        )
        return m.group(1).strip() if m else None

    title = _meta("title")
    description = _meta("description")
    image = _meta("image")
    price = _meta("price:amount") or _meta("price")
    currency = _meta("price:currency") or "INR"

    images = []
    if image:
        images.append(image)
    # Also try og:image:secure_url and additional og:images
    for m in _re.finditer(
        r'<meta[^>]+(?:property|name)=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        html, _re.IGNORECASE
    ):
        img_url = m.group(1).strip()
        if img_url not in images:
            images.append(img_url)

    price_inr = None
    if price:
        try:
            price_inr = float(re.sub(r'[^\d.]', '', price))
        except ValueError:
            pass

    return {
        "title": title,
        "description": description,
        "images": images,
        "price_inr": price_inr if currency in ("INR", "₹") else None,
        "price_raw": price,
    }


def _upsert_scraped_product(workspace_id: str, url: str, p: dict, method: str) -> dict | None:
    """
    Insert/update a product scraped from a URL.
    source_platform='scraped', source_product_id=url (the canonical identifier).
    """
    try:
        title = p.get("title") or p.get("name") or ""
        if not title:
            return None

        description = _strip_html(p.get("description") or p.get("body_html") or "")

        # Price
        price_inr = None
        mrp_inr = None
        if p.get("price_inr") is not None:
            try:
                price_inr = float(p["price_inr"])
            except (ValueError, TypeError):
                pass
        if p.get("mrp_inr") is not None:
            try:
                mrp_inr = float(p["mrp_inr"])
            except (ValueError, TypeError):
                pass

        # Images — handle both list-of-strings and Shopify list-of-dicts
        raw_images = p.get("images", [])
        images = []
        for img in raw_images:
            if isinstance(img, str) and img.startswith("http"):
                images.append({"url": img, "alt": "", "position": len(images)})
            elif isinstance(img, dict) and img.get("src"):
                images.append({"url": img["src"], "alt": img.get("alt", ""), "position": img.get("position", len(images))})

        # SKU, category, features
        sku = p.get("sku") or None
        category = p.get("category") or p.get("product_type") or None
        key_features = p.get("key_features") or p.get("tags") or []
        if isinstance(key_features, str):
            key_features = [t.strip() for t in key_features.split(",") if t.strip()]

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO products (
                        workspace_id, name, description, price_inr, mrp_inr,
                        product_url, images, sku, category,
                        key_features, source_platform, source_product_id,
                        active, last_synced_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'scraped',%s,TRUE,NOW())
                    ON CONFLICT (workspace_id, source_platform, source_product_id)
                    DO UPDATE SET
                        name            = EXCLUDED.name,
                        description     = EXCLUDED.description,
                        price_inr       = EXCLUDED.price_inr,
                        mrp_inr         = EXCLUDED.mrp_inr,
                        images          = EXCLUDED.images,
                        sku             = EXCLUDED.sku,
                        category        = EXCLUDED.category,
                        key_features    = EXCLUDED.key_features,
                        active          = TRUE,
                        last_synced_at  = NOW(),
                        updated_at      = NOW()
                    RETURNING id
                    """,
                    (
                        workspace_id, title, description or None,
                        price_inr, mrp_inr,
                        url, json.dumps(images),
                        sku, category,
                        json.dumps(key_features if isinstance(key_features, list) else []),
                        url,  # source_product_id = the URL itself
                    ),
                )
                row = cur.fetchone()
                internal_id = str(row[0]) if row else None

        print(f"Scraped product ({method}): '{title}' from {url} → id={internal_id}")
        invalidate_workspace_cache(workspace_id)
        return {
            "id": internal_id,
            "name": title,
            "price_inr": price_inr,
            "images": images,
            "product_url": url,
            "source_platform": "scraped",
            "source_product_id": url,
            "method": method,
        }
    except Exception as e:
        print(f"Error upserting scraped product from {url}: {e}")
        return None


def delete_product(workspace_id: str, product_id: str) -> bool:
    """Hard-delete a product by ID (only if it belongs to the workspace)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM products WHERE id=%s AND workspace_id=%s RETURNING id",
                    (product_id, workspace_id),
                )
                deleted = cur.fetchone()
        invalidate_workspace_cache(workspace_id)
        return deleted is not None
    except Exception as e:
        print(f"Error deleting product {product_id}: {e}")
        return False


# ── Utility ───────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """Remove HTML tags, return plain text."""
    return re.sub(r'<[^>]+>', ' ', html or '').strip()


def _deactivate_removed_products(workspace_id: str, platform: str, active_ids: list[str]):
    """Mark products that no longer appear in the store's catalog as inactive."""
    if not active_ids:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE products
                SET active = FALSE, updated_at = NOW()
                WHERE workspace_id = %s
                  AND source_platform = %s
                  AND source_product_id != ALL(%s)
                  AND active = TRUE
                """,
                (workspace_id, platform, active_ids),
            )
