"""
Unit tests -- capture_queue_promotion.py's pure-logic functions
(_map_line_items, _build_order). No network calls, no DB required for
these -- everything they touch is plain data in, plain data out.

Run: python -m pytest tests/test_capture_queue_promotion_pure.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from capture_queue_promotion import _map_line_items, _build_order, _build_missing_item_rows, _payment_fields_from_methods


# --------------------------------------------------------------------------- #
# _map_line_items
# --------------------------------------------------------------------------- #

def test_map_line_items_basic():
    raw_items = [{
        "description": "Gringotts Wizarding Bank", "set_number": "76417",
        "quantity": 1, "unit_price": 499.99, "net_price": 499.99, "is_gwp": False,
    }]
    items = _map_line_items(raw_items)
    assert len(items) == 1
    it = items[0]
    assert it["set_name"] == "Gringotts Wizarding Bank"
    assert it["line_total"] == 499.99
    assert it["line_discount"] == 0
    assert it["item_status"] == "received"


def test_map_line_items_computes_discount_from_unit_vs_net_price():
    raw_items = [{
        "description": "Sale Item", "set_number": "12345",
        "quantity": 2, "unit_price": 10.0, "net_price": 8.0, "is_gwp": False,
    }]
    items = _map_line_items(raw_items)
    assert items[0]["line_discount"] == 4.0   # (10-8)*2
    assert items[0]["line_total"] == 16.0      # 8*2


def test_map_line_items_cancelled_item_zeroes_total_and_discount():
    # ADR-029 -- a cancelled item is never actually charged, regardless of
    # whatever price the raw capture happened to carry.
    raw_items = [{
        "description": "Malfoy Manor", "set_number": "76453",
        "quantity": 1, "unit_price": 129.99, "net_price": 129.99, "is_gwp": False,
        "item_status": "cancelled", "cancellation_reason": "out_of_stock", "cancelled_at": "2026-09-02",
    }]
    items = _map_line_items(raw_items)
    assert items[0]["item_status"] == "cancelled"
    assert items[0]["line_total"] == 0
    assert items[0]["line_discount"] == 0


def test_map_line_items_defaults_missing_fields():
    raw_items = [{"description": None, "quantity": None, "unit_price": None}]
    items = _map_line_items(raw_items)
    assert items[0]["set_name"] == "(no description)"
    assert items[0]["quantity"] == 1
    assert items[0]["unit_price"] == 0.0


# --------------------------------------------------------------------------- #
# _build_order
# --------------------------------------------------------------------------- #

def _row(order_number="T123", retailer="lego", total=None):
    return {"capture_id": "abc-123", "order_number": order_number, "retailer": retailer, "total": total}


def test_build_order_uses_raw_data_totals_when_present():
    raw = {
        "retailer": "lego", "order_number": "T123", "order_date": "2026-09-01",
        "line_items": [{"description": "Set A", "set_number": "1", "quantity": 1, "unit_price": 50.0, "net_price": 50.0, "is_gwp": False}],
        "subtotal": 50.0, "tax": 5.0, "total": 55.0,
    }
    order, items, rewards_earned = _build_order(raw, _row())
    assert order["subtotal"] == 50.0
    assert order["tax_paid"] == 5.0
    assert order["total"] == 55.0
    assert order["order_status"] == "pending_review"
    assert order["entry_method"] == "capture_queue_promotion"
    assert len(items) == 1


def test_build_order_derives_subtotal_from_items_when_raw_subtotal_missing():
    raw = {
        "retailer": "lego", "order_number": "T123", "order_date": "2026-09-01",
        "line_items": [
            {"description": "Set A", "set_number": "1", "quantity": 2, "unit_price": 10.0, "net_price": 10.0, "is_gwp": False},
        ],
        "subtotal": None, "tax": None, "total": None,
    }
    order, items, rewards_earned = _build_order(raw, _row(total=25.0))
    assert order["subtotal"] == 20.0   # 10 * 2, derived from items
    assert order["total"] == 25.0      # falls back to row["total"]


def test_build_order_marks_walmart_tax_exempt():
    raw = {"retailer": "walmart", "order_number": "W1", "order_date": "2026-09-01", "line_items": []}
    order, items, rewards_earned = _build_order(raw, _row(order_number="W1", retailer="walmart", total=0))
    assert order["tax_exempt"] is True
    assert order["tax_exemption_method"] == "at_purchase"


def test_build_order_expected_item_count_includes_cancelled_items():
    # ADR-029: expected_item_count deliberately still counts a cancelled
    # item -- it reflects what the order was confirmed to contain, not what
    # shipped. Don't "fix" this without re-reading ADR-029's Consequences.
    raw = {
        "retailer": "lego", "order_number": "T1", "order_date": "2026-09-01",
        "line_items": [
            {"description": "Set A", "set_number": "1", "quantity": 1, "unit_price": 10.0, "net_price": 10.0, "is_gwp": False},
            {"description": "Set B", "set_number": "2", "quantity": 1, "unit_price": 20.0, "net_price": 20.0,
             "is_gwp": False, "item_status": "cancelled"},
        ],
        "subtotal": 10.0, "tax": 0, "total": 10.0,
    }
    order, items, rewards_earned = _build_order(raw, _row())
    assert order["expected_item_count"] == 2


# --------------------------------------------------------------------------- #
# _build_missing_item_rows (the 2026-09-18 reconciliation fix)
# --------------------------------------------------------------------------- #

def _missing(set_number="76417", set_name="Gringotts Wizarding Bank", quantity_missing=1,
             unit_price=499.99, is_gwp=False):
    return {
        "set_number": set_number, "set_name": set_name,
        "quantity_missing": quantity_missing, "unit_price": unit_price, "is_gwp": is_gwp,
    }


def test_build_missing_item_rows_basic():
    rows, added_subtotal = _build_missing_item_rows("order-1", [_missing()], shipment_id=None)
    assert len(rows) == 1
    assert rows[0]["order_id"] == "order-1"
    assert rows[0]["set_number"] == "76417"
    assert rows[0]["quantity"] == 1
    assert rows[0]["line_total"] == 499.99
    assert rows[0]["item_status"] == "received"
    assert added_subtotal == 499.99


def test_build_missing_item_rows_attaches_shipment_id_when_given():
    rows, _ = _build_missing_item_rows("order-1", [_missing()], shipment_id="ship-99")
    assert rows[0]["shipment_id"] == "ship-99"


def test_build_missing_item_rows_skips_zero_quantity():
    rows, added_subtotal = _build_missing_item_rows(
        "order-1", [_missing(quantity_missing=0), _missing(set_number="99", quantity_missing=1, unit_price=10.0)],
        shipment_id=None,
    )
    assert len(rows) == 1
    assert rows[0]["set_number"] == "99"
    assert added_subtotal == 10.0


def test_build_missing_item_rows_sums_multiple_items():
    rows, added_subtotal = _build_missing_item_rows(
        "order-1",
        [_missing(set_number="1", quantity_missing=2, unit_price=10.0),
         _missing(set_number="2", quantity_missing=1, unit_price=5.0)],
        shipment_id=None,
    )
    assert len(rows) == 2
    assert added_subtotal == 25.0  # 2*10 + 1*5


# --------------------------------------------------------------------------- #
# _payment_fields_from_methods -- regression test for a real bug caught in
# code review (2026-09-18): auto_promote() calling _build_order() alone
# silently zeroed gift_card_applied/payment_method for PDF-backfilled
# orders that the old (deleted) direct-write path used to populate
# correctly from parsed invoice payment legs.
# --------------------------------------------------------------------------- #

def test_payment_fields_empty_when_no_methods():
    gc, pm, detail = _payment_fields_from_methods([])
    assert gc == 0.0
    assert pm is None
    assert detail is None


def test_payment_fields_single_gift_card():
    methods = [{"type": "gift_card", "last4": "1234", "amount": 50.0}]
    gc, pm, detail = _payment_fields_from_methods(methods)
    assert gc == 50.0
    assert pm == "gift_card"
    assert detail is None


def test_payment_fields_single_card_uses_brand():
    methods = [{"type": "card", "brand": "VISA ...3013", "amount": 114.66}]
    gc, pm, detail = _payment_fields_from_methods(methods)
    assert gc == 0.0
    assert pm == "VISA ...3013"


def test_payment_fields_mixed_multiple_methods():
    methods = [
        {"type": "gift_card", "last4": "1234", "amount": 100.0},
        {"type": "card", "brand": "VISA", "amount": 14.66},
    ]
    gc, pm, detail = _payment_fields_from_methods(methods)
    assert gc == 100.0
    assert pm == "mixed"
    assert "VISA $14.66" in detail
    assert "gift_card $100.00" in detail
