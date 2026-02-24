-- =============================================================================
-- db_v16_phase0_foundation.sql
-- Runway Studios — Phase 0 SaaS Foundation Migration
--
-- What this does:
--   1. Creates new SaaS core tables: organizations, users, workspaces,
--      platform_connections, products, subscriptions
--   2. Adds workspace_id to ALL existing data tables
--   3. Seeds the first organization (Agatsa) and workspace from existing
--      accounts table data so no historical data is lost
--   4. Backfills workspace_id on all existing rows
--
-- Safe to run: all operations are idempotent (IF NOT EXISTS / IF NOT EXISTS cols)
-- Run AFTER all previous migrations (db.sql through db_additions_v15.sql)
-- =============================================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 1 — Core SaaS tables
-- ─────────────────────────────────────────────────────────────────────────────

-- Organizations: the top-level account (a brand or an agency)
CREATE TABLE IF NOT EXISTS organizations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL,
    slug                    TEXT NOT NULL UNIQUE,     -- url-friendly: "agatsa-health"
    plan                    TEXT NOT NULL DEFAULT 'starter',  -- starter|growth|scale|agency
    razorpay_customer_id    TEXT,
    billing_email           TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_organizations_slug ON organizations(slug);

-- Users: people who log in (Google SSO or email)
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT NOT NULL UNIQUE,
    name            TEXT,
    google_id       TEXT UNIQUE,                -- from Google OAuth
    avatar_url      TEXT,
    role            TEXT NOT NULL DEFAULT 'member',  -- owner|admin|member|viewer
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Workspaces: one per client brand being managed
-- Replaces the `accounts` table as the central tenant identifier
CREATE TABLE IF NOT EXISTS workspaces (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name                    TEXT NOT NULL,                  -- "Agatsa India"
    store_url               TEXT,                           -- "https://agatsaone.com"
    store_platform          TEXT,                           -- shopify|woocommerce|custom|none
    timezone                TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    currency                TEXT NOT NULL DEFAULT 'INR',

    -- Notification channels
    wa_phone_number_id      TEXT,                           -- WhatsApp Cloud API phone ID
    wa_access_token         TEXT,                           -- WhatsApp access token
    notification_wa_number  TEXT,                           -- admin WA number for alerts
    telegram_chat_id        TEXT,                           -- Telegram chat/group ID for alerts
    telegram_enabled        BOOLEAN NOT NULL DEFAULT FALSE,

    -- Business rules (overrides global defaults)
    daily_spend_cap         NUMERIC,
    approval_threshold      NUMERIC,

    -- Metadata
    active                  BOOLEAN NOT NULL DEFAULT TRUE,
    onboarding_complete     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workspaces_org ON workspaces(org_id);
CREATE INDEX IF NOT EXISTS idx_workspaces_wa_phone ON workspaces(wa_phone_number_id);
CREATE INDEX IF NOT EXISTS idx_workspaces_active ON workspaces(active) WHERE active = TRUE;

-- Platform connections: one row per ad account per platform per workspace
-- Supports multiple Meta accounts, multiple Google accounts, etc.
CREATE TABLE IF NOT EXISTS platform_connections (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    platform            TEXT NOT NULL,  -- meta|google|amazon|flipkart|youtube
    account_id          TEXT NOT NULL,  -- platform's own account identifier
    account_name        TEXT,           -- human label: "India Retargeting"
    access_token        TEXT,
    refresh_token       TEXT,
    token_expires_at    TIMESTAMPTZ,

    -- Platform-specific IDs
    ad_account_id       TEXT,           -- Meta: act_123 / Google: customer_id
    page_id             TEXT,           -- Meta: FB Page ID
    pixel_id            TEXT,           -- Meta: Pixel ID / Google: Conversion ID
    mcc_id              TEXT,           -- Google: Manager Account ID if applicable

    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,  -- default account for new campaigns
    metadata            JSONB NOT NULL DEFAULT '{}',     -- platform-specific extra fields
    connected_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (workspace_id, platform, account_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_connections_workspace
    ON platform_connections(workspace_id, platform);
CREATE INDEX IF NOT EXISTS idx_platform_connections_primary
    ON platform_connections(workspace_id, platform) WHERE is_primary = TRUE;

-- Products: central catalog, auto-populated from Shopify/WooCommerce or manually entered
CREATE TABLE IF NOT EXISTS products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    description         TEXT,
    price_inr           NUMERIC,                    -- selling price
    mrp_inr             NUMERIC,                    -- max retail price
    product_url         TEXT,                       -- canonical product page URL
    images              JSONB NOT NULL DEFAULT '[]', -- [{url, alt, position}]
    sku                 TEXT,
    category            TEXT,                       -- "health_device" / "wearable" etc.

    -- Source platform tracking
    source_platform     TEXT,                       -- shopify|woocommerce|manual
    source_product_id   TEXT,                       -- Shopify product ID if synced

    -- Ad creative context (replaces hardcoded PRODUCT_CONTEXT)
    ad_context          TEXT,                       -- Claude-ready product description for ad copy
    target_audience     TEXT,                       -- "Health-conscious Indians 28-55..."
    key_features        JSONB NOT NULL DEFAULT '[]', -- ["12-lead ECG", "keychain size", ...]
    unique_selling_prop TEXT,                       -- "Only pocket ECG with 12 leads"

    -- Google Merchant Center fields
    gtin                TEXT,                       -- barcode/ISBN
    mpn                 TEXT,                       -- manufacturer part number
    google_product_category TEXT,                   -- Google taxonomy category
    brand               TEXT,

    active              BOOLEAN NOT NULL DEFAULT TRUE,
    last_synced_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_workspace ON products(workspace_id);
CREATE INDEX IF NOT EXISTS idx_products_active ON products(workspace_id) WHERE active = TRUE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_source
    ON products(workspace_id, source_platform, source_product_id)
    WHERE source_platform IS NOT NULL AND source_product_id IS NOT NULL;

-- Subscriptions: Razorpay billing per organization
CREATE TABLE IF NOT EXISTS subscriptions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE UNIQUE,
    razorpay_subscription_id    TEXT UNIQUE,
    plan                        TEXT NOT NULL DEFAULT 'starter',
    status                      TEXT NOT NULL DEFAULT 'active',  -- active|past_due|cancelled|trialing
    current_period_start        TIMESTAMPTZ,
    current_period_end          TIMESTAMPTZ,
    trial_ends_at               TIMESTAMPTZ,
    cancelled_at                TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_org ON subscriptions(org_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 2 — Add workspace_id to all existing data tables
-- Each ADD COLUMN is idempotent via IF NOT EXISTS
-- ─────────────────────────────────────────────────────────────────────────────

-- Core KPI tables
ALTER TABLE kpi_hourly           ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE daily_kpis           ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE entities_snapshot    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE sync_runs            ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE sync_state           ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

-- Memory tables
ALTER TABLE mem_entity_daily     ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE mem_daily_digest     ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE mem_weekly_digest    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE mem_monthly_digest   ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE fact_objections_daily ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

-- Operational tables
ALTER TABLE alerts               ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE action_log           ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE pending_approvals    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE creative_suggestions ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE landing_page_audits  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE creative_queue       ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE moment_campaigns     ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE comment_replies      ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

-- product_assets: add workspace_id (was single-tenant, keyed by asset_type)
ALTER TABLE product_assets       ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
-- Also add tenant_id as alias for tables that use tenant_id already
-- (fb_deep_insights, competitor_intelligence, etc. already have tenant_id — add workspace_id as the canonical key)
ALTER TABLE fb_deep_insights         ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE competitor_intelligence  ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE sales_strategies         ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE strategy_actions         ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE video_queue              ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE lp_audit_cache           ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE shopify_connections      ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE lp_builds                ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);
ALTER TABLE lp_sections              ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id);

-- Creative queue: add product_id foreign key for per-product creative tracking
ALTER TABLE creative_queue       ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES products(id);
ALTER TABLE video_queue          ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES products(id);

-- Platform-specific: add platform_connection_id so we know which ad account an action targets
ALTER TABLE action_log           ADD COLUMN IF NOT EXISTS platform_connection_id UUID REFERENCES platform_connections(id);
ALTER TABLE creative_queue       ADD COLUMN IF NOT EXISTS platform_connection_id UUID REFERENCES platform_connections(id);

-- Workspace-scoped indexes for query performance
CREATE INDEX IF NOT EXISTS idx_kpi_hourly_workspace
    ON kpi_hourly(workspace_id, platform, hour_ts DESC);
CREATE INDEX IF NOT EXISTS idx_action_log_workspace
    ON action_log(workspace_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_creative_queue_workspace
    ON creative_queue(workspace_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_queue_workspace
    ON video_queue(workspace_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sales_strategies_workspace
    ON sales_strategies(workspace_id, created_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 3 — Attribution tracking (new: click-level cross-channel attribution)
-- ─────────────────────────────────────────────────────────────────────────────

-- Every ad click gets a click_id appended to the landing page URL (?rwid=...)
-- When a purchase fires, the click_id is matched to attribute the conversion correctly
CREATE TABLE IF NOT EXISTS attribution_clicks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    click_id        TEXT NOT NULL UNIQUE,           -- rwid= param value
    platform        TEXT NOT NULL,                  -- meta|google|youtube|amazon
    platform_click_id TEXT,                         -- fbclid / gclid / etc.
    campaign_id     TEXT,
    adset_id        TEXT,
    ad_id           TEXT,
    product_id      UUID REFERENCES products(id),
    landing_url     TEXT,
    ip_hash         TEXT,                           -- hashed for privacy
    user_agent      TEXT,
    clicked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    converted       BOOLEAN NOT NULL DEFAULT FALSE,
    converted_at    TIMESTAMPTZ,
    conversion_value NUMERIC,                       -- order value in INR
    order_id        TEXT                            -- Shopify/store order reference
);

CREATE INDEX IF NOT EXISTS idx_attribution_clicks_workspace
    ON attribution_clicks(workspace_id, clicked_at DESC);
CREATE INDEX IF NOT EXISTS idx_attribution_clicks_click_id
    ON attribution_clicks(click_id);
CREATE INDEX IF NOT EXISTS idx_attribution_clicks_converted
    ON attribution_clicks(workspace_id, converted) WHERE converted = TRUE;

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 4 — Seed data: Agatsa as Workspace 1
-- Migrates the existing single-tenant setup to the new multi-tenant model
-- This is idempotent: the DO block only inserts if slug doesn't exist yet
-- ─────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    v_org_id        UUID;
    v_workspace_id  UUID;
    v_account       RECORD;
BEGIN
    -- Skip if already migrated
    IF EXISTS (SELECT 1 FROM organizations WHERE slug = 'agatsa-health') THEN
        RAISE NOTICE 'Seed data already present, skipping.';
        RETURN;
    END IF;

    -- Try to read the existing accounts row for Agatsa
    BEGIN
        SELECT * INTO v_account FROM accounts LIMIT 1;
    EXCEPTION WHEN undefined_table THEN
        -- accounts table doesn't exist yet, use defaults
        v_account := NULL;
    END;

    -- Create organization
    INSERT INTO organizations (name, slug, plan, billing_email)
    VALUES ('Agatsa Health', 'agatsa-health', 'scale', 'admin@agatsa.com')
    RETURNING id INTO v_org_id;

    -- Create workspace from existing account row (or defaults)
    INSERT INTO workspaces (
        org_id, name, store_url, store_platform, timezone, currency,
        wa_phone_number_id, wa_access_token, notification_wa_number,
        daily_spend_cap, approval_threshold, active, onboarding_complete
    ) VALUES (
        v_org_id,
        COALESCE(v_account.name, 'Agatsa India'),
        'https://agatsaone.com',
        'shopify',
        COALESCE(v_account.timezone, 'Asia/Kolkata'),
        'INR',
        v_account.wa_phone_number_id,
        v_account.meta_access_token,   -- meta_access_token doubles as WA token
        COALESCE(v_account.admin_wa_id, '918826283840'),
        COALESCE(v_account.daily_spend_cap, 20000),
        COALESCE(v_account.approval_threshold, 10000),
        TRUE,
        TRUE    -- existing setup = onboarding already done
    )
    RETURNING id INTO v_workspace_id;

    -- Create Meta platform connection from existing account credentials
    IF v_account.ad_account_id IS NOT NULL THEN
        INSERT INTO platform_connections (
            workspace_id, platform, account_id, account_name,
            access_token, ad_account_id, page_id, pixel_id, is_primary
        ) VALUES (
            v_workspace_id, 'meta',
            COALESCE(v_account.ad_account_id, ''),
            'Agatsa Meta (Migrated)',
            v_account.meta_access_token,
            v_account.ad_account_id,
            v_account.fb_page_id,
            v_account.pixel_id,
            TRUE
        );
    END IF;

    -- Backfill workspace_id on ALL existing data rows using account_id match
    -- kpi_hourly, daily_kpis, etc. store account_id as the ad account ID
    UPDATE kpi_hourly           SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE daily_kpis           SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE entities_snapshot    SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE sync_runs            SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE mem_entity_daily     SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE mem_daily_digest     SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE mem_weekly_digest    SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE mem_monthly_digest   SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE fact_objections_daily SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE alerts               SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE action_log           SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE creative_suggestions SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE creative_queue       SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE moment_campaigns     SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE comment_replies      SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE product_assets       SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;

    -- Tables that used tenant_id: backfill workspace_id from tenant_id
    UPDATE fb_deep_insights        SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE competitor_intelligence SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE sales_strategies        SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE strategy_actions        SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE video_queue             SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE lp_audit_cache          SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE shopify_connections     SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;
    UPDATE lp_builds               SET workspace_id = v_workspace_id WHERE workspace_id IS NULL;

    RAISE NOTICE 'Seeded org_id=%, workspace_id=%', v_org_id, v_workspace_id;
END;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- SECTION 5 — Backward compatibility view
-- Existing code that queries `accounts` still works during the migration period
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW accounts_v AS
SELECT
    w.id,
    w.name,
    w.wa_phone_number_id,
    w.wa_access_token,
    pc.access_token           AS meta_access_token,
    pc.page_id                AS fb_page_id,
    pc.ad_account_id,
    pc.pixel_id,
    w.notification_wa_number  AS admin_wa_id,
    w.active,
    w.daily_spend_cap,
    w.approval_threshold,
    w.timezone,
    w.id                      AS workspace_id,
    w.org_id
FROM workspaces w
LEFT JOIN platform_connections pc
    ON pc.workspace_id = w.id
    AND pc.platform = 'meta'
    AND pc.is_primary = TRUE;

COMMIT;
