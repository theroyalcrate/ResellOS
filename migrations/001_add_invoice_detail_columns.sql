-- ============================================================
-- Migration 001: Add Invoice Detail Columns
-- Date: 2026-05-18 (Pre-S02)
-- Purpose: Capture additional fields from invoice parser
--   - invoice_number (separate from order_number)
--   - invoice_date (separate from order_date)
--   - shipping_address (for users who ship to different addresses)
--   - article_number on line_items (LEGO internal SKU)
--   - insider_points_redeemed on orders
-- ============================================================

-- Orders table additions
ALTER TABLE orders ADD COLUMN invoice_number TEXT;
ALTER TABLE orders ADD COLUMN invoice_date DATE;
ALTER TABLE orders ADD COLUMN shipping_address TEXT;
ALTER TABLE orders ADD COLUMN insider_points_redeemed NUMERIC(12,2) DEFAULT 0;

-- Line items additions
ALTER TABLE line_items ADD COLUMN article_number TEXT;

-- Index for invoice number lookups (rare but useful for audits)
CREATE INDEX idx_orders_invoice_number ON orders(invoice_number)
    WHERE invoice_number IS NOT NULL;

-- ============================================================
-- Migration complete. 5 columns added, 1 index added.
-- ============================================================