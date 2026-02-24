-- db_additions_v4.sql
-- Product asset reference images for consistent product in ad creatives

CREATE TABLE IF NOT EXISTS product_assets (
    asset_type TEXT PRIMARY KEY,          -- 'physical' or 'app'
    cdn_url    TEXT NOT NULL,             -- permanent fal.ai CDN URL
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
