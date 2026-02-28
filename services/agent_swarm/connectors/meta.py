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

    def pause(self, entity_id: str) -> dict:
        """Returns {"ok": bool, "error": str | None}."""
        try:
            r = requests.post(
                f"{self.graph}/{entity_id}",
                data={"status": "PAUSED", "access_token": self.access_token},
                timeout=20,
            )
            if r.status_code < 300:
                return {"ok": True, "error": None}
            try:
                err = r.json().get("error", {})
                msg = err.get("message") or err.get("error_user_msg") or f"Meta error {r.status_code}"
            except Exception:
                msg = r.text[:300] or f"Meta error {r.status_code}"
            return {"ok": False, "error": msg}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Map Meta account_status codes to human-readable reasons
    _ACCOUNT_STATUS = {
        2:   "Ad account is disabled",
        3:   "Ad account has an outstanding balance — please settle your bill",
        7:   "Ad account is under risk review",
        8:   "Ad account is pending payment settlement",
        9:   "Ad account is in grace period — payment overdue",
        100: "Ad account is pending closure",
        101: "Ad account is closed",
    }

    def _check_account_health(self) -> str | None:
        """
        Returns a human-readable error string if the ad account has billing/
        suspension issues, or None if the account is healthy.
        """
        try:
            r = requests.get(
                f"{self.graph}/{self.ad_account_id}",
                params={
                    "fields": "account_status,disable_reason,currency",
                    "access_token": self.access_token,
                },
                timeout=15,
            )
            if r.status_code >= 300:
                return None  # can't determine — don't block
            data = r.json()
            status_code = data.get("account_status")
            if status_code and status_code != 1:
                return self._ACCOUNT_STATUS.get(status_code, f"Ad account issue (status code {status_code})")
        except Exception:
            pass
        return None

    def resume(self, entity_id: str) -> dict:
        """
        Attempt to activate a campaign/adset.
        After the Meta API call succeeds (HTTP 200), verify the effective_status
        actually changed to ACTIVE.  If not, check the ad account health and
        return a clear error message (e.g. billing block, account disabled).
        Returns {"ok": bool, "error": str | None}.
        """
        try:
            r = requests.post(
                f"{self.graph}/{entity_id}",
                data={"status": "ACTIVE", "access_token": self.access_token},
                timeout=20,
            )
            # ── Hard API failure ───────────────────────────────────────────
            if r.status_code >= 300:
                try:
                    err = r.json().get("error", {})
                    msg = err.get("message") or err.get("error_user_msg") or f"Meta error {r.status_code}"
                    code = err.get("code")
                    subcode = err.get("error_subcode")
                    # Enrich vague "Permissions error" with account health context
                    if "Permissions" in msg or code in (200, 100):
                        acct_err = self._check_account_health()
                        if acct_err:
                            msg = acct_err
                        else:
                            msg = f"{msg} — your ad account may have a billing issue or policy violation. Check Meta Business Manager."
                except Exception:
                    msg = r.text[:300] or f"Meta error {r.status_code}"
                return {"ok": False, "error": msg}

            # ── API returned 200 — verify the campaign actually went ACTIVE ─
            verify = requests.get(
                f"{self.graph}/{entity_id}",
                params={
                    "fields": "status,effective_status,issues_info",
                    "access_token": self.access_token,
                },
                timeout=15,
            )
            if verify.status_code < 300:
                vdata = verify.json()
                effective = vdata.get("effective_status") or vdata.get("status", "")

                if effective not in ("ACTIVE", "CAMPAIGN_ACTIVE"):
                    # Campaign didn't activate — figure out why
                    # 1. Check issues_info on the entity itself
                    issues = vdata.get("issues_info") or []
                    if issues:
                        issue_msg = issues[0].get("error_message") or issues[0].get("summary", "")
                        if issue_msg:
                            return {"ok": False, "error": f"Campaign cannot be activated: {issue_msg}"}

                    # 2. Check ad account health (billing / suspension)
                    acct_error = self._check_account_health()
                    if acct_error:
                        return {"ok": False, "error": acct_error}

                    # 3. Generic fallback
                    status_map = {
                        "ACCOUNT_PAUSED": "Ad account is paused — check billing or account status in Meta Business Manager",
                        "PAUSED":         "Campaign is still paused — Meta did not activate it. Check your ad account for billing or policy issues.",
                        "WITH_ISSUES":    "Campaign has issues preventing activation — review in Meta Ads Manager",
                        "DISAPPROVED":    "Campaign was disapproved by Meta — review ad content",
                        "PENDING_REVIEW": "Campaign is pending Meta review",
                    }
                    friendly = status_map.get(effective, f"Campaign status is '{effective}' — could not activate. Check Meta Business Manager.")
                    return {"ok": False, "error": friendly}

            return {"ok": True, "error": None}
        except Exception as e:
            return {"ok": False, "error": str(e)}

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
