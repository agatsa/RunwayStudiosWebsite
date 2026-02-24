import os, json, time, requests, threading
import psycopg2
import psycopg2.pool
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

AGENT_SWARM_URL = os.getenv("AGENT_SWARM_URL", "").rstrip("/")


def _agent_swarm_post(path: str, payload: dict, timeout: int = 60) -> requests.Response:
    """Call an agent-swarm endpoint with IAM identity token + cron token."""
    url = f"{AGENT_SWARM_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if CRON_TOKEN := os.getenv("CRON_TOKEN", ""):
        headers["X-Cron-Token"] = CRON_TOKEN
    try:
        meta = requests.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
            f"?audience={AGENT_SWARM_URL}",
            headers={"Metadata-Flavor": "Google"},
            timeout=5,
        )
        if meta.status_code == 200:
            headers["Authorization"] = f"Bearer {meta.text}"
    except Exception as e:
        print(f"Could not fetch identity token: {e}")
    return requests.post(url, json=payload, headers=headers, timeout=timeout)

app = FastAPI()

# =========================
# WhatsApp Cloud API
# =========================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_verify_token_123")
if not os.getenv("VERIFY_TOKEN"):
    print("⚠️  WARNING: VERIFY_TOKEN env var is not set. Using insecure default 'my_verify_token_123'. Set VERIFY_TOKEN in production!")
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
ADMIN = os.getenv("ADMIN_WA_ID", "918826283840")  # fallback admin number

META_API_VERSION = os.getenv("META_API_VERSION", "v21.0")
GRAPH = f"https://graph.facebook.com/{META_API_VERSION}"

# =========================
# Meta Ads API
# =========================
META_ADS_TOKEN = os.getenv("META_ADS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
META_GRAPH = f"https://graph.facebook.com/{META_API_VERSION}"

# =========================
# Cron protection
# =========================
CRON_TOKEN = os.getenv("CRON_TOKEN", "")

# =========================
# Database (for account lookup)
# =========================
DATABASE_URL = os.getenv("DATABASE_URL", "")
_pg_pool = None


def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None and DATABASE_URL:
        try:
            _pg_pool = psycopg2.pool.SimpleConnectionPool(1, 3, DATABASE_URL)
            print("✅ DB pool ready (wa-bot account lookup)")
        except Exception as e:
            print(f"⚠️ DB pool failed: {e}")
    return _pg_pool


# =========================
# Tenant / Account lookup
# =========================
_ACCOUNT_CACHE: dict = {}
ACCOUNT_CACHE_TTL = 300  # 5 minutes


def _env_account() -> dict:
    """Construct account dict from env vars (backward compat for default account)."""
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "wa_phone_number_id": WA_PHONE_NUMBER_ID,
        "wa_access_token": WA_ACCESS_TOKEN,
        "meta_access_token": META_ADS_TOKEN,
        "ad_account_id": META_AD_ACCOUNT_ID,
        "admin_wa_id": ADMIN,
    }


def _get_account(phone_number_id: str) -> dict | None:
    """
    Look up account by WA phone_number_id from DB. In-memory cache, TTL 5 min.
    Falls back to env vars for the default account if DB is unavailable.
    """
    now = time.time()
    cached = _ACCOUNT_CACHE.get(phone_number_id)
    if cached and (now - cached["ts"]) < ACCOUNT_CACHE_TTL:
        return cached["data"]

    pool = _get_pg_pool()
    if not pool:
        if phone_number_id == WA_PHONE_NUMBER_ID:
            return _env_account()
        return None

    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, name, wa_phone_number_id, meta_access_token,
                      fb_page_id, ad_account_id, pixel_id, admin_wa_id, active
               FROM accounts
               WHERE wa_phone_number_id=%s AND active=TRUE""",
            (phone_number_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        pool.putconn(conn)

    if not row:
        return None

    data = {
        "id": str(row[0]),
        "name": row[1],
        "wa_phone_number_id": row[2],
        # meta_access_token in DB doubles as WA access token (same system user token)
        "wa_access_token": row[3] or WA_ACCESS_TOKEN,
        "meta_access_token": row[3] or META_ADS_TOKEN,
        "fb_page_id": row[4],
        "ad_account_id": row[5] or META_AD_ACCOUNT_ID,
        "pixel_id": row[6],
        "admin_wa_id": row[7] or ADMIN,
        "active": row[8],
    }
    _ACCOUNT_CACHE[phone_number_id] = {"data": data, "ts": now}
    return data


# =========================
# Firestore (state per tenant)
# =========================
FIRESTORE_ENABLED = os.getenv("FIRESTORE_ENABLED", "1") == "1"
_db = None
try:
    if FIRESTORE_ENABLED:
        from google.cloud import firestore
        _db = firestore.Client()
        print("✅ Firestore ready")
except Exception as e:
    _db = None
    print("⚠️ Firestore not available, using in-memory state:", str(e))

# Immutable template of default state fields (used as fallback per tenant)
_STATE_DEFAULTS = {
    "alert_threshold": None,
    "alert_last_sent_at": 0,
    "guard_threshold": None,
    "guard_enabled": False,
    "guard_last_action_at": 0,
    "pending_photo": None,
    "campaign_wip": None,
    "product_photo_pending": None,
    "campaign_product_pending": False,
    "product_selection_list": [],
    "page_selection_pending": False,
    "page_selection_list": [],
    "pixel_selection_pending": False,
    "pixel_selection_list": [],
}

# Per-tenant in-memory state, keyed by phone_number_id (fallback when Firestore unavailable)
_STATE_MEM: dict[str, dict] = {}

# In-memory cache: sender -> last listed campaigns (for pause/resume by index)
LAST_CAMPAIGN_LIST = {}


# ── State helpers (keyed by phone_number_id = one state doc per bot/tenant) ──

def _state_doc(phone_number_id: str = None):
    key = phone_number_id or WA_PHONE_NUMBER_ID or "default"
    return _db.collection("wa_bot_state").document(key) if _db else None


def get_state(phone_number_id: str = None) -> dict:
    key = phone_number_id or WA_PHONE_NUMBER_ID or "default"
    if _db:
        try:
            doc = _state_doc(phone_number_id).get()
            if doc.exists:
                data = doc.to_dict() or {}
                out = dict(_STATE_DEFAULTS)
                out.update(data)
                return out
        except Exception as e:
            print("Firestore get_state error:", str(e))
    return dict(_STATE_MEM.get(key, _STATE_DEFAULTS))


def set_state(patch: dict, phone_number_id: str = None):
    key = phone_number_id or WA_PHONE_NUMBER_ID or "default"
    current = dict(_STATE_MEM.get(key, _STATE_DEFAULTS))
    current.update(patch)
    _STATE_MEM[key] = current
    if _db:
        try:
            _state_doc(phone_number_id).set(patch, merge=True)
        except Exception as e:
            print("Firestore set_state error:", str(e))


# ── WhatsApp send helpers ────────────────────────────────

def send_text(to: str, text: str, account: dict = None) -> bool:
    token = (account or {}).get("wa_access_token") or WA_ACCESS_TOKEN
    phone_id = (account or {}).get("wa_phone_number_id") or WA_PHONE_NUMBER_ID
    if not token or not phone_id:
        print("❌ Missing WA token or phone_number_id")
        return False
    url = f"{GRAPH}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:3900]},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    print("SEND STATUS:", r.status_code, r.text[:400])
    return r.status_code < 300


# ── Meta Pages helper ────────────────────────────────────

def _fetch_meta_pages(account: dict) -> list:
    """
    Fetch all Facebook Pages the user manages.
    Checks two sources and merges:
      1. /me/accounts          — personal pages & pages with direct admin role
      2. /me/businesses → owned_pages — pages under Business Manager portfolios
    """
    token = (account or {}).get("meta_access_token") or META_ADS_TOKEN
    if not token:
        return []

    pages = {}  # keyed by page id to deduplicate

    # Source 1: personal / direct-role pages
    try:
        r = requests.get(
            f"{META_GRAPH}/me/accounts",
            params={"access_token": token, "fields": "id,name,category", "limit": "50"},
            timeout=15,
        )
        if r.ok:
            for p in r.json().get("data", []):
                pages[p["id"]] = p
    except Exception as e:
        print(f"_fetch_meta_pages /me/accounts error: {e}")

    # Source 2: Business Manager owned pages
    try:
        biz_r = requests.get(
            f"{META_GRAPH}/me/businesses",
            params={"access_token": token, "fields": "id,name", "limit": "20"},
            timeout=15,
        )
        if biz_r.ok:
            for biz in biz_r.json().get("data", []):
                biz_id = biz.get("id")
                if not biz_id:
                    continue
                owned_r = requests.get(
                    f"{META_GRAPH}/{biz_id}/owned_pages",
                    params={"access_token": token, "fields": "id,name,category", "limit": "50"},
                    timeout=15,
                )
                if owned_r.ok:
                    for p in owned_r.json().get("data", []):
                        pages[p["id"]] = p
    except Exception as e:
        print(f"_fetch_meta_pages /me/businesses error: {e}")

    return list(pages.values())


def _fetch_meta_pixels(account: dict) -> list:
    """Fetch all Meta Pixels linked to the ad account."""
    token = (account or {}).get("meta_access_token") or META_ADS_TOKEN
    ad_acct = _ad_acct(account)
    if not token or not ad_acct:
        return []
    try:
        r = requests.get(
            f"{META_GRAPH}/{ad_acct}/adspixels",
            params={"access_token": token, "fields": "id,name", "limit": "25"},
            timeout=15,
        )
        if r.ok:
            return r.json().get("data", [])
    except Exception as e:
        print(f"_fetch_meta_pixels error: {e}")
    return []


# ── Meta Ads helpers (per-account) ───────────────────────

def _ad_acct(account: dict = None):
    raw = (account or {}).get("ad_account_id") or META_AD_ACCOUNT_ID or ""
    ad_acct = raw.strip()
    if ad_acct.isdigit():
        ad_acct = f"act_{ad_acct}"
    return ad_acct


def meta_get_account_spend_today(account: dict = None):
    token = (account or {}).get("meta_access_token") or META_ADS_TOKEN
    ad_acct = _ad_acct(account)
    if not token or not ad_acct:
        return None, "❌ META_ADS_TOKEN or META_AD_ACCOUNT_ID missing."
    url = f"{META_GRAPH}/{ad_acct}/insights"
    params = {"date_preset": "today", "fields": "spend", "limit": "1", "access_token": token}
    r = requests.get(url, params=params, timeout=20)
    if r.status_code >= 300:
        return None, f"❌ Meta insights error {r.status_code}: {r.text[:250]}"
    data = (r.json() or {}).get("data", [])
    spend = float(data[0].get("spend") or 0.0) if data else 0.0
    return spend, None


def meta_list_campaigns(limit: int = 20, account: dict = None):
    token = (account or {}).get("meta_access_token") or META_ADS_TOKEN
    ad_acct = _ad_acct(account)
    if not token or not ad_acct:
        return None, "❌ META_ADS_TOKEN or META_AD_ACCOUNT_ID missing."
    url = f"{META_GRAPH}/{ad_acct}/campaigns"
    params = {"fields": "id,name,status", "limit": str(limit), "access_token": token}
    r = requests.get(url, params=params, timeout=20)
    if r.status_code >= 300:
        return None, f"❌ Meta campaigns error {r.status_code}: {r.text[:250]}"
    campaigns = (r.json() or {}).get("data", [])
    out = []
    for c in campaigns:
        cid = c.get("id")
        name = (c.get("name") or "")[:44]
        status = c.get("status") or "UNKNOWN"
        spend = 0.0
        try:
            ir = requests.get(
                f"{META_GRAPH}/{cid}/insights",
                params={"date_preset": "today", "fields": "spend", "access_token": token},
                timeout=20,
            )
            if ir.status_code < 300:
                d = (ir.json() or {}).get("data", [])
                if d:
                    spend = float(d[0].get("spend") or 0.0)
        except Exception as e:
            print("Insights error:", str(e))
        out.append({"id": cid, "name": name, "status": status, "spend": spend})
    out.sort(key=lambda x: x.get("spend", 0.0), reverse=True)
    return out, None


def meta_set_campaign_status(campaign_id: str, status: str, account: dict = None):
    token = (account or {}).get("meta_access_token") or META_ADS_TOKEN
    if not token:
        return "❌ META_ADS_TOKEN missing."
    url = f"{META_GRAPH}/{campaign_id}"
    data = {"status": status, "access_token": token}
    r = requests.post(url, data=data, timeout=20)
    if r.status_code >= 300:
        return f"❌ Meta update error {r.status_code}: {r.text[:250]}"
    return f"✅ Campaign {campaign_id} set to {status}"


def meta_pause_all_campaigns(max_count: int = 200, account: dict = None):
    rows, err = meta_list_campaigns(limit=max_count, account=account)
    if err:
        return err
    paused = 0
    failed = 0
    for c in rows:
        if (c.get("status") or "").upper() == "PAUSED":
            continue
        resp = meta_set_campaign_status(c["id"], "PAUSED", account)
        if resp.startswith("✅"):
            paused += 1
        else:
            failed += 1
        time.sleep(0.15)
    return f"🛑 Guard action: paused {paused} campaigns" + (f" (failed {failed})" if failed else "")


# ── Webhook verify ───────────────────────────────────────

@app.get("/webhooks/whatsapp")
def verify(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge"))
    return PlainTextResponse("fail")


# ── Incoming message handler ─────────────────────────────

@app.post("/webhooks/whatsapp")
async def receive(req: Request):
    data = await req.json()
    print("WEBHOOK PAYLOAD:", json.dumps(data)[:2000])

    value = (data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}))

    # ── Extract which bot number received this message ──
    phone_number_id = value.get("metadata", {}).get("phone_number_id", "") or WA_PHONE_NUMBER_ID

    messages = value.get("messages", [])
    if not messages:
        statuses = value.get("statuses", [])
        if statuses:
            print("STATUS EVENT:", json.dumps(statuses)[:1500])
        return "ok"

    msg = messages[0]
    sender = msg.get("from")
    mtype = msg.get("type")
    text = ""
    if mtype == "text":
        text = (msg.get("text", {}).get("body", "")).strip()
    print("INBOUND:", sender, mtype, text, "phone_number_id:", phone_number_id)

    # ── Load account for this bot number ──
    account = _get_account(phone_number_id) or _env_account()
    admin_wa_id = account.get("admin_wa_id") or ADMIN

    # Auth: only the account's admin can send commands
    if sender != admin_wa_id:
        send_text(sender, "⛔ Not authorized for commands.", account)
        return "ok"

    # ── Image message handler ────────────────────────────
    if mtype == "image":
        media_id = msg.get("image", {}).get("id", "")
        st_now = get_state(phone_number_id)

        # Product photo upload mode
        if st_now.get("product_photo_pending") is True:
            if not AGENT_SWARM_URL:
                send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
                return "ok"
            try:
                send_text(sender, "⏳ Uploading photo to CDN...", account)
                r = _agent_swarm_post(
                    "/product/upload",
                    {"media_id": media_id, "phone_number_id": phone_number_id},
                    timeout=60,
                )
                if r.ok and r.json().get("cdn_url"):
                    cdn_url = r.json()["cdn_url"]
                    set_state(
                        {"product_photo_pending": {"cdn_url": cdn_url, "step": "name"}},
                        phone_number_id,
                    )
                    send_text(
                        sender,
                        "Got it! 📦 What's this product called?\n"
                        "_e.g. EasyTouch Rhythm, EasyTouch Pro, Sanket Life Band_",
                        account,
                    )
                else:
                    set_state({"product_photo_pending": None}, phone_number_id)
                    send_text(sender, f"⚠️ Upload failed: {r.text[:200]}", account)
            except Exception as e:
                set_state({"product_photo_pending": None}, phone_number_id)
                send_text(sender, f"⚠️ Error uploading photo: {str(e)[:200]}", account)
            return "ok"

        # Creative edit reference photo
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/creative/pending",
                {"phone_number_id": phone_number_id},
                timeout=10,
            )
            if r.ok and r.json().get("creative_id"):
                cid = r.json()["creative_id"]
                set_state({"pending_photo": {"media_id": media_id, "creative_id": cid}}, phone_number_id)
                send_text(
                    sender,
                    "📷 Got your photo! What should I do with it?\n\n"
                    "*1* — Use this photo directly as the ad image\n"
                    "*2* — Use it as AI style reference (fal.ai generates new image inspired by it)",
                    account,
                )
            else:
                send_text(sender, "📷 Got your photo, but no pending creative found. Generate creatives first.", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error processing photo: {str(e)[:200]}", account)
        return "ok"

    cmd = text.strip().lower()
    st = get_state(phone_number_id)

    # ── Hard reset: "new campaign" or "cancel" always clears all pending state ──
    if cmd in ("new campaign", "cancel", "reset"):
        set_state({
            "page_selection_pending": False,
            "page_selection_list": [],
            "pixel_selection_pending": False,
            "pixel_selection_list": [],
            "campaign_product_pending": False,
            "product_selection_list": [],
            "campaign_wip": None,
            "pending_photo": None,
        }, phone_number_id)
        # Re-fetch fresh state so the "new campaign" handler below sees clean state
        st = get_state(phone_number_id)

    # ── Product photo pipeline: step "name" → step "url" → save ──
    product_photo_pending = st.get("product_photo_pending")

    if isinstance(product_photo_pending, dict) and product_photo_pending.get("step") == "name":
        name = text.strip()
        if not name:
            send_text(sender, "❌ Please type the product name.", account)
            return "ok"
        updated = dict(product_photo_pending)
        updated["name"] = name
        updated["step"] = "url"
        set_state({"product_photo_pending": updated}, phone_number_id)
        send_text(
            sender,
            "🔗 What's the *landing page URL* for this product?\n"
            "_e.g. https://easytouch.in/rhythm_\n\n"
            "Or type *skip* to skip.",
            account,
        )
        return "ok"

    if isinstance(product_photo_pending, dict) and product_photo_pending.get("step") == "url":
        import re as _re
        product_url = "" if cmd == "skip" else text.strip()
        cdn_url = product_photo_pending["cdn_url"]
        name = product_photo_pending["name"]
        slug = _re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")[:30] or "product"
        set_state({"product_photo_pending": None}, phone_number_id)
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            send_text(sender, "🔍 Analyzing product...", account)
            r = _agent_swarm_post(
                "/product/asset",
                {
                    "asset_type": slug, "cdn_url": cdn_url,
                    "name": name, "product_url": product_url,
                    "phone_number_id": phone_number_id,
                },
                timeout=60,
            )
            if r.ok:
                data = r.json()
                analysis = data.get("analysis", {})
                desc = analysis.get("product_description", "")
                placement = analysis.get("placement_instruction", "")
                colors = ", ".join(analysis.get("dominant_colors", []))
                category = analysis.get("placement_category", "")
                routing = {
                    "clothing_upper": "LEFFA virtual try-on",
                    "clothing_lower": "LEFFA virtual try-on",
                    "wearable_wrist": "IP-Adapter",
                }.get(category, "IP-Adapter")
                msg = f"✅ *{name}* saved!\n\n"
                if desc:
                    msg += f"🔍 {desc}\n\n"
                if placement:
                    msg += f"📍 Placement: {placement}\n"
                if colors:
                    msg += f"🎨 Colors: {colors}\n"
                msg += f"⚙️ Method: {routing}\n"
                if product_url:
                    msg += f"🔗 URL: {product_url}\n"
                msg += (
                    "\n🖼️ Generating 8 training image variations...\n"
                    "🎓 LoRA training will start automatically (~5 min total)\n"
                    "I'll message you when done."
                )
                send_text(sender, msg, account)
            else:
                send_text(sender, f"⚠️ Failed to save: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── Page selection: number pick or manual page ID entry ──
    if st.get("page_selection_pending"):
        pages = st.get("page_selection_list", [])
        raw = text.strip()

        # Handle "Enter page ID manually" option
        if raw.isdigit() and int(raw) == len(pages) + 1:
            # User picked the manual entry option — ask for page ID
            set_state({"page_selection_pending": "manual"}, phone_number_id)
            send_text(
                sender,
                "✏️ *Enter the Facebook Page ID:*\n\n"
                "_Find it at: facebook.com/YourPage → About → Page ID_\n"
                "_Or in Meta Business Suite → Pages_",
                account,
            )
            return "ok"

        # Handle manual page ID text input
        if st.get("page_selection_pending") == "manual":
            page_id_input = raw.strip()
            if not page_id_input.isdigit():
                send_text(sender, "❌ Page ID should be a number. Try again.", account)
                return "ok"
            fb_page_id = page_id_input
            fb_page_name = f"Page {fb_page_id}"
            # Try to look up the page name
            try:
                token = (account or {}).get("meta_access_token") or META_ADS_TOKEN
                pr = requests.get(
                    f"{META_GRAPH}/{fb_page_id}",
                    params={"fields": "id,name", "access_token": token},
                    timeout=10,
                )
                if pr.ok and pr.json().get("name"):
                    fb_page_name = pr.json()["name"]
            except Exception:
                pass
        elif not raw.isdigit():
            return "ok"  # ignore non-numeric input while in page selection
        else:
            idx = int(raw) - 1
            if idx < 0 or idx >= len(pages):
                send_text(sender, "❌ Invalid selection. Reply with a number from the list.", account)
                return "ok"
            selected_page = pages[idx]
            fb_page_id = selected_page.get("id", "")
            fb_page_name = selected_page.get("name", "")
        # Fetch pixels — if 2+ show selection, else auto-pick
        pixels = _fetch_meta_pixels(account)
        if len(pixels) >= 2:
            lines = [f"✅ Page: *{fb_page_name}*\n\n📊 *Which Pixel for tracking conversions?*\n"]
            for i, p in enumerate(pixels, 1):
                lines.append(f"*{i}.* {p.get('name', 'Pixel')}  `{p.get('id', '')}`")
            set_state({
                "page_selection_pending": False,
                "page_selection_list": [],
                "pixel_selection_pending": True,
                "pixel_selection_list": pixels,
                "campaign_product_pending": False,
                "campaign_wip": {"step": "pick_product", "fb_page_id": fb_page_id, "fb_page_name": fb_page_name},
            }, phone_number_id)
            send_text(sender, "\n".join(lines), account)
            return "ok"

        # Auto-select pixel (0 or 1 available)
        pixel_id = pixels[0].get("id", "") if pixels else ""
        pixel_name = pixels[0].get("name", "") if pixels else ""
        wip_base = {
            "step": "pick_product", "fb_page_id": fb_page_id, "fb_page_name": fb_page_name,
            "pixel_id": pixel_id, "pixel_name": pixel_name,
        }
        set_state({
            "page_selection_pending": False,
            "page_selection_list": [],
            "campaign_product_pending": False,
            "campaign_wip": wip_base,
        }, phone_number_id)
        # Fetch and show product list
        products = []
        try:
            r = requests.get(
                f"{AGENT_SWARM_URL}/products/list",
                headers={"X-Cron-Token": CRON_TOKEN},
                params={"phone_number_id": phone_number_id},
                timeout=15,
            )
            if r.ok:
                products = r.json().get("products", [])
        except Exception as e:
            print(f"Could not fetch products after page selection: {e}")
        if products:
            lora_icons = {"none": "⚪", "training": "🟡", "ready": "🟢", "failed": "🔴"}
            lines = [f"✅ Page: *{fb_page_name}*\n\n🎯 *Which product for this campaign?*\n"]
            for i, p in enumerate(products, 1):
                icon = lora_icons.get(p.get("lora_status", "none"), "⚪")
                name = p.get("name", p.get("asset_type", "Product"))
                lora_str = "LoRA ready ✨" if p.get("lora_status") == "ready" else f"LoRA {p.get('lora_status', 'none')}"
                lines.append(f"*{i}.* {icon} {name}  ({lora_str})")
            n = len(products)
            lines.append(f"\n*{n + 1}.* ➕ Add new product")
            lines.append(f"*{n + 2}.* ⏭ No product (text/abstract creatives only)")
            set_state({"campaign_product_pending": True, "product_selection_list": products}, phone_number_id)
            send_text(sender, "\n".join(lines), account)
        else:
            set_state({
                "campaign_product_pending": False,
                "campaign_wip": {
                    **wip_base,
                    "step": "url", "product_id": None, "product_url": "",
                    "occasion": "", "budget": 300, "duration": "ongoing",
                },
            }, phone_number_id)
            send_text(
                sender,
                f"✅ Page: *{fb_page_name}*\n\n"
                "🔗 *Landing page URL to scrape for ad copy?*\n"
                "_e.g. https://shop.myeasytouch.com/rhythm_\n\n"
                "_Or type_ *skip* _to continue without._",
                account,
            )
        return "ok"

    # ── Pixel selection: number pick ──────────────────────
    if st.get("pixel_selection_pending"):
        pixels = st.get("pixel_selection_list", [])
        raw = text.strip()
        if not raw.isdigit():
            send_text(sender, "❌ Please reply with a number to select a pixel.", account)
            return "ok"
        idx = int(raw) - 1
        if idx < 0 or idx >= len(pixels):
            send_text(sender, "❌ Invalid selection. Reply with a number from the list.", account)
            return "ok"
        selected_pixel = pixels[idx]
        pixel_id = selected_pixel.get("id", "")
        pixel_name = selected_pixel.get("name", pixel_id)
        current_wip = st.get("campaign_wip") or {}
        fb_page_id = current_wip.get("fb_page_id", "")
        fb_page_name = current_wip.get("fb_page_name", "")
        wip_base = {
            "step": "pick_product", "fb_page_id": fb_page_id, "fb_page_name": fb_page_name,
            "pixel_id": pixel_id, "pixel_name": pixel_name,
        }
        set_state({
            "pixel_selection_pending": False,
            "pixel_selection_list": [],
            "campaign_wip": wip_base,
        }, phone_number_id)
        # Fetch and show product list
        products = []
        try:
            r = requests.get(
                f"{AGENT_SWARM_URL}/products/list",
                headers={"X-Cron-Token": CRON_TOKEN},
                params={"phone_number_id": phone_number_id},
                timeout=15,
            )
            if r.ok:
                products = r.json().get("products", [])
        except Exception as e:
            print(f"Could not fetch products after pixel selection: {e}")
        if products:
            lora_icons = {"none": "⚪", "training": "🟡", "ready": "🟢", "failed": "🔴"}
            lines = [f"✅ Pixel: *{pixel_name}*\n\n🎯 *Which product for this campaign?*\n"]
            for i, p in enumerate(products, 1):
                icon = lora_icons.get(p.get("lora_status", "none"), "⚪")
                name = p.get("name", p.get("asset_type", "Product"))
                lora_str = "LoRA ready ✨" if p.get("lora_status") == "ready" else f"LoRA {p.get('lora_status', 'none')}"
                lines.append(f"*{i}.* {icon} {name}  ({lora_str})")
            n = len(products)
            lines.append(f"\n*{n + 1}.* ➕ Add new product")
            lines.append(f"*{n + 2}.* ⏭ No product (text/abstract creatives only)")
            set_state({"campaign_product_pending": True, "product_selection_list": products}, phone_number_id)
            send_text(sender, "\n".join(lines), account)
        else:
            set_state({
                "campaign_product_pending": False,
                "campaign_wip": {
                    **wip_base,
                    "step": "url", "product_id": None, "product_url": "",
                    "occasion": "", "budget": 300, "duration": "ongoing",
                },
            }, phone_number_id)
            send_text(
                sender,
                f"✅ Pixel: *{pixel_name}*\n\n"
                "🔗 *Landing page URL to scrape for ad copy?*\n"
                "_e.g. https://shop.myeasytouch.com/rhythm_\n\n"
                "_Or type_ *skip* _to continue without._",
                account,
            )
        return "ok"

    # ── Campaign product selection: number pick ──────────
    if st.get("campaign_product_pending") and text.strip().isdigit():
        products = st.get("product_selection_list", [])
        idx = int(text.strip()) - 1
        n = len(products)
        # Preserve fb_page_id and pixel_id from page/pixel selection steps
        current_wip = st.get("campaign_wip") or {}
        fb_page_id = current_wip.get("fb_page_id", "")
        fb_page_name = current_wip.get("fb_page_name", "")
        pixel_id = current_wip.get("pixel_id", "")
        pixel_name = current_wip.get("pixel_name", "")

        if idx == n:
            set_state({"campaign_product_pending": False, "product_photo_pending": True}, phone_number_id)
            send_text(sender, "📷 Send me a photo of the new product.", account)
            return "ok"
        elif idx == n + 1:
            set_state({
                "campaign_product_pending": False,
                "product_selection_list": [],
                "campaign_wip": {
                    "step": "url", "fb_page_id": fb_page_id, "fb_page_name": fb_page_name,
                    "pixel_id": pixel_id, "pixel_name": pixel_name,
                    "occasion": "", "budget": 300, "duration": "ongoing", "product_id": None, "product_url": "",
                },
            }, phone_number_id)
            send_text(
                sender,
                "🔗 *Landing page URL to scrape for ad copy?*\n"
                "_I'll scrape it for current pricing, offers and features._\n\n"
                "_Or type_ *skip* _to continue without._",
                account,
            )
            return "ok"
        elif 0 <= idx < n:
            selected = products[idx]
            product_id = selected["asset_type"]
            stored_url = selected.get("product_url") or ""
            lora_icon = "🟢" if selected.get("lora_status") == "ready" else "⚪"
            set_state({
                "campaign_product_pending": False,
                "product_selection_list": [],
                "campaign_wip": {
                    "step": "url", "fb_page_id": fb_page_id, "fb_page_name": fb_page_name,
                    "pixel_id": pixel_id, "pixel_name": pixel_name,
                    "product_id": product_id, "product_name": selected.get("name", product_id),
                    "product_url": stored_url, "occasion": "", "budget": 300, "duration": "ongoing",
                },
            }, phone_number_id)
            if stored_url:
                send_text(
                    sender,
                    f"✅ {lora_icon} *{selected.get('name', product_id)}* selected.\n\n"
                    f"🔗 *Landing page URL for this campaign?*\n\n"
                    f"Stored: {stored_url}\n\n"
                    "Reply *same* to use this, or type a different URL.",
                    account,
                )
            else:
                send_text(
                    sender,
                    f"✅ {lora_icon} *{selected.get('name', product_id)}* selected.\n\n"
                    "🔗 *Landing page URL to scrape for ad copy?*\n"
                    "_e.g. https://shop.myeasytouch.com/rhythm_\n\n"
                    "_Or type_ *skip* _to continue without._",
                    account,
                )
            return "ok"
        else:
            send_text(sender, "❌ Invalid selection. Please reply with a number from the list.", account)
            return "ok"

    # ── Pending photo choice: 1 = use directly, 2 = AI style reference ──
    pending_photo = st.get("pending_photo")
    if cmd in ("1", "2") and pending_photo:
        edit_type = "reference_direct" if cmd == "1" else "reference_ai"
        set_state({"pending_photo": None}, phone_number_id)
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            ack = "✅ Using your photo directly as the ad image..." if cmd == "1" else "🎨 Generating AI variation inspired by your photo..."
            send_text(sender, ack, account)
            r = _agent_swarm_post(
                "/creative/edit",
                {
                    "creative_id": pending_photo["creative_id"],
                    "edit_type": edit_type,
                    "media_id": pending_photo["media_id"],
                    "phone_number_id": phone_number_id,
                },
                timeout=120,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Photo edit failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── Edit commands ────────────────────────────────────

    def _parse_edit_cmd(raw_text: str, prefix: str):
        rest = raw_text[len(prefix):].strip()
        if rest.startswith(":"):
            return "", rest[1:].strip()
        colon = rest.find(":")
        if colon > 0:
            maybe_id = rest[:colon].strip()
            if maybe_id and " " not in maybe_id and maybe_id.replace("-", "").isalnum():
                return maybe_id.lower(), rest[colon + 1:].strip()
        return "", rest

    if cmd.startswith("edit copy"):
        creative_id, instructions = _parse_edit_cmd(text, "edit copy")
        if not instructions:
            send_text(sender, "❌ Usage:\n`edit copy: <instructions>`\n`edit copy <id>: <instructions>`", account)
            return "ok"
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            send_text(sender, "✏️ Rewriting ad copy with Claude...", account)
            payload = {"edit_type": "copy", "instructions": instructions, "phone_number_id": phone_number_id}
            if creative_id:
                payload["creative_id"] = creative_id
            r = _agent_swarm_post("/creative/edit", payload, timeout=90)
            if not r.ok:
                send_text(sender, f"⚠️ Copy edit failed: {r.text[:200]}", account)
            else:
                data = r.json()
                if not data.get("ok"):
                    send_text(sender, f"⚠️ Copy edit failed: {data.get('error', 'unknown error')[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    if cmd.startswith("edit url"):
        creative_id, new_url = _parse_edit_cmd(text, "edit url")
        if not new_url.startswith("http"):
            send_text(sender, "❌ Usage:\n`edit url: https://...`\n`edit url <id>: https://...`", account)
            return "ok"
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            send_text(sender, "🔗 Updating landing page URL...", account)
            payload = {"edit_type": "url", "instructions": new_url, "phone_number_id": phone_number_id}
            if creative_id:
                payload["creative_id"] = creative_id
            r = _agent_swarm_post("/creative/edit", payload, timeout=30)
            if not r.ok:
                send_text(sender, f"⚠️ URL update failed: {r.text[:200]}", account)
            else:
                data = r.json()
                if not data.get("ok"):
                    send_text(sender, f"⚠️ URL update failed: {data.get('error', 'unknown error')[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    if cmd.startswith("edit image"):
        creative_id, instructions = _parse_edit_cmd(text, "edit image")
        if not instructions:
            send_text(sender, "❌ Usage:\n`edit image: <instructions>`\n`edit image <id>: <instructions>`", account)
            return "ok"
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            send_text(sender, "🎨 Regenerating image with fal.ai (may take ~30s)...", account)
            payload = {"edit_type": "image", "instructions": instructions, "phone_number_id": phone_number_id}
            if creative_id:
                payload["creative_id"] = creative_id
            r = _agent_swarm_post("/creative/edit", payload, timeout=120)
            if not r.ok:
                send_text(sender, f"⚠️ Image edit failed: {r.text[:200]}", account)
            else:
                data = r.json()
                if not data.get("ok"):
                    send_text(sender, f"⚠️ Image edit failed: {data.get('error', 'unknown error')[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── product photo ────────────────────────────────────
    if cmd == "product photo":
        set_state({"product_photo_pending": True}, phone_number_id)
        send_text(
            sender,
            "📷 Send me the product photo now.\n\n"
            "_I'll analyze it, auto-generate 8 training variations, and start LoRA training automatically._\n"
            "_Just one photo is enough — the AI handles the rest!_",
            account,
        )
        return "ok"

    # ── products ─────────────────────────────────────────
    if cmd == "products":
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = requests.get(
                f"{AGENT_SWARM_URL}/products/list",
                headers={"X-Cron-Token": CRON_TOKEN},
                params={"phone_number_id": phone_number_id},
                timeout=15,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Could not fetch products: {r.text[:200]}", account)
                return "ok"
            products = r.json().get("products", [])
            if not products:
                send_text(
                    sender,
                    "No products stored yet.\n\n"
                    "Type *product photo* to upload your first product image.\n"
                    "The system will auto-generate training variations and start LoRA training.",
                    account,
                )
                return "ok"
            lora_icons = {"none": "⚪", "training": "🟡", "ready": "🟢", "failed": "🔴"}
            lines = ["📦 *Stored Products:*\n"]
            for p in products:
                icon = lora_icons.get(p.get("lora_status", "none"), "⚪")
                name = p.get("name") or p.get("asset_type", "")
                slug = p.get("asset_type", "")
                photos = p.get("photo_count", 0)
                lora_status = p.get("lora_status", "none")
                product_url = p.get("product_url", "")
                category = p.get("placement_category", "")
                desc = p.get("product_description", "")
                method = {
                    "clothing_upper": "LEFFA (virtual try-on)",
                    "clothing_lower": "LEFFA (virtual try-on)",
                    "wearable_wrist": "IP-Adapter",
                }.get(category, "IP-Adapter")
                if lora_status == "ready":
                    method = "LoRA (pixel-perfect) ✨"
                elif lora_status == "training":
                    method = "Training... (IP-Adapter fallback)"
                lines.append(
                    f"{icon} *{name}*\n"
                    f"  ID: `{slug}` | Photos: {photos} | LoRA: {lora_status}\n"
                    f"  Method: {method}"
                )
                if desc:
                    lines.append(f"  _{desc[:100]}_")
                if product_url:
                    lines.append(f"  🔗 {product_url}")
                lines.append("")
            lines.append(
                "*Commands:*\n"
                "• `product photo` — add new product (auto-trains LoRA)\n"
                "• `new campaign` — pick a product and generate creatives"
            )
            send_text(sender, "\n".join(lines), account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── train lora ───────────────────────────────────────
    if cmd.startswith("train lora"):
        import re as _re
        rest = text[len("train lora"):].strip().lstrip(":").strip()
        if not rest:
            send_text(sender, "❌ Usage: train lora: <product name>\n_e.g._ `train lora: EasyTouch Rhythm`", account)
            return "ok"
        asset_type = _re.sub(r"[^a-z0-9]+", "-", rest.lower().strip()).strip("-")[:30]
        if not asset_type:
            send_text(sender, "❌ Invalid product name.", account)
            return "ok"
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/products/train-lora",
                {"asset_type": asset_type, "phone_number_id": phone_number_id},
                timeout=15,
            )
            if r.ok and r.json().get("ok"):
                data = r.json()
                name = data.get("name", rest)
                photos = data.get("photo_count", 0)
                send_text(
                    sender,
                    f"🎓 *LoRA training started for {name}!*\n\n"
                    f"Photos: {photos}\n"
                    f"Est. time: 3-5 minutes\n\n"
                    "I'll message you when done.",
                    account,
                )
            else:
                send_text(sender, f"⚠️ Could not start training: {r.text[:300]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── new campaign ─────────────────────────────────────
    if cmd == "new campaign":
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"

        # Step 1: Fetch Meta pages and show numbered list
        pages = _fetch_meta_pages(account)
        if len(pages) >= 1:
            lines = ["🏠 *Which Facebook Page for this campaign?*\n"]
            for i, p in enumerate(pages, 1):
                lines.append(f"*{i}.* {p.get('name', 'Unknown')}  _{p.get('category', '')}_")
            lines.append(f"\n*{len(pages) + 1}.* ✏️ Enter page ID manually")
            set_state({
                "page_selection_pending": True,
                "page_selection_list": pages,
                "campaign_product_pending": False,
                "campaign_wip": None,
            }, phone_number_id)
            send_text(sender, "\n".join(lines), account)
            return "ok"

        # Only one (or zero) pages — skip page selection, use account default
        fb_page_id = (pages[0].get("id") if pages else "") or account.get("fb_page_id", "")
        fb_page_name = (pages[0].get("name") if pages else "") or ""

        # Fetch pixels — if 2+ show selection, else auto-pick
        pixels = _fetch_meta_pixels(account)
        if len(pixels) >= 2:
            lines = ["📊 *Which Pixel for tracking conversions?*\n"]
            for i, p in enumerate(pixels, 1):
                lines.append(f"*{i}.* {p.get('name', 'Pixel')}  `{p.get('id', '')}`")
            set_state({
                "pixel_selection_pending": True,
                "pixel_selection_list": pixels,
                "campaign_product_pending": False,
                "campaign_wip": {"step": "pick_product", "fb_page_id": fb_page_id, "fb_page_name": fb_page_name},
            }, phone_number_id)
            send_text(sender, "\n".join(lines), account)
            return "ok"

        # Auto-select pixel (0 or 1 available)
        pixel_id = pixels[0].get("id", "") if pixels else ""
        pixel_name = pixels[0].get("name", "") if pixels else ""
        wip_base = {
            "step": "pick_product", "fb_page_id": fb_page_id, "fb_page_name": fb_page_name,
            "pixel_id": pixel_id, "pixel_name": pixel_name,
        }

        # Fetch products
        products = []
        try:
            r = requests.get(
                f"{AGENT_SWARM_URL}/products/list",
                headers={"X-Cron-Token": CRON_TOKEN},
                params={"phone_number_id": phone_number_id},
                timeout=15,
            )
            if r.ok:
                products = r.json().get("products", [])
        except Exception as e:
            print(f"Could not fetch products for campaign: {e}")

        if products:
            lora_icons = {"none": "⚪", "training": "🟡", "ready": "🟢", "failed": "🔴"}
            lines = ["🎯 *Which product should this campaign feature?*\n"]
            for i, p in enumerate(products, 1):
                icon = lora_icons.get(p.get("lora_status", "none"), "⚪")
                name = p.get("name", p.get("asset_type", "Product"))
                lora_str = "LoRA ready ✨" if p.get("lora_status") == "ready" else f"LoRA {p.get('lora_status', 'none')}"
                lines.append(f"*{i}.* {icon} {name}  ({lora_str})")
            n = len(products)
            lines.append(f"\n*{n + 1}.* ➕ Add new product")
            lines.append(f"*{n + 2}.* ⏭ No product (text/abstract creatives only)")
            set_state({
                "campaign_product_pending": True,
                "product_selection_list": products,
                "campaign_wip": wip_base,
            }, phone_number_id)
            send_text(sender, "\n".join(lines), account)
        else:
            set_state({
                "campaign_wip": {
                    **wip_base,
                    "step": "url", "product_id": None, "product_url": "",
                    "occasion": "", "budget": 300, "duration": "ongoing",
                },
            }, phone_number_id)
            send_text(
                sender,
                "🔗 *Landing page URL to scrape for ad copy?*\n"
                "_I'll scrape it for current pricing, offers and features._\n\n"
                "_Or type_ *skip* _to continue without._",
                account,
            )
        return "ok"

    # ── Campaign wip step handler ─────────────────────────
    campaign_wip = st.get("campaign_wip")
    if campaign_wip and isinstance(campaign_wip, dict):
        step = campaign_wip.get("step", 0)

        if step == "url":
            url_input = text.strip()
            url_lower = url_input.lower()
            if url_lower == "same":
                pass  # keep pre-filled product_url as-is
            elif url_lower == "skip":
                campaign_wip["product_url"] = ""
            else:
                campaign_wip["product_url"] = url_input
            campaign_wip["step"] = 1
            set_state({"campaign_wip": campaign_wip}, phone_number_id)
            send_text(
                sender,
                "Step 1/3 — What's the *occasion or goal* for this campaign?\n"
                "_e.g. Holi festival, World Diabetes Day, product launch, monsoon sale_",
                account,
            )
            return "ok"

        if step == 1:
            campaign_wip["occasion"] = text
            campaign_wip["step"] = 2
            set_state({"campaign_wip": campaign_wip}, phone_number_id)
            send_text(
                sender,
                f"✅ Got it — *{text}*\n\n"
                "Step 2/3 — What's your *daily budget in ₹*?\n"
                "_Reply a number, e.g. 500. Default is ₹300._",
                account,
            )
            return "ok"

        if step == 2:
            if text.strip().isdigit():
                campaign_wip["budget"] = int(text.strip())
            else:
                campaign_wip["budget"] = 300
            campaign_wip["step"] = 3
            set_state({"campaign_wip": campaign_wip}, phone_number_id)
            send_text(
                sender,
                f"✅ Budget: ₹{campaign_wip['budget']}/day\n\n"
                "Step 3/3 — How many *days* should this run?\n"
                "_Reply a number, e.g. 7. Or type_ *ongoing* _for no end date._",
                account,
            )
            return "ok"

        if step == 3:
            campaign_wip["duration"] = text.strip() or "ongoing"
            occasion = campaign_wip["occasion"]
            budget = campaign_wip["budget"]
            duration = campaign_wip["duration"]
            product_id = campaign_wip.get("product_id")
            product_name = campaign_wip.get("product_name") or product_id or ""
            product_url = campaign_wip.get("product_url") or ""
            fb_page_id = campaign_wip.get("fb_page_id", "")
            fb_page_name = campaign_wip.get("fb_page_name", "")
            pixel_id = campaign_wip.get("pixel_id", "")
            pixel_name = campaign_wip.get("pixel_name", "")
            set_state({"campaign_wip": None}, phone_number_id)

            trigger_reason = (
                f"CUSTOM CAMPAIGN: Occasion={occasion}, Budget=₹{budget}/day, "
                f"Duration={duration}. "
                f"Generate high-converting ad concepts specifically tailored to this brief."
            )
            if not AGENT_SWARM_URL:
                send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
                return "ok"

            confirm = f"✅ *Got it!* Generating 2 ad concepts for:\n"
            if fb_page_name:
                confirm += f"• Page: {fb_page_name}\n"
            if pixel_name:
                confirm += f"• Pixel: {pixel_name}\n"
            if product_name:
                confirm += f"• Product: {product_name}\n"
            confirm += f"• Occasion: {occasion}\n"
            confirm += f"• Budget: ₹{budget}/day\n"
            confirm += f"• Duration: {duration}\n"
            if product_url:
                confirm += f"• URL: {product_url} _(will be scraped)_\n"
            confirm += "\n⏳ This takes ~60s — concepts will arrive shortly."
            send_text(sender, confirm, account)

            try:
                payload = {
                    "trigger_reason": trigger_reason,
                    "daily_budget_inr": budget,
                    "product_id": product_id,
                    "product_url": product_url or None,
                    "phone_number_id": phone_number_id,
                }
                if fb_page_id:
                    payload["fb_page_id"] = fb_page_id
                if pixel_id:
                    payload["pixel_id"] = pixel_id
                _agent_swarm_post("/cron/creative-gen", payload, timeout=15)
            except Exception as e:
                print(f"Creative gen trigger error: {e}")
            return "ok"

    # ── status ───────────────────────────────────────────
    if cmd == "status":
        send_text(sender, "🟢 Bot alive. WhatsApp OK.", account)
        return "ok"

    # ── today ────────────────────────────────────────────
    if cmd == "today":
        spend, err = meta_get_account_spend_today(account)
        if err:
            send_text(sender, err, account)
            return "ok"
        rows, err2 = meta_list_campaigns(limit=10, account=account)
        if err2:
            send_text(sender, f"Today spend: ₹{int(spend)}\n\n{err2}", account)
            return "ok"
        lines = [f"📊 Today Spend: ₹{int(spend)}", "Top campaigns (by spend):"]
        for i, c in enumerate(rows[:5], start=1):
            lines.append(f"{i}) {c['name']} | {c['status']} | ₹{int(c['spend'])}")
        send_text(sender, "\n".join(lines), account)
        return "ok"

    # ── alerts ───────────────────────────────────────────
    if cmd.startswith("alert "):
        parts = cmd.split()
        if len(parts) != 2 or not parts[1].isdigit():
            send_text(sender, "❌ Format: alert 5000", account)
            return "ok"
        threshold = int(parts[1])
        set_state({"alert_threshold": threshold}, phone_number_id)
        send_text(sender, f"✅ Alert set: notify when today spend crosses ₹{threshold}", account)
        return "ok"

    if cmd in ("alerts off", "alert off"):
        set_state({"alert_threshold": None, "alert_last_sent_at": 0}, phone_number_id)
        send_text(sender, "✅ Alerts disabled.", account)
        return "ok"

    if cmd in ("alert status", "alerts status"):
        thr = st.get("alert_threshold")
        send_text(sender, f"🔔 Alert threshold: {thr if thr else 'OFF'}", account)
        return "ok"

    # ── guard ────────────────────────────────────────────
    if cmd.startswith("guard on"):
        parts = cmd.split()
        if len(parts) != 3 or not parts[2].isdigit():
            send_text(sender, "❌ Format: guard on 20000", account)
            return "ok"
        gthr = int(parts[2])
        set_state({"guard_enabled": True, "guard_threshold": gthr}, phone_number_id)
        send_text(sender, f"🛡️ Guard ON: auto-pause if today spend > ₹{gthr}", account)
        return "ok"

    if cmd == "guard off":
        set_state({"guard_enabled": False}, phone_number_id)
        send_text(sender, "🛡️ Guard OFF.", account)
        return "ok"

    if cmd == "guard status":
        ge = st.get("guard_enabled", False)
        gt = st.get("guard_threshold")
        send_text(sender, f"🛡️ Guard: {'ON' if ge else 'OFF'} | Threshold: {gt if gt else '-'}", account)
        return "ok"

    # ── campaigns list + pause/resume ────────────────────
    if cmd in ("campaigns", "meta campaigns", "meta list"):
        rows, err = meta_list_campaigns(limit=10, account=account)
        if err:
            send_text(sender, err, account)
            return "ok"
        LAST_CAMPAIGN_LIST[sender] = rows
        lines = ["📣 Meta Campaigns (Top 10 by spend):"]
        for i, c in enumerate(rows, start=1):
            lines.append(f"{i}) {c['name']} | {c['status']} | ₹{int(c['spend'])}")
        lines.append("")
        lines.append("Reply: pause 3  OR  resume 3")
        send_text(sender, "\n".join(lines), account)
        return "ok"

    if cmd.startswith("pause ") or cmd.startswith("resume "):
        parts = cmd.split()
        if len(parts) != 2 or not parts[1].isdigit():
            send_text(sender, "❌ Format: pause 3  OR  resume 3", account)
            return "ok"
        action = parts[0]
        idx = int(parts[1])
        rows = LAST_CAMPAIGN_LIST.get(sender) or []
        if idx < 1 or idx > len(rows):
            send_text(sender, "❌ Invalid index. First send: campaigns", account)
            return "ok"
        campaign = rows[idx - 1]
        new_status = "PAUSED" if action == "pause" else "ACTIVE"
        resp = meta_set_campaign_status(campaign["id"], new_status, account)
        send_text(sender, resp, account)
        return "ok"

    # ── ugc video ─────────────────────────────────────────
    if cmd == "ugc video":
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        send_text(
            sender,
            "🎬 *Generating UGC Video Ads...*\n\n"
            "• HeyGen AI avatar testimonial\n"
            "• Kling lifestyle product video\n\n"
            "Takes ~5 min. I'll send both previews when ready.",
            account,
        )
        threading.Thread(
            target=_agent_swarm_post,
            args=("/cron/ugc-gen", {"phone_number_id": phone_number_id}),
            kwargs={"timeout": 600},
            daemon=True,
        ).start()
        return "ok"

    # ── confirm copy <id> → trigger image generation ─────
    if cmd.startswith("confirm copy"):
        parts = cmd.split()
        creative_short_id = parts[2].strip() if len(parts) >= 3 else ""
        if not creative_short_id or len(creative_short_id) < 6:
            send_text(sender, "❌ Format: confirm copy <id>\n_e.g._ `confirm copy ab12cd34`", account)
            return "ok"
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        send_text(sender, "🎨 Confirmed! Generating image with GPT-Image-1 (~30-60s)...", account)
        try:
            r = _agent_swarm_post(
                "/creative/generate-image",
                {"creative_id": creative_short_id, "phone_number_id": phone_number_id},
                timeout=120,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Could not start image generation: {r.text[:200]}", account)
            else:
                data = r.json()
                if not data.get("ok"):
                    send_text(sender, f"⚠️ {data.get('error', 'Unknown error')[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── approve video / reject video ──────────────────────
    if cmd.startswith("approve video ") or cmd.startswith("reject video "):
        parts = cmd.split()
        if len(parts) != 3 or len(parts[2]) < 6:
            send_text(sender, "❌ Format: approve video ab12cd34  OR  reject video ab12cd34", account)
            return "ok"
        decision = parts[0]
        video_short_id = parts[2].strip()
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/approval/video",
                {"video_id": video_short_id, "decision": decision, "phone_number_id": phone_number_id},
                timeout=120,
            )
            if r.ok:
                data = r.json()
                if not data.get("ok"):
                    send_text(sender, f"⚠️ {data.get('error', 'Unknown error')}", account)
            else:
                send_text(sender, f"⚠️ Video approval failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── approve creative / reject creative ───────────────
    if cmd.startswith("approve creative ") or cmd.startswith("reject creative "):
        parts = cmd.split()
        if len(parts) != 3 or len(parts[2]) < 6:
            send_text(sender, "❌ Format: approve creative abc12345  OR  reject creative abc12345", account)
            return "ok"
        decision = parts[0]
        creative_short_id = parts[2].strip()
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/approval/creative",
                {"creative_id": creative_short_id, "decision": decision, "phone_number_id": phone_number_id},
                timeout=60,
            )
            if r.ok:
                data = r.json()
                if not data.get("ok"):
                    send_text(sender, f"⚠️ {data.get('error', 'Unknown error')}", account)
            else:
                send_text(sender, f"⚠️ Creative approval failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── approve all strategy (bulk approve all pending approval actions) ──
    if cmd in ("approve all strategy", "approve all budgets", "approve all"):
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/strategy/bulk-approve",
                {"decision": "approve", "phone_number_id": phone_number_id},
                timeout=120,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Bulk approve failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── approve/reject by number(s): "approve 5" or "approve 5 6 7 8" ──
    # Must check before the generic "approve strategy" handler
    _ap_parts = cmd.split()
    if (
        len(_ap_parts) >= 2
        and _ap_parts[0] in ("approve", "reject")
        and all(p.isdigit() for p in _ap_parts[1:])
    ):
        decision = _ap_parts[0]
        numbers = [int(p) for p in _ap_parts[1:]]
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/strategy/approve-by-numbers",
                {"numbers": numbers, "decision": decision, "phone_number_id": phone_number_id},
                timeout=120,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Approval failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── approve strategy / reject strategy (legacy short-id format) ──
    if cmd.startswith("approve strategy ") or cmd.startswith("reject strategy "):
        parts = cmd.split()
        if len(parts) != 3 or len(parts[2]) < 6:
            send_text(sender, "❌ Format: approve strategy abc12345  OR  reject strategy abc12345", account)
            return "ok"
        decision = parts[0]
        action_short_id = parts[2].strip()
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/strategy/action/approve",
                {"action_id": action_short_id, "decision": decision, "phone_number_id": phone_number_id},
                timeout=60,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Strategy approval failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── approve / reject (budget governor) ───────────────
    if cmd.startswith("approve ") or cmd.startswith("reject "):
        parts = cmd.split()
        if len(parts) != 2 or len(parts[1]) < 6:
            send_text(sender, "❌ Format: approve abc12345  OR  reject abc12345", account)
            return "ok"
        decision = parts[0]
        action_short_id = parts[1].strip()
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/approval/respond",
                {"action_id": action_short_id, "decision": decision, "phone_number_id": phone_number_id},
                timeout=20,
            )
            if r.ok:
                data = r.json()
                if decision == "approve":
                    executed = data.get("executed", False)
                    send_text(sender, f"✅ Action {action_short_id} approved and {'executed' if executed else 'queued'}.", account)
                else:
                    send_text(sender, f"❌ Action {action_short_id} rejected.", account)
            else:
                send_text(sender, f"⚠️ Approval failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── comment commands ──────────────────────────────────
    # auto reply <id>
    if cmd.startswith("auto reply "):
        comment_short_id = cmd[len("auto reply "):].strip()
        if not comment_short_id or len(comment_short_id) < 6:
            send_text(sender, "❌ Format: auto reply <id>  (use short ID from comment notification)", account)
            return "ok"
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/comment/reply",
                {"comment_id": comment_short_id, "action": "auto_reply", "phone_number_id": phone_number_id},
                timeout=30,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Auto-reply failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # reply comment <id>: <text>
    if cmd.startswith("reply comment "):
        rest = text[len("reply comment "):].strip()
        colon_pos = rest.find(":")
        if colon_pos < 6:
            send_text(sender, "❌ Format: reply comment <id>: <your reply text>", account)
            return "ok"
        comment_short_id = rest[:colon_pos].strip().lower()
        reply_text = rest[colon_pos + 1:].strip()
        if not reply_text:
            send_text(sender, "❌ Reply text cannot be empty.", account)
            return "ok"
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/comment/reply",
                {
                    "comment_id": comment_short_id,
                    "action": "manual_reply",
                    "reply_text": reply_text,
                    "phone_number_id": phone_number_id,
                },
                timeout=30,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Reply failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # skip comment <id>
    if cmd.startswith("skip comment "):
        comment_short_id = cmd[len("skip comment "):].strip()
        if not comment_short_id or len(comment_short_id) < 6:
            send_text(sender, "❌ Format: skip comment <id>", account)
            return "ok"
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post(
                "/comment/reply",
                {"comment_id": comment_short_id, "action": "skip", "phone_number_id": phone_number_id},
                timeout=15,
            )
            if not r.ok:
                send_text(sender, f"⚠️ Skip failed: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # pending comments
    if cmd == "pending comments":
        if not AGENT_SWARM_URL:
            send_text(sender, "⚠️ AGENT_SWARM_URL not configured.", account)
            return "ok"
        try:
            r = _agent_swarm_post("/comment/pending", {"phone_number_id": phone_number_id}, timeout=15)
            if r.ok:
                items = r.json().get("pending", [])
                if not items:
                    send_text(sender, "No pending comments.", account)
                else:
                    lines = [f"*{len(items)} pending comment(s):*\n"]
                    for item in items[:8]:
                        lines.append(
                            f"[{item['type'].upper()}] {item['commenter']}: \"{item['text']}\"\n"
                            f"  auto reply {item['short_id']}\n"
                            f"  reply comment {item['short_id']}: your text\n"
                            f"  skip comment {item['short_id']}\n"
                        )
                    send_text(sender, "\n".join(lines), account)
            else:
                send_text(sender, f"⚠️ Could not fetch pending comments: {r.text[:200]}", account)
        except Exception as e:
            send_text(sender, f"⚠️ Error: {str(e)[:200]}", account)
        return "ok"

    # ── pending ───────────────────────────────────────────
    if cmd == "pending":
        send_text(sender, "📋 Pending approvals — reply 'approve/reject <id>'.", account)
        return "ok"

    # ── Conversational strategy chat (fallback for any unrecognized message) ──
    if AGENT_SWARM_URL and text.strip():
        try:
            r = _agent_swarm_post(
                "/strategy/chat",
                {"message": text, "phone_number_id": phone_number_id},
                timeout=60,
            )
            if r.ok:
                reply = r.json().get("reply", "")
                if reply:
                    send_text(sender, reply, account)
                    return "ok"
        except Exception as e:
            print(f"Strategy chat error: {e}")

    send_text(sender, (
        "Commands:\n"
        "status | today | campaigns\n"
        "alert 5000 | alerts off\n"
        "guard on 20000 | guard off\n"
        "pause 3 | resume 3\n"
        "approve 5 | reject 5 → approve/reject action #5\n"
        "approve 5 6 7 8 → approve multiple at once\n"
        "approve all → approve all pending actions\n"
        "approve creative <id> | reject creative <id>\n"
        "approve <id> | reject <id> | pending\n\n"
        "💬 Comment commands:\n"
        "  auto reply <id>\n"
        "  reply comment <id>: <text>\n"
        "  skip comment <id>\n"
        "  pending comments\n\n"
        "✏️ edit copy <id>: <instructions>\n"
        "✅ confirm copy <id> → generate image (GPT-Image-1)\n"
        "🎨 edit image: <instructions>\n"
        "🔗 edit url: https://...\n"
        "📷 Send a photo → use as ad image or AI reference\n\n"
        "🎯 *new campaign* → create a custom campaign (guided 3-step flow)\n"
        "📦 *product photo* → upload product photo (auto-trains LoRA)\n"
        "🎬 *ugc video* → generate HeyGen + Kling UGC video ads"
    ), account)
    return "ok"


# ── Cron endpoint ────────────────────────────────────────

@app.post("/cron/5min")
def cron_5min(request: Request):
    if CRON_TOKEN:
        token = request.headers.get("X-Cron-Token", "")
        if token != CRON_TOKEN:
            return {"ok": False, "error": "unauthorized"}

    now = int(time.time())

    # Fetch all active accounts from DB; fall back to default env-var account
    accounts_to_check = []
    pool = _get_pg_pool()
    if pool:
        conn = pool.getconn()
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, name, wa_phone_number_id, meta_access_token,
                          ad_account_id, admin_wa_id
                   FROM accounts WHERE active=TRUE"""
            )
            for row in cur.fetchall():
                accounts_to_check.append({
                    "id": str(row[0]),
                    "name": row[1],
                    "wa_phone_number_id": row[2],
                    "wa_access_token": row[3] or WA_ACCESS_TOKEN,
                    "meta_access_token": row[3] or META_ADS_TOKEN,
                    "ad_account_id": row[4] or META_AD_ACCOUNT_ID,
                    "admin_wa_id": row[5] or ADMIN,
                })
            cur.close()
        except Exception as e:
            print(f"cron_5min DB error: {e}")
        finally:
            pool.putconn(conn)

    if not accounts_to_check:
        accounts_to_check = [_env_account()]

    results = []
    for account in accounts_to_check:
        phone_number_id = account.get("wa_phone_number_id") or WA_PHONE_NUMBER_ID
        admin_wa_id = account.get("admin_wa_id") or ADMIN
        st = get_state(phone_number_id)

        spend, err = meta_get_account_spend_today(account)
        if err:
            print(f"cron spend error ({account.get('name', phone_number_id)}): {err}")
            results.append({"account": phone_number_id, "error": err})
            continue

        alert_thr = st.get("alert_threshold")
        last_alert = int(st.get("alert_last_sent_at") or 0)
        if alert_thr and spend >= float(alert_thr) and (now - last_alert) > (30 * 60):
            send_text(admin_wa_id, f"🔔 ALERT: Today spend crossed ₹{alert_thr}. Current: ₹{int(spend)}", account)
            set_state({"alert_last_sent_at": now}, phone_number_id)

        guard_enabled = bool(st.get("guard_enabled"))
        guard_thr = st.get("guard_threshold")
        last_guard = int(st.get("guard_last_action_at") or 0)
        if guard_enabled and guard_thr and spend > float(guard_thr) and (now - last_guard) > (60 * 60):
            summary = meta_pause_all_campaigns(max_count=200, account=account)
            send_text(admin_wa_id, f"🛡️ GUARD TRIGGERED\nSpend: ₹{int(spend)} > ₹{guard_thr}\n{summary}", account)
            set_state({"guard_last_action_at": now}, phone_number_id)

        results.append({"account": phone_number_id, "spend_today": spend})

    return {"ok": True, "accounts_checked": len(results), "results": results}
