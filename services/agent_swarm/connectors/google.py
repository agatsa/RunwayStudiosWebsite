# services/agent_swarm/connectors/google.py
"""
Google Ads Platform Connector.

Implements PlatformConnector for Google Ads (Search, Shopping,
Performance Max, YouTube, Display).

Authentication:
  Google Ads uses OAuth2 with a refresh token. Access tokens expire
  every 1 hour and are automatically refreshed by this connector.
  Required credentials:
    - developer_token  (from Google Ads → Tools → API Center)
    - client_id        (OAuth2 app)
    - client_secret    (OAuth2 app)
    - refresh_token    (user grants access once, stored long-term)
    - customer_id      (Google Ads account ID, no dashes)

API:
  Uses Google Ads REST API v20 directly (no heavy google-ads library).
  All queries use GAQL (Google Ads Query Language).
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from services.agent_swarm.connectors.base import (
    PlatformConnector, CampaignSpec, MetricSnapshot,
)

# Google Ads REST API base (v20 = stable as of early 2026; v18/v19 are sunset)
_GOOGLE_ADS_BASE = "https://googleads.googleapis.com/v20"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_CONTENT_BASE = "https://shoppingcontent.googleapis.com/content/v2.1"


class GoogleConnector(PlatformConnector):
    """
    Connector for Google Ads (Search, Shopping, PMax, YouTube).
    Credentials are loaded from google_auth_tokens table via workspace.
    """

    def __init__(self, connection: dict, workspace: dict):
        super().__init__(connection, workspace)
        # Google-specific fields stored in platform_connections.metadata
        meta = connection.get("metadata", {})
        self.customer_id = (
            connection.get("customer_id") or
            meta.get("customer_id") or
            connection.get("account_id", "")
        ).replace("-", "")
        self.merchant_id = connection.get("merchant_id") or meta.get("merchant_id")
        self.login_customer_id = (
            connection.get("login_customer_id") or
            meta.get("login_customer_id")
        )
        self.developer_token = meta.get("developer_token", "")
        self.client_id = meta.get("client_id", "")
        self.client_secret = meta.get("client_secret", "")
        self.refresh_token = (
            connection.get("refresh_token") or
            meta.get("refresh_token", "")
        )
        self._access_token: Optional[str] = connection.get("access_token")
        self._token_expiry: float = 0.0

    # ── OAuth2 token management ───────────────────────────

    def _get_access_token(self) -> str:
        """Return valid access token, refreshing if expired."""
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token
        return self._refresh_access_token()

    def _refresh_access_token(self) -> str:
        """Exchange refresh token for a new access token."""
        r = requests.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        if not r.ok:
            raise RuntimeError(f"Google token refresh failed: {r.status_code} — {r.text[:200]}")
        data = r.json()
        self._access_token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        # Persist updated token to DB
        self._save_access_token(self._access_token, self._token_expiry)
        return self._access_token

    def _save_access_token(self, token: str, expiry: float):
        """Persist refreshed access token to google_auth_tokens table."""
        try:
            from services.agent_swarm.db import get_conn
            expiry_ts = datetime.fromtimestamp(expiry, tz=timezone.utc)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE google_auth_tokens
                        SET access_token = %s, access_token_expiry = %s, updated_at = NOW()
                        WHERE workspace_id = %s AND customer_id = %s
                        """,
                        (token, expiry_ts, self.workspace["id"], self.customer_id),
                    )
        except Exception as e:
            print(f"Warning: could not save Google access token: {e}")

    def refresh_token_flow(self) -> bool:
        """Public method: force refresh and return success."""
        try:
            self._refresh_access_token()
            return True
        except Exception:
            return False

    # ── Request helpers ───────────────────────────────────

    def _headers(self) -> dict:
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "developer-token": self.developer_token,
            "Content-Type": "application/json",
        }
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id
        return headers

    def _gaql(self, query: str) -> list[dict]:
        """
        Execute a GAQL query via Google Ads Search Stream API.
        Returns list of result rows (each row is a dict).
        """
        url = f"{_GOOGLE_ADS_BASE}/customers/{self.customer_id}/googleAds:searchStream"
        r = requests.post(
            url,
            headers=self._headers(),
            json={"query": query},
            timeout=30,
        )
        if not r.ok:
            print(f"GAQL error {r.status_code}: {r.text[:300]}")
            return []
        # searchStream returns newline-delimited JSON objects
        results = []
        for line in r.text.strip().splitlines():
            try:
                batch = json.loads(line)
                results.extend(batch.get("results", []))
            except json.JSONDecodeError:
                pass
        return results

    # ── PlatformConnector interface ───────────────────────

    def validate_connection(self) -> bool:
        """Test by fetching customer info."""
        try:
            results = self._gaql(
                "SELECT customer.id, customer.descriptive_name "
                "FROM customer LIMIT 1"
            )
            return len(results) > 0
        except Exception:
            return False

    def fetch_metrics(
        self,
        since: str,
        until: str,
        entity_level: str = "campaign",
    ) -> list[MetricSnapshot]:
        """
        Pull Google Ads metrics for a date range using GAQL.
        entity_level: campaign | ad_group | ad | account
        """
        level_map = {
            "campaign":  ("campaign",  "campaign.id",    "campaign.name"),
            "ad_group":  ("ad_group",  "ad_group.id",    "ad_group.name"),
            "ad":        ("ad_group_ad","ad_group_ad.ad.id", "ad_group_ad.ad.name"),
            "account":   ("customer",  "customer.id",    "customer.descriptive_name"),
        }
        resource, id_field, name_field = level_map.get(
            entity_level, level_map["campaign"]
        )

        query = f"""
            SELECT
                {id_field},
                {name_field},
                segments.date,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpm,
                metrics.average_cpc,
                metrics.conversions,
                metrics.conversions_value,
                metrics.interaction_rate,
                metrics.search_impression_share,
                metrics.absolute_top_impression_percentage
            FROM {resource}
            WHERE segments.date BETWEEN '{since}' AND '{until}'
        """

        rows = self._gaql(query)
        snapshots = []
        for row in rows:
            try:
                metrics = row.get("metrics", {})
                seg = row.get("segments", {})
                entity = row.get(resource.replace("_group_ad", "GroupAd"), {})
                # Normalize entity dict access
                resource_key = resource.replace("_", " ").title().replace(" ", "")
                resource_key = resource_key[0].lower() + resource_key[1:]

                # Entity ID and name
                if entity_level == "ad":
                    ad_info = row.get("adGroupAd", {}).get("ad", {})
                    entity_id = str(ad_info.get("id", ""))
                    entity_name = ad_info.get("name", "") or entity_id
                    campaign_id = row.get("campaign", {}).get("id", "")
                elif entity_level == "ad_group":
                    ag = row.get("adGroup", {})
                    entity_id = str(ag.get("id", ""))
                    entity_name = ag.get("name", "") or entity_id
                    campaign_id = row.get("campaign", {}).get("id", "")
                elif entity_level == "account":
                    cust = row.get("customer", {})
                    entity_id = str(cust.get("id", self.customer_id))
                    entity_name = cust.get("descriptiveName", "account")
                    campaign_id = ""
                else:  # campaign
                    camp = row.get("campaign", {})
                    entity_id = str(camp.get("id", ""))
                    entity_name = camp.get("name", "") or entity_id
                    campaign_id = entity_id

                spend = float(metrics.get("costMicros", 0)) / 1_000_000
                impressions = int(metrics.get("impressions", 0))
                clicks = int(metrics.get("clicks", 0))
                conversions = float(metrics.get("conversions", 0))
                revenue = float(metrics.get("conversionsValue", 0))
                ctr = float(metrics.get("ctr", 0)) * 100
                cpm = float(metrics.get("averageCpm", 0)) / 1_000_000 * 1000
                cpc = float(metrics.get("averageCpc", 0)) / 1_000_000
                roas = round(revenue / spend, 4) if spend > 0 else 0.0

                date_str = seg.get("date", since)
                hour_ts = f"{date_str}T00:00:00+00:00"

                snapshots.append(MetricSnapshot(
                    platform="google",
                    account_id=self.customer_id,
                    entity_level=entity_level,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    hour_ts=hour_ts,
                    spend=spend,
                    impressions=impressions,
                    clicks=clicks,
                    conversions=int(conversions),
                    revenue=revenue,
                    ctr=ctr,
                    cpm=cpm,
                    cpc=cpc,
                    roas=roas,
                    raw_json=row,
                ))
            except Exception as e:
                print(f"GoogleConnector.fetch_metrics row parse error: {e}")

        return snapshots

    def list_campaigns(self, status: str = "ALL") -> list[dict]:
        """List campaigns with budget info. status='ALL' returns enabled + paused."""
        if status == "ALL":
            where = "campaign.status IN ('ENABLED', 'PAUSED')"
        else:
            where = f"campaign.status = '{status}'"
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign_budget.amount_micros,
                campaign_budget.id,
                metrics.cost_micros,
                metrics.impressions
            FROM campaign
            WHERE {where}
        """
        rows = self._gaql(query)
        result = []
        for row in rows:
            camp = row.get("campaign", {})
            budget = row.get("campaignBudget", {})
            metrics = row.get("metrics", {})
            result.append({
                "id": str(camp.get("id", "")),
                "name": camp.get("name", ""),
                "status": camp.get("status", ""),
                "type": camp.get("advertisingChannelType", ""),
                "daily_budget_inr": float(budget.get("amountMicros", 0)) / 1_000_000,
                "budget_id": str(budget.get("id", "")),
                "spend_today": float(metrics.get("costMicros", 0)) / 1_000_000,
                "impressions": int(metrics.get("impressions", 0)),
            })
        return result

    def update_budget(self, entity_id: str, new_daily_budget_inr: float) -> bool:
        """
        Update a campaign budget. entity_id is the campaignBudget resource name
        or we look it up by campaign ID.
        """
        budget_micros = int(new_daily_budget_inr * 1_000_000)
        budget_resource = f"customers/{self.customer_id}/campaignBudgets/{entity_id}"
        url = f"{_GOOGLE_ADS_BASE}/customers/{self.customer_id}/campaignBudgets:mutate"
        payload = {
            "operations": [{
                "update": {
                    "resourceName": budget_resource,
                    "amountMicros": str(budget_micros),
                },
                "updateMask": "amountMicros",
            }]
        }
        try:
            r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
            return r.status_code < 300
        except Exception as e:
            print(f"Google update_budget error: {e}")
            return False

    def pause(self, entity_id: str) -> bool:
        """Pause a campaign by ID."""
        return self._set_campaign_status(entity_id, "PAUSED")

    def resume(self, entity_id: str) -> bool:
        """Enable a paused campaign."""
        return self._set_campaign_status(entity_id, "ENABLED")

    def _set_campaign_status(self, campaign_id: str, status: str) -> bool:
        resource = f"customers/{self.customer_id}/campaigns/{campaign_id}"
        url = f"{_GOOGLE_ADS_BASE}/customers/{self.customer_id}/campaigns:mutate"
        payload = {
            "operations": [{
                "update": {"resourceName": resource, "status": status},
                "updateMask": "status",
            }]
        }
        try:
            r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
            return r.status_code < 300
        except Exception as e:
            print(f"Google _set_campaign_status error: {e}")
            return False

    # ── Performance Max campaign creation ─────────────────

    def create_campaign(self, spec: CampaignSpec) -> dict:
        """
        Create a Performance Max campaign.
        PMax is Google's recommended campaign type — covers Search,
        Shopping, YouTube, Display, and Gmail from one campaign.
        """
        try:
            budget_id = self._create_campaign_budget(spec.daily_budget_inr, spec.name)
            if not budget_id:
                return {"error": "Failed to create campaign budget"}

            campaign_id = self._create_pmax_campaign(spec.name, budget_id)
            if not campaign_id:
                return {"error": "Failed to create PMax campaign"}

            asset_group_id = self._create_asset_group(campaign_id, spec)
            return {
                "campaign_id": campaign_id,
                "budget_id": budget_id,
                "asset_group_id": asset_group_id,
                "status": "created",
                "platform": "google",
                "type": "PERFORMANCE_MAX",
            }
        except Exception as e:
            print(f"Google create_campaign error: {e}")
            return {"error": str(e)}

    def _create_campaign_budget(self, daily_budget_inr: float, name: str) -> Optional[str]:
        url = f"{_GOOGLE_ADS_BASE}/customers/{self.customer_id}/campaignBudgets:mutate"
        payload = {
            "operations": [{
                "create": {
                    "name": f"{name} Budget",
                    "amountMicros": str(int(daily_budget_inr * 1_000_000)),
                    "deliveryMethod": "STANDARD",
                    "explicitlyShared": False,
                }
            }]
        }
        r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
        if r.ok:
            results = r.json().get("results", [{}])
            resource = results[0].get("resourceName", "")
            return resource.split("/")[-1] if resource else None
        print(f"Create budget error: {r.text[:200]}")
        return None

    def _create_pmax_campaign(self, name: str, budget_id: str) -> Optional[str]:
        url = f"{_GOOGLE_ADS_BASE}/customers/{self.customer_id}/campaigns:mutate"
        budget_resource = f"customers/{self.customer_id}/campaignBudgets/{budget_id}"
        payload = {
            "operations": [{
                "create": {
                    "name": name,
                    "status": "PAUSED",           # Start paused, enable after review
                    "advertisingChannelType": "PERFORMANCE_MAX",
                    "campaignBudget": budget_resource,
                    "biddingStrategyType": "MAXIMIZE_CONVERSION_VALUE",
                    "targetRoas": {
                        "targetRoas": 2.5,        # 2.5x ROAS target
                    },
                }
            }]
        }
        r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
        if r.ok:
            results = r.json().get("results", [{}])
            resource = results[0].get("resourceName", "")
            return resource.split("/")[-1] if resource else None
        print(f"Create PMax campaign error: {r.text[:200]}")
        return None

    def _create_asset_group(self, campaign_id: str, spec: CampaignSpec) -> Optional[str]:
        """Create asset group with headlines, descriptions, images, and URLs."""
        url = f"{_GOOGLE_ADS_BASE}/customers/{self.customer_id}/assetGroups:mutate"
        campaign_resource = f"customers/{self.customer_id}/campaigns/{campaign_id}"

        # Build text assets from spec
        headlines = [
            spec.headline or spec.product_name,
            f"₹{spec.daily_budget_inr:.0f} Daily Budget" if spec.daily_budget_inr else spec.product_name,
            spec.product_name,
        ]
        descriptions = [
            spec.primary_text[:90] if spec.primary_text else spec.product_name,
            spec.description[:90] if spec.description else f"Buy {spec.product_name} online",
        ]

        payload = {
            "operations": [{
                "create": {
                    "name": f"{spec.name} Assets",
                    "campaign": campaign_resource,
                    "status": "ENABLED",
                    "finalUrls": [spec.product_url],
                    "headlines": [{"text": h[:30]} for h in headlines if h][:15],
                    "descriptions": [{"text": d[:90]} for d in descriptions if d][:5],
                    "businessName": self.workspace.get("name", "")[:25],
                }
            }]
        }
        r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
        if r.ok:
            results = r.json().get("results", [{}])
            resource = results[0].get("resourceName", "")
            return resource.split("/")[-1] if resource else None
        print(f"Create asset group error: {r.text[:200]}")
        return None

    # ── Keyword management ────────────────────────────────

    def add_keyword(self, ad_group_id: str, keyword_text: str, match_type: str = "BROAD") -> dict:
        """
        Add a keyword to an ad group.
        match_type: BROAD | PHRASE | EXACT
        Returns {ok, resource, error}.
        """
        url = f"{_GOOGLE_ADS_BASE}/customers/{self.customer_id}/adGroupCriteria:mutate"
        ad_group_resource = f"customers/{self.customer_id}/adGroups/{ad_group_id}"
        payload = {
            "operations": [{
                "create": {
                    "adGroup": ad_group_resource,
                    "status": "ENABLED",
                    "keyword": {
                        "text": keyword_text[:80],
                        "matchType": match_type.upper(),
                    },
                }
            }]
        }
        try:
            r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
            if r.ok:
                results = r.json().get("results", [{}])
                return {"ok": True, "resource": results[0].get("resourceName", "")}
            err = r.json().get("error", {})
            return {"ok": False, "error": err.get("message", r.text[:200])}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def adjust_bid(self, ad_group_id: str, cpc_bid_micros: int) -> dict:
        """
        Set CPC bid on an ad group (in micros, 1_000_000 = ₹1 / $1).
        Returns {ok, error}.
        """
        url = f"{_GOOGLE_ADS_BASE}/customers/{self.customer_id}/adGroups:mutate"
        resource = f"customers/{self.customer_id}/adGroups/{ad_group_id}"
        payload = {
            "operations": [{
                "update": {
                    "resourceName": resource,
                    "cpcBidMicros": str(cpc_bid_micros),
                },
                "updateMask": "cpcBidMicros",
            }]
        }
        try:
            r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
            return {"ok": r.status_code < 300, "error": r.text[:200] if not r.ok else None}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Search term report ────────────────────────────────

    def fetch_search_terms(self, since: str, until: str) -> list[dict]:
        """Fetch search terms that triggered ads. Used for keyword intelligence."""
        query = f"""
            SELECT
                search_term_view.search_term,
                search_term_view.status,
                ad_group.id,
                ad_group.name,
                campaign.id,
                campaign.name,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value,
                metrics.ctr,
                metrics.average_cpc,
                segments.date
            FROM search_term_view
            WHERE segments.date BETWEEN '{since}' AND '{until}'
              AND metrics.clicks > 0
            ORDER BY metrics.cost_micros DESC
            LIMIT 1000
        """
        rows = self._gaql(query)
        terms = []
        for row in rows:
            stv = row.get("searchTermView", {})
            ag = row.get("adGroup", {})
            camp = row.get("campaign", {})
            metrics = row.get("metrics", {})
            seg = row.get("segments", {})
            terms.append({
                "search_term": stv.get("searchTerm", ""),
                "status": stv.get("status", ""),
                "ad_group_id": str(ag.get("id", "")),
                "ad_group_name": ag.get("name", ""),
                "campaign_id": str(camp.get("id", "")),
                "campaign_name": camp.get("name", ""),
                "impressions": int(metrics.get("impressions", 0)),
                "clicks": int(metrics.get("clicks", 0)),
                "spend": float(metrics.get("costMicros", 0)) / 1_000_000,
                "conversions": float(metrics.get("conversions", 0)),
                "revenue": float(metrics.get("conversionsValue", 0)),
                "ctr": float(metrics.get("ctr", 0)) * 100,
                "avg_cpc": float(metrics.get("averageCpc", 0)) / 1_000_000,
                "date": seg.get("date", since),
                "customer_id": self.customer_id,
                "workspace_id": self.workspace["id"],
            })
        return terms

    # ── Keyword performance ───────────────────────────────

    def fetch_keyword_performance(self, since: str, until: str) -> list[dict]:
        """Fetch keyword-level performance for Search campaigns."""
        query = f"""
            SELECT
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.quality_info.quality_score,
                ad_group.id,
                campaign.id,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.ctr,
                metrics.average_cpc,
                segments.date
            FROM keyword_view
            WHERE segments.date BETWEEN '{since}' AND '{until}'
              AND metrics.impressions > 0
            LIMIT 500
        """
        rows = self._gaql(query)
        keywords = []
        for row in rows:
            criterion = row.get("adGroupCriterion", {})
            kw = criterion.get("keyword", {})
            quality = criterion.get("qualityInfo", {})
            metrics = row.get("metrics", {})
            seg = row.get("segments", {})
            keywords.append({
                "keyword": kw.get("text", ""),
                "match_type": kw.get("matchType", ""),
                "quality_score": quality.get("qualityScore"),
                "ad_group_id": str(row.get("adGroup", {}).get("id", "")),
                "campaign_id": str(row.get("campaign", {}).get("id", "")),
                "impressions": int(metrics.get("impressions", 0)),
                "clicks": int(metrics.get("clicks", 0)),
                "spend": float(metrics.get("costMicros", 0)) / 1_000_000,
                "conversions": float(metrics.get("conversions", 0)),
                "ctr": float(metrics.get("ctr", 0)) * 100,
                "avg_cpc": float(metrics.get("averageCpc", 0)) / 1_000_000,
                "date": seg.get("date", since),
            })
        return keywords

    # ── Shopping / Merchant Center helpers ────────────────

    def get_shopping_performance(self, since: str, until: str) -> list[dict]:
        """Shopping campaign performance broken down by product."""
        query = f"""
            SELECT
                segments.product_title,
                segments.product_item_id,
                campaign.id,
                campaign.name,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value,
                segments.date
            FROM shopping_performance_view
            WHERE segments.date BETWEEN '{since}' AND '{until}'
              AND metrics.impressions > 0
            ORDER BY metrics.cost_micros DESC
            LIMIT 200
        """
        rows = self._gaql(query)
        results = []
        for row in rows:
            seg = row.get("segments", {})
            metrics = row.get("metrics", {})
            camp = row.get("campaign", {})
            results.append({
                "product_title": seg.get("productTitle", ""),
                "product_item_id": seg.get("productItemId", ""),
                "campaign_id": str(camp.get("id", "")),
                "campaign_name": camp.get("name", ""),
                "impressions": int(metrics.get("impressions", 0)),
                "clicks": int(metrics.get("clicks", 0)),
                "spend": float(metrics.get("costMicros", 0)) / 1_000_000,
                "conversions": float(metrics.get("conversions", 0)),
                "revenue": float(metrics.get("conversionsValue", 0)),
                "date": seg.get("date", since),
            })
        return results
