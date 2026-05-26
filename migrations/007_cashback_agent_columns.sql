-- ============================================================
-- Migration 007: Cashback agent columns + onboarding table
-- Date: 2026-05-25
-- Purpose: Extend cashback_transactions for Agent 07 and add
--   platform onboarding tracking so blurbs show only once.
-- ============================================================

-- Extend cashback_transactions (IF NOT EXISTS makes each step idempotent)
ALTER TABLE cashback_transactions ADD COLUMN IF NOT EXISTS retailer               TEXT;
ALTER TABLE cashback_transactions ADD COLUMN IF NOT EXISTS order_number           TEXT;
ALTER TABLE cashback_transactions ADD COLUMN IF NOT EXISTS pretax_spend           NUMERIC(12,2);
ALTER TABLE cashback_transactions ADD COLUMN IF NOT EXISTS expected_payout_quarter TEXT;
ALTER TABLE cashback_transactions ADD COLUMN IF NOT EXISTS actual_amount_received  NUMERIC(12,2);
ALTER TABLE cashback_transactions ADD COLUMN IF NOT EXISTS payout_method          TEXT;
ALTER TABLE cashback_transactions ADD COLUMN IF NOT EXISTS cap1_gift_card_retailer TEXT;
ALTER TABLE cashback_transactions ADD COLUMN IF NOT EXISTS cap1_gift_card_last4    TEXT;

-- Track which platform onboarding blurbs have been shown to the user
CREATE TABLE user_platform_onboarding (
    user_id    UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    platform   TEXT NOT NULL,
    shown_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, platform)
);
ALTER TABLE user_platform_onboarding ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- Migration complete. 8 columns added to cashback_transactions,
-- 1 table created (user_platform_onboarding).
-- ============================================================
