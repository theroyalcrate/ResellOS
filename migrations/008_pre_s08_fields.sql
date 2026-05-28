-- ============================================================
-- Migration 008: Pre-S08 fields — buy_reason + is_retiring
-- Date: 2026-05-27
-- Purpose: Track why each order was placed (buy_reason on orders)
--   and whether each set is expected to retire soon (is_retiring
--   on line_items, default TRUE since most buys are retirement-driven).
-- ============================================================

ALTER TABLE orders     ADD COLUMN IF NOT EXISTS buy_reason  TEXT;
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS is_retiring BOOLEAN DEFAULT TRUE;

-- ============================================================
-- Migration complete. 1 column added to orders, 1 to line_items.
-- ============================================================
