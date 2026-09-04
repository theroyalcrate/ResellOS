"""
ResellOS — Agent 01D: Personal→Business Drive Historical Invoice Backfill
==========================================================================
One-time backfill: finds LEGO invoice PDFs sitting in personal Google Drive
(pre-dating the Gmail-forwarding + Agent 1B/1C pipeline), renames them to the
standard {order_number}_{RETAILER}_{YYYY-MM-DD}.pdf convention, and copies
them into the business Drive Invoices/ folder structure. Never modifies,
moves, or deletes anything in personal Drive — read-only source, exactly
like Agent 1C's guarantee on personal Gmail.

Background (SESSION_LOG.md "Start Here" Step 0, queued 2026-08-15):
  A Zapier scan of personal Drive for `mimeType='application/pdf' and
  (name contains 'LEGO' or name contains 'Receipt')` hit the 1,000-result
  page cap with more still available: 714 distinct filenames within that
  first page, 228 with duplicate copies. Too large and duplicated to
  hand-migrate one file at a time — this script automates it, reusing
  Agent 1B's matching/naming/foldering functions and Agent 1C's
  Preview/Copy/Ledger UX pattern rather than inventing new logic.

Modes:
  1 — Preview : scan personal Drive, download + parse every candidate PDF,
                show the filing plan and outcome counts. No writes anywhere.
  2 — Copy    : execute the plan — copy survivors into business Drive,
                write one invoice_files ledger row per personal file
                evaluated (idempotency key below). Personal Drive is never
                written to, moved from, or deleted from.
  3 — Ledger  : show every row this agent has written (drive-backfill: rows).

Scope (first build, matches Agent 1C): LEGO only. Other retailers' personal
Drive backlogs (if any exist) are out of scope until asked for.

Authentication:
  credentials/token_personal.json — needs gmail.modify, gmail.settings.basic,
    AND drive.readonly. The first two already exist from Agent 1C's setup;
    drive.readonly is NEW — added to setup_oauth.py's PERSONAL_SCOPES
    alongside this script. If the token on disk predates that change, every
    Drive call below fails with a 403 and prints the fix: re-run
      python setup_oauth.py --personal
    (one-time browser re-consent — scopes changed since personal was first
    authorized for Agent 1C. Business is unaffected; only personal needs it.)
  credentials/token_business.json — gmail.modify + drive (already granted,
    same token Agent 1B/1C use — no changes needed here).

Idempotency:
  Every personal Drive file this agent evaluates gets exactly one row in the
  invoice_files ledger, keyed by a synthetic gmail_message_id of the form
  "drive-backfill:{personal_drive_file_id}" (the ledger's gmail_message_id
  column is NOT NULL UNIQUE and predates a Drive-only source — this is the
  minimal way to reuse it without a schema migration). Re-running the script
  skips any personal file already in the ledger — matched, unmatched, or
  skipped — so the full 1,000+ backlog only needs one honest download+parse
  pass, and interrupted runs resume cheaply.

  Within a single run, duplicate personal-Drive copies of the same invoice
  are detected by invoice NUMBER, not order number, per the 2026-08-15
  decision — a legitimate split shipment has one order number but several
  invoice numbers, so order-number dedup would wrongly collapse those. The
  first copy of a given invoice number is filed; later copies are logged as
  duplicates and never copied.

  Orders already filed via the Gmail pipeline (Agent 1C copied the email,
  Agent 1B filed the PDF — already true for most Jun-Aug 2026 orders) are
  detected by checking invoice_files for an existing row on the same
  order_id, from ANY source, before copying — prevents a second copy of an
  invoice business Drive already has.

What this agent does NOT do:
  - Touch, rename, move, or delete anything in personal Drive. Read-only.
  - Process any retailer other than LEGO.
  - Guess or fill buy_reason / purchase_trigger — this is a filing agent,
    not an order-entry agent.
"""

import io
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httplib2
import requests
import urllib3
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_client import get_client, PHASE_1_USER_ID          # noqa: E402
from invoice_parser import parse_invoice                    # noqa: E402

from agent_01b_invoice_filing import (                      # noqa: E402
    RETAILER_DRIVE_FOLDER,
    build_filename,
    resolve_drive_folder_path,
    resolve_folder_id,
    upload_pdf,
    match_order,
    count_shipments,
    already_filed,
    record_filing,
    build_business_services,
    get_input,
    get_yes_no,
)

# Python 3.14 + Windows SSL interceptor workaround — same root cause / same
# fix as db_client.py and agent_01b_invoice_filing.py. Safe for a local CLI
# tool talking to Google's own APIs over HTTPS.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _insecure_http() -> httplib2.Http:
    return httplib2.Http(disable_ssl_certificate_validation=True)


def _insecure_requests_session() -> requests.Session:
    session = requests.Session()
    session.verify = False
    return session


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_CREDS_DIR = Path(__file__).parent.parent / "credentials"
TOKEN_PERSONAL_PATH = _CREDS_DIR / "token_personal.json"

# Superset of setup_oauth.py's PERSONAL_SCOPES — includes drive.readonly.
PERSONAL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/drive.readonly",
]

DRIVE_SEARCH_QUERY = (
    "mimeType='application/pdf' "
    "and (name contains 'LEGO' or name contains 'Receipt') "
    "and trashed=false"
)

LEDGER_KEY_PREFIX = "drive-backfill:"


# --------------------------------------------------------------------------- #
# OAuth / service setup
# --------------------------------------------------------------------------- #

def _load_creds(token_path: Path, scopes: list[str]) -> Optional[Credentials]:
    if not token_path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request(session=_insecure_requests_session()))
            token_path.write_text(creds.to_json())
        else:
            return None
    return creds


def build_personal_drive():
    """Return personal Drive service (read-only intent — this script only
    ever calls files().list() and files().get_media()). Uses
    token_personal.json."""
    creds = _load_creds(TOKEN_PERSONAL_PATH, PERSONAL_SCOPES)
    if not creds:
        print(f"  ERROR: Personal token missing/invalid at {TOKEN_PERSONAL_PATH}")
        print()
        print("  Run: python setup_oauth.py --personal")
        print("  Sign in with your PERSONAL Gmail account when prompted.")
        sys.exit(1)
    authed_http = AuthorizedHttp(creds, http=_insecure_http())
    return build("drive", "v3", http=authed_http)


def _print_scope_fix() -> None:
    print()
    print("  This usually means the personal token was authorized before")
    print("  drive.readonly was added to its scope list. Fix:")
    print("    python setup_oauth.py --personal")
    print("  (one-time browser re-consent — sign in with your PERSONAL")
    print("  Gmail account when prompted)")


# --------------------------------------------------------------------------- #
# Personal Drive listing (read-only)
# --------------------------------------------------------------------------- #

def list_personal_pdfs(drive) -> list[dict]:
    """
    Paginated search of personal Drive for candidate LEGO invoice PDFs.
    Pages through nextPageToken until exhausted — fixes the 2026-08-15
    Zapier discovery, which hit Zapier's 1,000-row cap on the first page.
    """
    files: list[dict] = []
    page_token: Optional[str] = None
    while True:
        kwargs = {
            "q": DRIVE_SEARCH_QUERY,
            "fields": "nextPageToken, files(id, name, createdTime)",
            "pageSize": 1000,
            "spaces": "drive",
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = drive.files().list(**kwargs).execute()
        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return files


def download_pdf_bytes(drive, file_id: str) -> bytes:
    """Download a personal Drive file's raw bytes. Read-only — get_media."""
    request = drive.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Ledger — idempotency key helpers (reuses invoice_files via agent_01b)
# --------------------------------------------------------------------------- #

def ledger_key(personal_file_id: str) -> str:
    return f"{LEDGER_KEY_PREFIX}{personal_file_id}"


def already_evaluated(personal_file_id: str, client) -> bool:
    return already_filed(ledger_key(personal_file_id), client)


def already_filed_for_order(order_id: str, client) -> bool:
    """
    True if ANY invoice_files row already exists for this order — from the
    Gmail pipeline (Agent 1C + 1B) or an earlier run of this script. Prevents
    filing a second copy of an invoice business Drive already has.
    """
    result = (
        client.table("invoice_files")
        .select("id")
        .eq("order_id", order_id)
        .execute()
    )
    return bool(result.data)


# --------------------------------------------------------------------------- #
# Per-file evaluation — pure decision logic (no writes)
# --------------------------------------------------------------------------- #

def _parse_order_date(order_date_raw: Optional[str]) -> Optional[str]:
    """LEGO PDFs print order date as '03 Dec 2025' — convert to ISO for the
    naming/foldering helpers, which expect YYYY-MM-DD (date.fromisoformat)."""
    if not order_date_raw:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(order_date_raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def evaluate_file(stub: dict, pdf_bytes: bytes, client, seen_invoice_numbers: set) -> dict:
    """
    Parse one PDF and decide its outcome. Pure function — no Drive/ledger
    writes. Returns a plan dict consumed by mode_preview / mode_copy.
    """
    file_id = stub["id"]
    try:
        invoice = parse_invoice(io.BytesIO(pdf_bytes))
    except Exception as e:
        return {
            "file_id": file_id, "outcome": "PARSE_ERROR", "detail": str(e),
            "order_number": None, "invoice_number": None, "order_id": None,
        }

    order_number   = invoice.order_number
    invoice_number = invoice.invoice_number
    order_date_iso = _parse_order_date(invoice.order_date)

    # Duplicate within this backlog scan — keyed on invoice number, not order
    # number, per the 2026-08-15 decision (a split shipment legitimately has
    # one order number but several invoice numbers).
    if invoice_number and invoice_number in seen_invoice_numbers:
        return {
            "file_id": file_id, "outcome": "DUPLICATE",
            "detail": f"invoice {invoice_number} already seen this run",
            "order_number": order_number, "invoice_number": invoice_number,
            "order_id": None,
        }

    order = match_order(order_number, client) if order_number else None

    if order:
        if already_filed_for_order(order["order_id"], client):
            return {
                "file_id": file_id, "outcome": "ALREADY_FILED",
                "detail": f"order {order_number} already has an invoice_files row",
                "order_number": order_number, "invoice_number": invoice_number,
                "order_id": order["order_id"],
            }
        retailer_key    = order["retailer"].upper().strip()
        retailer_folder = RETAILER_DRIVE_FOLDER.get(retailer_key, retailer_key.title())
        # Prefer the matched order's own order_date (Supabase, already ISO)
        # over the PDF's printed date — trust the matched record once one
        # exists, same precedent Agent 1B follows.
        order_date_str = order["order_date"] or order_date_iso
        if not order_date_str:
            return {
                "file_id": file_id, "outcome": "PARSE_ERROR",
                "detail": "matched order but no usable date",
                "order_number": order_number, "invoice_number": invoice_number,
                "order_id": order["order_id"],
            }
        next_shipment = count_shipments(order["order_id"], client) + 1
        filename = build_filename(
            order_number, retailer_key, order_date_str, shipment_num=next_shipment
        )
        folder_path = resolve_drive_folder_path(retailer_folder, order_date_str)
        return {
            "file_id": file_id, "outcome": "MATCHED",
            "order_number": order_number, "invoice_number": invoice_number,
            "order_id": order["order_id"], "retailer_key": retailer_key,
            "filename": filename, "folder_path": folder_path,
        }

    # Unmatched — no order number extracted, or extracted but no matching
    # order exists in Supabase yet. File to _unmatched/ using the personal
    # file's own Drive ID as the unique tag (mirrors Agent 1B's
    # {gmail_message_id}_{RETAILER}_{date}.pdf convention with no email
    # involved here).
    date_str = order_date_iso or (stub.get("createdTime") or "")[:10] or date.today().isoformat()
    filename = f"{file_id}_LEGO_{date_str}.pdf"
    folder_path = ["Invoices", "Lego", "_unmatched"]
    return {
        "file_id": file_id, "outcome": "UNMATCHED",
        "order_number": order_number, "invoice_number": invoice_number,
        "order_id": None, "retailer_key": "LEGO",
        "filename": filename, "folder_path": folder_path,
    }


# --------------------------------------------------------------------------- #
# Preview scan — read-only, no writes of any kind
# --------------------------------------------------------------------------- #

def _scan_preview(drive_personal, client) -> list[dict]:
    """
    Walk every candidate personal-Drive PDF not yet in the ledger and
    evaluate it. Downloads and parses each PDF (needed to categorize it) but
    performs no writes anywhere — not to personal Drive, business Drive, or
    the invoice_files ledger. Mode 2 (Copy) has its own loop (_run_copy)
    that additionally executes the plan; kept separate rather than sharing
    this function with an execute flag so a Preview run can never
    accidentally write.
    """
    try:
        stubs = list_personal_pdfs(drive_personal)
    except HttpError as e:
        print(f"  ERROR listing personal Drive: {e}")
        if e.resp is not None and e.resp.status in (401, 403):
            _print_scope_fix()
        sys.exit(1)

    print(f"\n  {len(stubs)} candidate PDF(s) found in personal Drive.\n")

    plans: list[dict] = []
    seen_invoice_numbers: set = set()
    skipped_already = 0

    for i, stub in enumerate(stubs, 1):
        file_id = stub["id"]
        if already_evaluated(file_id, client):
            skipped_already += 1
            continue

        try:
            pdf_bytes = download_pdf_bytes(drive_personal, file_id)
        except HttpError as e:
            print(f"  {i:>4}. ERROR downloading {stub.get('name', file_id)}: {e}")
            if e.resp is not None and e.resp.status in (401, 403):
                _print_scope_fix()
                sys.exit(1)
            continue

        plan = evaluate_file(stub, pdf_bytes, client, seen_invoice_numbers)
        if plan.get("invoice_number"):
            seen_invoice_numbers.add(plan["invoice_number"])

        outcome = plan["outcome"]
        if outcome == "MATCHED":
            label = f"FILE    order {plan['order_number']} -> {plan['filename']}"
        elif outcome == "UNMATCHED":
            label = f"UNMATCH {stub.get('name', '')[:40]} -> _unmatched/{plan['filename']}"
        elif outcome == "DUPLICATE":
            label = f"DUP     {plan['detail']}"
        elif outcome == "ALREADY_FILED":
            label = f"SKIP    {plan['detail']}"
        else:
            label = f"ERROR   {plan.get('detail', 'parse failed')}"
        print(f"  {i:>4}. {label}")
        plans.append(plan)

    print()
    print("-" * 70)
    matched   = sum(1 for p in plans if p["outcome"] == "MATCHED")
    unmatched = sum(1 for p in plans if p["outcome"] == "UNMATCHED")
    dup       = sum(1 for p in plans if p["outcome"] == "DUPLICATE")
    already   = sum(1 for p in plans if p["outcome"] == "ALREADY_FILED")
    errors    = sum(1 for p in plans if p["outcome"] == "PARSE_ERROR")
    print(
        f"  This run: {len(plans)} evaluated | {matched} matched | "
        f"{unmatched} unmatched | {dup} duplicate | {already} already-filed | "
        f"{errors} parse errors"
    )
    print(f"  Skipped (already in ledger from a prior run): {skipped_already}")
    return plans


def _apply(plan: dict, drive_business, client) -> None:
    """Execute one plan: copy to business Drive (MATCHED/UNMATCHED only) and
    always write a ledger row so re-runs skip this personal file forever."""
    outcome = plan["outcome"]
    new_drive_id = None

    if outcome in ("MATCHED", "UNMATCHED"):
        try:
            with_bytes = plan.get("_pdf_bytes")
            folder_id = resolve_folder_id(drive_business, plan["folder_path"])
            new_drive_id = upload_pdf(
                drive_business, with_bytes, plan["filename"], folder_id
            )
        except Exception as e:
            print(f"        ERROR copying to business Drive: {e}")
            return

    filed_filename = plan.get("filename")
    if outcome == "DUPLICATE":
        filed_filename = f"SKIPPED (duplicate of invoice {plan['invoice_number']})"
    elif outcome == "ALREADY_FILED":
        filed_filename = f"SKIPPED (order {plan['order_number']} already filed)"
    elif outcome == "PARSE_ERROR":
        filed_filename = f"SKIPPED (parse error: {plan.get('detail', '')[:100]})"

    record_filing(
        ledger_key(plan["file_id"]),
        new_drive_id,
        plan.get("order_id"),
        "LEGO",
        filed_filename,
        client,
    )


# --------------------------------------------------------------------------- #
# Mode 1 — Preview
# --------------------------------------------------------------------------- #

def mode_preview(drive_personal, client) -> None:
    print("\n" + "=" * 70)
    print("  PERSONAL -> BUSINESS DRIVE BACKFILL — PREVIEW")
    print("  LEGO only | no writes to personal or business Drive")
    print("=" * 70)
    _scan_preview(drive_personal, client)
    print("\n  No writes performed. Run Mode 2 to copy matched/unmatched files")
    print("  into business Drive.")


# --------------------------------------------------------------------------- #
# Mode 2 — Copy
# --------------------------------------------------------------------------- #

def mode_copy(drive_personal, drive_business, client) -> None:
    print("\n" + "=" * 70)
    print("  PERSONAL -> BUSINESS DRIVE BACKFILL — COPY")
    print("=" * 70)
    print()
    print("  Copies matched/unmatched PDFs into business Drive. Duplicate and")
    print("  already-filed personal files are logged and skipped, not copied.")
    print("  Personal Drive is never modified, moved from, or deleted from.")
    print()

    if not get_yes_no("Proceed with copy?", default="n"):
        print("  Cancelled.")
        return

    _run_copy(drive_personal, drive_business, client)


def _run_copy(drive_personal, drive_business, client) -> None:
    try:
        stubs = list_personal_pdfs(drive_personal)
    except HttpError as e:
        print(f"  ERROR listing personal Drive: {e}")
        if e.resp is not None and e.resp.status in (401, 403):
            _print_scope_fix()
        sys.exit(1)

    print(f"\n  {len(stubs)} candidate PDF(s) found in personal Drive.\n")

    seen_invoice_numbers: set = set()
    skipped_already = 0
    counts = {"MATCHED": 0, "UNMATCHED": 0, "DUPLICATE": 0, "ALREADY_FILED": 0, "PARSE_ERROR": 0}
    failed_copies = 0

    for i, stub in enumerate(stubs, 1):
        file_id = stub["id"]
        if already_evaluated(file_id, client):
            skipped_already += 1
            continue

        try:
            pdf_bytes = download_pdf_bytes(drive_personal, file_id)
        except HttpError as e:
            print(f"  {i:>4}. ERROR downloading {stub.get('name', file_id)}: {e}")
            if e.resp is not None and e.resp.status in (401, 403):
                _print_scope_fix()
                sys.exit(1)
            continue

        plan = evaluate_file(stub, pdf_bytes, client, seen_invoice_numbers)
        if plan.get("invoice_number"):
            seen_invoice_numbers.add(plan["invoice_number"])
        plan["_pdf_bytes"] = pdf_bytes
        counts[plan["outcome"]] = counts.get(plan["outcome"], 0) + 1

        outcome = plan["outcome"]
        if outcome == "MATCHED":
            print(f"  {i:>4}. FILE    order {plan['order_number']} -> {plan['filename']}")
        elif outcome == "UNMATCHED":
            print(f"  {i:>4}. UNMATCH {stub.get('name', '')[:40]} -> _unmatched/{plan['filename']}")
        elif outcome == "DUPLICATE":
            print(f"  {i:>4}. DUP     {plan['detail']}")
        elif outcome == "ALREADY_FILED":
            print(f"  {i:>4}. SKIP    {plan['detail']}")
        else:
            print(f"  {i:>4}. ERROR   {plan.get('detail', 'parse failed')}")

        try:
            _apply(plan, drive_business, client)
        except Exception as e:
            print(f"        ERROR filing: {e}")
            failed_copies += 1

    print()
    print("-" * 70)
    print(
        f"  Summary: {counts['MATCHED']} filed | {counts['UNMATCHED']} filed to "
        f"_unmatched | {counts['DUPLICATE']} duplicate (skipped) | "
        f"{counts['ALREADY_FILED']} already-filed (skipped) | "
        f"{counts['PARSE_ERROR']} parse errors | {failed_copies} copy failures"
    )
    print(f"  Skipped entirely (already in ledger from a prior run): {skipped_already}")
    if counts["MATCHED"] or counts["UNMATCHED"]:
        print("\n  Run Mode 3 (Ledger) to verify what landed in business Drive.")
    print("\n  Personal Drive was not modified. Safe to re-run at any time —")
    print("  already-evaluated files are skipped automatically.")


# --------------------------------------------------------------------------- #
# Mode 3 — Ledger
# --------------------------------------------------------------------------- #

def mode_ledger(client) -> None:
    print("\n" + "=" * 70)
    print("  DRIVE BACKFILL LEDGER (rows written by this agent)")
    print("=" * 70)

    result = (
        client.table("invoice_files")
        .select("gmail_message_id, drive_file_id, order_id, filed_filename, filed_at")
        .eq("user_id", PHASE_1_USER_ID)
        .like("gmail_message_id", f"{LEDGER_KEY_PREFIX}%")
        .order("filed_at", desc=True)
        .execute()
    )
    rows = result.data or []
    if not rows:
        print("\n  No rows yet — Mode 2 (Copy) hasn't been run.")
        return

    filed  = sum(1 for r in rows if r["drive_file_id"])
    skipped = len(rows) - filed
    print(f"\n  {len(rows)} row(s) total — {filed} filed, {skipped} skipped.\n")
    for r in rows[:30]:
        tag = "FILED " if r["drive_file_id"] else "SKIP  "
        print(f"  {tag} {r['filed_filename']}")
    if len(rows) > 30:
        print(f"  ... and {len(rows) - 30} more.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("\n" + "=" * 70)
    print("  RESELLOS — AGENT 01D: PERSONAL -> BUSINESS DRIVE BACKFILL")
    print("  LEGO only | one-time / safe to re-run | personal Drive is read-only")
    print("=" * 70)
    print()
    print("  1. Preview — scan + evaluate, no writes")
    print("  2. Copy    — file matched/unmatched PDFs into business Drive")
    print("  3. Ledger  — show what this agent has filed so far")
    print()

    mode = get_input("Select mode (1/2/3)").strip()
    if mode not in ("1", "2", "3"):
        print(f"  Unknown mode '{mode}'. Enter 1, 2, or 3.")
        return

    if mode == "3":
        mode_ledger(get_client())
        return

    print("\n  Connecting to personal Drive...")
    try:
        drive_personal = build_personal_drive()
        print("  Connected.")
    except SystemExit:
        raise
    except Exception as e:
        print(f"  ERROR connecting to personal Drive: {e}")
        return

    client = get_client()

    if mode == "1":
        mode_preview(drive_personal, client)
        return

    print("  Connecting to business Drive...")
    try:
        _, drive_business = build_business_services()
        print("  Connected.\n")
    except SystemExit:
        raise
    except Exception as e:
        print(f"  ERROR connecting to business Drive: {e}")
        return

    mode_copy(drive_personal, drive_business, client)


if __name__ == "__main__":
    main()
