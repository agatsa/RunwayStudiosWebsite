# services/agent_swarm/agents/fb_analyst.py
"""
Facebook Deep Analyst — Sales Intelligence Layer

Pulls data the basic KPI tracker never sees:
  • Age/gender breakdown  → which demographic converts vs burns budget
  • Placement breakdown   → Reels vs Feed vs Stories vs Audience Network
  • Device breakdown      → mobile vs desktop conversion differences
  • Ad relevance scores   → quality/engagement/conversion rankings vs competitors
  • Audience frequency    → saturation signals, when to refresh creative

Saves to fb_deep_insights table. Called by sales_strategist.py.
"""
import json
import re

import anthropic
import requests

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    META_ADS_TOKEN, META_GRAPH,
)
from services.agent_swarm.db import get_conn

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


# ── Meta API helper ─────────────────────────────────────────

def _meta_get(path: str, params: dict, meta_token: str) -> dict:
    params["access_token"] = meta_token
    try:
        r = requests.get(f"{META_GRAPH}{path}", params=params, timeout=30)
        return r.json()
    except Exception as e:
        print(f"fb_analyst _meta_get error ({path}): {e}")
        return {}


# ── Breakdown data ──────────────────────────────────────────

def _parse_purchase_actions(row: dict) -> tuple[float, float]:
    """Extract purchase count and revenue from Meta actions/action_values."""
    purchase_types = {
        "purchase", "offsite_conversion.fb_pixel_purchase",
        "omni_purchase", "web_in_store_purchase",
    }
    purchases = sum(
        float(a.get("value", 0))
        for a in (row.get("actions") or [])
        if a.get("action_type") in purchase_types
    )
    revenue = sum(
        float(a.get("value", 0))
        for a in (row.get("action_values") or [])
        if a.get("action_type") in purchase_types
    )
    return purchases, revenue


def _get_breakdown(account_id: str, meta_token: str, breakdown: str) -> list[dict]:
    """Get account-level insights broken down by a single dimension."""
    data = _meta_get(
        f"/{account_id}/insights",
        {
            "level": "account",
            "breakdowns": breakdown,
            "fields": "spend,impressions,clicks,actions,action_values",
            "date_preset": "last_7d",
            "limit": 100,
        },
        meta_token,
    )
    rows = data.get("data", [])
    result = []
    for row in rows:
        purchases, revenue = _parse_purchase_actions(row)
        spend = float(row.get("spend", 0) or 0)
        impressions = int(row.get("impressions", 0) or 0)
        clicks = int(row.get("clicks", 0) or 0)
        # Build dimension key dict from available row fields
        dim_keys = [k.strip() for k in breakdown.split(",")]
        dim_vals = {k: row.get(k, "") for k in dim_keys if k in row}
        result.append({
            "segment": dim_vals,
            "spend": round(spend, 2),
            "impressions": impressions,
            "clicks": clicks,
            "purchases": round(purchases, 1),
            "revenue": round(revenue, 2),
            "ctr": round(clicks / impressions, 4) if impressions > 0 else 0,
            "roas": round(revenue / spend, 2) if spend > 0 else 0,
            "cpa": round(spend / purchases, 2) if purchases > 0 else None,
        })
    # Sort by spend descending
    result.sort(key=lambda x: x["spend"], reverse=True)
    return result


# ── Ad relevance diagnostics ────────────────────────────────

def _get_ad_relevance(account_id: str, meta_token: str) -> list[dict]:
    """
    Get ad-level quality/engagement/conversion relevance rankings.
    These tell you how Meta scores your ads vs other advertisers
    competing for the same audience.
    """
    data = _meta_get(
        f"/{account_id}/insights",
        {
            "level": "ad",
            "fields": (
                "ad_id,ad_name,"
                "quality_ranking,engagement_rate_ranking,conversion_rate_ranking,"
                "spend,impressions,ctr,cpm,actions,action_values"
            ),
            "date_preset": "last_7d",
            "filtering": json.dumps([
                {"field": "spend", "operator": "GREATER_THAN", "value": "0"}
            ]),
            "limit": 50,
        },
        meta_token,
    )
    rows = data.get("data", [])
    result = []
    for row in rows:
        purchases, revenue = _parse_purchase_actions(row)
        spend = float(row.get("spend", 0) or 0)
        result.append({
            "ad_id": row.get("ad_id", ""),
            "ad_name": (row.get("ad_name") or "")[:60],
            "quality_ranking": row.get("quality_ranking", "UNKNOWN"),
            "engagement_rate_ranking": row.get("engagement_rate_ranking", "UNKNOWN"),
            "conversion_rate_ranking": row.get("conversion_rate_ranking", "UNKNOWN"),
            "spend": round(spend, 2),
            "impressions": int(row.get("impressions", 0) or 0),
            "ctr": float(row.get("ctr", 0) or 0),
            "cpm": float(row.get("cpm", 0) or 0),
            "roas": round(revenue / spend, 2) if spend > 0 else 0,
            "below_average_count": sum(1 for f in [
                row.get("quality_ranking"),
                row.get("engagement_rate_ranking"),
                row.get("conversion_rate_ranking"),
            ] if f and "BELOW_AVERAGE" in str(f)),
        })
    result.sort(key=lambda x: x["spend"], reverse=True)
    return result


# ── Frequency & audience saturation ────────────────────────

def _get_frequency(account_id: str, meta_token: str) -> list[dict]:
    """
    Frequency = average number of times a unique user saw your ad.
    > 3.0 = audience fatigue zone; creative refresh needed.
    """
    data = _meta_get(
        f"/{account_id}/insights",
        {
            "level": "adset",
            "fields": "adset_id,adset_name,frequency,reach,impressions,spend",
            "date_preset": "last_7d",
            "filtering": json.dumps([
                {"field": "spend", "operator": "GREATER_THAN", "value": "0"}
            ]),
            "limit": 50,
        },
        meta_token,
    )
    rows = data.get("data", [])
    result = []
    for row in rows:
        freq = float(row.get("frequency", 0) or 0)
        spend = float(row.get("spend", 0) or 0)
        saturation = "critical" if freq > 4 else ("high" if freq > 3 else ("medium" if freq > 2 else "low"))
        result.append({
            "adset_id": row.get("adset_id", ""),
            "adset_name": (row.get("adset_name") or "")[:60],
            "frequency": round(freq, 2),
            "reach": int(row.get("reach", 0) or 0),
            "impressions": int(row.get("impressions", 0) or 0),
            "spend": round(spend, 2),
            "saturation_level": saturation,
        })
    result.sort(key=lambda x: x["frequency"], reverse=True)
    return result


# ── Claude summary ──────────────────────────────────────────

def _summarize_with_claude(
    breakdowns: dict,
    relevance: list,
    frequency: list,
) -> str:
    """Ask Claude to produce a crisp diagnostic summary of the FB data."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Trim data to keep prompt size reasonable
    ag = breakdowns.get("age_gender", [])[:10]
    pl = breakdowns.get("placement", [])[:8]
    dv = breakdowns.get("device", [])[:6]
    rel = relevance[:10]
    freq = frequency[:8]

    prompt = f"""You are a Facebook Ads performance analyst.
Analyze this data for an Indian D2C brand and produce a concise diagnostic summary (max 250 words).

Focus on:
1. Which age/gender segments are wasting money vs converting well?
2. Which placements are efficient vs draining budget?
3. Which ads have below-average quality/engagement/conversion rankings?
4. Which adsets have dangerously high frequency (audience fatigue)?
5. What are the top 3 immediate opportunities?

=== AGE/GENDER BREAKDOWN (by spend) ===
{json.dumps(ag, indent=2)}

=== PLACEMENT BREAKDOWN ===
{json.dumps(pl, indent=2)}

=== DEVICE BREAKDOWN ===
{json.dumps(dv, indent=2)}

=== AD RELEVANCE DIAGNOSTICS ===
{json.dumps(rel, indent=2)}

=== FREQUENCY / AUDIENCE SATURATION ===
{json.dumps(freq, indent=2)}

Return plain text with clear bullet points. Be specific — use the actual numbers."""

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"fb_analyst Claude summary failed: {e}")
        return ""


# ── DB persistence ──────────────────────────────────────────

def _save(
    tenant_id: str, platform: str, account_id: str,
    breakdowns: dict, relevance: list, frequency: list, summary: str,
) -> None:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO fb_deep_insights
                      (tenant_id, platform, account_id, analysis_date,
                       age_gender, placement, device, relevance, frequency, summary)
                    VALUES (%s,%s,%s,CURRENT_DATE,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        tenant_id, platform, account_id,
                        json.dumps(breakdowns.get("age_gender", [])),
                        json.dumps(breakdowns.get("placement", [])),
                        json.dumps(breakdowns.get("device", [])),
                        json.dumps(relevance),
                        json.dumps(frequency),
                        summary,
                    ),
                )
    except Exception as e:
        print(f"fb_analyst DB save failed: {e}")


# ── Main entry point ────────────────────────────────────────

def run_fb_deep_analysis(
    platform: str,
    account_id: str,
    tenant: dict = None,
) -> dict:
    """
    Pull deep Facebook Ads breakdown data, relevance diagnostics,
    and frequency stats. Saves to fb_deep_insights. Returns structured dict.

    account_id: the Meta ad account ID (with or without 'act_' prefix).
    """
    meta_token = (tenant or {}).get("meta_access_token") or META_ADS_TOKEN
    tenant_id = (tenant or {}).get("id") or _DEFAULT_TENANT_ID

    # Meta requires 'act_' prefix
    meta_acct = account_id if account_id.startswith("act_") else f"act_{account_id}"

    breakdowns: dict = {}

    for dim_name, breakdown_param in [
        ("age_gender", "age,gender"),
        ("placement",  "publisher_platform,platform_position"),
        ("device",     "device_platform"),
    ]:
        try:
            breakdowns[dim_name] = _get_breakdown(meta_acct, meta_token, breakdown_param)
            print(f"fb_analyst: {dim_name} — {len(breakdowns[dim_name])} rows")
        except Exception as e:
            print(f"fb_analyst: {dim_name} breakdown failed: {e}")
            breakdowns[dim_name] = []

    relevance: list = []
    try:
        relevance = _get_ad_relevance(meta_acct, meta_token)
        print(f"fb_analyst: relevance — {len(relevance)} ads")
    except Exception as e:
        print(f"fb_analyst: relevance failed: {e}")

    frequency: list = []
    try:
        frequency = _get_frequency(meta_acct, meta_token)
        print(f"fb_analyst: frequency — {len(frequency)} adsets")
    except Exception as e:
        print(f"fb_analyst: frequency failed: {e}")

    summary = ""
    if any([breakdowns.get("age_gender"), relevance, frequency]):
        summary = _summarize_with_claude(breakdowns, relevance, frequency)

    _save(tenant_id, platform, account_id, breakdowns, relevance, frequency, summary)

    return {
        "ok": True,
        "breakdowns": breakdowns,
        "relevance_diagnostics": relevance,
        "frequency": frequency,
        "summary": summary,
        "high_saturation_adsets": [f for f in frequency if f["saturation_level"] in ("high", "critical")],
        "below_average_ads": [r for r in relevance if r.get("below_average_count", 0) >= 2],
    }
