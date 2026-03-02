-- db_v24_growth_recipe.sql
-- Own-channel comparison + workspace-type-aware growth recipe

-- Workspace type (d2c | creator | saas | agency | media)
ALTER TABLE workspaces
  ADD COLUMN IF NOT EXISTS workspace_type TEXT DEFAULT 'd2c'
  CHECK (workspace_type IN ('d2c','creator','saas','agency','media'));

-- Add phase column to analysis jobs for richer progress reporting
ALTER TABLE yt_analysis_jobs
  ADD COLUMN IF NOT EXISTS phase TEXT DEFAULT 'competitor_analysis';

-- Own channel video snapshot (analysed separately from competitors)
CREATE TABLE IF NOT EXISTS yt_own_channel_snapshot (
  workspace_id      UUID          NOT NULL,
  channel_id        TEXT          NOT NULL,
  video_id          TEXT          NOT NULL,
  title             TEXT,
  published_at      TIMESTAMPTZ,
  views             BIGINT        DEFAULT 0,
  likes             INT           DEFAULT 0,
  comments          INT           DEFAULT 0,
  duration_seconds  INT           DEFAULT 0,
  is_short          BOOL          DEFAULT FALSE,
  velocity          NUMERIC(12,4),
  engagement_rate   NUMERIC(8,4),
  format_label      TEXT,
  title_patterns    JSONB,
  thumb_face        BOOL,
  thumb_emotion     TEXT,
  thumb_text        BOOL,
  analyzed_at       TIMESTAMPTZ   DEFAULT NOW(),
  PRIMARY KEY (workspace_id, video_id)
);
CREATE INDEX IF NOT EXISTS idx_yt_own_snap_ws ON yt_own_channel_snapshot(workspace_id);

-- Growth recipe (15-day + 30-day plan, workspace-type-aware)
CREATE TABLE IF NOT EXISTS yt_growth_recipe (
  workspace_id             UUID          PRIMARY KEY,
  own_video_count          INT           DEFAULT 0,
  own_velocity_avg         NUMERIC(12,4) DEFAULT 0,
  own_velocity_percentile  NUMERIC(5,2)  DEFAULT 0,
  content_gaps             JSONB,
  plan_15d                 TEXT,
  plan_30d                 TEXT,
  thumbnail_brief          TEXT,
  hooks_library            TEXT,
  emerging_topics          TEXT,
  generated_at             TIMESTAMPTZ   DEFAULT NOW()
);
