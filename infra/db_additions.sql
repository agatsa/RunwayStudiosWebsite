-- infra/db_additions.sql
-- Run this AFTER db.sql to add tables needed by agent_swarm

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Daily KPI rollups (written by memory_builder, read by agents)
CREATE TABLE IF NOT EXISTS daily_kpis (
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entity_level TEXT NOT NULL,
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
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (platform, account_id, entity_level, entity_id, day)
);

CREATE INDEX IF NOT EXISTS idx_daily_kpis_day
  ON daily_kpis(platform, account_id, day DESC);

-- Alerts written by ingestion_service and agent_swarm
CREATE TABLE IF NOT EXISTS alerts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entity_level TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  alert_type TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'info',
  summary TEXT,
  details JSONB DEFAULT '{}'::jsonb,
  resolved BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts
  ON alerts(platform, account_id, ts DESC);

-- All actions taken by the action engine
CREATE TABLE IF NOT EXISTS action_log (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  entity_level TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action_type TEXT NOT NULL,   -- pause/resume/increase_budget/decrease_budget/duplicate
  old_value JSONB,
  new_value JSONB,
  triggered_by TEXT,           -- budget_governor/manual/whatsapp_cmd
  approved_by TEXT,            -- auto/whatsapp_918826283840
  status TEXT DEFAULT 'pending', -- pending/approved/rejected/executed/failed
  ts TIMESTAMPTZ DEFAULT NOW(),
  executed_at TIMESTAMPTZ,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_action_log_ts
  ON action_log(platform, account_id, ts DESC);

CREATE INDEX IF NOT EXISTS idx_action_log_status
  ON action_log(status, ts DESC);

-- Pending WhatsApp approvals for large actions
CREATE TABLE IF NOT EXISTS pending_approvals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  action_log_id UUID REFERENCES action_log(id),
  wa_number TEXT NOT NULL,
  message_sent TEXT,
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  response TEXT,               -- YES/NO
  responded_at TIMESTAMPTZ,
  status TEXT DEFAULT 'pending' -- pending/approved/rejected/expired
);

-- Creative suggestions from the creative director agent
CREATE TABLE IF NOT EXISTS creative_suggestions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  week_start DATE NOT NULL,
  suggestion_type TEXT,        -- hook/ugc_script/headline/cta
  content TEXT,
  context_json JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Landing page audit results
CREATE TABLE IF NOT EXISTS landing_page_audits (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  url TEXT NOT NULL,
  ts TIMESTAMPTZ DEFAULT NOW(),
  clarity_score NUMERIC,
  trust_score NUMERIC,
  friction_score NUMERIC,
  overall_score NUMERIC,
  issues JSONB,
  recommendations JSONB,
  raw_html_length INT,
  agent_response TEXT
);

CREATE INDEX IF NOT EXISTS idx_landing_page_audits_ts
  ON landing_page_audits(url, ts DESC);
