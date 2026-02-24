# services/agent_swarm/connectors/base.py
"""
Platform Connector Interface — every ad platform implements this.

Adding a new platform (YouTube, Amazon, Flipkart, TikTok) means:
  1. Create connectors/<platform>.py
  2. Implement PlatformConnector
  3. Register in CONNECTOR_REGISTRY below

Nothing else in the core agent layer changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CampaignSpec:
    """Standardized campaign creation spec (platform-agnostic)."""
    name: str
    product_id: str
    product_name: str
    product_url: str
    daily_budget_inr: float
    objective: str = "conversions"          # conversions|awareness|traffic
    audience_description: str = ""
    image_url: str = ""
    video_url: str = ""
    headline: str = ""
    primary_text: str = ""
    description: str = ""
    cta: str = "Shop Now"
    targeting: dict = field(default_factory=dict)


@dataclass
class MetricSnapshot:
    """Standardized hourly metrics row (platform-agnostic)."""
    platform: str
    account_id: str
    entity_level: str           # account|campaign|adset|ad
    entity_id: str
    entity_name: str
    hour_ts: str                # ISO timestamp of the hour bucket
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    revenue: float = 0.0
    ctr: float = 0.0
    cpm: float = 0.0
    cpc: float = 0.0
    roas: float = 0.0
    raw_json: dict = field(default_factory=dict)


class PlatformConnector(ABC):
    """
    Abstract base class for all ad platform connectors.
    Each connector wraps one platform_connection row.
    """

    def __init__(self, connection: dict, workspace: dict):
        """
        connection: a platform_connections row dict (from core.workspace)
        workspace:  the parent workspace dict
        """
        self.connection = connection
        self.workspace = workspace
        self.platform = connection["platform"]
        self.account_id = connection["account_id"]
        self.access_token = connection["access_token"]

    # ── Required: every platform must implement these ─────────

    @abstractmethod
    def validate_connection(self) -> bool:
        """
        Test that the stored credentials are still valid.
        Returns True if credentials work, False if they need refresh.
        """
        ...

    @abstractmethod
    def fetch_metrics(
        self,
        since: str,
        until: str,
        entity_level: str = "account",
    ) -> list[MetricSnapshot]:
        """
        Pull performance metrics for the given time window.
        since/until: ISO date strings (YYYY-MM-DD)
        Returns list of MetricSnapshot objects.
        """
        ...

    @abstractmethod
    def create_campaign(self, spec: CampaignSpec) -> dict:
        """
        Create a new campaign from a standardized CampaignSpec.
        Returns: {campaign_id, adset_id, ad_id, status, platform_response}
        """
        ...

    @abstractmethod
    def update_budget(self, entity_id: str, new_daily_budget_inr: float) -> bool:
        """
        Update the daily budget for a campaign or adset.
        Returns True on success.
        """
        ...

    @abstractmethod
    def pause(self, entity_id: str) -> bool:
        """Pause a campaign, adset, or ad. Returns True on success."""
        ...

    @abstractmethod
    def resume(self, entity_id: str) -> bool:
        """Resume a paused entity. Returns True on success."""
        ...

    # ── Optional: platforms implement if supported ────────────

    def list_campaigns(self, status: str = "ACTIVE") -> list[dict]:
        """List campaigns. Returns list of {id, name, status, daily_budget}."""
        return []

    def get_campaign(self, campaign_id: str) -> Optional[dict]:
        """Get single campaign details."""
        return None

    def upload_image(self, image_url: str) -> Optional[str]:
        """Upload an image asset. Returns platform asset ID."""
        return None

    def upload_video(self, video_url: str) -> Optional[str]:
        """Upload a video asset. Returns platform asset ID."""
        return None

    def get_creative_performance(self, ad_ids: list[str]) -> list[dict]:
        """Get per-creative performance breakdown."""
        return []

    def refresh_token(self) -> bool:
        """Refresh OAuth token if expired. Returns True if refreshed."""
        return False


# ── Registry ──────────────────────────────────────────────

def get_connector(connection: dict, workspace: dict) -> Optional[PlatformConnector]:
    """
    Factory: return the right connector for a platform_connection row.
    Usage:
        conn = get_primary_connection(workspace, "meta")
        connector = get_connector(conn, workspace)
        metrics = connector.fetch_metrics(since="2026-02-01", until="2026-02-23")
    """
    platform = connection.get("platform", "")
    if platform == "meta":
        from services.agent_swarm.connectors.meta import MetaConnector
        return MetaConnector(connection, workspace)
    if platform == "google":
        from services.agent_swarm.connectors.google import GoogleConnector
        return GoogleConnector(connection, workspace)
    # Future: amazon, flipkart, youtube, tiktok
    print(f"No connector registered for platform: {platform}")
    return None
