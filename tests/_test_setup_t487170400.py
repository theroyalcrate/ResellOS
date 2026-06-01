"""
Test setup script — Order T487170400 (2025-12-03 LEGO)
=======================================================
Inserts the verification order for Agent 08 cost basis testing.
Idempotent: skips any record that already exists.

Requires migration 009 to be applied before running.

Order data:
  Subtotal:          $151.95
  Gift card applied: $167.75  (purchased for $150.98 → savings $16.77)
  Tax:               $15.80
  Total charged:     $0.00

Paid items:
  Moana's Flowerpot   43252  qty 3  @ $39.99  → $119.97
  Wednesday and Enid  40750  qty 1  @ $11.99  → $11.99
  The Armory          21252  qty 1  @ $19.99  → $19.99

GWP items (status: sold, proceeds: to be entered in Agent 08):
  Micro Ninjago City Gardens  40705  qty 1
  Magic Maze                  40596  qty 1
  Winter Gazebo               40778  qty 1
"""

from db_client import get_client, PHASE_1_USER_ID

ORDER_NUMBER = "T487170400"

PAID_ITEMS = [
    {"set_name": "Moana's Flowerpot",  "set_number": "43252", "quantity": 3, "unit_price": 39.99, "line_total": 119.97, "is_retiring": True},
    {"set_name": "Wednesday and Enid", "set_number": "40750", "quantity": 1, "unit_price": 11.99, "line_total": 11.99,  "is_retiring": True},
    {"set_name": "The Armory",         "set_number": "21252", "quantity": 1, "unit_price": 19.99, "line_total": 19.99,  "is_retiring": True},
]

GWP_ITEMS = [
    {"set_name": "Micro Ninjago City Gardens", "set_number": "40705", "quantity": 1},
    {"set_name": "Magic Maze",                  "set_number": "40596", "quantity": 1},
    {"set_name": "Winter Gazebo",               "set_number": "40778", "quantity": 1},
]


def main():
    client = get_client()
    print(f"\nSetting up verification order {ORDER_NUMBER}...\n")

    # ---------------------------------------------------------------- Order
    existing_order = (
        client.table("orders")
        .select("order_id, cost_basis_state")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", ORDER_NUMBER)
        .execute()
    )

    if existing_order.data:
        order_id = existing_order.data[0]["order_id"]
        state    = existing_order.data[0].get("cost_basis_state")
        print(f"  Order already exists (order_id: {order_id}, state: {state})")
    else:
        order_row = {
            "user_id":                  PHASE_1_USER_ID,
            "retailer":                 "LEGO",
            "order_number":             ORDER_NUMBER,
            "order_date":               "2025-12-03",
            "subtotal":                 151.95,
            "tax_paid":                 15.80,
            "tax_exempt":               False,
            "discount_total":           0,
            "gift_card_applied":        167.75,
            "rewards_applied":          0,
            "insider_points_redeemed":  0,
            "insider_points_earned":    988,
            "insider_points_multiplier": 1,
            "total":                    0,
            "payment_method":           "gift_card",
            "payment_method_detail":    "gift_card",
            "purchase_trigger":         "planned",
            "tax_exemption_method":     "not_applicable",
            "pickup_method":            "shipped",
            "buy_reason":               "sale_gwp",
            "entry_method":             "manual",
            "invoice_expected":         True,
            "reconciliation_status":    "pending",
            "cost_basis_state":         "estimated",
            "order_status":             "confirmed",
            "expected_item_count":      8,
            "expected_total":           0,
        }
        result = client.table("orders").insert(order_row).execute()
        if not result.data:
            print("  ERROR: Failed to insert order.")
            return
        order_id = result.data[0]["order_id"]
        print(f"  OK: Order inserted (order_id: {order_id})")

    # -------------------------------------------------------------- Shipment
    existing_shipment = (
        client.table("shipments")
        .select("shipment_id")
        .eq("order_id", order_id)
        .execute()
    )

    if existing_shipment.data:
        shipment_id = existing_shipment.data[0]["shipment_id"]
        print(f"  Shipment already exists (shipment_id: {shipment_id})")
    else:
        shipment_row = {
            "user_id":              PHASE_1_USER_ID,
            "order_id":             order_id,
            "subtotal":             151.95,
            "tax_amount":           15.80,
            "shipping_amount":      0,
            "shipment_status":      "received",
            "entry_method":         "manual",
            "no_invoice_received":  False,
        }
        result = client.table("shipments").insert(shipment_row).execute()
        if not result.data:
            print("  ERROR: Failed to insert shipment.")
            return
        shipment_id = result.data[0]["shipment_id"]
        print(f"  OK: Shipment inserted (shipment_id: {shipment_id})")

    # ----------------------------------------------------------- Line items
    existing_items = (
        client.table("line_items")
        .select("line_item_id, set_number, is_gwp")
        .eq("order_id", order_id)
        .execute()
    )
    existing_set_numbers = {r["set_number"] for r in (existing_items.data or [])}

    gwp_line_item_ids = {}  # set_number -> line_item_id (for GWP records)
    for r in (existing_items.data or []):
        if r.get("is_gwp"):
            gwp_line_item_ids[r["set_number"]] = r["line_item_id"]

    items_to_insert = []
    for item in PAID_ITEMS:
        if item["set_number"] not in existing_set_numbers:
            items_to_insert.append({
                "user_id":      PHASE_1_USER_ID,
                "order_id":     order_id,
                "shipment_id":  shipment_id,
                "set_name":     item["set_name"],
                "set_number":   item["set_number"],
                "quantity":     item["quantity"],
                "unit_price":   item["unit_price"],
                "msrp":         item["unit_price"],
                "line_discount": 0,
                "line_total":   item["line_total"],
                "is_gwp":       False,
                "is_retiring":  item["is_retiring"],
            })

    for item in GWP_ITEMS:
        if item["set_number"] not in existing_set_numbers:
            items_to_insert.append({
                "user_id":      PHASE_1_USER_ID,
                "order_id":     order_id,
                "shipment_id":  shipment_id,
                "set_name":     item["set_name"],
                "set_number":   item["set_number"],
                "quantity":     item["quantity"],
                "unit_price":   0,
                "msrp":         0,
                "line_discount": 0,
                "line_total":   0,
                "is_gwp":       True,
                "is_retiring":  False,
            })

    if items_to_insert:
        result = client.table("line_items").insert(items_to_insert).execute()
        if not result.data:
            print("  ERROR: Failed to insert line items.")
            return
        print(f"  OK: {len(result.data)} line item(s) inserted")
        for r in result.data:
            if r.get("is_gwp"):
                gwp_line_item_ids[r["set_number"]] = r["line_item_id"]
    else:
        print(f"  Line items already exist ({len(existing_set_numbers)} set(s))")

    # If we didn't just insert GWP items, pull their IDs from the existing records
    if not gwp_line_item_ids:
        for r in (existing_items.data or []):
            if r.get("is_gwp"):
                gwp_line_item_ids[r["set_number"]] = r["line_item_id"]

    # ---------------------------------------------------------- GWP records
    existing_gwp = (
        client.table("gwp")
        .select("gwp_id, set_number, status, net_proceeds")
        .eq("order_id", order_id)
        .execute()
    )
    existing_gwp_set_numbers = {r["set_number"] for r in (existing_gwp.data or [])}

    gwp_to_insert = []
    for item in GWP_ITEMS:
        if item["set_number"] not in existing_gwp_set_numbers:
            li_id = gwp_line_item_ids.get(item["set_number"])
            gwp_to_insert.append({
                "user_id":         PHASE_1_USER_ID,
                "order_id":        order_id,
                "line_item_id":    li_id,
                "set_number":      item["set_number"],
                "set_name":        item["set_name"],
                "allocation_method": "proceeds_reduce_order",
                "status":          "sold",
            })

    if gwp_to_insert:
        result = client.table("gwp").insert(gwp_to_insert).execute()
        if not result.data:
            print("  ERROR: Failed to insert GWP records.")
            return
        print(f"  OK: {len(result.data)} GWP record(s) inserted (status: sold, proceeds: TBD)")
    else:
        print(f"  GWP records already exist")
        for r in (existing_gwp.data or []):
            proc = f"${float(r['net_proceeds']):.2f}" if r.get("net_proceeds") else "TBD"
            print(f"    {r['set_number']}  status={r['status']}  proceeds={proc}")

    print(f"\n  Setup complete. Run Agent 08 Mode 1 with order number: {ORDER_NUMBER}")
    print()


if __name__ == "__main__":
    main()
