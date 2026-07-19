"""
Tests for agents/email_enricher.py — LEGO parser module.
Runs against the 5 real email fixtures in tests/fixtures/emails/lego/.

Expected values verified against Supabase (Cowork 2026-07-05):
  T508041747 : ship1 = 10454×5 / $99.95 subtotal
               ship2 = 31157×2 / $39.98 subtotal
               order total = $169.28 (different from per-shipment sum — GWP + unshipped item)
  T508221251 : 60495×3/$119.97 + 42167×1/$32.99 + 40902×1/GWP ($0), total $169.33

Includes all 5 matching test cases from the A-007 spec:
  1. Tier 1 direct match (shipping email → existing order)
  2. Identical totals ($169.33) must NOT be a matching criterion
  3. Orphan (order not in DB) → flag_unmatched, review queue only, no order created
  4. Split shipment (two emails, same order, different tracking)
  5. Declined email (orphan) → flag_unmatched with payment_declined noted

Manual-entry-first architecture (revised 2026-07-18): Josh enters orders himself
via agent_02. This agent never creates orders from email data — an unmatched
email is always flagged for manual review, never auto-inserted as a stub.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.email_enricher import (
    ACT_CREATE_SHIPMENT,
    ACT_ENRICH_ORDER,
    ACT_FLAG_DECLINED,
    ACT_FLAG_UNMATCHED,
    ACT_RECEIPT_PDF,
    ACT_SKIP,
    LineItemData,
    LegoParsedOrderConfirmation,
    LegoParsedPaymentDeclined,
    LegoParsedReceipt,
    LegoParsedShippingConfirmation,
    SkippedEmail,
    classify_lego_email,
    load_fixture_file,
    parse_lego_email,
    parse_lego_order_confirmation,
    parse_lego_payment_declined,
    parse_lego_receipt,
    parse_lego_shipping_confirmation,
    plan_enrichment,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "emails" / "lego"


def _load(filename: str) -> tuple:
    return load_fixture_file(_FIXTURES / filename)


# ---------------------------------------------------------------------------
# Email classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_order_confirmation(self):
        assert classify_lego_email(
            "Noreply@t.crm.lego.com",
            "We've got it! Your LEGO(R) order is confirmed, Joshua",
            "",
        ) == "order_confirmation"

    def test_shipping_confirmation(self):
        assert classify_lego_email(
            "Noreply@t.crm.lego.com",
            "Your LEGO Order T508041747 is on its way Joshua",
            "",
        ) == "shipping_confirmation"

    def test_payment_declined(self):
        assert classify_lego_email(
            "Noreply@t.crm.lego.com",
            "Your payment was unsuccessful",
            "",
        ) == "payment_declined"

    def test_receipt_billing03_sender(self):
        assert classify_lego_email(
            "no-reply-billing03@lego.com",
            "LEGO® Shop  Receipt 1355278758 from 07/01/2026",
            "",
        ) == "receipt"

    def test_receipt_historical_m_sender(self):
        assert classify_lego_email(
            "receipts@m.lego.com",
            "LEGO receipt",
            "",
        ) == "receipt"

    def test_survey(self):
        assert classify_lego_email(
            "Noreply@t.crm.lego.com",
            "Thank you for your recent LEGO® purchase.",
            "",
        ) == "survey"

    def test_historical_e_lego_sender(self):
        # e.lego.com is a known historical sender (Agent 1B filters target it)
        assert classify_lego_email(
            "noreply@e.lego.com",
            "Your LEGO Order T508041747 is on its way Joshua",
            "",
        ) == "shipping_confirmation"

    def test_unknown_sender_rejected(self):
        assert classify_lego_email(
            "newsletter@randomsite.com",
            "Your LEGO Order T123456789 is on its way",
            "",
        ) == "unknown"

    def test_case_insensitive_sender(self):
        # Fixture sender is "Noreply@t.crm.lego.com" (capital N)
        assert classify_lego_email(
            "NOREPLY@T.CRM.LEGO.COM",
            "Your payment was unsuccessful",
            "",
        ) == "payment_declined"


# ---------------------------------------------------------------------------
# Fixture: order confirmation T508221251
# ---------------------------------------------------------------------------

@pytest.fixture
def order_conf():
    msg_id, sender, subject, body = _load("order_confirmation_T508221251.txt")
    return parse_lego_order_confirmation(msg_id, sender, body)


class TestOrderConfirmation:
    def test_email_type(self, order_conf):
        assert order_conf.email_type == "order_confirmation"

    def test_order_number(self, order_conf):
        assert order_conf.order_number == "T508221251"

    def test_order_date(self, order_conf):
        assert order_conf.order_date == date(2026, 6, 25)

    def test_subtotal(self, order_conf):
        assert order_conf.subtotal == pytest.approx(152.96)

    def test_tax(self, order_conf):
        assert order_conf.tax == pytest.approx(16.37)

    def test_order_total(self, order_conf):
        assert order_conf.order_total == pytest.approx(169.33)

    def test_shipping(self, order_conf):
        assert order_conf.shipping == pytest.approx(0.0)

    def test_line_item_count(self, order_conf):
        assert len(order_conf.line_items) == 3

    def test_set_60495_values(self, order_conf):
        item = next(i for i in order_conf.line_items if i.set_number == "60495")
        assert item.qty == 3
        assert item.line_total == pytest.approx(119.97)
        assert item.unit_price == pytest.approx(119.97 / 3)  # = 39.99
        assert not item.is_gwp

    def test_set_42167_values(self, order_conf):
        item = next(i for i in order_conf.line_items if i.set_number == "42167")
        assert item.qty == 1
        assert item.line_total == pytest.approx(32.99)
        assert item.unit_price == pytest.approx(32.99)
        assert not item.is_gwp

    def test_gwp_40902_detection(self, order_conf):
        """line_total == 0 and qty >= 1 → is_gwp = True"""
        item = next(i for i in order_conf.line_items if i.set_number == "40902")
        assert item.qty == 1
        assert item.line_total == pytest.approx(0.0)
        assert item.unit_price == pytest.approx(0.0)
        assert item.is_gwp is True

    def test_unit_price_not_from_price_column(self, order_conf):
        """
        Parser trap: price column showed $0.00 for paid items.
        unit_price must be derived from line_total / qty, not the price column.
        """
        item = next(i for i in order_conf.line_items if i.set_number == "60495")
        assert item.unit_price > 0.0
        assert item.unit_price == pytest.approx(119.97 / 3)

    def test_v_suffix_stripped_clean_name(self, order_conf):
        """Parser trap: 'Recycling Truck V39' → name must not contain 'V39'"""
        item = next(i for i in order_conf.line_items if i.set_number == "60495")
        assert "V39" not in item.name
        assert item.name == "Recycling Truck"

    def test_truncated_name_v_suffix_stripped(self, order_conf):
        """Parser trap: 'Mack® LR Electric Garbage Tr.. V39' → V39 stripped, dots cleaned"""
        item = next(i for i in order_conf.line_items if i.set_number == "42167")
        assert "V39" not in item.name

    def test_is_retiring_defaults_true(self, order_conf):
        """CLAUDE.md rule 6: is_retiring defaults True on every line item"""
        for item in order_conf.line_items:
            assert item.is_retiring is True

    def test_gmail_message_id(self, order_conf):
        assert order_conf.gmail_message_id == "19efd09d7c5056ff"


# ---------------------------------------------------------------------------
# Fixture: shipping confirmation T508041747, shipment 1
# ---------------------------------------------------------------------------

@pytest.fixture
def ship1():
    msg_id, sender, subject, body = _load("shipping_confirmation_T508041747_ship1.txt")
    return parse_lego_shipping_confirmation(msg_id, sender, subject, body)


class TestShip1:
    def test_email_type(self, ship1):
        assert ship1.email_type == "shipping_confirmation"

    def test_order_number(self, ship1):
        assert ship1.order_number == "T508041747"

    def test_tracking_number(self, ship1):
        assert ship1.tracking_number == "1Z0V069A0382992440"

    def test_shipment_subtotal(self, ship1):
        assert ship1.shipment_subtotal == pytest.approx(99.95)

    def test_shipment_tax(self, ship1):
        assert ship1.shipment_tax == pytest.approx(10.70)

    def test_shipment_total(self, ship1):
        assert ship1.shipment_total == pytest.approx(110.65)

    def test_line_item_count(self, ship1):
        assert len(ship1.line_items) == 1

    def test_set_10454(self, ship1):
        item = ship1.line_items[0]
        assert item.set_number == "10454"
        assert item.qty == 5
        assert item.line_total == pytest.approx(99.95)
        assert item.unit_price == pytest.approx(99.95 / 5)  # = 19.99
        assert not item.is_gwp

    def test_gmail_message_id(self, ship1):
        assert ship1.gmail_message_id == "19f1d8fe7fb21dfe"


# ---------------------------------------------------------------------------
# Fixture: shipping confirmation T508041747, shipment 2 (same order, different tracking)
# ---------------------------------------------------------------------------

@pytest.fixture
def ship2():
    msg_id, sender, subject, body = _load("shipping_confirmation_T508041747_ship2.txt")
    return parse_lego_shipping_confirmation(msg_id, sender, subject, body)


class TestShip2:
    def test_same_order_as_ship1(self, ship2):
        """Split shipment — same order number as ship1"""
        assert ship2.order_number == "T508041747"

    def test_different_tracking_from_ship1(self, ship1, ship2):
        assert ship2.tracking_number == "1ZH5A091YW36790031"
        assert ship2.tracking_number != ship1.tracking_number

    def test_shipment_subtotal(self, ship2):
        assert ship2.shipment_subtotal == pytest.approx(39.98)

    def test_shipment_tax(self, ship2):
        assert ship2.shipment_tax == pytest.approx(4.28)

    def test_shipment_total(self, ship2):
        assert ship2.shipment_total == pytest.approx(44.26)

    def test_set_31157(self, ship2):
        item = ship2.line_items[0]
        assert item.set_number == "31157"
        assert item.qty == 2
        assert item.line_total == pytest.approx(39.98)
        assert item.unit_price == pytest.approx(39.98 / 2)  # = 19.99
        assert not item.is_gwp

    def test_different_gmail_message_id(self, ship1, ship2):
        """
        Parser trap: two emails with identical subjects for the same order.
        They must be deduped at gmail_message_id level, NOT treated as duplicates.
        """
        assert ship1.gmail_message_id != ship2.gmail_message_id

    def test_date_skew_in_email(self, ship2):
        """
        Parser trap: shipping email says 6/23/2026, but order was placed 6/22/2026.
        The parser faithfully extracts the email's date. Tolerance applied at match time.
        """
        assert ship2.order_date == date(2026, 6, 23)

    def test_shipment_totals_are_not_order_totals(self, ship1, ship2):
        """
        Parser trap: shipping emails label per-shipment amounts as 'ORDER TOTAL'.
        Verify these map to shipment fields, not orders fields.
        Combined subtotals != the order-level total ($169.28 confirmed in Supabase).
        """
        combined_subtotal = ship1.shipment_subtotal + ship2.shipment_subtotal
        assert combined_subtotal == pytest.approx(99.95 + 39.98)
        assert combined_subtotal != pytest.approx(169.28)

    def test_gmail_message_id(self, ship2):
        assert ship2.gmail_message_id == "19f1f65bbb3a98bf"


# ---------------------------------------------------------------------------
# Fixture: payment declined T507979974
# ---------------------------------------------------------------------------

@pytest.fixture
def payment_declined():
    msg_id, sender, subject, body = _load("payment_declined_T507979974.txt")
    return parse_lego_payment_declined(msg_id, sender, body)


class TestPaymentDeclined:
    def test_email_type(self, payment_declined):
        assert payment_declined.email_type == "payment_declined"

    def test_order_number(self, payment_declined):
        assert payment_declined.order_number == "T507979974"

    def test_order_date(self, payment_declined):
        assert payment_declined.order_date == date(2026, 6, 22)

    def test_gmail_message_id(self, payment_declined):
        assert payment_declined.gmail_message_id == "19f197de0b77f865"


# ---------------------------------------------------------------------------
# Fixture: receipt email invoice 1355278758
# ---------------------------------------------------------------------------

@pytest.fixture
def receipt():
    msg_id, sender, subject, body = _load("receipt_email_1355278758.txt")
    return parse_lego_receipt(msg_id, sender, subject, body)


class TestReceipt:
    def test_email_type(self, receipt):
        assert receipt.email_type == "receipt"

    def test_invoice_number(self, receipt):
        assert receipt.invoice_number == "1355278758"

    def test_purchase_date(self, receipt):
        assert receipt.purchase_date == date(2026, 7, 1)

    def test_gmail_message_id(self, receipt):
        assert receipt.gmail_message_id == "19f212ee4b51fd75"

    def test_no_order_number(self, receipt):
        """Receipt body has no order number — Tier 2 only (Agent 1A handles PDF)."""
        assert not hasattr(receipt, "order_number") or not getattr(receipt, "order_number", "")


# ---------------------------------------------------------------------------
# A-007 cascade — 5 spec test cases
# ---------------------------------------------------------------------------

class TestA007Cascade:
    # --- Spec test 1: Tier 1 direct match ---

    def test_shipping_email_matches_existing_order(self, ship1):
        """Shipping email with order in DB → create_shipment plan."""
        existing = {
            "order_id":         "mock-uuid-t508041747",
            "order_number":     "T508041747",
            "order_status":     "confirmed",
            "cost_basis_state": "estimated",
        }
        plan = plan_enrichment(ship1, existing_order=existing)
        assert plan.action == ACT_CREATE_SHIPMENT
        assert plan.matched_order_id == "mock-uuid-t508041747"
        assert plan.matched_order_number == "T508041747"

    def test_order_confirmation_matches_existing_order(self, order_conf):
        """Order confirmation with order in DB → enrich_order plan (not a stub)."""
        existing = {
            "order_id":         "mock-uuid-t508221251",
            "order_number":     "T508221251",
            "order_status":     "confirmed",
            "cost_basis_state": "estimated",
        }
        plan = plan_enrichment(order_conf, existing_order=existing)
        assert plan.action == ACT_ENRICH_ORDER

    # --- Spec test 2: identical totals must NOT be used as a matching criterion ---

    def test_identical_totals_never_trigger_match(self, order_conf):
        """
        T508056398 and T508221251 both total $169.33.
        With no order-number match, result is flag_unmatched — never a wrong-order match.
        The cascade has no total-based tier, so this is structurally guaranteed.
        """
        plan = plan_enrichment(order_conf, existing_order=None)
        assert plan.action == ACT_FLAG_UNMATCHED
        assert plan.matched_order_id is None
        assert plan.matched_order_number is None

    # --- Spec test 3: orphan → flag_unmatched, never silently dropped, never auto-created ---

    def test_unmatched_order_confirmation_flagged(self, order_conf):
        """T508221251 not in DB → flagged for manual review, not silently dropped, no order created."""
        plan = plan_enrichment(order_conf, existing_order=None)
        assert plan.action == ACT_FLAG_UNMATCHED
        assert "T508221251" in plan.notes

    def test_unmatched_shipping_flagged(self, ship1):
        """Shipping email with no matching order → flagged, no stub or shipment created."""
        plan = plan_enrichment(ship1, existing_order=None)
        assert plan.action == ACT_FLAG_UNMATCHED

    # --- Spec test 4: split shipment → two separate plans, not duplicates ---

    def test_split_shipment_produces_two_plans(self, ship1, ship2):
        """Two shipping emails for the same order → two create_shipment plans."""
        existing = {
            "order_id":         "mock-uuid-t508041747",
            "order_number":     "T508041747",
            "order_status":     "confirmed",
            "cost_basis_state": "estimated",
        }
        plan1 = plan_enrichment(ship1, existing_order=existing)
        plan2 = plan_enrichment(ship2, existing_order=existing)

        assert plan1.action == ACT_CREATE_SHIPMENT
        assert plan2.action == ACT_CREATE_SHIPMENT
        assert plan1.gmail_message_id != plan2.gmail_message_id

    def test_split_shipment_different_tracking(self, ship1, ship2):
        """Each plan carries its own tracking number — no deduplication at plan level."""
        existing = {"order_id": "oid", "order_number": "T508041747",
                    "order_status": "confirmed", "cost_basis_state": "estimated"}
        plan1 = plan_enrichment(ship1, existing)
        plan2 = plan_enrichment(ship2, existing)
        assert plan1.parsed.tracking_number != plan2.parsed.tracking_number

    # --- Spec test 5: payment declined → flag_unmatched with payment_declined noted ---

    def test_declined_orphan_flagged_unmatched(self, payment_declined):
        """T507979974 not in DB → flagged for manual review, no order created."""
        plan = plan_enrichment(payment_declined, existing_order=None)
        assert plan.action == ACT_FLAG_UNMATCHED
        assert "payment_declined" in plan.notes.lower()

    def test_declined_existing_order_flags_not_cancels(self, payment_declined):
        """
        Payment declined for an existing order → flag_declined (pending_review).
        Must NEVER auto-cancel. Spec: 'flag the matching order for review, do NOT auto-cancel'.
        """
        existing = {
            "order_id":         "mock-uuid-t507979974",
            "order_number":     "T507979974",
            "order_status":     "confirmed",
            "cost_basis_state": "estimated",
        }
        plan = plan_enrichment(payment_declined, existing_order=existing)
        # flag_declined means the order is queued for review — not cancelled
        assert plan.action == ACT_FLAG_DECLINED

    # --- Receipt → forward to Agent 1A (no order number in body) ---

    def test_receipt_forwarded_to_agent1a(self, receipt):
        plan = plan_enrichment(receipt, existing_order=None)
        assert plan.action == ACT_RECEIPT_PDF

    # --- Survey → skip ---

    def test_survey_skipped(self):
        skipped = SkippedEmail(gmail_message_id="msg-survey", reason="survey — skip per spec")
        plan = plan_enrichment(skipped, existing_order=None)
        assert plan.action == ACT_SKIP


# ---------------------------------------------------------------------------
# End-to-end: parse_lego_email dispatch (covers all 5 fixture types)
# ---------------------------------------------------------------------------

class TestDispatch:
    def test_dispatches_order_confirmation(self):
        msg_id, sender, subject, body = _load("order_confirmation_T508221251.txt")
        result = parse_lego_email(msg_id, sender, subject, body)
        assert isinstance(result, LegoParsedOrderConfirmation)
        assert result.order_number == "T508221251"

    def test_dispatches_shipping_ship1(self):
        msg_id, sender, subject, body = _load("shipping_confirmation_T508041747_ship1.txt")
        result = parse_lego_email(msg_id, sender, subject, body)
        assert isinstance(result, LegoParsedShippingConfirmation)
        assert result.order_number == "T508041747"

    def test_dispatches_shipping_ship2(self):
        msg_id, sender, subject, body = _load("shipping_confirmation_T508041747_ship2.txt")
        result = parse_lego_email(msg_id, sender, subject, body)
        assert isinstance(result, LegoParsedShippingConfirmation)

    def test_dispatches_payment_declined(self):
        msg_id, sender, subject, body = _load("payment_declined_T507979974.txt")
        result = parse_lego_email(msg_id, sender, subject, body)
        assert isinstance(result, LegoParsedPaymentDeclined)
        assert result.order_number == "T507979974"

    def test_dispatches_receipt(self):
        msg_id, sender, subject, body = _load("receipt_email_1355278758.txt")
        result = parse_lego_email(msg_id, sender, subject, body)
        assert isinstance(result, LegoParsedReceipt)
        assert result.invoice_number == "1355278758"

    def test_survey_returns_skipped(self):
        result = parse_lego_email(
            "msg-survey",
            "Noreply@t.crm.lego.com",
            "Thank you for your recent LEGO® purchase.",
            "body text",
        )
        assert isinstance(result, SkippedEmail)
        assert "survey" in result.reason.lower()

    def test_unknown_sender_returns_skipped(self):
        result = parse_lego_email(
            "msg-unknown",
            "spam@notlego.com",
            "Your LEGO Order is ready",
            "",
        )
        assert isinstance(result, SkippedEmail)

    def test_fixture_metadata_extraction(self):
        """load_fixture_file correctly extracts sender, subject, gmail_message_id."""
        msg_id, sender, subject, body = _load("order_confirmation_T508221251.txt")
        assert msg_id    == "19efd09d7c5056ff"
        assert sender    == "Noreply@t.crm.lego.com"
        assert "confirmed" in subject.lower()
        assert "LEGO" in body
