-- Migration v5: per-creative landing page URL
ALTER TABLE creative_queue ADD COLUMN IF NOT EXISTS landing_page_url TEXT;
-- NULL means "use LANDING_PAGE_URL env var" (existing behaviour, no breaking change)
