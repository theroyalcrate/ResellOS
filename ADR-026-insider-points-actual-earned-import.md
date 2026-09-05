# ADR-026 — LEGO Insider Points: Actual-Earned Import (Weekly Reconciliation)

**Date:** 2026-09-04
**Status:** Accepted
**Supersedes:** Nothing — replaces the authoritative source for LEGO Insider points-earned data; does not change cost basis treatment of points

---

## Context

LEGO Insider points earned per order are currently computed at order-entry time in Agent 02 using a multiplier formula (6.5 pts × spend × multiplier, per the retailer rewards table). This requires knowing which multiplier event (2X, 4X, etc.) applied to a given order at the moment of entry — often ambiguous, easy to get wrong, and dependent on the user remembering or looking up which promotion was live.

LEGO's own Insider portal (lego.com profile) maintains an authoritative, exportable history of points actually earned per order. This export can be reviewed and pulled on a recurring basis — weekly is sufficient, per how often meaningful new activity accumulates.

The `rewards_transactions` table already exists in the schema (0 rows, previously unused) with a shape that fits this need directly: `points_amount`, `dollar_value`, `order_id`, `promotion_type`, `multiplier`, `transaction_date`, `retailer`, `program_name`. It was designed for exactly this purpose but has never had an import path feeding it.

**Explicit scope boundary:** this ADR is about rewards-pool balance accuracy only. Per the existing earned-vs-redeemed rule, points earned never affect cost basis — only points *redeemed* on a future order do (Layer 3 of Agent 08). Nothing here changes cost basis math; it only makes the earned-points side of the ledger trustworthy instead of estimated.

## Decision

### Source of truth shifts to LEGO's own export

Actual points earned per order is sourced from a weekly LEGO Insider transaction export, not from Agent 02's at-entry-time multiplier calculation. The export is the record; the multiplier formula becomes a same-day estimate only.

### New import agent

A new agent parses the weekly export and writes to `rewards_transactions`, matching each earned-points transaction to an `order_id` using a strength-ordered cascade (same philosophy as ADR-023):

1. **Order number**, if present in the export — deterministic, write directly.
2. **Date + dollar amount** against `orders` where `retailer = 'LEGO'`, as a fallback — probabilistic, resolved via review, never auto-committed on amount alone if more than one candidate matches.

### Reconciling against Agent 02's estimate

When the imported actual value disagrees with Agent 02's at-entry estimate (e.g., the wrong multiplier was assumed at entry), the imported value wins and overwrites the estimate. The discrepancy is logged, not silently dropped — this is useful specifically for catching cases where a 2X/4X event was misjudged at entry time.

### Cadence

Weekly, matching the export's own natural update frequency. No need for real-time sync.

### Out of scope

This is scoped to LEGO Insider only — the retailer with a reliable individual export available today. Other retailers' rewards programs (Kohl's Rewards Cash, Macy's Star Money, etc.) are unaffected and continue on their existing tracking approach.

## Consequences

- `rewards_transactions` begins being populated for the first time.
- Agent 02's multiplier logic remains in place for same-day feedback at entry but is explicitly demoted to a provisional estimate once this is implemented — needs a way to distinguish an entry-time estimate from an import-confirmed value (e.g. a `source` field on the row, or logging the pre-import value in `notes` when overwritten).
- Removes the main pain point around 2X/4X multiplier events: the rewards pool balance for LEGO becomes a verified number instead of an assumed one.
- Order-matching for the import needs its own small cascade — mirrors ADR-023's matching philosophy rather than inventing a new one.

## Related decisions

- Agent 02 — retailer rewards design (multiplier-based entry-time estimate, now demoted to provisional)
- ADR-023 — Capture Queue Promotion and Extension Primacy (matching-cascade philosophy reused here)
- ADR-025 — Pre-Shipment Estimated Cost Basis Calculator (confirms points never need to be guessed there)
- CONTEXT.md — "Rewards earned vs redeemed" rule

---

## Addendum — 2026-09-05, live verification of the Insider portal export

Checked live (lego.com/en-us/insiders/account) while working the 220-order lookup queue. Findings that affect the assumptions above:

- **"Points Earned" tab has no order number and no dollar amount** — each row is just `Date | Activity ("LEGO Purchase" / "Bonus Points" / "Rewards Redeemed") | Points`, e.g. `08/28/2026 | LEGO Purchase | +682`. Clicking a row does not expand any further detail. This directly undercuts Decision § "New import agent," option 1 (order number "if present in the export" — it is not present in this view) and weakens option 2 (date + dollar amount fallback — no dollar amount is shown here either, only points; matching would have to go on date + points value alone, which is far more collision-prone across a day with multiple orders).
- **"Purchases Made" tab returned a bare "Error"** on the live site during this check — this may be the actual order-level export ADR-026 was written assuming exists (it's the more likely candidate, given the tab name), but it wasn't reachable to confirm. Needs a retry — possibly transient, possibly needs to be checked from Josh's own logged-in session rather than through this session's browser automation.
- No CSV/export download control was found anywhere on this page — "export" in the original context may have meant "this on-screen history," not a literal downloadable file. Worth confirming intent before building the weekly import agent.

**Net effect:** the import agent this ADR calls for cannot be built against the "Points Earned" tab as observed — it lacks the join key needed for either matching option. Before writing that agent, either (a) get "Purchases Made" working and confirm it carries order numbers, or (b) find another authoritative per-order points source. Until then, `content.js`'s `capture_stage: "shipped"` captures continue to have `rewards_earned: null` for anything this old (order-details never shows points; only the checkout-stage `order_confirmation.js` page does, and per Josh, that page frequently 404s once an order is old enough — unconfirmed exactly how old, pending his check).
