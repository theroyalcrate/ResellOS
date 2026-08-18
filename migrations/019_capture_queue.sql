-- Migration 019: capture_queue -- staging table for the ResellOS Chrome Extension's
-- review-queue write model (decided 2026-08-01, see CONTEXT.md -> Planned Future
-- Systems -> ResellOS Chrome Extension). Sits between the extension's raw page
-- capture and a real orders/line_items row: the extension writes here only, a
-- human promotes a row into a real order, nothing here ever auto-creates a
-- settled order or triggers cost basis -- same principle as the email-order-
-- matching review queue (A-007) and the stub->pending_review->confirmed order
-- gate (DECISION 017).
--
-- raw_data is jsonb because each of the 5 scoped retailers' captured page differs
-- (LEGO.com: set#/qty/price/card-last-4; Kohl's: rewards earned + KC redeemed;
-- Walmart: charge-history hold/adjustment/final; etc. -- see the per-retailer
-- recon findings in CONTEXT.md). The handful of top-level columns are pulled out
-- for a fast review-queue list view; raw_data is the source of truth for the
-- eventual promote-to-order mapping, which is a separate, not-yet-built piece.
--
-- Status vocabulary matches the existing hit_list pattern (active/purchased/
-- abandoned) with equivalent semantics: pending (default, awaiting review) ->
-- promoted (became a real order, promoted_order_id set) -> discarded (reviewed
-- and rejected, e.g. a duplicate capture or a personal-use order not meant for
-- ResellOS). Discarded rows are kept, not deleted -- preserves history per the
-- same "never silently lose data" convention used elsewhere.
--
-- Applied live via Supabase MCP 2026-08-12. apply_migration reported success;
-- a follow-up verification read was blocked by the session's auto-mode
-- classifier (after several consecutive DB-write calls in one session) before
-- it could be confirmed independently -- verify column list / RLS in the
-- Supabase dashboard (Table Editor -> capture_queue) next session before
-- building the promote-to-order logic against it.
--
-- Idempotent: NOT idempotent (no IF NOT EXISTS) -- do not re-run if the table
-- already exists.

CREATE TABLE capture_queue (
  capture_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(user_id),
  retailer text NOT NULL,
  source_url text,
  captured_at timestamptz NOT NULL DEFAULT now(),
  raw_data jsonb NOT NULL,
  order_number text,
  order_date date,
  total numeric,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'promoted', 'discarded')),
  promoted_order_id uuid REFERENCES orders(order_id),
  reviewed_at timestamptz,
  review_note text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX capture_queue_user_status_idx ON capture_queue(user_id, status);

ALTER TABLE capture_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY capture_queue_user_policy ON capture_queue FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
