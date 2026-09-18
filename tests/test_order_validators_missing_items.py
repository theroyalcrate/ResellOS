"""
Unit tests -- order_validators._compute_missing_items() / _item_match_key()
(the missing-shipment reconciliation logic added 2026-09-18, closing
CONTEXT.md Open Question #22 -- agent_1e_pdf_backfill silently dropping an
entire shipment's line items on 6 real orders because nothing ever compared
newly-found data against what was already on file for an order).

No network calls, no DB -- these are pure functions, plain data in, plain
data out.

Run: python -m pytest tests/test_order_validators_missing_items.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from order_validators import _compute_missing_items, _item_match_key, raw_line_items_to_compare_items


def _existing(set_number=None, set_name="Some Set", quantity=1, unit_price=10.0,
              is_gwp=False, item_status="received"):
    return {
        "set_number": set_number,
        "set_name": set_name,
        "quantity": quantity,
        "unit_price": unit_price,
        "is_gwp": is_gwp,
        "item_status": item_status,
    }


def _incoming(set_number=None, set_name="Some Set", quantity=1, unit_price=10.0,
              is_gwp=False, item_status=None):
    item = {
        "set_number": set_number,
        "set_name": set_name,
        "quantity": quantity,
        "unit_price": unit_price,
        "is_gwp": is_gwp,
    }
    if item_status is not None:
        item["item_status"] = item_status
    return item


# --------------------------------------------------------------------------- #
# _item_match_key
# --------------------------------------------------------------------------- #

def test_match_key_prefers_set_number():
    assert _item_match_key({"set_number": "76417", "set_name": "Gringotts", "is_gwp": False}) == (
        "set_number", "76417", False,
    )


def test_match_key_includes_is_gwp_for_same_set_number():
    # Regression test for a real bug caught in code review (2026-09-18): a
    # set can legitimately ship as both a paid item and a same-numbered
    # promotional GWP -- without is_gwp in the key, a paid unit could
    # wrongly cross-match against an existing GWP unit of the same set,
    # letting a real missing paid item pass undetected.
    paid_key = _item_match_key({"set_number": "76417", "is_gwp": False})
    gwp_key = _item_match_key({"set_number": "76417", "is_gwp": True})
    assert paid_key != gwp_key


def test_match_key_normalizes_case_and_whitespace():
    a = _item_match_key({"set_number": " 76417 "})
    b = _item_match_key({"set_number": "76417"})
    assert a == b


def test_match_key_falls_back_to_set_name_and_gwp_when_no_set_number():
    key = _item_match_key({"set_number": None, "set_name": "Premier Ball", "is_gwp": True})
    assert key == ("set_name", "premier ball", True)


# --------------------------------------------------------------------------- #
# _compute_missing_items -- the real bug this closes
# --------------------------------------------------------------------------- #

def test_exact_match_no_warnings():
    existing = [_existing(set_number="76417", quantity=1)]
    incoming = [_incoming(set_number="76417", quantity=1)]
    assert _compute_missing_items(incoming, existing) == []


def test_item_entirely_missing_from_order():
    # T450671168-style: the order exists, but a whole set is missing.
    existing = []
    incoming = [_incoming(set_number="76417", set_name="Gringotts Wizarding Bank", quantity=1, unit_price=499.99)]
    warnings = _compute_missing_items(incoming, existing)
    assert len(warnings) == 1
    w = warnings[0]
    assert w["check"] == "missing_line_item"
    assert w["set_number"] == "76417"
    assert w["quantity_missing"] == 1
    assert w["quantity_on_file"] == 0
    assert w["unit_price"] == 499.99


def test_partial_shortfall_t508221251_style():
    # T508221251: 2 units on file, invoice indicates 3 -- shortfall of 1.
    existing = [_existing(set_number="60495", quantity=2, unit_price=39.99)]
    incoming = [_incoming(set_number="60495", quantity=3, unit_price=39.99)]
    warnings = _compute_missing_items(incoming, existing)
    assert len(warnings) == 1
    assert warnings[0]["quantity_missing"] == 1
    assert warnings[0]["quantity_on_file"] == 2


def test_incoming_quantity_less_than_existing_is_not_flagged():
    # Order already has more than this run's PDF shows (e.g. it saw a
    # different partial shipment) -- not a gap, don't flag it.
    existing = [_existing(set_number="10454", quantity=5)]
    incoming = [_incoming(set_number="10454", quantity=2)]
    assert _compute_missing_items(incoming, existing) == []


def test_quantities_aggregate_across_multiple_existing_rows_of_same_set():
    # Two separate shipments each have 1x the same set -- pool should sum to 2.
    existing = [_existing(set_number="76934", quantity=1), _existing(set_number="76934", quantity=1)]
    incoming = [_incoming(set_number="76934", quantity=2)]
    assert _compute_missing_items(incoming, existing) == []


def test_gwp_item_matches_by_set_name_when_no_set_number():
    existing = [_existing(set_number=None, set_name="Premier Ball", is_gwp=True, quantity=1)]
    incoming = [_incoming(set_number=None, set_name="Premier Ball", is_gwp=True, quantity=1)]
    assert _compute_missing_items(incoming, existing) == []


def test_gwp_item_with_no_set_number_and_no_match_is_flagged():
    existing = []
    incoming = [_incoming(set_number=None, set_name="Mixed Flowerpot", is_gwp=True, quantity=1, unit_price=0)]
    warnings = _compute_missing_items(incoming, existing)
    assert len(warnings) == 1
    assert warnings[0]["is_gwp"] is True
    assert warnings[0]["set_name"] == "Mixed Flowerpot"


def test_cancelled_existing_items_excluded_from_the_pool():
    # A cancelled item (ADR-029) shouldn't count as "on file" coverage.
    existing = [_existing(set_number="76453", quantity=1, item_status="cancelled")]
    incoming = [_incoming(set_number="76453", quantity=1)]
    warnings = _compute_missing_items(incoming, existing)
    assert len(warnings) == 1
    assert warnings[0]["quantity_on_file"] == 0


def test_cancelled_incoming_items_are_never_flagged():
    existing = []
    incoming = [_incoming(set_number="76453", quantity=1, item_status="cancelled")]
    assert _compute_missing_items(incoming, existing) == []


def test_zero_quantity_incoming_item_is_ignored():
    existing = []
    incoming = [_incoming(set_number="99999", quantity=0)]
    assert _compute_missing_items(incoming, existing) == []


def test_raw_line_items_to_compare_items_uses_net_price_not_pre_discount_price():
    # Regression test for a real cost-basis bug caught in code review
    # (2026-09-18): capture_queue_promotion.py's _merge_shipped_capture()
    # used to feed _map_line_items()'s output (pre-discount "unit_price")
    # into this comparison, which would have overstated cost basis for any
    # missing item that had a discount. "unit_price" for this comparison
    # must mean what was actually paid (net_price).
    raw_items = [{
        "description": "Discounted Set", "set_number": "12345", "quantity": 1,
        "unit_price": 50.0, "net_price": 40.0, "is_gwp": False,
    }]
    items = raw_line_items_to_compare_items(raw_items)
    assert items[0]["unit_price"] == 40.0


def test_raw_line_items_to_compare_items_falls_back_to_unit_price_when_no_net_price():
    raw_items = [{
        "description": "No discount info", "set_number": "999", "quantity": 1,
        "unit_price": 25.0, "net_price": None, "is_gwp": False,
    }]
    items = raw_line_items_to_compare_items(raw_items)
    assert items[0]["unit_price"] == 25.0


def test_multiple_incoming_items_only_flags_the_actual_gap():
    existing = [_existing(set_number="854245", quantity=1, set_name="Fennec Shand Keychain")]
    incoming = [
        _incoming(set_number="854245", quantity=1, set_name="Fennec Shand Keychain"),
        _incoming(set_number="76417", quantity=1, set_name="Gringotts Wizarding Bank", unit_price=499.99),
    ]
    warnings = _compute_missing_items(incoming, existing)
    assert len(warnings) == 1
    assert warnings[0]["set_number"] == "76417"


# --------------------------------------------------------------------------- #
# Real-data regression test -- T450671168, the actual order fixed by hand on
# 2026-09-17 (CONTEXT.md Open Question #22). Confirms 2026-09-18's ask
# directly: a manually-added line item's shipment has NO invoice_number
# (only tracking_number) and a different entry_method than the item
# agent_1e_pdf_backfill originally captured -- this test proves neither
# fact can matter, because _compute_missing_items() never reads the
# shipments table or invoice_number at all, only line_items' own
# set_number/quantity/is_gwp. Fixture values pulled directly from Supabase
# 2026-09-18 (read-only query), not invented.
# --------------------------------------------------------------------------- #

def _t450671168_existing_line_items():
    """Exactly what's on file for order T450671168 right now -- two
    line_items from the agent_1e_pdf_backfill shipment (40756 GWP, 10316
    paid) and one from the manually-added shipment (76417, invoice_number
    NULL on its shipment row -- only that manual row's tracking_number is
    set)."""
    return [
        _existing(set_number="40756", set_name="40756 Lucky Knots V39", quantity=1, is_gwp=True),
        _existing(set_number="10316", set_name="10316 THE LORD OF THE RINGS: RIVEN.. V39",
                   quantity=1, unit_price=499.99, is_gwp=False),
        _existing(set_number="76417", set_name="76417 Gringotts Wizarding Bank - Collectors Edition",
                   quantity=1, unit_price=429.99, is_gwp=False),
    ]


def test_t450671168_reencountering_the_original_pdf_invoice_is_a_noop():
    # Simulates agent_1e re-finding invoice #1343175743 (the one it already
    # captured on 2026-09-17) -- e.g. a duplicate copy still sitting in the
    # Drive backlog. Both items it contains are already on file.
    existing = _t450671168_existing_line_items()
    incoming = [
        _incoming(set_number="40756", set_name="40756 Lucky Knots V39", quantity=1, is_gwp=True),
        _incoming(set_number="10316", set_name="10316 THE LORD OF THE RINGS: RIVEN.. V39",
                   quantity=1, unit_price=499.99, is_gwp=False),
    ]
    assert _compute_missing_items(incoming, existing) == []


def test_t450671168_manually_added_item_recognized_despite_blank_invoice_number():
    # The actual scenario Josh asked to verify: 76417 (Gringotts) sits on a
    # shipment row with invoice_number=NULL (only tracking_number was set
    # when it was added by hand). If agent_1e later finds A REAL PDF
    # invoice for this same order_number that happens to include 76417,
    # the comparison must recognize it as already covered -- the blank
    # invoice_number on the EXISTING shipment record is invisible to this
    # check by construction (it only reads line_items, never shipments).
    existing = _t450671168_existing_line_items()
    incoming = [
        _incoming(set_number="76417", set_name="76417 Gringotts Wizarding Bank - Collectors Edition",
                   quantity=1, unit_price=429.99, is_gwp=False),
    ]
    assert _compute_missing_items(incoming, existing) == []


def test_t450671168_genuinely_new_item_still_gets_flagged():
    # Sanity check the fixture isn't accidentally making everything pass --
    # an item that really isn't on file for this order yet must still be
    # flagged.
    existing = _t450671168_existing_line_items()
    incoming = [_incoming(set_number="99999", set_name="Not On This Order", quantity=1, unit_price=10.0)]
    warnings = _compute_missing_items(incoming, existing)
    assert len(warnings) == 1
    assert warnings[0]["set_number"] == "99999"
