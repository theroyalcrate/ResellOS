-- ============================================================
-- Migration 010: Add cost_basis_state to orders
-- Date: 2026-05-27
-- Purpose: Track cost basis lifecycle per order so Agent 08
--   settlement lock and provisional guard function correctly.
--
-- Valid values:
--   estimated   — order entered, no shipment yet (Agent 02 default)
--   provisional — cost basis calculated, 12-month GWP window open
--   settled     — all layers confirmed, cost basis locked forever
--
-- DEFAULT 'estimated' matches Agent 02 order entry behavior.
-- ============================================================

ALTER TABLE orders ADD COLUMN IF NOT EXISTS cost_basis_state TEXT NOT NULL DEFAULT 'estimated';

-- ============================================================
-- Migration complete. 1 column added to orders.
-- ============================================================
