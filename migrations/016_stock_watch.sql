-- Migration 016: Buy-side stock/discount watch tool (Agent 10) schema
-- stock_watch_targets + stock_watch_checks. See CONTEXT.md "Buy-side stock
-- watch tool (Agent 10)" for full design. Scoped to the 7 daily-cadence
-- retailers (Macy's, Target, Kohl's, Walmart, JCPenney, Christianbook,
-- Amazon) — LEGO.com seconds-level restock alerts are explicitly out of
-- scope; Josh already pays for a dedicated service for that (decided
-- 2026-07-19).
--
-- Design note: one row per SET in stock_watch_targets (not per set+retailer)
-- — which retailers actually carry a given set isn't known ahead of time,
-- so a daily check fans out across all active retailers per set and
-- discovers carriers naturally (found=false rows are expected and normal,
-- not errors).
--
-- Idempotent (IF NOT EXISTS) — safe to re-run.

CREATE TABLE IF NOT EXISTS public.stock_watch_targets (
    target_id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     uuid        NOT NULL,
    set_number                  text        NOT NULL,
    set_name                    text,
    theme                       text,
    msrp                        numeric(12,2),
    tier                        text,
        -- High | High-mid | Mid | Mid-low — from the Brick Domain tier list source
    retiring_month              text,
        -- e.g. 'July' — as reported by the source list, not a hard LEGO EOL date
    active                      boolean     NOT NULL DEFAULT true,
    discount_alert_threshold_pct numeric(6,2) NOT NULL DEFAULT 20,
    notes                       text,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, set_number)
);

CREATE TABLE IF NOT EXISTS public.stock_watch_checks (
    check_id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     uuid        NOT NULL,
    target_id                   uuid        NOT NULL REFERENCES public.stock_watch_targets(target_id) ON DELETE CASCADE,
    retailer                    text        NOT NULL,
    checked_at                  timestamptz NOT NULL DEFAULT now(),
    found                       boolean     NOT NULL DEFAULT false,
        -- whether the retailer carries/lists this item at all — false is
        -- expected and normal, not an error (not every retailer carries
        -- every set)
    in_stock                    boolean,
        -- null when found = false
    price                       numeric(12,2),
    availability_raw            text,
    product_url                 text,
    alert_triggered             boolean     NOT NULL DEFAULT false,
    alert_reason                text,
        -- 'restock' | 'discount_<pct>pct' | comma-joined if both fire
    created_at                  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stock_watch_targets_user_id   ON public.stock_watch_targets(user_id);
CREATE INDEX IF NOT EXISTS idx_stock_watch_targets_active    ON public.stock_watch_targets(active);
CREATE INDEX IF NOT EXISTS idx_stock_watch_checks_target_id  ON public.stock_watch_checks(target_id);
CREATE INDEX IF NOT EXISTS idx_stock_watch_checks_retailer   ON public.stock_watch_checks(retailer);
CREATE INDEX IF NOT EXISTS idx_stock_watch_checks_checked_at ON public.stock_watch_checks(checked_at);

ALTER TABLE public.stock_watch_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stock_watch_checks ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'stock_watch_targets'
        AND policyname = 'stock_watch_targets_user_policy'
    ) THEN
        EXECUTE $policy$
            CREATE POLICY stock_watch_targets_user_policy
                ON public.stock_watch_targets
                FOR ALL
                USING (user_id = auth.uid())
                WITH CHECK (user_id = auth.uid())
        $policy$;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'stock_watch_checks'
        AND policyname = 'stock_watch_checks_user_policy'
    ) THEN
        EXECUTE $policy$
            CREATE POLICY stock_watch_checks_user_policy
                ON public.stock_watch_checks
                FOR ALL
                USING (user_id = auth.uid())
                WITH CHECK (user_id = auth.uid())
        $policy$;
    END IF;
END $$;
