# services/ingestion_service/collectors/meta.py
import os
import time
import json
import requests
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from zoneinfo import ZoneInfo

META_GRAPH_BASE = "https://graph.facebook.com/v19.0"


class MetaCollector:
    def __init__(self):
        # Support both names so we don't break deployments:
        # - META_ADS_TOKEN (preferred)
        # - META_ACCESS_TOKEN (legacy)
        self.access_token = os.getenv("META_ADS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
        self.account_id = os.getenv("META_AD_ACCOUNT_ID")  # e.g. act_123

        if not self.access_token or not self.account_id:
            raise RuntimeError("META_ADS_TOKEN (or META_ACCESS_TOKEN) and META_AD_ACCOUNT_ID must be set")

   
    def fetch_account_timezone(self) -> str | None:
        # requires ads_management/ads_read access
        try:
            j = self._get(self.account_id, params={"fields": "timezone_name"})
            return j.get("timezone_name")
        except Exception:
            return None
        
    def fetch_account_timezone_name(self) -> str | None:
        data = self._get(f"{self.account_id}", params={"fields": "timezone_name"})
        return data.get("timezone_name")
        
    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{META_GRAPH_BASE}/{path.lstrip('/')}"
        params = {**params, "access_token": self.access_token}

        last_err = None

        for attempt in range(6):
            try:
                r = requests.get(url, params=params, timeout=60)
            except requests.RequestException as e:
                last_err = f"RequestException: {type(e).__name__}: {e}"
                time.sleep(min(30, 2 ** attempt))
                continue

            # Always record something useful
            last_err = f"{r.status_code} {r.text[:500]}"

            # Retry transient errors
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(30, 2 ** attempt))
                continue

            # Some Meta throttles come as 400 with error codes 4/17/32
            if r.status_code == 400:
                try:
                    j = r.json()
                    code = (j.get("error") or {}).get("code")
                    if code in (4, 17, 32):
                        last_err = f"400 throttle code={code} body={str(j)[:500]}"
                        time.sleep(min(30, 2 ** attempt))
                        continue
                except Exception:
                    pass

            if r.ok:
                return r.json()

            r.raise_for_status()

        raise RuntimeError(f"Meta GET failed after retries: {last_err}")

    def _paginate_allow_403(self, path: str, params: Dict[str, Any], max_pages: int = 50) -> List[Dict[str, Any]]:
        try:
            return self._paginate(path, params, max_pages=max_pages)
        except requests.exceptions.HTTPError as e:
            # If forbidden for entities, skip gracefully so the pipeline still runs.
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code == 403:
                return []
            raise

    def _paginate(self, path: str, params: Dict[str, Any], max_pages: int = 50) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        next_url: Optional[str] = None

        last_err = None
        for attempt_page in range(max_pages):
            if next_url:
                # Follow Meta's paging.next URL (already contains access_token & params)
                r = requests.get(next_url, timeout=60)

                # Retry transient paging errors too
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(min(30, 2 ** min(attempt_page, 5)))
                    continue

                # Meta sometimes returns 400 throttles here too
                if r.status_code == 400:
                    try:
                        j = r.json()
                        code = (j.get("error") or {}).get("code")
                        if code in (4, 17, 32):
                            time.sleep(min(30, 2 ** min(attempt_page, 5)))
                            continue
                    except Exception:
                        pass

                if not r.ok:
                    last_err = f"{r.status_code} {r.text}"
                    r.raise_for_status()

                data = r.json()
            else:
                data = self._get(path, params)

            items = data.get("data", [])
            if isinstance(items, list):
                out.extend(items)

            paging = data.get("paging", {}) or {}
            next_url = paging.get("next")
            if not next_url:
                break

        if last_err:
            # Only reached if raise_for_status didn't throw for some reason
            raise RuntimeError(f"Meta paginate failed: {last_err}")

        return out

    def fetch_entities(self) -> Dict[str, List[Dict[str, Any]]]:
        campaigns = self._paginate_allow_403(
            f"{self.account_id}/campaigns",
            params={"fields": "id,name,status,effective_status,objective,created_time,updated_time", "limit": 200},
        )
        adsets = self._paginate_allow_403(
            f"{self.account_id}/adsets",
            params={
                "fields": "id,name,status,effective_status,campaign_id,daily_budget,lifetime_budget,bid_strategy,created_time,updated_time",
                "limit": 200,
            },
        )
        ads = self._paginate_allow_403(
            f"{self.account_id}/ads",
            params={"fields": "id,name,status,effective_status,adset_id,campaign_id,created_time,updated_time", "limit": 200},
        )
        return {"campaigns": campaigns, "adsets": adsets, "ads": ads}

    def fetch_insights(self, window_start: datetime, window_end: datetime, ad_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        # Meta Insights is date-granular most reliably. Use a safe 2-day range.
        since = (window_end.astimezone(timezone.utc).date() - timedelta(days=1)).strftime("%Y-%m-%d")
        until = window_end.astimezone(timezone.utc).date().strftime("%Y-%m-%d")

        fields = ",".join([
            "account_id","campaign_id","adset_id","ad_id",
            "date_start","date_stop",
            "impressions","clicks","spend","ctr","cpm","cpc",
            "actions","action_values","purchase_roas"
        ])

        params = {
            "time_increment": 1,  # daily
            "time_range": json.dumps({"since": since, "until": until}),
            "fields": fields,
            "limit": 200,
        }

        # fallback
        if not ad_ids:
            return self._paginate(f"{self.account_id}/insights", params={**params, "level": "ad"})

        out: List[Dict[str, Any]] = []
        for ad_id in ad_ids:
            try:
                rows = self._paginate(f"{ad_id}/insights", params=params, max_pages=5)
                for r in rows:
                    r.setdefault("ad_id", ad_id)
                out.extend(rows)
            except requests.exceptions.HTTPError as e:
                resp = getattr(e, "response", None)
                if resp is not None and resp.status_code in (403, 400):
                    continue
                raise

        return out

    def pull_minimum(self, window_start: datetime, window_end: datetime) -> Dict[str, Any]:
        entities = self.fetch_entities()
        ad_ids = [a.get("id") for a in (entities.get("ads") or []) if a.get("id")]
        insights = self.fetch_insights(window_start, window_end, ad_ids=ad_ids)
        tz_name = self.fetch_account_timezone()

        return {
            "platform": "meta",
            "account_id": self.account_id,
            "account_timezone": tz_name,
            "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
            "entities": entities,
            "insights": insights,
        }