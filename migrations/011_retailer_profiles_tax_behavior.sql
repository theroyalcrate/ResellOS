-- Migration 011: Add tax-behavior, pickup, and shipping columns to retailer_profiles.
-- rewards_reduce_taxable_base: per-retailer flag set from real invoice evidence.
--   true = promo-cash/coupons reduce the taxable base (pre-tax discounts).
--   Engine must use actual invoice tax — never recompute.
--   Default false preserves existing semantics for all other retailers.
-- Kohl's row seeded separately via Python (requires PHASE_1_USER_ID at runtime).

ALTER TABLE retailer_profiles
  ADD COLUMN IF NOT EXISTS retailer_key            text,
  ADD COLUMN IF NOT EXISTS rewards_reduce_taxable_base
                                                   boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS supports_pickup         boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS free_shipping_threshold numeric;

-- Composite unique constraint: one retailer_key per user (multi-tenant safe).
-- NULL retailer_key rows are excluded from uniqueness enforcement (PostgreSQL NULL != NULL).
-- Guarded: ADD CONSTRAINT has no IF NOT EXISTS in Postgres; this block makes re-runs safe.
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_retailer_profiles_user_key'
      AND conrelid = 'retailer_profiles'::regclass
  ) THEN
    ALTER TABLE retailer_profiles
      ADD CONSTRAINT uq_retailer_profiles_user_key UNIQUE (user_id, retailer_key);
  END IF;
END $$;
