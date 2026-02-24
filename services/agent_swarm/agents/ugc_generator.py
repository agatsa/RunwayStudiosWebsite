# services/agent_swarm/agents/ugc_generator.py
"""
UGC Video Ad Generator — full pipeline:

1. Pull performance context + scrape landing page
2. Claude generates UGC script (testimonial) + lifestyle scene prompt
3. HeyGen renders AI avatar video (~3-5 min, polls until done)
4. fal.ai Kling animates product photo into lifestyle clip (~2 min)
5. Save both to video_queue DB
6. Send WhatsApp video previews with copy + approve/reject commands
"""
import json
import re
import uuid
from datetime import datetime, timezone

import anthropic
import requests

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    PRODUCT_CONTEXT, LANDING_PAGE_URL,
    WA_REPORT_NUMBER,
)
from services.agent_swarm.db import get_conn
from services.agent_swarm.wa import send_text, send_video
from services.agent_swarm.creative.video_gen import (
    generate_ugc_heygen,
    generate_lifestyle_video_kling,
    get_default_heygen_avatar,
)

_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


# ── Claude: generate UGC concepts ──────────────────────────

def _generate_ugc_concepts(
    product_context: str,
    page_content: str = None,
    perf_summary: str = "",
) -> dict:
    """
    Claude writes:
    - A 15-20 second UGC testimonial script (natural Indian English, spoken)
    - A lifestyle scene prompt for Kling (what to animate from the product photo)
    - Ad copy for both (primary_text, headline, cta)
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    live_section = ""
    if page_content:
        live_section = f"\n=== LIVE PAGE CONTENT ===\n{page_content[:2000]}\n"

    prompt = f"""You are a performance marketer creating UGC-style video ad concepts for an Indian D2C brand.

=== PRODUCT ===
{product_context[:600]}
{live_section}
=== RECENT PERFORMANCE ===
{perf_summary or 'No performance data available.'}

=== TASK ===
Generate 2 video ad concepts — one talking avatar testimonial (HeyGen) and one lifestyle product video (Kling).

RULES for the UGC testimonial script:
- Spoken naturally, like a real Indian customer (28-55 years old, working professional)
- 60-80 words max (approx 15-20 seconds when spoken at normal pace)
- First 5 words must be a strong hook that stops the scroll
- IMPORTANT: The avatar will appear in front of the product photo as the background — write the script as if the speaker is holding/wearing/showing the product. Reference it naturally ("this device", "this band", "see this").
- Mention a specific benefit, result, or feeling — not generic praise
- End with a soft CTA ("I got mine from their website, link in bio")
- Do NOT sound like an ad. Sound like a genuine WhatsApp voice note.

RULES for the lifestyle scene prompt (for Kling image-to-video):
- You are animating the ACTUAL PRODUCT PHOTO into a video — the product must stay central and clearly visible
- Describe natural motion: gentle float, slow zoom in, soft light rays, morning light sweep — keep it subtle so the product doesn't distort
- Be cinematic: warm lighting, Indian home or office setting, clean background
- 30-50 words, very visual and specific
- Do NOT describe people or hands — only the product and environment

Return ONLY valid JSON (no markdown):
{{
  "ugc": {{
    "angle": "short concept name (5 words max)",
    "script": "full spoken script here (60-80 words)",
    "headline": "bold text below video (40 chars max)",
    "primary_text": "full ad body copy (80-120 words, written text for the feed post)",
    "cta": "Shop Now"
  }},
  "lifestyle": {{
    "angle": "short concept name (5 words max)",
    "scene_prompt": "cinematic scene prompt for Kling (30-50 words)",
    "headline": "bold text below video (40 chars max)",
    "primary_text": "full ad body copy (80-120 words)",
    "cta": "Order Now"
  }}
}}"""

    resp = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if m:
            raw = m.group(1).strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        return json.loads(m.group())
    return json.loads(raw)


# ── DB helpers ──────────────────────────────────────────────

def _save_video(
    tenant_id: str,
    account_id: str,
    video_type: str,
    concept: dict,
    video_url: str,
    avatar_id: str = "",
    voice_id: str = "",
    heygen_video_id: str = "",
    landing_page_url: str = None,
    daily_budget_inr: float = 300,
) -> str:
    video_id = str(uuid.uuid4())
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO video_queue
                      (id, tenant_id, platform, account_id, video_type, angle,
                       script, scene_prompt, heygen_video_id, avatar_id, voice_id,
                       video_url, primary_text, headline, cta,
                       landing_page_url, daily_budget_inr, status)
                    VALUES (%s,%s,'meta',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending_approval')
                    """,
                    (
                        video_id, tenant_id, account_id, video_type,
                        concept.get("angle", ""),
                        concept.get("script", ""),
                        concept.get("scene_prompt", ""),
                        heygen_video_id, avatar_id, voice_id,
                        video_url,
                        concept.get("primary_text", ""),
                        concept.get("headline", ""),
                        concept.get("cta", "Shop Now"),
                        landing_page_url,
                        daily_budget_inr,
                    ),
                )
    except Exception as e:
        print(f"ugc_generator: save_video failed: {e}")
    return video_id


# ── WhatsApp preview ────────────────────────────────────────

def _send_video_preview(
    concept: dict,
    video_url: str,
    video_id: str,
    video_type: str,
    wa_num: str,
    tenant: dict = None,
) -> None:
    short_id = video_id[:8]
    type_label = "🎭 HeyGen UGC Testimonial" if video_type == "heygen_ugc" else "🎬 Runway Gen-3 Lifestyle Video"

    # Send video with brief caption
    send_video(
        wa_num,
        video_url,
        caption=f"{type_label}: {concept.get('angle', '')}",
        tenant=tenant,
    )

    # Send copy breakdown + commands
    msg = (
        f"{type_label}\n"
        f"🎯 *{concept.get('angle', '')}*\n\n"
    )
    if concept.get("script"):
        msg += f"*SCRIPT:*\n_{concept['script']}_\n\n"
    msg += (
        f"*PRIMARY TEXT:*\n{concept.get('primary_text', '')}\n\n"
        f"*HEADLINE:* {concept.get('headline', '')}\n"
        f"*CTA:* {concept.get('cta', 'Shop Now')}\n\n"
        f"*Video ID:* `{short_id}`\n\n"
        f"✅ *approve video {short_id}*\n"
        f"❌ *reject video {short_id}*"
    )
    send_text(wa_num, msg, tenant)


# ── Main entry point ────────────────────────────────────────

def run_ugc_generator(
    platform: str,
    account_id: str,
    tenant: dict = None,
    daily_budget_inr: float = 300,
) -> dict:
    """
    Full UGC video pipeline. Runs synchronously (designed for asyncio.to_thread).
    Generates 2 videos: one HeyGen UGC + one Kling lifestyle.
    Sends both to WhatsApp for approval.
    """
    tenant_id = (tenant or {}).get("id") or _DEFAULT_TENANT_ID
    wa_num = (tenant or {}).get("admin_wa_id") or WA_REPORT_NUMBER
    product_ctx = (tenant or {}).get("product_context") or PRODUCT_CONTEXT
    lp_url = (tenant or {}).get("landing_page_url") or LANDING_PAGE_URL

    print(f"ugc_generator: starting for tenant={tenant_id}")
    send_text(
        wa_num,
        "🎬 *UGC Video Ad Generation starting...*\n"
        "_Generating HeyGen testimonial + Kling lifestyle video. "
        "Takes ~5 min. I'll send previews when ready._",
        tenant,
    )

    # ── Scrape landing page ───────────────────────────────
    page_content = None
    if lp_url:
        try:
            r = requests.get(
                lp_url, timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AdBot/1.0)"},
            )
            html = r.text
            html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
            html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", html)
            page_content = re.sub(r"\s+", " ", text).strip()[:2000]
        except Exception as e:
            print(f"ugc_generator: LP scrape failed: {e}")

    # ── Pull perf summary (lightweight) ──────────────────
    perf_summary = ""
    try:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        t7d = now - timedelta(days=7)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COALESCE(SUM(spend),0), COALESCE(SUM(revenue),0),
                              COALESCE(SUM(conversions),0)
                       FROM kpi_hourly
                       WHERE platform=%s AND account_id=%s AND hour_ts >= %s""",
                    (platform, account_id, t7d),
                )
                row = cur.fetchone()
                spend, rev, conv = [float(x or 0) for x in row]
                roas = round(rev / spend, 2) if spend > 0 else 0
                perf_summary = f"Last 7d: ₹{round(spend)} spend, ₹{round(rev)} revenue, ROAS {roas}, {int(conv)} conversions"
    except Exception as e:
        print(f"ugc_generator: perf fetch failed: {e}")

    # ── Generate concepts ─────────────────────────────────
    try:
        concepts = _generate_ugc_concepts(product_ctx, page_content, perf_summary)
    except Exception as e:
        send_text(wa_num, f"⚠️ UGC concept generation failed: {str(e)[:200]}", tenant)
        return {"ok": False, "error": str(e)}

    ugc_concept = concepts.get("ugc", {})
    lifestyle_concept = concepts.get("lifestyle", {})

    # ── Fetch HeyGen avatar + voice ───────────────────────
    avatar_id, voice_id = get_default_heygen_avatar()
    if not avatar_id or not voice_id:
        send_text(wa_num, "⚠️ Could not fetch HeyGen avatar/voice. Check HEYGEN_API_KEY.", tenant)
        return {"ok": False, "error": "HeyGen avatar/voice unavailable"}

    # ── Fetch product asset for Kling ─────────────────────
    product_image_url = None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT cdn_url FROM product_assets
                       WHERE tenant_id=%s ORDER BY updated_at DESC LIMIT 1""",
                    (tenant_id,),
                )
                row = cur.fetchone()
                if row:
                    product_image_url = row[0]
    except Exception as e:
        print(f"ugc_generator: product asset fetch failed: {e}")

    results = []
    errors = []

    # ── Generate HeyGen UGC video ─────────────────────────
    script = ugc_concept.get("script", "")
    if script and avatar_id and voice_id:
        try:
            print("ugc_generator: generating HeyGen UGC video...")
            video_url = generate_ugc_heygen(
                script, avatar_id, voice_id,
                aspect_ratio="9:16",
                product_image_url=product_image_url,
            )
            video_id = _save_video(
                tenant_id, account_id, "heygen_ugc", ugc_concept,
                video_url, avatar_id=avatar_id, voice_id=voice_id,
                landing_page_url=lp_url, daily_budget_inr=daily_budget_inr,
            )
            _send_video_preview(ugc_concept, video_url, video_id, "heygen_ugc", wa_num, tenant)
            results.append({"type": "heygen_ugc", "video_id": video_id[:8]})
            print(f"ugc_generator: HeyGen video done, id={video_id[:8]}")
        except Exception as e:
            print(f"ugc_generator: HeyGen failed: {e}")
            errors.append({"type": "heygen_ugc", "error": str(e)})
            send_text(wa_num, f"⚠️ HeyGen UGC video failed: {str(e)[:200]}", tenant)
    else:
        errors.append({"type": "heygen_ugc", "error": "Missing script or avatar/voice"})

    # ── Generate Kling lifestyle video ────────────────────
    scene_prompt = lifestyle_concept.get("scene_prompt", "")
    if scene_prompt and product_image_url:
        try:
            print("ugc_generator: generating Kling lifestyle video...")
            video_url = generate_lifestyle_video_kling(
                product_image_url, scene_prompt, duration=5, aspect_ratio="9:16"
            )
            video_id = _save_video(
                tenant_id, account_id, "kling_lifestyle", lifestyle_concept,
                video_url, landing_page_url=lp_url, daily_budget_inr=daily_budget_inr,
            )
            _send_video_preview(lifestyle_concept, video_url, video_id, "kling_lifestyle", wa_num, tenant)
            results.append({"type": "kling_lifestyle", "video_id": video_id[:8]})
            print(f"ugc_generator: Kling video done, id={video_id[:8]}")
        except Exception as e:
            print(f"ugc_generator: Kling failed: {e}")
            errors.append({"type": "kling_lifestyle", "error": str(e)})
            send_text(wa_num, f"⚠️ Kling lifestyle video failed: {str(e)[:200]}", tenant)
    elif not product_image_url:
        errors.append({"type": "kling_lifestyle", "error": "No product photo uploaded yet — type 'product photo' first"})
        send_text(wa_num, "ℹ️ Kling lifestyle video skipped — no product photo uploaded. Type *product photo* to upload one.", tenant)

    if results:
        send_text(
            wa_num,
            f"✅ {len(results)} video concept(s) sent above.\n"
            "Review and reply *approve video <id>* or *reject video <id>*.",
            tenant,
        )

    print(f"ugc_generator: done. {len(results)} videos, {len(errors)} errors")
    return {
        "ok": len(results) > 0,
        "videos_generated": len(results),
        "results": results,
        "errors": errors,
    }
