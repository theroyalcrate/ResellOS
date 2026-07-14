# ADR-019 — Order Settlement Gate: Conditions for cost_basis_state → settled

**Date:** 2026-06-22
**Status:** Accepted
**Supersedes:** Nothing — extends DECISION 017 (Order Edit Lifecycle & Cost Basis Trigger Gate)

---

## Context

DECISION 017 defined the gate from `confirmed → placed` (atomic write: cost basis calculated + gift card balance debited). It did not define what gates the transition from `placed → settled`. Settlement is the most consequential state transition in the system: true_cost_basis locks permanently and cannot be reopened. Returns or refunds after settlement create P&L adjustment entries — they never reopen cost basis.

Three separate events can affect an order's final economic cost after it is placed:
1. **Cashback paid out** — reduces Layer 4 of the cost basis engine
2. **GWP sold** — net proceeds reduce the originating order's Layer 5 economic cost
3. **Inventory unit sold through Walmart** — triggers FIFO matching, raises a settlement review flag

None of these are automatic. An order must not settle until all known cost-reducing events have been applied, otherwise the locked cost basis will be higher than it should be.

---

## Decision

### Settlement is always manual

`cost_basis_state` never auto-advances to `settled`. A flag is raised when trigger conditions are met, and the user reviews and marks settled explicitly. This mirrors the `confirmed → placed` gate where the user confirms before cost basis is written.

### Settlement trigger events

Any of the following raises a `settlement_review_flag` on the order:

1. **A unit from this order sells through Walmart** — Walmart reconciliation report matched to an inventory line item via FIFO. The matched unit's cost is consumed; the originating order is flagged.

2. **A GWP from this order sells** — GWP `gwp_status` moves to `sold`, Layer 5 proceeds are applied to reduce originating order economic cost, originating order is flagged.

3. **12-month provisional window elapses** — time-based backstop from GWP Philosophy C. Any order with a GWP still in `pending` status at 12 months is flagged. The GWP retains `$0 cost basis`; the order settles at its current provisional economic cost. The GWP status is left for the user to resolve separately.

### Settlement conditions (all must pass before user can mark settled)

When a user reviews a flagged order, the UI must surface the following checklist. All must be satisfied before settlement is permitted:

| Condition | Requirement |
|-----------|-------------|
| Cashback complete | Every `cashback_transactions` row linked to this order has `cashback_status = 'confirmed'`. If any row is `pending`, settlement is blocked unless user explicitly overrides with a note. |
| GWP resolved | Every GWP linked to this order has `gwp_status` in `('sold', 'retained_personal', 'donated', 'lost_damaged')` — OR the 12-month window has elapsed. |
| Cost basis in current state | `cost_basis_state = 'placed'` (not `stub`, `pending_review`, or `confirmed` — those cannot settle). |

### Override

If a user needs to settle an order with outstanding cashback (e.g., a platform closed or a tiny amount is not worth tracking), they may override the cashback-pending block with a required note field. The override is recorded, not silently allowed.

### What settlement does

1. `cost_basis_state` → `'settled'`
2. `true_cost_basis` locks — the value written at this moment is permanent
3. All future returns, refunds, or adjustments on this order create entries in a `pl_adjustments` table — they never reopen cost basis
4. `extended_cost_basis` (true_cost_basis + accumulated carrying cost) continues to be updated as storage snapshots accumulate — it is never locked

### Cashback platform priority for tracking

- **Rakuten** — email confirmation available; Agent 1C can match payout emails to orders via order number
- **Capital One Shopping** — requires manual entry when payout appears in the Cap1 portal
- **RetailMeNot** — requires manual entry
- **Honey / TopCashback / Microsoft Shopping** — manual entry

Cashback is recorded per-order in `cashback_transactions` when confirmed, not when pending. Pending state is tracked on the originating order's gift card record (`cashback_status = 'pending'`) as a reminder only — it does not activate Layer 4.

---

## FIFO interaction

FIFO determines *which* inventory unit's cost is consumed when a Walmart sale is matched. It does not determine settlement timing. Settlement is per-order (the acquisition event), not per-unit (the sale event). A single LEGO order may have 10 units; 3 may sell in month 1, 7 in month 6. The order cannot settle until the cost basis is finalized — but settlement does not require all units to be sold. Once settled, every unit from that order carries the settled true_cost_basis divided across units.

---

## Consequences

- Settlement review UI must show outstanding cashback status and GWP status before allowing the settle action
- `cashback_transactions` must be linkable to an order (already the case via `order_id` FK)
- Walmart reconciliation import raises flags — it does not settle automatically
- An order with no GWP and instant cashback confirmation (e.g., Rakuten pays same quarter) can settle quickly; an order with a pending GWP may not settle for up to 12 months
- Negative true_cost_basis remains valid after settlement — never suppress

---

## Related decisions

- DECISION 017 — Order Edit Lifecycle & Cost Basis Trigger Gate (gate into `placed`)
- GWP Philosophy C — proceeds_reduce_order, 12-month provisional window
- ADR-020 — Cost basis regression testing before bulk backfill
