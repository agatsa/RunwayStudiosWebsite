# services/ingestion_service/app.py
import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException

from datetime import timedelta

from services.ingestion_service.agents.performance import analyze_account

from services.ingestion_service.collectors.meta import MetaCollector

from services.ingestion_service.storage.gcs_raw import write_raw_json
from services.ingestion_service.storage.postgres import (
    create_sync_run,
    get_last_success_end,
    mark_sync_run_failed,
    mark_sync_run_success,
    update_last_success_end,
    upsert_entities_snapshot,
    upsert_kpi_hourly,
    get_conn,
    upsert_daily_kpis,
    insert_alerts,
)

from services.ingestion_service.utils.timewindows import compute_window

from zoneinfo import ZoneInfo

app = FastAPI(title="AI Agency Ingestion Service", version="0.1.0")


# -------------------------
# Helpers (top-level)
# -------------------------
def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _to_int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def _extract_action_value(actions_list, key_candidates):
    """
    actions_list: list of dicts like {"action_type":"purchase","value":"3"}
    key_candidates: list of action_type strings to match
    Returns summed numeric value.
    """
    if not isinstance(actions_list, list):
        return 0.0
    total = 0.0
    for a in actions_list:
        at = a.get("action_type")
        if at in key_candidates:
            v = a.get("value")
            try:
                total += float(v)
            except Exception:
                pass
    return total


def _require_meta_env() -> tuple[str, str]:
    """
    MetaCollector currently reads META_ACCESS_TOKEN internally.
    But deployments have used META_ADS_TOKEN too.
    We enforce that at least one token + account id exist, so the error is clear.
    """
    token = os.getenv("META_ADS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
    acct = os.getenv("META_AD_ACCOUNT_ID")
    if not token or not acct:
        raise HTTPException(status_code=500, detail="❌ META_ADS_TOKEN or META_ACCESS_TOKEN, and META_AD_ACCOUNT_ID are required.")
    return token, acct


@app.get("/health")
def health():
    return {"ok": True, "service": "ingestion", "ts": datetime.now(timezone.utc).isoformat()}


def _dedupe_kpi_rows(rows: list[dict]) -> list[dict]:
    """
    Deduplicate by (platform, account_id, entity_level, entity_id, hour_ts)
    and SUM numeric metrics. Keep latest raw_json list for debugging.
    """
    agg = {}

    sum_fields = ["spend", "impressions", "clicks", "conversions", "revenue"]
    avg_fields = ["ctr", "cpm", "cpc", "roas"]  # optional; we’ll recompute roas if possible

    for r in rows:
        key = (r["platform"], r["account_id"], r["entity_level"], r["entity_id"], r["hour_ts"])
        if key not in agg:
            agg[key] = {**r}
            agg[key]["raw_json"] = [r.get("raw_json")] if r.get("raw_json") is not None else []
            agg[key]["_ctr_num"] = 0.0
            agg[key]["_ctr_den"] = 0.0
            continue

        a = agg[key]

        # raw_json keep list
        if r.get("raw_json") is not None:
            a["raw_json"].append(r["raw_json"])

        # sum core fields
        for f in sum_fields:
            av = a.get(f)
            rv = r.get(f)
            if rv is None:
                continue
            a[f] = float(av or 0) + float(rv)

        # weighted CTR (clicks/impressions)
        try:
            a["_ctr_num"] = float(a.get("_ctr_num") or 0) + float(r.get("clicks") or 0)
            a["_ctr_den"] = float(a.get("_ctr_den") or 0) + float(r.get("impressions") or 0)
        except Exception:
            pass

    out = []
    for a in agg.values():
        # recompute ctr/cpc/cpm/roas safely from sums
        clicks = float(a.get("clicks") or 0)
        imps = float(a.get("impressions") or 0)
        spend = float(a.get("spend") or 0)
        rev = float(a.get("revenue") or 0)

        a["ctr"] = (clicks / imps) if imps > 0 else None
        a["cpc"] = (spend / clicks) if clicks > 0 else None
        a["cpm"] = (spend / imps * 1000.0) if imps > 0 else None
        a["roas"] = (rev / spend) if spend > 0 else None

        # raw_json: store as json list (still valid jsonb)
        out.append(a)

    return out

def _run_meta_pull(
    x_cloudscheduler_jobname: str | None,
    x_cloudscheduler_scheduled_time: str | None,
    x_request_id: str | None,
):
    platform = "meta"
    _require_meta_env()

    account_id = os.getenv("META_AD_ACCOUNT_ID", "unknown")
    request_id = x_request_id or str(uuid.uuid4())

    try:
        last_end = get_last_success_end(platform, account_id)
        window = compute_window(last_end)

        # We still run every hour, but insights are daily buckets
        window_start = window.end - timedelta(hours=1)
        window_end = window.end

        run_id = create_sync_run(
            platform=platform,
            account_id=account_id,
            request_id=request_id,
            window_start=window_start,
            window_end=window_end,
        )

        collector = MetaCollector()
        payload = collector.pull_minimum(window_start, window_end)

        # Advertiser timezone (best effort)
        tz_name = payload.get("account_timezone") or os.getenv("META_AD_TIMEZONE") or "UTC"
        try:
            adv_tz = ZoneInfo(tz_name)
        except Exception:
            adv_tz = timezone.utc
            tz_name = "UTC"

        raw_path = write_raw_json(
            platform=platform,
            account_id=account_id,
            window_start=window_start,
            window_end=window_end,
            request_id=request_id,
            payload=payload,
        )

        # -------------------------
        # Entities snapshot upsert
        # -------------------------
        entities_rows = []
        for level in ("campaigns", "adsets", "ads"):
            for e in (payload.get("entities", {}) or {}).get(level, []) or []:
                entities_rows.append(
                    {
                        "platform": platform,
                        "entity_level": level[:-1],
                        "entity_id": e.get("id"),
                        "account_id": account_id,
                        "name": e.get("name"),
                        "status": e.get("effective_status") or e.get("status"),
                        "raw_json": e,
                    }
                )
        upsert_entities_snapshot(entities_rows)

        # -------------------------
        # Insights -> kpi_hourly (bucketed by advertiser-day midnight)
        # -------------------------
        kpi_rows = []

        for row in payload.get("insights", []) or []:
            date_start = row.get("date_start")  # 'YYYY-MM-DD'
            if not date_start:
                continue

            # advertiser midnight -> UTC timestamp stored in hour_ts
            local_midnight = datetime.fromisoformat(date_start).replace(tzinfo=adv_tz)
            hour_ts = local_midnight.astimezone(timezone.utc)

            spend = _to_float(row.get("spend"))
            impressions = _to_int(row.get("impressions"))
            clicks = _to_int(row.get("clicks"))
            ctr = _to_float(row.get("ctr"))
            cpm = _to_float(row.get("cpm"))
            cpc = _to_float(row.get("cpc"))

            conversions = _extract_action_value(
                row.get("actions"),
                ["purchase", "offsite_conversion.purchase"],
            )
            revenue = _extract_action_value(
                row.get("action_values"),
                ["purchase", "offsite_conversion.purchase"],
            )

            roas = None
            pr = row.get("purchase_roas")
            if isinstance(pr, list) and len(pr) > 0:
                roas = _to_float(pr[0].get("value"))
            if roas is None and spend is not None and spend > 0 and revenue is not None:
                roas = float(revenue) / float(spend)

            ad_id = row.get("ad_id") or "unknown"

            kpi_rows.append(
                {
                    "platform": platform,
                    "account_id": account_id,
                    "entity_level": "ad",
                    "entity_id": ad_id,
                    "hour_ts": hour_ts,
                    "spend": spend,
                    "impressions": impressions,
                    "clicks": clicks,
                    "ctr": ctr,
                    "cpm": cpm,
                    "cpc": cpc,
                    "conversions": int(conversions) if conversions is not None else None,
                    "revenue": revenue,
                    "roas": roas,
                    "raw_json": row,
                }
            )

        # Deduplicate inside the batch to avoid ON CONFLICT "row a second time"
        kpi_rows = _dedupe_kpi_rows(kpi_rows)
        upsert_kpi_hourly(kpi_rows)

        # Spend today computed from DB in advertiser timezone (authoritative)
        spend_today = 0.0
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(spend),0)
                    FROM kpi_hourly
                    WHERE platform=%s
                      AND account_id=%s
                      AND (hour_ts AT TIME ZONE %s)::date = (now() AT TIME ZONE %s)::date
                    """,
                    (platform, account_id, tz_name, tz_name),
                )
                spend_today = float(cur.fetchone()[0] or 0.0)

        update_last_success_end(platform, account_id, window_end)

        stats = {
            "job": x_cloudscheduler_jobname,
            "scheduled_time": x_cloudscheduler_scheduled_time,
            "entities": {
                k: len((payload.get("entities", {}) or {}).get(k, []) or [])
                for k in ["campaigns", "adsets", "ads"]
            },
            "insights_rows": len(payload.get("insights", []) or []),
            "kpi_rows_upserted": len(kpi_rows),
            "timezone": tz_name,
        }

        mark_sync_run_success(run_id, raw_path, stats)

        return {
            "ok": True,
            "run_id": run_id,
            "raw_path": raw_path,
            "window": {"start": window_start, "end": window_end},
            "stats": stats,
            "spend_today": round(spend_today, 2),
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        try:
            if "run_id" in locals():
                mark_sync_run_failed(run_id, str(e), stats={"job": x_cloudscheduler_jobname})
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"meta pull failed: {e}")


# Keep your original endpoint
@app.post("/cron/pull/meta")
def pull_meta(
    x_cloudscheduler_jobname: str | None = Header(default=None),
    x_cloudscheduler_scheduled_time: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
):
    return _run_meta_pull(x_cloudscheduler_jobname, x_cloudscheduler_scheduled_time, x_request_id)


# Add the endpoint that your deployed OpenAPI showed
@app.post("/cron/5min")
def cron_5min(
    x_cloudscheduler_jobname: str | None = Header(default=None),
    x_cloudscheduler_scheduled_time: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
):
    return _run_meta_pull(x_cloudscheduler_jobname, x_cloudscheduler_scheduled_time, x_request_id)


@app.post("/cron/build/memory")
def build_memory():
    platform = "meta"
    account_id = os.getenv("META_AD_ACCOUNT_ID", "unknown")
    now = datetime.now(timezone.utc)

    # ---- Daily rollups (last 14 days) ----
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  DATE(hour_ts) AS day,
                  COALESCE(SUM(spend),0) AS spend,
                  COALESCE(SUM(impressions),0)::bigint AS impressions,
                  COALESCE(SUM(clicks),0)::bigint AS clicks,
                  COALESCE(SUM(conversions),0)::bigint AS conversions,
                  COALESCE(SUM(revenue),0) AS revenue
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT 14
                """,
                (platform, account_id),
            )
            agg = cur.fetchall()

    daily_rows = []
    for (day, spend, impressions, clicks, conversions, revenue) in agg:
        ctr = (float(clicks) / float(impressions)) if impressions and impressions > 0 else None
        cpc = (float(spend) / float(clicks)) if clicks and clicks > 0 else None
        cpm = (float(spend) / float(impressions) * 1000.0) if impressions and impressions > 0 else None
        roas = (float(revenue) / float(spend)) if spend and spend > 0 else None

        daily_rows.append(
            {
                "platform": platform,
                "account_id": account_id,
                "entity_level": "account",
                "entity_id": "account",
                "day": day,
                "spend": float(spend),
                "impressions": int(impressions),
                "clicks": int(clicks),
                "conversions": int(conversions),
                "revenue": float(revenue),
                "roas": roas,
                "ctr": ctr,
                "cpm": cpm,
                "cpc": cpc,
            }
        )

    upsert_daily_kpis(daily_rows)

    # ---- Basic anomaly alerts (3h vs 24h) ----
    t24 = now - timedelta(hours=24)
    t3 = now - timedelta(hours=3)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  COALESCE(SUM(spend),0) AS spend,
                  COALESCE(SUM(clicks),0)::bigint AS clicks,
                  COALESCE(SUM(impressions),0)::bigint AS impressions,
                  COALESCE(SUM(revenue),0) AS revenue
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t24),
            )
            spend24, clicks24, imp24, rev24 = cur.fetchone()

            cur.execute(
                """
                SELECT
                  COALESCE(SUM(spend),0) AS spend,
                  COALESCE(SUM(clicks),0)::bigint AS clicks,
                  COALESCE(SUM(impressions),0)::bigint AS impressions,
                  COALESCE(SUM(revenue),0) AS revenue
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t3),
            )
            spend3, clicks3, imp3, rev3 = cur.fetchone()

    def safe_div(a, b):
        a = float(a or 0)
        b = float(b or 0)
        return (a / b) if b != 0 else None

    ctr24 = safe_div(clicks24, imp24)
    ctr3 = safe_div(clicks3, imp3)
    roas24 = safe_div(rev24, spend24)
    roas3 = safe_div(rev3, spend3)

    alerts = []

    if spend24 and float(spend24) > 0 and spend3 and float(spend3) > 0.6 * float(spend24):
        alerts.append(
            {
                "platform": platform,
                "account_id": account_id,
                "entity_level": "account",
                "entity_id": "account",
                "ts": now,
                "alert_type": "spend_spike",
                "severity": "warn",
                "summary": f"Spend spike: last 3h {float(spend3):.2f} vs 24h {float(spend24):.2f}",
                "details": {"spend_3h": float(spend3), "spend_24h": float(spend24)},
            }
        )

    if roas24 is not None and roas3 is not None and roas24 > 0 and roas3 < 0.7 * roas24:
        alerts.append(
            {
                "platform": platform,
                "account_id": account_id,
                "entity_level": "account",
                "entity_id": "account",
                "ts": now,
                "alert_type": "roas_drop",
                "severity": "warn",
                "summary": f"ROAS drop: last 3h {roas3:.2f} vs 24h {roas24:.2f}",
                "details": {"roas_3h": roas3, "roas_24h": roas24},
            }
        )

    if ctr24 is not None and ctr3 is not None and ctr24 > 0 and ctr3 < 0.7 * ctr24:
        alerts.append(
            {
                "platform": platform,
                "account_id": account_id,
                "entity_level": "account",
                "entity_id": "account",
                "ts": now,
                "alert_type": "ctr_fatigue",
                "severity": "info",
                "summary": f"CTR fatigue: last 3h {ctr3:.4f} vs 24h {ctr24:.4f}",
                "details": {"ctr_3h": ctr3, "ctr_24h": ctr24},
            }
        )

    if alerts:
        insert_alerts(alerts)

    return {"ok": True, "daily_rows_upserted": len(daily_rows), "alerts_inserted": len(alerts)}

@app.post("/agent/performance/analyze")
def agent_performance():
    platform = "meta"
    account_id = os.getenv("META_AD_ACCOUNT_ID", "unknown")

    result = analyze_account(platform, account_id)

    return {"ok": True, "analysis": result}