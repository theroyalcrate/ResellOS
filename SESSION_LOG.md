# ResellOS — Session Log

**Single source of truth for build state. Updated at the end of every session. Read this first before opening VS Code.**

| | |
|---|---|
| **Last Updated** | 2026-06-04 |
| **Sessions Complete** | S01 → S08 ✓, S8.5 ✓ |
| **Next Session** | S09 |
| **Phase** | P1 — Week 2 |
| **GitHub** | theroyalcrate/ResellOS |

> **Document home & sync rule:** Source-of-truth copy lives in the GitHub repo, edited via Claude Code. GitHub MCP read access confirmed 2026-06-03 — chat-Claude can read the repo directly. Manual paste into project copy is no longer required. Writes still route through Claude Code.

---

## Start Here — Next Session

### S09 — Barnes Scrapyard Verification + Agent 1B + Gmail/Drive Connection

**Goal:** S08 is complete and verified on Order T487170400 (all 5 layers, $63.95 net economic cost confirmed). S09 has two goals: (1) verify the cost basis engine Layer 3 rewards redemption using the Barnes Scrapyard order ($52.43 rewards redemption, $21.65 out of pocket) — proves the rewards layer works correctly; (2) connect Gmail and Google Drive MCPs, then build Agent 1B to download LEGO invoices, rename to order number format, and file into the correct Drive folder. Also move _test_setup_t487170400.py from repo root to /tests folder.

1. Connect Gmail MCP and Google Drive MCP in Claude.ai connectors — both personal and business Gmail accounts temporarily
2. Run cost basis engine against Barnes Scrapyard order — confirm Layer 3 rewards redemption calculates correctly ($52.43 rewards, $21.65 out of pocket)
3. Build agent_1b_invoice_filing.py — download PDFs from Gmail, rename to order number format, file into Drive folder structure
4. Move _test_setup_t487170400.py to /tests folder to keep repo root clean
5. Run S08 minor deferred cleanup sprint — tax_paid_allocated, gwp.settlement_date in Mode 3, dead elif branch, net_economic_cost double calculation
6. Code review both new files before commit
7. Commit: "S09: Layer 3 verification, Agent 1B invoice filing, S08 minor fixes" and push

**Note — email order-confirmation agents:** Separate planned focus. Per-retailer confirmation parsers (LEGO first), then one per retailer, then a general catch-all. Must handle an unbuilt retailer gracefully. CRITICAL: enrich/match existing orders, never duplicate line items (no cross-path idempotency guard exists). Leave buy_reason + purchase_trigger null — agents never guess intent or channel.

---

## Current Sprint — Phase 1, Week 2 / Session Status

| Session | Description | Status |
|---------|-------------|--------|
| S01 | Database creation — 21 tables in Supabase. Migrations 002–020 applied. RLS + user_id on every table. | ✓ Complete |
| S02 | Connect Agent 1A output to database. Order-vs-shipment flaw found — one order can produce multiple invoice PDFs. Shipments table added (migration 003). No data loss. | ⚠ Partial |
| S03 | Agent 02 — manual order entry. orders → shipments → line_items. Insider points auto-calculated. Duplicate detection. 2 real LEGO orders. Committed. | ✓ Complete |
| S04 | Update Agent 1A — shipments model + verification. Verified vs 2 real invoices. SSL fix for Python 3.14 on Windows. Migration 002. Split payment bug fixed. Committed + pushed. | ✓ Complete |
| S05 | Gift card ledger — single + bulk entry, discount_pct, balance tracking. agent_05_gift_cards.py. Migration 003. Verified. Committed + pushed. | ✓ Complete |
| S06 | Full retailer rewards overhaul — all 7 retailers. agent_02 overhauled. Migrations 004-006. Code review: 4 MODERATE fixed. Committed + pushed. | ✓ Complete |
| S07 | Cashback pool manager — 6 platforms. agent_07_cashback.py. 3 modes. Migration 007. Code review: 2 CRITICAL + 4 MODERATE fixed. Committed + pushed. | ✓ Complete |
| S08 | Cost basis engine — 5 layers, 4 costing methods, GWP Philosophy C. Migrations 008-010. Verified on T487170400. 2 CRITICAL + 4 MODERATE fixed. Committed + pushed. | ✓ Complete |
| S8.5 | Intent/channel field split — buy_reason + purchase_trigger refactor. Data cleaned. Code-only (no migration). | ✓ Complete |
| Pre-S09 (2026-06-01) | Outside VS Code: Obsidian + ResellOS-Knowledge repo setup, PARA vault structure, DECISION 017 added to architecture doc. | ✓ Complete |
| Pre-S09 (2026-06-03) | Vault content phase: lego.md + lego-instore.md + email-order-matching.md committed to Knowledge vault. GitHub MCP read access confirmed. CONTEXT.md + SESSION_LOG.md corrected. A-007 in CONTEXT.md. | ✓ Complete |
| S09 | Layer 3 verification + Agent 1B invoice filing + Gmail/Drive connection | → Next |

---

## Database — Current State

**Supabase PostgreSQL — Live**

- **22** tables live
- Migrations applied through **010**
- **5** orders in DB
- **RLS ON** — every table secured
- **Multi-user** — user_id on every table
- Code committed to GitHub (note: GitHub MCP not currently connecting — verify via Claude Code)

**Key tables confirmed live:** orders (+ cost_basis_state, buy_reason, purchase_trigger), shipments, line_items (+ set_number, is_retiring), inventory, sales, gift_cards, gift_card_assignments, rewards_transactions, cashback_transactions, gwp (+ status, net_proceeds, sale_date, settlement_date), tax_recovery, market_events, promotional_cash, returns, retailer_profiles, retailer_cashback_profiles, portal_health, business_expenses, inventory_check_sessions, inventory_check_items, users (+ gwp_cost_treatment, costing_method) — 22 tables total.

---

## Session History

### Pre-S09 — Vault Content Phase + GitHub MCP Confirmed ✓ Done — 2026-06-03

**What was done (outside VS Code and in chat-Claude):**
- Vault scaffolding already existed from 2026-06-01; content phase begun
- Discovered CONTEXT.md and SESSION_LOG.md were stale (predated 2026-06-01 vault setup) — corrected both documents
- GitHub MCP read access confirmed (Claude Github 3 connector) — chat-Claude can now read the repo directly; manual paste of project copy no longer required
- Retailer notes committed to ResellOS-Knowledge vault:
  - **lego.md** (updated) — earn rate confirmed pre-tax, full LEGO email family documented with real samples (order confirmation, shipping confirmation, invoice), promo-code GWP class (StudentBeans, Capital One Shopping), private edge cases (purchase limits, GWP-on-cancellation mechanic), invoice layout confirmed from real receipt
  - **lego-instore.md** (new) — receipt signature, strategic context (in-store vs online trade-offs), cashback null default for in-store, in-store exclusive bonus points
- **email-order-matching.md** committed (A-007) — full order matching cascade with identical-basket disambiguation, keystone shipping email binding, email-level idempotency, claim ledger requirement
- CPA meeting prep note identified as next vault priority (June 10, 9:00am)
- Next vault sessions: Barnes, Kohl's, Macy's retailer notes; cashback platform email patterns; CPA prep note

---

### Pre-S09 — Outside VS Code Activity ✓ Done — 2026-06-01

**What was done (outside VS Code, no code changes):**
- Obsidian installed as knowledge management tool
- ResellOS-Knowledge private GitHub repo created at github.com/theroyalcrate/ResellOS-Knowledge
- PARA folder structure built inside Obsidian vault: Projects / Areas / Resources / Archive with subfolders
- Vault wired to GitHub remote and push verified
- DECISION 017 (Order Edit Lifecycle & Cost Basis Trigger Gate) added to ResellOS Master Architecture Document — defines order status values (stub → pending_review → confirmed → placed → settled), cost basis trigger gate, email agent field rules, editable fields by status, and gift card ledger atomic write pattern
- Architecture document version bumped to v2.1, `.gitignore` updated to exclude `/knowledge`

---

### S8.5 — Intent/Channel Field Split — buy_reason + purchase_trigger Refactor ✓ Done — 2026-05-30

**Why this session:**
- Verifying pre-S08 task state revealed buy_reason used a mechanic-based scheme (sale_gwp / clearance_opportunistic) that conflated "why I bought" with "how the deal worked"
- Agent 02 also had a separate purchase_trigger field (6 values) that overlapped — both fields partly answered the same question
- Resolved before email agents get built, since those will write these fields and bake in whatever scheme exists

**Decision — two clean single-purpose fields:**
- buy_reason = INTENT (why I pulled the trigger): `planned`, `opportunistic`, `promo_expiration`
- purchase_trigger = CHANNEL (how I found the deal): `community_alert`, `deal_software_alert`, `self_discovered`
- Deal mechanic (sale/GWP/clearance/cashback) is NOT encoded in either — already lives in discount fields, gwp table, cashback_transactions, promotional_cash
- Both nullable, default null. Null = "not yet classified" (honest). Hidden from basic users, surfaced for upgraded users with manual override.
- Future hit list (opt-in enrichment, not core dependency) auto-sets buy_reason = planned on match. Designed for, not built.
- promo_expiration buys (expiring Kohl's Cash / Star Money) carry promo-subsidized ROI — must be read on a different yardstick or they inflate other categories

**What changed:**
- agent_02_order_entry.py — both prompts updated to new values, defaults removed (null-skippable), null-handling verified (writes true SQL NULL not empty string)
- No DB migration — both columns already plain nullable text, no constraint
- is_retiring unchanged — confirmed it's a different axis (fact about the set, not purchase intent)

**Data cleanup (Supabase, 5 orders):**
- T487170400: buy_reason sale_gwp → planned (deliberate GWP-value-driven buy; 3 GWPs dropped effective basis to ~35% of retail — that's mechanic; intent was "planned")
- All 5 orders: purchase_trigger 'planned' → null (invalid channel value; channel was never truly recorded)
- Verified: no retired values remain in either field

**Carry-forward:**
- ⚠ Re-parse old invoices to backfill null set_number on parser-written line_items (Task 1 code done; old rows predate it)
- ⚠ Duplicate line items (manual + parser entry of same sets) — inspect and clean before further cost-basis work
- ⚠ Email agents need cross-path idempotency — must enrich existing orders, not duplicate line items
- ⚠ Value validation / DB check constraint deferred — UI dropdowns will enforce values at source
- ✕ GitHub MCP not connecting — standalone troubleshoot

**Commit message:**
```
S8.5: Split intent (buy_reason) from channel (purchase_trigger) — 3 values each, nullable, data cleaned
```

---

### S08 — Cost Basis Engine — 5 Layers, 4 Costing Methods, GWP Philosophy C ✓ Done — 2026-05-27

**Pre-S08 tasks completed first:**
- ✓ invoice_parser.py — now captures public set number (e.g. 10242) alongside internal article number. Writes to set_number in line_items.
- ✓ agent_02_order_entry.py — buy_reason field added. is_retiring boolean added to line items, defaults TRUE, single toggle to override. (Buy reason scheme later revised in S8.5.)
- ✓ Migrations 008-010 applied — buy_reason, is_retiring, GWP lifecycle columns, cost_basis_state on orders.

**What was built:**
- agent_08_cost_basis.py — three modes: calculate, write to inventory, review order state
- Five cost layers: invoice cost (tax-inclusive) → gift card discount → retailer rewards redemption → cashback allocation (toggleable) → GWP net proceeds
- All four costing methods: FIFO, LIFO, Average Cost, Specific Identification — stored in users.costing_method, locks per tax year
- GWP Philosophy C (proceeds_reduce_order) — $0 cost basis at receipt, net proceeds reduce order economic cost, 12-month provisional window, reallocated across paid items only
- GWP treatment configurable: proceeds_reduce_order (default), proportional_msrp, zero_no_allocation
- GWP status values: pending, sold, retained_personal, donated, lost_damaged
- Cost basis locks at settlement — returns create P&L adjustment entries, never reopen
- Negative cost basis is valid — never suppressed
- Cost basis state: estimated → provisional → settled
- Cancelled line items excluded from cost allocation

**Verification — Order T487170400 (LEGO 2025-12-03):**
- Economic cost: $150.98 (gift card purchase price, tax-inclusive)
- GWP proceeds: $87.03 total (40705: $16.91 / 40596: $37.40 / 40778: $32.72)
- Net economic cost: $63.95 ✓
- Moana's Flowerpot 43252 — $16.83/unit × 3 ✓
- Wednesday and Enid 40750 — $5.05 ✓
- The Armory 21252 — $8.41 ✓
- All values match expected to 2 decimal places — verification passed

**Code review results:**
- ✓ C1 CRITICAL fixed — orders.cost_basis_state missing from schema, settlement lock never fired (migration 010)
- ✓ C2 CRITICAL fixed — overwrite delete unchecked, FK RESTRICT failure silent causing duplicates
- ✓ M1 fixed — cashback pending filter included written_off/ineligible
- ✓ M2 fixed — Mode 1 allowed settled write with pending GWP items, provisional guard added
- ✓ M3 fixed — GWP proceeds not persisted when gwp_id is None
- ✓ M4 fixed — order state update result never checked
- ⚠ MINOR deferred — dead elif branch, duplicate calculation, tax_paid_allocated always 0, Mode 3 never writes gwp.settlement_date — cleanup sprint in S09

**Design decisions this session:**
- GWP Philosophy C selected — proceeds_reduce_order is default for all users
- Personal use orders flagged at order level — never enter inventory. No attribution %.
- Rewards earned have no cost basis impact until redeemed on a future order
- Tax recovery flows as P&L credit after filing — does not reopen cost basis
- A-005: GWP return handling — cost basis locks, returns create P&L adjustments
- A-006: Storage cost allocation — physical unit monthly snapshots, WFS fee tiers, 365-day aging alert

**Also noted:**
- Walmart reconciliation report structure analyzed — net proceeds = Product Price + Walmart Funded Savings - 8% commission - WFS fulfillment fee
- WFS storage fee tiers: $0.75/cu ft (0-365 days), $2.25 (366-450), $7.50 (450+). New 450+ tier effective June 30 2026.
- CPA/Attorney meeting scheduled June 10 9:00-9:30am — 5 questions prepared
- ⚠ _test_setup_t487170400.py in repo root — move to /tests in S09

**Commit messages:**
```
S08-pre: Set number extraction in invoice parser, buy_reason + is_retiring, migrations 008-010
S08: Cost basis engine — 5 layers, 4 costing methods, GWP Philosophy C, verification confirmed
S08: Code review — 2 CRITICAL 4 MODERATE resolved before commit
```

---

### S07 — Cashback Pool Manager — 6 Platforms ✓ Done — 2026-05-26

**What was built:**
- agent_07_cashback.py — 3 modes: earn, payout received, review status
- 6 platforms: Rakuten, RetailMeNot, Capital One Shopping, Microsoft Shopping, Honey, TopCashback + Other write-in
- Platform-specific rules: RMN same-day warning + 90-day dispute window, C1 Shopping gift card redemption → gift_cards table
- Onboarding insight shown once per platform on first use
- Migration 007 applied. Verified. Committed + pushed.

**Code review:** 2 CRITICAL fixed during build, 4 MODERATE fixed post-review. MINOR deferred: mode_payout 183 lines — future refactor candidate.

**Commit messages:**
```
S07: Cashback pool manager — 6 platforms, earn/payout/review modes
S07: Code review MODERATE fixes
```

---

### S06 — Full Retailer Rewards Overhaul — All 7 Retailers ✓ Done — 2026-05-26

- agent_02_order_entry.py overhauled — full reward logic all 7 retailers
- LEGO, Barnes, Kohl's, Macy's, Walmart Business, Target, Best Buy all complete
- Migrations 004-006 applied — 9 new DB columns
- Barnes Scrapyard verification: 14 stamps confirmed ✓

**Commit message:** `S06: Full retailer rewards overhaul — all retailers`

---

### S05 — Gift Card Ledger ✓ Done — 2026-05-26

- agent_05_gift_cards.py — single entry, bulk entry, view ledger modes
- Captures: retailer, face_value, price_paid, discount_pct (auto-calculated), last 4 digits, date purchased, status, balance_remaining
- Migration 003 applied. Verified. Committed + pushed.

**Commit message:** `S05: Gift card ledger — single + bulk entry, balance tracking`

---

### S04 — Update Agent 1A — Shipments Model + Verification ✓ Done — 2026-05-23

- 2 real LEGO invoice PDFs parsed and written to Supabase successfully
- Split payment bug fixed — payment_method = 'mixed' on split orders
- SSL fix applied for Python 3.14 on Windows
- Migration 002 applied. Committed + pushed.

**Commit messages:**
```
S04: Verification fixes — SSL, schema discovery, migration 002
S04: Fix split payment capture — collect all payment legs, set mixed
```

---

### S03 — Agent 02 — Manual Order Entry ✓ Done — 2026-05-22

- agent_02_order_entry.py — CLI script for manual order entry
- Writes to orders → shipments → line_items. Duplicate detection. Confirm before save.
- Two real LEGO orders in Supabase. Committed + pushed.
- ⚠ Deferred: GWP record creation, rewards transaction records, gift card assignment records — later sessions

**Commit message:** `S03: Agent 02 manual order entry with auto-calculated insider points`

---

### S02 — Connect Agent 1A — Flaw Found ⚠ Partial — ~2026-05-18

- invoice_parser.py connected to Supabase via --db flag
- ⚠ Critical flaw found: one LEGO order can produce multiple invoice PDFs
- Migration 003 added shipments table to fix the data model. No data loss.

---

### S01 — Database Creation — 21 Tables ✓ Done — ~2026-05-18

- Supabase project created — PostgreSQL, RLS auto-enabled
- schema.sql — original 10-table schema, expanded to 21 via migrations 002-020
- Python virtual environment. supabase-py installed. GitHub repo created.

---

### P0 — Phase 0 Complete — Foundation ✓ Done — Pre-S01

- Dev environment — Python, Git, VS Code, Claude Code extension
- GitHub repo — theroyalcrate/ResellOS
- Gmail infrastructure — LEGO invoices forwarded to business inbox, ResellOS-Invoices label filtering
- Agent 1A (invoice_parser.py) — handles standard orders, GWP, discount column, insider points, split payments. Tested against 5 real invoices.

---

## Architecture Doc Corrections

**OVERRIDE 001 — Database Stack (2026-05-18):** The Master Architecture Document lists SQLite → PostgreSQL as a future migration path. This decision was reversed before S01. The project went directly to Supabase (PostgreSQL) from day one. No migration will ever happen. The SQLite path is dead.
- ~~SQLite for local development → PostgreSQL at community launch~~
- → Supabase PostgreSQL from S01 — live, cloud-hosted, no migration path needed

**OVERRIDE 002 — Session Mapping Shift (2026-05-22):** Session numbering shifted when Agent 02 was prioritized ahead of the verification pass. S03 = Agent 02. S04 = verification. All subsequent sessions shifted accordingly.
- ~~S03 — Verify and debug~~
- → S03 — Agent 02 manual order entry. S04 = verify + Agent 1A shipments fix

**OVERRIDE 003 — Ideas Doc Sequencing Stale (2026-05-22):** Ideas doc "Sequencing — Next 7 Days" section is no longer current. Sequencing lives in this document only.
- ~~Ideas doc sequencing section~~
- → Session Log is the only sequencing source of truth

**OVERRIDE 004 — Buy Reason Scheme (2026-05-30):** The original two-value mechanic-based buy_reason scheme conflated why a purchase was made with how the deal worked. Replaced with a two-field intent/channel split. Deal mechanic stays in its own tables. See session card S8.5.
- ~~buy_reason: sale_gwp, clearance_opportunistic — purchase_trigger: planned, planned_seasonal, community_alert, deal_software_alert, cashback_opportunity, self_discovered~~
- → buy_reason (intent): planned, opportunistic, promo_expiration — purchase_trigger (channel): community_alert, deal_software_alert, self_discovered

---

## Open Questions

**CPA/Attorney Meeting — June 10, 9:00-9:30am:** (1) Confirm FIFO — locks permanently once data accumulates. (2) Cashback/credit card rewards — cost reduction or income? Determines whether cashback layer activates. (3) WA State tax recovery — reduces COGS retroactively or separate income in period received? (4) S-Corp vs Schedule C — at $72K net profit year one, 2026 or 2027? (5) Capital One Shopping chain — cashback → Macy's gift card → inventory. Does rebate treatment follow the chain or does gift card redemption create a new cost basis event?

**LEGO Set Number Mapping — resolved for parser:** Parser now captures set_number (Pre-S08 task complete). Still needed: Set Reference Agent — local DB of all LEGO sets with retirement status, EOL date, UPC, EAN, dimensions. Source: Brickset API (validate vs Bricktap lists on 20-30 sets first). LEGO.com catalog endpoints — rewatch Brick Dynasty episode. Initial seed from Bricktap retirement lists.

**Backfill set_number on old line items:** Code captures it now, but rows written before that change have null set_number. Re-parse old invoices to backfill.

**Duplicate line items:** Cross-path (manual + parser) historical artifact, not an ongoing bug. Inspect and clean before further cost-basis work. Email agents must enrich existing orders, not duplicate.

**Google Drive Migration:** 15 months of historical invoices in personal Drive. Move to business Drive before Agent 1B filing automation runs against historical data. Connect Gmail (personal + business temporarily) and Drive MCPs in S09.

**Walmart Business Rewards Basis:** 2% likely on original order value at placement, not final pickup total. Real example: $290 placed, $204 final, $8.40 credited. Confirm from more order data before automating.

**Kohl's Cancellation Cliff Edge:** Confirm from Q4 2025 history whether Kohl's eliminated Kohl's Cash entirely or reduced proportionally when a cancellation crossed the threshold.

**WFS 365-Day Aging Alert — build priority:** WFS storage fee triples at day 366 ($0.75 → $2.25/cu ft/month). New 450+ day tier at $7.50 effective June 30 2026. Aging alert needed before WFS volume grows. 60-day, 30-day, at-threshold alerts. Cubic footage per set from Brickset dimensions.

**S08 Minor Deferred Items — cleanup sprint in S09:** tax_paid_allocated always 0. Mode 3 never writes gwp.settlement_date. Dead elif branch in collect_gwp_proceeds. net_economic_cost calculated twice. _test_setup_t487170400.py → /tests.

**GitHub MCP not connecting:** Does not appear under connections. Standalone troubleshoot. Chat-Claude cannot reach GitHub or local repo regardless — route local file work through Claude Code.

**Stale project Instructions field:** The project's Instructions panel still holds the old 2026-05-26 context. Sync it to the current context doc so fresh conversations don't start stale.

---

## How to Use This Document

**Start of session:** Open this document. Read "Start Here — Next Session" and "Current Sprint." Do not open VS Code until you've confirmed the database state matches what's recorded here.

**End of session:** Update this document before closing VS Code. Record what was completed, what was deferred, commit message, and next session goal. Update the repo copy via Claude Code first, then sync the project copy.

**Tool access reality:** Chat-Claude can reach Supabase directly but NOT GitHub or the local repo. Claude Code reads/writes the local repo. Route local file work through Claude Code.

**What this document supersedes:** The Project Map session descriptions, the Ideas doc sequencing section, and any Claude memory about SQLite. If there's a conflict, this document wins.
