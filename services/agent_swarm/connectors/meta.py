# services/agent_swarm/connectors/meta.py
"""
Meta Ads Platform Connector.

Implements PlatformConnector for Facebook/Instagram Ads.
Consolidates all Meta Graph API calls that were previously
scattered across budget_governor.py, creative_generator.py,
meta_publisher.py, fb_analyst.py, and sales_strategist.py.
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from services.agent_swarm.config import META_GRAPH, META_API_VERSION
from services.agent_swarm.connectors.base import (
    PlatformConnector, CampaignSpec, MetricSnapshot,
)


class MetaConnector(PlatformConnector):
    """Connector for Meta Ads (Facebook + Instagram)."""

    def __init__(self, connection: dict, workspace: dict):
        super().__init__(connection, workspace)
        self.graph = META_GRAPH
        self.ad_account_id = connection.get("ad_account_id", "")
        self.page_id = connection.get("page_id", "")
        self.pixel_id = connection.get("pixel_id", "")
        # Normalize act_ prefix
        if self.ad_account_id and not self.ad_account_id.startswith("act_"):
            self.ad_account_id = f"act_{self.ad_account_id}"

    # ── Validation ────────────────────────────────────────

    def validate_connection(self) -> bool:
        """Test token by fetching /me."""
        try:
            r = requests.get(
                f"{self.graph}/me",
                params={"access_token": self.access_token, "fields": "id,name"},
                timeout=10,
            )
            return r.ok
        except Exception:
            return False

    # ── Metrics ───────────────────────────────────────────

    def fetch_metrics(
        self,
        since: str,
        until: str,
        entity_level: str = "account",
    ) -> list[MetricSnapshot]:
        """
        Pull insights from Meta Ads API for a date range.
        entity_level: account|campaign|adset|ad
        Returns list of MetricSnapshot (one per entity per hour).
        """
        snapshots = []
        try:
            if entity_level == "account":
                endpoint = f"{self.graph}/{self.ad_account_id}/insights"
            elif entity_level == "campaign":
                endpoint = f"{self.graph}/{self.ad_account_id}/campaigns"
            else:
                endpoint = f"{self.graph}/{self.ad_account_id}/{entity_level}s"

            params = {
                "access_token": self.access_token,
                "level": entity_level,
                "time_range": {"since": since, "until": until},
                "time_increment": 1,  # daily breakdown
                "fields": (
                    "account_id,campaign_id,campaign_name,"
                    "adset_id,adset_name,ad_id,ad_name,"
                    "spend,impressions,clicks,ctr,cpm,cpc,"
                    "actions,action_values,date_start"
                ),
                "limit": 500,
            }
            r = requests.get(endpoint, params=params, timeout=30)
            if not r.ok:
                print(f"Meta metrics error: {r.status_code} — {r.text[:200]}")
                return []

            data = r.json().get("data", [])
            for row in data:
                spend = float(row.get("spend") or 0)
                impressions = int(row.get("impressions") or 0)
                clicks = int(row.get("clicks") or 0)
                ctr = float(row.get("ctr") or 0)
                cpm = float(row.get("cpm") or 0)
                cpc = float(row.get("cpc") or 0)

                # Extract conversions and revenue from actions
                actions = row.get("actions") or []
                action_values = row.get("action_values") or []
                conversions = sum(
                    int(a.get("value", 0)) for a in actions
                    if a.get("action_type") in ("purchase", "omni_purchase")
                )
                revenue = sum(
                    float(a.get("value", 0)) for a in action_values
                    if a.get("action_type") in ("purchase", "omni_purchase")
                )
                roas = round(revenue / spend, 4) if spend > 0 else 0.0

                entity_id = (
                    row.get("ad_id") or row.get("adset_id") or
                    row.get("campaign_id") or row.get("account_id") or self.ad_account_id
                )
                entity_name = (
                    row.get("ad_name") or row.get("adset_name") or
                    row.get("campaign_name") or "account"
                )
                hour_ts = row.get("date_start", since) + "T00:00:00+00:00"

                snapshots.append(MetricSnapshot(
                    platform="meta",
                    account_id=self.ad_account_id,
                    entity_level=entity_level,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    hour_ts=hour_ts,
                    spend=spend,
                    impressions=impressions,
                    clicks=clicks,
                    conversions=conversions,
                    revenue=revenue,
                    ctr=ctr,
                    cpm=cpm,
                    cpc=cpc,
                    roas=roas,
                    raw_json=row,
                ))
        except Exception as e:
            print(f"MetaConnector.fetch_metrics error: {e}")

        return snapshots

    # ── Campaign management ───────────────────────────────

    def list_campaigns(self, status: str = "ACTIVE") -> list[dict]:
        try:
            r = requests.get(
                f"{self.graph}/{self.ad_account_id}/campaigns",
                params={
                    "access_token": self.access_token,
                    "fields": "id,name,status,daily_budget,objective,effective_status",
                    "effective_status": json.dumps([status]),  # Meta requires JSON array string
                    "limit": 100,
                },
                timeout=20,
            )
            return r.json().get("data", []) if r.ok else []
        except Exception:
            return []

    def list_adsets(self, status: str = "ACTIVE") -> list[dict]:
        try:
            r = requests.get(
                f"{self.graph}/{self.ad_account_id}/adsets",
                params={
                    "access_token": self.access_token,
                    "fields": "id,name,daily_budget,status,effective_status,campaign_id",
                    "limit": 100,
                },
                timeout=20,
            )
            if r.ok:
                return [
                    a for a in r.json().get("data", [])
                    if a.get("effective_status") in (status, status.lower())
                ]
            return []
        except Exception:
            return []

    def update_budget(self, entity_id: str, new_daily_budget_inr: float) -> bool:
        """Update adset daily budget. Meta API uses cents (paise)."""
        budget_paise = int(new_daily_budget_inr * 100)
        try:
            r = requests.post(
                f"{self.graph}/{entity_id}",
                data={
                    "daily_budget": budget_paise,
                    "access_token": self.access_token,
                },
                timeout=20,
            )
            return r.status_code < 300
        except Exception:
            return False

    def pause(self, entity_id: str) -> bool:
        try:
            r = requests.post(
                f"{self.graph}/{entity_id}",
                data={"status": "PAUSED", "access_token": self.access_token},
                timeout=20,
            )
            return r.status_code < 300
        except Exception:
            return False

    def resume(self, entity_id: str) -> bool:
        try:
            r = requests.post(
                f"{self.graph}/{entity_id}",
                data={"status": "ACTIVE", "access_token": self.access_token},
                timeout=20,
            )
            return r.status_code < 300
        except Exception:
            return False

    def upload_image(self, image_url: str) -> Optional[str]:
        """Download image from URL and upload to Meta. Returns image hash."""
        import io
        import requests as _r
        try:
            img_resp = _r.get(image_url, timeout=30)
            img_resp.raise_for_status()
            upload = requests.post(
                f"{self.graph}/{self.ad_account_id}/adimages",
                files={"file": ("ad.jpg", io.BytesIO(img_resp.content), "image/jpeg")},
                data={"access_token": self.access_token},
                timeout=60,
            )
            if upload.ok:
                images = upload.json().get("images", {})
                for key, val in images.items():
                    return val.get("hash")
        except Exception as e:
            print(f"Meta image upload error: {e}")
        return None

    def upload_video(self, video_url: str) -> Optional[str]:
        """Upload video to Meta from public URL. Returns advideo ID."""
        try:
            r = requests.post(
                f"https://graph.facebook.com/{META_API_VERSION}/{self.ad_account_id}/advideos",
                data={
                    "file_url": video_url,
                    "access_token": self.access_token,
                },
                timeout=120,
            )
            if r.ok:
                return r.json().get("id")
        except Exception as e:
            print(f"Meta video upload error: {e}")
        return None

    def create_campaign(self, spec: CampaignSpec) -> dict:
        """
        Full campaign creation: Campaign → AdSet → Creative → Ad.
        Uses the standardized CampaignSpec. Delegates to meta_publisher.
        """
        from services.agent_swarm.creative.meta_publisher import publish_ad_from_spec
        return publish_ad_from_spec(spec, self.connection, self.workspace)

    # ── Meta-specific helpers (not in base interface) ─────

    def get_ad_comments(self, ad_id: str, limit: int = 100) -> list[dict]:
        """Fetch public comments on a Meta ad post."""
        try:
            r = requests.get(
                f"{self.graph}/{ad_id}/comments",
                params={
                    "access_token": self.access_token,
                    "fields": "id,message,from,created_time",
                    "limit": limit,
                },
                timeout=20,
            )
            return r.json().get("data", []) if r.ok else []
        except Exception:
            return []

    def reply_to_comment(self, comment_id: str, message: str) -> bool:
        """Post a reply to an ad comment."""
        try:
            r = requests.post(
                f"{self.graph}/{comment_id}/comments",
                data={
                    "message": message,
                    "access_token": self.access_token,
                },
                timeout=20,
            )
            return r.status_code < 300
        except Exception:
            return False

    def get_pages(self) -> list[dict]:
        """List all Facebook Pages the token has access to."""
        try:
            r = requests.get(
                f"{self.graph}/me/accounts",
                params={
                    "access_token": self.access_token,
                    "fields": "id,name,access_token,category",
                    "limit": 100,
                },
                timeout=20,
            )
            return r.json().get("data", []) if r.ok else []
        except Exception:
            return []

    def get_pixels(self) -> list[dict]:
        """List pixels associated with the ad account."""
        try:
            r = requests.get(
                f"{self.graph}/{self.ad_account_id}/adspixels",
                params={
                    "access_token": self.access_token,
                    "fields": "id,name,last_fired_time",
                },
                timeout=20,
            )
            return r.json().get("data", []) if r.ok else []
        except Exception:
            return []
