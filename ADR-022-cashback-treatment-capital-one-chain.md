# ADR-022 — Cashback Tax Treatment + Capital One Chain

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-26 |
| **Decided by** | Josh Buckingham |
| **CPA status** | Confirmed 2026-06-10: personal-preference choice; CPA will accommodate either treatment |

---

## Decision

### Part 1 — Cashback Layer 4 is ACTIVE

Cashback earnings (Rakuten, RetailMeNot, Microsoft Shopping, Honey, TopCashback) are treated as **cost reductions** (rebate treatment), not income. Layer 4 of the cost basis engine is activated. When a cashback payout is received and confirmed, it is allocated back to the originating orders proportionally and reduces their `net_economic_cost`.

### Part 2 — Capital One Shopping: Rebate Chain Ends at Gift Card Acquisition

Capital One Shopping cashback can only be redeemed as gift cards (not cash). The rebate treatment **ends at the point of gift card acquisition**. The gift card is recorded in `gift_cards` with `price_paid = $0` (since C1 covered the full cost). Layer 2 of the cost basis engine then applies the full face value as a gift card discount on any order paid with that card. No further chain-following is required or correct.

---

## Context

### Why Layer 4 is Active

Cashback is economic consideration received in exchange for purchasing through a specific portal. It reduces the true economic cost of the inventory — the same way a rebate check reduces what you actually paid. Recording it as income would overstate both revenue and COGS. Rebate treatment (cost reduction) is cleaner, more accurate, and what the system was designed to support.

### Why the Capital One Chain Ends at the Gift Card

The alternative — following the chain all the way through to inventory cost basis via Layer 4 — would require:
1. Matching a C1 cashback earning event to specific gift card purchases
2. Matching those gift cards to specific orders
3. Matching those orders to specific inventory units
4. Feeding the C1 earnings back into those units' cost basis

This chain can span 12-18+ months. At each link there's potential for ambiguity, error, and drift. The complexity is not worth the marginal accuracy gain — especially since the effective result is identical: a gift card purchased with C1 earnings has zero out-of-pocket cost, and Layer 2 already captures that via `price_paid = $0`.

**The chain does feed through — just implicitly, through the gift card's price, which is the right level of abstraction.**

---

## Implementation Requirements

### cashback_transactions Status: `redeemed_as_gc`

A new status value is needed on `cashback_transactions` to prevent double-counting:

| Status | Meaning | Layer 4 behavior |
|--------|---------|-----------------|
| `pending` | Earned, not yet paid out | Skip |
| `confirmed` | Cash payout received | Include in Layer 4 allocation |
| `redeemed_as_gc` | Redeemed as gift card (C1 Shopping only today) | Skip — Layer 2 handles it via the GC's `price_paid` |
| `written_off` | Not collectible | Skip |
| `ineligible` | Disqualified | Skip |

### agent_07 Mode 2 (Payout Received) — New Branch Required

When recording a C1 Shopping payout, the agent must ask:
> "Was this payout received as cash or as a gift card?"

**If cash:** mark `cashback_transactions.status = 'confirmed'`. Layer 4 allocates it normally.

**If gift card (C1 Shopping only):**
1. Mark `cashback_transactions.status = 'redeemed_as_gc'`
2. Create a new row in `gift_cards`:
   - `retailer` = the retailer the GC is for (e.g., `macys`)
   - `face_value` = gift card face value
   - `price_paid` = $0.00
   - `discount_pct` = 100.0
   - `source` = `'capital_one_shopping'`
   - `source_type` = `'cashback_redemption'`
3. Do NOT trigger Layer 4 allocation for this cashback row

### No Double-Counting Guard

Layer 4 must filter out `redeemed_as_gc` rows. The existing filter in `agent_08_cost_basis.py`'s cashback allocation logic (which already skips `written_off` and `ineligible`) should add `redeemed_as_gc` to the skip list.

---

## What Changes in the Codebase

| File | Change |
|------|--------|
| `agent_07_cashback.py` | Mode 2 adds cash/GC branch for C1 payout; GC path creates `gift_cards` row at $0 and sets `redeemed_as_gc` status |
| `agent_08_cost_basis.py` | Layer 4 cashback filter adds `redeemed_as_gc` to skip conditions |
| `migrations/` | May need a migration to add `redeemed_as_gc` as a recognized status if a check constraint exists on `cashback_transactions.status` |

---

## What Does NOT Change

- Layer 4 is active and correct for all other platforms (Rakuten, RetailMeNot, Microsoft Shopping, Honey, TopCashback)
- Credit card rewards (e.g., future Amazon Prime Visa 5%) are separate from portal cashback — they remain outside the cost basis engine until a specific decision is made about them
- GCs from other sources (giftcards.com, retailer purchase) continue to use their actual `price_paid`

---

## Consequences

- Every confirmed Rakuten/RMN/etc. payout reduces originating order cost basis through Layer 4
- C1 Shopping redemptions show up as $0-cost gift cards — orders paid with those cards get the full face value as a Layer 2 discount
- Both paths produce the same economic result; they just arrive there through different layers
- Audit trail: `cashback_transactions.status = 'redeemed_as_gc'` + `gift_cards.source = 'capital_one_shopping'` tells the full story without any chain-following

---

## Related Decisions

- ADR-019: Order Settlement Gate
- ADR-021: FIFO Costing Method (companion decision, same date)
- DECISION 017: Order Edit Lifecycle & Cost Basis Trigger Gate
