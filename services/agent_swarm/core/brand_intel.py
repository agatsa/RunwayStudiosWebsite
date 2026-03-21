"""
services/agent_swarm/core/brand_intel.py

Brand Intelligence — 9-layer competitive analysis engine.

Mirrors the YouTube Competitor Intelligence architecture:
  Phase 1 — Discovery (live-streaming JSONB log, ~30s)
  Phase 2 — Deep Analysis (all 9 layers per competitor, ~3-5 min)

DB pattern: callers pass a live psycopg2 conn.
"""

import json
import uuid
import asyncio
import re
from datetime import datetime, timezone
from typing import Optional

import anthropic

from services.agent_swarm.config import ANTHROPIC_API_KEY
from services.agent_swarm.connectors.brand_scraper import (
    fetch_page, fetch_text, try_sub_pages, strip_html,
    detect_tech_stack, extract_social_links, extract_fb_page_handle,
    fetch_meta_ads, jina_read, jina_search, search_ddg, serp_presence,
    scrape_trustpilot, scrape_g2,
    extract_domain, extract_brand_name,
)

CLAUDE_SONNET = "claude-sonnet-4-6"
CLAUDE_HAIKU  = "claude-haiku-4-5-20251001"

MAX_COMPETITORS = 5


# ── DB helpers ──────────────────────────────────────────────────────────────────

def _log(conn, job_id: str, entry: dict):
    """Append a log entry to brand_intel_jobs.discovery_log (JSONB array)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE brand_intel_jobs
                   SET discovery_log = discovery_log || %s::jsonb,
                       updated_at    = NOW()
                 WHERE id = %s::uuid
                """,
                (json.dumps([{**entry, "ts": datetime.now(timezone.utc).isoformat()}]), job_id),
            )
        conn.commit()
    except Exception as e:
        print(f"[brand_intel] _log failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def _set_status(conn, job_id: str, status: str, discovery_status: str = None):
    try:
        with conn.cursor() as cur:
            if discovery_status:
                cur.execute(
                    "UPDATE brand_intel_jobs SET status=%s, discovery_status=%s, updated_at=NOW() WHERE id=%s::uuid",
                    (status, discovery_status, job_id),
                )
            else:
                cur.execute(
                    "UPDATE brand_intel_jobs SET status=%s, updated_at=NOW() WHERE id=%s::uuid",
                    (status, job_id),
                )
        conn.commit()
    except Exception as e:
        print(f"[brand_intel] _set_status failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def _save_candidates(conn, job_id: str, candidates: list):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE brand_intel_jobs SET discovery_candidates=%s::jsonb, updated_at=NOW() WHERE id=%s::uuid",
                (json.dumps(candidates), job_id),
            )
        conn.commit()
    except Exception as e:
        print(f"[brand_intel] _save_candidates failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


# ── Phase 1: Discovery ──────────────────────────────────────────────────────────

async def run_discovery_phase(
    job_id: str,
    workspace_id: str,
    brand_url: str,
    workspace_type: str,
    conn,
):
    """
    Phase 1: Scrape own brand, find competitor candidates via web search,
    stream progress to discovery_log, set awaiting_confirmation.
    """
    _set_status(conn, job_id, "discovering", "discovering")
    _log(conn, job_id, {"type": "start", "msg": "Starting brand discovery…"})

    # ── Step 1: Scrape own brand ──────────────────────────────────────────────
    own_domain = extract_domain(brand_url) if brand_url else ""
    own_name   = extract_brand_name(own_domain) if own_domain else "Your Brand"

    _log(conn, job_id, {"type": "info", "msg": f"Fetching your brand page: {brand_url}"})

    # Use Jina reader for clean text (bypasses Cloudflare/bot protection)
    own_text = await jina_read(brand_url, max_chars=3000) if brand_url else ""
    own_html, own_headers = await fetch_page(brand_url) if brand_url else ("", {})

    # Save own topic space keywords to DB
    own_keywords = _extract_keywords(own_text, n=12) if own_text else []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE brand_intel_jobs SET own_topic_space=%s::jsonb, updated_at=NOW() WHERE id=%s::uuid",
                (json.dumps(own_keywords), job_id),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

    _log(conn, job_id, {
        "type": "own_brand",
        "msg": f"Your brand scanned: {own_name}",
        "keywords": own_keywords,
    })

    # ── Step 2: Claude Haiku — directly identify competitor domains ──────────────
    _log(conn, job_id, {"type": "info", "msg": "Asking ARIA to identify competitors…"})

    type_labels = {
        "d2c": "D2C / e-commerce product brand",
        "saas": "SaaS product or mobile app",
        "agency": "marketing or creative agency",
        "creator": "content creator / media brand",
        "media": "media company",
    }
    type_label = type_labels.get(workspace_type, "brand")

    candidate_urls: dict[str, dict] = {}   # domain → {url, title, hit_count}

    skip_domains = {
        "reddit.com", "quora.com", "trustpilot.com", "g2.com",
        "capterra.com", "producthunt.com", "techcrunch.com",
        "wikipedia.org", "youtube.com", "twitter.com", "x.com",
        "linkedin.com", "facebook.com", "instagram.com",
        "medium.com", "substack.com", "amazon.com", "flipkart.com",
        "google.com", "bing.com", "duckduckgo.com",
    }

    # Primary: Ask Claude Haiku to directly name competitor domains using its world knowledge
    claude_competitors = []
    if own_text or brand_url:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model=CLAUDE_HAIKU,
                max_tokens=700,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Brand: {own_name}\n"
                        f"Website: {brand_url}\n"
                        f"Type: {type_label}\n"
                        f"Brand page content:\n{own_text[:2000]}\n\n"
                        "Based on the brand page content and your world knowledge, "
                        "list the 6 most direct competitors to this brand "
                        "(same product category, similar price range, similar target audience).\n\n"
                        "Return ONLY a valid JSON array, no explanation:\n"
                        '[{"domain": "competitor.com", "name": "Brand Name", "reason": "same category + audience"}]\n\n'
                        "Use real, verifiable competitor domains. "
                        "If this is an Indian brand, prioritise Indian competitors first."
                    ),
                }],
            )
            raw = msg.content[0].text.strip()
            start = raw.find("[")
            if start != -1:
                claude_competitors = json.loads(raw[start:raw.rfind("]") + 1])
                _log(conn, job_id, {
                    "type": "info",
                    "msg": f"ARIA identified {len(claude_competitors)} competitor candidates",
                })
        except Exception as e:
            print(f"[brand_intel] claude competitor discovery failed: {e}")

    # Add Claude's suggestions to candidate pool (high initial hit_count = high priority)
    for item in claude_competitors:
        dom = extract_domain(item.get("domain", ""))
        if not dom or dom == own_domain or any(s in dom for s in skip_domains):
            continue
        if dom not in candidate_urls:
            candidate_urls[dom] = {
                "url": f"https://{dom}",
                "domain": dom,
                "title": item.get("name", dom),
                "reason": item.get("reason", ""),
                "hit_count": 3,  # Claude-suggested gets priority score
            }

    # ── Step 3: Web search (DDG) as secondary signal ──────────────────────────
    _log(conn, job_id, {"type": "info", "msg": "Running web searches to validate competitors…"})

    # Generate 2 search queries from Claude
    search_queries = []
    if own_text or brand_url:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model=CLAUDE_HAIKU,
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Brand: {own_name} ({brand_url}), type: {type_label}\n"
                        "Give 2 Google search queries to find direct competitors of this brand.\n"
                        "Return ONLY a JSON array of 2 query strings."
                    ),
                }],
            )
            raw = msg.content[0].text.strip()
            start = raw.find("[")
            if start != -1:
                search_queries = json.loads(raw[start:raw.rfind("]") + 1])
        except Exception:
            pass

    if not search_queries:
        search_queries = [
            f"{own_name} alternatives",
            f"{own_domain} competitors",
        ]

    for query in search_queries[:2]:
        _log(conn, job_id, {"type": "search", "msg": f"Searching: {query}"})
        results = await search_ddg(query, max_results=8)
        await asyncio.sleep(0.5)

        for r in results:
            url   = r.get("url", "")
            title = r.get("title", "")
            dom   = extract_domain(url)
            if not dom or dom == own_domain:
                continue
            if any(s in dom for s in skip_domains):
                continue
            if dom not in candidate_urls:
                candidate_urls[dom] = {
                    "url": url.split("?")[0].rstrip("/"),
                    "domain": dom,
                    "title": title,
                    "hit_count": 1,
                }
            else:
                candidate_urls[dom]["hit_count"] += 1

    # ── Step 4: Score + validate top candidates ───────────────────────────────
    sorted_candidates = sorted(
        candidate_urls.values(),
        key=lambda x: x["hit_count"],
        reverse=True,
    )[:MAX_COMPETITORS + 3]

    validated = []
    for cand in sorted_candidates:
        if len(validated) >= MAX_COMPETITORS:
            break
        _log(conn, job_id, {"type": "checking", "msg": f"Checking: {cand['domain']}"})
        # Use Jina reader for reliable page fetch (bypasses bot protection)
        root = f"https://{cand['domain']}"
        text = await jina_read(root, max_chars=1500)
        html, _ = await fetch_page(root)  # also need raw HTML for tech stack
        # Claude-suggested competitors (hit_count=3) are accepted even if page fetch fails
        is_claude_suggested = cand.get("hit_count", 0) >= 3
        if not text and not html and not is_claude_suggested:
            continue
        if not text:
            text = strip_html(html)[:1500] if html else cand.get("reason", "")[:400]
        cand["url"] = root
        text = text[:800]
        keywords = _extract_keywords(text, n=8)
        # Confidence: based on keyword overlap + hit count
        overlap = len(set(own_keywords) & set(keywords)) if own_keywords else 0
        confidence = min(95, 40 + overlap * 8 + cand["hit_count"] * 10)

        name = _extract_brand_name_from_html(html) or extract_brand_name(cand["domain"])
        cand.update({
            "name": name,
            "confidence_pct": confidence,
            "topic_space": keywords,
            "is_auto": True,
            "confirmed": False,
        })
        validated.append(cand)
        _log(conn, job_id, {
            "type": "candidate",
            "msg": f"Found competitor: {name} ({cand['domain']}) — {confidence}% match",
            "domain": cand["domain"],
            "name": name,
            "confidence_pct": confidence,
            "topic_space": keywords,
        })
        await asyncio.sleep(0.3)

    _save_candidates(conn, job_id, validated)
    _set_status(conn, job_id, "awaiting_confirmation", "awaiting_confirmation")
    _log(conn, job_id, {
        "type": "done",
        "msg": f"Discovery complete — {len(validated)} competitor candidates found. Please review and confirm.",
    })


# ── Phase 2: Deep Analysis ──────────────────────────────────────────────────────

async def run_analysis_phase(
    job_id: str,
    workspace_id: str,
    brand_url: str,
    workspace_type: str,
    meta_access_token: str,
    conn,
):
    """
    Phase 2: Run all 9 analysis layers on each confirmed competitor,
    then analyse own brand, then generate growth recipe.
    """
    _set_status(conn, job_id, "analysing", "analysing")
    _log(conn, job_id, {"type": "info", "msg": "Starting deep competitive analysis…"})

    # Load confirmed competitors
    with conn.cursor() as cur:
        cur.execute(
            "SELECT discovery_candidates FROM brand_intel_jobs WHERE id=%s::uuid",
            (job_id,),
        )
        row = cur.fetchone()
    candidates = (row[0] or []) if row else []
    confirmed  = [c for c in candidates if c.get("confirmed")]

    if not confirmed:
        _log(conn, job_id, {"type": "warn", "msg": "No confirmed competitors — skipping analysis."})
        _set_status(conn, job_id, "completed", "completed")
        return

    total = len(confirmed)
    _log(conn, job_id, {"type": "info", "msg": f"Analysing {total} competitor(s)…"})

    for i, cand in enumerate(confirmed):
        url   = cand.get("url", f"https://{cand.get('domain', '')}")
        name  = cand.get("name", extract_brand_name(cand.get("domain", "")))
        domain = cand.get("domain", extract_domain(url))
        profile_id = str(uuid.uuid4())

        _log(conn, job_id, {"type": "phase", "msg": f"[{i+1}/{total}] Analysing {name}…"})

        # Upsert profile row early so we can update incrementally
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO brand_competitor_profiles
                        (id, job_id, workspace_id, competitor_url, competitor_name,
                         confidence_pct, confirmed, is_auto)
                    VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, TRUE, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (profile_id, job_id, workspace_id, url, name,
                     cand.get("confidence_pct", 0), cand.get("is_auto", True)),
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

        # ── Layer 1: Brand DNA ────────────────────────────────────────────────
        _log(conn, job_id, {"type": "layer", "msg": f"  Layer 1: Brand DNA — {name}"})
        brand_dna = await _analyse_brand_dna(url, name, workspace_type)

        # ── Layer 2: Meta Ads ─────────────────────────────────────────────────
        _log(conn, job_id, {"type": "layer", "msg": f"  Layer 2: Meta Ad Library — {name}"})
        fb_handle = brand_dna.get("facebook_handle") or name
        meta_ads = []
        if meta_access_token:
            meta_ads = fetch_meta_ads(fb_handle, meta_access_token, limit=20)
            if not meta_ads:
                meta_ads = fetch_meta_ads(domain, meta_access_token, limit=20)
        meta_ads_summary = _summarise_meta_ads(meta_ads, name)

        # ── Layer 3: SERP presence ────────────────────────────────────────────
        _log(conn, job_id, {"type": "layer", "msg": f"  Layer 3: SERP presence — {name}"})
        serp = await serp_presence(name, domain)

        # ── Layer 4: Content strategy ─────────────────────────────────────────
        _log(conn, job_id, {"type": "layer", "msg": f"  Layer 4: Content strategy — {name}"})
        content = await _analyse_content_strategy(url)

        # ── Layer 5: Pricing intel ────────────────────────────────────────────
        _log(conn, job_id, {"type": "layer", "msg": f"  Layer 5: Pricing intel — {name}"})
        pricing = await _analyse_pricing(url, name)

        # ── Layer 6: Review intel ─────────────────────────────────────────────
        _log(conn, job_id, {"type": "layer", "msg": f"  Layer 6: Review intel — {name}"})
        reviews = await _get_review_intel(domain, name)

        # ── Layer 7: Tech stack ───────────────────────────────────────────────
        _log(conn, job_id, {"type": "layer", "msg": f"  Layer 7: Tech stack — {name}"})
        html, headers = await fetch_page(url)
        tech_stack = detect_tech_stack(html, headers)

        # ── Save full profile ─────────────────────────────────────────────────
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE brand_competitor_profiles
                       SET brand_dna        = %s::jsonb,
                           meta_ads         = %s::jsonb,
                           serp_presence    = %s::jsonb,
                           content_strategy = %s::jsonb,
                           pricing_intel    = %s::jsonb,
                           review_intel     = %s::jsonb,
                           tech_stack       = %s::jsonb,
                           updated_at       = NOW()
                     WHERE id = %s::uuid
                    """,
                    (
                        json.dumps(brand_dna),
                        json.dumps({"ads": meta_ads, "summary": meta_ads_summary}),
                        json.dumps(serp),
                        json.dumps(content),
                        json.dumps(pricing),
                        json.dumps(reviews),
                        json.dumps(tech_stack),
                        profile_id,
                    ),
                )
            conn.commit()
        except Exception as e:
            print(f"[brand_intel] save profile failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

        _log(conn, job_id, {"type": "done_competitor", "msg": f"  ✓ {name} analysed"})
        await asyncio.sleep(0.5)

    # ── Layer 8: Own brand analysis ───────────────────────────────────────────
    _log(conn, job_id, {"type": "phase", "msg": "Analysing your own brand…"})
    own_profile = await _analyse_brand_dna(brand_url, "Your Brand", workspace_type) if brand_url else {}
    own_pricing  = await _analyse_pricing(brand_url, "Your Brand") if brand_url else {}
    own_html, own_headers = await fetch_page(brand_url) if brand_url else ("", {})
    own_tech = detect_tech_stack(own_html, own_headers)
    own_meta_ads = fetch_meta_ads(
        extract_brand_name(extract_domain(brand_url)),
        meta_access_token,
        limit=10,
    ) if meta_access_token and brand_url else []

    own_brand_data = {
        **own_profile,
        "pricing": own_pricing,
        "tech_stack": own_tech,
        "meta_ads": own_meta_ads,
    }

    # ── Layer 9: Growth Recipe ────────────────────────────────────────────────
    _log(conn, job_id, {"type": "phase", "msg": "Generating growth recipe with ARIA…"})
    await generate_brand_growth_recipe(
        workspace_id, job_id, own_brand_data, workspace_type, conn
    )

    _set_status(conn, job_id, "completed", "completed")
    _log(conn, job_id, {"type": "done", "msg": "Brand Intelligence analysis complete!"})


# ── Layer helpers ───────────────────────────────────────────────────────────────

async def _analyse_brand_dna(url: str, name: str, workspace_type: str) -> dict:
    """Layer 1: Scrape homepage + about page via Jina, extract brand identity via Claude Haiku."""
    # Use Jina for reliable text extraction
    homepage_text = await jina_read(url, max_chars=2500)
    # Also get raw HTML for social link extraction
    html, _ = await fetch_page(url)
    social = extract_social_links(html) if html else {}
    fb_handle = extract_fb_page_handle(html) if html else None

    # Sub-pages via Jina
    about_text = await jina_read(f"{url.rstrip('/')}/about", max_chars=1500)
    if not about_text:
        about_text = await jina_read(f"{url.rstrip('/')}/about-us", max_chars=1500)

    combined = f"Homepage:\n{homepage_text}\n\n"
    if about_text:
        combined += f"/about:\n{about_text}\n\n"
    combined = combined[:3500]

    result = {
        "name": name,
        "url": url,
        "social_links": social,
        "facebook_handle": fb_handle,
        "tagline": "",
        "icp": "",
        "uvp": "",
        "key_messages": [],
        "cta": "",
        "positioning": "",
    }

    if not combined.strip():
        return result

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_HAIKU,
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": (
                    f"Analyse this brand ({name}) and extract structured intel.\n\n"
                    f"Page content:\n{combined}\n\n"
                    "Return ONLY valid JSON with these keys:\n"
                    '{"tagline":"","icp":"ideal customer in 1 sentence","uvp":"unique value prop in 1 sentence",'
                    '"key_messages":["msg1","msg2","msg3"],"cta":"primary CTA text","positioning":"market positioning in 1 sentence"}'
                ),
            }],
        )
        raw = msg.content[0].text.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            parsed = json.loads(raw[start:end])
            result.update(parsed)
    except Exception as e:
        print(f"[brand_intel] brand_dna failed for {name}: {e}")

    return result


async def _analyse_content_strategy(base_url: str) -> dict:
    """Layer 4: Scrape blog/resources to infer content pillars and cadence."""
    pages = await try_sub_pages(
        base_url,
        ["blog", "resources", "articles", "insights", "news"],
        max_chars=2000,
    )
    if not pages:
        return {"found": False, "pillars": [], "cadence": "unknown"}

    combined = "\n".join(list(pages.values())[:2])[:2500]
    # Extract post titles as a rough proxy for topics
    titles = re.findall(r'<h[23][^>]*>(.*?)</h[23]>', combined, re.IGNORECASE)
    titles = [strip_html(t)[:80] for t in titles if len(t) > 5][:12]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_HAIKU,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Blog/content titles: {json.dumps(titles)}\n\n"
                    "Infer: (1) top 3 content pillars, (2) estimated posting cadence, "
                    "(3) primary SEO intent (awareness/consideration/conversion).\n"
                    "Return JSON: "
                    '{"pillars":["p1","p2","p3"],"cadence":"weekly|biweekly|monthly","seo_intent":"..."}'
                ),
            }],
        )
        raw = msg.content[0].text.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            return {**json.loads(raw[start:end]), "found": True, "titles": titles}
    except Exception:
        pass

    return {"found": bool(titles), "titles": titles, "pillars": [], "cadence": "unknown"}


async def _analyse_pricing(base_url: str, name: str) -> dict:
    """Layer 5: Scrape pricing page, extract tiers and price points via Claude Haiku."""
    pages = await try_sub_pages(base_url, ["pricing", "plans", "packages"], max_chars=2500)
    if not pages:
        return {"found": False, "tiers": []}

    text = list(pages.values())[0]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_HAIKU,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"Pricing page content for {name}:\n{text}\n\n"
                    "Extract pricing tiers. Return JSON:\n"
                    '{"found":true,"currency":"INR|USD|etc",'
                    '"tiers":[{"name":"Free","price":"0","billing":"month",'
                    '"key_features":["f1","f2"]}],'
                    '"has_free_tier":false,"has_trial":false}'
                ),
            }],
        )
        raw = msg.content[0].text.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except Exception:
        pass

    return {"found": True, "raw_text": text[:500], "tiers": []}


async def _get_review_intel(domain: str, name: str) -> dict:
    """Layer 6: Scrape Trustpilot + G2, combine into review intel."""
    tp, g2 = await asyncio.gather(
        scrape_trustpilot(domain),
        scrape_g2(name),
    )
    combined_snippets = (tp.get("snippets") or []) + (g2.get("snippets") or [])
    pain_points = []
    wins = []

    if combined_snippets:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model=CLAUDE_HAIKU,
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Customer review snippets for {name}:\n"
                        + "\n".join(combined_snippets[:6])
                        + "\n\nExtract: top 3 pain points and top 3 winning features.\n"
                        "JSON: {\"pain_points\":[\"p1\",\"p2\",\"p3\"],\"wins\":[\"w1\",\"w2\",\"w3\"]}"
                    ),
                }],
            )
            raw = msg.content[0].text.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                parsed = json.loads(raw[start:end])
                pain_points = parsed.get("pain_points", [])
                wins = parsed.get("wins", [])
        except Exception:
            pass

    return {
        "trustpilot": tp,
        "g2": g2,
        "pain_points": pain_points,
        "wins": wins,
        "snippet_count": len(combined_snippets),
    }


def _summarise_meta_ads(ads: list, name: str) -> dict:
    """Summarise Meta Ad Library results into intel signals."""
    if not ads:
        return {"found": False, "ad_count": 0}

    # Longest-running = most likely winning creative
    def days_running(ad):
        try:
            from datetime import date
            d = datetime.fromisoformat(ad["start_date"]).date()
            return (date.today() - d).days
        except Exception:
            return 0

    ads_sorted = sorted(ads, key=days_running, reverse=True)
    winning = ads_sorted[:3]

    platform_counts: dict = {}
    for ad in ads:
        for p in ad.get("platforms", []):
            platform_counts[p] = platform_counts.get(p, 0) + 1

    return {
        "found": True,
        "ad_count": len(ads),
        "winning_creatives": [
            {
                "body": a["body"],
                "title": a["title"],
                "days_running": days_running(a),
                "platforms": a["platforms"],
            }
            for a in winning
        ],
        "platform_mix": platform_counts,
        "top_message_themes": _extract_ad_themes(ads),
    }


def _extract_ad_themes(ads: list) -> list:
    """Extract recurring themes from ad copy bodies."""
    theme_keywords = {
        "discount": ["off", "sale", "discount", "save", "deal", "%"],
        "social_proof": ["customers", "users", "reviews", "trusted", "rated", "stars"],
        "urgency": ["limited", "hurry", "ends", "today", "last chance", "now"],
        "feature_led": ["track", "monitor", "analytics", "automate", "dashboard"],
        "emotion": ["feel", "love", "amazing", "transform", "life-changing"],
        "free_trial": ["free", "trial", "try", "demo", "no credit card"],
    }
    theme_counts: dict = {}
    all_text = " ".join(
        (a.get("body") or "") + " " + (a.get("title") or "")
        for a in ads
    ).lower()
    for theme, keywords in theme_keywords.items():
        if any(k in all_text for k in keywords):
            theme_counts[theme] = sum(all_text.count(k) for k in keywords)
    return sorted(theme_counts, key=lambda t: theme_counts[t], reverse=True)[:4]


# ── Layer 9: Growth Recipe ──────────────────────────────────────────────────────

async def generate_brand_growth_recipe(
    workspace_id: str,
    job_id: str,
    own_brand: dict,
    workspace_type: str,
    conn,
) -> dict:
    """
    Layer 9: Claude Sonnet synthesis of all competitor intel → growth recipe.
    Saves to brand_growth_recipe table.
    """
    # Load all competitor profiles for this job
    profiles = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT competitor_name, brand_dna, meta_ads, pricing_intel,
                       review_intel, tech_stack, serp_presence
                  FROM brand_competitor_profiles
                 WHERE job_id=%s::uuid
                """,
                (job_id,),
            )
            for row in cur.fetchall():
                profiles.append({
                    "name":      row[0],
                    "brand_dna": row[1] or {},
                    "meta_ads":  row[2] or {},
                    "pricing":   row[3] or {},
                    "reviews":   row[4] or {},
                    "tech":      row[5] or [],
                    "serp":      row[6] or {},
                })
    except Exception as e:
        print(f"[brand_intel] load profiles failed: {e}")

    prompt = _build_recipe_prompt(own_brand, profiles, workspace_type)

    recipe_text = ""
    competitive_gaps = []
    ad_angle_opportunities = []

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_SONNET,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        recipe_text = raw

        # Also parse structured output
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                parsed = json.loads(raw[start:end])
                competitive_gaps        = parsed.get("competitive_gaps", [])
                ad_angle_opportunities  = parsed.get("ad_angle_opportunities", [])
                recipe_text             = parsed.get("recipe_narrative", raw)
            except Exception:
                pass
    except Exception as e:
        print(f"[brand_intel] recipe generation failed: {e}")

    recipe_id = str(uuid.uuid4())
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO brand_growth_recipe
                    (id, workspace_id, job_id, own_brand_profile,
                     competitive_gaps, ad_angle_opportunities, recipe_text)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s::jsonb,
                        %s::jsonb, %s::jsonb, %s)
                """,
                (
                    recipe_id, workspace_id, job_id,
                    json.dumps(own_brand),
                    json.dumps(competitive_gaps),
                    json.dumps(ad_angle_opportunities),
                    recipe_text,
                ),
            )
        conn.commit()
    except Exception as e:
        print(f"[brand_intel] save recipe failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return {
        "id": recipe_id,
        "competitive_gaps": competitive_gaps,
        "ad_angle_opportunities": ad_angle_opportunities,
        "recipe_text": recipe_text,
    }


def _build_recipe_prompt(own: dict, competitors: list, workspace_type: str) -> str:
    type_labels = {
        "d2c": "D2C / e-commerce product brand",
        "saas": "SaaS product or mobile app",
        "agency": "marketing or creative agency",
        "creator": "content creator / media brand",
        "media": "media company",
    }
    wt = type_labels.get(workspace_type, "brand")

    comp_summaries = []
    for c in competitors[:4]:
        ads_summary = c.get("meta_ads", {}).get("summary", {})
        pricing = c.get("pricing", {})
        reviews = c.get("reviews", {})
        brand   = c.get("brand_dna", {})
        comp_summaries.append(
            f"### Competitor: {c['name']}\n"
            f"- Positioning: {brand.get('positioning', 'N/A')}\n"
            f"- UVP: {brand.get('uvp', 'N/A')}\n"
            f"- Pricing: {json.dumps(pricing.get('tiers', []))[:200]}\n"
            f"- Active ads: {ads_summary.get('ad_count', 0)} | "
            f"Winning themes: {', '.join(ads_summary.get('top_message_themes', []))}\n"
            f"- Customer pain points: {', '.join(reviews.get('pain_points', []))}\n"
            f"- Customer wins: {', '.join(reviews.get('wins', []))}\n"
            f"- Tech stack: {', '.join(c.get('tech', []))}\n"
        )

    own_summary = (
        f"### Your Brand\n"
        f"- Positioning: {own.get('positioning', 'N/A')}\n"
        f"- UVP: {own.get('uvp', 'N/A')}\n"
        f"- Pricing: {json.dumps(own.get('pricing', {}).get('tiers', []))[:200]}\n"
        f"- Tech stack: {', '.join(own.get('tech_stack', []))}\n"
        f"- Running ads: {len(own.get('meta_ads', []))}\n"
    )

    return f"""You are an elite growth strategist. Analyse this competitive landscape for a {wt}.

{own_summary}

## Competitor Intelligence
{chr(10).join(comp_summaries)}

## Your Task
Generate a comprehensive competitive growth strategy. Return a JSON object with these keys:

1. "competitive_gaps": array of 5 objects — gaps/opportunities vs competitors
   Each: {{"gap":"description","opportunity":"how to exploit","priority":"high|medium|low"}}

2. "ad_angle_opportunities": array of 6 objects — winning ad angles to test
   Each: {{"angle":"hook/angle name","headline":"example headline","body":"example ad copy 40 words","why_it_works":"reason based on competitor analysis"}}

3. "recipe_narrative": a markdown string with:
   - **Executive Summary** (2 sentences)
   - **Where You Win** — your unfair advantages vs each competitor
   - **Their Playbook** — what's working for competitors (ad themes, pricing, content)
   - **Your Attack Plan** — 30-day action roadmap (10 bullet points)
   - **Pricing Strategy** — recommended positioning vs competitors
   - **Ad Strategy** — top 3 ad angles to test immediately with rationale

Return ONLY valid JSON. No markdown code fences."""


# ── Gather intel for Growth OS ──────────────────────────────────────────────────

def gather_brand_intel(workspace_id: str, conn) -> dict:
    """
    Called by growth_os.gather_intelligence() to include brand intel signals.
    Returns empty keys gracefully if no brand intel exists.
    """
    result = {
        "brand_competitors": [],
        "brand_ad_angles": [],
        "brand_gaps": [],
        "brand_recipe": None,
    }
    try:
        with conn.cursor() as cur:
            # Latest completed job
            cur.execute(
                """
                SELECT id FROM brand_intel_jobs
                 WHERE workspace_id=%s::uuid AND status='completed'
                 ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
            if not row:
                return result
            job_id = row[0]

            # Competitor profiles (brief summaries)
            cur.execute(
                """
                SELECT competitor_name, brand_dna, meta_ads, pricing_intel, review_intel
                  FROM brand_competitor_profiles
                 WHERE job_id=%s::uuid AND confirmed=TRUE
                """,
                (str(job_id),),
            )
            for prow in cur.fetchall():
                ads = (prow[2] or {}).get("summary", {})
                result["brand_competitors"].append({
                    "name": prow[0],
                    "positioning": (prow[1] or {}).get("positioning", ""),
                    "uvp": (prow[1] or {}).get("uvp", ""),
                    "ad_themes": ads.get("top_message_themes", []),
                    "pain_points": (prow[4] or {}).get("pain_points", []),
                })

            # Latest growth recipe
            cur.execute(
                """
                SELECT competitive_gaps, ad_angle_opportunities, recipe_text
                  FROM brand_growth_recipe
                 WHERE workspace_id=%s::uuid
                 ORDER BY created_at DESC LIMIT 1
                """,
                (workspace_id,),
            )
            rrow = cur.fetchone()
            if rrow:
                result["brand_gaps"]       = rrow[0] or []
                result["brand_ad_angles"]  = rrow[1] or []
                result["brand_recipe"]     = (rrow[2] or "")[:1000]
    except Exception as e:
        print(f"[brand_intel] gather failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass

    return result


# ── Utilities ───────────────────────────────────────────────────────────────────

def _extract_keywords(text: str, n: int = 10) -> list:
    """Simple TF-IDF-lite keyword extraction using word frequency."""
    stop = {
        "the","a","an","and","or","but","in","on","at","to","for","of","with",
        "is","are","was","were","be","been","have","has","had","will","would",
        "can","could","should","may","might","this","that","these","those",
        "we","our","your","their","its","it","he","she","they","you","i",
        "not","no","more","all","any","each","from","by","as","so","if","do",
        "get","use","also","just","how","what","when","which","who","about",
        "new","one","two","free","best","top","help","need","want","like",
        "com","www","https","http","page",
    }
    words = re.findall(r"[a-z]{4,}", text.lower())
    freq: dict = {}
    for w in words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:n]]


def _extract_brand_name_from_html(html: str) -> Optional[str]:
    """Try to extract brand name from <title> or og:site_name."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        t = strip_html(m.group(1)).strip()
        # Remove common suffixes: "- Home", "| Official Site", etc.
        t = re.split(r"\s*[-|–—]\s*", t)[0].strip()
        if 2 < len(t) < 50:
            return t
    og = re.search(r'property=["\']og:site_name["\'][^>]*content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if og:
        return og.group(1).strip()
    return None
