# ResellOS — Claude Context Document
**Last Updated: 2026-05-30**
**Read this first. This document orients Claude at the start of every conversation.**

> **Document home & sync rule:** The source-of-truth copy lives in the GitHub repo (`theroyalcrate/ResellOS`), edited via Claude Code. An identical copy lives in the Claude project here so chat-Claude starts every conversation current. **When this doc changes: update the repo copy via Claude Code first, then paste the same content into the project copy.** Keep them identical — drift between the two causes re-walking already-completed work.

---

## What ResellOS Is

ResellOS is a personal business operating system being built by a LEGO reseller with 15 months of live experience and $160K revenue / $72K net profit proven. It is not a theoretical product — it is being built to run an active reselling business first, then offered to other resellers as a community product.

The core problem it solves: resellers who have proven the model are trading time for money in a way that isn't sustainable. ResellOS gives them their time back through accurate tracking, automation, and insight — without sacrificing the income.

**Primary vertical: LEGO.** Architecture is designed to generalize to other reselling categories over time.

**The builder:** A complete beginner to coding and development learning as he builds. Needs step-by-step guidance with no assumed knowledge. Every instruction should be explicit — what to open, what to click, what to copy, where to paste. He works evening sessions after his day job (mortgage) and golf. Sessions are typically 1-3 hours.

---

## The Single Most Important Design Principle

**Own your data, rent enrichment.**

Core transactions, cost basis, inventory, and sales always live in the user's own database. Market data, set information, and pricing signals are useful enrichment but never load-bearing. This is a direct response to the Camelcamelcamel cautionary tale — they lost value when Amazon cut API access. ResellOS core functions must never depend on any third-party API to work.

---

## Current Tech Stack

- **Database:** Supabase (PostgreSQL) — cloud-hosted, RLS enabled, user_id on every table. Live from day one. There is no SQLite. The architecture doc references SQLite but that decision was reversed before S01. Supabase is permanent.
- **Language:** Python 3.14 with virtual environment
- **Version control:** GitHub — repo: theroyalcrate/ResellOS
- **Development environment:** VS Code + Claude Code extension
- **MCP connectors connected:** Supabase ✓, GitHub ✗ (not connecting — does not appear under connections; standalone troubleshoot pending. Chat-Claude can reach Supabase directly but NOT GitHub or the local repo — use Claude Code for anything touching local files.)

---

## Build State — Where We Are Right Now

**Sessions S01 through S08 are complete and committed to GitHub. S8.5 (field refactor) done 2026-05-30.**

| Session | What Was Built | Status |
|---------|---------------|--------|
| P0 | Dev environment, GitHub repo, Gmail infrastructure, invoice parser (Agent 1A) | ✓ Done |
| S01 | Database — 21 tables in Supabase, migrations 002-020 applied | ✓ Done |
| S02 | Connect Agent 1A to database — shipments model flaw found and fixed | ✓ Done |
| S03 | Agent 02 — manual order entry, 2 real orders in Supabase | ✓ Done |
| S04 | Agent 1A shipments model verified, SSL fix, split payment bug fixed | ✓ Done |
| S05 | Agent 05 — gift card ledger, single + bulk entry, balance tracking | ✓ Done |
| S06 | Agent 02 overhaul — full retailer rewards for all 7 retailers | ✓ Done |
| S07 | Agent 07 — cashback pool manager, 6 platforms | ✓ Done |
| S08 | Cost basis engine (Agent 04) — 5 layers, 4 costing methods, GWP Philosophy C, verified | ✓ Done |
| S8.5 | Intent/channel field split — buy_reason + purchase_trigger refactor, data cleaned | ✓ Done |
| S09 | Barnes Scrapyard verification (Layer 3 rewards) + Agent 1B invoice filing | → Next |

**Database state:** 22 tables live, migrations 002-027 + 008-010 applied, 5 orders in DB, RLS enabled on all tables.

---

## The Cost Basis Engine — What Was Built (S08)

Five layers calculated in order:

1. **Invoice cost** — tax-inclusive economic cost (what gift card actually cost)
2. **Gift card discount** — face value minus purchase price, applied to order economic cost
3. **Retailer rewards redemption** — rewards redeemed ON this order reduce economic cost. Rewards EARNED do not affect cost basis until spent on a future order.
4. **Cashback allocation** — toggleable pending CPA guidance. When activated, quarterly payout allocated back to originating orders.
5. **GWP net proceeds** — Philosophy C: GWP carries $0 cost basis. Net proceeds reduce originating order economic cost. Reallocated across paid items only.

**GWP Philosophy C (proceeds_reduce_order):**
- GWP $0 cost basis at receipt always
- Net proceeds reduce order economic cost when GWP sells
- 12-month provisional window — paid items settle after 12 months at current economic cost
- Cost basis locks at settlement — returns after settlement create P&L adjustment entries, never reopen cost basis
- Negative cost basis is valid and correct — never suppress
- GWP status values: pending, sold, retained_personal, donated, lost_damaged
- Configurable via `users.gwp_cost_treatment`: proceeds_reduce_order (default), proportional_msrp, zero_no_allocation

**Cost basis state on orders:** estimated → provisional → settled

**Two separate cost concepts — never conflate:**
- `true_cost_basis` — acquisition cost, locks at settlement
- `extended_cost_basis` — true_cost_basis + accumulated storage carrying cost, always current

**Verification confirmed:** Order T487170400 — $150.98 economic cost, $87.03 GWP proceeds, $63.95 net → Moana's Flowerpot $16.83/unit, Wednesday and Enid $5.05, The Armory $8.41. All exact. ✓

**Minor deferred items (future cleanup sprint):**
- tax_paid_allocated always writes 0 — needs real allocation logic
- Mode 3 settle never writes gwp.settlement_date
- Dead elif branch in collect_gwp_proceeds
- net_economic_cost calculated twice at different precision
- _test_setup_t487170400.py in repo root — move to /tests folder

---

## Retailers Currently in the System

All 7 retailers have full reward profiles built in Agent 02:

| Retailer | Reward Mechanic | Notes |
|----------|----------------|-------|
| LEGO | Insider points (6.5 pts × spend × multiplier), per-set bonuses | Online only, no pickup. supports_pickup = false always. |
| Barnes & Noble | Stamps = floor(pretax/10) × multiplier | Stamp threshold tracking critical |
| Kohl's | 5% Rewards Cash + Event Kohl's Cash ($10/$50 thresholds) + pickup bonus | Cliff edge on thresholds |
| Macy's | Bronze tier 1pt/$1, Bonus Day overrides, Star Money | Gift cards earn 0 points |
| Walmart Business | 2% on orders over $250 — calculated on original order value at placement, NOT final total | Pickup orders common |
| Target | Circle debit card flag, one-off offers manual entry | Pickup supported |
| Best Buy | Promotional offers manual entry only | Pickup supported |

**Cashback platforms (Agent 07):** Rakuten, RetailMeNot, Capital One Shopping, Microsoft Shopping, Honey, TopCashback + Other write-in.

---

## Key Business Logic — Things Claude Must Know

### Buy reason — intent (why the trigger was pulled). REVISED 2026-05-30, supersedes prior `sale_gwp`/`clearance_opportunistic` scheme.

`buy_reason` captures *intent* — the one signal only a human knows at purchase that cannot be reconstructed from data later. Deal mechanics (sale/GWP/clearance/cashback) are NOT encoded here — they live in their own tables (discount fields, `gwp`, `cashback_transactions`, `promotional_cash`) and must not be duplicated.

- **Type:** nullable text, no DB constraint. Default null. Three values:
  - `planned` — targeted buy (I went looking for it). Includes deliberate GWP-value-driven buys where stacked GWPs make the math work — the GWP *value* is mechanic (in the gwp table); the *decision to target it* is intent.
  - `opportunistic` — wasn't targeting it; a clearance/sale price found me.
  - `promo_expiration` — bought mainly to use expiring Kohl's Cash / Star Money. ROI here is promo-subsidized (compressed cost basis); read on a different yardstick. If untagged, these inflate the ROI of whatever category they land in.

### Purchase trigger — channel (how the deal was found). Separate field, separate axis.

- **Type:** nullable text, no DB constraint. Default null. Three values: `community_alert`, `deal_software_alert`, `self_discovered`.
- Dropped from the old six-value list: `planned`/`planned_seasonal` (intent → now `buy_reason`), `cashback_opportunity` (deal mechanic → cashback table).

**Why two fields:** intent (why) and channel (how I found it) are different questions; one text field can only cleanly answer one. Kept as two single-purpose fields so each is unambiguous to fill and trustworthy to query.

**Surfacing (both fields, same rules):** null by default; hidden from basic users entirely (zero friction, core never depends on them); surfaced for upgraded users with manual override. When a hit list exists (future opt-in enrichment), a hit-list match auto-sets `buy_reason = planned`. The hit list is NOT a core dependency — design for it, build later.

**Validation gap (known, deliberate):** values are enforced only by the Agent 02 prompts, not the DB. No check constraint while value sets settle. UI dropdowns will enforce values at source. Revisit when email agents write these fields programmatically.

### Retirement flag
`is_retiring` (line-item level) defaults TRUE on every line item. User only toggles if they know a set is NOT retiring. No extra prompts — friction kills consistency. This is a **different axis** from buy_reason: a fact about the *set*, not the purchase *intent*. The two no longer need to agree.

### FIFO costing method
Selected (Decision 002). Must confirm with CPA before year-end. Do not change after real data accumulates — retrofitting requires recalculating every true_cost_basis ever written.

### Washington State tax recovery
Tax captured at invoice parse time — static known number. Included in Layer 1 economic cost. When recovered after filing, flows as P&L credit not a cost basis change. Cost basis does not reopen.

### GWP (Gift With Purchase)
unit_price = 0.00, msrp = retail price. $0 cost basis always. Proceeds reduce originating order economic cost when sold. See GWP Philosophy C above.

### Personal use orders
Flag at order entry — never enters inventory. Gift card balance reduces normally. Gift card discount on that spend is not claimed as business cost reduction. No attribution percentage needed — handled at order level, not gift card level.

### Rewards earned vs redeemed
Rewards earned are recorded in the pool — no cost basis impact. Rewards redeemed on a new order reduce that order's economic cost (Layer 3). The distinction is critical.

---

## Known Edge Cases Already Designed For

**Partial order cancellations with GWP retention (A-003):**
Occurred 15-20 times in Q4 2025 — a predictable seasonal pattern, not an edge case. LEGO cancels sets but honors GWP from original qualifying order value. Manual adjustment workflow available to ANY tier user at ANY time — no automation dependency. LEGO email infrastructure was unreliable in December — cannot depend on automated detection. Cliff edge warnings for Kohl's and Walmart Business when cancellation crosses threshold.

**Retailer-specific cancellation behavior:**
- LEGO — GWP may still ship despite cancellation. Unique favorable mechanic.
- Barnes — stamps recalculate on shipped total. Proportional reduction.
- Kohl's — threshold-based cliff edge. Cancellation crossing threshold may eliminate Kohl's Cash entirely. Warning required.
- Macy's — Star Money recalculates proportionally on shipped total.
- Walmart Business — 2% threshold cliff. Same cliff edge warning as Kohl's.
- Target, Best Buy — proportional reduction on shipped total.

**Order status framework for pickup orders (A-004):**
`supports_pickup = true`: Walmart, Target, Kohl's, Barnes, Macy's, Best Buy.
`supports_pickup = false`: LEGO always.
Pickup orders sit in `placed` status until user marks picked up. Cost basis calculates only after pickup confirmed. Walmart digital receipts arrive via email (Walmart Pay). Paper receipts are edge cases. Phase 2 build.

**GWP return handling (A-005):**
Cost basis locks at settlement. Returns after settlement create P&L adjustment entries — never reopen cost basis. Returned GWP re-enters inventory at $0 cost basis plus return processing costs. GWP cohort averaging: all units of same set number received as GWP within a rolling 90-day period share averaged proceeds allocation.

**Storage cost allocation (A-006):**
Physical storage unit ($208/month, ~2,500 sets) is a real accumulating cost. Monthly snapshots capture per-unit carrying cost rate. Extended cost basis = true_cost_basis + accumulated_carrying_cost. These are always kept as separate fields. WFS storage fees (~$0.10/month) are negligible and captured in Walmart payment reports — do not route through this system.

**Walmart Business rewards calculation:**
2% likely calculated on original order value at placement, not final pickup/invoiced total. One real order: $290 placed, $204 final pickup, $8.40 rewards credited. Needs confirmation.

**Split payments:** payment_method = 'mixed'. All payment legs captured.

**Split shipments:** One LEGO order can produce multiple invoice PDFs. Shipments table handles correctly.

**Duplicate line items (data hygiene, open):** Some early orders have a set represented twice — once from the parser (article_number, set_number) and once from manual Agent 02 entry. This is a cross-path historical artifact, NOT an ongoing bug. No cross-path idempotency guard exists yet. Must be cleaned before further cost-basis work, and email agents must be designed to enrich existing orders rather than duplicate line items.

---

## Planned Future Systems (Not Yet Built)

**S09 — Barnes Scrapyard Verification + Agent 1B**
Verify cost basis engine Layer 3 (rewards redemption) against Barnes Scrapyard order ($52.43 rewards redemption, $21.65 out of pocket). Then connect Gmail + Google Drive, build Agent 1B to download, rename, and file invoices.

**Email Order-Confirmation Agents (Planned — next build focus)**
Per-retailer order-confirmation email parsers, starting with LEGO, then one agent per retailer, then a general confirmation agent to ensure all confirmation emails are handled. Must handle a new/unbuilt retailer gracefully when an email arrives. CRITICAL: must enrich/match existing orders, not duplicate line items (no cross-path idempotency guard exists). Leave buy_reason and purchase_trigger null — agents never guess intent or channel.

**Hit List (Future opt-in enrichment — NOT core)**
Annual list of sets retiring within the calendar year that meet appreciation-probability metrics, built at start of each year. When present, it is the authoritative source that auto-sets `buy_reason = planned` for matching buys. Opt-in premium/power-user feature — deliberately NOT part of basic onboarding (heavy onboarding deters adoption). Depends on unbuilt systems (Set Reference Agent, accumulated history, Brickset/Bricktap validation). Design for it now, build later. Connects to `promotional_cash` (expiry data could later auto-detect `promo_expiration` buys).

**Set Reference Agent (Planned — before Phase 2)**
Local database of all LEGO sets updated on a schedule. Fields: set number, name, theme, MSRP, retirement status, EOL date, release date, piece count, UPC, EAN.
- Brickset API primary sync source candidate
- LEGO.com catalog endpoints — Brick Dynasty creator pulls directly from LEGO. Rewatch episode to confirm approach.
- Pre-build research: validate Brickset retirement data against Bricktap lists on 20-30 sets
- Initial seed: existing Bricktap retirement lists
- Sync design: full initial load once, weekly delta updates after
- UPC/EAN from Brickset connects Walmart sales to inventory by set number

**Purchase Planner Agent (Phase 2 — A-002)**
Pre-purchase optimization. User selects retailer and budget, target sets feed in, agent calculates optimal combination to maximize rewards, hit GWP threshold with minimum overspend, reach next stamp/tier. Stays in plan mode until user enters order number and gift card details. Then flows to manual order entry. No double entry.

**WFS Shipment Portal (Phase 2)**
Build shipment manifest from inventory, export as CSV matching WFS upload format. Eliminates manual data entry into WFS portal. Extends to FBA shipment creation for Amazon.

**Storage Cost Allocation (A-006 — Phase 1 storage session)**
New tables: storage_locations, storage_snapshots. Two new inventory columns: storage_location_id, storage_assigned_date. Monthly automated snapshots. Carrying cost calculated dynamically from snapshot history. Projections when EOL date available from set reference database.

**Sales Import System**
Walmart reconciliation report structure confirmed: group by Customer Order # and Customer Order line #, sum correct Amount Types. Net proceeds = Product Price + Walmart Funded Savings - 8% commission - WFS fulfillment fee. Tax collected and withheld net to zero. Partner GTIN column = UPC/EAN — connects sales to inventory. Commission Saving column is informational only — negotiated collectibles rate vs standard. Do not use as financial input.

**Intelligence / Reporting Layer (Phase 2-3)**
Passive reporting, pattern recognition, alerts. Requires 6-12 months of data. Examples: stamp expiry alerts, cashback payout timing, seasonal sourcing signals. buy_reason + purchase_trigger tagging powers pattern recognition — ROI by intent, channel-source effectiveness.

**Buying History / Purchase Intelligence (Phase 2-3)**
Discount % by retailer over time, sell-through velocity, ROI by buy_reason. Turns gut feel into repeatable sourcing decisions.

**Inventory / Storage System**
Unit-level tracking — box tracking, location awareness, WFS shipment creation.

**Monthly Expenses Tracker**
Storage units, subscriptions, QuickBooks, recurring overhead.

**Pre-UI Design Task**
Capture screenshots of current reselling software using Claude in Chrome. Annotate pain points and things done well. Produces design brief for ResellOS UI. Key pain points already identified: orders lose cohesion after entry (can't edit without deleting), gift card table popup centers on page requiring scroll. Design direction: high end, polished, dark aesthetic, purposeful color for status, expandable from day one. UI will enforce buy_reason/purchase_trigger values via dropdowns.

---

## Architecture Decisions Already Made (Do Not Reverse Without Flagging)

| Decision | What Was Decided |
|----------|-----------------|
| Database | Supabase PostgreSQL — permanent. No SQLite. No migration planned. |
| Costing method | FIFO — confirm with CPA before year-end |
| GWP cost treatment | Philosophy C — proceeds_reduce_order. Configurable per user. |
| Cost basis locking | Locks at settlement. Returns create P&L adjustments, never reopen cost basis. |
| Negative cost basis | Valid and correct output. Never suppress. |
| Retailer rewards | Separate pools per retailer — earned and spent within each ecosystem |
| GWP | Can occur in any channel. Tax exemption determined by retailer cert, not channel. |
| Tax treatment | User-selected at onboarding based on CPA guidance |
| Tax recovery | Flows as P&L credit after filing. Does not reopen cost basis. |
| Personal use | Handled at order level — flag order as personal, never enters inventory. No attribution % on gift cards or cashback. |
| Storage carrying cost | Separate from true_cost_basis. Always kept as extended_cost_basis. Monthly snapshots. |
| Buy reason / purchase trigger | Two separate fields: buy_reason = intent (planned/opportunistic/promo_expiration), purchase_trigger = channel (community_alert/deal_software_alert/self_discovered). Both nullable, hidden for basic users. Mechanic stays in its own tables. (Revised 2026-05-30) |
| Build environment | VS Code + Claude Code, Python, GitHub |
| API independence | Core functions must never depend on third-party API. Enrichment APIs optional layers only. |

---

## CPA/Attorney Meeting — June 10, 9:00-9:30am

Questions to answer before year-end:

1. **Confirm FIFO** as the costing method. Locks permanently once data accumulates.
2. **Cashback and credit card rewards** — cost reduction (rebate treatment) or income? Affects whether cashback layer in cost basis engine activates.
3. **Washington State sales tax recovery** — does recovered tax reduce COGS retroactively or record as separate income in period received?
4. **S-Corp vs Schedule C** — at $72K net profit year one, does S-Corp election make sense for 2026 or 2027?
5. **Capital One Shopping chain** — cashback redeemed as Macy's gift card, then used for inventory. Does rebate treatment follow the chain or does gift card redemption create a new cost basis event?

---

## Open Questions (Unresolved)

1. **CPA confirmation on FIFO** — confirm before year-end, do not change after data accumulates.
2. **Google Drive migration** — 15 months of historical invoices in personal Drive, need to move to business Drive before invoice archive automation can run.
3. **Walmart Business rewards basis** — confirm whether 2% calculated on original order value or final total. Real example: $290 placed, $204 final, $8.40 credited.
4. **Kohl's cancellation cliff edge** — confirm from Q4 2025 history whether Kohl's eliminated Kohl's Cash entirely or reduced proportionally when cancellation crossed threshold.
5. **Brickset API validation** — validate retirement data against Bricktap lists on 20-30 sets before committing as primary sync source.
6. **LEGO catalog endpoints** — Brick Dynasty creator pulls from LEGO directly. Rewatch episode to confirm approach before Set Reference Agent design session.
7. **Cashback tax treatment** — pending CPA guidance June 10. Determines whether cashback layer in cost basis engine activates.
8. **S08 minor deferred items** — cleanup sprint needed before inventory layer is built. See S08 section above.
9. **Backfill set_number on old line items** — parser captures set_number now (code done), but rows written before that change have null set_number. Re-parse old invoices to backfill.
10. **Duplicate line items** — cross-path (manual + parser) historical artifact. Inspect and clean before further cost-basis work.
11. **GitHub MCP not connecting** — does not appear under connections. Standalone troubleshoot.
12. **Stale project Instructions field** — the project's Instructions panel still holds the old 2026-05-26 context. Sync it to this current doc so fresh conversations don't start stale.

---

## Document Hierarchy — What Supersedes What

1. **Session Log (SESSION_LOG.md)** — single source of truth for build state. Read this before any VS Code session. If anything conflicts, Session Log wins.
2. **This context document** — broad orientation for Claude at conversation start.
3. **Master Architecture Document** — design decisions and agent map. Note: references SQLite which is overridden.
4. **Project Map** — session plan. Note: session numbering shifted from original plan — defer to Session Log for actual sequence.
5. **Ideas Doc** — future feature candidates only. Sequencing section is stale — ignore it.

---

## How to Use This Document

**At the start of every conversation:** Claude reads this document first. It provides enough context to be useful without searching multiple files or relying on potentially stale memory summaries.

**Two copies, kept in sync:** repo copy (source of truth, edited via Claude Code) and project copy (so chat-Claude starts current). When this doc changes, update the repo copy first via Claude Code, then paste identical content into the project copy. Drift between the two causes re-walking completed work.

**Tool access reality:** Chat-Claude (this interface) can reach Supabase directly but CANNOT reach the local repo, GitHub, or VS Code's filesystem. Claude Code can read/write the local repo but is a separate process. For anything touching local files, route through Claude Code.

**When something changes:** Update this document at the end of any session where a significant decision was made, a new system was designed, or a known edge case was documented. A stale context doc is worse than no context doc.

**When in doubt:** Search the Session Log. It is always the most current record of what was actually built.
