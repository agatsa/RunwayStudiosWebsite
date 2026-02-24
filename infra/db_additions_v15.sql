-- Migration v15: Sales Intelligence tables + missing LP audit cache
-- Idempotent (IF NOT EXISTS) — safe to re-run

BEGIN;

-- lp_audit_cache (v13 — in case not run yet)
CREATE TABLE IF NOT EXISTS lp_audit_cache (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID,
    site_url         TEXT NOT NULL,
    score            INT  DEFAULT 0,
    grade            TEXT DEFAULT 'D',
    mobile_load_ms   INT,
    desktop_load_ms  INT,
    ctas_above_fold  INT  DEFAULT 0,
    price_visible    BOOLEAN DEFAULT FALSE,
    page_height_px   INT,
    issues           JSONB DEFAULT '[]',
    competitor_summary JSONB DEFAULT '[]',
    full_audit_json  JSONB,
    audited_at       TIMESTAMPTZ DEFAULT NOW(),
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lp_audit_cache_tenant
    ON lp_audit_cache(tenant_id, created_at DESC);

-- sales_strategies: stores the full Claude Opus strategy output per tenant per run
CREATE TABLE IF NOT EXISTS sales_strategies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL,
    platform            TEXT NOT NULL DEFAULT 'meta',
    account_id          TEXT NOT NULL,
    diagnosis           JSONB,
    competitive_insights TEXT,
    forecast            TEXT,
    whatsapp_summary    TEXT,
    raw_fb_data         JSONB,
    raw_competitor      JSONB,
    raw_lp_data         JSONB,
    status              TEXT DEFAULT 'pending',   -- pending | delivered | failed
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sales_strategies_tenant
    ON sales_strategies(tenant_id, created_at DESC);

-- strategy_actions: individual action items from a strategy run
CREATE TABLE IF NOT EXISTS strategy_actions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id         UUID REFERENCES sales_strategies(id) ON DELETE CASCADE,
    tenant_id           UUID NOT NULL,
    tier                TEXT NOT NULL,       -- auto | approval | strategic
    priority            INT  NOT NULL DEFAULT 1,
    action_type         TEXT NOT NULL,       -- pause_ad | scale_budget | new_creative | ...
    title               TEXT NOT NULL,
    description         TEXT,
    data                JSONB DEFAULT '{}',
    estimated_revenue_impact TEXT,
    status              TEXT DEFAULT 'pending',   -- pending | approved | executed | rejected | failed
    execute_result      TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_strategy_actions_strategy
    ON strategy_actions(strategy_id, priority);
CREATE INDEX IF NOT EXISTS idx_strategy_actions_tenant_pending
    ON strategy_actions(tenant_id, status) WHERE status = 'pending';

-- LP Builder tables (v14 — in case not run yet)
CREATE TABLE IF NOT EXISTS shopify_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    shop_domain     TEXT NOT NULL,
    access_token    TEXT NOT NULL,
    scope           TEXT,
    draft_theme_id  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, shop_domain)
);

CREATE TABLE IF NOT EXISTS lp_builds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    shop_domain     TEXT NOT NULL,
    draft_theme_id  TEXT,
    preview_url     TEXT,
    status          TEXT DEFAULT 'building',
    audit_score     INT,
    brand_colors    JSONB,
    font_heading    TEXT DEFAULT 'Clash Display',
    font_body       TEXT DEFAULT 'Inter',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lp_builds_tenant ON lp_builds(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS lp_sections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id        UUID REFERENCES lp_builds(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL,
    section_name    TEXT NOT NULL,
    section_index   INT NOT NULL,
    copy_data       JSONB,
    image_urls      JSONB,
    status          TEXT DEFAULT 'generated',
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(build_id, section_name)
);
CREATE INDEX IF NOT EXISTS idx_lp_sections_build ON lp_sections(build_id, section_index);

CREATE TABLE IF NOT EXISTS shopify_oauth_states (
    state           TEXT PRIMARY KEY,
    shop_domain     TEXT,
    tenant_id       UUID,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

COMMIT;
