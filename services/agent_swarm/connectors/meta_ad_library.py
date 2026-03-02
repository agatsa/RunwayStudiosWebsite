"""Meta Ad Library connector

Fetches competitor ads from the public Meta Ad Library API (ads_archive).
Uses a single platform-level token (META_AD_LIBRARY_TOKEN env var) set by
Runway Studios — no per-client Meta connection needed since Ad Library is
public data.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.facebook.com/v21.0"
_FIELDS = (
    "id,ad_creative_bodies,ad_snapshot_url,page_name,page_id,"
    "ad_delivery_start_time,ad_creative_link_titles,"
    "publisher_platforms,ad_creative_media_type"
)


# ── Platform token (Runway Studios-level, not per-client) ────────────────────

def _get_platform_token() -> Optional[str]:
    """Return the platform-wide Ad Library token from env var."""
    return os.environ.get("META_AD_LIBRARY_TOKEN") or None


def _normalize_name(raw: str) -> str:
    """Extract handle from a Facebook URL, or return the raw brand name."""
    raw = raw.strip()
    if raw.startswith("http"):
        try:
            from urllib.parse import urlparse
            parsed = urlparse(raw)
            handle = parsed.path.strip("/").split("/")[0]
            if handle:
                return handle
        except Exception:
            pass
    return raw


def _get_competitor_names(workspace_id: str, conn) -> list:
    """Return deduplicated brand names from both manual pages and YT competitor channels."""
    names: list = []
    seen: set = set()

    # 1. Manually added pages (Settings → Competitor Intel) — highest priority
    with conn.cursor() as cur:
        cur.execute(
            "SELECT page_name FROM meta_competitor_pages "
            "WHERE workspace_id=%s ORDER BY added_at ASC LIMIT 15",
            (workspace_id,),
        )
        for (name,) in cur.fetchall():
            norm = _normalize_name(name) if name else ""
            if norm and norm.lower() not in seen:
                names.append(norm)
                seen.add(norm.lower())

    # 2. YouTube competitor discovery — auto-populated brand names
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT channel_title FROM yt_competitor_channels "
            "WHERE workspace_id=%s AND channel_title IS NOT NULL "
            "ORDER BY channel_title LIMIT 10",
            (workspace_id,),
        )
        for (name,) in cur.fetchall():
            norm = _normalize_name(name) if name else ""
            if norm and norm.lower() not in seen:
                names.append(norm)
                seen.add(norm.lower())

    return names[:15]  # cap total


# ── API fetch ────────────────────────────────────────────────────────────────

def fetch_ads_for_term(search_term: str, access_token: str, countries: list = None) -> tuple:
    """Call ads_archive for one search term.
    Returns (ads_list, error_message_or_None).
    Searches IN + US + GB so global-only advertisers are included.
    """
    if countries is None:
        # Cast a wide net — ads targeted to any of these countries
        countries = ["IN", "US", "GB", "AU", "SG", "AE"]

    params = {
        "search_terms": search_term,
        "ad_reached_countries": json.dumps(countries),
        "ad_active_status": "ACTIVE",
        "ad_type": "ALL",
        "fields": _FIELDS,
        "limit": 50,
        "access_token": access_token,
    }

    ads = []
    url = f"{_GRAPH_BASE}/ads_archive"
    api_error = None

    while url and len(ads) < 200:
        resp = requests.get(url, params=params, timeout=30)

        if resp.status_code in (400, 403):
            try:
                err = resp.json().get("error", {})
                api_error = err.get("message") or resp.text[:300]
            except Exception:
                api_error = resp.text[:300]
            logger.warning("[meta_ad_library] %s for '%s': %s", resp.status_code, search_term, api_error)
            break

        resp.raise_for_status()
        data = resp.json()
        ads.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        params = {}

    return ads, api_error


# ── DB write ─────────────────────────────────────────────────────────────────

def _upsert_ads(workspace_id: str, ads: list, conn) -> int:
    """Upsert raw ad dicts into meta_competitor_ads. Returns count."""
    if not ads:
        return 0

    count = 0
    with conn.cursor() as cur:
        for ad in ads:
            ad_id = str(ad.get("id") or "")
            if not ad_id:
                continue

            bodies = ad.get("ad_creative_bodies") or []
            ad_copy = bodies[0] if bodies else None

            titles = ad.get("ad_creative_link_titles") or []
            headline = titles[0] if titles else None

            start_raw = ad.get("ad_delivery_start_time")
            delivery_start = None
            if start_raw:
                try:
                    delivery_start = datetime.fromisoformat(
                        start_raw.replace("Z", "+00:00")
                    ).date()
                except Exception:
                    pass

            platforms = json.dumps(ad.get("publisher_platforms") or [])
            page_id   = str(ad.get("page_id") or "")
            page_name = ad.get("page_name") or ""
            snapshot  = ad.get("ad_snapshot_url") or ""
            media     = ad.get("ad_creative_media_type") or ""

            cur.execute(
                """
                INSERT INTO meta_competitor_ads
                  (workspace_id, competitor_page_id, competitor_page_name, ad_id,
                   ad_copy, headline, snapshot_url, media_type, platforms,
                   delivery_start_date, last_fetched_at, is_active, raw_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),TRUE,%s)
                ON CONFLICT (workspace_id, ad_id) DO UPDATE SET
                  ad_copy        = EXCLUDED.ad_copy,
                  headline       = EXCLUDED.headline,
                  snapshot_url   = EXCLUDED.snapshot_url,
                  last_fetched_at = NOW(),
                  is_active      = TRUE,
                  raw_json       = EXCLUDED.raw_json
                """,
                (
                    workspace_id, page_id or page_name, page_name, ad_id,
                    ad_copy, headline, snapshot, media, platforms,
                    delivery_start, json.dumps(ad),
                ),
            )
            count += 1

    conn.commit()
    return count


# ── Public API ───────────────────────────────────────────────────────────────

def sync_workspace_ads(workspace_id: str, conn) -> dict:
    """Sync competitor ads for a workspace. Called by cron + manual trigger."""
    token = _get_platform_token()
    if not token:
        return {
            "status": "no_platform_token",
            "message": "META_AD_LIBRARY_TOKEN not configured — contact Runway Studios admin",
        }

    competitors = _get_competitor_names(workspace_id, conn)
    if not competitors:
        return {
            "status": "no_competitors",
            "message": "Run YouTube Competitor Discovery first to populate competitor names",
        }

    results = []
    api_errors = []
    for name in competitors:
        try:
            ads, err = fetch_ads_for_term(name, token)
            inserted = _upsert_ads(workspace_id, ads, conn)
            row = {"name": name, "ads_found": len(ads), "upserted": inserted}
            if err:
                row["api_error"] = err
                api_errors.append(err)
            results.append(row)
            logger.info("[meta_ad_library] %s → %d ads", name, len(ads))
        except Exception as e:
            logger.error("[meta_ad_library] failed for '%s': %s", name, e)
            results.append({"name": name, "error": str(e)})

    response = {"status": "ok", "synced": results}
    # If ALL searches returned API errors (likely identity verification needed)
    if api_errors and len(api_errors) == len(competitors):
        response["api_warning"] = api_errors[0]
    return response


def get_competitor_ads(workspace_id: str, conn) -> dict:
    """Return all stored competitor ads grouped by page name."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT competitor_page_name, ad_id, ad_copy, headline,
                   snapshot_url, media_type, platforms,
                   delivery_start_date, last_fetched_at,
                   CASE WHEN delivery_start_date IS NOT NULL
                        THEN (CURRENT_DATE - delivery_start_date)
                        ELSE NULL END AS running_days
            FROM meta_competitor_ads
            WHERE workspace_id=%s AND is_active=TRUE
            ORDER BY competitor_page_name, delivery_start_date ASC NULLS LAST
            """,
            (workspace_id,),
        )
        rows = cur.fetchall()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(last_fetched_at) FROM meta_competitor_ads WHERE workspace_id=%s",
            (workspace_id,),
        )
        ts_row = cur.fetchone()
    last_synced = ts_row[0].isoformat() if (ts_row and ts_row[0]) else None

    pages: dict = {}
    for r in rows:
        pname = r[0]
        running_days = int(r[9]) if r[9] is not None else None
        ad = {
            "ad_id":               r[1],
            "ad_copy":             r[2],
            "headline":            r[3],
            "snapshot_url":        r[4],
            "media_type":          r[5],
            "platforms":           json.loads(r[6]) if r[6] else [],
            "delivery_start_date": r[7].isoformat() if r[7] else None,
            "running_days":        running_days,
            "is_proven_winner":    (running_days is not None and running_days >= 90),
        }
        pages.setdefault(pname, []).append(ad)

    # proven winners first, then longest-running
    for pname in pages:
        pages[pname].sort(
            key=lambda a: (not a["is_proven_winner"], -(a["running_days"] or 0))
        )

    return {
        "has_data":    bool(pages),
        "last_synced": last_synced,
        "competitors": [
            {
                "page_name":       k,
                "ads":             v,
                "ad_count":        len(v),
                "proven_winners":  sum(1 for a in v if a["is_proven_winner"]),
            }
            for k, v in pages.items()
        ],
    }
