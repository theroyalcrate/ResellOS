"""
ResellOS - Agent 01B: Invoice Filing
=====================================
Downloads invoice PDFs from Gmail (label: ResellOS-Invoices), renames them
to the project naming convention, files them into the business Drive folder
structure, and records each filing in the invoice_files ledger.

Mode 1 — Preview  : scan ResellOS-Invoices, show proposed filename + folder
                    for each pending message. No writes.
Mode 2 — File one : pick one pending invoice from the preview list and file it.
                    Asks for confirmation before every write.
Mode 3 — Ledger   : show the invoice_files table (what has already been filed).

Naming convention (§3):
  {order_number}_{RETAILER}_{YYYY-MM-DD}.pdf
  {order_number}_{RETAILER}_{YYYY-MM-DD}_ship2.pdf   ← split shipments
  _unmatched/{gmail_message_id}_{RETAILER}_{YYYY-MM-DD}.pdf

Walmart routing rule (§7.5):
  businessinfo@walmart.com → Walmart Business/
  help@walmart.com         → Walmart/

Idempotency (§5): gmail_message_id checked against invoice_files before any
write. Belt-and-suspenders against a label transition that failed silently.

Auth: credentials/token.json — run setup_oauth.py once to generate it.

Usage: python agents/agent_01b_invoice_filing.py
"""

import base64
import io
import re
import sys
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# db_client lives at project root, one level up from agents/
sys.path.insert(0, str(Path(__file__).parent.parent))
from db_client import get_client, PHASE_1_USER_ID


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

_CREDS_DIR = Path(__file__).parent.parent / "credentials"
TOKEN_PATH = _CREDS_DIR / "token.json"

GMAIL_INTAKE_LABEL_ID = "Label_2573281147792874926"  # ResellOS-Invoices
GMAIL_FILED_LABEL_ID  = "Label_1"                    # ResellOS-Filed
DRIVE_ROOT_FOLDER     = "Invoices"

# Normalized orders.retailer → Drive subfolder name
RETAILER_DRIVE_FOLDER: dict[str, str] = {
    "LEGO":             "Lego",
    "BARNES":           "Barnes and Noble",
    "KOHLS":            "Kohls",
    "MACYS":            "Macy's",
    "TARGET":           "Target",
    "BESTBUY":          "Best Buy",
    "FRED MEYER":       "Fred Meyer",
    "WALGREENS":        "Walgreens",
    "DISNEY":           "Disney Store",
    "AMAZON":           "Amazon personal",
    "AMAZON BUSINESS":  "Amazon Business",
    "WALMART":          "Walmart",
    "WALMART BUSINESS": "Walmart Business",
}

# Ordered list of (sender-fragment, retailer-key) for unmatched-path routing.
# Checked with `fragment in sender_email` so more-specific entries come first.
_SENDER_RETAILER: list[tuple[str, str]] = [
    ("businessinfo@walmart.com", "WALMART BUSINESS"),
    ("help@walmart.com",         "WALMART"),
    ("e.lego.com",               "LEGO"),
    ("kohls.com",                "KOHLS"),
    ("macys.com",                "MACYS"),
    ("target.com",               "TARGET"),
    ("bestbuy.com",              "BESTBUY"),
    ("barnesandnoble.com",       "BARNES"),
    ("amazon.com",               "AMAZON"),
    ("fredmeyer.com",            "FRED MEYER"),
    ("walgreens.com",            "WALGREENS"),
]


# --------------------------------------------------------------------------- #
# Pure logic — no I/O, testable in isolation
# --------------------------------------------------------------------------- #

def build_filename(
    order_number: str,
    retailer_key: str,
    date_str: str,
    shipment_num: int = 1,
) -> str:
    """
    Standard invoice filename per §3.
    _ship{N} suffix only when N > 1 (split shipments per A-007).
    """
    tag  = retailer_key.upper().replace(" ", "_")
    base = f"{order_number}_{tag}_{date_str}"
    if shipment_num > 1:
        base += f"_ship{shipment_num}"
    return base + ".pdf"


def build_unmatched_filename(
    gmail_message_id: str,
    retailer_key: str,
    date_str: str,
) -> str:
    """Unmatched fallback filename per §3: {gmail_message_id}_{RETAILER}_{date}.pdf"""
    tag = retailer_key.upper().replace(" ", "_")
    return f"{gmail_message_id}_{tag}_{date_str}.pdf"


def resolve_retailer_folder(order_retailer: str, sender_email: str) -> str:
    """
    Map order.retailer + sender email → Drive subfolder name.
    Sender email is the authoritative discriminator for Walmart vs
    Walmart Business (§7.5) because both could share retailer key 'WALMART'.
    """
    se = (sender_email or "").lower()
    ru = (order_retailer or "").upper().strip()

    if "businessinfo@walmart.com" in se:
        return "Walmart Business"
    if "walmart" in ru or "walmart" in se:
        return "Walmart"

    return RETAILER_DRIVE_FOLDER.get(ru, ru.title())


def resolve_drive_folder_path(retailer_folder: str, order_date_str: str) -> list[str]:
    """
    Build Drive path segments for a matched invoice.
    Returns e.g. ['Invoices', 'Kohls', '2026', 'June 2026'].
    """
    d = date.fromisoformat(order_date_str)
    return [DRIVE_ROOT_FOLDER, retailer_folder, str(d.year), d.strftime("%B %Y")]


def resolve_unmatched_folder_path(retailer_folder: str) -> list[str]:
    """Unmatched invoices go to Invoices/{retailer}/_unmatched/."""
    return [DRIVE_ROOT_FOLDER, retailer_folder, "_unmatched"]


def extract_order_number_from_subject(subject: str) -> Optional[str]:
    """
    Extract an order number from an email subject line.
    Covers LEGO (T-prefixed alphanumeric), Kohl's (long numeric),
    and generic "Order #XXXXX" / hash-prefixed patterns.
    Returns None when no confident match is found.
    """
    if not subject:
        return None
    patterns = [
        # Hash-prefixed comes first so "Order Confirmation #WB-001" doesn't misfire on "Confirmation"
        r"#([A-Z0-9][A-Z0-9\-]{6,19})\b",
        # Pure-numeric order numbers, optionally preceded by "Confirmation" filler word
        r"Order[\s:#]*(?:Confirmation\s+)?([0-9]{7,20})\b",
        # Letter-prefixed alphanumeric (LEGO T-numbers): letter then all digits
        r"Order[\s:#]*([A-Z][0-9]{6,19})\b",
        # Invoice-style subjects where the number trails the order label
        r"Invoice[^0-9]*([0-9]{8,20})\b",
    ]
    for pat in patterns:
        m = re.search(pat, subject, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) >= 7:
                return candidate
    return None


def extract_sender_email(from_header: str) -> str:
    """Extract bare email address from 'Display Name <email>' header."""
    m = re.search(r"<([^>]+)>", from_header or "")
    if m:
        return m.group(1).lower().strip()
    return (from_header or "").lower().strip()


def detect_retailer_from_sender(sender_email: str) -> str:
    """Map sender email to a retailer key. Used for unmatched-path routing."""
    se = sender_email.lower()
    for fragment, retailer in _SENDER_RETAILER:
        if fragment in se:
            return retailer
    return "UNKNOWN"


def extract_email_date(date_header: str) -> str:
    """
    Parse RFC 2822 email Date header to YYYY-MM-DD.
    Falls back to today so filenames are never empty.
    """
    try:
        return parsedate_to_datetime(date_header).strftime("%Y-%m-%d")
    except Exception:
        return date.today().isoformat()


# --------------------------------------------------------------------------- #
# Input helpers
# --------------------------------------------------------------------------- #

def get_input(prompt, required=True, default=None):
    display = f"{prompt} [{default}]: " if default is not None else f"{prompt}: "
    while True:
        value = input(display).strip()
        if value:
            return value
        if default is not None:
            return str(default)
        if not required:
            return None
        print("  This field is required.")


def get_yes_no(prompt, default="n"):
    while True:
        raw = get_input(f"{prompt} (y/n)", default=default).lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


# --------------------------------------------------------------------------- #
# OAuth / service setup
# --------------------------------------------------------------------------- #

def _load_creds() -> Credentials:
    if not TOKEN_PATH.exists():
        print(f"  ERROR: {TOKEN_PATH} not found. Run setup_oauth.py first.")
        sys.exit(1)
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def build_services():
    """Return (gmail_service, drive_service). Refreshes token if expired."""
    creds = _load_creds()
    gmail = build("gmail", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return gmail, drive


# --------------------------------------------------------------------------- #
# Gmail I/O
# --------------------------------------------------------------------------- #

def list_intake_messages(gmail) -> list[dict]:
    messages: list[dict] = []
    page_token = None
    while True:
        kwargs: dict = {
            "userId":   "me",
            "labelIds": [GMAIL_INTAKE_LABEL_ID],
            "maxResults": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = gmail.users().messages().list(**kwargs).execute()
        messages.extend(result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return messages


def fetch_message(gmail, msg_id: str) -> dict:
    return (
        gmail.users().messages().get(userId="me", id=msg_id, format="full").execute()
    )


def parse_message_meta(msg: dict) -> dict:
    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }
    return {
        "id":      msg["id"],
        "subject": headers.get("subject", ""),
        "from":    headers.get("from", ""),
        "date":    headers.get("date", ""),
        "payload": msg.get("payload", {}),
    }


def extract_pdf_attachments(gmail, msg_id: str, payload: dict) -> list[dict]:
    """
    Walk the MIME tree recursively and collect every PDF part.
    Handles both inline base64 data and external attachmentId references.
    Returns list of {'filename': str, 'data': bytes}.
    """
    pdfs: list[dict] = []

    def _walk(part):
        if (part.get("filename") or "").lower().endswith(".pdf"):
            body   = part.get("body", {})
            att_id = body.get("attachmentId")
            if att_id:
                att      = gmail.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=att_id
                ).execute()
                data_b64 = att.get("data", "")
            else:
                data_b64 = body.get("data", "")
            if data_b64:
                pdfs.append({
                    "filename": part["filename"],
                    "data":     base64.urlsafe_b64decode(data_b64),
                })
        for sub in part.get("parts", []):
            _walk(sub)

    _walk(payload)
    return pdfs


def transition_label(gmail, msg_id: str) -> None:
    """Remove ResellOS-Invoices, add ResellOS-Filed (the two-stage move per §6)."""
    gmail.users().messages().modify(
        userId="me",
        id=msg_id,
        body={
            "removeLabelIds": [GMAIL_INTAKE_LABEL_ID],
            "addLabelIds":    [GMAIL_FILED_LABEL_ID],
        },
    ).execute()


# --------------------------------------------------------------------------- #
# Drive I/O
# --------------------------------------------------------------------------- #

def _find_folder(drive, name: str, parent_id: str) -> Optional[str]:
    """
    Return the ID of the first folder matching name under parent_id.
    The name filter in the query is server-side — avoids pagination misses
    when a parent folder has many children. Client-side strip comparison is
    kept as a safety net for the trailing-space folder names (§2).
    """
    name_q = name.strip().replace("'", "\\'")
    q = (
        f"mimeType='application/vnd.google-apps.folder'"
        f" and '{parent_id}' in parents"
        f" and name = '{name_q}'"
        f" and trashed=false"
    )
    result = (
        drive.files()
        .list(q=q, fields="files(id, name)", spaces="drive")
        .execute()
    )
    target = name.strip().lower()
    for f in result.get("files", []):
        if f["name"].strip().lower() == target:
            return f["id"]
    return None


def _create_folder(drive, name: str, parent_id: str) -> str:
    meta = {
        "name":     name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents":  [parent_id],
    }
    return drive.files().create(body=meta, fields="id").execute()["id"]


def resolve_folder_id(drive, path_segments: list[str]) -> str:
    """
    Walk path_segments from Drive root, creating any missing folder along the way.
    Returns the ID of the deepest folder.
    """
    parent = "root"
    for seg in path_segments:
        found  = _find_folder(drive, seg, parent)
        parent = found if found else _create_folder(drive, seg, parent)
    return parent


def upload_pdf(drive, pdf_bytes: bytes, filename: str, folder_id: str) -> str:
    """Upload PDF bytes to a Drive folder. Returns the new Drive file ID."""
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
    meta  = {"name": filename, "parents": [folder_id]}
    return (
        drive.files().create(body=meta, media_body=media, fields="id").execute()["id"]
    )


# --------------------------------------------------------------------------- #
# Supabase — A-007 order matching (Tier 1: order number)
# --------------------------------------------------------------------------- #

def match_order(order_number: str, client) -> Optional[dict]:
    """
    A-007 Tier 1: deterministic match on order_number.
    Returns the order row (order_id, order_number, retailer, order_date) or None.
    Tier 2 (article numbers from PDF content) is deferred to a future version.
    """
    if not order_number:
        return None
    result = (
        client.table("orders")
        .select("order_id, order_number, retailer, order_date")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .execute()
    )
    return result.data[0] if result.data else None


def count_shipments(order_id: str, client) -> int:
    """Return the number of shipment rows for an order (split-shipment detection)."""
    result = (
        client.table("shipments")
        .select("shipment_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_id", order_id)
        .execute()
    )
    return len(result.data or [])


# --------------------------------------------------------------------------- #
# Supabase — invoice_files ledger
# --------------------------------------------------------------------------- #

def already_filed(gmail_message_id: str, client) -> bool:
    """Belt-and-suspenders idempotency check — never process the same message twice."""
    result = (
        client.table("invoice_files")
        .select("id")
        .eq("gmail_message_id", gmail_message_id)
        .execute()
    )
    return bool(result.data)


def record_filing(
    gmail_message_id: str,
    drive_file_id: str,
    order_id: Optional[str],
    retailer: str,
    filename: str,
    client,
) -> bool:
    row = {
        "user_id":          PHASE_1_USER_ID,
        "gmail_message_id": gmail_message_id,
        "drive_file_id":    drive_file_id,
        "order_id":         order_id,
        "retailer":         retailer,
        "filed_filename":   filename,
        "filed_at":         datetime.now(timezone.utc).isoformat(),
    }
    result = client.table("invoice_files").insert(row).execute()
    return bool(result.data)


# --------------------------------------------------------------------------- #
# Filing plan — pure decision-making, no file writes
# --------------------------------------------------------------------------- #

def build_filing_plan(meta: dict, client) -> dict:
    """
    Given a parsed message meta dict + Supabase client, compute the full
    filing plan: matched order, retailer folder, filename, Drive path.
    Returns a plan dict — no writes performed here.
    """
    msg_id       = meta["id"]
    sender_email = extract_sender_email(meta["from"])
    date_str     = extract_email_date(meta["date"])
    order_number = extract_order_number_from_subject(meta["subject"])
    order        = match_order(order_number, client)

    if order:
        retailer_key    = order["retailer"].upper().strip()
        retailer_folder = resolve_retailer_folder(order["retailer"], sender_email)
        order_date_str  = order["order_date"]
        shipment_count  = count_shipments(order["order_id"], client)
        next_shipment   = shipment_count + 1  # first new PDF is ship(N+1)
        filename        = build_filename(
            order_number, retailer_key, order_date_str, shipment_num=next_shipment
        )
        folder_path = resolve_drive_folder_path(retailer_folder, order_date_str)
        matched       = True
        order_id      = order["order_id"]
    else:
        retailer_key    = detect_retailer_from_sender(sender_email)
        retailer_folder = RETAILER_DRIVE_FOLDER.get(retailer_key, retailer_key.title())
        filename        = build_unmatched_filename(msg_id, retailer_key, date_str)
        folder_path     = resolve_unmatched_folder_path(retailer_folder)
        matched         = False
        order_id        = None

    return {
        "msg_id":          msg_id,
        "subject":         meta["subject"],
        "sender_email":    sender_email,
        "date_str":        date_str,
        "order_number":    order_number,
        "order_id":        order_id,
        "retailer_key":    retailer_key,
        "retailer_folder": retailer_folder,
        "filename":        filename,
        "folder_path":     folder_path,
        "matched":         matched,
        # next_shipment: only meaningful when matched=True; shipment_count + 1
        "next_shipment":   next_shipment if matched else 1,
    }


# --------------------------------------------------------------------------- #
# Mode 1 — Preview (read-only)
# --------------------------------------------------------------------------- #

def mode_preview(gmail, client) -> list[dict]:
    """
    Scan ResellOS-Invoices and print the proposed filing plan for each message.
    Skips already-filed messages. Returns the plan list for mode_file to use.
    No writes of any kind.
    """
    print("\n" + "=" * 70)
    print("  INVOICE FILING PREVIEW — ResellOS-Invoices")
    print("=" * 70)

    stubs = list_intake_messages(gmail)
    if not stubs:
        print("\n  No messages in ResellOS-Invoices.")
        return []

    print(f"\n  {len(stubs)} message(s) in queue.\n")

    plans: list[dict] = []
    for stub in stubs:
        msg_id = stub["id"]
        if already_filed(msg_id, client):
            print(f"  [ already filed: {msg_id} ]")
            continue
        try:
            msg  = fetch_message(gmail, msg_id)
            meta = parse_message_meta(msg)
        except Exception as e:
            print(f"  ERROR fetching {msg_id}: {e}")
            continue

        plan = build_filing_plan(meta, client)
        plans.append(plan)

        n          = len(plans)
        match_info = f"order {plan['order_number']}" if plan["matched"] else "UNMATCHED"
        folder_str = "/".join(plan["folder_path"])
        print(f"  {n:>2}.  {plan['subject'][:55]}")
        print(f"        From:   {plan['sender_email']}")
        print(f"        Match:  {match_info}")
        print(f"        File:   {plan['filename']}")
        print(f"        Into:   {folder_str}")
        print()

    if not plans:
        print("  All queued messages have already been filed.")
    return plans


# --------------------------------------------------------------------------- #
# Mode 2 — File one invoice
# --------------------------------------------------------------------------- #

def _execute_filing(plan: dict, gmail, drive, client) -> bool:
    """
    Execute the filing plan for one message: download → upload → ledger → relabel.
    Returns True on full success.
    """
    msg_id = plan["msg_id"]

    if already_filed(msg_id, client):
        print("  Already in ledger — nothing to do.")
        return False

    print("  Fetching PDF attachment(s)...")
    try:
        msg     = fetch_message(gmail, msg_id)
        meta    = parse_message_meta(msg)
        pdfs    = extract_pdf_attachments(gmail, msg_id, meta["payload"])
    except Exception as e:
        print(f"  ERROR fetching message: {e}")
        return False

    if not pdfs:
        print("  No PDF attachment found in this message.")
        return False

    if len(pdfs) > 1:
        print(f"  {len(pdfs)} PDF attachments — each will get a _ship{{N}} suffix.")

    print(f"  Resolving Drive folder: {'/'.join(plan['folder_path'])}")
    try:
        folder_id = resolve_folder_id(drive, plan["folder_path"])
    except Exception as e:
        print(f"  ERROR: Drive folder resolution failed: {e}")
        return False

    first_drive_id = None
    for idx, pdf in enumerate(pdfs, 1):
        if len(pdfs) > 1:
            if plan["matched"]:
                # Numbered from next_shipment so we don't collide with existing files
                ship_num = plan["next_shipment"] + (idx - 1)
                filename = build_filename(
                    plan["order_number"],
                    plan["retailer_key"],
                    plan["date_str"],
                    shipment_num=ship_num,
                )
            else:
                # Unmatched multi-PDF: base name for first, _ship{N} suffix for extras
                base = build_unmatched_filename(
                    msg_id, plan["retailer_key"], plan["date_str"]
                )
                filename = base if idx == 1 else f"{base[:-4]}_ship{idx}.pdf"
        else:
            filename = plan["filename"]

        print(f"  Uploading {filename}  ({len(pdf['data'])} bytes)...")
        try:
            drive_file_id = upload_pdf(drive, pdf["data"], filename, folder_id)
        except Exception as e:
            print(f"  ERROR: Drive upload failed: {e}")
            return False
        print(f"  OK: Drive file {drive_file_id}")

        if idx == 1:
            first_drive_id = drive_file_id

    # One ledger row per email message (keyed on gmail_message_id).
    # first_drive_id points to the primary (or only) PDF.
    ok = record_filing(
        msg_id, first_drive_id, plan["order_id"],
        plan["retailer_key"], plan["filename"], client,
    )
    if not ok:
        print("  ERROR: Ledger write failed. File is in Drive — record manually.")
        return False
    print("  OK: Ledger row written")

    try:
        transition_label(gmail, msg_id)
        print("  OK: Label → ResellOS-Filed")
    except Exception as e:
        # File is safe in Drive; label failure is recoverable manually.
        print(f"  WARNING: Label transition failed ({e}). Update label manually.")

    return True


def mode_file(plans: list[dict], gmail, drive, client) -> None:
    if not plans:
        print("\n  Nothing pending to file.")
        return

    print("\n" + "=" * 70)
    print("  FILE INVOICE")
    print("=" * 70)
    print(f"\n  {len(plans)} pending invoice(s) shown above.")
    print("  Enter the number to file, or q to cancel.\n")

    raw = get_input("Invoice number")
    if raw.lower() in ("q", "quit", "cancel"):
        print("  Cancelled.")
        return
    try:
        idx = int(raw)
        if not (1 <= idx <= len(plans)):
            raise IndexError(idx)
        plan = plans[idx - 1]
    except (ValueError, IndexError):
        print("  Invalid selection.")
        return

    print(f"\n  Subject: {plan['subject']}")
    print(f"  File as: {plan['filename']}")
    print(f"  Into:    {'/'.join(plan['folder_path'])}")
    if plan["matched"]:
        print(f"  Order:   {plan['order_number']}")
    else:
        print("  *** UNMATCHED — will file to _unmatched/ ***")

    if not get_yes_no("\n  Proceed?", default="n"):
        print("  Cancelled.")
        return

    success = _execute_filing(plan, gmail, drive, client)
    if success:
        print("\n  Invoice filed successfully.")
    else:
        print("\n  Filing did not complete — see errors above.")


# --------------------------------------------------------------------------- #
# Mode 3 — Ledger review
# --------------------------------------------------------------------------- #

def mode_ledger(client) -> None:
    print("\n" + "=" * 70)
    print("  INVOICE FILES LEDGER")
    print("=" * 70)

    result = (
        client.table("invoice_files")
        .select("gmail_message_id, retailer, filed_filename, filed_at, order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .order("filed_at", desc=True)
        .execute()
    )
    rows = result.data or []

    if not rows:
        print("\n  No filed invoices on record.")
        return

    print(f"\n  {len(rows)} filed invoice(s):\n")
    print(f"  {'#':>3}  {'Filed At':<20}  {'Retailer':<18}  Filename")
    print("  " + "-" * 70)
    for i, row in enumerate(rows, 1):
        filed_at = (row.get("filed_at") or "")[:19]
        retailer = row.get("retailer") or ""
        fname    = row.get("filed_filename") or ""
        print(f"  {i:>3}  {filed_at:<20}  {retailer:<18}  {fname}")
    print()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    print("\n" + "=" * 70)
    print("  RESELLOS — AGENT 01B: INVOICE FILING")
    print("=" * 70)
    print()
    print("  1. Preview  — scan queue, show filing plan, no writes")
    print("  2. File one — pick one pending invoice and file it")
    print("  3. Ledger   — show filed invoice history")
    print()

    mode = get_input("Select mode (1/2/3)").strip()
    if mode not in ("1", "2", "3"):
        print(f"  Unknown mode '{mode}'. Enter 1, 2, or 3.")
        return

    client = get_client()

    if mode == "3":
        mode_ledger(client)
        return

    print("\n  Connecting to Gmail and Drive...")
    try:
        gmail, drive = build_services()
        print("  Connected.\n")
    except Exception as e:
        print(f"  ERROR connecting to Google APIs: {e}")
        print("  Run setup_oauth.py to refresh credentials.")
        return

    if mode == "1":
        mode_preview(gmail, client)
    elif mode == "2":
        plans = mode_preview(gmail, client)
        mode_file(plans, gmail, drive, client)


if __name__ == "__main__":
    main()
