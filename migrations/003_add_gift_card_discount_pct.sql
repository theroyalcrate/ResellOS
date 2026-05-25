-- ============================================================
-- Migration 003: Add discount_pct to gift_cards
-- Date: 2026-05-25 (S05)
-- Purpose: Store pre-calculated discount percentage alongside
--   discount_amount so queries can filter/sort by discount rate
--   without recalculating from face_value and purchase_price.
-- Formula: (face_value - purchase_price) / face_value * 100
-- ============================================================

ALTER TABLE gift_cards ADD COLUMN discount_pct NUMERIC(6,2);

-- ============================================================
-- Migration complete. 1 column added to gift_cards.
-- Backfill existing rows (if any):
-- UPDATE gift_cards
--    SET discount_pct = ROUND((face_value - purchase_price) / face_value * 100, 2)
--  WHERE discount_pct IS NULL AND face_value > 0;
-- ============================================================
