# ADR-030 — Gift Card Bulk Import & Review Queue

**Date:** 2026-09-14
**Status:** Accepted
**Extends:** ADR-027 (Gift Card Discount Estimation Policy) and the `gift_cards` wallet table it built on. Mirrors the ADR-023 (capture_queue) / ADR-028 (review app) two-step pattern already proven for LEGO orders.

---

## Context

Josh keeps sanitized "LGC" (gift card) ledgers outside ResellOS — spreadsheets tracking each physical gift card's last-4 digits, face value, and (for the LEGO one) which orders it was spent against. These predate ResellOS and are the only record of a meaningful chunk of gift card inventory: a first pass on the LEGO sheet alone found 212 unique cards, 129 of which aren't in the `gift_cards` table yet.

These ledgers were never built to feed a database directly, and it shows: column alignment is inconsistent in places (a "balance" column that means something different in different sections of the same sheet), and — critically — they don't carry purchase price, purchase date, or source platform. `gift_cards.purchase_price` and `purchase_date` are `NOT NULL` by design (ADR-027: a card's cost is load-bearing for cost basis), so there's no honest way to write these rows straight into the wallet. Also relevant, from Josh directly: entering that missing data one card at a time via `agent_05_gift_cards.py`'s terminal prompts, or by hand in Supabase, is not something he wants to do for a batch this size — his words, entering last-4s "in Supabase or the terminal gets to be a bit much."

Josh's own framing, unprompted: "this requires a two-step build similar to what we did with LEGO orders" — bulk upload, then a Streamlit app where he verifies purchase date, discount percent or purchase price, before it's logged into the wallet. That's exactly the capture_queue → review app → orders shape this ADR follows.

Barnes & Noble, Kohl's, and other retailer gift card ledgers exist but are not yet sanitized to last-4-only (they currently show full card numbers) — out of scope for this ADR's first run, but the schema and tooling built here are retailer-agnostic and need no changes to take them once Josh sanitizes and uploads them.

## Decision

### New table: `gift_card_import_queue` (migration 021)

A staging table, structurally parallel to `capture_queue`: bulk-written mechanically, reviewed and confirmed by a human, then promoted into the real table (`gift_cards` here, `orders`/`line_items` there). Columns: `retailer`, `card_number_last4`, `face_value` (populated at import time); `purchase_date`, `purchase_price`, `discount_pct`, `source_platform`, `notes` (populated at review time, all nullable until then); `source_linkage` (jsonb — the raw source row, kept verbatim for the reviewer's reference, never parsed into a schema — see Open Questions); `source_batch` (a free-text tag identifying which upload a row came from, so a re-run of the same file doesn't double-queue); `status` (`pending` / `promoted` / `skipped`); `promoted_card_id` (FK into `gift_cards` once written).

### Bulk import: `agents/agent_11_gift_card_bulk_import.py`

Reads a ledger spreadsheet, extracts only the two fields that were unambiguous across every row actually checked — card last-4 and face value — and stages each as a `pending` row. Deliberately does **not** attempt to parse "remaining balance" or per-order spend amounts out of these sheets: the column layout for that data is inconsistent within the one real ledger inspected so far (a header cell labeled "balance" doesn't line up with where the actual balance value lands a few rows down), and guessing at a misaligned column is worse than not extracting it — consistent with this system's standing rule to flag rather than silently guess (ADR-023, ADR-024). That raw row is preserved untouched in `source_linkage` so Josh can eyeball it during review if a number looks off, but it is not treated as authoritative for anything.

Dedupes against both the existing `gift_cards` wallet (skip a last-4 already tracked for that retailer) and any prior queue rows from the same `source_batch` tag (so re-running the same file is safe). Does not collapse a last-4 that appears more than once *within* one file — flags it and queues both, since a repeated last-4 across genuinely different physical cards is a real possibility this system doesn't rule out (ADR-027 treats last-4 the same way).

### Review: `gift_card_import_review_app.py` (Streamlit)

Same shape as `capture_queue_review_app.py` (ADR-028): pending rows listed, nothing reaches `gift_cards` without a human confirming it here. Two paths, because most cards in one ledger batch were bought together at the same price/date/source:

- **Bulk apply** — set purchase date, price, and source platform once, tick which pending rows it applies to, save them all in one action. This is the fast path for the common case (a $250 face-value batch bought in one Kroger or CardCenter order).
- **Per-row override** — each row also has its own expander with the same three fields, for the case where a handful of cards in a batch were bought differently.

On save, `discount_pct` is computed the same way `agent_05_gift_cards.py` already does ((face_value − purchase_price) / face_value), the new `gift_cards` row is written with `discount_confidence = 'exact'` (Josh is confirming real numbers from his own ledger — same tier as a direct receipt, per ADR-027's confidence-tiering), and the queue row is marked `promoted` with a reference back to the new card. A "Skip" action exists per row for anything Josh decides not to bring in (already accounted for elsewhere, bad data, etc.), with a required reason.

## Consequences

- Migration 021 required — applied live 2026-09-14.
- Confirms which of a bulk ledger's cards are genuinely new vs. already tracked before any review work happens, so Josh isn't re-entering data for cards already in the wallet.
- Purchase price is always required before a card reaches `gift_cards` — this ADR does not relax ADR-027's confidence tiering or introduce a path for an un-costed card to enter cost basis.
- Barnes/Kohl's/other retailer ledgers can run through the exact same importer and review app once sanitized — no retailer-specific logic was built into either script.

## Open Questions

1. **Order↔gift-card linkage is out of scope here.** The LEGO ledger's order-number/spent-amount data is preserved in `source_linkage` for reference but isn't written into any queryable schema — no `order_gift_card_links`-equivalent table exists in ResellOS yet (confirmed: no such table, and `orders.gift_card_applied` is a boolean, not a linkage). ADR-027 already flagged that this linkage is "necessary but not sufficient" for Layer 2 cost basis. Worth its own ADR when Josh wants that reconciliation queryable rather than living in a private spreadsheet — not addressed by this one.
2. **"Remaining balance" is currently unrecoverable from the LEGO ledger's inconsistent columns.** If Josh wants it tracked (e.g. for a partially-spent card), it'll need either a cleaner source export or manual entry per card in the review app — not built here since it wasn't part of the stated ask (purchase date, discount/price, before logging to the wallet).

## Related decisions

- ADR-023 — Capture Queue Promotion and Extension Primacy (the bulk-stage/review-stage/promote-stage pattern this ADR reuses)
- ADR-027 — Gift Card Discount Estimation Policy (confidence tiering; `discount_confidence = 'exact'` applied here follows its rule directly)
- ADR-028 — Capture Queue Review Tool (the Streamlit review-app shape this ADR mirrors)
- `agent_05_gift_cards.py` — the existing single/bulk manual-entry CLI this doesn't replace; still the right tool for entering one or two cards by hand
