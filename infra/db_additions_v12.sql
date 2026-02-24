-- db_additions_v12.sql
-- Add fb_page_id and pixel_id columns to creative_queue
-- This allows the per-campaign page and pixel choice to persist
-- from generation time through to publishing.

ALTER TABLE creative_queue ADD COLUMN IF NOT EXISTS fb_page_id TEXT;
ALTER TABLE creative_queue ADD COLUMN IF NOT EXISTS pixel_id   TEXT;
