"""
Unit tests — Agent 10 Stock Watch pure-logic functions.
No network calls, no DB, no API. Safe to run at any time.

Run: python tests/test_agent_10_stock_watch.py
  or: python -m pytest tests/test_agent_10_stock_watch.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agent_10_stock_watch import (
    _coerce_in_stock,
    _coerce_price,
    _first_present,
    determine_alert,
    parse_tier_list_row,
)


# --------------------------------------------------------------------------- #
# determine_alert
# --------------------------------------------------------------------------- #

def test_no_alert_when_not_found():
    current = {"found": False, "in_stock": None, "price": None}
    assert determine_alert(None, current) == []


def test_no_alert_on_first_check_even_if_in_stock():
    # No baseline to compare against yet — informational only, not an alert
    current = {"found": True, "in_stock": True, "price": 50.0}
    assert determine_alert(None, current) == []


def test_restock_alert_when_transitioning_out_to_in_stock():
    previous = {"found": True, "in_stock": False}
    current = {"found": True, "in_stock": True, "price": 50.0}
    assert determine_alert(previous, current) == ["restock"]


def test_no_alert_when_staying_in_stock():
    previous = {"found": True, "in_stock": True}
    current = {"found": True, "in_stock": True, "price": 50.0}
    assert determine_alert(previous, current) == []


def test_no_alert_when_going_out_of_stock():
    # Going OOS isn't urgent for this tool's purpose — not alerted
    previous = {"found": True, "in_stock": True}
    current = {"found": True, "in_stock": False, "price": None}
    assert determine_alert(previous, current) == []


def test_discount_alert_at_threshold():
    current = {"found": True, "in_stock": True, "price": 80.0}
    # msrp 100, price 80 -> 20% discount, threshold 20 -> fires (>=)
    assert determine_alert(None, current, msrp=100.0, threshold_pct=20) == ["discount_20.0pct"]


def test_no_discount_alert_below_threshold():
    current = {"found": True, "in_stock": True, "price": 90.0}
    # 10% discount, threshold 20 -> no alert
    assert determine_alert(None, current, msrp=100.0, threshold_pct=20) == []


def test_both_restock_and_discount_can_fire_together():
    previous = {"found": True, "in_stock": False}
    current = {"found": True, "in_stock": True, "price": 70.0}
    reasons = determine_alert(previous, current, msrp=100.0, threshold_pct=20)
    assert "restock" in reasons
    assert "discount_30.0pct" in reasons


def test_no_discount_alert_without_msrp():
    current = {"found": True, "in_stock": True, "price": 1.0}
    assert determine_alert(None, current, msrp=None) == []


# --------------------------------------------------------------------------- #
# parse_tier_list_row
# --------------------------------------------------------------------------- #

def test_parse_tier_list_row_standard_format():
    assert parse_tier_list_row("10327 Dune Atreides Royal Ornithopter") == (
        "10327", "Dune Atreides Royal Ornithopter"
    )


def test_parse_tier_list_row_special_characters_preserved():
    set_number, name = parse_tier_list_row("42670 Heartlake City Apartments and Stores")
    assert set_number == "42670"
    assert name == "Heartlake City Apartments and Stores"


def test_parse_tier_list_row_no_leading_number_returns_none():
    set_number, name = parse_tier_list_row("Some Unnumbered Item")
    assert set_number is None
    assert name == "Some Unnumbered Item"


# --------------------------------------------------------------------------- #
# _coerce_price
# --------------------------------------------------------------------------- #

def test_coerce_price_from_dollar_string():
    assert _coerce_price("$199.99") == 199.99


def test_coerce_price_from_string_with_commas():
    assert _coerce_price("$1,234.56") == 1234.56


def test_coerce_price_from_number():
    assert _coerce_price(37.94) == 37.94


def test_coerce_price_none_passthrough():
    assert _coerce_price(None) is None


def test_coerce_price_unparseable_returns_none():
    assert _coerce_price("call for price") is None


# --------------------------------------------------------------------------- #
# _coerce_in_stock
# --------------------------------------------------------------------------- #

def test_coerce_in_stock_walmart_style():
    assert _coerce_in_stock("IN_STOCK") is True
    assert _coerce_in_stock("OUT_OF_STOCK") is False


def test_coerce_in_stock_bool_passthrough():
    assert _coerce_in_stock(True) is True
    assert _coerce_in_stock(False) is False


def test_coerce_in_stock_unrecognized_returns_none():
    assert _coerce_in_stock("BACKORDER_MAYBE") is None


def test_coerce_in_stock_none_returns_none():
    assert _coerce_in_stock(None) is None


# --------------------------------------------------------------------------- #
# _first_present
# --------------------------------------------------------------------------- #

def test_first_present_returns_first_hit():
    d = {"a": None, "b": 5, "c": 10}
    assert _first_present(d, ["a", "b", "c"]) == 5


def test_first_present_default_when_none_found():
    d = {"a": None}
    assert _first_present(d, ["a", "b"], default="fallback") == "fallback"


# --------------------------------------------------------------------------- #
# Standalone runner (no pytest required)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import traceback

    tests = {k: v for k, v in globals().items() if k.startswith("test_")}
    passed = failed = 0
    for name, fn in tests.items():
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {name}  — {exc}")
            traceback.print_exc()
            failed += 1
        except Exception as exc:
            print(f"  ERROR {name}  — {exc}")
            traceback.print_exc()
            failed += 1

    print()
    print(f"  {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
