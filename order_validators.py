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
# 0. Cancelled-item exclusion (ADR-029 / migration 020, 2026-09-14)
# --------------------------------------------------------------------------- #

def _received_only(items: list[dict]) -> list[dict]:
    """Items the retailer actually shipped/Josh actually received --
    excludes item_status == 'cancelled' rows (ADR-029: a retailer cancelled
    this specific item after the order was confirmed, most commonly the
    "GWP-hack" pattern where a qualifying item is cancelled but the GWP it
    unlocked still ships). Cancelled items are *expected* to be priced at
    $0/unknown and never received -- without this filter they'd trip the
    GWP-price-mismatch and missing-set-number checks below on every single
    occurrence of an intentional, recurring pattern (15-20+ times/year per
    Josh), which is exactly backwards from what those checks are for.
    Items with no item_status key at all (any write path from before this
    field existed) are treated as received, matching the column's DB
    default.
    """
    return [it for it in items if it.get("item_status") != "cancelled"]


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

    Cancelled items (item_status == 'cancelled', ADR-029) are excluded first
    — they're expected to be $0/unpriced and not flagged GWP, and that's
    correct, not suspicious.
    """
    warnings = []
    for it in _received_only(items):
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

    Cancelled items (ADR-029) are excluded — a retailer-cancelled item's set
    number not being worth chasing down is expected, not a gap to flag.
    """
    warnings = []
    for it in _received_only(items):
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

    Cancelled items (ADR-029) always carry line_total 0 and were never part
    of what was actually charged, so they're excluded before summing —
    harmless either way today since a cancelled row's line_total is enforced
    at 0 by every write path, but excluded explicitly so this stays correct
    even if that enforcement ever changes.
    """
    if expected_subtotal is None:
        return []
    paid_total = round(
        sum(float(it.get("line_total") or 0) for it in _received_only(items) if not it.get("is_gwp")),
        2,
    )
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
# 5. Missing line items on an order that already exists (found 2026-09-17 --
#    see CONTEXT.md Open Question #22 and the 2026-09-17 Session History
#    entry for the bug this closes: agent_1e_pdf_backfill silently dropped
#    an entire shipment's line items on 6 real orders, undetected, because
#    nothing ever compared newly-parsed data against what was already on
#    file for an order_number that already existed.)
# --------------------------------------------------------------------------- #

def raw_line_items_to_compare_items(raw_line_items: list[dict]) -> list[dict]:
    """Shapes a capture_queue raw_data['line_items'] list (ADR-023 shape --
    each item has both 'unit_price' [pre-discount] and 'net_price' [what was
    actually paid]) into what find_missing_line_items()/_compute_missing_items()
    expect: a plain 'unit_price' key that means the actual per-unit amount
    paid, since that's what add_missing_items_to_order() prices a missing
    item at.

    The single source of truth for this shaping (2026-09-18, added after
    code review caught capture_queue_promotion.py's _merge_shipped_capture()
    feeding _map_line_items()'s output straight into find_missing_line_items()
    instead -- that function's 'unit_price' means the pre-discount MSRP, not
    what was paid, which would have silently overstated cost basis for any
    missing item that had a discount. agent_01e_pdf_backfill.py's
    _invoice_to_compare_items() calls this too (after first converting its
    LegoInvoice line items to this same raw dict shape) so there is exactly
    one place that decides what 'unit_price' means for this comparison.
    """
    items = []
    for it in raw_line_items:
        net_price = it.get("net_price")
        unit_price = it.get("unit_price")
        items.append({
            "set_name": it.get("description"),
            "set_number": it.get("set_number"),
            "is_gwp": bool(it.get("is_gwp")),
            "unit_price": float(net_price if net_price is not None else (unit_price or 0)),
            # msrp (2026-09-18, code review): the pre-discount price,
            # carried through separately so add_missing_items_to_order()
            # can record a real discount on a reconstructed missing item
            # instead of losing it (msrp == unit_price, line_discount == 0)
            # the moment an item is rebuilt through this comparison path.
            "msrp": float(unit_price) if unit_price is not None else None,
            "quantity": it.get("quantity") or 1,
        })
    return items


def _item_match_key(it: dict) -> tuple:
    """Match key for comparing an item against what's already on an order.
    Prefer set_number (normalized) when present -- it's the more reliable
    identity. Fall back to (normalized set_name, is_gwp) for items with no
    set_number at all (common on GWPs), so they can still be matched
    instead of always looking "missing".

    is_gwp is always part of the key (2026-09-18 fix, caught in code
    review) -- a set can legitimately ship as both a paid item and a same-
    numbered promotional GWP on one order. Without is_gwp in the
    set_number key, a paid unit and a GWP unit of the same set could
    silently cross-match: an existing GWP "covering" an incoming paid
    unit's quantity would let a real missing paid item pass the check
    undetected -- exactly backwards from what this check exists for."""
    set_number = (it.get("set_number") or "").strip().lower()
    is_gwp = bool(it.get("is_gwp"))
    if set_number:
        return ("set_number", set_number, is_gwp)
    set_name = (it.get("set_name") or it.get("description") or "").strip().lower()
    return ("set_name", set_name, is_gwp)


def _safe_int(value) -> int:
    """Never raises -- a malformed quantity (e.g. a non-numeric string from
    a source _compute_missing_items() wasn't originally written for) is
    treated as 0 rather than crashing the whole comparison. Added
    2026-09-18 after code review found a bare int() call here contradicted
    find_missing_line_items()'s own "never raises" docstring promise --
    capture_queue_review_app.py's evaluate_row() has no exception handling
    around this call, so an uncaught ValueError here would have crashed the
    whole review-queue page over one bad item."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _compute_missing_items(incoming_items: list[dict], existing_items: list[dict]) -> list[dict]:
    """
    Pure comparison logic behind find_missing_line_items() below -- no
    client, no network, just two plain item lists in and a list of warning
    dicts out. Split out on its own (2026-09-18) so it can be unit-tested
    directly, matching this codebase's existing convention of only unit-
    testing pure logic (see tests/test_order_confirm_review_app.py).

    This is a presence/quantity check only -- it does not compare dollar
    totals. That's deliberate: the caller may only have parsed ONE of
    several shipments for this order this run (e.g. agent_1e_pdf_backfill
    grouping whatever invoices it found today, when the order may have other
    shipments it never saw a PDF for), so a partial view's subtotal will
    legitimately be less than the order's real total. Comparing item
    presence/quantity instead avoids false positives from that, while still
    catching the actual failure mode this exists for: a shipment's worth of
    items that were never written to `line_items` at all.

    Matching is by set_number when available, falling back to (set_name,
    is_gwp) for items with no set_number (common on GWPs). Quantity is
    tracked as a pool per match key -- if the existing order has 2 of a set
    and incoming says 3, that's a shortfall of 1 (a real partial gap, e.g.
    the T508221251 case from 2026-09-17: 2 on file, 3 actually received).

    Cancelled items are excluded from both sides (ADR-029) -- a cancelled
    item is expected to differ, not a data gap.

    Returns one warning dict per item with a real shortfall, each carrying
    enough detail (set_number, set_name, is_gwp, unit_price,
    quantity_missing, quantity_on_file) for a caller to actually build the
    missing line_item row(s) -- not just a printed message.
    """
    incoming = _received_only(incoming_items)
    if not incoming:
        return []

    existing_rows = [r for r in existing_items if r.get("item_status") != "cancelled"]

    # Pool of remaining existing quantity per match key -- decremented as
    # incoming items claim coverage, so a later incoming item can't double-
    # count the same existing units.
    pool: dict[tuple, int] = {}
    for row in existing_rows:
        key = _item_match_key(row)
        pool[key] = pool.get(key, 0) + _safe_int(row.get("quantity"))

    warnings = []
    for it in incoming:
        key = _item_match_key(it)
        quantity_expected = _safe_int(it.get("quantity"))
        if quantity_expected <= 0:
            continue
        available = pool.get(key, 0)
        if available >= quantity_expected:
            pool[key] = available - quantity_expected
            continue
        quantity_missing = quantity_expected - max(available, 0)
        pool[key] = 0
        name = it.get("set_name") or it.get("description") or it.get("set_number") or "item"
        warnings.append({
            "check": "missing_line_item",
            "message": (
                f"{name} -- this order's records show {max(available, 0)} on file, but the new "
                f"data indicates {quantity_expected} -- {quantity_missing} unit(s) may be missing "
                f"from this order's line items."
            ),
            "blocking": False,
            "set_number": it.get("set_number"),
            "set_name": it.get("set_name") or it.get("description"),
            "is_gwp": bool(it.get("is_gwp")),
            "unit_price": it.get("unit_price"),
            # msrp (2026-09-18): pre-discount price, when the caller
            # supplied one (raw_line_items_to_compare_items() does; a
            # caller building compare_items by hand may not) -- lets
            # add_missing_items_to_order() record a real discount instead
            # of always writing line_discount=0 for a reconstructed item.
            "msrp": it.get("msrp"),
            "quantity_missing": quantity_missing,
            "quantity_on_file": max(available, 0),
        })
    return warnings


def find_missing_line_items(order_id: str, incoming_items: list[dict], client=None) -> list[dict]:
    """
    Compares `incoming_items` (newly parsed/captured data for an order_number
    that ALREADY has a real order) against the line items actually on file
    for `order_id`, and flags anything incoming that isn't already covered.
    See _compute_missing_items() above for the actual comparison rules --
    this is just the DB-fetching wrapper around it. Never raises; a failed
    lookup returns a single soft warning instead of blocking whatever write
    path is protecting.
    """
    client = client if client is not None else get_client()
    if not _received_only(incoming_items):
        return []

    try:
        existing = (
            client.table("line_items")
            .select("set_number, set_name, quantity, unit_price, is_gwp, item_status")
            .eq("order_id", order_id)
            .execute()
        )
        existing_rows = existing.data or []
    except Exception as e:
        return [{
            "check": "missing_line_items_check_error",
            "message": f"NOTE: missing-items check could not run ({e}); proceeding without it.",
            "blocking": False,
        }]

    return _compute_missing_items(incoming_items, existing_rows)


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
