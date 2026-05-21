"""
ResellOS - Agent 02: Manual Order Entry
========================================
Captures a new order at time of purchase.
Writes to: orders -> shipments -> line_items (in correct FK order).
Confirms before every database write.

Usage: python agent_02_order_entry.py
"""

from datetime import date
from db_client import get_client, PHASE_1_USER_ID

LEGO_POINTS_PER_DOLLAR = 6.5


def get_input(prompt, required=True, default=None):
    if default:
        display = f"{prompt} [{default}]: "
    else:
        display = f"{prompt}: "
    while True:
        value = input(display).strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return None
        print("  This field is required.")


def get_float(prompt, required=True, default=None):
    while True:
        raw = get_input(prompt, required, default)
        if raw is None:
            return None
        try:
            return float(raw.replace("$", "").replace(",", ""))
        except ValueError:
            print("  Please enter a valid number (e.g. 49.99)")


def get_int(prompt, required=True, default="0"):
    while True:
        raw = get_input(prompt, required, default)
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a whole number (e.g. 1)")


def get_yes_no(prompt, default="n"):
    while True:
        raw = get_input(f"{prompt} (y/n)", default=default).lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def calculate_lego_points(eligible_spend, multiplier):
    """Calculate LEGO Insider points. Rate: 6.5 points per $1 USD."""
    return int(eligible_spend * LEGO_POINTS_PER_DOLLAR * multiplier)


def collect_line_items():
    items = []
    print("\n  -- LINE ITEMS --")
    print("  Enter each item. Type 'done' as set name when finished.")
    print()
    while True:
        print(f"  Item {len(items) + 1}:")
        set_name = get_input("    Set name or description")
        if set_name.lower() == "done":
            if not items:
                print("  At least one item is required.")
                continue
            break
        set_number = get_input("    Set number (e.g. 10242)", required=False)
        quantity = get_int("    Quantity", default="1")
        msrp = get_float("    MSRP (retail price)", required=False)
        unit_price = get_float("    Price paid per unit")
        is_gwp = get_yes_no("    Is this a GWP?")
        item = {
            "set_name": set_name,
            "set_number": set_number,
            "quantity": quantity,
            "msrp": msrp,
            "unit_price": unit_price,
            "line_discount": round((msrp - unit_price) * quantity, 2) if msrp else 0,
            "line_total": round(unit_price * quantity, 2),
            "is_gwp": is_gwp,
        }
        items.append(item)
        print(f"  Added: {set_name} x{quantity} @ ${unit_price:.2f}")
        if not get_yes_no("  Add another item?", default="y"):
            break
    return items


def collect_order():
    print("\n" + "=" * 60)
    print("  RESELLOS -- NEW ORDER ENTRY")
    print("=" * 60)
    print()

    retailer = get_input("Retailer (e.g. LEGO, Target, BN)")
    order_number = get_input("Order number")
    order_date = get_input("Order date (YYYY-MM-DD)", default=str(date.today()))

    print()
    subtotal = get_float("Subtotal (before discounts)")
    tax_paid = get_float("Tax paid", default="0")
    shipping = get_float("Shipping paid", default="0")

    print()
    print("  -- PAYMENT LAYERS --")
    gift_card_applied = get_float("Gift card amount applied", default="0")
    rewards_applied = get_float("Rewards applied ($)", default="0")
    insider_points_redeemed = get_float("Insider points redeemed ($)", default="0")

    print()
    discount_total = get_float("Total discounts applied", default="0")
    order_total = get_float("Order total (charged to card)")
    payment_method = get_input("Payment method", required=False)
    payment_method_detail = get_input(
        "Payment detail (e.g. circle_debit, business_credit_card)",
        required=False
    )

    print()
    print("  -- ORDER SETTINGS --")
    print("  Trigger: planned, planned_seasonal, community_alert,")
    print("           deal_software_alert, cashback_opportunity, self_discovered")
    purchase_trigger = get_input("Purchase trigger", default="planned")

    print("  Tax exemption: at_purchase, retroactive_adjustment, not_applicable")
    tax_exemption_method = get_input("Tax exemption method", default="not_applicable")

    pickup_method = get_input(
        "Pickup method (shipped/in_store_pickup)",
        default="shipped"
    )

    print()
    print("  -- INSIDER POINTS --")
    insider_points_multiplier = get_int("Points multiplier (1=standard, 2=double, 4=quad)", default="1")
    points_eligible_spend = subtotal - insider_points_redeemed
    calculated_points = calculate_lego_points(points_eligible_spend, insider_points_multiplier)
    print(f"  Auto-calculated: {calculated_points} points")
    print(f"  (Based on ${points_eligible_spend:.2f} eligible spend x {LEGO_POINTS_PER_DOLLAR} x {insider_points_multiplier})")
    insider_points_earned = get_int("Insider points earned", default=str(calculated_points))

    notes = get_input("Order notes (optional)", required=False)

    line_items = collect_line_items()

    order = {
        "retailer": retailer,
        "order_number": order_number,
        "order_date": order_date,
        "subtotal": subtotal,
        "tax_paid": tax_paid,
        "tax_exempt": tax_exemption_method == "at_purchase",
        "shipping": shipping,
        "gift_card_applied": gift_card_applied,
        "rewards_applied": rewards_applied,
        "insider_points_redeemed": insider_points_redeemed,
        "insider_points_earned": insider_points_earned,
        "insider_points_multiplier": insider_points_multiplier,
        "discount_total": discount_total,
        "total": order_total,
        "payment_method": payment_method,
        "payment_method_detail": payment_method_detail,
        "purchase_trigger": purchase_trigger,
        "tax_exemption_method": tax_exemption_method,
        "pickup_method": pickup_method,
        "notes": notes,
        "entry_method": "manual",
        "invoice_expected": True,
        "reconciliation_status": "pending",
        "cost_basis_state": "estimated",
        "order_status": "confirmed",
        "expected_item_count": sum(i["quantity"] for i in line_items),
        "expected_total": order_total,
    }

    return order, line_items


def print_summary(order, line_items):
    print("\n" + "=" * 60)
    print("  ORDER SUMMARY -- REVIEW BEFORE SAVING")
    print("=" * 60)
    print(f"  Retailer:        {order['retailer']}")
    print(f"  Order Number:    {order['order_number']}")
    print(f"  Order Date:      {order['order_date']}")
    print(f"  Subtotal:        ${order['subtotal']:.2f}")
    print(f"  Tax Paid:        ${order['tax_paid']:.2f}")
    print(f"  Shipping:        ${order['shipping']:.2f}")
    print(f"  Gift Card:       ${order['gift_card_applied']:.2f}")
    print(f"  Rewards:         ${order['rewards_applied']:.2f}")
    print(f"  Insider Pts Red: ${order['insider_points_redeemed']:.2f}")
    print(f"  Insider Pts Ern: {order['insider_points_earned']} pts")
    print(f"  Discounts:       ${order['discount_total']:.2f}")
    print(f"  ORDER TOTAL:     ${order['total']:.2f}")
    print(f"  Payment:         {order['payment_method'] or 'not specified'}")
    print(f"  Tax Treatment:   {order['tax_exemption_method']}")
    print(f"  Trigger:         {order['purchase_trigger']}")
    print()
    print(f"  LINE ITEMS ({len(line_items)}):")
    for i, item in enumerate(line_items, 1):
        gwp_flag = " [GWP]" if item["is_gwp"] else ""
        print(f"  {i}. {item['set_name']}{gwp_flag}")
        print(f"     Qty: {item['quantity']} | "
              f"Price: ${item['unit_price']:.2f} | "
              f"Total: ${item['line_total']:.2f}")
        if item.get("set_number"):
            print(f"     Set #: {item['set_number']}")
    print("=" * 60)


def write_order(order, line_items):
    client = get_client()

    existing = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order["order_number"])
        .execute()
    )
    if existing.data:
        print(f"\nWARNING: Order {order['order_number']} already exists.")
        if not get_yes_no("Write anyway?", default="n"):
            print("Cancelled.")
            return False

    print("\n  Writing order...")
    order_row = {**order, "user_id": PHASE_1_USER_ID}
    order_result = client.table("orders").insert(order_row).execute()
    if not order_result.data:
        print("ERROR: Failed to write order.")
        return False
    order_id = order_result.data[0]["order_id"]
    print(f"  OK: Order written (order_id: {order_id})")

    print("  Creating shipment record...")
    shipment_row = {
        "user_id": PHASE_1_USER_ID,
        "order_id": order_id,
        "shipment_status": "pending",
        "entry_method": "manual",
        "no_invoice_received": False,
    }
    shipment_result = client.table("shipments").insert(shipment_row).execute()
    if not shipment_result.data:
        print("ERROR: Failed to create shipment record.")
        return False
    shipment_id = shipment_result.data[0]["shipment_id"]
    print(f"  OK: Shipment record created (shipment_id: {shipment_id})")

    print(f"  Writing {len(line_items)} line item(s)...")
    line_item_rows = []
    for item in line_items:
        line_item_rows.append({
            "user_id": PHASE_1_USER_ID,
            "order_id": order_id,
            "shipment_id": shipment_id,
            "set_name": item["set_name"],
            "set_number": item.get("set_number"),
            "quantity": item["quantity"],
            "unit_price": item["unit_price"],
            "msrp": item.get("msrp"),
            "line_discount": item["line_discount"],
            "line_total": item["line_total"],
            "is_gwp": item["is_gwp"],
        })

    line_result = client.table("line_items").insert(line_item_rows).execute()
    if not line_result.data:
        print("ERROR: Failed to write line items.")
        return False
    print(f"  OK: {len(line_result.data)} line item(s) written")

    print("\n" + "=" * 60)
    print("  ORDER SAVED SUCCESSFULLY")
    print(f"  Order ID:    {order_id}")
    print(f"  Shipment ID: {shipment_id}")
    print(f"  Line Items:  {len(line_result.data)}")
    print("=" * 60)
    return True


def main():
    order, line_items = collect_order()
    print_summary(order, line_items)
    print()
    if get_yes_no("Save this order to the database?", default="n"):
        write_order(order, line_items)
    else:
        print("\nOrder entry cancelled. Nothing was saved.")


if __name__ == "__main__":
    main()