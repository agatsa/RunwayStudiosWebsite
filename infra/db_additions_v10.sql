-- db_additions_v10.sql
-- Sales Intelligence Layer: deep FB analysis, competitor intel, strategies, action items

-- Deep Facebook Ads analysis cache (breakdown data, relevance diagnostics, frequency)
CREATE TABLE IF NOT EXISTS fb_deep_insights (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL,
    platform      TEXT NOT NULL,
    account_id    TEXT NOT NULL,
    analysis_date DATE DEFAULT CURRENT_DATE,
    age_gender    JSONB DEFAULT '[]',
    placement     JSONB DEFAULT '[]',
    device        JSONB DEFAULT '[]',
    relevance     JSONB DEFAULT '[]',
    frequency     JSONB DEFAULT '[]',
    summary       TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fb_deep_insights_tenant_date
    ON fb_deep_insights(tenant_id, analysis_date DESC);

-- Competitor intelligence (FB Ad Library + LP analysis)
CREATE TABLE IF NOT EXISTS competitor_intelligence (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL,
    search_terms    TEXT[],
    total_ads_found INTEGER DEFAULT 0,
    top_competitors JSONB DEFAULT '[]',
    opportunity_gaps JSONB DEFAULT '[]',
    summary         TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_competitor_intel_tenant
    ON competitor_intelligence(tenant_id, created_at DESC);

-- Full sales strategies (one per run)
CREATE TABLE IF NOT EXISTS sales_strategies (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL,
    platform             TEXT NOT NULL,
    account_id           TEXT NOT NULL,
    diagnosis            TEXT,
    competitive_insights TEXT,
    forecast             TEXT,
    whatsapp_summary     TEXT,
    raw_fb_data          JSONB,
    raw_competitor       JSONB,
    raw_lp_data          JSONB,
    status               TEXT DEFAULT 'generated',
    created_at           TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sales_strategies_tenant
    ON sales_strategies(tenant_id, created_at DESC);

-- Individual action items from each strategy
CREATE TABLE IF NOT EXISTS strategy_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID REFERENCES sales_strategies(id),
    tenant_id       UUID NOT NULL,
    tier            TEXT NOT NULL,       -- 'auto' | 'approval' | 'strategic'
    priority        INTEGER DEFAULT 0,
    action_type     TEXT NOT NULL,       -- 'pause_ad' | 'scale_budget' | 'new_creative' |
                                         -- 'new_audience' | 'fix_lp' | 'test_offer' | 'restructure'
    title           TEXT NOT NULL,
    description     TEXT,
    data            JSONB DEFAULT '{}',  -- action-specific params
    status          TEXT DEFAULT 'pending',  -- 'pending'|'approved'|'rejected'|'executed'|'failed'
    execute_result  TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_strategy_actions_tenant_status
    ON strategy_actions(tenant_id, status, created_at DESC);
