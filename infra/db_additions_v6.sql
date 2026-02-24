-- Migration v6: comment_replies table
-- Tracks every Meta ad comment the system has seen/replied to.
-- UNIQUE on (platform, account_id, comment_id) prevents duplicate processing.

BEGIN;

CREATE TABLE IF NOT EXISTS comment_replies (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    platform            TEXT        NOT NULL DEFAULT 'meta',
    account_id          TEXT        NOT NULL,
    ad_id               TEXT        NOT NULL,
    comment_id          TEXT        NOT NULL,
    commenter_name      TEXT,
    comment_text        TEXT        NOT NULL,
    comment_created     TIMESTAMPTZ,
    objection_type      TEXT        NOT NULL,
    suggested_reply     TEXT,
    reply_generated_at  TIMESTAMPTZ,
    -- pending | auto_replied | replied | skipped | failed
    status              TEXT        NOT NULL DEFAULT 'pending',
    reply_text          TEXT,
    replied_at          TIMESTAMPTZ,
    replied_by          TEXT,
    meta_reply_id       TEXT,
    wa_notified_at      TIMESTAMPTZ,
    wa_notify_count     INT         NOT NULL DEFAULT 0,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT comment_replies_unique_comment
        UNIQUE (platform, account_id, comment_id)
);

CREATE INDEX IF NOT EXISTS idx_cr_account_status
    ON comment_replies (platform, account_id, status);

CREATE INDEX IF NOT EXISTS idx_cr_ad_id
    ON comment_replies (ad_id);

CREATE INDEX IF NOT EXISTS idx_cr_first_seen
    ON comment_replies (first_seen_at DESC);

COMMIT;
