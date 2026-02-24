import psycopg2.extras

from datetime import date, timedelta
from services.ingestion_service.storage.postgres import get_conn

def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"

def month_range(d: date):
    start = date(d.year, d.month, 1)
    if d.month == 12:
        end = date(d.year + 1, 1, 1)
    else:
        end = date(d.year, d.month + 1, 1)
    return start, end

def run_monthly_memory(month_str: str | None = None):
    # default = current month-to-date or last completed month (choose)
    today = date.today()
    if month_str:
        y, m = map(int, month_str.split("-"))
        target = date(y, m, 1)
    else:
        # last completed month
        first_this_month = date(today.year, today.month, 1)
        target = first_this_month - timedelta(days=1)
        target = date(target.year, target.month, 1)

    ms, me = month_range(target)
    mk = month_key(ms)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT DISTINCT platform, account_id
              FROM daily_kpis
              WHERE day >= %s AND day < %s
            """, (ms, me))
            combos = cur.fetchall()

        for (platform, account_id) in combos:
            with conn.cursor() as cur:
                cur.execute("""
                  SELECT COALESCE(SUM(spend),0), COALESCE(SUM(revenue),0),
                         COALESCE(SUM(conversions),0),
                         CASE WHEN COALESCE(SUM(spend),0)>0 THEN COALESCE(SUM(revenue),0)/SUM(spend) ELSE 0 END roas
                  FROM daily_kpis
                  WHERE platform=%s AND account_id=%s AND day >= %s AND day < %s
                """, (platform, account_id, ms, me))
                spend, revenue, conversions, roas = cur.fetchone()

                # Best ads this month
                cur.execute("""
                  SELECT entity_id, SUM(spend) spend, AVG(roas) roas, AVG(ctr) ctr
                  FROM daily_kpis
                  WHERE platform=%s AND account_id=%s AND entity_level='ad'
                    AND day >= %s AND day < %s
                  GROUP BY entity_id
                  HAVING SUM(spend) >= 8000
                  ORDER BY AVG(roas) DESC
                  LIMIT 8
                """, (platform, account_id, ms, me))
                top_ads = [{"ad_id":r[0], "spend":float(r[1] or 0), "roas":float(r[2] or 0), "ctr":float(r[3] or 0)} for r in cur.fetchall()]

                # Objection mix (optional)
                cur.execute("""
                  SELECT objection_type, SUM(count)
                  FROM fact_objections_daily
                  WHERE platform=%s AND account_id=%s AND day >= %s AND day < %s
                  GROUP BY objection_type
                  ORDER BY SUM(count) DESC
                """, (platform, account_id, ms, me))
                objections = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

            text = "\n".join([
                f"Month {mk} | {platform.upper()} | {account_id}",
                "",
                f"Spend ₹{float(spend or 0):.0f} | Revenue ₹{float(revenue or 0):.0f} | ROAS {float(roas or 0):.2f} | Conversions {int(conversions or 0)}",
                "",
                "Top Ads:",
                *([f"- {a['ad_id']} | spend ₹{a['spend']:.0f} | roas {a['roas']:.2f} | ctr {a['ctr']:.2f}%" for a in top_ads] if top_ads else ["- none (or spend threshold too high)"]),
                "",
                "Objections:",
                *([f"- {k}: {v}" for k,v in objections.items()] if objections else ["- none"])
            ])

            js = {
                "totals": {"spend": float(spend or 0), "revenue": float(revenue or 0), "roas": float(roas or 0), "conversions": int(conversions or 0)},
                "top_ads": top_ads,
                "objections": objections,
                "month_start": str(ms),
                "month_end": str(me),
            }

            with conn.cursor() as cur:
                cur.execute("""
                  INSERT INTO mem_monthly_digest(platform, account_id, month, digest_text, json_summary)
                  VALUES (%s,%s,%s,%s,%s)
                  ON CONFLICT (platform, account_id, month)
                  DO UPDATE SET digest_text=EXCLUDED.digest_text, json_summary=EXCLUDED.json_summary;
                """, (platform, account_id, mk, text, psycopg2.extras.Json(js)))

    print(f"[Layer2] monthly_memory complete month={mk}")

if __name__ == "__main__":
    run_monthly_memory()