"""
Unit tests — Agent 09 Purchase Planner pure-logic functions.
No network calls, no DB, no API. Safe to run at any time.

Run: python tests/test_agent_09_purchase_planner.py
  or: python -m pytest tests/test_agent_09_purchase_planner.py -v
"""

import sys
from pathlib import Path

# Agent lives in agents/, one level up from tests/. Repo root (for
# agent_02_order_entry's normalize_retailer/LEGO_POINTS_PER_DOLLAR import
# inside agent_09) also needs to be on the path.
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agent_09_purchase_planner import (
    describe_combination,
    evaluate_gift_card_fit,
    find_best_combination,
    generate_combinations,
    lego_points_for_item,
)


# --------------------------------------------------------------------------- #
# lego_points_for_item — round-half-up, matches agent_02's _lego_item_points
# --------------------------------------------------------------------------- #

def test_lego_points_whole_dollar_amount():
    # $10 x 2 x 6.5 = 130.0 exactly — no rounding ambiguity
    assert lego_points_for_item(10.0, 2, 1) == 130


def test_lego_points_rounds_half_up():
    # $9.99 x 1 x 6.5 = 64.935 -> rounds up to 65
    assert lego_points_for_item(9.99, 1, 1) == 65


def test_lego_points_applies_multiplier():
    # $9.99 x 1 x 6.5 x 2 = 129.87 -> rounds up to 130
    assert lego_points_for_item(9.99, 1, 2) == 130


def test_lego_points_zero_quantity_is_zero():
    assert lego_points_for_item(49.99, 0, 1) == 0


# --------------------------------------------------------------------------- #
# generate_combinations — safety guard on the brute-force search space
# --------------------------------------------------------------------------- #

def test_generate_combinations_small_search_space_ok():
    items = [{"max_quantity": 2}, {"max_quantity": 2}]
    combos = list(generate_combinations(items))
    assert len(combos) == 9  # 3 options (0,1,2) each => 3*3


def test_generate_combinations_raises_on_oversized_search():
    # 7 items x max_quantity 10 => 11^7 ≈ 19.5M, well over MAX_COMBINATIONS
    items = [{"max_quantity": 10} for _ in range(7)]
    try:
        list(generate_combinations(items))
        assert False, "expected ValueError for oversized search space"
    except ValueError as e:
        assert "too large" in str(e)


# --------------------------------------------------------------------------- #
# find_best_combination — gwp_threshold (minimize spend, must reach target)
# --------------------------------------------------------------------------- #

def test_gwp_threshold_finds_minimum_overspend_combo():
    items = [
        {"set_name": "A", "unit_price": 25.0, "max_quantity": 3},
        {"set_name": "B", "unit_price": 40.0, "max_quantity": 2},
    ]
    result = find_best_combination(items, "gwp_threshold", 75.0)
    best = result["best"]
    assert best is not None
    assert best["total_spend"] == 75.0
    # Only exact-75 solution is A x3, B x0
    qtys = {it["set_name"]: it["quantity"] for it in best["items"]}
    assert qtys == {"A": 3}


def test_gwp_threshold_no_combination_reaches_target():
    items = [{"set_name": "A", "unit_price": 10.0, "max_quantity": 2}]
    # Max possible spend is $20 — target of $500 is unreachable
    result = find_best_combination(items, "gwp_threshold", 500.0)
    assert result["best"] is None
    assert result["all_considered"] == 3  # qty 0, 1, 2


# --------------------------------------------------------------------------- #
# find_best_combination — spend_cap (maximize spend without exceeding target)
# --------------------------------------------------------------------------- #

def test_spend_cap_maximizes_spend_without_exceeding():
    items = [
        {"set_name": "A", "unit_price": 25.0, "max_quantity": 3},
        {"set_name": "B", "unit_price": 40.0, "max_quantity": 2},
    ]
    result = find_best_combination(items, "spend_cap", 90.0)
    best = result["best"]
    assert best is not None
    assert best["total_spend"] == 90.0  # A x2, B x1 = 50 + 40 = 90
    qtys = {it["set_name"]: it["quantity"] for it in best["items"]}
    assert qtys == {"A": 2, "B": 1}


def test_spend_cap_zero_target_finds_nothing():
    items = [{"set_name": "A", "unit_price": 10.0, "max_quantity": 2}]
    result = find_best_combination(items, "spend_cap", 0.0)
    assert result["best"] is None


# --------------------------------------------------------------------------- #
# find_best_combination — points_tier (minimize spend, must reach point target)
# --------------------------------------------------------------------------- #

def test_points_tier_finds_minimum_spend_to_reach_points():
    items = [{"set_name": "C", "unit_price": 50.0, "max_quantity": 2}]
    # qty 1 = 325 pts (< 500), qty 2 = 650 pts (>= 500) — only qty 2 qualifies
    result = find_best_combination(items, "points_tier", 500, lego_multiplier=1)
    best = result["best"]
    assert best is not None
    assert best["total_spend"] == 100.0
    assert best["total_points"] == 650


# --------------------------------------------------------------------------- #
# evaluate_gift_card_fit
# --------------------------------------------------------------------------- #

def test_gift_card_fit_no_balance_given():
    fit = evaluate_gift_card_fit(75.0, None)
    assert fit == {"balance": None, "remaining": None, "shortfall": None}


def test_gift_card_fit_shortfall():
    fit = evaluate_gift_card_fit(75.0, 50.0)
    assert fit["shortfall"] == 25.0
    assert fit["remaining"] == 0


def test_gift_card_fit_covers_with_remainder():
    fit = evaluate_gift_card_fit(75.0, 100.0)
    assert fit["remaining"] == 25.0
    assert fit["shortfall"] == 0


# --------------------------------------------------------------------------- #
# describe_combination — pure formatting
# --------------------------------------------------------------------------- #

def test_describe_combination_gwp_threshold_omits_points_line():
    combo = {
        "items": [{"set_name": "A", "quantity": 3, "unit_price": 25.0, "line_spend": 75.0}],
        "total_spend": 75.0,
        "total_points": 0,
    }
    lines = describe_combination(combo, "gwp_threshold")
    assert "A x3 @ $25.00 = $75.00" in lines
    assert "Total spend: $75.00" in lines
    assert not any("points" in line.lower() for line in lines)


def test_describe_combination_points_tier_includes_points_line():
    combo = {
        "items": [{"set_name": "C", "quantity": 2, "unit_price": 50.0, "line_spend": 100.0}],
        "total_spend": 100.0,
        "total_points": 650,
    }
    lines = describe_combination(combo, "points_tier")
    assert "Total points: 650" in lines


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
