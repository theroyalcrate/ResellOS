-- Migration 020: Line item cancellation tracking (mid-order cancellation retention)
-- ADR-029 -- see repo root for full rationale and the real example (T513531463).
--
-- Problem: LEGO (and possibly other retailers) will cancel a single item on a
-- multi-item order after the fact -- almost always because it went out of
-- stock again before shipping -- while still shipping everything else on the
-- order, INCLUDING any GWP that item's presence in the cart qualified for at
-- checkout. Until now this was handled ad hoc: the cancelled item was simply
-- omitted from line_items entirely and the story preserved only in free-text
-- order notes (T513531463, "GWP hack" pattern flagged by Josh 2026-09-14).
-- That loses the ability to see or report on the pattern later. Josh has
-- identified this recurs 15-20+ times per year, predictably every Q4 (see
-- CONTEXT.md's A-003 edge case), and asked for it to be trackable in the
-- schema rather than re-explained in prose every time it happens.
--
-- Fix: line_items keeps a row for every item that was actually part of the
-- order as confirmed, whether or not it ultimately shipped. item_status
-- distinguishes the two. A cancelled row always carries $0 cost basis and
-- never enters inventory -- Josh was never charged for it and never
-- received it -- but stays queryable for pattern reporting later (e.g. "how
-- many times did a cancelled item still net me a GWP this year, and what
-- was the GWP worth").

ALTER TABLE line_items
    ADD COLUMN item_status TEXT NOT NULL DEFAULT 'received',
    ADD COLUMN cancellation_reason TEXT,
    ADD COLUMN cancelled_at DATE;

ALTER TABLE line_items
    ADD CONSTRAINT line_items_item_status_check
    CHECK (item_status IN ('received', 'cancelled'));

COMMENT ON COLUMN line_items.item_status IS
    'received = normal, shipped/delivered as ordered (default). cancelled = '
    'retailer cancelled this specific item after the order was confirmed '
    '(e.g. went out of stock again before shipping) -- never charged, never '
    'received, carries $0 cost basis and never enters inventory. Orthogonal '
    'to is_gwp: this flags what happened to THIS item post-order, not '
    'whether it was a gift-with-purchase (rare case: a GWP itself could in '
    'principle be the cancelled item). See ADR-029 / migration 020.';

COMMENT ON COLUMN line_items.cancellation_reason IS
    'Free text, only meaningful when item_status = ''cancelled'' -- e.g. '
    '"out_of_stock_after_gwp_qualified". Null for received items.';

COMMENT ON COLUMN line_items.cancelled_at IS
    'Date the cancellation was confirmed (e.g. from a retailer cancellation '
    'email or the order-details page), if known. Null for received items or '
    'when the date isn''t known.';
