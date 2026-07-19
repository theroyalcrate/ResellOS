-- Migration 015: Purchase Planner (Agent 09) schema
-- purchase_plans + purchase_plan_items — one row per planned buying session,
-- created ahead of time when a sale window, double-points event, or GWP
-- threshold is coming up. See CONTEXT.md "Purchase Planner design (Agent 09)"
-- (decided 2026-07-18) for full design.
--
-- Applied via Supabase MCP under migration name "014_purchase_plans" (the
-- name it was actually run under) before the local file was renumbered to
-- 015 — same pattern as migration 012 tolerating an MCP-name/file-number
-- mismatch. The schema is what matters; local file is reference only.
--
-- Renumbered 014 -> 015 (2026-07-18) because SESSION_LOG.md's "Note on
-- Migration 012 numbering" already reserves 013 for account_type on
-- retailer_profiles and 014 for block_identifier on promotional_cash
-- (both planned for S10, not yet built). This file didn't know that when
-- first written — 015 is the actual next free slot.
--
-- Idempotent (IF NOT EXISTS) — safe to re-run.

CREATE TABLE IF NOT EXISTS public.purchase_plans (
    plan_id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     uuid        NOT NULL,
    plan_name                   text        NOT NULL,
    retailer                    text        NOT NULL,
    status                      text        NOT NULL DEFAULT 'draft',
        -- draft | ready | placed  (mirrors hit_list's active/purchased/abandoned pattern)
    target_type                 text        NOT NULL,
        -- gwp_threshold | points_tier | spend_cap
    target_value                numeric(12,2) NOT NULL,
    lego_points_multiplier      integer     NOT NULL DEFAULT 1,
        -- used only when target_type = points_tier or retailer = lego, for points estimate
    gift_card_id                uuid        REFERENCES public.gift_cards(card_id) ON DELETE SET NULL,
    planned_gift_card_balance   numeric(12,2),
        -- manual snapshot/override — used when gift_card_id is null (card not bought yet)
        -- or Josh wants to plan against a different balance than the live one
    insider_points_available    integer,
        -- manual entry — no running points-balance table exists yet
    notes                       text,
    placed_order_id             uuid        REFERENCES public.orders(order_id) ON DELETE SET NULL,
        -- set when status -> placed and linked to the real order in agent_02
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.purchase_plan_items (
    item_id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     uuid        NOT NULL,
    plan_id                     uuid        NOT NULL REFERENCES public.purchase_plans(plan_id) ON DELETE CASCADE,
    set_name                    text        NOT NULL,
    set_number                  text,
    unit_price                  numeric(12,2) NOT NULL,
    is_gwp_eligible              boolean     NOT NULL DEFAULT false,
    is_sale_or_promo             boolean     NOT NULL DEFAULT false,
    max_quantity                integer     NOT NULL DEFAULT 2,
        -- caps the combination search — how many of this set Josh would realistically buy
    notes                       text,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_purchase_plans_user_id   ON public.purchase_plans(user_id);
CREATE INDEX IF NOT EXISTS idx_purchase_plans_status     ON public.purchase_plans(status);
CREATE INDEX IF NOT EXISTS idx_purchase_plan_items_plan_id ON public.purchase_plan_items(plan_id);

ALTER TABLE public.purchase_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_plan_items ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'purchase_plans'
        AND policyname = 'purchase_plans_user_policy'
    ) THEN
        EXECUTE $policy$
            CREATE POLICY purchase_plans_user_policy
                ON public.purchase_plans
                FOR ALL
                USING (user_id = auth.uid())
                WITH CHECK (user_id = auth.uid())
        $policy$;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'purchase_plan_items'
        AND policyname = 'purchase_plan_items_user_policy'
    ) THEN
        EXECUTE $policy$
            CREATE POLICY purchase_plan_items_user_policy
                ON public.purchase_plan_items
                FOR ALL
                USING (user_id = auth.uid())
                WITH CHECK (user_id = auth.uid())
        $policy$;
    END IF;
END $$;
