"""
ResellOS - Gift Card Import Review Tool (Streamlit)
====================================================
ADR-030: review screen for gift_card_import_queue -> gift_cards promotion.
Bulk-uploaded ledgers (agents/agent_11_gift_card_bulk_import.py) only ever
carry last4 + face value -- this is where Josh confirms the purchase
economics (purchase_date, purchase_price/discount_pct, source_platform)
that gift_cards.purchase_price/purchase_date require before a card is
allowed into the wallet. Same shape as capture_queue_review_app.py
(ADR-028): a bulk mechanical step upstream, a human confirmation gate here,
nothing reaches the table that feeds cost basis without it.

Most cards in a real ledger were bought together in one batch (the same
krogergiftcards.com or cardcenter.cc order, same day, same discount) --
this app leans on that: set purchase_date/price-or-discount/source once in
the sidebar-style panel, tick the rows it applies to, apply to all of them
in one click. Any card bought differently gets its own row-level override
via its expander instead of forcing a one-at-a-time flow on everything.

Run:  streamlit run gift_card_import_review_app.py
"""

from datetime import date, datetime, timezone

import httpx
import streamlit as st

from db_client import get_client, PHASE_1_USER_ID


st.set_page_config(page_title="ResellOS -- Gift Card Import Review", layout="wide")

# Known source platforms (ADR-027) plus a couple of general fallbacks.
SOURCE_PLATFORMS = [
    "giftcards.com",
    "krogergiftcards.com",
    "cardcenter_cc",
    "gcx",
    "cardcookie",
    "arbitrage_card",
    "direct",
    "other",
]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


@st.cache_resource
def _client():
    # Same keep-alive workaround as capture_queue_review_app.py -- a
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


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

def load_pending(client):
    result = (
        client.table("gift_card_import_queue")
        .select("*")
        .eq("user_id", PHASE_1_USER_ID)
        .eq("status", "pending")
        .order("source_batch")
        .order("card_number_last4")
        .execute()
    )
    return result.data or []


def load_counts(client):
    rows = (
        client.table("gift_card_import_queue")
        .select("status")
        .eq("user_id", PHASE_1_USER_ID)
        .execute()
        .data
        or []
    )
    counts = {"pending": 0, "promoted": 0, "skipped": 0}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# Promotion / skip
# --------------------------------------------------------------------------- #

def promote_row(client, row, purchase_date_val, purchase_price, source_platform, notes):
    face_value = float(row["face_value"])
    discount_pct = round((face_value - purchase_price) / face_value * 100, 2) if face_value else 0.0

    card = {
        # discount_amount is a DB-generated column (face_value -
        # purchase_price) -- caught 2026-09-15 while promoting the
        # 130-card import queue; the insert fails outright if it's
        # included here.
        "user_id": PHASE_1_USER_ID,
        "retailer": row["retailer"],
        "face_value": face_value,
        "purchase_price": purchase_price,
        "discount_pct": discount_pct,
        "purchase_date": purchase_date_val.isoformat(),
        "remaining_balance": face_value,
        "status": "available",
        "card_number_last4": row["card_number_last4"],
        "source": source_platform,
        "source_platform": source_platform,
        "source_type": "gift_card_reseller" if source_platform not in ("direct",) else "direct_retailer",
        # Josh is confirming real numbers here, from his own sanitized
        # ledger -- same confidence tier as a direct receipt (ADR-027).
        "discount_confidence": "exact",
        "notes": (
            f"Bulk-imported via ADR-030 review queue (batch '{row['source_batch']}')."
            + (f" {notes}" if notes else "")
        ),
    }
    result = client.table("gift_cards").insert(card).execute()
    if not result.data:
        return {"ok": False, "message": "Insert into gift_cards returned no data."}
    new_card_id = result.data[0]["card_id"]

    client.table("gift_card_import_queue").update({
        "status": "promoted",
        "purchase_date": purchase_date_val.isoformat(),
        "purchase_price": purchase_price,
        "discount_pct": discount_pct,
        "source_platform": source_platform,
        "notes": notes,
        "promoted_card_id": new_card_id,
        "reviewed_at": _now_iso(),
    }).eq("import_id", row["import_id"]).execute()

    return {"ok": True, "card_id": new_card_id, "discount_pct": discount_pct}


def skip_row(client, row, reason):
    client.table("gift_card_import_queue").update({
        "status": "skipped",
        "skip_reason": reason,
        "reviewed_at": _now_iso(),
    }).eq("import_id", row["import_id"]).execute()


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
    st.title("ResellOS -- Gift Card Import Review")
    st.caption(
        "ADR-030 -- confirm purchase date + price/discount + source for bulk-uploaded gift "
        "card rows before they're added to the wallet (gift_cards)."
    )

    counts = load_counts(client)
    c1, c2, c3 = st.columns(3)
    c1.metric("Pending review", counts.get("pending", 0))
    c2.metric("Added to wallet", counts.get("promoted", 0))
    c3.metric("Skipped", counts.get("skipped", 0))

    rows = load_pending(client)
    if not rows:
        st.success("Nothing pending -- the import queue is empty.")
        return

    batches = sorted({r["source_batch"] for r in rows})
    batch_filter = st.selectbox("Batch", ["All"] + batches)
    if batch_filter != "All":
        rows = [r for r in rows if r["source_batch"] == batch_filter]

    st.write(f"**{len(rows)} row(s) pending review.**")

    # ----------------------------------------------------------------- #
    # Bulk-apply panel -- most cards in a batch were bought together at
    # one price/date/source. Set it once, tick which rows it applies to.
    # ----------------------------------------------------------------- #
    with st.expander("Bulk apply to selected rows", expanded=True):
        bcol1, bcol2, bcol3 = st.columns(3)
        with bcol1:
            bulk_date = st.date_input("Purchase date", value=date.today(), key="bulk_date")
        with bcol2:
            bulk_price = st.number_input(
                "Purchase price per card ($)", min_value=0.0, step=0.01, key="bulk_price"
            )
        with bcol3:
            bulk_source = st.selectbox("Source platform", SOURCE_PLATFORMS, key="bulk_source")
        bulk_notes = st.text_input("Notes (applied to all selected)", key="bulk_notes")

        if bulk_price and rows:
            sample_face = float(rows[0]["face_value"])
            sample_disc = round((sample_face - bulk_price) / sample_face * 100, 2) if sample_face else 0
            st.caption(f"On a ${sample_face:.2f} face-value card, that's a {sample_disc:.2f}% discount.")

        select_all = st.checkbox("Select all shown", key="select_all_gc")

    if "selected_imports" not in st.session_state:
        st.session_state.selected_imports = set()

    selected_rows = []
    for row in rows:
        checked = st.checkbox(
            f"{row['retailer']} ...{row['card_number_last4']} -- ${row['face_value']:.2f} face "
            f"(batch: {row['source_batch']})",
            value=select_all,
            key=f"sel_{row['import_id']}",
        )
        if checked:
            selected_rows.append(row)

        with st.expander(f"Details / individual override -- ...{row['card_number_last4']}"):
            linkage = row.get("source_linkage") or {}
            if linkage:
                st.caption("Raw source row (reference only, not authoritative):")
                st.json(linkage, expanded=False)

            ocol1, ocol2, ocol3 = st.columns(3)
            with ocol1:
                own_date = st.date_input(
                    "Purchase date", value=date.today(), key=f"date_{row['import_id']}"
                )
            with ocol2:
                own_price = st.number_input(
                    "Purchase price ($)", min_value=0.0, step=0.01, key=f"price_{row['import_id']}"
                )
            with ocol3:
                own_source = st.selectbox(
                    "Source platform", SOURCE_PLATFORMS, key=f"source_{row['import_id']}"
                )
            own_notes = st.text_input("Notes", key=f"notes_{row['import_id']}")

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Save this card to wallet", key=f"save_{row['import_id']}"):
                    if not own_price:
                        st.error("Purchase price is required.")
                    else:
                        result = promote_row(client, row, own_date, own_price, own_source, own_notes)
                        if result["ok"]:
                            st.success(f"Added to wallet ({result['discount_pct']:.2f}% discount).")
                            st.rerun()
                        else:
                            st.error(result["message"])
            with col_b:
                skip_reason = st.text_input("Skip reason", key=f"skipreason_{row['import_id']}")
                if st.button("Skip", key=f"skip_{row['import_id']}"):
                    skip_row(client, row, skip_reason or "Skipped without a reason.")
                    st.rerun()

    st.divider()
    if selected_rows:
        st.write(f"**{len(selected_rows)} row(s) selected for bulk apply.**")
        if st.button(f"Apply bulk values and save {len(selected_rows)} card(s) to wallet"):
            if not bulk_price:
                st.error("Purchase price is required for bulk apply.")
            else:
                saved, failed = 0, []
                for row in selected_rows:
                    result = promote_row(client, row, bulk_date, bulk_price, bulk_source, bulk_notes)
                    if result["ok"]:
                        saved += 1
                    else:
                        failed.append((row["card_number_last4"], result["message"]))
                st.success(f"Added {saved} card(s) to the wallet.")
                if failed:
                    st.error(f"{len(failed)} failed: {failed}")
                st.rerun()


if __name__ == "__main__":
    main()
