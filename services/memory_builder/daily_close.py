import os
from datetime import date, timedelta
from collections import defaultdict

from services.ingestion_service.storage.postgres import get_conn
from .utils.features import safe_div, fatigue_from_ratios
from .utils.templates import render_daily_digest

def _day_from_env():
    # default = yesterday
    d = os.getenv("DAY")
    if d:
        return date.fromisoformat(d)
    return date.today() - timedelta(days=1)

def _discover_accounts_for_day(conn, day: date):
    with conn.cursor() as cur:
        cur.execute("""
          SELECT DISTINCT platform, account_id
          FROM daily_kpis
          WHERE day = %s
        """, (day,))
        return cur.fetchall()  # (platform, account_id)

def _fetch_daily_rows(conn, day, platform, account_id, entity_level_filter=None):
    q = """
      SELECT platform, account_id, entity_level, entity_id, day,
             COALESCE(spend,0), COALESCE(impressions,0), COALESCE(clicks,0),
             COALESCE(conversions,0), COALESCE(revenue,0),
             COALESCE(roas,0), COALESCE(ctr,0), COALESCE(cpm,0), COALESCE(cpc,0)
      FROM daily_kpis
      WHERE day=%s AND platform=%s AND account_id=%s
    """
    params = [day, platform, account_id]
    if entity_level_filter:
        q += " AND entity_level=%s"
        params.append(entity_level_filter)

    with conn.cursor() as cur:
        cur.execute(q, params)
        rows = cur.fetchall()
    return rows

def _fetch_7d_baselines(conn, day, platform, account_id, entity_level):
    # baseline window: previous 7 days (exclude today)
    start = day - timedelta(days=7)
    end = day
    with conn.cursor() as cur:
        cur.execute("""
          SELECT entity_id,
                 AVG(COALESCE(ctr,0)) AS ctr7,
                 AVG(COALESCE(roas,0)) AS roas7
          FROM daily_kpis
          WHERE platform=%s AND account_id=%s AND entity_level=%s
            AND day >= %s AND day < %s
          GROUP BY entity_id
        """, (platform, account_id, entity_level, start, end))
        base = cur.fetchall()
    return {r[0]: {"ctr7": float(r[1] or 0), "roas7": float(r[2] or 0)} for r in base}

def _upsert_mem_entity_daily(conn, rows, baselines):
    upsert_sql = """
      INSERT INTO mem_entity_daily(
        platform, account_id, entity_level, entity_id, day,
        spend, impressions, clicks, conversions, revenue, roas, ctr, cpm, cpc,
        ctr_7d_avg, roas_7d_avg,
        fatigue_ctr_ratio, fatigue_roas_ratio, fatigue_score, fatigue_flag
      ) VALUES (
        %s,%s,%s,%s,%s,
        %s,%s,%s,%s,%s,%s,%s,%s,%s,
        %s,%s,
        %s,%s,%s,%s
      )
      ON CONFLICT (platform, account_id, entity_level, entity_id, day)
      DO UPDATE SET
        spend=EXCLUDED.spend,
        impressions=EXCLUDED.impressions,
        clicks=EXCLUDED.clicks,
        conversions=EXCLUDED.conversions,
        revenue=EXCLUDED.revenue,
        roas=EXCLUDED.roas,
        ctr=EXCLUDED.ctr,
        cpm=EXCLUDED.cpm,
        cpc=EXCLUDED.cpc,
        ctr_7d_avg=EXCLUDED.ctr_7d_avg,
        roas_7d_avg=EXCLUDED.roas_7d_avg,
        fatigue_ctr_ratio=EXCLUDED.fatigue_ctr_ratio,
        fatigue_roas_ratio=EXCLUDED.fatigue_roas_ratio,
        fatigue_score=EXCLUDED.fatigue_score,
        fatigue_flag=EXCLUDED.fatigue_flag;
    """

    fatigue_watch = []
    with conn.cursor() as cur:
        for r in rows:
            platform, account_id, level, eid, day, spend, imp, clk, conv, rev, roas, ctr, cpm, cpc = r
            base = baselines.get(eid, {"ctr7": 0, "roas7": 0})
            ctr7 = base["ctr7"]
            roas7 = base["roas7"]

            ctr_ratio = safe_div(ctr, ctr7, default=1.0) if ctr7 else 1.0
            roas_ratio = safe_div(roas, roas7, default=1.0) if roas7 else 1.0
            fatigue_score, fatigue_flag = fatigue_from_ratios(ctr_ratio, roas_ratio)

            cur.execute(upsert_sql, (
                platform, account_id, level, eid, day,
                spend, imp, clk, conv, rev, roas, ctr, cpm, cpc,
                ctr7, roas7,
                ctr_ratio, roas_ratio, fatigue_score, fatigue_flag
            ))

            if fatigue_flag:
                fatigue_watch.append({
                    "entity_level": level,
                    "entity_id": eid,
                    "fatigue_score": float(fatigue_score),
                    "fatigue_ctr_ratio": float(ctr_ratio),
                    "fatigue_roas_ratio": float(roas_ratio),
                })

    return sorted(fatigue_watch, key=lambda x: x["fatigue_score"], reverse=True)

def _build_digest(conn, day, platform, account_id):
    # totals at account level if present, else sum everything
    rows = _fetch_daily_rows(conn, day, platform, account_id)

    totals = {
        "spend": sum(float(r[5] or 0) for r in rows),
        "revenue": sum(float(r[9] or 0) for r in rows),
        "conversions": sum(int(r[8] or 0) for r in rows),
        "roas": 0.0,
        "ctr": 0.0,
        "cpc": 0.0,
    }
    totals["roas"] = (totals["revenue"] / totals["spend"]) if totals["spend"] else 0.0

    # CTR, CPC from sums (not avg)
    impressions = sum(int(r[6] or 0) for r in rows)
    clicks = sum(int(r[7] or 0) for r in rows)
    totals["ctr"] = (clicks * 100.0 / impressions) if impressions else 0.0
    totals["cpc"] = (totals["spend"] / clicks) if clicks else 0.0

    # winners/losers: focus on ads (best control surface)
    ad_rows = _fetch_daily_rows(conn, day, platform, account_id, entity_level_filter="ad")
    ad_perf = [{
        "entity_level": r[2], "entity_id": r[3],
        "spend": float(r[5] or 0),
        "roas": float(r[10] or 0),
        "ctr": float(r[11] or 0),
    } for r in ad_rows if float(r[5] or 0) >= float(os.getenv("MIN_SPEND_WINLOSE", "500"))]

    winners = sorted(ad_perf, key=lambda x: x["roas"], reverse=True)[:3]
    losers = sorted(ad_perf, key=lambda x: x["roas"])[:3]

    # fatigue watchlist pulled from mem_entity_daily
    with conn.cursor() as cur:
        cur.execute("""
          SELECT entity_level, entity_id, fatigue_score, fatigue_ctr_ratio, fatigue_roas_ratio
          FROM mem_entity_daily
          WHERE platform=%s AND account_id=%s AND day=%s AND fatigue_flag=true
          ORDER BY fatigue_score DESC
          LIMIT 10
        """, (platform, account_id, day))
        fatigue_watch = [{
            "entity_level": x[0], "entity_id": x[1],
            "fatigue_score": float(x[2] or 0),
            "fatigue_ctr_ratio": float(x[3] or 1),
            "fatigue_roas_ratio": float(x[4] or 1),
        } for x in cur.fetchall()]

    # objections optional (if Agent 2 is writing)
    objections = {}
    with conn.cursor() as cur:
        cur.execute("""
          SELECT objection_type, SUM(count)
          FROM fact_objections_daily
          WHERE platform=%s AND account_id=%s AND day=%s
          GROUP BY objection_type
          ORDER BY SUM(count) DESC
        """, (platform, account_id, day))
        objections = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

    text = render_daily_digest(day, platform, account_id, totals, winners, losers, fatigue_watch, objections)
    summary = {"totals": totals, "winners": winners, "losers": losers, "fatigue": fatigue_watch, "objections": objections}
    return text, summary

def run_daily_close():
    day = _day_from_env()

    with get_conn() as conn:
        combos = _discover_accounts_for_day(conn, day)

        for (platform, account_id) in combos:
            # For fatigue we compute per level (adset + ad are most useful)
            levels = _discover_entity_levels(conn, day, platform, account_id)
            for level in levels:
                rows = _fetch_daily_rows(conn, day, platform, account_id, entity_level_filter=level)
                baselines = _fetch_7d_baselines(conn, day, platform, account_id, level)
                _upsert_mem_entity_daily(conn, rows, baselines)

            # Build + store digest
            text, js = _build_digest(conn, day, platform, account_id)
            with conn.cursor() as cur:
                cur.execute("""
                  INSERT INTO mem_daily_digest(platform, account_id, day, digest_text, json_summary)
                  VALUES (%s,%s,%s,%s,%s)
                  ON CONFLICT (platform, account_id, day)
                  DO UPDATE SET digest_text=EXCLUDED.digest_text, json_summary=EXCLUDED.json_summary;
                """, (platform, account_id, day, text, js))

    print(f"[Layer2] daily_close complete for {day}")


def _discover_entity_levels(conn, day, platform, account_id):
    with conn.cursor() as cur:
        cur.execute("""
          SELECT DISTINCT entity_level
          FROM daily_kpis
          WHERE day=%s AND platform=%s AND account_id=%s
        """, (day, platform, account_id))
        levels = [r[0] for r in cur.fetchall()]
    # Prefer ad + adset for fatigue; remove account if present
    levels = [l for l in levels if l and l != "account"]
    # Stable priority ordering if exists
    priority = ["ad", "adset", "campaign"]
    levels = sorted(levels, key=lambda x: priority.index(x) if x in priority else 99)
    return levels

if __name__ == "__main__":
    run_daily_close()