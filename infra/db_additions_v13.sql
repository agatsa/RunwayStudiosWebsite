-- db_additions_v13.sql
-- LP Audit Cache: stores Playwright browser audit results pushed from the
-- LP Auditor web tool. Sales strategist reads this to include real browser
-- audit data in its 6h analysis.

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
