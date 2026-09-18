-- ResellOS Migration 022: invoice_files.excluded_reason (Agent 01E backlog exclusions)
--
-- A 2026-09-19 investigation of Agent 01E's Invoices/Lego/_unmatched/
-- backlog found 18 files that will NEVER resolve into a real order match no
-- matter how many times Agent 01E re-scans them: 8 are pure noise (Home
-- Depot receipts, a donation receipt, LEGO Insiders points-history
-- screenshots) and 10 are real purchases (Walmart.com, Fred Meyer, an
-- in-store LEGO purchase, LEGO gift-card purchases) already tracked
-- separately in Brickprobe, in a retailer/format this LEGO-only PDF agent
-- was never going to match. Without a way to mark these as permanently
-- dismissed, they sit in the backlog forever, re-downloaded from Drive and
-- re-parsed on every single run.
--
-- excluded_reason marks a row as permanently out of Agent 01E's backlog
-- (agents/agent_01e_pdf_order_backfill.py's fetch_backlog_rows() filters on
-- it being null) without touching the underlying Drive file or deleting the
-- ledger row -- the file stays exactly where it is, still discoverable by
-- hand if ever needed, and the exclusion is reversible by clearing this
-- column if a file is ever found to have been excluded wrongly.

ALTER TABLE invoice_files ADD COLUMN excluded_reason text;

COMMENT ON COLUMN invoice_files.excluded_reason IS
    'Set when a backlog file will never resolve into a real order match -- either not an order at all, or a real purchase already tracked elsewhere in a format/retailer agent_01e_pdf_order_backfill.py does not handle. That agent''s fetch_backlog_rows() excludes any row with this set. Null = still an active backlog candidate. Never touches the underlying Drive file -- reversible by clearing this column.';
