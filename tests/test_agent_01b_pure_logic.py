"""
Unit tests — Agent 01B pure-logic functions.
No network calls, no DB, no API. Safe to run at any time.

Run: python tests/test_agent_01b_pure_logic.py
  or: python -m pytest tests/test_agent_01b_pure_logic.py -v

Real-data fixtures use June 2026 Kohl's orders already in Supabase
(order numbers 6714029349, 6702180930 etc.) and the LEGO T487170400 order.
"""

import sys
from datetime import date
from pathlib import Path

# Agent lives in agents/, one level up from tests/
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from agent_01b_invoice_filing import (
    build_filename,
    build_unmatched_filename,
    detect_retailer_from_sender,
    extract_email_date,
    extract_order_number_from_subject,
    extract_sender_email,
    has_pdf_attachment,
    match_order,
    resolve_drive_folder_path,
    resolve_order_number,
    resolve_retailer_folder,
    resolve_unmatched_folder_path,
)
from db_client import PHASE_1_USER_ID


# --------------------------------------------------------------------------- #
# build_filename
# --------------------------------------------------------------------------- #

def test_filename_standard_kohls():
    # Real Kohl's order from Supabase — standard single shipment
    assert build_filename("6714029349", "KOHLS", "2026-06-08") == "6714029349_KOHLS_2026-06-08.pdf"


def test_filename_standard_lego():
    # Real LEGO order T487170400 (Dec 2025)
    assert build_filename("T487170400", "LEGO", "2025-12-03") == "T487170400_LEGO_2025-12-03.pdf"


def test_filename_ship1_has_no_suffix():
    assert build_filename("6702180930", "KOHLS", "2026-06-08", shipment_num=1) == "6702180930_KOHLS_2026-06-08.pdf"


def test_filename_split_shipment_ship2():
    assert build_filename("6714029349", "KOHLS", "2026-06-08", shipment_num=2) == "6714029349_KOHLS_2026-06-08_ship2.pdf"


def test_filename_split_shipment_ship3():
    assert build_filename("T487170400", "LEGO", "2025-12-03", shipment_num=3) == "T487170400_LEGO_2025-12-03_ship3.pdf"


def test_filename_lowercase_retailer_normalised():
    # Retailer key is always uppercased regardless of input case
    assert build_filename("12345678", "kohls", "2026-06-08") == "12345678_KOHLS_2026-06-08.pdf"


def test_filename_walmart_business_spaces_become_underscores():
    assert build_filename("WB001", "WALMART BUSINESS", "2026-01-15") == "WB001_WALMART_BUSINESS_2026-01-15.pdf"


# --------------------------------------------------------------------------- #
# build_unmatched_filename
# --------------------------------------------------------------------------- #

def test_unmatched_filename_kohls():
    result = build_unmatched_filename("18b000000000abcd", "KOHLS", "2026-06-08")
    assert result == "18b000000000abcd_KOHLS_2026-06-08.pdf"


def test_unmatched_filename_unknown():
    result = build_unmatched_filename("msg123", "UNKNOWN", "2026-06-09")
    assert result == "msg123_UNKNOWN_2026-06-09.pdf"


def test_unmatched_filename_uppercases_retailer():
    result = build_unmatched_filename("abc", "lego", "2026-01-01")
    assert result == "abc_LEGO_2026-01-01.pdf"


# --------------------------------------------------------------------------- #
# resolve_drive_folder_path
# --------------------------------------------------------------------------- #

def test_folder_path_june_2026_kohls():
    # Real Kohl's June 8th orders
    assert resolve_drive_folder_path("Kohls", "2026-06-08") == ["Invoices", "Kohls", "2026", "June 2026"]


def test_folder_path_december_2025_lego():
    # LEGO T487170400 order date
    assert resolve_drive_folder_path("Lego", "2025-12-03") == ["Invoices", "Lego", "2025", "December 2025"]


def test_folder_path_january_2026():
    assert resolve_drive_folder_path("Target", "2026-01-15") == ["Invoices", "Target", "2026", "January 2026"]


def test_folder_path_walmart_business():
    assert resolve_drive_folder_path("Walmart Business", "2026-03-22") == [
        "Invoices", "Walmart Business", "2026", "March 2026"
    ]


def test_folder_path_november_macys():
    assert resolve_drive_folder_path("Macy's", "2025-11-01") == ["Invoices", "Macy's", "2025", "November 2025"]


# --------------------------------------------------------------------------- #
# resolve_unmatched_folder_path
# --------------------------------------------------------------------------- #

def test_unmatched_folder_path():
    assert resolve_unmatched_folder_path("Kohls") == ["Invoices", "Kohls", "_unmatched"]


# --------------------------------------------------------------------------- #
# resolve_retailer_folder — Walmart routing rule §7.5
# --------------------------------------------------------------------------- #

def test_walmart_business_sender_routes_to_business_folder():
    assert resolve_retailer_folder("WALMART", "businessinfo@walmart.com") == "Walmart Business"


def test_walmart_personal_sender_routes_to_walmart_folder():
    assert resolve_retailer_folder("WALMART", "help@walmart.com") == "Walmart"


def test_walmart_business_display_name_sender():
    # Full From header — extract_sender_email would give just the address, but test
    # the retailer key too just in case caller passes the full header by mistake
    assert resolve_retailer_folder("WALMART", "Walmart Business <businessinfo@walmart.com>") == "Walmart Business"


def test_kohls_folder():
    assert resolve_retailer_folder("KOHLS", "noreply@kohls.com") == "Kohls"


def test_lego_folder():
    assert resolve_retailer_folder("LEGO", "noreply@e.lego.com") == "Lego"


def test_macys_folder():
    assert resolve_retailer_folder("MACYS", "noreply@macys.com") == "Macy's"


def test_target_folder():
    assert resolve_retailer_folder("TARGET", "noreply@target.com") == "Target"


def test_bestbuy_folder():
    assert resolve_retailer_folder("BESTBUY", "noreply@bestbuy.com") == "Best Buy"


def test_barnes_folder():
    assert resolve_retailer_folder("BARNES", "noreply@barnesandnoble.com") == "Barnes and Noble"


# --------------------------------------------------------------------------- #
# extract_order_number_from_subject
# --------------------------------------------------------------------------- #

def test_order_number_lego_t_prefix():
    # LEGO invoice subject format: "Invoice for Order T487170400"
    assert extract_order_number_from_subject("Invoice for Order T487170400") == "T487170400"


def test_order_number_kohls_numeric():
    # Kohl's: long numeric order number
    assert extract_order_number_from_subject("Your Kohl's Invoice - Order 6714029349") == "6714029349"


def test_order_number_second_kohls_june8():
    assert extract_order_number_from_subject("Kohl's Order Confirmation 6702180930") == "6702180930"


def test_order_number_hash_prefix():
    assert extract_order_number_from_subject("Order Confirmation #WB-2026-00123") == "WB-2026-00123"


def test_order_number_generic_order_colon():
    assert extract_order_number_from_subject("Order: 12345678") == "12345678"


def test_order_number_not_found_returns_none():
    assert extract_order_number_from_subject("Thank you for shopping with us!") is None


def test_order_number_empty_string_returns_none():
    assert extract_order_number_from_subject("") is None


def test_order_number_none_input_returns_none():
    assert extract_order_number_from_subject(None) is None


def test_order_number_too_short_ignored():
    # Numbers shorter than 7 chars are not order numbers
    assert extract_order_number_from_subject("Order 123") is None


# --------------------------------------------------------------------------- #
# extract_sender_email
# --------------------------------------------------------------------------- #

def test_sender_with_display_name():
    assert extract_sender_email("Kohl's <noreply@kohls.com>") == "noreply@kohls.com"


def test_sender_bare_address():
    assert extract_sender_email("noreply@kohls.com") == "noreply@kohls.com"


def test_sender_walmart_business():
    assert extract_sender_email("Walmart Business <businessinfo@walmart.com>") == "businessinfo@walmart.com"


def test_sender_uppercased_normalised():
    assert extract_sender_email("LEGO <NOREPLY@E.LEGO.COM>") == "noreply@e.lego.com"


def test_sender_empty_string():
    assert extract_sender_email("") == ""


# --------------------------------------------------------------------------- #
# detect_retailer_from_sender
# --------------------------------------------------------------------------- #

def test_detect_kohls():
    assert detect_retailer_from_sender("noreply@kohls.com") == "KOHLS"


def test_detect_walmart_business():
    assert detect_retailer_from_sender("businessinfo@walmart.com") == "WALMART BUSINESS"


def test_detect_walmart_personal():
    assert detect_retailer_from_sender("help@walmart.com") == "WALMART"


def test_detect_lego():
    assert detect_retailer_from_sender("shipping@e.lego.com") == "LEGO"


def test_detect_macys():
    assert detect_retailer_from_sender("invoice@macys.com") == "MACYS"


def test_detect_target():
    assert detect_retailer_from_sender("noreply@target.com") == "TARGET"


def test_detect_unknown():
    assert detect_retailer_from_sender("info@unknownretailer.com") == "UNKNOWN"


# --------------------------------------------------------------------------- #
# extract_email_date
# --------------------------------------------------------------------------- #

def test_email_date_rfc2822_utc():
    assert extract_email_date("Mon, 08 Jun 2026 14:30:00 +0000") == "2026-06-08"


def test_email_date_rfc2822_negative_offset():
    # Dec 3 2025 — LEGO order date (PST offset)
    assert extract_email_date("Wed, 03 Dec 2025 09:15:00 -0800") == "2025-12-03"


def test_email_date_invalid_falls_back_to_today():
    assert extract_email_date("not a real date") == date.today().isoformat()


def test_email_date_empty_falls_back_to_today():
    assert extract_email_date("") == date.today().isoformat()


# --------------------------------------------------------------------------- #
# has_pdf_attachment
# --------------------------------------------------------------------------- #

def test_has_pdf_attachment_top_level_part():
    payload = {"filename": "T487170400_receipt.pdf", "parts": []}
    assert has_pdf_attachment(payload) is True


def test_has_pdf_attachment_nested_multipart():
    payload = {
        "filename": "",
        "parts": [
            {"filename": "", "parts": [
                {"filename": "body.html"},
                {"filename": "invoice.pdf"},
            ]},
        ],
    }
    assert has_pdf_attachment(payload) is True


def test_has_pdf_attachment_no_pdf_present():
    payload = {"filename": "", "parts": [{"filename": "body.html"}]}
    assert has_pdf_attachment(payload) is False


def test_has_pdf_attachment_case_insensitive_extension():
    payload = {"filename": "Receipt.PDF", "parts": []}
    assert has_pdf_attachment(payload) is True


# --------------------------------------------------------------------------- #
# resolve_order_number — A-007 Tier 1 / Tier 2 cascade
# --------------------------------------------------------------------------- #

def _counting_extractor(return_value):
    """Zero-arg extractor stub that records how many times it was called."""
    calls = {"count": 0}

    def extractor():
        calls["count"] += 1
        return return_value

    extractor.calls = calls
    return extractor


def test_tier1_hit_skips_tier2_entirely():
    # Subject alone resolves the order — Tier 2 extractor must never run,
    # even though a PDF is present, so no wasted PDF opens.
    extractor = _counting_extractor("T487170400")
    order_number, tier = resolve_order_number(
        "Invoice for Order T487170400", has_pdf=True, pdf_order_extractor=extractor
    )
    assert (order_number, tier) == ("T487170400", "subject")
    assert extractor.calls["count"] == 0


def test_tier1_miss_with_pdf_falls_through_to_tier2():
    extractor = _counting_extractor("T999888777")
    order_number, tier = resolve_order_number(
        "Thanks for your LEGO purchase!", has_pdf=True, pdf_order_extractor=extractor
    )
    assert (order_number, tier) == ("T999888777", "pdf")
    assert extractor.calls["count"] == 1


def test_tier1_miss_no_pdf_never_attempts_tier2():
    extractor = _counting_extractor("SHOULD_NOT_BE_USED")
    order_number, tier = resolve_order_number(
        "Thanks for your LEGO purchase!", has_pdf=False, pdf_order_extractor=extractor
    )
    assert (order_number, tier) == (None, "none")
    assert extractor.calls["count"] == 0


def test_tier2_extractor_finds_no_order_number_in_pdf():
    # PDF present, Tier 1 misses, but the PDF itself has no extractable order number.
    extractor = _counting_extractor(None)
    order_number, tier = resolve_order_number(
        "Thanks for your LEGO purchase!", has_pdf=True, pdf_order_extractor=extractor
    )
    assert (order_number, tier) == (None, "none")
    assert extractor.calls["count"] == 1


# --------------------------------------------------------------------------- #
# match_order — read-only lookup, no stub-order creation (Tier 2 safety)
# --------------------------------------------------------------------------- #

class _FakeQueryResult:
    def __init__(self, data):
        self.data = data


class _FakeOrdersQuery:
    """Minimal chainable stand-in for the Supabase query builder, filtering
    an in-memory list of order rows. SELECT-only — no insert/update/delete
    methods exist, so a Tier 2 match accidentally creating a stub order
    would raise AttributeError instead of silently succeeding."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        return _FakeOrdersQuery([r for r in self._rows if r.get(field) == value])

    def execute(self):
        return _FakeQueryResult(self._rows)


class _FakeSupabaseClient:
    def __init__(self, orders):
        self._orders = orders

    def table(self, name):
        assert name == "orders", f"unexpected table access in pure-logic test: {name}"
        return _FakeOrdersQuery(self._orders)


def test_match_order_found():
    client = _FakeSupabaseClient([
        {"order_id": "abc-123", "order_number": "T487170400",
         "user_id": PHASE_1_USER_ID, "retailer": "LEGO", "order_date": "2025-12-03"},
    ])
    result = match_order("T487170400", client)
    assert result == {
        "order_id": "abc-123", "order_number": "T487170400",
        "user_id": PHASE_1_USER_ID, "retailer": "LEGO", "order_date": "2025-12-03",
    }


def test_match_order_tier2_number_with_no_matching_row_returns_none():
    # Simulates a Tier 2 PDF extraction that yields a real-looking order
    # number with no corresponding row in `orders` — must resolve to None
    # (caller treats this as UNMATCHED) rather than raising or inserting.
    client = _FakeSupabaseClient([
        {"order_id": "abc-123", "order_number": "T487170400",
         "user_id": PHASE_1_USER_ID, "retailer": "LEGO", "order_date": "2025-12-03"},
    ])
    result = match_order("T000000000", client)
    assert result is None


class _ExplodingClient:
    """Raises if anything touches .table() — proves match_order short-circuits
    on a falsy order_number instead of firing a query with no filter value."""

    def table(self, name):
        raise AssertionError("match_order should not query when order_number is falsy")


def test_match_order_none_order_number_returns_none_without_querying():
    assert match_order(None, _ExplodingClient()) is None


def test_match_order_empty_string_order_number_returns_none_without_querying():
    assert match_order("", _ExplodingClient()) is None


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
