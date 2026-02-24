-- infra/db.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tracks each ingestion run (auditable)
CREATE TABLE IF NOT EXISTS sync_runs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  platform TEXT NOT NULL,                 -- meta, google, youtube, x
  account_id TEXT NOT NULL,               -- platform account id, eg act_123
  request_id TEXT NOT NULL,               -- idempotency key
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'running', -- running/success/failed/partial
  raw_gcs_path TEXT,
  stats JSONB DEFAULT '{}'::jsonb,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_runs_platform_account_time
  ON sync_runs(platform, account_id, started_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sync_runs_platform_account_request
  ON sync_runs(platform, account_id, request_id);

-- Watermark/cursor per platform+account
CREATE TABLE IF NOT EXISTS sync_state (
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  last_success_end TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (platform, account_id)
);

-- Latest snapshot of entities (campaign/adset/ad)
CREATE TABLE IF NOT EXISTS entities_snapshot (
  platform TEXT NOT NULL,
  entity_level TEXT NOT NULL,            -- campaign/adset/ad/account
  entity_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  name TEXT,
  status TEXT,
  raw_json JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (platform, entity_level, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_entities_snapshot_account
  ON entities_snapshot(platform, account_id);

-- Hourly KPI facts (upsert by unique key)
CREATE TABLE IF NOT EXISTS kpi_hourly (
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entity_level TEXT NOT NULL,            -- account/campaign/adset/ad
  entity_id TEXT NOT NULL,
  hour_ts TIMESTAMPTZ NOT NULL,          -- hour bucket
  spend NUMERIC,
  impressions BIGINT,
  clicks BIGINT,
  ctr NUMERIC,
  cpm NUMERIC,
  cpc NUMERIC,
  conversions BIGINT,
  revenue NUMERIC,
  roas NUMERIC,
  raw_json JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (platform, account_id, entity_level, entity_id, hour_ts)
);

CREATE INDEX IF NOT EXISTS idx_kpi_hourly_hour
  ON kpi_hourly(platform, account_id, hour_ts DESC);



-- ==============================
-- LAYER 2 MEMORY TABLES (built from daily_kpis / kpi_hourly)
-- ==============================

-- 1) Generic entity memory (fatigue, baselines, flags)
CREATE TABLE IF NOT EXISTS mem_entity_daily (
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entity_level TEXT NOT NULL,   -- account/campaign/adset/ad (same as daily_kpis)
  entity_id TEXT NOT NULL,
  day DATE NOT NULL,

  spend NUMERIC DEFAULT 0,
  impressions BIGINT DEFAULT 0,
  clicks BIGINT DEFAULT 0,
  conversions BIGINT DEFAULT 0,
  revenue NUMERIC DEFAULT 0,
  roas NUMERIC DEFAULT 0,
  ctr NUMERIC DEFAULT 0,
  cpm NUMERIC DEFAULT 0,
  cpc NUMERIC DEFAULT 0,

  ctr_7d_avg NUMERIC DEFAULT 0,
  roas_7d_avg NUMERIC DEFAULT 0,

  fatigue_ctr_ratio NUMERIC DEFAULT 1,
  fatigue_roas_ratio NUMERIC DEFAULT 1,
  fatigue_score NUMERIC DEFAULT 0,
  fatigue_flag BOOLEAN DEFAULT FALSE,

  PRIMARY KEY (platform, account_id, entity_level, entity_id, day)
);

CREATE INDEX IF NOT EXISTS idx_mem_entity_daily_lookup
  ON mem_entity_daily(account_id, platform, entity_level, day);

-- 2) Daily / weekly / monthly recall digests
CREATE TABLE IF NOT EXISTS mem_daily_digest (
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  day DATE NOT NULL,
  digest_text TEXT NOT NULL,
  json_summary JSONB,
  embedding_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (platform, account_id, day)
);

CREATE TABLE IF NOT EXISTS mem_weekly_digest (
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  week_start DATE NOT NULL,
  digest_text TEXT NOT NULL,
  json_summary JSONB,
  embedding_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (platform, account_id, week_start)
);

CREATE TABLE IF NOT EXISTS mem_monthly_digest (
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  month TEXT NOT NULL, -- YYYY-MM
  digest_text TEXT NOT NULL,
  json_summary JSONB,
  embedding_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (platform, account_id, month)
);

-- 3) Optional: objections memory (Agent 2 writes here)
CREATE TABLE IF NOT EXISTS fact_objections_daily (
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entity_level TEXT NOT NULL, -- usually ad
  entity_id TEXT NOT NULL,
  day DATE NOT NULL,
  objection_type TEXT NOT NULL, -- trust/price/scam/feature_confusion/delivery/purchase_intent/support
  count BIGINT NOT NULL DEFAULT 0,
  examples_json JSONB,
  PRIMARY KEY (platform, account_id, entity_level, entity_id, day, objection_type)
);