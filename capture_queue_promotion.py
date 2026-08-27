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

Usage: python capture_queue_promotion.py
"""

from datetime import date, datetime, timezone

from db_client import get_client, PHASE_1_USER_ID
from agent_02_order_entry import get_input, get_int, get_yes_no, normalize_retailer, write_order
from order_validators import run_all_checks, print_warnings


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
        print(
            f"  {i}. {row.get('retailer')}  order {row.get('order_number') or '?'}  "
            f"{row.get('order_date') or '?'}  {total_display}  "
            f"({item_count} item(s))  [capture_id: {row['capture_id']}]"
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
        items.append({
            "set_name":     it.get("description") or "(no description)",
            "set_number":   it.get("set_number"),
            "quantity":     quantity,
            "msrp":         None,
            "unit_price":   unit_price,
            "line_discount": round((unit_price - net_price) * quantity, 2),
            "line_total":   round(net_price * quantity, 2),
            "is_gwp":       bool(it.get("is_gwp")),
            "is_retiring":  True,
        })
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


def _write_shipments(client, order_id, raw_shipments):
    """Create shipments row(s) for a just-written order and link each
    shipment's line items via line_items.shipment_id.

    raw_shipments is raw_data["shipments"] from capture_queue -- a list of
    {tracking_number, status, set_numbers} groups per ADR-023's raw_data
    contract (extension addendum 2026-08-27). Falls back to a single blank
    placeholder shipment (no tracking number) when raw_shipments is empty --
    matches prior behavior for orders that haven't shipped yet or were
    captured before this field existed, so nothing regresses.
    """
    if not raw_shipments:
        client.table("shipments").insert({
            "user_id": PHASE_1_USER_ID,
            "order_id": order_id,
            "shipment_status": "pending",
            "entry_method": "capture_queue_promotion",
        }).execute()
        return

    existing_items = (
        client.table("line_items")
        .select("line_item_id, set_number")
        .eq("order_id", order_id)
        .execute()
    ).data or []
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
                "entry_method": "capture_queue_promotion",
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

    Deliberately does NOT touch line_items: the checkout capture already
    created the canonical rows, and this stage's job is enrichment, not
    replacement. Prints a warning (does not block) if the item counts
    disagree, since that's worth Josh's eyes but not worth halting on.
    """
    order_id = existing["order_id"]
    print(f"\n  Order {row.get('order_number')} already exists (order_id {order_id}, status={existing.get('order_status')}).")
    print("  This is the 'shipped' stage capture -- merging tracking/payment-identity info, not creating a new order.")

    incoming_items = raw.get("line_items") or []
    existing_items = (
        client.table("line_items")
        .select("line_item_id")
        .eq("order_id", order_id)
        .execute()
    ).data or []
    if incoming_items and existing_items and len(incoming_items) != len(existing_items):
        print(
            f"  WARNING: this capture has {len(incoming_items)} line item(s) but the existing "
            f"order already has {len(existing_items)} -- verify manually, line_items were NOT changed."
        )

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

    _write_shipments(client, order_id, raw.get("shipments") or [])

    if card_lines:
        existing_notes = existing.get("notes") or ""
        new_notes = (existing_notes + " " if existing_notes else "") + (
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
    expected_item_count = sum(it["quantity"] for it in items)

    # rewards_earned isn't populated by the capture flow today (the extension
    # doesn't scrape it), but if a future capture path -- or a manual backfill
    # from the LEGO points-history ledger -- does supply it, use the real
    # value instead of silently zeroing it out.
    rewards_earned_raw = raw.get("rewards_earned")
    insider_points_earned = int(rewards_earned_raw) if rewards_earned_raw is not None else 0

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
        "entry_method":              "capture_queue_promotion",
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
        print(
            f"  {i}. {it['set_name']}{gwp_flag}  "
            f"qty {it['quantity']} @ ${it['unit_price']:.2f}  "
            f"(set#: {it.get('set_number') or '?'})"
        )
    print("=" * 70)


def promote(client, row):
    raw = row.get("raw_data") or {}
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
                # merge -- nothing to ask Josh here.
                label = pm.get("label") or pm.get("type") or "tender"
                if pm.get("inferred"):
                    # added 2026-08-26: order_confirmation.js infers a card
                    # tender from LEGO's "Order Total" balance-due field
                    # when itemized gift-card deductions don't cover the
                    # full total. Not read directly off the page -- flag it
                    # so Josh checks it against the actual card statement.
                    tender_notes.append(
                        f"{label}: ${pm.get('amount')} [INFERRED, not read from page -- verify against card statement]"
                    )
                else:
                    tender_notes.append(f"{label}: ${pm.get('amount')} (card identity not yet known)")
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

    _write_shipments(client, new_order_id, raw.get("shipments") or [])

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
