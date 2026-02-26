"""
Google Analytics 4 connector.

Uses the GA4 Data API v1beta (REST) + GA4 Admin API to:
  - Auto-discover the GA4 property ID after OAuth.
  - Fetch overview metrics, conversions, landing pages, traffic sources,
    device breakdown, geo breakdown, and hourly session data.

Authentication: OAuth2 access + refresh token (same flow as YouTube connector).
No new pip packages needed — uses the `requests` library already installed.
"""

import time
from datetime import datetime, timedelta, timezone

import requests


_DATA_BASE  = "https://analyticsdata.googleapis.com/v1beta"
_ADMIN_BASE = "https://analyticsadmin.googleapis.com/v1beta"
_TOKEN_URL  = "https://oauth2.googleapis.com/token"


class GA4Connector:
    """Connector for Google Analytics 4 Data API + Admin API."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        property_id: str,
        client_id: str,
        client_secret: str,
    ):
        self._access_token: str = access_token or ""
        self._token_expiry: float = 0
        self.refresh_token: str = refresh_token or ""
        self.property_id: str = property_id or ""  # numeric, e.g. "123456789"
        self.client_id: str = client_id or ""
        self.client_secret: str = client_secret or ""

    # ── OAuth2 token management ──────────────────────────────────────────────

    def _get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token
        return self._refresh_access_token()

    def _refresh_access_token(self) -> str:
        resp = requests.post(
            _TOKEN_URL,
            data={
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        return self._access_token

    # ── Low-level helpers ────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_access_token()}"}

    def _run_report(self, body: dict) -> dict:
        """POST to GA4 Data API runReport for this property."""
        url = f"{_DATA_BASE}/properties/{self.property_id}:runReport"
        resp = requests.post(url, json=body, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _date_range(days: int) -> dict:
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=days - 1)
        return {"startDate": start.isoformat(), "endDate": "today"}

    @staticmethod
    def _prev_date_range(days: int) -> dict:
        today = datetime.now(timezone.utc).date()
        end   = today - timedelta(days=days)
        start = end   - timedelta(days=days - 1)
        return {"startDate": start.isoformat(), "endDate": end.isoformat()}

    @staticmethod
    def _safe_float(val: str | None) -> float:
        try:
            return float(val or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(val: str | None) -> int:
        try:
            return int(float(val or 0))
        except (TypeError, ValueError):
            return 0

    def _row_to_dict(self, report: dict, dim_names: list[str], met_names: list[str]) -> list[dict]:
        """Convert runReport response rows → list of dicts."""
        rows = report.get("rows", []) or []
        result = []
        for row in rows:
            dims = {dim_names[i]: dv["value"] for i, dv in enumerate(row.get("dimensionValues", []))}
            mets = {met_names[i]: mv["value"] for i, mv in enumerate(row.get("metricValues", []))}
            result.append({**dims, **mets})
        return result

    # ── Admin API: property discovery ────────────────────────────────────────

    @classmethod
    def discover_property_id(cls, access_token: str) -> str | None:
        """
        Call GA4 Admin API accountSummaries and pick the property with the
        most sessions in the last 30 days (most active / current).
        Falls back to the first property if none have recent traffic.
        Returns the numeric property ID string (e.g. "123456789") or None.
        """
        props = cls.list_all_properties(access_token)
        if not props:
            return None
        if len(props) == 1:
            return props[0]["property_id"]

        # Score each property by last-30-day sessions
        best_id = props[0]["property_id"]
        best_sessions = -1
        headers = {"Authorization": f"Bearer {access_token}"}
        from datetime import datetime, timedelta, timezone
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=29)).isoformat()
        for prop in props:
            pid = prop["property_id"]
            try:
                r = requests.post(
                    f"{_DATA_BASE}/properties/{pid}:runReport",
                    headers=headers,
                    json={
                        "dateRanges": [{"startDate": start, "endDate": "today"}],
                        "metrics": [{"name": "sessions"}],
                    },
                    timeout=10,
                )
                if r.ok:
                    rows = r.json().get("rows", []) or []
                    sessions = int(float(rows[0]["metricValues"][0]["value"])) if rows else 0
                    print(f"[ga4] property {pid} ({prop['display_name']}): {sessions} sessions")
                    if sessions > best_sessions:
                        best_sessions = sessions
                        best_id = pid
            except Exception as e:
                print(f"[ga4] scoring property {pid} failed: {e}")
        print(f"[ga4] best property: {best_id} with {best_sessions} sessions")
        return best_id

    @classmethod
    def list_all_properties(cls, access_token: str) -> list[dict]:
        """
        Return all GA4 properties visible to this Google account.
        Each entry: {property_id, display_name, account_name}
        """
        try:
            resp = requests.get(
                f"{_ADMIN_BASE}/accountSummaries",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if not resp.ok:
                print(f"[ga4] accountSummaries {resp.status_code}: {resp.text[:300]}")
                return []
            data = resp.json()
            result = []
            for account in data.get("accountSummaries", []):
                acct_name = account.get("displayName", "")
                for prop in account.get("propertySummaries", []):
                    prop_name = prop.get("property", "")
                    if prop_name.startswith("properties/"):
                        result.append({
                            "property_id":   prop_name.split("/")[-1],
                            "display_name":  prop.get("displayName", ""),
                            "account_name":  acct_name,
                        })
            return result
        except Exception as e:
            print(f"[ga4] list_all_properties error: {e}")
            return []

    # ── Overview ─────────────────────────────────────────────────────────────

    def get_overview(self, days: int = 30) -> dict:
        """
        Aggregate sessions, users, new_users, bounce_rate, avg_session_duration,
        conversions, and revenue for the current and previous period.
        Returns: {current: {...}, previous: {...}, pct_changes: {...}}
        """
        metrics = [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "newUsers"},
            {"name": "bounceRate"},
            {"name": "averageSessionDuration"},
            {"name": "conversions"},
            {"name": "totalRevenue"},
        ]

        def _fetch_period(dr: dict) -> dict:
            body = {"dateRanges": [dr], "metrics": metrics}
            try:
                report = self._run_report(body)
                rows = report.get("rows", []) or []
                if not rows:
                    return {}
                mvs = rows[0].get("metricValues", [])
                return {
                    "sessions":               self._safe_int(mvs[0]["value"] if mvs else None),
                    "users":                  self._safe_int(mvs[1]["value"] if len(mvs) > 1 else None),
                    "new_users":              self._safe_int(mvs[2]["value"] if len(mvs) > 2 else None),
                    "bounce_rate":            round(self._safe_float(mvs[3]["value"] if len(mvs) > 3 else None) * 100, 1),
                    "avg_session_duration":   round(self._safe_float(mvs[4]["value"] if len(mvs) > 4 else None), 1),
                    "conversions":            self._safe_int(mvs[5]["value"] if len(mvs) > 5 else None),
                    "revenue":                round(self._safe_float(mvs[6]["value"] if len(mvs) > 6 else None), 2),
                }
            except Exception as e:
                print(f"[ga4] get_overview period error: {e}")
                return {}

        current  = _fetch_period(self._date_range(days))
        previous = _fetch_period(self._prev_date_range(days))

        pct_changes: dict = {}
        for key in current:
            cur_val  = current.get(key, 0) or 0
            prev_val = previous.get(key, 0) or 0
            if prev_val:
                pct_changes[key] = round((cur_val - prev_val) / prev_val * 100, 1)
            else:
                pct_changes[key] = None

        return {"current": current, "previous": previous, "pct_changes": pct_changes, "days": days}

    # ── Conversions ──────────────────────────────────────────────────────────

    def get_conversions(self, days: int = 30) -> list[dict]:
        """
        Return per-event conversion counts and revenue for the period.
        """
        body = {
            "dateRanges": [self._date_range(days)],
            "dimensions": [{"name": "eventName"}],
            "metrics": [
                {"name": "eventCount"},
                {"name": "conversions"},
                {"name": "totalRevenue"},
            ],
            "orderBys": [{"metric": {"metricName": "conversions"}, "desc": True}],
            "limit": 20,
        }
        try:
            report = self._run_report(body)
            rows = self._row_to_dict(report, ["event_name"], ["event_count", "conversions", "revenue"])
            return [
                {
                    "event_name":   r["event_name"],
                    "event_count":  self._safe_int(r["event_count"]),
                    "conversions":  self._safe_int(r["conversions"]),
                    "revenue":      round(self._safe_float(r["revenue"]), 2),
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[ga4] get_conversions error: {e}")
            return []

    # ── Landing Pages ────────────────────────────────────────────────────────

    def get_landing_pages(self, days: int = 30) -> list[dict]:
        """
        Return landing page paths with sessions, bounce_rate, avg_engagement_time,
        conversions, and computed drop_off_pct.
        """
        body = {
            "dateRanges": [self._date_range(days)],
            "dimensions": [{"name": "landingPage"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "bounceRate"},
                {"name": "averageSessionDuration"},
                {"name": "conversions"},
            ],
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit": 25,
        }
        try:
            report = self._run_report(body)
            rows = self._row_to_dict(
                report,
                ["page_path"],
                ["sessions", "bounce_rate", "avg_engagement_time", "conversions"],
            )
            result = []
            for r in rows:
                sessions    = self._safe_int(r["sessions"])
                bounce_rate = round(self._safe_float(r["bounce_rate"]) * 100, 1)
                avg_time    = round(self._safe_float(r["avg_engagement_time"]), 1)
                conversions = self._safe_int(r["conversions"])
                drop_off    = round(max(0.0, (sessions - conversions) / sessions * 100), 1) if sessions > 0 else 100.0
                result.append({
                    "page_path":          r["page_path"],
                    "sessions":           sessions,
                    "bounce_rate":        bounce_rate,
                    "avg_engagement_time":avg_time,
                    "conversions":        conversions,
                    "drop_off_pct":       drop_off,
                })
            return result
        except Exception as e:
            print(f"[ga4] get_landing_pages error: {e}")
            return []

    # ── Traffic Sources ──────────────────────────────────────────────────────

    def get_traffic_sources(self, days: int = 30) -> list[dict]:
        """
        Return sessions + conversions + revenue grouped by sessionSourceMedium.
        """
        body = {
            "dateRanges": [self._date_range(days)],
            "dimensions": [{"name": "sessionSourceMedium"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "conversions"},
                {"name": "totalRevenue"},
            ],
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit": 20,
        }
        try:
            report = self._run_report(body)
            rows = self._row_to_dict(
                report,
                ["source_medium"],
                ["sessions", "conversions", "revenue"],
            )
            return [
                {
                    "source_medium": r["source_medium"],
                    "sessions":      self._safe_int(r["sessions"]),
                    "conversions":   self._safe_int(r["conversions"]),
                    "revenue":       round(self._safe_float(r["revenue"]), 2),
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[ga4] get_traffic_sources error: {e}")
            return []

    # ── Devices ──────────────────────────────────────────────────────────────

    def get_devices(self, days: int = 30) -> list[dict]:
        """Return session + conversion breakdown by device category."""
        body = {
            "dateRanges": [self._date_range(days)],
            "dimensions": [{"name": "deviceCategory"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "conversions"},
            ],
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        }
        try:
            report = self._run_report(body)
            rows = self._row_to_dict(report, ["device"], ["sessions", "conversions"])
            total_sessions = sum(self._safe_int(r["sessions"]) for r in rows) or 1
            return [
                {
                    "device":       r["device"],
                    "sessions":     self._safe_int(r["sessions"]),
                    "conversions":  self._safe_int(r["conversions"]),
                    "pct_of_total": round(self._safe_int(r["sessions"]) / total_sessions * 100, 1),
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[ga4] get_devices error: {e}")
            return []

    # ── Geo ──────────────────────────────────────────────────────────────────

    def get_geo(self, days: int = 30) -> list[dict]:
        """Return top countries + cities by sessions."""
        body = {
            "dateRanges": [self._date_range(days)],
            "dimensions": [{"name": "country"}, {"name": "city"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "conversions"},
            ],
            "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
            "limit": 30,
        }
        try:
            report = self._run_report(body)
            rows = self._row_to_dict(report, ["country", "city"], ["sessions", "conversions"])
            return [
                {
                    "country":     r["country"],
                    "city":        r["city"],
                    "sessions":    self._safe_int(r["sessions"]),
                    "conversions": self._safe_int(r["conversions"]),
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[ga4] get_geo error: {e}")
            return []

    # ── Hourly (best posting time) ────────────────────────────────────────────

    def get_hourly(self, days: int = 7) -> list[dict]:
        """Return session breakdown by hour of day."""
        body = {
            "dateRanges": [self._date_range(days)],
            "dimensions": [{"name": "hour"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "conversions"},
            ],
            "orderBys": [{"dimension": {"dimensionName": "hour"}}],
        }
        try:
            report = self._run_report(body)
            rows = self._row_to_dict(report, ["hour"], ["sessions", "conversions"])
            return [
                {
                    "hour":        self._safe_int(r["hour"]),
                    "sessions":    self._safe_int(r["sessions"]),
                    "conversions": self._safe_int(r["conversions"]),
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[ga4] get_hourly error: {e}")
            return []
