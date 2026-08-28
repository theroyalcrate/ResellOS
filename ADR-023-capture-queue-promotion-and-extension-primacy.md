# ADR-023 — Capture Queue Promotion Workflow + Chrome Extension Primacy

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-18 |
| **Decided by** | Josh Buckingham |

---

## Decision

### Part 1 — Chrome extension becomes the primary order-capture method, going forward, for retailers it supports

Once built for a given retailer, new orders are captured live at the point of purchase via a browser content script — not reconstructed after the fact from an email or PDF.

### Part 2 — Agent 1A/1B (PDF/email parsing) become the backstop, not the primary path

They continue to run exactly as built. Their job going forward is catching anything the extension didn't capture: retailers the extension doesn't cover yet, a capture that failed, or historical orders that predate the extension entirely. This is a role change, not a rebuild — no existing Agent 1A/1B code changes because of this decision.

### Part 3 — This supersedes the 2026-07-18 manual-entry-first decision

That decision paused agent-created orders because "set numbers, gift card linkage, and reward detail are unreliable or absent from confirmation/receipt emails." The 2026-08-17 Tier 2 matching work (see SESSION_LOG.md) proved PDF extraction is reliable — 86% of a 1,032-message backlog yielded a clean order number. The stated blocker is resolved. The manual-entry-first row in CONTEXT.md's Architecture Decisions table has been updated to point here rather than deleted.

### Part 4 — `capture_queue` is the single landing zone for every non-manual capture path

Both the Chrome extension and the new PDF-based backfill agent (Agent 1D, built later per this ADR) write into the same table, using the same shape (below), reviewed through the same promote-to-order workflow. There is one review gate, not two.

---

## capture_queue — verified live 2026-08-18

Confirmed directly via Supabase (not assumed): the table exists, 0 rows, and the column list matches `migrations/019_capture_queue.sql` exactly —

`capture_id` (uuid, PK) | `user_id` (uuid) | `retailer` (text) | `source_url` (text, nullable) | `captured_at` (timestamptz) | `raw_data` (jsonb) | `order_number` (text, nullable) | `order_date` (date, nullable) | `total` (numeric, nullable) | `status` (text, default `'pending'`) | `promoted_order_id` (uuid, nullable) | `reviewed_at` (timestamptz, nullable) | `review_note` (text, nullable) | `created_at` (timestamptz)

**Status vocabulary note:** the migration's `CHECK` constraint allows exactly `'pending' | 'promoted' | 'discarded'`. An earlier draft of this ADR used `'rejected'` for the reject path — corrected here to `'discarded'` to match the live constraint (0 rows in the table today, so this was a documentation fix, not a schema change).

---

## raw_data contract — NEW, defined by this ADR

Every writer into `capture_queue` (extension content scripts, Agent 1D) must shape `raw_data` as:

```json
{
  "source": "chrome_extension" | "agent_1d_pdf_backfill",
  "capture_stage": "checkout" | "shipped",
  "retailer": "lego" | "kohls" | "walmart" | "walmart_business" | "macys",
  "order_number": "string",
  "order_date": "YYYY-MM-DD",
  "line_items": [
    {
      "set_number": "string | null",
      "description": "string",
      "quantity": "int",
      "unit_price": "number",
      "net_price": "number",
      "is_gwp": "bool",
      "list_price": "number | null (checkout stage only, added 2026-08-26 -- pre-sale price when unit_price reflects a Sale Price line)",
      "points_earned": "number | null (checkout stage only -- TOTAL Insiders points for this line, quantity-adjusted; fixed 2026-08-28, see below)",
      "points_per_unit": "number | null (checkout stage only, added 2026-08-28 -- the raw per-unit rate LEGO's page actually shows)"
    }
  ],
  "subtotal": "number | null",
  "tax": "number | null",
  "total": "number",
  "balance_due": "number | null",
  "rewards_earned": "number | null",
  "gift_card_last4": "string | null",
  "payment_methods": [
    {
      "type": "gift_card | card | unknown",
      "last4": "string (gift_card, card; shipped stage)",
      "brand": "string (card only)",
      "raw": "string (unknown only)",
      "amount": "number (checkout stage only)",
      "inferred": "bool (checkout stage only, added 2026-08-26 -- true when computed from balance_due rather than read directly off the page)"
    }
  ],
  "shipments": [
    {
      "tracking_number": "string",
      "status": "string | null",
      "set_numbers": ["string"]
    }
  ]
}
```

**`shipments` — added 2026-08-27**, verified live against T513203884 (one shipment,
5 items) and T513202830 (two shipments -- one with an item + a GWP, the other with
a lone GWP). Extracted from the order-detail page's "Order overview" section, which
repeats a `{status}\nTracking number: {value}\n...items...` block once per shipment.
`set_numbers` is the list of `Item:` values found between this shipment's tracking
line and the next (or end of page) -- used at promotion time to create one `shipments`
row per tracking number and set each matching `line_items.shipment_id`, instead of the
single blank placeholder shipment promotion wrote before this. Empty list when the
order hasn't shipped yet (no "Tracking number:" text present) -- promotion falls back
to the old single-blank-placeholder behavior in that case, so nothing regresses for
orders captured pre-shipment.

`payment_methods[].last4` on a `"checkout"` capture — **added 2026-08-26.** Confirmed live on T513381170: a card tender's last4 (e.g. "3013") is readable directly from a "Payment Method" heading near the top of the confirmation page, separate from the itemized "Order Summary" gift-card deduction lines -- so a checkout-stage card entry now carries `last4` even though its `amount` is still derived from `balance_due` (see below) rather than an itemized line. Gift card entries at this stage still have no `last4` -- LEGO never shows the per-gift-card split anywhere.

`line_items[].points_earned` quantity fix — **fixed 2026-08-28.** Confirmed live on T513265219 (Sonic: Speedster Lightning, Qty: 2): LEGO's "Insiders Points on this order: {n}" label is PER UNIT, not per line -- the page showed "65" for a 2-unit line, and the order-level "You will earn 682 points" total only reconciled as 390 + 162 + 65*2 + 0, not with 65 counted once. `points_earned` in `raw_data` is now the quantity-adjusted total for the line (previously the raw per-unit number, silently undercounting on any Qty > 1 item); the raw per-unit rate is kept separately as `points_per_unit`. `order_confirmation.js` also now sanity-checks that `sum(line_items[].points_earned) == rewards_earned` (the page's own order-level total) and warns on the console if they disagree, to catch the next surprise like this one before it ships bad data. Note: this bug never affected any promoted order's `insider_points_earned` -- `capture_queue_promotion.py` has only ever used the order-level `rewards_earned` field for that, never summed from line items -- it only affected the accuracy of the informational per-line `points_earned` value inside `raw_data`.

`line_items[].unit_price` sale-price fix — **fixed 2026-08-26.** Confirmed live on T513381170 (Mirabel Key Chain): an item on sale renders both "Price $5.99" (list) and "Sale Price $3.59" (what's actually charged) in the same block; `order_confirmation.js` was always grabbing the first dollar amount after "Price", silently overstating `unit_price` to the list price on any sale item (subtotal only reconciled once `unit_price` used the sale price). Now prefers "Sale Price" when present. The list price is kept separately as `list_price`.

`total` / `balance_due` — **fixed 2026-08-26.** `total` is now always computed as `subtotal + tax` (the order's real economic value), never read directly off the page. Before this fix, `order_confirmation.js` wrote whatever LEGO's page labels "Order Total" straight into `total` -- but that field is actually the *remaining balance still to be charged to a card*, which reads `$0.00` on any order paid off entirely by gift card (caught live on T513380643: subtotal $102.96 + tax $11.02 = $113.98, fully covered by two gift card deductions, `total` had been landing as `0`). That raw LEGO value is kept separately as `balance_due` -- normally `0` once `payment_methods` fully covers `total`. When `balance_due` is still positive after itemized gift-card deductions, the extension infers a card must have covered the rest (LEGO doesn't itemize card charges as a deduction line the way it does gift cards) and adds a synthetic `payment_methods` entry for that amount with `inferred: true`, flagged in `capture_queue_promotion.py`'s review prompt so Josh checks it against the card statement before confirming. Confirmed live 2026-08-26 on T513381170 (a real card-paid order, card ...3013): subtotal $103.58 + tax $11.08 = $114.66, one $114.00 gift card, "Order Total"/`balance_due` $0.66 -- exactly the amount charged to the card. Also confirmed on that order: the card's last4 IS readable directly (see `payment_methods[].last4` below), even though the dollar amount still isn't an itemized line and stays `inferred: true`. `content.js` (shipped stage) is unaffected -- it never wrote a `total` from this buggy field.

`gift_card_last4` — **deprecated 2026-08-27, kept for backward compat only.** Derived as the first gift card found in `payment_methods` below; the extension may fill this when visible on the order-detail page (confirmed present on LEGO's page per recon); Agent 1D leaves this null always — PDFs never print it.

`payment_methods` — **added 2026-08-27**, verified live against three real orders, all multi-gift-card (T513203884: one card; T513207318 and T513202830: two cards each). Replaces `gift_card_last4` as the authoritative field: an order can carry several gift cards plus a credit card (Josh: "there are some orders that have 3 gift cards listed and a credit card"), and the order-details page never shows the dollar split across them, so `capture_queue_promotion.py` prompts Josh per tender at review time when only a `last4` is known. Branded-card detection (`type: "card"`) is written from an earlier confirmed format ("VISA ••••3013") but not verified live this session — none of the three test orders paid with a card.

`capture_stage` — **added 2026-08-27**, distinguishes which page a capture came from, since the two pages expose different, complementary data and neither alone is complete:

- **`"checkout"`** — `order_confirmation.js`, the `lego.com/.../page/static/order-confirmation/{orderNumber}` page shown right after purchase. Verified live against T513379536. Has Insiders points per line item and in total (`rewards_earned` is a real number here, not always null), and payment tenders as itemized dollar amounts (`payment_methods[].amount`, no `last4` — the confirmation page never shows card identity). GWP items on this page are name-only (no set number). `shipments` is always `[]` (order hasn't shipped yet). Not confirmed live: whether this URL stays reachable for an order from an earlier session, or how a second tender type (e.g. a branded card) renders here.
- **`"shipped"`** — `content.js`, the order-details page, unchanged from the description above. Has tracking numbers and card `last4`s, never amounts.
- Legacy captures written before this field existed have no `capture_stage` key; `capture_queue_promotion.py` treats a missing value as `"shipped"` (the only path that existed before 2026-08-27).

**Promotion behavior:** a `"checkout"` capture for a new order number promotes normally (creates the order — this is now the primary create path when both stages are used, since it has the real Insiders points). A `"shipped"` capture for an order number that's *already* promoted is merged into the existing order (tracking + payment identity notes only, via `_merge_shipped_capture` in `capture_queue_promotion.py`) instead of creating a duplicate order. A `"checkout"` capture for an order number that's already promoted is flagged as a likely duplicate and offered for discard.

Writers also populate the top-level `order_number` / `order_date` / `total` columns (not just inside `raw_data`) so the review list can be queried without parsing JSON.

This mirrors DECISION 017's existing field split (agents/extension fill order data; Josh fills `gift_card_last4` [when the extension didn't already capture it], `buy_reason`, `purchase_trigger`, `cashback_rate`) — this ADR does not change that split, it defines the wire format that carries it.

---

## Implementation Requirements

1. **Promote-to-order workflow** (next session) — reads a pending `capture_queue` row, shows it to Josh, collects the Josh-only fields, writes a real order via the same creation path `agent_02` already uses, sets `capture_queue.status = 'promoted'` + `promoted_order_id`. Reject path sets `status = 'discarded'` with a `review_note`.
2. **Chrome extension** (later session) — Supabase client + login + LEGO.com content script first, writing `raw_data` in the shape above.
3. **Agent 1D** (later session) — reuses Agent 1A's `parse_invoice()`, writes into `capture_queue` in the same shape, `source = 'agent_1d_pdf_backfill'`, for the ~876-order historical backlog found 2026-08-17. Built last, once the promote workflow already exists and is proven on real extension data.

---

## What Does NOT Change

- Agent 1B's Tier 1/Tier 2 matching cascade — unchanged, still the backstop filing path for invoices tied to orders already in the system
- Cost basis gating (DECISION 017) — a promoted order still starts at whatever status DECISION 017 already defines; cost basis still never runs before `confirmed`
- Agent 02 manual entry — remains the true fallback for any retailer the extension never covers

---

## Consequences

- The ~876-order LEGO backlog found 2026-08-17, and the ~1,000-file personal Drive backlog found 2026-08-15, are very likely the same underlying gap viewed from two angles (invoice emails vs. Drive files) — worth checking overlap before building Agent 1D, not assuming they're separate
- Kohl's variable-earn (S10) is effectively solved once the extension covers Kohl's — Kohl's Rewards Activity ledger gives exact figures directly, no separate schema-guessing session needed
- The other retailers without extension coverage (Barnes, Target, Best Buy, Amazon) stay manual-entry-only until the extension expands to them

---

## Related Decisions

- DECISION 017: Order Edit Lifecycle & Cost Basis Trigger Gate (field split this ADR reuses)
- Supersedes: Manual-entry-first order architecture (2026-07-18)
