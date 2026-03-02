"""
services/agent_swarm/connectors/yt_competitor.py

Stateless YouTube Data API v3 client for competitor intelligence.
Uses only the public Data API — no OAuth required.
api_key is passed explicitly so this module stays pure and testable.
"""

import re
import time
from typing import Optional

import requests

_DATA_BASE = "https://www.googleapis.com/youtube/v3"
_SEARCH_SLEEP = 0.30  # 300 ms between search.list calls to avoid quota spikes


# ── Helpers ───────────────────────────────────────────────────────────────────

def iso8601_to_seconds(dur: str) -> int:
    """Parse ISO 8601 duration string → total seconds.

    Examples: "PT4M13S" → 253, "PT1H2M30S" → 3750, "PT45S" → 45
    Returns 0 on any parsing failure.
    """
    if not dur:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur or "")
    if not m:
        return 0
    hours   = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class QuotaExceededError(Exception):
    """Raised when the YouTube Data API v3 daily quota is exhausted."""


def _get(endpoint: str, params: dict, api_key: str, timeout: int = 25) -> dict:
    """GET a YouTube Data API v3 endpoint. Raises on HTTP errors."""
    r = requests.get(
        f"{_DATA_BASE}/{endpoint}",
        params={**params, "key": api_key},
        timeout=timeout,
    )
    # Detect quota-exceeded before raise_for_status (it just says 403)
    if r.status_code == 403:
        try:
            body = r.json()
            errors = body.get("error", {}).get("errors", [])
            if any(e.get("reason") == "quotaExceeded" for e in errors):
                raise QuotaExceededError("YouTube API daily quota exceeded — please try again after midnight Pacific Time.")
        except QuotaExceededError:
            raise
        except Exception:
            pass
    r.raise_for_status()
    return r.json()


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_channel_id_from_handle(handle: str, api_key: str) -> Optional[str]:
    """Convert a YouTube handle / URL / channel-id to a channel_id string.

    Strategy (in order):
      1. Already a UC... channel ID (24-char) → return as-is.
      2. Strip known URL prefixes (@, /c/, /user/, /channel/).
      3. Try the ``channels?forHandle=`` endpoint (works for @-handles since 2023).
      4. Fall back to ``search.list?type=channel&q=handle``.
    Returns None if all strategies fail.
    """
    handle = (handle or "").strip()

    # Already a channel ID
    if handle.startswith("UC") and len(handle) == 24:
        return handle

    # Strip URL boilerplate — ordered most-specific first
    for prefix in (
        "https://www.youtube.com/@",
        "https://youtube.com/@",
        "http://www.youtube.com/@",
        "https://www.youtube.com/c/",
        "https://www.youtube.com/user/",
        "https://www.youtube.com/channel/",
        "https://www.youtube.com/",   # bare custom URL: youtube.com/UltrahumanOfficial
        "https://youtube.com/",
        "http://www.youtube.com/",
        "http://youtube.com/",
        "@",
    ):
        if handle.lower().startswith(prefix.lower()):
            handle = handle[len(prefix):]
            break

    # Remove trailing slashes and query strings
    handle = handle.split("?")[0].rstrip("/")

    # 3. forHandle API (most reliable for @ handles)
    try:
        data = _get("channels", {"part": "id", "forHandle": handle}, api_key)
        items = data.get("items", [])
        if items:
            return items[0]["id"]
    except Exception:
        pass

    # 4. Fallback search
    try:
        time.sleep(_SEARCH_SLEEP)
        data = _get("search", {
            "part": "snippet",
            "type": "channel",
            "q": handle,
            "maxResults": 1,
        }, api_key)
        items = data.get("items", [])
        if items:
            snip = items[0].get("snippet", {})
            return snip.get("channelId") or (items[0].get("id") or {}).get("channelId")
    except Exception:
        pass

    return None


def get_channel_meta(channel_id: str, api_key: str) -> dict:
    """Return basic metadata for a channel.

    Returns dict with keys: channel_id, title, description, country,
    handle (customUrl), subscriber_count, video_count.
    Returns minimal dict on failure.
    """
    try:
        data = _get("channels", {
            "part": "snippet,statistics",
            "id": channel_id,
        }, api_key)
    except Exception as e:
        print(f"[yt_competitor] get_channel_meta error for {channel_id}: {e}")
        return {"channel_id": channel_id, "title": "Unknown"}

    items = data.get("items", [])
    if not items:
        return {"channel_id": channel_id, "title": "Unknown"}

    item  = items[0]
    snip  = item.get("snippet", {})
    stats = item.get("statistics", {})
    return {
        "channel_id":       item["id"],
        "title":            snip.get("title", ""),
        "description":      (snip.get("description", "") or "")[:500],
        "country":          snip.get("country", ""),
        "handle":           snip.get("customUrl", ""),
        "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
        "video_count":      int(stats.get("videoCount", 0) or 0),
    }


def list_recent_video_ids(channel_id: str, max_n: int, api_key: str) -> list[str]:
    """Return up to *max_n* recent video IDs for a channel (ordered by date DESC).

    Strategy (two-step fallback):
      1. ``playlistItems.list`` on the uploads playlist (costs 1 unit, fast).
         Uploads playlist ID = "UU" + channel_id[2:].
      2. If 403 / empty: fall back to ``search.list(channelId, type=video, order=date)``
         (costs 100 units, slower, but works for more channels).
    Returns empty list if both fail.
    """
    # Strategy 1: uploads playlist (cheapest)
    playlist_id = "UU" + channel_id[2:]
    ids: list[str] = []
    page_token: Optional[str] = None
    playlist_worked = False

    while len(ids) < max_n:
        batch = min(50, max_n - len(ids))
        params: dict = {
            "part":       "contentDetails",
            "playlistId": playlist_id,
            "maxResults": batch,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            data = _get("playlistItems", params, api_key)
            playlist_worked = True
        except Exception:
            # 403 or other error — fall through to Strategy 2
            break

        for item in data.get("items", []):
            vid_id = (item.get("contentDetails") or {}).get("videoId")
            if vid_id:
                ids.append(vid_id)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    if ids or playlist_worked:
        return ids[:max_n]

    # Strategy 2: search.list fallback (more expensive but broader compatibility)
    time.sleep(0.5)  # small back-off before retry
    page_token = None
    while len(ids) < max_n:
        batch = min(50, max_n - len(ids))
        params = {
            "part":       "id",
            "channelId":  channel_id,
            "type":       "video",
            "order":      "date",
            "maxResults": batch,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            data = _get("search", params, api_key)
        except Exception as e:
            print(f"[yt_competitor] list_recent_video_ids fallback error: {e}")
            break

        for item in data.get("items", []):
            vid_id = (item.get("id") or {}).get("videoId")
            if vid_id:
                ids.append(vid_id)

        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(_SEARCH_SLEEP)

    return ids[:max_n]


def get_videos_details(video_ids: list[str], api_key: str) -> list[dict]:
    """Fetch full metadata for a list of video IDs.

    Internally batches in chunks of 50 (API limit).
    Returns list of normalized dicts with keys:
      video_id, channel_id, title, description, thumbnail_url,
      published_at (ISO 8601 str), duration_seconds (int),
      views, likes, comments (all int).
    """
    results: list[dict] = []

    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        try:
            data = _get("videos", {
                "part": "snippet,statistics,contentDetails",
                "id":   ",".join(chunk),
            }, api_key)
        except Exception as e:
            print(f"[yt_competitor] get_videos_details chunk error: {e}")
            continue

        for v in data.get("items", []):
            snip    = v.get("snippet", {})
            stats   = v.get("statistics", {})
            content = v.get("contentDetails", {})

            # Best available thumbnail
            thumbs   = snip.get("thumbnails", {})
            thumb_url = None
            for quality in ("maxres", "standard", "high", "medium", "default"):
                if quality in thumbs:
                    thumb_url = thumbs[quality].get("url")
                    break

            results.append({
                "video_id":         v["id"],
                "channel_id":       snip.get("channelId", ""),
                "title":            snip.get("title", ""),
                "description":      snip.get("description", ""),
                "thumbnail_url":    thumb_url,
                "published_at":     snip.get("publishedAt"),   # ISO 8601 str
                "duration_seconds": iso8601_to_seconds(content.get("duration", "")),
                "views":            int(stats.get("viewCount", 0) or 0),
                "likes":            int(stats.get("likeCount", 0) or 0),
                "comments":         int(stats.get("commentCount", 0) or 0),
            })

    return results


def search_channels_by_query(q: str, max_results: int, api_key: str) -> list[dict]:
    """Search YouTube channels by a text query.

    Returns list of {channel_id, title, description}.
    Sleeps 300 ms before call to respect quota budget.
    """
    time.sleep(_SEARCH_SLEEP)
    try:
        data = _get("search", {
            "part":       "snippet",
            "type":       "channel",
            "q":          q,
            "maxResults": min(max_results, 50),
        }, api_key)
    except QuotaExceededError:
        raise  # propagate so discover_competitors can show a clear error
    except Exception as e:
        print(f"[yt_competitor] search_channels error for '{q}': {e}")
        return []

    results = []
    for item in data.get("items", []):
        snip = item.get("snippet", {})
        ch_id = snip.get("channelId")
        if ch_id:
            results.append({
                "channel_id":  ch_id,
                "title":       snip.get("title", ""),
                "description": snip.get("description", ""),
            })
    return results


def search_videos_by_query(q: str, max_results: int, api_key: str) -> list[dict]:
    """Search YouTube videos by a text query; collect their channel_ids.

    Returns list of {video_id, channel_id, title}.
    Sleeps 300 ms before call.
    """
    time.sleep(_SEARCH_SLEEP)
    try:
        data = _get("search", {
            "part":       "snippet",
            "type":       "video",
            "q":          q,
            "maxResults": min(max_results, 50),
        }, api_key)
    except QuotaExceededError:
        raise  # propagate so discover_competitors can show a clear error
    except Exception as e:
        print(f"[yt_competitor] search_videos error for '{q}': {e}")
        return []

    results = []
    for item in data.get("items", []):
        vid_id = (item.get("id") or {}).get("videoId")
        if vid_id:
            snip = item.get("snippet", {})
            results.append({
                "video_id":   vid_id,
                "channel_id": snip.get("channelId", ""),
                "title":      snip.get("title", ""),
            })
    return results
