-- infra/db_additions_v2.sql
-- Creative pipeline tables (run after db_additions.sql)

CREATE TABLE IF NOT EXISTS creative_queue (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  platform TEXT NOT NULL,
  account_id TEXT NOT NULL,
  concept_index INT DEFAULT 0,          -- 0,1,2 (which concept in the batch)
  trigger_reason TEXT,                  -- e.g. "zero_roas_6h", "manual", "weekly"
  angle TEXT,                           -- ad angle name
  hook TEXT,                            -- opening line
  primary_text TEXT,                    -- main ad body copy
  headline TEXT,                        -- bold text below image
  description TEXT,                     -- smaller text below headline
  cta TEXT DEFAULT 'Shop Now',
  image_prompt TEXT,                    -- Flux prompt used
  image_url TEXT,                       -- fal.ai image URL (public)
  image_meta_hash TEXT,                 -- Meta image hash after upload
  status TEXT DEFAULT 'pending_approval',
  -- pending_approval / approved / rejected / publishing / published / failed
  meta_campaign_id TEXT,
  meta_adset_id TEXT,
  meta_ad_id TEXT,
  wa_message_id TEXT,
  approved_by TEXT,
  reject_reason TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_creative_queue_status
  ON creative_queue(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_creative_queue_account
  ON creative_queue(platform, account_id, created_at DESC);
