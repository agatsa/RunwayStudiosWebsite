"""
services/agent_swarm/connectors/brand_scraper.py

Stateless scraping utilities for Brand Intelligence.
No DB, no FastAPI — pure async functions.

Layers:
  1. Page fetch + HTML stripping
  2. Tech stack detection
  3. Social link extraction
  4. Meta Ad Library (public API)
  5. DuckDuckGo SERP scrape
  6. Trustpilot / G2 review scrape
"""

import re
import json
import asyncio
from typing import Optional

import httpx

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_TIMEOUT = 15


# ── Page fetch ─────────────────────────────────────────────────────────────────

async def fetch_page(url: str) -> tuple[str, dict]:
    """Fetch URL → (html_text, response_headers). Returns ('', {}) on failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.text, dict(r.headers)
    except Exception:
        return "", {}


def strip_html(html: str) -> str:
    """Strip HTML tags, scripts, styles and collapse whitespace."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def fetch_text(url: str, max_chars: int = 4000) -> str:
    html, _ = await fetch_page(url)
    return strip_html(html)[:max_chars]


async def try_sub_pages(base_url: str, paths: list, max_chars: int = 2000) -> dict:
    """Try sub-page paths in parallel, return {path: text} for 200s."""
    base = base_url.rstrip("/")
    results = {}
    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _UA},
    ) as c:
        async def _get(path):
            try:
                r = await c.get(f"{base}/{path}")
                if r.status_code == 200:
                    results[path] = strip_html(r.text)[:max_chars]
            except Exception:
                pass
        await asyncio.gather(*[_get(p) for p in paths])
    return results


# ── Tech stack ──────────────────────────────────────────────────────────────────

_TECH_SIGNALS = {
    "klaviyo": "Klaviyo",
    "shopify": "Shopify",
    "woocommerce": "WooCommerce",
    "hubspot": "HubSpot",
    "intercom": "Intercom",
    "hotjar": "Hotjar",
    "gtag(": "Google Analytics",
    "google-analytics": "Google Analytics",
    "fbq(": "Meta Pixel",
    "segment.io": "Segment",
    "clevertap": "CleverTap",
    "webengage": "WebEngage",
    "mailchimp": "Mailchimp",
    "crisp.chat": "Crisp",
    "freshchat": "Freshchat",
    "zendesk": "Zendesk",
    "razorpay": "Razorpay",
    "stripe.js": "Stripe",
    "__next": "Next.js",
    "nuxt": "Nuxt.js",
    "react.production": "React",
    "angular": "Angular",
    "vue.min": "Vue.js",
    "wp-content": "WordPress",
    "squarespace": "Squarespace",
    "webflow": "Webflow",
    "appsflyer": "AppsFlyer",
    "adjust.com": "Adjust",
}


def detect_tech_stack(html: str, headers: dict) -> list:
    stack = set()
    src = html.lower()
    for signal, name in _TECH_SIGNALS.items():
        if signal in src:
            stack.add(name)
    server = headers.get("server", "").lower()
    if "shopify" in server:
        stack.add("Shopify")
    xpow = headers.get("x-powered-by", "").lower()
    if "next" in xpow:
        stack.add("Next.js")
    if "express" in xpow:
        stack.add("Node.js")
    return sorted(stack)


# ── Social links ────────────────────────────────────────────────────────────────

def extract_social_links(html: str) -> dict:
    patterns = {
        "facebook":  r"https?://(?:www\.)?facebook\.com/(?!sharer|share)([A-Za-z0-9._\-]+)",
        "instagram": r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9._\-]+)",
        "twitter":   r"https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9._\-]+)",
        "youtube":   r"https?://(?:www\.)?youtube\.com/(?:@|channel/|c/)([A-Za-z0-9._\-]+)",
        "linkedin":  r"https?://(?:www\.)?linkedin\.com/(?:company|in)/([A-Za-z0-9._\-]+)",
    }
    result = {}
    for platform, pattern in patterns.items():
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            result[platform] = m.group(0)
    return result


def extract_fb_page_handle(html: str) -> Optional[str]:
    """Extract Facebook page handle/name from social links in HTML."""
    m = re.search(
        r"facebook\.com/(?!sharer|share|dialog|tr\?)([A-Za-z0-9._\-]{3,})",
        html, re.IGNORECASE,
    )
    return m.group(1) if m else None


# ── Meta Ad Library ─────────────────────────────────────────────────────────────

def fetch_meta_ads(search_term: str, access_token: str, limit: int = 25) -> list:
    """
    Fetch active ads from Meta Ad Library for a brand/page name.
    Returns list of dicts. Returns [] on any error.
    Requires a valid Meta access_token (user or app token).
    """
    import requests
    if not access_token or not search_term:
        return []
    try:
        params = {
            "search_terms": search_term,
            "ad_type": "ALL",
            "fields": (
                "id,ad_creative_bodies,ad_creative_link_titles,"
                "ad_delivery_start_time,publisher_platforms,ad_snapshot_url"
            ),
            "limit": limit,
            "access_token": access_token,
        }
        r = requests.get(
            "https://graph.facebook.com/v21.0/ads_archive",
            params=params,
            timeout=20,
        )
        if r.status_code != 200:
            return []
        ads = r.json().get("data", [])
        return [
            {
                "id": ad.get("id"),
                "body": ((ad.get("ad_creative_bodies") or [""])[0])[:300],
                "title": ((ad.get("ad_creative_link_titles") or [""])[0])[:150],
                "start_date": ad.get("ad_delivery_start_time"),
                "platforms": ad.get("publisher_platforms", []),
                "snapshot_url": ad.get("ad_snapshot_url"),
            }
            for ad in ads
        ]
    except Exception:
        return []


def get_meta_app_token(app_id: str, app_secret: str) -> str:
    """Exchange App ID + Secret for an App Access Token."""
    import requests
    try:
        r = requests.get(
            "https://graph.facebook.com/oauth/access_token",
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "client_credentials",
            },
            timeout=10,
        )
        return r.json().get("access_token", "")
    except Exception:
        return ""


# ── DuckDuckGo SERP ──────────────────────────────────────────────────────────────

async def search_ddg(query: str, max_results: int = 8) -> list:
    """
    Scrape DuckDuckGo HTML search for a query.
    Returns list of {url, title}.
    """
    html, _ = await fetch_page(
        f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
    )
    if not html:
        return []
    results = []
    # DuckDuckGo HTML result links
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.DOTALL,
    ):
        url = m.group(1)
        title = strip_html(m.group(2))[:150]
        if url.startswith("//duckduckgo"):
            continue
        results.append({"url": url, "title": title})
        if len(results) >= max_results:
            break
    return results


async def serp_presence(brand_name: str, domain: str) -> dict:
    """
    Run 2-3 DuckDuckGo queries for a brand and return organic presence signals.
    """
    queries = [
        f'"{brand_name}" review',
        f"{brand_name} vs",
        f'site:{domain}',
    ]
    all_results = []
    for q in queries:
        r = await search_ddg(q, max_results=5)
        all_results.extend(r)
        await asyncio.sleep(0.5)   # polite delay

    branded_hits = sum(1 for r in all_results if domain.lower() in r.get("url", "").lower())
    return {
        "query_results": all_results,
        "branded_hits": branded_hits,
        "domain": domain,
    }


# ── Review scraping ──────────────────────────────────────────────────────────────

async def scrape_trustpilot(domain: str) -> dict:
    """Fetch public Trustpilot page for a domain and extract rating + snippets."""
    clean = (
        domain.replace("https://", "").replace("http://", "")
              .replace("www.", "").split("/")[0]
    )
    html, _ = await fetch_page(f"https://www.trustpilot.com/review/{clean}")
    if not html:
        return {"source": "trustpilot", "found": False}
    text = strip_html(html)
    rating_m  = re.search(r"(\d+\.\d+)\s*out of\s*5", text, re.IGNORECASE)
    reviews_m = re.search(r"([\d,]+)\s*(?:total\s*)?reviews?", text, re.IGNORECASE)
    # Grab up to 5 review snippet blocks
    snippets = re.findall(r'"reviewBody"\s*:\s*"([^"]{30,300})"', html)[:5]
    return {
        "source": "trustpilot",
        "found": bool(rating_m),
        "url": f"https://www.trustpilot.com/review/{clean}",
        "rating": float(rating_m.group(1)) if rating_m else None,
        "review_count": reviews_m.group(1).replace(",", "") if reviews_m else None,
        "snippets": snippets,
    }


async def scrape_g2(brand_name: str) -> dict:
    """Search G2 for a brand and extract rating + top review snippets."""
    slug = brand_name.lower().replace(" ", "-").replace(".", "")
    html, _ = await fetch_page(f"https://www.g2.com/products/{slug}/reviews")
    if not html or "page not found" in html.lower():
        # Try search
        html, _ = await fetch_page(
            f"https://www.g2.com/search?query={brand_name.replace(' ', '+')}"
        )
    if not html:
        return {"source": "g2", "found": False}
    text = strip_html(html)
    rating_m  = re.search(r"(\d+\.\d+)\s*/\s*5", text)
    reviews_m = re.search(r"([\d,]+)\s*reviews?", text, re.IGNORECASE)
    snippets  = re.findall(r'"reviewBody"\s*:\s*"([^"]{30,300})"', html)[:5]
    return {
        "source": "g2",
        "found": bool(rating_m),
        "rating": float(rating_m.group(1)) if rating_m else None,
        "review_count": reviews_m.group(1).replace(",", "") if reviews_m else None,
        "snippets": snippets,
    }


# ── Brand domain helper ──────────────────────────────────────────────────────────

def extract_domain(url: str) -> str:
    """https://www.example.com/page → example.com"""
    url = url.lower().replace("https://", "").replace("http://", "").replace("www.", "")
    return url.split("/")[0].split("?")[0]


def extract_brand_name(domain: str) -> str:
    """example.com → Example"""
    name = domain.split(".")[0]
    return name.replace("-", " ").replace("_", " ").title()
