# ADR-021 — FIFO Costing Method (Locked)

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-26 |
| **Decided by** | Josh Buckingham |
| **CPA status** | Confirmed 2026-06-10: personal-preference choice; CPA will accommodate either method |

---

## Decision

ResellOS uses **FIFO (First In, First Out)** as the costing method for all inventory.

When a unit sells, it is matched to the earliest-purchased unit of that set still in inventory. That unit's `true_cost_basis` is what flows into COGS for the sale.

---

## Context

FIFO was the working default from S08 (cost basis engine build, 2026-05-27) but was flagged as "confirm with CPA before year-end" before being formally locked. The June 10, 2026 CPA meeting resolved that costing method is a personal-preference choice — the CPA will work with whichever method ResellOS uses. This ADR locks the decision.

FIFO was chosen over LIFO, Average Cost, and Specific Identification because:
- It's the most common and broadly defensible method for physical goods
- It naturally matches how inventory physically moves (older stock exits first)
- It avoids the tax-deferral complexity of LIFO
- The system already stores `true_cost_basis` per order (per acquisition event, not per unit) — FIFO settlement is per-order, not per-unit sale. All units from the same order share the same cost basis calculation.

---

## What This Means in the System

- `users.costing_method` is set to `'fifo'` for all users by default
- `agent_08_cost_basis.py` uses FIFO mode for all cost basis writes
- Settlement is per-order (acquisition event). When any unit from an order sells, that triggers settlement review — not just when the last unit sells. All units from one order share the same `true_cost_basis` per unit.
- **Do not change this after real data accumulates.** Retrofitting to a different method requires recalculating every `true_cost_basis` ever written. Once live orders have settled, the cost of switching is prohibitive.

---

## What Does NOT Change

- All four costing methods remain in the codebase — the engine supports them for future multi-user scenarios where a different user might choose differently
- `true_cost_basis` locks at settlement regardless of costing method
- `extended_cost_basis` (true_cost_basis + accumulated carrying cost) continues to update after settlement

---

## Consequences

- COGS reporting will reflect earliest-cost inventory first
- In a rising-cost environment, this produces higher near-term COGS and lower taxable income than LIFO would
- In a falling-cost environment, the reverse is true
- No retroactive changes to any existing `true_cost_basis` records — those are correct under FIFO already

---

## Related Decisions

- ADR-019: Order Settlement Gate (conditions for `cost_basis_state → settled`)
- ADR-020: Cost Basis Regression Testing (proposed — test suite for `agent_08_cost_basis.py`)
- ADR-022: Cashback Tax Treatment + Capital One Chain (companion decision, same date)
