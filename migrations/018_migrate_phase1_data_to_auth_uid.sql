-- Migration 018: Re-point all existing data from the Phase 1 hardcoded placeholder
-- UUID (00000000-0000-0000-0000-000000000001) to Josh's real Supabase Auth user
-- (9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4, joshua.buckingham@gmail.com), created
-- 2026-08-12 as part of the Chrome extension's Supabase Auth prerequisite.
-- Applied live via Supabase MCP 2026-08-12 (Josh approved via AskUserQuestion).
--
-- Safe reparent order (users.user_id has UNIQUE(email) + is referenced by 26 child
-- tables via NO ACTION foreign keys, so the PK can't just be UPDATEd in place):
--   1. Free the email on the old placeholder row (avoids UNIQUE(email) collision).
--   2. Insert a new users row under the real auth UID with the real email.
--   3. Re-point all 26 child tables' user_id from old -> new.
--   4. Delete the old placeholder users row (now has zero children referencing it).
--
-- Verified after apply: users=1, orders=9, gift_cards=216, line_items=36 under the
-- new UID; 0 rows anywhere still on the old placeholder.
--
-- Companion code change (same session, not part of this SQL file): db_client.py's
-- PHASE_1_USER_ID constant updated to this same UID, so future agent runs (Agent
-- 02, 05, 07, 08, 09, 10, email_enricher, Agent 1B) keep writing to one identity
-- instead of recreating the old placeholder.
--
-- NOT idempotent -- this is a one-time data migration, not safe to re-run.

BEGIN;

UPDATE users
SET email = email || '.migrating-2026-08-12'
WHERE user_id = '00000000-0000-0000-0000-000000000001';

INSERT INTO users (
  user_id, email, state, reseller_cert_number, reseller_cert_expiry,
  costing_method, tax_treatment, subscription_tier, stripe_customer_id,
  account_status, deletion_scheduled_for, deleted_at, last_export_at,
  created_at, updated_at, gwp_cost_treatment, export_format,
  marketplace_concentration_alert_pct, capital_one_balance_alert,
  promo_cash_expiry_alert_days
)
SELECT
  '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4'::uuid, 'joshua.buckingham@gmail.com', state,
  reseller_cert_number, reseller_cert_expiry, costing_method, tax_treatment,
  subscription_tier, stripe_customer_id, account_status, deletion_scheduled_for,
  deleted_at, last_export_at, created_at, now(), gwp_cost_treatment, export_format,
  marketplace_concentration_alert_pct, capital_one_balance_alert,
  promo_cash_expiry_alert_days
FROM users
WHERE user_id = '00000000-0000-0000-0000-000000000001';

UPDATE business_expenses SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE cashback_transactions SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE gift_card_assignments SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE gift_cards SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE gwp SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE inventory SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE inventory_check_items SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE inventory_check_sessions SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE invoice_files SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE line_items SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE market_events SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE orders SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE portal_health SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE promotional_cash SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE purchase_plan_items SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE purchase_plans SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE retailer_cashback_profiles SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE retailer_profiles SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE returns SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE rewards_transactions SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE sales SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE shipments SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE stock_watch_checks SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE stock_watch_targets SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE tax_recovery SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';
UPDATE user_platform_onboarding SET user_id = '9f9f2ad3-d889-4c5e-a057-73ea0ddc93b4' WHERE user_id = '00000000-0000-0000-0000-000000000001';

DELETE FROM users WHERE user_id = '00000000-0000-0000-0000-000000000001';

COMMIT;
