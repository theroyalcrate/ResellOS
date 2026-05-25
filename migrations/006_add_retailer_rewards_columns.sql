-- ============================================================
-- Migration 006: Add per-retailer rewards columns to orders
-- Date: 2026-05-25
-- Purpose: Track retailer-specific rewards earned per order.
--   All columns are nullable — only the relevant retailer's
--   columns will be populated; all others remain NULL.
-- ============================================================

-- Kohl's
ALTER TABLE orders ADD COLUMN kohls_rewards_earned    NUMERIC(8,2);
ALTER TABLE orders ADD COLUMN kohls_event_cash_earned NUMERIC(8,2);
ALTER TABLE orders ADD COLUMN kohls_pickup_bonus      NUMERIC(8,2);

-- Macy's
ALTER TABLE orders ADD COLUMN macys_points_earned     INTEGER;

-- Walmart Business
ALTER TABLE orders ADD COLUMN walmart_rewards_earned  NUMERIC(8,2);

-- Target
ALTER TABLE orders ADD COLUMN target_offer_earned     NUMERIC(8,2);

-- Best Buy
ALTER TABLE orders ADD COLUMN bestbuy_offer_earned    NUMERIC(8,2);

-- ============================================================
-- Migration complete. 7 columns added to orders.
-- ============================================================
