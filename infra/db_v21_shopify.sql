-- db_v21_shopify.sql
-- Shopify public app integration: stores OAuth tokens per workspace
-- Run via POST /admin/migrate (X-Admin-Token: adm_secret_wa_agency_2026)

CREATE TABLE IF NOT EXISTS shopify_connections (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    shop_domain   TEXT NOT NULL,           -- e.g. agatsaone.myshopify.com
    access_token  TEXT NOT NULL,           -- permanent offline token from OAuth
    scopes        TEXT,                    -- comma-sep granted scopes
    shop_name     TEXT,                    -- friendly display name from /admin/api/.../shop.json
    installed_at  TIMESTAMPTZ DEFAULT NOW(),
    synced_at     TIMESTAMPTZ,             -- last successful product sync
    UNIQUE(workspace_id, shop_domain)
);

CREATE INDEX IF NOT EXISTS idx_shopify_workspace
    ON shopify_connections(workspace_id);

-- Also index by shop_domain so webhook handler can look up workspace fast
CREATE INDEX IF NOT EXISTS idx_shopify_domain
    ON shopify_connections(shop_domain);
