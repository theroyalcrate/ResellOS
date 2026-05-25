-- ============================================================
-- Migration 005: Add barnes_bonus_reward to orders
-- Date: 2026-05-25
-- Purpose: Track Barnes & Noble bonus reward dollars earned per
--   order (e.g. double-stamp promotions that pay out a cash reward
--   in addition to stamps). NULL for non-Barnes orders or Barnes
--   orders with no bonus reward.
-- ============================================================

ALTER TABLE orders ADD COLUMN barnes_bonus_reward NUMERIC(8,2);

-- ============================================================
-- Migration complete. 1 column added to orders.
-- ============================================================
