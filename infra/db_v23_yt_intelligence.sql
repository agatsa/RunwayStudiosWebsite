-- db_v23_yt_intelligence.sql
-- YouTube Competitor Intelligence — 9-layer analysis engine
-- Run via POST /admin/migrate (X-Admin-Token: adm_secret_wa_agency_2026)
-- Requires: db_v18_youtube.sql (workspaces table must exist)

-- ── 1. Competitor channel registry ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS yt_competitor_channels (
    workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    channel_id       TEXT NOT NULL,
    channel_title    TEXT NOT NULL DEFAULT '',
    channel_handle   TEXT,
    subscriber_count BIGINT,
    similarity_score NUMERIC(6,4) NOT NULL DEFAULT 0,
    rank             INT NOT NULL DEFAULT 0,
    source           TEXT NOT NULL DEFAULT 'auto',   -- 'auto' | 'manual'
    discovered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_analyzed_at TIMESTAMPTZ,
    PRIMARY KEY (workspace_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_ytcc_ws ON yt_competitor_channels(workspace_id, rank);

-- ── 2. All videos from competitor channels ────────────────────────────────────
-- video_id is globally unique on YouTube — PK without workspace_id
CREATE TABLE IF NOT EXISTS yt_competitor_videos (
    video_id         TEXT PRIMARY KEY,
    channel_id       TEXT NOT NULL,
    workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title            TEXT NOT NULL DEFAULT '',
    description      TEXT,
    thumbnail_url    TEXT,
    published_at     TIMESTAMPTZ,
    duration_seconds INT NOT NULL DEFAULT 0,
    views            BIGINT NOT NULL DEFAULT 0,
    likes            BIGINT NOT NULL DEFAULT 0,
    comments         BIGINT NOT NULL DEFAULT 0,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ytcv_ws_ch  ON yt_competitor_videos(workspace_id, channel_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_ytcv_ch     ON yt_competitor_videos(channel_id);

-- ── 3. Scientific features per video (Layers 1, 6, 8 inputs) ─────────────────
CREATE TABLE IF NOT EXISTS yt_video_features (
    video_id          TEXT PRIMARY KEY REFERENCES yt_competitor_videos(video_id) ON DELETE CASCADE,
    workspace_id      UUID NOT NULL,
    channel_id        TEXT NOT NULL,
    age_days          INT NOT NULL DEFAULT 0,
    velocity          NUMERIC(12,4) NOT NULL DEFAULT 0,   -- views / max(age_days, 1)
    engagement_rate   NUMERIC(8,6) NOT NULL DEFAULT 0,    -- (likes+comments) / max(views, 1)
    comment_density   NUMERIC(8,6) NOT NULL DEFAULT 0,    -- comments / max(views, 1)
    upload_gap_days   NUMERIC(8,2),                       -- days since prior video on this channel
    duration_bucket   TEXT NOT NULL DEFAULT 'medium',     -- short|medium|long
    is_breakout       BOOLEAN NOT NULL DEFAULT FALSE,     -- velocity >= global p90 (set in Layer 9)
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ytvf_ws        ON yt_video_features(workspace_id, channel_id);
CREATE INDEX IF NOT EXISTS idx_ytvf_breakout  ON yt_video_features(workspace_id, is_breakout);

-- ── 4. AI classification features per video (Layers 3, 4, 5) ─────────────────
CREATE TABLE IF NOT EXISTS yt_ai_features (
    video_id           TEXT PRIMARY KEY REFERENCES yt_competitor_videos(video_id) ON DELETE CASCADE,
    workspace_id       UUID NOT NULL,
    -- Layer 2: topic cluster assignment (set after KMeans run)
    topic_cluster_id   INT,
    -- Layer 3: format detection
    format_label       TEXT,          -- one of FORMAT_TAXONOMY
    format_structure   JSONB,         -- array of structure steps
    format_energy      TEXT,          -- high | medium | low
    -- Layer 4: title pattern analysis
    title_patterns     JSONB,         -- array of matched TITLE_PATTERNS
    curiosity_score    INT,           -- 0–10
    specificity_score  INT,           -- 0–10
    -- Layer 5: thumbnail psychology (vision)
    thumb_face         BOOLEAN,
    thumb_text         BOOLEAN,
    thumb_emotion      TEXT,          -- warning|surprise|calm|confidence|fear|neutral|unknown
    thumb_objects      JSONB,         -- array of detected object labels
    thumb_style        TEXT,          -- high_contrast|minimal|clinical|busy|unknown
    thumb_readable_text TEXT,         -- extracted readable text (max 200 chars)
    -- Embedding vector for clustering (TF-IDF/SVD 50-dim, stored as JSONB float array)
    embedding_json     JSONB,
    labeled_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ytaif_ws      ON yt_ai_features(workspace_id, topic_cluster_id);
CREATE INDEX IF NOT EXISTS idx_ytaif_format  ON yt_ai_features(workspace_id, format_label);

-- ── 5. Topic clusters per channel (Layer 2 output) ────────────────────────────
CREATE TABLE IF NOT EXISTS yt_topic_clusters (
    id               BIGSERIAL PRIMARY KEY,
    workspace_id     UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    channel_id       TEXT NOT NULL,
    topic_cluster_id INT NOT NULL,
    topic_name       TEXT NOT NULL DEFAULT 'Uncategorized',
    subthemes        JSONB NOT NULL DEFAULT '[]',
    cluster_size     INT NOT NULL DEFAULT 0,
    avg_velocity     NUMERIC(12,4) NOT NULL DEFAULT 0,
    median_velocity  NUMERIC(12,4) NOT NULL DEFAULT 0,
    hit_rate         NUMERIC(5,2) NOT NULL DEFAULT 0,   -- % above channel p75
    trs_score        INT NOT NULL DEFAULT 0,            -- count in last 30 videos (Topic Recurrence Score)
    shelf_life       TEXT,                              -- 'evergreen' | 'trend' (Layer 7)
    half_life_weeks  INT,                               -- weeks until velocity drops to 50% of peak
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(workspace_id, channel_id, topic_cluster_id)
);
CREATE INDEX IF NOT EXISTS idx_yttc_ws ON yt_topic_clusters(workspace_id, avg_velocity DESC);

-- ── 6. Channel-level risk profile (Layer 8) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS yt_channel_profiles (
    workspace_id      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    channel_id        TEXT NOT NULL,
    median_velocity   NUMERIC(12,4) NOT NULL DEFAULT 0,
    p25_velocity      NUMERIC(12,4) NOT NULL DEFAULT 0,
    p75_velocity      NUMERIC(12,4) NOT NULL DEFAULT 0,
    p90_velocity      NUMERIC(12,4) NOT NULL DEFAULT 0,
    iqr               NUMERIC(12,4) NOT NULL DEFAULT 0,
    std_velocity      NUMERIC(12,4) NOT NULL DEFAULT 0,
    hit_rate          NUMERIC(5,2) NOT NULL DEFAULT 0,        -- % above p75
    underperform_rate NUMERIC(5,2) NOT NULL DEFAULT 0,        -- % below p25
    breakout_rate     NUMERIC(5,2) NOT NULL DEFAULT 0,        -- % above p90
    risk_profile      TEXT NOT NULL DEFAULT 'medium_variance', -- low_variance|medium_variance|high_variance
    cadence_pattern   TEXT,                                    -- burst|weekly|biweekly|monthly
    median_gap_days   NUMERIC(8,2),
    analyzed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(workspace_id, channel_id)
);

-- ── 7. Breakout recipe output (Layer 9) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS yt_breakout_recipe (
    workspace_id   UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    playbook_text  TEXT NOT NULL,
    top_features   JSONB NOT NULL DEFAULT '{}',  -- {feature_name: importance_coefficient}
    p90_threshold  NUMERIC(12,4) NOT NULL DEFAULT 0,
    breakout_count INT NOT NULL DEFAULT 0,
    trained_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 8. Analysis job tracking ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS yt_analysis_jobs (
    id                BIGSERIAL PRIMARY KEY,
    workspace_id      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    status            TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','running','completed','failed')),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    error             TEXT,
    channels_analyzed INT NOT NULL DEFAULT 0,
    videos_analyzed   INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ytaj_ws ON yt_analysis_jobs(workspace_id, created_at DESC);
