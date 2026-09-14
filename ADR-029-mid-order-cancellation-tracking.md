# ADR-029 — Mid-Order Cancellation Tracking (the "GWP-Hack" Pattern)

**Date:** 2026-09-14
**Status:** Accepted
**Supersedes:** The "manual adjustment workflow" language in CONTEXT.md's A-003 edge case (Partial order cancellations with GWP retention) — that edge case is now handled structurally instead of purely by convention.

---

## Context

LEGO (and potentially other retailers) will sometimes cancel a single item on a multi-item order after checkout — almost always because it went out of stock again before shipping — while still shipping everything else on the order, **including any GWP that the cancelled item's presence in the cart qualified for**. Real, confirmed example: order T513531463 (2026-09-02). Josh was alerted by stock-watch software that Malfoy Manor (76453) had come back in stock, placed the order, which qualified for the Ministry Munchies & Daily Prophet Stands GWP (40901) at checkout. LEGO cancelled Malfoy Manor again before it shipped. The Fennec Shand keychain (854245, 70% off) and the GWP both shipped and were received; the card was charged $1.98 total, not the ~$7+ the order would have been with Malfoy Manor included.

Josh confirmed this is not a one-off: it happens **15-20+ times a year, predictably concentrated around Q4** (already documented, before this ADR, as edge case A-003 in CONTEXT.md — "Partial order cancellations with GWP retention"). He deliberately targets sets he actually wants when doing this — if the set ships, great; if it's cancelled, he still nets a GWP for a much smaller outlay. This is a recurring, intentional sourcing tactic, not noise to be cleaned up — Josh explicitly asked (2026-09-14) for it to be trackable in the schema so it can eventually be reported on (frequency, GWP value captured this way, hit rate), rather than re-explained in free-text order notes every time it happens.

Until this ADR, the pattern was handled entirely ad hoc: the cancelled item was simply **omitted from `line_items` entirely**, with the full story preserved only in `orders.notes` (exactly what was done for T513531463 when it was first entered). This satisfies cost-basis correctness (nothing improperly enters inventory) but has real costs:

1. **No way to query the pattern.** "How many times did this happen this year" or "what's the average GWP value captured this way" requires manually re-reading order notes across hundreds of orders.
2. **Loses the record of what was actually ordered**, not just what shipped — useful context if a retailer's cancellation behavior itself needs auditing later (e.g. confirming LEGO really did honor the GWP every time, per CONTEXT.md's retailer-cancellation-behavior notes).
3. **Collides with a check this session just added to the capture-queue review tool** (ADR-028): `order_validators.check_gwp_price_consistency()` flags any non-GWP item priced at $0 as a probable mis-flagged GWP. A cancelled item that's kept as a $0 line item to preserve the record would trip this warning on *every single occurrence* of an expected, intentional pattern — exactly backwards from what a warning should do.

## Decision

### New `line_items` columns (migration 020)

- `item_status TEXT NOT NULL DEFAULT 'received'`, `CHECK (item_status IN ('received', 'cancelled'))`
- `cancellation_reason TEXT` — free text, e.g. `out_of_stock_after_gwp_qualified`. Null unless cancelled.
- `cancelled_at DATE` — when known. Null otherwise (the exact cancellation date usually isn't surfaced anywhere Josh sees it).

`item_status` is **orthogonal to `is_gwp`** — it flags what happened to *this* item after the order was placed, not whether it's a gift-with-purchase. In principle a GWP itself could be the cancelled item (rare, not seen yet, but the schema doesn't rule it out).

### A cancelled line item is kept, not omitted

Every item that was actually part of the order as confirmed gets a `line_items` row, whether or not it shipped. A `cancelled` row:

- Always carries `line_total = 0`, `line_discount = 0` — never charged.
- Never enters `inventory` and never gets a cost-basis allocation — never received. (No code currently creates `inventory` rows straight from `line_items` outside the cost-basis engine's own explicit steps, so this is a constraint on future work, not a change to existing behavior.)
- Keeps `unit_price`/`msrp` when known, for record — left null when the retailer never surfaced a price before cancelling (as with Malfoy Manor: LEGO's own capture showed $0 for it once cancelled, so the real retail price wasn't recorded anywhere Josh has access to).
- Is fully queryable later: `SELECT * FROM line_items WHERE item_status = 'cancelled'`, or the full pattern — orders with a cancelled item *and* a retained GWP on the same order — via a join on `order_id`.

### Validators updated (`order_validators.py`)

`check_gwp_price_consistency()` and `check_missing_set_numbers()` now skip any item with `item_status == 'cancelled'` — a cancelled item is expected to be priced at $0 (or unknown) and is not "probably a mis-flagged GWP." This directly fixes the collision with ADR-028's review-tool warnings described above.

### Entry points updated

- **`agent_02_order_entry.py`** (manual entry): after "Is this a GWP?", asks "Was this item cancelled by the retailer (never charged, never received)?" When yes, prompts for an optional reason and date, forces `line_total`/`line_discount` to 0 regardless of what was entered for price, and skips the LEGO points-multiplier / bonus-points / Walmart set-cash-reward follow-ups (none of those apply to an item that was never actually fulfilled).
- **`capture_queue_review_app.py`** (ADR-028 review tool): the per-item inline-edit row gets a third checkbox, "Cancelled," alongside the existing GWP checkbox and set-number field — the natural point for Josh to mark this, since a cancellation is usually only visible once the shipped-stage capture or tracking page shows fewer items than the order confirmation did.
- **`capture_queue_promotion.py`**: `_map_line_items()` passes through `item_status`/`cancellation_reason`/`cancelled_at` when present in `raw_data` (defaults to `received` — no existing capture path detects a cancellation automatically; it's always a human noticing and marking it).

### `expected_item_count` is deliberately left alone

`capture_queue_promotion.py`'s `_build_order()` still counts a cancelled item toward `expected_item_count`, because that field represents what the order was originally confirmed to contain, which is a fact independent of what later happened to it. This is a known, accepted nuance — not treated as a bug — and is called out here so a future session doesn't "fix" it into double-counting or under-counting against invoice/shipment reconciliation.

## Consequences

- Migration 020 required, applied live 2026-09-14.
- T513531463 was retrofitted: Malfoy Manor (76453) was inserted as an `item_status = 'cancelled'` line item on the existing order (previously omitted entirely) — the first real use of this pattern, done at the same time as this ADR so the schema is validated against real data immediately rather than sitting unused.
- CONTEXT.md's A-003 edge case updated to point to this ADR instead of describing a purely manual workflow.
- Reporting/ROI queries that sum or average `line_items` should filter `item_status != 'cancelled'` wherever they aren't already implicitly excluding $0/never-received items — worth a sweep once the Intelligence/Reporting Layer (CONTEXT.md, Phase 2-3) is actually built, not urgent before then since no reporting layer exists yet to get this wrong.
- Future possibility, not built now: a dedicated view or report specifically for this pattern (count per year, GWP value captured, hit rate of "item ships anyway" vs. "item cancelled") — Josh's stated interest is in eventually seeing this, but no UI/report exists yet; this ADR only makes the underlying data queryable.

## Related decisions

- ADR-023 — Capture Queue Promotion and Extension Primacy (capture_queue as the review gate this flows through)
- ADR-028 — Capture Queue Review Tool (the inline-edit UI this extends, and the validator whose false-positive this fixes)
- CONTEXT.md — Edge Case A-003 (Partial order cancellations with GWP retention) and the GWP Philosophy C cost-basis rules ($0 cost basis, proceeds reduce order)
- DECISION 017 — Order edit lifecycle & cost basis trigger gate (cost basis never touches a cancelled item, consistent with "never guess, never auto-fill")
