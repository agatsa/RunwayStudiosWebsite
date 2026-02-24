from datetime import datetime, timedelta, timezone
from services.ingestion_service.storage.postgres import get_conn


def analyze_account(platform: str, account_id: str):
    now = datetime.now(timezone.utc)
    t24 = now - timedelta(hours=24)
    t3 = now - timedelta(hours=3)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  COALESCE(SUM(spend),0),
                  COALESCE(SUM(clicks),0),
                  COALESCE(SUM(impressions),0),
                  COALESCE(SUM(revenue),0)
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t24),
            )
            spend24, clicks24, imp24, rev24 = cur.fetchone()

            cur.execute(
                """
                SELECT
                  COALESCE(SUM(spend),0),
                  COALESCE(SUM(clicks),0),
                  COALESCE(SUM(impressions),0),
                  COALESCE(SUM(revenue),0)
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t3),
            )
            spend3, clicks3, imp3, rev3 = cur.fetchone()

    def safe_div(a, b):
        return float(a)/float(b) if b and b > 0 else None

    roas24 = safe_div(rev24, spend24)
    roas3 = safe_div(rev3, spend3)

    ctr24 = safe_div(clicks24, imp24)
    ctr3 = safe_div(clicks3, imp3)

    risk = "low"
    causes = []
    recommendations = []

    if roas24 and roas3 and roas3 < 0.7 * roas24:
        risk = "high"
        causes.append("ROAS dropped sharply")
        recommendations.append("Reduce spend 15% on worst adsets")

    if ctr24 and ctr3 and ctr3 < 0.7 * ctr24:
        risk = "medium"
        causes.append("CTR fatigue detected")
        recommendations.append("Rotate creatives")

    if spend24 and spend3 and spend3 > 0.6 * spend24:
        risk = "medium"
        causes.append("Spend spike detected")
        recommendations.append("Review scaling rules")

    return {
        "risk_level": risk,
        "causes": causes,
        "recommendations": recommendations,
        "metrics": {
            "roas_24h": roas24,
            "roas_3h": roas3,
            "ctr_24h": ctr24,
            "ctr_3h": ctr3,
            "spend_24h": spend24,
            "spend_3h": spend3,
        },
    }