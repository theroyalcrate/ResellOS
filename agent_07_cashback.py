"""
ResellOS - Agent 07: Cashback Pool Manager
==========================================
Tracks portal cashback across 6 platforms: earn, receive, review.

Mode 1 — Record cashback earned on an order
Mode 2 — Record payout received
Mode 3 — Review cashback status

Platforms: Rakuten, RetailMeNot, Capital One Shopping,
           Microsoft Shopping, Honey, TopCashback, Other (write-in)

Usage: python agent_07_cashback.py
"""

import calendar
import re
from datetime import date

from db_client import get_client, PHASE_1_USER_ID

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

PLATFORMS = [
    "Rakuten",
    "RetailMeNot",
    "Capital One Shopping",
    "Microsoft Shopping",
    "Honey",
    "TopCashback",
    "Other",
]

RMN_DISPUTE_WINDOW      = 90  # days to dispute a RetailMeNot transaction
RMN_MERCHANT_MONTH_CAP  = 7   # RMN orders per merchant per month
RMN_TOTAL_MONTH_CAP     = 20  # RMN total online offers per month
STALE_FLAG_DAYS         = 60  # flag pending transactions older than this

# Default payout methods for known platforms; RMN prompts since it varies.
PAYOUT_METHODS = {
    "Rakuten":               "venmo",
    "Capital One Shopping":  "gift_card",
}

ONBOARDING = {
    "Rakuten": (
        "Rakuten pays quarterly via Venmo. Rate range 2.5-20%. "
        "Track manually after each order — no auto-sync with portal."
    ),
    "RetailMeNot": (
        "RetailMeNot pays via PayPal or Venmo. Same-day orders at the same "
        "retailer may be lumped together and capped at $50. "
        "90-day dispute window. Monthly limits: "
        f"{RMN_MERCHANT_MONTH_CAP} orders/merchant, {RMN_TOTAL_MONTH_CAP} total online offers."
    ),
    "Capital One Shopping": (
        "Capital One Shopping pays as gift cards only — not cash. "
        "Each payout creates a new gift card entry in your gift card ledger. "
        "Unredeemed gift card balance is tracked across all confirmed transactions."
    ),
    "Microsoft Shopping": (
        "Microsoft Shopping — basic tracking: rate, amount, status. No special payout rules."
    ),
    "Honey": (
        "Honey — basic tracking: rate, amount, status. Payouts vary by promotion type."
    ),
    "TopCashback": (
        "TopCashback — basic tracking: rate, amount, status. "
        "Typically pays via PayPal or check."
    ),
    "Other": "Custom platform — basic tracking: rate, amount, status. No special rules.",
}

VALID_STATUSES     = ("pending", "received", "confirmed", "ineligible", "written_off")
UPDATABLE_STATUSES = ("ineligible", "written_off", "confirmed")


# ------------------------------------------------------------------ #
# Input helpers
# ------------------------------------------------------------------ #

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


def get_float(prompt, required=True, default=None):
    while True:
        raw = get_input(prompt, required, str(default) if default is not None else None)
        if raw is None:
            return None
        try:
            return float(str(raw).replace("$", "").replace(",", ""))
        except ValueError:
            print("  Please enter a valid number (e.g. 10.5)")


def get_yes_no(prompt, default="n"):
    while True:
        raw = get_input(f"{prompt} (y/n)", default=default).lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


# ------------------------------------------------------------------ #
# Platform helpers
# ------------------------------------------------------------------ #

def pick_platform():
    print()
    for i, p in enumerate(PLATFORMS, 1):
        print(f"  {i}. {p}")
    while True:
        raw = get_input("Platform (number or name)").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(PLATFORMS):
                platform = PLATFORMS[idx]
                if platform == "Other":
                    return get_input("  Platform name (write-in)")
                return platform
            print(f"  Enter a number between 1 and {len(PLATFORMS)}.")
        else:
            match = next((p for p in PLATFORMS if p.lower() == raw.lower()), None)
            if match:
                if match == "Other":
                    return get_input("  Platform name (write-in)")
                return match
            return raw  # accept unlisted name directly


def show_onboarding_if_new(platform, client):
    """Show the platform onboarding blurb the first time, then never again."""
    try:
        seen = (
            client.table("user_platform_onboarding")
            .select("platform")
            .eq("user_id", PHASE_1_USER_ID)
            .eq("platform", platform)
            .execute()
        )
        if seen.data:
            return
        msg = ONBOARDING.get(platform)
        if msg:
            print()
            print(f"  *** {platform} — First Use ***")
            print(f"  {msg}")
        client.table("user_platform_onboarding").insert(
            {"user_id": PHASE_1_USER_ID, "platform": platform}
        ).execute()
    except Exception:
        pass  # table not yet migrated; skip silently


# ------------------------------------------------------------------ #
# Order lookup
# ------------------------------------------------------------------ #

def lookup_order(order_number, client):
    result = (
        client.table("orders")
        .select(
            "order_id, order_number, retailer, order_date, "
            "subtotal, discount_total, tax_paid"
        )
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .execute()
    )
    return result.data[0] if result.data else None


def calc_pretax_spend(order):
    """Post-discount pre-tax spend — the base cashback portals use."""
    return round(
        float(order["subtotal"]) - float(order.get("discount_total") or 0), 2
    )


# ------------------------------------------------------------------ #
# Quarter input
# ------------------------------------------------------------------ #

def get_quarter(prompt):
    today = date.today()
    q = (today.month - 1) // 3 + 1
    default = f"Q{q}-{today.year}"
    while True:
        raw = get_input(prompt, default=default)
        if re.match(r"^Q[1-4]-\d{4}$", raw):
            return raw
        print("  Format must be Q1-2026, Q2-2026, etc.")


# ------------------------------------------------------------------ #
# RetailMeNot checks
# ------------------------------------------------------------------ #

def _month_range(d_str):
    d = date.fromisoformat(d_str)
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=1).isoformat(), d.replace(day=last).isoformat()


def rmn_check_sameday(retailer, order_date, client):
    try:
        result = (
            client.table("cashback_transactions")
            .select("cb_id")
            .eq("user_id", PHASE_1_USER_ID)
            .eq("source", "RetailMeNot")
            .eq("retailer", retailer)
            .eq("transaction_date", order_date)
            .not_.in_("status", ["ineligible", "written_off"])
            .execute()
        )
        if result.data:
            print(
                f"\n  *** WARNING: A RetailMeNot cashback for {retailer} on "
                f"{order_date} already exists. Same-day same-retailer orders "
                f"may be lumped together and capped at $50. ***"
            )
    except Exception as e:
        print(f"  NOTE: Same-day RMN check skipped ({e}).")


def rmn_check_monthly_caps(retailer, order_date, client):
    try:
        ms, me = _month_range(order_date)
        result = (
            client.table("cashback_transactions")
            .select("cb_id, retailer")
            .eq("user_id", PHASE_1_USER_ID)
            .eq("source", "RetailMeNot")
            .gte("transaction_date", ms)
            .lte("transaction_date", me)
            .not_.in_("status", ["ineligible", "written_off"])
            .execute()
        )
        rows = result.data or []
        total = len(rows)
        merchant = sum(
            1 for r in rows
            if (r.get("retailer") or "").lower() == retailer.lower()
        )

        if total >= RMN_TOTAL_MONTH_CAP:
            print(
                f"\n  *** WARNING: Monthly RetailMeNot limit of "
                f"{RMN_TOTAL_MONTH_CAP} total offers reached "
                f"({total} recorded). This transaction may be ineligible. ***"
            )
        elif total >= RMN_TOTAL_MONTH_CAP - 2:
            print(
                f"\n  NOTE: {total}/{RMN_TOTAL_MONTH_CAP} RetailMeNot "
                f"offers used this month — approaching limit."
            )

        if merchant >= RMN_MERCHANT_MONTH_CAP:
            print(
                f"\n  *** WARNING: Monthly RetailMeNot limit of "
                f"{RMN_MERCHANT_MONTH_CAP} orders/merchant for {retailer} "
                f"reached ({merchant} recorded). May be ineligible. ***"
            )
        elif merchant >= RMN_MERCHANT_MONTH_CAP - 1:
            print(
                f"\n  NOTE: {merchant}/{RMN_MERCHANT_MONTH_CAP} RetailMeNot "
                f"orders for {retailer} this month — approaching merchant limit."
            )
    except Exception as e:
        print(f"  NOTE: RMN monthly cap check skipped ({e}).")


# ------------------------------------------------------------------ #
# Mode 1 — Record cashback earned
# ------------------------------------------------------------------ #

def mode_earn(client):
    print("\n" + "=" * 60)
    print("  RECORD CASHBACK EARNED")
    print("=" * 60)

    order_number = get_input("Order number")
    order = lookup_order(order_number, client)
    if not order:
        print(f"  No order found for '{order_number}'. Enter it with Agent 02 first.")
        return

    pretax_spend = calc_pretax_spend(order)
    print(f"\n  Order found:")
    print(f"    Retailer:     {order['retailer']}")
    print(f"    Date:         {order['order_date']}")
    print(f"    Pretax Spend: ${pretax_spend:.2f}")

    print("\n  Select cashback platform:")
    platform = pick_platform()
    show_onboarding_if_new(platform, client)

    if platform == "RetailMeNot":
        rmn_check_sameday(order["retailer"], order["order_date"], client)
        rmn_check_monthly_caps(order["retailer"], order["order_date"], client)
        print()

    rate = get_float(f"Cashback rate applied (%) for {platform}")
    expected = round(pretax_spend * rate / 100, 2)
    print(f"  Expected cashback: ${expected:.2f}  ({rate}% × ${pretax_spend:.2f})")

    quarter = get_quarter("Expected payout quarter")

    # Payout method
    payout_method = PAYOUT_METHODS.get(platform)
    if platform == "RetailMeNot":
        pm_raw = get_input("Payout method (paypal/venmo)", default="paypal")
        payout_method = pm_raw.lower()

    # Capital One: expected gift card retailer
    cap1_gc_retailer = None
    if platform == "Capital One Shopping":
        cap1_gc_retailer = get_input("Expected gift card retailer (e.g. Amazon)")

    notes = get_input("Notes (optional)", required=False)

    row = {
        "user_id":                   PHASE_1_USER_ID,
        "source":                    platform,
        "source_type":               "portal",
        "order_id":                  order["order_id"],
        "order_number":              order["order_number"],
        "retailer":                  order["retailer"],
        "pretax_spend":              pretax_spend,
        "cashback_amount":           expected,
        "cashback_percent":          rate,
        "transaction_date":          order["order_date"],
        "expected_payout_quarter":   quarter,
        "status":                    "pending",
        "notes":                     notes,
    }
    if payout_method:
        row["payout_method"] = payout_method
    if cap1_gc_retailer:
        row["cap1_gift_card_retailer"] = cap1_gc_retailer

    print("\n" + "=" * 60)
    print("  CASHBACK SUMMARY — REVIEW BEFORE SAVING")
    print("=" * 60)
    print(f"  Platform:        {platform}")
    print(f"  Order Number:    {order['order_number']}")
    print(f"  Retailer:        {order['retailer']}")
    print(f"  Order Date:      {order['order_date']}")
    print(f"  Pretax Spend:    ${pretax_spend:.2f}")
    print(f"  Rate:            {rate}%")
    print(f"  Expected:        ${expected:.2f}")
    print(f"  Payout Quarter:  {quarter}")
    if payout_method:
        print(f"  Payout Method:   {payout_method}")
    if cap1_gc_retailer:
        print(f"  Expected GC:     {cap1_gc_retailer}")
    print(f"  Status:          pending")
    if notes:
        print(f"  Notes:           {notes}")
    print("=" * 60)

    if not get_yes_no("Save to database?"):
        print("  Cancelled.")
        return

    result = client.table("cashback_transactions").insert(row).execute()
    if not result.data:
        print("  ERROR: Insert failed.")
        return
    print(f"\n  OK: Cashback recorded (cb_id: {result.data[0]['cb_id']})")


# ------------------------------------------------------------------ #
# Mode 2 — Record payout received
# ------------------------------------------------------------------ #

def mode_payout(client):
    print("\n" + "=" * 60)
    print("  RECORD PAYOUT RECEIVED")
    print("=" * 60)

    print("\n  Select platform for payout:")
    platform = pick_platform()

    result = (
        client.table("cashback_transactions")
        .select(
            "cb_id, order_number, retailer, cashback_amount, "
            "transaction_date, expected_payout_quarter, cap1_gift_card_retailer"
        )
        .eq("user_id", PHASE_1_USER_ID)
        .eq("source", platform)
        .eq("status", "pending")
        .order("transaction_date")
        .execute()
    )
    pending = result.data or []

    if not pending:
        print(f"\n  No pending cashback transactions for {platform}.")
        return

    today = date.today()
    print(f"\n  Pending {platform} transactions ({len(pending)}):")
    print(f"  {'#':<4} {'Order':<18} {'Retailer':<15} {'Expected':>9}  {'Quarter':<10}  Age")
    print("  " + "-" * 68)
    for i, tx in enumerate(pending, 1):
        age = (today - date.fromisoformat(tx["transaction_date"])).days
        print(
            f"  {i:<4} {(tx.get('order_number') or 'N/A'):<18} "
            f"{(tx.get('retailer') or 'N/A'):<15} "
            f"${float(tx['cashback_amount']):>8.2f}  "
            f"{(tx.get('expected_payout_quarter') or 'N/A'):<10}  {age}d"
        )

    print()
    raw_sel = get_input("Transactions covered by this payout (e.g. 1,3 or all)")
    if raw_sel.strip().lower() == "all":
        selected = pending
    else:
        try:
            indices = [int(x.strip()) - 1 for x in raw_sel.split(",")]
            selected = [pending[i] for i in indices if 0 <= i < len(pending)]
        except (ValueError, IndexError):
            print("  Invalid selection.")
            return

    if not selected:
        print("  No valid transactions selected.")
        return

    expected_total = round(sum(float(tx["cashback_amount"]) for tx in selected), 2)
    print(f"\n  {len(selected)} transaction(s) selected — expected total: ${expected_total:.2f}")

    # ---- Capital One Shopping: write gift card ----
    if platform == "Capital One Shopping":
        default_retailer = selected[0].get("cap1_gift_card_retailer") or None
        gc_retailer = get_input(
            "Gift card retailer",
            default=default_retailer,
        )
        last4       = get_input("Gift card last 4 digits", required=False)
        gc_face     = get_float("Gift card face value ($)", default=str(expected_total))
        disc_pct    = round((gc_face - expected_total) / gc_face * 100, 2) if gc_face else 0

        gc_row = {
            "user_id":           PHASE_1_USER_ID,
            "retailer":          gc_retailer,
            "face_value":        gc_face,
            "purchase_price":    expected_total,
            "discount_pct":      disc_pct,
            "purchase_date":     today.isoformat(),
            "remaining_balance": gc_face,
            "status":            "available",
            "card_number_last4": last4,
            "notes": (
                "Capital One Shopping cashback — "
                + ", ".join(tx.get("order_number") or "" for tx in selected)
            ),
        }

        print("\n" + "=" * 60)
        print("  PAYOUT SUMMARY — REVIEW BEFORE SAVING")
        print("=" * 60)
        print(f"  Platform:        {platform}")
        print(f"  Transactions:    {len(selected)}")
        print(f"  Cashback Total:  ${expected_total:.2f}")
        print(f"  GC Retailer:     {gc_retailer}")
        print(f"  GC Face Value:   ${gc_face:.2f}")
        print(f"  GC Last 4:       {last4 or '----'}")
        print(f"  Effective Disc:  {disc_pct:.1f}%")
        print("=" * 60)

        if not get_yes_no("Save payout and create gift card?"):
            print("  Cancelled.")
            return

        gc_result = client.table("gift_cards").insert(gc_row).execute()
        if not gc_result.data:
            print("  ERROR: Gift card insert failed. Nothing updated.")
            return
        gc_card_id = gc_result.data[0]["card_id"]
        print(f"  OK: Gift card created (card_id: {gc_card_id})")

        fail = False
        for tx in selected:
            upd = client.table("cashback_transactions").update({
                "status":                "received",
                "received_date":         today.isoformat(),
                "actual_amount_received": round(float(tx["cashback_amount"]), 2),
                "cap1_gift_card_last4":  last4,
            }).eq("cb_id", tx["cb_id"]).execute()
            if not upd.data:
                print(f"  ERROR: Could not update cb_id {tx['cb_id']}.")
                fail = True
        if fail:
            print("  Rolling back gift card insert...")
            client.table("gift_cards").delete().eq("card_id", gc_card_id).execute()
            print("  ROLLED BACK: Gift card removed. No transactions updated. Review and retry.")
        else:
            print(f"  OK: {len(selected)} transaction(s) marked received.")

    # ---- All other platforms ----
    else:
        actual_total  = get_float(
            f"Actual total received from {platform} ($)",
            default=str(expected_total),
        )
        payout_method = get_input(
            "Payout method used (e.g. venmo, paypal)", required=False
        )
        variance      = round(expected_total - actual_total, 2)
        v_sign        = "+" if variance > 0 else ("-" if variance < 0 else "")

        print("\n" + "=" * 60)
        print("  PAYOUT SUMMARY — REVIEW BEFORE SAVING")
        print("=" * 60)
        print(f"  Platform:        {platform}")
        print(f"  Transactions:    {len(selected)}")
        print(f"  Expected Total:  ${expected_total:.2f}")
        print(f"  Actual Received: ${actual_total:.2f}")
        print(f"  Variance:        {v_sign}${abs(variance):.2f}")
        if payout_method:
            print(f"  Payout Method:   {payout_method}")
        print("=" * 60)

        if not get_yes_no("Save payout?"):
            print("  Cancelled.")
            return

        # Distribute actual proportionally; assign remainder to last to absorb rounding.
        fail = False
        distributed = 0.0
        for idx, tx in enumerate(selected):
            if expected_total > 0 and idx < len(selected) - 1:
                tx_actual = round(float(tx["cashback_amount"]) / expected_total * actual_total, 2)
            else:
                tx_actual = round(actual_total - distributed, 2)
            distributed += tx_actual

            upd_fields = {
                "status":                "received",
                "received_date":         today.isoformat(),
                "actual_amount_received": tx_actual,
            }
            if payout_method:
                upd_fields["payout_method"] = payout_method
            upd = (
                client.table("cashback_transactions")
                .update(upd_fields)
                .eq("cb_id", tx["cb_id"])
                .execute()
            )
            if not upd.data:
                print(f"  ERROR: Could not update cb_id {tx['cb_id']}.")
                fail = True

        if fail:
            print("  WARNING: Some transactions not updated — review manually.")
        else:
            print(f"  OK: {len(selected)} transaction(s) marked received.")
            if variance != 0:
                print(f"  Variance: {v_sign}${abs(variance):.2f} distributed proportionally.")


# ------------------------------------------------------------------ #
# Mode 3 — Review cashback status
# ------------------------------------------------------------------ #

def mode_review(client):
    print("\n" + "=" * 60)
    print("  CASHBACK STATUS REVIEW")
    print("=" * 60)

    result = (
        client.table("cashback_transactions")
        .select(
            "cb_id, source, order_number, retailer, cashback_amount, "
            "cashback_percent, transaction_date, expected_payout_quarter, "
            "status, actual_amount_received"
        )
        .eq("user_id", PHASE_1_USER_ID)
        .order("source")
        .order("transaction_date")
        .execute()
    )
    txns = result.data or []

    if not txns:
        print("\n  No cashback transactions on record.")
        return

    today      = date.today()
    all_listed = []  # flat numbered list for status-update prompts

    by_platform = {}
    for tx in txns:
        by_platform.setdefault(tx["source"], []).append(tx)

    for platform, p_txns in by_platform.items():
        by_status = {}
        for tx in p_txns:
            by_status.setdefault(tx["status"], []).append(tx)

        print(f"\n  {platform.upper()}")
        print("  " + "-" * 56)

        for status in VALID_STATUSES:
            group = by_status.get(status, [])
            if not group:
                continue
            print(f"\n    [{status.upper()}]")
            for tx in group:
                num     = len(all_listed) + 1
                all_listed.append(tx)
                age     = (today - date.fromisoformat(tx["transaction_date"])).days
                flags   = []
                if status == "pending" and age > STALE_FLAG_DAYS:
                    flags.append(f"STALE {age}d")
                    if platform == "RetailMeNot":
                        remaining = RMN_DISPUTE_WINDOW - age
                        flags.append(
                            f"{remaining}d dispute left"
                            if remaining > 0
                            else "DISPUTE WINDOW EXPIRED"
                        )
                flag_str = "  *** " + " | ".join(flags) if flags else ""
                actual = tx.get("actual_amount_received")
                amt_str = (
                    f"${float(actual):.2f} actual"
                    if actual is not None
                    else f"${float(tx['cashback_amount']):.2f} expected"
                )
                print(
                    f"    {num:>3}. {(tx.get('order_number') or 'N/A'):<18} "
                    f"{(tx.get('retailer') or 'N/A'):<14} "
                    f"{amt_str:<20}  "
                    f"({tx.get('expected_payout_quarter') or 'N/A'})  "
                    f"{age}d{flag_str}"
                )

    # Summary totals
    pending_total  = sum(float(t["cashback_amount"]) for t in txns if t["status"] == "pending")
    received_total = sum(
        float(t.get("actual_amount_received") or t["cashback_amount"])
        for t in txns if t["status"] in ("received", "confirmed")
    )
    print(f"\n  Total pending:            ${pending_total:.2f}")
    print(f"  Total received/confirmed: ${received_total:.2f}")

    # Capital One: unredeemed balance from confirmed transactions
    cap1_conf = [
        t for t in txns
        if t["source"] == "Capital One Shopping"
        and t["status"] in ("received", "confirmed")
    ]
    if cap1_conf:
        cap1_bal = sum(
            float(t.get("actual_amount_received") or t["cashback_amount"])
            for t in cap1_conf
        )
        print(f"  Capital One Shopping gift card pool: ${cap1_bal:.2f}")

    if not all_listed:
        return
    print()
    if not get_yes_no("Update the status of any transaction?"):
        return

    while True:
        raw = get_input("Transaction number to update (or 'done')")
        if raw.lower() == "done":
            break
        try:
            tx = all_listed[int(raw) - 1]
        except (ValueError, IndexError):
            print("  Invalid number.")
            continue

        print(
            f"  Selected: #{raw}  {tx.get('order_number')} — "
            f"{tx.get('retailer')} — ${float(tx['cashback_amount']):.2f}  [{tx['status']}]"
        )
        print(f"  Choose new status: {' / '.join(UPDATABLE_STATUSES)}")
        new_status = get_input("New status")
        if new_status not in UPDATABLE_STATUSES:
            print(f"  Invalid. Choose from: {', '.join(UPDATABLE_STATUSES)}")
            continue

        print(f"  Change: {tx['status']} → {new_status}")
        if not get_yes_no("Confirm?"):
            print("  Skipped.")
            continue

        upd = (
            client.table("cashback_transactions")
            .update({"status": new_status})
            .eq("cb_id", tx["cb_id"])
            .execute()
        )
        if upd.data:
            tx["status"] = new_status
            print(f"  OK: Status updated to {new_status}.")
        else:
            print("  ERROR: Update failed.")

        if not get_yes_no("Update another?"):
            break


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main():
    print("\n" + "=" * 60)
    print("  RESELLOS — CASHBACK POOL MANAGER")
    print("=" * 60)
    print()
    print("  1. Record cashback earned on an order")
    print("  2. Record payout received")
    print("  3. Review cashback status")
    print()

    client = get_client()

    while True:
        raw = get_input("Select mode (1/2/3)").strip()
        if raw == "1":
            mode_earn(client)
            break
        if raw == "2":
            mode_payout(client)
            break
        if raw == "3":
            mode_review(client)
            break
        print("  Please enter 1, 2, or 3.")


if __name__ == "__main__":
    main()
