"""
ResellOS - Capture Queue Promotion Workflow
=============================================
LIST / PROMOTE / DISCARD for capture_queue rows (ADR-023 Part 4 -- the single
review gate every non-manual capture path, extension or Agent 1D, lands in).

Promotion reuses agent_02_order_entry.write_order() exactly -- this is not a
second order-creation path. A promoted order lands at order_status =
"pending_review" (DECISION 017's order_status lifecycle -- live data shows
only "pending_review" and "confirmed" are actually used) because a human
has already reviewed the line items here, but not "confirmed" because Josh
hasn't signed off on the final numbers the way agent_02's manual flow does.
(Note: ADR-019 describes a "stub -> pending_review -> confirmed -> placed ->
settled" list under cost_basis_state -- that's a doc bug, found 2026-08-27;
cost_basis_state's real values are estimated -> provisional -> settled per
CONTEXT.md's cost basis engine section and live data.)

**Two capture stages, as of 2026-08-27:** raw_data.capture_stage is
"checkout" (order_confirmation.js, right after purchase -- has Insiders
points and payment amounts by type, no tracking/last4 yet) or "shipped"
(content.js, order-details page -- has tracking numbers and card last4s,
no amounts). A "shipped" capture for an order_number that's already
promoted gets merged into the existing order (tracking + payment identity
notes only) instead of creating a duplicate -- see _find_existing_order /
_merge_shipped_capture below. Legacy captures with no capture_stage are
treated as "shipped" (that was the only capture path before this date).

gift_card_last4 and cashback_rate are prompted for per DECISION 017 (fields
agents/the extension never fill) but have no dedicated orders-table column
today -- agent_02's manual entry doesn't capture them either (no
gift_card_assignments or cashback_transactions writes exist in that path).
Building that linkage is a separate feature; this records what Josh enters
in order.notes so it isn't silently dropped.

**Non-interactive auto-promote + missing-item reconciliation, added
2026-09-18 (CONTEXT.md Open Question #22).** Found 2026-09-17:
agent_1e_pdf_backfill used to write orders directly instead of going
through this module, and never compared newly-found PDF data against an
order that already existed -- both gaps let it silently drop an entire
shipment's line items on 6 real orders without anything catching it.
Fixed with two additions any unattended writer can now use:
`auto_promote()` is a no-prompts twin of `promote()`'s "create a new
order" path (write_order(interactive=False) refuses instead of hanging if
a race means the order already exists); `find_missing_line_items()`
(order_validators.py) + `add_missing_items_to_order()` (below) are the
shared pieces that compare newly-found data against what's on file for an
order and, on request, add whatever's missing. `_merge_shipped_capture()`
now uses this reconciliation too, instead of only warning on an item-count
mismatch and never acting on it. A capture_queue row with
`raw_data._discrepancy` set (written by an unattended writer that found a
mismatch but -- per Josh's explicit instruction -- never applies a fix
itself) is resolved interactively via `_resolve_discrepancy_row()`, reached
automatically from `promote()`.

Usage: python capture_queue_promotion.py
"""

from datetime import date, datetime, timezone
from typing import Optional

from db_client import get_client, PHASE_1_USER_ID
from agent_02_order_entry import get_input, get_int, get_yes_no, normalize_retailer, write_order
from order_validators import (
    run_all_checks,
    print_warnings,
    find_missing_line_items,
    raw_line_items_to_compare_items,
    _compute_missing_items,
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# LIST
# --------------------------------------------------------------------------- #

def list_pending(client):
    result = (
        client.table("capture_queue")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("status", "pending")
        .order("captured_at")
        .execute()
    )
    rows = result.data or []
    print("\n" + "=" * 70)
    print("  CAPTURE QUEUE -- PENDING REVIEW")
    print("=" * 70)
    if not rows:
        print("  (nothing pending)")
    for i, row in enumerate(rows, 1):
        raw = row.get("raw_data") or {}
        item_count = len(raw.get("line_items") or [])
        total = row.get("total")
        total_display = f"${total:.2f}" if total is not None else "?"
        tag = "  [DISCREPANCY -- order already exists]" if raw.get("_discrepancy") else ""
        print(
            f"  {i}. {row.get('retailer')}  order {row.get('order_number') or '?'}  "
            f"{row.get('order_date') or '?'}  {total_display}  "
            f"({item_count} item(s))  [capture_id: {row['capture_id']}]{tag}"
        )
    print("=" * 70)
    return rows


def _choose_row(rows):
    if not rows:
        return None
    idx = get_int(f"  Row number (1-{len(rows)}, 0 to cancel)", default="0")
    if idx <= 0 or idx > len(rows):
        return None
    return rows[idx - 1]


# --------------------------------------------------------------------------- #
# PROMOTE -- field mapping
# --------------------------------------------------------------------------- #

def _map_line_items(raw_items):
    items = []
    for it in raw_items:
        quantity = it.get("quantity") or 1
        unit_price = float(it.get("unit_price") or 0)
        net_price = it.get("net_price")
        net_price = float(net_price) if net_price is not None else unit_price

        # ADR-029 / migration 020 (2026-09-14): no capture path (extension or
        # PDF backfill) detects a retailer's post-order cancellation on its
        # own today -- this only ever comes from raw_data a human already
        # annotated (e.g. the ADR-028 review tool's "Cancelled" checkbox, or
        # a manual capture_queue insert like the T513531463-style GWP-hack
        # backfill). Defaults to "received" so every existing/ordinary
        # capture is unaffected.
        item_status = it.get("item_status") or "received"

        mapped = {
            "set_name":     it.get("description") or "(no description)",
            "set_number":   it.get("set_number"),
            "quantity":     quantity,
            "msrp":         None,
            "unit_price":   unit_price,
            "line_discount": round((unit_price - net_price) * quantity, 2),
            "line_total":   round(net_price * quantity, 2),
            "is_gwp":       bool(it.get("is_gwp")),
            "is_retiring":  True,
            "item_status":  item_status,
            "cancellation_reason": it.get("cancellation_reason"),
            "cancelled_at": it.get("cancelled_at"),
        }
        if item_status == "cancelled":
            # Never actually charged -- zero out regardless of whatever
            # unit_price/net_price the raw capture happened to carry.
            mapped["line_total"] = 0
            mapped["line_discount"] = 0
        items.append(mapped)
    return items


# --------------------------------------------------------------------------- #
# PROMOTE -- shipment mapping (added 2026-08-27, T513203884/T513202830 recon)
# --------------------------------------------------------------------------- #

_SHIPMENT_STATUS_MAP = {
    "shipped": "shipped",
    "delivered": "delivered",
    "processing": "pending",
    "preparing": "pending",
}


def _write_shipments(client, order_id, raw_shipments, only_line_item_ids=None, entry_method="capture_queue_promotion"):
    """Create shipments row(s) for a just-written order and link each
    shipment's line items via line_items.shipment_id.

    raw_shipments is raw_data["shipments"] from capture_queue -- a list of
    {tracking_number, status, set_numbers} groups per ADR-023's raw_data
    contract (extension addendum 2026-08-27). Falls back to a single blank
    placeholder shipment (no tracking number) when raw_shipments is empty --
    matches prior behavior for orders that haven't shipped yet or were
    captured before this field existed, so nothing regresses.

    `only_line_item_ids` (optional, added 2026-09-18): when given, only
    match against this exact set of line_item_ids instead of every item on
    the order. Without this, a set_number shared by two different
    line_items on the order (a real possibility once add_missing_items_to_order()
    can add a second unit of something already on file -- e.g. a split
    shipment revealing more of a set already partly received) could let
    this function reassign an item that's already correctly attached to a
    real shipment from an earlier call, silently corrupting that earlier,
    correct association (caught in code review). Every existing caller
    passes nothing here and is unaffected -- the normal "brand-new order,
    every item still on write_order()'s single placeholder shipment" case
    has nothing already-correctly-assigned to protect.

    `entry_method` (optional, added 2026-09-18, code review): defaults to
    the historical "capture_queue_promotion" value so nothing changes for a
    caller that doesn't pass it, but a caller that knows the real source
    (e.g. auto_promote() passing raw_data['source'], which ADR-023 always
    sets to "chrome_extension" or "agent_1d_pdf_backfill") should pass that
    through instead -- restores the provenance agent_1e_pdf_backfill's old,
    deleted direct-write code used to record explicitly, needed to tell a
    PDF-backfilled shipment apart from a live-captured one in any future
    audit or bulk correction.
    """
    if not raw_shipments:
        client.table("shipments").insert({
            "user_id": PHASE_1_USER_ID,
            "order_id": order_id,
            "shipment_status": "pending",
            "entry_method": entry_method,
        }).execute()
        return

    existing_items = (
        client.table("line_items")
        .select("line_item_id, set_number")
        .eq("order_id", order_id)
        .execute()
    ).data or []
    if only_line_item_ids is not None:
        existing_items = [it for it in existing_items if it["line_item_id"] in only_line_item_ids]
    claimed_ids = set()

    for group in raw_shipments:
        status_key = (group.get("status") or "").strip().lower()
        shipment_status = _SHIPMENT_STATUS_MAP.get(status_key, "shipped")

        result = (
            client.table("shipments")
            .insert({
                "user_id": PHASE_1_USER_ID,
                "order_id": order_id,
                "tracking_number": group.get("tracking_number"),
                "shipment_status": shipment_status,
                "entry_method": entry_method,
                # migration 002's shipment-level financial columns
                # (2026-09-18): a Chrome-extension shipment group never
                # carries these keys, so .get() leaves them null there,
                # unchanged from before. agent_1e_pdf_backfill's shipment
                # groups DO carry them (restored in code review after being
                # silently dropped when that agent was rewritten to route
                # through this shared function instead of its own deleted
                # direct-write code).
                "invoice_number": group.get("invoice_number"),
                "invoice_date": group.get("invoice_date"),
                # no_invoice_received (2026-09-18, code review): a real,
                # meaningfully-used column elsewhere (agents/email_enricher.py
                # sets it True when there's no invoice in hand) -- a
                # Chrome-extension group never carries this key so it stays
                # at the column's own default there, unchanged; a group that
                # DOES specify it (agent_1e's, always False -- its whole job
                # is processing a real invoice) is honored here instead of
                # silently dropping to null.
                "no_invoice_received": group.get("no_invoice_received"),
                "subtotal": group.get("subtotal"),
                "tax_amount": group.get("tax_amount"),
                "payment_method": group.get("payment_method"),
            })
            .execute()
        )
        shipment_id = result.data[0]["shipment_id"]

        for set_number in group.get("set_numbers") or []:
            match = next(
                (
                    it for it in existing_items
                    if it["set_number"] == set_number and it["line_item_id"] not in claimed_ids
                ),
                None,
            )
            if not match:
                print(
                    f"  WARNING: shipment {group.get('tracking_number')} listed set "
                    f"{set_number}, but no unclaimed line item with that set number "
                    f"was found on this order -- leaving it unassigned, check manually."
                )
                continue
            claimed_ids.add(match["line_item_id"])
            client.table("line_items").update({"shipment_id": shipment_id}).eq(
                "line_item_id", match["line_item_id"]
            ).execute()


# --------------------------------------------------------------------------- #
# Non-interactive auto-promote (added 2026-09-18, ADR/Open-Question #22 fix)
# --------------------------------------------------------------------------- #

def _payment_fields_from_methods(payment_methods: list[dict]) -> tuple[float, Optional[str], Optional[str]]:
    """Pure logic behind auto_promote()'s payment-field handling below.
    Derives (gift_card_applied, payment_method, payment_method_detail) from
    a raw_data["payment_methods"] list (ADR-023 shape) -- restores what
    agent_1e_pdf_backfill's old, deleted direct-write path used to compute
    from parsed PDF payment legs directly, before this agent was rewritten
    to route through capture_queue's shared raw_data shape instead (a real
    regression caught in code review, 2026-09-18: _build_order() alone never
    reads payment_methods at all, since the interactive promote() path
    deliberately leaves gift-card/payment detail to Josh's per-tender review
    rather than auto-trusting it -- see this module's own docstring on that
    gap. auto_promote() only ever runs on data order_validators.py has
    already confirmed CLEAN with no human review, so trusting the PDF's own
    payment legs here is the same trust level the deleted code already had).

    Not used by the interactive promote() path -- that one's existing
    per-tender prompt-and-record-to-notes behavior is intentionally left
    unchanged.
    """
    if not payment_methods:
        return 0.0, None, None
    gift_card_applied = round(
        sum(float(pm.get("amount") or 0) for pm in payment_methods if pm.get("type") == "gift_card"),
        2,
    )
    if len(payment_methods) == 1:
        pm = payment_methods[0]
        payment_method = pm.get("brand") or pm.get("raw") or pm.get("type")
        payment_method_detail = None
    else:
        payment_method = "mixed"
        payment_method_detail = "; ".join(
            f"{pm.get('brand') or pm.get('raw') or pm.get('type')} ${float(pm.get('amount') or 0):.2f}"
            for pm in payment_methods
        )
    return gift_card_applied, payment_method, payment_method_detail


def auto_promote(client, row) -> dict:
    """Non-interactive equivalent of promote()'s "create a new order" path --
    no get_input()/get_yes_no() calls anywhere in this function or anything
    it calls, so it's safe for an unattended scheduled run (agent_1e_pdf_backfill
    is the first caller). Reuses the exact same _build_order()/write_order()/
    _write_shipments() path the interactive promote() uses for a brand-new
    order, so a promoted order looks identical no matter which path created
    it. This replaces agent_1e's old private copy of the same write logic
    (found 2026-09-17: agent_1e wrote orders directly instead of going
    through this shared path, which is very likely why its missing-shipment
    bug went unnoticed for as long as it did -- see CONTEXT.md Open Question
    #22).

    Only call this for a capture_queue row you've already confirmed
    represents a genuinely NEW order_number -- it does not check for an
    existing order itself (that's `_find_existing_order` / the caller's
    job); write_order()'s own duplicate check (interactive=False) still
    refuses safely rather than writing a duplicate if one turns up anyway
    (e.g. a race between the check and this call).

    Returns {"ok": True, "order_id": str} or {"ok": False, "message": str}.
    """
    raw = row.get("raw_data") or {}
    order, items, rewards_earned = _build_order(raw, row)
    order["notes"] = (
        f"Auto-promoted from capture_queue ({row['capture_id']}) -- clean parse, "
        f"no data-quality flags at write time. buy_reason/purchase_trigger left "
        f"blank -- fill in manually if relevant."
    )

    # Restores fields _build_order() alone doesn't populate (2026-09-18 code
    # review) -- see _payment_fields_from_methods()'s docstring for why this
    # only happens here, not in the interactive promote() path.
    gift_card_applied, payment_method, payment_method_detail = _payment_fields_from_methods(
        raw.get("payment_methods") or []
    )
    order["gift_card_applied"] = gift_card_applied
    order["payment_method"] = payment_method
    order["payment_method_detail"] = payment_method_detail
    if raw.get("insider_points_redeemed") is not None:
        order["insider_points_redeemed"] = raw["insider_points_redeemed"]

    # unit_price/msrp correction (2026-09-18, code review): _map_line_items()
    # (used by _build_order() above) puts ADR-023's pre-discount "unit_price"
    # field straight into the line_items row's unit_price column and always
    # leaves msrp null -- a pre-existing characteristic of the shared
    # capture_queue_promotion path (predates this session, also affects
    # Chrome-extension-sourced orders; out of scope to change there without
    # Josh's sign-off, since it's used in production daily). But
    # agent_1e_pdf_backfill's OLD, deleted direct-write code correctly kept
    # unit_price = net price paid and msrp = the real pre-discount price
    # separately -- auto_promote() only ever runs on data confirmed CLEAN
    # from a full PDF invoice (unlike a live DOM scrape), so it's safe and
    # correct to re-derive the right values here from the same raw_data
    # line_items already in hand, without touching _map_line_items() itself
    # or any other caller. line_total/line_discount are untouched -- they
    # already use net_price correctly.
    raw_items = raw.get("line_items") or []
    for item, raw_item in zip(items, raw_items):
        net_price = raw_item.get("net_price")
        gross_price = raw_item.get("unit_price")
        if net_price is not None:
            item["msrp"] = gross_price
            item["unit_price"] = float(net_price)

    # _build_order() defaults every capture_queue row to "pending" since an
    # ordinary capture needs Josh's review before its reconciliation status
    # can be trusted -- but auto_promote() is only ever called (by its own
    # contract, see docstring above) on data order_validators.py has already
    # confirmed CLEAN with no flags, which is exactly what "reconciled"
    # means. Restores the old, deleted direct-write path's behavior for this
    # field (caught in code review, 2026-09-18).
    order["reconciliation_status"] = "reconciled"

    if not write_order(order, items, client, interactive=False):
        return {"ok": False, "message": "write_order() refused or failed -- see log above."}

    lookup = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order["order_number"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not lookup.data:
        return {
            "ok": False,
            "message": "Order written but could not be looked back up -- capture_queue row NOT updated.",
        }
    new_order_id = lookup.data[0]["order_id"]

    client.table("capture_queue").update({
        "status": "promoted",
        "promoted_order_id": new_order_id,
        "reviewed_at": _now_iso(),
        "review_note": "Auto-promoted -- clean parse, no data-quality flags.",
    }).eq("capture_id", row["capture_id"]).execute()

    _write_shipments(
        client, new_order_id, raw.get("shipments") or [],
        entry_method=raw.get("source") or "capture_queue_promotion",
    )

    return {"ok": True, "order_id": new_order_id}


# --------------------------------------------------------------------------- #
# Adding items an existing order was missing (added 2026-09-18, closes the
# gap found 2026-09-17 -- see CONTEXT.md Open Question #22). Used by
# _merge_shipped_capture() below, by the new capture_queue "discrepancy" row
# kind agent_1e_pdf_backfill can create, and by capture_queue_review_app.py.
# --------------------------------------------------------------------------- #

def _build_missing_item_rows(order_id, missing_items, shipment_id) -> tuple[list[dict], float]:
    """Pure row-construction logic behind add_missing_items_to_order() below
    -- no client, no network. Split out (2026-09-18) so it's unit-testable
    directly, matching this codebase's convention of only unit-testing pure
    logic. Returns (line_item_rows, added_subtotal)."""
    added_subtotal = 0.0
    line_item_rows = []
    for it in missing_items:
        quantity = int(it.get("quantity_missing") or 0)
        if quantity <= 0:
            continue
        unit_price = float(it.get("unit_price") or 0)
        # msrp (2026-09-18, code review): use the real pre-discount price
        # when the caller supplied one (order_validators.raw_line_items_to_
        # compare_items() does); fall back to unit_price (no discount known)
        # only when it's genuinely absent, rather than always losing any
        # real discount on a reconstructed item.
        msrp = it.get("msrp")
        msrp = float(msrp) if msrp is not None else unit_price
        line_discount = round((msrp - unit_price) * quantity, 2)
        line_total = round(unit_price * quantity, 2)
        added_subtotal += line_total
        line_item_rows.append({
            "user_id": PHASE_1_USER_ID,
            "order_id": order_id,
            "shipment_id": shipment_id,
            "set_name": it.get("set_name") or "(no description)",
            "set_number": it.get("set_number"),
            "quantity": quantity,
            "unit_price": unit_price,
            "msrp": msrp,
            "line_discount": line_discount,
            "line_total": line_total,
            "is_gwp": bool(it.get("is_gwp")),
            "is_retiring": True,
            "item_status": "received",
        })
    return line_item_rows, round(added_subtotal, 2)


def add_missing_items_to_order(
    client, order_id, missing_items, shipment_meta=None, additional_tax=None, note=None,
):
    """
    Writes real line_items (and, if `shipment_meta` is given, a real
    shipments row) for items a later capture/invoice revealed weren't on
    file for `order_id` -- the automated version of the direct-SQL fix
    applied by hand to 6 real orders on 2026-09-17 (T450671168, T509174028,
    T507663840, T509176263, T508221251, T512438222 -- see SESSION_LOG.md's
    2026-09-17 entry and CONTEXT.md Open Question #22).

    `missing_items` is exactly what order_validators.find_missing_line_items()
    returns -- each entry already carries set_number/set_name/is_gwp/
    unit_price/quantity_missing, everything a line_items row needs.
    `shipment_meta` (optional) is {"invoice_number", "invoice_date",
    "tracking_number", "shipment_status", "subtotal", "tax_amount",
    "payment_method"} -- when given, a real shipments row is created (with
    whichever of those fields are present -- migration 002's financial
    columns included, added 2026-09-18 after code review found they'd been
    silently dropped here even though _write_shipments() elsewhere in this
    file already carries them) and the new line_items are attached to it;
    when omitted, the new line_items are written with no shipment_id (still
    correct, just not grouped under a specific shipment -- better than not
    writing them at all).

    Also bumps the order's own subtotal/total by what's being added (this
    was always real money spent, just never recorded) and appends a note to
    orders.notes describing exactly what was added and when -- the same
    audit trail Josh's manual SQL fixes left behind, now automatic.
    `additional_tax`, when known (e.g. from a specific invoice), is added to
    tax_paid too; when not known, tax_paid is left alone and the note says
    so explicitly rather than guessing at it.

    Never touches an already-CONFIRMED order (refuses outright -- see the
    check right below) and never touches any EXISTING line_items row --
    purely additive to a still-`pending_review` order. Returns {"ok": True,
    "order_id", "added_item_count", "added_subtotal"} or {"ok": False,
    "message"}.
    """
    if not missing_items:
        return {"ok": False, "message": "No missing items given -- nothing to add."}

    # CLAUDE.md Rule 4: "Cost basis locks at settlement. Never reopen."
    # (added 2026-09-18, caught in code review -- this function used to
    # silently rewrite subtotal/total/tax_paid on ANY order regardless of
    # status, which for a `confirmed` order could mean changing the exact
    # totals its cost basis was already computed against, corrupting
    # whatever P&L is already booked.) A `confirmed` order needs
    # order_lifecycle.py's reopen_order() first -- that's the real,
    # existing mechanism for editing a confirmed order's data (it also
    # reverses any gift-card debit before letting edits happen) -- this
    # function refuses outright rather than quietly bypassing it.
    order_check = client.table("orders").select("order_status").eq("order_id", order_id).execute()
    if not order_check.data:
        return {"ok": False, "message": f"Order {order_id} not found -- nothing written."}
    if order_check.data[0].get("order_status") == "confirmed":
        return {
            "ok": False,
            "message": (
                f"Order {order_id} is already 'confirmed' -- its cost basis may already be "
                f"computed against its current totals. Reopen it first via order_lifecycle.py's "
                f"reopen_order(), then add these items through the normal edit flow, rather than "
                f"silently changing a confirmed order's totals here."
            ),
        }

    # Re-verify against the order's CURRENT line_items right before writing
    # (2026-09-18, caught in code review -- CLAUDE.md Rule 2: never
    # duplicate line items). `missing_items` can be stale by the time this
    # runs: e.g. two pending capture_queue rows both reference the same
    # order (two discrepancy rows, or a discrepancy row and a shipped-merge
    # row), each caching its own "what's missing" snapshot in the calling
    # UI. Resolving one adds the item; resolving the other with its
    # stale snapshot would silently write a duplicate row for the exact
    # same item. Recomputes the real, current shortfall using the same
    # logic find_missing_line_items() uses -- `missing_items` is only ever
    # trusted as "what the caller THINKS is missing," never as ground
    # truth for what actually gets written.
    current_existing = (
        client.table("line_items")
        .select("set_number, set_name, quantity, unit_price, is_gwp, item_status")
        .eq("order_id", order_id)
        .execute()
    ).data or []
    recheck_input = [{**it, "quantity": it.get("quantity_missing")} for it in missing_items]
    missing_items = _compute_missing_items(recheck_input, current_existing)
    if not missing_items:
        return {
            "ok": False,
            "message": (
                "Nothing left to add -- these item(s) already appear to be on the order "
                "(likely resolved by a different action in the meantime)."
            ),
        }

    shipment_id = None
    if shipment_meta:
        result = (
            client.table("shipments")
            .insert({
                "user_id": PHASE_1_USER_ID,
                "order_id": order_id,
                "invoice_number": shipment_meta.get("invoice_number"),
                "invoice_date": shipment_meta.get("invoice_date"),
                "tracking_number": shipment_meta.get("tracking_number"),
                "shipment_status": shipment_meta.get("shipment_status") or "received",
                "subtotal": shipment_meta.get("subtotal"),
                "tax_amount": shipment_meta.get("tax_amount"),
                "payment_method": shipment_meta.get("payment_method"),
                "entry_method": "capture_queue_promotion",
            })
            .execute()
        )
        if not result.data:
            return {"ok": False, "message": "Failed to create shipment row -- nothing written."}
        shipment_id = result.data[0]["shipment_id"]

    line_item_rows, added_subtotal = _build_missing_item_rows(order_id, missing_items, shipment_id)

    if not line_item_rows:
        return {"ok": False, "message": "Nothing left to add after filtering zero-quantity entries."}

    result = client.table("line_items").insert(line_item_rows).execute()
    if not result.data:
        return {"ok": False, "message": "Failed to insert line_items -- nothing else was changed."}

    added_subtotal = round(added_subtotal, 2)
    order_result = (
        client.table("orders")
        .select("subtotal, total, tax_paid, notes")
        .eq("order_id", order_id)
        .execute()
    )
    if order_result.data:
        current = order_result.data[0]
        new_subtotal = round(float(current.get("subtotal") or 0) + added_subtotal, 2)
        new_tax = float(current.get("tax_paid") or 0)
        tax_note = ""
        if additional_tax is not None:
            new_tax = round(new_tax + float(additional_tax), 2)
        else:
            tax_note = " (tax not adjusted -- amount unknown, verify manually if it matters)"
        new_total = round(new_subtotal + new_tax, 2)
        existing_notes = current.get("notes") or ""
        added_note = note or (
            f"[Missing items added {_now_iso()}] {len(line_item_rows)} item(s), "
            f"${added_subtotal:.2f} subtotal{tax_note} -- found via capture_queue reconciliation."
        )
        new_notes = (existing_notes + " " if existing_notes else "") + added_note
        client.table("orders").update({
            "subtotal": new_subtotal,
            "total": new_total,
            "tax_paid": new_tax,
            "notes": new_notes,
        }).eq("order_id", order_id).execute()

    return {
        "ok": True,
        "order_id": order_id,
        "added_item_count": len(line_item_rows),
        "added_subtotal": added_subtotal,
        # The exact line_item_ids just inserted (added 2026-09-18) -- a
        # caller that goes on to call _write_shipments() afterward should
        # pass these as only_line_item_ids so that call can only ever touch
        # what was just added here, never an unrelated existing item that
        # happens to share a set_number (see _write_shipments()'s docstring
        # for the corruption this prevents).
        "added_line_item_ids": [r["line_item_id"] for r in result.data],
    }


# --------------------------------------------------------------------------- #
# PROMOTE -- checkout/shipped merge (added 2026-08-27)
# --------------------------------------------------------------------------- #

def _find_existing_order(client, order_number):
    if not order_number:
        return None
    result = (
        client.table("orders")
        .select("order_id, order_status, notes")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _merge_shipped_capture(client, row, raw, existing):
    """A 'shipped' (order-details) capture arrived for an order_number that
    a 'checkout' capture already promoted. Rather than writing a second,
    duplicate order, add what only the shipped-stage page has -- tracking
    numbers and card last4 identities -- onto the existing order.

    Line items are enriched, not blindly replaced -- the checkout capture
    already created the canonical rows for whatever it saw. But this used
    to only WARN when the new capture's item count didn't match what's on
    file, without ever checking WHAT was different or doing anything about
    it -- the exact same gap that let agent_1e_pdf_backfill silently drop a
    whole shipment on 6 real orders (found 2026-09-17, CONTEXT.md Open
    Question #22). Fixed: now runs the same missing-item reconciliation
    agent_1e uses, shows Josh exactly what's missing, and offers to add it
    right here -- rather than a printed warning that's easy to miss and
    that nothing ever acted on.
    """
    order_id = existing["order_id"]
    print(f"\n  Order {row.get('order_number')} already exists (order_id {order_id}, status={existing.get('order_status')}).")
    print("  This is the 'shipped' stage capture -- merging tracking/payment-identity info, not creating a new order.")

    # Surface ANY original flagged reasons before doing anything else
    # (2026-09-18, caught in code review): a capture_queue row can end up
    # here even if it was originally flagged for something this function's
    # own item-presence check wouldn't catch (e.g. "no usable order date",
    # a GWP-price mismatch) -- most likely a still-unreviewed
    # agent_1e_pdf_backfill row whose order_number happened to get a real
    # order through a different path before it was ever reviewed. Without
    # this, those original reasons would be silently lost the moment this
    # function's merge path runs instead of the review the row was actually
    # queued for.
    if raw.get("_flags"):
        print("\n  NOTE: this capture was originally flagged for the following reason(s):")
        for f in raw["_flags"]:
            print(f"    ! {f}")
    if raw.get("_parse_errors"):
        print("  Parse error(s) from the original capture:")
        for e in raw["_parse_errors"]:
            print(f"    ! {e}")

    # Tracked locally and only ever written to the DB as a full replacement
    # of the column -- add_missing_items_to_order() below does its own
    # notes update internally, so this gets refreshed from the DB after
    # calling it rather than risking a stale in-memory copy overwriting what
    # it just wrote (a real bug caught during review: the old code re-read
    # `existing.get("notes")` a second time near the bottom of this
    # function, which would have clobbered any note written earlier in the
    # same run).
    current_notes = existing.get("notes") or ""

    # Set when add_missing_items_to_order() below succeeds -- restricts the
    # _write_shipments() call further down to ONLY these new line_item_ids
    # instead of the whole order. Without this, if the order already has a
    # different, already-correctly-shipped line_item with the same
    # set_number (a real possibility -- e.g. two separate purchases of the
    # same set), _write_shipments()'s set_number matching could grab that
    # older, correct item instead of the new one and silently reassign it
    # away from its real shipment (caught in code review, 2026-09-18 --
    # see _write_shipments()'s own docstring for the corruption this
    # prevents). Deliberately NOT passing shipment_meta to
    # add_missing_items_to_order() either -- creating a shipment row there
    # AND relying on _write_shipments() right below to also create one for
    # the same tracking info would duplicate the shipment row.
    newly_added_line_item_ids = None

    # raw_line_items_to_compare_items(), NOT _map_line_items() -- caught in
    # code review, 2026-09-18: _map_line_items()'s "unit_price" is the
    # pre-discount MSRP (correct for building a real line_items row, where
    # msrp and unit_price are separate columns), but find_missing_line_items()
    # expects "unit_price" to mean what was actually paid, which is what
    # add_missing_items_to_order() then prices a missing item at. Passing
    # the wrong one would have silently overstated cost basis for any
    # discounted item.
    compare_items = raw_line_items_to_compare_items(raw.get("line_items") or [])
    missing = find_missing_line_items(order_id, compare_items, client=client) if compare_items else []
    if missing:
        print(
            "\n  NOTE: this capture indicates item(s) not currently on file for this order "
            "(see CONTEXT.md Open Question #22):"
        )
        for w in missing:
            print(f"    ! {w['message']}")
        if get_yes_no("\n  Add these missing item(s) to the order now?", default="n"):
            result = add_missing_items_to_order(client, order_id, missing)
            if result["ok"]:
                print(
                    f"  OK: added {result['added_item_count']} item(s), "
                    f"${result['added_subtotal']:.2f} to order_id {order_id}."
                )
                newly_added_line_item_ids = set(result["added_line_item_ids"])
                refreshed = client.table("orders").select("notes").eq("order_id", order_id).execute()
                if refreshed.data:
                    current_notes = refreshed.data[0].get("notes") or ""
            else:
                print(f"  ERROR: {result['message']} -- continuing with the tracking/payment merge below regardless.")
        else:
            print("  Not adding automatically -- noting it on the order instead so it isn't lost.")
            flag_note = (
                f"[Shipped-stage discrepancy noted {_now_iso()}] This capture indicated possible "
                "missing item(s): " + "; ".join(w["message"] for w in missing)
            )
            current_notes = (current_notes + " " if current_notes else "") + flag_note
            client.table("orders").update({"notes": current_notes}).eq("order_id", order_id).execute()

    payment_methods = raw.get("payment_methods") or []
    card_lines = [
        f"{pm.get('brand') or 'Gift card'} ...{pm.get('last4')}"
        for pm in payment_methods
        if pm.get("last4")
    ]
    if card_lines and not get_yes_no(
        f"\n  Payment identities from order-details: {', '.join(card_lines)}. Append to order notes?",
        default="y",
    ):
        card_lines = []

    if not get_yes_no("\n  Write shipment/tracking info to this order?", default="y"):
        print("  Merge cancelled. Nothing was saved.")
        return

    # Restricted to just-added items when there were any (see comment above)
    # -- otherwise unrestricted, exactly as before, which is what correctly
    # splits a brand-new order's single placeholder shipment into its real
    # per-shipment groups the first time this ever runs for an order. Known,
    # accepted tradeoff: when items WERE added, this call only attaches
    # tracking to those new items, not to any other still-unsplit item on
    # the order -- safer than the alternative (matching against everything
    # and risking the reassignment bug above) given how narrow the case is
    # where both would matter at once (an order with a genuine duplicate
    # set_number AND a missing-item gap at the same time).
    _write_shipments(
        client, order_id, raw.get("shipments") or [],
        only_line_item_ids=newly_added_line_item_ids,
        entry_method=raw.get("source") or "capture_queue_promotion",
    )

    if card_lines:
        new_notes = (current_notes + " " if current_notes else "") + (
            f"[Shipped-stage merge {_now_iso()}] Payment identities: " + "; ".join(card_lines) + "."
        )
        client.table("orders").update({"notes": new_notes}).eq("order_id", order_id).execute()

    client.table("capture_queue").update({
        "status": "promoted",
        "promoted_order_id": order_id,
        "reviewed_at": _now_iso(),
    }).eq("capture_id", row["capture_id"]).execute()

    print(f"\n  OK: shipped-stage capture merged into existing order_id {order_id}")


def _build_order(raw, row):
    retailer = normalize_retailer(raw.get("retailer") or row.get("retailer") or "")
    order_number = raw.get("order_number") or row.get("order_number") or ""
    order_date = raw.get("order_date") or row.get("order_date") or str(date.today())

    items = _map_line_items(raw.get("line_items") or [])

    subtotal = raw.get("subtotal")
    if subtotal is None:
        subtotal = sum(it["unit_price"] * it["quantity"] for it in items)
    subtotal = round(float(subtotal), 2)

    tax_paid = round(float(raw.get("tax") or 0), 2)

    total = raw.get("total")
    if total is None:
        total = row.get("total")
    total = round(float(total or 0), 2)

    tax_exempt = retailer in ("walmart", "walmart_business")
    tax_exemption_method = "at_purchase" if tax_exempt else "not_applicable"

    discount_total = round(sum(it["line_discount"] for it in items), 2)
    # ADR-029: a cancelled item is deliberately still counted here -- this
    # reflects what the order was originally confirmed to contain, which is
    # a fact independent of what later happened to any one item. Do not
    # "fix" this into excluding cancelled items without re-reading ADR-029's
    # Consequences section first.
    expected_item_count = sum(it["quantity"] for it in items)

    # rewards_earned isn't populated by the capture flow today (the extension
    # doesn't scrape it), but if a future capture path -- or a manual backfill
    # from the LEGO points-history ledger -- does supply it, use the real
    # value instead of silently zeroing it out.
    rewards_earned_raw = raw.get("rewards_earned")
    insider_points_earned = int(rewards_earned_raw) if rewards_earned_raw is not None else 0

    # entry_method (2026-09-18, code review): derived from raw_data['source']
    # (ADR-023 always sets this to "chrome_extension" or
    # "agent_1d_pdf_backfill") when present, falling back to the generic
    # "capture_queue_promotion" for any legacy row that predates that field.
    # Restores real provenance -- agent_1e_pdf_backfill's old, deleted
    # direct-write code recorded its own entry_method explicitly; routing it
    # through this shared function had silently flattened every
    # capture_queue-sourced order to the same generic value regardless of
    # which unattended writer or the extension actually produced it.
    entry_method = raw.get("source") or "capture_queue_promotion"

    order = {
        "retailer":                  retailer,
        "order_number":              order_number,
        "order_date":                order_date,
        "subtotal":                  subtotal,
        "tax_paid":                  tax_paid,
        "tax_exempt":                tax_exempt,
        "shipping":                  0,
        "gift_card_applied":         0,
        "rewards_applied":           0,
        "insider_points_redeemed":   0,
        "insider_points_earned":     insider_points_earned,
        "insider_points_multiplier": 1,
        "discount_total":            discount_total,
        "total":                     total,
        "payment_method":            None,
        "payment_method_detail":     None,
        "purchase_trigger":          None,
        "tax_exemption_method":      tax_exemption_method,
        "pickup_method":             "shipped",
        "buy_reason":                None,
        "notes":                     None,
        "entry_method":              entry_method,
        "invoice_expected":          True,
        "reconciliation_status":     "pending",
        "cost_basis_state":          "estimated",
        "order_status":              "pending_review",
        "expected_item_count":       expected_item_count,
        "expected_total":            total,
    }
    return order, items, raw.get("rewards_earned")


def _print_parsed_summary(order, items, rewards_earned):
    print("\n" + "=" * 70)
    print("  PARSED FROM CAPTURE_QUEUE -- REVIEW BEFORE PROMOTING")
    print("=" * 70)
    print(f"  Retailer:     {order['retailer']}")
    print(f"  Order Number: {order['order_number']}")
    print(f"  Order Date:   {order['order_date']}")
    print(f"  Subtotal:     ${order['subtotal']:.2f}")
    print(f"  Tax Paid:     ${order['tax_paid']:.2f}")
    print(f"  Discounts:    ${order['discount_total']:.2f}")
    print(f"  ORDER TOTAL:  ${order['total']:.2f}")
    print(f"  Pickup:       {order['pickup_method']}  (raw_data has no pickup field -- defaults to shipped; decline below if wrong)")
    if rewards_earned is not None:
        print(f"  Rewards Earned (raw): {rewards_earned}  -- mapped to insider_points_earned")
    else:
        print(f"  Rewards Earned (raw): none captured -- insider_points_earned will be 0")
    print(f"\n  LINE ITEMS ({len(items)}):")
    for i, it in enumerate(items, 1):
        gwp_flag = " [GWP]" if it["is_gwp"] else ""
        cancelled_flag = " [CANCELLED]" if it.get("item_status") == "cancelled" else ""
        print(
            f"  {i}. {it['set_name']}{gwp_flag}{cancelled_flag}  "
            f"qty {it['quantity']} @ ${it['unit_price']:.2f}  "
            f"(set#: {it.get('set_number') or '?'})"
        )
    print("=" * 70)


def _resolve_discrepancy_row(client, row, raw, discrepancy):
    """A capture_queue row created by an unattended writer (agent_1e_pdf_backfill
    is the first one) when it found data for an order_number that already
    has a real order, but the new data didn't fully match what's on file --
    the class of gap found 2026-09-17 (CONTEXT.md Open Question #22).
    Nothing was auto-applied when this row was created -- per Josh's
    explicit instruction, an unattended run only ever flags a mismatch for
    review, never fixes it on its own. This is where that review actually
    happens.
    """
    order_id = discrepancy.get("existing_order_id")
    missing = discrepancy.get("missing_items") or []
    print(
        f"\n  This isn't a new order -- order_id {order_id} already exists for "
        f"{row.get('order_number')}, but new data found item(s) that don't match what's on file:"
    )
    for m in missing:
        name = m.get("set_name") or m.get("set_number") or "item"
        print(f"    ! {name} -- {m.get('quantity_missing')} unit(s) possibly missing (on file: {m.get('quantity_on_file')})")
    if discrepancy.get("note"):
        print(f"  {discrepancy['note']}")
    print(f"\n  Detected by: {discrepancy.get('detected_by', 'unknown')} at {discrepancy.get('detected_at', 'unknown time')}")

    if not missing:
        # The "order exists but nothing parsed to compare" case (agent_1e's
        # FLAGGED_UNPARSEABLE outcome) -- nothing structured to add, but
        # this must still be resolvable from the CLI (caught in code
        # review, 2026-09-18: this used to just print a message and return,
        # leaving the row 'pending' forever with no way to close it out
        # here, unlike capture_queue_review_app.py's equivalent branch).
        print("  Nothing structured to add for this row.")
        if get_yes_no("  Discard this row?", default="n"):
            discard(client, row)
        else:
            print("  Left pending -- resolve manually.")
        return

    if get_yes_no("\n  Add these missing item(s) to the existing order now?", default="n"):
        shipment_meta = discrepancy.get("shipment_meta") or {}
        # additional_tax (2026-09-18, caught in code review): shipment_meta's
        # tax_amount is a real, parsed figure from the invoice that revealed
        # this discrepancy -- passing it through means the order's tax_paid
        # actually gets updated instead of silently staying stale while the
        # auto-generated note incorrectly claims the tax amount is unknown.
        result = add_missing_items_to_order(
            client, order_id, missing,
            shipment_meta=shipment_meta or None,
            additional_tax=shipment_meta.get("tax_amount"),
        )
        if result["ok"]:
            print(
                f"  OK: added {result['added_item_count']} item(s), "
                f"${result['added_subtotal']:.2f} to order_id {order_id}."
            )
            client.table("capture_queue").update({
                "status": "promoted",
                "promoted_order_id": order_id,
                "reviewed_at": _now_iso(),
                "review_note": f"Missing items added to existing order_id {order_id} via reconciliation.",
            }).eq("capture_id", row["capture_id"]).execute()
        else:
            print(f"  ERROR: {result['message']} -- capture_queue row left pending.")
    else:
        reason = get_input(
            "  Reason for not adding (e.g. already accounted for elsewhere)", required=False
        ) or "Reviewed, no action taken."
        client.table("capture_queue").update({
            "status": "discarded",
            "promoted_order_id": order_id,
            "review_note": reason,
            "reviewed_at": _now_iso(),
        }).eq("capture_id", row["capture_id"]).execute()
        print("  OK: marked reviewed, no items added.")


def promote(client, row):
    raw = row.get("raw_data") or {}
    if raw.get("_discrepancy"):
        _resolve_discrepancy_row(client, row, raw, raw["_discrepancy"])
        return

    capture_stage = raw.get("capture_stage") or "shipped"  # legacy rows (pre-2026-08-27) only ever came from the order-details page
    order_number = raw.get("order_number") or row.get("order_number")
    existing = _find_existing_order(client, order_number)

    if existing and capture_stage == "shipped":
        _merge_shipped_capture(client, row, raw, existing)
        return

    if existing and capture_stage == "checkout":
        print(f"\n  An order already exists for {order_number} (order_id {existing['order_id']}).")
        print("  A second checkout-stage capture for the same order looks like a duplicate, not new data.")
        if get_yes_no("  Discard this capture as a duplicate?", default="y"):
            discard(client, row)
        else:
            print("  Left as pending -- resolve manually.")
        return

    order, items, rewards_earned = _build_order(raw, row)

    _print_parsed_summary(order, items, rewards_earned)

    if not get_yes_no("\nProceed with promotion?", default="y"):
        print("Promotion cancelled.")
        return

    print("\n  -- FIELDS RESERVED FOR JOSH (DECISION 017) --")
    # payment_methods (added 2026-08-27) replaces the old single
    # gift_card_last4 prompt -- an order can carry several gift cards plus
    # a credit card (confirmed live: T513207318 alone had two), and the
    # order-detail page never shows the dollar split across them, so Josh
    # is asked per tender rather than once for the whole order. Falls back
    # to the old single-field prompt for any capture_queue row written
    # before this field existed.
    payment_methods = raw.get("payment_methods")
    tender_notes = []
    if payment_methods:
        print(f"  {len(payment_methods)} payment method(s) captured from the page:")
        for pm in payment_methods:
            if pm.get("amount") is not None:
                # checkout-stage: dollar amount already known from the
                # confirmation page, last4 comes later via a shipped-stage
                # merge (or, for a card, may already be known -- see below)
                # -- nothing to ask Josh here either way.
                label = pm.get("label") or pm.get("type") or "tender"
                last4 = pm.get("last4")
                # added 2026-08-26: order_confirmation.js's "Payment Method"
                # section names a card's last4 directly, even for a checkout
                # capture -- confirmed live on T513381170. Only gift cards
                # stay identity-unknown at this stage. label already reads
                # "Card ...{last4}" for that case, so skip re-appending it
                # here (Claude Code caught this duplication on ac62578).
                if last4 and last4 in label:
                    identity = ""
                elif last4:
                    identity = f" (...{last4})"
                else:
                    identity = " (card identity not yet known)"
                if pm.get("inferred"):
                    # order_confirmation.js infers a card tender's DOLLAR
                    # AMOUNT from LEGO's "Order Total" balance-due field
                    # when itemized gift-card deductions don't cover the
                    # full total -- not an itemized line the way gift cards
                    # are, so flag it even when last4 is known, so Josh
                    # checks the amount against the actual card statement.
                    tender_notes.append(
                        f"{label}: ${pm.get('amount')}{identity} [amount INFERRED from balance due, not an itemized line -- verify against card statement]"
                    )
                else:
                    tender_notes.append(f"{label}: ${pm.get('amount')}{identity}")
            elif pm.get("type") == "gift_card":
                amount = get_input(f"    Gift card ...{pm.get('last4')} -- amount applied (blank if unknown)", required=False)
                tender_notes.append(f"GC ...{pm.get('last4')}: ${amount}" if amount else f"GC ...{pm.get('last4')}: amount unknown")
            elif pm.get("type") == "card":
                tender_notes.append(f"{pm.get('brand', 'Card')} ...{pm.get('last4')}")
            else:
                tender_notes.append(f"Unrecognized tender: {pm.get('raw')}")
        gift_card_last4 = ", ".join(
            pm.get("last4") for pm in payment_methods if pm.get("type") == "gift_card" and pm.get("last4")
        ) or None
    else:
        gift_card_last4 = raw.get("gift_card_last4")
        if gift_card_last4:
            print(f"  Gift card last4 (already captured): {gift_card_last4}")
        else:
            gift_card_last4 = get_input("  Gift card last 4 (blank if none)", required=False)

    buy_reason = get_input(
        "  Buy reason (planned/opportunistic/promo_expiration, blank if none)",
        required=False,
    ) or None
    purchase_trigger = get_input(
        "  Purchase trigger (community_alert/deal_software_alert/self_discovered, blank if none)",
        required=False,
    ) or None
    cashback_rate = get_input("  Cashback rate, if applicable (blank to skip)", required=False)

    order["buy_reason"] = buy_reason
    order["purchase_trigger"] = purchase_trigger

    note_bits = [f"Promoted from capture_queue ({row['capture_id']})."]
    if tender_notes:
        note_bits.append(
            "Payment methods -- " + "; ".join(tender_notes) +
            " -- no gift_card_assignments linkage built yet, recorded here only."
        )
    elif gift_card_last4:
        note_bits.append(
            f"Gift card used ending in {gift_card_last4} -- no gift_card_assignments "
            f"linkage built yet, recorded here only."
        )
    if cashback_rate:
        note_bits.append(
            f"Cashback rate noted: {cashback_rate} -- no cashback_transactions row "
            f"created, recorded here only."
        )
    if rewards_earned is None:
        note_bits.append(
            "No points captured for this order at promotion time -- "
            "insider_points_earned left at 0, backfill later from the points-history ledger if needed."
        )
    order["notes"] = " ".join(note_bits)

    # Post-discount paid total, not the raw pre-discount subtotal -- line_total
    # on each item is already net_price*quantity (post-discount), so comparing
    # it against a pre-discount subtotal would false-positive on every order
    # that has any per-item discount.
    warnings = run_all_checks(
        order_id=None,
        items=items,
        expected_subtotal=round(order["subtotal"] - order["discount_total"], 2),
        entry_method="capture_queue_promotion",
        client=client,
    )
    print_warnings(warnings)

    if not get_yes_no("\nWrite this order to the database?", default="n"):
        print("Promotion cancelled. Nothing was saved.")
        return

    if not write_order(order, items, client):
        print("ERROR: write_order failed -- capture_queue row left as pending.")
        return

    lookup = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order["order_number"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not lookup.data:
        print(
            "WARNING: order written but could not be looked back up -- "
            "capture_queue row NOT updated. Fix manually."
        )
        return
    new_order_id = lookup.data[0]["order_id"]

    client.table("capture_queue").update({
        "status": "promoted",
        "promoted_order_id": new_order_id,
        "reviewed_at": _now_iso(),
    }).eq("capture_id", row["capture_id"]).execute()

    _write_shipments(
        client, new_order_id, raw.get("shipments") or [],
        entry_method=raw.get("source") or "capture_queue_promotion",
    )

    print(f"\n  OK: capture_queue row marked promoted -> order_id {new_order_id}")


# --------------------------------------------------------------------------- #
# DISCARD
# --------------------------------------------------------------------------- #

def discard(client, row):
    print(f"\n  Discarding capture_id {row['capture_id']} ({row.get('retailer')} / {row.get('order_number')})")
    reason = get_input("  Reason for discarding")
    client.table("capture_queue").update({
        "status": "discarded",
        "review_note": reason,
        "reviewed_at": _now_iso(),
    }).eq("capture_id", row["capture_id"]).execute()
    print("  OK: capture_queue row marked discarded.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    client = get_client()
    while True:
        print("\n" + "=" * 60)
        print("  RESELLOS -- CAPTURE QUEUE PROMOTION")
        print("=" * 60)
        print("  1) List pending")
        print("  2) Promote a row")
        print("  3) Discard a row")
        print("  4) Quit")
        choice = get_input("Choice", default="4")

        if choice == "1":
            list_pending(client)
        elif choice == "2":
            rows = list_pending(client)
            row = _choose_row(rows)
            if row:
                promote(client, row)
        elif choice == "3":
            rows = list_pending(client)
            row = _choose_row(rows)
            if row:
                discard(client, row)
        elif choice == "4":
            break
        else:
            print("  Please enter 1-4.")


if __name__ == "__main__":
    main()
