# Detecting Missing Shipments on `agent_1e_pdf_backfill` Orders

**Created: 2026-09-17 (Cowork session), after finding and fixing 6 real orders with a missing shipment. Status: technique documented and run once manually. Not automated.**

## The problem

For orders that ship in multiple separate boxes, `agents/agent_01e_pdf_order_backfill.py` sometimes only ever finds/parses ONE of the invoice PDFs for a multi-shipment order, silently leaving the order missing an entire shipment's line items. The order still looks internally "reconciled" — its `subtotal` matches its own (incomplete) line items — so none of the existing checks in `order_validators.py` catch it. This is a class of bug, not a one-off: it can affect any order this agent auto-promoted (`entry_method = 'agent_1e_pdf_backfill'`), and there is no code-level guard against it today.

## The technique

For each order with `entry_method = 'agent_1e_pdf_backfill'`:

1. Search Gmail for LEGO's own shipping-confirmation emails — subject pattern `"Your LEGO Order T###### is on its way"`, sender `Noreply@t.crm.lego.com` — filtered to that order's order number.
2. Count how many distinct shipping-confirmation emails exist for that order number.
3. Compare against the count of `shipments` rows in Supabase for that same `order_number`.
4. **Where the email count is greater than the DB shipment count, that order is a high-confidence candidate for a missing shipment.**

Each shipping-confirmation email includes a per-shipment subtotal, tax, total, and item list — reading the actual email body (not just the count) is what confirms whether a candidate is a real gap or a false positive, and gives everything needed to reconstruct the missing shipment's line items without needing the original PDF at all.

Run once against all 592 `agent_1e_pdf_backfill` orders (2026-09-17), this surfaced 8 candidates — 6 were real gaps (fixed, see SESSION_LOG.md's 2026-09-17 Session History entry), 2 were false positives from the heuristic itself:

- A second "shipment" that was actually a $0 promo item shipped separately (doesn't affect cost basis) — seen on 2 orders.
- A manual-entry order that already had all real line items captured correctly, just with no `shipments`/tracking rows recorded (cosmetic gap only, not a missing-item gap).

A third case (T508133224) looked like a candidate but Josh confirmed directly the existing DB record is accurate and complete — LEGO simply never sent a complete shipping-notification email for that order. **A count mismatch is a signal to go read the actual emails, not proof of a gap by itself.**

## Known unreliable alternative: the LEGO order-details "shipped" page

The same investigation found that LEGO's own order-details page (the page the Chrome extension's `content.js` scrapes for `capture_stage='shipped'` captures) shows **inaccurate historical data for old orders**:

- It mislabels each item's allocated tax as a price "discount."
- It can show wildly wrong shipped-quantity totals — one real order displayed "6 shipped" when only 3 units were ever ordered or received (confirmed directly with Josh).

Do not trust a Chrome-extension recapture of an old order's pricing or quantity fields against this page. The Gmail shipping-confirmation emails are the reliable source for reconstructing historical shipments; the live order-details page is not, once an order is old enough.

## What's not built

This was run once, by hand, against one entry_method (592 orders). It has not been:

- Automated as a repeatable check or added to `order_validators.py` (an order missing a whole shipment can still pass every existing check — see CONTEXT.md Open Question #22).
- Extended to orders with other `entry_method` values (manual entry, `capture_queue_promotion.py`, the Chrome extension, `walmart_business_csv_import`, etc.) — LEGO's split-shipment behavior isn't unique to PDF-backfilled orders, so the same class of gap could in principle exist elsewhere.

## Related

- CONTEXT.md Open Question #22 — the durable "known gap" entry for this bug class.
- SESSION_LOG.md, 2026-09-17 Session History entry — the 6 orders fixed and 3 candidates investigated this run.
