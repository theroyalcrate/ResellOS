"""
ResellOS - Database Writer (Agent 1A)
Takes parsed LegoInvoice objects and writes them to Supabase.

Agent 1A write path (S04+):
  orders     <- MATCH only (Agent 02 owns creation)
  shipments  <- CREATE one per invoice PDF
  line_items <- CREATE one per set, linked to shipment_id

Each invoice PDF = one shipment. Split orders produce multiple shipments
on the same order_id, which is correct and expected.
"""

from datetime import datetime
from typing import Optional

from db_client import get_client, PHASE_1_USER_ID
from invoice_parser import LegoInvoice
from order_validators import run_all_checks, print_warnings


def _parse_lego_date(date_str: Optional[str]) -> Optional[str]:
    """Convert LEGO's '04 May 2026' format to '2026-05-04' for Postgres DATE."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d %B %Y").date().isoformat()
    except ValueError:
        return None


def _calculate_subtotal(invoice: LegoInvoice) -> float:
    """Sum of net_price * quantity for all paid (non-GWP) line items."""
    return round(
        sum(item.net_price * item.quantity for item in invoice.line_items if not item.is_gwp),
        2,
    )


def _normalize_payment_method(method: Optional[str]) -> Optional[str]:
    """Map invoice payment text to DB values: gift_card / credit_card / mixed."""
    if not method:
        return None
    lower = method.lower()
    if lower == "mixed":
        return "mixed"
    if "gift" in lower:
        return "gift_card"
    if any(w in lower for w in ("credit", "visa", "mastercard", "amex", "debit")):
        return "credit_card"
    return method


def _get_yes_no(prompt: str) -> bool:
    while True:
        raw = input(f"{prompt} (y/n): ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def write_invoice(invoice: LegoInvoice) -> Optional[str]:
    """
    Match existing order, create a shipment, write line items, update reconciliation.

    Returns shipment_id (UUID) if written, None if skipped or failed.
    """
    client = get_client()

    if not invoice.order_number:
        print("SKIP: invoice has no order_number, cannot write.")
        return None

    # ------------------------------------------------------------------ #
    # Step 1: Match existing order — Agent 02 must have created it first
    # ------------------------------------------------------------------ #
    order_result = (
        client.table("orders")
        .select("order_id, order_number, total")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", invoice.order_number)
        .execute()
    )

    if not order_result.data:
        print(
            f"\nNo matching order found for {invoice.order_number}.\n"
            f"Enter it manually with Agent 02 first, then re-run."
        )
        return None

    order = order_result.data[0]
    order_id = order["order_id"]
    recorded_total = float(order["total"])

    # ------------------------------------------------------------------ #
    # Step 2: Idempotency — skip if this invoice already has a shipment
    # ------------------------------------------------------------------ #
    if invoice.invoice_number:
        existing = (
            client.table("shipments")
            .select("shipment_id")
            .eq("order_id", order_id)
            .eq("invoice_number", invoice.invoice_number)
            .execute()
        )
        if existing.data:
            shipment_id = existing.data[0]["shipment_id"]
            print(
                f"SKIP: invoice {invoice.invoice_number} already recorded "
                f"(shipment_id: {shipment_id})"
            )
            return shipment_id

    # ------------------------------------------------------------------ #
    # Step 3: Show summary and confirm before writing anything
    # ------------------------------------------------------------------ #
    calculated_subtotal = _calculate_subtotal(invoice)
    invoice_total = invoice.order_total or 0.0
    paid_items = [it for it in invoice.line_items if not it.is_gwp]
    gwp_items = [it for it in invoice.line_items if it.is_gwp]

    print("\n" + "=" * 60)
    print("  SHIPMENT WRITE SUMMARY -- REVIEW BEFORE SAVING")
    print("=" * 60)
    print(f"  Order Number:   {invoice.order_number}")
    print(f"  Order ID:       {order_id}")
    print(f"  Invoice Number: {invoice.invoice_number or 'NOT FOUND'}")
    print(f"  Invoice Date:   {invoice.invoice_date or 'NOT FOUND'}")
    if invoice.payment_legs:
        for i, (method, amount) in enumerate(invoice.payment_legs):
            label = "Payment Method:" if i == 0 else "              :"
            print(f"  {label} {method}  -${amount:.2f}")
    else:
        print(f"  Payment Method: {invoice.payment_method or 'NOT FOUND'}")
    print()
    print(f"  Subtotal:       ${calculated_subtotal:.2f}")
    print(f"  Tax:            ${invoice.tax or 0:.2f}")
    print(f"  Shipping:       $0.00")
    print(f"  Invoice Total:  ${invoice_total:.2f}")
    print(f"  Order Recorded: ${recorded_total:.2f}")
    print()
    print(f"  LINE ITEMS ({len(paid_items)} paid, {len(gwp_items)} GWP):")
    for item in paid_items + gwp_items:
        flag = " [GWP]" if item.is_gwp else ""
        desc = item.description[:30] + "..." if len(item.description) > 30 else item.description
        print(
            f"    {item.article_number:<10} {desc:<33}"
            f" x{item.quantity}  ${item.net_price:.2f}/unit{flag}"
        )
    print("=" * 60)

    # ------------------------------------------------------------------ #
    # Step 3.5: Data checks — catch cross-shipment duplicates and a few
    # other issues before anything writes. Never blocks; warns and lets
    # the person decide, same as the checks already in this codebase.
    # ------------------------------------------------------------------ #
    check_items = [
        {
            "set_number": item.set_number,
            "is_gwp": item.is_gwp,
            "unit_price": item.net_price,
            "quantity": item.quantity,
            "line_total": round(item.net_price * item.quantity, 2),
        }
        for item in invoice.line_items
    ]
    warnings = run_all_checks(
        order_id, check_items, expected_subtotal=invoice.subtotal,
        entry_method="invoice_parser", client=client,
    )
    print_warnings(warnings)

    if not _get_yes_no("\nWrite to database?"):
        print("Cancelled. Nothing was written.")
        return None

    # ------------------------------------------------------------------ #
    # Step 4: Create shipment record
    # ------------------------------------------------------------------ #
    print("\n  Creating shipment record...")
    shipment_row = {
        "user_id": PHASE_1_USER_ID,
        "order_id": order_id,
        "invoice_number": invoice.invoice_number,
        "invoice_date": _parse_lego_date(invoice.invoice_date),
        "subtotal": calculated_subtotal,
        "tax_amount": invoice.tax or 0,
        "shipping_amount": 0,
        "payment_method": _normalize_payment_method(invoice.payment_method),
        "shipment_status": "received",
        "entry_method": "invoice_parser",
        "no_invoice_received": False,
    }
    shipment_result = client.table("shipments").insert(shipment_row).execute()
    if not shipment_result.data:
        print(f"FAIL: could not create shipment for invoice {invoice.invoice_number}")
        return None
    shipment_id = shipment_result.data[0]["shipment_id"]
    print(f"  OK: Shipment created (shipment_id: {shipment_id})")

    # ------------------------------------------------------------------ #
    # Step 5: Write line items (linked to both order_id and shipment_id)
    # ------------------------------------------------------------------ #
    print(f"  Writing {len(invoice.line_items)} line item(s)...")
    line_item_rows = []
    for item in invoice.line_items:
        line_item_rows.append({
            "user_id": PHASE_1_USER_ID,
            "order_id": order_id,
            "shipment_id": shipment_id,
            "article_number": item.article_number,
            "set_name": item.description,
            "set_number": item.set_number,
            "quantity": item.quantity,
            "unit_price": item.net_price,
            "msrp": item.unit_price,
            "line_discount": round((item.unit_price - item.net_price) * item.quantity, 2),
            "line_total": round(item.net_price * item.quantity, 2),
            "is_gwp": item.is_gwp,
        })

    line_result = client.table("line_items").insert(line_item_rows).execute()
    if not line_result.data:
        print("FAIL: could not write line items — rolling back shipment")
        client.table("shipments").delete().eq("shipment_id", shipment_id).execute()
        return None
    print(f"  OK: {len(line_result.data)} line item(s) written")

    # ------------------------------------------------------------------ #
    # Step 6: Update order reconciliation_status
    # ------------------------------------------------------------------ #
    total_diff = abs(invoice_total - recorded_total)
    if total_diff <= 0.01:
        recon_status = "reconciled"
    else:
        recon_status = "discrepancy"

    client.table("orders").update(
        {"reconciliation_status": recon_status}
    ).eq("order_id", order_id).execute()

    if recon_status == "reconciled":
        print(f"  OK: Order {invoice.order_number} reconciled (totals match)")
    else:
        print(
            f"\n  Discrepancy on order {invoice.order_number} — "
            f"recorded ${recorded_total:.2f}, invoice shows ${invoice_total:.2f}. "
            f"Review before continuing."
        )

    # ------------------------------------------------------------------ #
    # Done
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 60)
    print("  SHIPMENT SAVED SUCCESSFULLY")
    print(f"  Order ID:       {order_id}")
    print(f"  Shipment ID:    {shipment_id}")
    print(f"  Line Items:     {len(line_result.data)}")
    print(f"  Reconciliation: {recon_status}")
    print("=" * 60)

    return shipment_id
