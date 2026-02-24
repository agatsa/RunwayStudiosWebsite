import os
from datetime import date, timedelta
from services.ingestion_service.storage.postgres import get_conn

def week_start(d: date):
    return d - timedelta(days=d.weekday())  # Monday

def run_weekly_memory():
    today = date.today()
    ws = week_start(today - timedelta(days=1))  # last completed week if you run Monday morning
    we = ws + timedelta(days=7)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT DISTINCT platform, account_id
              FROM daily_kpis
              WHERE day >= %s AND day < %s
            """, (ws, we))
            combos = cur.fetchall()

        for (platform, account_id) in combos:
            with conn.cursor() as cur:
                cur.execute("""
                  SELECT COALESCE(SUM(spend),0), COALESCE(SUM(revenue),0),
                         CASE WHEN COALESCE(SUM(spend),0)>0 THEN COALESCE(SUM(revenue),0)/SUM(spend) ELSE 0 END roas
                  FROM daily_kpis
                  WHERE platform=%s AND account_id=%s AND day >= %s AND day < %s
                """, (platform, account_id, ws, we))
                spend, revenue, roas = cur.fetchone()

                # weekly winners: ads with spend >= threshold
                min_spend = float(os.getenv("WEEKLY_MIN_SPEND", "3000"))
                cur.execute("""
                  SELECT entity_id, SUM(spend) spend, AVG(roas) roas, AVG(ctr) ctr
                  FROM daily_kpis
                  WHERE platform=%s AND account_id=%s AND entity_level='ad'
                    AND day >= %s AND day < %s
                  GROUP BY entity_id
                  HAVING SUM(spend) >= %s
                  ORDER BY AVG(roas) DESC
                  LIMIT 5
                """, (platform, account_id, ws, we, min_spend))
                winners = [{"ad_id":r[0], "spend":float(r[1] or 0), "roas":float(r[2] or 0), "ctr":float(r[3] or 0)} for r in cur.fetchall()]

                # fatigue summary: count fatigue days per ad
                cur.execute("""
                  SELECT entity_id, COUNT(*) fatigue_days, AVG(fatigue_score) avg_fatigue
                  FROM mem_entity_daily
                  WHERE platform=%s AND account_id=%s AND entity_level='ad'
                    AND day >= %s AND day < %s AND fatigue_flag=true
                  GROUP BY entity_id
                  ORDER BY AVG(fatigue_score) DESC
                  LIMIT 10
                """, (platform, account_id, ws, we))
                fatigue = [{"ad_id":r[0], "fatigue_days":int(r[1] or 0), "avg_fatigue":float(r[2] or 0)} for r in cur.fetchall()]

                # objections mix (optional)
                cur.execute("""
                  SELECT objection_type, SUM(count)
                  FROM fact_objections_daily
                  WHERE platform=%s AND account_id=%s AND day >= %s AND day < %s
                  GROUP BY objection_type
                  ORDER BY SUM(count) DESC
                """, (platform, account_id, ws, we))
                objections = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

            text = "\n".join([
                f"Week {ws} → {we - timedelta(days=1)} | {platform.upper()} | {account_id}",
                "",
                f"Spend ₹{float(spend or 0):.0f} | Revenue ₹{float(revenue or 0):.0f} | ROAS {float(roas or 0):.2f}",
                "",
                "Top Winners:",
                *[f"- ad {w['ad_id']} | spend ₹{w['spend']:.0f} | roas {w['roas']:.2f} | ctr {w['ctr']:.2f}%" for w in winners],
                "",
                "Fatigue Watchlist:",
                *[f"- ad {f['ad_id']} | fatigue_days {f['fatigue_days']} | avg_fatigue {f['avg_fatigue']:.2f}" for f in fatigue],
                "",
                "Objections:",
                *([f"- {k}: {v}" for k,v in objections.items()] if objections else ["- none"])
            ])

            js = {"totals": {"spend": float(spend or 0), "revenue": float(revenue or 0), "roas": float(roas or 0)},
                  "winners": winners, "fatigue": fatigue, "objections": objections}

            with conn.cursor() as cur:
                cur.execute("""
                  INSERT INTO mem_weekly_digest(platform, account_id, week_start, digest_text, json_summary)
                  VALUES (%s,%s,%s,%s,%s)
                  ON CONFLICT (platform, account_id, week_start)
                  DO UPDATE SET digest_text=EXCLUDED.digest_text, json_summary=EXCLUDED.json_summary;
                """, (platform, account_id, ws, text, js))

    print(f"[Layer2] weekly_memory complete for week_start={ws}")

if __name__ == "__main__":
    run_weekly_memory()