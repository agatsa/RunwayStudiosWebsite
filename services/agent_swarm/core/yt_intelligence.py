"""
services/agent_swarm/core/yt_intelligence.py

9-layer YouTube Competitor Intelligence engine.

Layer map
─────────
  L1  velocity = views / max(age_days, 1)  +  engagement_rate  +  comment_density
  L2  TF-IDF → TruncatedSVD(50d) → KMeans  +  Claude Haiku cluster naming
  L3  Claude Haiku  →  format detection
  L4  Claude Haiku  →  title pattern classification
  L5  Claude Haiku vision (base64)  →  thumbnail psychology
  L6  upload gap cadence analysis  +  momentum windows (pre-breakout cadence)
  L7  topic lifecycle decay curves  →  evergreen vs trend  +  half-life weeks
  L8  channel velocity distribution  →  IQR risk profile  +  cadence classification
  L9  sklearn LogisticRegression breakout model  →  Claude Sonnet playbook text

AI stack
────────
  - Claude Haiku (claude-haiku-4-5-20251001) : batch classification, cluster naming
  - Claude Sonnet 4.6 (claude-sonnet-4-6)    : final playbook generation
  - sklearn TF-IDF + TruncatedSVD            : 50-dim embeddings (no external API)
  - sklearn KMeans                            : topic clustering
  - sklearn LogisticRegression               : breakout prediction

DB pattern: psycopg2 — callers pass a live conn; functions call conn.commit() internally.
"""

import json
import math
import re
import statistics
import time
import base64
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import anthropic
import numpy as np
import requests
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import MultiLabelBinarizer

from services.agent_swarm.config import ANTHROPIC_API_KEY, YOUTUBE_API_KEY
from services.agent_swarm.connectors.yt_competitor import (
    QuotaExceededError,
    get_channel_meta,
    get_videos_details,
    list_recent_video_ids,
    resolve_channel_id_from_handle,
    search_channels_by_query,
    search_videos_by_query,
)

# ── Constants ─────────────────────────────────────────────────────────────────
CLAUDE_HAIKU  = "claude-haiku-4-5-20251001"
CLAUDE_SONNET = "claude-sonnet-4-6"
CLAUDE_SLEEP  = 0.5   # seconds between Claude API calls (rate-limit guard)

FORMAT_TAXONOMY = [
    "talking_head_explainer",
    "tutorial_steps",
    "review_comparison",
    "case_study",
    "story_narrative",
    "testimonial",
    "news_update",
    "reaction_commentary",
    "promo_ad",
]

TITLE_PATTERNS = [
    "how_to",
    "list_numbered",
    "curiosity_gap",
    "fear_warning",
    "authority_experience",
    "transformation",
    "myth_busting",
    "vs_comparison",
    "urgent_update",
    "question_hook",
]

VIDEO_POOL_SIZE   = 30   # recent videos fetched per channel before selection
N_BEST            = 6    # top performers kept (highest views)
N_WORST           = 4    # under-performers kept (lowest views)
N_VIDEOS_DEFAULT  = N_BEST + N_WORST   # = 10  (kept for any legacy callers)
MAX_COMPETITORS   = 5
OWN_CHANNEL_N     = 15   # own channel videos to analyse for comparison
DISCOVERY_N_SEED  = 30
DISCOVERY_KW_TOP  = 8    # top keywords to search (each = 2 search.list calls = 200 quota units)
DISCOVERY_CANDS   = 25   # max candidates per keyword search


# ── Internal helpers ──────────────────────────────────────────────────────────

def _auto_k(n: int) -> int:
    """auto_k = min(12, max(4, round(sqrt(n))))  — KMeans cluster count heuristic."""
    return min(12, max(4, round(math.sqrt(n))))


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length float vectors."""
    dot   = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _strip_json_fences(raw: str) -> str:
    """Remove ```json ... ``` markdown fences from a Claude response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"```[a-z]*\n?", "", raw).replace("```", "")
    return raw.strip()


def _safe_json(raw: str, fallback: dict) -> dict:
    """Parse JSON from Claude response with graceful fallback."""
    try:
        return json.loads(_strip_json_fences(raw))
    except Exception:
        return fallback


def _extract_topic_space(titles: list[str], n_keywords: int = 12) -> list[str]:
    """Extract top TF-IDF keyword n-grams from a list of video titles.

    Returns a list of keyword strings representing the channel's topic fingerprint.
    Used for the live 'Topic Space' display during competitor discovery.
    """
    if not titles or len(titles) < 2:
        return []
    try:
        tfidf = TfidfVectorizer(ngram_range=(1, 2), max_features=300, min_df=1, stop_words='english')
        X = tfidf.fit_transform(titles)
        feature_names = tfidf.get_feature_names_out()
        scores = np.asarray(X.sum(axis=0)).flatten()
        top_idx = scores.argsort()[-n_keywords:][::-1]
        # Filter out single-char and very short tokens
        return [feature_names[i] for i in top_idx if len(feature_names[i]) > 3]
    except Exception:
        return []


def _log_to_job(conn, job_id: int, entry: dict):
    """Append a structured log entry to yt_analysis_jobs.discovery_log (JSONB array).

    entry format: {type: 'keyword'|'channel_found'|'own_topic_space'|'info'|'complete'|'error', msg, data?}
    Silently ignores errors (column may not exist on old deployments).
    """
    try:
        entry_with_ts = {"ts": datetime.now(timezone.utc).isoformat(), **entry}
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE yt_analysis_jobs
                SET discovery_log = COALESCE(discovery_log, '[]'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (json.dumps([entry_with_ts]), job_id),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


# ── Layer 3: Format Detection ─────────────────────────────────────────────────

def _classify_format(
    title: str,
    description: str,
    duration_seconds: int,
    client: anthropic.Anthropic,
) -> dict:
    """Classify video format using Claude Haiku.

    Returns: {format_label, format_structure: list[str], format_energy: str}
    """
    dur = duration_seconds or 0
    if dur < 180:
        bucket = "short (<3 min)"
    elif dur <= 600:
        bucket = "medium (3–10 min)"
    else:
        bucket = "long (>10 min)"

    desc_trunc = (description or "")[:1200]
    prompt = (
        f"Classify this YouTube video's format.\n\n"
        f"Title: {title}\n"
        f"Description: {desc_trunc}\n"
        f"Duration bucket: {bucket}\n\n"
        f"FORMAT_TAXONOMY options: {', '.join(FORMAT_TAXONOMY)}\n\n"
        "Return JSON with exactly:\n"
        '- "format_label": one value from FORMAT_TAXONOMY\n'
        '- "structure": array of 2–4 strings describing the video structure\n'
        '- "energy": one of "high", "medium", "low"\n\n'
        "Return ONLY valid JSON, no other text."
    )
    try:
        resp = client.messages.create(
            model=CLAUDE_HAIKU,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _safe_json(
            resp.content[0].text,
            {"format_label": "talking_head_explainer", "structure": [], "energy": "medium"},
        )
        label = parsed.get("format_label", "talking_head_explainer")
        if label not in FORMAT_TAXONOMY:
            label = "talking_head_explainer"
        return {
            "format_label":     label,
            "format_structure": parsed.get("structure", []),
            "format_energy":    parsed.get("energy", "medium"),
        }
    except Exception as e:
        print(f"[yt_intel] _classify_format error: {e}")
        return {"format_label": "talking_head_explainer", "format_structure": [], "format_energy": "medium"}


# ── Layer 4: Title Pattern Intelligence ───────────────────────────────────────

def _classify_title_patterns(title: str, client: anthropic.Anthropic) -> dict:
    """Classify title persuasion patterns using Claude Haiku.

    Returns: {title_patterns: list[str], curiosity_score: int(0-10), specificity_score: int(0-10)}
    """
    prompt = (
        f"Analyse this YouTube video title for persuasion patterns.\n\n"
        f"Title: {title}\n\n"
        f"TITLE_PATTERNS (can match multiple): {', '.join(TITLE_PATTERNS)}\n\n"
        "Return JSON with exactly:\n"
        '- "title_patterns": array of matched patterns (subset of the list above, can be empty)\n'
        '- "curiosity_score": integer 0–10 (how much curiosity does this title trigger?)\n'
        '- "specificity_score": integer 0–10 (how specific/concrete vs vague is this title?)\n\n'
        "Return ONLY valid JSON, no other text."
    )
    try:
        resp = client.messages.create(
            model=CLAUDE_HAIKU,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        parsed = _safe_json(
            resp.content[0].text,
            {"title_patterns": [], "curiosity_score": 5, "specificity_score": 5},
        )
        patterns = [p for p in parsed.get("title_patterns", []) if p in TITLE_PATTERNS]
        return {
            "title_patterns":   patterns,
            "curiosity_score":  min(10, max(0, int(parsed.get("curiosity_score", 5) or 5))),
            "specificity_score": min(10, max(0, int(parsed.get("specificity_score", 5) or 5))),
        }
    except Exception as e:
        print(f"[yt_intel] _classify_title_patterns error: {e}")
        return {"title_patterns": [], "curiosity_score": 5, "specificity_score": 5}


# ── Layer 5: Thumbnail Psychology (vision) ────────────────────────────────────

def _analyze_thumbnail(thumbnail_url: str, client: anthropic.Anthropic) -> dict:
    """Analyse a YouTube thumbnail using Claude Haiku vision (base64 image).

    Returns: {thumb_face, thumb_text, thumb_emotion, thumb_objects, thumb_style, thumb_readable_text}
    """
    default = {
        "thumb_face": None, "thumb_text": None, "thumb_emotion": "unknown",
        "thumb_objects": [], "thumb_style": "unknown", "thumb_readable_text": "",
    }
    if not thumbnail_url:
        return default

    # Download image and encode as base64
    try:
        r = requests.get(thumbnail_url, timeout=12)
        r.raise_for_status()
        image_b64 = base64.standard_b64encode(r.content).decode("utf-8")
        ct = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if "png" in ct:
            media_type: str = "image/png"
        elif "webp" in ct:
            media_type = "image/webp"
        elif "gif" in ct:
            media_type = "image/gif"
        else:
            media_type = "image/jpeg"
    except Exception as e:
        print(f"[yt_intel] thumbnail download error for {thumbnail_url}: {e}")
        return default

    prompt = (
        "Analyse this YouTube video thumbnail for marketing signals. Return JSON with exactly:\n"
        '- "thumb_face": boolean — is there a human face visible?\n'
        '- "thumb_text": boolean — is there text overlay on the thumbnail?\n'
        '- "thumb_emotion": one of "warning", "surprise", "calm", "confidence", "fear", "neutral", "unknown"\n'
        '- "thumb_objects": array from ["person","device","heart_icon","chart","doctor","text_banner","other"]\n'
        '- "thumb_style": one of "high_contrast", "minimal", "clinical", "busy", "unknown"\n'
        '- "thumb_readable_text": string — readable text visible (empty string if none)\n\n'
        "Return ONLY valid JSON, no other text."
    )
    try:
        resp = client.messages.create(
            model=CLAUDE_HAIKU,
            max_tokens=250,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type":       "base64",
                            "media_type": media_type,
                            "data":       image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        parsed = _safe_json(resp.content[0].text, default)
        valid_emotions = {"warning", "surprise", "calm", "confidence", "fear", "neutral", "unknown"}
        valid_styles   = {"high_contrast", "minimal", "clinical", "busy", "unknown"}
        return {
            "thumb_face":         bool(parsed.get("thumb_face")) if parsed.get("thumb_face") is not None else None,
            "thumb_text":         bool(parsed.get("thumb_text")) if parsed.get("thumb_text") is not None else None,
            "thumb_emotion":      parsed.get("thumb_emotion", "unknown")
                                  if parsed.get("thumb_emotion") in valid_emotions else "unknown",
            "thumb_objects":      parsed.get("thumb_objects", []),
            "thumb_style":        parsed.get("thumb_style", "unknown")
                                  if parsed.get("thumb_style") in valid_styles else "unknown",
            "thumb_readable_text": str(parsed.get("thumb_readable_text", ""))[:200],
        }
    except Exception as e:
        print(f"[yt_intel] _analyze_thumbnail error: {e}")
        return default


# ── Competitor Discovery ───────────────────────────────────────────────────────

def discover_competitors(
    workspace_id: str,
    seed_channel_id: str,
    conn,
    n_seed: int = DISCOVERY_N_SEED,
    final_k: int = MAX_COMPETITORS,
    job_id: Optional[int] = None,
) -> list[dict]:
    """Discover top competitor channels from a seed channel using topic similarity.

    Algorithm:
      1. Fetch the seed channel's last *n_seed* video titles via Data API.
      2. Build TF-IDF (1-2 ngrams, max_features=300) + TruncatedSVD(50d) → seed centroid.
      3. Extract top-DISCOVERY_KW_TOP keyword n-grams.
      4. For each keyword: search_channels_by_query + search_videos_by_query → collect channel_ids.
      5. Score each candidate channel: embed(title+keyword) → cosine_sim vs seed centroid.
      6. Deduplicate, exclude seed channel, sort by score, take top *final_k*.
      7. For each top candidate: fetch video titles → compute topic_space (keyword pills).
      8. Upsert into yt_competitor_channels + save candidates to discovery_candidates JSONB.

    When job_id is provided, live-logs progress to yt_analysis_jobs.discovery_log.
    Returns list of {channel_id, score, topic_space, meta} dicts.
    """
    def _log(entry: dict):
        if job_id is not None:
            _log_to_job(conn, job_id, entry)

    # Step 1: get seed titles — read from DB (already ingested by YouTubeConnector, zero API calls)
    _log({"type": "info", "msg": "Reading your channel's recent videos from database…"})
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title FROM youtube_videos WHERE workspace_id = %s AND title IS NOT NULL ORDER BY published_at DESC LIMIT %s",
                (workspace_id, n_seed),
            )
            titles = [r[0] for r in cur.fetchall() if r[0]]
    except Exception as e:
        print(f"[yt_intel] discover_competitors seed titles DB error: {e}")
        titles = []

    if len(titles) < 3:
        # DB empty — fall back to API with extended retry
        _log({"type": "info", "msg": "No videos in database yet — fetching from YouTube API…"})
        vid_ids = list_recent_video_ids(seed_channel_id, n_seed, YOUTUBE_API_KEY)
        if not vid_ids:
            _log({"type": "error", "msg": "Could not fetch your channel's videos. Make sure your YouTube channel is connected and has at least 3 public videos."})
            return []
        vids = get_videos_details(vid_ids, YOUTUBE_API_KEY)
        titles = [v["title"] for v in vids if v.get("title")]
        if len(titles) < 3:
            _log({"type": "error", "msg": "Too few videos on your channel to run discovery."})
            return []

    # Compute own channel's topic space and log it
    own_topic_space = _extract_topic_space(titles, n_keywords=15)
    _log({"type": "own_topic_space", "msg": "Your channel's topic fingerprint computed", "data": own_topic_space})

    # Also save own_topic_space to the job row
    if job_id is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE yt_analysis_jobs SET own_topic_space = %s WHERE id = %s",
                    (json.dumps(own_topic_space), job_id),
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    # Step 2: TF-IDF + SVD on seed titles → seed centroid
    tfidf = TfidfVectorizer(ngram_range=(1, 2), max_features=300, min_df=1, stop_words='english')
    try:
        X = tfidf.fit_transform(titles)
    except Exception:
        return []

    n_comp = min(50, X.shape[1] - 1, len(titles) - 1)
    if n_comp < 2:
        return []
    svd = TruncatedSVD(n_components=n_comp, random_state=42)
    X_embed = svd.fit_transform(X)
    seed_centroid: list[float] = X_embed.mean(axis=0).tolist()

    # Step 3: top keywords by TF-IDF sum score
    feature_names = tfidf.get_feature_names_out()
    scores = np.asarray(X.sum(axis=0)).flatten()
    top_idx = scores.argsort()[-DISCOVERY_KW_TOP:][::-1]
    keywords = [feature_names[i] for i in top_idx if len(feature_names[i]) > 3]

    _log({"type": "info", "msg": f"Searching YouTube for {len(keywords)} topic keywords…", "data": keywords})

    # Step 4: candidate collection — log each keyword being searched
    candidates: dict[str, dict] = {}
    quota_hit = False
    for kw in keywords:
        if quota_hit:
            break
        _log({"type": "keyword", "msg": f'Searching: "{kw}"', "data": {"keyword": kw}})
        try:
            for ch in search_channels_by_query(kw, DISCOVERY_CANDS, YOUTUBE_API_KEY):
                ch_id = ch["channel_id"]
                if ch_id not in candidates:
                    candidates[ch_id] = {"score_text": ch.get("title", ""), "query": kw}
        except QuotaExceededError:
            quota_hit = True
            _log({"type": "error", "msg": "YouTube API quota exceeded for today. Discovery will retry automatically after midnight Pacific Time (UTC-8). Your existing competitors remain intact."})
            break
        try:
            for vid in search_videos_by_query(kw, DISCOVERY_CANDS, YOUTUBE_API_KEY):
                ch_id = vid["channel_id"]
                if ch_id not in candidates:
                    candidates[ch_id] = {"score_text": vid.get("title", ""), "query": kw}
        except QuotaExceededError:
            quota_hit = True
            _log({"type": "error", "msg": "YouTube API quota exceeded for today. Discovery will retry automatically after midnight Pacific Time (UTC-8). Your existing competitors remain intact."})
            break

    _log({"type": "info", "msg": f"Found {len(candidates)} candidate channels — scoring by topic similarity…"})

    # Step 5: score candidates by cosine similarity
    scored: list[tuple[str, float]] = []
    for ch_id, meta in candidates.items():
        if ch_id == seed_channel_id:
            continue
        text = f"{meta.get('score_text', '')} {meta.get('query', '')}"
        try:
            X_cand = tfidf.transform([text])
            emb    = svd.transform(X_cand)[0].tolist()
            sim    = _cosine_sim(seed_centroid, emb)
        except Exception:
            sim = 0.0
        scored.append((ch_id, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    top_candidates = scored[:final_k * 3]

    # Step 6: fetch real channel metadata for top candidates, filter junk
    _log({"type": "info", "msg": "Fetching channel details for top matches…"})
    top: list[tuple[str, float, dict]] = []
    for ch_id, sim in top_candidates:
        if len(top) >= final_k:
            break
        meta = get_channel_meta(ch_id, YOUTUBE_API_KEY)
        if not meta.get("title") or meta.get("title") == "Unknown":
            continue
        subs = meta.get("subscriber_count", 0) or 0
        if subs < 100:
            continue
        top.append((ch_id, sim, meta))

    # Step 7: fetch video titles for each top candidate → compute topic_space
    candidate_data: list[dict] = []
    for ch_id, sim, meta in top:
        ch_vid_ids = list_recent_video_ids(ch_id, 20, YOUTUBE_API_KEY)
        ch_vids = get_videos_details(ch_vid_ids, YOUTUBE_API_KEY) if ch_vid_ids else []
        ch_titles = [v["title"] for v in ch_vids if v.get("title")]
        topic_space = _extract_topic_space(ch_titles, n_keywords=10)

        confidence_pct = int(round(max(0.0, min(1.0, sim)) * 100))

        _log({
            "type": "channel_found",
            "msg": f'Found: {meta.get("title", ch_id)} ({confidence_pct}% match)',
            "data": {
                "channel_id": ch_id,
                "title": meta.get("title", ""),
                "handle": meta.get("handle", ""),
                "subscriber_count": meta.get("subscriber_count"),
                "similarity_score": round(sim, 4),
                "confidence_pct": confidence_pct,
                "topic_space": topic_space,
            },
        })

        candidate_data.append({
            "channel_id": ch_id,
            "title": meta.get("title", ""),
            "handle": meta.get("handle", ""),
            "subscriber_count": meta.get("subscriber_count"),
            "similarity_score": round(sim, 4),
            "confidence_pct": confidence_pct,
            "topic_space": topic_space,
        })

    # Save candidates to discovery_candidates JSONB on the job row
    if job_id is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE yt_analysis_jobs SET discovery_candidates = %s WHERE id = %s",
                    (json.dumps(candidate_data), job_id),
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    # Step 8: upsert into yt_competitor_channels (with topic_space)
    with conn.cursor() as cur:
        for rank_0, (ch_id, sim, meta) in enumerate(top):
            topic_space = next(
                (c["topic_space"] for c in candidate_data if c["channel_id"] == ch_id), []
            )
            try:
                cur.execute(
                    """
                    INSERT INTO yt_competitor_channels
                        (workspace_id, channel_id, channel_title, channel_handle,
                         subscriber_count, similarity_score, rank, source, discovered_at,
                         topic_space)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'auto', NOW(), %s)
                    ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                        channel_title    = EXCLUDED.channel_title,
                        channel_handle   = EXCLUDED.channel_handle,
                        subscriber_count = EXCLUDED.subscriber_count,
                        similarity_score = EXCLUDED.similarity_score,
                        rank             = EXCLUDED.rank,
                        topic_space      = EXCLUDED.topic_space
                    """,
                    (
                        workspace_id, ch_id,
                        meta.get("title", "")[:200],
                        meta.get("handle", ""),
                        meta.get("subscriber_count"),
                        round(sim, 4), rank_0 + 1,
                        json.dumps(topic_space),
                    ),
                )
            except Exception:
                # Fallback if topic_space column doesn't exist yet
                cur.execute(
                    """
                    INSERT INTO yt_competitor_channels
                        (workspace_id, channel_id, channel_title, channel_handle,
                         subscriber_count, similarity_score, rank, source, discovered_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'auto', NOW())
                    ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                        channel_title    = EXCLUDED.channel_title,
                        channel_handle   = EXCLUDED.channel_handle,
                        subscriber_count = EXCLUDED.subscriber_count,
                        similarity_score = EXCLUDED.similarity_score,
                        rank             = EXCLUDED.rank
                    """,
                    (
                        workspace_id, ch_id,
                        meta.get("title", "")[:200],
                        meta.get("handle", ""),
                        meta.get("subscriber_count"),
                        round(sim, 4), rank_0 + 1,
                    ),
                )
    conn.commit()

    _log({"type": "complete", "msg": f"Discovery complete — {len(top)} competitor channels found"})
    return [{"channel_id": ch_id, "score": float(sim)} for ch_id, sim, _ in top]


# ── Ingest Channel ─────────────────────────────────────────────────────────────

def ingest_channel(
    workspace_id: str,
    channel_id: str,
    conn,
    pool_size: int = VIDEO_POOL_SIZE,
    n_best: int = N_BEST,
    n_worst: int = N_WORST,
) -> int:
    """Fetch and store metadata + videos for a competitor channel.

    Fetches *pool_size* recent videos, then selects *n_best* top-viewed
    (best performers) and *n_worst* lowest-viewed (under-performers) from
    the pool — giving a representative signal of what works and what doesn't.

    Upserts into yt_competitor_channels + yt_competitor_videos.
    Returns number of videos stored.
    """
    # Update channel meta
    meta = get_channel_meta(channel_id, YOUTUBE_API_KEY)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO yt_competitor_channels
                (workspace_id, channel_id, channel_title, channel_handle,
                 subscriber_count, similarity_score, rank, source)
            VALUES (%s, %s, %s, %s, %s, 0, 99, 'auto')
            ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                channel_title    = EXCLUDED.channel_title,
                channel_handle   = EXCLUDED.channel_handle,
                subscriber_count = EXCLUDED.subscriber_count,
                last_analyzed_at = NOW()
            """,
            (
                workspace_id, channel_id,
                meta.get("title", "")[:200],
                meta.get("handle", ""),
                meta.get("subscriber_count"),
            ),
        )
    conn.commit()

    # Fetch a pool of recent videos
    pool_ids = list_recent_video_ids(channel_id, pool_size, YOUTUBE_API_KEY)
    if not pool_ids:
        return 0
    pool_videos = get_videos_details(pool_ids, YOUTUBE_API_KEY)

    # Select n_best top-viewed + n_worst lowest-viewed for a balanced signal
    pool_sorted = sorted(pool_videos, key=lambda v: v["views"], reverse=True)
    best    = pool_sorted[:n_best]
    others  = pool_sorted[n_best:]
    worst   = others[-n_worst:] if len(others) >= n_worst else others
    videos  = best + worst

    print(
        f"[yt_intel] ingest_channel {channel_id}: "
        f"pool={len(pool_videos)}, best={len(best)}, worst={len(worst)}, total={len(videos)}"
    )

    with conn.cursor() as cur:
        for v in videos:
            cur.execute(
                """
                INSERT INTO yt_competitor_videos
                    (video_id, channel_id, workspace_id, title, description, thumbnail_url,
                     published_at, duration_seconds, views, likes, comments, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (video_id) DO UPDATE SET
                    views      = EXCLUDED.views,
                    likes      = EXCLUDED.likes,
                    comments   = EXCLUDED.comments,
                    updated_at = NOW()
                """,
                (
                    v["video_id"], channel_id, workspace_id,
                    v["title"][:500], (v["description"] or "")[:3000],
                    v["thumbnail_url"], v["published_at"],
                    v["duration_seconds"],
                    v["views"], v["likes"], v["comments"],
                ),
            )
    conn.commit()
    return len(videos)


# ── Layer 1 + 6: Scientific Video Features ────────────────────────────────────

def compute_video_features(workspace_id: str, channel_id: str, conn) -> int:
    """Compute Layers 1 and 6 features for all videos in a channel.

    Layer 1: velocity, engagement_rate, comment_density
    Layer 6: upload_gap_days (gap to previous upload)
    Also: duration_bucket classification

    Writes to yt_video_features. Returns number of rows upserted.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT video_id, published_at, duration_seconds, views, likes, comments
            FROM yt_competitor_videos
            WHERE workspace_id = %s AND channel_id = %s
            ORDER BY published_at ASC
            """,
            (workspace_id, channel_id),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    now = datetime.now(timezone.utc)
    prev_pub = None
    upserted = 0

    with conn.cursor() as cur:
        for video_id, pub_at, dur_secs, views, likes, comments in rows:
            # Age
            if pub_at:
                pub_dt  = pub_at if pub_at.tzinfo else pub_at.replace(tzinfo=timezone.utc)
                age_days = max(1, (now - pub_dt).days)
            else:
                age_days = 1

            velocity        = views / age_days
            engagement_rate = (likes + comments) / max(views, 1)
            comment_density = comments / max(views, 1)

            # Layer 6: upload gap
            gap_days: Optional[float] = None
            if prev_pub is not None and pub_at is not None:
                prev_dt  = prev_pub if prev_pub.tzinfo else prev_pub.replace(tzinfo=timezone.utc)
                curr_dt  = pub_at   if pub_at.tzinfo  else pub_at.replace(tzinfo=timezone.utc)
                gap_days = max(0.0, (curr_dt - prev_dt).total_seconds() / 86400)
            prev_pub = pub_at

            # Duration bucket
            dur = dur_secs or 0
            if dur < 180:
                duration_bucket = "short"
            elif dur <= 600:
                duration_bucket = "medium"
            else:
                duration_bucket = "long"

            cur.execute(
                """
                INSERT INTO yt_video_features
                    (video_id, workspace_id, channel_id, age_days, velocity,
                     engagement_rate, comment_density, upload_gap_days,
                     duration_bucket, is_breakout, computed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, NOW())
                ON CONFLICT (video_id) DO UPDATE SET
                    age_days        = EXCLUDED.age_days,
                    velocity        = EXCLUDED.velocity,
                    engagement_rate = EXCLUDED.engagement_rate,
                    comment_density = EXCLUDED.comment_density,
                    upload_gap_days = EXCLUDED.upload_gap_days,
                    duration_bucket = EXCLUDED.duration_bucket,
                    computed_at     = NOW()
                """,
                (
                    video_id, workspace_id, channel_id,
                    age_days,
                    round(velocity, 4),
                    round(engagement_rate, 6),
                    round(comment_density, 6),
                    round(gap_days, 2) if gap_days is not None else None,
                    duration_bucket,
                ),
            )
            upserted += 1

    conn.commit()
    return upserted


# ── Layer 2: Topic Clustering ─────────────────────────────────────────────────

def build_topic_clusters(workspace_id: str, channel_id: str, conn) -> int:
    """Layer 2: TF-IDF + SVD embeddings + KMeans + Claude Haiku cluster naming.

    Steps:
      1. Load videos with titles + descriptions.
      2. TF-IDF(1-2 ngrams, max_features=500) → TruncatedSVD(50d) embeddings.
      3. Store embeddings in yt_ai_features.embedding_json.
      4. auto_k = min(12, max(4, round(sqrt(n)))).
      5. KMeans(n_clusters=auto_k).
      6. Per cluster: velocity stats + TRS score.
      7. Claude Haiku naming from top-5-velocity titles.
      8. Upsert yt_topic_clusters + update yt_ai_features.topic_cluster_id.

    Returns number of clusters created.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT v.video_id, v.title, v.description, f.velocity
            FROM yt_competitor_videos v
            JOIN yt_video_features f ON f.video_id = v.video_id
            WHERE v.workspace_id = %s AND v.channel_id = %s
            """,
            (workspace_id, channel_id),
        )
        rows = cur.fetchall()

    if len(rows) < 4:
        return 0

    video_ids  = [r[0] for r in rows]
    texts      = [f"{r[1] or ''} {(r[2] or '')[:300]}" for r in rows]
    velocities = [float(r[3] or 0) for r in rows]

    # TF-IDF → SVD
    tfidf = TfidfVectorizer(ngram_range=(1, 2), max_features=500, min_df=1, stop_words='english')
    try:
        X_tfidf = tfidf.fit_transform(texts)
    except ValueError:
        return 0

    n_comp = min(50, X_tfidf.shape[1] - 1, len(texts) - 1)
    if n_comp < 2:
        return 0

    svd    = TruncatedSVD(n_components=n_comp, random_state=42)
    X_emb  = svd.fit_transform(X_tfidf)   # shape: (n_videos, n_comp)

    # KMeans
    k      = _auto_k(len(texts))
    km     = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
    labels = km.fit_predict(X_emb)        # shape: (n_videos,)

    # Channel p75 for hit_rate computation
    sorted_vel = sorted(velocities)
    n          = len(sorted_vel)
    p75        = sorted_vel[min(int(0.75 * n), n - 1)]

    # Last-30-video set for TRS (Topic Recurrence Score)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT video_id FROM yt_competitor_videos
            WHERE workspace_id = %s AND channel_id = %s
            ORDER BY published_at DESC LIMIT 30
            """,
            (workspace_id, channel_id),
        )
        last30_ids: set[str] = {r[0] for r in cur.fetchall()}

    # Store embeddings + cluster IDs in yt_ai_features
    with conn.cursor() as cur:
        for i, vid_id in enumerate(video_ids):
            emb_list = X_emb[i].tolist()
            cur.execute(
                """
                INSERT INTO yt_ai_features (video_id, workspace_id, topic_cluster_id, embedding_json, labeled_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (video_id) DO UPDATE SET
                    topic_cluster_id = EXCLUDED.topic_cluster_id,
                    embedding_json   = EXCLUDED.embedding_json
                """,
                (vid_id, workspace_id, int(labels[i]), json.dumps(emb_list)),
            )
    conn.commit()

    # Per-cluster stats + Claude naming
    client          = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    clusters_created = 0

    for cluster_id in range(k):
        mask         = labels == cluster_id
        cluster_vel  = [velocities[i] for i in range(n) if mask[i]]
        cluster_vids = [video_ids[i]  for i in range(n) if mask[i]]

        if not cluster_vel:
            continue

        avg_vel    = sum(cluster_vel) / len(cluster_vel)
        median_vel = statistics.median(cluster_vel)
        hit_rate   = round(sum(1 for v in cluster_vel if v >= p75) / len(cluster_vel) * 100, 2)
        trs_score  = sum(1 for vid in cluster_vids if vid in last30_ids)

        # Top-5-velocity titles for Claude naming
        paired       = sorted(zip(cluster_vel, cluster_vids), reverse=True)[:5]
        top_titles: list[str] = []
        with conn.cursor() as cur:
            for _, vid in paired:
                cur.execute("SELECT title FROM yt_competitor_videos WHERE video_id = %s", (vid,))
                row = cur.fetchone()
                if row and row[0]:
                    top_titles.append(row[0])

        topic_name = f"Topic {cluster_id + 1}"
        subthemes: list[str] = []

        if top_titles:
            try:
                naming_prompt = (
                    "Given these YouTube video titles from the same content cluster:\n"
                    + "\n".join(f"- {t}" for t in top_titles)
                    + "\n\nReturn JSON with exactly:\n"
                    '- "topic_name": a 2–4 word topic label (e.g. "ECG Home Monitoring")\n'
                    '- "subthemes": array of 2–3 specific subtheme strings\n\n'
                    "Return ONLY valid JSON, no other text."
                )
                resp = client.messages.create(
                    model=CLAUDE_HAIKU,
                    max_tokens=150,
                    messages=[{"role": "user", "content": naming_prompt}],
                )
                parsed    = _safe_json(resp.content[0].text, {})
                topic_name = parsed.get("topic_name", topic_name)
                subthemes  = parsed.get("subthemes", [])
                time.sleep(CLAUDE_SLEEP)
            except Exception as e:
                print(f"[yt_intel] cluster naming error: {e}")

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO yt_topic_clusters
                    (workspace_id, channel_id, topic_cluster_id, topic_name, subthemes,
                     cluster_size, avg_velocity, median_velocity, hit_rate, trs_score, computed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (workspace_id, channel_id, topic_cluster_id) DO UPDATE SET
                    topic_name      = EXCLUDED.topic_name,
                    subthemes       = EXCLUDED.subthemes,
                    cluster_size    = EXCLUDED.cluster_size,
                    avg_velocity    = EXCLUDED.avg_velocity,
                    median_velocity = EXCLUDED.median_velocity,
                    hit_rate        = EXCLUDED.hit_rate,
                    trs_score       = EXCLUDED.trs_score,
                    computed_at     = NOW()
                """,
                (
                    workspace_id, channel_id, cluster_id,
                    topic_name[:200], json.dumps(subthemes),
                    len(cluster_vel),
                    round(avg_vel, 4), round(median_vel, 4),
                    hit_rate, trs_score,
                ),
            )
        conn.commit()
        clusters_created += 1

    return clusters_created


# ── Layers 3–5: Batch AI Labeling ─────────────────────────────────────────────

def label_videos(workspace_id: str, channel_id: str, conn) -> int:
    """Batch AI labeling for all unlabeled (or stale) videos in a channel.

    Processes only videos where labeled_at IS NULL or older than 7 days.
    Rate-limited: 500 ms sleep between each Claude call.
    Returns number of videos labeled.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT v.video_id, v.title, v.description, v.thumbnail_url, v.duration_seconds
            FROM yt_competitor_videos v
            LEFT JOIN yt_ai_features a ON a.video_id = v.video_id
            WHERE v.workspace_id = %s AND v.channel_id = %s
              AND (a.video_id IS NULL OR a.labeled_at < NOW() - INTERVAL '7 days')
            ORDER BY v.published_at DESC
            """,
            (workspace_id, channel_id),
        )
        rows = cur.fetchall()

    if not rows:
        return 0

    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    labeled = 0

    for video_id, title, description, thumbnail_url, duration_seconds in rows:
        title       = title or ""
        description = description or ""

        # Layer 3: Format
        fmt = _classify_format(title, description, duration_seconds or 0, client)
        time.sleep(CLAUDE_SLEEP)

        # Layer 4: Title patterns
        pats = _classify_title_patterns(title, client)
        time.sleep(CLAUDE_SLEEP)

        # Layer 5: Thumbnail vision
        thumb: dict = {}
        if thumbnail_url:
            thumb = _analyze_thumbnail(thumbnail_url, client)
            time.sleep(CLAUDE_SLEEP)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO yt_ai_features
                    (video_id, workspace_id,
                     format_label, format_structure, format_energy,
                     title_patterns, curiosity_score, specificity_score,
                     thumb_face, thumb_text, thumb_emotion, thumb_objects,
                     thumb_style, thumb_readable_text, labeled_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (video_id) DO UPDATE SET
                    format_label        = EXCLUDED.format_label,
                    format_structure    = EXCLUDED.format_structure,
                    format_energy       = EXCLUDED.format_energy,
                    title_patterns      = EXCLUDED.title_patterns,
                    curiosity_score     = EXCLUDED.curiosity_score,
                    specificity_score   = EXCLUDED.specificity_score,
                    thumb_face          = EXCLUDED.thumb_face,
                    thumb_text          = EXCLUDED.thumb_text,
                    thumb_emotion       = EXCLUDED.thumb_emotion,
                    thumb_objects       = EXCLUDED.thumb_objects,
                    thumb_style         = EXCLUDED.thumb_style,
                    thumb_readable_text = EXCLUDED.thumb_readable_text,
                    labeled_at          = NOW()
                """,
                (
                    video_id, workspace_id,
                    fmt["format_label"],
                    json.dumps(fmt["format_structure"]),
                    fmt["format_energy"],
                    json.dumps(pats["title_patterns"]),
                    pats["curiosity_score"],
                    pats["specificity_score"],
                    thumb.get("thumb_face"),
                    thumb.get("thumb_text"),
                    thumb.get("thumb_emotion"),
                    json.dumps(thumb.get("thumb_objects", [])),
                    thumb.get("thumb_style"),
                    thumb.get("thumb_readable_text", ""),
                ),
            )
        conn.commit()
        labeled += 1

    return labeled


# ── Layer 7: Topic Lifecycle ───────────────────────────────────────────────────

def compute_topic_lifecycle(workspace_id: str, channel_id: str, conn) -> None:
    """Layer 7: Compute decay curves and classify topics as evergreen or trend.

    For each topic cluster in the channel:
      - Find first video publication date.
      - Bucket videos by week-since-first-appearance.
      - Compute median velocity per week.
      - peak_velocity = max of weekly medians.
      - half_life_weeks = first week where velocity ≤ 50% of peak.
      - shelf_life = 'evergreen' if any week ≥ 8 has velocity > 50% of peak,
                     'trend' otherwise.
      - UPDATE yt_topic_clusters SET shelf_life, half_life_weeks.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT a.topic_cluster_id
            FROM yt_ai_features a
            JOIN yt_competitor_videos v ON v.video_id = a.video_id
            WHERE v.workspace_id = %s AND v.channel_id = %s
              AND a.topic_cluster_id IS NOT NULL
            """,
            (workspace_id, channel_id),
        )
        cluster_ids = [r[0] for r in cur.fetchall()]

    for cluster_id in cluster_ids:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.published_at, f.velocity
                FROM yt_competitor_videos v
                JOIN yt_video_features  f ON f.video_id = v.video_id
                JOIN yt_ai_features     a ON a.video_id = v.video_id
                WHERE v.workspace_id = %s AND v.channel_id = %s
                  AND a.topic_cluster_id = %s
                ORDER BY v.published_at ASC
                """,
                (workspace_id, channel_id, cluster_id),
            )
            rows = cur.fetchall()

        if len(rows) < 2:
            continue

        first_pub = rows[0][0]
        if first_pub is None:
            continue
        if first_pub.tzinfo is None:
            first_pub = first_pub.replace(tzinfo=timezone.utc)

        # Bucket by weeks since first appearance
        week_vel: dict[int, list[float]] = defaultdict(list)
        for pub_at, vel in rows:
            if pub_at is None:
                continue
            if pub_at.tzinfo is None:
                pub_at = pub_at.replace(tzinfo=timezone.utc)
            week_num = max(0, int((pub_at - first_pub).days / 7))
            week_vel[week_num].append(float(vel or 0))

        weekly_medians: dict[int, float] = {
            w: statistics.median(vels) for w, vels in week_vel.items()
        }
        if not weekly_medians:
            continue

        peak = max(weekly_medians.values())
        if peak <= 0:
            continue

        # Half-life: first week velocity drops to ≤ 50% of peak
        half_life: Optional[int] = None
        for week in sorted(weekly_medians.keys()):
            if weekly_medians[week] <= peak * 0.5:
                half_life = week
                break

        # Evergreen: any week ≥ 8 still above 50% of peak
        later = {w: v for w, v in weekly_medians.items() if w >= 8}
        shelf_life = "evergreen" if (later and max(later.values()) > peak * 0.5) else "trend"

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE yt_topic_clusters
                SET shelf_life = %s, half_life_weeks = %s
                WHERE workspace_id = %s AND channel_id = %s AND topic_cluster_id = %s
                """,
                (shelf_life, half_life, workspace_id, channel_id, cluster_id),
            )
        conn.commit()


# ── Layer 8: Channel Risk Profile ─────────────────────────────────────────────

def compute_channel_profile(workspace_id: str, channel_id: str, conn) -> None:
    """Layer 8: Compute channel velocity distribution stats + risk classification.

    Metrics computed:
      - p25, median (p50), p75, p90 velocity percentiles
      - IQR = p75 - p25
      - std (standard deviation)
      - hit_rate        = % videos above p75
      - underperform_rate = % videos below p25
      - breakout_rate   = % videos above p90
      - risk_profile    = low_variance | medium_variance | high_variance
                         (IQR / median: <0.5 / 0.5–1.5 / >1.5)
      - cadence_pattern = burst | weekly | biweekly | monthly
                         (median_gap: <3d / 3–9d / 10–20d / >20d)

    Upserts into yt_channel_profiles.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.velocity, f.upload_gap_days
            FROM yt_video_features f
            JOIN yt_competitor_videos v ON v.video_id = f.video_id
            WHERE v.workspace_id = %s AND v.channel_id = %s
            """,
            (workspace_id, channel_id),
        )
        rows = cur.fetchall()

    if not rows:
        return

    velocities = [float(r[0] or 0) for r in rows]
    gaps       = [float(r[1]) for r in rows if r[1] is not None]

    vel_arr = np.array(velocities)
    p25  = float(np.percentile(vel_arr, 25))
    p50  = float(np.percentile(vel_arr, 50))
    p75  = float(np.percentile(vel_arr, 75))
    p90  = float(np.percentile(vel_arr, 90))
    iqr  = p75 - p25
    std  = float(np.std(vel_arr))
    n    = len(velocities)

    hit_rate         = round(sum(1 for v in velocities if v >= p75) / n * 100, 2)
    underperform_rate = round(sum(1 for v in velocities if v <= p25) / n * 100, 2)
    breakout_rate    = round(sum(1 for v in velocities if v >= p90) / n * 100, 2)

    ratio = iqr / p50 if p50 > 0 else 0
    if ratio < 0.5:
        risk_profile = "low_variance"
    elif ratio <= 1.5:
        risk_profile = "medium_variance"
    else:
        risk_profile = "high_variance"

    median_gap: Optional[float] = float(statistics.median(gaps)) if gaps else None
    cadence: Optional[str] = None
    if median_gap is not None:
        if median_gap < 3:
            cadence = "burst"
        elif median_gap <= 9:
            cadence = "weekly"
        elif median_gap <= 20:
            cadence = "biweekly"
        else:
            cadence = "monthly"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO yt_channel_profiles
                (workspace_id, channel_id, median_velocity, p25_velocity, p75_velocity, p90_velocity,
                 iqr, std_velocity, hit_rate, underperform_rate, breakout_rate,
                 risk_profile, cadence_pattern, median_gap_days, analyzed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (workspace_id, channel_id) DO UPDATE SET
                median_velocity   = EXCLUDED.median_velocity,
                p25_velocity      = EXCLUDED.p25_velocity,
                p75_velocity      = EXCLUDED.p75_velocity,
                p90_velocity      = EXCLUDED.p90_velocity,
                iqr               = EXCLUDED.iqr,
                std_velocity      = EXCLUDED.std_velocity,
                hit_rate          = EXCLUDED.hit_rate,
                underperform_rate = EXCLUDED.underperform_rate,
                breakout_rate     = EXCLUDED.breakout_rate,
                risk_profile      = EXCLUDED.risk_profile,
                cadence_pattern   = EXCLUDED.cadence_pattern,
                median_gap_days   = EXCLUDED.median_gap_days,
                analyzed_at       = NOW()
            """,
            (
                workspace_id, channel_id,
                round(p50, 4), round(p25, 4), round(p75, 4), round(p90, 4),
                round(iqr, 4), round(std, 4),
                hit_rate, underperform_rate, breakout_rate,
                risk_profile, cadence, round(median_gap, 2) if median_gap is not None else None,
            ),
        )
    conn.commit()


# ── Layer 9: Breakout Model ────────────────────────────────────────────────────

def train_breakout_model(workspace_id: str, conn) -> dict:
    """Layer 9: Train a LogisticRegression breakout prediction model.

    Steps:
      1. Compute global p90 across ALL competitor videos for this workspace.
      2. Mark is_breakout = (velocity >= p90) in yt_video_features.
      3. Load feature matrix:
           - format_label (one-hot)
           - thumb_emotion (one-hot)
           - duration_bucket (one-hot)
           - title_patterns (MultiLabelBinarizer)
           - thumb_face, thumb_text (0/1)
           - upload_gap_days (numeric)
      4. Train LogisticRegression(max_iter=2000, C=1.0, class_weight='balanced').
      5. Extract top 10 feature importances.
      6. Call Claude Sonnet to generate a human-readable playbook from the features.
      7. Upsert yt_breakout_recipe.

    Returns {p90_threshold, breakout_count, top_features, playbook_text}
    or {note: 'insufficient_data'} if fewer than 5 breakout videos found.
    """
    import pandas as pd

    # Step 1: global p90
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT velocity FROM yt_video_features
            WHERE workspace_id = %s
            """,
            (workspace_id,),
        )
        all_vels = [float(r[0] or 0) for r in cur.fetchall()]

    if not all_vels:
        return {"note": "no_data"}

    p90 = float(np.percentile(np.array(all_vels), 90))

    # Step 2: update is_breakout flags
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE yt_video_features
            SET is_breakout = (velocity >= %s)
            WHERE workspace_id = %s
            """,
            (p90, workspace_id),
        )
    conn.commit()

    # Step 3: load feature data
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                f.video_id, f.velocity, f.is_breakout, f.upload_gap_days, f.duration_bucket,
                a.format_label, a.thumb_emotion, a.thumb_face, a.thumb_text, a.title_patterns
            FROM yt_video_features f
            JOIN yt_ai_features a ON a.video_id = f.video_id
            WHERE f.workspace_id = %s
              AND a.format_label IS NOT NULL
            """,
            (workspace_id,),
        )
        rows = cur.fetchall()

    if not rows:
        return {"note": "insufficient_data", "p90_threshold": p90}

    df = pd.DataFrame(rows, columns=[
        "video_id", "velocity", "is_breakout", "upload_gap_days",
        "duration_bucket", "format_label", "thumb_emotion",
        "thumb_face", "thumb_text", "title_patterns",
    ])

    df["is_breakout"]     = df["is_breakout"].astype(int)
    df["format_label"]    = df["format_label"].fillna("unknown")
    df["thumb_emotion"]   = df["thumb_emotion"].fillna("unknown")
    df["duration_bucket"] = df["duration_bucket"].fillna("medium")
    df["upload_gap_days"] = df["upload_gap_days"].fillna(df["upload_gap_days"].median() or 7.0)
    df["thumb_face"]      = df["thumb_face"].fillna(False).astype(float)
    df["thumb_text"]      = df["thumb_text"].fillna(False).astype(float)

    # title_patterns: stored as JSONB list
    def _safe_list(x) -> list:
        if isinstance(x, list):
            return x
        if isinstance(x, str):
            try:
                return json.loads(x)
            except Exception:
                return []
        return []

    df["title_patterns"] = df["title_patterns"].apply(_safe_list)

    breakout_count = int(df["is_breakout"].sum())
    if breakout_count < 5:
        return {"note": "insufficient_data", "p90_threshold": p90, "breakout_count": breakout_count}

    # Build feature matrix
    X_basic = pd.get_dummies(df[["format_label", "thumb_emotion", "duration_bucket"]], drop_first=False)

    mlb   = MultiLabelBinarizer()
    X_pat = pd.DataFrame(
        mlb.fit_transform(df["title_patterns"]),
        columns=[f"pat_{p}" for p in mlb.classes_],
    )

    X = pd.concat([
        X_basic.reset_index(drop=True),
        X_pat.reset_index(drop=True),
    ], axis=1)
    X["thumb_face"]      = df["thumb_face"].values
    X["thumb_text"]      = df["thumb_text"].values
    X["upload_gap_days"] = df["upload_gap_days"].values

    y = df["is_breakout"].values

    # Train
    model = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced", random_state=42)
    model.fit(X, y)

    coefs     = pd.Series(model.coef_[0], index=X.columns)
    coefs_abs = coefs.reindex(coefs.abs().sort_values(ascending=False).index)
    top10     = coefs_abs.head(10).to_dict()

    # Step 6: Claude Sonnet playbook
    features_str = "\n".join(
        f"  {feat}: {'+' if coef > 0 else ''}{coef:.3f}"
        for feat, coef in top10.items()
    )
    playbook_prompt = (
        "You are a YouTube content strategy expert. Based on the following logistic regression "
        "feature importances from a breakout prediction model (positive = increases breakout probability, "
        "negative = decreases), write a concise, actionable playbook paragraph (3–5 sentences) for a "
        "brand channel. Use plain English — no bullet points.\n\n"
        f"Top model features:\n{features_str}\n\n"
        "Write the playbook as if speaking directly to the creator."
    )
    playbook_text = "Analysis in progress."
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp   = client.messages.create(
            model=CLAUDE_SONNET,
            max_tokens=400,
            messages=[{"role": "user", "content": playbook_prompt}],
        )
        playbook_text = resp.content[0].text.strip()
    except Exception as e:
        print(f"[yt_intel] breakout playbook error: {e}")

    # Step 7: upsert
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO yt_breakout_recipe
                (workspace_id, playbook_text, top_features, p90_threshold, breakout_count, trained_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (workspace_id) DO UPDATE SET
                playbook_text  = EXCLUDED.playbook_text,
                top_features   = EXCLUDED.top_features,
                p90_threshold  = EXCLUDED.p90_threshold,
                breakout_count = EXCLUDED.breakout_count,
                trained_at     = NOW()
            """,
            (workspace_id, playbook_text, json.dumps(top10), round(p90, 4), breakout_count),
        )
    conn.commit()

    return {
        "p90_threshold":  round(p90, 4),
        "breakout_count": breakout_count,
        "top_features":   top10,
        "playbook_text":  playbook_text,
    }


# ── Master Orchestrator ────────────────────────────────────────────────────────

# ── Own Channel Analysis (Layer 0 — your channel vs competitors) ──────────────

WORKSPACE_TYPE_CONTEXT: dict = {
    "d2c": {
        "desc": "D2C brand",
        "goal": (
            "Drive product awareness → purchase intent → sales conversions. "
            "Build brand equity through educational content that positions you as an authority. "
            "Each video should serve the funnel: attract new audience → educate → convert to customers."
        ),
        "cta": "Include product link, limited offer, or discount CTA in description and pinned comment",
        "metrics": "Views on product-relevant topics, comment engagement, link clicks, subscriber growth for retargeting",
        "tone": "Brand storytelling + educational authority",
    },
    "creator": {
        "desc": "content creator (individual YouTuber)",
        "goal": (
            "Reach YouTube monetisation threshold (1,000 subscribers + 4,000 watch hours) as fast as possible. "
            "Then maximise CPM, watch time, and brand deal potential. "
            "Consistency and niche authority are your two biggest levers."
        ),
        "cta": "Ask viewers to subscribe, watch the next video, enable notifications",
        "metrics": "Watch time (hours), subscriber growth rate, CTR, average view duration, return viewer %",
        "tone": "Highly engaging, personality-driven, entertaining + educational",
    },
    "saas": {
        "desc": "SaaS company",
        "goal": (
            "Build thought leadership in your space, educate your ideal customer profile (ICP), "
            "and drive trial/demo signups. Every view should be a qualified prospect learning about the problem you solve."
        ),
        "cta": "Free trial link, demo booking, or gated content download in description",
        "metrics": "Qualified subscriber growth, comment quality (are prospects asking product questions?), demo requests",
        "tone": "Expert authority + practical problem-solving",
    },
    "agency": {
        "desc": "agency / service business",
        "goal": (
            "Showcase expertise, attract ideal clients, and position as the go-to agency in your niche. "
            "Drive inbound leads from people who already trust you from watching your content."
        ),
        "cta": "Free audit, strategy call booking, or case study download in description",
        "metrics": "Qualified inbound leads, brand searches, subscriber growth among decision-makers",
        "tone": "Expert authority + results showcase",
    },
    "media": {
        "desc": "media channel / publisher",
        "goal": (
            "Maximise views and watch time for ad revenue. Grow a loyal subscriber base. "
            "Build a recognisable brand in your content category."
        ),
        "cta": "Subscribe, join membership, Patreon/sponsor link",
        "metrics": "Views per video, watch time, subscriber growth, return viewer rate",
        "tone": "Informative + highly entertaining",
    },
}


def _compute_percentile(val: float, p25: float, p50: float, p75: float, p90: float) -> float:
    """Linearly interpolate a percentile rank for *val* given known distribution thresholds."""
    if p25 <= 0:
        return 0.0
    if val >= p90:
        return min(90 + (val - p90) / max(p90 * 0.1, 0.01) * 10, 99)
    elif val >= p75:
        return 75 + (val - p75) / max(p90 - p75, 0.01) * 15
    elif val >= p50:
        return 50 + (val - p50) / max(p75 - p50, 0.01) * 25
    elif val >= p25:
        return 25 + (val - p25) / max(p50 - p25, 0.01) * 25
    else:
        return val / max(p25, 0.01) * 25


def analyze_own_channel(workspace_id: str, channel_id: str, conn) -> dict:
    """Fetch + AI-label own channel's recent videos for competitor comparison.

    Uses the same Claude Haiku pipeline as competitor videos.
    Stores results in yt_own_channel_snapshot.
    Returns {video_count, has_enough (bool, needs >= 5)}.
    """
    vid_ids = list_recent_video_ids(channel_id, OWN_CHANNEL_N + 5, YOUTUBE_API_KEY)
    if not vid_ids:
        print(f"[yt_intel] analyze_own_channel: no videos found for {channel_id}")
        return {"video_count": 0, "has_enough": False}

    videos = get_videos_details(vid_ids, YOUTUBE_API_KEY)
    if len(videos) < 5:
        print(f"[yt_intel] analyze_own_channel: only {len(videos)} videos — need ≥5")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO yt_growth_recipe (workspace_id, own_video_count) "
                "VALUES (%s,%s) ON CONFLICT (workspace_id) DO UPDATE SET own_video_count=%s",
                (workspace_id, len(videos), len(videos)),
            )
        conn.commit()
        return {"video_count": len(videos), "has_enough": False}

    # Most recent N videos
    videos = sorted(videos, key=lambda v: v.get("published_at") or "", reverse=True)
    videos = videos[:OWN_CHANNEL_N]

    now    = datetime.now(timezone.utc)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    labeled: list[dict] = []
    for v in videos:
        pub = v.get("published_at")
        if pub:
            try:
                pub_dt   = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                age_days = max((now - pub_dt).total_seconds() / 86400, 1)
            except Exception:
                age_days = 30
        else:
            age_days = 30

        velocity        = v["views"] / age_days
        engagement_rate = (v["likes"] + v["comments"]) / max(v["views"], 1)
        desc_lower      = (v.get("description") or "").lower()
        title_lower     = v["title"].lower()
        is_short        = v["duration_seconds"] <= 60 and (
            "#shorts" in desc_lower or "#shorts" in title_lower or "shorts" in title_lower
        )

        fmt_r   = _classify_format(v["title"], v.get("description", ""), v["duration_seconds"], client)
        time.sleep(CLAUDE_SLEEP)
        title_r = _classify_title_patterns(v["title"], client)
        time.sleep(CLAUDE_SLEEP)
        thumb_r = _analyze_thumbnail(v.get("thumbnail_url"), client)
        time.sleep(CLAUDE_SLEEP)

        labeled.append({
            "video_id":       v["video_id"],
            "title":          v["title"][:500],
            "published_at":   pub,
            "views":          v["views"],
            "likes":          v["likes"],
            "comments":       v["comments"],
            "duration_seconds": v["duration_seconds"],
            "is_short":       is_short,
            "velocity":       round(velocity, 4),
            "engagement_rate": round(engagement_rate, 6),
            "format_label":   fmt_r.get("format_label"),
            "title_patterns": title_r.get("title_patterns", []),
            "thumb_face":     thumb_r.get("thumb_face"),
            "thumb_emotion":  thumb_r.get("thumb_emotion"),
            "thumb_text":     thumb_r.get("thumb_text"),
        })

    with conn.cursor() as cur:
        for lv in labeled:
            cur.execute(
                """
                INSERT INTO yt_own_channel_snapshot
                    (workspace_id, channel_id, video_id, title, published_at,
                     views, likes, comments, duration_seconds, is_short,
                     velocity, engagement_rate, format_label, title_patterns,
                     thumb_face, thumb_emotion, thumb_text, analyzed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (workspace_id, video_id) DO UPDATE SET
                    views=EXCLUDED.views, velocity=EXCLUDED.velocity,
                    format_label=EXCLUDED.format_label, title_patterns=EXCLUDED.title_patterns,
                    thumb_face=EXCLUDED.thumb_face, thumb_emotion=EXCLUDED.thumb_emotion,
                    thumb_text=EXCLUDED.thumb_text, analyzed_at=NOW()
                """,
                (
                    workspace_id, channel_id, lv["video_id"], lv["title"], lv["published_at"],
                    lv["views"], lv["likes"], lv["comments"], lv["duration_seconds"], lv["is_short"],
                    lv["velocity"], lv["engagement_rate"], lv["format_label"],
                    json.dumps(lv["title_patterns"]),
                    lv["thumb_face"], lv["thumb_emotion"], lv["thumb_text"],
                ),
            )
    conn.commit()
    print(f"[yt_intel] analyze_own_channel: stored {len(labeled)} own videos")
    return {"video_count": len(labeled), "has_enough": True}


def _compute_own_channel_gaps(workspace_id: str, conn) -> dict:
    """Compute own channel velocity percentile + gaps vs competitors."""

    # Own channel velocity avg
    with conn.cursor() as cur:
        cur.execute(
            "SELECT AVG(velocity), COUNT(*) FROM yt_own_channel_snapshot WHERE workspace_id = %s",
            (workspace_id,),
        )
        row = cur.fetchone()
    own_avg_vel = float(row[0] or 0) if row else 0
    own_count   = int(row[1] or 0) if row else 0

    # Competitor velocity distribution (only active competitors via INNER JOIN)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.velocity),
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY f.velocity),
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.velocity),
                PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY f.velocity)
            FROM yt_video_features f
            JOIN yt_competitor_videos v ON v.video_id = f.video_id
            JOIN yt_competitor_channels cc
                ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
            WHERE f.workspace_id = %s
            """,
            (workspace_id,),
        )
        prow = cur.fetchone()
    comp_p25 = float(prow[0] or 0) if prow else 0
    comp_p50 = float(prow[1] or 0) if prow else 0
    comp_p75 = float(prow[2] or 0) if prow else 0
    comp_p90 = float(prow[3] or 0) if prow else 0

    own_percentile = _compute_percentile(own_avg_vel, comp_p25, comp_p50, comp_p75, comp_p90)

    # Own formats used
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT format_label, COUNT(*), AVG(velocity)
            FROM yt_own_channel_snapshot
            WHERE workspace_id = %s AND format_label IS NOT NULL
            GROUP BY format_label ORDER BY COUNT(*) DESC
            """,
            (workspace_id,),
        )
        own_formats = {r[0]: {"count": r[1], "avg_vel": float(r[2] or 0)} for r in cur.fetchall()}

    # Competitor top formats
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.format_label, AVG(f.velocity), COUNT(*)
            FROM yt_ai_features a
            JOIN yt_video_features f ON f.video_id = a.video_id
            JOIN yt_competitor_videos v ON v.video_id = a.video_id
            JOIN yt_competitor_channels cc
                ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
            WHERE f.workspace_id = %s AND a.format_label IS NOT NULL
            GROUP BY a.format_label ORDER BY AVG(f.velocity) DESC LIMIT 6
            """,
            (workspace_id,),
        )
        comp_formats = [{"format": r[0], "avg_vel": float(r[1] or 0), "count": int(r[2])} for r in cur.fetchall()]

    missing_formats = [f for f in comp_formats if f["format"] not in own_formats]

    # Thumbnail gap
    with conn.cursor() as cur:
        cur.execute(
            "SELECT AVG(CASE WHEN thumb_face THEN 1.0 ELSE 0 END) FROM yt_own_channel_snapshot "
            "WHERE workspace_id = %s AND thumb_face IS NOT NULL",
            (workspace_id,),
        )
        ofr = cur.fetchone()
    own_face_rate = float(ofr[0] or 0) if ofr else 0

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.thumb_face, AVG(f.velocity)
            FROM yt_ai_features a
            JOIN yt_video_features f ON f.video_id = a.video_id
            JOIN yt_competitor_videos v ON v.video_id = a.video_id
            JOIN yt_competitor_channels cc
                ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
            WHERE f.workspace_id = %s AND a.thumb_face IS NOT NULL
            GROUP BY a.thumb_face
            """,
            (workspace_id,),
        )
        comp_face = {bool(r[0]): float(r[1] or 0) for r in cur.fetchall()}

    thumb_insight = ""
    if True in comp_face and False in comp_face:
        if comp_face[True] > comp_face[False] and own_face_rate < 0.4:
            thumb_insight = (
                f"Face thumbnails average {comp_face[True]:.0f} views/day vs {comp_face[False]:.0f} without face. "
                f"Your channel uses faces only {own_face_rate*100:.0f}% of the time — increase this significantly."
            )
        elif comp_face.get(False, 0) > comp_face.get(True, 0) and own_face_rate > 0.6:
            thumb_insight = (
                f"No-face thumbnails outperform in this niche ({comp_face.get(False,0):.0f} vs "
                f"{comp_face.get(True,0):.0f} views/day). Your {own_face_rate*100:.0f}% face rate may be limiting reach."
            )

    return {
        "own_video_count":        own_count,
        "own_velocity_avg":       round(own_avg_vel, 2),
        "own_velocity_percentile": round(min(own_percentile, 99), 1),
        "comp_p25":               round(comp_p25, 2),
        "comp_p50":               round(comp_p50, 2),
        "comp_p75":               round(comp_p75, 2),
        "comp_p90":               round(comp_p90, 2),
        "own_formats":            own_formats,
        "comp_formats_top":       comp_formats,
        "missing_formats":        missing_formats,
        "thumbnail_insight":      thumb_insight,
    }


def generate_growth_recipe(workspace_id: str, workspace_type: str, conn) -> dict:
    """Generate a 15-day + 30-day growth plan using Claude Sonnet.

    Uses all available competitor intelligence + own channel gaps.
    Workspace-type-aware: d2c / creator / saas / agency / media.
    Stores result in yt_growth_recipe table.
    Returns dict with plan sections.
    """
    ctx  = WORKSPACE_TYPE_CONTEXT.get(workspace_type, WORKSPACE_TYPE_CONTEXT["d2c"])
    gaps = _compute_own_channel_gaps(workspace_id, conn)

    # ── Load context data ──────────────────────────────────────────────────────

    # Top topic clusters
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tc.topic_name, tc.avg_velocity, tc.shelf_life, tc.subthemes
            FROM yt_topic_clusters tc
            INNER JOIN yt_competitor_channels cc
                ON cc.workspace_id = tc.workspace_id AND cc.channel_id = tc.channel_id
            WHERE tc.workspace_id = %s
            ORDER BY tc.avg_velocity DESC LIMIT 15
            """,
            (workspace_id,),
        )
        top_topics = cur.fetchall()

    # Best formats
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.format_label, AVG(f.velocity), COUNT(*)
            FROM yt_ai_features a
            JOIN yt_video_features f ON f.video_id = a.video_id
            JOIN yt_competitor_videos v ON v.video_id = a.video_id
            JOIN yt_competitor_channels cc
                ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
            WHERE f.workspace_id = %s AND a.format_label IS NOT NULL
            GROUP BY a.format_label ORDER BY AVG(f.velocity) DESC LIMIT 6
            """,
            (workspace_id,),
        )
        top_formats = cur.fetchall()

    # Title patterns + uplift
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.title_patterns, f.velocity
            FROM yt_ai_features a
            JOIN yt_video_features f ON f.video_id = a.video_id
            JOIN yt_competitor_videos v ON v.video_id = a.video_id
            JOIN yt_competitor_channels cc
                ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
            WHERE f.workspace_id = %s AND a.title_patterns IS NOT NULL
            """,
            (workspace_id,),
        )
        rows = cur.fetchall()

    from collections import defaultdict
    pat_vels: dict = defaultdict(list)
    for pats_raw, vel in rows:
        for p in (pats_raw if isinstance(pats_raw, list) else []):
            pat_vels[p].append(float(vel or 0))

    all_vels   = [v for vlist in pat_vels.values() for v in vlist]
    base_vel   = sum(all_vels) / max(len(all_vels), 1)
    top_patterns = sorted(
        [{"pattern": p, "avg_vel": sum(v) / len(v),
          "uplift": round((sum(v)/len(v) - base_vel) / max(base_vel, 0.01) * 100, 1)}
         for p, v in pat_vels.items()],
        key=lambda x: x["avg_vel"], reverse=True,
    )[:7]

    # Thumbnail winners
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.thumb_face, a.thumb_text, a.thumb_emotion, AVG(f.velocity), COUNT(*)
            FROM yt_ai_features a
            JOIN yt_video_features f ON f.video_id = a.video_id
            JOIN yt_competitor_videos v ON v.video_id = a.video_id
            JOIN yt_competitor_channels cc
                ON cc.workspace_id = v.workspace_id AND cc.channel_id = v.channel_id
            WHERE f.workspace_id = %s AND a.thumb_face IS NOT NULL
            GROUP BY a.thumb_face, a.thumb_text, a.thumb_emotion
            ORDER BY AVG(f.velocity) DESC LIMIT 5
            """,
            (workspace_id,),
        )
        top_thumb = cur.fetchall()

    # Cadence leaders
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cp.cadence_pattern, cp.median_gap_days, cp.breakout_rate, cc.channel_title
            FROM yt_channel_profiles cp
            INNER JOIN yt_competitor_channels cc
                ON cc.workspace_id = cp.workspace_id AND cc.channel_id = cp.channel_id
            WHERE cp.workspace_id = %s
            ORDER BY cp.breakout_rate DESC LIMIT 3
            """,
            (workspace_id,),
        )
        cadence_rows = cur.fetchall()

    # Breakout playbook
    with conn.cursor() as cur:
        cur.execute(
            "SELECT playbook_text, p90_threshold FROM yt_breakout_recipe WHERE workspace_id = %s",
            (workspace_id,),
        )
        br = cur.fetchone()
    breakout_text = (br[0] or "No breakout model trained yet.") if br else "No breakout model trained yet."
    p90_threshold = float(br[1] or 0) if br else 0

    # Own channel title sample
    with conn.cursor() as cur:
        cur.execute(
            "SELECT title, velocity FROM yt_own_channel_snapshot WHERE workspace_id = %s "
            "ORDER BY published_at DESC LIMIT 10",
            (workspace_id,),
        )
        own_titles = cur.fetchall()

    # Channel name
    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_id FROM platform_connections "
            "WHERE workspace_id = %s AND platform = 'youtube' ORDER BY updated_at DESC LIMIT 1",
            (workspace_id,),
        )
        pc_row = cur.fetchone()
    own_channel_id   = pc_row[0] if pc_row else None
    own_channel_meta = get_channel_meta(own_channel_id, YOUTUBE_API_KEY) if own_channel_id else {}

    # ── Build prompt strings ───────────────────────────────────────────────────

    topics_str = "\n".join([
        f"  - {t[0]} ({t[2] or 'unknown'} shelf-life) — {float(t[1] or 0):.0f} views/day. Subthemes: {', '.join((t[3] or [])[:3])}"
        for t in top_topics
    ]) or "  - No data yet"

    formats_str = "\n".join([
        f"  - {str(f[0]).replace('_',' ')}: {float(f[1] or 0):.0f} views/day avg ({int(f[2])} videos)"
        for f in top_formats
    ]) or "  - No data yet"

    patterns_str = "\n".join([
        f"  - {p['pattern'].replace('_',' ')}: {p['avg_vel']:.0f} views/day  ({'+' if p['uplift'] >= 0 else ''}{p['uplift']}% vs baseline)"
        for p in top_patterns
    ]) or "  - No data yet"

    thumb_str = "\n".join([
        f"  - {'Face' if t[0] else 'No face'} + {'Text overlay' if t[1] else 'No text'} + {t[2] or 'neutral'}: {float(t[3] or 0):.0f} views/day ({int(t[4])} videos)"
        for t in top_thumb
    ]) or "  - No data yet"

    cadence_str = "\n".join([
        f"  - {r[3] or r[0]} — {r[0]} cadence ({float(r[1] or 0):.0f} days between uploads), {float(r[2] or 0)*100:.0f}% breakout rate"
        for r in cadence_rows
    ]) or "  - No cadence data yet"

    own_titles_str = "\n".join([
        f"  - \"{t[0]}\" — {float(t[1] or 0):.0f} views/day"
        for t in own_titles
    ]) or "  - No own videos yet"

    missing_fmts_str = "\n".join([
        f"  - {f['format'].replace('_',' ')}: competitors avg {f['avg_vel']:.0f} views/day — you don't use this format"
        for f in gaps.get("missing_formats", [])[:3]
    ]) or "  - No major format gaps"

    channel_title = own_channel_meta.get("title", "Your channel")
    sub_count     = own_channel_meta.get("subscriber_count", 0) or 0

    # ── Claude Sonnet prompt ───────────────────────────────────────────────────
    prompt = f"""You are a YouTube growth strategist. Based on real competitor intelligence, generate an extremely specific, actionable growth plan.

## Channel: {channel_title}
Channel type: {ctx['desc']}
Subscribers: {sub_count:,}
Your recent video performance: {gaps['own_velocity_avg']:.0f} avg views/day
Your percentile vs competitors: {gaps['own_velocity_percentile']:.0f}th percentile
Competitor benchmarks: P25={gaps['comp_p25']:.0f} | median={gaps['comp_p50']:.0f} | P75={gaps['comp_p75']:.0f} | Breakout (P90)={gaps['comp_p90']:.0f} views/day

## Your Recent Videos (and their performance)
{own_titles_str}

## Strategic Goal
{ctx['goal']}

## What Works for Competitors (from real data)

**Top Topics by views/day:**
{topics_str}

**Best Content Formats:**
{formats_str}

**Title Patterns (with velocity uplift vs average):**
{patterns_str}

**Thumbnail Combinations that Win:**
{thumb_str}

**Upload Cadence of Top Performers:**
{cadence_str}

**Breakout Formula (ML analysis of top-10% videos):**
{breakout_text}
Breakout threshold: {p90_threshold:.0f} views/day

## Your Gaps vs Competitors
- Format gaps (you don't use): {missing_fmts_str}
- Thumbnail gap: {gaps.get('thumbnail_insight') or 'No clear gap detected'}

---

Generate the complete growth plan. Be EXTREMELY specific — use actual topic names from the data, actual numbers, specific visual directions. Write as if briefing a video creator who will start shooting tomorrow. No vague advice.

### 15-Day Sprint Plan
Pick optimal upload days based on cadence data. For each video:

**Video [N] — Day [X]:**
- Topic: [specific topic name from the data, not generic]
- Why this works: [1 sentence backed by the data]
- Format: [specific format from taxonomy — and why]
- Title Option 1: [ready to copy-paste, uses a winning pattern]
- Title Option 2: [different angle]
- Title Option 3: [different angle]
- Opening hook (first 15–20 seconds): [exact script — what to say to hook viewers]
- Thumbnail direction: [face or no-face, exact emotion expression, exact text overlay words, background style, what to avoid]
- CTA to include: [{ctx['cta']}]

### 30-Day Roadmap

**Week 1 (Days 1–7):**
- Upload days: [specific]
- Content pillar: [topic cluster name and why now]
- Format focus: [and why]
- Expected outcome: [realistic, data-backed]

**Week 2 (Days 8–14):**
[same structure]

**Week 3 (Days 15–21):**
[same structure]

**Week 4 (Days 22–30):**
[same structure]

### Thumbnail Creative Brief
Based on what wins in this niche (real data). Specific visual rules for your next 5 thumbnails: face in frame or not, expression, text overlay — exact wording style, font weight, color palette, background, what NOT to do (common mistakes in your current thumbnails).

### 10 Hook Lines to Use
Opening lines (first 20 seconds) that work in this niche. Ready to use — just swap in your topic. Include the psychological trigger each one uses.

### 5 Emerging Topics to Own Now
Topics gaining velocity in competitor data but not yet saturated. Why each is an opportunity right now.

Success metrics to track: {ctx['metrics']}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp   = client.messages.create(
        model=CLAUDE_SONNET, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    recipe_text = resp.content[0].text

    # ── Parse sections (flexible — handles ##/###/**header** variations) ────────
    def _find_section(text: str, keywords: list[str]) -> int:
        """Return start index of the first section whose header contains any keyword (case-insensitive)."""
        lines = text.split("\n")
        pos = 0
        for line in lines:
            stripped = line.strip().lower()
            # Match markdown headings (## / ###) or bold lines (**...**)
            if stripped.startswith("#") or (stripped.startswith("**") and stripped.endswith("**")):
                for kw in keywords:
                    if kw.lower() in stripped:
                        return pos
            pos += len(line) + 1  # +1 for newline
        return -1

    def _extract_section(text: str, keywords: list[str], next_keyword_groups: list[list[str]]) -> str:
        start = _find_section(text, keywords)
        if start == -1:
            return ""
        end = len(text)
        for nkg in next_keyword_groups:
            ni = _find_section(text[start + 1:], nkg)
            if ni != -1:
                candidate = start + 1 + ni
                if candidate < end:
                    end = candidate
        return text[start:end].strip()

    plan_15d    = _extract_section(recipe_text,
        ["15-day", "15 day", "sprint plan", "sprint"],
        [["30-day", "30 day", "roadmap"], ["thumbnail"], ["hook"], ["emerging", "topic"]])

    plan_30d    = _extract_section(recipe_text,
        ["30-day", "30 day", "roadmap"],
        [["thumbnail"], ["hook"], ["emerging", "topic"]])

    thumb_brief = _extract_section(recipe_text,
        ["thumbnail", "creative brief"],
        [["hook"], ["emerging", "topic"]])

    hooks       = _extract_section(recipe_text,
        ["hook line", "hook"],
        [["emerging", "topic"]])

    emerging    = _extract_section(recipe_text,
        ["emerging topic", "emerging"],
        [])

    # Fallback: if all sections are empty, the full text IS the plan
    sections_empty = not any([plan_15d, plan_30d, thumb_brief, hooks, emerging])
    if sections_empty:
        print("[yt_intel] WARNING: section parser found no headers — storing full text as plan_15d")
        plan_15d = recipe_text   # surface the full text in the primary section

    # ── Upsert to DB ──────────────────────────────────────────────────────────
    gaps_json = json.dumps({
        "topic_gaps":      [],    # Claude handles this via prompt
        "missing_formats": gaps.get("missing_formats", []),
        "thumbnail_insight": gaps.get("thumbnail_insight", ""),
        "own_formats":     list(gaps.get("own_formats", {}).keys()),
    })

    # Ensure recipe_text column exists (added in v24b migration)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO yt_growth_recipe
                    (workspace_id, own_video_count, own_velocity_avg, own_velocity_percentile,
                     content_gaps, plan_15d, plan_30d, thumbnail_brief, hooks_library,
                     emerging_topics, recipe_text, generated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (workspace_id) DO UPDATE SET
                    own_video_count          = EXCLUDED.own_video_count,
                    own_velocity_avg         = EXCLUDED.own_velocity_avg,
                    own_velocity_percentile  = EXCLUDED.own_velocity_percentile,
                    content_gaps             = EXCLUDED.content_gaps,
                    plan_15d                 = EXCLUDED.plan_15d,
                    plan_30d                 = EXCLUDED.plan_30d,
                    thumbnail_brief          = EXCLUDED.thumbnail_brief,
                    hooks_library            = EXCLUDED.hooks_library,
                    emerging_topics          = EXCLUDED.emerging_topics,
                    recipe_text              = EXCLUDED.recipe_text,
                    generated_at             = NOW()
                """,
                (
                    workspace_id, gaps["own_video_count"], gaps["own_velocity_avg"],
                    gaps["own_velocity_percentile"], gaps_json,
                    plan_15d, plan_30d, thumb_brief, hooks, emerging, recipe_text,
                ),
            )
        conn.commit()
    except Exception:
        # recipe_text column may not exist yet — fall back to without it
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO yt_growth_recipe
                    (workspace_id, own_video_count, own_velocity_avg, own_velocity_percentile,
                     content_gaps, plan_15d, plan_30d, thumbnail_brief, hooks_library,
                     emerging_topics, generated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (workspace_id) DO UPDATE SET
                    own_video_count          = EXCLUDED.own_video_count,
                    own_velocity_avg         = EXCLUDED.own_velocity_avg,
                    own_velocity_percentile  = EXCLUDED.own_velocity_percentile,
                    content_gaps             = EXCLUDED.content_gaps,
                    plan_15d                 = EXCLUDED.plan_15d,
                    plan_30d                 = EXCLUDED.plan_30d,
                    thumbnail_brief          = EXCLUDED.thumbnail_brief,
                    hooks_library            = EXCLUDED.hooks_library,
                    emerging_topics          = EXCLUDED.emerging_topics,
                    generated_at             = NOW()
                """,
                (
                    workspace_id, gaps["own_video_count"], gaps["own_velocity_avg"],
                    gaps["own_velocity_percentile"], gaps_json,
                    plan_15d, plan_30d, thumb_brief, hooks, emerging,
                ),
            )
        conn.commit()

    return {
        "own_video_count":        gaps["own_video_count"],
        "own_velocity_percentile": gaps["own_velocity_percentile"],
        "plan_15d":   plan_15d,
        "plan_30d":   plan_30d,
        "thumbnail_brief": thumb_brief,
        "hooks_library":   hooks,
        "emerging_topics": emerging,
        "recipe_text":     recipe_text,
    }


# ── Phase Orchestrators ────────────────────────────────────────────────────────

def run_discovery_phase(workspace_id: str, job_id: int) -> dict:
    """Phase 1: Discover competitors, compute topic spaces, then set awaiting_confirmation.

    Called from FastAPI BackgroundTasks.
    Sets discovery_status = 'discovering' → (live logs throughout) → 'awaiting_confirmation'.
    """
    from services.agent_swarm.db import get_conn

    def _set_ds(conn, discovery_status: str):
        """Set discovery_status on the job row (silent if column missing)."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE yt_analysis_jobs SET discovery_status = %s WHERE id = %s",
                    (discovery_status, job_id),
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    try:
        with get_conn() as conn:
            _set_ds(conn, "discovering")

            # Get seed channel
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT account_id FROM platform_connections
                    WHERE workspace_id = %s AND platform = 'youtube'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
            seed_channel_id = row[0] if row else None

            if not seed_channel_id:
                _log_to_job(conn, job_id, {"type": "error", "msg": "No YouTube channel connected. Please connect your YouTube channel first."})
                _set_ds(conn, "error")
                return {"error": "no_youtube_channel"}

            _log_to_job(conn, job_id, {"type": "info", "msg": "Starting competitor discovery…"})

            discover_competitors(
                workspace_id, seed_channel_id, conn,
                final_k=MAX_COMPETITORS, job_id=job_id,
            )

            # Even if 0 found (e.g. quota hit mid-search), move to awaiting_confirmation
            # so user can still add manual channels
            _set_ds(conn, "awaiting_confirmation")
            print(f"[yt_intel] discovery phase complete for {workspace_id} — awaiting confirmation")

    except QuotaExceededError as e:
        print(f"[yt_intel] run_discovery_phase QUOTA EXCEEDED")
        try:
            with get_conn() as conn:
                _log_to_job(conn, job_id, {"type": "error", "msg": "YouTube API daily quota exceeded. Discovery stopped. You can still add competitor channels manually, or retry tomorrow after midnight Pacific Time."})
                _set_ds(conn, "awaiting_confirmation")  # allow manual channel input
        except Exception:
            pass
    except Exception as e:
        print(f"[yt_intel] run_discovery_phase ERROR: {e}")
        try:
            with get_conn() as conn:
                _log_to_job(conn, job_id, {"type": "error", "msg": f"Discovery failed: {str(e)[:200]}"})
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE yt_analysis_jobs SET discovery_status = %s WHERE id = %s",
                            ("error", job_id),
                        )
                    conn.commit()
                except Exception:
                    pass
        except Exception:
            pass

    return {}


def run_analysis_phase(workspace_id: str, job_id: int) -> dict:
    """Phase 2: Run full 9-layer pipeline on confirmed competitors + own channel + growth recipe.

    Called from FastAPI BackgroundTasks after user confirms competitor list.
    Sets discovery_status = 'analyzing' → (pipeline) → 'completed'.
    """
    from services.agent_swarm.db import get_conn

    def _set_ds(conn, discovery_status: str):
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE yt_analysis_jobs SET discovery_status = %s WHERE id = %s",
                    (discovery_status, job_id),
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    def _set_job(conn, status: str, **kwargs):
        sets = ["status = %s"]
        vals = [status]
        if status == "running":
            sets.append("started_at = NOW()")
        if status in ("completed", "failed"):
            sets.append("completed_at = NOW()")
        for k, v in kwargs.items():
            sets.append(f"{k} = %s")
            vals.append(v)
        vals.append(job_id)
        with conn.cursor() as cur:
            cur.execute(f"UPDATE yt_analysis_jobs SET {', '.join(sets)} WHERE id = %s", vals)
        conn.commit()

    def _try_set_phase(conn, phase: str):
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE yt_analysis_jobs SET phase = %s WHERE id = %s", (phase, job_id))
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    channels_done = 0
    videos_done   = 0

    try:
        with get_conn() as conn:
            _set_ds(conn, "analyzing")
            _set_job(conn, "running")
            _try_set_phase(conn, "competitor_analysis")

            # Get seed channel
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT account_id FROM platform_connections
                    WHERE workspace_id = %s AND platform = 'youtube'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
            seed_channel_id = row[0] if row else None

            # Load confirmed competitors (already upserted by discovery / confirm step)
            # No LIMIT here — manual channels have rank=99 and must be included too
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT channel_id FROM yt_competitor_channels WHERE workspace_id = %s ORDER BY rank",
                    (workspace_id,),
                )
                competitor_ids = [r[0] for r in cur.fetchall()]

            total_channels = len(competitor_ids)
            _log_to_job(conn, job_id, {
                "type": "info",
                "msg": f"Starting deep analysis on {total_channels} competitor channel(s)…",
            })

            # Per-channel 9-layer pipeline
            for ch_id in competitor_ids:
                print(f"[yt_intel] analysing channel {ch_id}")
                _log_to_job(conn, job_id, {"type": "info", "msg": f"Analysing: {ch_id}…"})
                n = ingest_channel(workspace_id, ch_id, conn)
                videos_done += n
                compute_video_features(workspace_id, ch_id, conn)
                label_videos(workspace_id, ch_id, conn)
                build_topic_clusters(workspace_id, ch_id, conn)
                compute_topic_lifecycle(workspace_id, ch_id, conn)
                compute_channel_profile(workspace_id, ch_id, conn)
                channels_done += 1
                _set_job(conn, "running", channels_analyzed=channels_done,
                         videos_analyzed=videos_done, channels_total=total_channels)

            train_breakout_model(workspace_id, conn)

            # Own channel + growth recipe
            if seed_channel_id:
                _try_set_phase(conn, "own_channel_analysis")
                _log_to_job(conn, job_id, {"type": "info", "msg": "Analysing your channel performance…"})
                own_result = analyze_own_channel(workspace_id, seed_channel_id, conn)

                if own_result.get("has_enough", False):
                    with conn.cursor() as cur:
                        cur.execute("SELECT workspace_type FROM workspaces WHERE id = %s", (workspace_id,))
                        wt_row = cur.fetchone()
                    workspace_type = (wt_row[0] or "d2c") if wt_row else "d2c"

                    _try_set_phase(conn, "growth_recipe")
                    _log_to_job(conn, job_id, {"type": "info", "msg": "Generating your personalised growth plan…"})
                    generate_growth_recipe(workspace_id, workspace_type, conn)

            _set_job(conn, "completed", channels_analyzed=channels_done, videos_analyzed=videos_done)
            _try_set_phase(conn, "completed")
            _set_ds(conn, "completed")

            # Auto-trigger Growth OS plan generation
            try:
                from services.agent_swarm.core.growth_os import generate_action_plan as _gen_gos
                _log_to_job(conn, job_id, {"type": "info", "msg": "Generating Growth OS cross-platform action plan…"})
                _gen_gos(workspace_id, conn)
                _log_to_job(conn, job_id, {"type": "info", "msg": "Growth OS action plan refreshed — check Growth OS page."})
            except Exception as e:
                print(f"[growth_os] auto-generate failed (non-fatal): {e}")

            _log_to_job(conn, job_id, {
                "type": "complete",
                "msg": f"Analysis complete — {channels_done} channels, {videos_done} videos processed",
            })

    except Exception as e:
        print(f"[yt_intel] run_analysis_phase ERROR: {e}")
        try:
            with get_conn() as conn:
                _set_job(conn, "failed", error=str(e)[:500])
                _set_ds(conn, "error")
        except Exception:
            pass

    return {"channels_analyzed": channels_done, "videos_analyzed": videos_done}


# ── Master Orchestrator ────────────────────────────────────────────────────────

def run_full_analysis(workspace_id: str, job_id: int) -> dict:
    """Run the complete 9-layer competitor intelligence pipeline + own channel comparison.

    Called from FastAPI BackgroundTasks — must not raise unhandled exceptions.
    Updates yt_analysis_jobs status throughout.
    Returns summary dict.
    """
    from services.agent_swarm.db import get_conn  # local import to avoid circular

    def _set_job(conn, status: str, **kwargs):
        sets = ["status = %s"]
        vals = [status]
        if status == "running":
            sets.append("started_at = NOW()")
        if status in ("completed", "failed"):
            sets.append("completed_at = NOW()")
        for k, v in kwargs.items():
            sets.append(f"{k} = %s")
            vals.append(v)
        vals.append(job_id)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE yt_analysis_jobs SET {', '.join(sets)} WHERE id = %s",
                vals,
            )
        conn.commit()

    def _try_set_phase(conn, phase: str):
        """Silently update job phase — ignores errors if column doesn't exist yet."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE yt_analysis_jobs SET phase = %s WHERE id = %s",
                    (phase, job_id),
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    channels_done = 0
    videos_done   = 0

    try:
        with get_conn() as conn:
            _set_job(conn, "running")
            _try_set_phase(conn, "competitor_analysis")

            # Get seed channel from platform_connections
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT account_id FROM platform_connections
                    WHERE workspace_id = %s AND platform = 'youtube'
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (workspace_id,),
                )
                row = cur.fetchone()
            seed_channel_id = row[0] if row else None

            # How many competitors already registered?
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM yt_competitor_channels WHERE workspace_id = %s",
                    (workspace_id,),
                )
                comp_count = cur.fetchone()[0]

            if comp_count < MAX_COMPETITORS and seed_channel_id:
                print(f"[yt_intel] discovering competitors for {workspace_id}")
                discover_competitors(workspace_id, seed_channel_id, conn, final_k=MAX_COMPETITORS)

            # Load all competitor channel_ids
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT channel_id FROM yt_competitor_channels WHERE workspace_id = %s ORDER BY rank LIMIT %s",
                    (workspace_id, MAX_COMPETITORS),
                )
                competitor_ids = [r[0] for r in cur.fetchall()]

            total_channels = len(competitor_ids)
            print(f"[yt_intel] will process {total_channels} competitor channels")

            # Per-channel pipeline
            for ch_id in competitor_ids:
                print(f"[yt_intel] processing channel {ch_id}")
                n  = ingest_channel(workspace_id, ch_id, conn)
                videos_done += n
                compute_video_features(workspace_id, ch_id, conn)
                label_videos(workspace_id, ch_id, conn)
                build_topic_clusters(workspace_id, ch_id, conn)
                compute_topic_lifecycle(workspace_id, ch_id, conn)
                compute_channel_profile(workspace_id, ch_id, conn)
                channels_done += 1
                _set_job(conn, "running", channels_analyzed=channels_done, videos_analyzed=videos_done,
                         channels_total=total_channels)

            # Global breakout model
            train_breakout_model(workspace_id, conn)

            # ── Own channel analysis + growth recipe ──────────────────────────
            if seed_channel_id:
                _try_set_phase(conn, "own_channel_analysis")
                print(f"[yt_intel] analysing own channel {seed_channel_id}")
                own_result = analyze_own_channel(workspace_id, seed_channel_id, conn)

                if own_result.get("has_enough", False):
                    # Fetch workspace_type for recipe generation
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT workspace_type FROM workspaces WHERE id = %s",
                            (workspace_id,),
                        )
                        wt_row = cur.fetchone()
                    workspace_type = (wt_row[0] or "d2c") if wt_row else "d2c"

                    _try_set_phase(conn, "growth_recipe")
                    print(f"[yt_intel] generating growth recipe (type={workspace_type})")
                    generate_growth_recipe(workspace_id, workspace_type, conn)
                else:
                    print(f"[yt_intel] own channel has <5 videos — skipping growth recipe")

            _set_job(conn, "completed", channels_analyzed=channels_done, videos_analyzed=videos_done)
            _try_set_phase(conn, "completed")

    except Exception as e:
        print(f"[yt_intel] run_full_analysis ERROR: {e}")
        try:
            with get_conn() as conn:
                _set_job(conn, "failed", error=str(e)[:500])
        except Exception:
            pass

    return {"channels_analyzed": channels_done, "videos_analyzed": videos_done}
