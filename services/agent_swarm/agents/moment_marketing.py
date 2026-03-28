# services/agent_swarm/agents/moment_marketing.py
"""
Moment Marketing Agent — runs daily at 8am IST via Cloud Scheduler.

Spots marketing opportunities (festivals, health awareness days, salary windows,
trending news) and generates ad creatives for WhatsApp approval.
Deduplicates via the moment_campaigns DB table (one trigger per occasion per month).
"""
from datetime import date, datetime, timezone

import anthropic

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, WA_REPORT_NUMBER,
)
from services.agent_swarm.db import get_conn
from services.agent_swarm.wa import send_text
from services.agent_swarm.agents.calendar_agent import get_upcoming_occasions
from services.agent_swarm.agents.creative_generator import run_creative_generator


def _is_already_triggered(occasion: str) -> bool:
    """Return True if this occasion was already triggered this calendar month."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM moment_campaigns
                WHERE occasion = %s
                  AND DATE_TRUNC('month', COALESCE(occasion_date, triggered_at::date))
                      = DATE_TRUNC('month', CURRENT_DATE)
                LIMIT 1
                """,
                (occasion,),
            )
            return cur.fetchone() is not None


def _record_triggered(occasion: str, occasion_date_str: str | None, category: str):
    """Insert a row into moment_campaigns so we won't re-trigger this month."""
    occ_date = None
    if occasion_date_str:
        try:
            occ_date = date.fromisoformat(occasion_date_str)
        except Exception:
            pass
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO moment_campaigns (occasion, occasion_date, category)
                VALUES (%s, %s, %s)
                """,
                (occasion, occ_date, category),
            )


def _get_trending_angle() -> str | None:
    """
    Ask Claude for a trending health/wellness angle in India right now.
    Returns a 1-2 sentence angle string, or None if nothing significant.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today = date.today().isoformat()
    from services.agent_swarm.config import PRODUCT_CONTEXT
    brand_ctx = (PRODUCT_CONTEXT or "Indian D2C brand")[:300]
    prompt = f"""You are a moment marketing strategist for the following brand:
{brand_ctx}

Today is {today}. Based on your knowledge of India:
- Are there any upcoming trends, news events, cultural moments, or occasions in the next 7 days that are highly relevant to this brand's target audience?
- If yes: suggest 1 specific ad angle in 1-2 sentences. Start with "TREND:"
- If nothing significant: reply "NO_TREND"

Reply with ONLY "TREND: <angle>" or "NO_TREND". No other text."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    if text.startswith("TREND:"):
        return text[len("TREND:"):].strip()
    return None


def run_moment_marketing(platform: str, account_id: str) -> dict:
    """
    Daily moment marketing agent.
    1. Check upcoming occasions (7-day horizon) from calendar_agent
    2. Filter: high/very_high importance + not already triggered this month
    3. Ask Claude for trending news angle
    4. Generate up to 2 creatives and send to WhatsApp for approval
    """
    triggered_count = 0
    triggered_occasions = []
    errors = []

    # 1. Get upcoming occasions (7-day window)
    try:
        cal = get_upcoming_occasions(horizon_days=7)
        top_priority = cal.get("top_priority", [])
    except Exception as e:
        return {"ok": False, "error": f"Calendar fetch failed: {e}"}

    # 2. Filter to new high-priority occasions
    new_occasions = []
    for occ in top_priority:
        if occ.get("importance") not in ("high", "very_high"):
            continue
        if _is_already_triggered(occ["occasion"]):
            print(f"Moment marketing: skipping '{occ['occasion']}' — already triggered this month")
            continue
        new_occasions.append(occ)

    # Cap at 2 creatives per day
    new_occasions = new_occasions[:2]

    # 3. Generate creative for each new occasion
    for occ in new_occasions:
        try:
            trigger_reason = (
                f"MOMENT MARKETING: {occ['occasion']} on {occ['date']} ({occ['days_away']} days away). "
                f"Category: {occ['category']}. "
                f"Create a highly relevant, time-sensitive ad for this brand that ties into this moment."
            )
            result = run_creative_generator(
                platform, account_id,
                trigger_reason=trigger_reason,
                num_concepts=1,
            )
            if result.get("ok"):
                _record_triggered(occ["occasion"], occ.get("date"), occ["category"])
                triggered_occasions.append(occ["occasion"])
                triggered_count += 1
        except Exception as e:
            errors.append({"occasion": occ["occasion"], "error": str(e)})

    # 4. Trending news angle (if we still have capacity)
    if triggered_count < 2:
        try:
            trend = _get_trending_angle()
            if trend:
                trend_key = f"TRENDING_NEWS_{date.today().isoformat()}"
                if not _is_already_triggered(trend_key):
                    trigger_reason = (
                        f"TRENDING MOMENT: {trend}. "
                        f"This is a timely opportunity for this brand — create a relevant, newsworthy ad."
                    )
                    result = run_creative_generator(
                        platform, account_id,
                        trigger_reason=trigger_reason,
                        num_concepts=1,
                    )
                    if result.get("ok"):
                        _record_triggered(trend_key, str(date.today()), "trending")
                        triggered_occasions.append("Trending news")
                        triggered_count += 1
        except Exception as e:
            errors.append({"occasion": "trending_news", "error": str(e)})

    # 5. If nothing triggered, send a brief status message
    if triggered_count == 0 and not errors:
        send_text(
            WA_REPORT_NUMBER,
            "📅 Daily check: no new high-priority occasions in next 7 days. "
            "Monitoring continues — creatives will arrive here when opportunities arise.",
        )

    return {
        "ok": True,
        "triggered_count": triggered_count,
        "triggered_occasions": triggered_occasions,
        "errors": errors,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
