"""
services/agent_swarm/connectors/lp_auditor.py

Landing Page Auditor — ported from lp-auditor project.
Uses httpx + BeautifulSoup (no Playwright) so it works on Cloud Run.

6 phases:
  1. Technical audit  — load time, CTAs, price visibility, images
  2. Score            — 100-pt scale based on conversion signals
  3. Recommendations  — Claude Haiku (4 specific fixes)
  4. Competitor audit — same audit on brand_intel competitor URLs
  5. Conversion win   — Claude picks which LP would convert best from paid ad
  6. LP intel stored  — returned as dict for Growth OS + DB persistence
"""

import re
import time
import json
import asyncio
from typing import Optional

import httpx
from bs4 import BeautifulSoup

import anthropic
from services.agent_swarm.config import ANTHROPIC_API_KEY

CLAUDE_HAIKU  = "claude-haiku-4-5-20251001"
CLAUDE_SONNET = "claude-sonnet-4-6"

_TIMEOUT = 15
_UA_MOBILE  = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
_UA_DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

CTA_KEYWORDS = [
    # E-commerce
    "buy", "shop", "order", "pre-book", "add to cart", "checkout",
    "book now", "buy now", "get it now", "purchase", "claim", "grab",
    "get yours", "add to bag",
    # SaaS / tools / lead-gen
    "get started", "try free", "start free", "sign up", "subscribe",
    "enquire", "book a demo", "get quote", "book a call", "schedule demo",
    "watch demo", "request demo", "see how", "request access",
    "analyse", "analyze", "start now", "try now", "free trial",
    "get access", "join free", "create account", "register free",
    "get free", "start today", "join now", "download free",
    "see pricing", "view plans", "get report", "run report",
    "explore", "discover", "learn more", "find out",
]

PRICE_PATTERN = re.compile(r'[₹$€£]\s*[\d,]+|[\d,]+\s*(?:rs|inr|usd)', re.IGNORECASE)


# ── Core audit ─────────────────────────────────────────────────────────────────

async def _fetch_page(url: str, mobile: bool = True) -> tuple[str, float, int]:
    """Fetch a URL, return (html, load_ms, status_code)."""
    ua = _UA_MOBILE if mobile else _UA_DESKTOP
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True, headers=headers
        ) as c:
            r = await c.get(url)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return r.text, elapsed_ms, r.status_code
    except Exception:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return "", elapsed_ms, 0


def _extract_signals(html: str) -> dict:
    """Extract conversion signals from HTML using BeautifulSoup."""
    if not html:
        return {
            "title": "", "meta_desc": "", "h1": "",
            "cta_count": 0, "ctas": [],
            "price_visible": False, "price_text": "",
            "image_count": 0, "broken_image_count": 0,
            "word_count": 0, "has_trust_signals": False,
            "has_reviews": False, "has_guarantee": False,
        }

    soup = BeautifulSoup(html, "lxml")

    # Remove scripts/styles for text analysis
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    title = (soup.find("title") or {}).get_text(strip=True) if soup.find("title") else ""
    meta_desc_tag = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    meta_desc = meta_desc_tag.get("content", "")[:200] if meta_desc_tag else ""
    h1_tag = soup.find("h1")
    h1 = h1_tag.get_text(strip=True)[:150] if h1_tag else ""

    # CTA detection — buttons and prominent links
    ctas = []
    for tag in soup.find_all(["button", "a", "input"]):
        text = tag.get_text(strip=True).lower()
        tag_text = tag.get_text(strip=True)
        if not text or len(text) > 80:
            continue
        # Match by keyword OR by visual CTA signals (btn class, onclick, arrow)
        classes = " ".join(tag.get("class", [])).lower()
        has_btn_class = any(c in classes for c in ["btn", "cta", "button", "primary", "action"])
        has_onclick = bool(tag.get("onclick") or tag.get("data-action"))
        has_arrow = "→" in tag_text or "->" in tag_text
        if (any(kw in text for kw in CTA_KEYWORDS)
                or (has_btn_class and len(text) < 40)
                or (has_onclick and len(text) < 40)
                or (has_arrow and len(text) < 40)):
            ctas.append({"text": tag_text[:60], "tag": tag.name})
        if len(ctas) >= 10:
            break

    # Price detection
    page_text = soup.get_text(" ")
    price_matches = PRICE_PATTERN.findall(page_text[:3000])  # above-fold proxy
    price_visible = bool(price_matches)
    price_text = price_matches[0] if price_matches else ""

    # Images
    images = soup.find_all("img")
    image_count = len(images)
    broken = sum(1 for img in images if not img.get("src") or img.get("src", "").startswith("data:"))

    # Trust signals
    body_text = page_text.lower()
    has_reviews = any(w in body_text for w in ["review", "rating", "stars", "verified", "testimonial", "customer"])
    has_guarantee = any(w in body_text for w in ["guarantee", "warranty", "refund", "return", "money back", "assured"])
    has_trust = any(w in body_text for w in ["certified", "iso", "award", "secure", "ssl", "trusted", "years", "customers"])
    word_count = len(page_text.split())

    return {
        "title": title,
        "meta_desc": meta_desc,
        "h1": h1,
        "cta_count": len(ctas),
        "ctas": ctas[:6],
        "price_visible": price_visible,
        "price_text": price_text,
        "image_count": image_count,
        "broken_image_count": broken,
        "word_count": word_count,
        "has_trust_signals": has_trust,
        "has_reviews": has_reviews,
        "has_guarantee": has_guarantee,
        "page_text_snippet": page_text[:800] + " " + page_text[len(page_text)//2:len(page_text)//2+600] + " " + page_text[-400:],
    }


def _score_page(signals: dict, load_ms: int) -> tuple[int, list[str]]:
    """Score a page 0–100 based on conversion signals. Returns (score, issues)."""
    score = 100
    issues = []

    # Load time
    if load_ms > 5000:
        score -= 20
        issues.append(f"Very slow load ({load_ms}ms) — kills conversion from paid ads, target <3s")
    elif load_ms > 3000:
        score -= 10
        issues.append(f"Slow load ({load_ms}ms) — target under 3,000ms for paid traffic")

    # CTAs
    if signals["cta_count"] == 0:
        score -= 25
        issues.append("No CTA detected — visitors have nowhere to convert")
    elif signals["cta_count"] == 1:
        score -= 5
        issues.append("Only 1 CTA — add a secondary CTA for different intent levels")

    # Price
    if not signals["price_visible"]:
        score -= 15
        issues.append("Price not visible in page text — friction for paid ad visitors expecting pricing")

    # Broken images
    if signals["broken_image_count"] > 0:
        score -= 10
        issues.append(f"{signals['broken_image_count']} broken image(s) — looks untrustworthy")

    # Trust signals
    if not signals["has_reviews"]:
        score -= 5
        issues.append("No customer reviews/ratings visible — social proof increases conversion by 15–30%")
    if not signals["has_guarantee"]:
        score -= 5
        issues.append("No guarantee/return policy visible — reduces purchase anxiety")

    # No H1
    if not signals.get("h1"):
        score -= 5
        issues.append("No H1 heading — page relevance signal for both SEO and visitor orientation")

    return max(0, score), issues


def _grade(score: int) -> str:
    if score >= 85: return "A"
    if score >= 70: return "B"
    if score >= 55: return "C"
    if score >= 40: return "D"
    return "F"


# ── Audit a single URL ─────────────────────────────────────────────────────────

async def audit_url(url: str, name: str = None) -> dict:
    """Full audit of one URL. Returns structured result dict."""
    if not url.startswith("http"):
        url = "https://" + url

    label = name or url

    # Fetch mobile + desktop in parallel
    (html_m, load_m, status_m), (html_d, load_d, status_d) = await asyncio.gather(
        _fetch_page(url, mobile=True),
        _fetch_page(url, mobile=False),
    )

    if not html_m and not html_d:
        return {
            "name": label, "url": url, "reachable": False,
            "score": 0, "grade": "F", "load_ms": load_m,
            "issues": ["Page unreachable or timeout"], "signals": {}, "recommendations": [],
        }

    signals = _extract_signals(html_m or html_d)
    score, issues = _score_page(signals, load_m)
    grade = _grade(score)

    return {
        "name": label,
        "url": url,
        "reachable": True,
        "score": score,
        "grade": grade,
        "load_ms_mobile": load_m,
        "load_ms_desktop": load_d,
        "signals": signals,
        "issues": issues,
    }


# ── Claude recommendations ─────────────────────────────────────────────────────

async def get_recommendations(audit: dict) -> list[dict]:
    """Claude Haiku — 4 specific conversion improvements for our site."""
    try:
        s = audit.get("signals", {})
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_HAIKU,
            max_tokens=800,
            messages=[{"role": "user", "content": (
                f"Landing page audit for: {audit['url']}\n"
                f"Score: {audit['score']}/100 (Grade {audit['grade']})\n"
                f"Mobile load: {audit['load_ms_mobile']}ms\n"
                f"CTAs detected: {s.get('cta_count', 0)}\n"
                f"Price visible: {s.get('price_visible', False)}\n"
                f"Reviews visible: {s.get('has_reviews', False)}\n"
                f"Guarantee visible: {s.get('has_guarantee', False)}\n"
                f"Broken images: {s.get('broken_image_count', 0)}\n"
                f"Issues: {'; '.join(audit.get('issues', []))}\n"
                f"Page snippet: {s.get('page_text_snippet', '')[:400]}\n\n"
                "Give 4 specific, actionable recommendations to improve this landing page's "
                "conversion rate for paid ad traffic (Facebook/Google ads).\n"
                "Return ONLY a JSON array:\n"
                '[{"priority":"HIGH|MEDIUM|LOW","title":"Short title","detail":"2-3 sentences what to do and why","impact":"Expected improvement e.g. +20% CVR"}]'
            )}],
        )
        raw = msg.content[0].text.strip()
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        print(f"[lp_auditor] recommendations failed: {e}")
    return []


# ── Conversion winner analysis ─────────────────────────────────────────────────

async def analyze_conversion_winner(sites: list[dict]) -> dict:
    """Claude Sonnet — compare all audited sites and pick the conversion winner."""
    if not sites:
        return {}
    try:
        site_summaries = []
        for i, s in enumerate(sites):
            sig = s.get("signals", {})
            site_summaries.append(
                f"[{i}] {s['name']} ({s['url']})\n"
                f"  Score: {s['score']}/100, Load: {s.get('load_ms_mobile', '?')}ms\n"
                f"  CTAs: {sig.get('cta_count', 0)}, Price visible: {sig.get('price_visible', False)}\n"
                f"  Reviews: {sig.get('has_reviews', False)}, Guarantee: {sig.get('has_guarantee', False)}\n"
                f"  Issues: {'; '.join(s.get('issues', [])[:3])}"
            )

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_SONNET,
            max_tokens=600,
            messages=[{"role": "user", "content": (
                "Analyse these landing pages and determine which is MOST LIKELY to convert "
                "a visitor into a buyer coming from a paid ad (Facebook/Google).\n\n"
                + "\n\n".join(site_summaries) +
                "\n\nReturn ONLY valid JSON:\n"
                '{"winner_index":0,"winner_name":"Name","confidence":"High|Medium|Low",'
                '"conversion_verdict":"One sentence why this wins",'
                '"key_insight":"One key insight separating high vs low converting pages",'
                '"site_verdicts":[{"name":"Site","verdict":"Short verdict","biggest_fix":"Top fix"}]}'
            )}],
        )
        raw = msg.content[0].text.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        print(f"[lp_auditor] conversion analysis failed: {e}")
    return {}


# ── Full audit orchestrator ────────────────────────────────────────────────────

async def run_full_audit(
    brand_url: str,
    competitor_urls: list[str] = None,
    brand_name: str = "Your Brand",
) -> dict:
    """
    Run full LP audit — our brand + up to 3 competitors.
    Returns complete audit dict suitable for DB storage and Growth OS.
    """
    if not brand_url:
        return {"error": "No brand URL provided"}

    urls_to_audit = [{"url": brand_url, "name": brand_name, "our_site": True}]
    for i, cu in enumerate((competitor_urls or [])[:3]):
        if cu:
            urls_to_audit.append({"url": cu, "name": f"Competitor {i+1}", "our_site": False})

    # Audit all sites in parallel
    audits = await asyncio.gather(*[
        audit_url(item["url"], item["name"])
        for item in urls_to_audit
    ])

    our_audit = audits[0]
    competitor_audits = list(audits[1:])

    # Get recommendations for our site + conversion winner in parallel
    recs, winner = await asyncio.gather(
        get_recommendations(our_audit),
        analyze_conversion_winner(list(audits)),
    )

    our_audit["recommendations"] = recs

    return {
        "our_site": our_audit,
        "competitors": competitor_audits,
        "conversion_analysis": winner,
        "summary": {
            "our_score": our_audit["score"],
            "our_grade": our_audit["grade"],
            "our_load_ms": our_audit.get("load_ms_mobile", 0),
            "our_cta_count": our_audit.get("signals", {}).get("cta_count", 0),
            "our_price_visible": our_audit.get("signals", {}).get("price_visible", False),
            "top_issue": our_audit.get("issues", [""])[0],
            "recommendation_count": len(recs),
        },
    }


# ── Growth OS summary (called from gather_intelligence) ───────────────────────

def get_lp_intel_from_db(workspace_id: str, conn) -> dict:
    """Load latest LP audit from DB for Growth OS context."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT audit_json, created_at
                FROM lp_audits
                WHERE workspace_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
            if not row:
                return {}
            data = row[0] if isinstance(row[0], dict) else {}
            return {
                "lp_score": data.get("summary", {}).get("our_score"),
                "lp_grade": data.get("summary", {}).get("our_grade"),
                "lp_load_ms": data.get("summary", {}).get("our_load_ms"),
                "lp_cta_count": data.get("summary", {}).get("our_cta_count"),
                "lp_price_visible": data.get("summary", {}).get("our_price_visible"),
                "lp_top_issue": data.get("summary", {}).get("top_issue", ""),
                "lp_recommendations": data.get("our_site", {}).get("recommendations", [])[:3],
                "lp_competitor_scores": [
                    {"name": c.get("name"), "score": c.get("score"), "grade": c.get("grade")}
                    for c in data.get("competitors", [])
                ],
                "lp_conversion_winner": data.get("conversion_analysis", {}).get("winner_name", ""),
                "lp_conversion_verdict": data.get("conversion_analysis", {}).get("conversion_verdict", ""),
                "lp_key_insight": data.get("conversion_analysis", {}).get("key_insight", ""),
                "lp_audited_at": row[1].isoformat() if row[1] else None,
            }
    except Exception as e:
        print(f"[lp_auditor] get_lp_intel_from_db failed: {e}")
        return {}
