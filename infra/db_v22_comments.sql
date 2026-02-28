-- ── v22 — YouTube comments + like_count on Meta comments ─────────────────────

-- YouTube comments table (classified by Claude, same categories as comment_replies)
CREATE TABLE IF NOT EXISTS youtube_comments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    video_id        TEXT NOT NULL,
    video_title     TEXT,
    comment_id      TEXT NOT NULL,
    author_name     TEXT,
    comment_text    TEXT NOT NULL,
    like_count      INT  NOT NULL DEFAULT 0,
    reply_count     INT  NOT NULL DEFAULT 0,
    published_at    TIMESTAMPTZ,
    -- price|trust|scam|feature_confusion|delivery|purchase_intent|support|positive|other
    category        TEXT,
    -- praise|concern|question|neutral
    sentiment       TEXT,
    suggested_reply TEXT,
    -- pending|replied|skipped
    status          TEXT NOT NULL DEFAULT 'pending',
    classified_at   TIMESTAMPTZ,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_yt_comments_uniq
    ON youtube_comments(workspace_id, comment_id);
CREATE INDEX IF NOT EXISTS idx_yt_comments_ws
    ON youtube_comments(workspace_id);
CREATE INDEX IF NOT EXISTS idx_yt_comments_video
    ON youtube_comments(video_id);
CREATE INDEX IF NOT EXISTS idx_yt_comments_first_seen
    ON youtube_comments(first_seen_at DESC);

-- Add like_count to existing Meta comment_replies table
ALTER TABLE comment_replies ADD COLUMN IF NOT EXISTS like_count INT NOT NULL DEFAULT 0;
