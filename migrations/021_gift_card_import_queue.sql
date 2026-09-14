-- ResellOS Migration 021: Gift Card Import Queue (ADR-030)
--
-- Staging table for bulk-uploaded gift card data (Josh's "LGC" ledgers --
-- last4 + face value, sourced from sanitized spreadsheets he's kept outside
-- ResellOS) that has NOT yet had its purchase economics confirmed. Mirrors
-- the capture_queue -> orders promotion pattern (ADR-023/ADR-028): a bulk
-- import writes rows here as 'pending', a Streamlit review app
-- (gift_card_import_review_app.py) is where Josh confirms purchase_date and
-- purchase_price/discount_pct/source_platform per row (or in bulk across a
-- batch bought together), and only on that confirmation does a row get
-- written into the real `gift_cards` wallet table.
--
-- Why not write straight into `gift_cards`? Its purchase_price and
-- purchase_date columns are NOT NULL -- correctly, since a card's cost is
-- load-bearing for cost basis (ADR-027). A bulk-uploaded ledger of
-- last4+face_value alone can't satisfy that without guessing, which this
-- system does not do (ADR-023, ADR-024). This table exists to hold that gap
-- honestly instead of inventing a placeholder price.

CREATE TABLE IF NOT EXISTS gift_card_import_queue (
    import_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             uuid NOT NULL,
    retailer            text NOT NULL,
    card_number_last4   text NOT NULL,
    face_value          numeric NOT NULL,

    -- Raw order-linkage / balance data as read from the source ledger, kept
    -- verbatim for Josh's reference while reviewing -- NOT authoritative for
    -- anything and NOT parsed into a dedicated linkage table by this
    -- migration (no order<->gift-card linkage table exists yet; out of
    -- scope for ADR-030, see that ADR's Open Questions).
    source_linkage      jsonb,
    source_batch        text NOT NULL,

    status              text NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'promoted', 'skipped')),

    -- Filled in during review, not at bulk-import time.
    purchase_date       date,
    purchase_price      numeric,
    discount_pct        numeric,
    source_platform     text,
    notes               text,

    skip_reason         text,
    promoted_card_id    uuid REFERENCES gift_cards(card_id),
    reviewed_at         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE gift_card_import_queue IS
    'ADR-030: staging rows for bulk-uploaded gift card ledgers (last4 + face value only) awaiting purchase-economics confirmation in gift_card_import_review_app.py before being written into gift_cards.';
COMMENT ON COLUMN gift_card_import_queue.source_linkage IS
    'Raw order-linkage/balance data as read from the source spreadsheet, for reference only -- not parsed into a dedicated schema, no linkage table exists yet (see ADR-030 Open Questions).';
COMMENT ON COLUMN gift_card_import_queue.source_batch IS
    'Free-text tag identifying the upload this row came from, e.g. "lgc_2026_lego_2026-09-14" -- lets a re-run of the same file be recognized rather than re-queuing duplicates.';
COMMENT ON COLUMN gift_card_import_queue.promoted_card_id IS
    'Set when this row is confirmed and written into gift_cards -- the FK this row promoted into.';

CREATE INDEX IF NOT EXISTS idx_gift_card_import_queue_status
    ON gift_card_import_queue (user_id, status);
