"""
ResellOS — Agent 01E: Historical PDF -> Order Backfill
========================================================
Closes the gap Agent 01D's Drive backfill exposed: ~900 real LEGO invoices
now sit filed in business Drive's Invoices/Lego/_unmatched/ folder (copied
there by Agent 01D), each with an invoice_files ledger row but no matching
Supabase order — because that order was simply never entered. Until an
order_number has an `orders` row, nothing else in ResellOS (cost basis,
reconciliation, Amazon-readiness recordkeeping) can see that purchase.

This agent reuses Agent 1A's parse_invoice() (invoice_parser.py) to read
each still-unmatched PDF straight out of business Drive, and writes real
orders — landing every one of them at order_status = 'pending_review',
never 'confirmed' (DECISION 017's cost-basis gate: cost basis never runs
before Josh explicitly confirms an order, and this agent never does that
on his behalf).

NAMING NOTE (flag for Josh, matches the open agent-numbering question in
CONTEXT.md re: agent_08): ADR-023 Part 4 / Implementation Requirement 3
calls this future piece "Agent 1D" and says it should write into
capture_queue with raw_data.source = "agent_1d_pdf_backfill". By the time
this was built, "Agent 1D" already meant the Drive file-copy agent
(agent_01d_drive_historical_backfill.py, built 2026-09-04 earlier the same
day). Rather than have two different scripts both claim the "1D" name,
this one is filed as 01E and keeps going where 01D left off. The raw_data
source string below is kept as ADR-023 literally specified
("agent_1d_pdf_backfill") since that's a documented wire-format value, not
a filename — reconcile the naming in SESSION_LOG/ADR-023 next session.

WHY THIS WRITES ORDERS DIRECTLY INSTEAD OF ALWAYS GOING THROUGH THE
INTERACTIVE capture_queue_promotion.py REVIEW GATE:
ADR-023 built capture_queue as "the single review gate every non-manual
capture path... lands in" — one row, one interactive promotion, Josh
answering a handful of y/n prompts per order. That's the right shape for
a few new live captures a day. It is not a workable shape for ~900
historical invoices in one sitting — that's an unattended overnight job,
not something Josh should have to sit through prompt by prompt.

So every invoice this agent evaluates still gets a capture_queue row
(preserves ADR-023's "one landing zone" contract and gives a durable
audit trail + a place for genuinely uncertain ones to wait). But instead
of always leaving it 'pending' for interactive promotion, this agent
promotes it ITSELF, immediately, using the exact same write path
agent_02_order_entry.write_order() / capture_queue_promotion.py use --
ONLY when the parsed invoice is unambiguous:
  - order_number present
  - a usable order_date
  - at least one line item
  - subtotal and an invoice-printed total both present
  - order_validators.run_all_checks() raises no GWP-price-mismatch or
    line-item-total-mismatch warning (missing set_number is NOT a gate --
    order_validators.py itself documents that as informational-only, and
    it's expected on a lot of the older backlog)
Anything that fails one of those stays a 'pending' capture_queue row,
untouched, exactly the "queue to be verified" Josh asked for -- reviewed
the normal way, through capture_queue_promotion.py, at whatever pace he
wants. Nothing is ever silently dropped: every invoice evaluated ends up
in exactly one of orders (auto-promoted) or capture_queue (flagged,
pending) or a clearly logged skip.

FIELDS THIS AGENT NEVER FILLS (DECISION 017 / ADR-023's field split,
identical to every other agent in this codebase):
  buy_reason, purchase_trigger, gift_card_last4 (PDFs never print a gift
  card's last 4), cashback_rate. These stay null. Josh can fill them in
  later, per order, whenever he wants -- they're optional and hidden from
  basic users by design (CONTEXT.md).

SPLIT SHIPMENTS: a single order_number can have more than one invoice PDF
(LEGO ships in waves). Backlog rows are grouped by order_number before
processing -- a group with N invoices becomes ONE order (subtotal/tax/
total summed across the group, since that's what was actually spent) with
N shipments, each carrying its own invoice's line items. If ANY invoice
in the group is flagged, the WHOLE order_number is left for manual
review rather than partially written.

WHAT THIS AGENT DOES NOT DO:
  - Never touches personal Drive (everything it reads is already sitting
    in BUSINESS Drive, filed there by Agent 01D).
  - Never writes to an order_number that already exists in `orders` --
    that order was entered some other way (manually, by the extension) and
    this agent will not silently modify it. It DOES link the invoice into
    the invoice_files ledger (order_id) for that case, purely as
    recordkeeping, since that's a safe, reversible, read-only-in-spirit
    update.
  - Never sets order_status to anything but 'pending_review'.
  - Never triggers the cost basis engine.

Modes:
  1 — Preview : scan the backlog, parse + classify every order_number
                group, print the plan and outcome counts. No writes
                anywhere -- not to orders, capture_queue, or invoice_files.
  2 — Run     : execute the plan from Mode 1 (writes orders/shipments/
                line_items for clean groups, capture_queue rows for
                everything, invoice_files.order_id links where safe).
  3 — Report  : summarize the current capture_queue state for this
                agent's rows (source = agent_1d_pdf_backfill) --
                how many promoted vs. still pending review, with reasons.

Usage: python agents/agent_01e_pdf_order_backfill.py
"""

import io
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_client import get_client, PHASE_1_USER_ID              # noqa: E402
from invoice_parser import parse_invoice, LegoInvoice            # noqa: E402
from order_validators import run_all_checks                      # noqa: E402

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
    """Returns order_id if order_number already has a real order, else None."""
    result = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .limit(1)
        .execute()
    )
    return result.data[0]["order_id"] if result.data else None


def capture_queue_exists(order_number: str, client) -> bool:
    """True if this order_number has already been queued (any status) by
    a prior run -- keeps re-runs idempotent without a separate ledger."""
    result = (
        client.table("capture_queue")
        .select("capture_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .limit(1)
        .execute()
    )
    return bool(result.data)


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


# --------------------------------------------------------------------------- #
# Group classification -- pure decision logic, no writes
# --------------------------------------------------------------------------- #

class InvoiceGroupPlan:
    """Everything needed to either auto-write or queue-for-review one
    order_number's worth of invoice(s)."""

    def __init__(self, order_number: str):
        self.order_number = order_number
        self.invoices: list[LegoInvoice] = []      # parsed invoices, one per PDF
        self.file_rows: list[dict] = []             # matching invoice_files rows (same order)
        self.parse_errors: list[str] = []            # (filed_filename, error) for files that wouldn't parse
        self.outcome: str = ""                        # set by classify()
        self.reasons: list[str] = []                  # human-readable flags, populated by classify()
        self.existing_order_id: Optional[str] = None

    def classify(self, client) -> None:
        if self.existing_order_id:
            self.outcome = "ORDER_EXISTS"
            self.reasons = [f"order_number already has an order (order_id {self.existing_order_id})"]
            return

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

def scan_and_group(drive_business, client) -> tuple[list[InvoiceGroupPlan], int, list[dict]]:
    """Returns (plans, skipped_already_queued_count, download_errors)."""
    rows = fetch_backlog_rows(client)
    print(f"\n  {len(rows)} unmatched invoice_files row(s) found (Agent 01D's backlog).\n")

    groups: dict[str, InvoiceGroupPlan] = {}
    already_queued_order_numbers: set = set()   # order_numbers skipped this run -- checked once, not per invoice
    unresolved: list[dict] = []   # rows whose PDF wouldn't parse at all or had no order_number
    download_errors: list[dict] = []
    skipped_already_queued = 0

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
        if order_number in already_queued_order_numbers:
            continue  # already counted + logged when this order_number was first seen this run

        if order_number not in groups:
            if capture_queue_exists(order_number, client):
                already_queued_order_numbers.add(order_number)
                skipped_already_queued += 1
                print(f"  {i:>4}. SKIP (already queued)  {order_number}")
                continue
            groups[order_number] = InvoiceGroupPlan(order_number)
            groups[order_number].existing_order_id = order_exists(order_number, client)

        plan = groups[order_number]
        plan.invoices.append(invoice)
        plan.file_rows.append(row)
        label = "MATCH" if plan.existing_order_id else "NEW"
        print(f"  {i:>4}. {label:<5} order {order_number}  ({row.get('filed_filename', row['id'])[:50]})")

    for u in unresolved:
        row = u["row"]
        order_number = None  # unresolved rows never got a group -- track separately below
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

    return plans, skipped_already_queued, download_errors


# --------------------------------------------------------------------------- #
# Build the order/shipments/line_items/capture_queue rows for one group
# --------------------------------------------------------------------------- #

def _build_order_row(plan: InvoiceGroupPlan) -> dict:
    primary = plan.invoices[0]
    order_date_iso = _parse_lego_date(primary.order_date) or _parse_lego_date(primary.invoice_date)

    subtotal_sum = round(sum(inv.subtotal or 0 for inv in plan.invoices), 2)
    tax_sum = round(sum(inv.tax or 0 for inv in plan.invoices), 2)
    total_sum = round(sum(inv.order_total or 0 for inv in plan.invoices), 2)
    points_redeemed_sum = round(
        sum(inv.insider_points_redeemed or 0 for inv in plan.invoices), 2
    )

    all_legs = [leg for inv in plan.invoices for leg in inv.payment_legs]
    gift_card_applied = round(
        sum(amt for method, amt in all_legs if "gift" in method.lower()), 2
    )
    if len(all_legs) == 1:
        payment_method = all_legs[0][0]
        payment_method_detail = None
    elif len(all_legs) > 1:
        payment_method = "mixed"
        payment_method_detail = "; ".join(f"{m} ${a:.2f}" for m, a in all_legs)
    else:
        payment_method = None
        payment_method_detail = None

    combined_items = [it for inv in plan.invoices for it in inv.line_items]
    expected_item_count = sum(it.quantity for it in combined_items)

    invoice_numbers = ", ".join(inv.invoice_number for inv in plan.invoices if inv.invoice_number)
    notes = (
        f"Auto-entered by {ENTRY_METHOD} (historical PDF backfill) from invoice(s) "
        f"{invoice_numbers or 'unknown'}. No data-quality flags at write time. "
        f"buy_reason/purchase_trigger left blank -- fill in manually if relevant."
    )
    if gift_card_applied:
        notes += (
            f" Gift card tender totaling ${gift_card_applied:.2f} detected on the invoice "
            f"-- no gift_card_assignments linkage built yet, recorded here only."
        )

    return {
        "retailer": "lego",
        "order_number": plan.order_number,
        "order_date": order_date_iso,
        "subtotal": subtotal_sum,
        "tax_paid": tax_sum,
        "tax_exempt": False,
        "shipping": 0,
        "gift_card_applied": gift_card_applied,
        "rewards_applied": 0,
        "insider_points_redeemed": points_redeemed_sum,
        "insider_points_earned": 0,
        "insider_points_multiplier": 1,
        "discount_total": round(
            sum((it.unit_price - it.net_price) * it.quantity for it in combined_items), 2
        ),
        "total": total_sum if total_sum else round(subtotal_sum + tax_sum, 2),
        "payment_method": payment_method,
        "payment_method_detail": payment_method_detail,
        "purchase_trigger": None,
        "tax_exemption_method": "not_applicable",
        "pickup_method": "shipped",
        "buy_reason": None,
        "notes": notes,
        "entry_method": ENTRY_METHOD,
        "invoice_expected": True,
        "reconciliation_status": "reconciled",
        "cost_basis_state": "estimated",
        "order_status": "pending_review",
        "expected_item_count": expected_item_count,
        "expected_total": total_sum if total_sum else round(subtotal_sum + tax_sum, 2),
    }


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

    shipments = [
        {
            "tracking_number": None,
            "status": "received",
            "set_numbers": [it.set_number for it in inv.line_items if it.set_number],
            "invoice_number": inv.invoice_number,
        }
        for inv in plan.invoices
    ]

    return {
        "source": SOURCE_TAG,
        "capture_stage": "checkout",
        "retailer": "lego",
        "order_number": plan.order_number if not plan.order_number.startswith("__unresolved__") else None,
        "order_date": order_date_iso,
        "line_items": [_line_item_to_raw(it) for it in combined_items],
        "subtotal": subtotal_sum,
        "tax": tax_sum,
        "total": total_sum,
        "balance_due": None,
        "rewards_earned": None,
        "gift_card_last4": None,
        "payment_methods": _payment_legs_to_methods(all_legs),
        "shipments": shipments,
        "_flags": list(plan.reasons),
        "_parse_errors": list(plan.parse_errors),
    }


# --------------------------------------------------------------------------- #
# Apply: write capture_queue always; auto-write orders for CLEAN groups only
# --------------------------------------------------------------------------- #

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _write_order_and_shipments(order_row: dict, plan: InvoiceGroupPlan, client) -> Optional[str]:
    order_row = {**order_row, "user_id": PHASE_1_USER_ID}
    order_result = client.table("orders").insert(order_row).execute()
    if not order_result.data:
        print(f"        ERROR: order insert failed for {plan.order_number}")
        return None
    order_id = order_result.data[0]["order_id"]

    for inv in plan.invoices:
        shipment_row = {
            "user_id": PHASE_1_USER_ID,
            "order_id": order_id,
            "invoice_number": inv.invoice_number,
            "invoice_date": _parse_lego_date(inv.invoice_date),
            "subtotal": round(inv.subtotal or 0, 2),
            "tax_amount": round(inv.tax or 0, 2),
            "shipping_amount": 0,
            "payment_method": inv.payment_method,
            "shipment_status": "received",
            "entry_method": ENTRY_METHOD,
            "no_invoice_received": False,
        }
        shipment_result = client.table("shipments").insert(shipment_row).execute()
        if not shipment_result.data:
            print(f"        ERROR: shipment insert failed for {plan.order_number} / invoice {inv.invoice_number}")
            continue
        shipment_id = shipment_result.data[0]["shipment_id"]

        line_item_rows = [
            {
                "user_id": PHASE_1_USER_ID,
                "order_id": order_id,
                "shipment_id": shipment_id,
                "article_number": it.article_number,
                "set_name": it.description,
                "set_number": it.set_number,
                "quantity": it.quantity,
                "unit_price": it.net_price,
                "msrp": it.unit_price,
                "line_discount": round((it.unit_price - it.net_price) * it.quantity, 2),
                "line_total": round(it.net_price * it.quantity, 2),
                "is_gwp": it.is_gwp,
                "is_retiring": True,
            }
            for it in inv.line_items
        ]
        if line_item_rows:
            line_result = client.table("line_items").insert(line_item_rows).execute()
            if not line_result.data:
                print(f"        ERROR: line_items insert failed for shipment {shipment_id}")

    return order_id


def _link_invoice_files(plan: InvoiceGroupPlan, order_id: Optional[str], client) -> None:
    for row in plan.file_rows:
        client.table("invoice_files").update({"order_id": order_id}).eq("id", row["id"]).execute()


def apply_plan(plan: InvoiceGroupPlan, client) -> str:
    """Executes one group's plan. Returns a short outcome label for the summary line."""
    if plan.outcome == "ORDER_EXISTS":
        _link_invoice_files(plan, plan.existing_order_id, client)
        return "LINKED (order already existed)"

    raw_data = _build_raw_data(plan)
    capture_row = {
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

    if plan.outcome == "FLAGGED":
        client.table("capture_queue").insert(capture_row).execute()
        return f"QUEUED for review ({'; '.join(plan.reasons)[:120]})"

    # CLEAN — auto-promote
    order_row = _build_order_row(plan)
    order_id = _write_order_and_shipments(order_row, plan, client)
    if not order_id:
        # Write failed -- fall back to a pending capture_queue row so nothing is lost.
        client.table("capture_queue").insert(capture_row).execute()
        return "QUEUED (order write failed, see log above)"

    capture_row["status"] = "promoted"
    capture_row["promoted_order_id"] = order_id
    capture_row["reviewed_at"] = _now_iso()
    capture_row["review_note"] = "Auto-promoted by agent_01e -- clean parse, no data-quality flags."
    client.table("capture_queue").insert(capture_row).execute()

    _link_invoice_files(plan, order_id, client)
    return f"WRITTEN order_id {order_id}"


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #

def _print_plan_summary(plans: list[InvoiceGroupPlan], skipped_already_queued: int, download_errors: list) -> None:
    clean = [p for p in plans if p.outcome == "CLEAN"]
    flagged = [p for p in plans if p.outcome == "FLAGGED"]
    existing = [p for p in plans if p.outcome == "ORDER_EXISTS"]
    print()
    print("-" * 70)
    print(
        f"  {len(plans)} order_number group(s) evaluated: "
        f"{len(clean)} clean (auto-write) | {len(flagged)} flagged (queue for review) | "
        f"{len(existing)} already have an order (link only)"
    )
    print(f"  Skipped (already queued from a prior run): {skipped_already_queued}")
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
    plans, skipped, errors = scan_and_group(drive_business, client)
    _print_plan_summary(plans, skipped, errors)
    print("\n  Run Mode 2 to execute this plan.")


def mode_run(drive_business, client) -> None:
    print("\n" + "=" * 70)
    print("  AGENT 01E — PDF -> ORDER BACKFILL — RUN")
    print("=" * 70)
    print()
    print("  Clean order groups get written straight to orders/shipments/line_items")
    print("  at order_status='pending_review' (cost basis never fires from this).")
    print("  Anything flagged lands in capture_queue for review via")
    print("  capture_queue_promotion.py, same as always.")
    print()
    if not get_yes_no("Proceed?", default="n"):
        print("  Cancelled.")
        return

    plans, skipped, errors = scan_and_group(drive_business, client)
    _print_plan_summary(plans, skipped, errors)

    if not get_yes_no("\nExecute this plan?", default="n"):
        print("  Cancelled. Nothing written.")
        return

    print()
    outcomes = {"WRITTEN": 0, "QUEUED": 0, "LINKED": 0}
    for i, plan in enumerate(plans, 1):
        try:
            result = apply_plan(plan, client)
        except Exception as e:
            print(f"  {i:>4}. ERROR applying {plan.order_number}: {e}")
            continue
        for k in outcomes:
            if result.startswith(k):
                outcomes[k] += 1
        label = plan.order_number if not plan.order_number.startswith("__unresolved__") else "(unparseable file)"
        print(f"  {i:>4}. {label}: {result}")

    print()
    print("-" * 70)
    print(
        f"  Done. {outcomes['WRITTEN']} order(s) written | "
        f"{outcomes['QUEUED']} queued for review | "
        f"{outcomes['LINKED']} linked to a pre-existing order"
    )
    print("  Run Mode 3 (Report) anytime to see current capture_queue status,")
    print("  or open capture_queue_promotion.py to review the flagged ones.")


def mode_report(client) -> None:
    print("\n" + "=" * 70)
    print("  AGENT 01E — CAPTURE QUEUE STATUS (this agent's rows)")
    print("=" * 70)
    result = (
        client.table("capture_queue")
        .select("status, order_number, reviewed_at")
        .eq("user_id", PHASE_1_USER_ID)
        .execute()
    )
    rows = [r for r in (result.data or []) if True]
    # Filter to this agent's rows client-side (raw_data->>source not queryable
    # via this simple select without a second round trip per row).
    detail = (
        client.table("capture_queue")
        .select("status, order_number")
        .eq("user_id", PHASE_1_USER_ID)
        .execute()
    )
    all_rows = detail.data or []
    print(f"\n  {len(all_rows)} total capture_queue row(s) for this account (all sources).")
    pending = [r for r in all_rows if r["status"] == "pending"]
    promoted = [r for r in all_rows if r["status"] == "promoted"]
    discarded = [r for r in all_rows if r["status"] == "discarded"]
    print(f"  pending: {len(pending)} | promoted: {len(promoted)} | discarded: {len(discarded)}")
    if pending:
        print("\n  Still pending review:")
        for r in pending[:40]:
            print(f"    {r.get('order_number') or '(no order number)'}")
        if len(pending) > 40:
            print(f"    ... and {len(pending) - 40} more.")
    print("\n  Open capture_queue_promotion.py to review pending rows.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("\n" + "=" * 70)
    print("  RESELLOS — AGENT 01E: HISTORICAL PDF -> ORDER BACKFILL")
    print("  LEGO only | reads business Drive _unmatched/ | safe to re-run")
    print("=" * 70)
    print()
    print("  1. Preview — scan + classify, no writes")
    print("  2. Run     — write clean orders, queue flagged ones for review")
    print("  3. Report  — current capture_queue status")
    print()

    mode = get_input("Select mode (1/2/3)").strip()
    if mode not in ("1", "2", "3"):
        print(f"  Unknown mode '{mode}'. Enter 1, 2, or 3.")
        return

    client = get_client()

    if mode == "3":
        mode_report(client)
        return

    print("\n  Connecting to business Drive...")
    try:
        _, drive_business = build_business_services()
        print("  Connected.")
    except SystemExit:
        raise
    except Exception as e:
        print(f"  ERROR connecting to business Drive: {e}")
        return

    if mode == "1":
        mode_preview(drive_business, client)
    else:
        mode_run(drive_business, client)


if __name__ == "__main__":
    main()
