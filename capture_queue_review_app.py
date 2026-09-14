"""
ResellOS - Capture Queue Review Tool (Streamlit)
=================================================
ADR-028: minimal, purpose-built review screen for capture_queue -> order
promotion, plus bulk buy_reason/purchase_trigger tagging on orders.

Does NOT reimplement capture_queue_promotion.py's order-building logic --
imports and reuses its private helpers (_build_order, _find_existing_order,
_write_shipments) directly, plus agent_02_order_entry.write_order() and
order_validators.run_all_checks(), so this is a new front end on the same
proven backend contract, not a new data path. capture_queue_promotion.py's
interactive CLI is untouched -- confirmed permanent scriptable fallback per
ADR-028's Resolution (e.g. the merge-shipped-capture and duplicate-discard
flows for messy rows, which this tool deliberately does NOT attempt to
replicate -- those stay "Needs CLI" here).

Run:  streamlit run capture_queue_review_app.py
"""

from datetime import datetime, timezone

import httpx
import streamlit as st

from db_client import get_client, PHASE_1_USER_ID
from capture_queue_promotion import _build_order, _find_existing_order, _write_shipments
from agent_02_order_entry import write_order
from order_validators import run_all_checks


st.set_page_config(page_title="ResellOS -- Capture Queue Review", layout="wide")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


@st.cache_resource
def _client():
    client = get_client()
    # get_client()'s httpx.Client is tuned for a short-lived CLI process
    # (capture_queue_promotion.py): one connection, used for a few seconds,
    # then the process exits, so a stale pooled connection never has a
    # chance to matter. @st.cache_resource keeps this same client alive for
    # Josh's whole browser session -- possibly many minutes between clicks
    # while he reads line items -- so a keep-alive connection can go stale
    # (Supabase's edge closes idle connections) and Windows throws
    # WinError 10035 (a non-blocking socket op on a half-dead socket)
    # instead of transparently reconnecting when httpx tries to reuse it.
    # Disabling keep-alive reuse trades a few ms of TCP/TLS handshake per
    # click for never touching a stale connection -- worth it at this
    # request volume. db_client.py itself is left untouched since every
    # other script that imports it is a short CLI run where this never bites.
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
    """Shown when a Supabase call fails with a transport-level error (a
    dropped/stale connection, a network blip) instead of a raw traceback --
    Josh isn't a Python developer and a stack trace tells him nothing
    actionable. One click clears the cached client and retries."""
    st.error(
        f"Lost the connection to Supabase for a moment ({type(error).__name__}). "
        "This is usually transient -- click below to reconnect."
    )
    if st.button("Reconnect and retry"):
        _client.clear()
        st.rerun()
    st.stop()


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def load_pending(client):
    result = (
        client.table("capture_queue")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("status", "pending")
        .order("captured_at")
        .execute()
    )
    return result.data or []


def load_progress_counts(client):
    cq = (
        client.table("capture_queue")
        .select("status")
        .eq("user_id", PHASE_1_USER_ID)
        .execute()
        .data
        or []
    )
    counts = {"pending": 0, "promoted": 0, "discarded": 0}
    for row in cq:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    untagged = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .is_("buy_reason", "null")
        .is_("purchase_trigger", "null")
        .execute()
    )
    counts["untagged_orders"] = len(untagged.data or [])
    return counts


def evaluate_row(client, row):
    """Non-interactive dry run of what capture_queue_promotion.py's promote()
    would do -- returns whether this row is a clean quick-promote candidate,
    a duplicate that needs the CLI, or has validator warnings to show."""
    raw = row.get("raw_data") or {}
    line_items = raw.get("line_items") or []
    order_number = raw.get("order_number") or row.get("order_number")

    # Some agent_1d/1e PDF-backfill rows come from a PDF that failed to parse
    # entirely -- no order_number, no line items, no total, nothing to build
    # an order from. Distinct from "needs_cli" (a real duplicate) and from
    # "flagged" (a real order with a data-quality warning): there is no order
    # here at all, so the only sane action is discard.
    if not line_items and not order_number and not row.get("total"):
        return {
            "kind": "empty",
            "reason": (
                "No line items, order number, or total captured -- looks like a PDF that "
                "failed to parse (see parse errors below, if any). Nothing here to promote."
            ),
            "parse_errors": raw.get("_parse_errors") or [],
        }

    existing = _find_existing_order(client, order_number)
    if existing:
        # Two-capture-stage design (ADR-023 addendum 2026-08-27): a
        # "checkout" capture (order_confirmation.js) creates the order, then
        # a "shipped" capture (content.js, the order-details page) arrives
        # later with tracking numbers/card last4s the checkout page didn't
        # have yet. Once the checkout capture is promoted, that second
        # capture is EXPECTED to show back up here still pending -- it's not
        # a re-appearance of the same row, it's a second row for the same
        # order_number that was always going to need this extra step. This
        # used to dead-end at "Needs CLI" (2026-08-21) with no explanation
        # of what that meant or why it kept happening -- 2026-09-14: both
        # real cases behind that label are now handled directly here.
        capture_stage = raw.get("capture_stage") or "shipped"
        if capture_stage == "shipped":
            incoming_items = raw.get("line_items") or []
            existing_items = (
                client.table("line_items")
                .select("line_item_id")
                .eq("order_id", existing["order_id"])
                .execute()
            ).data or []
            return {
                "kind": "shipped_merge",
                "reason": (
                    f"This is the 'shipped' (order-details) capture for order {order_number} -- "
                    f"the 'checkout' capture for the same order was already promoted to order_id "
                    f"{existing['order_id']}. Merging just adds tracking numbers and payment-card "
                    f"identities onto that existing order; it never touches its line items or totals."
                ),
                "existing_order_id": existing["order_id"],
                "existing_order_status": existing.get("order_status"),
                "item_count_mismatch": (
                    len(incoming_items) != len(existing_items) if incoming_items and existing_items else False
                ),
                "existing_item_count": len(existing_items),
                "incoming_item_count": len(incoming_items),
                "raw": raw,
            }
        return {
            "kind": "duplicate_checkout",
            "reason": (
                f"A second 'checkout' capture for order {order_number} -- an order already exists "
                f"(order_id {existing['order_id']}, status={existing.get('order_status')}). This "
                f"almost always means the same order was captured twice, not a new order."
            ),
            "existing_order_id": existing["order_id"],
        }

    order, items, rewards_earned = _build_order(raw, row)
    warnings = run_all_checks(
        order_id=None,
        items=items,
        expected_subtotal=round(order["subtotal"] - order["discount_total"], 2),
        entry_method="capture_queue_promotion",
        client=client,
    )
    return {
        "kind": "clean" if not warnings else "flagged",
        "order": order,
        "items": items,
        "warnings": warnings,
        "rewards_earned": rewards_earned,
    }


# --------------------------------------------------------------------------- #
# Promotion / discard -- mirrors capture_queue_promotion.py's non-interactive
# core exactly (same write_order() call, same capture_queue update, same
# _write_shipments() call), just without the interactive input-gathering.
# --------------------------------------------------------------------------- #

def promote_row(client, row, order, items, buy_reason=None, purchase_trigger=None):
    order = dict(order)
    order["buy_reason"] = buy_reason
    order["purchase_trigger"] = purchase_trigger
    order["notes"] = (
        f"Promoted from capture_queue ({row['capture_id']}) via the ADR-028 review tool. "
        f"Gift card / cashback tender detail not captured here -- use "
        f"capture_queue_promotion.py's CLI for a row where that detail needs recording."
    )

    # write_order() has its own get_yes_no() fallback if order_number already
    # exists in `orders` -- that would call input() and hang a Streamlit
    # server process. Replicate its exact pre-check here so that path is
    # provably unreachable from this function.
    dup = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order["order_number"])
        .execute()
    )
    if dup.data:
        return {
            "ok": False,
            "message": (
                f"Order {order['order_number']} appeared in `orders` between listing and "
                f"promoting (race, or this row's evaluation is stale) -- use the CLI to resolve."
            ),
        }

    if not write_order(order, items, client):
        return {"ok": False, "message": "write_order() failed -- capture_queue row left as pending."}

    lookup = (
        client.table("orders")
        .select("order_id")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("order_number", order["order_number"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not lookup.data:
        return {
            "ok": False,
            "message": "Order written but could not be looked back up -- capture_queue row NOT updated, fix manually.",
        }
    new_order_id = lookup.data[0]["order_id"]

    client.table("capture_queue").update(
        {"status": "promoted", "promoted_order_id": new_order_id, "reviewed_at": _now_iso()}
    ).eq("capture_id", row["capture_id"]).execute()

    raw = row.get("raw_data") or {}
    _write_shipments(client, new_order_id, raw.get("shipments") or [])

    return {"ok": True, "order_id": new_order_id}


def discard_row(client, row, reason):
    client.table("capture_queue").update(
        {"status": "discarded", "review_note": reason, "reviewed_at": _now_iso()}
    ).eq("capture_id", row["capture_id"]).execute()


def merge_shipped_row(client, row, raw, existing_order_id):
    """Non-interactive counterpart to capture_queue_promotion.py's
    _merge_shipped_capture (added 2026-09-14, closing the 'Needs CLI'
    dead-end for this case). Adds tracking numbers (via _write_shipments)
    and payment-card identities from a 'shipped'-stage capture onto an
    order a 'checkout'-stage capture already created. Purely additive and
    safe -- never touches the existing order's line_items, totals, or any
    other field besides appending to notes -- so unlike promote/discard
    this doesn't need a confirmation step of its own."""
    payment_methods = raw.get("payment_methods") or []
    card_lines = [
        f"{pm.get('brand') or 'Gift card'} ...{pm.get('last4')}"
        for pm in payment_methods
        if pm.get("last4")
    ]

    _write_shipments(client, existing_order_id, raw.get("shipments") or [])

    if card_lines:
        current = (
            client.table("orders").select("notes").eq("order_id", existing_order_id).execute()
        ).data
        existing_notes = (current[0].get("notes") if current else None) or ""
        new_notes = (existing_notes + " " if existing_notes else "") + (
            f"[Shipped-stage merge {_now_iso()}] Payment identities: " + "; ".join(card_lines) + "."
        )
        client.table("orders").update({"notes": new_notes}).eq("order_id", existing_order_id).execute()

    client.table("capture_queue").update({
        "status": "promoted",
        "promoted_order_id": existing_order_id,
        "reviewed_at": _now_iso(),
    }).eq("capture_id", row["capture_id"]).execute()

    return {"ok": True, "order_id": existing_order_id, "card_lines": card_lines}


# --------------------------------------------------------------------------- #
# Retailer-aware quick-pick (ADR-028 Scope Refinement #4). Canonical retailer
# strings confirmed against agent_02_order_entry.py's _RETAILER_ALIASES and
# live `orders.retailer` values -- do not guess new ones without checking.
# --------------------------------------------------------------------------- #

FULL_BUY_REASONS = ["planned", "opportunistic", "promo_expiration"]
FULL_TRIGGERS = ["community_alert", "deal_software_alert", "self_discovered"]

# Retailers Josh named as realistically producing only two answers in
# practice (ADR-028). LEGO (and anything else not listed here) gets the
# full picker -- planned targeted buys and GWP-hunts are real for LEGO.
SIMPLE_QUICKPICK_RETAILERS = {"walmart", "macys", "target", "amazon"}


def apply_tag(client, order_ids, buy_reason, purchase_trigger):
    if not order_ids:
        return 0
    client.table("orders").update(
        {"buy_reason": buy_reason, "purchase_trigger": purchase_trigger}
    ).in_("order_id", order_ids).execute()
    return len(order_ids)


# --------------------------------------------------------------------------- #
# Inline line-item edits (is_gwp / set_number / cancelled) -- Josh found real
# rows where the capture got these wrong (a $0 GWP item not flagged as one, a
# missing set_number) with no way to fix them before promoting. The
# "Cancelled" checkbox (ADR-029 / migration 020, 2026-09-14) covers a
# related, recurring gap: a retailer cancels one item on the order after the
# fact (out of stock again) while still shipping everything else, including
# any GWP that item's presence qualified for -- the "GWP-hack" pattern,
# confirmed by Josh to recur 15-20+ times/year. This is usually only visible
# once a shipped-stage capture or tracking page shows fewer items than the
# order confirmation did, so review time (here) is the natural place to mark
# it, not entry time. Nothing else about the parsed order is editable yet
# (quantity/price edits would be the natural next increment if a similar gap
# shows up there).
# --------------------------------------------------------------------------- #

def _item_widget_keys(capture_id, idx):
    return (
        f"gwp_{capture_id}_{idx}",
        f"setnum_{capture_id}_{idx}",
        f"cancelled_{capture_id}_{idx}",
    )


def _apply_edits(capture_id, items):
    """Read this row's per-item edit widgets out of session_state and return
    a new items list with those edits applied. Safe to call both while
    rendering the row (right after its widgets are created) and later in the
    same script run (e.g. from the bulk-promote handler) -- once a Streamlit
    widget is created with a given key, session_state holds its live value
    for the rest of that run."""
    edited = []
    for idx, it in enumerate(items):
        gwp_key, setnum_key, cancelled_key = _item_widget_keys(capture_id, idx)
        new_it = dict(it)
        new_it["is_gwp"] = st.session_state.get(gwp_key, it["is_gwp"])
        raw_setnum = st.session_state.get(setnum_key, it.get("set_number") or "")
        new_it["set_number"] = raw_setnum.strip() or None
        is_cancelled = st.session_state.get(cancelled_key, it.get("item_status") == "cancelled")
        new_it["item_status"] = "cancelled" if is_cancelled else "received"
        if is_cancelled:
            # Never actually charged -- zero out regardless of the captured
            # price, same rule as agent_02/capture_queue_promotion (ADR-029).
            new_it["line_total"] = 0
            new_it["line_discount"] = 0
        edited.append(new_it)
    return edited


def _live_warnings(client, order, items):
    """Re-run the validator against possibly-edited items so the badge/warning
    display reflects fixes the reviewer just made, before they click Promote."""
    expected_subtotal = round(order["subtotal"] - sum(it["line_discount"] for it in items), 2)
    return run_all_checks(
        order_id=None,
        items=items,
        expected_subtotal=expected_subtotal,
        entry_method="capture_queue_promotion",
        client=client,
    )


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
    st.title("ResellOS -- Capture Queue Review")
    st.caption(
        "ADR-028 -- quick-promote clean orders, capture_queue holds the flagged ones. "
        "Bulk-tag buy_reason/purchase_trigger on the Tag Orders tab."
    )

    counts = load_progress_counts(client)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pending review", counts.get("pending", 0))
    c2.metric("Promoted", counts.get("promoted", 0))
    c3.metric("Discarded", counts.get("discarded", 0))
    c4.metric("Orders needing tags", counts.get("untagged_orders", 0))

    tab1, tab2 = st.tabs(["Review Queue", "Tag Orders"])
    with tab1:
        render_review_queue(client)
    with tab2:
        render_tag_orders(client)


def render_review_queue(client):
    rows = load_pending(client)
    if not rows:
        st.success("Nothing pending -- capture_queue is empty.")
        return

    if "evaluations" not in st.session_state:
        st.session_state.evaluations = {}

    st.write(f"**{len(rows)} row(s) pending review.**")
    st.caption(
        "Fix a mis-flagged GWP, a missing set number, or mark an item the retailer cancelled "
        "(ADR-029 -- 'GWP hack' pattern) inline before promoting. Edits here only affect what "
        "gets written to orders/line_items -- capture_queue's raw_data is untouched."
    )
    clean_capture_ids = []
    empty_capture_ids = []
    badge_map = {
        "clean": "\U0001F7E2 Clean",
        "flagged": "\U0001F7E1 Flagged",
        "needs_cli": "\U0001F534 Needs CLI",
        "empty": "⚪ Empty",
        "shipped_merge": "\U0001F535 Ready to merge",
        "duplicate_checkout": "\U0001F7E0 Likely duplicate",
    }

    for row in rows:
        capture_id = row["capture_id"]
        if capture_id not in st.session_state.evaluations:
            st.session_state.evaluations[capture_id] = evaluate_row(client, row)
        ev = st.session_state.evaluations[capture_id]

        raw = row.get("raw_data") or {}
        item_count = len(raw.get("line_items") or [])
        total = row.get("total")
        total_display = f"${total:.2f}" if total is not None else "?"

        header = (
            f"{badge_map[ev['kind']]} — {row.get('retailer')} · {row.get('order_number') or '?'} · "
            f"{row.get('order_date') or '?'} · {total_display} · {item_count} item(s)"
        )
        with st.expander(header):
            if ev["kind"] == "needs_cli":
                st.warning(ev["reason"])
                st.caption(f"Run `python capture_queue_promotion.py` for this one -- capture_id: {capture_id}")
                continue

            if ev["kind"] == "shipped_merge":
                st.info(
                    "This isn't a new order -- it's the follow-up 'shipped' capture for an order "
                    "already created from an earlier 'checkout' capture. Merging just adds tracking "
                    "numbers and payment-card identities to that existing order."
                )
                st.caption(ev["reason"])
                if ev["item_count_mismatch"]:
                    st.warning(
                        f"This capture lists {ev['incoming_item_count']} item(s) but the existing "
                        f"order has {ev['existing_item_count']} -- worth a manual look, but merging "
                        f"tracking/payment info is still safe either way (line items are never touched)."
                    )
                if st.button("Merge into existing order", key=f"merge_{capture_id}"):
                    result = merge_shipped_row(client, row, ev["raw"], ev["existing_order_id"])
                    st.success(f"Merged -> order_id {result['order_id']}")
                    del st.session_state.evaluations[capture_id]
                    st.rerun()
                continue

            if ev["kind"] == "duplicate_checkout":
                st.warning(ev["reason"])
                st.caption(
                    f"Existing order_id: {ev['existing_order_id']}. If this really is the same order "
                    f"captured twice, discard this row below -- it changes nothing in `orders`."
                )
                reason = st.text_input(
                    "Discard reason", value="Duplicate checkout-stage capture", key=f"dupreason_{capture_id}"
                )
                if st.button("Discard as duplicate", key=f"discard_dup_{capture_id}"):
                    discard_row(client, row, reason)
                    del st.session_state.evaluations[capture_id]
                    st.rerun()
                continue

            if ev["kind"] == "empty":
                st.info(ev["reason"])
                if ev["parse_errors"]:
                    st.caption("Parse errors: " + "; ".join(ev["parse_errors"]))
                if st.button("Discard (empty capture)", key=f"discard_empty_{capture_id}"):
                    discard_row(client, row, "Empty capture -- source PDF failed to parse, no data recovered.")
                    del st.session_state.evaluations[capture_id]
                    st.rerun()
                empty_capture_ids.append(capture_id)
                continue

            hcols = st.columns([3, 1, 1, 2, 1, 1])
            hcols[0].caption("Item")
            hcols[1].caption("Qty")
            hcols[2].caption("Price")
            hcols[3].caption("Set #")
            hcols[4].caption("GWP")
            hcols[5].caption("Cancelled")
            for idx, it in enumerate(ev["items"]):
                gwp_key, setnum_key, cancelled_key = _item_widget_keys(capture_id, idx)
                cols = st.columns([3, 1, 1, 2, 1, 1])
                cols[0].write(it["set_name"])
                cols[1].write(str(it["quantity"]))
                cols[2].write(f"${it['unit_price']:.2f}")
                cols[3].text_input(
                    "Set #", value=it.get("set_number") or "", key=setnum_key,
                    label_visibility="collapsed", placeholder="set #",
                )
                cols[4].checkbox("GWP", value=it["is_gwp"], key=gwp_key, label_visibility="collapsed")
                cols[5].checkbox(
                    "Cancelled", value=it.get("item_status") == "cancelled", key=cancelled_key,
                    label_visibility="collapsed",
                )

            if st.button("Auto-flag $0 items as GWP", key=f"autoflag_{capture_id}"):
                changed = False
                for idx, it in enumerate(ev["items"]):
                    gwp_key, _ = _item_widget_keys(capture_id, idx)
                    if it["unit_price"] == 0 and not st.session_state.get(gwp_key, it["is_gwp"]):
                        st.session_state[gwp_key] = True
                        changed = True
                if changed:
                    st.rerun()

            edited_items = _apply_edits(capture_id, ev["items"])
            live_warnings = _live_warnings(client, ev["order"], edited_items)
            is_clean_now = not live_warnings

            st.write(
                f"Subtotal ${ev['order']['subtotal']:.2f} · Tax ${ev['order']['tax_paid']:.2f} "
                f"· Total ${ev['order']['total']:.2f}"
            )

            if live_warnings:
                for w in live_warnings:
                    st.error(w["message"])
            elif ev["kind"] == "flagged":
                st.success("Edits above resolve the flag(s) -- clean to promote now.")

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Promote", key=f"promote_{capture_id}"):
                    result = promote_row(client, row, ev["order"], edited_items)
                    if result["ok"]:
                        st.success(f"Promoted -> order_id {result['order_id']}")
                        del st.session_state.evaluations[capture_id]
                        st.rerun()
                    else:
                        st.error(result["message"])
            with col_b:
                reason = st.text_input("Discard reason", key=f"reason_{capture_id}")
                if st.button("Discard", key=f"discard_{capture_id}"):
                    if not reason:
                        st.error("Reason required.")
                    else:
                        discard_row(client, row, reason)
                        del st.session_state.evaluations[capture_id]
                        st.rerun()

            if is_clean_now:
                clean_capture_ids.append(capture_id)

    if clean_capture_ids:
        st.divider()
        if st.button(f"Promote all {len(clean_capture_ids)} clean row(s) (including inline edits above)"):
            promoted, failed = 0, []
            for row in rows:
                cid = row["capture_id"]
                if cid not in clean_capture_ids:
                    continue
                ev = st.session_state.evaluations.get(cid)
                if not ev:
                    continue
                edited_items = _apply_edits(cid, ev["items"])
                result = promote_row(client, row, ev["order"], edited_items)
                if result["ok"]:
                    promoted += 1
                    del st.session_state.evaluations[cid]
                else:
                    failed.append((cid, result["message"]))
            st.success(f"Promoted {promoted} row(s).")
            if failed:
                st.error(f"{len(failed)} failed: {failed}")
            st.rerun()

    if empty_capture_ids:
        st.divider()
        if st.button(f"Discard all {len(empty_capture_ids)} empty row(s)"):
            discarded = 0
            rows_by_id = {r["capture_id"]: r for r in rows}
            for cid in empty_capture_ids:
                discard_row(client, rows_by_id[cid], "Empty capture -- source PDF failed to parse, no data recovered.")
                discarded += 1
                if cid in st.session_state.evaluations:
                    del st.session_state.evaluations[cid]
            st.success(f"Discarded {discarded} empty row(s).")
            st.rerun()


def render_tag_orders(client):
    st.write("Bulk-apply `buy_reason` + `purchase_trigger` to orders that share one true answer.")

    untagged = (
        client.table("orders")
        .select("retailer")
        .eq("user_id", PHASE_1_USER_ID)
        .is_("buy_reason", "null")
        .is_("purchase_trigger", "null")
        .execute()
        .data
        or []
    )
    retailer_options = sorted({r["retailer"] for r in untagged if r.get("retailer")})

    if not retailer_options:
        st.success("No untagged orders.")
        return

    retailer = st.selectbox("Retailer", retailer_options)

    orders = (
        client.table("orders")
        .select("order_id, order_number, order_date, total, retailer")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("retailer", retailer)
        .is_("buy_reason", "null")
        .is_("purchase_trigger", "null")
        .order("order_date")
        .execute()
        .data
        or []
    )

    st.write(f"**{len(orders)} untagged order(s) for {retailer}.**")

    select_all = st.checkbox("Select all shown", key="select_all")
    selected_ids = []
    for o in orders:
        total_display = f"${o['total']:.2f}" if o.get("total") is not None else "?"
        label = f"{o['order_number']} · {o['order_date']} · {total_display}"
        if st.checkbox(label, key=f"sel_{o['order_id']}", value=select_all):
            selected_ids.append(o["order_id"])

    st.write(f"**{len(selected_ids)} selected.**")

    if retailer in SIMPLE_QUICKPICK_RETAILERS:
        st.caption(
            "This retailer realistically only produces two real answers in practice "
            "(ADR-028) -- quick-pick below, or use the full picker for the rare exception."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Sale (found it myself)", disabled=not selected_ids):
                n = apply_tag(client, selected_ids, "opportunistic", "self_discovered")
                st.success(f"Tagged {n} order(s) as opportunistic / self_discovered.")
                st.rerun()
        with col_b:
            if st.button("Price alert (community/app)", disabled=not selected_ids):
                n = apply_tag(client, selected_ids, "opportunistic", "community_alert")
                st.success(f"Tagged {n} order(s) as opportunistic / community_alert.")
                st.rerun()
        with st.expander("Full picker (rare exception)"):
            br = st.selectbox("buy_reason", FULL_BUY_REASONS, key="full_br")
            pt = st.selectbox("purchase_trigger", FULL_TRIGGERS, key="full_pt")
            if st.button("Apply full picker", disabled=not selected_ids):
                n = apply_tag(client, selected_ids, br, pt)
                st.success(f"Tagged {n} order(s) as {br} / {pt}.")
                st.rerun()
    else:
        st.caption(
            "LEGO (and any other retailer with a fuller range) uses the full picker -- "
            "planned targeted buys and GWP-hunts are real here."
        )
        br = st.selectbox("buy_reason", FULL_BUY_REASONS, key="full_br_lego")
        pt = st.selectbox("purchase_trigger", FULL_TRIGGERS, key="full_pt_lego")
        if st.button("Apply to selected", disabled=not selected_ids):
            n = apply_tag(client, selected_ids, br, pt)
            st.success(f"Tagged {n} order(s) as {br} / {pt}.")
            st.rerun()


if __name__ == "__main__":
    main()
