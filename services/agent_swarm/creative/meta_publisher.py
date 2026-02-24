# services/agent_swarm/creative/meta_publisher.py
"""
Publishes an approved creative to Meta Ads:
1. Upload image → get hash
2. Create campaign
3. Create adset (targeting + budget)
4. Create ad creative (image + copy)
5. Create ad

Multi-tenant: credentials come from the tenant dict (passed in or loaded from DB
via the creative's tenant_id). Falls back to env-var defaults for backward compat.
"""
import json
import requests

from services.agent_swarm.config import (
    META_ADS_TOKEN, META_GRAPH, META_AD_ACCOUNT_ID,
    META_PIXEL_ID, META_PAGE_ID, NEW_CAMPAIGN_DAILY_BUDGET_INR, LANDING_PAGE_URL,
)
from services.agent_swarm.db import get_conn


def _tok(tenant: dict = None) -> str:
    return (tenant or {}).get("meta_access_token") or META_ADS_TOKEN


def _headers(tenant: dict = None) -> dict:
    return {"Authorization": f"Bearer {_tok(tenant)}"}


def _pixel(tenant: dict = None) -> str:
    return (tenant or {}).get("pixel_id") or META_PIXEL_ID


def _page_id_for(account_id: str, tenant: dict = None) -> str:
    """Get the Facebook Page ID. Uses tenant config first, then dynamic fallback."""
    pid = (tenant or {}).get("fb_page_id") or META_PAGE_ID
    if pid:
        return pid
    # Dynamic fallback: read page_id from the most recent existing ad
    try:
        r = requests.get(
            f"{META_GRAPH}/{account_id}/ads",
            params={
                "fields": "creative{object_story_spec}",
                "limit": "1",
                "access_token": _tok(tenant),
            },
            timeout=10,
        )
        if r.ok:
            ads = r.json().get("data", [])
            if ads:
                return ads[0]["creative"]["object_story_spec"]["page_id"]
    except Exception:
        pass
    return ""


def upload_image_from_url(image_url: str, account_id: str, tenant: dict = None) -> str:
    """Download image from URL and upload to Meta. Returns image hash."""
    import tempfile, urllib.request, os

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        urllib.request.urlretrieve(image_url, tmp.name)
        tmp_path = tmp.name

    url = f"{META_GRAPH}/{account_id}/adimages"
    with open(tmp_path, "rb") as f:
        r = requests.post(
            url,
            data={"access_token": _tok(tenant)},
            files={"filename": ("creative.jpg", f, "image/jpeg")},
            timeout=60,
        )

    os.unlink(tmp_path)

    if not r.ok:
        raise RuntimeError(f"Image upload failed: {r.status_code} {r.text[:300]}")

    images = r.json().get("images", {})
    for _name, info in images.items():
        return info["hash"]

    raise RuntimeError(f"No image hash in response: {r.text[:300]}")


def create_campaign(account_id: str, name: str, tenant: dict = None) -> str:
    """Create a new SALES campaign. Returns campaign_id."""
    url = f"{META_GRAPH}/{account_id}/campaigns"
    data = {
        "name": name,
        "objective": "OUTCOME_SALES",
        "status": "ACTIVE",
        "special_ad_categories": "[]",
        "is_adset_budget_sharing_enabled": "false",
        "access_token": _tok(tenant),
    }
    r = requests.post(url, data=data, timeout=20)
    if not r.ok:
        raise RuntimeError(f"Campaign creation failed: {r.status_code} {r.text[:300]}")
    return r.json()["id"]


def create_adset(
    account_id: str,
    campaign_id: str,
    name: str,
    daily_budget_inr: float = NEW_CAMPAIGN_DAILY_BUDGET_INR,
    tenant: dict = None,
) -> str:
    """Create adset with India targeting. Returns adset_id."""
    url = f"{META_GRAPH}/{account_id}/adsets"

    targeting = {
        "geo_locations": {"countries": ["IN"]},
        "age_min": 28,
        "age_max": 55,
        "publisher_platforms": ["facebook", "instagram"],
        "facebook_positions": ["feed", "story"],
        "instagram_positions": ["stream", "story"],
        "targeting_automation": {"advantage_audience": 0},
    }

    data = {
        "name": name,
        "campaign_id": campaign_id,
        "daily_budget": str(int(daily_budget_inr * 100)),  # Meta uses paise
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "promoted_object": json.dumps({
            "pixel_id": _pixel(tenant),
            "custom_event_type": "PURCHASE",
        }),
        "targeting": json.dumps(targeting),
        "status": "ACTIVE",
        "access_token": _tok(tenant),
    }

    r = requests.post(url, data=data, timeout=20)
    if not r.ok:
        raise RuntimeError(f"Adset creation failed: {r.status_code} {r.text[:300]}")
    return r.json()["id"]


def create_ad_creative(
    account_id: str,
    image_hash: str,
    primary_text: str,
    headline: str,
    description: str,
    cta: str = "SHOP_NOW",
    landing_page_url: str = None,
    tenant: dict = None,
) -> str:
    """Create ad creative with image + copy. Returns creative_id."""
    cta_map = {
        "Shop Now": "SHOP_NOW",
        "Learn More": "LEARN_MORE",
        "Get Offer": "GET_OFFER",
        "Order Now": "ORDER_NOW",
        "Sign Up": "SIGN_UP",
    }
    cta_type = cta_map.get(cta, "SHOP_NOW")

    # Use: per-creative URL → tenant landing page → global env var
    final_url = landing_page_url or (tenant or {}).get("landing_page_url") or LANDING_PAGE_URL

    object_story_spec = {
        "page_id": _page_id_for(account_id, tenant),
        "link_data": {
            "image_hash": image_hash,
            "link": final_url,
            "message": primary_text[:2000],
            "name": headline[:255],
            "description": description[:255],
            "call_to_action": {
                "type": cta_type,
                "value": {"link": final_url},
            },
        },
    }

    url = f"{META_GRAPH}/{account_id}/adcreatives"
    data = {
        "name": f"AI-Creative-{headline[:30]}",
        "object_story_spec": json.dumps(object_story_spec),
        "access_token": _tok(tenant),
    }
    r = requests.post(url, data=data, timeout=20)
    if not r.ok:
        raise RuntimeError(f"Creative creation failed: {r.status_code} {r.text[:300]}")
    return r.json()["id"]


def create_ad(account_id: str, adset_id: str, creative_id: str, name: str, tenant: dict = None) -> str:
    """Create the ad. Returns ad_id."""
    url = f"{META_GRAPH}/{account_id}/ads"
    data = {
        "name": name,
        "adset_id": adset_id,
        "creative": json.dumps({"creative_id": creative_id}),
        "status": "ACTIVE",
        "access_token": _tok(tenant),
    }
    r = requests.post(url, data=data, timeout=20)
    if not r.ok:
        raise RuntimeError(f"Ad creation failed: {r.status_code} {r.text[:300]}")
    return r.json()["id"]


def upload_video_from_url(video_url: str, account_id: str, tenant: dict = None) -> str:
    """Download video from URL and upload to Meta. Returns Meta video_id."""
    import tempfile, urllib.request, os

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        urllib.request.urlretrieve(video_url, tmp.name)
        tmp_path = tmp.name

    url = f"{META_GRAPH}/{account_id}/advideos"
    with open(tmp_path, "rb") as f:
        r = requests.post(
            url,
            data={"access_token": _tok(tenant), "name": "AI-UGC-Video"},
            files={"source": ("video.mp4", f, "video/mp4")},
            timeout=120,
        )

    os.unlink(tmp_path)

    if not r.ok:
        raise RuntimeError(f"Video upload failed: {r.status_code} {r.text[:300]}")

    meta_video_id = r.json().get("id")
    if not meta_video_id:
        raise RuntimeError(f"No video id in Meta response: {r.text[:300]}")

    return meta_video_id


def create_video_ad_creative(
    account_id: str,
    meta_video_id: str,
    primary_text: str,
    headline: str,
    cta: str = "Shop Now",
    landing_page_url: str = None,
    tenant: dict = None,
) -> str:
    """Create Meta ad creative using a video. Returns creative_id."""
    cta_map = {
        "Shop Now": "SHOP_NOW",
        "Learn More": "LEARN_MORE",
        "Get Offer": "GET_OFFER",
        "Order Now": "ORDER_NOW",
        "Sign Up": "SIGN_UP",
    }
    cta_type = cta_map.get(cta, "SHOP_NOW")
    final_url = landing_page_url or (tenant or {}).get("landing_page_url") or LANDING_PAGE_URL

    object_story_spec = {
        "page_id": _page_id_for(account_id, tenant),
        "video_data": {
            "video_id": meta_video_id,
            "message": primary_text[:2000],
            "title": headline[:255],
            "call_to_action": {
                "type": cta_type,
                "value": {"link": final_url},
            },
        },
    }

    url = f"{META_GRAPH}/{account_id}/adcreatives"
    data = {
        "name": f"AI-Video-{headline[:30]}",
        "object_story_spec": json.dumps(object_story_spec),
        "access_token": _tok(tenant),
    }
    r = requests.post(url, data=data, timeout=20)
    if not r.ok:
        raise RuntimeError(f"Video creative creation failed: {r.status_code} {r.text[:300]}")
    return r.json()["id"]


def publish_video_ad(video_id_db: str, tenant: dict = None) -> dict:
    """
    Full publishing pipeline for an approved video from video_queue.
    Returns dict with meta IDs or error.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT vq.platform, vq.account_id, vq.angle, vq.primary_text,
                       vq.headline, vq.cta, vq.video_url,
                       COALESCE(vq.daily_budget_inr, %s) AS daily_budget_inr,
                       vq.landing_page_url,
                       a.meta_access_token, a.fb_page_id, a.pixel_id,
                       a.landing_page_url AS acct_lp
                FROM video_queue vq
                LEFT JOIN accounts a ON a.id = vq.tenant_id
                WHERE vq.id=%s
                """,
                (NEW_CAMPAIGN_DAILY_BUDGET_INR, video_id_db),
            )
            row = cur.fetchone()

    if not row:
        return {"ok": False, "error": "Video not found"}

    (platform, account_id, angle, primary_text, headline, cta, video_url,
     daily_budget_inr, landing_page_url,
     db_meta_token, db_page_id, db_pixel_id, db_acct_lp) = row

    effective_tenant = {
        "meta_access_token": (tenant or {}).get("meta_access_token") or db_meta_token or META_ADS_TOKEN,
        "fb_page_id": (tenant or {}).get("fb_page_id") or db_page_id or META_PAGE_ID,
        "pixel_id": (tenant or {}).get("pixel_id") or db_pixel_id or META_PIXEL_ID,
        "landing_page_url": (tenant or {}).get("landing_page_url") or db_acct_lp or LANDING_PAGE_URL,
    }

    meta_account_id = account_id
    if meta_account_id and not meta_account_id.startswith("act_") and meta_account_id.isdigit():
        meta_account_id = f"act_{meta_account_id}"

    try:
        from datetime import datetime
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M")
        campaign_name = f"AI-Video-{angle[:20]}-{ts}"

        meta_video_id = upload_video_from_url(video_url, meta_account_id, effective_tenant)
        campaign_id = create_campaign(meta_account_id, campaign_name, effective_tenant)
        adset_id = create_adset(
            meta_account_id, campaign_id,
            f"{campaign_name}-adset", float(daily_budget_inr),
            effective_tenant,
        )
        ad_creative_id = create_video_ad_creative(
            meta_account_id, meta_video_id, primary_text, headline,
            cta=cta or "Shop Now",
            landing_page_url=landing_page_url or None,
            tenant=effective_tenant,
        )
        ad_id = create_ad(meta_account_id, adset_id, ad_creative_id, f"{campaign_name}-ad", effective_tenant)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE video_queue
                       SET status='published', meta_video_id=%s, meta_ad_id=%s, updated_at=NOW()
                       WHERE id=%s""",
                    (meta_video_id, ad_id, video_id_db),
                )

        return {
            "ok": True,
            "campaign_id": campaign_id,
            "adset_id": adset_id,
            "ad_id": ad_id,
            "meta_video_id": meta_video_id,
            "daily_budget_inr": float(daily_budget_inr),
        }

    except Exception as e:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE video_queue SET status='failed', updated_at=NOW() WHERE id=%s",
                    (video_id_db,),
                )
        return {"ok": False, "error": str(e)}


def post_comment_reply(comment_id: str, reply_text: str, tenant: dict = None) -> str:
    """
    Post a reply to a Meta ad comment.
    Uses POST /{comment_id}/comments with message=reply_text.
    Returns the new reply's comment_id from Meta.
    Raises RuntimeError on failure.
    """
    url = f"{META_GRAPH}/{comment_id}/comments"
    data = {
        "message": reply_text,
        "access_token": _tok(tenant),
    }
    r = requests.post(url, data=data, timeout=20)
    if not r.ok:
        raise RuntimeError(f"Comment reply failed: {r.status_code} {r.text[:300]}")
    return r.json().get("id", "")


def publish_creative(creative_id_db: str, tenant: dict = None) -> dict:
    """
    Full publishing pipeline for an approved creative from creative_queue.
    Loads per-tenant Meta credentials via LEFT JOIN on accounts.
    tenant dict (if provided) overrides DB credentials.
    Returns dict with meta IDs or error.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cq.platform, cq.account_id, cq.angle, cq.primary_text,
                       cq.headline, cq.description, cq.cta, cq.image_url,
                       COALESCE(cq.daily_budget_inr, %s) AS daily_budget_inr,
                       cq.landing_page_url,
                       a.meta_access_token, a.fb_page_id, a.pixel_id,
                       a.landing_page_url AS acct_landing_page_url,
                       cq.fb_page_id AS cq_fb_page_id,
                       cq.pixel_id   AS cq_pixel_id
                FROM creative_queue cq
                LEFT JOIN accounts a ON a.id = cq.tenant_id
                WHERE cq.id=%s
                """,
                (NEW_CAMPAIGN_DAILY_BUDGET_INR, creative_id_db),
            )
            row = cur.fetchone()

    if not row:
        return {"ok": False, "error": "Creative not found"}

    (platform, account_id, angle, primary_text, headline,
     description, cta, image_url, daily_budget_inr, landing_page_url,
     db_meta_token, db_page_id, db_pixel_id, db_acct_landing_page,
     cq_fb_page_id, cq_pixel_id) = row

    # Build effective tenant dict.
    # Priority for fb_page_id / pixel_id:
    #   1. Value stored in creative_queue at generation time (per-campaign choice)
    #   2. Account default from accounts table
    #   3. Global env-var fallback
    effective_tenant = {
        "meta_access_token": (tenant or {}).get("meta_access_token") or db_meta_token or META_ADS_TOKEN,
        "fb_page_id": cq_fb_page_id or db_page_id or META_PAGE_ID,
        "pixel_id":   cq_pixel_id   or db_pixel_id or META_PIXEL_ID,
        "landing_page_url": (tenant or {}).get("landing_page_url") or db_acct_landing_page or LANDING_PAGE_URL,
    }

    # Resolve the Meta account_id (e.g. act_643294036096788)
    meta_account_id = account_id
    if meta_account_id and not meta_account_id.startswith("act_") and meta_account_id.isdigit():
        meta_account_id = f"act_{meta_account_id}"

    try:
        image_hash = upload_image_from_url(image_url, meta_account_id, effective_tenant)

        from datetime import datetime
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M")
        campaign_name = f"AI-{angle[:25]}-{ts}"
        campaign_id = create_campaign(meta_account_id, campaign_name, effective_tenant)

        adset_id = create_adset(
            meta_account_id, campaign_id,
            f"{campaign_name}-adset", float(daily_budget_inr),
            effective_tenant,
        )

        ad_creative_id = create_ad_creative(
            meta_account_id, image_hash, primary_text, headline,
            description or "", cta or "Shop Now",
            landing_page_url=landing_page_url or None,
            tenant=effective_tenant,
        )

        ad_id = create_ad(meta_account_id, adset_id, ad_creative_id, f"{campaign_name}-ad", effective_tenant)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE creative_queue
                    SET status='published', image_meta_hash=%s,
                        meta_campaign_id=%s, meta_adset_id=%s, meta_ad_id=%s,
                        updated_at=NOW()
                    WHERE id=%s
                    """,
                    (image_hash, campaign_id, adset_id, ad_id, creative_id_db),
                )

        return {
            "ok": True,
            "campaign_id": campaign_id,
            "adset_id": adset_id,
            "ad_id": ad_id,
            "daily_budget_inr": float(daily_budget_inr),
            "note": "Campaign created — ACTIVE and live.",
        }

    except Exception as e:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE creative_queue SET status='failed', reject_reason=%s WHERE id=%s",
                    (str(e)[:500], creative_id_db),
                )
        return {"ok": False, "error": str(e)}
