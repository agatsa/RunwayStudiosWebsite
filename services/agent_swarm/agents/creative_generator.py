# services/agent_swarm/agents/creative_generator.py
"""
Creative Generator — full pipeline:
1. Claude reads performance data + LP audit + objections
2. Claude generates 2 high-converting ad concepts (copy + image prompt)
3. fal.ai Flux generates the images
4. WhatsApp sends image + copy to admin for approval
5. On approval → meta_publisher.py creates the Meta campaign

Multi-tenant: all DB queries filter by tenant_id. Admin WA number comes
from the tenant dict (not the global WA_REPORT_NUMBER env var).
"""
import io
import json
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import anthropic
import requests

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, PRODUCT_CONTEXT,
    META_AD_ACCOUNT_ID, WA_REPORT_NUMBER,
    WA_ACCESS_TOKEN, META_API_VERSION, FAL_KEY,
)
from services.agent_swarm.db import get_conn
from services.agent_swarm.wa import send_text, send_image
from services.agent_swarm.creative.image_gen import (
    generate_ad_image,
    generate_ad_image_ip_adapter,
    generate_ad_image_virtual_tryon,
    generate_ad_image_lora,
    generate_product_variations,
)

# Default tenant UUID (existing single-tenant setup)
_DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _tenant_id_from(tenant: dict | None) -> str:
    return (tenant or {}).get("id") or _DEFAULT_TENANT_ID


def _wa_report(tenant: dict | None) -> str:
    return (tenant or {}).get("admin_wa_id") or WA_REPORT_NUMBER


# ── Live page scraper ──────────────────────────────────────

def _scrape_page_content(url: str, max_chars: int = 4000) -> str | None:
    """
    Fetch a URL and return stripped plain-text content (scripts/styles removed).
    Used to give Claude live pricing, offers, and product details at generation time.
    Returns None on any failure — caller continues without it.
    """
    try:
        resp = requests.get(
            url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AdBot/1.0)"},
        )
        resp.raise_for_status()
        html = resp.text
        html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else None
    except Exception as e:
        print(f"_scrape_page_content error ({url}): {e}")
        return None


# ── Fetch context ──────────────────────────────────────────

def _fetch_creative_context(platform: str, account_id: str) -> dict:
    now = datetime.now(timezone.utc)
    t7d = now - timedelta(days=7)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(spend),0), COALESCE(SUM(revenue),0),
                       COALESCE(SUM(conversions),0), COALESCE(SUM(clicks),0),
                       COALESCE(SUM(impressions),0)
                FROM kpi_hourly
                WHERE platform=%s AND account_id=%s AND hour_ts >= %s
                """,
                (platform, account_id, t7d),
            )
            r = cur.fetchone()
            spend7, rev7, conv7, clicks7, imp7 = [float(x or 0) for x in r]
            roas7 = round(rev7 / spend7, 2) if spend7 > 0 else 0
            ctr7 = round(clicks7 / imp7, 4) if imp7 > 0 else 0

            cur.execute(
                """
                SELECT objection_type, SUM(count) as cnt
                FROM fact_objections_daily
                WHERE platform=%s AND account_id=%s
                  AND day >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY objection_type
                ORDER BY cnt DESC LIMIT 5
                """,
                (platform, account_id),
            )
            objections = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

            cur.execute(
                """
                SELECT clarity_score, trust_score, friction_score, overall_score,
                       issues, recommendations
                FROM landing_page_audits
                ORDER BY ts DESC LIMIT 1
                """
            )
            lp = cur.fetchone()
            lp_data = {}
            if lp:
                lp_data = {
                    "clarity": float(lp[0] or 0),
                    "trust": float(lp[1] or 0),
                    "friction": float(lp[2] or 0),
                    "overall": float(lp[3] or 0),
                    "issues": lp[4],
                    "recommendations": lp[5],
                }

            cur.execute(
                """
                SELECT entity_id, fatigue_score, ctr, ctr_7d_avg
                FROM mem_entity_daily
                WHERE platform=%s AND account_id=%s AND entity_level='ad'
                  AND fatigue_flag=true AND day >= CURRENT_DATE - INTERVAL '3 days'
                ORDER BY fatigue_score DESC LIMIT 5
                """,
                (platform, account_id),
            )
            fatigue = [
                {"ad_id": r[0], "fatigue_score": float(r[1] or 0),
                 "ctr": float(r[2] or 0), "ctr_7d_avg": float(r[3] or 0)}
                for r in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT digest_text FROM mem_weekly_digest
                WHERE platform=%s AND account_id=%s
                ORDER BY week_start DESC LIMIT 1
                """,
                (platform, account_id),
            )
            row = cur.fetchone()
            weekly_digest = row[0] if row else "No prior weekly data."

    return {
        "last_7d": {
            "spend": round(spend7, 2), "revenue": round(rev7, 2), "roas": roas7,
            "conversions": int(conv7), "clicks": int(clicks7),
            "impressions": int(imp7), "ctr": ctr7,
        },
        "top_objections": objections,
        "landing_page": lp_data,
        "fatigue_ads": fatigue,
        "weekly_digest": weekly_digest[:800],
    }


# ── Claude generates ad concepts ───────────────────────────

def _generate_concepts(
    context: dict,
    trigger_reason: str,
    product_context: str = None,
    page_content: str = None,
) -> list[dict]:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    ctx = product_context or PRODUCT_CONTEXT

    live_section = ""
    if page_content:
        live_section = f"""
=== LIVE PAGE CONTENT (scraped now — use for current pricing, offers, SKUs) ===
{page_content}
"""

    prompt = f"""You are a senior performance marketing strategist for Indian D2C brands.
Your job: create 2 high-converting Facebook/Instagram ad concepts for the product below.

=== PRODUCT ===
{ctx}
{live_section}
=== ACCOUNT PERFORMANCE (last 7 days) ===
{json.dumps(context['last_7d'], indent=2)}

=== TOP CUSTOMER OBJECTIONS ===
{json.dumps(context['top_objections'], indent=2) if context['top_objections'] else 'No data yet — use common health-product objections: price, trust, "does it really work?"'}

=== LANDING PAGE AUDIT ===
{json.dumps(context['landing_page'], indent=2) if context['landing_page'] else 'Not audited yet. Assume standard e-commerce page.'}

=== TRIGGER REASON ===
{trigger_reason}

=== TASK ===
Generate 2 completely different ad concepts. Use proven high-converting frameworks for Indian D2C:
- Framework options: PAS (Problem-Agitate-Solution), Social Proof + Authority, Before/After,
  Specificity + Curiosity, Price Anchor + Urgency, UGC/Testimonial style, Fear + Relief
- Target: health-conscious Indians 28-55, working professionals, people with diabetes/BP concerns
- Tone: trustworthy, simple, proudly Made in India
- Address the top objections if data is available
- Landing page issues (if score < 7): compensate in ad copy (add trust, urgency, social proof)

For each concept return EXACTLY this JSON structure (no markdown, just JSON array):
[
  {{
    "concept_index": 0,
    "angle": "short name for this concept (5 words max)",
    "framework": "which framework used",
    "hook": "first 1-2 sentences — this is what stops the scroll. Make it visceral.",
    "primary_text": "full ad body text (100-200 words). Include hook, expand problem/solution, include social proof, price, CTA nudge. Use line breaks for readability.",
    "headline": "bold text below image (40 chars max). Clear benefit or curiosity.",
    "description": "smaller text below headline (30 chars max). Supporting detail.",
    "cta": "one of: Shop Now, Learn More, Get Offer, Order Now",
    "image_prompt": "detailed Flux image generation prompt (no text in image). Describe scene, subject, lighting, style. Include: Indian person, product clearly visible on wrist, specific emotional state or setting. Aim for high-quality product lifestyle photography.",
    "use_product_image": true,
    "product_image_type": "physical"
  }},
  {{
    "concept_index": 1,
    "angle": "short name for this concept (5 words max)",
    "framework": "which framework used",
    "hook": "first 1-2 sentences — this is what stops the scroll. Make it visceral.",
    "primary_text": "full ad body text (100-200 words). Include hook, expand problem/solution, include social proof, price, CTA nudge. Use line breaks for readability.",
    "headline": "bold text below image (40 chars max). Clear benefit or curiosity.",
    "description": "smaller text below headline (30 chars max). Supporting detail.",
    "cta": "one of: Shop Now, Learn More, Get Offer, Order Now",
    "image_prompt": "detailed Flux image generation prompt (no text in image). Describe scene, subject, lighting, style. Include: Indian person, product clearly visible on wrist, specific emotional state or setting. Aim for high-quality product lifestyle photography.",
    "use_product_image": true,
    "product_image_type": "physical"
  }}
]

=== PRODUCT IMAGE REFERENCE RULES ===
ALWAYS set use_product_image: true for both concepts — we have the actual product photo and must use it.
- use_product_image: true AND product_image_type: "physical"
  → lifestyle scene with person using device, testimonial, before/after, product showcase
- use_product_image: true AND product_image_type: "app"
  → showcases app metrics, health readings, dashboard, data visualization
- use_product_image: false is ONLY allowed when the concept has zero product in scene (pure emotion/story)

Return ONLY the JSON array."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if m:
            raw = m.group(1).strip()
    m = re.search(r"\[[\s\S]*\]", raw)
    if m:
        raw = m.group()
    return json.loads(raw.strip())


# ── Product asset reference + intelligence ─────────────────

def _get_product_asset(asset_type: str, tenant_id: str) -> dict | None:
    """
    Fetch product reference image, metadata, and LoRA info from product_assets.
    Filters by tenant_id for proper multi-tenant isolation.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT cdn_url, metadata, lora_url, lora_status,
                              lora_trigger_word, name, image_urls, product_url
                       FROM product_assets
                       WHERE asset_type=%s AND tenant_id=%s""",
                    (asset_type, tenant_id),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "cdn_url": row[0],
            "metadata": row[1] or {},
            "lora_url": row[2],
            "lora_status": row[3] or "none",
            "lora_trigger_word": row[4],
            "name": row[5] or asset_type,
            "image_urls": row[6] or [],
            "product_url": row[7],
        }
    except Exception as e:
        print(f"_get_product_asset error: {e}")
        return None


def auto_generate_and_train(
    asset_type: str,
    cdn_url: str,
    product_description: str,
    tenant_id: str = _DEFAULT_TENANT_ID,
    wa_report_number: str = None,
) -> None:
    """
    Background task: generate 8 training variations → save to DB → train LoRA.
    Sends WhatsApp progress updates to the tenant's admin number.
    """
    wa_num = wa_report_number or WA_REPORT_NUMBER
    try:
        send_text(wa_num, "🖼️ Generating 8 training image variations from your photo...")
        desc = product_description or "product, clean product photo"
        variations = generate_product_variations(cdn_url, desc, count=8)

        if variations:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for url in variations:
                        cur.execute(
                            """UPDATE product_assets
                               SET image_urls = CASE
                                   WHEN %s = ANY(COALESCE(image_urls, '{}')) THEN image_urls
                                   ELSE COALESCE(image_urls, '{}') || ARRAY[%s::TEXT]
                               END, updated_at=NOW()
                               WHERE asset_type=%s AND tenant_id=%s""",
                            (url, url, asset_type, tenant_id),
                        )
            send_text(
                wa_num,
                f"✅ Generated {len(variations)} training variations.\n"
                "🎓 Starting LoRA training now (~3-5 min)...",
            )
        else:
            send_text(
                wa_num,
                "⚠️ Variation generation failed — training on original photo only.\n"
                "🎓 Starting LoRA training now...",
            )

        train_product_lora(asset_type, tenant_id, wa_num)

    except Exception as e:
        print(f"auto_generate_and_train error for {asset_type}: {e}")
        import traceback; traceback.print_exc()
        send_text(wa_num, f"⚠️ Auto-training pipeline failed: {str(e)[:200]}")


def analyze_product_image(cdn_url: str) -> dict:
    """
    Use Claude vision to analyze a product image.
    Returns metadata dict for use in generation prompts.
    Called once when user uploads a product photo — stored in product_assets.metadata.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "url", "url": cdn_url},
                },
                {
                    "type": "text",
                    "text": """Analyze this product image carefully. Return ONLY a JSON object:
{
  "product_type": "smartwatch|fitness_band|clothing_shirt|clothing_pants|footwear|jewelry|bag|other",
  "placement_category": "wearable_wrist|clothing_upper|clothing_lower|footwear|accessory|other",
  "placement_instruction": "worn on left wrist|worn on body|carried in hand|etc",
  "dominant_colors": ["color1", "color2"],
  "key_features": ["feature1", "feature2", "feature3"],
  "brand_visible": true,
  "negative_constraints": ["no other wristwatch or fitness band on either wrist"],
  "product_description": "Detailed 2-3 sentence visual description for an image generation model. Be specific about shape, size, color, texture, any visible text or logo, and exactly how it should look when worn/used."
}
Return ONLY the JSON, no other text.""",
                },
            ],
        }],
    )
    raw = response.content[0].text.strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {}


def _build_product_aware_prompt(base_prompt: str, metadata: dict) -> str:
    desc = metadata.get("product_description", "")
    placement = metadata.get("placement_instruction", "")
    negatives = metadata.get("negative_constraints", [])
    if not desc:
        return base_prompt
    enhanced = base_prompt
    enhanced += f". The person is {placement}: {desc}"
    if negatives:
        enhanced += ". " + ". ".join(negatives)
    enhanced += ". The product is clearly visible and looks exactly like the reference photo."
    return enhanced


def _generate_with_product_reference(
    base_prompt: str,
    product_url: str,
    metadata: dict,
    lora_url: str = None,
    lora_trigger_word: str = None,
) -> str:
    """
    Route to best generation strategy:
    Tier 1: LoRA (best) → Tier 2: LEFFA try-on → Tier 3: IP-Adapter → Tier 4: T2I
    """
    category = metadata.get("placement_category", "other")
    enhanced_prompt = _build_product_aware_prompt(base_prompt, metadata)

    if lora_url and lora_trigger_word:
        try:
            print("PRODUCT PLACEMENT: Tier 1 — LoRA")
            return generate_ad_image_lora(enhanced_prompt, lora_url, lora_trigger_word)
        except Exception as e:
            print(f"LoRA failed: {e} — falling back")

    if category in ("clothing_upper", "clothing_lower"):
        base_person_prompt = (
            f"{base_prompt}. Person in plain neutral clothes, full body visible, "
            "no branded garments. High quality fashion photography, clean background."
        )
        try:
            print(f"PRODUCT PLACEMENT: Tier 2 — LEFFA virtual try-on for {category}")
            return generate_ad_image_virtual_tryon(product_url, base_person_prompt)
        except Exception as e:
            print(f"LEFFA failed: {e} — falling back")

    ip_scale = 0.85 if category == "wearable_wrist" else 0.80
    try:
        print(f"PRODUCT PLACEMENT: Tier 3 — IP-Adapter (scale={ip_scale})")
        return generate_ad_image_ip_adapter(enhanced_prompt, product_url, ip_scale=ip_scale)
    except Exception as e:
        print(f"IP-Adapter failed: {e} — falling back to T2I")
        return generate_ad_image(base_prompt)


# ── Store creative in DB ───────────────────────────────────

def _save_creative(
    platform: str, account_id: str, concept: dict,
    image_url: str | None, trigger_reason: str, daily_budget_inr: float = 300,
    landing_page_url: str = None, tenant_id: str = _DEFAULT_TENANT_ID,
    fb_page_id: str = None, pixel_id: str = None,
    status: str = "pending_approval",
) -> str:
    creative_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO creative_queue
                  (id, platform, account_id, tenant_id, concept_index, trigger_reason,
                   angle, hook, primary_text, headline, description, cta,
                   image_prompt, image_url, status, daily_budget_inr, landing_page_url,
                   fb_page_id, pixel_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    creative_id, platform, account_id, tenant_id,
                    concept.get("concept_index", 0),
                    trigger_reason,
                    concept.get("angle", ""),
                    concept.get("hook", ""),
                    concept.get("primary_text", ""),
                    concept.get("headline", ""),
                    concept.get("description", ""),
                    concept.get("cta", "Shop Now"),
                    concept.get("image_prompt", ""),
                    image_url,
                    status,
                    daily_budget_inr,
                    landing_page_url,
                    fb_page_id or None,
                    pixel_id or None,
                ),
            )
    return creative_id


# ── Send WhatsApp preview ──────────────────────────────────

def _send_wa_preview(
    concept: dict, image_url: str, creative_id: str,
    landing_page_url: str = None, wa_report_number: str = None,
):
    wa_num = wa_report_number or WA_REPORT_NUMBER
    short_id = creative_id[:8]
    caption = f"🎨 Ad Concept: {concept['angle']}\n\n{concept.get('hook', '')[:200]}"
    send_image(wa_num, image_url, caption)

    url_display = landing_page_url or "(default — set via edit url:)"
    msg = (
        f"📋 *Ad Copy — {concept['angle']}*\n"
        f"Framework: {concept.get('framework', '')}\n\n"
        f"*PRIMARY TEXT:*\n{concept['primary_text']}\n\n"
        f"*HEADLINE:* {concept['headline']}\n"
        f"*DESCRIPTION:* {concept.get('description', '')}\n"
        f"*CTA:* {concept.get('cta', 'Shop Now')}\n"
        f"*URL:* {url_display}\n\n"
        f"*Creative ID:* `{short_id}`\n\n"
        f"✏️ *Edit copy:* `edit copy: <instructions>`\n"
        f"🎨 *Edit image:* `edit image: <instructions>`\n"
        f"🔗 *Edit URL:* `edit url: https://...`\n"
        f"📷 *Use your photo:* send an image\n\n"
        f"✅ *approve creative {short_id}*\n"
        f"❌ *reject creative {short_id}*"
    )
    send_text(wa_num, msg)


# ── Copy-only preview (split flow) ────────────────────────

def _send_copy_preview(
    concept: dict, creative_id: str,
    landing_page_url: str = None, wa_report_number: str = None,
):
    """Send ad copy text only — user confirms before image is generated."""
    wa_num = wa_report_number or WA_REPORT_NUMBER
    short_id = creative_id[:8]
    url_display = landing_page_url or "(default — set via edit url:)"
    msg = (
        f"✍️ *Ad Copy — {concept['angle']}*\n"
        f"Framework: {concept.get('framework', '')}\n\n"
        f"*HOOK:*\n{concept.get('hook', '')}\n\n"
        f"*PRIMARY TEXT:*\n{concept['primary_text']}\n\n"
        f"*HEADLINE:* {concept['headline']}\n"
        f"*DESCRIPTION:* {concept.get('description', '')}\n"
        f"*CTA:* {concept.get('cta', 'Shop Now')}\n"
        f"*URL:* {url_display}\n\n"
        f"*Creative ID:* `{short_id}`\n\n"
        f"✏️ *Edit copy:* `edit copy {short_id}: <instructions>`\n"
        f"✅ *Confirm & generate image:* `confirm copy {short_id}`\n"
        f"❌ *Reject:* `reject creative {short_id}`"
    )
    send_text(wa_num, msg)


# ── Generate image for a draft_copy creative ───────────────

def generate_image_for_creative(creative_id: str, tenant: dict = None) -> dict:
    """
    Fetch a draft_copy creative, generate its image with gpt-image-1,
    update status to pending_approval, and send the full WA preview.

    Called as a background task when user types 'confirm copy <id>'.
    """
    wa_num = _wa_report(tenant)
    tid = _tenant_id_from(tenant)

    # Fetch the draft creative
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT angle, hook, primary_text, headline, description,
                       cta, image_prompt, landing_page_url, tenant_id
                FROM creative_queue
                WHERE id=%s AND status='draft_copy'
                """,
                (creative_id,),
            )
            row = cur.fetchone()

    if not row:
        return {"ok": False, "error": "Draft creative not found or already processed"}

    angle, hook, primary_text, headline, description, cta, image_prompt, landing_page_url, creative_tenant_id = row
    concept = {
        "angle": angle, "hook": hook, "primary_text": primary_text,
        "headline": headline, "description": description,
        "cta": cta, "image_prompt": image_prompt,
    }

    # Use the creative's own tenant_id for product lookup
    effective_tid = str(creative_tenant_id) if creative_tenant_id else tid

    # Find best product reference image for this tenant (prioritise LoRA-ready)
    product_image_url = None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cdn_url FROM product_assets
                    WHERE tenant_id=%s AND cdn_url IS NOT NULL
                    ORDER BY
                        CASE lora_status WHEN 'ready' THEN 0 WHEN 'training' THEN 1 ELSE 2 END,
                        updated_at DESC
                    LIMIT 1
                    """,
                    (effective_tid,),
                )
                asset_row = cur.fetchone()
        if asset_row:
            product_image_url = asset_row[0]
    except Exception as e:
        print(f"generate_image_for_creative: could not fetch product asset: {e}")

    try:
        send_text(
            wa_num,
            f"🎨 Generating image for *{angle}* with GPT-Image-1...\n"
            f"{'Using your product photo as reference. ' if product_image_url else ''}"
            "~30-60 seconds.",
        )

        # Build enhanced prompt
        enhanced_prompt = (
            f"{image_prompt}. "
            "Professional Facebook/Instagram ad image for Indian market. "
            "No text overlays. Photorealistic, lifestyle photography quality."
        )

        from services.agent_swarm.creative.image_gen import generate_ad_image_openai
        image_url = generate_ad_image_openai(enhanced_prompt, product_image_url)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE creative_queue
                       SET image_url=%s, status='pending_approval', updated_at=NOW()
                       WHERE id=%s""",
                    (image_url, creative_id),
                )

        _send_wa_preview(concept, image_url, creative_id, landing_page_url, wa_num)
        return {"ok": True, "creative_id": creative_id, "image_url": image_url}

    except Exception as e:
        print(f"generate_image_for_creative error: {e}")
        import traceback; traceback.print_exc()
        send_text(wa_num, f"⚠️ Image generation failed for '{angle}': {str(e)[:200]}")
        return {"ok": False, "error": str(e)}


# ── Main entry point ───────────────────────────────────────

def run_creative_generator(
    platform: str,
    account_id: str,
    trigger_reason: str = "manual",
    num_concepts: int = 2,
    daily_budget_inr: float = 300,
    product_id: str = None,
    product_url: str = None,
    tenant: dict = None,
    split_flow: bool = True,
) -> dict:
    """
    Full pipeline: analyse → generate concepts → (optionally) create images → send WA previews.

    split_flow=True (default for manual campaigns):
      Saves copy only as 'draft_copy', sends copy-only WA preview.
      User reviews/edits copy, then types 'confirm copy <id>' to trigger image generation.

    split_flow=False (automated cron runs):
      Original behaviour — generates images immediately and sends full previews.

    tenant: account dict from accounts table (contains tenant_id, admin_wa_id,
            product_context, etc.). Falls back to env-var defaults if not provided.
    product_url: explicit URL to scrape for live pricing/offers. Falls back to
                 product_asset.product_url, then tenant.landing_page_url.
    """
    tid = _tenant_id_from(tenant)
    wa_num = _wa_report(tenant)
    results = []
    errors = []

    campaign_product_asset = None
    if product_id:
        campaign_product_asset = _get_product_asset(product_id, tid)
        if campaign_product_asset:
            print(f"Campaign product: {campaign_product_asset.get('name')} (LoRA: {campaign_product_asset.get('lora_status')})")
        else:
            print(f"Product '{product_id}' not found for tenant {tid} — standard T2I")

    # Build product context from selected product asset (name, description, category, colors)
    # Falls back to tenant-level product_context, then global default
    if campaign_product_asset:
        meta = campaign_product_asset.get("metadata") or {}
        _name = campaign_product_asset.get("name", "")
        _desc = meta.get("product_description", "")
        _cat  = meta.get("placement_category", "")
        _cols = ", ".join(meta.get("dominant_colors", []))
        _place = meta.get("placement_instruction", "")
        _purl = campaign_product_asset.get("product_url", "")
        product_ctx = f"Product: {_name}"
        if _desc:   product_ctx += f"\nDescription: {_desc}"
        if _cat:    product_ctx += f"\nCategory: {_cat}"
        if _cols:   product_ctx += f"\nColors: {_cols}"
        if _place:  product_ctx += f"\nPlacement: {_place}"
        if _purl:   product_ctx += f"\nURL: {_purl}"
        print(f"run_creative_generator: product_ctx built from asset '{_name}'")
    else:
        product_ctx = (tenant or {}).get("product_context") or PRODUCT_CONTEXT

    # Determine URL to scrape (priority: explicit arg > product asset URL > tenant landing page)
    scrape_url = (
        product_url
        or (campaign_product_asset or {}).get("product_url")
        or (tenant or {}).get("landing_page_url")
    ) or None
    page_content = None
    if scrape_url:
        print(f"Scraping page content from: {scrape_url}")
        page_content = _scrape_page_content(scrape_url)
        if page_content:
            print(f"Scraped {len(page_content)} chars from {scrape_url}")
        else:
            print(f"Scrape returned nothing for {scrape_url} — continuing without")

    try:
        context = _fetch_creative_context(platform, account_id)
    except Exception as e:
        return {"ok": False, "error": f"Context fetch failed: {e}"}

    try:
        concepts = _generate_concepts(context, trigger_reason, product_ctx, page_content)[:num_concepts]
    except Exception as e:
        return {"ok": False, "error": f"Concept generation failed: {e}"}

    for concept in concepts:
        try:
            product_asset = None
            if campaign_product_asset:
                product_asset = campaign_product_asset
            elif concept.get("use_product_image") and concept.get("product_image_type"):
                product_asset = _get_product_asset(concept["product_image_type"], tid)

            # Priority: explicit product_url passed in > product asset stored URL > tenant URL
            landing_page_url = (
                scrape_url
                or (product_asset or {}).get("product_url")
                or (tenant or {}).get("landing_page_url")
            ) or None

            if split_flow:
                # ── Split flow: save copy only, send text preview ──────
                creative_id = _save_creative(
                    platform, account_id, concept, None,
                    trigger_reason, daily_budget_inr, landing_page_url,
                    tenant_id=tid,
                    fb_page_id=(tenant or {}).get("fb_page_id") or None,
                    pixel_id=(tenant or {}).get("pixel_id") or None,
                    status="draft_copy",
                )
                _send_copy_preview(concept, creative_id, landing_page_url, wa_num)
                results.append({
                    "creative_id": creative_id[:8],
                    "angle": concept.get("angle"),
                    "status": "draft_copy",
                })
            else:
                # ── Full flow: generate image immediately ──────────────
                if product_asset:
                    lora_ready = product_asset.get("lora_status") == "ready"
                    image_url = _generate_with_product_reference(
                        concept["image_prompt"],
                        product_asset["cdn_url"],
                        product_asset["metadata"] or {},
                        lora_url=product_asset.get("lora_url") if lora_ready else None,
                        lora_trigger_word=product_asset.get("lora_trigger_word") if lora_ready else None,
                    )
                else:
                    image_url = generate_ad_image(concept["image_prompt"])

                creative_id = _save_creative(
                    platform, account_id, concept, image_url,
                    trigger_reason, daily_budget_inr, landing_page_url,
                    tenant_id=tid,
                    fb_page_id=(tenant or {}).get("fb_page_id") or None,
                    pixel_id=(tenant or {}).get("pixel_id") or None,
                    status="pending_approval",
                )
                _send_wa_preview(concept, image_url, creative_id, landing_page_url, wa_num)
                results.append({
                    "creative_id": creative_id[:8],
                    "angle": concept.get("angle"),
                    "status": "pending_approval",
                })

        except Exception as e:
            errors.append({"angle": concept.get("angle", "?"), "error": str(e)})

    if split_flow:
        send_text(
            wa_num,
            f"✍️ {len(results)} copy concept(s) sent above.\n"
            f"Review each → *confirm copy <id>* to generate the image with GPT-Image-1.\n"
            f"Or *edit copy <id>: <instructions>* to refine first.",
        )
    else:
        send_text(
            wa_num,
            f"🎨 {len(results)} ad concept(s) sent above.\n"
            f"Use *edit copy: ...* or *edit image: ...* to refine, or send a photo.\n"
            f"When ready: *approve creative [id]* or *reject creative [id]*",
        )

    return {
        "ok": True,
        "trigger": trigger_reason,
        "concepts_generated": len(results),
        "creatives": results,
        "errors": errors,
    }


# ── LoRA training ──────────────────────────────────────────

def train_product_lora(
    asset_type: str,
    tenant_id: str = _DEFAULT_TENANT_ID,
    wa_report_number: str = None,
) -> dict:
    """
    Train a Flux LoRA model on the product's uploaded photos.
    Stores LoRA URL back in product_assets on success.
    Called as a BackgroundTask — takes 3-5 minutes.
    """
    import fal_client
    os.environ["FAL_KEY"] = FAL_KEY
    wa_num = wa_report_number or WA_REPORT_NUMBER

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, image_urls, cdn_url FROM product_assets WHERE asset_type=%s AND tenant_id=%s",
                (asset_type, tenant_id),
            )
            row = cur.fetchone()

    if not row:
        send_text(wa_num, f"⚠️ LoRA training failed: No product found for type '{asset_type}'")
        return {"ok": False, "error": "Product not found"}

    name, image_urls, cdn_url = row
    image_urls = image_urls or []
    all_urls = list(dict.fromkeys([u for u in image_urls if u] + ([cdn_url] if cdn_url else [])))

    if not all_urls:
        send_text(wa_num, f"⚠️ LoRA training failed: No photos uploaded for '{name or asset_type}'")
        return {"ok": False, "error": "No images uploaded"}

    product_name = name or asset_type
    photo_count = len(all_urls)
    print(f"LORA TRAINING: starting for '{product_name}' ({tenant_id}) with {photo_count} photos")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE product_assets SET lora_status='training', updated_at=NOW() WHERE asset_type=%s AND tenant_id=%s",
                (asset_type, tenant_id),
            )

    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, url in enumerate(all_urls):
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                ext = ".jpg"
                ct = r.headers.get("Content-Type", "")
                if "png" in ct:
                    ext = ".png"
                elif "webp" in ct:
                    ext = ".webp"
                zf.writestr(f"product_{i + 1:03d}{ext}", r.content)
        zip_buffer.seek(0)

        # Upload zip to GCS (fal.ai CDN upload is broken — use GCS instead)
        from google.cloud import storage as gcs
        import uuid as _uuid
        zip_bytes = zip_buffer.read()
        zip_filename = f"lora-training/{_uuid.uuid4().hex}.zip"
        _gcs_client = gcs.Client()
        _bucket = _gcs_client.bucket("wa-agency-raw-wa-ai-agency")
        _blob = _bucket.blob(zip_filename)
        _blob.upload_from_string(zip_bytes, content_type="application/zip")
        zip_url = f"https://storage.googleapis.com/wa-agency-raw-wa-ai-agency/{zip_filename}"
        print(f"LORA TRAINING: zip uploaded to GCS: {zip_url}")

        slug_part = asset_type.replace("-", "")[:6].upper()
        trigger_word = f"PRDCT{slug_part}"

        result = fal_client.run(
            "fal-ai/flux-lora-fast-training",
            arguments={
                "images_data_url": zip_url,
                "trigger_word": trigger_word,
                "steps": 1000,
                "data_archive_format": "zip",
            },
        )

        lora_url = (result.get("diffusers_lora_file") or {}).get("url")
        if not lora_url:
            raise RuntimeError(f"Training returned no LoRA model. Response: {result}")

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE product_assets
                       SET lora_url=%s, lora_status='ready',
                           lora_trigger_word=%s, updated_at=NOW()
                       WHERE asset_type=%s AND tenant_id=%s""",
                    (lora_url, trigger_word, asset_type, tenant_id),
                )

        print(f"LORA TRAINING: complete for '{product_name}', trigger='{trigger_word}'")
        send_text(
            wa_num,
            f"✅ *LoRA training complete!*\n\n"
            f"Product: *{product_name}*\n"
            f"Photos used: {photo_count}\n"
            f"Trigger word: `{trigger_word}`\n\n"
            f"Future creatives will use this fine-tuned model for pixel-perfect product placement."
            f" (Tier 1 — best quality)",
        )
        return {"ok": True, "asset_type": asset_type, "lora_url": lora_url, "trigger_word": trigger_word}

    except Exception as e:
        print(f"LORA TRAINING ERROR for '{product_name}': {e}")
        import traceback; traceback.print_exc()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE product_assets SET lora_status='failed', updated_at=NOW() WHERE asset_type=%s AND tenant_id=%s",
                    (asset_type, tenant_id),
                )
        send_text(
            wa_num,
            f"⚠️ LoRA training failed for '{product_name}': {str(e)[:200]}\n"
            f"IP-Adapter will continue to be used as fallback.",
        )
        return {"ok": False, "error": str(e)}


# ── Creative editing ───────────────────────────────────────

def _edit_copy_with_claude(concept: dict, instructions: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""You are editing an ad creative for an Indian health/wellness product.

Current ad copy:
Angle: {concept['angle']}
Primary Text: {concept['primary_text']}
Headline: {concept['headline']}
Description: {concept['description']}
CTA: {concept['cta']}

User instructions: {instructions}

Apply the instructions and return ONLY a JSON object with all updated fields:
{{
  "angle": "short name (5 words max)",
  "primary_text": "full ad body (100-200 words)",
  "headline": "bold text below image (40 chars max)",
  "description": "smaller text below headline (30 chars max)",
  "cta": "one of: Shop Now, Learn More, Get Offer, Order Now"
}}

Return ONLY the JSON object, no other text."""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return concept
    try:
        return json.loads(m.group())
    except Exception:
        return concept


def _download_wa_media_to_cdn(media_id: str) -> str:
    """
    Download a WhatsApp media item and upload to Google Cloud Storage.
    Returns public https://storage.googleapis.com/... URL.
    """
    from google.cloud import storage as gcs

    # 1. Get the download URL from WhatsApp
    r = requests.get(
        f"https://graph.facebook.com/{META_API_VERSION}/{media_id}",
        headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}"},
        timeout=10,
    )
    r.raise_for_status()
    download_url = r.json().get("url")
    if not download_url:
        raise RuntimeError(f"No URL in WA media response: {r.text[:200]}")

    # 2. Download the image bytes
    r2 = requests.get(
        download_url,
        headers={"Authorization": f"Bearer {WA_ACCESS_TOKEN}"},
        timeout=30,
    )
    r2.raise_for_status()

    # 3. Detect content type and extension
    content_type = r2.headers.get("Content-Type", "image/jpeg")
    ext = ".jpg" if "jpeg" in content_type else ".png" if "png" in content_type else ".jpg"

    # 4. Upload to GCS under product-assets/ prefix
    import uuid
    filename = f"product-assets/{uuid.uuid4().hex}{ext}"
    bucket_name = "wa-agency-raw-wa-ai-agency"

    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(filename)
    blob.upload_from_string(r2.content, content_type=content_type)

    public_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"
    print(f"_download_wa_media_to_cdn: uploaded to GCS: {public_url}")
    return public_url


def edit_creative(
    creative_id: str,
    edit_type: str,
    instructions: str = "",
    media_id: str = "",
    wa_report_number: str = None,
    tenant_id: str = _DEFAULT_TENANT_ID,
) -> dict:
    """
    Edit an existing pending_approval creative in-place and resend WA preview.

    edit_type:
      "copy"             — Claude rewrites copy fields
      "image"            — fal.ai regenerates image
      "reference_direct" — Use uploaded photo as-is
      "reference_ai"     — Use photo as img2img style reference
      "url"              — Change landing page URL
    """
    wa_num = wa_report_number or WA_REPORT_NUMBER

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT angle, hook, primary_text, headline, description,
                       cta, image_prompt, image_url, landing_page_url
                FROM creative_queue WHERE id=%s
                """,
                (creative_id,),
            )
            row = cur.fetchone()

    if not row:
        return {"ok": False, "error": "Creative not found"}

    angle, hook, primary_text, headline, description, cta, image_prompt, image_url, landing_page_url = row
    concept = {
        "angle": angle, "hook": hook, "primary_text": primary_text,
        "headline": headline, "description": description,
        "cta": cta, "image_prompt": image_prompt,
    }

    try:
        if edit_type == "copy":
            new_concept = _edit_copy_with_claude(concept, instructions)
            new_concept.setdefault("hook", concept.get("hook", ""))
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE creative_queue
                        SET angle=%s, primary_text=%s, headline=%s,
                            description=%s, cta=%s, updated_at=NOW()
                        WHERE id=%s
                        """,
                        (new_concept["angle"], new_concept["primary_text"],
                         new_concept["headline"], new_concept["description"],
                         new_concept["cta"], creative_id),
                    )
            _send_wa_preview(new_concept, image_url, creative_id, landing_page_url, wa_num)

        elif edit_type == "image":
            from services.agent_swarm.creative.image_gen import generate_ad_image_openai, generate_ad_image_lora

            new_prompt = f"{image_prompt}. {instructions}" if instructions else image_prompt
            enhanced_prompt = (
                f"{new_prompt}. "
                "Professional Facebook/Instagram ad image for Indian market. "
                "No text overlays. Photorealistic, lifestyle photography quality."
            )

            # Fetch best product asset — prefer LoRA-ready
            product_ref_url = None
            lora_url = None
            lora_trigger_word = None
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT cdn_url, lora_url, lora_status, lora_trigger_word
                               FROM product_assets
                               WHERE tenant_id=%s AND cdn_url IS NOT NULL
                               ORDER BY
                                   CASE lora_status WHEN 'ready' THEN 0 WHEN 'training' THEN 1 ELSE 2 END,
                                   updated_at DESC
                               LIMIT 1""",
                            (tenant_id,),
                        )
                        pa = cur.fetchone()
                if pa:
                    product_ref_url = pa[0]
                    if pa[2] == "ready" and pa[1] and pa[3]:
                        lora_url = pa[1]
                        lora_trigger_word = pa[3]
            except Exception as e:
                print(f"edit_creative: product asset fetch error: {e}")

            if lora_url and lora_trigger_word:
                # Step 1: LoRA generates a photorealistic product image
                print(f"edit_creative: using LoRA ({lora_trigger_word}) as product reference for GPT-Image-1")
                lora_prompt = f"{lora_trigger_word} product photo, clean white background, studio lighting"
                try:
                    product_ref_url = generate_ad_image_lora(lora_prompt, lora_url, lora_trigger_word)
                except Exception as e:
                    print(f"edit_creative: LoRA generation failed: {e} — falling back to cdn_url")

            # Step 2: GPT-Image-1 composes the ad scene using the product reference
            new_image_url = generate_ad_image_openai(enhanced_prompt, product_ref_url)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE creative_queue SET image_prompt=%s, image_url=%s, updated_at=NOW() WHERE id=%s",
                        (new_prompt, new_image_url, creative_id),
                    )
            _send_wa_preview(concept, new_image_url, creative_id, landing_page_url, wa_num)

        elif edit_type == "url":
            new_url = instructions.strip()
            if not new_url.startswith("http"):
                return {"ok": False, "error": "URL must start with http"}
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE creative_queue SET landing_page_url=%s, updated_at=NOW() WHERE id=%s",
                        (new_url, creative_id),
                    )
            _send_wa_preview(concept, image_url, creative_id, new_url, wa_num)

        elif edit_type == "reference_direct":
            new_image_url = _download_wa_media_to_cdn(media_id)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE creative_queue SET image_url=%s, updated_at=NOW() WHERE id=%s",
                        (new_image_url, creative_id),
                    )
            _send_wa_preview(concept, new_image_url, creative_id, landing_page_url, wa_num)

        elif edit_type == "reference_ai":
            reference_url = _download_wa_media_to_cdn(media_id)
            new_image_url = generate_ad_image(image_prompt, reference_image_url=reference_url)
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE creative_queue SET image_url=%s, updated_at=NOW() WHERE id=%s",
                        (new_image_url, creative_id),
                    )
            _send_wa_preview(concept, new_image_url, creative_id, landing_page_url, wa_num)

        else:
            return {"ok": False, "error": f"Unknown edit_type: {edit_type}"}

    except Exception as e:
        print(f"edit_creative ERROR [{edit_type}]: {e}")
        import traceback; traceback.print_exc()
        return {"ok": False, "error": str(e)}

    return {"ok": True, "edit_type": edit_type, "creative_id": creative_id}
