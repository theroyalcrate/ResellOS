# ADR-025 — Pre-Shipment Estimated Cost Basis Calculator

**Date:** 2026-09-04
**Status:** Accepted
**Supersedes:** Nothing — extends the Agent 08 Cost Basis Engine (S08) without modifying it

---

## Context

Agent 08's Mode 1 (Compute & Write) calculates and permanently records cost basis, but only once an order is confirmed and its units are being written to inventory. There's no way today to ask "what would this set's cost basis come out to" before that point — and that number is exactly what's needed to decide whether a set is worth shipping to Walmart at all, by comparing an estimated cost-per-unit against current market sale price.

Of Agent 08's five layers, three are already known facts by the time a shipping decision is being made: Layer 1 (invoice cost + tax — from the invoice in hand), Layer 2 (gift card discount — known at gift card purchase), and Layer 3 (rewards redemption — known if it was applied on that order). The two layers genuinely unresolved at ship-decision time are Layer 4 (cashback) and Layer 5 (GWP net proceeds) — both not yet realized because the item hasn't sold yet. Agent 08 Mode 1 already handles this exact situation for orders with pending GWP: it prompts for an assumed/actual proceeds figure and prints a full breakdown. That behavior is reused here, not reinvented.

**Explicit clarification on Insider points (this session):** points never enter the cost basis estimate as a guess. Per the existing earned-vs-redeemed rule, Insider points affect cost basis only at the moment they're *redeemed* on an order (Layer 3) — points sitting in the earned pool have no cost basis effect at all. Actual points earned per order will be tracked separately and precisely via ADR-026's weekly import, which removes any need to estimate or guess a points value here.

## Decision

1. Reuse `compute_cost_records()` and `print_cost_breakdown()` from `agent_08_cost_basis.py` as-is — the math is already correct and verified; nothing new needs to be calculated.
2. Given an order number, load real Layer 1/2/3 data (invoice cost, tax, gift card savings, rewards applied) exactly as Mode 1 does.
3. For Layer 4 (cashback) and Layer 5 (GWP proceeds), prompt for an assumed dollar value — the same interaction Mode 1 already uses for orders with pending/unresolved cashback or GWP. No new UI pattern.
4. Print the same breakdown table Mode 1 prints.
5. **Never writes anything.** No `inventory` insert, no `orders.cost_basis_state` update, no `gwp` or `cashback_transactions` write. Pure read-and-print. This is the entire point — it must be safe to run repeatedly, speculatively, without consequence.
6. Runs on any order regardless of `order_status` — including `stub` or `pending_review` orders that haven't been confirmed yet. Mode 1 correctly refuses to run on unconfirmed orders per DECISION 017; the estimator explicitly does not carry that restriction, since informing a pre-confirmation shipping decision is its whole purpose.
7. Implementation: extract `compute_cost_records()` / `print_cost_breakdown()` out of `agent_08_cost_basis.py` into a shared module (e.g. `cost_basis_math.py`) imported by both the existing engine and the new estimator, rather than duplicating the logic. This guarantees the estimate and the final computation can never silently drift apart.

## Consequences

- No schema changes required.
- Low implementation risk — read-only reuse of already-verified math, not new logic.
- Requires one refactor (extracting shared functions into their own module) before or alongside building the estimator, to keep the two calculators permanently in sync.
- Gives a concrete go/no-go number for shipping decisions, independent of and prior to the formal cost-basis-locking workflow.

## Related decisions

- Agent 08 Cost Basis Engine (S08) — five-layer model, reused verbatim here
- DECISION 017 — Order Edit Lifecycle & Cost Basis Trigger Gate (the confirmed-only gate on Mode 1 explicitly does not apply to this estimator)
- ADR-026 — LEGO Insider Points Actual-Earned Import (removes any need to guess a points value in this estimate)
