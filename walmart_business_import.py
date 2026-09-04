"""
ResellOS -- Walmart Business Order-Data CSV Import
====================================================
Parses the official "Order Data" export from business.walmart.com
(Reports/Order History) and writes orders + line_items to Supabase.

Replaces the plan to build a Walmart Business Chrome-extension content
script (SESSION_LOG "Start Here" next step as of 2026-08-22). Josh found
this export covers the same ground with less engineering: full line-item
detail, cancellations, in-store (non-eComm) transactions, and per-item
tender type, exported on demand from the Walmart Business portal.

Key quirks of this export format, all confirmed against real data
(2026-09-04 sample, orders 2026-07-09 -> 2026-09-01):

1. A row is excluded from a line item only when its OWN
   "Order Fulfillment Status" == "CANCELED". Do NOT use
   "Item Received Quantity > 0" as the inclusion test -- a just-shipped,
   still-in-transit order (status SHIPMENT) legitimately has Received
   Quantity = 0 even though it's a real, charged order (order
   200015233442473, $1199.76, confirmed 2026-09-01). For an included row,
   effective quantity = Received Quantity if > 0, else Placed Quantity
   (covers both "not yet received" and "fully received" cases; a genuine
   partial pick like order 200015005500246's Kingfisher line, placed 5 /
   received 4, still resolves correctly since received > 0 there).

2. "Order Net Total" is NOT stable across a single order's rows -- it
   reads 0.0 on any row whose OWN status is CANCELED, even though
   "Order Subtotal" / "Order Fees" / "Order SubTotal Tax" ARE stable
   (same value on every row, representing the pre-cancellation original
   cart). This script never trusts "Order Net Total" -- it rebuilds
   totals from item-level fields on the included rows only.

3. Item Id "100001" with a blank Item Name is a per-order fee line (its
   Item Fee matches "Order Fees" exactly) -- rolled into orders.shipping,
   never turned into a line item.

4. In-store ("Wmt Store (non-eComm)") purchases explode to ONE ROW PER
   PHYSICAL UNIT of the same Item Id (verified: order 130351209120772423179,
   6 identical rows, each Item Placed Quantity=1.0, summing to the order's
   Order Quantity=6.0) -- unlike online orders, which already aggregate a
   line's full quantity onto one row. In-store rows also leave
   "Item Net Total" and "Item Tax" blank (net is reconstructed from
   Item Subtotal + Item Tax + Item Fee) and leave "Tax Exemption Applied"
   blank entirely (treated as NOT exempt -- conservative, needs manual
   verification since in-store reseller-cert handling isn't confirmed).
   This script groups included rows by (Order Id, Item Id) and sums
   quantity/subtotal/net before writing one line_item per distinct item,
   matching the aggregate-quantity convention used everywhere else in
   ResellOS.

5. Per-item Payment Instrument Type (not the per-order "Payment Amount",
   which is just the order net total repeated on every row) is what lets
   gift_card_applied be computed exactly rather than guessed -- confirmed
   against order 200014941115596 (2026-07-21): item 1 ($48.00) tendered
   GIFTCARD *3201, items 2-3 ($46.50) tendered CREDITCARD *3013, summing
   to the order's $94.50 net exactly.

A whole order is skipped entirely (not written) only if EVERY row on it
is CANCELED -- i.e. nothing was ever charged, no economic activity.
Partially-canceled orders ARE written, using only the non-canceled rows.

Idempotent: an order already in Supabase (matched on retailer +
order_number) is skipped, not duplicated, on every run -- safe to
re-import overlapping export date ranges.

Never sets buy_reason or purchase_trigger (agents never guess intent or
channel -- CLAUDE.md Critical Rule #3). Lands every order at
order_status = "pending_review", same convention as
capture_queue_promotion.py, so cost basis never auto-runs on unreviewed
bulk-imported orders (DECISION 017).

Usage:
  python walmart_business_import.py --file <path/to/export.csv> --mode preview
  python walmart_business_import.py --file <path/to/export.csv> --mode import
"""

import argparse
import csv
import re
import sys
from collections import OrderedDict
from pathlib import Path

from db_client import get_client, PHASE_1_USER_ID

RETAILER = "walmart_business"
ENTRY_METHOD = "walmart_business_csv_import"

_SET_NUMBER_RE = re.compile(r"-\s*(\d{4,6})\s*$")


def _f(row, key):
    """Float-parse a CSV cell, treating blank as 0.0."""
    val = (row.get(key) or "").strip()
    return float(val) if val else 0.0


def load_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def group_by_order(rows):
    orders = OrderedDict()
    for row in rows:
        orders.setdefault(row["Order Id"], []).append(row)
    return orders


def _parse_set_number(item_name):
    m = _SET_NUMBER_RE.search(item_name or "")
    return m.group(1) if m else None


def _pickup_method(fulfillment_method):
    fm = (fulfillment_method or "").strip()
    if fm == "DELIVERY":
        return "shipped"
    if fm == "PICKUP":
        return "pickup"
    if fm == "Wmt Store (non-eComm)":
        return "in_store"
    return fm or "shipped"


def _item_net(row):
    """Item Net Total if given, else reconstructed from subtotal+tax+fee
    (needed for in-store rows, which leave Item Net Total blank)."""
    raw = (row.get("Item Net Total") or "").strip()
    if raw:
        return float(raw)
    return round(_f(row, "Item Subtotal") + _f(row, "Item Tax") + _f(row, "Item Fee"), 2)


def _effective_qty(row):
    received = _f(row, "Item Received Quantity")
    if received > 0:
        return received
    return _f(row, "Item Placed Quantity")


def build_order(order_id, rows):
    """Returns (order_dict, line_items, skip_reason). skip_reason is a
    string if this order should not be written (fully canceled), else None.
    """
    included = [
        r for r in rows
        if r.get("Order Fulfillment Status") != "CANCELED" and (r.get("Item Name") or "").strip()
    ]
    fee_rows = [
        r for r in rows
        if r.get("Order Fulfillment Status") != "CANCELED" and not (r.get("Item Name") or "").strip()
    ]
    canceled_rows = [r for r in rows if r.get("Order Fulfillment Status") == "CANCELED"]

    if not included:
        return None, None, "fully canceled -- no non-canceled items"

    first = rows[0]

    subtotal = round(sum(_f(r, "Item Subtotal") for r in included), 2)
    item_net_sum = round(sum(_item_net(r) for r in included), 2)
    tax_paid = round(sum(_f(r, "Item Tax") for r in included) + sum(_f(r, "Item Tax") for r in fee_rows), 2)
    order_fee = round(sum(_f(r, "Item Fee") for r in fee_rows), 2)
    total = round(item_net_sum + order_fee, 2)

    gift_card_applied = round(
        sum(_item_net(r) for r in included if r.get("Payment Instrument Type") == "GIFTCARD"), 2
    )
    credit_total = round(total - gift_card_applied, 2)

    tender_ids = sorted({r.get("Payment Identifier") for r in included if r.get("Payment Identifier")})
    if gift_card_applied > 0 and credit_total > 0.01:
        payment_method = "mixed"
    elif gift_card_applied > 0:
        payment_method = "gift_card"
    elif credit_total > 0:
        payment_method = "credit_card"
    else:
        payment_method = None

    tax_flags = {r.get("Tax Exemption Applied") or "(blank)" for r in included}
    tax_exempt = tax_flags == {"Y"}
    mixed_tax_flag = len(tax_flags) > 1
    blank_tax_flag = "(blank)" in tax_flags

    fulfillment_method = first.get("Fulfillment Method") or ""

    canceled_names = [r["Item Name"] for r in canceled_rows if (r.get("Item Name") or "").strip()]

    notes_parts = [f"Imported from Walmart Business order-data export (order {order_id})."]
    if order_fee:
        notes_parts.append(f"Includes ${order_fee:.2f} Walmart order fee, folded into shipping.")
    if blank_tax_flag:
        notes_parts.append(
            "Tax-exemption flag was blank (in-store purchase) -- treated as tax_exempt=False; "
            "verify reseller-cert handling for in-store manually."
        )
    elif mixed_tax_flag:
        notes_parts.append(
            "Tax-exemption flag was NOT uniform across line items on this order "
            "-- treated as tax_exempt=False; verify manually."
        )
    if gift_card_applied > 0:
        notes_parts.append(
            f"${gift_card_applied:.2f} of this order was tendered by gift card "
            f"({', '.join(tender_ids)}) -- unusual for Walmart Business per Josh "
            f"(almost always business credit card). Not linked to any existing "
            f"gift_cards row -- verify origin if it matters for cost basis."
        )
    if canceled_names:
        notes_parts.append(
            f"{len(canceled_names)} line item(s) on this order were canceled and excluded: "
            + "; ".join(n[:60] for n in canceled_names)
        )
    if fulfillment_method == "Wmt Store (non-eComm)":
        notes_parts.append(
            "In-store (non-eComm) purchase -- new fulfillment channel, not previously "
            "modeled in ResellOS. Payment Instrument Type reads 'Visa' rather than "
            "'CREDITCARD' for this channel; export explodes one row per physical unit "
            "(aggregated back into per-item quantities on import)."
        )
    any_in_transit = any(
        r.get("Order Fulfillment Status") == "SHIPMENT" and _f(r, "Item Received Quantity") == 0
        for r in included
    )
    if any_in_transit:
        notes_parts.append(
            "Order still shows Received Quantity=0 as of export date (in transit) -- "
            "quantity/total here reflect the placed order, not a confirmed delivery."
        )

    order = {
        "user_id": PHASE_1_USER_ID,
        "retailer": RETAILER,
        "order_number": order_id,
        "order_date": first["Order Date"],
        "subtotal": subtotal,
        "shipping": order_fee,
        "tax_paid": tax_paid,
        "tax_exempt": tax_exempt,
        "tax_exemption_method": "at_purchase" if tax_exempt else "not_applicable",
        "discount_total": 0,
        "gift_card_applied": gift_card_applied,
        "rewards_applied": 0,
        "total": total,
        "payment_method": payment_method,
        "payment_method_detail": ", ".join(tender_ids) if tender_ids else None,
        "insider_points_earned": 0,
        "insider_points_redeemed": 0,
        "insider_points_multiplier": 1,
        "purchase_trigger": None,
        "buy_reason": None,
        "pickup_method": _pickup_method(fulfillment_method),
        "notes": " ".join(notes_parts),
        "entry_method": ENTRY_METHOD,
        "invoice_expected": False,
        "reconciliation_status": "pending",
        "cost_basis_state": "estimated",
        "order_status": "pending_review",
    }

    # Aggregate by Item Id -- in-store rows explode to one row per physical
    # unit; online rows already carry the full line quantity on one row, so
    # this is a no-op for them.
    groups = OrderedDict()
    for r in included:
        key = r.get("Item Id")
        groups.setdefault(key, []).append(r)

    line_items = []
    for item_id, group_rows in groups.items():
        rep = group_rows[0]
        qty = int(round(sum(_effective_qty(r) for r in group_rows)))
        item_subtotal = round(sum(_f(r, "Item Subtotal") for r in group_rows), 2)
        item_net = round(sum(_item_net(r) for r in group_rows), 2)
        unit_price = _f(rep, "Purchase PPU")
        set_number = _parse_set_number(rep.get("Item Name"))
        notes = f"Walmart Item ID {item_id}"
        if rep.get("Walmart Product Sub Category"):
            notes += f"; category: {rep.get('Walmart Product Category')}/{rep.get('Walmart Product Sub Category')}"
        if set_number:
            notes += "; set_number parsed from title, not confirmed against a printed set number"
        if len(group_rows) > 1:
            notes += f"; {len(group_rows)} export rows aggregated into this line (in-store per-unit rows)"
        line_items.append({
            "user_id": PHASE_1_USER_ID,
            "set_name": rep["Item Name"],
            "set_number": set_number,
            "quantity": qty,
            "unit_price": unit_price,
            "line_discount": round(unit_price * qty - item_subtotal, 2),
            "line_total": item_net,
            "is_gwp": False,
            "is_retiring": True,
            "notes": notes,
        })

    expected_item_count = sum(li["quantity"] for li in line_items)
    order["expected_item_count"] = expected_item_count
    order["expected_total"] = total

    return order, line_items, None


def order_exists(client, order_number):
    result = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("retailer", RETAILER)
        .eq("order_number", order_number)
        .execute()
    )
    return bool(result.data)


def write_order(client, order, line_items):
    result = client.table("orders").insert(order).execute()
    order_id = result.data[0]["order_id"]
    for item in line_items:
        item["order_id"] = order_id
    client.table("line_items").insert(line_items).execute()
    return order_id


def main():
    parser = argparse.ArgumentParser(description="Import Walmart Business order-data CSV export.")
    parser.add_argument("--file", required=True, help="Path to the exported CSV.")
    parser.add_argument("--mode", choices=["preview", "import"], default="preview")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(1)

    rows = load_rows(path)
    orders_by_id = group_by_order(rows)

    print(f"Loaded {len(rows)} rows -> {len(orders_by_id)} distinct orders from {path.name}\n")

    client = get_client() if args.mode == "import" else None

    written, skipped_dupe, skipped_canceled = 0, 0, 0
    total_written = 0.0

    for order_id, order_rows in orders_by_id.items():
        order, line_items, skip_reason = build_order(order_id, order_rows)

        if skip_reason:
            skipped_canceled += 1
            print(f"  SKIP  {order_id}  ({skip_reason})")
            continue

        if args.mode == "import" and order_exists(client, order_id):
            skipped_dupe += 1
            print(f"  SKIP  {order_id}  (already in Supabase)")
            continue

        tag = "WOULD WRITE" if args.mode == "preview" else "WRITE"
        print(
            f"  {tag}  {order_id}  {order['order_date']}  "
            f"${order['total']:.2f}  {len(line_items)} line item(s)  "
            f"pay={order['payment_method']}  pickup={order['pickup_method']}"
        )

        if args.mode == "import":
            write_order(client, order, line_items)

        written += 1
        total_written += order["total"]

    print(
        f"\n{'Would write' if args.mode == 'preview' else 'Wrote'} {written} order(s), "
        f"total ${total_written:.2f}. "
        f"Skipped {skipped_canceled} fully-canceled, {skipped_dupe} already-imported."
    )


if __name__ == "__main__":
    main()
