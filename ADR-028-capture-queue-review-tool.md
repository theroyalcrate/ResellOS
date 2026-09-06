# ADR-028: Adopt a Minimal, Purpose-Built Review Tool for Capture Queue Promotion

**Status:** Accepted
**Date:** 2026-09-06
**Deciders:** Josh
**Supersedes:** Nothing — builds a visual layer on top of ADR-023's `capture_queue` promotion contract (LIST/PROMOTE/DISCARD via `capture_queue_promotion.py`); does not change that contract's data rules, DECISION 017's cost-basis gate, or any confirmed/settled-order locking behavior.

## Context

ResellOS has deliberately had no user interface anywhere in the system — every touchpoint is Supabase directly (SQL/MCP/Table Editor), a Python CLI script, or the Chrome extension (which only writes to `capture_queue`, with no read/review surface). CONTEXT.md's own "Pre-UI Design Task" explicitly deferred any real interface work to Phase 2/3, on the reasoning that the schema and business logic were still moving too fast (field splits, cost-basis ADRs, confidence tiers) for a UI investment to be worth making yet.

That reasoning held up fine while `capture_queue` review meant occasionally checking a handful of fixture rows or a few live captures a day. It is about to stop holding up: Agent 01E (built, not yet run) is going to walk 758 historical LEGO invoices and route every ambiguous one into `capture_queue` for manual review — a batch, not a trickle. Reviewing a queue at that scale through `capture_queue_promotion.py`'s one-row-at-a-time terminal prompts, or by paging through Supabase's raw Table Editor (confirmed tonight by Josh to get "overwhelming pretty quick" — too many columns, hard to focus on what actually matters for a promote/discard call), is a real bottleneck for the single highest-priority task on the board.

Josh also named a second, independent reason to want this now: seeing the queue visually, with only the fields that matter for a decision, is likely to surface exactly the kind of schema/API awkwardness that's currently invisible while everything lives in database columns and script output. That's a legitimate secondary benefit, not just a workaround for CLI fatigue.

## Decision

Build a small, purpose-built review screen scoped **only** to `capture_queue` → order promotion — not a general ResellOS UI. It shows each pending queue row with a curated set of fields chosen for the promote/discard decision (order number, retailer, date, total, line-item summary, and any `order_validators.py` warnings), and gives Josh an approve/reject action per row instead of a typed command. It calls the same promotion/discard logic `capture_queue_promotion.py` already uses — this is a new front end on an existing, proven backend contract, not a new data path.

## Options Considered

### Option A: Status quo — `capture_queue_promotion.py` CLI + Supabase Table Editor as needed

| Dimension | Assessment |
|---|---|
| Complexity (now) | None — already built |
| Complexity (later) | Grows linearly with queue size; each session re-pays the "which rows matter" scanning cost |
| Cost | $0 |
| Scalability | Poor past a few dozen rows per sitting — already flagged as overwhelming by Josh at current data volumes |
| Builder familiarity | Total — Josh already uses both today |
| Endgame readiness | Doesn't move the needle either way; punts the review-UX problem indefinitely |

**Pros**
- Zero build time, zero new surface to maintain
- Already proven against real captures (T512391077) and fixtures

**Cons**
- Confirmed today to not scale to the ~758-invoice Agent 01E backlog about to land
- No visual scan — every row review re-pays full attention cost
- Doesn't surface schema/API friction the way a purpose-built screen would

### Option B: Minimal custom review app (e.g. Streamlit) on top of Supabase — recommended

| Dimension | Assessment |
|---|---|
| Complexity (now) | Low — pure Python, reuses `db_client.py`'s existing Supabase connection pattern; a working first version is realistic in one evening session |
| Complexity (later) | Low — small enough to throw away without regret once/if a real product UI gets built in Phase 2/3 |
| Cost | $0 (self-hosted, runs locally) |
| Scalability | Good for a queue in the hundreds; not built for many concurrent users, which isn't a requirement here |
| Builder familiarity | High — Josh's entire stack today is Python; this adds a handful of new decorators, not a new language or paradigm |
| Endgame readiness | Doesn't presuppose or block the eventual "real" UI — stays a disposable internal tool |

**Pros**
- Matches the "beginner coder, minimize total rework" priority directly — no new language, no new deployment model
- Fast enough to actually get built and used before the Agent 01E backlog needs reviewing
- Reuses existing promotion logic rather than re-implementing it — low risk of drifting from the proven CLI behavior
- Disposable: doesn't lock in a design direction that competes with the later, deliberate Phase 2/3 UI pass

**Cons**
- One more small app to keep running locally alongside everything else
- Not a "real" product UI — no auth, no polish, not meant to be shown to anyone else

### Option C: Low-code tool directly on Supabase (e.g. Retool, Appsmith)

| Dimension | Assessment |
|---|---|
| Complexity (now) | Low-to-medium — drag-and-drop builder, but a new platform to learn |
| Complexity (later) | Medium — the app's logic lives in the vendor's cloud, not the repo, which is an odd fit for a codebase that otherwise keeps everything in git |
| Cost | Ongoing subscription once past a free tier |
| Scalability | Good, more headroom than needed here |
| Builder familiarity | Low — new tool, no transferable Python skill gained |
| Endgame readiness | Weak — doesn't teach anything reusable for the eventual real frontend, and adds an external vendor dependency for a core operational workflow |

**Pros**
- Fastest to a polished-looking result with the least code written
- Handles things like auth and hosting Josh would otherwise have to build himself

**Cons**
- Ongoing cost for a tool used by one person, for one internal task
- App logic and config live outside the repo — a philosophical mismatch with a codebase that otherwise treats "own your data" (and, by extension, your own tooling) as a first principle
- Builds no skill Josh can reuse elsewhere in the project — pure time spent, no compounding return

## Trade-off Analysis

The decisive axis here is builder fit, not raw capability. Every option can technically show a list of rows with buttons. What matters is which one a solo, beginner coder can actually finish and keep using without it becoming its own maintenance burden or its own abandoned side-quest. Option C is the fastest to something good-looking, but it teaches nothing transferable, costs money indefinitely for a single-user internal tool, and puts a piece of core operational logic outside version control — a real tension with how this codebase already treats ownership of its own logic. Option A is free and already exists, but Josh named its failure mode himself tonight before this ADR was even proposed: it doesn't scale to what's about to hit it. Option B wins because it's the only one that's simultaneously fast to build (same language, same libraries, same Supabase connection pattern already used everywhere else in the repo), cheap to throw away later (a Streamlit script is not a sunk-cost architecture commitment), and directly targeted at the one bottleneck that's actually blocking progress right now — reviewing the Agent 01E backlog — rather than a general-purpose UI investment the project has already, deliberately, decided to defer.

## Consequences

**What becomes easier**
- Reviewing and promoting `capture_queue` rows at the volume Agent 01E is about to generate
- Spotting a bad parse or a suspicious total before it becomes a bad cost-basis record, instead of after
- Surfacing which database columns/API shapes are actually confusing in practice — direct feedback into future schema cleanup
- Running Agent 01E's backlog through review without CLI fatigue becoming a reason to defer it

**What becomes harder**
- Nothing structurally — but there are now two review surfaces (this tool and `capture_queue_promotion.py`); worth deciding later whether the CLI stays as a scriptable/automatable fallback or gets retired once this covers its use cases

**What we'll need to revisit**
- CONTEXT.md's "Pre-UI Design Task" wording — should note explicitly that this interim tool doesn't replace or presuppose that later, deliberate design pass; it's scoped narrowly and disposably on purpose
- CONTEXT.md's "Planned Future Systems" list — worth a short pointer noting this exists, so a future session doesn't rediscover the same gap from scratch

## Action Items

1. [x] Streamlit confirmed (2026-09-06, same evening) — see Resolution below
2. [ ] Enumerate the exact `capture_queue` fields that matter for a promote/discard call (order number, retailer, date, total, line-item summary, `order_validators.py` warnings) and confirm nothing important is missing
3. [ ] Build a first version that lists pending rows and calls the existing promote/discard logic from `capture_queue_promotion.py` directly, rather than reimplementing it
4. [ ] Test it against a handful of real Agent 01E-flagged rows once that agent has run, before trusting it for the full backlog

---

## Resolution (2026-09-06, same evening)

Josh confirmed all three open questions above before any code was written:

- **Tool choice:** Streamlit, as recommended. Explicit reasoning given: this phase of the project is also where Josh is learning to build, and what gets learned building the Streamlit version (Supabase queries, thinking through what a review screen needs) carries forward into the eventual full UI build — not wasted effort even though the tool itself is disposable.
- **Retirement path:** Likely retired once the full ResellOS UI exists, rather than kept indefinitely as a separate internal ops screen. Josh's reasoning: permanently maintaining a second, separate review surface alongside a real product UI is over-complication — reviewing and promoting a queued order should be core, first-class functionality *in* ResellOS itself, not something that lives forever in a side tool. This sharpens the original ADR's framing (which left "stays forever as an ops screen" open as a live option) — it's now the less likely outcome, not a coin flip.
- **`capture_queue_promotion.py` CLI:** Stays. Confirmed as the permanent scriptable fallback (e.g. bulk operations, automation, anything the visual tool isn't built to handle) rather than being deprecated once the Streamlit tool exists. The two are complementary, not competing.

**Still genuinely open (as of the Resolution above):** whether the Streamlit tool eventually shows basic progress/status beyond strict `capture_queue` promotion. **Superseded by the Scope Refinement below** — this is now decided, not open.

## Scope Refinement (2026-09-06, same evening, continued)

Before any code was written, Josh added three concrete pieces of scope based on thinking through what actually happens once real batches of orders hit the queue:

**1. Progress/status view moves into v1, not deferred.** A simple pending/promoted/flagged counter (or equivalent) ships with the first version rather than waiting to see if the narrow version feels incomplete. Directly resolves the "still genuinely open" item from the Resolution above.

**2. Primary interaction model confirmed: quick-promote the clean ones, hold the questionable ones.** The tool's default action promotes orders that already pass validation cleanly (no `order_validators.py` warnings) with minimal friction — ideally a bulk action, not one click per row. `capture_queue` keeps holding anything genuinely ambiguous for closer manual review. This matches Agent 01E's own auto-promote-clean / flag-the-rest design (Step 0b in SESSION_LOG.md) — the review tool is the human-facing half of that same split, not a separate policy.

**3. Bulk-tagging `buy_reason`/`purchase_trigger` across a batch of orders that share one real answer.** Josh's example: LEGO.com orders from a promotional bonus-GWP window (community-sourced tip) shouldn't require re-answering the same two-field question 45 separate times — the tool should let a batch of rows sharing one true answer get tagged together in a single action. This is a UI/workflow feature, not a schema change — `buy_reason`/`purchase_trigger` stay exactly as CONTEXT.md already defines them; the gap was always "answer this once for N rows," not "we're missing a category." A live precedent already exists in `orders`: 2 rows are already tagged `opportunistic` / `community_alert`, which reads as the same shape of decision (a community-sourced tip driving a purchase that wasn't a from-scratch targeted hunt). **Confirmed by Josh (2026-09-06):** `opportunistic` / `community_alert` — matching the existing precedent, not `planned`. RetailMeNot unexpectedly released codes for a bonus GWP (set 40762) on LEGO.com orders of $100+; the promo was called out in Josh's Brickdomain community, and he used the opportunity to buy sets that were still in stock ahead of their end-of-July retirement, plus some higher-tier sets retiring in December. The GWP promo itself wasn't hunted for or anticipated — it was a community tip acted on opportunistically — which is exactly the `opportunistic`/`community_alert` shape, not a `planned` targeted GWP-hunt. This is now the confirmed default the bulk-tag action applies to that batch, and a good concrete worked example to test the batch-tag feature against once built (retailer=LEGO, GWP set 40762, $100+ threshold, community source=Brickdomain).

**4. Retailer-aware quick-pick, not one generic dropdown for every retailer.** Josh's observation: LEGO carries the system's full range of real answers (`planned` targeted buys, deliberate GWP-hunts, Kohl's-style `promo_expiration` timing), but Walmart, Macy's, Target, and Amazon realistically only ever produce two answers in practice — a sale found on its own (`opportunistic` + `self_discovered`) or a price alert from a community/app source (`opportunistic` + `community_alert` or `deal_software_alert`). The tool should offer a simplified two-button quick-pick for those retailers by default, with the full field set still reachable for the rare exception, rather than presenting the same undifferentiated dropdown everywhere. No new field values needed — this is entirely a UI-affordance decision layered on the existing taxonomy.

**Net effect on Action Items above:** item 2 (enumerate fields to show) now also needs to spec the progress counter and the bulk-tag/quick-pick UI, not just the per-row promote/discard fields.
