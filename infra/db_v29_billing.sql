-- db_v29_billing.sql
-- Credit-based billing system for Runway Studios
-- Run via: POST /admin/migrate (X-Admin-Token: adm_secret_wa_agency_2026)

-- ── Step 1: Extend organizations ─────────────────────────────────────────────
ALTER TABLE organizations
  ADD COLUMN IF NOT EXISTS credit_balance INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS plan           TEXT    NOT NULL DEFAULT 'free';

-- Sync plan from subscriptions table (safe no-op if subscriptions is empty)
UPDATE organizations o
  SET plan = COALESCE((SELECT s.plan FROM subscriptions s WHERE s.org_id = o.id LIMIT 1), 'free')
  WHERE plan = 'free';

-- ── Step 2: Credit ledger (append-only audit trail) ───────────────────────────
CREATE TABLE IF NOT EXISTS credit_ledger (
  id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id               UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  workspace_id         UUID        REFERENCES workspaces(id) ON DELETE SET NULL,
  amount               INTEGER     NOT NULL,
  balance_after        INTEGER     NOT NULL,
  type                 TEXT        NOT NULL,
  -- type values: signup_grant | topup | monthly_plan | feature_use | admin_grant | admin_deduct
  feature              TEXT,
  -- feature values: yt_competitor_intel | growth_os | video_ai_insights | campaign_brief | competitor_ai | growth_recipe_regen
  razorpay_payment_id  TEXT,
  description          TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_org  ON credit_ledger(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_ws   ON credit_ledger(workspace_id);
CREATE INDEX IF NOT EXISTS idx_credit_ledger_type ON credit_ledger(type);

-- ── Step 3: Billing orders (Razorpay top-up tracking) ────────────────────────
CREATE TABLE IF NOT EXISTS billing_orders (
  id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id               UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  razorpay_order_id    TEXT        UNIQUE NOT NULL,
  type                 TEXT        NOT NULL DEFAULT 'topup',
  credits              INTEGER     NOT NULL DEFAULT 0,
  amount_paise         INTEGER     NOT NULL,
  status               TEXT        NOT NULL DEFAULT 'pending',
  -- status: pending | paid | failed
  razorpay_payment_id  TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_billing_orders_org ON billing_orders(org_id);
CREATE INDEX IF NOT EXISTS idx_billing_orders_rzp ON billing_orders(razorpay_order_id);
