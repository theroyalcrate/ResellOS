"""
ResellOS — Agent 01C: Historical Invoice Backfill
=================================================
One-time LEGO invoice backfill: copies historical billing emails from personal
Gmail to business Gmail, then stays dormant. Safe to re-run — idempotent via
RFC 2822 Message-ID.

Senders:    no-reply-billing03@lego.com  |  receipts@m.lego.com
Date range: 2025-02-01 → 2026-06-01

Modes:
  1 — Preview : search personal Gmail, show count + first 5 results. No writes.
  2 — Copy    : export each raw email from personal Gmail, import to business
                Gmail with ResellOS-Invoices label applied at insert time.
                Idempotent — skips if Message-ID already exists in business Gmail.
  3 — Ledger  : list all LEGO billing emails in business Gmail that carry the
                ResellOS-Invoices label, sorted by date descending.

Authentication:
  credentials/token_personal.json  — gmail.modify (personal account, read-from)
  credentials/token_business.json  — gmail.modify + drive (business account, write-to)
  Run setup_oauth.py once to generate both tokens if not already present.

Idempotency (Mode 2):
  Before importing, checks whether the RFC 2822 Message-ID already exists in
  business Gmail via rfc822msgid search. Prevents duplicate inserts on re-run.

What this agent does NOT do:
  - Rename PDFs or modify email content — raw RFC 2822 copy only.
  - Process any retailer other than LEGO (senders above only).
  - Delete or label anything in personal Gmail.
"""

import base64
import io
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_CREDS_DIR = Path(__file__).parent.parent / "credentials"

TOKEN_PERSONAL_PATH = _CREDS_DIR / "token_personal.json"
TOKEN_BUSINESS_PATH = _CREDS_DIR / "token_business.json"

PERSONAL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

BUSINESS_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]

GMAIL_INTAKE_LABEL_ID = "Label_2573281147792874926"  # ResellOS-Invoices

# Gmail query — senders + date range.
# 'before:' is exclusive in Gmail; using 2026/6/2 ensures Jun 1 emails are included.
_BACKFILL_QUERY = (
    "from:(no-reply-billing03@lego.com OR receipts@m.lego.com) "
    "after:2025/2/1 before:2026/6/2"
)

# Sender-only query reused for Mode 3 ledger (no date restriction there).
_LEGO_SENDER_QUERY = "from:(no-reply-billing03@lego.com OR receipts@m.lego.com)"


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
            # Expired with no refresh_token — needs re-auth.
            return None
    return creds


def build_personal_services():
    """Return gmail_personal. Uses token_personal.json (gmail.modify scope)."""
    creds = _load_creds(TOKEN_PERSONAL_PATH, PERSONAL_SCOPES)
    if not creds:
        print(f"  ERROR: Personal token not found or expired: {TOKEN_PERSONAL_PATH}")
        print("  Run: python setup_oauth.py --personal")
        sys.exit(1)
    return build("gmail", "v1", credentials=creds)


def build_business_services():
    """Return (gmail_business, drive_business). Uses token_business.json."""
    creds = _load_creds(TOKEN_BUSINESS_PATH, BUSINESS_SCOPES)
    if not creds:
        print(f"  ERROR: Business token not found or expired: {TOKEN_BUSINESS_PATH}")
        print("  Run: python setup_oauth.py --business")
        sys.exit(1)
    gmail = build("gmail", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return gmail, drive


# --------------------------------------------------------------------------- #
# Input helpers
# --------------------------------------------------------------------------- #

def get_input(prompt: str, default: Optional[str] = None) -> str:
    display = f"{prompt} [{default}]: " if default is not None else f"{prompt}: "
    while True:
        value = input(display).strip()
        if value:
            return value
        if default is not None:
            return str(default)
        print("  This field is required.")


def get_yes_no(prompt: str, default: str = "n") -> bool:
    while True:
        raw = get_input(f"{prompt} (y/n)", default=default).lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


# --------------------------------------------------------------------------- #
# Gmail helpers
# --------------------------------------------------------------------------- #

def _get_header(msg: dict, name: str) -> str:
    """Extract a named header value from a Gmail message dict (any format)."""
    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }
    return headers.get(name.lower(), "")


def _parse_date_str(date_header: str) -> str:
    """Parse RFC 2822 Date header to YYYY-MM-DD, or '' on failure."""
    try:
        return parsedate_to_datetime(date_header).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _fetch_metadata(gmail, msg_id: str) -> dict:
    """Fetch Subject, From, Date, and Message-ID headers in one API call."""
    return gmail.users().messages().get(
        userId="me",
        id=msg_id,
        format="metadata",
        metadataHeaders=["Subject", "From", "Date", "Message-ID"],
    ).execute()


def _get_rfc822_message_id(msg: dict) -> str:
    """Extract the RFC 2822 Message-ID header value from a fetched message."""
    return _get_header(msg, "message-id").strip()


def _search_messages(gmail, query: str, label_ids: Optional[list[str]] = None) -> list[dict]:
    """
    Paginated Gmail message search. Returns all matching message stubs.
    Gmail returns results newest-first by default.
    """
    stubs: list[dict] = []
    page_token: Optional[str] = None
    while True:
        kwargs: dict = {
            "userId":     "me",
            "q":          query,
            "maxResults": 100,
        }
        if label_ids:
            kwargs["labelIds"] = label_ids
        if page_token:
            kwargs["pageToken"] = page_token
        result = gmail.users().messages().list(**kwargs).execute()
        stubs.extend(result.get("messages", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return stubs


def _message_exists_in_business(gmail_business, rfc822_message_id: str) -> bool:
    """
    Return True if a message with this RFC 2822 Message-ID is already present
    in business Gmail. Prevents duplicate imports on re-run.
    """
    if not rfc822_message_id:
        return False
    mid = rfc822_message_id.strip()
    if not mid.startswith("<"):
        mid = f"<{mid}>"
    result = gmail_business.users().messages().list(
        userId="me",
        q=f"rfc822msgid:{mid}",
        maxResults=1,
    ).execute()
    return bool(result.get("messages"))


def _import_message_to_business(
    gmail_personal,
    gmail_business,
    personal_msg_id: str,
) -> Optional[str]:
    """
    Export raw RFC 2822 from personal Gmail and import it into business Gmail
    with the ResellOS-Invoices label. Returns the new business message ID or None.

    Uses messages.import_() (not insert) so Gmail applies standard processing.
    neverMarkSpam=True prevents spam classification from stripping the label.
    Base64 padding is computed exactly to avoid structural corruption.
    """
    raw_resp = gmail_personal.users().messages().get(
        userId="me", id=personal_msg_id, format="raw"
    ).execute()
    raw_b64 = raw_resp.get("raw", "")
    if not raw_b64:
        return None

    # Gmail's format=raw uses unpadded base64url. Add exact padding.
    raw_bytes = base64.urlsafe_b64decode(raw_b64 + "=" * (-len(raw_b64) % 4))

    result = gmail_business.users().messages().import_(
        userId="me",
        neverMarkSpam=True,
        internalDateSource="dateHeader",
        body={"labelIds": [GMAIL_INTAKE_LABEL_ID]},
        media_body=MediaIoBaseUpload(
            io.BytesIO(raw_bytes),
            mimetype="message/rfc822",
            resumable=False,
        ),
    ).execute()
    return result.get("id")


# --------------------------------------------------------------------------- #
# Mode 1 — Preview (read-only)
# --------------------------------------------------------------------------- #

def mode_preview(gmail_personal) -> None:
    print("\n" + "=" * 70)
    print("  HISTORICAL BACKFILL — PREVIEW")
    print("  Senders: no-reply-billing03@lego.com | receipts@m.lego.com")
    print("  Range:   2025-02-01 → 2026-06-01")
    print("=" * 70)
    print(f"\n  Query: {_BACKFILL_QUERY}\n")

    stubs = _search_messages(gmail_personal, _BACKFILL_QUERY)
    total = len(stubs)

    if total == 0:
        print("  No matching emails found in personal Gmail.")
        return

    print(f"  {total} email(s) found matching the search.\n")
    print("  First 5 (most recent first):\n")
    print(f"  {'#':>3}  {'Date':<12}  {'From':<38}  Subject")
    print("  " + "-" * 72)

    for i, stub in enumerate(stubs[:5], 1):
        try:
            meta = _fetch_metadata(gmail_personal, stub["id"])
        except Exception as e:
            print(f"  {i:>3}  ERROR fetching metadata: {e}")
            continue

        date_str = _parse_date_str(_get_header(meta, "Date")) or "unknown"
        from_hdr = _get_header(meta, "From")[:38]
        subject  = (_get_header(meta, "Subject") or "(no subject)")[:40]
        print(f"  {i:>3}  {date_str:<12}  {from_hdr:<38}  {subject}")

    print()
    if total > 5:
        print(f"  ... and {total - 5} more.")
    print()
    print("  No writes performed. Run Mode 2 to copy all emails to business Gmail.")


# --------------------------------------------------------------------------- #
# Mode 2 — Copy
# --------------------------------------------------------------------------- #

def mode_copy(gmail_personal, gmail_business) -> None:
    print("\n" + "=" * 70)
    print("  HISTORICAL BACKFILL — COPY TO BUSINESS GMAIL")
    print("=" * 70)
    print()
    print("  Exports each LEGO billing email from personal Gmail (raw RFC 2822)")
    print("  and imports it into business Gmail under the ResellOS-Invoices label.")
    print("  Emails already present in business Gmail are skipped.")
    print()

    if not get_yes_no("Proceed with copy?", default="n"):
        print("  Cancelled.")
        return

    print(f"\n  Searching personal Gmail...")
    stubs = _search_messages(gmail_personal, _BACKFILL_QUERY)
    total = len(stubs)
    print(f"  {total} email(s) found.\n")

    if total == 0:
        print("  Nothing to copy.")
        return

    copied  = 0
    skipped = 0
    failed  = 0

    for stub in stubs:
        personal_msg_id = stub["id"]

        # Fetch metadata for display and idempotency check.
        try:
            meta = _fetch_metadata(gmail_personal, personal_msg_id)
        except Exception as e:
            print(f"  ERROR  [{personal_msg_id}]  Could not fetch metadata: {e}")
            failed += 1
            continue

        date_str  = _parse_date_str(_get_header(meta, "Date")) or "unknown"
        sender    = _get_header(meta, "From")
        subject   = (_get_header(meta, "Subject") or personal_msg_id)[:55]
        rfc822_id = _get_rfc822_message_id(meta)

        # Idempotency: skip if already in business Gmail.
        try:
            already = _message_exists_in_business(gmail_business, rfc822_id)
        except Exception as e:
            print(f"  WARNING  Could not check business Gmail ({e}) — will attempt copy.")
            already = False

        if already:
            print(f"  SKIP   {date_str}  {subject}")
            skipped += 1
            continue

        # Import raw message to business Gmail.
        print(f"  COPY   {date_str}  {subject}")
        try:
            new_id = _import_message_to_business(
                gmail_personal, gmail_business, personal_msg_id
            )
        except Exception as e:
            print(f"    ERROR: {e}")
            failed += 1
            continue

        if not new_id:
            print("    ERROR: Import returned no message ID.")
            failed += 1
            continue

        print(f"    → Business message ID: {new_id}")
        copied += 1

    print()
    print("-" * 70)
    print(
        f"  Summary: {total} found | {copied} copied | "
        f"{skipped} already present | {failed} failed"
    )
    if copied > 0:
        print(f"\n  {copied} email(s) now in business Gmail under ResellOS-Invoices.")
        print("  Run Mode 3 (Ledger) to verify, then Agent 1B Mode 1 to file them.")
    if failed > 0:
        print(f"\n  {failed} message(s) failed — check errors above and re-run.")
        print("  Re-running is safe: already-copied messages are skipped.")


# --------------------------------------------------------------------------- #
# Mode 3 — Ledger
# --------------------------------------------------------------------------- #

def mode_ledger(gmail_business) -> None:
    print("\n" + "=" * 70)
    print("  BUSINESS GMAIL LEGO INVOICE LEDGER")
    print("  Label: ResellOS-Invoices | Senders: billing03 + m.lego.com")
    print("=" * 70)

    print("\n  Searching business Gmail...")
    stubs = _search_messages(
        gmail_business,
        query=_LEGO_SENDER_QUERY,
        label_ids=[GMAIL_INTAKE_LABEL_ID],
    )
    total = len(stubs)

    if total == 0:
        print("\n  No LEGO billing emails found in business Gmail under ResellOS-Invoices.")
        return

    print(f"  {total} message(s) found. Fetching details...\n")

    rows: list[dict] = []
    for stub in stubs:
        try:
            meta = _fetch_metadata(gmail_business, stub["id"])
        except Exception as e:
            print(f"  WARNING: Could not fetch {stub['id']}: {e} — skipping")
            continue
        rows.append({
            "date":    _parse_date_str(_get_header(meta, "Date")),
            "from":    _get_header(meta, "From"),
            "subject": _get_header(meta, "Subject") or "(no subject)",
        })

    # Sort date descending; empty dates sort last.
    rows.sort(key=lambda r: r["date"] if r["date"] else "0000-00-00", reverse=True)

    print(f"  {'#':>3}  {'Date':<12}  {'From':<40}  Subject")
    print("  " + "-" * 74)
    for i, row in enumerate(rows, 1):
        date_disp = row["date"] or "unknown"
        from_disp = row["from"][:40]
        subj_disp = row["subject"][:38]
        print(f"  {i:>3}  {date_disp:<12}  {from_disp:<40}  {subj_disp}")
    print()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    print("\n" + "=" * 70)
    print("  RESELLOS — AGENT 01C: HISTORICAL INVOICE BACKFILL")
    print("  LEGO only  |  Feb 2025 – Jun 2026  |  One-time / safe to re-run")
    print("=" * 70)
    print()
    print("  1. Preview — count + sample from personal Gmail (no writes)")
    print("  2. Copy    — export from personal → import to business Gmail")
    print("  3. Ledger  — verify LEGO emails landed in business Gmail")
    print()

    mode = get_input("Select mode (1/2/3)").strip()
    if mode not in ("1", "2", "3"):
        print(f"  Unknown mode '{mode}'. Enter 1, 2, or 3.")
        return

    if mode == "1":
        print("\n  Connecting to personal Gmail...")
        try:
            gmail_personal = build_personal_services()
            print("  Connected.\n")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ERROR: {e}")
            return
        mode_preview(gmail_personal)
        return

    if mode == "2":
        print("\n  Connecting to personal Gmail...")
        try:
            gmail_personal = build_personal_services()
            print("  Connected.")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ERROR connecting to personal Gmail: {e}")
            return
        print("  Connecting to business Gmail...")
        try:
            gmail_business, _ = build_business_services()
            print("  Connected.\n")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ERROR connecting to business Gmail: {e}")
            return
        mode_copy(gmail_personal, gmail_business)
        return

    if mode == "3":
        print("\n  Connecting to business Gmail...")
        try:
            gmail_business, _ = build_business_services()
            print("  Connected.\n")
        except SystemExit:
            raise
        except Exception as e:
            print(f"  ERROR connecting to business Gmail: {e}")
            return
        mode_ledger(gmail_business)
        return


if __name__ == "__main__":
    main()
