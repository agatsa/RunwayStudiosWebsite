# services/agent_swarm/agents/comment_intel.py
"""
Agent 2 — Comment Intelligence (v2)
Fetches comments from active Meta ads, deduplicates via comment_replies table,
classifies each comment, auto-replies to positive/purchase_intent,
and queues objections for human review via WhatsApp.
"""
import json
import time
from datetime import date, datetime, timezone

import anthropic
import requests

from services.agent_swarm.config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    META_ADS_TOKEN, META_GRAPH,
)
from services.agent_swarm.db import get_conn


OBJECTION_TYPES = [
    "price", "trust", "scam", "feature_confusion",
    "delivery", "purchase_intent", "support", "positive", "other",
]

# Auto-reply immediately without human review
AUTO_REPLY_TYPES = {"positive", "purchase_intent"}

# Queue for human review + WA notification
HUMAN_REVIEW_TYPES = {"price", "trust", "scam", "feature_confusion", "delivery", "support"}


def _tok(tenant: dict = None) -> str:
    return (tenant or {}).get("meta_access_token") or META_ADS_TOKEN


def _get_ad_context(ad_id: str, platform: str, account_id: str) -> dict:
    """
    Look up ad name, campaign name, and ad copy headline for display in WA notifications.
    Gracefully returns empty strings if not found.
    """
    ctx = {"ad_name": "", "campaign_name": "", "headline": ""}
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Ad name + try campaign name via creative_queue join
                cur.execute(
                    """
                    SELECT
                        e_ad.name,
                        e_camp.name AS campaign_name,
                        cq.headline
                    FROM entities_snapshot e_ad
                    LEFT JOIN creative_queue cq
                        ON cq.meta_ad_id = e_ad.entity_id
                    LEFT JOIN entities_snapshot e_camp
                        ON e_camp.entity_id::text = cq.meta_campaign_id::text
                       AND e_camp.entity_level = 'campaign'
                       AND e_camp.platform = e_ad.platform
                    WHERE e_ad.entity_id = %s
                      AND e_ad.entity_level = 'ad'
                      AND e_ad.platform = %s
                    LIMIT 1
                    """,
                    (ad_id, platform),
                )
                row = cur.fetchone()
                if row:
                    ctx["ad_name"] = row[0] or ""
                    ctx["campaign_name"] = row[1] or ""
                    ctx["headline"] = row[2] or ""
    except Exception as e:
        print(f"_get_ad_context error for ad {ad_id}: {e}")
    return ctx


def _fetch_ad_comments(ad_id: str, tenant: dict = None, limit: int = 50) -> list[dict]:
    """
    Fetch comments on a Meta ad.
    Comments live on the page post that the ad promotes — not on the ad object.
    Step 1: resolve effective_object_story_id from the ad's creative.
    Step 2: fetch comments from that page post.
    """
    try:
        # Step 1: get the backing page post ID
        r = requests.get(
            f"{META_GRAPH}/{ad_id}",
            params={
                "fields": "creative{effective_object_story_id}",
                "access_token": _tok(tenant),
            },
            timeout=15,
        )
        if not r.ok:
            print(f"Ad fetch error for {ad_id}: {r.status_code} {r.text[:150]}")
            return []
        post_id = (
            r.json()
            .get("creative", {})
            .get("effective_object_story_id", "")
        )
        if not post_id:
            return []

        # Step 2: fetch comments on the page post
        cr = requests.get(
            f"{META_GRAPH}/{post_id}/comments",
            params={
                "fields": "id,message,from,created_time",
                "limit": limit,
                "access_token": _tok(tenant),
            },
            timeout=30,
        )
        if cr.status_code == 200:
            return cr.json().get("data", [])
        print(f"Comment fetch error for post {post_id}: {cr.status_code} {cr.text[:150]}")
        return []
    except Exception as e:
        print(f"Comment fetch error for ad {ad_id}: {e}")
        return []


def _fetch_active_ad_ids(platform: str, account_id: str, limit: int = 20) -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT e.entity_id
                FROM entities_snapshot e
                JOIN (
                    SELECT entity_id, SUM(spend) spend
                    FROM kpi_hourly
                    WHERE platform=%s AND account_id=%s
                      AND hour_ts >= NOW() - INTERVAL '24 hours'
                    GROUP BY entity_id
                    ORDER BY spend DESC
                    LIMIT %s
                ) k ON k.entity_id = e.entity_id
                WHERE e.platform=%s AND e.entity_level='ad'
                  AND e.status IN ('ACTIVE', 'active')
                """,
                (platform, account_id, limit, platform),
            )
            return [row[0] for row in cur.fetchall()]


def _get_new_comments(platform: str, account_id: str, comments: list[dict]) -> list[dict]:
    """Return only comments not already in comment_replies."""
    if not comments:
        return []
    comment_ids = [c["id"] for c in comments if c.get("id")]
    if not comment_ids:
        return []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT comment_id FROM comment_replies WHERE platform=%s AND account_id=%s AND comment_id = ANY(%s)",
                (platform, account_id, comment_ids),
            )
            seen = {row[0] for row in cur.fetchall()}
    return [c for c in comments if c.get("id") and c["id"] not in seen]


def _classify_comments_batch(comments: list[dict], ad_id: str, product_context: str = "") -> list[dict]:
    """
    Claude classifies each comment and generates a suggested reply in one batch call.
    Returns list of {comment_id, type, suggested_reply}.

    CRITICAL: No medical device claims, no CDSCO references in replies.
    """
    if not comments:
        return []

    product_ctx = product_context or (
        "Indian wellness wearable brand. Smart wellness band that tracks sleep, activity, and recovery."
    )

    items = "\n".join(
        f'{i+1}. [id:{c["id"]}] {c.get("message", "")[:200]}'
        for i, c in enumerate(comments[:20])
    )

    prompt = f"""You are a social media community manager for an Indian D2C brand.
Classify and draft replies for these comments on a Meta ad (ad_id: {ad_id}).

Product context: {product_ctx[:400]}

Comments:
{items}

Categories:
- price: mentions price too high, expensive, costly
- trust: asks if real, genuine, authentic, legit
- scam: calls it fraud, fake, scam, cheat
- feature_confusion: confused about what product does or how to use it
- delivery: asks about shipping, COD, delivery time, availability
- purchase_intent: wants to buy, how to order, inquiring to purchase
- support: existing customer with issue or complaint
- positive: happy comment, good review, recommendation, thank you
- other: jokes, unrelated, irrelevant

For each comment write a short friendly reply (max 150 chars, Hinglish or English, natural tone).

CRITICAL RULES — these MUST be followed:
- Do NOT say the product is a medical device
- Do NOT say "CDSCO approved" or any regulatory certification
- Do NOT claim it diagnoses, treats, monitors, or cures any health condition
- Position as a wellness and lifestyle product only
- For scam/trust: be warm, invite to DM, no defensiveness
- For purchase_intent: give a simple next step (link or DM)
- Use emojis naturally but sparingly

Return ONLY a valid JSON array (no markdown, no extra text):
[
  {{"comment_id": "<exact id from [id:...]>", "type": "<category>", "suggested_reply": "<reply text>"}},
  ...
]"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except Exception:
        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return []


def _save_comment(
    platform: str, account_id: str, ad_id: str,
    comment: dict, classified: dict,
) -> str | None:
    """Insert comment into comment_replies. Returns UUID string, or None if duplicate."""
    comment_id = comment.get("id", "")
    if not comment_id:
        return None

    frm = comment.get("from") or {}
    commenter_name = frm.get("name", "")
    comment_text = comment.get("message", "")
    created_raw = comment.get("created_time", "")

    try:
        comment_created = datetime.fromisoformat(created_raw.replace("Z", "+00:00")) if created_raw else None
    except Exception:
        comment_created = None

    objection_type = classified.get("type", "other")
    suggested_reply = classified.get("suggested_reply", "")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO comment_replies
                  (platform, account_id, ad_id, comment_id, commenter_name,
                   comment_text, comment_created, objection_type, suggested_reply,
                   reply_generated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (platform, account_id, comment_id) DO NOTHING
                RETURNING id
                """,
                (platform, account_id, ad_id, comment_id, commenter_name,
                 comment_text, comment_created, objection_type, suggested_reply),
            )
            row = cur.fetchone()

    return str(row[0]) if row else None


def _auto_reply_to_meta(comment_id: str, reply_text: str, db_id: str, tenant: dict = None):
    """Post reply to Meta and update comment_replies status to auto_replied."""
    try:
        from services.agent_swarm.creative.meta_publisher import post_comment_reply
        meta_reply_id = post_comment_reply(comment_id, reply_text, tenant)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE comment_replies
                       SET status='auto_replied', reply_text=%s, replied_at=NOW(),
                           replied_by='auto', meta_reply_id=%s, updated_at=NOW()
                       WHERE id=%s""",
                    (reply_text, meta_reply_id, db_id),
                )
    except Exception as e:
        print(f"Auto-reply failed for comment {comment_id}: {e}")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE comment_replies SET status='failed', updated_at=NOW() WHERE id=%s",
                    (db_id,),
                )


def _notify_wa_pending(
    pending: list[dict],
    ad_id: str,
    admin_wa_id: str,
    tenant: dict = None,
    ad_context: dict = None,
):
    """Send WhatsApp notification listing comments needing human review."""
    if not pending or not admin_wa_id:
        return

    from services.agent_swarm.wa import send_text

    ctx = ad_context or {}
    campaign_name = ctx.get("campaign_name", "")
    ad_name = ctx.get("ad_name", "")
    headline = ctx.get("headline", "")

    # Build header with as much context as available
    header = "💬 *New comments need your reply*\n"
    if campaign_name:
        header += f"📢 Campaign: _{campaign_name}_\n"
    if ad_name:
        header += f"📝 Ad: _{ad_name}_\n"
    elif ad_id:
        header += f"📝 Ad ID: _{ad_id[:15]}_\n"
    if headline:
        header += f"🔗 Copy: \"{headline[:80]}\"\n"

    lines = [header]

    for item in pending[:5]:  # max 5 per message
        short_id = item["db_id"][:8]
        obj_type = item["type"].upper()
        commenter = item.get("commenter", "Someone")
        text = (item.get("text") or "")[:80]
        suggestion = (item.get("suggested_reply") or "")[:120]

        lines.append(
            f"[{obj_type}] {commenter}: \"{text}\"\n"
            f"Suggested: {suggestion}\n"
            f"  auto reply {short_id}\n"
            f"  reply comment {short_id}: your text\n"
            f"  skip comment {short_id}\n"
        )

    send_text(admin_wa_id, "\n".join(lines), tenant)

    # Mark as notified — cast to uuid[] to avoid text vs uuid type mismatch
    db_ids = [item["db_id"] for item in pending[:5]]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE comment_replies
                   SET wa_notified_at=NOW(), wa_notify_count=wa_notify_count+1, updated_at=NOW()
                   WHERE id::text = ANY(%s)""",
                (db_ids,),
            )


def _write_objections(
    platform: str, account_id: str, ad_id: str,
    type_counts: dict[str, int], examples: list[str],
):
    """Write aggregate type counts to fact_objections_daily."""
    today = date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            for obj_type, count in type_counts.items():
                if count <= 0:
                    continue
                cur.execute(
                    """
                    INSERT INTO fact_objections_daily
                      (platform, account_id, entity_level, entity_id, day, objection_type, count, examples_json)
                    VALUES (%s,%s,'ad',%s,%s,%s,%s,%s)
                    ON CONFLICT (platform, account_id, entity_level, entity_id, day, objection_type)
                    DO UPDATE SET
                      count = fact_objections_daily.count + EXCLUDED.count,
                      examples_json = EXCLUDED.examples_json
                    """,
                    (platform, account_id, ad_id, today, obj_type, count, json.dumps(examples[:3])),
                )


def run_comment_intelligence(platform: str, account_id: str, tenant: dict = None) -> dict:
    ad_ids = _fetch_active_ad_ids(platform, account_id)
    if not ad_ids:
        return {"ok": True, "ads_processed": 0, "total_comments": 0}

    admin_wa_id = (tenant or {}).get("admin_wa_id") or ""
    product_context = (tenant or {}).get("product_context") or ""

    total_new = 0
    total_auto_replied = 0
    total_queued = 0
    ads_processed = 0

    for ad_id in ad_ids[:10]:
        comments = _fetch_ad_comments(ad_id, tenant)
        if not comments:
            continue

        new_comments = _get_new_comments(platform, account_id, comments)
        if not new_comments:
            continue

        # Classify all new comments in a single Claude call
        classified_list = _classify_comments_batch(new_comments, ad_id, product_context)
        classified_map = {c["comment_id"]: c for c in classified_list if c.get("comment_id")}

        type_counts: dict[str, int] = {}
        example_texts: list[str] = []
        pending_for_wa: list[dict] = []

        for comment in new_comments:
            comment_id = comment.get("id", "")
            classified = classified_map.get(comment_id, {"type": "other", "suggested_reply": ""})

            db_id = _save_comment(platform, account_id, ad_id, comment, classified)
            if not db_id:
                continue  # Duplicate (race condition)

            obj_type = classified.get("type", "other")
            suggested_reply = classified.get("suggested_reply", "")
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
            if comment.get("message"):
                example_texts.append(comment["message"][:100])

            total_new += 1

            if obj_type in AUTO_REPLY_TYPES and suggested_reply:
                _auto_reply_to_meta(comment_id, suggested_reply, db_id, tenant)
                total_auto_replied += 1

            elif obj_type in HUMAN_REVIEW_TYPES:
                frm = comment.get("from") or {}
                pending_for_wa.append({
                    "db_id": db_id,
                    "type": obj_type,
                    "commenter": frm.get("name", "Someone"),
                    "text": comment.get("message", ""),
                    "suggested_reply": suggested_reply,
                })
                total_queued += 1

        _write_objections(platform, account_id, ad_id, type_counts, example_texts)

        if pending_for_wa and admin_wa_id:
            ad_ctx = _get_ad_context(ad_id, platform, account_id)
            _notify_wa_pending(pending_for_wa, ad_id, admin_wa_id, tenant, ad_context=ad_ctx)

        ads_processed += 1
        time.sleep(0.5)

    return {
        "ok": True,
        "ads_processed": ads_processed,
        "total_comments": total_new,
        "auto_replied": total_auto_replied,
        "queued_for_review": total_queued,
    }
