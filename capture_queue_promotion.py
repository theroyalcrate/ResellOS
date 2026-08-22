"""
ResellOS - Capture Queue Promotion Workflow
=============================================
LIST / PROMOTE / DISCARD for capture_queue rows (ADR-023 Part 4 -- the single
review gate every non-manual capture path, extension or Agent 1D, lands in).

Promotion reuses agent_02_order_entry.write_order() exactly -- this is not a
second order-creation path. A promoted order lands at order_status =
"pending_review" (DECISION 017's stub -> pending_review -> confirmed ->
placed -> settled lifecycle), one step past "stub" because a human has
already reviewed the line items here, but not "confirmed" because Josh
hasn't signed off on the final numbers the way agent_02's manual flow does.

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
        "insider_points_earned":     0,
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
        print(
            f"  Rewards Earned (raw): {rewards_earned}  -- not mapped to a "
            f"retailer reward column, will be recorded in notes only"
        )
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
    order, items, rewards_earned = _build_order(raw, row)

    _print_parsed_summary(order, items, rewards_earned)

    if not get_yes_no("\nProceed with promotion?", default="y"):
        print("Promotion cancelled.")
        return

    print("\n  -- FIELDS RESERVED FOR JOSH (DECISION 017) --")
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
    if gift_card_last4:
        note_bits.append(
            f"Gift card used ending in {gift_card_last4} -- no gift_card_assignments "
            f"linkage built yet, recorded here only."
        )
    if cashback_rate:
        note_bits.append(
            f"Cashback rate noted: {cashback_rate} -- no cashback_transactions row "
            f"created, recorded here only."
        )
    if rewards_earned is not None:
        note_bits.append(
            f"Rewards earned per capture: {rewards_earned} -- not mapped to a "
            f"retailer reward column, recorded here only."
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
