"""
ResellOS - Agent 01B: Invoice Filing (Business + Personal Gmail)
================================================================
Three-part agent that consolidates business invoice filing and personal
Gmail historical backfill into a single script.

Part 1 — Business Gmail filing (Modes 1-3, ongoing):
  Downloads PDF invoices from business Gmail (label: ResellOS-Invoices),
  renames them, files them into the business Drive folder structure, and
  records each filing in the invoice_files ledger. Moves the email label
  from ResellOS-Invoices → ResellOS-Filed on success.

Part 2 — Personal Gmail backfill (Mode 4, one-time / safe to re-run):
  Searches personal Gmail for LEGO invoice emails (from e.lego.com with
  attachments) not yet labeled ResellOS-Processed. Copies each match to
  business Gmail under the ResellOS-Invoices label so Part 1 picks it up
  on the next run. Labels the personal copy ResellOS-Processed so re-runs
  don't reprocess the same email.

Part 3 — Personal safety-net filter (Mode 5, one-time setup):
  Creates a Gmail filter on the personal account that applies the label
  ResellOS-Needs-Copy to any new email from e.lego.com. The P0 forwarding
  rule handles most new LEGO invoices; this filter catches any that slip
  through to personal. Mode 4 picks them up on its next run.

Modes:
  1 — Preview       : scan business ResellOS-Invoices, show filing plan, no writes
  2 — File one      : pick one pending invoice and file it (business Gmail → Drive)
  3 — Ledger        : show invoice_files history
  4 — Personal backfill : copy unprocessed personal LEGO emails to business Gmail
  5 — Safety filter : create personal Gmail filter for e.lego.com emails

Authentication:
  credentials/token_business.json   gmail.modify + drive (business account)
  credentials/token_personal.json   gmail.modify + gmail.settings.basic (personal)
  Run setup_oauth.py once to generate both tokens.
  Legacy credentials/token.json is recognized and used if token_business.json
  is absent (pre-S10 setup — re-run setup_oauth.py to migrate properly).

Naming convention (§3):
  {order_number}_{RETAILER}_{YYYY-MM-DD}.pdf
  {order_number}_{RETAILER}_{YYYY-MM-DD}_ship2.pdf   ← split shipments
  _unmatched/{gmail_message_id}_{RETAILER}_{YYYY-MM-DD}.pdf

Walmart routing rule (§7.5):
  businessinfo@walmart.com → Walmart Business/
  help@walmart.com         → Walmart/

Idempotency (§5):
  Part 1: gmail_message_id checked against invoice_files before any write.
  Part 2: ResellOS-Processed label on personal copy + rfc822msgid search on
          business Gmail — prevents duplicate copies even if personal labeling
          failed on a prior run.
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

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_client import get_client, PHASE_1_USER_ID


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_CREDS_DIR = Path(__file__).parent.parent / "credentials"

# Business account: gmail.modify + Drive
TOKEN_BUSINESS_PATH = _CREDS_DIR / "token_business.json"
TOKEN_LEGACY_PATH   = _CREDS_DIR / "token.json"          # pre-S10 name

BUSINESS_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

# Personal account: gmail.modify + settings (needed for filter creation)
TOKEN_PERSONAL_PATH = _CREDS_DIR / "token_personal.json"

PERSONAL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]

# Business Gmail label IDs (Part 1)
GMAIL_INTAKE_LABEL_ID = "Label_2573281147792874926"  # ResellOS-Invoices
GMAIL_FILED_LABEL_ID  = "Label_1"                    # ResellOS-Filed

DRIVE_ROOT_FOLDER = "Invoices"

# Personal Gmail labels (Part 2 and 3)
PERSONAL_PROCESSED_LABEL  = "ResellOS-Processed"    # marks personal copy as copied
PERSONAL_NEEDS_COPY_LABEL = "ResellOS-Needs-Copy"   # applied by safety-net filter

# Gmail search for LEGO invoice emails in personal account.
# Matches only emails with attachments — avoids copying order confirmations
# that have no PDFs and would create noise in the business queue.
PERSONAL_LEGO_QUERY = "from:(e.lego.com) has:attachment"

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
# More-specific entries first.
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

def _load_creds(token_path: Path, scopes: list[str]) -> Optional[Credentials]:
    """Load, refresh-if-needed, and persist credentials from token_path."""
    if not token_path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
        else:
            # Token expired with no refresh_token (revoked or never issued).
            # Return None so callers surface a clear error instead of
            # building an API service that fails on the first API call.
            return None
    return creds


def build_business_services():
    """Return (gmail_business, drive_business). Uses token_business.json."""
    # Accept legacy token.json if token_business.json hasn't been created yet
    token_path = TOKEN_BUSINESS_PATH
    if not TOKEN_BUSINESS_PATH.exists() and TOKEN_LEGACY_PATH.exists():
        print(
            "  NOTE: Using legacy token.json for business account. "
            "Re-run setup_oauth.py to migrate to token_business.json."
        )
        token_path = TOKEN_LEGACY_PATH

    creds = _load_creds(token_path, BUSINESS_SCOPES)
    if not creds:
        print(f"  ERROR: Business token not found at {token_path}")
        print("  Run: python setup_oauth.py --business")
        sys.exit(1)

    gmail = build("gmail", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return gmail, drive


def build_personal_gmail():
    """Return personal gmail service. Uses token_personal.json."""
    creds = _load_creds(TOKEN_PERSONAL_PATH, PERSONAL_SCOPES)
    if not creds:
        print(f"  ERROR: Personal token not found at {TOKEN_PERSONAL_PATH}")
        print("  Run: python setup_oauth.py --personal")
        print()
        print("  If setup fails with a scope error, add these scopes in Google Cloud Console:")
        print("  APIs & Services → OAuth consent screen → Data Access:")
        print("    gmail.modify, gmail.settings.basic, drive.file")
        sys.exit(1)
    return build("gmail", "v1", credentials=creds)


# --------------------------------------------------------------------------- #
# Gmail I/O — Business (Part 1)
# --------------------------------------------------------------------------- #

def list_intake_messages(gmail) -> list[dict]:
    messages: list[dict] = []
    page_token = None
    while True:
        kwargs: dict = {
            "userId":     "me",
            "labelIds":   [GMAIL_INTAKE_LABEL_ID],
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
# Gmail I/O — Personal (Part 2 and 3)
# --------------------------------------------------------------------------- #

def get_or_create_label(gmail, label_name: str) -> str:
    """Return the ID of a Gmail label, creating it if it doesn't exist."""
    result = gmail.users().labels().list(userId="me").execute()
    for label in result.get("labels", []):
        if label["name"] == label_name:
            return label["id"]
    created = gmail.users().labels().create(
        userId="me", body={"name": label_name}
    ).execute()
    return created["id"]


def get_rfc822_message_id(msg: dict) -> str:
    """Extract the RFC 2822 Message-ID from a full message's headers."""
    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }
    return headers.get("message-id", "")


def message_exists_in_business(gmail_business, rfc822_message_id: str) -> bool:
    """
    Check whether a message with this RFC 2822 Message-ID already exists in
    business Gmail. Used as belt-and-suspenders to prevent duplicate inserts
    when a prior run's personal-labeling step failed after a successful copy.
    """
    if not rfc822_message_id:
        return False
    # Normalise: ensure the ID is wrapped in angle brackets for Gmail search.
    # Bare colons or spaces in the local part can break the query grammar when
    # the ID is passed unquoted; the <...> form is what Gmail expects.
    msg_id = rfc822_message_id.strip()
    if not msg_id.startswith("<"):
        msg_id = f"<{msg_id}>"
    result = gmail_business.users().messages().list(
        userId="me",
        q=f"rfc822msgid:{msg_id}",
        maxResults=1,
    ).execute()
    return bool(result.get("messages"))


def search_personal_lego_emails(gmail_personal) -> list[dict]:
    """
    Return message stubs from personal Gmail matching PERSONAL_LEGO_QUERY.
    The ResellOS-Processed exclusion is done via label ID after fetching,
    because Gmail search only supports label names (which may vary by account).
    The caller handles the processed-label filter.
    """
    stubs: list[dict] = []
    page_token = None
    while True:
        kwargs: dict = {
            "userId":     "me",
            "q":          PERSONAL_LEGO_QUERY,
            "maxResults": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = gmail_personal.users().messages().list(**kwargs).execute()
        stubs.extend(result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return stubs


def copy_message_to_business_gmail(
    gmail_personal,
    gmail_business,
    personal_msg_id: str,
    intake_label_id: str,
) -> Optional[str]:
    """
    Export the raw RFC 2822 message from personal Gmail, insert it into
    business Gmail with the ResellOS-Invoices label applied at insert time.
    Returns the new business Gmail message ID, or None on failure.
    """
    raw_response = gmail_personal.users().messages().get(
        userId="me", id=personal_msg_id, format="raw"
    ).execute()
    raw_b64 = raw_response.get("raw", "")
    if not raw_b64:
        return None

    # Compute exact padding needed: Gmail's format=raw uses unpadded base64.
    # Adding "==" unconditionally corrupts messages when len(raw_b64) % 4 == 3
    # (the extra "=" produces length % 4 == 1 which is structurally invalid).
    raw_bytes = base64.urlsafe_b64decode(raw_b64 + "=" * (-len(raw_b64) % 4))

    inserted = gmail_business.users().messages().insert(
        userId="me",
        body={"labelIds": [intake_label_id]},
        internalDateSource="dateHeader",
        media_body=MediaIoBaseUpload(
            io.BytesIO(raw_bytes),
            mimetype="message/rfc822",
            resumable=False,
        ),
    ).execute()
    return inserted.get("id")


def apply_label_to_message(gmail, msg_id: str, label_id: str) -> None:
    """Add a label to a Gmail message (non-destructive)."""
    gmail.users().messages().modify(
        userId="me",
        id=msg_id,
        body={"addLabelIds": [label_id]},
    ).execute()


# --------------------------------------------------------------------------- #
# Drive I/O
# --------------------------------------------------------------------------- #

def _find_folder(drive, name: str, parent_id: str) -> Optional[str]:
    """
    Return the ID of the first folder matching name under parent_id.
    The name filter in the query is server-side — avoids pagination misses
    when a parent folder has many children. Client-side strip comparison is
    kept as a safety net for trailing-space folder names.
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
        next_shipment   = shipment_count + 1
        filename        = build_filename(
            order_number, retailer_key, order_date_str, shipment_num=next_shipment
        )
        folder_path = resolve_drive_folder_path(retailer_folder, order_date_str)
        matched     = True
        order_id    = order["order_id"]
    else:
        retailer_key    = detect_retailer_from_sender(sender_email)
        retailer_folder = RETAILER_DRIVE_FOLDER.get(retailer_key, retailer_key.title())
        filename        = build_unmatched_filename(msg_id, retailer_key, date_str)
        folder_path     = resolve_unmatched_folder_path(retailer_folder)
        matched         = False
        order_id        = None
        next_shipment   = 1

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
        "next_shipment":   next_shipment,
    }


# --------------------------------------------------------------------------- #
# Mode 1 — Preview (read-only, Part 1)
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
# Mode 2 — File one invoice (Part 1)
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
                ship_num = plan["next_shipment"] + (idx - 1)
                filename = build_filename(
                    plan["order_number"],
                    plan["retailer_key"],
                    plan["date_str"],
                    shipment_num=ship_num,
                )
            else:
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
# Mode 3 — Ledger review (Part 1)
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
# Mode 4 — Personal Gmail historical backfill (Part 2)
# --------------------------------------------------------------------------- #

def mode_personal_backfill(gmail_personal, gmail_business) -> None:
    """
    Copy unprocessed LEGO invoice emails from personal Gmail to business Gmail.
    Idempotency:
      - Primary guard:  ResellOS-Processed label on personal copy (set after copy)
      - Secondary guard: rfc822msgid search on business Gmail (catches the case
        where copy succeeded but personal labeling failed on a prior run — skips
        the duplicate insert and retries only the labeling)
    """
    print("\n" + "=" * 70)
    print("  PERSONAL GMAIL BACKFILL")
    print("  Copy LEGO invoice emails → business Gmail (ResellOS-Invoices)")
    print("=" * 70)

    print(f"\n  Ensuring '{PERSONAL_PROCESSED_LABEL}' label exists on personal account...")
    processed_label_id = get_or_create_label(gmail_personal, PERSONAL_PROCESSED_LABEL)
    print(f"  Label ID: {processed_label_id}")

    print(f"\n  Searching personal Gmail for: {PERSONAL_LEGO_QUERY}")
    all_stubs = search_personal_lego_emails(gmail_personal)
    print(f"  Found {len(all_stubs)} matching message(s). Filtering for unprocessed...")

    # Filter out messages that already carry the ResellOS-Processed label.
    # Include Message-ID in metadataHeaders so we don't need a second full-format
    # fetch later — the rfc822 Message-ID is available from this single call.
    unprocessed_stubs: list[dict] = []
    for stub in all_stubs:
        try:
            meta_msg = gmail_personal.users().messages().get(
                userId="me", id=stub["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date", "Message-ID"],
            ).execute()
            label_ids = meta_msg.get("labelIds", [])
            if processed_label_id in label_ids:
                continue
            unprocessed_stubs.append({**stub, "_meta": meta_msg})
        except Exception as e:
            print(f"  WARNING: Could not check labels for {stub['id']}: {e} — skipping")

    print(f"  {len(unprocessed_stubs)} unprocessed email(s) to copy.\n")

    if not unprocessed_stubs:
        print("  Nothing to backfill — all matching emails already processed.")
        return

    found       = len(unprocessed_stubs)
    copied      = 0
    skipped_dup = 0
    failed      = 0

    for stub in unprocessed_stubs:
        personal_msg_id = stub["id"]
        meta_msg        = stub["_meta"]

        # Extract subject for display (already fetched in metadata above)
        meta_headers = {
            h["name"].lower(): h["value"]
            for h in meta_msg.get("payload", {}).get("headers", [])
        }
        subject_short = meta_headers.get("subject", personal_msg_id)[:55]

        # Message-ID was requested in metadataHeaders above — no second fetch needed
        rfc822_id = get_rfc822_message_id(meta_msg)

        # Belt-and-suspenders: already in business Gmail?
        already_in_biz = message_exists_in_business(gmail_business, rfc822_id)
        if already_in_biz:
            print(f"  SKIP (already in business): {subject_short}")
            # Retry labeling the personal copy — it was missed on a prior run
            try:
                apply_label_to_message(gmail_personal, personal_msg_id, processed_label_id)
            except Exception as e:
                print(f"    WARNING: Could not apply ResellOS-Processed label: {e}")
            skipped_dup += 1
            continue

        # Copy raw message to business Gmail with ResellOS-Invoices label
        print(f"  Copying: {subject_short}")
        try:
            new_biz_id = copy_message_to_business_gmail(
                gmail_personal, gmail_business,
                personal_msg_id, GMAIL_INTAKE_LABEL_ID,
            )
        except Exception as e:
            print(f"    ERROR copying to business Gmail: {e}")
            failed += 1
            continue

        if not new_biz_id:
            print("    ERROR: Insert returned no message ID.")
            failed += 1
            continue

        print(f"    → Business Gmail message ID: {new_biz_id}")

        # Label personal copy as processed (only after successful business insert)
        try:
            apply_label_to_message(gmail_personal, personal_msg_id, processed_label_id)
            print("    → Personal copy labeled ResellOS-Processed")
        except Exception as e:
            print(f"    WARNING: Personal labeling failed ({e}).")
            print("    The email is safely in business Gmail.")
            print("    On next run, the rfc822msgid check will detect it and retry labeling.")

        copied += 1

    print()
    print("-" * 70)
    print(
        f"  Summary: {found} found | {copied} copied to business | "
        f"{skipped_dup} already there | {failed} failed"
    )
    if copied > 0:
        print(f"\n  {copied} invoice(s) are now in business Gmail under ResellOS-Invoices.")
        print("  Run Mode 1 (Preview) to review them, then Mode 2 (File one) to file.")
    if failed > 0:
        print(f"\n  {failed} message(s) failed — check errors above and re-run.")


# --------------------------------------------------------------------------- #
# Mode 5 — Personal Gmail safety-net filter (Part 3)
# --------------------------------------------------------------------------- #

def mode_create_safety_filter(gmail_personal) -> None:
    """
    Create a Gmail filter on the personal account that labels any new email
    from e.lego.com with ResellOS-Needs-Copy. Mode 4 picks those up on its
    next run. This is a safety net only — the P0 forwarding rule handles
    most new LEGO invoices at the domain level.
    """
    print("\n" + "=" * 70)
    print("  PERSONAL GMAIL SAFETY-NET FILTER")
    print("=" * 70)
    print()
    print(f"  Creates a filter on your PERSONAL Gmail account:")
    print(f"  From: e.lego.com  →  label '{PERSONAL_NEEDS_COPY_LABEL}'")
    print()
    print("  This catches any LEGO invoices that slip through to personal Gmail")
    print("  instead of routing to business via the P0 forwarding rule.")
    print("  Run Mode 4 periodically to copy flagged emails to business Gmail.")
    print()

    if not get_yes_no("Create this filter now?", default="y"):
        print("  Cancelled.")
        return

    print(f"\n  Ensuring '{PERSONAL_NEEDS_COPY_LABEL}' label exists...")
    try:
        needs_copy_label_id = get_or_create_label(gmail_personal, PERSONAL_NEEDS_COPY_LABEL)
        print(f"  Label ID: {needs_copy_label_id}")
    except Exception as e:
        print(f"  ERROR creating label: {e}")
        return

    # Check whether this exact filter already exists
    try:
        existing = gmail_personal.users().settings().filters().list(userId="me").execute()
        for f in existing.get("filter", []):
            criteria = f.get("criteria", {})
            action   = f.get("action", {})
            if (
                criteria.get("from") == "e.lego.com"
                and needs_copy_label_id in action.get("addLabelIds", [])
            ):
                print("  Filter already exists — nothing to do.")
                return
    except Exception as e:
        print(f"  WARNING: Could not list existing filters ({e}). Attempting to create anyway.")

    filter_body = {
        "criteria": {"from": "e.lego.com"},
        "action":   {"addLabelIds": [needs_copy_label_id]},
    }

    try:
        result = gmail_personal.users().settings().filters().create(
            userId="me", body=filter_body
        ).execute()
        print(f"\n  Filter created (ID: {result.get('id', 'unknown')})")
        print(f"  Criteria : from e.lego.com")
        print(f"  Action   : apply label '{PERSONAL_NEEDS_COPY_LABEL}'")
        print()
        print("  Safety-net filter is now active on your personal Gmail.")
        print(f"  New LEGO emails will be labeled '{PERSONAL_NEEDS_COPY_LABEL}'.")
        print("  Run Mode 4 periodically to copy any flagged emails to business Gmail.")
    except Exception as e:
        print(f"\n  ERROR creating filter: {e}")
        print()
        print("  If you see a 403 or insufficient scope error:")
        print("  1. Go to Google Cloud Console → APIs & Services → OAuth consent screen")
        print("     → Data Access tab and ensure these scopes are listed:")
        print("       gmail.modify, gmail.settings.basic, drive.file")
        print("  2. Re-run: python setup_oauth.py --personal")
        print("  3. Try Mode 5 again.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    print("\n" + "=" * 70)
    print("  RESELLOS — AGENT 01B: INVOICE FILING")
    print("=" * 70)
    print()
    print("  — BUSINESS GMAIL (ongoing) —")
    print("  1. Preview  — scan business queue, show filing plan, no writes")
    print("  2. File one — pick one pending invoice and file it to Drive")
    print("  3. Ledger   — show filed invoice history")
    print()
    print("  — PERSONAL GMAIL (one-time setup) —")
    print("  4. Personal backfill — copy historical LEGO emails to business Gmail")
    print("  5. Safety filter     — create personal Gmail filter for e.lego.com")
    print()

    mode = get_input("Select mode (1/2/3/4/5)").strip()
    if mode not in ("1", "2", "3", "4", "5"):
        print(f"  Unknown mode '{mode}'. Enter 1, 2, 3, 4, or 5.")
        return

    if mode == "3":
        client = get_client()
        mode_ledger(client)
        return

    if mode in ("1", "2"):
        client = get_client()
        print("\n  Connecting to business Gmail and Drive...")
        try:
            gmail_biz, drive_biz = build_business_services()
            print("  Connected.\n")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ERROR connecting to Google APIs: {e}")
            print("  Run: python setup_oauth.py --business")
            return
        if mode == "1":
            mode_preview(gmail_biz, client)
        else:
            plans = mode_preview(gmail_biz, client)
            mode_file(plans, gmail_biz, drive_biz, client)
        return

    if mode == "4":
        print("\n  Connecting to business Gmail...")
        try:
            gmail_biz, _ = build_business_services()
            print("  Connected.")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ERROR connecting to business Gmail: {e}")
            print("  Run: python setup_oauth.py --business")
            return
        print("  Connecting to personal Gmail...")
        try:
            gmail_personal = build_personal_gmail()
            print("  Connected.\n")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ERROR connecting to personal Gmail: {e}")
            print("  Run: python setup_oauth.py --personal")
            return
        mode_personal_backfill(gmail_personal, gmail_biz)
        return

    if mode == "5":
        print("\n  Connecting to personal Gmail...")
        try:
            gmail_personal = build_personal_gmail()
            print("  Connected.\n")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ERROR connecting to personal Gmail: {e}")
            print("  Run: python setup_oauth.py --personal")
            return
        mode_create_safety_filter(gmail_personal)


if __name__ == "__main__":
    main()
