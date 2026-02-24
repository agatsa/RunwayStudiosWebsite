# services/agent_swarm/agents/competitor_monitor.py
"""
Competitor Monitor — Sales Intelligence Layer

1. Uses Claude to generate competitor search queries from product context
2. Scrapes DuckDuckGo for competitor brand/product URLs (no API key needed)
3. Scrapes each competitor landing page (pricing, offer, features, guarantees)
4. Claude produces deep competitive analysis:
   - What are competitors doing that's working?
   - Where are WE lagging RIGHT NOW vs competitors?
   - Specific opportunity gaps based on current performance data

Saves to competitor_intelligence table. Called by sales_strategist.py.
"""
import json
import re
import urllib.parse
from datetime import datetime, timezone

import anthropic
import requests

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    META_ADS_TOKEN, PRODUCT_CONTEXT,
)
from services.agent_swarm.db import get_conn

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


# ── Step 1: Claude generates search queries ─────────────────

def _get_search_queries(product_context: str, landing_page_url: str = None) -> list[str]:
    """Ask Claude what to search to find real direct competitors."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    lp_hint = f"\nOur landing page: {landing_page_url}" if landing_page_url else ""
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"Product:\n{product_context[:600]}{lp_hint}\n\n"
                    "Generate 4 search queries to find the top competing brands/products "
                    "sold online in India that are direct alternatives to this product.\n"
                    "Focus on queries that return competitor brand websites — "
                    "NOT Amazon, Flipkart, or generic articles.\n"
                    "Example: 'boAt smartwatch buy India', 'noise smartwatch India official'\n\n"
                    "Return ONLY a JSON array of 4 strings."
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        m = re.search(r"\[[\s\S]*?\]", raw)
        if m:
            queries = json.loads(m.group())
            return [str(q).strip() for q in queries[:4] if q]
    except Exception as e:
        print(f"competitor_monitor: query generation failed: {e}")
    return ["health wearable smartband India buy", "wellness smart band India official site"]


# ── Step 2: DuckDuckGo web search ──────────────────────────

def _search_duckduckgo(query: str, num: int = 6) -> list[str]:
    """Search DuckDuckGo HTML and extract top result URLs."""
    urls = []
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": "in-en"},
            headers=_HEADERS,
            timeout=15,
        )
        raw_links = re.findall(r'uddg=(https?[^&"]+)', r.text)
        for link in raw_links:
            decoded = urllib.parse.unquote(link)
            skip = ("amazon.", "flipkart.", "wikipedia.", "indiamart.", "quora.",
                    "reddit.", "youtube.", "meesho.", "snapdeal.", "myntra.",
                    "duckduckgo.", "google.", "facebook.", "instagram.", "twitter.")
            if any(s in decoded.lower() for s in skip):
                continue
            urls.append(decoded)
            if len(urls) >= num:
                break
    except Exception as e:
        print(f"competitor_monitor: DuckDuckGo search failed for '{query}': {e}")
    return urls


def _deduplicate_by_domain(urls: list[str], max_results: int = 5) -> list[str]:
    """Keep one URL per domain, up to max_results."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        try:
            domain = urllib.parse.urlparse(url).netloc.lstrip("www.")
            if domain and domain not in seen:
                seen.add(domain)
                out.append(url)
                if len(out) >= max_results:
                    break
        except Exception:
            pass
    return out


# ── Step 3: Scrape competitor landing pages ─────────────────

def _scrape_page(url: str, max_chars: int = 4000) -> dict:
    """Fetch a competitor page and return cleaned text + metadata."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        html = r.text
        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"<[^>]+>", "", title_m.group(1) if title_m else "").strip()
        html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        domain = urllib.parse.urlparse(url).netloc.lstrip("www.")
        return {"url": url, "domain": domain, "title": title, "text": text[:max_chars]}
    except Exception as e:
        print(f"competitor_monitor: scrape failed ({url}): {e}")
        return {}


# ── Step 4: Claude analyses each competitor page ────────────

def _analyse_competitor(page: dict, our_product_context: str) -> dict:
    """Extract structured competitive intel from a scraped competitor page."""
    if not page.get("text"):
        return {}
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": (
                    f"Competitor: {page['domain']}\nURL: {page['url']}\n"
                    f"Page title: {page.get('title', '')}\n\n"
                    f"PAGE CONTENT:\n{page['text'][:3000]}\n\n"
                    f"OUR PRODUCT (for comparison):\n{our_product_context[:400]}\n\n"
                    "Extract competitive intel. Return ONLY JSON:\n"
                    '{{\n'
                    '  "brand": "brand name",\n'
                    '  "product_name": "their main product name",\n'
                    '  "price": "price or price range in INR",\n'
                    '  "key_offer": "main offer shown — discount, EMI, bundle, free gift etc.",\n'
                    '  "guarantee": "return/refund/warranty policy",\n'
                    '  "top_features": ["feature 1", "feature 2", "feature 3"],\n'
                    '  "ad_angles": ["emotional/pain-point angle", "social proof angle", "urgency angle"],\n'
                    '  "trust_signals": ["X reviews", "certifications", "media mentions"],\n'
                    '  "cta": "primary buy/CTA button text",\n'
                    '  "strengths_vs_us": "what they do better than us in 1-2 sentences",\n'
                    '  "weaknesses_vs_us": "where we have a clear advantage in 1-2 sentences"\n'
                    '}}'
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            data = json.loads(m.group())
            data["url"] = page["url"]
            data["domain"] = page["domain"]
            return data
    except Exception as e:
        print(f"competitor_monitor: analysis failed for {page.get('domain', '?')}: {e}")
    return {"domain": page.get("domain", ""), "url": page.get("url", "")}


# ── Step 5: Claude deep gap analysis vs current performance ─

def _generate_gap_analysis(
    competitors: list[dict],
    our_product_context: str,
    our_lp_url: str,
    current_performance: dict,
) -> dict:
    """
    Synthesises all competitor data + our CURRENT performance metrics
    to identify exactly where we are lagging and what to do about it.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    perf_summary = "No recent performance data available."
    if current_performance:
        spend = current_performance.get("spend_7d", 0)
        roas = current_performance.get("roas_7d", 0)
        ctr = current_performance.get("ctr_7d", 0)
        cpc = current_performance.get("cpc_7d", 0)
        conv = current_performance.get("conversions_7d", 0)
        cpm = current_performance.get("cpm_7d", 0)
        perf_summary = (
            f"7-day: ₹{spend:.0f} spend | ROAS {roas:.2f}x | "
            f"CTR {ctr:.2f}% | CPC ₹{cpc:.0f} | CPM ₹{cpm:.0f} | {conv} conversions"
        )

    valid = [c for c in competitors if c.get("brand")]

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1200,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a senior growth strategist analysing an Indian D2C brand's competitive position.\n\n"
                    f"OUR PRODUCT:\n{our_product_context[:500]}\n"
                    f"Our landing page: {our_lp_url or 'N/A'}\n"
                    f"OUR CURRENT PERFORMANCE: {perf_summary}\n\n"
                    f"COMPETITOR INTELLIGENCE ({len(valid)} competitors researched):\n"
                    f"{json.dumps(valid, indent=2)[:4000]}\n\n"
                    "Based on the CURRENT performance data and competitor research, produce a sharp, "
                    "data-driven competitive analysis focused on where we are lagging RIGHT NOW "
                    "and the most impactful fixes.\n\n"
                    "Return ONLY JSON:\n"
                    '{{\n'
                    '  "summary": "3-4 sentences: market landscape, what competitors are doing, '
                    'key patterns you see",\n'
                    '  "where_we_lag": [\n'
                    '    {{"area": "Pricing|Offer|Creative|Trust|LP|Audience|Spend", '
                    '"gap": "specific gap with data context", '
                    '"competitor_example": "brand + what they do", '
                    '"fix": "specific actionable fix with expected impact"}},\n'
                    '    ...\n'
                    '  ],\n'
                    '  "our_advantages": ["advantage 1 — be specific, cite product features or data", '
                    '"advantage 2"],\n'
                    '  "opportunity_gaps": ["gap no competitor fills that we could own"],\n'
                    '  "winning_ad_angles": ["angle 1 that competitors use successfully + why it works"],\n'
                    '  "top_priority_fix": "Single most impactful change to make THIS WEEK based on current metrics"\n'
                    '}}'
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                # Attempt repair of truncated JSON
                candidate = m.group().rstrip().rstrip(",")
                candidate += "]}" * candidate.count("[") - candidate.count("]")
                try:
                    return json.loads(candidate)
                except Exception:
                    pass
    except Exception as e:
        print(f"competitor_monitor: gap analysis failed: {e}")

    return {
        "summary": "Competitor data collected — gap analysis incomplete.",
        "where_we_lag": [],
        "our_advantages": [],
        "opportunity_gaps": [],
        "winning_ad_angles": [],
        "top_priority_fix": "",
    }


# ── DB persistence ──────────────────────────────────────────

def _save(tenant_id, search_terms, total_found, top_competitors, opportunity_gaps, summary):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO competitor_intelligence
                         (tenant_id, search_terms, total_ads_found,
                          top_competitors, opportunity_gaps, summary)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (tenant_id, search_terms, total_found,
                     json.dumps(top_competitors), json.dumps(opportunity_gaps), summary),
                )
    except Exception as e:
        print(f"competitor_monitor: DB save failed: {e}")


# ── Main entry point ────────────────────────────────────────

def run_competitor_monitor(
    tenant: dict = None,
    own_page_name: str = None,
    current_performance: dict = None,
) -> dict:
    """
    Web-based competitor research pipeline:
    1. Claude generates search queries from product context
    2. DuckDuckGo finds competitor URLs
    3. Scrape each competitor LP
    4. Claude analyses each + produces gap analysis vs our current performance
    """
    tenant_id = (tenant or {}).get("id") or _DEFAULT_TENANT_ID
    product_ctx = (tenant or {}).get("product_context") or PRODUCT_CONTEXT
    lp_url = (tenant or {}).get("landing_page_url") or ""

    # Step 1: Generate search queries
    print("competitor_monitor: generating search queries...")
    queries = _get_search_queries(product_ctx, lp_url)
    print(f"competitor_monitor: queries = {queries}")

    # Step 2: Search DuckDuckGo
    all_urls: list[str] = []
    for q in queries:
        found = _search_duckduckgo(q)
        print(f"competitor_monitor: '{q}' → {len(found)} URLs")
        all_urls.extend(found)

    competitor_urls = _deduplicate_by_domain(all_urls, max_results=5)
    print(f"competitor_monitor: scraping {len(competitor_urls)} pages: {competitor_urls}")

    # Step 3: Scrape each competitor page
    scraped = [_scrape_page(url) for url in competitor_urls]
    scraped = [p for p in scraped if p.get("text")]

    # Step 4: Analyse each with Claude
    print(f"competitor_monitor: analysing {len(scraped)} pages...")
    competitors = [_analyse_competitor(p, product_ctx) for p in scraped]
    competitors = [c for c in competitors if c]

    # Step 5: Gap analysis vs current performance
    print("competitor_monitor: running gap analysis vs current performance...")
    gap_analysis = _generate_gap_analysis(competitors, product_ctx, lp_url, current_performance or {})

    summary = gap_analysis.get("summary", "")
    opportunity_gaps = gap_analysis.get("opportunity_gaps", [])

    # Step 6: Save to DB
    _save(tenant_id, queries, len(competitors), competitors, opportunity_gaps, summary)

    return {
        "ok": True,
        "search_terms": queries,
        "total_ads_found": len(competitors),
        "top_competitors": competitors,
        "gap_analysis": gap_analysis,
        "opportunity_gaps": opportunity_gaps,
        "summary": summary,
    }
