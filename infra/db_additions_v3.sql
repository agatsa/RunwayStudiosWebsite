-- db_additions_v3.sql
-- Moment marketing tracking + budget per creative

-- Allow custom budget per creative (for user-specified campaigns)
ALTER TABLE creative_queue ADD COLUMN IF NOT EXISTS daily_budget_inr NUMERIC DEFAULT 300;

-- Track which occasions have already triggered campaigns (prevents duplicates)
CREATE TABLE IF NOT EXISTS moment_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    occasion TEXT NOT NULL,
    occasion_date DATE,
    category TEXT,
    creative_id UUID,
    triggered_at TIMESTAMPTZ DEFAULT NOW()
);

-- Dedup: one campaign per occasion per calendar month
CREATE UNIQUE INDEX IF NOT EXISTS idx_moment_campaigns_dedup
    ON moment_campaigns(occasion, DATE_TRUNC('month', COALESCE(occasion_date, triggered_at::date)));
