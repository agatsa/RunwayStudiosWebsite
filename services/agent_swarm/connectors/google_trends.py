"""
services/agent_swarm/connectors/google_trends.py

Google Trends via pytrends — seasonality signals for Growth OS.
Fetches 12-month interest index for the brand's top keywords.
"""

import time
from typing import Optional


def get_trends_for_keywords(
    keywords: list[str],
    geo: str = "IN",
    timeframe: str = "today 12-m",
) -> dict:
    """
    Fetch Google Trends interest-over-time for up to 5 keywords.
    Returns dict with:
      - weekly_interest: {keyword: [52 weekly values (0-100)]}
      - peak_months: {keyword: "Oct-Nov"}
      - current_trend: {keyword: "rising|falling|stable"}
      - seasonality_summary: str
    """
    if not keywords:
        return {}

    keywords = [k.strip() for k in keywords[:5] if k.strip()]
    if not keywords:
        return {}

    try:
        from pytrends.request import TrendReq

        pt = TrendReq(hl="en-IN", tz=330, timeout=(10, 25), retries=2, backoff_factor=0.5)
        pt.build_payload(keywords, cat=0, timeframe=timeframe, geo=geo, gprop="")

        df = pt.interest_over_time()
        if df is None or df.empty:
            return {}

        weekly_interest = {}
        peak_months = {}
        current_trend = {}

        for kw in keywords:
            if kw not in df.columns:
                continue
            series = df[kw].tolist()
            weekly_interest[kw] = series

            # Find peak period — month with highest average
            if len(series) >= 4:
                # Group into 4-week buckets
                monthly = [sum(series[i:i+4]) / 4 for i in range(0, len(series) - 3, 4)]
                peak_idx = monthly.index(max(monthly))
                month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                # Approximate month from week index
                approx_month = (peak_idx) % 12
                peak_months[kw] = month_names[approx_month]

            # Current trend — compare last 4 weeks to prior 4 weeks
            if len(series) >= 8:
                recent = sum(series[-4:]) / 4
                prior = sum(series[-8:-4]) / 4
                if prior > 0:
                    delta = (recent - prior) / prior
                    if delta > 0.15:
                        current_trend[kw] = "rising"
                    elif delta < -0.15:
                        current_trend[kw] = "falling"
                    else:
                        current_trend[kw] = "stable"
                else:
                    current_trend[kw] = "stable"

        # Build plain-English summary
        rising = [k for k, v in current_trend.items() if v == "rising"]
        falling = [k for k, v in current_trend.items() if v == "falling"]
        summary_parts = []
        if rising:
            summary_parts.append(f"Rising now: {', '.join(rising)}")
        if falling:
            summary_parts.append(f"Falling: {', '.join(falling)}")
        if peak_months:
            for kw, mo in peak_months.items():
                summary_parts.append(f'"{kw}" peaks in {mo}')

        return {
            "keywords_tracked": keywords,
            "current_trend": current_trend,
            "peak_months": peak_months,
            "seasonality_summary": ". ".join(summary_parts),
            "weekly_interest": {k: v[-12:] for k, v in weekly_interest.items()},  # last 12 weeks only
        }

    except ImportError:
        print("[google_trends] pytrends not installed — skipping trends")
        return {}
    except Exception as e:
        print(f"[google_trends] trends fetch failed: {e}")
        return {}


def get_trends_for_workspace(workspace_id: str, conn) -> dict:
    """
    Pull the workspace's top search terms from DB, then fetch trends for those.
    Falls back to brand name if no search terms.
    """
    keywords = []
    brand_name = ""

    try:
        with conn.cursor() as cur:
            # Get top search terms
            cur.execute(
                """
                SELECT entity_name FROM kpi_hourly
                WHERE workspace_id = %s AND entity_level = 'search_term'
                  AND entity_name IS NOT NULL
                GROUP BY entity_name
                ORDER BY SUM(clicks) DESC
                LIMIT 5
                """,
                (workspace_id,),
            )
            keywords = [r[0] for r in cur.fetchall() if r[0]]

            if not keywords:
                # Fall back to brand name from workspace
                cur.execute(
                    "SELECT name, brand_url FROM workspaces WHERE id = %s",
                    (workspace_id,),
                )
                row = cur.fetchone()
                if row:
                    brand_name = row[0] or ""
                    if brand_name:
                        keywords = [brand_name]
    except Exception as e:
        print(f"[google_trends] DB query failed: {e}")

    if not keywords:
        return {}

    return get_trends_for_keywords(keywords)
