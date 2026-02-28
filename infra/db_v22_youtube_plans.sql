-- db_v22_youtube_plans.sql
-- YouTube Growth Plans persistence + Shorts detection
-- Run after db_v18_youtube.sql

-- 1. Add is_short flag to youtube_videos
ALTER TABLE youtube_videos
    ADD COLUMN IF NOT EXISTS is_short BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Persistent growth plan history (INSERT-only, never overwrite)
CREATE TABLE IF NOT EXISTS youtube_growth_plans (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    steps         JSONB NOT NULL,          -- array of step strings
    subs_at_time  INT,                     -- subscriber count when plan was generated
    views_at_time BIGINT,                  -- total view count when plan was generated
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_yt_growth_plans_ws
    ON youtube_growth_plans(workspace_id, created_at DESC);

-- 3. Link growth actions to a specific plan (optional)
ALTER TABLE youtube_growth_actions
    ADD COLUMN IF NOT EXISTS plan_id UUID REFERENCES youtube_growth_plans(id);
