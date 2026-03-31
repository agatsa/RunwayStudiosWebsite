"""
services/agent_swarm/core/onboard_chain.py

Onboarding Chain — the engine that powers the visitor-to-customer funnel.

Flow:
  1. Visitor enters any URL (YouTube channel / product page / website / app)
  2. URL type detected (youtube | website)
  3. Free preview runs:
       website → Brand Intel Phase 1 (competitor discovery, ~30s)
       youtube → YouTube channel detection via Data API (instant)
  4. Preview results shown → visitor pays ₹499 flat
  5. Post-payment chain starts automatically:
       website → Brand Intel Phase 2 → LP Audit → Growth OS
       youtube → YT Competitor Discovery (Phase 1) → YT Analysis (Phase 2) → Growth Recipe
  6. Progress logged to onboard_jobs.chain_log (JSONB array, polled every 2s)

DB table: onboard_jobs (see SQL at bottom of this file)

BACKGROUND TASK RULE — same as app.py:
  def task():   ← thread pool (non-blocking ✅)
  async def task(): ← EVENT LOOP (blocks ALL requests ❌)
  All chain runners are sync `def`.
"""

from __future__ import annotations

import json
import re
import uuid
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

# ── URL type detection ─────────────────────────────────────────────────────────

_YT_PATTERNS = [
    r"youtube\.com/@",
    r"youtube\.com/channel/",
    r"youtube\.com/c/",
    r"youtube\.com/user/",
    r"youtu\.be/",
]

def detect_url_type(url: str) -> str:
    """Return 'youtube' or 'website'."""
    if not url:
        return "website"
    url_lower = url.lower().strip()
    for pat in _YT_PATTERNS:
        if re.search(pat, url_lower):
            return "youtube"
    return "website"


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _log(conn, job_id: str, msg: str, type_: str = "info", source: str = "chain"):
    """Append a log entry to onboard_jobs.chain_log (JSONB array)."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "msg": msg,
        "type": type_,
        "source": source,
    }
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE onboard_jobs
                      SET chain_log  = chain_log || %s::jsonb,
                          updated_at = NOW()
                    WHERE id = %s::uuid""",
                (json.dumps([entry]), job_id),
            )
        conn.commit()
    except Exception as e:
        print(f"[onboard_chain] _log failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def _set_status(conn, job_id: str, status: str, extra: dict = None):
    """Update onboard_jobs.status (and optional extra columns)."""
    try:
        sets = ["status = %s", "updated_at = NOW()"]
        vals = [status]
        if extra:
            for col, val in extra.items():
                sets.append(f"{col} = %s")
                vals.append(val)
        vals.append(job_id)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE onboard_jobs SET {', '.join(sets)} WHERE id = %s::uuid",
                vals,
            )
        conn.commit()
    except Exception as e:
        print(f"[onboard_chain] _set_status failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


# ── Free Preview ───────────────────────────────────────────────────────────────

async def run_free_preview(job_id: str, workspace_id: str, url: str, url_type: str, conn):
    """
    Async. Called from background via asyncio.run().
    website → Brand Intel Phase 1 (competitor names, topic space).
    youtube → YouTube channel detection (name, subs, top-3 videos) via Data API.
    """
    _set_status(conn, job_id, "previewing")
    _log(conn, job_id, "═══════════════════════════════════════", "separator")
    _log(conn, job_id, "  ARIA — Free Preview Analysis", "header")
    _log(conn, job_id, "═══════════════════════════════════════", "separator")

    if url_type == "youtube":
        await _preview_youtube(job_id, workspace_id, url, conn)
    else:
        await _preview_website(job_id, workspace_id, url, conn)


async def _preview_youtube(job_id: str, workspace_id: str, url: str, conn):
    """Detect YouTube channel from URL, fetch basic stats via Data API."""
    from services.agent_swarm.config import YOUTUBE_API_KEY
    import httpx

    _log(conn, job_id, f"Detecting YouTube channel from URL: {url}", "info", "youtube")

    # Extract channel handle / ID
    channel_ref = ""
    m = re.search(r"youtube\.com/@([^/?&]+)", url)
    if m:
        channel_ref = f"@{m.group(1)}"
    else:
        m2 = re.search(r"youtube\.com/channel/([^/?&]+)", url)
        if m2:
            channel_ref = m2.group(1)
        else:
            m3 = re.search(r"youtube\.com/(?:c|user)/([^/?&]+)", url)
            if m3:
                channel_ref = m3.group(1)

    if not channel_ref:
        _log(conn, job_id, "⚠ Could not extract channel handle from URL. Please check the URL.", "missing", "youtube")
        _set_status(conn, job_id, "preview_ready", {
            "preview_data": json.dumps({"url_type": "youtube", "error": "Could not parse channel URL"})
        })
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if channel_ref.startswith("@"):
                r = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={
                        "part": "snippet,statistics",
                        "forHandle": channel_ref[1:],
                        "key": YOUTUBE_API_KEY,
                        "maxResults": 1,
                    },
                )
            else:
                r = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={
                        "part": "snippet,statistics",
                        "id": channel_ref,
                        "key": YOUTUBE_API_KEY,
                        "maxResults": 1,
                    },
                )
            data = r.json()
        items = data.get("items", [])
        if not items:
            _log(conn, job_id, "⚠ YouTube channel not found. Please check your URL.", "missing", "youtube")
            _set_status(conn, job_id, "preview_ready", {
                "preview_data": json.dumps({"url_type": "youtube", "error": "Channel not found"})
            })
            return

        ch = items[0]
        snippet = ch.get("snippet", {})
        stats = ch.get("statistics", {})
        channel_id = ch.get("id", "")
        title = snippet.get("title", "Unknown Channel")
        description = snippet.get("description", "")[:300]
        subs = int(stats.get("subscriberCount", 0))
        views = int(stats.get("viewCount", 0))
        videos = int(stats.get("videoCount", 0))
        thumbnail = snippet.get("thumbnails", {}).get("medium", {}).get("url", "")

        _log(conn, job_id, f"✓ Found channel: {title}", "success", "youtube")
        _log(conn, job_id, f"  Subscribers: {subs:,}  |  Views: {views:,}  |  Videos: {videos}", "info", "youtube")

        # Fetch top 3 recent videos
        top_videos = []
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r2 = await client.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={
                        "part": "snippet",
                        "channelId": channel_id,
                        "order": "viewCount",
                        "type": "video",
                        "maxResults": 3,
                        "key": YOUTUBE_API_KEY,
                    },
                )
                vdata = r2.json()
            for item in vdata.get("items", []):
                top_videos.append({
                    "title": item["snippet"].get("title", ""),
                    "video_id": item["id"].get("videoId", ""),
                })
                _log(conn, job_id, f"  Top video: {item['snippet'].get('title', '')[:60]}", "info", "youtube")
        except Exception:
            pass

        preview = {
            "url_type": "youtube",
            "channel_id": channel_id,
            "title": title,
            "description": description,
            "subscribers": subs,
            "views": views,
            "video_count": videos,
            "thumbnail": thumbnail,
            "top_videos": top_videos,
        }
        _log(conn, job_id, "─────────────────────────────────────────────────────────", "divider")
        _log(conn, job_id, "✓ Preview complete! Purchase to unlock full competitor analysis + Growth OS strategy.", "success", "chain")
        _set_status(conn, job_id, "preview_ready", {
            "preview_data": json.dumps(preview)
        })

    except Exception as e:
        print(f"[onboard_chain] _preview_youtube error: {e}")
        _log(conn, job_id, f"⚠ Preview error: {e}", "error", "youtube")
        _set_status(conn, job_id, "preview_ready", {
            "preview_data": json.dumps({"url_type": "youtube", "error": str(e)})
        })


async def _preview_website(job_id: str, workspace_id: str, url: str, conn):
    """Brand Intel Phase 1 — scrape brand + find competitors."""
    import importlib
    try:
        bi = importlib.import_module("services.agent_swarm.core.brand_intel")
        _log(conn, job_id, f"Scanning brand: {url}", "info", "brand_intel")

        # Create a brand_intel_jobs row
        bi_job_id = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO brand_intel_jobs
                       (id, workspace_id, brand_url, workspace_type, status, discovery_status)
                   VALUES (%s::uuid, %s::uuid, %s, 'd2c', 'pending', 'idle')""",
                (bi_job_id, workspace_id, url),
            )
        conn.commit()

        # Save bi_job_id on onboard_jobs
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE onboard_jobs SET bi_job_id=%s::uuid, updated_at=NOW() WHERE id=%s::uuid",
                (bi_job_id, job_id),
            )
        conn.commit()

        _log(conn, job_id, "Starting Brand Intelligence Phase 1 — competitor discovery…", "phase", "brand_intel")

        # Run Phase 1 in a fresh connection (brand_intel uses its own conn)
        from services.agent_swarm.db import get_conn as _get_conn
        with _get_conn() as bi_conn:
            await bi.run_discovery_phase(
                job_id=bi_job_id,
                workspace_id=workspace_id,
                brand_url=url,
                workspace_type="d2c",
                conn=bi_conn,
            )

        # Read back the discovered candidates
        from services.agent_swarm.db import get_conn as _get_conn2
        with _get_conn2() as rc:
            with rc.cursor() as cur:
                cur.execute(
                    "SELECT discovery_candidates, own_topic_space FROM brand_intel_jobs WHERE id=%s::uuid",
                    (bi_job_id,),
                )
                row = cur.fetchone()
        candidates = row[0] if row else []
        own_kws = row[1] if row else []

        if isinstance(candidates, str):
            candidates = json.loads(candidates)
        if isinstance(own_kws, str):
            own_kws = json.loads(own_kws)

        _log(conn, job_id, f"✓ Found {len(candidates)} competitors", "success", "brand_intel")
        for c in candidates[:5]:
            name = c.get("name") or c.get("domain", "unknown")
            conf = c.get("confidence_pct", 0)
            _log(conn, job_id, f"  • {name}  ({conf}% match)", "info", "brand_intel")

        preview = {
            "url_type": "website",
            "bi_job_id": bi_job_id,
            "competitors": candidates[:5],
            "own_keywords": own_kws[:10] if own_kws else [],
        }
        _log(conn, job_id, "─────────────────────────────────────────────────────────", "divider")
        _log(conn, job_id, "✓ Preview complete! Purchase to unlock full 9-layer analysis + LP Audit + Growth OS.", "success", "chain")
        _set_status(conn, job_id, "preview_ready", {
            "preview_data": json.dumps(preview)
        })

    except Exception as e:
        import traceback
        print(f"[onboard_chain] _preview_website error: {e}\n{traceback.format_exc()}")
        _log(conn, job_id, f"⚠ Preview error: {e}", "error", "brand_intel")
        _set_status(conn, job_id, "preview_ready", {
            "preview_data": json.dumps({"url_type": "website", "error": str(e)})
        })


# ── Post-Payment Chain ─────────────────────────────────────────────────────────

def run_paid_chain(job_id: str, workspace_id: str, url: str, url_type: str,
                   bi_job_id: str = None, directive: str = None):
    """
    Sync function — runs in thread pool via BackgroundTasks.
    Orchestrates the full post-payment analysis chain.
    website: Brand Intel P2 → LP Audit → Growth OS
    youtube: YT Discovery P1 → YT Analysis P2 + Growth Recipe
    """
    from services.agent_swarm.db import get_conn

    def _chain_log(msg, type_="info", source="chain"):
        try:
            with get_conn() as conn2:
                _log(conn2, job_id, msg, type_, source)
        except Exception as e:
            print(f"[onboard_chain] _chain_log error: {e}")

    def _chain_status(status, extra=None):
        try:
            with get_conn() as conn2:
                _set_status(conn2, job_id, status, extra)
        except Exception as e:
            print(f"[onboard_chain] _chain_status error: {e}")

    try:
        _chain_status("chain_running")
        _chain_log("═══════════════════════════════════════", "separator")
        _chain_log("  ARIA — Full Analysis Chain Starting", "header")
        _chain_log("═══════════════════════════════════════", "separator")

        if url_type == "youtube":
            _run_youtube_chain(job_id, workspace_id, url, _chain_log, _chain_status)
        else:
            _run_website_chain(job_id, workspace_id, url, bi_job_id, directive, _chain_log, _chain_status)

    except Exception as e:
        import traceback
        print(f"[onboard_chain] run_paid_chain error: {e}\n{traceback.format_exc()}")
        _chain_log(f"✕ Chain failed: {e}", "error")
        _chain_status("failed")


def _run_website_chain(job_id, workspace_id, url, bi_job_id, directive, log, set_status):
    """Website chain: Brand Intel P2 → LP Audit → Growth OS."""
    import asyncio
    from services.agent_swarm.db import get_conn
    import importlib

    # ── Step 1: Brand Intel Phase 2 ──────────────────────────────────────────
    # Runs in a thread with heartbeat logs + 8-min hard timeout so it never blocks forever.
    log("Phase 1/4 — Brand Intel: Full 9-layer competitor analysis", "phase", "brand_intel")
    log("─────────────────────────────────────────────────────────", "divider")

    if bi_job_id:
        try:
            import threading as _threading
            bi = importlib.import_module("services.agent_swarm.core.brand_intel")

            # Load and confirm candidates
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT discovery_candidates FROM brand_intel_jobs WHERE id=%s::uuid",
                        (bi_job_id,),
                    )
                    row = cur.fetchone()
                candidates = row[0] if row else []
                if isinstance(candidates, str):
                    candidates = json.loads(candidates)

            candidates = candidates[:5]
            _competitor_names = [c.get("name") or c.get("domain", "?") for c in candidates]

            # Mark all candidates as confirmed in DB
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE brand_intel_jobs SET discovery_status='confirmed', updated_at=NOW() WHERE id=%s::uuid",
                        (bi_job_id,),
                    )
                    cur.execute(
                        """UPDATE brand_intel_jobs
                           SET discovery_candidates = (
                               SELECT jsonb_agg(c || '{"confirmed":true}')
                               FROM jsonb_array_elements(discovery_candidates) AS c
                           ),
                           updated_at = NOW()
                           WHERE id = %s::uuid""",
                        (bi_job_id,),
                    )
                conn.commit()

            # Fetch meta token
            _meta_token = ""
            try:
                with get_conn() as _tc:
                    with _tc.cursor() as _tcur:
                        _tcur.execute(
                            "SELECT access_token FROM platform_connections "
                            "WHERE workspace_id=%s::uuid AND platform='meta' AND is_active LIMIT 1",
                            (workspace_id,),
                        )
                        _tr = _tcur.fetchone()
                        if _tr:
                            _meta_token = _tr[0] or ""
            except Exception:
                pass

            _bi_exc: list = [None]
            _bi_url, _bi_token = url, _meta_token

            def _run_bi_thread():
                try:
                    with get_conn() as _bi_conn:
                        asyncio.run(bi.run_analysis_phase(
                            bi_job_id, workspace_id, _bi_url, "d2c", _bi_token, _bi_conn
                        ))
                except Exception as _e:
                    _bi_exc[0] = _e

            log(f"Analysing {len(_competitor_names)} competitors: {', '.join(_competitor_names[:3])}{'…' if len(_competitor_names) > 3 else ''}", "info", "brand_intel")
            log("(scraping websites → ad library → content patterns → Claude AI analysis)", "info", "brand_intel")

            _bi_thread = _threading.Thread(target=_run_bi_thread, daemon=True)
            _bi_thread.start()

            _elapsed = 0
            _BI_MAX = 8 * 60  # hard cap: 8 minutes
            while _bi_thread.is_alive() and _elapsed < _BI_MAX:
                _bi_thread.join(timeout=20)
                if _bi_thread.is_alive():
                    _elapsed += 20
                    log(f"⏳ Competitor analysis running… ({_elapsed // 60}m {_elapsed % 60:02d}s)", "info", "brand_intel")

            if _bi_thread.is_alive():
                log("⚠ Brand Intel taking longer than expected — moving on, results will appear later in Competitor Intel tab", "missing", "brand_intel")
            elif _bi_exc[0]:
                raise _bi_exc[0]
            else:
                log("✓ Brand Intel complete — competitor intelligence gathered", "success", "brand_intel")

        except Exception as e:
            log(f"⚠ Brand Intel Phase 2 partial: {e}", "missing", "brand_intel")
    else:
        log("~ Brand Intel skipped (no Phase 1 job found)", "missing", "brand_intel")

    # ── Step 2: Reddit Voice of Customer (Competitive Sweep) ─────────────────
    log("Phase 2/4 — Reddit VoC: Mining customer conversations across product space", "phase", "reddit_voc")
    log("─────────────────────────────────────────────────────────", "divider")

    reddit_voc_data: dict = {}
    try:
        from urllib.parse import urlparse as _urlparse
        import httpx as _httpx_voc

        # Build own brand query from domain + top own keywords
        _domain = _urlparse(url).netloc.replace('www.', '').split('.')[0]
        _brand_q = _domain.strip().capitalize()
        _own_kws: list = []
        if bi_job_id:
            try:
                with get_conn() as _kw_conn:
                    with _kw_conn.cursor() as _kw_cur:
                        _kw_cur.execute(
                            "SELECT own_topic_space FROM brand_intel_jobs WHERE id=%s::uuid",
                            (bi_job_id,),
                        )
                        _kw_row = _kw_cur.fetchone()
                    if _kw_row and _kw_row[0]:
                        _raw = _kw_row[0]
                        _own_kws = (_raw if isinstance(_raw, list) else json.loads(_raw))[:3]
            except Exception:
                pass
        _kw_q = " ".join(_own_kws)
        _own_query = f"{_brand_q} {_kw_q}".strip() or _brand_q

        # Get confirmed competitor names from brand intel (Brand Intel step ran first)
        _competitor_names: list = []
        if bi_job_id:
            try:
                with get_conn() as _cp_conn:
                    with _cp_conn.cursor() as _cp_cur:
                        _cp_cur.execute(
                            """SELECT competitor_name FROM brand_competitor_profiles
                               WHERE job_id=%s::uuid AND confirmed=TRUE
                               ORDER BY confidence_pct DESC LIMIT 4""",
                            (bi_job_id,),
                        )
                        _competitor_names = [r[0] for r in _cp_cur.fetchall() if r[0]]
            except Exception:
                pass

        # Build list: own brand first, then each competitor
        _search_targets = [("own", _own_query)] + [("competitor", name) for name in _competitor_names]
        log(f"Sweeping Reddit: own brand + {len(_competitor_names)} competitors ({len(_search_targets)} searches)", "info", "reddit_voc")

        async def _sweep_reddit_all():
            """Run all Reddit searches sequentially with rate-limit delay."""
            _results: dict = {}
            async with _httpx_voc.AsyncClient(
                timeout=12,
                headers={"User-Agent": "runway-studios-aria/1.0"},
                follow_redirects=True,
            ) as _cli:
                for _idx, (_kind, _query) in enumerate(_search_targets):
                    if _idx > 0:
                        await asyncio.sleep(1.5)  # avoid Reddit rate limit
                    try:
                        _r = await _cli.get(
                            "https://www.reddit.com/search.json",
                            params={"q": _query, "sort": "relevance", "limit": 20, "type": "link"},
                        )
                        _posts = []
                        if _r.status_code == 200:
                            for _child in _r.json().get("data", {}).get("children", []):
                                _p = _child.get("data", {})
                                _posts.append({
                                    "title": _p.get("title", ""),
                                    "subreddit": _p.get("subreddit_name_prefixed", ""),
                                    "score": _p.get("score", 0),
                                    "url": f"https://reddit.com{_p.get('permalink', '')}",
                                    "text_preview": (_p.get("selftext") or "")[:300].strip(),
                                    "num_comments": _p.get("num_comments", 0),
                                })
                        _results[_query] = {"kind": _kind, "query": _query, "posts": _posts}
                    except Exception as _se:
                        _results[_query] = {"kind": _kind, "query": _query, "posts": [], "error": str(_se)}
            return _results

        _raw_results = asyncio.run(_sweep_reddit_all())

        _own_posts = _raw_results.get(_own_query, {}).get("posts", [])
        _comp_posts = {
            _v["query"]: _v["posts"]
            for _v in _raw_results.values()
            if _v.get("kind") == "competitor"
        }
        _total_posts = sum(len(_v.get("posts", [])) for _v in _raw_results.values())

        log(f"✓ Found {_total_posts} Reddit discussions across {len(_search_targets)} queries", "success", "reddit_voc")
        for _qv in _raw_results.values():
            log(f"  [{_qv.get('kind')}] \"{_qv.get('query')[:50]}\": {len(_qv.get('posts', []))} posts", "info", "reddit_voc")

        # Claude Haiku synthesis — extract competitive VoC insight across all brands
        _synthesis: dict = {}
        if _total_posts > 0:
            try:
                import anthropic as _anth_voc
                from services.agent_swarm.config import ANTHROPIC_API_KEY
                _HAIKU = "claude-haiku-4-5-20251001"

                _digest: list = []
                if _own_posts:
                    _digest.append(f"=== Reddit posts about {_brand_q} (our brand) ===")
                    for _p in _own_posts[:8]:
                        _digest.append(f"[{_p['subreddit']}] {_p['title']} | {_p['text_preview'][:150]}")
                for _cname, _cposts in _comp_posts.items():
                    if _cposts:
                        _digest.append(f"\n=== Reddit posts about {_cname} (competitor) ===")
                        for _p in _cposts[:8]:
                            _digest.append(f"[{_p['subreddit']}] {_p['title']} | {_p['text_preview'][:150]}")

                _haiku_client = _anth_voc.Anthropic(api_key=ANTHROPIC_API_KEY)
                _haiku_resp = _haiku_client.messages.create(
                    model=_HAIKU,
                    max_tokens=800,
                    system="You are a market research analyst. Return ONLY valid JSON, no markdown.",
                    messages=[{"role": "user", "content": (
                        "Analyse these Reddit posts about a product category and return a JSON synthesis.\n\n"
                        + "\n".join(_digest[:60])
                        + '\n\nReturn JSON with exactly these keys:\n'
                        '{"top_pain_points":["pain 1","pain 2","pain 3","pain 4","pain 5"],'
                        '"unmet_desires":["desire 1","desire 2","desire 3"],'
                        '"competitor_weaknesses":{"CompetitorName":["weakness 1","weakness 2"]},'
                        '"our_brand_sentiment":"positive|neutral|negative|not_mentioned",'
                        '"category_sentiment":"positive|neutral|negative",'
                        '"win_opportunity":"One sentence: what gap exists that our brand can own"}'
                    )}],
                )
                _syn_raw = _haiku_resp.content[0].text.strip()
                if _syn_raw.startswith("```"):
                    _syn_raw = _syn_raw.split("```", 2)[1]
                    if _syn_raw.startswith("json"):
                        _syn_raw = _syn_raw[4:]
                    _syn_raw = _syn_raw.rsplit("```", 1)[0]
                _synthesis = json.loads(_syn_raw.strip())
                log(f"✓ VoC synthesis: {len(_synthesis.get('top_pain_points', []))} pain points identified", "success", "reddit_voc")
                if _synthesis.get("win_opportunity"):
                    log(f"  Win opportunity: {_synthesis['win_opportunity'][:80]}", "info", "reddit_voc")
            except Exception as _syn_e:
                log(f"~ VoC synthesis partial: {_syn_e}", "missing", "reddit_voc")

        reddit_voc_data = {
            "own_posts": _own_posts[:15],
            "competitor_posts": {k: v[:10] for k, v in _comp_posts.items()},
            "synthesis": _synthesis,
            "queries_run": len(_search_targets),
            "total_posts": _total_posts,
        }

        # Persist to onboard_jobs.reddit_voc (enriched competitive sweep)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE onboard_jobs SET reddit_voc=%s::jsonb, updated_at=NOW() WHERE id=%s::uuid",
                    (json.dumps(reddit_voc_data), job_id),
                )
            conn.commit()

    except Exception as e:
        log(f"⚠ Reddit VoC partial: {e}", "missing", "reddit_voc")

    # ── Step 3: LP Audit ──────────────────────────────────────────────────────
    log("Phase 3/4 — LP Audit: Analysing landing page conversion score", "phase", "lp_audit")
    log("─────────────────────────────────────────────────────────", "divider")

    lp_result = None
    try:
        from services.agent_swarm.connectors.lp_auditor import run_full_audit

        # Get competitor URLs from brand intel (now available since P2 just ran)
        competitor_urls = []
        if bi_job_id:
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT competitor_domains FROM brand_intel_jobs WHERE id=%s::uuid",
                            (bi_job_id,),
                        )
                        row = cur.fetchone()
                    if row and row[0]:
                        doms = row[0] if isinstance(row[0], list) else json.loads(row[0])
                        competitor_urls = [f"https://{d}" if not d.startswith("http") else d
                                           for d in doms[:3]]
            except Exception:
                pass

        log(f"Auditing {url}" + (f" + {len(competitor_urls)} competitors" if competitor_urls else ""), "info", "lp_audit")

        # 3-minute hard timeout so LP Audit never blocks the chain indefinitely
        async def _run_audit_with_timeout():
            return await asyncio.wait_for(
                run_full_audit(brand_url=url, competitor_urls=competitor_urls or None),
                timeout=180,
            )

        lp_result = asyncio.run(_run_audit_with_timeout())
        score = (lp_result.get("our_site") or lp_result.get("our_audit") or {}).get("score", 0)
        log(f"✓ LP Audit complete — conversion score: {score}/100", "success", "lp_audit")

        # Save to onboard_jobs (for display on onboard page)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE onboard_jobs SET lp_audit=%s::jsonb, updated_at=NOW() WHERE id=%s::uuid",
                    (json.dumps(lp_result), job_id),
                )
            conn.commit()

        # Also save to lp_audits table so Growth OS can read it
        try:
            import uuid as _lp_uuid
            _lp_audit_id = str(_lp_uuid.uuid4())
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO lp_audits (id, workspace_id, brand_url, status, audit_json, updated_at)
                           VALUES (%s::uuid, %s::uuid, %s, 'completed', %s::jsonb, NOW())""",
                        (_lp_audit_id, workspace_id, url, json.dumps(lp_result)),
                    )
                conn.commit()
        except Exception as _lp_e:
            print(f"[onboard_chain] lp_audits insert failed: {_lp_e}")

    except asyncio.TimeoutError:
        log("⚠ LP Audit timed out after 3 min — moving on", "missing", "lp_audit")
    except Exception as e:
        log(f"⚠ LP Audit partial: {e}", "missing", "lp_audit")

    # ── Step 4: Growth OS ─────────────────────────────────────────────────────
    log("Phase 4/4 — Growth OS: Generating 90-day growth strategy", "phase", "growth_os")
    log("─────────────────────────────────────────────────────────", "divider")

    try:
        from services.agent_swarm.core.growth_os import run_full_strategy_job
        import uuid as _uuid

        gos_job_id = str(_uuid.uuid4())
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO growth_os_jobs (id, workspace_id, directive, strategy_mode, status)
                       VALUES (%s::uuid, %s::uuid, %s, 'onboard', 'pending')""",
                    (gos_job_id, workspace_id, directive or "Build full-funnel growth strategy from scratch"),
                )
            conn.commit()

        # Save gos_job_id on onboard_jobs
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE onboard_jobs SET gos_job_id=%s::uuid, updated_at=NOW() WHERE id=%s::uuid",
                    (gos_job_id, job_id),
                )
            conn.commit()

        import threading as _gos_thread

        _gos_exc: list = [None]
        _gos_done: list = [False]

        def _run_gos():
            try:
                run_full_strategy_job(
                    gos_job_id, workspace_id,
                    directive=directive or "Build a full-funnel growth strategy from scratch",
                    brand_url=url,
                    strategy_mode="onboard",
                    auto_trigger_analyses=False,
                )
                _gos_done[0] = True
            except Exception as _ge:
                _gos_exc[0] = _ge

        _gos_t = _gos_thread.Thread(target=_run_gos, daemon=True)
        _gos_t.start()

        _gos_elapsed = 0
        _GOS_MAX = 20 * 60  # 20-minute hard cap
        while _gos_t.is_alive() and _gos_elapsed < _GOS_MAX:
            _gos_t.join(timeout=30)
            if _gos_t.is_alive():
                _gos_elapsed += 30
                log(f"⏳ Generating strategy… ({_gos_elapsed // 60}m {_gos_elapsed % 60:02d}s)", "info", "growth_os")

        if _gos_t.is_alive():
            log("⚠ Growth OS still generating — strategy will appear in dashboard within 5 minutes", "missing", "growth_os")
            # Mark complete anyway so user isn't left waiting
            set_status("complete", {"gos_job_id": gos_job_id})
        elif _gos_exc[0]:
            log(f"⚠ Growth OS error: {_gos_exc[0]}", "missing", "growth_os")
            set_status("complete", {"gos_job_id": gos_job_id})
        else:
            log("✓ Growth OS strategy complete!", "success", "growth_os")
            # Deduct 50 credits on successful completion only
            try:
                from services.agent_swarm.app import _get_org_id_for_workspace, _deduct_credits_only
                with get_conn() as _cc:
                    _org = _get_org_id_for_workspace(_cc, workspace_id)
                    _deduct_credits_only(_cc, _org, workspace_id, 50, "growth_os_bundle")
            except Exception as _ce:
                print(f"[onboard_chain] credit deduction warning (gos): {_ce}")
            set_status("complete", {"gos_job_id": gos_job_id})

    except Exception as e:
        import traceback
        print(f"[onboard_chain] growth_os step error: {e}\n{traceback.format_exc()}")
        log(f"⚠ Growth OS partial: {e}", "missing", "growth_os")
        set_status("complete")

    # Mark workspace onboarding complete so the "Welcome" modal never shows again
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE workspaces SET onboarding_complete=true, "
                    "onboarding_channels=%s::jsonb WHERE id=%s::uuid",
                    (json.dumps(["brand_intel", "growth_os"]), workspace_id),
                )
            conn.commit()
    except Exception as _e:
        print(f"[onboard_chain] onboarding_complete update failed: {_e}")

    log("═══════════════════════════════════════", "separator")
    log("  ✓ Analysis complete — view your results in the dashboard", "header")
    log("═══════════════════════════════════════", "separator")


def _run_youtube_chain(job_id, workspace_id, url, log, set_status):
    """YouTube chain: YT Competitor Discovery → YT Analysis + Growth Recipe."""
    import re as _re
    import uuid as _uuid
    from services.agent_swarm.db import get_conn
    import importlib

    log("Phase 1/2 — YouTube Competitor Discovery", "phase", "youtube")
    log("─────────────────────────────────────────────────────────", "divider")

    yt_job_id = str(_uuid.uuid4())
    try:
        # ── Bug fix 3: Resolve channel ID and save to platform_connections ──
        # Best source: preview_data already has the resolved channel_id from the YouTube API
        channel_id = None
        try:
            with get_conn() as _pconn:
                with _pconn.cursor() as _pcur:
                    _pcur.execute(
                        "SELECT preview_data FROM onboard_jobs WHERE id=%s::uuid",
                        (job_id,),
                    )
                    _prow = _pcur.fetchone()
            if _prow and _prow[0]:
                _pd = _prow[0] if isinstance(_prow[0], dict) else json.loads(_prow[0])
                channel_id = _pd.get("channel_id")
        except Exception as _pe:
            print(f"[onboard_chain] preview_data read failed: {_pe}")

        # Fallback: extract from /channel/UCXXX URL directly
        if not channel_id:
            _m = _re.search(r"youtube\.com/channel/([A-Za-z0-9_\-]+)", url)
            if _m:
                channel_id = _m.group(1)

        if channel_id:
            log(f"Saving YouTube channel {channel_id} to workspace…", "info", "youtube")
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO platform_connections
                               (id, workspace_id, platform, account_id, status, updated_at)
                           VALUES (%s::uuid, %s::uuid, 'youtube', %s, 'active', NOW())
                           ON CONFLICT (workspace_id, platform, account_id)
                           DO UPDATE SET status='active', updated_at=NOW()""",
                        (str(_uuid.uuid4()), workspace_id, channel_id),
                    )
                conn.commit()
        else:
            log("⚠ Could not extract channel ID from URL — discovery may find no seed channel", "missing", "youtube")

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO yt_analysis_jobs
                           (id, workspace_id, status, phase, discovery_status)
                       VALUES (%s::uuid, %s::uuid, 'pending', 'idle', 'discovering')""",
                    (yt_job_id, workspace_id),
                )
            conn.commit()

        # Save yt_job_id on onboard_jobs
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE onboard_jobs SET yt_job_id=%s::uuid, updated_at=NOW() WHERE id=%s::uuid",
                    (yt_job_id, job_id),
                )
            conn.commit()

        yt_intel = importlib.import_module("services.agent_swarm.core.yt_intelligence")

        # Phase 1: Discovery — call directly (sync function, manages own conn)
        yt_intel.run_discovery_phase(workspace_id=workspace_id, job_id=yt_job_id)
        log("✓ Competitor channels discovered", "success", "youtube")

        # Auto-confirm all discovered competitors and jump straight to 'analyzing'
        # (skip awaiting_confirmation — no user confirmation step in onboard flow)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT discovery_candidates FROM yt_analysis_jobs WHERE id=%s::uuid",
                    (yt_job_id,),
                )
                row = cur.fetchone()
            candidates = row[0] if row else []
            if isinstance(candidates, str):
                candidates = json.loads(candidates)

        confirmed_ids = [c.get("channel_id") for c in candidates if c.get("channel_id")]
        log(f"Auto-confirming {len(confirmed_ids)} YouTube competitor channels…", "info", "youtube")

        # Immediately mark as 'analyzing' so frontend shows analysis in progress
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE yt_analysis_jobs SET discovery_status='analyzing', status='running' WHERE id=%s::uuid",
                    (yt_job_id,),
                )
            conn.commit()

        # Phase 2: Deep Analysis
        log("Phase 2/2 — YouTube Deep Analysis + Growth Recipe", "phase", "youtube")
        log("─────────────────────────────────────────────────────────", "divider")

        yt_intel.run_analysis_phase(workspace_id=workspace_id, job_id=yt_job_id)

        log("✓ YouTube analysis + growth recipe complete!", "success", "youtube")

        # Deduct 50 credits on successful completion only
        try:
            from services.agent_swarm.app import _get_org_id_for_workspace, _deduct_credits_only
            with get_conn() as _cc:
                _org = _get_org_id_for_workspace(_cc, workspace_id)
                _deduct_credits_only(_cc, _org, workspace_id, 50, "youtube_intel_bundle")
        except Exception as _ce:
            print(f"[onboard_chain] credit deduction warning (yt): {_ce}")

        set_status("complete", {"yt_job_id": yt_job_id})

    except Exception as e:
        import traceback
        print(f"[onboard_chain] _run_youtube_chain error: {e}\n{traceback.format_exc()}")
        log(f"⚠ YouTube chain partial: {e}", "missing", "youtube")
        set_status("complete", {"yt_job_id": yt_job_id})

    # Mark workspace onboarding complete
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE workspaces SET onboarding_complete=true, "
                    "onboarding_channels=%s::jsonb WHERE id=%s::uuid",
                    (json.dumps(["youtube"]), workspace_id),
                )
            conn.commit()
    except Exception as _e:
        print(f"[onboard_chain] onboarding_complete update failed: {_e}")

    log("═══════════════════════════════════════", "separator")
    log("  ✓ YouTube analysis complete — view results in the dashboard", "header")
    log("═══════════════════════════════════════", "separator")


# ── DB Migration SQL ───────────────────────────────────────────────────────────

ONBOARD_MIGRATION_SQL = """
-- onboard_jobs: tracks the full visitor→paid→chain flow
CREATE TABLE IF NOT EXISTS onboard_jobs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    url               TEXT NOT NULL,
    url_type          TEXT NOT NULL DEFAULT 'website',  -- website | youtube
    status            TEXT NOT NULL DEFAULT 'pending'   -- pending | previewing | preview_ready | chain_running | complete | failed
        CHECK (status IN ('pending','previewing','preview_ready','chain_running','complete','failed')),
    preview_data      JSONB,
    bi_job_id         UUID,
    yt_job_id         UUID,
    gos_job_id        UUID,
    lp_audit          JSONB,
    chain_log         JSONB NOT NULL DEFAULT '[]',
    razorpay_order_id TEXT,
    paid_at           TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboard_jobs_ws ON onboard_jobs (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_onboard_jobs_order ON onboard_jobs (razorpay_order_id) WHERE razorpay_order_id IS NOT NULL;
"""
