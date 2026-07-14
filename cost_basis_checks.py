"""
ResellOS - Cost Basis Output Checks

Runs after Agent 08 (agent_08_cost_basis.py, Mode 1) writes inventory rows,
checking what it wrote against a few invariants that should always hold.
This is the "check the math on the way out" layer discussed 2026-06-21 —
read-only, never modifies anything, meant to be run on demand or wired into
a review step.

Important scope note, found while reading agent_08_cost_basis.py: the gift
card savings figure (Layer 2) is collected interactively in Mode 1 and used
in that one calculation, but it is never written to the database anywhere.
That means a check like this one cannot independently re-derive what
net_economic_cost *should* have been — there's no persisted record of every
input that went into it, only the final per-unit cost_basis values on
inventory. So these checks verify internal consistency of what was actually
written, not full correctness of the calculation against fresh inputs. If
ResellOS ever wants to audit a cost-basis run after the fact, the inputs
(gc_savings especially) would need to be persisted somewhere first — flagged
as a new open question, not fixed here.

What this CAN check, from data that is persisted:
  1. Every GWP line item's inventory rows carry exactly $0.00 cost basis.
  2. The number of inventory units for an order matches the total quantity
     across its line items (catches partial writes or double writes).
  3. tax_paid_allocated is still always 0 — a known S08 deferred item,
     surfaced here as a reminder rather than silently ignored.
"""

from db_client import get_client, PHASE_1_USER_ID


def check_order_inventory(order_number: str, client=None) -> list[dict]:
    """
    Run all checks for one order, identified by order_number. Returns a list
    of warning dicts (empty list = clean). Looks up the order, its line
    items, and the inventory rows tied to those line items.
    """
    client = client if client is not None else get_client()
    warnings: list[dict] = []

    order_result = (
        client.table("orders")
        .select("order_id, order_number, cost_basis_state")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .execute()
    )
    if not order_result.data:
        return [{
            "check": "order_not_found",
            "message": f"No order found for '{order_number}'.",
            "blocking": False,
        }]
    order = order_result.data[0]
    order_id = order["order_id"]

    li_result = (
        client.table("line_items")
        .select("line_item_id, set_name, set_number, quantity, is_gwp")
        .eq("order_id", order_id)
        .execute()
    )
    line_items = li_result.data or []
    if not line_items:
        return [{
            "check": "no_line_items",
            "message": f"Order {order_number} has no line items — nothing to check.",
            "blocking": False,
        }]

    li_ids = [li["line_item_id"] for li in line_items]
    inv_result = (
        client.table("inventory")
        .select("unit_id, line_item_id, cost_basis, tax_paid_allocated")
        .eq("user_id", PHASE_1_USER_ID)
        .in_("line_item_id", li_ids)
        .execute()
    )
    inventory = inv_result.data or []

    if not inventory:
        return [{
            "check": "no_inventory",
            "message": (
                f"Order {order_number} has line items but no inventory rows yet — "
                f"cost basis (Mode 1) hasn't been run on it."
            ),
            "blocking": False,
        }]

    # ------------------------------------------------------------ Check 1: GWP $0
    gwp_li_ids = {li["line_item_id"] for li in line_items if li.get("is_gwp")}
    for unit in inventory:
        if unit["line_item_id"] in gwp_li_ids and float(unit.get("cost_basis") or 0) != 0.0:
            warnings.append({
                "check": "gwp_nonzero_cost_basis",
                "message": (
                    f"Inventory unit {unit['unit_id']} is a GWP item but has "
                    f"cost_basis ${float(unit['cost_basis']):.2f}, not $0.00."
                ),
                "blocking": True,
            })

    # ------------------------------------------------------- Check 2: unit count
    expected_units = sum(int(li.get("quantity") or 0) for li in line_items)
    actual_units = len(inventory)
    if expected_units != actual_units:
        warnings.append({
            "check": "unit_count_mismatch",
            "message": (
                f"Order {order_number} line items total {expected_units} unit(s) "
                f"but inventory has {actual_units} — possible partial write or "
                f"duplicate write."
            ),
            "blocking": True,
        })

    # --------------------------------------------------- Check 3: known gap reminder
    if any(float(unit.get("tax_paid_allocated") or 0) == 0 for unit in inventory):
        warnings.append({
            "check": "tax_paid_allocated_zero",
            "message": (
                "tax_paid_allocated is 0 on this order's inventory — known S08 "
                "deferred item (agent_08_cost_basis.py always writes 0 here), "
                "not a new bug. Listed in CONTEXT.md open questions."
            ),
            "blocking": False,
        })

    return warnings


def print_warnings(order_number: str, warnings: list[dict]) -> None:
    if not warnings:
        print(f"  OK: order {order_number} — no issues found in inventory checks.")
        return
    blocking = [w for w in warnings if w.get("blocking")]
    print(f"\n  -- {len(warnings)} finding(s) for order {order_number} --")
    for w in warnings:
        tag = "BLOCKING" if w.get("blocking") else "info"
        print(f"    [{tag}] {w['message']}")
    if blocking:
        print(f"\n  {len(blocking)} of these point at a real data problem — worth a look.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python cost_basis_checks.py <order_number> [<order_number> ...]")
        sys.exit(1)
    for order_number in sys.argv[1:]:
        warnings = check_order_inventory(order_number)
        print_warnings(order_number, warnings)
