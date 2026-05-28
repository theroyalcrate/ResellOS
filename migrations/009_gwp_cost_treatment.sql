-- ============================================================
-- Migration 009: GWP cost treatment
-- Date: 2026-05-27
-- Purpose: Add per-user GWP cost treatment preference and
--   lifecycle tracking columns to the gwp table.
--
-- GWP treatment options (users.gwp_cost_treatment):
--   proceeds_reduce_order  — default (Philosophy C): $0 cost basis at
--     receipt; when GWP sells, net proceeds reduce originating order's
--     economic cost, reallocated across paid items only.
--   proportional_msrp      — allocate order cost at receipt using MSRP
--     weighting across paid + GWP items.
--   zero_no_allocation     — GWP proceeds are pure income; no cost
--     basis reduction on paid items ever.
--
-- GWP status values (gwp.status):
--   pending           — not yet sold; provisional window running
--   sold              — proceeds recorded; allocation applied
--   retained_personal — kept for personal use; $0 proceeds; settles now
--   donated           — $0 proceeds; settles immediately
--   lost_damaged      — $0 proceeds; settles immediately
-- ============================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS gwp_cost_treatment TEXT NOT NULL DEFAULT 'proceeds_reduce_order';

ALTER TABLE gwp ADD COLUMN IF NOT EXISTS status          TEXT          NOT NULL DEFAULT 'pending';
ALTER TABLE gwp ADD COLUMN IF NOT EXISTS net_proceeds    NUMERIC(12,2);
ALTER TABLE gwp ADD COLUMN IF NOT EXISTS sale_date       DATE;
ALTER TABLE gwp ADD COLUMN IF NOT EXISTS settlement_date DATE;

-- ============================================================
-- Migration complete. 1 column added to users, 4 to gwp.
-- ============================================================
