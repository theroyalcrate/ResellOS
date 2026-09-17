"""
Unit tests -- order_confirm_review_app's pure-logic functions
(_compute_records_and_net_cost, compute_preview). No network calls, no DB,
no Streamlit runtime required -- everything these two functions touch is
plain data in, plain data out.

Run: python -m pytest tests/test_order_confirm_review_app.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from order_confirm_review_app import _compute_records_and_net_cost, compute_preview


def _item(li_id="li1", set_number="10242", set_name="MINI Cooper", qty=1,
          line_total=100.0, is_gwp=False, item_status="active"):
    return {
        "line_item_id": li_id,
        "set_number": set_number,
        "set_name": set_name,
        "quantity": qty,
        "line_total": line_total,
        "is_gwp": is_gwp,
        "item_status": item_status,
        "unit_price": (line_total / qty) if qty else 0,
    }


def _order(order_id="o1", order_number="T1", subtotal=100.0, tax_paid=0.0,
           gift_card_applied=0.0, rewards_applied=0.0,
           reconciliation_status="reconciled", entry_method="manual"):
    return {
        "order_id": order_id,
        "order_number": order_number,
        "subtotal": subtotal,
        "tax_paid": tax_paid,
        "gift_card_applied": gift_card_applied,
        "rewards_applied": rewards_applied,
        "reconciliation_status": reconciliation_status,
        "entry_method": entry_method,
    }


# --------------------------------------------------------------------------- #
# _compute_records_and_net_cost
# --------------------------------------------------------------------------- #

def test_compute_records_simple_single_item():
    items = [_item(line_total=100.0, qty=1)]
    records, invoice_cost, net_cost = _compute_records_and_net_cost(items, 0.0, 0.0, "proceeds_reduce_order")
    assert invoice_cost == 100.0
    assert net_cost == 100.0
    assert records[0]["cost_per_unit"] == 100.0


def test_compute_records_tax_and_rewards_reduce_net_cost():
    items = [_item(line_total=100.0, qty=1)]
    records, invoice_cost, net_cost = _compute_records_and_net_cost(items, 8.0, 20.0, "proceeds_reduce_order")
    assert invoice_cost == 100.0
    # 100 invoice + 8 tax - 20 rewards = 88
    assert net_cost == 88.0


def test_compute_records_gwp_item_zero_cost_and_excluded_from_invoice():
    items = [_item(li_id="paid1", line_total=100.0, qty=1),
              _item(li_id="gwp1", line_total=0.0, qty=1, is_gwp=True)]
    records, invoice_cost, net_cost = _compute_records_and_net_cost(items, 0.0, 0.0, "proceeds_reduce_order")
    assert invoice_cost == 100.0  # GWP item contributes nothing to invoice cost
    gwp_record = next(r for r in records if r["is_gwp"])
    assert gwp_record["cost_per_unit"] == 0.0


def test_compute_records_multi_unit_prorata_allocation():
    items = [_item(li_id="a", line_total=60.0, qty=2), _item(li_id="b", line_total=40.0, qty=1)]
    records, invoice_cost, net_cost = _compute_records_and_net_cost(items, 0.0, 0.0, "proceeds_reduce_order")
    assert invoice_cost == 100.0
    rec_a = next(r for r in records if r["line_item_id"] == "a")
    rec_b = next(r for r in records if r["line_item_id"] == "b")
    assert rec_a["cost_per_unit"] == 30.0  # $60 / 2 units
    assert rec_b["cost_per_unit"] == 40.0  # $40 / 1 unit


# --------------------------------------------------------------------------- #
# compute_preview -- needs_review gating
# --------------------------------------------------------------------------- #

def test_compute_preview_clean_when_reconciled_and_subtotal_matches():
    items = [_item(line_total=100.0, qty=1)]
    order = _order(subtotal=100.0, reconciliation_status="reconciled")
    p = compute_preview(order, items, "proceeds_reduce_order")
    assert p["needs_review"] is False
    assert p["net_economic_cost"] == 100.0


def test_compute_preview_flags_non_reconciled_status():
    items = [_item(line_total=100.0, qty=1)]
    order = _order(subtotal=100.0, reconciliation_status="pending")
    p = compute_preview(order, items, "proceeds_reduce_order")
    assert p["needs_review"] is True


def test_compute_preview_flags_subtotal_mismatch():
    items = [_item(line_total=90.0, qty=1)]
    order = _order(subtotal=100.0, reconciliation_status="reconciled")
    p = compute_preview(order, items, "proceeds_reduce_order")
    assert p["needs_review"] is True
    assert p["subtotal_mismatch"] is True


def test_compute_preview_flags_and_excludes_cancelled_items():
    active = _item(li_id="a", line_total=100.0, qty=1)
    cancelled = _item(li_id="b", line_total=0.0, qty=2, item_status="cancelled")
    order = _order(subtotal=100.0, reconciliation_status="reconciled")
    p = compute_preview(order, [active, cancelled], "proceeds_reduce_order")
    assert p["needs_review"] is True  # cancelled item present -> flagged
    assert len(p["cancelled_items"]) == 1
    # the cancelled item's 2 units must NOT appear in the inventory-bound records
    assert all(r["line_item_id"] != "b" for r in p["records"])


def test_compute_preview_flags_gwp_price_mismatch():
    # is_gwp=True but priced > $0 -- order_validators.check_gwp_price_consistency
    # should catch this and force needs_review, even though reconciliation_status
    # and subtotal are otherwise clean.
    items = [_item(li_id="a", line_total=50.0, qty=1, is_gwp=True)]
    order = _order(subtotal=50.0, reconciliation_status="reconciled")
    p = compute_preview(order, items, "proceeds_reduce_order")
    assert p["needs_review"] is True
    assert any(w.get("check") == "gwp_price_mismatch" for w in p["validator_warnings"])


def test_compute_preview_no_paid_items_is_flagged():
    items = [_item(li_id="a", line_total=0.0, qty=1, is_gwp=True)]
    order = _order(subtotal=0.0, reconciliation_status="reconciled")
    p = compute_preview(order, items, "proceeds_reduce_order")
    assert p["needs_review"] is True
    assert p["paid_items"] == []
