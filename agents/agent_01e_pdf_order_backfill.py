"""
ResellOS — Agent 01E: Historical PDF -> Order Backfill
========================================================
Closes the gap Agent 01D's Drive backfill exposed: LEGO invoices sit filed
in business Drive's Invoices/Lego/_unmatched/ folder (copied there by Agent
01D), each with an invoice_files ledger row but no matching Supabase order.
Until an order_number has an `orders` row, nothing else in ResellOS (cost
basis, reconciliation, Amazon-readiness recordkeeping) can see that
purchase.

This agent reuses Agent 1A's parse_invoice() (invoice_parser.py) to read
each still-unmatched PDF straight out of business Drive.

REWRITTEN 2026-09-18 (CONTEXT.md Open Question #22) -- read this before the
older architecture notes below, which describe the ORIGINAL (2026-09-04)
design this replaces:

**The bug this closes.** A 2026-09-17 session found that for orders
shipping in multiple separate boxes, this agent sometimes only ever
found/parsed ONE of the invoice PDFs, silently writing an order missing an
entire shipment's line items. The order still looked internally
"reconciled" (its subtotal matched its own incomplete data), so nothing
caught it -- 6 real orders were found broken this way and fixed by hand via
direct SQL (T450671168, T509174028, T507663840, T509176263, T508221251,
T512438222). Two root causes, both fixed here:

1. **This agent wrote orders directly**, bypassing `capture_queue` --
   ADR-023 Part 4 calls `capture_queue` "the single review gate" every
   non-manual capture path lands in, but this agent only ever used it as an
   after-the-fact audit log, not a real gate. Fixed: this agent now ALWAYS
   writes into `capture_queue` first, exactly like the Chrome extension
   does, and a clean new order gets promoted through
   `capture_queue_promotion.auto_promote()` -- the same shared,
   non-interactive promotion path any future unattended writer can reuse --
   instead of this agent's own private copy of the write logic.

2. **Nothing ever compared newly-found PDF data against an order that
   already existed** -- when an order_number already had a real order, this
   agent just linked the invoice file and stopped, with zero check that the
   PDF's contents actually matched what was on file. Fixed: it now calls
   `order_validators.find_missing_line_items()` to compare, and:
     - **Matches** -> links the invoice file (as before) AND writes a
       "confirmed, no discrepancy" audit row to `capture_queue` (status
       already `promoted`) so there's a durable record this PDF was
       checked, not just silence.
     - **Doesn't match** -> links the invoice file (it genuinely is
       documentation for that order, regardless of what happens next) AND
       writes a `capture_queue` row with `raw_data._discrepancy` set,
       status `pending`, describing exactly what's missing. Per Josh's
       explicit instruction, THIS AGENT NEVER APPLIES THE FIX ITSELF -- it
       only flags it. A human resolves it via `capture_queue_promotion.py`
       (`_resolve_discrepancy_row()`, reached automatically through
       `promote()`) or `capture_queue_review_app.py`.

**Going forward, most order_numbers this agent sees will already exist**
(Josh captures live or within a few days via the Chrome extension, and the
PDF invoice usually arrives after). The "brand new order_number" auto-write
path below is expected to matter mostly for the historical backlog and any
retailer/period the extension doesn't cover -- the match/discrepancy path
above is the primary case now, not a corner case.

**Safe to run unattended on a schedule**, added 2026-09-18. Run with
`--run` for a fully non-interactive scan-and-process pass (no menu, no
confirmation prompts) -- see SESSION_LOG.md/CONTEXT.md for plain-language
Windows Task Scheduler setup steps. `--preview` and `--report` give the
same non-interactive treatment to Modes 1 and 3, for scripting/logging.
With no arguments, the original interactive menu still runs, unchanged, so
nothing breaks for a manual session at a terminal.

FIELDS THIS AGENT NEVER FILLS (DECISION 017 / ADR-023's field split,
identical to every other agent in this codebase): buy_reason,
purchase_trigger, gift_card_last4 (PDFs never print a gift card's last 4),
cashback_rate. These stay null. Josh can fill them in later, per order,
whenever he wants -- they're optional and hidden from basic users by design
(CONTEXT.md).

SPLIT SHIPMENTS: a single order_number can have more than one invoice PDF
(LEGO ships in waves). Backlog rows are grouped by order_number before
processing -- a group with N invoices becomes ONE order (subtotal/tax/
total summed across the group, since that's what was actually spent) with
N shipments, each carrying its own invoice's line items, when writing a
BRAND NEW order. If ANY invoice in the group is flagged, the WHOLE
order_number is left for manual review rather than partially written.

WHAT THIS AGENT DOES NOT DO:
  - Never touches personal Drive (everything it reads is already sitting
    in BUSINESS Drive, filed there by Agent 01D).
  - Never modifies an existing order's line_items itself -- a discrepancy
    is always left for a human to resolve (see above).
  - Never sets order_status to anything but 'pending_review'.
  - Never triggers the cost basis engine.

Modes:
  1 — Preview : scan the backlog, parse + classify every order_number
                group, print the plan and outcome counts. No writes
                anywhere -- not to orders, capture_queue, or invoice_files.
  2 — Run     : execute the plan from Mode 1 (writes capture_queue rows for
                everything, auto-promotes clean new orders, flags
                discrepancies against existing orders, links invoice_files
                where safe).
  3 — Report  : summarize the current capture_queue state for this
                agent's rows (source = agent_1d_pdf_backfill) --
                how many promoted vs. still pending review, with reasons.

NAMING NOTE (flag for Josh, matches the open agent-numbering question in
CONTEXT.md re: agent_08): ADR-023 Part 4 calls this future piece "Agent 1D"
and says it should write into capture_queue with raw_data.source =
"agent_1d_pdf_backfill". By the time this was built, "Agent 1D" already
meant the Drive file-copy agent (agent_01d_drive_historical_backfill.py).
Rather than have two different scripts both claim the "1D" name, this one
is filed as 01E. The raw_data source string below is kept as ADR-023
literally specified ("agent_1d_pdf_backfill") since that's a documented
wire-format value, not a filename.

RE-RUN SAFETY: idempotency is per invoice_files row, via its own `order_id`
column -- once a row is linked to an order (whether by a clean auto-write,
a confirmed match, or a flagged-but-still-linked discrepancy), it drops out
of `fetch_backlog_rows()`'s query and won't be re-processed. The one
exception is a PDF that fails to parse entirely or has no extractable
order_number at all -- those have nothing to link to, so they get queued
fresh every run rather than being remembered. A capture_queue row still
sitting `pending` (no real order yet) IS re-visited on every run --
`_apply_merge_pending()` (backed by `_unmerged_invoice_pairs()`) only
appends an invoice's data once per invoice_files row id, not per
invoice_number (a real PDF can parse with no invoice_number at all, which
would defeat a dedup keyed on it), so this is safe to re-run repeatedly
without piling up duplicate content while something waits for review.

Usage: python agents/agent_01e_pdf_order_backfill.py [--run | --preview | --report]
"""

import argparse
import io
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_client import get_client, PHASE_1_USER_ID              # noqa: E402
from invoice_parser import parse_invoice, LegoInvoice            # noqa: E402
from order_validators import (  # noqa: E402
    run_all_checks,
    find_missing_line_items,
    raw_line_items_to_compare_items,
)
from capture_queue_promotion import auto_promote                 # noqa: E402

from agent_01b_invoice_filing import (                           # noqa: E402
    build_business_services,
    get_input,
    get_yes_no,
)
from agent_01d_drive_historical_backfill import download_pdf_bytes  # noqa: E402


SOURCE_TAG = "agent_1d_pdf_backfill"     # ADR-023's documented wire value -- see NAMING NOTE above
ENTRY_METHOD = "agent_1e_pdf_backfill"
LEDGER_KEY_PREFIX = "drive-backfill:"    # Agent 01D's invoice_files key scheme, reused for lookup only

# order_validators.py check names that are real red flags -- block auto-write.
# "missing_set_number" is deliberately excluded: order_validators.py's own
# docstring calls it informational-only, and it's common on the older backlog.
_BLOCKING_CHECK_NAMES = {"gwp_price_mismatch", "line_item_total_mismatch", "cross_shipment_duplicate"}


# --------------------------------------------------------------------------- #
# Backlog source: invoice_files rows Agent 01D filed but couldn't match
# --------------------------------------------------------------------------- #

def fetch_backlog_rows(client) -> list[dict]:
    """
    Every LEGO invoice Agent 01D copied into business Drive's _unmatched/
    folder that still has no order linked. Paginated -- the backlog is
    comfortably under Supabase's default page size today but this agent
    is meant to be safe to re-run indefinitely, so don't silently cap it.
    """
    rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        result = (
            client.table("invoice_files")
            .select("id, drive_file_id, filed_filename")
            .eq("user_id", PHASE_1_USER_ID)
            .eq("retailer", "LEGO")
            .like("gmail_message_id", f"{LEDGER_KEY_PREFIX}%")
            .not_.is_("drive_file_id", "null")
            .is_("order_id", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def order_exists(order_number: str, client) -> Optional[str]:
    """Returns order_id if order_number already has a real order, else None.
    Orders by created_at desc (2026-09-18, code review) to match
    capture_queue_promotion._find_existing_order()'s tiebreak -- without it,
    if a duplicate order_number ever existed (nothing enforces uniqueness at
    the DB level; write_order() only warns, doesn't hard-block), this
    function and _find_existing_order() could silently pick different rows
    for "the same" order_number."""
    result = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0]["order_id"] if result.data else None


def fetch_capture_queue_row(order_number: str, client) -> Optional[dict]:
    """Returns the most recent capture_queue row for this order_number (any
    status), or None. Replaces the old boolean-only capture_queue_exists() --
    the new design needs the row's actual contents (status, raw_data) to
    decide whether to merge into it, flag a resurfaced-after-discard case,
    or leave it alone."""
    if not order_number:
        return None
    result = (
        client.table("capture_queue")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

def _parse_lego_date(date_str: Optional[str]) -> Optional[str]:
    """LEGO PDFs print dates as '03 Dec 2025' or '03 December 2025'."""
    if not date_str:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _payment_legs_to_methods(legs: list[tuple]) -> list[dict]:
    """Map LegoInvoice.payment_legs [(method_text, amount), ...] to the
    ADR-023 payment_methods[] shape. PDFs never print last4 for either
    tender type -- that's the one thing capture_stage='shipped' extension
    captures have that PDFs don't, and it's left null here on purpose."""
    methods = []
    for method_text, amount in legs:
        lower = method_text.lower()
        if "gift" in lower:
            methods.append({"type": "gift_card", "last4": None, "amount": round(amount, 2)})
        elif any(w in lower for w in ("credit", "visa", "mastercard", "amex", "debit", "card")):
            methods.append({"type": "card", "brand": method_text, "last4": None, "amount": round(amount, 2)})
        else:
            methods.append({"type": "unknown", "raw": method_text, "amount": round(amount, 2)})
    return methods


def _line_item_to_raw(item) -> dict:
    return {
        "set_number": item.set_number,
        "description": item.description,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "net_price": item.net_price,
        "is_gwp": item.is_gwp,
    }


def _invoice_to_shipment_meta(inv: LegoInvoice) -> dict:
    """Pure logic behind _apply_order_exists()'s discrepancy record below --
    shapes one invoice's financial detail for add_missing_items_to_order()'s
    shipment_meta parameter. Split out (2026-09-18, code review) so the
    real bug this closes -- a discrepancy record originally carried no
    shipment_meta at all, silently losing invoice_number/date/subtotal/tax/
    payment_method the moment the discrepancy got resolved -- has a direct
    regression test."""
    return {
        "invoice_number": inv.invoice_number,
        "invoice_date": _parse_lego_date(inv.invoice_date),
        "tracking_number": None,
        "shipment_status": "received",
        "subtotal": round(inv.subtotal or 0, 2),
        "tax_amount": round(inv.tax or 0, 2),
        "payment_method": inv.payment_method,
        # Always False -- this agent's entire job is processing a real
        # invoice PDF, so there's never a case where it doesn't have one
        # (2026-09-18, code review; a real, meaningfully-used column --
        # agents/email_enricher.py sets it True when it has no invoice).
        "no_invoice_received": False,
    }


def _invoice_to_compare_items(inv: LegoInvoice) -> list[dict]:
    """Shape one parsed invoice's line items for
    order_validators.find_missing_line_items(). Goes through
    raw_line_items_to_compare_items() (2026-09-18) -- the same function
    capture_queue_promotion.py's _merge_shipped_capture() uses -- so there is
    exactly one place deciding that "unit_price" for this comparison means
    net_price (what was actually paid), not the raw ADR-023 'unit_price'
    field (pre-discount MSRP). Feeding the wrong one in was a real bug
    caught in code review that would have overstated cost basis for a
    discounted missing item."""
    return raw_line_items_to_compare_items([_line_item_to_raw(it) for it in inv.line_items])


# --------------------------------------------------------------------------- #
# Group classification -- pure decision logic, no writes
# --------------------------------------------------------------------------- #

class InvoiceGroupPlan:
    """Everything needed to decide what to do with one order_number's worth
    of invoice(s): write a brand-new order, confirm/flag against an
    existing order, merge into a still-pending capture_queue row, or queue
    for review."""

    def __init__(self, order_number: str):
        self.order_number = order_number
        self.invoices: list[LegoInvoice] = []      # parsed invoices, one per PDF
        self.file_rows: list[dict] = []             # matching invoice_files rows (same order)
        self.parse_errors: list[str] = []            # (filed_filename, error) for files that wouldn't parse
        self.outcome: str = ""                        # set by classify()
        self.reasons: list[str] = []                  # human-readable flags, populated by classify()
        self.existing_order_id: Optional[str] = None
        self.existing_capture_row: Optional[dict] = None

    def classify(self, client) -> None:
        if self.existing_order_id:
            self.outcome = "ORDER_EXISTS"
            # Cheap insurance (2026-09-18, code review): the real comparison
            # happens in _apply_order_exists(), which doesn't need this, but
            # leaving `reasons` non-empty means any future summary/report
            # code that assumes every outcome carries a human-readable
            # explanation (the way FLAGGED/RESURFACED_AFTER_DISCARD already
            # do) won't silently print nothing for this one.
            self.reasons = [f"order_number already has an order (order_id {self.existing_order_id})"]
            return

        if self.existing_capture_row:
            status = self.existing_capture_row.get("status")
            if status == "pending":
                self.outcome = "MERGE_PENDING"
                return
            if status == "discarded":
                self.outcome = "RESURFACED_AFTER_DISCARD"
                return
            if status == "promoted" and self.existing_capture_row.get("promoted_order_id"):
                # Edge case: promoted but order_exists() somehow missed it
                # (e.g. a different user_id mismatch never expected in
                # practice). Fall back to the same path ORDER_EXISTS uses.
                self.existing_order_id = self.existing_capture_row["promoted_order_id"]
                self.outcome = "ORDER_EXISTS"
                return
            # Any other/unknown status -- fall through to normal classification
            # rather than getting stuck; treat as if nothing existed.

        if self.parse_errors:
            self.outcome = "FLAGGED"
            self.reasons.append(
                f"{len(self.parse_errors)} PDF(s) in this order failed to parse"
            )

        if not self.invoices:
            self.outcome = "FLAGGED"
            self.reasons.append("no invoice parsed cleanly for this order_number")
            return

        primary = self.invoices[0]
        order_date_iso = _parse_lego_date(primary.order_date) or _parse_lego_date(primary.invoice_date)
        if not order_date_iso:
            self.reasons.append("no usable order date on any invoice in this group")

        combined_items = [it for inv in self.invoices for it in inv.line_items]
        if not combined_items:
            self.reasons.append("no line items extracted")

        subtotal_sum = sum(inv.subtotal for inv in self.invoices if inv.subtotal is not None)
        if not any(inv.subtotal is not None for inv in self.invoices):
            self.reasons.append("no subtotal extracted on any invoice")

        if not any(inv.order_total is not None for inv in self.invoices):
            self.reasons.append("no invoice total extracted on any invoice")

        check_items = [
            {
                "set_name": it.description,
                "set_number": it.set_number,
                "is_gwp": it.is_gwp,
                "unit_price": it.net_price,
                "quantity": it.quantity,
                "line_total": round(it.net_price * it.quantity, 2),
            }
            for it in combined_items
        ]
        warnings = run_all_checks(
            order_id=None, items=check_items,
            expected_subtotal=round(subtotal_sum, 2) if subtotal_sum else None,
            entry_method=None, client=client,
        )
        blocking = [w for w in warnings if w.get("check") in _BLOCKING_CHECK_NAMES]
        if blocking:
            self.reasons.extend(w["message"] for w in blocking)

        self.outcome = "FLAGGED" if self.reasons else "CLEAN"


# --------------------------------------------------------------------------- #
# Scan: download + parse every backlog row, group by order_number
# --------------------------------------------------------------------------- #

def scan_and_group(drive_business, client) -> tuple[list[InvoiceGroupPlan], list[dict]]:
    """Returns (plans, download_errors). No "already queued, skip entirely"
    shortcut anymore (removed 2026-09-18) -- re-run safety now comes from
    invoice_files.order_id (see module docstring's RE-RUN SAFETY section),
    and every group's existing order/capture_queue state is looked up so
    classify()/apply_plan() can make a real comparison instead of blindly
    skipping."""
    rows = fetch_backlog_rows(client)
    print(f"\n  {len(rows)} unmatched invoice_files row(s) found (Agent 01D's backlog).\n")

    groups: dict[str, InvoiceGroupPlan] = {}
    unresolved: list[dict] = []   # rows whose PDF wouldn't parse at all or had no order_number
    download_errors: list[dict] = []

    for i, row in enumerate(rows, 1):
        try:
            pdf_bytes = download_pdf_bytes(drive_business, row["drive_file_id"])
        except HttpError as e:
            print(f"  {i:>4}. ERROR downloading {row.get('filed_filename', row['id'])}: {e}")
            download_errors.append({"row": row, "error": str(e)})
            continue

        try:
            invoice = parse_invoice(io.BytesIO(pdf_bytes))
        except Exception as e:
            unresolved.append({"row": row, "error": str(e)})
            print(f"  {i:>4}. PARSE ERROR  {row.get('filed_filename', row['id'])}: {e}")
            continue

        if not invoice.order_number:
            unresolved.append({"row": row, "error": "no order_number extracted"})
            print(f"  {i:>4}. NO ORDER #    {row.get('filed_filename', row['id'])}")
            continue

        order_number = invoice.order_number
        if order_number not in groups:
            groups[order_number] = InvoiceGroupPlan(order_number)
            groups[order_number].existing_order_id = order_exists(order_number, client)
            if not groups[order_number].existing_order_id:
                groups[order_number].existing_capture_row = fetch_capture_queue_row(order_number, client)

        plan = groups[order_number]
        plan.invoices.append(invoice)
        plan.file_rows.append(row)
        label = "MATCH" if plan.existing_order_id else "NEW"
        print(f"  {i:>4}. {label:<5} order {order_number}  ({row.get('filed_filename', row['id'])[:50]})")

    for u in unresolved:
        row = u["row"]
        # File with no extractable order_number gets its own single-row group keyed by
        # the ledger id, so it still surfaces as something needing manual attention rather
        # than silently vanishing.
        key = f"__unresolved__:{row['id']}"
        plan = InvoiceGroupPlan(key)
        plan.parse_errors.append(f"{row.get('filed_filename', row['id'])}: {u['error']}")
        plan.file_rows.append(row)
        groups[key] = plan

    plans = list(groups.values())
    for plan in plans:
        plan.classify(client)

    return plans, download_errors


# --------------------------------------------------------------------------- #
# Build the raw_data / order rows for a BRAND NEW order_number
# --------------------------------------------------------------------------- #

def _build_raw_data(plan: InvoiceGroupPlan) -> dict:
    combined_items = [it for inv in plan.invoices for it in inv.line_items]
    primary = plan.invoices[0] if plan.invoices else None
    order_date_iso = None
    if primary:
        order_date_iso = _parse_lego_date(primary.order_date) or _parse_lego_date(primary.invoice_date)

    all_legs = [leg for inv in plan.invoices for leg in inv.payment_legs]
    subtotal_sum = round(sum(inv.subtotal or 0 for inv in plan.invoices), 2) if plan.invoices else None
    tax_sum = round(sum(inv.tax or 0 for inv in plan.invoices), 2) if plan.invoices else None
    total_sum = round(sum(inv.order_total or 0 for inv in plan.invoices), 2) if plan.invoices else None
    # LEGO PDFs print "Insider points redeemed" separately from points
    # earned -- ADR-023's raw_data contract has no field for this (only
    # rewards_earned, for points EARNED), so it's added here as a plain
    # extra field, read back out by capture_queue_promotion.auto_promote()
    # (2026-09-18: restores a real field the old, deleted direct-write path
    # used to set on `orders` that got silently dropped when this agent was
    # rewritten to route through capture_queue -- caught in code review).
    points_redeemed_sum = round(sum(inv.insider_points_redeemed or 0 for inv in plan.invoices), 2)

    shipments = [
        {
            "tracking_number": None,
            "status": "received",
            "set_numbers": [it.set_number for it in inv.line_items if it.set_number],
            # invoice_number/invoice_date/subtotal/tax_amount/payment_method
            # (2026-09-18): migration 002 added these columns specifically
            # so a PDF-parsed shipment's own financial detail could be
            # stored directly -- restored here after code review found
            # they'd been silently dropped by routing through the shared
            # _write_shipments() (which only ever needed tracking_number/
            # status/set_numbers for the Chrome extension's shape). Extra
            # keys a Chrome-extension shipment group never carries -- safe,
            # _write_shipments() reads them with .get() and leaves the
            # columns null when absent.
            "invoice_number": inv.invoice_number,
            "invoice_date": _parse_lego_date(inv.invoice_date),
            "subtotal": round(inv.subtotal or 0, 2),
            "tax_amount": round(inv.tax or 0, 2),
            "payment_method": inv.payment_method,
            "no_invoice_received": False,
        }
        for inv in plan.invoices
    ]

    return {
        "source": SOURCE_TAG,
        # A PDF invoice is proof of what actually happened (like the
        # extension's "shipped" stage), not a point-of-purchase snapshot
        # (like "checkout") -- relabeled 2026-09-18 from the old, mislabeled
        # "checkout" value. This only matters when an order already exists
        # (capture_queue_promotion.py's promote() branches on it); a
        # brand-new order_number promotes the same way regardless of stage.
        "capture_stage": "shipped",
        "retailer": "lego",
        "order_number": plan.order_number if not plan.order_number.startswith("__unresolved__") else None,
        "order_date": order_date_iso,
        "line_items": [_line_item_to_raw(it) for it in combined_items],
        "subtotal": subtotal_sum,
        "tax": tax_sum,
        "total": total_sum,
        "balance_due": None,
        "rewards_earned": None,
        "insider_points_redeemed": points_redeemed_sum,
        "gift_card_last4": None,
        "payment_methods": _payment_legs_to_methods(all_legs),
        "shipments": shipments,
        "_flags": list(plan.reasons),
        "_parse_errors": list(plan.parse_errors),
    }


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _base_capture_row(plan: InvoiceGroupPlan, raw_data: dict) -> dict:
    return {
        "user_id": PHASE_1_USER_ID,
        "retailer": "lego",
        "source_url": None,
        "captured_at": _now_iso(),
        "raw_data": raw_data,
        "order_number": raw_data.get("order_number"),
        "order_date": raw_data.get("order_date"),
        "total": raw_data.get("total"),
        "status": "pending",
    }


def _link_invoice_files(plan: InvoiceGroupPlan, order_id: Optional[str], client) -> None:
    for row in plan.file_rows:
        client.table("invoice_files").update({"order_id": order_id}).eq("id", row["id"]).execute()


# --------------------------------------------------------------------------- #
# Apply: every group always lands in capture_queue in some form
# --------------------------------------------------------------------------- #

def _apply_order_exists(plan: InvoiceGroupPlan, client) -> tuple[str, str]:
    """The order_number already has a real order. Compare what this run's
    PDF(s) say against what's actually on file, and either confirm (quiet
    but logged) or flag (never auto-fixed -- see module docstring)."""
    order_id = plan.existing_order_id
    compare_items = [item for inv in plan.invoices for item in _invoice_to_compare_items(inv)]

    if not compare_items:
        # Every invoice in this group failed to parse into usable items --
        # nothing to compare, but still worth a flagged record rather than
        # silence, since a human should know a PDF for this order exists
        # and couldn't be checked.
        raw_data = _build_raw_data(plan)
        raw_data["_discrepancy"] = {
            "existing_order_id": order_id,
            "missing_items": [],
            "detected_by": ENTRY_METHOD,
            "detected_at": _now_iso(),
            "note": "Invoice(s) found for this order but none parsed into usable line items -- could not compare.",
        }
        capture_row = _base_capture_row(plan, raw_data)
        client.table("capture_queue").insert(capture_row).execute()
        _link_invoice_files(plan, order_id, client)
        return "FLAGGED_UNPARSEABLE", f"order exists (order_id {order_id}) but nothing parsed to compare"

    missing = find_missing_line_items(order_id, compare_items, client=client)
    raw_data = _build_raw_data(plan)

    if not missing:
        raw_data["_confirmed_match"] = {
            "existing_order_id": order_id,
            "confirmed_by": ENTRY_METHOD,
            "confirmed_at": _now_iso(),
        }
        capture_row = _base_capture_row(plan, raw_data)
        capture_row["status"] = "promoted"
        capture_row["promoted_order_id"] = order_id
        capture_row["reviewed_at"] = _now_iso()
        capture_row["review_note"] = (
            "Confirmed by agent_1e -- PDF invoice matches order, no discrepancy found."
        )
        client.table("capture_queue").insert(capture_row).execute()
        _link_invoice_files(plan, order_id, client)
        return "CONFIRMED", f"order_id {order_id}"

    # Attributed to the first invoice in this run (best-effort, matching the
    # same "usually one new shipment" assumption capture_queue_promotion.py's
    # _merge_shipped_capture() makes) -- unlike that function, there's no
    # follow-up _write_shipments() call in the review path that would risk
    # double-creating a shipment, so it's safe to always pass this along
    # (added 2026-09-18 after code review found the discrepancy record
    # never carried it at all, silently losing the invoice's financial
    # detail whenever a discrepancy got resolved).
    shipment_meta = _invoice_to_shipment_meta(plan.invoices[0]) if plan.invoices else None

    raw_data["_discrepancy"] = {
        "existing_order_id": order_id,
        "missing_items": missing,
        "detected_by": ENTRY_METHOD,
        "detected_at": _now_iso(),
        "shipment_meta": shipment_meta,
    }
    capture_row = _base_capture_row(plan, raw_data)
    client.table("capture_queue").insert(capture_row).execute()
    _link_invoice_files(plan, order_id, client)
    return "DISCREPANCY", f"order_id {order_id}, {len(missing)} item(s)"


def _unmerged_invoice_pairs(invoices: list, file_rows: list[dict], already_merged_ids: set) -> list[tuple]:
    """Pure filtering logic behind _apply_merge_pending() below -- which of
    this run's (invoice, file_row) pairs aren't already represented in a
    pending capture_queue row's raw_data. Split out (2026-09-18) so the
    exact bug caught in code review -- de-duping by invoice_number, which
    can be None and would then never actually dedupe -- has a direct
    regression test. `invoices` and `file_rows` are index-parallel (both
    appended together in scan_and_group()'s main loop)."""
    return [
        (inv, file_row) for inv, file_row in zip(invoices, file_rows)
        if file_row["id"] not in already_merged_ids
    ]


def _apply_merge_pending(plan: InvoiceGroupPlan, client) -> tuple[str, str]:
    """The order_number is already sitting as a 'pending' capture_queue row
    (no real order yet -- e.g. the Chrome extension captured it but Josh
    hasn't reviewed it). Merge this run's newly-found invoice(s) into that
    same row instead of creating a second, competing row for the same
    order_number.

    Idempotent per invoice_files row id (`plan.file_rows`, index-parallel to
    `plan.invoices` -- both are appended together in scan_and_group()'s main
    loop), NOT per invoice_number -- a real PDF can parse with no
    invoice_number at all (invoice_parser.py leaves it Optional), and
    de-duping on that would have treated every such invoice as "new" on
    every re-run forever, silently re-duplicating its items and dollar
    totals into raw_data each time (caught in code review, 2026-09-18,
    before this ever ran against real data)."""
    row = plan.existing_capture_row
    raw = row.get("raw_data") or {}
    already_merged = set(raw.get("_agent_1e_merged_file_ids") or [])

    new_pairs = _unmerged_invoice_pairs(plan.invoices, plan.file_rows, already_merged)
    if not new_pairs:
        return "NOTHING_NEW", f"already merged into pending capture_id {row['capture_id']}"
    new_invoices = [inv for inv, _ in new_pairs]

    new_items = [_line_item_to_raw(it) for inv in new_invoices for it in inv.line_items]
    new_shipments = [
        {
            "tracking_number": None,
            "status": "received",
            "set_numbers": [it.set_number for it in inv.line_items if it.set_number],
            # Same financial fields _build_raw_data() carries for the
            # CLEAN/brand-new path (2026-09-18 fix) -- omitted here
            # originally, which would have silently dropped this invoice's
            # detail once the row is eventually promoted and its shipments
            # get written (caught in code review).
            "invoice_number": inv.invoice_number,
            "invoice_date": _parse_lego_date(inv.invoice_date),
            "subtotal": round(inv.subtotal or 0, 2),
            "tax_amount": round(inv.tax or 0, 2),
            "payment_method": inv.payment_method,
            "no_invoice_received": False,
        }
        for inv in new_invoices
    ]

    raw["line_items"] = (raw.get("line_items") or []) + new_items
    raw["shipments"] = (raw.get("shipments") or []) + new_shipments
    raw["_agent_1e_merged_file_ids"] = sorted(
        already_merged | {file_row["id"] for _, file_row in new_pairs}
    )
    if plan.parse_errors:
        # This run may have found some invoices that parsed fine (merged
        # above) and others that didn't -- don't let those silently vanish
        # just because this path updates an existing row instead of building
        # a fresh raw_data via _build_raw_data() (which already carries
        # _parse_errors for the other outcomes).
        raw["_parse_errors"] = list(raw.get("_parse_errors") or []) + list(plan.parse_errors)
    added_subtotal = round(sum(inv.subtotal or 0 for inv in new_invoices), 2)
    added_tax = round(sum(inv.tax or 0 for inv in new_invoices), 2)
    # Treat a currently-null field as 0 and set it, rather than skipping the
    # update entirely -- a prior version only updated when the existing
    # value was already non-null, which meant a pending row captured before
    # its totals were known (e.g. an in-flight checkout-stage capture) would
    # never pick up a real total even after this merge learned one from a
    # newly-found invoice (caught in code review, 2026-09-18).
    raw["subtotal"] = round(float(raw.get("subtotal") or 0) + added_subtotal, 2)
    raw["tax"] = round(float(raw.get("tax") or 0) + added_tax, 2)
    raw["total"] = round(float(raw.get("total") or 0) + added_subtotal + added_tax, 2)

    existing_note = row.get("review_note") or ""
    merge_note = (
        f"[agent_1e merge {_now_iso()}] Added {len(new_items)} item(s) from "
        f"{len(new_invoices)} invoice(s) not previously represented in this pending capture."
    )
    new_note = (existing_note + " " if existing_note else "") + merge_note

    client.table("capture_queue").update({
        "raw_data": raw,
        "total": raw.get("total"),
        "review_note": new_note,
    }).eq("capture_id", row["capture_id"]).execute()

    return "MERGED", f"into pending capture_id {row['capture_id']}"


def _apply_resurfaced_after_discard(plan: InvoiceGroupPlan, client) -> tuple[str, str]:
    """The order_number's only prior capture_queue record was discarded --
    Josh already made a decision about it once. Rather than silently
    reviving it or silently ignoring the new PDF, raise a fresh, distinctly-
    worded pending row so it's clear this needs a second look, not a
    duplicate of the original.

    No real order exists yet, so -- same as _apply_merge_pending -- there's
    nothing to link invoice_files.order_id to; this row stays "pending" and
    IS re-fetched on future runs (by design, matching the module's
    documented re-run behavior for a still-open row). Seeds
    _agent_1e_merged_file_ids with THIS run's invoice_files ids so that a
    later run finding the SAME PDFs again (classified MERGE_PENDING against
    the row just created here, since it's now the most recent row for this
    order_number) recognizes them as already represented instead of
    re-appending the same items a second time (caught in code review,
    2026-09-18)."""
    prior = plan.existing_capture_row
    raw_data = _build_raw_data(plan)
    raw_data["_flags"] = list(raw_data.get("_flags") or []) + [
        f"A previous capture_queue row for this order_number was discarded "
        f"(reason: {prior.get('review_note') or 'no reason recorded'}). This PDF resurfaced it -- "
        f"confirm whether this is a genuine new data point or the same thing already handled."
    ]
    raw_data["_agent_1e_merged_file_ids"] = sorted({row["id"] for row in plan.file_rows})
    capture_row = _base_capture_row(plan, raw_data)
    client.table("capture_queue").insert(capture_row).execute()
    return "RESURFACED", "flagged for review, prior row was discarded"


# Every category apply_plan() can return -- kept as one explicit set (rather
# than matching against free-text message prefixes, which is exactly what
# silently dropped RESURFACED/NOTHING_NEW/FLAGGED_UNPARSEABLE from the
# printed summary before this was caught in code review, 2026-09-18) so a
# future new category can't fall through unnoticed: _execute_plan() asserts
# every returned category is one of these.
OUTCOME_CATEGORIES = (
    "WRITTEN", "CONFIRMED", "DISCREPANCY", "FLAGGED_UNPARSEABLE",
    "MERGED", "NOTHING_NEW", "RESURFACED", "QUEUED", "ERROR",
)


def apply_plan(plan: InvoiceGroupPlan, client) -> tuple[str, str]:
    """Executes one group's plan. Returns (category, detail) -- category is
    always one of OUTCOME_CATEGORIES above."""
    if plan.outcome == "ORDER_EXISTS":
        return _apply_order_exists(plan, client)

    if plan.outcome == "MERGE_PENDING":
        return _apply_merge_pending(plan, client)

    if plan.outcome == "RESURFACED_AFTER_DISCARD":
        return _apply_resurfaced_after_discard(plan, client)

    raw_data = _build_raw_data(plan)
    # Seed the merge-dedup marker on every insert path, not just
    # _apply_resurfaced_after_discard() (caught in code review, 2026-09-18):
    # a FLAGGED row never links invoice_files either, so it's re-fetched on
    # every future run just like a resurfaced-after-discard row is -- without
    # this, the first _apply_merge_pending() pass against it (once its
    # status is still 'pending' on the next run) would have seen an empty
    # already-merged set and re-appended the same items/dollars on top of
    # what this insert already wrote.
    raw_data["_agent_1e_merged_file_ids"] = sorted({row["id"] for row in plan.file_rows})
    capture_row = _base_capture_row(plan, raw_data)

    if plan.outcome == "FLAGGED":
        client.table("capture_queue").insert(capture_row).execute()
        return "QUEUED", '; '.join(plan.reasons)[:120]

    # CLEAN, brand-new order_number -- write to capture_queue first (ADR-023's
    # gate), then auto-promote through the shared, non-interactive path
    # (2026-09-18: replaces this agent's old private write logic).
    insert_result = client.table("capture_queue").insert(capture_row).execute()
    if not insert_result.data:
        return "ERROR", "capture_queue insert failed, nothing written"
    row = insert_result.data[0]

    result = auto_promote(client, row)
    if not result["ok"]:
        return "QUEUED", f"auto-promote failed: {result['message']}"

    _link_invoice_files(plan, result["order_id"], client)
    return "WRITTEN", f"order_id {result['order_id']}"


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #

def _print_plan_summary(plans: list[InvoiceGroupPlan], download_errors: list) -> None:
    clean = [p for p in plans if p.outcome == "CLEAN"]
    flagged = [p for p in plans if p.outcome == "FLAGGED"]
    existing = [p for p in plans if p.outcome == "ORDER_EXISTS"]
    merge_pending = [p for p in plans if p.outcome == "MERGE_PENDING"]
    resurfaced = [p for p in plans if p.outcome == "RESURFACED_AFTER_DISCARD"]
    print()
    print("-" * 70)
    print(
        f"  {len(plans)} order_number group(s) evaluated: "
        f"{len(clean)} clean new order(s) | {len(flagged)} flagged for review | "
        f"{len(existing)} already have an order (will compare) | "
        f"{len(merge_pending)} merge into a pending capture | "
        f"{len(resurfaced)} resurfaced after a prior discard"
    )
    print(f"  Download errors: {len(download_errors)}")
    if flagged:
        print("\n  Flagged order_numbers and why:")
        for p in flagged[:40]:
            label = p.order_number if not p.order_number.startswith("__unresolved__") else "(unparseable file)"
            print(f"    {label}: {'; '.join(p.reasons)[:140]}")
        if len(flagged) > 40:
            print(f"    ... and {len(flagged) - 40} more.")


def mode_preview(drive_business, client) -> None:
    print("\n" + "=" * 70)
    print("  AGENT 01E — PDF -> ORDER BACKFILL — PREVIEW")
    print("  No writes anywhere (orders, capture_queue, invoice_files all untouched)")
    print("=" * 70)
    plans, errors = scan_and_group(drive_business, client)
    _print_plan_summary(plans, errors)
    print("\n  Run Mode 2 (or --run) to execute this plan.")


def _execute_plan(plans: list[InvoiceGroupPlan], client) -> dict:
    """Runs apply_plan() for every group and tallies outcomes by category.
    Every category in OUTCOME_CATEGORIES is counted explicitly (2026-09-18
    fix: the previous version matched free-text message prefixes into a
    fixed WRITTEN/CONFIRMED/DISCREPANCY/MERGED/QUEUED/OTHER bucket set and
    then never printed the OTHER count, so RESURFACED, NOTHING_NEW, and
    FLAGGED_UNPARSEABLE outcomes were silently missing from an unattended
    run's reported totals -- caught in code review before this ever ran
    against real data)."""
    outcomes = {k: 0 for k in OUTCOME_CATEGORIES}
    for i, plan in enumerate(plans, 1):
        try:
            category, detail = apply_plan(plan, client)
        except Exception as e:
            print(f"  {i:>4}. ERROR applying {plan.order_number}: {e}")
            outcomes["ERROR"] += 1
            continue
        assert category in outcomes, f"apply_plan() returned an unrecognized category: {category!r}"
        outcomes[category] += 1
        label = plan.order_number if not plan.order_number.startswith("__unresolved__") else "(unparseable file)"
        print(f"  {i:>4}. {label}: {category} -- {detail}")
    return outcomes


def mode_run(drive_business, client, *, interactive: bool = True) -> None:
    print("\n" + "=" * 70)
    print("  AGENT 01E — PDF -> ORDER BACKFILL — RUN")
    print("=" * 70)
    print()
    print("  Clean new orders are auto-promoted through capture_queue")
    print("  (order_status='pending_review' -- cost basis never fires from this).")
    print("  Orders that already exist are compared against this run's PDF data --")
    print("  a match is confirmed quietly, a mismatch is flagged for review, never")
    print("  auto-fixed. Anything else lands in capture_queue pending, same as always.")
    print()
    if interactive and not get_yes_no("Proceed?", default="n"):
        print("  Cancelled.")
        return

    plans, errors = scan_and_group(drive_business, client)
    _print_plan_summary(plans, errors)

    if interactive and not get_yes_no("\nExecute this plan?", default="n"):
        print("  Cancelled. Nothing written.")
        return

    print()
    outcomes = _execute_plan(plans, client)

    print()
    print("-" * 70)
    print(
        f"  Done. {outcomes['WRITTEN']} new order(s) written | "
        f"{outcomes['CONFIRMED']} confirmed matching an existing order | "
        f"{outcomes['DISCREPANCY']} discrepancy(ies) flagged | "
        f"{outcomes['FLAGGED_UNPARSEABLE']} flagged (order exists, nothing parsed to compare) | "
        f"{outcomes['MERGED']} merged into a pending capture | "
        f"{outcomes['NOTHING_NEW']} already merged (no-op this run) | "
        f"{outcomes['RESURFACED']} resurfaced after a prior discard | "
        f"{outcomes['QUEUED']} queued for review | "
        f"{outcomes['ERROR']} error(s)"
    )
    print("  Run Mode 3 (Report) anytime to see current capture_queue status,")
    print("  or open capture_queue_promotion.py / capture_queue_review_app.py to review flagged rows.")


def mode_report(client) -> None:
    print("\n" + "=" * 70)
    print("  AGENT 01E — CAPTURE QUEUE STATUS (this agent's rows)")
    print("=" * 70)
    detail = (
        client.table("capture_queue")
        .select("status, order_number, raw_data")
        .eq("user_id", PHASE_1_USER_ID)
        .execute()
    )
    all_rows = detail.data or []
    print(f"\n  {len(all_rows)} total capture_queue row(s) for this account (all sources).")
    pending = [r for r in all_rows if r["status"] == "pending"]
    promoted = [r for r in all_rows if r["status"] == "promoted"]
    discarded = [r for r in all_rows if r["status"] == "discarded"]
    discrepancies = [r for r in pending if (r.get("raw_data") or {}).get("_discrepancy")]
    print(f"  pending: {len(pending)} | promoted: {len(promoted)} | discarded: {len(discarded)}")
    print(f"  of the pending rows, {len(discrepancies)} are flagged discrepancies against an existing order")
    if pending:
        print("\n  Still pending review:")
        for r in pending[:40]:
            tag = "  [DISCREPANCY]" if (r.get("raw_data") or {}).get("_discrepancy") else ""
            print(f"    {r.get('order_number') or '(no order number)'}{tag}")
        if len(pending) > 40:
            print(f"    ... and {len(pending) - 40} more.")
    print("\n  Open capture_queue_promotion.py or capture_queue_review_app.py to review pending rows.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def _connect_drive():
    print("\n  Connecting to business Drive...")
    try:
        _, drive_business = build_business_services()
        print("  Connected.")
        return drive_business
    except SystemExit:
        raise
    except Exception as e:
        print(f"  ERROR connecting to business Drive: {e}")
        return None


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Agent 01E -- Historical PDF -> Order Backfill (ResellOS)"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--run", action="store_true",
        help="Non-interactive: scan, classify, and execute immediately. No prompts. "
             "Safe for Windows Task Scheduler -- see SESSION_LOG.md/CONTEXT.md for setup steps.",
    )
    group.add_argument(
        "--preview", action="store_true",
        help="Non-interactive: scan and classify only, no writes. Prints the plan and exits.",
    )
    group.add_argument(
        "--report", action="store_true",
        help="Non-interactive: print current capture_queue status and exit.",
    )
    args = parser.parse_args()

    client = get_client()

    if args.report:
        mode_report(client)
        return

    if args.run or args.preview:
        drive_business = _connect_drive()
        if drive_business is None:
            sys.exit(1)
        if args.preview:
            mode_preview(drive_business, client)
        else:
            mode_run(drive_business, client, interactive=False)
        return

    # No flags -- original interactive menu, unchanged for a manual session.
    print("\n" + "=" * 70)
    print("  RESELLOS — AGENT 01E: HISTORICAL PDF -> ORDER BACKFILL")
    print("  LEGO only | reads business Drive _unmatched/ | safe to re-run")
    print("=" * 70)
    print()
    print("  1. Preview — scan + classify, no writes")
    print("  2. Run     — write clean orders, queue flagged/discrepant ones for review")
    print("  3. Report  — current capture_queue status")
    print()
    print("  Tip: run with --run, --preview, or --report for a non-interactive pass")
    print("  (e.g. from Windows Task Scheduler) that skips this menu entirely.")
    print()

    mode = get_input("Select mode (1/2/3)").strip()
    if mode not in ("1", "2", "3"):
        print(f"  Unknown mode '{mode}'. Enter 1, 2, or 3.")
        return

    if mode == "3":
        mode_report(client)
        return

    drive_business = _connect_drive()
    if drive_business is None:
        return

    if mode == "1":
        mode_preview(drive_business, client)
    else:
        mode_run(drive_business, client, interactive=True)


if __name__ == "__main__":
    main()
