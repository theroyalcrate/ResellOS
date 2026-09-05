# ADR-027 — Gift Card Discount Estimation Policy (Confidence-Tagged Cost Basis)

**Date:** 2026-09-05
**Status:** Proposed
**Supersedes:** Nothing — extends the Agent 08 Cost Basis Engine's Layer 2 (S08) without changing its math

---

## Context

The gift-card reconciliation done this session (602 pending_review LEGO orders) surfaced a gap one level deeper than expected. Knowing *which* physical gift card was used on an order (order → card linkage) is necessary but not sufficient for Layer 2 cost basis — the card's own `discount_pct` (what it actually cost relative to face value) has to be known too, and for the large majority of cards purchased through giftcards.com and krogergiftcards.com, it isn't captured anywhere yet. Only 7 of the 235 `gift_cards` rows referenced by the old Brickprobe linkage files carry a `discount_pct` today.

Separately, `brickprobe_purchases_2026-06-19.csv` — Josh's original line-item purchase ledger, predating ResellOS — already has a computed `GC Discount $` column. Cross-checked against two orders with a known 10% card discount, the ledger's figure matched exactly (T507353447: $16.20 computed vs. $162.00 × 10% = $16.20; T507298870: $17.08 vs. $170.85 × 10% = $17.085). This ledger is a reliable, zero-additional-work data source for 116 of the 445 orders needing card linkage.

**Explicit scope decision (this session, stated by Josh):** ResellOS was not built to reconstruct cost basis to the penny on every 2025 order. It's the tool for going forward. Chasing exact discount data on every historical gift card is not worth the time relative to the value it returns. An educated, clearly-flagged estimate is the right tradeoff for the historical backlog — as long as the system never pretends an estimate is a verified number.

**New exact-data sources identified:** Gift card exchange platforms — GCX, CardCookie, and "Arbitrage Card" — let Josh pull the actual dollar amount paid and the card number directly. These are exact, receipt-equivalent data, same confidence tier as a direct retailer purchase.

**krogergiftcards.com is not a single-rate source — it's a parseable exact source.** The initial working assumption (flat 10%, with 11.11% as an occasional promo) was tested against real data rather than taken on stated recollection. Josh's Kroger Gift Card Mall order confirmations land in his *personal* Gmail (`joshua.buckingham@gmail.com`), not the business inbox — a distinct account from the first-party Gmail MCP connector, reachable via the Zapier Gmail connection instead. A search of that inbox for real order-confirmation emails (subject "Your Gift Card Order is Complete!", sender `no-reply@giftcardmall.com`) returned 65 fully-parseable orders spanning March 2025–August 2026. Every one of them contains the real face value, the real amount paid (the body's final `TOTAL:` line — not the header `ORDER TOTAL`, which is the pre-discount subtotal), and therefore an exact per-order discount_pct. Empirically:

| discount_pct | Order count | Share |
|---|---|---|
| 11.11% | 44 | 67.7% |
| 13.04% | 5 | 7.7% |
| 13.33% | 4 | 6.2% |
| 20.00% | 3 | 4.6% |
| 15.00% | 3 | 4.6% |
| 17.14% | 2 | 3.1% |
| 0.00% | 2 | 3.1% |
| 10.00% | 1 | 1.5% |
| 5.62% | 1 | 1.5% |
| **Total** | **65** | |

This confirms 11.11% as the dominant rate but rules out treating it, or any single number, as a safe blanket default — real per-order data is available and parseable for this source, so it should be used as `exact`, not estimated. (The 0.00% orders are worth a second look — likely a non-discounted reload, a promo code that didn't apply, or a different transaction type entirely, rather than a genuine zero-discount gift card purchase; flag for spot-check before import, not a blocker for this ADR.)

**Multi-retailer basket complication (open, not yet resolved):** Some Kroger orders bundle a LEGO gift card together with other retailers' cards (Barnes & Noble, Kohl's, Target, Lowe's, Bath & Body Works, One4All) under one order-level discount. For those, the order confirmation gives an exact *order-level* discount but not a clean per-card split. No apportionment method has been designed yet — see Open Questions below.

**Discrepancy flagged, not yet resolved:** Josh recalled 9 July-2025 orders at the "pay $200 get $225" (11.11%) structure; the 65-order pull contains no July-2025 dates at all. Possible causes: a result cap on the Zapier/Gmail search, a subject-line variant not covered by the query, or a different account/alias. Flagged to Josh; not folded into the importer design until resolved.

**Known default rate for giftcards.com (unchanged, still holds):** giftcards.com purchases without an exact record are believed to be predominantly 10% discount. Three specific giftcards.com purchases used 10% Capital One Shopping cashback instead of a straight discount (distinct from the 1.5% generic credit-card cashback already tracked as `cashback_expected` on 37 existing `gift_cards` rows — a different mechanism at a different rate). Unlike Kroger, no bulk real-email parse has been run yet for giftcards.com, so its 10% figure remains a *default*, not an empirical distribution — it should get the same email-parsing treatment as Kroger when time allows, but isn't blocking this ADR.

## Decision

### 1. Confidence tier replaces "known vs. unknown"

Every `gift_cards` row gets a confidence tier on its discount data, not a binary known/unknown:

- **`exact`** — discount_pct (or purchase_price/face_value) came from a receipt, invoice, order-confirmation email, or an exchange platform's transaction record (GCX, CardCookie, Arbitrage Card, direct retailer purchase, Kroger Gift Card Mall order-confirmation email, or Josh's own ledger).
- **`estimated_default`** — no exact record exists; a source-based default rate was applied.
- **`unknown`** — no exact record and no applicable default exists yet (rare going forward; expected to shrink to near-zero as new purchases flow through exact sources).

New column: `gift_cards.discount_confidence` (`exact` | `estimated_default` | `unknown`). Reports that roll up cost basis (P&L, ROI) can filter or visually flag `estimated_default` rows rather than presenting them with the same authority as `exact` ones — consistent with the system's existing philosophy of never silently guessing (DECISION 017, ADR-023, ADR-024).

### 2. krogergiftcards.com is an exact, parseable source — not a default rate

Reverses the original draft of this ADR. `krogergiftcards.com` cards are **not** assigned a flat default discount. Instead:

- The Kroger Gift Card Mall order-confirmation email (subject "Your Gift Card Order is Complete!", from `no-reply@giftcardmall.com`, landing in Josh's personal Gmail and reachable via the Zapier Gmail connection) is treated as a receipt-equivalent document. Its face value and real `TOTAL:` charged amount yield an exact per-order discount_pct, imported at `discount_confidence = 'exact'`.
- **11.11% is retained only as a last-resort estimate** — used solely when a specific card/order cannot be matched to any confirmation email (e.g. email deleted, search gap, pre-dates the account). That fallback always sets `discount_confidence = 'estimated_default'`, clearly distinguished from the 68% of orders where the real rate is known exactly.
- Multi-retailer basket orders (LEGO bundled with other retailers' cards under one order-level discount) import the order-level discount as `exact` at the order level; per-card apportionment within that order is an open question (see below) and should not block importing what's known.

### 3. Source-based default discount table (giftcards.com only, for now)

Used only when no exact record is available and no email-parsing pipeline has been built yet for that source:

| `source_platform` | Default `discount_pct` | Notes |
|---|---|---|
| `giftcards.com` | 10.00 | Believed common rate; 3 known exceptions use 10% Capital One Shopping cashback instead — those get modeled as `cashback_expected`, not `discount_pct`, when identified. Not yet empirically verified against real order emails the way Kroger was — candidate for the same treatment as Section 2 in a future session. |

`krogergiftcards.com` is intentionally absent from this table as of this revision — see Section 2. Any card later confirmed via a real receipt gets corrected individually, and using this table always sets `discount_confidence = 'estimated_default'`, never `exact`.

### 4. Historical brickprobe_purchases_2026-06-19.csv ledger import

The ledger's `GC Discount $` figure, summed per order, is treated as `exact` (validated against two known-rate orders, exact match both times) and imported as an order-level override that supersedes any per-card discount calculation for that specific order — it's a direct receipt-equivalent figure, not a rate applied to an unknown card. Covers 116 of today's 445-order gap immediately, no web lookups.

### 5. New exact-source platforms

`gift_cards.source_platform` gains three new recognized values: `gcx`, `cardcookie`, `arbitrage_card`. Cards entered from these sources always carry `discount_confidence = 'exact'` since the exchange's transaction record supplies the real purchase price directly — same tier as a direct retailer purchase or Josh's own ledger.

### 6. Historical vs. going-forward posture, made explicit

This ADR formally establishes what was previously implicit: cost basis on 2025 orders is allowed to carry `estimated_default` confidence where exact data isn't practically recoverable. Cost basis on orders from this point forward should trend toward `exact` as GCX/CardCookie/Arbitrage Card purchases, Kroger email parsing, and the ledger-based import become the normal path, not the exception. This does not relax anything about the cost-basis-locking rules already in place (DECISION 017, GWP Philosophy C) — a locked/settled order's cost basis still only ever changes through a P&L adjustment, never a silent reopen. It only changes how confidently Layer 2's *input* is labeled before that lock happens.

## Open Questions

1. **Multi-retailer basket apportionment.** When a single Kroger order's discount covers a LEGO card plus other retailers' cards, how should the order-level discount be split across cards? Candidates: pro-rata by face value, pro-rata by amount paid, or flag as `exact` at the order level only and leave per-card apportionment as `unknown` until a better method is designed. Not resolved in this ADR.
2. **July-2025 "9 orders" discrepancy.** Josh recalled 9 July-2025 Kroger orders at the 11.11% structure; the 65-order email pull contains none. Needs Josh's input — different account/alias, a search that missed them, or a misremembered date — before the importer is built against the full historical set.
3. **giftcards.com email-parsing pass.** Not yet attempted. Should get the same treatment as Section 2 once time allows, rather than remaining on a flat 10% default indefinitely.

## Implementation note (2026-09-05)

Migration applied to `gift_cards`: added `discount_confidence text CHECK (IN ('exact','estimated_default','unknown'))`, backfilled against the 235 existing rows. Backfill surfaced a finding worth flagging: all 55 existing `giftcards.com` rows carry an identical `discount_pct = 10.00` — a uniform value across every row is a strong signal this was a previously-applied default rather than 55 individually-verified receipts (compare to Kroger's real emails, which produced 9 different rates across 65 orders). Backfilled those 55 as `estimated_default`, not `exact`, pending the same email-verification pass recommended for giftcards.com in Open Question 3. The other 180 rows (direct-retailer purchases, `source = 'direct'` or a null source with real recorded `purchase_price`/`face_value`) backfilled as `exact`; 4 of those had a null `discount_pct` despite having both dollar figures on the row, so it was computed and filled in rather than left blank, since it's directly derivable from data already present. Result: 180 `exact` / 55 `estimated_default` / 0 `unknown` on the pre-existing table. No new rows were touched — this covers only what was already in `gift_cards` before today's reconciliation work; the 445-order Brickprobe gap is a separate, not-yet-imported population.

`source_platform` and `source_type` were confirmed to have no DB-level CHECK constraint (plain text columns), so the new `gcx`/`cardcookie`/`arbitrage_card` values from Section 5 need no schema change — only a naming convention going forward. Also confirmed: `krogergiftcards.com` does not appear anywhere in the existing 235 `gift_cards` rows today (`source_platform` is null on all of them; the only populated `source` values are `'direct'` and `'giftcards.com'`) — Kroger cards live only in the Brickprobe CSVs so far and haven't been imported into Supabase yet, which is exactly the work this ADR and the lookup tool build feed into.

## Consequences

- New column: `gift_cards.discount_confidence` (migration required) — **done**, see Implementation note above.
- New `source_platform` values: `gcx`, `cardcookie`, `arbitrage_card`.
- Cost basis reports gain the ability to show "how much of this P&L is estimated vs. verified" — directly useful for the CPA conversation (June 10 meeting questions) since it quantifies precision rather than asserting it.
- Removes the false choice between "chase every 2025 receipt" and "leave Layer 2 blank" — the system can carry a labeled, defensible estimate instead.
- Does not change any cost-basis math already implemented — purely an input-confidence and default-value layer on top of the existing five-layer engine.
- Establishes email-parsing (via the Zapier Gmail connection to Josh's personal inbox) as a legitimate `exact` data-collection method alongside receipts and exchange-platform records, not just a one-off for this session.

## Related decisions

- Agent 08 Cost Basis Engine (S08) — Layer 2, unchanged
- DECISION 017 — Order Edit Lifecycle & Cost Basis Trigger Gate (locking rules unaffected)
- ADR-023 — Capture Queue Promotion and Extension Primacy (never silently guess; flag instead — same principle applied here to confidence tiers)
- ADR-024 — WFS Phantom Inventory Credit Handling (precedent for "flag and estimate rather than block or corrupt" under missing data)
- CONTEXT.md — "Own your data, rent enrichment" design principle
