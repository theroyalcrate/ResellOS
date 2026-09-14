"""
ResellOS - Agent 11: Gift Card Bulk Import
===========================================
ADR-030: reads one of Josh's sanitized "LGC"-style gift card ledgers
(last4 + face value, no purchase economics) and stages each card into
gift_card_import_queue for review, instead of writing straight into the
`gift_cards` wallet. Mirrors the two-step pattern already used for LEGO
orders (ADR-023 capture_queue -> ADR-028 review app -> orders): a bulk,
mostly-mechanical ingest step, then a human confirmation step before
anything lands in a table that feeds cost basis.

Why not write straight to `gift_cards`? Its purchase_price and
purchase_date columns are NOT NULL by design (ADR-027 -- a card's cost is
load-bearing for cost basis). These source ledgers only ever carry last4
and face value; purchase price, date, and source platform have to come
from Josh, confirmed in gift_card_import_review_app.py (streamlit run
gift_card_import_review_app.py), not guessed here.

What this script does NOT do:
  - Does not parse or trust "remaining balance" columns. The source
    spreadsheets seen so far (the LEGO "lgc_2026" ledger) have inconsistent
    column alignment in that area -- header says one column, data lands in
    another a few cells over. Rather than silently misread it, this script
    only extracts the two fields that were consistently unambiguous across
    every row checked: card last4, and face value. Everything else in the
    row (order numbers, spent amounts, whatever else is present) is kept
    verbatim in `source_linkage` for Josh's own reference during review --
    never parsed into a schema, since no order<->gift-card linkage table
    exists yet (see ADR-030 Open Questions).
  - Does not dedupe fuzzy/partial matches -- only an exact
    (retailer, card_number_last4) match already present in `gift_cards`,
    or already queued from a previous run of the same source_batch tag,
    is skipped. A last4 that recurs across different physical cards over
    time is a known real possibility (ADR-027 doesn't treat last4 as
    globally unique either) -- this script surfaces repeats, it doesn't
    silently collapse them.

Usage:
    python agents/agent_11_gift_card_bulk_import.py <path_to_xlsx> --retailer LEGO [--sheet Sheet1] [--batch-tag lgc_2026]
"""

import argparse
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root, for db_client
from db_client import get_client, PHASE_1_USER_ID


# Face values seen in real ledgers so far are always a plain number in one
# of the row's first several cells. Rather than hardcode a fixed column
# index (fragile against a slightly different export), scan the row for the
# first cell that looks like a face value: a positive number under $1000
# (LEGO gift cards top out at $250 in practice) and NOT the card field
# itself.
_MAX_PLAUSIBLE_FACE_VALUE = 1000


def _extract_last4(cell_value) -> str | None:
    """Card cell looks like '****9832' or a bare '9832'. Returns just the
    last 4 digits, or None if this cell isn't a card identifier at all."""
    if not cell_value or not isinstance(cell_value, str):
        return None
    digits = "".join(ch for ch in cell_value if ch.isdigit())
    if len(digits) < 4:
        return None
    return digits[-4:]


def _extract_face_value(row) -> float | None:
    for cell in row:
        if isinstance(cell, (int, float)) and 0 < cell <= _MAX_PLAUSIBLE_FACE_VALUE:
            return float(cell)
    return None


def _row_linkage(row) -> dict:
    """Keep the raw row (minus the card/face-value cells already extracted
    into their own columns) as reference context for the reviewer -- order
    numbers, spent amounts, whatever else is present, in whatever shape the
    source sheet actually has it. Not parsed, not trusted, just preserved."""
    return {"raw_row": [c.isoformat() if hasattr(c, "isoformat") else c for c in row]}


def parse_ledger(path: str, sheet_name: str | None = None) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb[wb.sheetnames[0]]

    cards = []
    for row in ws.iter_rows(min_row=2, values_only=True):  # row 1 assumed header
        last4 = None
        for cell in row:
            last4 = _extract_last4(cell)
            if last4:
                break
        if not last4:
            continue
        face_value = _extract_face_value(row)
        if face_value is None:
            print(f"  ! Skipping card ...{last4} -- no plausible face value found in its row.")
            continue
        cards.append({
            "card_number_last4": last4,
            "face_value": face_value,
            "source_linkage": _row_linkage(row),
        })
    return cards


def dedupe_against_existing(client, retailer: str, cards: list[dict], batch_tag: str) -> tuple[list[dict], list[dict]]:
    """Split cards into (new, already_known). "Already known" means either
    already sitting in gift_cards for this retailer, or already queued
    (any status) under this exact batch_tag -- so re-running the same file
    twice is safe and doesn't double-queue."""
    last4s = [c["card_number_last4"] for c in cards]

    existing_wallet = (
        client.table("gift_cards")
        .select("card_number_last4")
        .eq("user_id", PHASE_1_USER_ID)
        .ilike("retailer", retailer)
        .in_("card_number_last4", last4s)
        .execute()
    ).data or []
    wallet_last4s = {r["card_number_last4"] for r in existing_wallet}

    existing_queue = (
        client.table("gift_card_import_queue")
        .select("card_number_last4")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("source_batch", batch_tag)
        .in_("card_number_last4", last4s)
        .execute()
    ).data or []
    queued_last4s = {r["card_number_last4"] for r in existing_queue}

    known = wallet_last4s | queued_last4s
    new_cards = [c for c in cards if c["card_number_last4"] not in known]
    skipped_cards = [c for c in cards if c["card_number_last4"] in known]
    return new_cards, skipped_cards


def queue_cards(client, retailer: str, cards: list[dict], batch_tag: str) -> int:
    if not cards:
        return 0
    rows = [
        {
            "user_id": PHASE_1_USER_ID,
            "retailer": retailer,
            "card_number_last4": c["card_number_last4"],
            "face_value": c["face_value"],
            "source_linkage": c["source_linkage"],
            "source_batch": batch_tag,
            "status": "pending",
        }
        for c in cards
    ]
    client.table("gift_card_import_queue").insert(rows).execute()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Bulk-import a gift card ledger into the review queue (ADR-030).")
    parser.add_argument("path", help="Path to the .xlsx ledger file")
    parser.add_argument("--retailer", required=True, help="Retailer these cards are for (e.g. LEGO, Barnes, Kohls)")
    parser.add_argument("--sheet", default=None, help="Sheet name (defaults to the first sheet)")
    parser.add_argument("--batch-tag", default=None, help="Tag for this import batch (defaults to '<filename>_<retailer>')")
    args = parser.parse_args()

    batch_tag = args.batch_tag or f"{Path(args.path).stem}_{args.retailer.lower()}"

    print(f"\n  Reading {args.path} ...")
    cards = parse_ledger(args.path, args.sheet)
    print(f"  Found {len(cards)} card row(s) with a readable last4 + face value.")

    dupes_within_file = {}
    seen = set()
    for c in cards:
        if c["card_number_last4"] in seen:
            dupes_within_file[c["card_number_last4"]] = dupes_within_file.get(c["card_number_last4"], 1) + 1
        seen.add(c["card_number_last4"])
    if dupes_within_file:
        print(f"  ! {len(dupes_within_file)} last4 value(s) appear more than once in this file: "
              f"{list(dupes_within_file.keys())} -- queuing all occurrences; sort out in the review app.")

    client = get_client()
    new_cards, skipped_cards = dedupe_against_existing(client, args.retailer, cards, batch_tag)
    print(f"  {len(skipped_cards)} already in the wallet or already queued under this batch tag -- skipped.")
    print(f"  {len(new_cards)} new card(s) to queue.")

    if not new_cards:
        print("  Nothing to do.")
        return

    n = queue_cards(client, args.retailer, new_cards, batch_tag)
    print(f"\n  OK: queued {n} card(s) under batch '{batch_tag}'.")
    print("  Run `streamlit run gift_card_import_review_app.py` to confirm purchase details and add them to the wallet.\n")


if __name__ == "__main__":
    main()
