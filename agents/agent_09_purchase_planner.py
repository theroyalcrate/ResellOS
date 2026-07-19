"""
ResellOS - Agent 09: Purchase Planner
========================================
Standalone planning tool for a buying session — deliberately separate from
agent_02_order_entry.py, not a mode within it (Josh's call, 2026-07-18).

One purchase plan = one planned buying session (not one order). Built ahead
of time when a sale window, double-points event, or GWP threshold is coming
up: enter the sets being targeted, the gift card/points available, and a
target (GWP spend threshold, points tier, or plain spend cap). The
calculator finds the combination of sets/quantities that clears the target
with the least overspend (or, for a spend cap, gets closest to it without
going over) and shows every combination it considered — not a black-box
number — so Josh can sanity-check it before buying.

GWP and sale thresholds are always typed in by hand, never predicted. Real
patterns exist but change often enough that automating the guess would
introduce noise rather than remove it (decided 2026-07-18).

IMPORTANT — this script never creates a real order. Per the manual-entry-
first architecture decision (CONTEXT.md, 2026-07-18), agent_02_order_entry.py
is the only order source until the ResellOS Chrome extension exists. When a
plan is placed, this script prints a paste-ready cheat sheet (set names,
numbers, quantities, prices) for the agent_02 prompts — Josh still confirms
every line against the real invoice there. That's what closes the "no double
entry" requirement without letting a plan (written before the purchase)
silently become the order record.

Plan lifecycle: draft -> ready -> placed (mirrors hit_list's
active/purchased/abandoned pattern).

Usage: python agents/agent_09_purchase_planner.py
"""

import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_client import get_client, PHASE_1_USER_ID
# Reused rather than re-derived: normalize_retailer and the LEGO points rate
# are shared facts (retailer key spelling, points formula), not interactive
# order-entry logic. Importing agent_02 here doesn't run any of its prompts —
# it only has a __main__ guard, so this stays a genuinely standalone tool.
from agent_02_order_entry import normalize_retailer, LEGO_POINTS_PER_DOLLAR


TARGET_TYPES = ("gwp_threshold", "points_tier", "spend_cap")
PLAN_STATUSES = ("draft", "ready", "placed")

# Safety guard on the brute-force combination search. A typical buying
# session is a handful of sets with small max-quantities (a few thousand
# combos at most) — this just stops a badly configured plan (e.g. ten items
# at max_quantity 10) from hanging the script.
MAX_COMBINATIONS = 200_000


# --------------------------------------------------------------------------- #
# Pure logic — combination calculator (no DB, no I/O; unit-testable)
# --------------------------------------------------------------------------- #

def lego_points_for_item(unit_price, quantity, multiplier=1):
    """Round-half-up, matching agent_02_order_entry.py's _lego_item_points."""
    return int(unit_price * quantity * LEGO_POINTS_PER_DOLLAR * multiplier + 0.5)


def _item_quantity_options(item):
    return range(0, max(item.get("max_quantity", 2), 0) + 1)


def _combo_totals(items, quantities, target_type, multiplier):
    total_spend = 0.0
    total_points = 0
    chosen = []
    for item, qty in zip(items, quantities):
        if qty <= 0:
            continue
        line_spend = round(item["unit_price"] * qty, 2)
        total_spend += line_spend
        if target_type == "points_tier":
            total_points += lego_points_for_item(item["unit_price"], qty, multiplier)
        chosen.append({**item, "quantity": qty, "line_spend": line_spend})
    return round(total_spend, 2), total_points, chosen


def generate_combinations(items):
    """
    Yield every quantity combination across all items' quantity ranges
    (0..max_quantity each). Raises ValueError instead of hanging if the
    search space is too large — see MAX_COMBINATIONS.
    """
    ranges = [_item_quantity_options(i) for i in items]
    total_combos = 1
    for r in ranges:
        total_combos *= len(r)
    if total_combos > MAX_COMBINATIONS:
        raise ValueError(
            f"Search space too large ({total_combos:,} combinations). "
            f"Lower max_quantity on some items and try again."
        )
    return product(*ranges)


def _sort_key(combo, target_type):
    # spend_cap: maximize spend (get closest to the cap), tie-break on points.
    # gwp_threshold / points_tier: minimize spend among combos that qualify,
    # tie-break on more points being slightly preferred.
    if target_type == "spend_cap":
        return (-combo["total_spend"], -combo["total_points"])
    return (combo["total_spend"], -combo["total_points"])


def find_best_combination(items, target_type, target_value, lego_multiplier=1):
    """
    Brute-force search over every quantity combination. Returns the best
    combo plus up to 3 runner-ups (by distinct total spend) so the plan
    "shows its work" instead of a single unexplained number.

    gwp_threshold / points_tier: minimize total spend among combos that
      reach or exceed target_value (dollars for gwp_threshold, points for
      points_tier).
    spend_cap: maximize total spend among combos that do not exceed
      target_value.

    Returns: {"best": combo or None, "runners_up": [combo, ...], "all_considered": int}
    """
    if target_type not in TARGET_TYPES:
        raise ValueError(f"Unknown target_type '{target_type}' — must be one of {TARGET_TYPES}")

    if not items:
        return {"best": None, "runners_up": [], "all_considered": 0}

    candidates = []
    considered = 0
    for quantities in generate_combinations(items):
        considered += 1
        total_spend, total_points, chosen = _combo_totals(
            items, quantities, target_type, lego_multiplier
        )
        if not chosen:
            continue

        if target_type == "spend_cap":
            if total_spend > target_value:
                continue
        else:
            metric = total_points if target_type == "points_tier" else total_spend
            if metric < target_value:
                continue

        candidates.append({
            "items": chosen,
            "total_spend": total_spend,
            "total_points": total_points,
        })

    if not candidates:
        return {"best": None, "runners_up": [], "all_considered": considered}

    candidates.sort(key=lambda c: _sort_key(c, target_type))
    best = candidates[0]

    runners_up = []
    seen_spends = {best["total_spend"]}
    for c in candidates[1:]:
        if c["total_spend"] in seen_spends:
            continue
        runners_up.append(c)
        seen_spends.add(c["total_spend"])
        if len(runners_up) == 3:
            break

    return {"best": best, "runners_up": runners_up, "all_considered": considered}


def evaluate_gift_card_fit(total_spend, balance):
    """balance may be None (no gift card constraint given for this plan)."""
    if balance is None:
        return {"balance": None, "remaining": None, "shortfall": None}
    remaining = round(balance - total_spend, 2)
    return {
        "balance": round(balance, 2),
        "remaining": remaining if remaining >= 0 else 0,
        "shortfall": round(abs(remaining), 2) if remaining < 0 else 0,
    }


def describe_combination(combo, target_type):
    """Pure formatting — returns display lines, used by both the CLI and tests."""
    lines = []
    for it in combo["items"]:
        lines.append(
            f"{it['set_name']} x{it['quantity']} @ ${it['unit_price']:.2f} = ${it['line_spend']:.2f}"
        )
    lines.append(f"Total spend: ${combo['total_spend']:.2f}")
    if target_type == "points_tier":
        lines.append(f"Total points: {combo['total_points']}")
    return lines


# --------------------------------------------------------------------------- #
# Input helpers (kept local — this script has no other interactive deps)
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
# Database access
# --------------------------------------------------------------------------- #

def fetch_gift_cards_for_retailer(client, retailer):
    result = (
        client.table("gift_cards")
        .select("card_id, remaining_balance, status, card_number_last4")
        .eq("user_id", PHASE_1_USER_ID)
        .ilike("retailer", retailer)
        .eq("status", "active")
        .order("remaining_balance", desc=True)
        .execute()
    )
    return result.data or []


def list_plans(client, status_filter=None):
    q = (
        client.table("purchase_plans")
        .select("plan_id, plan_name, retailer, status, target_type, target_value")
        .eq("user_id", PHASE_1_USER_ID)
        .order("created_at", desc=True)
    )
    if status_filter:
        q = q.eq("status", status_filter)
    result = q.execute()
    return result.data or []


def fetch_plan(client, plan_id):
    p = (
        client.table("purchase_plans")
        .select("*")
        .eq("plan_id", plan_id)
        .eq("user_id", PHASE_1_USER_ID)
        .execute()
    )
    if not p.data:
        return None, []
    items = (
        client.table("purchase_plan_items")
        .select("*")
        .eq("plan_id", plan_id)
        .execute()
    )
    return p.data[0], (items.data or [])


# --------------------------------------------------------------------------- #
# Plan creation / editing
# --------------------------------------------------------------------------- #

def create_plan(client):
    print("\n" + "=" * 60)
    print("  NEW PURCHASE PLAN")
    print("=" * 60)
    plan_name = get_input("Plan name (e.g. 'July GWP sale')")
    retailer = normalize_retailer(get_input("Retailer (e.g. LEGO, Target, BN)"))

    print("\n  Target type:")
    print("    gwp_threshold — hit a GWP spend threshold with minimum overspend")
    print("    points_tier   — hit a points/tier target with minimum spend")
    print("    spend_cap     — get as close as possible to a spend cap without going over")
    target_type = get_input("Target type", default="gwp_threshold")
    while target_type not in TARGET_TYPES:
        print(f"  Must be one of: {', '.join(TARGET_TYPES)}")
        target_type = get_input("Target type", default="gwp_threshold")

    label = {
        "gwp_threshold": "GWP spend threshold ($)",
        "points_tier": "Points target",
        "spend_cap": "Spend cap ($)",
    }[target_type]
    target_value = get_float(label)

    lego_multiplier = 1
    if retailer == "lego" or target_type == "points_tier":
        lego_multiplier = get_int("LEGO Insider points multiplier (1/2/4)", default="1")

    gift_card_id = None
    planned_balance = None
    cards = fetch_gift_cards_for_retailer(client, retailer)
    if cards:
        print(f"\n  Active {retailer} gift cards on file:")
        for i, c in enumerate(cards, 1):
            last4 = c.get("card_number_last4") or "----"
            print(f"    {i}. ...{last4} — balance ${float(c['remaining_balance']):.2f}")
        choice = get_input(
            "  Use one of these? Enter number, or 'manual', or 'skip'", default="skip"
        )
        if choice.isdigit() and 1 <= int(choice) <= len(cards):
            picked = cards[int(choice) - 1]
            gift_card_id = picked["card_id"]
            planned_balance = float(picked["remaining_balance"])
        elif choice.lower() == "manual":
            planned_balance = get_float("  Planned gift card balance ($)")
    else:
        if get_yes_no(f"  No active {retailer} gift cards on file. Enter a planned balance manually?"):
            planned_balance = get_float("  Planned gift card balance ($)")

    insider_points_available = None
    if retailer == "lego" and get_yes_no("  Enter current Insider points balance?"):
        insider_points_available = get_int("  Insider points available", default="0")

    notes = get_input("Notes (optional)", required=False)

    row = {
        "user_id": PHASE_1_USER_ID,
        "plan_name": plan_name,
        "retailer": retailer,
        "status": "draft",
        "target_type": target_type,
        "target_value": target_value,
        "lego_points_multiplier": lego_multiplier,
        "gift_card_id": gift_card_id,
        "planned_gift_card_balance": planned_balance,
        "insider_points_available": insider_points_available,
        "notes": notes,
    }
    result = client.table("purchase_plans").insert(row).execute()
    if not result.data:
        print("  ERROR: Failed to create plan.")
        return None
    return result.data[0]


def add_items(client, plan):
    print(f"\n  -- ADD TARGET SETS to '{plan['plan_name']}' --")
    print("  Type 'done' as set name when finished.\n")
    added = []
    while True:
        set_name = get_input(f"  Item {len(added) + 1}: Set name or description")
        if set_name.lower() == "done":
            break
        set_number = get_input("    Set number", required=False)
        unit_price = get_float("    Price per unit (expected sale/current price)")
        is_gwp = get_yes_no("    GWP-eligible at this price point?")
        is_sale = get_yes_no("    On sale / promo?")
        max_qty = get_int("    Max quantity to consider", default="2")
        item_notes = get_input("    Notes (optional)", required=False)

        row = {
            "user_id": PHASE_1_USER_ID,
            "plan_id": plan["plan_id"],
            "set_name": set_name,
            "set_number": set_number,
            "unit_price": unit_price,
            "is_gwp_eligible": is_gwp,
            "is_sale_or_promo": is_sale,
            "max_quantity": max_qty,
            "notes": item_notes,
        }
        result = client.table("purchase_plan_items").insert(row).execute()
        if result.data:
            added.append(result.data[0])
            print(f"    Added: {set_name} (max qty {max_qty})")
        else:
            print("    ERROR: Failed to add item.")

        if not get_yes_no("  Add another item?", default="y"):
            break
    return added


def _calc_items_from_rows(item_rows):
    return [
        {
            "set_name": i["set_name"],
            "set_number": i.get("set_number"),
            "unit_price": float(i["unit_price"]),
            "max_quantity": i["max_quantity"],
        }
        for i in item_rows
    ]


# --------------------------------------------------------------------------- #
# Calculator flow
# --------------------------------------------------------------------------- #

def run_calculator_flow(client, plan_id):
    plan, items = fetch_plan(client, plan_id)
    if plan is None:
        print("  Plan not found.")
        return
    if not items:
        print("  This plan has no items yet. Add items first.")
        return

    target_type = plan["target_type"]
    target_value = float(plan["target_value"])
    multiplier = plan.get("lego_points_multiplier") or 1
    calc_items = _calc_items_from_rows(items)

    try:
        result = find_best_combination(calc_items, target_type, target_value, multiplier)
    except ValueError as e:
        print(f"  ERROR: {e}")
        return

    print("\n" + "=" * 60)
    print(f"  CALCULATOR RESULTS — {plan['plan_name']}")
    print("=" * 60)
    if target_type == "spend_cap":
        print(f"  Target: spend_cap <= ${target_value:.2f}")
    else:
        unit = "points" if target_type == "points_tier" else "$"
        print(f"  Target: {target_type} >= {unit}{target_value:.2f}" if unit == "$"
              else f"  Target: {target_type} >= {target_value:.0f} points")
    print(f"  Combinations considered: {result['all_considered']:,}")

    if result["best"] is None:
        print("\n  No combination reaches this target with the items and max quantities given.")
        print("  Try raising a max_quantity, adding another set, or lowering the target.")
        print("=" * 60)
        return

    best = result["best"]
    print("\n  BEST COMBINATION:")
    for line in describe_combination(best, target_type):
        print(f"    {line}")

    balance = plan.get("planned_gift_card_balance")
    if balance is not None:
        fit = evaluate_gift_card_fit(best["total_spend"], float(balance))
        if fit["shortfall"]:
            print(
                f"\n  Gift card balance: ${fit['balance']:.2f} — "
                f"SHORT by ${fit['shortfall']:.2f} (needs another payment method for the rest)"
            )
        else:
            print(
                f"\n  Gift card balance: ${fit['balance']:.2f} — "
                f"covers it, ${fit['remaining']:.2f} left over"
            )

    points_avail = plan.get("insider_points_available")
    if points_avail is not None and target_type == "points_tier":
        print(f"  Insider points on hand before this order: {points_avail}")
        print(f"  Insider points after this order (est.): {points_avail + best['total_points']}")

    if result["runners_up"]:
        print("\n  RUNNER-UP COMBINATIONS (for comparison):")
        for i, c in enumerate(result["runners_up"], 1):
            print(f"\n  #{i}:")
            for line in describe_combination(c, target_type):
                print(f"    {line}")
    print("=" * 60)


# --------------------------------------------------------------------------- #
# Status transitions
# --------------------------------------------------------------------------- #

def mark_ready(client, plan_id):
    plan, items = fetch_plan(client, plan_id)
    if plan is None:
        print("  Plan not found.")
        return
    if not items:
        print("  Can't mark ready — plan has no items.")
        return
    client.table("purchase_plans").update({"status": "ready"}).eq("plan_id", plan_id).execute()
    print(f"  '{plan['plan_name']}' marked ready.")


def place_from_plan(client, plan_id):
    """
    Marks the plan placed and prints the chosen combination as a paste-ready
    cheat sheet for agent_02_order_entry.py. Never writes to orders or
    line_items directly — see module docstring.
    """
    plan, items = fetch_plan(client, plan_id)
    if plan is None:
        print("  Plan not found.")
        return
    if not items:
        print("  Plan has no items — nothing to place.")
        return

    calc_items = _calc_items_from_rows(items)
    try:
        result = find_best_combination(
            calc_items, plan["target_type"], float(plan["target_value"]),
            plan.get("lego_points_multiplier") or 1,
        )
    except ValueError as e:
        print(f"  ERROR: {e}")
        return

    if result["best"] is None:
        print("  No combination reached the target — run the calculator and adjust the plan first.")
        return

    order_number = get_input("  Real order number (from the confirmation you just placed)")

    client.table("purchase_plans").update({"status": "placed"}).eq("plan_id", plan_id).execute()

    print("\n" + "=" * 60)
    print("  PLAN MARKED PLACED")
    print(f"  Order number entered: {order_number}")
    print("  Now open agent_02_order_entry.py and enter the order for real,")
    print("  confirming every line against the actual invoice/confirmation email.")
    print("  Cheat sheet — line items from the chosen combination:")
    print("=" * 60)
    for it in result["best"]["items"]:
        print(f"\n  Set name:   {it['set_name']}")
        print(f"  Set number: {it.get('set_number') or '(enter from confirmation)'}")
        print(f"  Quantity:   {it['quantity']}")
        print(f"  Unit price: ${it['unit_price']:.2f}")
    print("\n  Total spend (planned): ${:.2f}".format(result["best"]["total_spend"]))
    print("=" * 60)

    if get_yes_no("\n  Has the order already been saved in agent_02? Link it now?", default="n"):
        real_order = (
            client.table("orders")
            .select("order_id, order_number")
            .eq("user_id", PHASE_1_USER_ID)
            .eq("order_number", order_number)
            .execute()
        )
        if real_order.data:
            client.table("purchase_plans").update(
                {"placed_order_id": real_order.data[0]["order_id"]}
            ).eq("plan_id", plan_id).execute()
            print(f"  Linked to order_id {real_order.data[0]['order_id']}.")
        else:
            print(
                f"  No order found with number {order_number} yet — "
                f"link it later by re-running 'Place order from plan' on this plan."
            )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def print_plans_table(plans):
    if not plans:
        print("  No plans yet.")
        return
    print()
    for p in plans:
        print(
            f"  [{p['status']:>7}] {p['plan_name']:<30} {p['retailer']:<12} "
            f"{p['target_type']:<15} target={p['target_value']}"
        )


def select_plan(client, status_filter=None):
    plans = list_plans(client, status_filter=status_filter)
    if not plans:
        label = f" with status '{status_filter}'" if status_filter else ""
        print(f"  No plans found{label}.")
        return None
    print()
    for i, p in enumerate(plans, 1):
        print(f"  {i}. [{p['status']}] {p['plan_name']} — {p['retailer']} — {p['target_type']} {p['target_value']}")
    choice = get_input("  Select plan number", required=False)
    if not choice or not choice.isdigit() or not (1 <= int(choice) <= len(plans)):
        print("  Cancelled.")
        return None
    return plans[int(choice) - 1]["plan_id"]


def main_menu():
    client = get_client()
    while True:
        print("\n" + "=" * 60)
        print("  RESELLOS -- AGENT 09: PURCHASE PLANNER")
        print("=" * 60)
        print("  1. Create new plan")
        print("  2. Add items to a plan")
        print("  3. Run calculator on a plan")
        print("  4. Mark plan ready")
        print("  5. Place order from plan")
        print("  6. List plans")
        print("  7. Exit")
        choice = get_input("Choice", default="6")

        if choice == "1":
            plan = create_plan(client)
            if plan:
                print(f"\n  Plan created: {plan['plan_name']} (plan_id {plan['plan_id']})")
                if get_yes_no("  Add items now?", default="y"):
                    add_items(client, plan)

        elif choice == "2":
            plan_id = select_plan(client, status_filter="draft")
            if plan_id:
                plan, _ = fetch_plan(client, plan_id)
                add_items(client, plan)

        elif choice == "3":
            plan_id = select_plan(client)
            if plan_id:
                run_calculator_flow(client, plan_id)

        elif choice == "4":
            plan_id = select_plan(client, status_filter="draft")
            if plan_id:
                mark_ready(client, plan_id)

        elif choice == "5":
            plan_id = select_plan(client, status_filter="ready")
            if plan_id:
                place_from_plan(client, plan_id)

        elif choice == "6":
            print_plans_table(list_plans(client))

        elif choice == "7":
            print("Goodbye.")
            break

        else:
            print("  Please choose 1-7.")


def main():
    main_menu()


if __name__ == "__main__":
    main()
