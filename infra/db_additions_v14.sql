-- Migration v14: LP Builder tables
-- shopify_connections, lp_builds, lp_sections, shopify_oauth_states

BEGIN;

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
