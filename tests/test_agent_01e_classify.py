"""
Unit tests -- agent_01e_pdf_order_backfill's pure decision logic
(InvoiceGroupPlan.classify(), _build_raw_data()). These never touch Drive
or Supabase for writes -- classify() only reaches order_validators checks
that stay in-memory when order_id/entry_method are None (the case for a
brand-new order_number group), so `client=None` is safe to pass here.

Rewritten 2026-09-18 alongside the fix for CONTEXT.md Open Question #22
(agent_1e used to write orders directly and never compared newly-found PDF
data against an order that already existed) -- these tests cover the new
classify() outcomes (ORDER_EXISTS, MERGE_PENDING, RESURFACED_AFTER_DISCARD)
as well as the original CLEAN/FLAGGED gating.

Run: python -m pytest tests/test_agent_01e_classify.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from invoice_parser import LegoInvoice, LineItem
from agent_01e_pdf_order_backfill import (
    InvoiceGroupPlan,
    _build_raw_data,
    _unmerged_invoice_pairs,
    _invoice_to_shipment_meta,
)


def _clean_invoice(order_number="T123456", invoice_number="INV-1", subtotal=100.0, tax=10.0, total=110.0):
    return LegoInvoice(
        order_number=order_number,
        invoice_number=invoice_number,
        invoice_date="01 Sep 2026",
        order_date="01 Sep 2026",
        line_items=[LineItem(
            article_number="A1", description="Test Set", quantity=1,
            unit_price=100.0, net_price=100.0, is_gwp=False, set_number="10242",
        )],
        subtotal=subtotal, tax=tax, order_total=total,
    )


def _plan_with_invoice(invoice) -> InvoiceGroupPlan:
    plan = InvoiceGroupPlan(invoice.order_number)
    plan.invoices.append(invoice)
    plan.file_rows.append({"id": "f1", "filed_filename": "f1.pdf"})
    return plan


# --------------------------------------------------------------------------- #
# CLEAN / FLAGGED -- brand new order_number, no existing order/capture row
# --------------------------------------------------------------------------- #

def test_clean_invoice_classifies_clean():
    plan = _plan_with_invoice(_clean_invoice())
    plan.classify(client=None)
    assert plan.outcome == "CLEAN"
    assert plan.reasons == []


def test_missing_order_date_is_flagged():
    inv = _clean_invoice()
    inv.order_date = None
    inv.invoice_date = None
    plan = _plan_with_invoice(inv)
    plan.classify(client=None)
    assert plan.outcome == "FLAGGED"
    assert any("order date" in r for r in plan.reasons)


def test_no_line_items_is_flagged():
    inv = _clean_invoice()
    inv.line_items = []
    plan = _plan_with_invoice(inv)
    plan.classify(client=None)
    assert plan.outcome == "FLAGGED"
    assert any("line items" in r for r in plan.reasons)


def test_missing_subtotal_is_flagged():
    inv = _clean_invoice(subtotal=None)
    plan = _plan_with_invoice(inv)
    plan.classify(client=None)
    assert plan.outcome == "FLAGGED"
    assert any("subtotal" in r for r in plan.reasons)


def test_missing_total_is_flagged():
    inv = _clean_invoice(total=None)
    plan = _plan_with_invoice(inv)
    plan.classify(client=None)
    assert plan.outcome == "FLAGGED"
    assert any("total" in r for r in plan.reasons)


def test_gwp_price_mismatch_blocks_clean():
    inv = _clean_invoice()
    inv.line_items = [LineItem(
        article_number="A1", description="Should be GWP", quantity=1,
        unit_price=0.0, net_price=0.0, is_gwp=False, set_number="99999",
    )]
    plan = _plan_with_invoice(inv)
    plan.classify(client=None)
    assert plan.outcome == "FLAGGED"


def test_missing_set_number_alone_does_not_block_clean():
    # order_validators.py's own docstring: missing_set_number is
    # informational only, never a gate -- common on the older backlog.
    inv = _clean_invoice()
    inv.line_items = [LineItem(
        article_number="A1", description="No set number here", quantity=1,
        unit_price=100.0, net_price=100.0, is_gwp=False, set_number=None,
    )]
    plan = _plan_with_invoice(inv)
    plan.classify(client=None)
    assert plan.outcome == "CLEAN"


def test_no_invoices_and_a_parse_error_is_flagged_with_both_reasons():
    plan = InvoiceGroupPlan("__unresolved__:f1")
    plan.parse_errors.append("f1.pdf: could not read PDF")
    plan.classify(client=None)
    assert plan.outcome == "FLAGGED"
    assert any("failed to parse" in r for r in plan.reasons)
    assert any("no invoice parsed cleanly" in r for r in plan.reasons)


# --------------------------------------------------------------------------- #
# ORDER_EXISTS / MERGE_PENDING / RESURFACED_AFTER_DISCARD -- 2026-09-18 fix
# --------------------------------------------------------------------------- #

def test_existing_order_short_circuits_to_order_exists_even_if_data_looks_bad():
    inv = _clean_invoice()
    inv.subtotal = None  # would normally be FLAGGED
    plan = _plan_with_invoice(inv)
    plan.existing_order_id = "order-abc"
    plan.classify(client=None)
    assert plan.outcome == "ORDER_EXISTS"
    # Doesn't need to explain data flaws (_apply_order_exists does the real
    # comparison), but should carry a basic reason rather than an empty
    # list, so any future code that assumes every outcome has one doesn't
    # silently get nothing for this case.
    assert plan.reasons != []


def test_pending_capture_row_classifies_merge_pending():
    plan = _plan_with_invoice(_clean_invoice())
    plan.existing_capture_row = {"status": "pending", "capture_id": "cq-1", "raw_data": {}}
    plan.classify(client=None)
    assert plan.outcome == "MERGE_PENDING"


def test_discarded_capture_row_classifies_resurfaced():
    plan = _plan_with_invoice(_clean_invoice())
    plan.existing_capture_row = {"status": "discarded", "capture_id": "cq-1", "review_note": "duplicate"}
    plan.classify(client=None)
    assert plan.outcome == "RESURFACED_AFTER_DISCARD"


def test_promoted_capture_row_with_order_id_falls_back_to_order_exists():
    plan = _plan_with_invoice(_clean_invoice())
    plan.existing_capture_row = {"status": "promoted", "capture_id": "cq-1", "promoted_order_id": "order-xyz"}
    plan.classify(client=None)
    assert plan.outcome == "ORDER_EXISTS"
    assert plan.existing_order_id == "order-xyz"


# --------------------------------------------------------------------------- #
# _build_raw_data
# --------------------------------------------------------------------------- #

def test_build_raw_data_capture_stage_is_shipped_not_checkout():
    # 2026-09-18 fix: a PDF invoice is proof of what happened, not a
    # point-of-purchase snapshot -- the old code mislabeled this "checkout".
    plan = _plan_with_invoice(_clean_invoice())
    raw = _build_raw_data(plan)
    assert raw["capture_stage"] == "shipped"
    assert raw["source"] == "agent_1d_pdf_backfill"


def test_build_raw_data_sums_across_multiple_invoices():
    inv1 = _clean_invoice(invoice_number="INV-1", subtotal=100.0, tax=10.0, total=110.0)
    inv2 = _clean_invoice(invoice_number="INV-2", subtotal=50.0, tax=5.0, total=55.0)
    plan = InvoiceGroupPlan("T123456")
    plan.invoices = [inv1, inv2]
    raw = _build_raw_data(plan)
    assert raw["subtotal"] == 150.0
    assert raw["tax"] == 15.0
    assert raw["total"] == 165.0
    assert len(raw["shipments"]) == 2
    assert len(raw["line_items"]) == 2


def test_build_raw_data_carries_insider_points_redeemed_and_shipment_financials():
    # Regression test for a real bug caught in code review (2026-09-18):
    # routing agent_1e through capture_queue silently dropped
    # insider_points_redeemed and per-shipment invoice_number/subtotal/
    # tax_amount/payment_method, which the old (deleted) direct-write path
    # used to populate on `orders`/`shipments` directly.
    inv = _clean_invoice(invoice_number="INV-1", subtotal=100.0, tax=10.0, total=110.0)
    inv.insider_points_redeemed = 25.0
    inv.payment_method = "Visa ...3013"
    plan = _plan_with_invoice(inv)
    raw = _build_raw_data(plan)
    assert raw["insider_points_redeemed"] == 25.0
    assert len(raw["shipments"]) == 1
    shipment = raw["shipments"][0]
    assert shipment["invoice_number"] == "INV-1"
    assert shipment["subtotal"] == 100.0
    assert shipment["tax_amount"] == 10.0
    assert shipment["payment_method"] == "Visa ...3013"


def test_build_raw_data_unresolved_group_has_null_order_number():
    plan = InvoiceGroupPlan("__unresolved__:f1")
    plan.parse_errors.append("f1.pdf: no order_number extracted")
    raw = _build_raw_data(plan)
    assert raw["order_number"] is None
    assert raw["_parse_errors"] == ["f1.pdf: no order_number extracted"]


# --------------------------------------------------------------------------- #
# _unmerged_invoice_pairs -- regression test for a real bug caught in code
# review (2026-09-18): deduping a re-run's invoices by invoice_number, which
# can be None, meant an invoice with no invoice_number was never actually
# deduped and would be re-merged (duplicating its items/dollars) every run.
# --------------------------------------------------------------------------- #

def test_unmerged_pairs_dedupes_by_file_row_id_not_invoice_number():
    inv1 = _clean_invoice(invoice_number=None)  # a real, parser-documented possibility
    inv2 = _clean_invoice(invoice_number=None)
    file_rows = [{"id": "file-1"}, {"id": "file-2"}]
    # Simulate a re-run where file-1 was already merged last time.
    already_merged = {"file-1"}
    pairs = _unmerged_invoice_pairs([inv1, inv2], file_rows, already_merged)
    assert len(pairs) == 1
    assert pairs[0][1]["id"] == "file-2"


def test_unmerged_pairs_all_new_when_nothing_merged_yet():
    inv1, inv2 = _clean_invoice(), _clean_invoice()
    file_rows = [{"id": "file-1"}, {"id": "file-2"}]
    pairs = _unmerged_invoice_pairs([inv1, inv2], file_rows, set())
    assert len(pairs) == 2


def test_unmerged_pairs_none_new_when_all_already_merged():
    inv1 = _clean_invoice()
    file_rows = [{"id": "file-1"}]
    pairs = _unmerged_invoice_pairs([inv1], file_rows, {"file-1"})
    assert pairs == []


# --------------------------------------------------------------------------- #
# _invoice_to_shipment_meta -- regression test for a real bug caught in
# code review (2026-09-18): a discrepancy record used to carry no
# shipment_meta at all, so resolving it via add_missing_items_to_order()
# silently lost the invoice's invoice_number/date/subtotal/tax/payment_method.
# --------------------------------------------------------------------------- #

def test_invoice_to_shipment_meta_carries_all_fields():
    inv = _clean_invoice(invoice_number="INV-99", subtotal=209.99, tax=22.66, total=232.65)
    inv.payment_method = "Visa ...3013"
    meta = _invoice_to_shipment_meta(inv)
    assert meta["invoice_number"] == "INV-99"
    assert meta["subtotal"] == 209.99
    assert meta["tax_amount"] == 22.66
    assert meta["payment_method"] == "Visa ...3013"
    assert meta["shipment_status"] == "received"
