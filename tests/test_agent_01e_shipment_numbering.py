"""
Regression test -- agent_01e_pdf_order_backfill._next_shipment_number()
must key off invoice_files.filed_filename (a direct signal of "this agent
already relocated a PDF here"), not shipments.invoice_number. Caught in
code review, 2026-09-19: shipments.invoice_number gets set by write paths
unrelated to whether a PDF was ever relocated to Drive, and a CONFIRMED
match never creates a new shipments row at all -- counting that field
would have let two separate CONFIRMED matches for the same order, made in
different runs, compute the identical shipment number and collide on the
exact same destination filename in Drive.

Deliberate exception to this codebase's "only unit-test pure functions"
convention (see other files under tests/) -- same reasoning as
test_add_missing_items_cost_basis_guard.py: a minimal fake client, only
supporting the exact chain this one function uses.

Run: python -m pytest tests/test_agent_01e_shipment_numbering.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agent_01e_pdf_order_backfill import _next_shipment_number


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    def __init__(self, invoice_files_rows):
        self._rows = invoice_files_rows

    def table(self, name):
        assert name == "invoice_files", f"unexpected table: {name}"
        return _FakeQuery(self._rows)


def test_starts_at_1_when_nothing_relocated_yet():
    client = _FakeClient([])
    assert _next_shipment_number("order-1", "T450671168", client) == 1


def test_counts_only_filenames_matching_this_orders_convention():
    client = _FakeClient([
        {"filed_filename": "T450671168_LEGO_2026-09-01.pdf"},
        {"filed_filename": "T450671168_LEGO_2026-09-01_ship2.pdf"},
    ])
    assert _next_shipment_number("order-1", "T450671168", client) == 3


def test_shipment_with_invoice_number_but_no_relocated_file_does_not_count():
    # The exact bug caught in code review: a shipment can have a real
    # invoice_number (set via an interactive capture_queue_promotion.py
    # merge, unrelated to this agent's own relocation) without any PDF
    # ever having been relocated for it. This function must not be fooled
    # by that -- it only counts invoice_files rows whose filed_filename
    # already reflects a real relocation.
    client = _FakeClient([
        {"filed_filename": "1AbCdEfGhIjKlMnOpQrStUvWxYz_LEGO_2026-09-01.pdf"},  # still unmatched-style name
    ])
    assert _next_shipment_number("order-1", "T450671168", client) == 1


def test_does_not_false_positive_on_a_similarly_prefixed_different_order_number():
    # T1234 must not be counted as already-filed for order T123 just
    # because its filename happens to start with the same characters.
    client = _FakeClient([
        {"filed_filename": "T1234_LEGO_2026-09-01.pdf"},
    ])
    assert _next_shipment_number("order-1", "T123", client) == 1


def test_two_separate_confirmed_matches_get_different_numbers_not_a_collision():
    # Simulates the real failure scenario: first CONFIRMED match relocates
    # ship2 (one prior file already on record); recomputing afterward (as
    # a later run would) must see that new file and continue to ship3, not
    # repeat ship2.
    client = _FakeClient([{"filed_filename": "T1_LEGO_2026-01-01.pdf"}])
    first = _next_shipment_number("order-1", "T1", client)
    assert first == 2

    client_after_first_relocation = _FakeClient([
        {"filed_filename": "T1_LEGO_2026-01-01.pdf"},
        {"filed_filename": "T1_LEGO_2026-01-01_ship2.pdf"},
    ])
    second = _next_shipment_number("order-1", "T1", client_after_first_relocation)
    assert second == 3
    assert second != first
