# ADR-024 — WFS Phantom Inventory Credit Handling

**Date:** 2026-09-04
**Status:** Accepted
**Supersedes:** Nothing — new decision area

---

## Context

Walmart Fulfillment Services (WFS) has occasionally credited more sellable units of a set to this account than were actually shipped in. Confirmed real example: set 75333 — 8 physical units shipped, but WFS's sellable-quantity count showed 33 units available to sell (25 units that were never sent). This is not a one-off; it happens often enough to need systemic handling rather than manual cleanup each time it's noticed. The likely mechanism is on Walmart's side — another marketplace seller ships units without a matching manifest, and the simplest resolution for the warehouse worker unpacking the box is to credit the units to a different seller's account (in this case, ours) — but the cause is out of ResellOS's control and isn't expected to be fixed by Walmart. ResellOS has to account for it, not prevent it.

Nothing in the current schema records outbound shipments to WFS at all. `inventory` carries WFS-related flags (`wfs_eligible`, `wfs_converted`, `wfs_conversion_date`, `wfs_prep_cost`, `walmart_listing_id`), but nothing records "N units of set X were shipped to WFS on date Y." The existing `inventory_check_sessions` / `inventory_check_items` tables (built, unused, 0 rows) are the wrong shape for this problem: they model a physical recount of units already in the user's own possession (expected vs. actual count), not a discrepancy between what was shipped to a third party and what that third party reports holding on the user's behalf.

Left unaddressed, this creates two integrity problems as the sales-import agent comes online:

1. The sales-import agent matches a sold unit to a real `in_stock` inventory row via FIFO by set_number. Once real shipped units for a set are exhausted, there is nothing left to match the phantom quantity against — the agent would either error or, worse, silently attach the sale to a real unit's cost basis, corrupting FIFO for that set permanently.
2. Phantom units were never paid for — they have no true cost basis. Folding them into real inventory (even at cost basis $0) would misattribute genuine cash received to a specific real order's economics.

## Decision

### New table: `wfs_shipments`

The manifest of what was actually shipped to WFS, populated by the user at ship time (this is a known fact — you know what went in the box):

- `shipment_id`, `user_id`
- `set_number`, `quantity_shipped`, `ship_date`
- `unit_ids` — the specific `inventory.unit_id` rows included in the shipment
- `tracking_number`, `notes`

### Reconciliation

A phantom credit exists when the cumulative quantity shipped for a set (`wfs_shipments`) is less than the cumulative quantity WFS has ever shown as available-to-sell or sold for that set. The gap is the phantom-credit quantity. Reconciliation is manual for now — triggered when the user notices sales volume exceeding what was shipped, or when reviewing the Walmart Seller Center inventory report — since there is no automated feed of WFS's own sellable-quantity count today (see CONTEXT.md's planned WFS Shipment Portal, Phase 2).

### Phantom-credit units are their own inventory rows, never merged into real ones

- `cost_basis = 0.00` always — never estimated, never allocated from a real order, because there is no real order.
- `status = 'wfs_phantom_credit'` — a new, distinct status value. Never conflated with `in_stock` or `sold`.
- Tagged with a note referencing the reconciliation event that created it.
- Excluded from all cost-basis-weighted reporting (ROI, average cost, per-set profitability) by filtering out this status. It is not "your" inventory in the ownership sense, even though it can legitimately be sold and paid out.
- Never deleted or merged after the fact — preserved as history, same principle as ADR-023's "never auto-merge, always flag."

### Sales-import agent must handle this from day one

When a Walmart sale for a set_number cannot be matched to any real `in_stock` unit via FIFO, the agent must not error or guess. It auto-creates a `wfs_phantom_credit` unit already marked `sold`, logs it, and surfaces it in the run's review output. This is a required part of the sales-import agent's design, not an optional enhancement — without it, any set that oversells relative to what was shipped breaks the import.

### Revenue treatment

Cash received from a phantom-credit sale is real and gets recorded in `sales` normally — `net_proceeds` intact, `cost_basis_at_sale = 0`, so `net_profit` equals the full proceeds and is visibly tied to a phantom-credit unit rather than a real one. This preserves an audit trail if Walmart or the rightful seller ever reconciles the error and claws the inventory or payout back — a `returns`-style reversal entry can undo it later without ever having touched a real order's cost basis.

## Consequences

- New `wfs_shipments` table and a new `inventory.status` value require a migration.
- The sales-import agent's design must include the phantom-credit fallback before its first real run — this is load-bearing, not a follow-up.
- Reporting and ROI queries must filter `status != 'wfs_phantom_credit'` unless phantom-credit accounting is explicitly requested.
- Consistent with the system's existing philosophy (DECISION 017, ADR-019, ADR-023): never silently reopen, merge, or misattribute cost basis — flag it and let the user resolve it.

## Related decisions

- ADR-019 — Order Settlement Gate (FIFO matching at sale time)
- ADR-023 — Capture Queue Promotion and Extension Primacy (never auto-merge, always flag)
- CONTEXT.md — WFS Shipment Portal (planned Phase 2 system)
- Sales-import agent design (discussed 2026-09-04, not yet its own ADR)
