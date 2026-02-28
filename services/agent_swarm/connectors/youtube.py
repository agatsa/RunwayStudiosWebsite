# services/agent_swarm/connectors/youtube.py
"""
YouTube Channel Intelligence connector.

Two access modes:
  1. API key only  — read public channel + video data (channel info, video list)
  2. OAuth2 + key  — everything above PLUS Analytics (watch time, CTR, avg view %)

Two APIs:
  - YouTube Data API v3:      https://www.googleapis.com/youtube/v3/
  - YouTube Analytics API v2: https://youtubeanalytics.googleapis.com/v2/reports
"""

import re
import time
from datetime import datetime, timezone

import requests


_DATA_BASE      = "https://www.googleapis.com/youtube/v3"
_ANALYTICS_BASE = "https://youtubeanalytics.googleapis.com/v2/reports"
_TOKEN_URL      = "https://oauth2.googleapis.com/token"


class YouTubeConnector:
    """Connector for YouTube Data API v3 + YouTube Analytics API v2."""

    def __init__(self, conn: dict, workspace: dict, api_key: str = ""):
        """
        conn keys (from google_auth_tokens row, all optional):
            client_id, client_secret, refresh_token, access_token
        channel_id must be in conn["youtube_channel_id"] or set separately.
        api_key — YouTube Data API key for public-data calls (no OAuth needed).
        has_oauth — True when OAuth2 credentials are present and valid.
        """
        meta = conn.get("metadata", {}) or {}
        self.client_id     = meta.get("client_id", "") or conn.get("client_id", "")
        self.client_secret = meta.get("client_secret", "") or conn.get("client_secret", "")
        self.refresh_token = conn.get("refresh_token", "")
        self._access_token: str  = conn.get("access_token") or ""
        self._token_expiry: float = 0
        self.channel_id    = conn.get("youtube_channel_id", "") or ""
        self.api_key       = api_key
        self.workspace     = workspace

        # True when OAuth2 credentials are present (Analytics API needs this)
        self.has_oauth: bool = bool(
            self.refresh_token and self.client_id and self.client_secret
        )

    # ── OAuth2 token management ─────────────────────────────

    def _get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token
        return self._refresh_access_token()

    def _refresh_access_token(self) -> str:
        """Exchange refresh_token for a new access token."""
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

    # ── Low-level API helpers ───────────────────────────────

    def _data_get(self, endpoint: str, params: dict) -> dict:
        """
        GET to YouTube Data API v3.
        Prefers OAuth2 Bearer token; falls back to API key for public data.
        """
        if self.has_oauth:
            token = self._get_access_token()
            r = requests.get(
                f"{_DATA_BASE}/{endpoint}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=20,
            )
        elif self.api_key:
            r = requests.get(
                f"{_DATA_BASE}/{endpoint}",
                params={**params, "key": self.api_key},
                timeout=20,
            )
        else:
            raise ValueError("No OAuth2 credentials or API key configured")
        r.raise_for_status()
        return r.json()

    def _analytics_get(self, params: dict) -> dict:
        """GET to YouTube Analytics API v2 — requires OAuth2."""
        if not self.has_oauth:
            raise PermissionError("YouTube Analytics requires OAuth2 credentials")
        token = self._get_access_token()
        full_params = {"ids": "channel==MINE", **params}
        r = requests.get(
            _ANALYTICS_BASE,
            headers={"Authorization": f"Bearer {token}"},
            params=full_params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    # ── Channel ─────────────────────────────────────────────

    def validate_connection(self) -> bool:
        """Test connection by fetching channel info."""
        try:
            self.get_channel_info()
            return True
        except Exception:
            return False

    def get_channel_info(self) -> dict:
        """
        Return basic channel snippet + statistics.
        Works with OAuth2 (mine=true) OR API key + channel_id (id=UC...).
        """
        params: dict = {"part": "snippet,statistics"}
        if self.has_oauth:
            params["mine"] = "true"
        elif self.channel_id:
            params["id"] = self.channel_id
        else:
            raise ValueError("Need OAuth2 or a channel_id to fetch channel info")

        data  = self._data_get("channels", params)
        items = data.get("items", [])
        if not items:
            raise ValueError("No YouTube channel found for these credentials")
        item  = items[0]
        self.channel_id = item["id"]   # update in case it wasn't set
        stats = item.get("statistics", {})
        snip  = item.get("snippet", {})
        return {
            "channel_id":        item["id"],
            "title":             snip.get("title", ""),
            "description":       snip.get("description", ""),
            "thumbnail":         (snip.get("thumbnails", {}).get("default", {}) or {}).get("url"),
            "subscriber_count":  int(stats.get("subscriberCount", 0)),
            "view_count":        int(stats.get("viewCount", 0)),
            "video_count":       int(stats.get("videoCount", 0)),
        }

    # ── Channel-level Analytics (OAuth2 required) ────────────

    def fetch_channel_stats(self, since: str, until: str) -> list[dict]:
        """
        Fetch daily channel-level stats from Analytics API.
        Raises PermissionError if OAuth2 not available.
        CTR comes as fraction (0.045) → multiplied ×100 before return.
        """
        data = self._analytics_get({
            "startDate": since,
            "endDate":   until,
            "metrics": (
                "views,estimatedMinutesWatched,"
                "subscribersGained,subscribersLost,"
                "impressions,impressionsClickThroughRate"
            ),
            "dimensions": "day",
            "sort":       "day",
        })
        rows   = data.get("rows", []) or []
        result = []
        for row in rows:
            result.append({
                "date":                row[0],
                "views":               int(row[1]),
                "watch_time_minutes":  int(row[2]),
                "subscribers_gained":  int(row[3]),
                "subscribers_lost":    int(row[4]),
                "impressions":         int(row[5]),
                "impression_ctr":      round(float(row[6]) * 100, 4),
            })
        return result

    # ── Video catalog (public — works with API key) ──────────

    @staticmethod
    def _parse_iso_duration(duration: str) -> int:
        """Parse ISO 8601 duration PT4M13S → seconds."""
        if not duration:
            return 0
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not m:
            return 0
        h  = int(m.group(1) or 0)
        mi = int(m.group(2) or 0)
        s  = int(m.group(3) or 0)
        return h * 3600 + mi * 60 + s

    def fetch_video_list(self, limit: int = 50) -> list[dict]:
        """
        Return the channel's most recent videos.
        Works with API key (public data). No OAuth2 needed.
        Two-step: search.list → videos.list.
        """
        if not self.channel_id:
            raise ValueError("channel_id required for fetch_video_list")

        # Step 1: get video IDs via search.list
        search_data = self._data_get("search", {
            "part":       "id",
            "channelId":  self.channel_id,
            "type":       "video",
            "order":      "date",
            "maxResults": min(limit, 50),
        })
        items     = search_data.get("items", [])
        video_ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
        if not video_ids:
            return []

        # Step 2: get full metadata via videos.list
        vid_data = self._data_get("videos", {
            "part":       "snippet,statistics,contentDetails",
            "id":         ",".join(video_ids),
            "maxResults": 50,
        })
        result = []
        for v in vid_data.get("items", []):
            snip    = v.get("snippet", {})
            stats   = v.get("statistics", {})
            content = v.get("contentDetails", {})
            thumbs  = snip.get("thumbnails", {})
            thumb   = (
                (thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {})
                .get("url")
            )
            title       = snip.get("title", "")
            description = snip.get("description", "")
            tags        = snip.get("tags", [])
            dur_secs    = self._parse_iso_duration(content.get("duration", ""))

            # A true YouTube Short: ≤60s AND has #shorts in title/description/tags
            shorts_corpus = (title + " " + description + " " + " ".join(tags or [])).lower()
            is_short = dur_secs <= 60 and "#short" in shorts_corpus

            result.append({
                "video_id":         v["id"],
                "title":            title,
                "description":      description,
                "tags":             tags,
                "thumbnail_url":    thumb,
                "published_at":     snip.get("publishedAt"),
                "duration_seconds": dur_secs,
                "is_short":         is_short,
                "view_count":       int(stats.get("viewCount", 0)),
                "like_count":       int(stats.get("likeCount", 0)),
                "comment_count":    int(stats.get("commentCount", 0)),
            })
        return result

    # ── Per-video Analytics (OAuth2 required) ────────────────

    def fetch_video_analytics(self, video_id: str, since: str, until: str) -> list[dict]:
        """
        Fetch daily per-video stats from Analytics API.
        NOTE: impressions/impressionsClickThroughRate are channel-level only —
        they cannot be filtered by video==ID (returns 400). Excluded here.
        Raises PermissionError if OAuth2 not available.
        """
        data = self._analytics_get({
            "startDate": since,
            "endDate":   until,
            "metrics": (
                "views,estimatedMinutesWatched,"
                "averageViewDuration,averageViewPercentage,"
                "likes,shares,subscribersGained"
            ),
            "dimensions": "day",
            "filters":    f"video=={video_id}",
            "sort":       "day",
        })
        rows   = data.get("rows", []) or []
        result = []
        for row in rows:
            result.append({
                "date":                      row[0],
                "views":                     int(row[1]),
                "watch_time_minutes":        int(row[2]),
                "avg_view_duration_seconds": int(row[3]),
                "avg_view_percentage":       round(float(row[4]), 3),
                "impressions":               0,     # not available per-video
                "impression_ctr":            0.0,   # not available per-video
                "likes":                     int(row[5]),
                "shares":                    int(row[6]),
                "subscribers_gained":        int(row[7]),
            })
        return result

    def fetch_audience_retention(self, video_id: str) -> list[dict]:
        """
        Return audience retention curve for a specific video.
        Uses elapsedVideoTimeRatio + audienceWatchRatio — OAuth2 required.
        Returns ~100 points: [{elapsed_ratio: 0-1, watch_pct: 0-100}].
        """
        data = self._analytics_get({
            "startDate":  "2020-01-01",
            "endDate":    datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "metrics":    "audienceWatchRatio",
            "dimensions": "elapsedVideoTimeRatio",
            "filters":    f"video=={video_id}",
            "sort":       "elapsedVideoTimeRatio",
        })
        rows = data.get("rows", []) or []
        return [
            {
                "elapsed_ratio": round(float(r[0]), 3),
                "watch_pct":     round(float(r[1]) * 100, 1),
            }
            for r in rows
        ]

    def fetch_top_videos(self, since: str, until: str, limit: int = 20) -> list[dict]:
        """Return top videos by views (Analytics — OAuth2 required)."""
        data = self._analytics_get({
            "startDate":  since,
            "endDate":    until,
            "metrics":    "views,estimatedMinutesWatched,averageViewPercentage",
            "dimensions": "video",
            "sort":       "-views",
            "maxResults": limit,
        })
        rows = data.get("rows", []) or []
        return [
            {
                "video_id":            r[0],
                "views":               int(r[1]),
                "watch_time_minutes":  int(r[2]),
                "avg_view_percentage": round(float(r[3]), 3),
            }
            for r in rows
        ]

    def fetch_traffic_sources(self, since: str, until: str) -> list[dict]:
        """Return traffic source breakdown (Analytics — OAuth2 required)."""
        data = self._analytics_get({
            "startDate":  since,
            "endDate":    until,
            "metrics":    "views,estimatedMinutesWatched",
            "dimensions": "insightTrafficSourceType",
            "sort":       "-views",
        })
        rows = data.get("rows", []) or []
        return [
            {"source": r[0], "views": int(r[1]), "watch_time_minutes": int(r[2])}
            for r in rows
        ]

    # ── Video metadata update (OAuth2 required) ──────────────

    def update_video_metadata(
        self,
        video_id:    str,
        title:       str        = None,
        description: str        = None,
        tags:        list[str]  = None,
    ) -> bool:
        """Update video title / description / tags via Data API PUT."""
        token  = self._get_access_token()
        body: dict = {"id": video_id, "snippet": {}}
        if title       is not None: body["snippet"]["title"]       = title
        if description is not None: body["snippet"]["description"] = description
        if tags        is not None: body["snippet"]["tags"]        = tags

        r = requests.put(
            f"{_DATA_BASE}/videos",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"part": "snippet"},
            json=body,
            timeout=20,
        )
        return r.ok

    # ── Comments ─────────────────────────────────────────────

    def fetch_video_comments(
        self,
        video_id: str,
        max_results: int = 100,
        raise_on_error: bool = False,
    ) -> list[dict]:
        """
        Fetch top-level comment threads for a video.
        Works with API key (public videos) or OAuth2.
        Returns list of dicts with: comment_id, author_name, comment_text,
        like_count, reply_count, published_at.
        If raise_on_error=False (default), silently returns [] on any error.
        If raise_on_error=True, raises the original exception so callers can
        detect and report why comments could not be fetched.
        """
        comments: list[dict] = []
        params: dict = {
            "part":        "snippet",
            "videoId":     video_id,
            "maxResults":  min(max_results, 100),
            "order":       "relevance",
            "textFormat":  "plainText",
        }
        while True:
            try:
                # commentThreads works with API key for public videos.
                # OAuth may lack youtube.force-ssl scope → 403.
                # Prefer API key path regardless of whether OAuth is present.
                if self.api_key:
                    r = requests.get(
                        f"{_DATA_BASE}/commentThreads",
                        params={**params, "key": self.api_key},
                        timeout=20,
                    )
                    r.raise_for_status()
                    data = r.json()
                else:
                    data = self._data_get("commentThreads", params)
            except Exception as e:
                if raise_on_error:
                    raise
                break
            for item in data.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "comment_id":  item["id"],
                    "author_name": top.get("authorDisplayName", "Anonymous"),
                    "comment_text": top.get("textDisplay", ""),
                    "like_count":  int(top.get("likeCount", 0)),
                    "reply_count": int(item["snippet"].get("totalReplyCount", 0)),
                    "published_at": top.get("publishedAt"),
                })
                if len(comments) >= max_results:
                    return comments
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            params["pageToken"] = page_token
        return comments
