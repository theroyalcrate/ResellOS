"""
ResellOS - Order Lifecycle: Reopen / Edit / Re-confirm (ADR-031)

Implements DECISION 017's confirm/reopen transition, which existed only as
architecture text (Master Architecture Document, added 2026-06-01) until
this build. order_status has always had "confirmed" and "pending_review"
values in real data -- what never existed anywhere in the codebase was a
way to move a CONFIRMED order back to pending_review, edit it, and
re-confirm it.

Why this exists: gift card balances need to correct themselves when an
order gets partially cancelled after the card was already debited. Per
DECISION 017, that's not a separate "adjustment tool" bolted on the side --
it's the ordinary reopen -> edit -> re-confirm cycle every order was always
meant to support. This module builds that cycle, using gift cards as its
first real consumer (ADR-031, 2026-09-15).

Scope: this reopens the fields DECISION 017 actually gates behind
"confirmed" -- line item cancellation status and the gift card amount/card
used. It is not a general "edit any field" order editor. Fields DECISION
017 already calls out as editable at any status (buy_reason, notes,
storage_location, purchase_trigger) don't need this machinery -- if those
turn out not to be editable anywhere today, that's a separate small fix,
not part of this one.

Refuses to reopen a settled order -- CLAUDE.md Critical Rule #4: "Cost
basis locks at settlement. Never reopen. Returns create P&L adjustments."
That rule is about the settled gate (ADR-019) and is untouched by this
module, which only ever moves confirmed <-> pending_review.

Usage: python order_lifecycle.py
  (also reachable from agent_02_order_entry.py's main menu, option 2)
"""

from datetime import date

from db_client import get_client, PHASE_1_USER_ID
from agent_02_order_entry import get_input, get_int, get_float, get_yes_no
from gift_card_ledger import apply_gift_card_debit, reverse_gift_card_assignments
from order_validators import run_all_checks, print_warnings


def _find_order(order_number, client):
    result = (
        client.table("orders")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _print_order(order):
    print(f"\n  Order {order['order_number']}  ({order['retailer']}, {order['order_date']})")
    print(f"  Status: {order['order_status']}   Cost basis state: {order.get('cost_basis_state')}")
    print(
        f"  Total: ${float(order['total']):.2f}   "
        f"Gift card applied: ${float(order.get('gift_card_applied') or 0):.2f}"
    )


def reopen_order(client, order_number=None):
    """
    confirmed -> pending_review. Reverses any gift card debit tied to this
    order first (DECISION 017: "reopening to pending_review reverses the
    prior balance reduction before applying the new one").
    """
    order_number = order_number or get_input("Order number to reopen")
    order = _find_order(order_number, client)
    if not order:
        print(f"  No order found with number {order_number}.")
        return None

    _print_order(order)
    status = order.get("order_status")
    if status == "settled":
        print("\n  Cannot reopen -- this order is settled. Cost basis locks at settlement")
        print("  and never reopens (CLAUDE.md Critical Rule #4). A return after settlement")
        print("  needs a P&L adjustment entry, not a reopened order.")
        return None
    if status != "confirmed":
        print(f"\n  This order is '{status}', not 'confirmed' -- nothing to reopen.")
        print("  (stub/pending_review orders are already fully editable as-is.)")
        return None

    if not get_yes_no(
        f"\n  Reopen order {order_number}? This reverses its gift card debit, if any.",
        default="n",
    ):
        print("  Cancelled.")
        return None

    reversed_assignments = reverse_gift_card_assignments(order["order_id"], client)

    update_result = (
        client.table("orders")
        .update({"order_status": "pending_review"})
        .eq("order_id", order["order_id"])
        .execute()
    )
    if not update_result.data:
        print("  ERROR: failed to update order status.")
        return None

    print(f"\n  OK: order {order_number} is now pending_review and editable.")
    if reversed_assignments:
        print(f"  ({len(reversed_assignments)} gift card assignment(s) reversed.)")
    if order.get("cost_basis_state") not in (None, "estimated"):
        print("  NOTE: this order already had cost basis computed.")
        print("  Re-run agent_08_cost_basis.py Mode 1 after re-confirming -- it will")
        print("  prompt to overwrite the existing inventory units.")
    return update_result.data[0]


def _list_line_items(order_id, client):
    result = (
        client.table("line_items")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_id", order_id)
        .execute()
    )
    return result.data or []


def _edit_cancel_item(order, client):
    items = _list_line_items(order["order_id"], client)
    if not items:
        print("  No line items found.")
        return
    print("\n  LINE ITEMS:")
    for i, it in enumerate(items, 1):
        flag = " [CANCELLED]" if it.get("item_status") == "cancelled" else ""
        print(
            f"  {i}. {it['set_name']}{flag}  qty {it['quantity']} @ "
            f"${float(it['unit_price']):.2f}  (line total ${float(it['line_total']):.2f})"
        )
    idx = get_int(f"  Which item? (1-{len(items)}, 0 to cancel)", default="0")
    if not idx or idx <= 0 or idx > len(items):
        return
    item = items[idx - 1]
    if item.get("item_status") == "cancelled":
        print("  Already marked cancelled.")
        return
    if not get_yes_no(f"  Mark '{item['set_name']}' as cancelled by the retailer?", default="n"):
        return
    reason = get_input(
        "  Cancellation reason (e.g. out_of_stock_after_gwp_qualified, blank if unknown)",
        required=False,
    )
    cancelled_at = get_input(
        "  Cancelled date (YYYY-MM-DD)", required=False, default=str(date.today())
    )
    # Same convention as agent_02's initial-entry cancellation path and
    # capture_queue_promotion's ADR-029 handling: never charged, so cost
    # basis and reconciliation are zeroed regardless of what price the row
    # originally carried.
    update = {
        "item_status":         "cancelled",
        "cancellation_reason": reason,
        "cancelled_at":        cancelled_at,
        "line_total":          0,
        "line_discount":       0,
    }
    result = client.table("line_items").update(update).eq(
        "line_item_id", item["line_item_id"]
    ).execute()
    if result.data:
        print(f"  OK: '{item['set_name']}' marked cancelled (line total zeroed per ADR-029).")
    else:
        print("  ERROR: failed to update line item.")


def _edit_gift_card_amount(order, client):
    current = float(order.get("gift_card_applied") or 0)
    print(f"\n  Current gift card amount applied: ${current:.2f}")
    new_amount = get_float("  Corrected gift card amount applied ($)", default=current)
    if round(new_amount, 2) == round(current, 2):
        print("  No change.")
        return order
    result = (
        client.table("orders")
        .update({"gift_card_applied": round(new_amount, 2)})
        .eq("order_id", order["order_id"])
        .execute()
    )
    if result.data:
        print(f"  OK: gift card amount applied updated to ${new_amount:.2f}.")
        return result.data[0]
    print("  ERROR: failed to update.")
    return order


def confirm_order(client, order_number=None):
    """
    pending_review -> confirmed. If a gift card amount is on the order,
    picks the card and applies the debit -- the same atomic step a
    brand-new order goes through in agent_02_order_entry.write_order().
    """
    order_number = order_number or get_input("Order number to confirm")
    order = _find_order(order_number, client)
    if not order:
        print(f"  No order found with number {order_number}.")
        return None

    _print_order(order)
    if order.get("order_status") != "pending_review":
        print(f"\n  This order is '{order.get('order_status')}', not 'pending_review' -- nothing to confirm.")
        return None

    # Same data checks the original write ran (order_validators.py) -- an
    # item marked cancelled while reopened will legitimately make the paid
    # line items no longer sum to order.subtotal (ADR-029 deliberately
    # leaves order.subtotal/total as "what was originally confirmed," so
    # this is expected after a cancellation, not necessarily a mistake) --
    # surface it so Josh sees it before finalizing rather than silently.
    items = _list_line_items(order["order_id"], client)
    warnings = run_all_checks(
        order_id=order["order_id"],
        items=items,
        expected_subtotal=order.get("subtotal"),
        entry_method="manual",
        client=client,
    )
    print_warnings(warnings)

    if not get_yes_no(
        f"\n  Confirm order {order_number}? This locks cost-basis-affecting fields "
        f"and applies any gift card amount.",
        default="n",
    ):
        print("  Cancelled.")
        return None

    gift_card_applied = float(order.get("gift_card_applied") or 0)
    if gift_card_applied > 0:
        apply_gift_card_debit(
            order["order_id"], order["retailer"], gift_card_applied, client,
            order_number=order_number,
        )

    result = (
        client.table("orders")
        .update({"order_status": "confirmed"})
        .eq("order_id", order["order_id"])
        .execute()
    )
    if result.data:
        print(f"\n  OK: order {order_number} is confirmed.")
        return result.data[0]
    print("  ERROR: failed to update order status.")
    return None


def main():
    client = get_client()
    print("\n" + "=" * 60)
    print("  RESELLOS -- REOPEN / EDIT / RE-CONFIRM AN ORDER")
    print("=" * 60)
    order = reopen_order(client)
    if not order:
        return

    order_number = order["order_number"]
    while True:
        print("\n  What do you want to fix?")
        print("  1. Mark a line item as cancelled by the retailer")
        print("  2. Correct the gift card amount applied")
        print("  3. Done editing -- re-confirm this order now")
        print("  4. Done editing -- leave it in pending_review for now")
        choice = get_input("  Choice", default="4")
        current = _find_order(order_number, client)
        if choice == "1":
            _edit_cancel_item(current, client)
        elif choice == "2":
            _edit_gift_card_amount(current, client)
        elif choice == "3":
            confirm_order(client, order_number=order_number)
            break
        else:
            print(f"\n  Order {order_number} left in pending_review. Run this script again to finish.")
            break


if __name__ == "__main__":
    main()
