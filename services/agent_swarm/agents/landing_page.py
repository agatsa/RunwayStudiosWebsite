# services/agent_swarm/agents/landing_page.py
"""
Agent 4 — Landing Page Auditor (runs hourly)
Fetches homepage/product/checkout, scores clarity/trust/friction.
"""
import json
import re

import anthropic
import requests

from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, LANDING_PAGE_URL
from services.agent_swarm.db import get_conn


def _fetch_page(url: str) -> tuple[str, int]:
    """Fetch page HTML and return (text_content, raw_length)."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10; Mobile) "
                "AppleWebKit/537.36 Chrome/91.0.4472.114 Mobile Safari/537.36"
            )
        }
        r = requests.get(url, headers=headers, timeout=20)
        raw_len = len(r.text)

        # Strip HTML tags for Claude (keep meaningful text)
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', r.text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text[:4000], raw_len
    except Exception as e:
        return f"[Page fetch failed: {e}]", 0


def _audit_with_claude(url: str, page_text: str) -> dict:
    prompt = f"""You are a conversion rate optimization (CRO) expert auditing a landing page for an Indian D2C brand.

URL: {url}

=== PAGE CONTENT (truncated) ===
{page_text[:3500]}

=== AUDIT TASK ===
Score this landing page on 3 dimensions (0-10 each):
1. CLARITY — Is the offer, product, and value prop immediately clear?
2. TRUST — Social proof, testimonials, guarantees, certifications visible?
3. FRICTION — How easy is it to take action? (fewer steps = less friction = higher score)

Then identify specific issues and recommendations.

Return ONLY valid JSON:
{{
  "clarity_score": 7,
  "trust_score": 5,
  "friction_score": 6,
  "overall_score": 6.0,
  "issues": [
    "No testimonials visible above the fold",
    "CTA button not prominent on mobile",
    "Price not shown on homepage"
  ],
  "recommendations": [
    "Add 3-5 customer reviews above the fold",
    "Make CTA button sticky on mobile scroll",
    "Show pricing or 'starting from' prominently"
  ],
  "verdict": "1-sentence WhatsApp-friendly verdict"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(match.group()) if match else {"error": raw}


def _write_audit(url: str, result: dict, raw_len: int, agent_response: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO landing_page_audits
                  (url, clarity_score, trust_score, friction_score, overall_score,
                   issues, recommendations, raw_html_length, agent_response)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    url,
                    result.get("clarity_score"),
                    result.get("trust_score"),
                    result.get("friction_score"),
                    result.get("overall_score"),
                    json.dumps(result.get("issues", [])),
                    json.dumps(result.get("recommendations", [])),
                    raw_len,
                    agent_response,
                ),
            )


def run_landing_page_audit(url: str | None = None) -> dict:
    target_url = url or LANDING_PAGE_URL
    if not target_url:
        return {"ok": False, "error": "LANDING_PAGE_URL not configured"}

    page_text, raw_len = _fetch_page(target_url)
    result = _audit_with_claude(target_url, page_text)

    if "error" not in result:
        _write_audit(target_url, result, raw_len, json.dumps(result))

    return {
        "ok": True,
        "url": target_url,
        "scores": {
            "clarity": result.get("clarity_score"),
            "trust": result.get("trust_score"),
            "friction": result.get("friction_score"),
            "overall": result.get("overall_score"),
        },
        "issues": result.get("issues", []),
        "recommendations": result.get("recommendations", []),
        "verdict": result.get("verdict", ""),
    }
