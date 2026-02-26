-- ============================================================
-- v19 — Excel Upload: add entity_name to kpi_hourly
-- ============================================================
-- The entity_name column stores a human-readable label for each
-- uploaded row (campaign name, keyword text, search term, etc.)
-- so the dashboard can display names without joining entities_snapshot.

ALTER TABLE kpi_hourly ADD COLUMN IF NOT EXISTS entity_name TEXT;
