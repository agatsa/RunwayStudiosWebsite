# services/agent_swarm/agents/lp_analyst.py
"""
Landing Page Deep Analyst — Sales Intelligence Layer

Extends the basic landing_page.py audit with:
  • Promise vs delivery gap  — do our running ads match what the LP says?
  • Google PageSpeed score   — mobile performance (PAGESPEED_API_KEY optional)
  • Mobile UX analysis       — specific mobile conversion killers
  • Offer strength analysis  — pricing clarity, urgency, CTA prominence
  • Competitor comparison    — how does our LP compare to what competitors offer?

Called by sales_strategist.py. Also usable standalone.
"""
import json
import os
import re

import anthropic
import requests

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    LANDING_PAGE_URL,
)
from services.agent_swarm.db import get_conn

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY", "")


# ── Page fetcher ────────────────────────────────────────────

def _fetch_page(url: str) -> tuple[str, int]:
    """Fetch page and return (stripped_text, raw_html_length)."""
    try:
        r = requests.get(
            url, timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Mobile Safari/537.36"},
        )
        raw_len = len(r.text)
        html = r.text
        html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:4000], raw_len
    except Exception as e:
        return f"[Page fetch failed: {e}]", 0


# ── Google PageSpeed ────────────────────────────────────────

def _get_pagespeed(url: str) -> dict:
    """
    Call Google PageSpeed Insights API for mobile score.
    Returns dict with score, metrics, opportunities.
    Skipped gracefully if PAGESPEED_API_KEY not set.
    """
    try:
        params = {
            "url": url,
            "strategy": "mobile",
            "category": "performance",
        }
        if _PAGESPEED_API_KEY:
            params["key"] = _PAGESPEED_API_KEY

        r = requests.get(
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            params=params, timeout=30,
        )
        if not r.ok:
            return {}
        data = r.json()
        lhr = data.get("lighthouseResult", {})
        categories = lhr.get("categories", {})
        perf = categories.get("performance", {})
        score = perf.get("score", None)

        audits = lhr.get("audits", {})
        opportunities = []
        for key, audit in audits.items():
            if audit.get("score") is not None and float(audit.get("score", 1)) < 0.9:
                savings = audit.get("details", {}).get("overallSavingsMs", 0)
                if savings and float(savings) > 500:
                    opportunities.append({
                        "issue": audit.get("title", key),
                        "savings_ms": round(float(savings), 0),
                    })

        opportunities.sort(key=lambda x: x.get("savings_ms", 0), reverse=True)

        return {
            "mobile_score": round(float(score) * 100) if score is not None else None,
            "top_opportunities": opportunities[:5],
        }
    except Exception as e:
        print(f"lp_analyst: PageSpeed failed: {e}")
        return {}


# ── Recent ad copy from DB ──────────────────────────────────

def _get_recent_ad_copy(tenant_id: str) -> list[dict]:
    """Fetch the last 3 approved/running ad creatives to check promise consistency."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT angle, hook, headline, primary_text, landing_page_url
                    FROM creative_queue
                    WHERE tenant_id = %s
                      AND status IN ('published', 'approved', 'pending_approval')
                    ORDER BY created_at DESC
                    LIMIT 3
                    """,
                    (tenant_id,),
                )
                rows = cur.fetchall()
        return [
            {
                "angle": r[0], "hook": r[1], "headline": r[2],
                "primary_text": (r[3] or "")[:300],
                "landing_page_url": r[4],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"lp_analyst: ad copy fetch failed: {e}")
        return []


# ── Deep LP audit with Claude ───────────────────────────────

def _deep_audit_with_claude(
    url: str,
    page_text: str,
    ad_copy_samples: list[dict],
    pagespeed: dict,
    competitor_summary: str = "",
) -> dict:
    """Claude performs the deep LP analysis."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    ps_section = ""
    if pagespeed.get("mobile_score") is not None:
        ps_section = f"\n=== MOBILE PAGESPEED SCORE: {pagespeed['mobile_score']}/100 ===\n"
        if pagespeed.get("top_opportunities"):
            ps_section += f"Top issues: {json.dumps(pagespeed['top_opportunities'][:3])}\n"

    ad_section = ""
    if ad_copy_samples:
        ad_section = f"\n=== CURRENT RUNNING ADS (for promise vs delivery check) ===\n{json.dumps(ad_copy_samples, indent=2)}\n"

    comp_section = ""
    if competitor_summary:
        comp_section = f"\n=== COMPETITOR LP CONTEXT ===\n{competitor_summary}\n"

    prompt = f"""You are a senior CRO (Conversion Rate Optimization) expert for Indian D2C e-commerce.

URL: {url}
{ps_section}
=== PAGE CONTENT ===
{page_text[:3000]}
{ad_section}{comp_section}
=== DEEP AUDIT TASK ===
Perform a comprehensive landing page analysis. Be specific — cite actual content from the page.

Return ONLY valid JSON:
{{
  "clarity_score": 7,
  "trust_score": 6,
  "friction_score": 5,
  "mobile_score": 4,
  "offer_strength_score": 6,
  "overall_score": 5.6,
  "promise_gap": "Is the LP delivering on what the ads promise? Cite specific mismatches if any.",
  "price_visibility": "Is price clear and compelling? Above fold? Compare to ads.",
  "offer_analysis": "Main offer strength — is it compelling vs what competitors show?",
  "trust_gaps": ["specific missing trust element 1", "specific missing trust element 2"],
  "friction_points": ["specific friction point 1", "specific friction point 2"],
  "mobile_issues": ["specific mobile UX issue 1", "specific mobile UX issue 2"],
  "above_fold_audit": "What does the user see first on mobile? Is CTA visible without scrolling?",
  "critical_fixes": [
    {{
      "fix": "Specific actionable fix",
      "impact": "high|medium|low",
      "effort": "easy|medium|hard"
    }}
  ],
  "verdict": "2-sentence WhatsApp-friendly verdict"
}}"""

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"lp_analyst: Claude audit failed: {e}")
    return {}


# ── Main entry point ────────────────────────────────────────

def run_lp_analyst(
    url: str = None,
    tenant: dict = None,
    competitor_summary: str = "",
) -> dict:
    """
    Deep landing page analysis: basic scores + promise gap + mobile speed + offer strength.

    url: override URL (defaults to tenant's landing_page_url or LANDING_PAGE_URL env)
    competitor_summary: optional competitor context from competitor_monitor
    """
    tenant_id = (tenant or {}).get("id") or _DEFAULT_TENANT_ID
    target_url = (
        url
        or (tenant or {}).get("landing_page_url")
        or LANDING_PAGE_URL
    )
    if not target_url:
        return {"ok": False, "error": "No landing page URL configured"}

    print(f"lp_analyst: auditing {target_url}")

    # 1. Fetch page
    page_text, raw_len = _fetch_page(target_url)

    # 2. PageSpeed (mobile)
    pagespeed = _get_pagespeed(target_url)

    # 3. Recent ad copy for promise-vs-delivery check
    ad_copy = _get_recent_ad_copy(tenant_id)

    # 4. Deep Claude audit
    result = _deep_audit_with_claude(target_url, page_text, ad_copy, pagespeed, competitor_summary)

    # Merge pagespeed score into result
    if pagespeed.get("mobile_score") is not None and "mobile_score" not in result:
        result["mobile_score"] = pagespeed["mobile_score"]

    return {
        "ok": True,
        "url": target_url,
        "scores": {
            "clarity": result.get("clarity_score"),
            "trust": result.get("trust_score"),
            "friction": result.get("friction_score"),
            "mobile": result.get("mobile_score"),
            "offer_strength": result.get("offer_strength_score"),
            "overall": result.get("overall_score"),
        },
        "promise_gap": result.get("promise_gap", ""),
        "price_visibility": result.get("price_visibility", ""),
        "offer_analysis": result.get("offer_analysis", ""),
        "trust_gaps": result.get("trust_gaps", []),
        "friction_points": result.get("friction_points", []),
        "mobile_issues": result.get("mobile_issues", []),
        "above_fold_audit": result.get("above_fold_audit", ""),
        "critical_fixes": result.get("critical_fixes", []),
        "verdict": result.get("verdict", ""),
        "pagespeed": pagespeed,
        "raw_len": raw_len,
    }
