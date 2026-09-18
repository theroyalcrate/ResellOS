"""
Regression test -- add_missing_items_to_order() must refuse to touch an
already-'confirmed' order (CLAUDE.md Rule 4: "Cost basis locks at
settlement. Never reopen."). Caught in code review, 2026-09-18: the
function originally rewrote orders.subtotal/total/tax_paid unconditionally,
with no gate on order_status, which for a confirmed order could silently
change the exact totals its cost basis was already computed against.

This is a deliberate exception to this codebase's usual "only unit-test
pure functions, no DB mocking" convention (see other files under tests/) --
the guard being tested here protects a hard, explicitly-stated correctness
rule, and is worth locking in with a real regression test even at the cost
of a minimal fake client. The fake only supports exactly the chain shape
add_missing_items_to_order()'s early-exit path uses; it does not attempt to
generally emulate Supabase.

Run: python -m pytest tests/test_add_missing_items_cost_basis_guard.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from capture_queue_promotion import add_missing_items_to_order


class _FakeQuery:
    def __init__(self, table, rows_by_table):
        self._table = table
        self._rows_by_table = rows_by_table
        self._filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def insert(self, *_args, **_kwargs):
        raise AssertionError(
            f"insert() called on table '{self._table}' -- the cost-basis guard should have "
            f"refused before any write was attempted."
        )

    def execute(self):
        rows = self._rows_by_table.get(self._table, [])
        matched = [
            r for r in rows
            if all(r.get(k) == v for k, v in self._filters.items())
        ]
        return _FakeResult(matched)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    """Only implements .table(name)... enough for the guard's own lookup
    query and to prove no insert() ever happens once it refuses."""
    def __init__(self, orders):
        self._rows_by_table = {"orders": orders}

    def table(self, name):
        return _FakeQuery(name, self._rows_by_table)


def _missing_item(set_number="76417", quantity_missing=1, unit_price=499.99):
    return {
        "set_number": set_number, "set_name": "Gringotts Wizarding Bank",
        "quantity_missing": quantity_missing, "unit_price": unit_price, "is_gwp": False,
    }


def test_refuses_when_order_is_confirmed():
    client = _FakeClient(orders=[{"order_id": "order-1", "order_status": "confirmed"}])
    result = add_missing_items_to_order(client, "order-1", [_missing_item()])
    assert result["ok"] is False
    assert "confirmed" in result["message"].lower()
    assert "reopen_order" in result["message"]


def test_refuses_when_order_not_found():
    client = _FakeClient(orders=[])
    result = add_missing_items_to_order(client, "order-missing", [_missing_item()])
    assert result["ok"] is False
    assert "not found" in result["message"].lower()


def test_no_missing_items_short_circuits_before_any_lookup():
    # Should refuse before even querying -- confirm no table() call blows up
    # on an empty fake (it would, since _rows_by_table has no "orders" key
    # populated for this order_id, but the guard for empty missing_items
    # should fire first regardless).
    client = _FakeClient(orders=[])
    result = add_missing_items_to_order(client, "order-1", [])
    assert result["ok"] is False
    assert "no missing items" in result["message"].lower()
