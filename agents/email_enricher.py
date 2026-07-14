"""
ResellOS - Email Enricher
=========================
One configurable agent with per-retailer parser modules.

Architecture (designed 2026-06-26):
  - Per-retailer parsers registered in PARSER_REGISTRY
  - Shared A-007 matching cascade (Tier 1: order number; Tier 2: invoice number)
  - Shared review queue — all write plans shown before any DB write
  - Shared write path to Supabase

LEGO module (built 2026-07-05):
  Handles order confirmations, shipping confirmations, receipt envelopes,
  payment declined emails, and skips surveys. Covers both 2026 CRM domain
  (t.crm.lego.com) and historical senders (e.lego.com, billing03).

Modes:
  1 — Preview fixtures : parse local fixture files, show write plans (no DB, no Gmail)
  2 — Live run         : fetch emails from Gmail and process (GATED — ask before running)

CRITICAL: Do not invoke live Gmail processing without explicit user approval.
"""

import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional, Union

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_client import get_client, PHASE_1_USER_ID


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 2026 sender: t.crm.lego.com. Historical: e.lego.com, m.lego.com.
_LEGO_CRM_DOMAINS = ("t.crm.lego.com", "e.lego.com", "m.lego.com")
_LEGO_BILLING_SENDERS = ("no-reply-billing03@lego.com", "receipts@m.lego.com")

_FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "emails" / "lego"


# ---------------------------------------------------------------------------
# Data classes — parsed email types
# ---------------------------------------------------------------------------

@dataclass
class LineItemData:
    set_number: str
    name: str
    qty: int
    line_total: float
    unit_price: float    # always derived from line_total/qty — price column unreliable
    is_gwp: bool
    is_retiring: bool = True    # always True per CLAUDE.md rule 6
    status: Optional[str] = None


@dataclass
class LegoParsedOrderConfirmation:
    email_type: str = "order_confirmation"
    gmail_message_id: str = ""
    sender: str = ""
    order_number: str = ""
    order_date: Optional[date] = None
    subtotal: Optional[float] = None
    shipping: Optional[float] = None
    tax: Optional[float] = None
    order_total: Optional[float] = None
    line_items: list = field(default_factory=list)


@dataclass
class LegoParsedShippingConfirmation:
    email_type: str = "shipping_confirmation"
    gmail_message_id: str = ""
    sender: str = ""
    order_number: str = ""
    order_date: Optional[date] = None
    tracking_number: Optional[str] = None
    # Per spec: labeled "ORDER TOTAL" in email but these are per-SHIPMENT totals
    shipment_subtotal: Optional[float] = None
    shipment_tax: Optional[float] = None
    shipment_total: Optional[float] = None
    line_items: list = field(default_factory=list)


@dataclass
class LegoParsedPaymentDeclined:
    email_type: str = "payment_declined"
    gmail_message_id: str = ""
    sender: str = ""
    order_number: str = ""
    order_date: Optional[date] = None


@dataclass
class LegoParsedReceipt:
    email_type: str = "receipt"
    gmail_message_id: str = ""
    sender: str = ""
    invoice_number: str = ""
    purchase_date: Optional[date] = None


@dataclass
class SkippedEmail:
    email_type: str = "skipped"
    gmail_message_id: str = ""
    reason: str = ""


ParsedLegoEmail = Union[
    LegoParsedOrderConfirmation,
    LegoParsedShippingConfirmation,
    LegoParsedPaymentDeclined,
    LegoParsedReceipt,
    SkippedEmail,
]


# ---------------------------------------------------------------------------
# Write plan — result of A-007 cascade, shown before any DB write
# ---------------------------------------------------------------------------

@dataclass
class WritePlan:
    action: str
    gmail_message_id: str
    parsed: object
    matched_order_id: Optional[str] = None
    matched_order_number: Optional[str] = None
    notes: str = ""


# Action constants
ACT_ENRICH_ORDER    = "enrich_order"      # update existing order from email data
ACT_CREATE_SHIPMENT = "create_shipment"   # add shipment + tracking to existing order
ACT_CREATE_STUB     = "create_stub"       # create pending_review order from email
ACT_FLAG_DECLINED   = "flag_declined"     # flag existing order for payment declined
ACT_STUB_DECLINED   = "stub_declined"     # create stub with payment_declined note
ACT_RECEIPT_PDF     = "receipt_needs_pdf" # receipt envelope — forward to Agent 1A
ACT_SKIP            = "skip"              # survey, dedup, or unhandled


# ---------------------------------------------------------------------------
# LEGO PARSER MODULE — pure logic, no I/O
# ---------------------------------------------------------------------------

# Compiled regex patterns
_ORDER_NUM_RE    = re.compile(r'T(\d{9})')
_DATE_MDY_RE     = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})')
_TRACKING_RE     = re.compile(r'tracknum=([A-Z0-9]+)', re.IGNORECASE)
_INVOICE_BODY_RE = re.compile(r'invoice\s+(\d+)', re.IGNORECASE)
_INVOICE_SUBJ_RE = re.compile(r'Receipt\s+(\d+)', re.IGNORECASE)
_SET_LINE_RE     = re.compile(r'^\s*(\d{5})\s+(.+)')
_NUMERIC_RE      = re.compile(r'^\s*\$?\s*(\d+(?:\.\d+)?)\s*$')
_V_SUFFIX_RE     = re.compile(r'\s+V\d+\s*$')


def classify_lego_email(sender: str, subject: str, body: str) -> str:
    """
    Determine the LEGO email type from sender and subject.

    Returns one of:
      order_confirmation | shipping_confirmation | payment_declined |
      receipt | survey | unknown
    """
    sender_lower  = sender.lower()
    subject_lower = subject.lower()

    # Billing/receipt sender — invoice envelopes only
    if any(s in sender_lower for s in _LEGO_BILLING_SENDERS):
        return "receipt"

    # Remaining types all come from CRM domains
    if not any(d in sender_lower for d in _LEGO_CRM_DOMAINS):
        return "unknown"

    if "payment was unsuccessful" in subject_lower:
        return "payment_declined"
    if "thank you for your recent lego" in subject_lower:
        return "survey"
    if "on its way" in subject_lower:
        return "shipping_confirmation"
    if "order is confirmed" in subject_lower or "we've got it" in subject_lower:
        return "order_confirmation"

    return "unknown"


def _extract_order_number(text: str) -> Optional[str]:
    m = _ORDER_NUM_RE.search(text)
    return f"T{m.group(1)}" if m else None


def _extract_date_mdy(text_chunk: str) -> Optional[date]:
    """Parse the first M/D/YYYY or MM/DD/YYYY date found in the chunk."""
    m = _DATE_MDY_RE.search(text_chunk)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def _extract_totals(text: str) -> dict:
    """
    Extract financial totals from email body.

    Handles both compact (order confirmation: label then value on next line)
    and spread-out (shipping: label, blank line, then $value) formats.
    Looks for the first numeric value within 120 chars after each label.

    Note for shipping emails: the "ORDER TOTAL" label in the email is misleading —
    it is the shipment total. Callers must map it to the right field.
    """
    result = {}
    label_map = {
        "subtotal":    r"SUB\s*TOTAL\s*:",
        "shipping":    r"SHIPPING\s*:",   # must have colon — avoids "Shipping address:" false match
        "tax":         r"\bTAX\s*:",
        "order_total": r"ORDER\s*TOTAL\s*:",
    }
    for key, label_re in label_map.items():
        m = re.search(label_re, text, re.IGNORECASE)
        if not m:
            continue
        after   = text[m.end(): m.end() + 120]
        num_m   = re.search(r'\$?\s*([\d]+(?:\.[\d]+)?)', after)
        if num_m:
            result[key] = float(num_m.group(1))
    return result


def _extract_line_items(text: str) -> list:
    """
    Extract line items from an order or shipping confirmation email body.

    Handles:
    - Compact format (order confirmations): values follow the set line with no blanks
    - Spread-out format (shipping confirmations): blank lines between each value

    Per spec:
    - unit_price = line_total / qty  (price column is unreliable — showed $0.00 on paid items)
    - GWP detection: line_total == 0 and qty >= 1
    - V{nn} suffix stripped from names (e.g., "Recycling Truck V39" → "Recycling Truck")
    - Truncation markers (..) stripped (name was truncated in the email template)
    - is_retiring = True always (CLAUDE.md rule 6)
    """
    lines = text.splitlines()

    # Find all set-number lines (5-digit number at start, possibly with leading whitespace)
    set_positions = []
    for i, line in enumerate(lines):
        m = _SET_LINE_RE.match(line)
        if m:
            set_positions.append((i, m.group(1), m.group(2).strip()))

    items = []
    for idx, (pos, set_num, raw_name) in enumerate(set_positions):
        # Strip V{nn} suffix, then trailing truncation markers and whitespace
        name = _V_SUFFIX_RE.sub("", raw_name).rstrip(". ").strip()

        # Collect lines between this set line and the next (or end of text)
        end_pos = set_positions[idx + 1][0] if idx + 1 < len(set_positions) else len(lines)

        numerics = []
        for line in lines[pos + 1: end_pos]:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("status"):
                break
            m_num = _NUMERIC_RE.match(stripped)
            if m_num:
                numerics.append(float(m_num.group(1)))

        if len(numerics) < 3:
            continue  # malformed — skip rather than guess

        # Values arrive in order: price (unreliable) / qty / line_total
        _, qty_val, line_total = numerics[0], numerics[1], numerics[2]
        qty = max(1, int(qty_val))

        unit_price = round(line_total / qty, 2) if qty > 0 and line_total != 0 else 0.0
        is_gwp     = line_total == 0.0 and qty >= 1

        items.append(LineItemData(
            set_number=set_num,
            name=name,
            qty=qty,
            line_total=line_total,
            unit_price=unit_price,
            is_gwp=is_gwp,
            is_retiring=True,
        ))

    return items


def _extract_tracking(text: str) -> Optional[str]:
    """Extract UPS tracking number. Prefers URL param; falls back to bare 1Z pattern."""
    m = _TRACKING_RE.search(text)
    if m:
        return m.group(1).upper()
    m = re.search(r'\b(1Z[A-Z0-9]{16})\b', text, re.IGNORECASE)
    return m.group(1).upper() if m else None


# ---- Per-type parsers ----

def parse_lego_order_confirmation(
    gmail_message_id: str, sender: str, body: str
) -> LegoParsedOrderConfirmation:
    result = LegoParsedOrderConfirmation(
        gmail_message_id=gmail_message_id,
        sender=sender,
    )
    result.order_number = _extract_order_number(body) or ""

    date_m = re.search(r'Order\s+date\s*:?\s*([\d/]+)', body, re.IGNORECASE)
    if date_m:
        result.order_date = _extract_date_mdy(date_m.group(1))

    totals = _extract_totals(body)
    result.subtotal     = totals.get("subtotal")
    result.shipping     = totals.get("shipping")
    result.tax          = totals.get("tax")
    result.order_total  = totals.get("order_total")
    result.line_items   = _extract_line_items(body)
    return result


def parse_lego_shipping_confirmation(
    gmail_message_id: str, sender: str, subject: str, body: str
) -> LegoParsedShippingConfirmation:
    result = LegoParsedShippingConfirmation(
        gmail_message_id=gmail_message_id,
        sender=sender,
    )
    # Order number: body is authoritative; fall back to subject
    result.order_number = _extract_order_number(body) or _extract_order_number(subject) or ""

    date_m = re.search(r'Order\s+date\s*:?\s*([\d/]+)', body, re.IGNORECASE)
    if date_m:
        result.order_date = _extract_date_mdy(date_m.group(1))

    result.tracking_number = _extract_tracking(body)

    # These are shipment-level totals — the email mislabels them "ORDER TOTAL"
    totals = _extract_totals(body)
    result.shipment_subtotal = totals.get("subtotal")
    result.shipment_tax      = totals.get("tax")
    result.shipment_total    = totals.get("order_total")

    result.line_items = _extract_line_items(body)
    return result


def parse_lego_payment_declined(
    gmail_message_id: str, sender: str, body: str
) -> LegoParsedPaymentDeclined:
    result = LegoParsedPaymentDeclined(
        gmail_message_id=gmail_message_id,
        sender=sender,
    )
    result.order_number = _extract_order_number(body) or ""

    date_m = re.search(r'placed\s+on\s+([\d/]+)', body, re.IGNORECASE)
    if date_m:
        result.order_date = _extract_date_mdy(date_m.group(1))

    return result


def parse_lego_receipt(
    gmail_message_id: str, sender: str, subject: str, body: str
) -> LegoParsedReceipt:
    result = LegoParsedReceipt(
        gmail_message_id=gmail_message_id,
        sender=sender,
    )
    m = _INVOICE_BODY_RE.search(body)
    if not m:
        m = _INVOICE_SUBJ_RE.search(subject)
    result.invoice_number = m.group(1) if m else ""

    date_m = re.search(r'purchase\s+([\d/]+)', body, re.IGNORECASE)
    if date_m:
        result.purchase_date = _extract_date_mdy(date_m.group(1))

    return result


def parse_lego_email(
    gmail_message_id: str, sender: str, subject: str, body: str
) -> ParsedLegoEmail:
    """Classify and dispatch to the correct LEGO parser. Returns a typed parsed result."""
    email_type = classify_lego_email(sender, subject, body)

    if email_type == "order_confirmation":
        return parse_lego_order_confirmation(gmail_message_id, sender, body)
    if email_type == "shipping_confirmation":
        return parse_lego_shipping_confirmation(gmail_message_id, sender, subject, body)
    if email_type == "payment_declined":
        return parse_lego_payment_declined(gmail_message_id, sender, body)
    if email_type == "receipt":
        return parse_lego_receipt(gmail_message_id, sender, subject, body)
    if email_type == "survey":
        return SkippedEmail(gmail_message_id=gmail_message_id, reason="survey — skip per spec")

    return SkippedEmail(
        gmail_message_id=gmail_message_id,
        reason=f"unknown email type (sender={sender!r}, subject={subject!r})",
    )


# ---------------------------------------------------------------------------
# Retailer parser registry — add new retailers here (one entry per retailer)
# ---------------------------------------------------------------------------

PARSER_REGISTRY = {
    "lego": parse_lego_email,
}


# ---------------------------------------------------------------------------
# A-007 matching cascade — pure logic, no DB I/O
# ---------------------------------------------------------------------------

def plan_enrichment(
    parsed: ParsedLegoEmail,
    existing_order: Optional[dict],
) -> WritePlan:
    """
    Apply the A-007 cascade and return a write plan.

    existing_order: the DB order row from a Tier 1 lookup, or None if no match.
    The caller performs the lookup (lookup_order_by_number) before calling here.

    Cascade:
      Tier 1 — order number → deterministic → enrich existing order or create shipment.
      No Tier 1 match → create pending_review stub (never silently drop).

    Rules:
      - Totals are NEVER a matching criterion. Two different orders can share
        identical totals ($169.33 confirmed on T508056398 and T508221251).
      - Payment declined → flag for review; never auto-cancel.
      - Receipt envelopes have no order number → forward to Agent 1A.
      - Surveys → skip.
    """
    msg_id = parsed.gmail_message_id

    if isinstance(parsed, SkippedEmail):
        return WritePlan(action=ACT_SKIP, gmail_message_id=msg_id, parsed=parsed,
                         notes=parsed.reason)

    if isinstance(parsed, LegoParsedReceipt):
        return WritePlan(action=ACT_RECEIPT_PDF, gmail_message_id=msg_id, parsed=parsed,
                         notes="no order number in receipt body — Agent 1A handles PDF parse")

    if isinstance(parsed, LegoParsedOrderConfirmation):
        if existing_order:
            return WritePlan(
                action=ACT_ENRICH_ORDER,
                gmail_message_id=msg_id,
                parsed=parsed,
                matched_order_id=existing_order["order_id"],
                matched_order_number=existing_order["order_number"],
                notes="enrich order metadata from confirmation email",
            )
        return WritePlan(
            action=ACT_CREATE_STUB,
            gmail_message_id=msg_id,
            parsed=parsed,
            notes=f"no existing order for {parsed.order_number} — create pending_review stub",
        )

    if isinstance(parsed, LegoParsedShippingConfirmation):
        if existing_order:
            return WritePlan(
                action=ACT_CREATE_SHIPMENT,
                gmail_message_id=msg_id,
                parsed=parsed,
                matched_order_id=existing_order["order_id"],
                matched_order_number=existing_order["order_number"],
                notes=f"create shipment with tracking {parsed.tracking_number}",
            )
        return WritePlan(
            action=ACT_CREATE_STUB,
            gmail_message_id=msg_id,
            parsed=parsed,
            notes=f"no existing order for {parsed.order_number} — create stub + shipment",
        )

    if isinstance(parsed, LegoParsedPaymentDeclined):
        if existing_order:
            return WritePlan(
                action=ACT_FLAG_DECLINED,
                gmail_message_id=msg_id,
                parsed=parsed,
                matched_order_id=existing_order["order_id"],
                matched_order_number=existing_order["order_number"],
                notes="flag order pending_review — payment declined; never auto-cancel",
            )
        return WritePlan(
            action=ACT_STUB_DECLINED,
            gmail_message_id=msg_id,
            parsed=parsed,
            notes=f"no existing order for {parsed.order_number} — orphan stub with payment_declined flag",
        )

    return WritePlan(action=ACT_SKIP, gmail_message_id=msg_id, parsed=parsed,
                     notes="unhandled parsed type")


def lookup_order_by_number(client, user_id: str, order_number: str) -> Optional[dict]:
    """Tier 1 DB lookup — order number is the only valid matching key."""
    result = (
        client.table("orders")
        .select("order_id, order_number, order_date, order_status, cost_basis_state")
        .eq("user_id", user_id)
        .eq("order_number", order_number)
        .execute()
    )
    return result.data[0] if result.data else None


# ---------------------------------------------------------------------------
# Review queue display
# ---------------------------------------------------------------------------

def show_review_queue(plans: list) -> None:
    print("\n" + "=" * 70)
    print("  EMAIL ENRICHER — WRITE PLAN REVIEW")
    print("=" * 70)
    for i, plan in enumerate(plans, 1):
        p = plan.parsed
        print(f"\n[{i}]  action={plan.action}  msg_id={plan.gmail_message_id}")
        print(f"     type={p.email_type}")
        if hasattr(p, "order_number") and p.order_number:
            print(f"     order_number={p.order_number}")
        if hasattr(p, "tracking_number") and p.tracking_number:
            print(f"     tracking={p.tracking_number}")
        if hasattr(p, "invoice_number") and p.invoice_number:
            print(f"     invoice_number={p.invoice_number}")
        if hasattr(p, "order_date") and p.order_date:
            print(f"     order_date={p.order_date}")
        if hasattr(p, "order_total") and p.order_total is not None:
            print(f"     order_total=${p.order_total:.2f}")
        if hasattr(p, "shipment_total") and p.shipment_total is not None:
            print(f"     shipment_total=${p.shipment_total:.2f}")
        if hasattr(p, "line_items") and p.line_items:
            print(f"     line_items ({len(p.line_items)}):")
            for item in p.line_items:
                gwp = " [GWP]" if item.is_gwp else ""
                print(
                    f"       {item.set_number}  {item.name[:28]:<28}"
                    f"  x{item.qty}  ${item.line_total:.2f}{gwp}"
                )
        if plan.matched_order_id:
            print(f"     matched_order_id={plan.matched_order_id}")
        print(f"     notes: {plan.notes}")
    print("\n" + "=" * 70)
    print(f"  Total: {len(plans)} email(s) to process")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Write path — Supabase I/O, GATED
# Never call execute_write_plan without showing the review queue first.
# ---------------------------------------------------------------------------

def _build_stub_order_row(parsed: ParsedLegoEmail) -> dict:
    """
    Build an orders table row for a stub (pending_review) order.
    Never fills: buy_reason, purchase_trigger, cashback_rate, gift_card_last4.
    """
    row: dict = {
        "retailer":               "lego",
        "entry_method":           "email_enricher",
        "order_status":           "pending_review",
        "cost_basis_state":       "estimated",
        "reconciliation_status":  "pending",
        "invoice_expected":       True,
    }
    if hasattr(parsed, "order_number"):
        row["order_number"] = parsed.order_number
    if hasattr(parsed, "order_date") and parsed.order_date:
        row["order_date"] = parsed.order_date.isoformat()

    if isinstance(parsed, LegoParsedOrderConfirmation):
        if parsed.subtotal    is not None: row["subtotal"]        = parsed.subtotal
        if parsed.tax         is not None: row["tax_paid"]        = parsed.tax
        if parsed.shipping    is not None: row["shipping"]        = parsed.shipping
        if parsed.order_total is not None:
            row["total"]          = parsed.order_total
            row["expected_total"] = parsed.order_total
        if parsed.line_items:
            row["expected_item_count"] = sum(i.qty for i in parsed.line_items)

    return row


def _build_shipment_row(
    order_id: str, user_id: str, parsed: LegoParsedShippingConfirmation
) -> dict:
    row: dict = {
        "order_id":        order_id,
        "user_id":         user_id,
        "entry_method":    "email_enricher",
        "shipment_status": "shipped",
        "no_invoice_received": True,
    }
    if parsed.tracking_number:
        # tracking_number column requires migration 015 if not already present
        row["tracking_number"] = parsed.tracking_number
    if parsed.shipment_subtotal is not None:
        row["subtotal"]    = parsed.shipment_subtotal
    if parsed.shipment_tax is not None:
        row["tax_amount"]  = parsed.shipment_tax
    return row


def _build_line_item_rows(
    order_id: str, shipment_id: str, user_id: str, items: list
) -> list:
    rows = []
    for item in items:
        rows.append({
            "user_id":        user_id,
            "order_id":       order_id,
            "shipment_id":    shipment_id,
            "set_number":     item.set_number,
            "set_name":       item.name,
            "article_number": item.set_number,  # LEGO set_number == article_number
            "quantity":       item.qty,
            "unit_price":     item.unit_price,
            "line_total":     item.line_total,
            "is_gwp":         item.is_gwp,
            # is_retiring defaults True in DB; not writing it explicitly avoids
            # a potential column-not-found error on older schema versions
        })
    return rows


def _tracking_shipment_exists(client, order_id: str, tracking: str) -> bool:
    """Dedup guard: True if a shipment with this tracking number already exists."""
    try:
        result = (
            client.table("shipments")
            .select("shipment_id")
            .eq("order_id", order_id)
            .eq("tracking_number", tracking)
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False  # column may not exist yet — treat as not-existing


def execute_write_plan(plan: WritePlan, client, user_id: str) -> bool:
    """
    Execute one write plan against Supabase.
    GATED — only called after the user has reviewed the plan queue.
    Returns True on success or idempotent skip.
    """
    p = plan.parsed

    if plan.action == ACT_SKIP:
        print(f"  SKIP: {plan.notes}")
        return True

    if plan.action == ACT_RECEIPT_PDF:
        print(f"  RECEIPT: invoice {getattr(p, 'invoice_number', '?')} — forward to Agent 1A")
        return True

    if plan.action == ACT_ENRICH_ORDER:
        updates: dict = {}
        if isinstance(p, LegoParsedOrderConfirmation) and p.order_date:
            updates["order_date"] = p.order_date.isoformat()
        if updates:
            client.table("orders").update(updates).eq(
                "order_id", plan.matched_order_id
            ).execute()
        print(f"  OK: order {plan.matched_order_number} enriched from confirmation")
        return True

    if plan.action == ACT_CREATE_SHIPMENT:
        if not isinstance(p, LegoParsedShippingConfirmation):
            return False
        if p.tracking_number and _tracking_shipment_exists(
            client, plan.matched_order_id, p.tracking_number
        ):
            print(f"  SKIP DEDUP: tracking {p.tracking_number} already recorded")
            return True
        row = _build_shipment_row(plan.matched_order_id, user_id, p)
        result = client.table("shipments").insert(row).execute()
        if not result.data:
            print(f"  FAIL: could not create shipment for {plan.matched_order_number}")
            return False
        print(f"  OK: shipment created — tracking {p.tracking_number}")
        return True

    if plan.action in (ACT_CREATE_STUB, ACT_STUB_DECLINED):
        order_number = getattr(p, "order_number", "")
        if order_number:
            existing = (
                client.table("orders")
                .select("order_id")
                .eq("user_id", user_id)
                .eq("order_number", order_number)
                .execute()
            )
            if existing.data:
                print(f"  SKIP DEDUP: stub for {order_number} already exists")
                return True

        stub = _build_stub_order_row(p)
        stub["user_id"] = user_id
        if plan.action == ACT_STUB_DECLINED:
            stub["notes"] = "payment_declined — created by email enricher; review before settling"

        order_result = client.table("orders").insert(stub).execute()
        if not order_result.data:
            print(f"  FAIL: could not create stub order for {order_number}")
            return False
        order_id = order_result.data[0]["order_id"]

        # Pending shipment row for the stub
        ship_row: dict = {
            "user_id":             user_id,
            "order_id":            order_id,
            "shipment_status":     "pending",
            "entry_method":        "email_enricher",
            "no_invoice_received": True,
        }
        if isinstance(p, LegoParsedShippingConfirmation) and p.tracking_number:
            ship_row["shipment_status"] = "shipped"
            ship_row["tracking_number"] = p.tracking_number
            if p.shipment_subtotal is not None:
                ship_row["subtotal"]   = p.shipment_subtotal
            if p.shipment_tax is not None:
                ship_row["tax_amount"] = p.shipment_tax

        ship_result = client.table("shipments").insert(ship_row).execute()
        if not ship_result.data:
            print(f"  FAIL: could not create shipment for stub {order_number}")
            return False
        shipment_id = ship_result.data[0]["shipment_id"]

        if hasattr(p, "line_items") and p.line_items:
            rows = _build_line_item_rows(order_id, shipment_id, user_id, p.line_items)
            li_result = client.table("line_items").insert(rows).execute()
            if not li_result.data:
                print(f"  FAIL: line_items insert failed for stub {order_number} — order+shipment rows exist, need manual fix")
                return False

        label = "payment_declined stub" if plan.action == ACT_STUB_DECLINED else "pending_review stub"
        print(f"  OK: {label} created for {order_number or 'unknown'}")
        return True

    if plan.action == ACT_FLAG_DECLINED:
        result = client.table("orders").update(
            {"order_status": "pending_review", "notes": "payment_declined — flagged by email enricher; do not auto-cancel"}
        ).eq("order_id", plan.matched_order_id).execute()
        if not result.data:
            print(f"  FAIL: could not flag {plan.matched_order_number} — check order_id and RLS")
            return False
        print(f"  OK: {plan.matched_order_number} flagged pending_review (payment declined)")
        return True

    print(f"  WARN: unhandled action {plan.action!r}")
    return False


# ---------------------------------------------------------------------------
# Gmail I/O layer — wired, GATED
# Do not call without explicit user approval.
# ---------------------------------------------------------------------------

def fetch_lego_emails_from_gmail(gmail_service, max_results: int = 100) -> list:
    """
    Search Gmail for unprocessed LEGO emails covering both 2026 (t.crm.lego.com)
    and historical (e.lego.com, billing03) senders. Skips survey emails and
    anything already labeled ResellOS-Enriched.

    IMPORTANT: Ask the user before calling this. Live runs are deferred.
    Use Mode 1 (fixture preview) for safe testing.
    """
    query = (
        "(from:t.crm.lego.com OR from:no-reply-billing03@lego.com OR from:e.lego.com)"
        ' -subject:"Thank you for your recent LEGO"'
        " -label:ResellOS-Enriched"
    )
    response = gmail_service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()
    return response.get("messages", [])


# ---------------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------------

def load_fixture_file(path: Path) -> tuple:
    """
    Load a fixture file and return (gmail_message_id, sender, subject, body).

    Fixture files have a comment header with metadata keys, then a blank line,
    then the email body. The gmail_message_id line may have a trailing date
    annotation; subject lines may have inline <-- notes — both are stripped.
    """
    text  = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    metadata: dict = {}
    header_end = 0

    for i, line in enumerate(lines):
        if line.startswith("# "):
            content = line[2:].strip()
            for key in ("sender", "subject", "gmail_message_id"):
                prefix = f"{key}: "
                if content.lower().startswith(prefix):
                    value = content[len(prefix):].strip()
                    if "<--" in value:
                        value = value[: value.index("<--")].strip()
                    if key == "gmail_message_id":
                        value = value.split()[0]
                    metadata[key] = value
                    break
            header_end = i + 1
        elif not line.strip():
            header_end = i + 1
        else:
            break

    body = "\n".join(lines[header_end:])
    return (
        metadata.get("gmail_message_id", path.stem),
        metadata.get("sender", ""),
        metadata.get("subject", ""),
        body,
    )


# ---------------------------------------------------------------------------
# Mode 1: parse fixtures, show review queue (safe — no DB, no Gmail)
# ---------------------------------------------------------------------------

def _preview_fixtures() -> None:
    fixture_files = sorted(_FIXTURES_DIR.glob("*.txt"))
    if not fixture_files:
        print(f"No fixtures found in {_FIXTURES_DIR}")
        return

    plans = []
    for fpath in fixture_files:
        msg_id, sender, subject, body = load_fixture_file(fpath)
        parsed = parse_lego_email(msg_id, sender, subject, body)
        # Mode 1: no DB lookup — all unmatched (shows stub plans for review)
        plan = plan_enrichment(parsed, existing_order=None)
        plans.append(plan)
        print(f"  parsed: {fpath.name}  →  type={parsed.email_type}")

    show_review_queue(plans)
    print(
        "\nMode 1 complete (fixtures only, no DB writes)."
        "\nLive Gmail processing requires explicit approval — use Mode 2."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("ResellOS — Email Enricher")
    print("=" * 40)
    print("Modes:")
    print("  1  Preview fixtures (no DB, no Gmail)")
    print("  2  Live run (GATED — ask Joshua first)")
    mode = input("\nSelect mode: ").strip()

    if mode == "1":
        print(f"\nParsing fixtures from: {_FIXTURES_DIR}\n")
        _preview_fixtures()

    elif mode == "2":
        print(
            "\nLive Gmail processing is GATED."
            "\nThis mode has NOT been reviewed end-to-end yet."
            "\nRun Mode 1 first and confirm parsed output is correct."
            "\nThen ask Joshua before proceeding."
        )
        confirmed = input("\nHas Joshua explicitly approved this run? (yes/no): ").strip().lower()
        if confirmed != "yes":
            print("Cancelled. Run Mode 1 to review fixture parsing first.")
            return
        print("[Live processing not yet activated — fixture testing only for this session]")

    else:
        print(f"Unknown mode {mode!r}.")


if __name__ == "__main__":
    main()
