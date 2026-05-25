"""
ResellOS - Agent 05: Gift Card Ledger
========================================
Manages the gift card inventory.

Modes:
  1 - Single entry  : add one card, confirm, write
  2 - Bulk entry    : add multiple cards of the same retailer back to back
  3 - View ledger   : all cards grouped by retailer with balance and status

Usage: python agent_05_gift_cards.py
"""

from datetime import date
from db_client import get_client, PHASE_1_USER_ID

RETAILERS = ["LEGO", "Walmart", "Kohls", "Barnes", "Macys"]


# ------------------------------------------------------------------ #
# Input helpers (same pattern as agent_02_order_entry.py)
# ------------------------------------------------------------------ #

def get_input(prompt, required=True, default=None):
    display = f"{prompt} [{default}]: " if default else f"{prompt}: "
    while True:
        value = input(display).strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return None
        print("  This field is required.")


def get_float(prompt, required=True, default=None):
    while True:
        raw = get_input(prompt, required, str(default) if default is not None else None)
        if raw is None:
            return None
        try:
            return float(raw.replace("$", "").replace(",", ""))
        except ValueError:
            print("  Please enter a valid number (e.g. 50.00)")


def get_yes_no(prompt, default="n"):
    while True:
        raw = get_input(f"{prompt} (y/n)", default=default).lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def pick_retailer():
    print()
    for i, r in enumerate(RETAILERS, 1):
        print(f"  {i}. {r}")
    while True:
        raw = get_input("Retailer (number or name)").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(RETAILERS):
                return RETAILERS[idx]
            print(f"  Enter a number between 1 and {len(RETAILERS)}.")
        elif raw.upper() in [r.upper() for r in RETAILERS]:
            return next(r for r in RETAILERS if r.upper() == raw.upper())
        else:
            return raw  # accept unlisted retailer


# ------------------------------------------------------------------ #
# Card data collection
# ------------------------------------------------------------------ #

def collect_card(retailer=None):
    """Prompt for one card's fields. Returns a dict ready for DB write."""
    if retailer is None:
        print("\n  -- RETAILER --")
        retailer = pick_retailer()

    face_value = get_float("Face value (e.g. 100.00)")
    price_paid = get_float("Price paid")
    discount_pct = ((face_value - price_paid) / face_value * 100) if face_value else 0
    print(f"  Discount: {discount_pct:.1f}%  (saved ${face_value - price_paid:.2f})")

    last_four = get_input("Last 4 digits of card number", required=False)
    purchase_date = get_input(
        "Purchase date (YYYY-MM-DD)", default=str(date.today())
    )
    notes = get_input("Notes (optional)", required=False)

    return {
        "user_id": PHASE_1_USER_ID,
        "retailer": retailer,
        "face_value": face_value,
        "purchase_price": price_paid,
        "discount_pct": round(discount_pct, 2),
        "purchase_date": purchase_date,
        "remaining_balance": face_value,
        "status": "available",
        "card_number_last4": last_four,
        "notes": notes,
        "_discount_pct": discount_pct,  # kept for print_card_summary display
    }


def print_card_summary(card, label="GIFT CARD SUMMARY"):
    print("\n" + "=" * 50)
    print(f"  {label}")
    print("=" * 50)
    print(f"  Retailer:      {card['retailer']}")
    print(f"  Face Value:    ${card['face_value']:.2f}")
    print(f"  Price Paid:    ${card['purchase_price']:.2f}")
    print(f"  Discount:      {card['_discount_pct']:.1f}%  "
          f"(saved ${card['face_value'] - card['purchase_price']:.2f})")
    print(f"  Last Four:     {card['card_number_last4'] or '----'}")
    print(f"  Purchase Date: {card['purchase_date']}")
    if card.get("notes"):
        print(f"  Notes:         {card['notes']}")
    print(f"  Balance:       ${card['remaining_balance']:.2f}  [{card['status']}]")
    print("=" * 50)


def write_card(card):
    """Write one gift card to the DB. Returns card_id or None."""
    client = get_client()
    row = {k: v for k, v in card.items() if not k.startswith("_")}
    result = client.table("gift_cards").insert(row).execute()
    if not result.data:
        print("  ERROR: insert returned no data.")
        return None
    return result.data[0]["card_id"]


# ------------------------------------------------------------------ #
# Mode 1 — single entry
# ------------------------------------------------------------------ #

def mode_single():
    print("\n" + "=" * 50)
    print("  ADD GIFT CARD")
    print("=" * 50)

    card = collect_card()
    print_card_summary(card)
    print()
    if not get_yes_no("Save to database?"):
        print("  Cancelled.")
        return

    card_id = write_card(card)
    if card_id:
        print(f"  OK: {card['retailer']} ${card['face_value']:.2f} card saved (id: {card_id})")


# ------------------------------------------------------------------ #
# Mode 2 — bulk entry (same retailer, loop)
# ------------------------------------------------------------------ #

def mode_bulk():
    print("\n" + "=" * 50)
    print("  BULK GIFT CARD ENTRY")
    print("=" * 50)
    print("\n  -- RETAILER (applies to all cards this session) --")
    retailer = pick_retailer()

    saved = 0
    card_num = 1
    while True:
        print(f"\n  -- Card {card_num} ({retailer}) --")
        card = collect_card(retailer=retailer)
        print_card_summary(card, label=f"CARD {card_num} SUMMARY")
        print()

        if get_yes_no("Save this card?"):
            card_id = write_card(card)
            if card_id:
                print(f"  OK: saved (id: {card_id})")
                saved += 1
        else:
            print("  Skipped.")

        card_num += 1
        if not get_yes_no(f"\nAdd another {retailer} card?", default="y"):
            break

    print(f"\n  Bulk entry complete: {saved} card(s) saved.")


# ------------------------------------------------------------------ #
# Mode 3 — view ledger
# ------------------------------------------------------------------ #

def mode_view():
    client = get_client()
    result = (
        client.table("gift_cards")
        .select(
            "card_id, retailer, face_value, purchase_price, discount_amount, "
            "remaining_balance, status, card_number_last4, purchase_date, notes"
        )
        .eq("user_id", PHASE_1_USER_ID)
        .order("retailer")
        .order("purchase_date")
        .execute()
    )

    cards = result.data
    if not cards:
        print("\n  No gift cards on record.")
        return

    # Group by retailer
    by_retailer: dict[str, list] = {}
    for c in cards:
        by_retailer.setdefault(c["retailer"], []).append(c)

    print("\n" + "=" * 74)
    print(f"  GIFT CARD LEDGER  ({len(cards)} card(s))")
    print("=" * 74)

    total_face = total_paid = total_remaining = 0.0

    for retailer, group in by_retailer.items():
        r_face = sum(c["face_value"] for c in group)
        r_remaining = sum(c["remaining_balance"] for c in group)
        print(f"\n  {retailer.upper()}  ({len(group)} card(s) | "
              f"${r_face:.2f} face | ${r_remaining:.2f} remaining)")
        print(f"  {'Last4':<6}  {'Face':>8}  {'Paid':>8}  {'Disc%':>6}  "
              f"{'Balance':>9}  {'Status':<10}  {'Date'}")
        print("  " + "-" * 68)
        for c in group:
            disc_pct = (c["discount_amount"] / c["face_value"] * 100) if c["face_value"] else 0
            last4 = c["card_number_last4"] or "----"
            print(
                f"  {last4:<6}  ${c['face_value']:>7.2f}  ${c['purchase_price']:>7.2f}  "
                f"{disc_pct:>5.1f}%  ${c['remaining_balance']:>8.2f}  "
                f"{c['status']:<10}  {c['purchase_date']}"
            )
        total_face += r_face
        total_paid += sum(c["purchase_price"] for c in group)
        total_remaining += r_remaining

    print("\n" + "=" * 74)
    total_saved = total_face - total_paid
    overall_disc = (total_saved / total_face * 100) if total_face else 0
    print(f"  TOTALS   Face: ${total_face:.2f}  Paid: ${total_paid:.2f}  "
          f"Saved: ${total_saved:.2f} ({overall_disc:.1f}%)  "
          f"Remaining: ${total_remaining:.2f}")
    print("=" * 74)


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main():
    print("\n" + "=" * 50)
    print("  RESELLOS -- GIFT CARD LEDGER")
    print("=" * 50)
    print()
    print("  1. Add a single gift card")
    print("  2. Bulk entry (multiple cards, same retailer)")
    print("  3. View ledger")
    print()

    while True:
        raw = get_input("Select mode (1/2/3)").strip()
        if raw == "1":
            mode_single()
            break
        if raw == "2":
            mode_bulk()
            break
        if raw == "3":
            mode_view()
            break
        print("  Please enter 1, 2, or 3.")


if __name__ == "__main__":
    main()
