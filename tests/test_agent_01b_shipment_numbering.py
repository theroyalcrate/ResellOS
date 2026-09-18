"""
Regression test -- agent_01b_invoice_filing._next_shipment_number() must
key off invoice_files.filed_filename (a direct signal of "this agent
already filed a PDF for this order"), not shipments/count_shipments().
Caught in code review, 2026-09-19, while adding Agent 01B's --run mode:
the same bug class already found and fixed in
agent_01e_pdf_order_backfill.py's own _next_shipment_number()
(2026-09-17, CONTEXT.md Open Question #22). Filing an invoice via this
agent's record_filing() never inserts a shipments row, so counting
shipments would stay frozen at its original value across every future
--run and hand the SAME shipment number to every later invoice for that
order -- a cross-run collision, most likely to actually bite on Agent
01B's own recurring weekly Task Scheduler job (any split-shipment order
that ships across more than one week).

Deliberate exception to this codebase's "only unit-test pure functions"
convention (see other files under tests/) -- same reasoning as
test_add_missing_items_cost_basis_guard.py and
test_agent_01e_shipment_numbering.py: a minimal fake client, only
supporting the exact chain this one function uses.

Run: python -m pytest tests/test_agent_01b_shipment_numbering.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agent_01b_invoice_filing import _next_shipment_number


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


def test_starts_at_1_when_nothing_filed_yet():
    client = _FakeClient([])
    assert _next_shipment_number("order-1", "T450671168", "LEGO", client) == 1


def test_counts_only_filenames_matching_this_orders_convention():
    client = _FakeClient([
        {"filed_filename": "T450671168_LEGO_2026-09-01.pdf"},
        {"filed_filename": "T450671168_LEGO_2026-09-01_ship2.pdf"},
    ])
    assert _next_shipment_number("order-1", "T450671168", "LEGO", client) == 3


def test_does_not_false_positive_on_a_similarly_prefixed_different_order_number():
    # T1234 must not be counted as already-filed for order T123 just
    # because its filename happens to start with the same characters.
    client = _FakeClient([
        {"filed_filename": "T1234_LEGO_2026-09-01.pdf"},
    ])
    assert _next_shipment_number("order-1", "T123", "LEGO", client) == 1


def test_retailer_tag_is_part_of_the_matching_prefix():
    # Same order_number, different retailer -- must not cross-count (this
    # agent handles multiple retailers, unlike agent_01e which is LEGO-only).
    client = _FakeClient([
        {"filed_filename": "T1_KOHLS_2026-09-01.pdf"},
    ])
    assert _next_shipment_number("order-1", "T1", "LEGO", client) == 1


def test_two_separate_runs_get_different_numbers_not_a_collision():
    # Simulates the real cross-run failure scenario this fix exists to
    # prevent: first --run files ship1; a LATER --run (a different week's
    # scheduled job) must see that filed row and continue to ship2, not
    # repeat ship1 -- the exact bug count_shipments() would have caused,
    # since filing never writes a shipments row.
    client = _FakeClient([])
    first = _next_shipment_number("order-1", "T1", "LEGO", client)
    assert first == 1

    client_after_first_run = _FakeClient([
        {"filed_filename": "T1_LEGO_2026-01-01.pdf"},
    ])
    second = _next_shipment_number("order-1", "T1", "LEGO", client_after_first_run)
    assert second == 2
    assert second != first
