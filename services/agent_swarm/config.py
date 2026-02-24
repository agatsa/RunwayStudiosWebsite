# services/agent_swarm/config.py
import os

# ── Anthropic ──────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# ── Meta Ads ───────────────────────────────────────────────
META_ADS_TOKEN = os.getenv("META_ADS_TOKEN") or os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")
META_API_VERSION = os.getenv("META_API_VERSION", "v21.0")
META_GRAPH = f"https://graph.facebook.com/{META_API_VERSION}"

# ── WhatsApp ───────────────────────────────────────────────
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID", "")
WA_REPORT_NUMBER = os.getenv("WA_REPORT_NUMBER", "918826283840")

# ── Database ───────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Business Rules ─────────────────────────────────────────
TARGET_ROAS = float(os.getenv("TARGET_ROAS", "2.5"))
MAX_CPA = float(os.getenv("MAX_CPA", "500"))
DAILY_SPEND_CAP = float(os.getenv("DAILY_SPEND_CAP", "20000"))
HOURLY_SCALE_MAX_PCT = float(os.getenv("HOURLY_SCALE_MAX_PCT", "0.15"))   # 15%
APPROVAL_THRESHOLD = float(os.getenv("APPROVAL_THRESHOLD", "10000"))       # ₹10k
NEW_CAMPAIGN_THRESHOLD = float(os.getenv("NEW_CAMPAIGN_THRESHOLD", "25000"))  # ₹25k

# ── Landing Page ───────────────────────────────────────────
# DEPRECATED: use workspace.store_url instead. Kept as env-var fallback.
LANDING_PAGE_URL = os.getenv("LANDING_PAGE_URL", "https://agatsaone.com/")

# ── Image Generation (fal.ai) ──────────────────────────────
FAL_KEY = os.getenv("FAL_KEY", "")

# ── Image Generation (OpenAI gpt-image-1) ──────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ── Video Generation (HeyGen) ──────────────────────────────
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY", "")

# ── Product Context (DEPRECATED — use products table via core.workspace) ───
# Kept for backward compatibility with agents that haven't been migrated yet.
# New code should call build_product_context(workspace) from core.workspace.
# This env var is the last-resort fallback when DB is unavailable.
PRODUCT_CONTEXT = os.getenv("PRODUCT_CONTEXT", "")

# ── Google Ads ─────────────────────────────────────────────
# These are workspace-level in multi-tenant deployments (stored in google_auth_tokens).
# The env-var versions are used as single-tenant fallbacks (dev / legacy Agatsa setup).
GOOGLE_DEVELOPER_TOKEN = os.getenv("GOOGLE_DEVELOPER_TOKEN", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")
GOOGLE_CUSTOMER_ID = os.getenv("GOOGLE_CUSTOMER_ID", "")       # no dashes
GOOGLE_MERCHANT_ID = os.getenv("GOOGLE_MERCHANT_ID", "")
GOOGLE_LOGIN_CUSTOMER_ID = os.getenv("GOOGLE_LOGIN_CUSTOMER_ID", "")  # MCC, if any
GOOGLE_ADS_API_VERSION = os.getenv("GOOGLE_ADS_API_VERSION", "v18")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# ── Meta Pixel (for conversion campaign creation) ──────────
META_PIXEL_ID = os.getenv("META_PIXEL_ID", "321066337528686")

# ── Meta Page ID (Facebook Page connected to ad account) ───
META_PAGE_ID = os.getenv("META_PAGE_ID", "203855559983211")

# ── New campaign defaults ──────────────────────────────────
NEW_CAMPAIGN_DAILY_BUDGET_INR = float(os.getenv("NEW_CAMPAIGN_DAILY_BUDGET_INR", "300"))

# ── Security ───────────────────────────────────────────────
CRON_TOKEN = os.getenv("CRON_TOKEN", "")

# ── Timezone ───────────────────────────────────────────────
AD_TIMEZONE = os.getenv("META_AD_TIMEZONE", "Asia/Kolkata")
