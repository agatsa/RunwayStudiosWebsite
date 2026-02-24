# services/agent_swarm/agents/performance.py
"""
Agent 1 — Performance Analyst (Claude-powered, runs hourly)
Detects: CAC spikes, ROAS drops, CTR fatigue, spend anomalies
Returns: {risk_level, causes, recommended_action, metrics}
"""
import json
from datetime import datetime, timedelta, timezone

import anthropic

from services.agent_swarm.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from services.agent_swarm.db import get_conn, fetchone_dict, fetchall_dict


def _fetch_metrics(platform: str, account_id: str) -> dict:
    now = datetime.now(timezone.utc)
    t3 = now - timedelta(hours=3)
    t24 = now - timedelta(hours=24)

    with get_conn() as conn:
        with conn.cursor() as cur:
            # 24h metrics
            cur.execute(
                """
                SELECT COALESCE(SUM(spend),0) spend,
                       COALESCE(SUM(clicks),0) clicks,
                       COALESCE(SUM(impressions),0) imps,
                       COALESCE(SUM(revenue),0) revenue,
                       COALESCE(SUM(conversions),0) conversions
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t24),
            )
            r24 = cur.fetchone()
            spend24, clicks24, imp24, rev24, conv24 = [float(x or 0) for x in r24]

            # 3h metrics
            cur.execute(
                """
                SELECT COALESCE(SUM(spend),0) spend,
                       COALESCE(SUM(clicks),0) clicks,
                       COALESCE(SUM(impressions),0) imps,
                       COALESCE(SUM(revenue),0) revenue,
                       COALESCE(SUM(conversions),0) conversions
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t3),
            )
            r3 = cur.fetchone()
            spend3, clicks3, imp3, rev3, conv3 = [float(x or 0) for x in r3]

            # Fatigue watchlist (ads with fatigue_flag=true in last 3 days)
            cur.execute(
                """
                SELECT entity_id, fatigue_score, fatigue_ctr_ratio, ctr, roas, spend
                FROM mem_entity_daily
                WHERE platform=%s AND account_id=%s AND entity_level='ad'
                  AND fatigue_flag=true
                  AND day >= CURRENT_DATE - INTERVAL '3 days'
                ORDER BY fatigue_score DESC
                LIMIT 10
                """,
                (platform, account_id),
            )
            fatigue_ads = [
                {
                    "ad_id": row[0],
                    "fatigue_score": float(row[1] or 0),
                    "ctr_ratio": float(row[2] or 0),
                    "ctr": float(row[3] or 0),
                    "roas": float(row[4] or 0),
                    "spend": float(row[5] or 0),
                }
                for row in cur.fetchall()
            ]

            # Recent alerts (last 6h)
            cur.execute(
                """
                SELECT alert_type, severity, summary
                FROM alerts
                WHERE platform=%s AND account_id=%s
                  AND ts >= NOW() - INTERVAL '6 hours'
                  AND resolved=false
                ORDER BY ts DESC
                LIMIT 10
                """,
                (platform, account_id),
            )
            recent_alerts = [
                {"type": row[0], "severity": row[1], "summary": row[2]}
                for row in cur.fetchall()
            ]

            # Yesterday's daily digest for context
            cur.execute(
                """
                SELECT digest_text FROM mem_daily_digest
                WHERE platform=%s AND account_id=%s
                ORDER BY day DESC LIMIT 1
                """,
                (platform, account_id),
            )
            row = cur.fetchone()
            last_digest = row[0] if row else "No prior digest available."

    def safe_div(a, b):
        return round(a / b, 4) if b and b > 0 else None

    return {
        "window_3h": {
            "spend": round(spend3, 2),
            "clicks": int(clicks3),
            "impressions": int(imp3),
            "revenue": round(rev3, 2),
            "conversions": int(conv3),
            "roas": safe_div(rev3, spend3),
            "ctr": safe_div(clicks3, imp3),
            "cac": safe_div(spend3, conv3),
        },
        "window_24h": {
            "spend": round(spend24, 2),
            "clicks": int(clicks24),
            "impressions": int(imp24),
            "revenue": round(rev24, 2),
            "conversions": int(conv24),
            "roas": safe_div(rev24, spend24),
            "ctr": safe_div(clicks24, imp24),
            "cac": safe_div(spend24, conv24),
        },
        "fatigue_ads": fatigue_ads,
        "recent_alerts": recent_alerts,
        "last_digest": last_digest,
    }


def analyze_account(platform: str, account_id: str) -> dict:
    metrics = _fetch_metrics(platform, account_id)

    prompt = f"""You are a performance marketing analyst for an Indian D2C brand running Meta ads.

Analyze the following ad account metrics and return a JSON assessment.

Account: {account_id} | Platform: {platform}
Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

=== METRICS (last 3h vs 24h) ===
{json.dumps(metrics['window_3h'], indent=2)} (3h)
{json.dumps(metrics['window_24h'], indent=2)} (24h)

=== FATIGUE WATCHLIST ({len(metrics['fatigue_ads'])} ads) ===
{json.dumps(metrics['fatigue_ads'], indent=2)}

=== RECENT ALERTS ===
{json.dumps(metrics['recent_alerts'], indent=2)}

=== LAST DAILY DIGEST ===
{metrics['last_digest'][:500]}

=== ANALYSIS RULES ===
- ROAS drop: if 3h ROAS < 70% of 24h ROAS → HIGH risk
- CTR fatigue: if 3h CTR < 70% of 24h CTR → MEDIUM risk
- Spend spike: if 3h spend > 60% of 24h spend → MEDIUM risk
- CAC spike: if 3h CAC > 150% of 24h CAC → HIGH risk
- Multiple flags → escalate to HIGH

Return ONLY valid JSON (no markdown, no explanation):
{{
  "risk_level": "low|medium|high",
  "causes": ["list of detected issues"],
  "recommended_action": "single most important action to take right now",
  "scale_suggestion": "increase|decrease|hold",
  "scale_pct": 0,
  "pause_adsets": [],
  "summary": "2-sentence WhatsApp-friendly summary"
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Extract JSON from response if wrapped in text
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(match.group()) if match else {"risk_level": "unknown", "raw": raw}

    result["metrics"] = metrics
    return result
