from datetime import date, datetime, timedelta
from collections import defaultdict

RAW_TABLE = "RAW_TABLE_NAME_HERE"   # <-- change this to your Layer-1 table

def _safe_float(x, default=0.0):
    try:
        return float(x) if x is not None else default
    except Exception:
        return default

def _safe_int(x, default=0):
    try:
        return int(float(x)) if x is not None else default
    except Exception:
        return default

def rollup_meta_day(conn, day: date, account_id: str):
    """
    Reads Layer-1 raw JSON rows for Meta for a given day and account
    and upserts into fact_kpis_daily.
    """

    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)

    # ---- Fetch raw payloads (edit column names if needed) ----
    # This assumes raw table has:
    # platform, account_id, ts (timestamp), payload_json (jsonb)
    # If your schema differs, adjust this query accordingly.
    sql = f"""
      SELECT payload_json
      FROM {RAW_TABLE}
      WHERE platform='meta'
        AND account_id=%s
        AND ts >= %s AND ts < %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (account_id, start, end))
        rows = cur.fetchall()

    # ---- Aggregate by ad_id (and keep creative_id if present) ----
    # Expect payload like Meta insights rows:
    # { "ad_id": "...", "campaign_id": "...", "adset_id": "...",
    #   "spend": "...", "impressions": "...", "clicks": "...",
    #   "actions": [...], "purchase_roas": [...], ... }
    agg = defaultdict(lambda: {
        "campaign_id": None, "adset_id": None, "ad_id": None, "creative_id": None,
        "spend": 0.0, "impressions": 0, "clicks": 0, "purchases": 0, "revenue": 0.0,
        "comments": 0, "shares": 0, "saves": 0, "frequency": 0.0,
    })

    for (payload,) in rows:
        if not payload:
            continue

        ad_id = payload.get("ad_id") or payload.get("adId") or payload.get("id")
        if not ad_id:
            continue

        a = agg[ad_id]
        a["ad_id"] = ad_id
        a["campaign_id"] = payload.get("campaign_id") or a["campaign_id"]
        a["adset_id"] = payload.get("adset_id") or a["adset_id"]
        a["creative_id"] = payload.get("creative_id") or a["creative_id"]

        a["spend"] += _safe_float(payload.get("spend"))
        a["impressions"] += _safe_int(payload.get("impressions"))
        a["clicks"] += _safe_int(payload.get("clicks"))
        a["frequency"] = max(a["frequency"], _safe_float(payload.get("frequency")))

        # actions parsing (Meta style)
        actions = payload.get("actions") or []
        for item in actions:
            atype = item.get("action_type")
            val = _safe_int(item.get("value"))
            if atype in ("purchase", "omni_purchase"):
                a["purchases"] += val
            if atype in ("comment", "post_comment"):
                a["comments"] += val
            if atype in ("post", "post_engagement"):  # optional
                pass
            if atype in ("share", "post_share"):
                a["shares"] += val
            if atype in ("save",):
                a["saves"] += val

        # revenue: often from action_values or purchase_roas * spend
        action_values = payload.get("action_values") or []
        for item in action_values:
            atype = item.get("action_type")
            val = _safe_float(item.get("value"))
            if atype in ("purchase", "omni_purchase"):
                a["revenue"] += val

        # If revenue still 0 but roas present:
        # purchase_roas array sometimes: [{"action_type":"purchase","value":"2.1"}]
        if a["revenue"] <= 0:
            purchase_roas = payload.get("purchase_roas") or []
            for item in purchase_roas:
                if item.get("action_type") in ("purchase", "omni_purchase"):
                    r = _safe_float(item.get("value"))
                    if r > 0:
                        a["revenue"] = max(a["revenue"], r * a["spend"])

    # ---- Upsert into fact_kpis_daily ----
    upsert = """
      INSERT INTO fact_kpis_daily(
        date, platform, account_id, campaign_id, adset_id, ad_id, creative_id,
        spend, impressions, clicks, purchases, revenue,
        ctr, cvr, cpa, roas,
        comments, shares, saves, frequency
      ) VALUES (
        %(date)s, 'meta', %(account_id)s, %(campaign_id)s, %(adset_id)s, %(ad_id)s, %(creative_id)s,
        %(spend)s, %(impressions)s, %(clicks)s, %(purchases)s, %(revenue)s,
        %(ctr)s, %(cvr)s, %(cpa)s, %(roas)s,
        %(comments)s, %(shares)s, %(saves)s, %(frequency)s
      )
      ON CONFLICT (date, platform, account_id, ad_id)
      DO UPDATE SET
        spend=EXCLUDED.spend,
        impressions=EXCLUDED.impressions,
        clicks=EXCLUDED.clicks,
        purchases=EXCLUDED.purchases,
        revenue=EXCLUDED.revenue,
        ctr=EXCLUDED.ctr,
        cvr=EXCLUDED.cvr,
        cpa=EXCLUDED.cpa,
        roas=EXCLUDED.roas,
        comments=EXCLUDED.comments,
        shares=EXCLUDED.shares,
        saves=EXCLUDED.saves,
        frequency=EXCLUDED.frequency,
        campaign_id=EXCLUDED.campaign_id,
        adset_id=EXCLUDED.adset_id,
        creative_id=EXCLUDED.creative_id;
    """

    with conn.cursor() as cur:
        for ad_id, a in agg.items():
            spend = a["spend"]
            impressions = a["impressions"]
            clicks = a["clicks"]
            purchases = a["purchases"]
            revenue = a["revenue"]

            ctr = (clicks * 100.0 / impressions) if impressions else 0.0
            cvr = (purchases * 100.0 / clicks) if clicks else 0.0
            cpa = (spend / purchases) if purchases else 0.0
            roas = (revenue / spend) if spend else 0.0

            cur.execute(upsert, {
                "date": str(day),
                "account_id": account_id,
                "campaign_id": a["campaign_id"],
                "adset_id": a["adset_id"],
                "ad_id": a["ad_id"],
                "creative_id": a["creative_id"],
                "spend": spend,
                "impressions": impressions,
                "clicks": clicks,
                "purchases": purchases,
                "revenue": revenue,
                "ctr": ctr,
                "cvr": cvr,
                "cpa": cpa,
                "roas": roas,
                "comments": a["comments"],
                "shares": a["shares"],
                "saves": a["saves"],
                "frequency": a["frequency"],
            })

    conn.commit()
    return {"ads_rolled_up": len(agg)}