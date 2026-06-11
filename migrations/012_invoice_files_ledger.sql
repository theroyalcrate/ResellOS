-- Applied via MCP as migration version 20260611041822 (011_invoice_files_ledger) — local file is reference only.
-- Migration 012: invoice_files ledger for Agent 1B filing tracking
-- Idempotent (IF NOT EXISTS) — safe if already applied via Supabase MCP.
--
-- Tracks every invoice PDF filed by Agent 1B.
-- gmail_message_id is the dedup key — checked before every write.

CREATE TABLE IF NOT EXISTS public.invoice_files (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid        NOT NULL,
    gmail_message_id  text        UNIQUE NOT NULL,
    drive_file_id     text,
    order_id          uuid        REFERENCES public.orders(order_id) ON DELETE SET NULL,
    retailer          text,
    filed_filename    text,
    filed_at          timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.invoice_files ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'invoice_files'
        AND policyname = 'invoice_files_user_policy'
    ) THEN
        EXECUTE $policy$
            CREATE POLICY invoice_files_user_policy
                ON public.invoice_files
                FOR ALL
                USING (user_id = auth.uid())
                WITH CHECK (user_id = auth.uid())
        $policy$;
    END IF;
END $$;
