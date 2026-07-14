"""
ResellOS - Cost Basis Status Report

Read-only report answering one question: which orders need a human to go run
Agent 08 (agent_08_cost_basis.py)?

Why this exists (2026-06-21): DECISION 017 deliberately gates cost basis
behind explicit user confirmation — it should never run automatically on an
order. That's the right call for a financial system, but it has a side
effect: nothing currently *reminds* anyone that an order is ready. We found
this directly — order T487170400 had its GWP fully sold and settled back on
2026-05-27, but cost_basis_state still read "estimated" a month later,
because Mode 1 (compute & write to inventory) was simply never run on it.
That's not a bug in the state machine; there isn't one to advance on its
own — it's a missing reminder. This script is that reminder, not an
auto-advancer: it never changes any data, it only reports.

What it flags, per order not yet settled:
  - "never processed"   — line items exist, no inventory yet (Mode 1 hasn't
    run at all)
  - "ready to settle"   — inventory exists, state is still
    provisional/estimated, and every GWP + cashback item linked to the order
    has resolved (GWP not pending, cashback not pending)
  - "waiting on GWP"    — at least one GWP item is still pending
  - "waiting on cashback" — at least one cashback transaction is still pending
"""

from db_client import get_client, PHASE_1_USER_ID


def build_report(client=None) -> list[dict]:
    client = client if client is not None else get_client()

    orders = (
        client.table("orders")
        .select("order_id, order_number, retailer, order_date, cost_basis_state")
        .eq("user_id", PHASE_1_USER_ID)
        .neq("cost_basis_state", "settled")
        .execute()
    ).data or []

    rows = []
    for order in orders:
        order_id = order["order_id"]

        li_result = (
            client.table("line_items")
            .select("line_item_id, is_gwp")
            .eq("order_id", order_id)
            .execute()
        )
        line_items = li_result.data or []
        li_ids = [li["line_item_id"] for li in line_items]
        if not li_ids:
            continue

        inv_count = len(
            (
                client.table("inventory")
                .select("unit_id")
                .eq("user_id", PHASE_1_USER_ID)
                .in_("line_item_id", li_ids)
                .execute()
            ).data
            or []
        )

        gwp_li_ids = [li["line_item_id"] for li in line_items if li.get("is_gwp")]
        gwp_pending = 0
        if gwp_li_ids:
            gwp_result = (
                client.table("gwp")
                .select("status")
                .in_("line_item_id", gwp_li_ids)
                .execute()
            )
            gwp_pending = sum(1 for g in (gwp_result.data or []) if g.get("status") == "pending")

        cb_result = (
            client.table("cashback_transactions")
            .select("status")
            .eq("order_id", order_id)
            .execute()
        )
        cb_pending = sum(1 for cb in (cb_result.data or []) if cb.get("status") == "pending")

        # Note: only pending GWP actually blocks settlement in agent_08
        # (mode_compute forces state="provisional" when GWP is pending —
        # see M2). Pending cashback does NOT block settling; agent_08 just
        # excludes it from the calculation and prints a note. So pending
        # cashback is surfaced here as a heads-up, not a "waiting on" status.
        if inv_count == 0:
            status = "never processed — run Mode 1"
        elif gwp_pending:
            status = f"waiting on GWP ({gwp_pending} pending) — settlement is blocked until this resolves"
        else:
            status = "ready to settle — run Mode 3" if order["cost_basis_state"] == "provisional" \
                else "ready — run Mode 1 to set provisional/settled"
            if cb_pending:
                status += f"  [note: {cb_pending} cashback txn(s) still pending — would be excluded if you settle now]"

        rows.append({
            "order_number": order["order_number"],
            "retailer": order["retailer"],
            "order_date": order["order_date"],
            "cost_basis_state": order["cost_basis_state"],
            "status": status,
        })

    return rows


def print_report(rows: list[dict]) -> None:
    if not rows:
        print("  No unsettled orders found — nothing to report.")
        return
    print(f"\n  -- COST BASIS STATUS REPORT -- {len(rows)} unsettled order(s)\n")
    for r in rows:
        print(
            f"  {r['order_number']:<14} {r['retailer']:<10} {r['order_date']:<12} "
            f"[{r['cost_basis_state']:<11}]  {r['status']}"
        )
    print()


if __name__ == "__main__":
    print_report(build_report())
