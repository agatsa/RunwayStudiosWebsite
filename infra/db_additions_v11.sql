-- db_additions_v11.sql
-- UGC Video Ad Queue

CREATE TABLE IF NOT EXISTS video_queue (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL,
    platform         TEXT NOT NULL DEFAULT 'meta',
    account_id       TEXT NOT NULL,
    video_type       TEXT NOT NULL,       -- 'heygen_ugc' | 'kling_lifestyle'
    angle            TEXT,
    script           TEXT,                -- HeyGen: spoken script text
    scene_prompt     TEXT,                -- Kling: visual scene description
    heygen_video_id  TEXT,                -- HeyGen job ID (for polling / retries)
    avatar_id        TEXT,
    voice_id         TEXT,
    video_url        TEXT,                -- Final public MP4 URL
    duration_seconds INT DEFAULT 15,
    primary_text     TEXT,
    headline         TEXT,
    cta              TEXT DEFAULT 'Shop Now',
    landing_page_url TEXT,
    daily_budget_inr NUMERIC DEFAULT 300,
    status           TEXT DEFAULT 'pending_approval',
        -- generating | pending_approval | approved | rejected | publishing | published | failed
    meta_video_id    TEXT,               -- Meta advideo ID after upload
    meta_ad_id       TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_queue_tenant
    ON video_queue (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_queue_status
    ON video_queue (status, created_at DESC);
