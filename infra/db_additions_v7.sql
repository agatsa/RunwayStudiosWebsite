-- db_additions_v7.sql
-- Expand product_assets for multi-photo storage, LoRA training, and named products

-- Human-friendly product name (auto-filled from Claude vision analysis)
ALTER TABLE product_assets ADD COLUMN IF NOT EXISTS name TEXT;

-- All uploaded photo URLs for this product (for LoRA training, more = better)
ALTER TABLE product_assets ADD COLUMN IF NOT EXISTS image_urls TEXT[] DEFAULT '{}';

-- LoRA model trained on this product's photos
ALTER TABLE product_assets ADD COLUMN IF NOT EXISTS lora_url TEXT;

-- LoRA training state: none | training | ready | failed
ALTER TABLE product_assets ADD COLUMN IF NOT EXISTS lora_status TEXT DEFAULT 'none';

-- Trigger word used during LoRA training (must be prepended to prompts when using LoRA)
ALTER TABLE product_assets ADD COLUMN IF NOT EXISTS lora_trigger_word TEXT;
