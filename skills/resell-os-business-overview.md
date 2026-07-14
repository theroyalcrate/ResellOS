---
name: resell-os-business-overview
description: >
  Displays a plain-English summary of how the ResellOS reselling business works —
  the business model, the lifecycle from deal to sale, the "stacking" strategy that
  makes it profitable, and a glossary of recurring terms (cost basis, GWP, retiring,
  WFS, FIFO, ROI). Use whenever the user says "how does the business work", "business
  overview", "explain the business", "summary of how this works", "what do you do",
  or any single-command request for the big picture — especially useful for a family
  member or new collaborator who knows Josh resells LEGO but not the details. Read-only:
  this skill displays the summary, it does not write or update anything.
---

# ResellOS Business Overview

Display the content below directly to the user (in chat, not as a file write). It is a
condensed version of the vault's entry-point note at
`C:\ResellOS-Knowledge\ResellOS-Knowledge\Welcome.md`. If the user wants more depth —
retailer-specific mechanics, the order-matching logic, vault navigation — point them to
that file and to `Areas/retailers/lego.md` as the next read.

---

## The business in one paragraph

Josh buys LEGO sets (mostly online, mostly LEGO.com) using a combination of sales, gift
cards, loyalty points, "gift with purchase" promos, and cashback portals — all stacked
together so the *real* cost of each set is much lower than the sticker price. Every
purchase is recorded in ResellOS (the database/software side of the project), sets are
held for a while (some go up in value as they're discontinued — "retire"), and then
shipped to Walmart's fulfillment service (WFS), where they sell on Walmart Marketplace.
ResellOS tracks the true cost of every item so Josh always knows the real profit, not
just the obvious one.

**Buy smart, track precisely, sell patiently, know your real numbers.**

## The lifecycle — start to finish

1. **Find a deal** — a sale, a promo (gift-with-purchase, bonus points), or a stacking
   opportunity. Some buys are planned (a specific set), some opportunistic (a good price
   found him).
2. **Buy it** — often paid for with a mix of gift cards, store credit, and loyalty
   points redeemed from past purchases.
3. **Record it in ResellOS** — what was actually paid, rewards earned vs. redeemed, and
   any free items (GWP — "gift with purchase").
4. **ResellOS calculates the real cost** — the "cost basis" (see Vocabulary). Almost
   always lower than the receipt price.
5. **Hold the inventory** — many sets are worth more after LEGO retires them. Some sell
   fast, some sit for months.
6. **Ship to Walmart (WFS)** — Walmart stores, packs, and ships to the end customer.
7. **It sells** — Walmart takes a commission + fulfillment fee; the rest comes back as
   proceeds.
8. **Reconcile** — ResellOS compares proceeds against true cost basis for actual profit,
   and feeds year-end tax reporting.

## Why this is actually profitable — "stacking"

The sticker price is almost never what Josh pays. Several of these often apply to the
**same order**:

- A sale or clearance price on the set itself
- Gift cards bought at a discount (cashback portal or promo)
- Loyalty points/rewards redeemed from previous purchases (LEGO Insider points, Kohl's
  Cash, Macy's Star Money, etc.)
- A free bonus item (GWP) once the order crosses a spend threshold — sometimes more than
  one per order
- Cashback from a shopping portal (Rakuten, Capital One Shopping, etc.) on top of
  everything else

Each retailer has its own version of this; the per-retailer mechanics live in
`Areas/retailers/` in the vault. LEGO.com is the primary channel and has the most detail
filled in.

## Vocabulary

- **Cost basis** — the *real* cost of an item after every discount, gift card, redeemed
  reward, and GWP adjustment. This is the number that matters for profit, not the
  receipt price.
- **GWP (Gift With Purchase)** — a free item from crossing a spend threshold. Recorded
  at $0 cost. If it later sells, the proceeds lower the cost of the *original* order.
- **Retiring / retirement** — LEGO discontinues sets on a schedule. Retiring or
  recently-retired sets often go up in resale value — timing matters.
- **Rewards earned vs. redeemed** — earning points on a purchase doesn't change that
  purchase's cost. *Redeeming* points on a purchase lowers that purchase's cost.
- **WFS (Walmart Fulfillment Services)** — Walmart's version of Amazon FBA. Josh ships
  inventory to Walmart; Walmart stores, ships, and takes a cut.
- **FIFO (First In, First Out)** — the oldest unit's cost is used first when multiple
  units of the same set were bought at different times/prices.
- **ROI** — profit divided by true cost basis, not sticker price.

---

## Where to go next

- **`C:\ResellOS-Knowledge\ResellOS-Knowledge\Welcome.md`** — the full vault entry
  point, with navigation, reading order, and a roadmap of what's coming.
- **`Areas/retailers/lego.md`** — the most fully-documented retailer note (reward math,
  tax behavior, GWP handling).
- **`Areas/business-logic/email-order-matching.md`** — how incoming order emails get
  matched without creating duplicates.

The vault is the "why and how" layer. Actual transaction records, inventory, and
financial calculations live in ResellOS itself (Supabase + Python agents) — not in this
summary.
