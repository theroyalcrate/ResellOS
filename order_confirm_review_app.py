"""
ResellOS - Bulk Order Confirm & Cost Basis Review (Streamlit)
================================================================
Built 2026-09-15 after discovering 665 of 674 orders were sitting in
order_status='pending_review' with cost basis never computed -- Agent 01E
(capture_queue_promotion) had actually been run (592 promoted, 22
discarded, correcting a stale SESSION_LOG note), but nothing ever walked
the resulting orders through confirm + cost basis. agent_08_cost_basis.py
never gates on order_status at all (grep-verified), so this tool bundles
"confirm" and "compute cost basis" into one action -- matching what
DECISION 017 always intended the two to do together, even though the CLI
never enforced it.

Live-verified 2026-09-15, across this entire 665-order backlog:
  - rewards_applied > 0:  0 orders
  - cashback rows:        0 orders
  - gwp table rows:       0 orders  (982 GWP *line items* exist across 597
                                      orders, but none has a gwp table row
                                      yet -- see Layer 5 note below)
  - existing inventory:   0 orders  (nothing here has ever had cost basis
                                      run against it)
  - cancelled line items: 1 order   (excluded from inventory write below --
                                      see the cancelled-item note)
So Layers 3 and 4 are always $0 for this whole backlog, and Layer 5 always
takes agent_08's own safe "pending / $0 proceeds this run" default. Only
Layer 1 (invoice cost + tax) and Layer 2 (gift card) ever actually vary
order to order here.

Decisions this tool encodes (all Josh's, 2026-09-15):
  - Layer 2 (gift card savings) = $0. No gift_cards row is debited and no
    gift_card_assignments row is written -- "skip linkage for now." 458 of
    665 orders have gift_card_applied > 0; it stays on the order as a
    historical fact, unlinked. Correct an individual order later via
    order_lifecycle.py (reopen -> link the real card in agent_05 -> "2.
    Correct the gift card amount applied" if needed -> re-confirm), then
    re-run agent_08_cost_basis.py Mode 1 to recompute (it prompts to
    overwrite the existing $0-linkage units this tool wrote).
  - received_date defaults to the order's own order_date, not today --
    these are historical backfilled orders, not shipments arriving today.
  - cost_basis_state is always written as "provisional," never "settled" --
    freely correctable via order_lifecycle.py's reopen/re-confirm cycle
    (ADR-019's settle gate is untouched; settling still happens separately
    via agent_08_cost_basis.py Mode 3).

Reuses agent_08_cost_basis.py's compute_cost_records() (pure, already
shared math) and load_gwp_treatment() directly rather than re-deriving the
cost formula here. Does NOT import mode_compute()'s write tail -- that
function is input()-driven end to end and isn't safely callable from
Streamlit, so the inventory-write + order-update here is a deliberate,
narrow re-implementation of that same tail (see confirm_and_write()).

Known pre-existing gap surfaced while building this (not fixed here,
flagged for Josh): agent_08_cost_basis.py's compute_cost_records() doesn't
filter out item_status='cancelled' line items, so a cancelled item (which
keeps its original quantity even though line_total is zeroed per ADR-029)
would still generate quantity inventory units at $0 cost through the CLI
today. This tool excludes cancelled items from its own inventory write and
routes the one affected order (of 665) into the "needs a look" bucket
below rather than silently reproducing that behavior.

Run:  streamlit run order_confirm_review_app.py
"""

import random
from datetime import date

import httpx
import streamlit as st

from db_client import get_client, PHASE_1_USER_ID
from agent_08_cost_basis import compute_cost_records, load_gwp_treatment
from order_validators import check_gwp_price_consistency, check_line_items_reconcile


st.set_page_config(page_title="ResellOS -- Confirm & Cost Basis", layout="wide")


@st.cache_resource
def _client():
    # Same keep-alive workaround as gift_card_import_review_app.py -- a
    # long-lived Streamlit session can outlast Supabase's idle connection
    # timeout, and get_client()'s default httpx session is tuned for a
    # short CLI run, not this.
    client = get_client()
    old = client.postgrest.session
    client.postgrest.session = httpx.Client(
        base_url=old.base_url,
        headers=dict(old.headers),
        verify=False,
        follow_redirects=True,
        http2=True,
        limits=httpx.Limits(max_keepalive_connections=0),
        timeout=httpx.Timeout(30.0),
    )
    return client


def _reconnect_button(error):
    st.error(
        f"Lost the connection to Supabase for a moment ({type(error).__name__}). "
        "This is usually transient -- click below to reconnect."
    )
    if st.button("Reconnect and retry"):
        _client.clear()
        st.rerun()
    st.stop()


def _reload():
    st.session_state["reload_token"] = st.session_state.get("reload_token", 0) + 1


def _flash(kind, message):
    st.session_state["flash"] = (kind, message)


# --------------------------------------------------------------------------- #
# Data loading (paginated -- 665 orders / ~2550 line items exceeds
# PostgREST's default 1000-row page)
# --------------------------------------------------------------------------- #

def _fetch_all_pages(query_builder, page_size=1000):
    rows = []
    start = 0
    while True:
        result = query_builder().range(start, start + page_size - 1).execute()
        batch = result.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows


@st.cache_data(ttl=300)
def load_pending_orders_cached(_client, token):
    return _fetch_all_pages(
        lambda: (
            _client.table("orders")
            .select("*")
            .eq("user_id", PHASE_1_USER_ID)
            .eq("order_status", "pending_review")
            .order("order_date")
        )
    )


@st.cache_data(ttl=300)
def load_all_line_items_cached(_client, token):
    # Fetched for the whole user rather than .in_()'d by 665 order_ids --
    # a URL with 665 UUIDs risks hitting PostgREST/proxy URL-length limits,
    # and the user's full line_items table (~2.6k rows) is cheap either way.
    return _fetch_all_pages(
        lambda: _client.table("line_items").select("*").eq("user_id", PHASE_1_USER_ID)
    )


# --------------------------------------------------------------------------- #
# Cost basis preview (Layers 1-5, reusing agent_08's pure compute_cost_records)
# --------------------------------------------------------------------------- #

def _compute_records_and_net_cost(items, tax_paid, rewards_applied, gwp_treatment):
    """
    Single source of truth for the (records, net_economic_cost) pair, used
    by both compute_preview() and the flagged-bucket per-order override
    path in _render_app() -- so an overridden tax_paid can never produce a
    displayed net_economic_cost that disagrees with what confirm_and_write()
    actually writes to inventory (a gap a review pass on 2026-09-15 flagged
    when this was two separately hand-written formulas). gc_savings and
    cashback_amount are always $0 for this entire backlog (see module
    docstring) so they're hardcoded here, not threaded through as params.
    """
    records = compute_cost_records(
        items, tax_paid, 0.0, rewards_applied, 0.0, {}, gwp_treatment,
    )
    invoice_cost = round(sum(float(it["line_total"]) for it in items if not it.get("is_gwp")), 2)
    net_economic_cost = round(invoice_cost + tax_paid - rewards_applied, 2)
    return records, invoice_cost, net_economic_cost


def compute_preview(order, items, gwp_treatment):
    """
    Mirrors agent_08_cost_basis.py's mode_compute() Layer 1-5 gather step,
    but with every input defaulted per this backlog's live-verified shape
    (see module docstring) instead of prompted -- no rewards, no cashback,
    no gift card linkage this pass, every GWP item pending/$0.

    Also runs two of order_validators.py's pure, no-DB-call checks --
    check_gwp_price_consistency (is_gwp disagreeing with unit_price) and
    check_line_items_reconcile (paid line items vs. the order's subtotal,
    which overlaps this function's own subtotal_mismatch check but is kept
    for parity with what order_lifecycle.py's confirm_order() runs). NOT
    running find_cross_shipment_duplicates() here: that check's whole point
    is "does a NEW write collide with something already in the DB under a
    different entry_method" -- called on an order's own already-persisted
    line items (this backlog's only situation) it just compares those rows
    against themselves, and a first attempt at wiring this in (2026-09-15)
    confirmed that in practice: it flagged 120 of 665 orders purely because
    orders.entry_method and shipments.entry_method don't share a vocabulary,
    not because of any real duplicate. Also not gating on
    check_missing_set_numbers -- that check's own docstring calls it
    "purely informational," unrelated to cost basis.
    """
    cancelled_items = [it for it in items if it.get("item_status") == "cancelled"]
    active_items = [it for it in items if it.get("item_status") != "cancelled"]
    paid_items = [it for it in active_items if not it.get("is_gwp")]
    gwp_items = [it for it in active_items if it.get("is_gwp")]

    tax_paid = float(order.get("tax_paid") or 0)
    gc_applied = float(order.get("gift_card_applied") or 0)
    rewards_applied = float(order.get("rewards_applied") or 0)

    records, invoice_cost, net_economic_cost = _compute_records_and_net_cost(
        active_items, tax_paid, rewards_applied, gwp_treatment
    )
    subtotal = float(order.get("subtotal") or 0)
    subtotal_mismatch = round(invoice_cost, 2) != round(subtotal, 2)

    try:
        validator_warnings = (
            check_gwp_price_consistency(active_items)
            + check_line_items_reconcile(active_items, order.get("subtotal"))
        )
    except Exception as e:
        validator_warnings = [{"message": f"Validator checks could not run ({e})."}]

    needs_review = (
        (order.get("reconciliation_status") or "") != "reconciled"
        or subtotal_mismatch
        or not paid_items
        or bool(cancelled_items)
        or bool(validator_warnings)
    )

    return {
        "records": records,
        "paid_items": paid_items,
        "gwp_items": gwp_items,
        "cancelled_items": cancelled_items,
        "invoice_cost": invoice_cost,
        "tax_paid": tax_paid,
        "gc_applied": gc_applied,
        "net_economic_cost": net_economic_cost,
        "subtotal": subtotal,
        "subtotal_mismatch": subtotal_mismatch,
        "validator_warnings": validator_warnings,
        "needs_review": needs_review,
    }


# --------------------------------------------------------------------------- #
# Write: confirm order + write inventory (mirrors agent_08's write tail)
# --------------------------------------------------------------------------- #

def confirm_and_write(client, order, preview, received_date, state="provisional"):
    """
    Writes one inventory unit per (record, quantity) -- paid items at their
    computed cost_per_unit, GWP items at $0 -- exactly like agent_08's CLI
    write loop, then flips the order to confirmed with the given
    cost_basis_state. Never touches gift_card_assignments/gift_cards
    (Josh's skip-linkage decision) and never marks an order settled.

    Idempotency guard (mirrors agent_08_cost_basis.py's own
    count_existing_inventory check before its write, added after a
    2026-09-15 review flagged its absence as CRITICAL): refuses to write if
    this order isn't still pending_review, or if inventory already exists
    for any of its line items -- so a double click or a stale Streamlit
    rerun can't double-insert units. If the order-status update fails after
    inventory was already inserted, the inserted units are rolled back
    (deleted) rather than left as a silent partial write.

    Never raises -- returns {"ok": False, "message": ...} on any failure,
    naming the order so it's easy to find and fix manually.
    """
    order_id = order["order_id"]
    order_number = order.get("order_number") or order_id
    records = preview["records"]
    if not records:
        return {"ok": False, "message": f"Order {order_number}: no line items to write inventory for."}

    try:
        current = client.table("orders").select("order_status").eq("order_id", order_id).execute()
    except Exception as e:
        return {"ok": False, "message": f"Order {order_number}: could not verify current status ({e}) -- not written."}
    current_rows = current.data or []
    current_status = current_rows[0].get("order_status") if current_rows else None
    if current_status != "pending_review":
        return {
            "ok": False,
            "message": f"Order {order_number}: already {current_status!r} -- skipped, nothing written.",
        }

    li_ids = [r["line_item_id"] for r in records]
    try:
        existing_inv = (
            client.table("inventory")
            .select("unit_id")
            .eq("user_id", PHASE_1_USER_ID)
            .in_("line_item_id", li_ids)
            .execute()
        )
    except Exception as e:
        return {"ok": False, "message": f"Order {order_number}: could not check existing inventory ({e}) -- not written."}
    if existing_inv.data:
        return {
            "ok": False,
            "message": (
                f"Order {order_number}: {len(existing_inv.data)} inventory unit(s) already exist "
                "for this order -- skipped to avoid duplicating."
            ),
        }

    inventory_rows = []
    for r in records:
        cost = round(r["cost_per_unit"], 2)
        for _ in range(r["quantity"]):
            inventory_rows.append({
                "user_id": PHASE_1_USER_ID,
                "line_item_id": r["line_item_id"],
                "set_number": r["set_number"],
                "set_name": r["set_name"],
                "cost_basis": cost,
                "tax_paid_allocated": 0,
                "received_date": received_date.isoformat(),
                "status": "in_stock",
            })

    try:
        inv_result = client.table("inventory").insert(inventory_rows).execute()
    except Exception as e:
        return {"ok": False, "message": f"Order {order_number}: inventory insert failed ({e})."}
    if not inv_result.data:
        return {"ok": False, "message": f"Order {order_number}: inventory insert returned no rows."}

    update_error = None
    upd = None
    try:
        upd = (
            client.table("orders")
            .update({"order_status": "confirmed", "cost_basis_state": state})
            .eq("order_id", order_id)
            .execute()
        )
    except Exception as e:
        update_error = e

    if update_error is not None or not upd.data:
        # Roll back the inventory we just inserted rather than leave a
        # partial write -- a still-pending_review order with no inventory
        # is a safe, recognizable state to retry from; a confirmed-looking
        # write with orphaned inventory and no status flip is not.
        unit_ids = [r["unit_id"] for r in inv_result.data]
        try:
            client.table("inventory").delete().in_("unit_id", unit_ids).execute()
            rollback_note = "inventory rolled back"
        except Exception as rollback_error:
            rollback_note = (
                f"ROLLBACK ALSO FAILED ({rollback_error}) -- "
                f"{len(unit_ids)} orphaned inventory unit(s), fix manually"
            )
        reason = f"({update_error})" if update_error is not None else "(update returned no rows)"
        return {
            "ok": False,
            "message": f"Order {order_number}: order status update failed {reason} -- {rollback_note}.",
        }

    return {"ok": True, "units": len(inv_result.data)}


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #

def main():
    client = _client()
    try:
        _render_app(client)
    except httpx.TransportError as e:
        _reconnect_button(e)


def _render_app(client):
    st.title("ResellOS -- Bulk Order Confirm & Cost Basis")
    st.caption(
        "Confirms pending_review orders and computes cost basis in one step. "
        "Safe to keep using for any new pending_review orders going forward."
    )

    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)

    with st.expander("How this works / what's being assumed", expanded=False):
        st.markdown(
            "- **Layer 1** (invoice + tax) is computed from each order's paid line items, "
            "exactly like the CLI.\n"
            "- **Layer 2** (gift card savings) is **$0 -- no card is debited**, per the "
            "2026-09-15 'skip linkage for now' decision. `gift_card_applied` stays on the "
            "order as a historical fact. Fix an individual order later via "
            "`order_lifecycle.py` (reopen -> link the real card -> re-confirm), then re-run "
            "`agent_08_cost_basis.py` Mode 1 to recompute.\n"
            "- **Layer 3** (rewards) and **Layer 4** (cashback) are $0 for this entire "
            "backlog -- verified live, no exceptions.\n"
            "- **Layer 5** (GWP proceeds) defaults every GWP item to **pending / $0 this "
            "pass** -- the same safe default the CLI uses when a GWP item has no `gwp` "
            "table row yet. Once one actually sells, re-run `agent_08_cost_basis.py` Mode 1 "
            "on that order to record real proceeds.\n"
            "- `received_date` defaults to the order's own **order_date**, not today.\n"
            "- Cost basis is written as **provisional**, never `settled` -- freely "
            "correctable via the reopen/re-confirm cycle."
        )

    token = st.session_state.get("reload_token", 0)
    orders = load_pending_orders_cached(client, token)
    if not orders:
        st.success("Nothing in pending_review -- the backlog is clear.")
        return

    items_all = load_all_line_items_cached(client, token)
    items_by_order = {}
    for it in items_all:
        items_by_order.setdefault(it["order_id"], []).append(it)

    gwp_treatment = load_gwp_treatment(client)

    previews = {
        o["order_id"]: compute_preview(o, items_by_order.get(o["order_id"], []), gwp_treatment)
        for o in orders
    }

    search = st.text_input("Jump to an order (order number or retailer contains)", "").strip().lower()
    if search:
        orders = [
            o for o in orders
            if search in (o.get("order_number") or "").lower()
            or search in (o.get("retailer") or "").lower()
        ]

    clean = [o for o in orders if not previews[o["order_id"]]["needs_review"]]
    flagged = [o for o in orders if previews[o["order_id"]]["needs_review"]]

    c1, c2, c3 = st.columns(3)
    c1.metric("Pending review (shown)", len(orders))
    c2.metric("Clean -- one click", len(clean))
    c3.metric("Flagged -- needs a look", len(flagged))

    st.divider()

    # ----------------------------------------------------------------- #
    # Clean bucket: reconciled, subtotal matches, no cancelled items --
    # nothing here needs a judgment call, so it's a single bulk action.
    # ----------------------------------------------------------------- #
    st.subheader(f"Clean: {len(clean)} order(s)")
    st.caption(
        "reconciliation_status == 'reconciled', paid line items sum to the order's "
        "subtotal, and no cancelled items -- no discretionary input for any of these."
    )
    if clean:
        table_rows = []
        for o in clean:
            p = previews[o["order_id"]]
            table_rows.append({
                "Order #": o.get("order_number"),
                "Retailer": o.get("retailer"),
                "Date": str(o.get("order_date")),
                "Items": len(p["paid_items"]),
                "GWP items": len(p["gwp_items"]),
                "Invoice cost": p["invoice_cost"],
                "Tax": p["tax_paid"],
                "Gift card applied (staying unlinked)": p["gc_applied"],
                "Net cost basis": p["net_economic_cost"],
            })
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        with st.expander("Spot-check a few before bulk-confirming"):
            max_n = min(10, len(clean))
            sample_n = st.slider("Sample size", 1, max_n, min(3, max_n))
            if st.button("Show random sample"):
                st.session_state["spot_sample"] = [o["order_id"] for o in random.sample(clean, sample_n)]
            for oid in st.session_state.get("spot_sample", []):
                o = next((x for x in clean if x["order_id"] == oid), None)
                if not o:
                    continue
                p = previews[oid]
                st.write(f"**{o.get('retailer')} #{o.get('order_number')}** ({o.get('order_date')})")
                st.table([
                    {
                        "Set": r["set_name"], "Qty": r["quantity"],
                        "Line total": r.get("line_total", 0.0),
                        "$/unit": r["cost_per_unit"], "GWP": r["is_gwp"],
                    }
                    for r in p["records"]
                ])

        ready = st.checkbox(
            f"I've spot-checked a sample -- confirm & compute cost basis for all {len(clean)} clean orders"
        )
        if ready and st.button(f"Confirm & compute cost basis for {len(clean)} clean orders", type="primary"):
            progress = st.progress(0.0, text="Starting...")
            ok_count, failures = 0, []
            for i, o in enumerate(clean):
                p = previews[o["order_id"]]
                received = date.fromisoformat(str(o["order_date"]))
                result = confirm_and_write(client, o, p, received)
                if result["ok"]:
                    ok_count += 1
                else:
                    failures.append(result["message"])
                progress.progress((i + 1) / len(clean), text=f"{i + 1}/{len(clean)}")
            msg = f"Confirmed {ok_count} of {len(clean)} orders."
            if failures:
                msg += f" {len(failures)} failed:\n\n" + "\n".join(f"- {m}" for m in failures)
                _flash("error", msg)
            else:
                _flash("success", msg)
            _reload()
            st.rerun()
    else:
        st.caption("None right now.")

    st.divider()

    # ----------------------------------------------------------------- #
    # Flagged bucket: one-by-one, with the reason shown up front and
    # tax/received-date overridable before confirming.
    # ----------------------------------------------------------------- #
    st.subheader(f"Needs a look: {len(flagged)} order(s)")
    st.caption(
        "Not reconciled yet, paid items don't sum to the order's subtotal, has a "
        "cancelled item, or has no paid line items at all."
    )
    for o in flagged:
        oid = o["order_id"]
        p = previews[oid]
        items = items_by_order.get(oid, [])
        reasons = []
        if (o.get("reconciliation_status") or "") != "reconciled":
            reasons.append(f"reconciliation_status={o.get('reconciliation_status')!r}")
        if p["subtotal_mismatch"]:
            reasons.append(f"paid items ${p['invoice_cost']:.2f} != subtotal ${p['subtotal']:.2f}")
        if not p["paid_items"]:
            reasons.append("no paid line items")
        if p["cancelled_items"]:
            reasons.append(f"{len(p['cancelled_items'])} cancelled item(s) excluded from inventory")
        if p["validator_warnings"]:
            reasons.append(f"{len(p['validator_warnings'])} data-quality warning(s)")

        label = f"{o.get('retailer')} #{o.get('order_number')} ({o.get('order_date')}) -- {', '.join(reasons)}"
        with st.expander(label):
            st.table([
                {
                    "Set": it.get("set_name"), "Qty": it.get("quantity"),
                    "Line total": it.get("line_total", 0.0),
                    "Status": it.get("item_status") or "active",
                    "GWP": bool(it.get("is_gwp")),
                }
                for it in items
            ])
            if p["validator_warnings"]:
                st.warning("\n".join(f"- {w['message']}" for w in p["validator_warnings"]))

            col1, col2 = st.columns(2)
            with col1:
                tax_override = st.number_input(
                    "Tax paid ($)", value=float(p["tax_paid"]), step=0.01, key=f"tax_{oid}",
                )
            with col2:
                received_override = st.date_input(
                    "Received date", value=date.fromisoformat(str(o["order_date"])), key=f"recv_{oid}",
                )
            if p["gc_applied"]:
                st.caption(
                    f"Gift card applied: ${p['gc_applied']:.2f} -- staying unlinked "
                    "per the skip-linkage decision."
                )

            active_items = [it for it in items if it.get("item_status") != "cancelled"]
            _, live_invoice, live_net = _compute_records_and_net_cost(
                active_items, tax_override, float(o.get("rewards_applied") or 0), gwp_treatment,
            )
            st.caption(f"Invoice cost ${live_invoice:.2f} + tax ${tax_override:.2f} = net cost basis ${live_net:.2f}")

            if st.button("Confirm & compute cost basis for this order", key=f"confirm_{oid}"):
                records, _, net_economic_cost = _compute_records_and_net_cost(
                    active_items, tax_override, float(o.get("rewards_applied") or 0), gwp_treatment,
                )
                p_override = dict(p, records=records, tax_paid=tax_override,
                                   net_economic_cost=net_economic_cost)
                result = confirm_and_write(client, o, p_override, received_override)
                if result["ok"]:
                    _flash("success", f"Order {o.get('order_number')}: confirmed, {result['units']} unit(s) written.")
                else:
                    _flash("error", result["message"])
                _reload()
                st.rerun()


if __name__ == "__main__":
    main()
