"""
ResellOS - Agent 02: Manual Order Entry
========================================
Captures a new order at time of purchase.
Writes to: orders -> shipments -> line_items (in correct FK order).
Confirms before every database write.

Usage: python agent_02_order_entry.py
"""

from datetime import date
from db_client import get_client, PHASE_1_USER_ID
from order_validators import run_all_checks, print_warnings

# --- Rewards constants ---
LEGO_POINTS_PER_DOLLAR   = 6.5
BARNES_STAMP_DIVISOR     = 10
KOHLS_REWARDS_RATE       = 0.05
KOHLS_EVENT_CASH_DIVISOR = 50
KOHLS_EVENT_CASH_BLOCK   = 10
KOHLS_PICKUP_BONUS       = 5.00
MACYS_BRONZE_RATE        = 1        # 1 pt per $1
MACYS_PTS_PER_STAR_MONEY = 1000     # 1000 pts = $10 Star Money
MACYS_GOLD_THRESHOLD     = 500
MACYS_PLATINUM_THRESHOLD = 1200
MACYS_TIER_GAP_ALERT     = 100
WALMART_POOL_RATE        = 0.02

# Retailer-specific reward columns (only written when non-None)
_REWARD_COLS = (
    "barnes_stamps_earned", "barnes_bonus_reward",
    "kohls_rewards_earned", "kohls_event_cash_earned", "kohls_pickup_bonus",
    "macys_points_earned",
    "walmart_rewards_earned",
    "target_offer_earned",
    "bestbuy_offer_earned",
)

# Canonical retailer values (lowercase snake_case) — matches Supabase orders/gift_cards
# columns after the 2026-07-13 casing normalization (was Barnes/BN/Lego/LEGO mixed).
# Aliases map common free-text input to the one stored value. Anything not listed falls
# back to a lowercased, underscored version of whatever the user typed, with a warning.
_RETAILER_ALIASES = {
    "LEGO": "lego",
    "BARNES": "barnes_noble", "BN": "barnes_noble", "B&N": "barnes_noble",
    "BARNES AND NOBLE": "barnes_noble", "BARNES & NOBLE": "barnes_noble",
    "BARNES_NOBLE": "barnes_noble", "BARNES NOBLE": "barnes_noble",
    "KOHLS": "kohls", "KOHL'S": "kohls",
    "MACYS": "macys", "MACY'S": "macys",
    "WALMART": "walmart",
    "TARGET": "target",
    "BESTBUY": "best_buy", "BEST BUY": "best_buy", "BEST_BUY": "best_buy",
}


def normalize_retailer(raw: str) -> str:
    """Map free-text retailer input to the canonical stored value."""
    key = raw.strip().upper()
    canonical = _RETAILER_ALIASES.get(key)
    if canonical is None:
        # Fallback for anything not in the alias table (e.g. Fred Meyer, Walgreens):
        # pad '&' with spaces BEFORE collapsing whitespace to '_', so "B&N"-style
        # shorthand doesn't garble into "band" instead of "b_and_n".
        cleaned = raw.strip().lower().replace("&", " and ")
        canonical = "_".join(cleaned.split())
        print(f"  NOTE: '{raw}' isn't a known retailer alias — storing as '{canonical}'.")
    return canonical


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


def get_float(prompt, required=True, default=None):
    while True:
        raw = get_input(prompt, required, str(default) if default is not None else None)
        if raw is None:
            return None
        try:
            return float(str(raw).replace("$", "").replace(",", ""))
        except ValueError:
            print("  Please enter a valid number (e.g. 49.99)")


def get_int(prompt, required=True, default="0"):
    while True:
        raw = get_input(prompt, required, default)
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a whole number (e.g. 1)")


def get_yes_no(prompt, default="n"):
    while True:
        raw = get_input(f"{prompt} (y/n)", default=default).lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


# --------------------------------------------------------------------------- #
# Rewards calculation helpers
# --------------------------------------------------------------------------- #

def _lego_item_points(item, order_multiplier):
    if item.get("is_gwp"):
        return 0
    m = item.get("lego_multiplier_override") or order_multiplier
    # int(x + 0.5) gives round-half-up for positive values; Python's round()
    # uses banker's rounding which would mismatch LEGO's actual calculation.
    base = int(item["line_total"] * LEGO_POINTS_PER_DOLLAR * m + 0.5)
    return base + (item.get("lego_bonus_points") or 0)


def _barnes_stamps(eligible, multiplier):
    # round(eligible, 2) before dividing prevents float subtraction artifacts
    # (e.g. 100.10 - 30.10 = 69.9999... → int(6.9999) = 6, not 7).
    return int(round(eligible, 2) / BARNES_STAMP_DIVISOR) * multiplier


def _kohls_rewards(spend):
    return round(spend * KOHLS_REWARDS_RATE, 2)


def _kohls_event_cash(spend):
    return int(round(spend, 2) / KOHLS_EVENT_CASH_DIVISOR) * KOHLS_EVENT_CASH_BLOCK


# --------------------------------------------------------------------------- #
# Line item collection
# --------------------------------------------------------------------------- #

def collect_line_items(retailer="", lego_order_multiplier=1):
    items = []
    r = retailer.upper()
    print("\n  -- LINE ITEMS --")
    print("  Enter each item. Type 'done' as set name when finished.")
    print()
    while True:
        print(f"  Item {len(items) + 1}:")
        set_name = get_input("    Set name or description")
        if set_name.lower() == "done":
            if not items:
                print("  At least one item is required.")
                continue
            break
        set_number  = get_input("    Set number (e.g. 10242)", required=False)
        quantity    = get_int("    Quantity", default="1")
        msrp        = get_float("    MSRP (retail price)", required=False)
        unit_price  = get_float("    Price paid per unit")
        is_gwp      = get_yes_no("    Is this a GWP?")
        is_retiring = get_yes_no("    Retiring set?", default="y")

        item = {
            "set_name":     set_name,
            "set_number":   set_number,
            "quantity":     quantity,
            "msrp":         msrp,
            "unit_price":   unit_price,
            "line_discount": round((msrp - unit_price) * quantity, 2) if msrp else 0,
            "line_total":   round(unit_price * quantity, 2),
            "is_gwp":       is_gwp,
            "is_retiring":  is_retiring,
        }

        if r == "LEGO" and not is_gwp:
            if get_yes_no(
                f"    Per-set multiplier override? (order default ×{lego_order_multiplier})"
            ):
                item["lego_multiplier_override"] = get_int(
                    "    Multiplier for this set (1/2/4)",
                    default=str(lego_order_multiplier),
                )
            if get_yes_no("    Any bonus points on this set?"):
                item["lego_bonus_points"] = get_int("    Bonus points (flat)", default="0")

        if r == "WALMART" and not is_gwp:
            if get_yes_no("    Set-specific cash reward on this item?"):
                item["walmart_set_cash_reward"] = get_float("    Cash reward ($)")

        items.append(item)
        print(f"  Added: {set_name} x{quantity} @ ${unit_price:.2f}")
        if not get_yes_no("  Add another item?", default="y"):
            break
    return items


# --------------------------------------------------------------------------- #
# Retailer rewards prompts + calculations
# --------------------------------------------------------------------------- #

def collect_rewards(retailer, order_date, subtotal, discount_total,
                    payment_method_detail, line_items, lego_order_multiplier, client):
    """
    Returns (rewards_dict, summary_lines).
    rewards_dict: reward fields to merge into the order record (None values excluded).
    summary_lines: pre-formatted strings for the order summary display.
    """
    r = retailer.upper()
    rewards = {}
    summary = []

    # ------------------------------------------------------------------ LEGO
    if r == "LEGO":
        total_pts = sum(_lego_item_points(it, lego_order_multiplier) for it in line_items)
        rewards["insider_points_earned"]    = total_pts
        rewards["insider_points_multiplier"] = lego_order_multiplier
        summary.append(f"  LEGO Insider Points:   {total_pts} pts  (order ×{lego_order_multiplier})")
        for it in line_items:
            if it.get("lego_multiplier_override"):
                summary.append(
                    f"    ↳ {it['set_name']}: ×{it['lego_multiplier_override']} override"
                )
            if it.get("lego_bonus_points"):
                summary.append(
                    f"    ↳ {it['set_name']}: +{it['lego_bonus_points']} bonus pts"
                )

    # --------------------------------------------------------------- BARNES
    elif r == "BARNES_NOBLE":
        print()
        print("  -- BARNES & NOBLE STAMPS --")
        stamp_multiplier = get_int(
            "  Stamp multiplier? (1=standard, 2=double, 3=triple)", default="1"
        )
        eligible = subtotal - discount_total
        stamps   = _barnes_stamps(eligible, stamp_multiplier)
        print(f"  Auto-calculated: {stamps} stamp(s)")
        print(f"  (Based on ${eligible:.2f} ÷ {BARNES_STAMP_DIVISOR} × {stamp_multiplier})")
        rewards["barnes_stamps_earned"] = stamps
        summary.append(
            f"  B&N Stamps Earned:     {stamps}  (×{stamp_multiplier} on ${eligible:.2f})"
        )
        if get_yes_no("  Any bonus reward on this transaction?"):
            bonus = get_float("  Bonus reward amount ($)")
            rewards["barnes_bonus_reward"] = bonus
            summary.append(f"  B&N Bonus Reward:      ${bonus:.2f}")

    # --------------------------------------------------------------- KOHLS
    elif r == "KOHLS":
        print()
        print("  -- KOHL'S REWARDS --")
        spend = subtotal - discount_total
        rc    = _kohls_rewards(spend)
        rewards["kohls_rewards_earned"] = rc
        summary.append(f"  Kohl's Rewards Cash:   ${rc:.2f}  (5% on ${spend:.2f})")
        if get_yes_no("  Kohl's Cash event active?"):
            ec     = _kohls_event_cash(spend)
            blocks = int(spend // KOHLS_EVENT_CASH_DIVISOR)
            rewards["kohls_event_cash_earned"] = ec
            summary.append(f"  Kohl's Event Cash:     ${ec:.2f}  ({blocks} × ${KOHLS_EVENT_CASH_BLOCK})")
        total_kohls = rc + (rewards.get("kohls_event_cash_earned") or 0)
        summary.append(f"  Kohl's Total:          ${total_kohls:.2f}  → Kohl's rewards pool")
        if get_yes_no("  In-store pickup bonus earned? (+$5.00)"):
            allow = True
            try:
                dup = (
                    client.table("orders")
                    .select("order_id")
                    .eq("user_id", PHASE_1_USER_ID)
                    .ilike("retailer", "kohls")
                    .eq("order_date", order_date)
                    .not_.is_("kohls_pickup_bonus", "null")
                    .execute()
                )
                if dup.data:
                    print(
                        f"  WARNING: A Kohl's order on {order_date} already has a pickup bonus."
                    )
                    allow = get_yes_no("  Record it anyway?", default="n")
            except Exception as e:
                print(f"  NOTE: Pickup bonus duplicate check failed ({e}); proceeding without check.")
            if allow:
                rewards["kohls_pickup_bonus"] = KOHLS_PICKUP_BONUS
                summary.append(f"  Kohl's Pickup Bonus:   ${KOHLS_PICKUP_BONUS:.2f}")

    # --------------------------------------------------------------- MACYS
    elif r == "MACYS":
        print()
        print("  -- MACY'S STAR REWARDS --")
        pm      = (payment_method_detail or "").lower()
        has_gc  = "gift" in pm or get_yes_no("  Payment includes a gift card?")
        if has_gc:
            rewards["macys_points_earned"] = 0
            summary.append("  Macy's Points:         0  (gift card — no points)")
        else:
            spend     = subtotal - discount_total
            base_pts  = int(spend * MACYS_BRONZE_RATE)
            total_pts = base_pts
            if get_yes_no("  Bonus Day event active?"):
                bonus_rate = get_float("  Bonus points rate per $1 (from notification)")
                bonus_pts  = int(spend * bonus_rate)
                total_pts  = base_pts + bonus_pts
                summary.append(
                    f"  Macy's Base Points:    {base_pts}  (Bronze ×{MACYS_BRONZE_RATE}/$)"
                )
                summary.append(
                    f"  Macy's Bonus Points:   {bonus_pts}  (×{bonus_rate:.1f}/$)"
                )
            else:
                summary.append(
                    f"  Macy's Points:         {total_pts}  (Bronze ×{MACYS_BRONZE_RATE}/$)"
                )
            star_money = round(total_pts / MACYS_PTS_PER_STAR_MONEY * 10, 2)
            summary.append(f"  Star Money This Order: ${star_money:.2f}")
            rewards["macys_points_earned"] = total_pts
            # Advisory tier tracking
            try:
                year_start = f"{date.today().year}-01-01"
                annual = (
                    client.table("orders")
                    .select("subtotal, discount_total")
                    .eq("user_id", PHASE_1_USER_ID)
                    .ilike("retailer", "macys")
                    .gte("order_date", year_start)
                    .execute()
                )
                prior = sum(
                    float(o.get("subtotal") or 0) - float(o.get("discount_total") or 0)
                    for o in annual.data
                )
                ytd = prior + spend
                for threshold, label in [
                    (MACYS_PLATINUM_THRESHOLD, "Platinum"),
                    (MACYS_GOLD_THRESHOLD,     "Gold"),
                ]:
                    if prior < threshold <= ytd:
                        print(f"\n  *** Macy's {label} tier reached! (${ytd:.2f} YTD)")
                        break
                    elif ytd < threshold and ytd >= threshold - MACYS_TIER_GAP_ALERT:
                        print(
                            f"\n  NOTE: ${threshold - ytd:.2f} away from Macy's {label}"
                            f" (${threshold} threshold)."
                        )
                        break
            except Exception:
                pass  # advisory only

    # ------------------------------------------------------------- WALMART
    elif r == "WALMART":
        print()
        print("  -- WALMART BUSINESS REWARDS --")
        if get_yes_no("  Order total over $250?"):
            spend = subtotal - discount_total
            pool  = round(spend * WALMART_POOL_RATE, 2)
            print(f"  Pool reward (2%):  ${pool:.2f}")
            rewards["walmart_rewards_earned"] = pool
            summary.append(
                f"  Walmart Pool Reward:   ${pool:.2f}  (2% of ${spend:.2f} post-discount)"
                f"  → Walmart Business pool"
            )
        for it in line_items:
            if it.get("walmart_set_cash_reward"):
                summary.append(
                    f"  Walmart Set Reward:    ${it['walmart_set_cash_reward']:.2f}"
                    f"  on {it['set_name']}  → cost basis reduction"
                )

    # -------------------------------------------------------------- TARGET
    elif r == "TARGET":
        print()
        print("  -- TARGET OFFERS --")
        if get_yes_no("  Target Circle debit card used?"):
            summary.append("  Target Circle Debit:   5% included in price paid")
        if get_yes_no("  Any one-off Target offer applied?"):
            offer = get_float("  Offer value ($)")
            rewards["target_offer_earned"] = offer
            summary.append(
                f"  Target Offer:          ${offer:.2f}  → cost basis reduction"
            )

    # ------------------------------------------------------------- BESTBUY
    elif r == "BEST_BUY":
        print()
        print("  -- BEST BUY OFFERS --")
        if get_yes_no("  Any promotional offer applied?"):
            offer = get_float("  Offer value ($)")
            rewards["bestbuy_offer_earned"] = offer
            summary.append(f"  Best Buy Promo Offer:  ${offer:.2f}")

    return rewards, summary


# --------------------------------------------------------------------------- #
# Order collection
# --------------------------------------------------------------------------- #

def collect_order():
    print("\n" + "=" * 60)
    print("  RESELLOS -- NEW ORDER ENTRY")
    print("=" * 60)
    print()

    retailer     = normalize_retailer(get_input("Retailer (e.g. LEGO, Target, BN)"))
    order_number = get_input("Order number")
    order_date   = get_input("Order date (YYYY-MM-DD)", default=str(date.today()))

    print()
    subtotal = get_float("Subtotal (before discounts)")
    if retailer.upper() == "WALMART":
        tax_paid = 0.0
        print("  Tax: $0.00 (Walmart Business — tax exempt)")
    else:
        tax_paid = get_float("Tax paid", default="0")
    shipping = get_float("Shipping paid", default="0")

    print()
    print("  -- PAYMENT LAYERS --")
    gift_card_applied = get_float("Gift card amount applied", default="0")
    rewards_applied   = get_float("Rewards applied ($)", default="0")
    if retailer.upper() == "LEGO":
        insider_points_redeemed = get_float("Insider points redeemed ($)", default="0")
    else:
        insider_points_redeemed = 0

    print()
    discount_total = get_float("Total discounts applied", default="0")
    order_total    = get_float("Order total (charged to card)")

    payment_method        = get_input("Payment method", required=False)
    payment_method_detail = get_input(
        "Payment detail (e.g. circle_debit, gift_card)", required=False
    )

    print()
    print("  -- ORDER SETTINGS --")
    print("  Trigger: community_alert, deal_software_alert, self_discovered")
    print("  (leave blank if channel is unknown or not applicable)")
    purchase_trigger = get_input("Purchase trigger", required=False) or None

    if retailer.upper() == "WALMART":
        tax_exemption_method = "at_purchase"
        print("  Tax exemption: at_purchase (Walmart default)")
    else:
        print("  Tax exemption: at_purchase, retroactive_adjustment, not_applicable")
        tax_exemption_method = get_input("Tax exemption method", default="not_applicable")

    pickup_method = get_input(
        "Pickup method (shipped/in_store_pickup)", default="shipped"
    )
    print("  Buy reason: planned, opportunistic, promo_expiration")
    print("  planned=targeted buy  opportunistic=deal found me  promo_expiration=expiring cash/points")
    print("  (leave blank if none apply)")
    buy_reason = get_input("Buy reason", required=False) or None
    notes = get_input("Order notes (optional)", required=False)

    # LEGO: collect order-level multiplier before line items so per-set
    # override prompts can show it as the default.
    lego_order_multiplier = 1
    if retailer.upper() == "LEGO":
        print()
        print("  -- LEGO INSIDER POINTS --")
        lego_order_multiplier = get_int("  Points multiplier? (1/2/4)", default="1")

    line_items = collect_line_items(
        retailer=retailer, lego_order_multiplier=lego_order_multiplier
    )

    client = get_client()
    rewards, rewards_summary = collect_rewards(
        retailer, order_date, subtotal, discount_total,
        payment_method_detail, line_items, lego_order_multiplier, client,
    )

    order = {
        "retailer":                  retailer,
        "order_number":              order_number,
        "order_date":                order_date,
        "subtotal":                  subtotal,
        "tax_paid":                  tax_paid,
        "tax_exempt":                (
            retailer.upper() == "WALMART" or tax_exemption_method == "at_purchase"
        ),
        "shipping":                  shipping,
        "gift_card_applied":         gift_card_applied,
        "rewards_applied":           rewards_applied,
        "insider_points_redeemed":   insider_points_redeemed,
        "insider_points_earned":     rewards.get("insider_points_earned", 0),
        "insider_points_multiplier": rewards.get("insider_points_multiplier", 1),
        "discount_total":            discount_total,
        "total":                     order_total,
        "payment_method":            payment_method,
        "payment_method_detail":     payment_method_detail,
        "purchase_trigger":          purchase_trigger,
        "tax_exemption_method":      tax_exemption_method,
        "pickup_method":             pickup_method,
        "buy_reason":                buy_reason,
        "notes":                     notes,
        "entry_method":              "manual",
        "invoice_expected":          True,
        "reconciliation_status":     "pending",
        "cost_basis_state":          "estimated",
        "order_status":              "confirmed",
        "expected_item_count":       sum(i["quantity"] for i in line_items),
        "expected_total":            order_total,
    }

    # Retailer-specific reward fields: only include when non-None so we don't
    # reference columns that may not exist for other retailers.
    for col in _REWARD_COLS:
        val = rewards.get(col)
        if val is not None:
            order[col] = val

    return order, line_items, rewards_summary, client


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #

def print_summary(order, line_items, rewards_summary):
    print("\n" + "=" * 60)
    print("  ORDER SUMMARY -- REVIEW BEFORE SAVING")
    print("=" * 60)
    print(f"  Retailer:        {order['retailer']}")
    print(f"  Order Number:    {order['order_number']}")
    print(f"  Order Date:      {order['order_date']}")
    print(f"  Subtotal:        ${order['subtotal']:.2f}")
    print(f"  Tax Paid:        ${order['tax_paid']:.2f}")
    print(f"  Shipping:        ${order['shipping']:.2f}")
    print(f"  Gift Card:       ${order['gift_card_applied']:.2f}")
    print(f"  Rewards:         ${order['rewards_applied']:.2f}")
    if order['retailer'].upper() == "LEGO" and order.get("insider_points_redeemed"):
        print(f"  Insider Pts Red: ${order['insider_points_redeemed']:.2f}")
    print(f"  Discounts:       ${order['discount_total']:.2f}")
    print(f"  ORDER TOTAL:     ${order['total']:.2f}")
    print(f"  Payment:         {order['payment_method'] or 'not specified'}")
    print(f"  Tax Treatment:   {order['tax_exemption_method']}")
    print(f"  Trigger:         {order.get('purchase_trigger') or 'not specified'}")
    print(f"  Buy Reason:      {order.get('buy_reason') or 'not specified'}")

    if rewards_summary:
        print()
        print("  -- REWARDS --")
        for line in rewards_summary:
            print(line)

    print()
    print(f"  LINE ITEMS ({len(line_items)}):")
    for i, item in enumerate(line_items, 1):
        gwp_flag = " [GWP]" if item["is_gwp"] else ""
        print(f"  {i}. {item['set_name']}{gwp_flag}")
        print(
            f"     Qty: {item['quantity']} | "
            f"Price: ${item['unit_price']:.2f} | "
            f"Total: ${item['line_total']:.2f}"
        )
        if item.get("set_number"):
            print(f"     Set #: {item['set_number']}")
        if not item.get("is_retiring", True):
            print(f"     Retiring: No")
    print("=" * 60)


# --------------------------------------------------------------------------- #
# Database write
# --------------------------------------------------------------------------- #

def write_order(order, line_items, client):
    existing = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order["order_number"])
        .execute()
    )
    if existing.data:
        print(f"\nWARNING: Order {order['order_number']} already exists.")
        if not get_yes_no("Write anyway?", default="n"):
            print("Cancelled.")
            return False

    print("\n  Writing order...")
    order_row    = {**order, "user_id": PHASE_1_USER_ID}
    order_result = client.table("orders").insert(order_row).execute()
    if not order_result.data:
        print("ERROR: Failed to write order.")
        return False
    order_id = order_result.data[0]["order_id"]
    print(f"  OK: Order written (order_id: {order_id})")

    print("  Creating shipment record...")
    shipment_row = {
        "user_id":         PHASE_1_USER_ID,
        "order_id":        order_id,
        "shipment_status": "pending",
        "entry_method":    "manual",
        "no_invoice_received": False,
    }
    shipment_result = client.table("shipments").insert(shipment_row).execute()
    if not shipment_result.data:
        print("ERROR: Failed to create shipment record. Rolling back order.")
        client.table("orders").delete().eq("order_id", order_id).execute()
        return False
    shipment_id = shipment_result.data[0]["shipment_id"]
    print(f"  OK: Shipment record created (shipment_id: {shipment_id})")

    print(f"  Writing {len(line_items)} line item(s)...")
    line_item_rows = []
    for item in line_items:
        line_item_rows.append({
            "user_id":      PHASE_1_USER_ID,
            "order_id":     order_id,
            "shipment_id":  shipment_id,
            "set_name":     item["set_name"],
            "set_number":   item.get("set_number"),
            "quantity":     item["quantity"],
            "unit_price":   item["unit_price"],
            "msrp":         item.get("msrp"),
            "line_discount": item["line_discount"],
            "line_total":   item["line_total"],
            "is_gwp":       item["is_gwp"],
            "is_retiring":  item.get("is_retiring", True),
        })

    line_result = client.table("line_items").insert(line_item_rows).execute()
    if not line_result.data:
        print("ERROR: Failed to write line items. Rolling back shipment and order.")
        client.table("shipments").delete().eq("shipment_id", shipment_id).execute()
        client.table("orders").delete().eq("order_id", order_id).execute()
        return False
    print(f"  OK: {len(line_result.data)} line item(s) written")

    print("\n" + "=" * 60)
    print("  ORDER SAVED SUCCESSFULLY")
    print(f"  Order ID:    {order_id}")
    print(f"  Shipment ID: {shipment_id}")
    print(f"  Line Items:  {len(line_result.data)}")
    print("=" * 60)
    return True


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    order, line_items, rewards_summary, client = collect_order()
    print_summary(order, line_items, rewards_summary)

    # Data checks — catch GWP/price mismatches, missing set numbers, and a
    # subtotal that doesn't match what was just entered, before saving.
    # No order_id yet (this is a brand-new order) so the cross-shipment
    # duplicate check is skipped here — that risk lives on the Agent 1A
    # side, when the invoice arrives later for an order this tool already
    # created.
    warnings = run_all_checks(
        order_id=None,
        items=line_items,
        expected_subtotal=order.get("subtotal"),
        entry_method="manual",
        client=client,
    )
    print_warnings(warnings)

    print()
    if get_yes_no("Save this order to the database?", default="n"):
        write_order(order, line_items, client)
    else:
        print("\nOrder entry cancelled. Nothing was saved.")


if __name__ == "__main__":
    main()
