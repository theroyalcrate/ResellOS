"""
Tests for walmart_business_import.py -- pure parsing/aggregation logic only,
no network/Supabase calls. Uses the real 2026-09-04 export archived at
walmart_business_imports/walmart_business_order_export_2026-09-04.csv as a
fixture, targeting the three quirks that a naive parse gets wrong (see the
docstring in walmart_business_import.py for how each was found):

  1. An in-transit SHIPMENT order (Received Quantity=0, not canceled) must
     still be written, using Placed Quantity.
  2. A partial cancellation must total correctly despite "Order Net Total"
     reading 0.0 on the CANCELED row of that same order.
  3. An in-store purchase's one-row-per-physical-unit rows must aggregate
     into one line item per Item Id.

Run: python -m pytest tests/test_walmart_business_import.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from walmart_business_import import build_order, group_by_order, load_rows

FIXTURE = (
    Path(__file__).parent.parent
    / "walmart_business_imports"
    / "walmart_business_order_export_2026-09-04.csv"
)


def _orders():
    rows = load_rows(FIXTURE)
    return group_by_order(rows)


def test_fully_canceled_order_is_skipped():
    orders = _orders()
    order, items, skip_reason = build_order(
        "200015130208388", orders["200015130208388"]
    )
    assert order is None
    assert items is None
    assert skip_reason == "fully canceled -- no non-canceled items"


def test_in_transit_shipment_uses_placed_quantity_not_received():
    """Order 200015233442473: SHIPMENT status, Received Quantity=0 (still in
    transit as of export date) -- must NOT be treated as canceled/skipped."""
    orders = _orders()
    order, items, skip_reason = build_order(
        "200015233442473", orders["200015233442473"]
    )
    assert skip_reason is None
    assert order["total"] == 1199.76
    assert order["gift_card_applied"] == 1199.76
    assert order["payment_method"] == "gift_card"
    assert len(items) == 1
    assert items[0]["quantity"] == 8  # Placed, since Received was 0


def test_partial_cancellation_totals_use_received_rows_only():
    """Order 200015009258127: 1 canceled item (Cristiano Ronaldo set) + 2
    received items + 1 fee pseudo-row. "Order Net Total" reads 0.0 on the
    CANCELED row itself -- must not be mistaken for the whole order's total."""
    orders = _orders()
    order, items, skip_reason = build_order(
        "200015009258127", orders["200015009258127"]
    )
    assert skip_reason is None
    assert order["total"] == 111.74
    assert order["shipping"] == 0.24  # the fee pseudo-row, folded in
    assert len(items) == 2  # canceled item and fee row both excluded
    assert "Cristiano Ronaldo" in order["notes"]


def test_in_store_rows_aggregate_by_item_id():
    """Order 130351209120772423179: 6 identical export rows (one per
    physical unit scanned in-store) for the same Item Id -- must collapse
    into a single line item with quantity=6, not six quantity=1 rows."""
    orders = _orders()
    order, items, skip_reason = build_order(
        "130351209120772423179", orders["130351209120772423179"]
    )
    assert skip_reason is None
    assert len(items) == 1
    assert items[0]["quantity"] == 6
    assert items[0]["line_total"] == 246.0
    assert order["total"] == 246.0
    assert order["tax_exempt"] is False  # blank flag -> conservative False
    assert order["pickup_method"] == "in_store"


def test_mixed_tender_splits_gift_card_from_credit_by_line():
    """Order 200014941115596: item 1 tendered by gift card, items 2-3 by
    credit card -- gift_card_applied must reflect only the gift-card line,
    not the whole order."""
    orders = _orders()
    order, items, skip_reason = build_order(
        "200014941115596", orders["200014941115596"]
    )
    assert skip_reason is None
    assert order["gift_card_applied"] == 48.0
    assert order["payment_method"] == "mixed"
    assert order["total"] == 94.5


def test_full_file_totals_match_known_good_run():
    """Regression guard: whole-file summary as verified 2026-09-04 against
    Supabase after import (26 orders, $7167.34, 58 line items total)."""
    orders = _orders()
    written, total, item_count = 0, 0.0, 0
    for order_id, rows in orders.items():
        order, items, skip_reason = build_order(order_id, rows)
        if skip_reason:
            continue
        written += 1
        total += order["total"]
        item_count += len(items)
    assert written == 26
    assert round(total, 2) == 7167.34
    assert item_count == 58
