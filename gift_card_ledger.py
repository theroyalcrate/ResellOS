"""
ResellOS - Gift Card Ledger: Debit / Reversal (ADR-031)

Shared functions for atomically linking an order to a specific gift_cards
row, debiting its remaining_balance, and reversing that debit when an order
is reopened. This is the "gift card ledger atomic write" DECISION 017
specified on 2026-06-01 -- it never had an implementation until this build.

Called from two places:
  - agent_02_order_entry.write_order() -- when a brand-new order is written
    with order_status == "confirmed" and a gift card amount applied.
  - order_lifecycle.confirm_order() -- when a pending_review order (created
    via capture_queue_promotion, or reopened for editing) is confirmed.

Deliberately a leaf module (only imports db_client) so both of the above,
and anything else, can import it without a circular-import risk.

Scope (ADR-031, 2026-09-15): forward-only. This governs gift cards used on
orders written or confirmed from here on, and cards that already carry a
real active balance. No retroactive rebuild of the pre-2026-09 gift card
history. Assumes one card per order for v1 -- flagged as an open question
in the ADR if Josh ever splits a single order's payment across two cards.

Usage: not run standalone -- imported by agent_02_order_entry.py and
order_lifecycle.py.
"""

from datetime import date

from db_client import get_client, PHASE_1_USER_ID


def get_int(prompt, required=True, default=None):
    display = f"{prompt} [{default}]: " if default is not None else f"{prompt}: "
    while True:
        raw = input(display).strip()
        if not raw and default is not None:
            raw = str(default)
        if not raw and not required:
            return None
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a whole number.")


def get_yes_no(prompt, default="n"):
    hint = " [Y/n]" if default == "y" else " [y/N]"
    while True:
        raw = input(f"{prompt}{hint}: ").strip().lower()
        if not raw:
            return default == "y"
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def _load_active_cards(client):
    result = (
        client.table("gift_cards")
        .select("card_id, retailer, card_number_last4, remaining_balance, status")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("status", "active")
        .gt("remaining_balance", 0)
        .execute()
    )
    return result.data or []


def apply_gift_card_debit(order_id, retailer, amount, client=None, order_number=None):
    """
    Interactive: let Josh pick which specific gift card was used on this
    order, write a gift_card_assignments row (card_id, order_id,
    amount_applied, applied_date), and debit gift_cards.remaining_balance
    by the same amount. This is the atomic pair DECISION 017 describes --
    "order status confirmed + cost basis calculated, and gift card balance
    reduced by amount applied" -- for the gift card half of that pair.

    Never raises. A lookup or write failure prints a clear warning (naming
    the order and the amount that still needs a manual fix) and returns
    False rather than blocking whatever confirmed the order -- the order
    write itself has usually already succeeded by the time this runs, and
    should not be rolled back over a gift card bookkeeping problem.

    Returns True if a debit was applied, False if skipped or failed.
    """
    client = client if client is not None else get_client()
    amount = round(float(amount or 0), 2)
    if amount <= 0:
        return False

    label = order_number or order_id
    try:
        cards = _load_active_cards(client)
    except Exception as e:
        print(f"  WARNING: could not look up gift cards ({e}) -- balance NOT debited.")
        print(f"  Record manually: ${amount:.2f} was applied to order {label}.")
        return False

    matches = [
        c for c in cards
        if (c.get("retailer") or "").strip().lower() == (retailer or "").strip().lower()
    ]
    candidates = matches or cards
    if not candidates:
        print(f"\n  No active gift cards with a remaining balance found (retailer: {retailer}).")
        print(f"  ${amount:.2f} was applied to order {label} but not linked to any card.")
        print("  Add the card in agent_05_gift_cards.py first if it's missing from the ledger.")
        return False

    print(f"\n  -- WHICH GIFT CARD WAS USED? (${amount:.2f} applied to order {label}) --")
    if matches:
        print(f"  {retailer} cards with a balance:")
    else:
        print(f"  No {retailer} cards found with a balance -- showing all active cards:")
    for i, c in enumerate(candidates, 1):
        last4 = c.get("card_number_last4") or "????"
        print(f"  {i}. {c['retailer']}  ...{last4}   balance: ${float(c['remaining_balance']):.2f}")
    print("  0. Skip -- don't link a card (not recommended)")

    idx = get_int(f"  Card (0-{len(candidates)})", default="0")
    if not idx or idx <= 0 or idx > len(candidates):
        print(f"  Skipped -- ${amount:.2f} was applied to this order but no card was debited.")
        return False

    card = candidates[idx - 1]
    new_balance = round(float(card["remaining_balance"]) - amount, 2)
    if new_balance < 0:
        print(
            f"  WARNING: this takes the card below $0 "
            f"(balance ${float(card['remaining_balance']):.2f}, applying ${amount:.2f})."
        )
        if not get_yes_no("  Apply anyway?", default="n"):
            print("  Skipped -- no card debited.")
            return False

    try:
        assign_row = {
            "user_id":       PHASE_1_USER_ID,
            "card_id":       card["card_id"],
            "order_id":      order_id,
            "amount_applied": amount,
            "applied_date":  str(date.today()),
        }
        assign_result = client.table("gift_card_assignments").insert(assign_row).execute()
        if not assign_result.data:
            print("  ERROR: failed to write gift_card_assignments row -- balance NOT debited.")
            return False

        bal_result = (
            client.table("gift_cards")
            .update({"remaining_balance": new_balance})
            .eq("card_id", card["card_id"])
            .execute()
        )
        if not bal_result.data:
            print("  ERROR: assignment was written but the balance update failed.")
            print(f"  MANUAL FIX NEEDED: debit ${amount:.2f} from gift_cards.card_id={card['card_id']}.")
            return False
    except Exception as e:
        print(f"  ERROR applying gift card debit: {e}")
        print(f"  MANUAL FIX NEEDED: order {label}, ${amount:.2f}, card ...{card.get('card_number_last4')}.")
        return False

    print(
        f"  OK: ${amount:.2f} debited from {card['retailer']} card "
        f"...{card.get('card_number_last4') or '????'} (new balance: ${new_balance:.2f})"
    )
    return True


def reverse_gift_card_assignments(order_id, client=None):
    """
    Reverse every gift_card_assignments row for this order: credit the
    amount back to gift_cards.remaining_balance and delete the assignment
    row. Looked up by order_id, per DECISION 017 ("gift card ledger stores
    order_id on every debit so reversals are unambiguous").

    Never raises -- prints a warning and continues so a reopen can still
    proceed even if one assignment fails to reverse cleanly (the warning
    names exactly what needs a manual fix).

    Returns the list of assignment rows successfully reversed.
    """
    client = client if client is not None else get_client()
    try:
        result = (
            client.table("gift_card_assignments")
            .select("assignment_id, card_id, amount_applied")
            .eq("order_id", order_id)
            .execute()
        )
        assignments = result.data or []
    except Exception as e:
        print(f"  WARNING: could not look up gift card assignments ({e}) -- nothing reversed.")
        return []

    reversed_list = []
    for a in assignments:
        try:
            card_result = (
                client.table("gift_cards")
                .select("card_id, retailer, card_number_last4, remaining_balance")
                .eq("card_id", a["card_id"])
                .execute()
            )
            card_rows = card_result.data or []
            if not card_rows:
                print(
                    f"  WARNING: card {a['card_id']} no longer exists -- "
                    f"${float(a['amount_applied']):.2f} not credited back."
                )
                continue
            card = card_rows[0]
            new_balance = round(float(card["remaining_balance"]) + float(a["amount_applied"]), 2)
            client.table("gift_cards").update({"remaining_balance": new_balance}).eq(
                "card_id", card["card_id"]
            ).execute()
            client.table("gift_card_assignments").delete().eq(
                "assignment_id", a["assignment_id"]
            ).execute()
            print(
                f"  OK: credited ${float(a['amount_applied']):.2f} back to {card['retailer']} card "
                f"...{card.get('card_number_last4') or '????'} (new balance: ${new_balance:.2f})"
            )
            reversed_list.append(a)
        except Exception as e:
            print(f"  WARNING: failed to reverse assignment {a.get('assignment_id')}: {e}")
    return reversed_list


def compute_gift_card_savings(order_id, client=None):
    """
    ADR-031: sum this order's gift_card_assignments and, for each, apply
    the card's discount_pct (a whole-number percent, e.g. 10.00 == 10%,
    per the gift_cards table's real data) to get what that card's own
    purchase discount is worth to this order's cost basis (agent_08's
    Layer 2). Used to auto-fill Layer 2 instead of Josh re-typing a raw
    dollar figure on every cost basis run.

    Returns (total_savings, detail_lines). detail_lines is empty when no
    assignment exists yet -- an order written before ADR-031, or one where
    the card link was skipped -- so Layer 2 can fall back to asking Josh
    directly. Never raises; a lookup failure returns (0.0, []).
    """
    client = client if client is not None else get_client()
    try:
        result = (
            client.table("gift_card_assignments")
            .select("amount_applied, card_id")
            .eq("order_id", order_id)
            .execute()
        )
        assignments = result.data or []
    except Exception:
        return 0.0, []

    if not assignments:
        return 0.0, []

    total = 0.0
    detail = []
    for a in assignments:
        try:
            card_result = (
                client.table("gift_cards")
                .select("retailer, card_number_last4, discount_pct, discount_confidence")
                .eq("card_id", a["card_id"])
                .execute()
            )
            cards = card_result.data or []
        except Exception:
            continue
        if not cards:
            continue
        card = cards[0]
        pct = float(card.get("discount_pct") or 0)
        amount = float(a["amount_applied"])
        savings = round(amount * pct / 100.0, 2)
        total += savings
        confidence = card.get("discount_confidence") or "unknown"
        detail.append(
            f"${amount:.2f} on {card['retailer']} card ...{card.get('card_number_last4') or '????'} "
            f"x {pct:.2f}% discount ({confidence}) = ${savings:.2f}"
        )
    return round(total, 2), detail
