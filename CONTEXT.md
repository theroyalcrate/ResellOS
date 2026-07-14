# ResellOS — Claude Context Document
**Last Updated: 2026-06-28**
**Read this first. This document orients Claude at the start of every conversation.**

> **Document home & sync rule (revised 2026-06-21):** This repo is the only copy. The previous "identical copy pasted into the Claude project" was deleted on 2026-06-21 because it kept drifting out of date and caused sessions to start from stale context (this exact conversation started from a 2026-06-04 snapshot while this file had moved on to 2026-06-18). Every Claude surface — plain chat, Cowork, or Claude Code — now reads this file (and SESSION_LOG.md, and CLAUDE.md) live from the repo, or fetches it fresh from GitHub if it has no folder access. Never rely on memory or a cached copy. Enforced by the `resell-os-session-start` skill (`skills/resell-os-session-start.md`) — see CONTEXT.md → "How to Use This Document" below.

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
- **MCP connectors connected:** Supabase ✓, GitHub ✓ (read access confirmed 2026-06-03, re-confirmed live in Cowork 2026-06-21 via `get_me`. Chat-Claude can read the repo directly — there is no project copy to paste into anymore. Writes still route through Claude Code.) Gmail ✓ and Google Drive ✓ also confirmed live in Cowork 2026-06-21 — connected to the actual ResellOS business account (`theroyalcratellc@gmail.com`), same inbox/Drive Agent 1B and Agent 1C use.
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
| Pre-S10 Agent 1B | Agent 1B invoice filing automation — Gmail→Drive→Supabase, 50 unit tests, migration 012, .gitignore UTF-8, OAuth setup. 6 bugs fixed in code review. Needs live test (one real invoice end-to-end). | ✓ Built |
| Pre-S10 Agent 1B+1C | Agent 1B extended: Mode 4 personal Gmail backfill (copy personal LEGO emails → business Gmail, idempotent), Mode 5 personal safety-net filter (labels e.lego.com emails ResellOS-Needs-Copy). Agent 1C scope folded in — no separate Agent 1C session needed. 4 code-review bugs fixed. Needs live test of all 5 modes. | ✓ Built |
| S10 | Phase 3: variable-earn schema (per-order observed rewards + Kohl's Cash block model with explicit expiration) + earn cliff pin against June 8th orders + Agent 1B live test (all 5 modes) | → Next |

**Database state:** 23 tables live, migrations through 012 applied, 5 orders in DB, RLS enabled on all tables.

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
| Macy's | Bronze tier 1pt/$1, Bonus Day overrides, Star Money + promotional Star Money events ($10 blocks per ~$50) | Gift cards earn 0 points. rewards_reduce_taxable_base = false confirmed 2026-06-07 — Star Money is post-tax tender. |
| Amazon | No loyalty program. Business account: tax-exempt (resale cert). Occasional delayed shipment 1% credit (Business only, opt-in). Amazon Prime Visa planned Q4 2026 (5% back). | Dual accounts: Business (preferred, tax-exempt) + Personal (fallback, taxable). Account disambiguation: multi-signal (email format, subject language, order number prefix). supports_pickup = false. |
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
Locked 2026-06-26 (ADR-021). CPA confirmed this is a personal-preference choice — not CPA-mandated. Do not change after data accumulates — retrofitting requires recalculating every true_cost_basis ever written.

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

**Duplicate line items (data hygiene) — guarded against as of 2026-06-21:** Some early orders have a set represented twice — once from the parser and once from manual Agent 02 entry. A live check 2026-06-21 found zero current duplicates. `order_validators.py` (new) now checks for this cross-shipment collision before every write in both `db_writer.write_invoice` (Agent 1A) and `agent_02_order_entry.write_order` — warns, never blocks. Email agents must still enrich existing orders, never duplicate line items, when they're built.

**Email order-matching cascade (A-007 — 2026-06-03):**
Every incoming email is matched to an existing order via a strength-ordered cascade — never creates duplicate line items, never auto-merges on basket alone. This is the cross-path idempotency guard flagged as missing in S8.5. Applies to all per-retailer email agents.

Cascade tiers (strength order):
1. **Order number** — deterministic, enrich directly. CORRECTED 2026-07-05 from real 2026 emails: the order confirmation BODY does contain the order number (`Order: T#########`), plus order date, line items, and totals — confirmations are Tier 1 matchable too. (Prior note said it first appears in the shipping confirmation subject; wrong for current templates.) Full extraction detail: `references/lego_email_parser_spec.md` + fixtures in `tests/fixtures/emails/lego/`.
2. **Set/article number from invoice** — deterministic at line level. Invoice may arrive late or not at all during high-volume drop periods.
3. **Set name + price + date window** — probabilistic. Resolve via product_catalog → whole-basket match → review queue only. Never auto-commit on name alone. Normalize the name, resolve to a catalog_id (auto-create a minimal flagged entry if unknown), match the whole basket.

Identical-basket disambiguation: when the same basket appears multiple times in a short window, never guess on basket content alone. Order number is the only true per-order identity. When an email carries an order number, claim the first unclaimed identical orphan stub and stamp it — interchangeable at claim time, the order number is the identity thereafter. When an email has no order number (order confirmation), distinct emails = distinct orders; deduplicate at email message-id level only, never on basket content.

Keystone binding sequence: order confirmation → shipping confirmation (first email carrying both order number + tracking, binding them) → cashback claim (Rakuten keys on order number) → invoice.

Implementation requirements: review queue (confidence score + candidate cluster), claim ledger, message-id deduplication. Never auto-delete or auto-merge — flag duplicates/abandoned, preserve history. Recommendation: capture order number at order creation (Purchase Planner / manual entry) so stubs are born numbered; name-tier matching is the safety net for confirmation-first flows only.

Full detail: ResellOS-Knowledge vault at Areas/business-logic/email-order-matching.md.

---

## Planned Future Systems (Not Yet Built)

**Agent 1B — Invoice Filing + Personal Backfill (Built — Pre-S10 Agent 1B+1C, 2026-06-17)**
`agents/agent_01b_invoice_filing.py` — Five modes: (1) Preview business queue, (2) File one invoice (business Gmail→Drive), (3) Ledger review, (4) Personal Gmail backfill, (5) Personal safety-net filter. Agent 1C scope folded into Agent 1B — no separate Agent 1C session will be built.

Part 1 (Modes 1-3): Business Gmail → Drive → Supabase ledger. Naming convention: `{order_number}_{RETAILER}_{YYYY-MM-DD}.pdf`. `invoice_files` table keyed on `gmail_message_id`. Label move: ResellOS-Invoices → ResellOS-Filed.

Part 2 (Mode 4): Personal Gmail backfill. Searches `from:(e.lego.com) has:attachment` in personal Gmail, copies each unprocessed email to business Gmail under ResellOS-Invoices, labels personal copy ResellOS-Processed. Idempotent: primary guard = ResellOS-Processed label; secondary guard = `rfc822msgid:` search on business Gmail (catches partial failures where business insert succeeded but personal labeling failed).

Part 3 (Mode 5): Creates Gmail filter on personal account: `from:(e.lego.com)` → label ResellOS-Needs-Copy. Safety net only; P0 forwarding handles most new LEGO invoices.

OAuth: `credentials/token_business.json` (gmail.modify + drive) and `credentials/token_personal.json` (gmail.modify + gmail.settings.basic). Both gitignored via `credentials/`. Run `setup_oauth.py` to generate both (two browser windows, clear labels). Legacy `token.json` auto-migrated to `token_business.json`.

50 unit tests: `tests/test_agent_01b_pure_logic.py`. **Pending: live test of all 5 modes before broader use.**

**S09 — Barnes Scrapyard Verification (Still Deferred)**
Verify cost basis engine Layer 3 (rewards redemption) against Barnes Scrapyard order ($52.43 rewards redemption, $21.65 out of pocket).

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
| Costing method | FIFO — locked 2026-06-26 (ADR-021). CPA confirmed this is a personal-preference choice. Do not change after data accumulates. |
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
| Per-retailer tax behavior (rewards_reduce_taxable_base) | Per-retailer boolean flag, default false. true = promo-cash/coupons are pre-tax discounts that reduce the taxable base; engine must use actual invoice tax, never recompute it. Set only from real invoice evidence — never assumed. Kohl's = true (confirmed 5 orders). Macy's = false (confirmed 2026-06-07 — Star Money is post-tax tender). (DECISION 018, 2026-06-05) |
| Order settlement gate — conditions for cost_basis_state → settled | Settlement is always manual — never auto-advances. Trigger events that raise a settlement_review_flag: (1) a unit from the order sells through Walmart (FIFO match), (2) a GWP from the order sells (Layer 5 applied), (3) 12-month provisional window elapses. All three conditions must pass before settlement is permitted: cashback_status = 'confirmed' for every cashback_transactions row on the order (override allowed with required note); all GWPs resolved (sold/retained/donated/lost) or 12-month window elapsed; cost_basis_state = 'placed'. At settlement: true_cost_basis locks permanently, extended_cost_basis continues updating. Returns after settlement → pl_adjustments table only, never reopen cost basis. Cashback platform priority: Rakuten (email-matchable) → Cap1 (manual) → RetailMeNot (manual). Settlement is per-order (acquisition event), not per-unit — does not require all inventory units sold. (DECISION 019, 2026-06-22) |
| Dual-account retailer architecture | Amazon and Walmart each have Business and Personal accounts with different tax treatment. `retailer_profiles` needs `account_type text DEFAULT 'default'` column + updated unique constraint `UNIQUE (user_id, retailer_key, account_type)`. Will be Migration 013 (012 taken by invoice_files). Affects both Amazon and Walmart — design once, apply to both. |
| Invoice filing (Agent 1B) | `invoice_files` Supabase ledger (migration 012) keyed on `gmail_message_id` — dedup key, checked before any write. One row per email. Gmail two-stage label move: `ResellOS-Invoices` (intake, `Label_2573281147792874926`) → `ResellOS-Filed` (processed, `Label_1`). Drive path: `Invoices/{Retailer}/{Year}/{Month Year}/`. OAuth credentials in `credentials/` (gitignored). (2026-06-10) |
| Authenticated account scraping vs. enrichment scraping (data acquisition boundary) | Two different trust tiers, two different tools. **Authenticated account data** (LEGO order history, gift card balances — anything behind a login) is only ever pulled through the user's own already-authenticated real browser session (Claude in Chrome), one order at a time, at a deliberately slow/human-paced rate, and never run concurrently with the user actively placing orders on the same site. Never use a third-party scraping/proxy service (e.g. Apify) for this tier — proxy rotation is built for anonymous public-page rate-limit evasion, and using it against a logged-in account (new IP/datacenter authenticating with the user's credentials) looks like account-takeover behavior to retailer fraud detection, risking an account lock — a far worse failure mode than a rate limit. **Public/enrichment data** (deal alerts, stock levels, set/retirement data) has no such constraint — it's not account-bound and not load-bearing per the "own your data, rent enrichment" principle, so Apify or similar scraping services are the right tool there; proxy rotation does exactly what it's designed for on anonymous public pages. (Decided 2026-06-20) **Note (2026-06-21): this whole approach is an intentional, acknowledged stopgap** — it backfills orders invoices never captured. The real long-term design is a browser extension that captures order details at the point of purchase, working with the Purchase Planner (Phase 2/4), with invoice parsing confirming/reconciling afterward. Don't over-invest in hardening today's scraping approach; revisit this row when the Chrome extension gets designed. |
| Cashback tax treatment — Layer 4 active; Capital One chain ends at GC acquisition | Cashback is rebate treatment (cost reduction), not income. Layer 4 activated for cash payouts (Rakuten, RMN, etc.). Capital One Shopping can only redeem as gift cards — the chain ends when the GC is acquired at price_paid = $0. Layer 2 handles the discount from there. New `cashback_transactions.status = 'redeemed_as_gc'` prevents double-counting. agent_07 Mode 2 needs a cash/GC branch for C1 payouts. Layer 4 skips `redeemed_as_gc` rows. (DECISION 020, ADR-022, 2026-06-26) |
| Third-party agent frameworks — do not install into this repo (Decided 2026-06-21) | Investigated GSD ("get-shit-done", a Claude Code meta-prompting/spec-driven-development framework) on Josh's request. The original maintainer (TÂCHES) went silent ~7 weeks, deleted his accounts, and a crypto token tied to the project was independently reported by multiple outlets as a ~$500K rug pull — the original npm package is permanently compromised; that maintainer can still push malicious updates to it at will. The community fork (`get-shit-done-redux`) was independently security-audited and found free of backdoors, but the audit flagged unresolved gaps: its safety hooks are advisory-only (warn, don't block), and a documented `@~/...` file-read pattern could be tricked into inlining secrets (SSH keys, credentials) into the AI's context. **This repo holds live credentials** (`.env`, `credentials/`, OAuth tokens) that make that risk concrete, not theoretical. Decision: do not install GSD — original or redux — into this repo. If ever tried, only in a throwaway sandbox with no real credentials. |

---

## CPA/Attorney Meeting — June 10, 9:00-9:30am (outcome clarified 2026-06-21)

1. ✅ **FIFO as the costing method** — resolved 2026-06-26: FIFO locked as ADR-021. CPA confirmed personal-preference choice.
2. ✅ **Cashback and credit card rewards — cost reduction or income** — resolved 2026-06-26: Layer 4 activated (ADR-022). Rebate treatment (cost reduction). C1 chain ends at GC acquisition.
3. **Washington State sales tax recovery** — still open: does recovered tax reduce COGS retroactively or record as separate income in period received?
4. **S-Corp vs Schedule C** — still open: at $72K net profit year one, does S-Corp election make sense for 2026 or 2027?
5. ✅ **Capital One Shopping chain** — resolved 2026-06-26: chain ends at GC acquisition. GC recorded at price_paid = $0. Layer 2 handles the discount. See ADR-022.

---

## Open Questions (Unresolved)

1. ~~**CPA confirmation on FIFO**~~ ✅ RESOLVED 2026-06-26 — FIFO locked as ADR-021. Do not change after data accumulates.
2. **Google Drive migration** — UPDATED 2026-07-13/14: more fragmented than previously described, not one folder. Real structure found via the Zapier Drive connector (personal account): "Lego inventory and purchase tracker." (LEGO-only, consistently month-organized), "The Royal Crate LLC receipts" (an abandoned consolidation attempt, started and last touched ~April 2025), plus separate ad-hoc root-level folders per retailer created after that attempt stalled ("Walmart Business Purchases," "Walmart.com," "Walmart Missed?," "Target receipts," "Barnes And Noble," "Kohls," "Kohl's 2026," "Best Buy"). Full detail: `references/retailer_email_sources.md`. Still needed before migration: a complete root-folder inventory (file counts, date ranges) — not yet built.
3. **Walmart Business rewards basis** — confirm whether 2% calculated on original order value or final total. Real example: $290 placed, $204 final, $8.40 credited.
4. **Kohl's cancellation behavior (updated 2026-06-05)** — community sources say Kohl's Cash is retained on cancellation (not eliminated). Real risk is **stranded gift card balances**: gift cards are not auto-refunded; must call Kohl's to recover (replacement cards mailed). Verify Kohl's Cash retention against a real cancellation if one occurs.
5. **Kohl's Cash earn cliff — exact sub-$50 boundary** — earn threshold is just under $50 post-coupon. Exact penny boundary not yet pinned. Pin against June 8th orders (S10 task).
6. ~~**Macy's Star Money pre-tax vs post-tax**~~ ✅ RESOLVED 2026-06-07 — `rewards_reduce_taxable_base = false` confirmed. Star Money is post-tax tender; tax computed on full merchandise subtotal even when order paid entirely with Star Money. macys.md built.
7. **agent_08 naming collision** — `agent_08_cost_basis.py` is named after session S08, but the conceptual agent numbering calls the cost basis engine "Agent 04" and reserves "Agent 08" for the unbuilt Product Catalog Agent (per CONTEXT.md Planned Future Systems). When Product Catalog is built, `agent_08_product_catalog.py` would collide with the existing file. Decide on a renaming convention before that session.
8. **Brickset API validation** — validate retirement data against Bricktap lists on 20-30 sets before committing as primary sync source.
9. **LEGO catalog endpoints** — Brick Dynasty creator pulls from LEGO directly. Rewatch episode to confirm approach before Set Reference Agent design session.
10. ~~**Cashback tax treatment**~~ ✅ RESOLVED 2026-06-26 — Layer 4 activated (ADR-022). Rebate treatment (cost reduction). C1 chain ends at GC acquisition (price_paid = $0 on GC).
11. **S08 minor deferred items** — cleanup sprint needed. tax_paid_allocated always 0. Mode 3 never writes gwp.settlement_date. Dead elif branch in collect_gwp_proceeds. net_economic_cost calculated twice. _test_setup_t487170400.py → /tests.
12. **Backfill set_number on old line items** — parser captures set_number now, but rows written before that change have null. Re-parse old invoices to backfill.
13. **Duplicate line items** — cross-path (manual + parser) historical artifact. Inspect and clean before further cost-basis work.
14. **Unit-level inventory schema confirmation** — confirm one row per physical unit before building inventory layer. Unit-level rows enable Specific Identification costing; harder to retrofit later.
15. ~~**Cost basis state machine doesn't self-advance**~~ — REFINED 2026-06-21: there isn't a state machine failing to advance — `cost_basis_state` only ever changes when a human runs Mode 1 or Mode 3 in `agent_08_cost_basis.py` (correct, per DECISION 017 — it should never run automatically). The real gap was that nothing reminded anyone an order was ready. Confirmed live: none of the 5 orders in the database have ever had Mode 1 run, including T487170400 whose GWP fully sold a month ago. Addressed with `cost_basis_status_report.py` (built 2026-06-21) — a status report, not an auto-advancer.
16. **Cost basis regression testing — ADR-020 (Proposed, 2026-06-21)** — `agent_08_cost_basis.py` has no automated test suite, only manual code review + one golden-record order. See `ADR-020-cost-basis-regression-testing.md` in repo root. Recommended before Agent 1C's ~635-order historical backfill runs at scale. Not yet built.
17. **Gift card savings (cost basis Layer 2) is never persisted (new 2026-06-21)** — `agent_08_cost_basis.py` Mode 1 collects it interactively and uses it in that one calculation, but writes it nowhere. No way to independently audit or re-derive a past `net_economic_cost` later — only the final per-unit `inventory.cost_basis` survives. Would need a schema addition before any cost-basis audit feature is possible.
18. **LLM enrichment layer — pluggable backend, Phase 3 decision (new 2026-07-05)** — Josh raised running a local open-source model (Ollama) inside ResellOS so future users pay no token costs. Direction agreed 2026-07-05: an LLM is *enrichment, never load-bearing* — same principle as all other enrichment. It must NEVER sit in the money path (cost basis, parsers for known formats, matching cascade stay deterministic Python; wrong data in cost basis is worse than no data). Legitimate LLM jobs, all ending in human confirmation per DECISION 017: (a) reading email formats not yet hardcoded (new retailer, template changes — e.g. the `t.crm.lego.com` template switch found 2026-07-05), (b) pre-sorting the enricher review queue with match suggestions, (c) future natural-language querying. Design as a pluggable interface (e.g. `classify_email() → suggestion`) with backend as per-user config: Ollama (free/local, needs ~8GB+ RAM and setup support), API model (Haiku-class ≈ well under $1/month at realistic reseller email volume — token cost is not the problem it feels like), or off entirely (system fully functional, just more manual review). Same configurability pattern as `gwp_cost_treatment`. Nothing to build now — the enricher's review queue is the future insertion point and is already in the design. Revisit at Phase 3 community launch. Mac mini (arriving ~late July 2026) is a candidate Ollama test machine.

---

## LEGO Order Scrape — Priority System

Historical LEGO order data is captured by walking the live LEGO order history page in the user's already-authenticated browser (Claude in Chrome). This is authenticated account scraping — see Architecture Decisions for the trust-tier boundary that governs it.

**Where the files live (moved 2026-06-21):** This repo, root folder — same place as everything else. Previously these lived in a separate Claude Project folder called "ResellOS software development," which caused real data fragmentation (a Cowork session had defaulted to saving there instead of here). Consolidated into this repo on 2026-06-21; the old folder is now empty.

| File | Contents |
|------|----------|
| `lego_order_numbers_master.txt` | Full master list of all known LEGO order numbers (635 as of 2026-06-20) |
| `lego_orders_todo.txt` | Orders still needing scrape attention (532 as of 2026-06-20) |
| `lego_scrape_priority.csv` | Priority tier per todo order (see tiers below) |
| `lego_gift_cards_master.csv` | Master gift card ledger being assembled from scrape + Brickprobe data |
| `order_gift_card_links.csv` | Maps orders to the gift cards used to pay for them |
| `brickprobe_purchases_2026-06-19.csv` | Brickprobe export (community LEGO purchase-tracking tool) used as cross-reference to avoid re-scraping orders that already have cost/GC data |
| `lego_order_scrape.csv` | Accumulated scrape output — one row per order |
| `lego_priority3_orders.csv`, `lego_priority3_line_items.csv`, `lego_priority3_manual_worklist.csv` | Priority-3 (highest-value) scrape working set |

**Priority tiers in `lego_scrape_priority.csv`:**

| Tier | Label | Count (2026-06-20) | Meaning | Scrape value |
|------|-------|-------------------|---------|-------------|
| 3 | Not in Brickprobe | 55 | No data anywhere else — these orders have no cost or GC info from any source | **Highest — scrape these first** |
| 2 | In Brickprobe, no GC | 378 | Order data exists in Brickprobe but gift card assignment is missing | Medium |
| 1 | GC confirmed by Brickprobe | 133 | Both cost and GC data already resolved via Brickprobe | **Lowest — can likely skip** |

**Rule for future scrape sessions:** Pull the next target from `lego_orders_todo.txt` ordered by priority **3 → 2 → 1** (highest-value gaps first). Do NOT navigate to the live LEGO order history page in default newest-first order — that picks up recent orders before older data gaps are filled, and recent orders will reconcile normally via Brickprobe / invoice matching anyway.

**⚠ Priority direction to verify:** The tier numbering (3 = highest priority) is counterintuitive — confirm against whoever built `lego_scrape_priority.csv` that 3 actually means "scrape first" before running a bulk session against it.

**2026-06-20 process note:** Four orders were captured outside the priority backlog this session by walking the live order history page newest-first: T507760965, T507761629, T507771505, T507787478 (all 2026-06-19/20). These are newer than anything in the backlog and weren't in `lego_orders_todo.txt`. The captures weren't harmful — the data is now in `lego_order_scrape.csv` and will reconcile normally — but it wasn't the right next target. Next session should resume from `lego_orders_todo.txt` at priority 3.

---

## Document Hierarchy — What Supersedes What

1. **Session Log (ResellOS_Session_Log.md)** — single source of truth for build state. Read this before any VS Code session. If anything conflicts, Session Log wins.
2. **This context document** — broad orientation for Claude at conversation start.
3. **Master Architecture Document (v2.1)** — all design decisions current through DECISION 018 (2026-06-05), SQLite references removed, multi-vertical catalog design included.
4. **Project Map (v2.0)** — accurate session history through S8.5, forward plan through community launch and multi-vertical expansion.
5. **Ideas Doc** — future feature candidates only. Sequencing section is stale — ignore it.

---

## How to Use This Document

**At the start of every conversation, on every surface (revised 2026-06-21):** Read CLAUDE.md → CONTEXT.md → SESSION_LOG.md → `stages/CURRENT/CONTEXT.md` (if present) live from this repo before doing or claiming anything about ResellOS's state. If you only have GitHub access and no folder access, fetch the same three files fresh from `theroyalcrate/ResellOS` instead. Never rely on memory, a prior conversation's summary, or a previously pasted copy — there is no pasted copy anymore, and a cached one is exactly what caused this document to go stale before. This rule is enforced by the `resell-os-session-start` skill (`skills/resell-os-session-start.md`); if you're a Claude session that doesn't have that skill loaded, follow this paragraph anyway.

**One copy only:** This repo is the single source of truth. The old "paste an identical copy into the Claude project" arrangement was deleted 2026-06-21 — it drifted out of date repeatedly (this exact document was a full two and a half weeks stale at one point) and caused real rework. There is nothing left to keep in sync.

**Tool access reality:** Claude Code reads/writes this repo locally and always auto-loads CLAUDE.md. Cowork has direct folder access to this same repo when connected. Plain chat (no Cowork) has GitHub read access and can fetch these files fresh — it just can't write local files directly; route writes through Claude Code or through a GitHub commit.

**When something changes:** Update this document at the end of any session where a significant decision was made, a new system was designed, or a known edge case was documented. A stale context doc is worse than no context doc.

**When in doubt:** Search the Session Log. It is always the most current record of what was actually built.