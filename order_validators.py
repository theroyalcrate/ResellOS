"""
ResellOS - Shared Pre-Write Validators

Lightweight checks run on order/line-item data before it's written to Supabase,
called from both Agent 1A (db_writer.write_invoice) and Agent 02
(agent_02_order_entry.write_order). These never block a write or silently fix
anything — they return a list of plain-English warnings so the calling agent
can show them and let a human decide whether to proceed, matching the pattern
already used elsewhere in this codebase (e.g. agent_02's Kohl's pickup-bonus
duplicate check, write_order's order_number duplicate check: warn, then ask).

Why this file exists (2026-06-21): CONTEXT.md's open questions describe a
"duplicate line items" issue — the same set getting written twice for one
order, once via Agent 02 manual entry and once via Agent 1A's invoice parser
when the real invoice PDF arrives later, because the two write paths never
checked each other. A live Supabase check this session found zero current
duplicates, but nothing currently stops a future one. These functions are
that stop, plus a couple of related data-quality checks found while reading
through the actual write paths (agent_02 lets `is_gwp` and the price paid
disagree with each other; nothing checks that line items add up to the order
total at the line level, only at the order level).

Design note: every function here takes plain data in, returns plain warnings
out (a list of dicts with at least a "message" key), and never raises on its
own account — a problem inside a check should never become a reason the real
write fails. Network/DB calls are wrapped accordingly.
"""

from typing import Optional

from db_client import get_client, PHASE_1_USER_ID


# --------------------------------------------------------------------------- #
# 1. Cross-shipment duplicate set_number (the core ask)
# --------------------------------------------------------------------------- #

def find_cross_shipment_duplicates(
    order_id: str, new_items: list[dict], new_entry_method: str, client=None
) -> list[dict]:
    """
    Check whether `new_items` look like the SAME physical items already
    written under a different shipment on this order — not just "this set
    appears again," which is normal (ordering 5 of the same set in one order
    is common and correct, and so is buying more of a set across genuinely
    separate orders/shipments).

    The actual failure mode this guards against is narrower: Agent 02 writes
    placeholder line items at purchase time (entry_method="manual"), then
    Agent 1A's invoice parser later writes the real line items for the same
    order (entry_method="invoice_parser") — and if nothing connects the two,
    the placeholder rows never get superseded, so the same physical sets end
    up counted twice. That only looks like a problem when BOTH of these hold:
      1. the existing row came from a *different* entry_method than this
         write (same-method repeats — e.g. two real invoice-parsed shipments
         both containing set X because Josh bought more of it later — are not
         flagged), and
      2. the quantity matches — if the existing manual entry said "3" and the
         real invoice also says "3" of the same set, that's almost certainly
         the same physical units, not 3 more on top.

    Returns a list of warning dicts, one per match. Empty list means clean.
    Never raises — a failed check here should never block the write path
    it's protecting; it just won't have caught anything that run.
    """
    client = client if client is not None else get_client()
    # Normalize (strip whitespace) so "10242" and " 10242 " are treated as
    # the same set — manual entry and parsed text can differ in stray spaces.
    set_numbers = sorted({
        it.get("set_number").strip() for it in new_items if it.get("set_number")
    })
    if not set_numbers:
        return []

    try:
        existing = (
            client.table("line_items")
            .select("set_number, quantity, shipment_id")
            .eq("order_id", order_id)
            .in_("set_number", set_numbers)
            .execute()
        )
        existing_rows = existing.data or []
        if not existing_rows:
            return []

        # Look up entry_method for each distinct shipment_id found — this is
        # the filter, not just context: only a *different* entry_method than
        # this write counts as a candidate duplicate.
        shipment_ids = sorted({row["shipment_id"] for row in existing_rows if row.get("shipment_id")})
        entry_methods: dict[str, str] = {}
        if shipment_ids:
            ship_result = (
                client.table("shipments")
                .select("shipment_id, entry_method")
                .in_("shipment_id", shipment_ids)
                .execute()
            )
            entry_methods = {
                r["shipment_id"]: r.get("entry_method") or "unknown"
                for r in (ship_result.data or [])
            }
    except Exception as e:
        return [{
            "check": "cross_shipment_duplicate",
            "message": f"NOTE: duplicate check could not run ({e}); proceeding without it.",
            "blocking": False,
        }]

    warnings = []
    for row in existing_rows:
        existing_method = entry_methods.get(row.get("shipment_id"), "unknown")
        if existing_method == new_entry_method:
            continue  # same path repeating itself — a genuine repeat purchase, not a collision

        matches = [
            it for it in new_items
            if it.get("set_number")
            and it.get("set_number").strip() == row["set_number"]
            and it.get("quantity") == row.get("quantity")
        ]
        for it in matches:
            warnings.append({
                "check": "cross_shipment_duplicate",
                "set_number": row["set_number"],
                "message": (
                    f"Set {row['set_number']} qty {row.get('quantity')} already exists on this "
                    f"order via a {existing_method} entry — about to write the same set and "
                    f"quantity again via {new_entry_method}. Looks like the same physical items "
                    f"entered twice, not a separate purchase of more of the same set."
                ),
                "blocking": False,
            })
    return warnings


# --------------------------------------------------------------------------- #
# 2. GWP flag vs. price agreement
# --------------------------------------------------------------------------- #

def check_gwp_price_consistency(items: list[dict]) -> list[dict]:
    """
    `is_gwp` and the price actually paid should never disagree:
      - is_gwp = True  and price paid != 0  -> GWP shouldn't have a paid price
      - is_gwp = False and price paid == 0  -> a "paid" item priced at $0 is
        suspicious (it's probably a GWP that wasn't flagged as one)

    Agent 1A's invoice parser derives is_gwp directly from the parsed price
    (`is_gwp=(net_price == 0.0)`), so this can't disagree there by
    construction. Agent 02's manual entry asks the two as separate questions —
    "Is this a GWP?" and "Price paid per unit" — with nothing tying them
    together, so a typo or a confused yes/no answer can slip through. This
    check exists mainly for that path, but runs on any item list either way.
    """
    warnings = []
    for it in items:
        price = it.get("unit_price")
        if price is None:
            continue
        is_gwp = bool(it.get("is_gwp"))
        name = it.get("set_name") or it.get("set_number") or "item"
        if is_gwp and price != 0:
            warnings.append({
                "check": "gwp_price_mismatch",
                "message": (
                    f"{name} is flagged GWP but priced at ${price:.2f}, not $0.00 — "
                    f"GWP items should always carry a $0 cost basis at receipt."
                ),
                "blocking": False,
            })
        elif not is_gwp and price == 0:
            warnings.append({
                "check": "gwp_price_mismatch",
                "message": (
                    f"{name} is priced at $0.00 but not flagged as GWP — "
                    f"double-check it isn't actually a gift-with-purchase item."
                ),
                "blocking": False,
            })
    return warnings


# --------------------------------------------------------------------------- #
# 3. Missing set_number (informational only — known to be sometimes unknown
#    at entry time, never block on this)
# --------------------------------------------------------------------------- #

def check_missing_set_numbers(items: list[dict]) -> list[dict]:
    """
    Flag line items with no set_number. Purely informational — set_number is
    intentionally optional at manual-entry time (CONTEXT.md), and this is the
    same gap behind the "backfill set_number on old line items" open question.
    Surfacing it at write time costs nothing and means fewer items need a
    later backfill pass.
    """
    warnings = []
    for it in items:
        if it.get("is_gwp"):
            continue  # GWP items are commonly catalog-light; not worth flagging
        if not it.get("set_number"):
            name = it.get("set_name") or "item"
            warnings.append({
                "check": "missing_set_number",
                "message": f"{name} has no set_number recorded.",
                "blocking": False,
            })
    return warnings


# --------------------------------------------------------------------------- #
# 4. Line items reconcile to the order total
# --------------------------------------------------------------------------- #

def check_line_items_reconcile(items: list[dict], expected_subtotal: Optional[float]) -> list[dict]:
    """
    Sum of paid (non-GWP) line_total should match the order's expected
    subtotal within a cent. Complements the order-level total check
    db_writer.py already does (invoice total vs. recorded order total) by
    checking the line-item-level math feeding into it.
    """
    if expected_subtotal is None:
        return []
    paid_total = round(sum(float(it.get("line_total") or 0) for it in items if not it.get("is_gwp")), 2)
    diff = round(abs(paid_total - float(expected_subtotal)), 2)
    if diff > 0.01:
        return [{
            "check": "line_item_total_mismatch",
            "message": (
                f"Line items sum to ${paid_total:.2f} but the expected subtotal is "
                f"${float(expected_subtotal):.2f} (off by ${diff:.2f})."
            ),
            "blocking": False,
        }]
    return []


# --------------------------------------------------------------------------- #
# Convenience: run everything that applies and print a plain summary
# --------------------------------------------------------------------------- #

def run_all_checks(
    order_id: Optional[str],
    items: list[dict],
    expected_subtotal: Optional[float] = None,
    entry_method: Optional[str] = None,
    client=None,
) -> list[dict]:
    """
    Run every check that has enough information to run. `order_id` is
    optional because the duplicate check needs an existing order to compare
    against — pass None when writing a brand-new order with no prior
    shipments (nothing to collide with yet). `entry_method` should be
    "manual" or "invoice_parser" (whichever this write path is) — required
    for the duplicate check to know which existing rows are a genuine cross-
    path collision versus a same-path repeat purchase; if omitted, the
    duplicate check is skipped entirely rather than guess.
    """
    warnings: list[dict] = []
    if order_id and entry_method:
        warnings += find_cross_shipment_duplicates(order_id, items, entry_method, client=client)
    warnings += check_gwp_price_consistency(items)
    warnings += check_missing_set_numbers(items)
    warnings += check_line_items_reconcile(items, expected_subtotal)
    return warnings


def print_warnings(warnings: list[dict]) -> None:
    """Plain-language display, consistent with the rest of the CLI agents."""
    if not warnings:
        return
    print(f"\n  -- {len(warnings)} DATA CHECK WARNING(S) -- review before continuing")
    for w in warnings:
        print(f"    ! {w['message']}")
    print()
