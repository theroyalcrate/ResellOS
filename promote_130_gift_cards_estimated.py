"""
One-off: promote the 130 pending gift_card_import_queue rows (source_batch
'claude_lgc_2026_lego') using ADR-027 estimated defaults, per Josh's
2026-09-15 decision ("Use estimated defaults now").

Why this exists as a standalone script rather than clicking through
gift_card_import_review_app.py: a Zapier search of Josh's personal Gmail
(joshua.buckingham@gmail.com) confirmed no purchase-confirmation or
delivery email from either giftcards.com or krogergiftcards.com/GiftCardMall
exposes a card's last-4 digits -- only a redeem link. So there is no way,
per-card, to find the real purchase_date/purchase_price these 130 rows
need. Rather than leave them blocked or guess row-by-row in the UI, this
applies ADR-027's existing discount-default policy at the group level
(giftcards.com 10%, krogergiftcards.com 11.11%) plus a real median
purchase date pulled from the same email search, grouped by the only
signals the queue rows actually carry: face_value and the "Kroger 12.5%"
note already present in 17 rows' source_linkage.

Everything this writes is discount_confidence = 'estimated_default', not
'exact' -- honest labeling per ADR-027, correctable per-card later if the
real purchase is ever identified (e.g. via giftcards.com/GiftCardMall
account order history, which does show card numbers once logged in).

Run once: python promote_130_gift_cards_estimated.py
"""

from datetime import date, datetime, timezone

from db_client import get_client, PHASE_1_USER_ID

BATCH = "claude_lgc_2026_lego"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Each group: (matcher function, source_platform, discount_pct, purchase_date, label)
def group_a_match(row, note):
    return row["face_value"] == 225.0 and note == "Kroger 12.5%"


def group_b_match(row, note):
    return row["face_value"] == 225.0 and note != "Kroger 12.5%"


def group_c_match(row, note):
    return row["face_value"] == 250.0


def group_d_match(row, note):
    return row["face_value"] == 50.0


GROUPS = [
    {
        "name": "A: Kroger $225 face, 'Kroger 12.5%' note already on the row",
        "match": group_a_match,
        "source_platform": "krogergiftcards.com",
        "discount_pct": 12.5,
        "purchase_date": date(2026, 2, 12),
        "note_text": (
            "Promoted from gift_card_import_queue (batch '{batch}'). "
            "No purchase-confirmation email exposes this card's last-4, so the exact "
            "order/date/price couldn't be matched (Zapier search of personal Gmail, "
            "2026-09-15). Used the '12.5%' discount already recorded on this row's "
            "raw import data (source_linkage) rather than ADR-027's generic 11.11% "
            "krogergiftcards.com default, since it's a more specific figure for this "
            "batch. purchase_date is the median date (2026-02-12) across 47 matching "
            "Kroger 'buy $200 get $25 bonus LEGO' order confirmations found in that "
            "search (range 2025-09-11 to 2026-08-17) -- not this specific card's real "
            "purchase date. discount_confidence=estimated_default; correct manually "
            "if the real order is ever identified."
        ),
    },
    {
        "name": "B: Kroger $225 face, no note",
        "match": group_b_match,
        "source_platform": "krogergiftcards.com",
        "discount_pct": 11.11,
        "purchase_date": date(2026, 2, 12),
        "note_text": (
            "Promoted from gift_card_import_queue (batch '{batch}'). "
            "No purchase-confirmation email exposes this card's last-4, so the exact "
            "order/date/price couldn't be matched (Zapier search of personal Gmail, "
            "2026-09-15). Applied ADR-027's krogergiftcards.com default discount "
            "(11.11%), which also reconstructs the well-known 'pay $200, get $225 "
            "value' Kroger LEGO promo structure exactly. purchase_date is the median "
            "date (2026-02-12) across 47 matching Kroger order confirmations found in "
            "that search (range 2025-09-11 to 2026-08-17) -- not this specific card's "
            "real purchase date. discount_confidence=estimated_default; correct "
            "manually if the real order is ever identified."
        ),
    },
    {
        "name": "C: giftcards.com $250 face, no note",
        "match": group_c_match,
        "source_platform": "giftcards.com",
        "discount_pct": 10.0,
        "purchase_date": date(2026, 1, 15),
        "note_text": (
            "Promoted from gift_card_import_queue (batch '{batch}'). "
            "No purchase-confirmation email exposes this card's last-4, so the exact "
            "order/date/price couldn't be matched (Zapier search of personal Gmail, "
            "2026-09-15). Applied ADR-027's giftcards.com default discount (10%) -- "
            "note real giftcards.com orders in the same search ranged 0%-50% "
            "depending on the promo running that day, so this is a genuine estimate, "
            "not a verified rate. purchase_date is the median date (2026-01-15) "
            "across 268 matching $250-face LEGO eGift order-confirmation emails found "
            "in that search (range 2026-01-14 to 2026-09-03) -- not this specific "
            "card's real purchase date. discount_confidence=estimated_default; "
            "correct manually if the real order is ever identified."
        ),
    },
    {
        "name": "D: giftcards.com $50 face, no note",
        "match": group_d_match,
        "source_platform": "giftcards.com",
        "discount_pct": 10.0,
        "purchase_date": date(2026, 3, 14),
        "note_text": (
            "Promoted from gift_card_import_queue (batch '{batch}'). "
            "No purchase-confirmation email exposes this card's last-4, so the exact "
            "order/date/price couldn't be matched (Zapier search of personal Gmail, "
            "2026-09-15). Applied ADR-027's giftcards.com default discount (10%). "
            "purchase_date is the median date (2026-03-14) across 10 matching $50-face "
            "LEGO eGift order-confirmation emails found in that search (range "
            "2026-01-15 to 2026-03-14) -- not this specific card's real purchase "
            "date. discount_confidence=estimated_default; correct manually if the "
            "real order is ever identified."
        ),
    },
]


def main():
    client = get_client()

    rows = (
        client.table("gift_card_import_queue")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("status", "pending")
        .eq("source_batch", BATCH)
        .execute()
        .data
        or []
    )
    print(f"Loaded {len(rows)} pending rows in batch '{BATCH}'.")

    totals = {g["name"]: 0 for g in GROUPS}
    unmatched = []

    for row in rows:
        linkage = row.get("source_linkage") or {}
        raw_row = linkage.get("raw_row") or []
        note = raw_row[18] if len(raw_row) > 18 else None

        group = None
        for g in GROUPS:
            if g["match"](row, note):
                group = g
                break
        if group is None:
            unmatched.append(row)
            continue

        face_value = float(row["face_value"])
        purchase_price = round(face_value * (1 - group["discount_pct"] / 100.0), 2)
        recomputed_discount_pct = round((face_value - purchase_price) / face_value * 100, 2) if face_value else 0.0

        notes = group["note_text"].format(batch=BATCH)

        card = {
            # NOTE: discount_amount is a DB-generated column (discovered
            # this run -- gift_card_import_review_app.py's promote_row()
            # still tries to set it manually and would fail the same way
            # if anyone ran it; worth a one-line fix there too, flagged
            # separately, not touched by this one-off script).
            "user_id": PHASE_1_USER_ID,
            "retailer": row["retailer"],
            "face_value": face_value,
            "purchase_price": purchase_price,
            "discount_pct": recomputed_discount_pct,
            "purchase_date": group["purchase_date"].isoformat(),
            "remaining_balance": face_value,
            "status": "available",
            "card_number_last4": row["card_number_last4"],
            "source": group["source_platform"],
            "source_platform": group["source_platform"],
            "source_type": "gift_card_reseller",
            "discount_confidence": "estimated_default",
            "notes": notes,
        }
        result = client.table("gift_cards").insert(card).execute()
        if not result.data:
            print(f"  ERROR: insert failed for import_id={row['import_id']} last4={row['card_number_last4']}")
            continue
        new_card_id = result.data[0]["card_id"]

        client.table("gift_card_import_queue").update({
            "status": "promoted",
            "purchase_date": group["purchase_date"].isoformat(),
            "purchase_price": purchase_price,
            "discount_pct": recomputed_discount_pct,
            "source_platform": group["source_platform"],
            "notes": notes,
            "promoted_card_id": new_card_id,
            "reviewed_at": _now_iso(),
        }).eq("import_id", row["import_id"]).execute()

        totals[group["name"]] += 1

    print("\nDone. Promoted:")
    for name, n in totals.items():
        print(f"  {n:>3}  {name}")
    if unmatched:
        print(f"\n  {len(unmatched)} row(s) did not match any group -- left pending, needs a look:")
        for r in unmatched:
            print(f"    import_id={r['import_id']} last4={r['card_number_last4']} face_value={r['face_value']}")


if __name__ == "__main__":
    main()
