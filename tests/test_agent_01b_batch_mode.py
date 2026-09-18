"""
Unit tests -- agent_01b_invoice_filing.mode_run_batch() (the --run
non-interactive batch mode, added 2026-09-19, mirroring
agent_01e_pdf_order_backfill.py's own --run mode).

_execute_filing() itself is not re-tested here -- its Drive-upload/ledger
I/O still requires real Gmail/Drive/Supabase to exercise (same reasoning
this function's interactive caller, mode_file(), has never been directly
unit tested either), so it's faked out via monkeypatch instead. It DID
change substantially this session (return type bool -> (success, pdf_count),
a try/except added around record_filing(), per-attachment upload-count
tracking) -- those changes are covered by reading/review, not by a unit
test, consistent with this file's convention of testing mode_run_batch()'s
own pure loop/tally logic rather than _execute_filing()'s I/O. What's new
and worth locking in with a regression test here is mode_run_batch()'s own
logic: it must never let one plan's exception abort the rest of the batch,
it must tally outcomes into the right bucket (filed_matched / filed_unmatched
/ error), and -- the real bugs caught in code review before this ever ran
live -- it must not let two invoices matched to the same split-shipment
order collide on an identical precomputed Drive filename, whether that's
because of a second single-PDF plan, a multi-PDF plan consuming more than
one shipment slot, or a plan that partially succeeded (Drive upload done,
ledger write failed) before erroring out.

Uses pytest's monkeypatch to replace _execute_filing() with a fake for
each scenario -- a deliberate, minimal exception to this codebase's
"pure functions only" testing convention (same reasoning as
tests/test_add_missing_items_cost_basis_guard.py), since gmail/drive/
client are never touched by mode_run_batch() itself once _execute_filing()
is faked out; only the loop/tally/collision-avoidance logic is under test.

Run: python -m pytest tests/test_agent_01b_batch_mode.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

import agent_01b_invoice_filing as agent


def _plan(matched=True, order_number="T1", subject="Test invoice", msg_id="m1",
          order_id=None, retailer_key="LEGO", date_str="2026-09-01",
          order_date_str="2026-06-01", next_shipment=1, filename=None):
    if filename is None:
        filename = f"{order_number}_{retailer_key}_{order_date_str}.pdf" if matched else f"{msg_id}_{retailer_key}_{date_str}.pdf"
    return {
        "matched": matched, "order_number": order_number, "subject": subject, "msg_id": msg_id,
        "order_id": order_id, "retailer_key": retailer_key, "date_str": date_str,
        "order_date_str": order_date_str, "next_shipment": next_shipment, "filename": filename,
    }


def test_empty_plans_returns_zeroed_tally():
    outcomes = agent.mode_run_batch([], gmail=None, drive=None, client=None)
    assert outcomes == {"total": 0, "filed_matched": 0, "filed_unmatched": 0, "error": 0}


def test_successful_matched_and_unmatched_plans_tally_correctly(monkeypatch):
    monkeypatch.setattr(agent, "_execute_filing", lambda plan, gmail, drive, client: (True, 1))
    plans = [_plan(matched=True, msg_id="m1"), _plan(matched=False, msg_id="m2")]
    outcomes = agent.mode_run_batch(plans, gmail=None, drive=None, client=None)
    assert outcomes == {"total": 2, "filed_matched": 1, "filed_unmatched": 1, "error": 0}


def test_plain_failure_return_counts_as_error(monkeypatch):
    # _execute_filing() returns (False, 0) (not an exception) on several
    # real failure paths (no PDF attachment, Drive upload failed, ledger
    # write failed) -- these must count as errors too, not be silently
    # dropped.
    monkeypatch.setattr(agent, "_execute_filing", lambda plan, gmail, drive, client: (False, 0))
    outcomes = agent.mode_run_batch([_plan()], gmail=None, drive=None, client=None)
    assert outcomes["error"] == 1
    assert outcomes["filed_matched"] == 0
    assert outcomes["filed_unmatched"] == 0


def test_one_exception_does_not_abort_the_rest_of_the_batch(monkeypatch):
    # The exact property this mode exists to guarantee: a single bad
    # invoice midway through ~1,169 messages must not waste the whole run.
    attempted = []

    def fake_execute(plan, gmail, drive, client):
        attempted.append(plan["msg_id"])
        if plan["msg_id"] == "bad":
            raise RuntimeError("simulated Drive upload failure")
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=True, msg_id="m1"),
        _plan(matched=True, msg_id="bad"),
        _plan(matched=False, msg_id="m3"),
    ]
    outcomes = agent.mode_run_batch(plans, gmail=None, drive=None, client=None)

    assert attempted == ["m1", "bad", "m3"], "every plan must be attempted, in order"
    assert outcomes["total"] == 3
    assert outcomes["error"] == 1
    assert outcomes["filed_matched"] == 1
    assert outcomes["filed_unmatched"] == 1


def test_multiple_exceptions_all_counted_independently(monkeypatch):
    def fake_execute(plan, gmail, drive, client):
        if plan["matched"] is None:
            raise RuntimeError("boom")
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=None, msg_id="bad1"),
        _plan(matched=True, msg_id="ok1"),
        _plan(matched=None, msg_id="bad2"),
    ]
    outcomes = agent.mode_run_batch(plans, gmail=None, drive=None, client=None)
    assert outcomes["error"] == 2
    assert outcomes["filed_matched"] == 1
    assert outcomes["total"] == 3


# --------------------------------------------------------------------------- #
# In-batch split-shipment collision fix -- regression test for a real bug
# caught in code review, 2026-09-19: build_filing_plan() computes each
# plan's shipment number from count_shipments() once, all up front during
# mode_preview()'s single scan. Filing an invoice never inserts a
# shipments row, so two messages matched to the same order within one
# batch would otherwise get identical precomputed shipment numbers and
# collide on the exact same destination filename in Drive.
# --------------------------------------------------------------------------- #

def test_second_invoice_for_same_order_gets_bumped_shipment_number(monkeypatch):
    seen_plans = []

    def fake_execute(plan, gmail, drive, client):
        seen_plans.append(dict(plan))
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m1", next_shipment=1),
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m2", next_shipment=1),
    ]
    outcomes = agent.mode_run_batch(plans, gmail=None, drive=None, client=None)

    assert outcomes["filed_matched"] == 2
    assert outcomes["error"] == 0
    # Both plans were precomputed with next_shipment=1 (simulating
    # count_shipments() returning the same stale value for both, since
    # filing never inserts a shipments row) -- the second must be bumped.
    assert seen_plans[0]["next_shipment"] == 1
    assert seen_plans[1]["next_shipment"] == 2
    assert seen_plans[0]["filename"] != seen_plans[1]["filename"], "must not collide on the same Drive filename"
    assert seen_plans[1]["filename"] == "T1_LEGO_2026-06-01_ship2.pdf"


def test_bumped_filename_uses_order_date_not_email_date(monkeypatch):
    # order_date_str (the order's own date) must be used to rebuild the
    # filename, not date_str (the email's date) -- using the wrong one
    # would silently produce a filename inconsistent with the first
    # invoice's own (correctly order-dated) filename.
    seen_plans = []

    def fake_execute(plan, gmail, drive, client):
        seen_plans.append(dict(plan))
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m1",
              next_shipment=1, order_date_str="2026-06-01", date_str="2026-09-15"),
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m2",
              next_shipment=1, order_date_str="2026-06-01", date_str="2026-09-16"),
    ]
    agent.mode_run_batch(plans, gmail=None, drive=None, client=None)

    assert "2026-06-01" in seen_plans[1]["filename"]
    assert "2026-09-16" not in seen_plans[1]["filename"]


def test_third_invoice_for_same_order_continues_numbering_correctly(monkeypatch):
    seen_plans = []

    def fake_execute(plan, gmail, drive, client):
        seen_plans.append(dict(plan))
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m1", next_shipment=1),
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m2", next_shipment=1),
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m3", next_shipment=1),
    ]
    agent.mode_run_batch(plans, gmail=None, drive=None, client=None)

    assert [p["next_shipment"] for p in seen_plans] == [1, 2, 3]
    filenames = [p["filename"] for p in seen_plans]
    assert len(set(filenames)) == 3, "all three filenames must be distinct"


def test_different_orders_in_same_batch_do_not_affect_each_others_numbering(monkeypatch):
    seen_plans = []

    def fake_execute(plan, gmail, drive, client):
        seen_plans.append(dict(plan))
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m1", next_shipment=1),
        _plan(matched=True, order_id="order-2", order_number="T2", msg_id="m2", next_shipment=1),
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m3", next_shipment=1),
    ]
    agent.mode_run_batch(plans, gmail=None, drive=None, client=None)

    assert seen_plans[0]["next_shipment"] == 1   # order-1, first time
    assert seen_plans[1]["next_shipment"] == 1   # order-2, unaffected by order-1's count
    assert seen_plans[2]["next_shipment"] == 2   # order-1, second time -- correctly bumped


def test_multi_attachment_plan_bumps_the_tracker_by_slots_consumed_not_by_one(monkeypatch):
    # The exact bug caught in a follow-up code review round, 2026-09-19:
    # a single plan's message can carry more than one PDF attachment, and
    # _execute_filing() gives each attachment its own ship{N} slot
    # internally (ship_num = next_shipment + (idx - 1)). If mode_run_batch()
    # bumped filed_this_batch by 1 per plan regardless of pdf_count, a
    # 2-attachment plan A (consuming ship1+ship2) followed by a
    # 1-attachment plan B for the same order would only push B to ship2 --
    # colliding with the ship2 file A already uploaded. This test fakes
    # _execute_filing() returning pdf_count=2 for plan A to prove the
    # tracker now bumps by the real number of slots consumed.
    seen_plans = []

    def fake_execute(plan, gmail, drive, client):
        seen_plans.append(dict(plan))
        if plan["msg_id"] == "m1":
            return True, 2  # simulates a message with 2 PDF attachments
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m1", next_shipment=1),
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m2", next_shipment=1),
    ]
    agent.mode_run_batch(plans, gmail=None, drive=None, client=None)

    assert seen_plans[0]["next_shipment"] == 1  # plan A: precomputed, unbumped (first for this order)
    assert seen_plans[1]["next_shipment"] == 3, (
        "plan B must be bumped past BOTH slots plan A consumed (ship1+ship2), "
        "not just by 1, or it collides with the ship2 file A already uploaded"
    )
    assert seen_plans[1]["filename"] != seen_plans[0]["filename"]


def test_partial_failure_still_bumps_the_tracker(monkeypatch):
    # Another follow-up code review catch, 2026-09-19: _execute_filing()
    # can upload a PDF to Drive successfully and THEN fail (e.g. the
    # ledger write), returning success=False but a nonzero pdf_count --
    # that real Drive file still occupies its shipment slot. If the
    # tracker only bumped on success, the next plan for the same order
    # would collide with the file the "failed" plan actually left behind
    # in Drive.
    seen_plans = []

    def fake_execute(plan, gmail, drive, client):
        seen_plans.append(dict(plan))
        if plan["msg_id"] == "m1":
            return False, 1  # Drive upload succeeded, ledger write then failed
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m1", next_shipment=1),
        _plan(matched=True, order_id="order-1", order_number="T1", msg_id="m2", next_shipment=1),
    ]
    outcomes = agent.mode_run_batch(plans, gmail=None, drive=None, client=None)

    assert outcomes["error"] == 1
    assert outcomes["filed_matched"] == 1
    assert seen_plans[1]["next_shipment"] == 2, (
        "plan B must still be bumped past the slot plan A's failed-but-uploaded "
        "file consumed, even though plan A counted as an error overall"
    )


def test_unmatched_plans_are_never_touched_by_collision_logic(monkeypatch):
    # Unmatched plans have no order_id -- must never be mistaken for
    # belonging to "no order" and grouped together.
    seen_plans = []

    def fake_execute(plan, gmail, drive, client):
        seen_plans.append(dict(plan))
        return True, 1

    monkeypatch.setattr(agent, "_execute_filing", fake_execute)
    plans = [
        _plan(matched=False, order_id=None, msg_id="m1"),
        _plan(matched=False, order_id=None, msg_id="m2"),
    ]
    agent.mode_run_batch(plans, gmail=None, drive=None, client=None)

    assert seen_plans[0]["next_shipment"] == 1
    assert seen_plans[1]["next_shipment"] == 1  # unaffected -- unmatched plans are exempt entirely
