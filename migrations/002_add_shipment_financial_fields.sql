-- ============================================================
-- Migration 002: Add Financial Fields to Shipments
-- Date: 2026-05-23 (S04)
-- Purpose: Store invoice-level financial data on each shipment row
--   so Agent 1A can write subtotal, tax, shipping, and payment_method
--   directly from the parsed PDF — no separate lookup needed.
-- ============================================================

ALTER TABLE shipments ADD COLUMN subtotal       NUMERIC(12,2);
ALTER TABLE shipments ADD COLUMN tax_amount     NUMERIC(12,2) DEFAULT 0;
ALTER TABLE shipments ADD COLUMN shipping_amount NUMERIC(12,2) DEFAULT 0;
ALTER TABLE shipments ADD COLUMN payment_method TEXT;

-- ============================================================
-- Migration complete. 4 columns added to shipments.
-- After applying: re-run invoice_parser.py --db to populate these
-- fields for any shipments created before this migration.
-- ============================================================
