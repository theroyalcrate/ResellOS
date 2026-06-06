"""
ResellOS - Agent 08: Cost Basis Engine
=======================================
Computes and records cost basis for each inventory unit across five layers:

  Layer 1  Invoice cost         line_item.line_total / quantity
           + tax_paid           order.tax_paid — actual invoice amount, never recomputed.
                                For retailers where rewards_reduce_taxable_base = true
                                (e.g. Kohl's), promos/coupons reduce the taxable base so
                                actual tax is lower. Use the real invoice number always.
  Layer 2  Gift card savings    face_value_applied - actual_purchase_cost
  Layer 3  Rewards redemption   order.rewards_applied (pro-rated)
  Layer 4  Cashback allocation  cashback_transactions (toggleable, pro-rated)
  Layer 5  GWP proceeds         behavior depends on users.gwp_cost_treatment:

  GWP cost treatment modes:
    proceeds_reduce_order  (default) — GWP units always $0 cost basis at
      receipt. When GWP sells, net proceeds reduce total economic cost of
      the originating order. Reduction allocated pro-rata across paid items
      only. Negative cost basis on paid items is valid — never suppress.
      12-month provisional window: after 12 months, paid items settle at
      current economic cost. Future GWP proceeds post-settlement create a
      P&L adjustment entry, not a cost basis recalculation.

    proportional_msrp      — allocate a share of order cost to each GWP
      at receipt, weighted by MSRP. (Not yet implemented — falls back to
      zero_no_allocation.)

    zero_no_allocation     — GWP proceeds are pure income. Paid items are
      never reduced by GWP proceeds. GWP cost basis is always $0.

Costing method (FIFO / LIFO / Average / Specific ID) stored on users record;
applies at sale time, not here.

Modes:
  1  Compute & Write  — walk all five layers, prompt for GWP proceeds,
                        write inventory units
  2  Review           — show inventory records for an order or set
  3  Settle           — lock cost_basis_state: provisional → settled

Usage: python agent_08_cost_basis.py
"""

from datetime import date
from typing import Optional

from db_client import get_client, PHASE_1_USER_ID

# GWP statuses that produce $0 proceeds immediately (no provisional window)
_GWP_ZERO_STATUSES = ("retained_personal", "donated", "lost_damaged")


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
            return ""
        print("  This field is required.")


def get_float(prompt, required=True, default=None):
    disp = f"{default:.2f}" if default is not None else None
    display = f"{prompt} [{disp}]: " if disp else f"{prompt}: "
    while True:
        raw = input(display).strip()
        if not raw and default is not None:
            return float(default)
        if not raw and not required:
            return None
        try:
            return float(raw.replace(",", ""))
        except ValueError:
            print("  Please enter a number.")


def get_yes_no(prompt, default=None):
    hint = " [Y/n]" if default == "y" else " [y/N]" if default == "n" else ""
    while True:
        raw = input(f"{prompt}{hint}: ").strip().lower()
        if not raw and default:
            return default == "y"
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def load_order(order_number: str, client) -> Optional[dict]:
    result = (
        client.table("orders")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order_number)
        .execute()
    )
    return result.data[0] if result.data else None


def load_line_items(order_id: str, client) -> list[dict]:
    result = (
        client.table("line_items")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_id", order_id)
        .execute()
    )
    return result.data or []


def load_cashback(order_id: str, client) -> list[dict]:
    result = (
        client.table("cashback_transactions")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_id", order_id)
        .execute()
    )
    return result.data or []


def load_gwp_data(order_id: str, client) -> dict:
    """Returns {line_item_id: {gwp_id, status, net_proceeds, market_value, set_name}}."""
    result = (
        client.table("gwp")
        .select("gwp_id, line_item_id, set_name, status, net_proceeds, market_value")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_id", order_id)
        .execute()
    )
    out = {}
    for row in (result.data or []):
        li_id = row.get("line_item_id")
        if li_id:
            out[li_id] = {
                "gwp_id":       row.get("gwp_id"),
                "status":       row.get("status") or "pending",
                "net_proceeds": row.get("net_proceeds"),
                "market_value": row.get("market_value"),
                "set_name":     row.get("set_name"),
            }
    return out


def load_costing_method(client) -> str:
    result = (
        client.table("users")
        .select("costing_method")
        .eq("user_id", PHASE_1_USER_ID)
        .execute()
    )
    return (result.data[0].get("costing_method") or "fifo") if result.data else "fifo"


def load_gwp_treatment(client) -> str:
    result = (
        client.table("users")
        .select("gwp_cost_treatment")
        .eq("user_id", PHASE_1_USER_ID)
        .execute()
    )
    return (result.data[0].get("gwp_cost_treatment") or "proceeds_reduce_order") if result.data else "proceeds_reduce_order"


def get_line_item_ids(order_id: str, client) -> list[str]:
    result = (
        client.table("line_items")
        .select("line_item_id")
        .eq("order_id", order_id)
        .execute()
    )
    return [r["line_item_id"] for r in (result.data or [])]


def count_existing_inventory(li_ids: list[str], client) -> int:
    if not li_ids:
        return 0
    result = (
        client.table("inventory")
        .select("unit_id")
        .eq("user_id", PHASE_1_USER_ID)
        .in_("line_item_id", li_ids)
        .execute()
    )
    return len(result.data or [])


# --------------------------------------------------------------------------- #
# Cost basis calculation
# --------------------------------------------------------------------------- #

def compute_cost_records(
    items: list[dict],
    tax_paid: float,
    gc_savings: float,
    rewards_applied: float,
    cashback_amount: float,
    gwp_proceeds_map: dict,   # {line_item_id: net_proceeds}
    gwp_treatment: str,
) -> list[dict]:
    """
    Returns one record per line item with per-unit cost basis.

    Net economic cost formula:
      (invoice_cost + tax_paid) - gc_savings - rewards - cashback - gwp_proceeds

    Tax is included because it is a cost of acquisition. For tax-exempt orders
    tax_paid is $0 so the formula degrades correctly.

    Allocation is always pro-rata by pre-tax line_total across paid items.
    GWP items always carry $0 cost basis (proceeds_reduce_order and
    zero_no_allocation modes). Negative cost_per_unit is valid.
    """
    paid_items = [it for it in items if not it.get("is_gwp")]
    gwp_items  = [it for it in items if it.get("is_gwp")]
    total_paid = round(sum(float(it["line_total"]) for it in paid_items), 2)

    gwp_proceeds_total = 0.0
    if gwp_treatment == "proceeds_reduce_order":
        gwp_proceeds_total = round(sum(gwp_proceeds_map.values()), 2)

    net_economic_cost = round(
        total_paid + tax_paid - gc_savings - rewards_applied
        - cashback_amount - gwp_proceeds_total,
        4,
    )

    records = []

    for item in paid_items:
        line_total = float(item["line_total"])
        qty        = int(item["quantity"])
        fraction   = line_total / total_paid if total_paid > 0 else 0

        net_allocated = round(net_economic_cost * fraction, 4)
        cost_per_u    = round(net_allocated / qty, 4) if qty else 0.0

        records.append({
            "line_item_id":  item["line_item_id"],
            "set_number":    item.get("set_number"),
            "set_name":      item.get("set_name") or "",
            "quantity":      qty,
            "line_total":    line_total,
            "is_gwp":        False,
            "net_allocated": net_allocated,
            "cost_per_unit": cost_per_u,
        })

    for item in gwp_items:
        li_id = item["line_item_id"]
        qty   = int(item["quantity"])
        records.append({
            "line_item_id":     li_id,
            "set_number":       item.get("set_number"),
            "set_name":         item.get("set_name") or "",
            "quantity":         qty,
            "line_total":       0.0,
            "is_gwp":           True,
            "net_allocated":    0.0,
            "cost_per_unit":    0.0,
            "gwp_net_proceeds": round(gwp_proceeds_map.get(li_id, 0.0), 2),
        })

    return records


def print_cost_breakdown(
    records: list[dict],
    layers: dict,
    gwp_treatment: str,
) -> None:
    sep = "-" * 72

    print("\n" + "=" * 72)
    print("  COST BASIS BREAKDOWN")
    print("=" * 72)

    invoice_cost = layers["invoice_cost"]
    tax_paid     = layers.get("tax_paid", 0.0)
    gross        = round(invoice_cost + tax_paid, 2)

    print(f"\n  Layer 1  Invoice cost (paid items):    ${invoice_cost:>9.2f}")
    if tax_paid > 0:
        print(f"           + Tax paid (cost of acq.):   ${tax_paid:>9.2f}")
        print(f"           = Gross acquisition cost:    ${gross:>9.2f}")
    if layers["gc_savings"] > 0:
        print(f"  Layer 2  Gift card savings:            -${layers['gc_savings']:>9.2f}")
    if layers["rewards_applied"] > 0:
        print(f"  Layer 3  Rewards redemption:           -${layers['rewards_applied']:>9.2f}")
    if layers["cashback_amount"] > 0:
        print(f"  Layer 4  Cashback (included):          -${layers['cashback_amount']:>9.2f}")
    elif layers.get("cashback_available", 0) > 0:
        print(f"  Layer 4  Cashback (excluded):           ${layers['cashback_available']:>9.2f}  [not reducing basis]")

    gwp_total = layers.get("gwp_proceeds_total", 0.0)
    if gwp_treatment == "proceeds_reduce_order":
        gwp_count = layers.get("gwp_sold_count", 0)
        if gwp_total > 0:
            print(f"  Layer 5  GWP proceeds ({gwp_count} sold):        -${gwp_total:>9.2f}")
        else:
            print(f"  Layer 5  GWP proceeds:                  $0.00  [none sold yet]")
    elif gwp_treatment == "zero_no_allocation":
        print(f"  Layer 5  GWP treatment: zero_no_allocation — proceeds are pure income")

    net_economic = layers["net_economic_cost"]
    print(f"\n  Net economic cost (paid items):        ${net_economic:>9.2f}")
    if net_economic < 0:
        print("  NOTE: Negative net cost — valid output. Heavy redemption/GWP order.")

    paid_recs = [r for r in records if not r["is_gwp"]]
    gwp_recs  = [r for r in records if r["is_gwp"]]

    if paid_recs:
        print(f"\n{sep}")
        print(f"  {'Set':<34} {'Qty':>4} {'Pre-tax':>8} {'Net Alloc':>10} {'$/Unit':>9}")
        print(sep)
        for r in paid_recs:
            name = r["set_name"][:33] + "…" if len(r["set_name"]) > 34 else r["set_name"]
            neg  = " *" if r["cost_per_unit"] < 0 else ""
            print(
                f"  {name:<34} {r['quantity']:>4} "
                f"${r['line_total']:>7.2f} "
                f"${r['net_allocated']:>9.4f} "
                f"${r['cost_per_unit']:>8.4f}{neg}"
            )

    if gwp_recs:
        print(f"\n  GWP items ({gwp_treatment} — $0 cost basis at receipt):")
        for r in gwp_recs:
            name     = r["set_name"][:33] + "…" if len(r["set_name"]) > 34 else r["set_name"]
            proc     = r.get("gwp_net_proceeds", 0.0)
            proc_str = f"net ${proc:.2f}" if proc > 0 else "no proceeds"
            print(f"    {name:<34}  x{r['quantity']}  {proc_str}  [cost basis $0.00]")

    if any(r.get("cost_per_unit", 0) < 0 for r in paid_recs):
        print("\n  * Negative cost basis — valid. GWP proceeds exceeded remaining invoice cost.")
    print("=" * 72)


# --------------------------------------------------------------------------- #
# GWP proceeds collection (Mode 1 Layer 5)
# --------------------------------------------------------------------------- #

def collect_gwp_proceeds(
    gwp_items: list[dict],
    gwp_data: dict,
    gwp_treatment: str,
) -> tuple[dict, dict]:
    """
    Prompt for net proceeds on sold GWP items.

    Returns:
      gwp_proceeds_map  — {line_item_id: net_proceeds} used in calculation
      gwp_updates       — {gwp_id: net_proceeds} to persist back to gwp table
    """
    gwp_proceeds_map = {}
    gwp_updates      = {}

    if gwp_treatment == "zero_no_allocation":
        print("\n  Layer 5 — GWP treatment: zero_no_allocation")
        print("  GWP proceeds recorded as pure income; no cost basis reduction applied.")
        for item in gwp_items:
            gwp_proceeds_map[item["line_item_id"]] = 0.0
        return gwp_proceeds_map, gwp_updates

    if gwp_treatment == "proportional_msrp":
        print("\n  Layer 5 — proportional_msrp not yet implemented; treating as zero_no_allocation.")
        for item in gwp_items:
            gwp_proceeds_map[item["line_item_id"]] = 0.0
        return gwp_proceeds_map, gwp_updates

    # proceeds_reduce_order
    print(f"\n  Layer 5 — GWP items ({len(gwp_items)})  [proceeds_reduce_order]")
    print("  Net proceeds from sold GWPs will reduce the order's economic cost,")
    print("  reallocated pro-rata across paid items. GWP cost basis is always $0.")
    print()

    for item in gwp_items:
        li_id = item["line_item_id"]
        gdata = gwp_data.get(li_id, {})
        status            = gdata.get("status") or "pending"
        existing_proceeds = gdata.get("net_proceeds")
        sname             = item.get("set_name") or ""
        snum              = item.get("set_number") or ""

        print(f"  {sname} ({snum})  [status: {status}]")

        if status in _GWP_ZERO_STATUSES:
            print(f"    {status} — $0 proceeds, no cost reduction.")
            gwp_proceeds_map[li_id] = 0.0

        elif status == "sold":
            if existing_proceeds is not None:
                existing_f = float(existing_proceeds)
                print(f"    Proceeds on record: ${existing_f:.2f}")
                if get_yes_no("    Update proceeds?", default="n"):
                    proceeds = get_float("    Net proceeds from sale ($)", default=existing_f)
                else:
                    proceeds = existing_f
            else:
                proceeds = get_float("    Net proceeds from sale ($)")
            proceeds = round(proceeds, 2)
            gwp_proceeds_map[li_id] = proceeds
            # M3: key by li_id so persists even when gwp_id is None
            if existing_proceeds is None or proceeds != float(existing_proceeds):
                gwp_updates[li_id] = proceeds

        elif status == "pending":
            print("    Provisional window running — proceeds not yet recorded.")
            if get_yes_no("    Record actual proceeds now (mark as sold)?", default="n"):
                proceeds = get_float("    Net proceeds from sale ($)")
                proceeds = round(proceeds, 2)
                gwp_proceeds_map[li_id] = proceeds
                gwp_updates[li_id] = proceeds  # M3: always persist, gwp_id not required
            else:
                print("    Skipping — GWP proceeds will not reduce cost basis this run.")
                gwp_proceeds_map[li_id] = 0.0
        else:
            gwp_proceeds_map[li_id] = 0.0

        print()

    proceeds_total = sum(gwp_proceeds_map.values())
    if proceeds_total > 0:
        print(f"  Total GWP proceeds reducing order cost: ${proceeds_total:.2f}")

    return gwp_proceeds_map, gwp_updates


# --------------------------------------------------------------------------- #
# Mode 1: Compute & Write
# --------------------------------------------------------------------------- #

def mode_compute(client):
    print("\n  -- COST BASIS: COMPUTE & WRITE --\n")

    order_number = get_input("Order number")
    order = load_order(order_number, client)
    if not order:
        print(f"  No order found for '{order_number}'.")
        return

    order_id      = order["order_id"]
    current_state = order.get("cost_basis_state") or "estimated"

    if current_state == "settled":
        print(f"  Order {order_number} is already settled. Cost basis is locked.")
        return

    li_ids   = get_line_item_ids(order_id, client)
    existing = count_existing_inventory(li_ids, client)
    if existing > 0:
        print(f"\n  WARNING: {existing} inventory unit(s) already exist for this order.")
        # C2: pre-flight — refuse overwrite if any unit is no longer in_stock
        inv_check = (
            client.table("inventory")
            .select("unit_id, status")
            .eq("user_id", PHASE_1_USER_ID)
            .in_("line_item_id", li_ids)
            .execute()
        )
        non_stock = [u for u in (inv_check.data or []) if u.get("status") != "in_stock"]
        if non_stock:
            statuses = ", ".join(sorted({u["status"] for u in non_stock}))
            print(f"  ERROR: {len(non_stock)} unit(s) have status [{statuses}] — cannot overwrite.")
            print("  Units that have left stock cannot be recalculated. Use Mode 3 to settle.")
            return
        if not get_yes_no("  Recalculate and overwrite?", default="n"):
            print("  Cancelled.")
            return

    items    = load_line_items(order_id, client)
    cashback = load_cashback(order_id, client)
    gwp_data = load_gwp_data(order_id, client)
    costing_method = load_costing_method(client)
    gwp_treatment  = load_gwp_treatment(client)

    if not items:
        print(f"  No line items found for order {order_number}.")
        print("  Run Agent 1A or the test setup script to import line items first.")
        return

    paid_items   = [it for it in items if not it.get("is_gwp")]
    gwp_items    = [it for it in items if it.get("is_gwp")]
    invoice_cost = round(sum(float(it["line_total"]) for it in paid_items), 2)
    tax_paid     = round(float(order.get("tax_paid") or 0), 2)

    print(f"\n  Order:          {order['retailer']} #{order_number}")
    print(f"  Order Date:     {order['order_date']}")
    print(f"  Current State:  {current_state}")
    print(f"  Costing Method: {costing_method.upper()}")
    print(f"  GWP Treatment:  {gwp_treatment}")
    print(f"  Line Items:     {len(paid_items)} paid, {len(gwp_items)} GWP")
    gross = round(invoice_cost + tax_paid, 2)
    print(f"  Layer 1:        ${invoice_cost:.2f} invoice + ${tax_paid:.2f} tax = ${gross:.2f} gross")

    # ---------------------------------------------------------------- Layer 2
    gc_applied = round(float(order.get("gift_card_applied") or 0), 2)
    gc_savings = 0.0
    if gc_applied > 0:
        print(f"\n  Layer 2 — Gift card face value applied: ${gc_applied:.2f}")
        print("  Enter 0 if cards were purchased at face value (no savings).")
        raw_savings = get_float("  Gift card savings ($)", default=0.0)
        gc_savings = round(max(raw_savings or 0.0, 0.0), 2)
        if gc_savings > 0:
            print(f"  Gift card savings: ${gc_savings:.2f}")
        else:
            print("  No gift card savings — invoice cost unchanged by this layer.")
    else:
        print("\n  Layer 2 — No gift card applied on this order.")

    # ---------------------------------------------------------------- Layer 3
    rewards_applied = round(float(order.get("rewards_applied") or 0), 2)
    if rewards_applied > 0:
        print(f"\n  Layer 3 — Rewards applied: ${rewards_applied:.2f} (from order record)")
    else:
        print("\n  Layer 3 — No rewards redemption on this order.")

    # ---------------------------------------------------------------- Layer 4
    cashback_amount    = 0.0
    cashback_available = 0.0

    if cashback:
        cb_received = [cb for cb in cashback if cb.get("status") in ("received", "confirmed")]
        # M1: only genuinely pending — exclude written_off and ineligible
        cb_pending  = [cb for cb in cashback if cb.get("status") == "pending"]
        cb_excluded = [cb for cb in cashback if cb.get("status") in ("ineligible", "written_off")]
        total_recv  = round(sum(float(cb.get("cashback_amount") or 0) for cb in cb_received), 2)
        total_pend  = round(sum(float(cb.get("cashback_amount") or 0) for cb in cb_pending), 2)
        cashback_available = total_recv

        print(f"\n  Layer 4 — Cashback linked to this order:")
        for cb in cb_received + cb_pending:
            amt  = float(cb.get("cashback_amount") or 0)
            src  = cb.get("source") or "?"
            stat = cb.get("status") or "?"
            print(f"    {src:<28} ${amt:.2f}  [{stat}]")
        for cb in cb_excluded:
            amt  = float(cb.get("cashback_amount") or 0)
            src  = cb.get("source") or "?"
            stat = cb.get("status") or "?"
            print(f"    {src:<28} ${amt:.2f}  [{stat}]  [excluded from pending]")

        if total_recv > 0:
            if get_yes_no(f"\n  Include ${total_recv:.2f} received cashback in cost basis?", default="y"):
                cashback_amount = total_recv
        if total_pend > 0:
            print(f"  NOTE: ${total_pend:.2f} cashback still pending — not included.")
    else:
        print("\n  Layer 4 — No cashback transactions linked to this order.")

    # ---------------------------------------------------------------- Layer 5
    if gwp_items:
        gwp_proceeds_map, gwp_updates = collect_gwp_proceeds(gwp_items, gwp_data, gwp_treatment)
    else:
        print("\n  Layer 5 — No GWP items on this order.")
        gwp_proceeds_map = {}
        gwp_updates      = {}

    # -------------------------------------------------------------- Calculate
    gwp_proceeds_total = round(sum(gwp_proceeds_map.values()), 2)
    net_economic_cost  = round(
        invoice_cost + tax_paid - gc_savings - rewards_applied
        - cashback_amount - gwp_proceeds_total,
        2,
    )

    records = compute_cost_records(
        items, tax_paid, gc_savings, rewards_applied, cashback_amount,
        gwp_proceeds_map, gwp_treatment,
    )

    layers = {
        "invoice_cost":       invoice_cost,
        "tax_paid":           tax_paid,
        "gc_savings":         gc_savings,
        "rewards_applied":    rewards_applied,
        "cashback_amount":    cashback_amount,
        "cashback_available": cashback_available,
        "gwp_proceeds_total": gwp_proceeds_total,
        "gwp_sold_count":     sum(1 for v in gwp_proceeds_map.values() if v > 0),
        "net_economic_cost":  net_economic_cost,
    }
    print_cost_breakdown(records, layers, gwp_treatment)

    # ------------------------------------------------------------ State + date
    # M2: force provisional when any GWP is still pending
    has_pending_gwp = any(
        gwp_data.get(item["line_item_id"], {}).get("status") == "pending"
        and item["line_item_id"] not in gwp_updates
        for item in gwp_items
    )
    print(f"\n  Costing method in use: {costing_method.upper()}")
    if has_pending_gwp:
        new_state = "provisional"
        print("  State forced to: provisional")
        print("  Reason: GWP item(s) still in pending window — cannot settle until resolved.")
    else:
        print("  State options: provisional (12-month window open), settled (locked)")
        raw_state = get_input("  Cost basis state", default="provisional")
        new_state = raw_state.lower() if raw_state.lower() in ("provisional", "settled", "estimated") else "provisional"

    today = date.today().isoformat()
    received_date = get_input("  Received date (YYYY-MM-DD)", default=today)

    # -------------------------------------------------------------- Confirm
    paid_units = sum(r["quantity"] for r in records if not r["is_gwp"])
    gwp_units  = sum(r["quantity"] for r in records if r["is_gwp"])
    print(f"\n  Will write {paid_units} paid unit(s) + {gwp_units} GWP unit(s) to inventory.")
    print(f"  cost_basis_state → {new_state}")
    if gwp_updates:
        print(f"  Will save proceeds for {len(gwp_updates)} GWP record(s).")
    if not get_yes_no("  Confirm?"):
        print("  Cancelled.")
        return

    # ------------------------------------------------ Delete if overwriting
    if existing > 0:
        # C2: check delete result — FK RESTRICT will fail silently without this
        del_result = (
            client.table("inventory")
            .delete()
            .eq("user_id", PHASE_1_USER_ID)
            .in_("line_item_id", li_ids)
            .execute()
        )
        if del_result.data is None:
            print("  ERROR: Delete failed (possible FK constraint). Inventory write aborted.")
            return
        print(f"  Deleted {len(del_result.data)} existing unit(s).")

    # ------------------------------------------------------------------ Write
    print("  Writing inventory units...")
    inventory_rows = []
    for r in records:
        cost = round(r["cost_per_unit"], 2)
        for _ in range(r["quantity"]):
            inventory_rows.append({
                "user_id":            PHASE_1_USER_ID,
                "line_item_id":       r["line_item_id"],
                "set_number":         r["set_number"],
                "set_name":           r["set_name"],
                "cost_basis":         cost,
                "tax_paid_allocated": 0,
                "received_date":      received_date,
                "status":             "in_stock",
            })

    inv_result = client.table("inventory").insert(inventory_rows).execute()
    if not inv_result.data:
        print("  ERROR: Failed to write inventory records.")
        return
    print(f"  OK: {len(inv_result.data)} unit(s) written to inventory")

    # ---------------------------------------------------------- Update order
    # M4: check result — silent failure possible if cost_basis_state column missing
    state_result = (
        client.table("orders")
        .update({"cost_basis_state": new_state})
        .eq("order_id", order_id)
        .execute()
    )
    if not state_result.data:
        print(f"  WARNING: cost_basis_state update returned no rows — verify in database.")
    else:
        print(f"  OK: cost_basis_state → {new_state}")

    # ---------------------------------------------------------- Save GWP proceeds
    # M3: key is li_id; falls back to WHERE line_item_id when gwp_id unavailable
    if gwp_updates:
        for li_id, proceeds in gwp_updates.items():
            gdata  = gwp_data.get(li_id, {})
            gwp_id = gdata.get("gwp_id")
            if gwp_id:
                client.table("gwp").update({
                    "net_proceeds": proceeds,
                    "status":       "sold",
                }).eq("gwp_id", gwp_id).execute()
            else:
                client.table("gwp").update({
                    "net_proceeds": proceeds,
                    "status":       "sold",
                }).eq("user_id", PHASE_1_USER_ID).eq("line_item_id", li_id).execute()
        print(f"  OK: GWP proceeds saved ({len(gwp_updates)} record(s))")

    print("\n" + "=" * 60)
    print("  COST BASIS SAVED SUCCESSFULLY")
    print(f"  Order:       {order_number}")
    print(f"  Units:       {len(inv_result.data)}  ({paid_units} paid + {gwp_units} GWP)")
    print(f"  State:       {new_state}")
    print("=" * 60)


# --------------------------------------------------------------------------- #
# Mode 2: Review
# --------------------------------------------------------------------------- #

def mode_review(client):
    print("\n  -- COST BASIS: REVIEW --\n")

    search = get_input("Order number or set number")
    order  = load_order(search, client)

    if order:
        li_ids = get_line_item_ids(order["order_id"], client)
        if not li_ids:
            print(f"  No line items found for order '{search}'.")
            return
        inv_result = (
            client.table("inventory")
            .select("*")
            .eq("user_id", PHASE_1_USER_ID)
            .in_("line_item_id", li_ids)
            .order("received_date")
            .execute()
        )
        state_line = f"  Order state:    {order.get('cost_basis_state') or 'unknown'}"
    else:
        inv_result = (
            client.table("inventory")
            .select("*")
            .eq("user_id", PHASE_1_USER_ID)
            .eq("set_number", search)
            .order("received_date")
            .execute()
        )
        state_line = ""

    units = inv_result.data or []
    if not units:
        print(f"  No inventory records found for '{search}'.")
        return

    costing_method = load_costing_method(client)
    sep = "-" * 70
    print(f"\n  Found {len(units)} unit(s):\n")
    print(f"  {'Set Name':<32} {'Set#':>6} {'Cost Basis':>10} {'Status':<12} {'Received'}")
    print(sep)
    for u in units:
        name = (u.get("set_name") or "")
        name = name[:31] + "…" if len(name) > 32 else name
        snum = u.get("set_number") or ""
        cost = float(u.get("cost_basis") or 0)
        stat = u.get("status") or ""
        recv = str(u.get("received_date") or "")
        neg  = "  *" if cost < 0 else ""
        print(f"  {name:<32} {snum:>6} ${cost:>9.4f} {stat:<12} {recv}{neg}")

    print()
    if state_line:
        print(state_line)
    print(f"  Costing method: {costing_method.upper()}")
    if any(float(u.get("cost_basis") or 0) < 0 for u in units):
        print("  * Negative cost basis — valid (heavy redemption / GWP proceeds order).")


# --------------------------------------------------------------------------- #
# Mode 3: Settle
# --------------------------------------------------------------------------- #

def mode_settle(client):
    print("\n  -- COST BASIS: SETTLE --\n")

    order_number = get_input("Order number")
    order = load_order(order_number, client)
    if not order:
        print(f"  No order found for '{order_number}'.")
        return

    current_state = order.get("cost_basis_state") or "estimated"
    if current_state == "settled":
        print(f"  Order {order_number} is already settled.")
        return

    order_id  = order["order_id"]
    li_ids    = get_line_item_ids(order_id, client)
    existing  = count_existing_inventory(li_ids, client)
    gwp_data  = load_gwp_data(order_id, client)

    print(f"\n  Order:           {order['retailer']} #{order_number}")
    print(f"  Current State:   {current_state}")
    print(f"  Inventory Units: {existing}")

    if existing == 0:
        print("\n  WARNING: No inventory units found. Run Mode 1 first.")
        return

    # Check for pending GWP items (12-month provisional window)
    pending_gwp = [g for g in gwp_data.values() if g.get("status") == "pending"]
    if pending_gwp:
        print(f"\n  NOTE: {len(pending_gwp)} GWP item(s) still pending.")
        print("  Settling now means any future GWP proceeds will create a P&L")
        print("  adjustment entry, NOT a cost basis recalculation.")

    # Show current per-set summary
    inv_units = (
        client.table("inventory")
        .select("set_name, set_number, cost_basis")
        .eq("user_id", PHASE_1_USER_ID)
        .in_("line_item_id", li_ids)
        .execute()
    ).data or []

    by_set: dict[str, dict] = {}
    for u in inv_units:
        sname = u.get("set_name") or "Unknown"
        if sname not in by_set:
            by_set[sname] = {
                "set_number": u.get("set_number") or "",
                "count":      0,
                "cost":       float(u.get("cost_basis") or 0),
            }
        by_set[sname]["count"] += 1

    print()
    for sname, info in by_set.items():
        neg = "  *" if info["cost"] < 0 else ""
        print(f"  {sname:<36} x{info['count']}  ${info['cost']:.4f}/unit{neg}")

    print(f"\n  Settling locks cost_basis_state → settled (irreversible).")
    if not get_yes_no("  Confirm settle?"):
        print("  Cancelled.")
        return

    client.table("orders").update(
        {"cost_basis_state": "settled"}
    ).eq("order_id", order_id).execute()
    print(f"\n  OK: Order {order_number} cost basis settled and locked.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    print("\n" + "=" * 60)
    print("  RESELL OS — AGENT 08: COST BASIS ENGINE")
    print("=" * 60)
    print("\n  1  Compute & Write  — calculate all layers, write to inventory")
    print("  2  Review           — inspect cost basis records")
    print("  3  Settle           — lock cost basis (provisional → settled)")
    print()

    mode   = get_input("Select mode (1/2/3)")
    client = get_client()

    if mode == "1":
        mode_compute(client)
    elif mode == "2":
        mode_review(client)
    elif mode == "3":
        mode_settle(client)
    else:
        print(f"  Unknown mode '{mode}'. Enter 1, 2, or 3.")


if __name__ == "__main__":
    main()
