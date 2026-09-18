"""
ResellOS - One-off: exclude 18 permanently-non-order backlog files
====================================================================
2026-09-19 investigation (Cowork session) of Agent 01E's
Invoices/Lego/_unmatched/ backlog found 18 invoice_files rows that will
NEVER resolve into a real order match: 8 are pure noise (Home Depot
receipts, a donation receipt, LEGO Insiders points-history screenshots)
and 10 are real purchases already tracked separately in Brickprobe (2
Walmart.com orders, 2 Fred Meyer orders, 1 in-store LEGO purchase, 2
duplicate-filed Walmart receipts, 2 LEGO gift-card purchases).

REQUIRES migrations/022_invoice_files_excluded_reason.sql to already be
applied to the live database -- this script cannot apply that migration
itself (no DDL access from this environment; apply it via Supabase MCP in
a Cowork/chat-Claude session, or the Supabase dashboard's SQL editor,
first). Running this before that migration exists will fail outright with
a "column does not exist" error from Supabase -- that failure is expected
and is not a bug in this script.

Does NOT touch the underlying Drive files -- only stamps
invoice_files.excluded_reason so agents/agent_01e_pdf_order_backfill.py's
fetch_backlog_rows() stops re-fetching them. Reversible: clear the column
by hand (UPDATE invoice_files SET excluded_reason = NULL WHERE ...) if a
file is ever found to have been excluded wrongly.

Usage: python exclude_non_order_backlog_files_2026_09.py [--dry-run]
"""

import sys

from db_client import get_client, PHASE_1_USER_ID

RETAILER = "LEGO"

# reason -> [filed_filename, ...]
EXCLUSIONS: dict[str, list[str]] = {
    "not_an_order": [
        "1NLJpV-VvVoYvgONMMysQjLOYi9Tfr5Px_LEGO_2026-05-02.pdf",
        "1IwSuhOuLS234VkkrGqvF3BG1yAHH1skN_LEGO_2026-02-11.pdf",
        "1bTStoMiyy-E0baEnFpnN4xGHlaj7QJIK_LEGO_2026-02-24.pdf",
        "1jw4pxcG3iHKhWf8wWbXwBYDIopT_AGDE_LEGO_2025-11-11.pdf",
        "1rjS75rKGv-KPJ80azS4rnwYngR_mb27x_LEGO_2025-11-05.pdf",
        "1dCmxCeBeQldJ5mcuYETwpTjVbUz-YeFn_LEGO_2025-04-13.pdf",
        "1Tm7Sx136qdiDkxUbri7PdN6vHEUcUUv7_LEGO_2025-04-13.pdf",
        "128SLywqhX9OCGKIhwB_9tQUYXWKPDtsU_LEGO_2025-04-13.pdf",
    ],
    "other_retailer_tracked_in_brickprobe": [
        "1bQ0E2X3bGbRMQ3YVoDqLwoELBkxfnKQW_LEGO_2026-07-30.pdf",
        "1JPYORSvnfvpMs2A4omP3ahqXPNL5ckYH_LEGO_2026-07-30.pdf",
        "1tYeng4cRae5HzYSxZ9XueciDxWNOxL5o_LEGO_2026-01-31.pdf",
        "1TRCx9W2ldXR-m8hb4gW3yUMMzwA9g8Gb_LEGO_2025-10-04.pdf",
        "1LCd8B1hR0v2mcH3Mn0a8vFtWHAMD71JO_LEGO_2025-10-04.pdf",
        "1G5Wo0gQK-Q8OlYURiKz4vKtEUEb254-a_LEGO_2025-10-03.pdf",
        "1iu4wqSMfrOo9DVcdCzi2Gd7___bmfEpB_LEGO_2025-07-29.pdf",
        "1JZxZSX4M07sKUQfQhziM4VJdjt-mLYOx_LEGO_2025-07-29.pdf",
    ],
    "gift_card_purchase": [
        "1kZTA6LHY4YTtcaxX8UuKt-tM1ofu0_tZ_LEGO_2026-03-27.pdf",
        "1rXDcVaXt_k0_jeY6gncMEjXcNGuDBU0x_LEGO_2026-01-24.pdf",
    ],
}


def main():
    dry_run = "--dry-run" in sys.argv
    client = get_client()

    total_expected = sum(len(v) for v in EXCLUSIONS.values())
    print(f"\n  {total_expected} file(s) to exclude, across {len(EXCLUSIONS)} reason(s).")
    if dry_run:
        print("  --dry-run: no writes will be made.\n")

    total_updated = 0
    for reason, filenames in EXCLUSIONS.items():
        for filename in filenames:
            existing = (
                client.table("invoice_files")
                .select("id, excluded_reason")
                .eq("user_id", PHASE_1_USER_ID)
                .eq("retailer", RETAILER)
                .eq("filed_filename", filename)
                .execute()
            )
            if not existing.data:
                print(f"  NOT FOUND: {filename} -- skipped, check filed_filename spelling.")
                continue
            row = existing.data[0]
            if row.get("excluded_reason"):
                print(f"  ALREADY EXCLUDED ({row['excluded_reason']}): {filename} -- skipped.")
                continue

            if dry_run:
                print(f"  WOULD EXCLUDE [{reason}]: {filename}")
            else:
                client.table("invoice_files").update(
                    {"excluded_reason": reason}
                ).eq("id", row["id"]).execute()
                print(f"  EXCLUDED [{reason}]: {filename}")
            total_updated += 1

    print(f"\n  {'Would update' if dry_run else 'Updated'}: {total_updated} of {total_expected}.")


if __name__ == "__main__":
    main()
