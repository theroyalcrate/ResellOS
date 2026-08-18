-- Migration 017: RLS policy backfill — Phase 2 Supabase Auth prep
--
-- Applied live via Supabase MCP 2026-08-12 (approved by Josh same session).
--
-- Context: RLS was already ON (rowsecurity=true) for all public tables, but
-- only 5 tables actually had a policy defined: invoice_files, purchase_plans,
-- purchase_plan_items, stock_watch_targets, stock_watch_checks (all built in
-- the 2026-07-18/19 Agent 09/10 sessions). The other 22 tables — including
-- orders, line_items, gift_cards, inventory, sales, users, everything that
-- matters for the core business — had RLS enabled with zero policies, which
-- means deny-all for any request under the anon/authenticated role. Backend
-- agents were never affected by this gap (db_client.py uses the secret
-- service-role key, which bypasses RLS entirely) — but it meant that as soon
-- as the ResellOS Chrome Extension or any future app tried to read/write
-- using the publishable key + a logged-in Supabase Auth user, it would see
-- nothing outside those 5 tables. Found and fixed as part of the 2026-08-12
-- Supabase Auth walkthrough (see SESSION_LOG.md).
--
-- This migration adds the identical policy pattern already proven on the 5
-- existing tables (user_id = auth.uid(), FOR ALL) to the remaining 22.
-- Purely additive — touches no data, doesn't change existing agent behavior.
--
-- Still open after this migration (see SESSION_LOG.md "Start Here"):
-- 1. No Supabase Auth user exists yet (auth.users was empty as of 2026-08-12).
--    Josh needs to create one via Dashboard -> Authentication -> Users -> Add user.
-- 2. Existing data (9 orders, 211 gift cards, etc.) is all keyed to the
--    Phase 1 hardcoded UUID (00000000-0000-0000-0000-000000000001, see
--    PHASE_1_USER_ID in db_client.py). Once Josh's real auth UID exists, a
--    decision is needed: migrate all existing user_id values to match it
--    (recommended — keeps one identity, no re-entry), or leave Phase 1 data
--    on the old UUID and only use the new UID for new tables going forward.
-- 3. capture_queue (or similar) staging table for the extension's
--    review-queue write model is not yet designed/created.
--
-- Idempotent: NOT idempotent (CREATE POLICY has no IF NOT EXISTS in this
-- Postgres version) — do not re-run against a project that already has these
-- policy names; drop first if re-applying.

CREATE POLICY business_expenses_user_policy ON business_expenses FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY cashback_transactions_user_policy ON cashback_transactions FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY gift_card_assignments_user_policy ON gift_card_assignments FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY gift_cards_user_policy ON gift_cards FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY gwp_user_policy ON gwp FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY inventory_user_policy ON inventory FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY inventory_check_items_user_policy ON inventory_check_items FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY inventory_check_sessions_user_policy ON inventory_check_sessions FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY line_items_user_policy ON line_items FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY market_events_user_policy ON market_events FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY orders_user_policy ON orders FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY portal_health_user_policy ON portal_health FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY promotional_cash_user_policy ON promotional_cash FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY retailer_cashback_profiles_user_policy ON retailer_cashback_profiles FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY retailer_profiles_user_policy ON retailer_profiles FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY returns_user_policy ON returns FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY rewards_transactions_user_policy ON rewards_transactions FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY sales_user_policy ON sales FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY shipments_user_policy ON shipments FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY tax_recovery_user_policy ON tax_recovery FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY user_platform_onboarding_user_policy ON user_platform_onboarding FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY users_user_policy ON users FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
