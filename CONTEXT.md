# ResellOS — Claude Context Document
**Last Updated: 2026-06-04**
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

- **Database:** Supabase (PostgreSQL) — cloud-hosted, RLS enabled, user_id on every table. Live from day one. There is no SQLite. The architecture doc has been updated to v2.0 and no longer references SQLite.
- **Language:** Python 3.14 with virtual environment
- **Version control:** GitHub — repo: theroyalcrate/ResellOS
- **Development environment:** VS Code + Claude Code extension
- **MCP connectors connected:** Supabase ✓, GitHub ✓ (read access confirmed 2026-06-03 via Claude Github 3 connector. Chat-Claude can read the repo directly — CONTEXT.md and SESSION_LOG.md no longer need to be pasted into the project copy manually. Writes still route through Claude Code.)
- **Knowledge vault:** Obsidian + ResellOS-Knowledge private GitHub repo (theroyalcrate/ResellOS-Knowledge). PARA structure: Projects / Areas / Resources / Archive. Business logic patterns live at Areas/business-logic/. Set up 2026-06-01.

---

## Build State — Where We Are Right Now

**Sessions S01 through S08 are complete and committed to GitHub. S8.5 (field refactor) done 2026-05-30. Architecture and Project Map documents updated to v2.0 on 2026-05-31. Architecture doc bumped to v2.1 on 2026-06-01 (DECISION 017 — Order Edit Lifecycle & Cost Basis Trigger Gate added). Obsidian knowledge vault (ResellOS-Knowledge) set up 2026-06-01 with PARA structure and wired to GitHub.**

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
| S09 | Kohl's retailer note (5 real orders verified), tax correction (rewards_reduce_taxable_base = true), migration 011, DECISION 018 | ✓ Done |
| S10 | Phase 3: variable-earn schema (per-order observed rewards + Kohl's Cash block model with explicit expiration) + earn cliff pin against June 8th orders | → Next |

**Database state:** 22 tables live, migrations through 011 applied, 5 orders in DB, RLS enabled on all tables.

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

**Minor deferred items (cleanup sprint in S09):**
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
| Kohl's | Variable-rate Rewards Cash (5–15%, card-independent) + event Kohl's Cash (block value varies by event: $10 Sep/Oct, $15 Nov observed) + pickup bonus | rewards_reduce_taxable_base = true (pre-tax discounts, confirmed 5 orders). Earn cliff ~$50 post-coupon. Read amounts from invoice — never compute from a rate. |
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

**Why two fields:** intent (why) and channel (how I found it) are different questions. Kept as two single-purpose fields so each is unambiguous to fill and trustworthy to query.

**Surfacing (both fields, same rules):** null by default; hidden from basic users entirely; surfaced for upgraded users with manual override. When a hit list exists (future), a hit-list match auto-sets `buy_reason = planned`. The hit list is NOT a core dependency — design for it, build later.

### Retirement flag
`is_retiring` (line-item level) defaults TRUE on every line item. User only toggles if they know a set is NOT retiring. No extra prompts — friction kills consistency. This is a **different axis** from buy_reason: a fact about the *set*, not the purchase *intent*.

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

## Multi-Vertical Architecture — Decided 2026-05-31

ResellOS is designed to expand beyond LEGO to other reselling verticals (Pokemon/TCG, wholesale, general online arbitrage) without rebuilding the transaction layer. All architecture decisions made to support this:

**One product_catalog table, all verticals.** A `vertical` field (lego | pokemon | wholesale | book | general) plus `identifier_type` (set_number | sku | upc | asin | isbn) normalizes product identity across categories. LEGO-specific fields (set_number, article_number, is_retiring) remain on line_items as legacy and continue working. A new `catalog_id` FK on line_items bridges to the catalog.

**vertical_config table** stores per-vertical display labels, identifier labels, discontinuation label ("Retiring" vs "Rotating Out" vs "Discontinued"), and enrichment source defaults. UI reads this to show each user a purpose-built experience for their vertical.

**discontinuation_date on product_catalog** generalizes `is_retiring` — applicable to any vertical. `is_retiring` stays on line_items as a LEGO-specific fast-lookup operational flag (defaults TRUE).

**Hit list as a status layer on product_catalog.** Not a separate system. A product moves: catalog entry → hit list (active) → purchased → inventory → sold. Hit list status values: active | purchased | abandoned. Abandoned preserves history, never deletes. Notes field becomes a sourcing decision journal that feeds the intelligence layer. Purchase Planner (Phase 2) consumes hit list as its input queue.

**Order-first onboarding.** New users are not required to pre-load a catalog before entering their first order. When a line item references an unknown product, a minimal catalog entry is created automatically. Catalog import (manual, CSV, Bricktap format) is available immediately but never required.

**Three catalog input methods:**
1. Auto-create on first order (no friction)
2. Manual single entry (daily use — add a set in 60 seconds)
3. CSV upload with flexible column mapper (bulk import, migration)
4. Bricktap retirement list upload (hardcoded mapper for the trusted community format)

**Catalog edits never retroactively affect locked cost basis records.** Edits update reference data only.

**Full business lifecycle:** product_catalog → hit_list → orders/line_items → inventory → sales → tax recovery → intelligence layer. Every vertical flows through the same pipeline with the same cost basis engine.

---

## Known Edge Cases Already Designed For

**Partial order cancellations with GWP retention (A-003):**
Occurred 15-20 times in Q4 2025 — a predictable seasonal pattern, not an edge case. LEGO cancels sets but honors GWP from original qualifying order value. Manual adjustment workflow available to ANY tier user at ANY time — no automation dependency. Cliff edge warnings for Kohl's and Walmart Business when cancellation crosses threshold.

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
Pickup orders sit in `placed` status until user marks picked up. Cost basis calculates only after pickup confirmed.

**GWP return handling (A-005):**
Cost basis locks at settlement. Returns after settlement create P&L adjustment entries — never reopen cost basis.

**Storage cost allocation (A-006):**
Monthly snapshots capture per-unit carrying cost rate. Extended cost basis = true_cost_basis + accumulated_carrying_cost. Always kept as separate fields.

**Walmart Business rewards calculation:**
2% likely calculated on original order value at placement, not final pickup/invoiced total. One real order: $290 placed, $204 final pickup, $8.40 rewards credited. Needs confirmation.

**Split payments:** payment_method = 'mixed'. All payment legs captured.

**Split shipments:** One LEGO order can produce multiple invoice PDFs. Shipments table handles correctly.

**Duplicate line items (data hygiene, open):** Some early orders have a set represented twice — once from the parser and once from manual Agent 02 entry. Cross-path historical artifact, NOT an ongoing bug. Must be cleaned before further cost-basis work. Email agents must enrich existing orders, never duplicate line items.

**Email order-matching cascade (A-007 — 2026-06-03):**
Every incoming email is matched to an existing order via a strength-ordered cascade — never creates duplicate line items, never auto-merges on basket alone. This is the cross-path idempotency guard flagged as missing in S8.5. Applies to all per-retailer email agents.

Cascade tiers (strength order):
1. **Order number** — deterministic, enrich directly. First appears in the shipping confirmation subject — never in the order confirmation email.
2. **Set/article number from invoice** — deterministic at line level. Invoice may arrive late or not at all during high-volume drop periods.
3. **Set name + price + date window** — probabilistic. Resolve via product_catalog → whole-basket match → review queue only. Never auto-commit on name alone. Normalize the name, resolve to a catalog_id (auto-create a minimal flagged entry if unknown), match the whole basket.

Identical-basket disambiguation: when the same basket appears multiple times in a short window, never guess on basket content alone. Order number is the only true per-order identity. When an email carries an order number, claim the first unclaimed identical orphan stub and stamp it — interchangeable at claim time, the order number is the identity thereafter. When an email has no order number (order confirmation), distinct emails = distinct orders; deduplicate at email message-id level only, never on basket content.

Keystone binding sequence: order confirmation → shipping confirmation (first email carrying both order number + tracking, binding them) → cashback claim (Rakuten keys on order number) → invoice.

Implementation requirements: review queue (confidence score + candidate cluster), claim ledger, message-id deduplication. Never auto-delete or auto-merge — flag duplicates/abandoned, preserve history. Recommendation: capture order number at order creation (Purchase Planner / manual entry) so stubs are born numbered; name-tier matching is the safety net for confirmation-first flows only.

Full detail: ResellOS-Knowledge vault at Areas/business-logic/email-order-matching.md.

---

## Planned Future Systems (Not Yet Built)

**S09 — Barnes Scrapyard Verification + Agent 1B**
Verify cost basis engine Layer 3 (rewards redemption) against Barnes Scrapyard order ($52.43 rewards redemption, $21.65 out of pocket). Then connect Gmail + Google Drive MCPs, build Agent 1B to download, rename, and file invoices into Drive folder structure.

**Email Order-Confirmation Agents (Planned — next build focus)**
Per-retailer order-confirmation email parsers, starting with LEGO. CRITICAL: must enrich/match existing orders, not duplicate line items. Leave buy_reason and purchase_trigger null — agents never guess intent or channel.

**Product Catalog Agent (Phase 2 — Agent 08)**
Manages product_catalog and hit_list tables. Manual entry, CSV upload, Bricktap list upload. Auto-creates minimal entry when order references unknown product. Edit and update catalog entries. See Multi-Vertical Architecture section above for full design.

**Set Reference Agent (Planned — before Phase 2)**
Local database of all LEGO sets updated on a schedule. Fields: set number, name, theme, MSRP, retirement status, EOL date, release date, piece count, UPC, EAN. Brickset API primary sync source candidate. Initial seed: existing Bricktap retirement lists. UPC/EAN from Brickset connects Walmart sales to inventory by set number. Pre-build: validate Brickset retirement data against Bricktap lists on 20-30 sets.

**Purchase Planner Agent (Phase 2 — A-002)**
Consumes hit list as input queue. User selects retailer and budget, agent calculates optimal buying combination to maximize rewards, hit GWP threshold with minimum overspend, reach next stamp/tier. Output feeds directly into Agent 02 order entry. No double entry.

**WFS Shipment Portal (Phase 2)**
Build shipment manifest from inventory, export as CSV matching WFS upload format. Eliminates manual data entry into WFS portal.

**Storage Cost Allocation (A-006 — Phase 1 storage session)**
New tables: storage_locations, storage_snapshots. Monthly automated snapshots. Carrying cost calculated dynamically from snapshot history.

**Sales Import System**
Walmart reconciliation report structure confirmed: Net proceeds = Product Price + Walmart Funded Savings - 8% commission - WFS fulfillment fee. Partner GTIN column = UPC/EAN connects sales to inventory.

**Intelligence / Reporting Layer (Phase 2-3)**
Passive reporting, pattern recognition, alerts. Requires 6-12 months of data. buy_reason + purchase_trigger tagging powers pattern recognition — ROI by intent, channel-source effectiveness, cross-vertical ROI comparison.

**Pre-UI Design Task**
Capture screenshots of current reselling software using Claude in Chrome. Annotate pain points. Design direction: high-end, dark, polished, purposeful color for status. UI will enforce buy_reason/purchase_trigger values via dropdowns.

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
| Multi-vertical product identity | One product_catalog table, all verticals. vertical field separates them. identifier_type normalizes product IDs across categories. Catalog edits never affect locked cost basis. (Decided 2026-05-31) |
| Order-first onboarding | No catalog pre-load required. Minimal catalog entry auto-created on first order. Import methods available but never mandatory. (Decided 2026-05-31) |
| Discontinuation date | Generalizes is_retiring to all verticals on product_catalog. is_retiring stays on line_items as LEGO operational flag. (Decided 2026-05-31) |
| Hit list design | Status layer on product_catalog. active → purchased → abandoned. Abandoned preserves history. Notes field = sourcing journal. Purchase Planner consumes as input queue. (Decided 2026-05-31) |
| Order edit lifecycle & cost basis trigger gate | Order status values: stub → pending_review → confirmed → placed → settled. Cost basis gated behind explicit user confirmation — never auto-runs on a stub or partial order. Email agents fill: order number, retailer, date, line items, GWP flags, totals, rewards earned, CC last 4. Agents never fill: gift_card_last4, buy_reason, purchase_trigger, cashback_rate. Confirmed → atomic write: cost basis + gift card balance debit. Reopening to pending_review reverses the prior balance reduction. Settled → P&L adjustments only, cost basis locked permanently. (DECISION 017, 2026-06-01) |
| Per-retailer tax behavior (rewards_reduce_taxable_base) | Per-retailer boolean flag, default false. true = promo-cash/coupons are pre-tax discounts that reduce the taxable base; engine must use actual invoice tax, never recompute it. Set only from real invoice evidence — never assumed. Kohl's = true, confirmed from 5 real orders (Sep 2025 – Jun 2026). Corrects prior wrong assumption that Kohl's Cash is post-tax tender. Macy's Star Money was on the same false assumption — must be verified independently against a real Macy's invoice before setting Macy's flag. (DECISION 018, 2026-06-05, supersedes prior Kohl's rewards-tax framing.) |

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
4. **Kohl's cancellation behavior (updated 2026-06-05)** — community sources say Kohl's Cash is retained on cancellation (not eliminated). Real risk is **stranded gift card balances**: gift cards are not auto-refunded; must call Kohl's to recover (replacement cards mailed). Verify Kohl's Cash retention against a real cancellation if one occurs.
5. **Kohl's Cash earn cliff — exact sub-$50 boundary** — earn threshold is just under $50 post-coupon. Exact penny boundary not yet pinned. Pin against June 8th orders (S10 task).
6. **Macy's Star Money pre-tax vs post-tax** — was on the same false `rewards_reduce_taxable_base = false` assumption as Kohl's, which just proved wrong for Kohl's. Do not change Macy's flag without a real Macy's invoice. Verify when the Macy's retailer note is built.
7. **agent_08 naming collision** — `agent_08_cost_basis.py` is named after session S08, but the conceptual agent numbering calls the cost basis engine "Agent 04" and reserves "Agent 08" for the unbuilt Product Catalog Agent (per CONTEXT.md Planned Future Systems). When Product Catalog is built, `agent_08_product_catalog.py` would collide with the existing file. Decide on a renaming convention before that session.
8. **Brickset API validation** — validate retirement data against Bricktap lists on 20-30 sets before committing as primary sync source.
9. **LEGO catalog endpoints** — Brick Dynasty creator pulls from LEGO directly. Rewatch episode to confirm approach before Set Reference Agent design session.
10. **Cashback tax treatment** — pending CPA guidance June 10. Determines whether cashback layer in cost basis engine activates.
11. **S08 minor deferred items** — cleanup sprint needed. tax_paid_allocated always 0. Mode 3 never writes gwp.settlement_date. Dead elif branch in collect_gwp_proceeds. net_economic_cost calculated twice. _test_setup_t487170400.py → /tests.
12. **Backfill set_number on old line items** — parser captures set_number now, but rows written before that change have null. Re-parse old invoices to backfill.
13. **Duplicate line items** — cross-path (manual + parser) historical artifact. Inspect and clean before further cost-basis work.
14. **Unit-level inventory schema confirmation** — confirm one row per physical unit before building inventory layer. Unit-level rows enable Specific Identification costing; harder to retrofit later.

---

## Document Hierarchy — What Supersedes What

1. **Session Log (ResellOS_Session_Log.md)** — single source of truth for build state. Read this before any VS Code session. If anything conflicts, Session Log wins.
2. **This context document** — broad orientation for Claude at conversation start.
3. **Master Architecture Document (v2.1)** — all design decisions current through DECISION 018 (2026-06-05), SQLite references removed, multi-vertical catalog design included.
4. **Project Map (v2.0)** — accurate session history through S8.5, forward plan through community launch and multi-vertical expansion.
5. **Ideas Doc** — future feature candidates only. Sequencing section is stale — ignore it.

---

## How to Use This Document

**At the start of every conversation:** Claude reads this document first. It provides enough context to be useful without searching multiple files or relying on potentially stale memory summaries.

**Two copies, kept in sync:** repo copy (source of truth, edited via Claude Code) and project copy (so chat-Claude starts current). When this doc changes, update the repo copy first via Claude Code, then paste identical content into the project copy. Drift between the two causes re-walking completed work.

**Tool access reality:** Chat-Claude (this interface) can reach Supabase directly but CANNOT reach the local repo, GitHub, or VS Code's filesystem. Claude Code can read/write the local repo but is a separate process. For anything touching local files, route through Claude Code.

**When something changes:** Update this document at the end of any session where a significant decision was made, a new system was designed, or a known edge case was documented. A stale context doc is worse than no context doc.

**When in doubt:** Search the Session Log. It is always the most current record of what was actually built.