# ADR-031: Gift Card Balance Tracking, Wired to the Order Confirm/Reopen Lifecycle

**Status:** Accepted — built 2026-09-15
**Date:** 2026-09-15
**Related:** CONTEXT.md Open Question #21, DECISION 017 (Order Edit Lifecycle & Cost Basis Trigger Gate, 2026-06-01), ADR-019 (Order Settlement Gate), ADR-029 / migration 020 (mid-order cancellation tracking)

## Correction from the first draft

The first draft of this ADR proposed debiting the gift card at raw order-write
time and building a separate, standalone "adjustment tool" for cancellations,
reasoning that no order-edit or status-reopen capability exists anywhere in
the codebase today. Josh caught the actual mistake: **that reasoning runs
backwards.** DECISION 017, recorded 2026-06-01 — before most of the codebase
existed — already specifies exactly this system, and it's the gap in the
*build*, not the *design*, that needed fixing. Quoting it in full:

> **Order status values:** stub (email agent created, payment details
> incomplete — cost basis blocked) → pending_review (user opened, something
> still needs attention — cost basis blocked) → confirmed (user explicitly
> confirmed all inputs — cost basis calculates once) → placed (pickup orders
> only, awaiting pickup — cost basis blocked until pickup confirmed) →
> settled (12-month window passed, cost basis locked permanently).
>
> **Editable fields by status:** stub/pending_review — any field editable.
> confirmed — only fields that do not affect cost basis (buy_reason, notes,
> storage_location, purchase_trigger). Fields affecting cost basis require
> explicit reopen to pending_review, which clears calculated cost basis and
> recalculates on re-confirm. settled — nothing reopens cost basis; P&L
> adjustment entries only.
>
> **Gift card ledger atomic write:** When order moves to confirmed, two
> writes happen atomically — order status confirmed + cost basis calculated,
> and gift card balance reduced by amount applied. Reopening to
> pending_review reverses the prior balance reduction before applying the
> new one. Gift card ledger stores order_id on every debit so reversals are
> unambiguous.

That is the actual answer to Josh's partial-cancellation requirement — not a
bolt-on adjustment tool. This build implements *that* mechanism, using gift
cards as the concrete driver, since it's the piece of DECISION 017 that never
got implemented.

## Context (what was real in the code before this build)

- `gift_card_assignments` existed with the right shape but was essentially
  unused (18 rows against 366 `gift_cards` rows); nothing wrote to it.
- `gift_cards.remaining_balance` was set once at creation/import and never
  debited by any code path.
- `agent_02_order_entry.py` wrote new manual orders directly as
  `order_status = "confirmed"`, with no reopen path back to an editable
  state afterward.
- `capture_queue_promotion.py` writes captured/parsed orders at
  `pending_review` (confirmed by reading the file — it reuses
  `agent_02_order_entry.write_order()` directly) and never promoted them
  further — nothing existed to move an order from `pending_review` to
  `confirmed`, or back again.
- `item_status = "cancelled"` (ADR-029) was only ever set *at initial entry
  time*, because there was no way to reopen an already-written order to
  change it.
- Cost basis Layer 2 (`agent_08_cost_basis.py`) asked Josh to manually type
  a "Gift card savings ($)" figure on every single cost-basis run, with no
  connection to which card was used or that card's actual purchase
  discount (`gift_cards.discount_pct`, already captured per ADR-027).

## Decision

### 1. The order's own confirm step is the gift card debit point

`agent_02_order_entry.write_order()` is the single write path both manual
entry and `capture_queue_promotion`'s PROMOTE reuse. The gift card debit now
fires there, but **only when the order is being written with
`order_status == "confirmed"`** — which today means agent_02's manual-entry
path (Josh reviews the full order before writing, same as always). A
`capture_queue_promotion` write, which always lands at `pending_review`,
does not trigger a debit — correctly, since Josh hasn't signed off on that
order's numbers yet. When a gift card amount is applied at the confirm
moment: Josh picks the specific `gift_cards` row, a `gift_card_assignments`
row is written (`card_id`, `order_id`, `amount_applied`, `applied_date`),
and `gift_cards.remaining_balance` is debited by that amount, in
`gift_card_ledger.apply_gift_card_debit()`.

### 2. Reopening a confirmed order — the actual new capability

`order_lifecycle.py` (new file) implements the transition that never
existed: `reopen_order()` takes a `confirmed` order back to
`pending_review`. It:

1. Refuses on a `settled` order (CLAUDE.md Critical Rule #4 — cost basis
   never reopens once settled) and on anything not already `confirmed`.
2. Reverses every `gift_card_assignments` row tied to the order — credits
   the amount back to `gift_cards.remaining_balance` using the `order_id`
   stored on the assignment, per DECISION 017, and deletes the assignment
   row (`gift_card_ledger.reverse_gift_card_assignments()`).
3. Sets `order_status = pending_review`.

Once reopened, `order_lifecycle.py`'s menu lets Josh mark a line item
cancelled (`item_status = cancelled`, `line_total`/`line_discount` zeroed,
same convention ADR-029 already established) or correct the gift card
amount applied, in a loop, before re-confirming.

### 3. Re-confirming closes the loop

`order_lifecycle.confirm_order()` takes a `pending_review` order back to
`confirmed`: if a gift card amount is present, it applies the same atomic
debit step as a brand-new order (`gift_card_ledger.apply_gift_card_debit()`),
then sets `order_status = confirmed`.

**This is the actual partial-cancellation flow:** retailer partially
cancels → Josh reopens the order (`agent_02_order_entry.py`, option 2, or
`python order_lifecycle.py` directly) → marks the cancelled item(s) and
corrects the gift card amount → re-confirms → the balance is right again,
because the reversal-then-reapply is the same mechanism DECISION 017 always
described. If cost basis had already been computed for the order,
`agent_08_cost_basis.py` Mode 1 already has its own overwrite guard (refuses
if any unit has left `in_stock`) — reopening does not touch inventory rows
directly; Josh re-runs Mode 1 after re-confirming and it prompts to
overwrite the existing computed units.

### 4. Scope boundary on which fields get the reopen treatment

DECISION 017 only gates fields that affect cost basis (line items, pricing,
gift card amount/card) behind confirmed → reopen → re-confirm. Fields it
calls always-editable regardless of status (`buy_reason`, `notes`,
`storage_location`, `purchase_trigger`) are not part of this build — if
those aren't actually editable post-write anywhere today, that's a small,
separate fix. `order_lifecycle.py` is not a general "edit any field" order
editor; it covers exactly what the reopen/re-confirm cycle needs.

### 5. Cost basis Layer 2 reads the ledger instead of asking

`agent_08_cost_basis.py`'s Layer 2 now calls
`gift_card_ledger.compute_gift_card_savings(order_id, client)`, which sums
`gift_card_assignments.amount_applied` for the order and multiplies each by
that card's `discount_pct` (a whole-number percent, e.g. `10.00` == 10%,
confirmed against real `gift_cards` rows) to get the actual purchase-time
savings. The computed figure is shown to Josh as the new default, with the
manual prompt still available as an override — never a silent auto-write,
since Layer 2 numbers feed directly into cost basis (CLAUDE.md Critical
Rule #9). An order with no assignment (written before this ADR, or where
the card link was skipped) falls back to the original manual prompt
unchanged.

### 6. Scope stays forward-only

This governs gift cards used on orders written or confirmed from here on,
and cards that already carry a real active balance. No retroactive rebuild
of the pre-2026-09 gift card history — consistent with ADR-027's own
"not built to reconstruct cost basis to the penny" scope decision. One card
per order is assumed for v1; if Josh ever splits a single order's payment
across two cards, `gift_card_ledger.apply_gift_card_debit()` would need a
loop rather than a single pick, but the `gift_card_assignments` table
already supports multiple rows per `order_id` with no schema change needed.

### 7. capture_queue_promotion.py's own gift-card gap is unchanged, on purpose

That file's PROMOTE flow already has a separate, more complex gift-card
question (per-tender `payment_methods` from the Chrome extension, recorded
into `order.notes` as text — its own docstring already flags this as "a
separate feature," not yet linked to any real card). This build does not
touch that flow. Since it always writes `gift_card_applied = 0` and
`order_status = "pending_review"`, nothing here fires for it today. Wiring
that path through the same ledger is a natural follow-on, now that
`order_lifecycle.confirm_order()` exists as the place it would eventually
hook into, but it's out of scope for tonight's build.

## Files touched

- `gift_card_ledger.py` (new) — `apply_gift_card_debit()`,
  `reverse_gift_card_assignments()`, `compute_gift_card_savings()`. Leaf
  module (only imports `db_client`) so it can be imported from anywhere
  without circular-import risk.
- `order_lifecycle.py` (new) — `reopen_order()`, `confirm_order()`, and the
  line-item-cancel / gift-card-amount edit helpers, wired into one guided
  CLI flow.
- `agent_02_order_entry.py` — new main-menu choice ("2. Reopen / edit /
  re-confirm an existing order"); `write_order()` now calls
  `apply_gift_card_debit()` when writing a `confirmed` order with a gift
  card amount.
- `agent_08_cost_basis.py` — Layer 2 now reads
  `gift_card_ledger.compute_gift_card_savings()` instead of only asking.

No migration was needed — `gift_card_assignments` already had the exact
shape required (`card_id`, `order_id`, `amount_applied`, `applied_date`,
`notes`), and no new columns were needed anywhere else.

## Consequences

- The order lifecycle DECISION 017 specified in June now actually exists in
  code, not just as a status column with no transitions.
- Gift card balances stay accurate through partial cancellations using the
  mechanism that was always meant to handle them — reopen, edit, re-confirm
  — rather than a parallel patch tool.
- Cost basis Layer 2 stops requiring manual gift-card re-entry per order,
  and uses real discount data instead of a guessed dollar figure.
- 2025's legacy ledger is untouched, as scoped.
- `capture_queue_promotion.py`'s own gift-card-tender gap (recorded as
  notes text, not a real link) remains open, tracked in that file's own
  docstring — a natural next step, not done here.
