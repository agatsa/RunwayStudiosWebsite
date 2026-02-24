-- db_v18_youtube.sql
-- YouTube Channel Intelligence tables
-- Run after db_v17

-- 1. Add youtube_channel_id to google_auth_tokens
ALTER TABLE google_auth_tokens
    ADD COLUMN IF NOT EXISTS youtube_channel_id TEXT;

-- 2. Channel-level daily stats
CREATE TABLE IF NOT EXISTS youtube_channel_stats (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    channel_id           TEXT NOT NULL,
    date                 DATE NOT NULL,
    views                BIGINT NOT NULL DEFAULT 0,
    watch_time_minutes   BIGINT NOT NULL DEFAULT 0,
    subscribers_gained   INT NOT NULL DEFAULT 0,
    subscribers_lost     INT NOT NULL DEFAULT 0,
    impressions          BIGINT NOT NULL DEFAULT 0,
    impression_ctr       NUMERIC(6,4) NOT NULL DEFAULT 0,  -- stored as percentage e.g. 4.5
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, channel_id, date)
);

-- 3. Video catalog
CREATE TABLE IF NOT EXISTS youtube_videos (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    video_id             TEXT NOT NULL,
    title                TEXT NOT NULL DEFAULT '',
    description          TEXT,
    tags                 TEXT[],
    thumbnail_url        TEXT,
    published_at         TIMESTAMPTZ,
    duration_seconds     INT,
    view_count           BIGINT NOT NULL DEFAULT 0,
    like_count           BIGINT NOT NULL DEFAULT 0,
    comment_count        BIGINT NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, video_id)
);

-- 4. Per-video daily stats
CREATE TABLE IF NOT EXISTS youtube_video_stats (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id              UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    video_id                  TEXT NOT NULL,
    date                      DATE NOT NULL,
    views                     BIGINT NOT NULL DEFAULT 0,
    watch_time_minutes        BIGINT NOT NULL DEFAULT 0,
    avg_view_duration_seconds INT NOT NULL DEFAULT 0,
    avg_view_percentage       NUMERIC(6,3) NOT NULL DEFAULT 0,
    impressions               BIGINT NOT NULL DEFAULT 0,
    impression_ctr            NUMERIC(6,4) NOT NULL DEFAULT 0,  -- stored as percentage e.g. 4.5
    likes                     BIGINT NOT NULL DEFAULT 0,
    shares                    BIGINT NOT NULL DEFAULT 0,
    subscribers_gained        INT NOT NULL DEFAULT 0,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, video_id, date)
);

-- 5. AI growth suggestions queue
CREATE TABLE IF NOT EXISTS youtube_growth_actions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id   UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    video_id       TEXT,                  -- NULL = channel-level suggestion
    lever          TEXT NOT NULL,         -- ctr_optimizer | retention | seo | schedule | comment | shorts | cross_channel
    suggestion     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'suggested'  -- suggested | approved | applied | rejected
        CHECK (status IN ('suggested', 'approved', 'applied', 'rejected')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_yt_channel_stats_ws   ON youtube_channel_stats (workspace_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_yt_videos_ws          ON youtube_videos (workspace_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_yt_video_stats_ws_vid ON youtube_video_stats (workspace_id, video_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_yt_growth_actions_ws  ON youtube_growth_actions (workspace_id, status, created_at DESC);
