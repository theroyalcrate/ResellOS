"""
LEGO Invoice PDF Parser
Extracts order/invoice metadata, line items, totals, and payment info.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
except ImportError:
    print("pdfplumber not installed. Run: pip install pdfplumber")
    sys.exit(1)


@dataclass
class LineItem:
    article_number: str
    description: str
    quantity: int
    unit_price: float       # retail price per unit (before discount)
    net_price: float        # price per unit actually paid (0.00 for GWP)
    is_gwp: bool = False


@dataclass
class LegoInvoice:
    order_number: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    order_date: Optional[str] = None
    shipping_address: Optional[str] = None
    line_items: list[LineItem] = field(default_factory=list)
    subtotal: Optional[float] = None
    insider_points_redeemed: Optional[float] = None
    tax: Optional[float] = None
    order_total: Optional[float] = None
    payment_method: Optional[str] = None
    payment_legs: list[tuple[str, float]] = field(default_factory=list)


def _parse_num(s: str) -> float:
    return float(re.sub(r"[^\d.]", "", s))


def _parse_net_price(unit_price: float, rest: str) -> float:
    """
    Derive per-unit net price from the trailing tokens after unit_price.

    Observed column patterns (all after article / description / qty / unit_price):
      <nothing>                       → no discount, net = unit_price
      <net_amount>                    → no discount, net = unit_price
      <discount> <net_unit> <net_amt> → discounted; net = net_unit (middle value)
      <discount> Free Free            → GWP; net = 0.00
      Free Free                       → GWP; net = 0.00
    """
    if not rest or not rest.strip():
        return unit_price

    if re.search(r"\bfree\b", rest, re.IGNORECASE):
        return 0.0

    nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+\.\d{2}", rest)]

    if len(nums) >= 2:
        # First number is discount amount, second is net price per unit
        return nums[1]

    # Only net_amount present (= unit_price when no discount)
    return unit_price


def extract_shipping_address(page) -> Optional[str]:
    """
    LEGO receipts have Ship-to and Bill-to side by side.
    Isolate the Ship-to column using word x-coordinates.
    """
    words = page.extract_words()
    if not words:
        return None

    ship_x0 = bill_x0 = ship_y_bottom = None

    for i, w in enumerate(words):
        text = w["text"].lower()
        nxt = words[i + 1]["text"].lower() if i + 1 < len(words) else ""
        if text == "ship" and nxt.startswith("to"):
            ship_x0 = w["x0"]
            ship_y_bottom = w["bottom"]
        if text == "bill" and nxt.startswith("to"):
            bill_x0 = w["x0"]

    if ship_x0 is None:
        return None

    # Determine which column is ship-to by comparing x positions.
    # If bill_x0 is to the right of ship_x0, ship-to is the LEFT column;
    # otherwise ship-to is the RIGHT column.
    if bill_x0 is not None and bill_x0 > ship_x0:
        # Ship-to is left column
        x_min, x_max = 0, (ship_x0 + bill_x0) / 2
    elif bill_x0 is not None:
        # Ship-to is right column
        x_min, x_max = (ship_x0 + bill_x0) / 2, page.width
    else:
        x_min, x_max = 0, page.width / 2

    rows: dict[int, list[str]] = {}
    for w in words:
        if x_min <= w["x0"] < x_max and w["top"] > ship_y_bottom:
            key = round(w["top"])
            rows.setdefault(key, []).append(w["text"])

    addr_lines = []
    for y in sorted(rows):
        line = " ".join(rows[y])
        if re.search(r"Order\s*No|Invoice\s*No|Page\s+\d", line, re.IGNORECASE):
            break
        addr_lines.append(line)

    return "\n".join(addr_lines) if addr_lines else None


def parse_invoice(pdf_path: str) -> LegoInvoice:
    invoice = LegoInvoice()

    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        invoice.shipping_address = extract_shipping_address(pdf.pages[0])

    lines = full_text.splitlines()

    # ------------------------------------------------------------------ #
    # Header: two-line label/value block
    #   "LEGO Order No.  Order Date  Invoice No.  Invoice Date  Customer No."
    #   "T503829514  04 May 2026  1354010867  04 May 2026  856470391"
    # ------------------------------------------------------------------ #
    header_re = re.compile(
        r"(?:LEGO\s+)?Order\s+No\..*?Invoice\s+No\..*?Invoice\s+Date",
        re.IGNORECASE,
    )
    for i, line in enumerate(lines):
        if header_re.search(line) and i + 1 < len(lines):
            m = re.match(
                r"(\S+)\s+(\d{1,2}\s+\w+\s+\d{4})\s+(\S+)\s+(\d{1,2}\s+\w+\s+\d{4})",
                lines[i + 1].strip(),
            )
            if m:
                invoice.order_number = m.group(1)
                invoice.order_date = m.group(2)
                invoice.invoice_number = m.group(3)
                invoice.invoice_date = m.group(4)
            break

    # Fallback single-line patterns
    for line in lines:
        s = line.strip()
        if invoice.order_number is None:
            m = re.search(r"Order\s*(?:number|#|no\.?)[:\s]+([A-Z0-9\-]+)", s, re.IGNORECASE)
            if m:
                invoice.order_number = m.group(1).strip()
        if invoice.invoice_number is None:
            m = re.search(r"Invoice\s*(?:number|#|no\.?)[:\s]+([A-Z0-9\-]+)", s, re.IGNORECASE)
            if m:
                invoice.invoice_number = m.group(1).strip()
        if invoice.invoice_date is None:
            m = re.search(r"Invoice\s*date[:\s]+([A-Za-z0-9,\s/\-\.]+?)(?:\n|$)", s, re.IGNORECASE)
            if m:
                invoice.invoice_date = m.group(1).strip()
        if invoice.order_date is None:
            m = re.search(r"Order\s*date[:\s]+([A-Za-z0-9,\s/\-\.]+?)(?:\n|$)", s, re.IGNORECASE)
            if m:
                invoice.order_date = m.group(1).strip()

    # ------------------------------------------------------------------ #
    # Line items
    #
    # Column layout (header row):
    #   Article | Product Description | Quantity | Unit Price | Discount | Net Price | Net Amount
    #
    # Observed trailing-token patterns after unit_price:
    #   <net_amount>                    → no discount (net_price = unit_price)
    #   <discount> <net_unit> <net_amt> → discounted item
    #   <discount> Free Free            → GWP (net_price = 0.00)
    #
    # All observed descriptions end with a version tag "V<digits>" (e.g. V39).
    # Using that as an anchor prevents the lazy description match from stopping
    # on the set number embedded at the start of each description.
    # ------------------------------------------------------------------ #
    item_anchored = re.compile(
        r"(\d{6,8})\s+"        # article number (6-8 digit internal code)
        r"(.+?V\d+)\s+"        # description ending with version tag
        r"(\d{1,3})\s+"        # quantity
        r"([\d,]+\.\d{2})"     # unit price
        r"(.*?)$"              # rest: discount / net price / net amount / Free
    )
    # Fallback without version-tag anchor
    item_fallback = re.compile(
        r"(\d{6,8})\s+"
        r"(.+?)\s+"
        r"(\d{1,3})\s+"
        r"([\d,]+\.\d{2})"
        r"(.*?)$"
    )

    for line in lines:
        m = item_anchored.search(line) or item_fallback.search(line)
        if not m:
            continue
        unit_price = _parse_num(m.group(4))
        rest = m.group(5)
        net_price = _parse_net_price(unit_price, rest)
        invoice.line_items.append(
            LineItem(
                article_number=m.group(1),
                description=m.group(2).strip(),
                quantity=int(m.group(3)),
                unit_price=unit_price,
                net_price=net_price,
                is_gwp=(net_price == 0.0),
            )
        )

    # ------------------------------------------------------------------ #
    # Totals
    # ------------------------------------------------------------------ #
    for line in lines:
        s = line.strip()

        if invoice.subtotal is None:
            m = re.search(r"^Subtotal\s+([\d,]+\.\d{2})$", s, re.IGNORECASE)
            if m:
                invoice.subtotal = _parse_num(m.group(1))

        if invoice.insider_points_redeemed is None:
            m = re.search(
                r"LEGO\s+Insiders?\s+Points?\s+Redeem\s+([-\d,]+\.\d{2})",
                s,
                re.IGNORECASE,
            )
            if m:
                # Store as a positive value (it appears as negative in the invoice)
                invoice.insider_points_redeemed = abs(_parse_num(m.group(1)))

        if invoice.tax is None:
            m = re.search(
                r"^(?:Tax|Sales\s*tax|VAT|GST|HST)\s+([\d,]+\.\d{2})$",
                s,
                re.IGNORECASE,
            )
            if m:
                invoice.tax = _parse_num(m.group(1))

        if invoice.order_total is None:
            m = re.search(
                r"^(?:Invoice\s+Total|Order\s+Total|Grand\s+Total)\s+([\d,]+\.\d{2})$",
                s,
                re.IGNORECASE,
            )
            if m:
                invoice.order_total = _parse_num(m.group(1))

    # ------------------------------------------------------------------ #
    # Payment method
    # "Paid by gift card -180.42"  /  "Paid by Credit Card -19.89"
    # Balance line "Credit card 0.00" is intentionally excluded by
    # requiring a negative amount marker after the method name.
    # Split payments produce multiple "Paid by" lines; collect all of them.
    # ------------------------------------------------------------------ #
    for line in lines:
        s = line.strip()
        m = re.search(r"^Paid\s+by\s+(.+?)\s+-([\d,]+\.\d{2})$", s, re.IGNORECASE)
        if m:
            invoice.payment_legs.append(
                (m.group(1).strip(), float(m.group(2).replace(",", "")))
            )

    if len(invoice.payment_legs) == 1:
        invoice.payment_method = invoice.payment_legs[0][0]
    elif len(invoice.payment_legs) > 1:
        invoice.payment_method = "mixed"

    return invoice


def print_invoice(invoice: LegoInvoice, filename: str = "") -> None:
    sep = "-" * 74

    print("\n" + "=" * 74)
    if filename:
        print(f"  {filename}")
    print("  LEGO INVOICE SUMMARY")
    print("=" * 74)

    print(f"\n{'Order Number:':<26} {invoice.order_number or 'NOT FOUND'}")
    print(f"{'Invoice Number:':<26} {invoice.invoice_number or 'NOT FOUND'}")
    print(f"{'Invoice Date:':<26} {invoice.invoice_date or 'NOT FOUND'}")
    print(f"{'Order Date:':<26} {invoice.order_date or 'NOT FOUND'}")

    print(f"\n{'Shipping Address:'}")
    if invoice.shipping_address:
        for addr_line in invoice.shipping_address.splitlines():
            print(f"  {addr_line}")
    else:
        print("  NOT FOUND")

    print(f"\n{sep}")
    print(f"{'LINE ITEMS':^74}")
    print(sep)

    if invoice.line_items:
        gwp_items = [it for it in invoice.line_items if it.is_gwp]
        paid_items = [it for it in invoice.line_items if not it.is_gwp]

        hdr = f"{'Article':<10} {'Description':<32} {'Qty':>4} {'Unit':>8} {'Net/Unit':>9} {'Discount':>9}"
        print(hdr)
        print(sep)

        for item in paid_items + gwp_items:
            desc = item.description[:31] + "…" if len(item.description) > 32 else item.description
            discount = item.unit_price - item.net_price
            disc_str = f"-${discount:.2f}" if discount > 0 else ""
            flag = "  [GWP]" if item.is_gwp else ""
            print(
                f"{item.article_number:<10} {desc:<32} {item.quantity:>4} "
                f"${item.unit_price:>7.2f} ${item.net_price:>8.2f} {disc_str:>9}{flag}"
            )
    else:
        print("  No line items extracted.")

    print(sep)

    def fmt(val: Optional[float]) -> str:
        return f"${val:,.2f}" if val is not None else "NOT FOUND"

    print(f"\n{'Subtotal:':<26} {fmt(invoice.subtotal)}")
    if invoice.insider_points_redeemed is not None:
        print(f"{'Insider Points Redeemed:':<26} -{fmt(invoice.insider_points_redeemed)}")
    print(f"{'Tax:':<26} {fmt(invoice.tax)}")
    print(f"{'Order Total:':<26} {fmt(invoice.order_total)}")
    if invoice.payment_legs:
        for i, (method, amount) in enumerate(invoice.payment_legs):
            label = "Payment Method:" if i == 0 else ""
            print(f"\n{label:<26} {method}  -${amount:.2f}")
    else:
        print(f"\n{'Payment Method:':<26} {invoice.payment_method or 'NOT FOUND'}")
    print("\n" + "=" * 74 + "\n")
def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python invoice_parser.py <invoice.pdf> [--db]")
        print("  --db    Write parsed invoices to the database")
        sys.exit(1)

    write_to_db = "--db" in sys.argv
    pdf_paths = [a for a in sys.argv[1:] if a != "--db"]

    for pdf_path in pdf_paths:
        if not Path(pdf_path).exists():
            print(f"File not found: {pdf_path}")
            continue
        invoice = parse_invoice(pdf_path)
        print_invoice(invoice, filename=Path(pdf_path).name)

        if write_to_db:
            from db_writer import write_invoice
            write_invoice(invoice)
            print()




if __name__ == "__main__":
    main()
