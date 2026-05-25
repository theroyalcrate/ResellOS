-- ============================================================
-- Migration 004: Add barnes_stamps_earned to orders
-- Date: 2026-05-25
-- Purpose: Track Barnes & Noble stamp rewards earned per order.
--   Stamps = floor(pre-tax post-member-discount subtotal / 10)
--   multiplied by the stamp multiplier (1x / 2x / 3x).
--   NULL for non-Barnes orders (not 0, to distinguish "no stamps
--   earned" from "stamps not applicable for this retailer").
-- ============================================================

ALTER TABLE orders ADD COLUMN barnes_stamps_earned INTEGER;

-- ============================================================
-- Migration complete. 1 column added to orders.
-- ============================================================
