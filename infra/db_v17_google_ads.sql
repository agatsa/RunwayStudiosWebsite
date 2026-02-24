-- =============================================================================
-- db_v17_google_ads.sql
-- Runway Studios — Phase 2: Google Ads Integration
--
-- New tables:
--   google_auth_tokens      — OAuth2 credentials per workspace
--   merchant_center_products — Sync status of each product in Merchant Center
--   google_search_terms     — Keyword/search term performance (unique to Google)
--   google_shopping_feed_log — History of Merchant Center sync runs
--
-- All idempotent (IF NOT EXISTS).
-- =============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- Google OAuth2 tokens (separate from platform_connections.access_token
-- because Google tokens have a 1-hour expiry and need automatic refresh)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS google_auth_tokens (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    platform_conn_id    UUID REFERENCES platform_connections(id) ON DELETE CASCADE,
    customer_id         TEXT NOT NULL,          -- Google Ads customer ID (no dashes)
    merchant_id         TEXT,                   -- Google Merchant Center ID (if connected)
    developer_token     TEXT NOT NULL,          -- From Google Ads account → API Center
    client_id           TEXT NOT NULL,          -- OAuth2 app client ID
    client_secret       TEXT NOT NULL,          -- OAuth2 app client secret
    refresh_token       TEXT NOT NULL,          -- Long-lived, use to get access tokens
    access_token        TEXT,                   -- Short-lived (1h), auto-refreshed
    access_token_expiry TIMESTAMPTZ,
    login_customer_id   TEXT,                   -- MCC account ID if using manager account
    scopes              TEXT[] DEFAULT ARRAY[
        'https://www.googleapis.com/auth/adwords',
        'https://www.googleapis.com/auth/content'   -- Merchant Center
    ],
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, customer_id)
);

CREATE INDEX IF NOT EXISTS idx_google_auth_workspace
    ON google_auth_tokens(workspace_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Merchant Center product sync status
-- Tracks each product's approval state in Google Merchant Center
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS merchant_center_products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    merchant_id         TEXT NOT NULL,              -- Merchant Center account ID
    mc_product_id       TEXT NOT NULL,              -- ID assigned by Merchant Center
    mc_offer_id         TEXT NOT NULL,              -- Our offer ID (product.sku or product.id)
    title               TEXT,
    status              TEXT DEFAULT 'pending',     -- pending|approved|disapproved|expiring
    disapproval_reasons JSONB DEFAULT '[]',         -- [{code, description}] if disapproved
    destinations        JSONB DEFAULT '{}',         -- {Shopping: approved, SurfacesAcrossGoogle: approved}
    last_synced_at      TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,                -- Google auto-expires products after 30 days
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, merchant_id, mc_offer_id)
);

CREATE INDEX IF NOT EXISTS idx_mc_products_workspace
    ON merchant_center_products(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_mc_products_product
    ON merchant_center_products(product_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Google Search Terms performance
-- Search terms that triggered your ads — unique Google insight
-- Used by: keyword optimization agent (Phase 3), negative keyword suggestions
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS google_search_terms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    customer_id     TEXT NOT NULL,
    campaign_id     TEXT NOT NULL,
    ad_group_id     TEXT NOT NULL,
    search_term     TEXT NOT NULL,
    match_type      TEXT,           -- BROAD|PHRASE|EXACT|NEAR_EXACT|EXPANDED
    day             DATE NOT NULL,
    impressions     BIGINT DEFAULT 0,
    clicks          BIGINT DEFAULT 0,
    spend           NUMERIC DEFAULT 0,
    conversions     NUMERIC DEFAULT 0,
    revenue         NUMERIC DEFAULT 0,
    ctr             NUMERIC DEFAULT 0,
    avg_cpc         NUMERIC DEFAULT 0,
    quality_score   INT,            -- 1-10, only available at keyword level
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, customer_id, campaign_id, ad_group_id, search_term, day)
);

CREATE INDEX IF NOT EXISTS idx_search_terms_workspace_day
    ON google_search_terms(workspace_id, day DESC);
CREATE INDEX IF NOT EXISTS idx_search_terms_term
    ON google_search_terms(workspace_id, search_term, day DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Merchant Center feed sync log
-- Audit trail of every product feed push
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS google_shopping_feed_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    merchant_id         TEXT NOT NULL,
    products_pushed     INT DEFAULT 0,
    products_approved   INT DEFAULT 0,
    products_disapproved INT DEFAULT 0,
    products_pending    INT DEFAULT 0,
    errors              JSONB DEFAULT '[]',
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              TEXT DEFAULT 'running'   -- running|success|partial|failed
);

CREATE INDEX IF NOT EXISTS idx_feed_log_workspace
    ON google_shopping_feed_log(workspace_id, started_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- Performance Max asset groups
-- PMax campaigns use asset groups instead of traditional ad creative
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS google_pmax_assets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    platform_conn_id    UUID REFERENCES platform_connections(id),
    customer_id         TEXT NOT NULL,
    campaign_id         TEXT NOT NULL,
    asset_group_id      TEXT NOT NULL,
    asset_group_name    TEXT,
    product_id          UUID REFERENCES products(id),

    -- Text assets (Google requires multiple variants for A/B)
    headlines           TEXT[] DEFAULT '{}',    -- 3-15 headlines (max 30 chars each)
    descriptions        TEXT[] DEFAULT '{}',    -- 2-5 descriptions (max 90 chars each)
    long_headlines      TEXT[] DEFAULT '{}',    -- 1-5 long headlines (max 90 chars)
    business_name       TEXT,
    final_url           TEXT,

    -- Image assets
    image_urls          JSONB DEFAULT '[]',     -- [{url, asset_id, type: landscape/square/portrait}]
    logo_urls           JSONB DEFAULT '[]',

    -- Video assets
    video_urls          JSONB DEFAULT '[]',     -- [{url, youtube_id}]

    status              TEXT DEFAULT 'pending', -- pending|active|paused|removed
    performance_label   TEXT,                   -- BEST|GOOD|LOW|PENDING (from Google)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pmax_assets_workspace
    ON google_pmax_assets(workspace_id, campaign_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Extend kpi_hourly for Google-specific metrics
-- (google_ads specific fields that don't exist in Meta)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE kpi_hourly ADD COLUMN IF NOT EXISTS quality_score       INT;
ALTER TABLE kpi_hourly ADD COLUMN IF NOT EXISTS search_impression_share NUMERIC;
ALTER TABLE kpi_hourly ADD COLUMN IF NOT EXISTS absolute_top_impression_pct NUMERIC;
ALTER TABLE kpi_hourly ADD COLUMN IF NOT EXISTS interaction_rate    NUMERIC;  -- for YouTube/Display

-- Extend platform_connections for Google-specific identifiers
ALTER TABLE platform_connections ADD COLUMN IF NOT EXISTS customer_id      TEXT;  -- Google Ads Customer ID
ALTER TABLE platform_connections ADD COLUMN IF NOT EXISTS merchant_id      TEXT;  -- Merchant Center ID
ALTER TABLE platform_connections ADD COLUMN IF NOT EXISTS login_customer_id TEXT; -- MCC ID
ALTER TABLE platform_connections ADD COLUMN IF NOT EXISTS youtube_channel_id TEXT; -- YouTube channel

COMMIT;
