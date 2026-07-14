# ADR-020: Adopt Automated Regression Testing for the Cost Basis Engine Before Historical Backfill

**Status:** Proposed
**Date:** 2026-06-21
**Deciders:** Josh

> Note on numbering: SESSION_LOG.md reserves ADR-019 for the FIFO confirmation write-up coming out of the June 10 CPA meeting. This ADR is numbered 020 to avoid colliding with that.

## Context

`agent_08_cost_basis.py` is the single most consequential module in ResellOS. It produces `true_cost_basis`, and per DECISION 011 that value **locks at settlement and never reopens** — corrections after the fact can only happen as P&L adjustment entries layered on top, never as a fix to the original number. CLAUDE.md rule 9 already names this explicitly: "wrong data in cost basis is worse than no data."

Today the correctness gate for this code is two things: manual code review before every commit (the `resell-os-code-review` skill / CLAUDE.md rule 9), and a single golden-record verification run once in S08 against real order T487170400. There is no automated, repeatable check that runs on every future change.

The track record says this gate is doing real work, not just rubber-stamping: S07's cashback agent review caught 2 CRITICAL + 4 MODERATE bugs, and S08's cost basis engine review caught 2 CRITICAL + 4 MODERATE bugs in the same session it was first verified — including one where the settlement lock never fired at all, and one where an overwrite-delete silently produced duplicate writes. Those weren't found by re-running a test; they were found by a human re-reading the diff. That's a strong signal this surface area is genuinely bug-prone, and that a one-time human read-through is a leaky filter, not a safety net.

What changes the calculus now: Agent 1C is staged to backfill roughly 635 historical LEGO orders (per `lego_order_numbers_master.txt`) into the same code paths that currently have 5–9 orders running through them. Several known-but-deferred defects already touch this exact module (tax_paid_allocated always writes 0, GWP Mode 3 never writes `settlement_date`, a dead `elif` branch, `net_economic_cost` calculated twice at different precision). Right now, building test fixtures is cheap — there are only a handful of real, already-hand-verified orders to encode. After backfill, any fixture set has to be built against orders that have already settled and can't be corrected if something's wrong.

## Decision

Adopt a pytest-based regression suite for `agent_08_cost_basis.py` and the layers that feed it (gift cards, rewards, cashback, GWP), built from a small library of golden-record fixtures — starting with the already-verified T487170400 order and the still-pending Barnes Scrapyard rewards-redemption order — and run it before every commit that touches cost-basis-adjacent code, **before** the Agent 1C historical backfill runs at scale.

## Options Considered

### Option A: Status quo — manual code review + single golden record

| Dimension | Assessment |
|---|---|
| Complexity (now) | Low — no new tooling |
| Complexity (later) | High — bugs surface against records that are already locked/settled |
| Cost | $0 now; unbounded later (manual reconciliation across hundreds of settled orders) |
| Scalability | Doesn't scale — quality depends entirely on one read-through catching it, with a track record of 2 CRITICAL bugs per session already |
| Builder familiarity | Already the current workflow |
| Endgame readiness | Weak — a community product (Phase 6) running other people's money can't rely on per-session manual review indefinitely |

**Pros:** No new skill to learn; zero setup time.
**Cons:** Already demonstrably missed CRITICAL bugs on first pass twice; gets strictly riskier as order volume grows; no defense against regressions introduced by unrelated future changes.

### Option B: pytest regression suite with golden-record fixtures (recommended)

| Dimension | Assessment |
|---|---|
| Complexity (now) | Medium — one session to scaffold, pytest is well-documented for beginners |
| Complexity (later) | Low — fixtures run for free on every future commit |
| Cost | ~60–90 min now; near-zero marginal cost per commit after |
| Scalability | Scales with order count — every newly verified order becomes a permanent fixture instead of a one-time check that's then forgotten |
| Builder familiarity | New tool, but matches the "no assumed knowledge, step-by-step" pattern already used for every other agent build |
| Endgame readiness | Strong — this is the minimum bar expected before Phase 6 community launch puts other people's financial data through this code |

**Pros:** Would already have caught both S08 CRITICAL bugs the moment a second test order existed; compounds in value with every order added; gives the `resell-os-code-review` skill something to run, not just read.
**Cons:** Requires deciding, per failing test, whether the fixture or the code is wrong — small added friction per commit (intentional).

### Option C: Property-based / invariant testing (e.g. `hypothesis`) in addition to golden records

| Dimension | Assessment |
|---|---|
| Complexity (now) | High — requires formalizing invariants first (e.g. "sum of line-item net cost == order economic cost minus total GWP proceeds"; "settled cost basis never changes") |
| Complexity (later) | Low once invariants are captured — catches whole classes of bugs golden records miss |
| Cost | Steepest learning curve of the three |
| Scalability | Excellent long-term |
| Builder familiarity | Lowest — newest concept for a beginner coder |
| Endgame readiness | Best eventual state, premature today |

**Pros:** Catches bug classes, not just specific instances.
**Cons:** Over-engineered for where the project is right now — worth revisiting once Option B exists and Phase 2/3 add inventory and sales matching.

## Trade-off Analysis

For a solo, beginner-level builder shipping a system whose entire value proposition is "accurate tracking" of real money, the deciding axis isn't elegance — it's what happens when a bug is found six months from now. DECISION 011 makes that scenario worse than in a typical app: a settled cost basis can't be reopened, only patched with an adjustment entry on top. The S07/S08 history (2 CRITICAL bugs caught by manual review in back-to-back sessions, in code paths smaller than what's about to be backfilled) says the current gate is catching things — which means it has likely missed things too. Agent 1C is the forcing function: it's about to multiply order volume through this exact code by roughly 70x in a single operation, while four known-but-deferred defects already sit in it. Building the regression suite first costs one evening. Skipping it risks discovering a systemic cost-basis error after 635 orders have already settled and can no longer be corrected at the source. Option C is the right answer eventually, but Option B alone — run consistently — would already have caught both S08 CRITICAL bugs as soon as a second order existed as a fixture.

## Consequences

**What becomes easier**
- Every future session touching `agent_08_cost_basis.py`, `agent_05_gift_cards.py`, or `agent_07_cashback.py` gets a fast, repeatable check instead of a fresh read-through each time.
- The `resell-os-code-review` skill has a concrete pass/fail signal to run alongside its read-through.
- Verified orders compound into a growing safety net instead of being discarded after one-time verification.

**What becomes harder**
- Any change that alters expected output requires a deliberate call — update the fixture, or the change is a real bug — adding small, intentional friction per commit.

**What we'll need to revisit**
- SESSION_LOG.md S10 plan: add fixture-building as an explicit step before the Agent 1C bulk backfill.
- CLAUDE.md rule 9: reference the automated suite alongside manual code review, not as a replacement for it.
- Master Architecture Document: add this as a numbered decision once adopted (see open questions below on doc drift generally).

## Action Items

1. [ ] Create `/tests/test_cost_basis.py` with one fixture from order T487170400 (numbers already verified in S08) — confirm it passes against current code.
2. [ ] Add a second fixture from the Barnes Scrapyard rewards-redemption order ($52.43 rewards, $21.65 out of pocket) — this does double duty with the still-deferred S09 verification task.
3. [ ] Add fixtures targeting the four S08 minor deferred items (tax_paid_allocated, GWP Mode 3 settlement_date, dead elif branch, double-calculated net_economic_cost) so each is provably fixed, not just edited.
4. [ ] Run the suite before every commit touching a cost-basis-adjacent file, and explicitly as a gate before Agent 1C's bulk backfill begins.

---

## Open questions for the next session

- Should the authenticated-scraping safeguards (rate limiting, CAPTCHA/account-lock detection) decided on 2026-06-20 be enforced in code, or remain a manually-followed discipline as currently documented only in CONTEXT.md?
- DECISION 018 (Kohl's pretax tax treatment) and the 2026-06-20 scraping-boundary decision both exist only in CONTEXT.md/SESSION_LOG, not in the Master Architecture Document (still v2.1, dated 2026-06-01) — should that document be regenerated from the current sources, or retired in favor of one canonical doc?
- Given 635 historical orders are about to backfill, should the known duplicate-line-item issue (Open Question 4) be fixed and idempotency-tested first, or is backfill itself the way to surface and force a fix?
