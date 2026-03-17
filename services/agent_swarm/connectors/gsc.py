"""
Google Search Console connector.

Uses the Search Console API v3 (REST) to fetch:
  - Site list / property URLs
  - Search analytics: keywords, pages, devices, countries
  - URL inspection (index status)

Auth: same OAuth2 refresh token flow as GA4.
Scope: https://www.googleapis.com/auth/webmasters.readonly
"""

import time
import requests

_BASE      = "https://searchconsole.googleapis.com/webmasters/v3"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GSCConnector:

    def __init__(self, access_token: str, refresh_token: str,
                 client_id: str, client_secret: str, site_url: str = ""):
        self._access_token = access_token or ""
        self._token_expiry = 0.0
        self.refresh_token = refresh_token or ""
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.site_url = site_url  # e.g. "sc-domain:example.com" or "https://example.com/"

    # ── Token management ─────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token
        r = requests.post(_TOKEN_URL, data={
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type":    "refresh_token",
        }, timeout=15)
        r.raise_for_status()
        d = r.json()
        self._access_token = d["access_token"]
        self._token_expiry = time.time() + d.get("expires_in", 3600)
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}",
                "Content-Type": "application/json"}

    # ── Site list ────────────────────────────────────────────────────────────

    def list_sites(self) -> list[dict]:
        """Return all verified GSC properties for this account."""
        r = requests.get(f"{_BASE}/sites", headers=self._headers(), timeout=15)
        r.raise_for_status()
        return r.json().get("siteEntry", [])

    # ── Search analytics ─────────────────────────────────────────────────────

    def _analytics(self, dimensions: list[str], days: int = 28,
                   row_limit: int = 50, filters: list | None = None) -> list[dict]:
        from datetime import date, timedelta
        end   = date.today() - timedelta(days=3)   # GSC has ~3-day lag
        start = end - timedelta(days=days - 1)
        body: dict = {
            "startDate":  start.isoformat(),
            "endDate":    end.isoformat(),
            "dimensions": dimensions,
            "rowLimit":   row_limit,
            "dataState":  "final",
        }
        if filters:
            body["dimensionFilterGroups"] = [{"filters": filters}]
        site = requests.utils.quote(self.site_url, safe="")
        r = requests.post(
            f"{_BASE}/sites/{site}/searchAnalytics/query",
            headers=self._headers(),
            json=body,
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("rows", [])

    def top_keywords(self, days: int = 28, limit: int = 50) -> list[dict]:
        rows = self._analytics(["query"], days=days, row_limit=limit)
        return [
            {
                "keyword":     r["keys"][0],
                "clicks":      r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr":         round(r.get("ctr", 0) * 100, 2),
                "position":    round(r.get("position", 0), 1),
            }
            for r in rows
        ]

    def top_pages(self, days: int = 28, limit: int = 50) -> list[dict]:
        rows = self._analytics(["page"], days=days, row_limit=limit)
        return [
            {
                "page":        r["keys"][0],
                "clicks":      r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr":         round(r.get("ctr", 0) * 100, 2),
                "position":    round(r.get("position", 0), 1),
            }
            for r in rows
        ]

    def keyword_trend(self, keyword: str, days: int = 90) -> list[dict]:
        """Daily clicks + impressions for a specific keyword."""
        rows = self._analytics(
            ["date"],
            days=days,
            row_limit=days,
            filters=[{"dimension": "query", "operator": "equals", "expression": keyword}],
        )
        return [
            {
                "date":        r["keys"][0],
                "clicks":      r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "position":    round(r.get("position", 0), 1),
            }
            for r in rows
        ]

    def device_breakdown(self, days: int = 28) -> list[dict]:
        rows = self._analytics(["device"], days=days, row_limit=10)
        return [
            {
                "device":      r["keys"][0],
                "clicks":      r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr":         round(r.get("ctr", 0) * 100, 2),
                "position":    round(r.get("position", 0), 1),
            }
            for r in rows
        ]

    def country_breakdown(self, days: int = 28, limit: int = 20) -> list[dict]:
        rows = self._analytics(["country"], days=days, row_limit=limit)
        return [
            {
                "country":     r["keys"][0],
                "clicks":      r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr":         round(r.get("ctr", 0) * 100, 2),
                "position":    round(r.get("position", 0), 1),
            }
            for r in rows
        ]
