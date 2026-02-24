# services/agent_swarm/agents/creative_director.py
"""
Agent 3 — Creative Director (runs weekly)
Generates new hooks, UGC scripts, headlines, CTAs based on
weekly performance data + calendar context + fatigue watchlist.
Also detects creative fatigue: CTR < 0.7 * 7d avg → flag.
"""
import json
from datetime import date, timedelta

import anthropic

from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, META_AD_ACCOUNT_ID
from services.agent_swarm.agents.calendar_agent import get_upcoming_occasions
from services.agent_swarm.db import get_conn


def _fetch_weekly_context(platform: str, account_id: str) -> dict:
    today = date.today()
    week_start = today - timedelta(days=7)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Top performers last 7d
            cur.execute(
                """
                SELECT entity_id, SUM(spend) spend, AVG(roas) roas, AVG(ctr) ctr,
                       SUM(conversions) conversions
                FROM daily_kpis
                WHERE platform=%s AND account_id=%s AND entity_level='ad'
                  AND day >= %s
                GROUP BY entity_id
                HAVING SUM(spend) > 100
                ORDER BY AVG(roas) DESC
                LIMIT 5
                """,
                (platform, account_id, week_start),
            )
            top_ads = [
                {
                    "ad_id": r[0],
                    "spend": float(r[1] or 0),
                    "roas": float(r[2] or 0),
                    "ctr": float(r[3] or 0),
                    "conversions": int(r[4] or 0),
                }
                for r in cur.fetchall()
            ]

            # Fatigue watchlist
            cur.execute(
                """
                SELECT entity_id, AVG(fatigue_score) avg_fatigue, AVG(ctr) ctr,
                       AVG(fatigue_ctr_ratio) ctr_ratio
                FROM mem_entity_daily
                WHERE platform=%s AND account_id=%s AND entity_level='ad'
                  AND day >= %s AND fatigue_flag=true
                GROUP BY entity_id
                ORDER BY AVG(fatigue_score) DESC
                LIMIT 10
                """,
                (platform, account_id, week_start),
            )
            fatigued = [
                {
                    "ad_id": r[0],
                    "avg_fatigue": float(r[1] or 0),
                    "ctr": float(r[2] or 0),
                    "ctr_ratio": float(r[3] or 0),
                }
                for r in cur.fetchall()
            ]

            # Top objections this week
            cur.execute(
                """
                SELECT objection_type, SUM(count) total
                FROM fact_objections_daily
                WHERE platform=%s AND account_id=%s AND day >= %s
                GROUP BY objection_type
                ORDER BY SUM(count) DESC
                LIMIT 5
                """,
                (platform, account_id, week_start),
            )
            objections = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

            # Weekly digest
            cur.execute(
                """
                SELECT digest_text FROM mem_weekly_digest
                WHERE platform=%s AND account_id=%s
                ORDER BY week_start DESC LIMIT 1
                """,
                (platform, account_id),
            )
            row = cur.fetchone()
            weekly_digest = row[0] if row else "No weekly digest available."

    return {
        "top_ads": top_ads,
        "fatigued_ads": fatigued,
        "objections": objections,
        "weekly_digest": weekly_digest,
    }


def _detect_fatigue(platform: str, account_id: str) -> list[dict]:
    """Flag ads where current CTR < 0.7 * 7d avg CTR."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH recent AS (
                    SELECT entity_id,
                           AVG(ctr) AS ctr_7d
                    FROM daily_kpis
                    WHERE platform=%s AND account_id=%s AND entity_level='ad'
                      AND day >= CURRENT_DATE - INTERVAL '7 days'
                    GROUP BY entity_id
                ),
                today AS (
                    SELECT entity_id, AVG(ctr) AS ctr_today
                    FROM daily_kpis
                    WHERE platform=%s AND account_id=%s AND entity_level='ad'
                      AND day = CURRENT_DATE - INTERVAL '1 day'
                    GROUP BY entity_id
                )
                SELECT r.entity_id, t.ctr_today, r.ctr_7d,
                       t.ctr_today / NULLIF(r.ctr_7d, 0) AS ratio
                FROM recent r
                JOIN today t ON t.entity_id = r.entity_id
                WHERE r.ctr_7d > 0 AND t.ctr_today < 0.7 * r.ctr_7d
                ORDER BY ratio ASC
                LIMIT 10
                """,
                (platform, account_id, platform, account_id),
            )
            return [
                {
                    "ad_id": row[0],
                    "ctr_today": float(row[1] or 0),
                    "ctr_7d_avg": float(row[2] or 0),
                    "ratio": float(row[3] or 0),
                    "fatigue_flag": True,
                }
                for row in cur.fetchall()
            ]


def _write_suggestions(platform: str, account_id: str, week_start: date, suggestions: list[dict]):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for s in suggestions:
                cur.execute(
                    """
                    INSERT INTO creative_suggestions
                      (platform, account_id, week_start, suggestion_type, content, context_json)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        platform, account_id, week_start,
                        s.get("type"), s.get("content"),
                        json.dumps(s.get("context", {})),
                    ),
                )


def run_creative_director(platform: str, account_id: str) -> dict:
    ctx = _fetch_weekly_context(platform, account_id)
    fatigue_list = _detect_fatigue(platform, account_id)
    calendar = get_upcoming_occasions(horizon_days=14)

    prompt = f"""You are a world-class creative director for an Indian D2C brand running Meta ads.

Generate fresh creative ideas based on this week's performance data.

=== WEEKLY PERFORMANCE ===
{ctx['weekly_digest'][:600]}

=== TOP PERFORMING ADS (to learn from) ===
{json.dumps(ctx['top_ads'], indent=2)}

=== FATIGUED ADS (need replacement) ===
{json.dumps(ctx['fatigued_ads'][:5], indent=2)}

=== TOP CUSTOMER OBJECTIONS ===
{json.dumps(ctx['objections'], indent=2)}

=== UPCOMING CALENDAR CONTEXT ===
{calendar['creative_context']}

=== YOUR TASK ===
Generate 10 fresh creative ideas. Mix of:
- 3 scroll-stopping HOOKS (first 3 seconds of video/image text)
- 2 UGC scripts (150 words max each, conversational, Indian context)
- 2 HEADLINES (for ad copy, benefit-led)
- 2 CTAs (action-oriented, urgency)
- 1 OBJECTION HANDLER (address the top objection creatively)

Rules:
- Use Hindi-English mix where natural (Hinglish)
- Be specific, not generic
- Address real objections from data above
- Tie to calendar occasion if relevant
- Keep it punchy, mobile-first

Return ONLY valid JSON:
{{
  "suggestions": [
    {{
      "type": "hook|ugc_script|headline|cta|objection_handler",
      "content": "the actual creative text",
      "context": {{"rationale": "why this works", "occasion": "if tied to calendar"}}
    }}
  ],
  "fatigue_alerts": ["list of ad IDs needing immediate replacement"],
  "creative_brief": "3-sentence brief for the next week's creative team"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    try:
        result = json.loads(raw)
    except Exception:
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(match.group()) if match else {"suggestions": [], "raw": raw}

    # Write to DB
    week_start = date.today() - timedelta(days=date.today().weekday())
    _write_suggestions(platform, account_id, week_start, result.get("suggestions", []))

    return {
        "ok": True,
        "suggestions_count": len(result.get("suggestions", [])),
        "fatigue_alerts": result.get("fatigue_alerts", []),
        "fatigue_detected_count": len(fatigue_list),
        "creative_brief": result.get("creative_brief", ""),
        "suggestions": result.get("suggestions", []),
    }
