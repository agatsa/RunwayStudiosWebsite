-- db_v20_google_reports.sql
-- New table for Auction Insights (competitor metrics, separate from kpi_hourly)
-- Apply via: POST /admin/migrate  (X-Admin-Token: adm_secret_wa_agency_2026)

CREATE TABLE IF NOT EXISTS google_auction_insights (
    id                     BIGSERIAL PRIMARY KEY,
    workspace_id           UUID REFERENCES workspaces(id),
    campaign_name          TEXT NOT NULL DEFAULT '',
    competitor_domain      TEXT NOT NULL,
    impression_share       NUMERIC,
    overlap_rate           NUMERIC,
    position_above_rate    NUMERIC,
    top_of_page_rate       NUMERIC,
    abs_top_impression_pct NUMERIC,
    outranking_share       NUMERIC,
    uploaded_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, campaign_name, competitor_domain)
);

CREATE INDEX IF NOT EXISTS idx_auction_ws ON google_auction_insights(workspace_id);
