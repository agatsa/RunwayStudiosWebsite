import os
from datetime import date
from services.ingestion_service.storage.postgres import get_conn, upsert_daily_kpis

def _parse_date(s: str) -> date:
    return date.fromisoformat(s)

def build_for_day(day: date):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  platform,
                  account_id,
                  entity_level,
                  entity_id,
                  DATE(hour_ts) AS day,

                  COALESCE(SUM(spend),0) AS spend,
                  COALESCE(SUM(impressions),0) AS impressions,
                  COALESCE(SUM(clicks),0) AS clicks,
                  COALESCE(SUM(conversions),0) AS conversions,
                  COALESCE(SUM(revenue),0) AS revenue,

                  CASE WHEN COALESCE(SUM(spend),0) > 0
                       THEN COALESCE(SUM(revenue),0) / SUM(spend)
                       ELSE 0 END AS roas,

                  CASE WHEN COALESCE(SUM(impressions),0) > 0
                       THEN (SUM(clicks)::numeric * 100.0) / SUM(impressions)
                       ELSE 0 END AS ctr,

                  CASE WHEN COALESCE(SUM(impressions),0) > 0
                       THEN (SUM(spend)::numeric * 1000.0) / SUM(impressions)
                       ELSE 0 END AS cpm,

                  CASE WHEN COALESCE(SUM(clicks),0) > 0
                       THEN (SUM(spend)::numeric) / SUM(clicks)
                       ELSE 0 END AS cpc
                FROM kpi_hourly
                WHERE DATE(hour_ts) = %s
                GROUP BY platform, account_id, entity_level, entity_id, DATE(hour_ts)
                """,
                (day,),
            )
            rows = cur.fetchall()

    payload = []
    for r in rows:
        platform, account_id, entity_level, entity_id, day_, spend, impressions, clicks, conversions, revenue, roas, ctr, cpm, cpc = r
        payload.append({
            "platform": platform,
            "account_id": account_id,
            "entity_level": entity_level,
            "entity_id": entity_id,
            "day": day_,
            "spend": float(spend or 0),
            "impressions": int(impressions or 0),
            "clicks": int(clicks or 0),
            "conversions": int(conversions or 0),
            "revenue": float(revenue or 0),
            "roas": float(roas or 0),
            "ctr": float(ctr or 0),
            "cpm": float(cpm or 0),
            "cpc": float(cpc or 0),
        })

    upsert_daily_kpis(payload)
    print(f"[daily_kpis] built day={day} rows={len(payload)}")

def main():
    day_env = os.getenv("DAY")
    if not day_env:
        raise RuntimeError("Set DAY=YYYY-MM-DD for now (since you currently have only 1 kpi_hourly row).")
    build_for_day(_parse_date(day_env))

if __name__ == "__main__":
    main()