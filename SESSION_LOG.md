# ResellOS — Session Log

**Single source of truth for build state. Updated at the end of every session. Read this first before opening VS Code.**

| | |
|---|---|
| **Last Updated** | 2026-07-18 |
| **Sessions Complete** | S01 → S09 ✓, S8.5 ✓, Pre-S10 ✓, Pre-S10 Agent 1B ✓, Pre-S10 Agent 1B+1C ✓, Pre-S10 Agent 1C standalone ✓, Cowork 2026-06-20 ✓, Cowork 2026-06-21 (parts 1+2) ✓, Cowork 2026-06-22 ✓, Cowork 2026-06-26 ✓, Cowork 2026-06-28 (non-LEGO GC import into Supabase) ✓, Cowork 2026-07-05 (LEGO email parser spec + fixtures) ✓, Cowork 2026-07-05 (eve — email enricher LEGO parser build) ✓, Cowork 2026-07-13 (pipeline audit + retailer casing fix) ✓, Cowork 2026-07-14 (Zapier connector verification) ✓, Cowork 2026-07-18 (eve — OAuth publish fix, invoice_files schema drift fix, first successful Agent 1B live filing) ✓, Cowork 2026-07-18 (late — manual-entry-first architecture decision + Agent 09 Purchase Planner built) ✓ |
| **Next Session** | S10 (variable-earn schema) — Agent 1B is now live-tested and working. Highest-leverage next step is Tier 2 PDF-content matching before bulk-filing the 201-email backlog (see Open Questions). Agent 09 Purchase Planner is built and ready to use for the next planned buying session, but untested against a real one yet. |
| **Phase** | P1 — Week 2 |
| **GitHub** | theroyalcrate/ResellOS |

> **Document home & sync rule (revised 2026-06-21):** This repo is the only copy. There is no project-knowledge paste-in anymore — it was deleted on 2026-06-21 because it kept going stale and caused sessions to start from outdated context. Every surface (plain chat, Cowork, Claude Code) reads CLAUDE.md → CONTEXT.md → SESSION_LOG.md live from this repo (or fetched fresh from GitHub if no folder access) at the start of every session — never from memory or a cached copy. Enforced by the `resell-os-session-start` skill — see `skills/resell-os-session-start.md`.

---

## Start Here — Next Session

**Agent 1B live test is DONE (2026-07-18 evening) — first real invoice filed end-to-end.** Order T469280178's receipt PDF was downloaded from Gmail, uploaded to Drive, logged in the `invoice_files` ledger, and the Gmail label transitioned — all verified independently via direct Supabase/Gmail/Drive checks, not just trusted from a single report. Full detail in the Session History entry below. This closes out the "stalled" period flagged on 2026-07-14 — but it also surfaced a bigger matching gap (Step 1 below) that needs solving before the rest of the backlog can file cleanly.

### Step 1 — Build Tier 2 PDF-content matching (new highest-leverage item, found 2026-07-18):
Tonight's test exposed that `extract_order_number_from_subject()` in `agents/agent_01b_invoice_filing.py` only matches subjects containing "Order" or "Invoice" + digits — but the only LEGO email type that carries a PDF attachment (the "Receipt" type, e.g. `no-reply-billing03@lego.com`) has neither in its subject line. The order number only exists inside the PDF itself. This means Tier 1 subject-matching fails on essentially every LEGO receipt email regardless of whether the order is already in Supabase — likely affecting most or all of the 201-email business-inbox backlog, not just tonight's test order. `invoice_parser.py` (Agent 1A) already does PDF-content extraction elsewhere in this repo — next session should design how that hooks into Agent 1B's matching cascade as the real Tier 2, rather than filing the whole backlog as UNMATCHED.

### Step 2 — Quick closes from 2026-07-14 findings, still open (~10 min):
- Pin Fred Meyer's exact order-confirmation subject line (tentative guess was "order placed" — not confirmed enough to filter on). Open a real Fred Meyer order email and copy the literal text into `references/retailer_email_sources.md`.
- Check whether Walgreens' `Walgreens@ecs.walgreens.com` is mixed-use like Disney Store/Fred Meyer (marketing + orders) or order-only. If mixed, needs a subject discriminator too.
- These close out the retailer email-sourcing thread completely — after this, every retailer with real order history has a fully specified (sender + subject where needed) filter definition ready to build.

### Step 3 — Decide the Map 2 mechanism (a decision, not more research):
Three options already documented in `references/retailer_email_sources.md`: (a) native Gmail filter (what LEGO's Mode 5 already does, extend past LEGO), (b) a Zap built in Zapier's own dashboard, (c) manual/session-based. Pick one so the eventual Mac mini filter-building session has a settled approach to execute, not another open question.

### Step 4 — S10 schema work (variable-earn schema, Kohl's Cash earn cliff) — see S10 section below.

### Step 5 — Bulk-file the remaining ~200-email backlog — hold until Step 1 (Tier 2 matching) exists, otherwise every file lands UNMATCHED in `_unmatched/` folders with no order linkage.

**Note on Migration 012 numbering:** The local file is `012_invoice_files_ledger.sql` but S10 had planned to use 012 for `account_type` on `retailer_profiles`. The invoice_files migration was applied in Supabase 2026-06-10 and takes 012. The `account_type` migration is now 013, and `block_identifier` is 014. **015 is now taken too** — `migrations/015_purchase_plans.sql` (Agent 09 Purchase Planner schema: `purchase_plans` + `purchase_plan_items`), applied live via Supabase MCP 2026-07-18 under the MCP migration name `014_purchase_plans` before the local file was renumbered — same tolerated name/number mismatch pattern as migration 012. Next open slot is **016**.

---

### S10 — Phase 3: Variable-Earn Schema + Kohl's Cash Earn Cliff Pin *(after June 10 CPA meeting)*

**Goal:** Two-part session. (1) Build the variable-earn schema: per-order observed rewards capture (not computed from fixed rates) + Kohl's Cash block model with explicit expiration_date per block. This touches `orders`, `promotional_cash`, and `agent_02_order_entry.py`. Run the resell-os-code-review skill on engine changes before committing. (2) Pin the exact sub-$50 Kohl's Cash earn cliff boundary against the June 8th orders.

**Phase 3 schema tasks:**
1. Migration 013 (was 012 — bumped by invoice_files): `account_type` column on `retailer_profiles` + updated unique constraint. Seed Amazon Business and Amazon Personal profiles. Seed Walmart Business profile.
2. Migration 014 (was 013): add `block_identifier` to `promotional_cash` (for xNNNN matching against invoice payment lines). Review whether any other columns are needed for the block model (see kohls.md Schema notes).
3. `agent_02_order_entry.py` — replace the computed Kohl's rewards section (`_kohls_rewards()`, `_kohls_event_cash()`) with read-from-invoice prompts: capture actual earned amounts from the invoice, not derived from hardcoded constants. Capture expiration window dates for Kohl's Cash blocks and write to `promotional_cash`.
4. Confirm `orders.kohls_rewards_earned` and `orders.kohls_event_cash_earned` columns exist and stay — but population path changes from compute to capture.
5. **Retailer value normalization (found 2026-07-05, deferred to S10):** live data has inconsistent retailer values — orders: `LEGO`×3 / `Lego`×3 / `BN`×1 / `Barnes`×1; gift_cards: `LEGO` / `kohls` / `target` / `Walmart` / `barnes_noble`. Case-sensitive grouping/matching sees these as different retailers. Decide canonical vocabulary (recommend anchoring to `retailer_profiles.retailer_key` machine keys from migration 011), then one-time UPDATE on orders + gift_cards, then normalize at write time in agent_02 + email_enricher. ⚠ Until then: email_enricher writes `LEGO`, which matches only 3 of the 6 LEGO orders — do the normalization BEFORE any live enricher run against orders entered as `Lego`.
6. Code review the agent_02 diff before commit (resell-os-code-review skill — look for any path that still derives a reward amount from a rate).
7. Commit: "S10: Variable-earn schema — read rewards from invoice, Kohl's Cash block model, migrations 013-014"

**Decisions to apply in S10 (no longer CPA-gated, just need Josh's call — see Cowork 2026-06-21 entry below):**
- Q1 (FIFO): write ADR-021 once decided (ADR-019 is now taken by Order Settlement Gate; ADR-020 is cost basis regression testing), lock `users.costing_method` docs
- Q2 (cashback treatment): activate or leave off Layer 4, update cashback agent
- Q5 (Capital One chain): set `gift_cards.price_paid` write path for C1 Shopping → Macy's gift card

**Kohl's Cash earn cliff pin:**
- Review June 8th order data to determine the exact sub-$50 threshold
- Update kohls.md open question when pinned

**Still deferred from original S09 scope:**
- Barnes Scrapyard order: verify cost basis engine Layer 3 rewards redemption ($52.43 rewards, $21.65 out of pocket)
- S08 minor deferred items (tax_paid_allocated, gwp.settlement_date, dead elif, double calculation, _test_setup_t487170400.py → /tests)

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
| S09 | Kohl's retailer note (5 real orders), tax correction (DECISION 018), migration 011, CONTEXT.md + SESSION_LOG.md updated | ✓ Complete |
| Pre-S10 (2026-06-07) | Knowledge vault phase 2: CPA prep note, Macy's note, Amazon note. Architecture decision: account_type migration needed for retailer_profiles (Amazon + Walmart). | ✓ Complete |
| Pre-S10 Agent 1B (2026-06-10) | Agent 1B invoice filing built: pure-logic functions, 50 unit tests, I/O layer (Gmail/Drive/Supabase), migration 012 (invoice_files), .gitignore UTF-8 fix, setup_oauth.py. Code-reviewed — 6 bugs fixed. Mode 2 live-tested successfully 2026-07-18 (see Cowork 2026-07-18 session). | ✓ Complete |
| Pre-S10 Agent 1B+1C (2026-06-17) | Agent 1B extended with personal Gmail backfill (Mode 4) + safety-net filter (Mode 5). setup_oauth.py rewritten for two tokens. 4 code-review bugs fixed. Mode 2 live-tested successfully 2026-07-18; Modes 4/5 still untested. | ✓ Mode 2 live-tested, 4/5 pending |
| Pre-S10 Agent 1C standalone (2026-06-17) | Agent 1C built as separate script (agents/agent_01c_historical_backfill.py). 3 modes: Preview, Copy, Ledger. LEGO senders only (billing03 + m.lego.com), Feb 2025–Jun 2026. Mode 1 confirmed 748 emails. Mode 2 copy run. OAuth issues resolved (personal token was wrong file; business token 7-day expiry on test app). | ✓ Complete |
| Cowork 2026-06-20 | Auth-vs-enrichment scraping architecture decision logged. 4 orders captured outside priority backlog (T507760965, T507761629, T507771505, T507787478 — 2026-06-19/20). Scrape priority system documented in CONTEXT.md. | ✓ Complete |
| Cowork 2026-06-21 | Architecture review (ADR-020 proposed: cost basis regression testing, before Agent 1C bulk backfill). Live Supabase check: only 5 orders exist, cost_basis_state never advances past "estimated" even on a fully-settled order. Found Brickprobe file + consolidated all scrape working files from the "ResellOS software development" project folder into this repo. Confirmed GitHub/Gmail/Drive connectors live in Cowork. CPA outcome clarified (FIFO/cashback are personal choice). Investigated and rejected installing GSD ("get-shit-done") — confirmed compromised original maintainer, unresolved security gaps in community fork. Root-caused cross-surface context drift; resell-os-session-start skill created; project-knowledge paste-in deleted. | ✓ Complete |
| Cowork 2026-06-22 | 36 LEGO gift cards bulk-loaded into Supabase (4 purchase dates: Jun 14/17/20/21, all $250/$225/10%/giftcards.com). lego_gift_cards_master.csv updated. GC *2275 purchase_date corrected. 3 LEGO orders entered: T508041747, T508056398, T508059246 (all Jun 22, 2× Insiders, each with 40902 GWP). ADR-019 written: Order Settlement Gate — conditions for cost_basis_state → settled (3 trigger events, 3 conditions). DECISION 019 added to CONTEXT.md. Multi-retailer GC ledger scoped: lgc_2026.xlsx has 5 tabs (lego, GC, B&N, WM, Kohl's, Target) — WM/Target/B&N/Kohl's import is next Cowork session. Confirmed GWP Philosophy C + FIFO design (per-order, not per-unit). | ✓ Complete |
| Cowork 2026-06-26 | ADR-021 (FIFO locked), ADR-022 (cashback Layer 4 active + C1 chain ends at GC), DECISION 020 added to CONTEXT.md. Email agent architecture designed (one configurable agent, not 7 separate ones). | ✓ Complete |
| Cowork 2026-06-28 | Non-LEGO GC import into Supabase: 175 rows (B&N 139, Kohl's 15, Target 21) from lgc_2026.xlsx. 44 active cards totaling $3,631.69 in available balance. CONTEXT.md + SESSION_LOG.md updated to close ADR-021/022 open questions. | ✓ Complete |
| Cowork 2026-06-28 (eve) | Kohl's 2026 behavior changes documented in kohls.md (ResellOS-Knowledge vault): provisional earn model (~$70 drift, $530 final on June batch), unit repricing on partial cancel, promotional_cash status vocabulary (pending→issued→redeemed→expired), in-store WiFi free shipping tactic. No code changes. | ✓ Complete |
| Cowork 2026-07-05 | LEGO email parser spec + 5 real fixtures + A-007 order-confirmation correction | ✓ Complete |
| Cowork 2026-07-05 (eve) | `agents/email_enricher.py` — LEGO parser module (908 lines). 72 tests passing. 5 code-review bugs fixed. No live Gmail run. | ✓ Complete |
| Cowork 2026-07-18 (eve) | OAuth publish-status fix (Testing→Production, resolves 7-day token expiry). invoice_files schema drift found + fixed live via Supabase MCP (missing user_id column, wrong RLS policy). Sender-detection widened (`e.lego.com` → `lego.com` generally), committed `b4248bf`. Order T469280178 entered into Supabase. First successful Agent 1B Mode 2 filing — verified independently. Tier 2 PDF-content matching gap found (not fixed — see Open Questions). | ✓ Complete |
| S10 | Phase 3: variable-earn schema + account_type migration (013) + Kohl's Cash block model (014). Agent 1B Modes 4/5 + Tier 2 matching + backlog bulk-file still pending. | ⏳ Next |

---

## Database — Current State

**Supabase PostgreSQL — Live**

- **25** tables live (invoice_files added — migration 012 applied 2026-06-10; purchase_plans + purchase_plan_items added — migration 015 applied 2026-07-18)
- Migrations applied through **012**, plus an unlogged fix **012b_invoice_files_user_id_fix** applied directly via Supabase MCP 2026-07-18 (added missing `user_id uuid NOT NULL` column + corrected RLS policy on `invoice_files` — the live table had drifted from what migration 011/012 documents since 2026-06-10). **Local `migrations/` folder does not yet have a matching .sql file for this — add one next Claude Code session.** Migration **015** (`purchase_plans` schema) applied live via Supabase MCP 2026-07-18, local file present and matches live schema.
- **9** orders in DB (T487170400, T507760965, T507761629, T507771505, T507787478, T508041747, T508056398, T508059246, T469280178)
- **1** row in `invoice_files` (was 0) — first successful Agent 1B filing, `order_id null` (unmatched — see Open Questions, Tier 2 matching gap)
- **211** gift cards in gift_cards table: 36 LEGO (giftcards.com, $250/$225/10%, Jun 14–21 2026) + 175 non-LEGO (B&N 139, Kohl's 15, Target 21 — imported 2026-06-28 from lgc_2026.xlsx; 44 active cards, $3,631.69 available balance)
- **RLS ON** — every table secured
- **Multi-user** — user_id on every table
- Code committed to GitHub (confirmed live and working via GitHub MCP 2026-07-18)

**Key tables confirmed live:** orders (+ cost_basis_state, buy_reason, purchase_trigger), shipments, line_items (+ set_number, is_retiring), inventory, sales, gift_cards, gift_card_assignments, rewards_transactions, cashback_transactions, gwp (+ status, net_proceeds, sale_date, settlement_date), tax_recovery, market_events, promotional_cash, returns, retailer_profiles, retailer_cashback_profiles, portal_health, business_expenses, inventory_check_sessions, inventory_check_items, users (+ gwp_cost_treatment, costing_method) — 22 tables total.

---

## Session History

### Cowork 2026-07-18 (eve) — OAuth Fix + Schema Drift Fix + First Successful Agent 1B Filing ✓ Done — 2026-07-18

**Context:** Cowork session, working jointly with Claude Code in VS Code. Continued from 2026-07-14's stall — this session finally produced a working filed invoice, but only after clearing three real blockers along the way, each verified independently rather than trusted from a single source.

**Blocker 1 — Google Cloud OAuth (Testing status, 7-day token expiry):** Both `token_business.json` and `token_personal.json` were dead (`invalid_grant` on refresh). Root cause confirmed live in Google Cloud Console: the `resellos-agent1b` OAuth consent screen was still in **Testing** publishing status, which caps refresh tokens at 7 days — matches the exact issue flagged back on 2026-06-17 but never fixed. Both accounts were already correctly listed as test users (2/100 cap), so that wasn't it. Fixed: published the app to **Production** (approved by Josh — safe here since it's an unverified app used only by Josh's own two accounts; new sign-ins now see a "Google hasn't verified this app" click-through, which is expected). Deleted the stale token files and re-ran `setup_oauth.py` — both tokens regenerated fresh, dated 2026-07-18.

**Test order selected — T469280178:** Josh chose an order with sets that fully sold last year (so real sales data exists for future cost-basis verification) as the Agent 1B test candidate. Found via Zapier's personal Gmail connection (`joshua.buckingham@gmail.com`, confirmed live — 13 Gmail + 16 Drive actions) and cross-verified directly in the business Gmail inbox: the receipt email (`no-reply-billing03@lego.com`, message `1978aadb673df73c`) was already sitting under the `ResellOS-Invoices` label — Agent 1C's 2026-06-17 backfill pass had already copied it over, it just had never been filed.

**Order entered into Supabase:** Claude Code pulled the actual PDF invoice content directly (not from memory) — real set numbers 21343 (Viking Village V39, $129.99), 40793 (Tom & Jerry Figures V39, $14.99), 40517 (Vespa V39, $9.99), 40766 (Tribute to Jane Austen's Books V39, $0 GWP, $24.99 MSRP). Subtotal $154.97, tax $16.04, total $171.01, paid entirely by gift card. `buy_reason`/`purchase_trigger` left null (genuinely unknown a year later — a supported default state, not a gap). Gift card entered as **unlinked** — no matching `gift_cards` record; Josh confirmed this is a known, planned gap (historical gift-card linkage needs manual backfill or a future LEGO-account scrape, tracked separately, not an `agent_02` bug). Landed as `order_id 4db2be29-3316-4956-95b4-5aff8f7f5f03`, 4 line items, 1007 Insider points.

**Blocker 2 — matching gap in Agent 1B (found, not fully fixed):** `extract_order_number_from_subject()` only matches subjects containing "Order"/"Invoice" + digits. LEGO's "Receipt" email type — the *only* LEGO email type that carries a PDF attachment — has neither, so Tier 1 subject-matching returns `None` immediately regardless of Supabase state. Tier 2 (PDF-content matching) was never built; the docstring already flags this as deferred. **This likely affects most or all of the 201-email business-inbox backlog**, not just tonight's order — flagged as the new top open item, not fixed tonight (too big a change to rush). Separately, `detect_retailer_from_sender()` only matched `"e.lego.com"` — widened to match `"lego.com"` generally, tested (50/50 pass), reviewed, committed as `b4248bf`.

**Blocker 3 — invoice_files schema drift (found and fixed):** First Mode 2 filing attempt got the PDF into Drive but failed writing the ledger row: `column invoice_files.user_id does not exist` (Postgres 42703, not a PostgREST cache issue — confirmed directly). The live table was missing the `user_id uuid NOT NULL` column that `migrations/012_invoice_files_ledger.sql` specifies, and had a completely different RLS policy (`"Users can view their own invoice files"`) that derived ownership by joining through `orders.user_id` off `order_id` — meaning any row with `order_id IS NULL` (every unmatched filing) was readable/writable by any authenticated user. Whoever applied migration `20260611041822` (011_invoice_files_ledger) back on 2026-06-10 ran a hand-modified version that was never synced back to the local file — same "doc went stale" pattern as several earlier findings this project has hit. **Fixed directly via Supabase MCP** (table confirmed empty, 0 rows, so no backfill needed): added `user_id uuid NOT NULL`, dropped the ad-hoc policy, recreated the documented `invoice_files_user_policy`. Verified live post-fix: column exists, policy named correctly. **Local `migrations/` folder still needs a matching `.sql` file for this fix (012b) — not yet created.**

**First successful Agent 1B Mode 2 filing — verified independently, not just trusted:**
- Manually deleted the orphaned Drive file from the failed first attempt (`Invoices/Unknown/_unmatched/1978aadb673df73c_UNKNOWN_2025-06-20.pdf`) before re-running, to avoid a duplicate.
- Re-ran Mode 1 (Preview) → confirmed retailer now resolves to `Lego`, still correctly UNMATCHED (Tier 2 gap, expected).
- Re-ran Mode 2 (File one) → succeeded fully. Verified directly: Drive file `Invoices/Lego/_unmatched/1978aadb673df73c_LEGO_2025-06-20.pdf` (ID `1yf6ND3VKdK6xpMRCwhlcjPpK_J7tZG_4`, 9,773 bytes — matches original attachment size exactly). `invoice_files` row `id 2796fac5-39a2-42bf-b143-53674f8ef962`, `order_id null` (expected, unmatched), `retailer LEGO`. Gmail message `1978aadb673df73c` now carries only `Label_1` (`ResellOS-Filed`) — `ResellOS-Invoices` label removed. **This is the first row ever written to `invoice_files` and the first successful Agent 1B Mode 2 run** — Agent 1B had been "built, pending live test" since 2026-06-17, over a month.

**Cosmetic bug found, not fixed:** `transition_label()`'s success message (`print("  OK: Label → ResellOS-Filed")`) contains a `→` character that crashes on Windows' cp1252 console encoding. That crash gets caught by the same `try/except` wrapping the real label-transition API call, so a successful transition prints a false `WARNING: Label transition failed` message. Verified the real state directly via the Gmail API rather than trusting the printed warning — it had actually succeeded. Low priority, but worth fixing since it currently makes a real future failure indistinguishable from this false one.

**Not done (deferred):**
- Tier 2 PDF-content matching (new top item — see Start Here)
- Local `migrations/012b_invoice_files_user_id_fix.sql` file (schema change is live, local file is missing)
- Bulk-filing the remaining ~200-email backlog — hold until Tier 2 matching exists, or they'll all land UNMATCHED
- Historical gift-card linkage for T469280178 and similar backfilled orders
- Modes 4 (personal backfill) and 5 (safety filter) of Agent 1B still untested

**Commit message (code changes, via Claude Code):**
```
Cowork 2026-07-18: widen detect_retailer_from_sender() to match lego.com generally (was e.lego.com only), fixes retailer detection on receipt-type LEGO emails
```

**Schema change (applied directly via Supabase MCP, not yet mirrored to a local migration file):**
```
012b_invoice_files_user_id_fix: ADD COLUMN user_id uuid NOT NULL, replaced ad-hoc RLS
policy with invoice_files_user_policy — closes drift from migration 20260611041822
```

---

### Cowork 2026-07-18 (late) — Manual-Entry-First Architecture Decision + Agent 09 Purchase Planner Built ✓ Done — 2026-07-18

**Context:** Continuation of the same evening's Cowork session, after the Agent 1B live-filing work above. Josh stepped back to a bigger architecture question before continuing with email-agent automation.

**Manual-entry-first order architecture decided:** Until the ResellOS Chrome extension can capture orders directly from LEGO/Walmart/Kohl's/Target at the point of purchase, Josh enters every order himself via `agent_02` — set numbers, gift card linkage, and reward detail are unreliable or absent from confirmation/receipt emails (confirmed directly: no LEGO receipt ever prints the gift card number used). Email agents (Agent 1B, `email_enricher.py`) are downgraded from an order source to a verification/tracking layer: file the invoice, match it to the order Josh already entered, flag discrepancies — never originate or auto-create an order. Full detail in CONTEXT.md's Architecture Decisions table.

**`email_enricher.py` stub-creation removed:** `ACT_CREATE_STUB`/`ACT_STUB_DECLINED` (built an `orders` insert dict and wrote it for any unmatched email) replaced with a single `ACT_FLAG_UNMATCHED` — no DB write, review-queue only, so Josh can check whether he forgot to enter the order or something genuinely doesn't match. `_build_stub_order_row()` deleted entirely. Tests updated in lockstep (`test_email_enricher_lego.py`): 4 tests renamed/reassert `ACT_FLAG_UNMATCHED`. Verified 72/72 relevant tests + 122/122 full suite passing before this change; committed as `1f01bbf` via Claude Code (GitHub MCP write access 403'd — see Known Issue below).

**Purchase Planner (Agent 09) designed and built:** Josh's ask — a planning tool for buying sessions where GWP thresholds, sale prices, or double-points events are known ahead of time, so the math (minimum overspend to hit a threshold, gift card constraints, points available) is worked out before he's standing at checkout. Confirmed as its own standalone script, not a mode inside `agent_02` — and GWP/sale thresholds are always typed in by hand, never predicted (patterns exist but change too often to automate without adding noise).

- **Schema:** `migrations/015_purchase_plans.sql` — `purchase_plans` (one row per buying session: target_type, target_value, gift card link/balance snapshot, Insider points available, status draft→ready→placed) + `purchase_plan_items` (target sets: price, GWP/sale eligibility, max quantity to consider). Both RLS-enabled, applied live via Supabase MCP and confirmed via `list_tables`. See numbering note above — this is 015, not 013/014 (both already reserved for S10 work).
- **Script:** `agents/agent_09_purchase_planner.py` — menu-driven CLI (create plan, add items, run calculator, mark ready, place order). Calculator is a brute-force search over each item's quantity range (0..max_quantity), bounded by a 200,000-combination safety guard, because a realistic buying session (a handful of sets, small max quantities) doesn't need anything more elaborate — and brute force is easy for Josh to trust because every combination it found is available to show, not just the winner. Three target types: `gwp_threshold`/`points_tier` (minimize spend to reach or exceed the target) and `spend_cap` (maximize spend without exceeding it). Reuses `normalize_retailer` and `LEGO_POINTS_PER_DOLLAR` from `agent_02_order_entry.py` (shared facts, not interactive logic — importing the module doesn't run any of its prompts) rather than re-deriving them and risking drift.
- **Never writes real orders:** placing a plan marks it `placed` and prints a paste-ready cheat sheet (set name, number, quantity, price) for the `agent_02` prompts — Josh still confirms every line against the real invoice there. This is what keeps Agent 09 from becoming a second, unintended order source under the architecture decision above.
- **Tests:** `tests/test_agent_09_purchase_planner.py`, 16 tests covering the points formula (round-half-up, matches `agent_02`'s), the combination search for all three target types, the oversized-search-space guard, gift card fit, and output formatting. All 16 pass; full suite 138/138 passing (122 prior + 16 new).
- **CONTEXT.md updated:** Purchase Planner design write-up added to "Planned Future Systems," manual-entry-first architecture decision added to the Architecture Decisions table. **Not yet pushed to GitHub as of this entry — GitHub MCP write access is 403'ing (see Known Issue below); routing through Claude Code.**

**Known issue — GitHub MCP write access 403'ing:** `create_or_update_file` returned `403 Resource not accessible by integration` three times this session (SESSION_LOG.md, `email_enricher.py`, CONTEXT.md), even after Josh changed the GitHub App's permission to "Contents: Read and write" mid-session. Root cause not confirmed — likely needs a GitHub App installation re-approval step, not just the permission checkbox. Every push this session was routed through Claude Code instead (worked every time). Revisit the App permission/installation state before assuming GitHub MCP writes work again.

**Not done (deferred):**
- Agent 09 hasn't been used against a real buying session yet — first real use will be the actual test.
- No programmatic pre-fill into `agent_02` (the cheat sheet is manual copy — refactoring `agent_02` into a callable function so a plan could inject values directly is a natural follow-up, not built now).
- GitHub MCP write access still broken — needs the App installation checked, not just its permissions.

---

### Cowork 2026-07-14 — Zapier Connector Verification (Gmail + Drive) ✓ Done — 2026-07-14

**Context:** Chat session. Josh asked what Zapier's Gmail/Drive connector could do (create filters vs. read/write). Initial answer treated Zapier as unauthenticated based on stale tool-availability info in the session's system context — wrong. Josh caught it and asked for a live check plus a doc update.

**Verified live (`list_enabled_zapier_actions` + one throwaway `gmail_find_email` read):**
- Zapier MCP is connected with two apps enabled: **Gmail** (13 actions) and **Google Drive** (16 actions).
- Live read confirms the Zapier Gmail connection points to Josh's **personal** account (`joshua.buckingham@gmail.com`) — same account first identified in the 2026-07-13 session, re-confirmed today. This is a distinct connection from the direct Gmail/Drive MCP connectors (business account, `theroyalcratellc@gmail.com`) that Agent 1B/1C use — don't conflate the two.
- **Gmail via Zapier:** label, add/remove label, reply, create draft/draft reply, send, delete, archive, forward, find email, get attachment by filename. **No create-filter action** — matches the 2026-07-13 finding; real Gmail filters still require the Gmail UI directly, not scriptable via Zapier.
- **Google Drive via Zapier — not previously logged:** full write access, not read-only. Actions include Create Folder, Create File From Text, Upload File, Move File, Copy File, Replace File, Update File/Folder Name & Metadata, Add/Remove File Sharing Permission, Export File, plus Find a Folder/File and Retrieve by ID for reads.

**Documentation updated:** CONTEXT.md "MCP connectors connected" section — added a dedicated Zapier bullet distinguishing it from the direct connectors, with the account-ownership and capability notes above.

**Not done:** no decision on whether/when to actually route any pipeline work through the Zapier path. Composio was rejected 2026-07-01 for putting paid middleware in the core invoice pipeline (own-your-data principle); Zapier is the same category of concern and hasn't been evaluated against that principle yet. Treat as available for ad hoc chat-surface tasks only until a decision is made.

---

### Cowork 2026-07-13 — Invoice Pipeline Audit + Retailer Casing Fix ✓ Done — 2026-07-13

**Context:** Cowork chat session. Josh asked what's next for S10; before starting schema work he flagged that Gmail/Drive might need organizing first. Verified live rather than assuming (per `resell-os-environment-check`).

**Verified findings (Gmail + Drive MCP, now connected in Cowork — did not exist when Agent 1B was designed around local OAuth):**
- **201 LEGO order/invoice emails** sit under the business account's `ResellOS-Invoices` label, unprocessed, still arriving live (newest same-day). None have ever moved to `ResellOS-Filed`.
- **Drive `Invoices/` folder skeleton is empty.** All 13 retailer folders + all 12 month-folders for 2026 exist, but checked July 2026's Lego folder directly — zero files. Agent 1B has never filed a single invoice end-to-end.
- **`invoice_files` ledger: 0 rows.** Confirms the above — despite "Built" status in this log, Mode 2 (file) has never actually run.
- **`retailer_profiles` has only 1 row (Kohl's).** CONTEXT.md's "Retailers Currently in the System" table describes reward mechanics for 7+ retailers as built, but the table itself was never seeded beyond Kohl's — S10's plan to anchor casing normalization to `retailer_profiles.retailer_key` isn't viable as-is.
- **Retailer casing mess confirmed current:** `orders` had Barnes(1)/BN(1)/Lego(3)/LEGO(3) across 8 rows; `gift_cards` had barnes_noble(139)/kohls(15)/LEGO(38)/target(21)/Walmart(3).

**Fixed this session:**
- One-time UPDATE on `orders` and `gift_cards`: all retailer values normalized to lowercase snake_case (`lego`, `barnes_noble`, `kohls`, `target`, `walmart`). Verified post-fix: orders now `barnes_noble`(2)/`lego`(6); gift_cards now 5 clean canonical values.
- **`agent_02_order_entry.py`:** added `_RETAILER_ALIASES` + `normalize_retailer()`, applied at the retailer input prompt so new orders can't reintroduce the casing mess. Renamed the reward-branch comparisons `elif r == "BARNES"` → `"BARNES_NOBLE"` and `elif r == "BESTBUY"` → `"BEST_BUY"` to match the new canonical values (these would have silently stopped matching otherwise — caught in code review before commit). Unknown retailers (Fred Meyer, Walgreens, Disney Store, etc.) fall back to a lowercased/underscored version with a console note rather than erroring.
- **`agents/email_enricher.py`:** `_build_stub_order_row` now writes `"retailer": "lego"` (was `"LEGO"`). Checked `test_email_enricher_lego.py` — no test asserts this field's casing, so no test changes needed.
- Code review (resell-os-code-review, 4-pass) on the agent_02 diff: caught one real bug in my own first draft — the alias fallback's naive `"&" → "and"` replace would have garbled `"B&N"` into `"band"`. Fixed by padding `&` with spaces before collapsing whitespace, and added `"B&N"` as an explicit alias. No other CRITICAL/MODERATE issues found; `order_validators.py` has no retailer-string comparisons so it's unaffected.

**Part 2 — personal Gmail retailer sender map (same session):** the Gmail MCP connected natively in Cowork is business-account-only, but Josh pointed out a *second* Gmail connection exists via the Zapier MCP — confirmed live against `joshua.buckingham@gmail.com` (personal) via a throwaway search. Used it to build `references/retailer_email_sources.md`: real (not guessed) senders confirmed for LEGO (already known), Barnes & Noble, Kohl's, Macy's, and Amazon Business. Target, Best Buy, and Walmart-personal senders are NOT yet confirmed — two guessed Target addresses (`orders@target.com`, `shipment-tracking@target.com`) came back with zero matches and are recorded as confirmed-wrong so nobody retries them. Also surfaced: `retailer_profiles`/CONTEXT.md's 7-retailer list is missing Fred Meyer, Walgreens, and Disney Store, all of which already have Drive invoice folders from 2026-05-19 — a documentation gap, not a code bug.

**Capability gap found:** the Zapier Gmail connector can search/label/forward/archive but has no create-filter action — it can't replicate what Agent 1B Mode 5 does (a real Gmail API filter that runs with no agent involvement). Going-forward auto-routing for the new retailers needs one of: extend Mode 5's local script past LEGO, a Zap built in Zapier's own dashboard, or repeated manual session-based searches like this one. Not decided — documented as three options in the reference doc for Josh to pick from.

**Not done (deferred):** confirm Target/Best Buy/Walmart-personal senders (need a real order-date search or a forwarded sample, not another guess); decide the Map 2 mechanism; decide whether to file the 201-email backlog via native Cowork MCP calls or the local Agent 1B script.

**Correction (2026-07-14 — this paragraph is stale, `references/retailer_email_sources.md` is current):** later the same day/evening, Josh did his own inspection and resolved all three "not yet confirmed" items above — the doc was updated in place but this log entry never was, so it kept saying "not yet confirmed" after it no longer was true. Corrected status, per the reference doc:
- **Target — CONFIRMED:** `orders@oe1.target.com` is the real order-confirmation sender (good line-item detail). The doc's own guessed `orders@oe1.target.com`-adjacent entries were wrong in a different way than recorded here — see the reference doc directly rather than this summary.
- **Walmart (personal) — RESOLVED, but not via email:** Josh confirmed Walmart order emails don't carry usable price/line-item detail regardless of sender. Ruled out as an email-parser retailer entirely; routes through the future Chrome-extension capture path instead, same as the existing LEGO order-history scrape precedent. No Map 2 filter needed here.
- **Best Buy — DEFERRED, not a sender problem:** the account was originally set up under a now-dead email domain, so historical confirmations aren't retrievable by sender search at all (Josh has been downloading invoices manually from bestbuy.com instead). Going forward, Best Buy order confirmations already land directly in the **business** inbox — so Best Buy needs **no** personal→business Map 2 step, unlike every other retailer here.
- Net effect (updated again same evening, 2026-07-14): 6 of the 7 documented retailers have confirmed Map 2 filter requirements (LEGO ×2 domains, Barnes & Noble, Kohl's, Macy's, Amazon Business, Target). Josh then also confirmed senders for the three previously-unsearched retailers not in CONTEXT.md's table at all: **Fred Meyer** (`email@e.fredmeyermail.com`), **Walgreens** (`Walgreens@ecs.walgreens.com`), **Disney Store** (`guest.services@disneystore.com`) — all added to `references/retailer_email_sources.md` and to a new "known but not onboarded" table in CONTEXT.md. Full current Map 2 scope: 9 retailers, ~10 filters (LEGO's two domains). Best Buy and Walmart-personal remain the only two needing no Map 2 filter (resolved above). These three new retailers still have no `retailer_profiles` row or reward-mechanic logic in Agent 02 — sender confirmation only resolves email routing, not full onboarding.
- **Amazon Personal — different problem, not a sender gap:** Josh confirmed Amazon Personal order confirmations land in a *different personal email inbox* than the one Claude/Zapier is connected to (`joshua.buckingham@gmail.com`). No Claude-built filter is possible there without connecting that other inbox — Josh will set that filter up manually. Mitigating factor: Amazon's order history/invoices are easy to pull directly from the account regardless, so this is low-priority to chase further. Amazon Business is unaffected and stays in the 9-retailer Map 2 scope above.
- **Lesson:** a session-summary paragraph in this log is not the same document as the reference file it points to, and can go stale the moment the reference file gets a same-day follow-up edit. When answering questions about retailer sender status, read `references/retailer_email_sources.md` directly — don't rely on this log's prose summary of it.

**Commit message:**
```
Cowork 2026-07-13: invoice pipeline audit (201 unfiled emails, empty Drive, 0 invoice_files rows, retailer_profiles gap), retailer casing normalized in orders+gift_cards, normalize_retailer() added to agent_02, email_enricher retailer casing fixed, retailer_email_sources.md (B&N/Kohl's/Macy's/Amazon confirmed via personal Gmail)
```

**Verification outcome (Claude Code, 2026-07-14 — read this before trusting any future "✓ Complete, committed + pushed" note in this log):** asked Claude Code to review and push just today's 5 files before this went out. `git status` found **18** changed/untracked items, not 5 — three weeks of work from the Cowork 2026-06-21 (2) session (`order_validators.py` wiring into `agent_02`'s `main()`, matching `db_writer.py` wiring, ADR-019, ADR-020, `cost_basis_checks.py`, `cost_basis_status_report.py`) plus several new/rewritten skills, a Kohl's repricing design doc, and LEGO backlog files had been sitting locally uncommitted the entire time, despite this log recording that session as "✓ Complete" with its own commit message. **If Claude Code had committed only the 5 files this session's prompt described, `agent_02_order_entry.py` would have shipped importing `order_validators.py` — a module not in that narrower commit — breaking `main` with an ImportError on a fresh checkout.** Caught before push, not after. Josh chose to commit everything together in one combined commit (with an expanded message) rather than split it. 122 tests passed, compile checks and code review clean. Push landed: `a4b66ca..9d2da13 main -> main`, also carrying two previously-unpushed 2026-07-05 commits. Repo is now fully caught up as of this push — but the takeaway stands: **"✓ Complete" in this log has meant "the work was done," not reliably "it's committed and pushed."** Verify with `git status`/`git log` before assuming a past session's log entry reflects what's actually on `main`.

---

### Cowork 2026-07-05 (eve) — Email Enricher: LEGO Parser Module ✓ Done — 2026-07-05

**Context:** VS Code / Claude Code session. Built `agents/email_enricher.py` from the spec and fixtures committed in the morning Cowork session.

**New files:**
- `agents/email_enricher.py` — 908 lines. One configurable email enricher with LEGO parser module. PARSER_REGISTRY architecture (per-retailer parsers, shared A-007 cascade, shared review queue, shared write path). Pure-logic parsing functions separated from I/O (same pattern as Agent 1B).
- `tests/test_email_enricher_lego.py` — 72 tests in 8 classes, all passing. Covers all 5 fixture types, all 5 A-007 spec matching test cases, all parser trap edge cases.

**Key design decisions implemented:**
- A-007 Tier 1 cascade: order number is the only match key. Identical totals ($169.33 on two different orders) structurally cannot match — totals are never used.
- Unmatched emails → stub orders with `order_status='pending_review'`. Never auto-delete, auto-merge, or auto-cancel.
- Payment-declined emails: flag matched order for review (`ACT_FLAG_DECLINED`), or create `ACT_STUB_DECLINED` if no order found. Never auto-cancel.
- Receipt emails forwarded to Agent 1A (`ACT_RECEIPT_PDF`) — no order-number matching possible from the envelope.
- Gmail I/O wired (`fetch_lego_emails_from_gmail`) but GATED — no live run until Josh reviews. `_preview_fixtures()` mode confirmed working.
- Field rules: NEVER fills `buy_reason`, `purchase_trigger`, `cashback_rate`, `gift_card_last4`. Cost basis never runs on agent-written data.
- `is_retiring=True` on every line item (code-enforced, not relying on DB default).
- `retailer="LEGO"` (uppercase, matching agent_02 stored values).
- `no_invoice_received=True` on all email-enricher-created shipments (corrected by code review — enricher never has an invoice in hand).

**Code review — 5 bugs fixed before commit:**
1. `unit_price` suppressed negatives: `line_total > 0` → `line_total != 0` (CLAUDE.md rule 5)
2. `no_invoice_received` was `False` on both `_build_shipment_row` and stub shipments → corrected to `True`
3. `retailer` was `"lego"` (lowercase) → corrected to `"LEGO"` to match agent_02 stored casing
4. `line_items` insert in stub path had no result check → now checked; failure returns `False` with message
5. `ACT_FLAG_DECLINED` discarded the `.execute()` result → now checked; also adds `notes` field explaining the flag

**Other code-review findings (not fixed — documented for awareness):**
- Totals regex uses a 120-char lookahead; could grab a phone/zip number if LEGO adds promo text before the dollar amount. No fixture triggers this today.
- Order number regex `T(\d{9})` has no trailing anchor — truncates 10-digit variants (theoretical; LEGO hasn't issued 10-digit T-numbers).
- `ACT_CREATE_STUB` dedup guard skipped when `order_number` is empty — can create duplicate stubs on re-run if regex fails. Acceptable for now; gmail_message_id dedup would require a new column.
- Mode 2 (live run) has no client construction in `main()` — `get_client()` is imported but not called. Wire when activating live mode.

**First live run expectation:** T508133224, T508206446, T508221251, T507979974 should surface as pending_review stubs — the natural acceptance test for the enricher.

**Not done (deferred):**
- Live Gmail run (ask Josh before running)
- Non-LEGO parser modules (target Kohl's next — repricing-review email spec already written)
- `shipment_id` column on `line_items` (required for email-enricher writes — needs migration 015 or verify already added)

**Files committed:** `agents/email_enricher.py`, `tests/test_email_enricher_lego.py`, `SESSION_LOG.md`.

---

### Cowork 2026-07-05 — LEGO Email Parser Spec + Real Fixtures + A-007 Correction ✓ Done — 2026-07-05

**Context:** Cowork session. Prep work for the email enricher agent (designed 2026-06-26, not yet built): pulled real LEGO emails from the business inbox via Gmail MCP, verified extracted data against live Supabase rows, and wrote parser fixtures + an extraction spec so the enricher build session starts from verified real-world formats.

**New files:**
- `references/lego_email_parser_spec.md` — full LEGO email family (senders/subjects for all 6 types incl. two NEW types: payment-declined and survey), per-type extractable fields, parser traps, field-fill rules restated from DECISION 017, and 5 real matching test cases for the A-007 cascade.
- `tests/fixtures/emails/lego/` — 5 real-email fixtures: order confirmation (T508221251), shipping confirmations ship1+ship2 (T508041747 — real split shipment), payment declined (T507979974), receipt email (invoice 1355278758). Click-tracking URLs stripped; headers document gmail message ids.

**Key findings (all from real emails, verified against Supabase):**
1. **A-007 correction:** 2026 order-confirmation emails DO carry the order number in the body (`Order: T#########`) plus full line items and totals — Tier 1 matchable. CONTEXT.md cascade note corrected.
2. **Split shipments confirmed live:** T508041747 got two same-subject "on its way" emails, different tracking + items, matching DB line items exactly (10454×5 / 31157×2; 40797 + GWP 40902 unshipped). Message-id-level dedup validated.
3. **Per-shipment totals mislabeled "ORDER TOTAL"** in shipping emails — must map to shipments.subtotal/tax_amount, never orders totals.
4. **+1 day date skew:** shipping email says order date 6/23; order was placed 6/22. Date matching needs ±1 day tolerance.
5. **Unreliable price column:** order confirmation showed $0.00 unit prices for paid items; derive unit_price = line_total/qty.
6. **Identical totals across different orders:** T508056398 and T508221251 both $169.33 — totals can never disambiguate.
7. **2026 sender is `t.crm.lego.com`** — Agent 1B Mode 4/5 filters target `e.lego.com`; must cover both domains.

**Data gap found:** orders T508133224, T508206446, T508221251 (placed ~Jun 23–25) + declined T507979974 exist in the business inbox but NOT in Supabase. These are the natural acceptance test for the enricher's first live run (should surface exactly these as pending_review stubs). Also: T507979974 payment declined 6/30 — order held 5 business days; Josh calling LEGO evening of 7/5 to pay by credit card. Root cause identified (7/5): the same gift card was assigned to two separate orders — the second order's charge failed on insufficient balance. Not a card problem. Data implications: (1) T507979974's final payment will be CC (or mixed), no GC discount on this order; (2) the double-assigned gift card was never debited for this order — its ledger balance reflects only the first order. Design note: this is the exact failure mode a balance check at order entry (card balance minus existing assignments) would prevent — candidate for Agent 02 / Purchase Planner once the enricher lands.

**Files modified:** CONTEXT.md (A-007 tier 1 correction, OQ#18 LLM enrichment layer), SESSION_LOG.md (this entry).

**Part 2 (same evening) — Kohl's partial-cancel repricing review mechanic designed:**
- Problem: Kohl's reprices remaining items on partial cancel; website order details shows ORIGINAL line prices (wrong) with correct final total; only the mobile app shows adjusted per-line prices.
- Found the "Joshua, your Kohl's order has been updated." email (Kohls@t.kohls.com) via Chrome — carries order number, cancelled items + qty + reason, remaining items, and UPDATED subtotal/tax/total. Machine-parseable. 4 real emails captured (orders 6718163821/165953/166823/167062, all 2026-06-28, all losing 72032 to stock-out; one is the pickup-variant layout).
- Design written: `references/kohls_repricing_review_design.md` — auto-detect from email → `reconciliation_status='repricing_review'` (columns already exist) → manual per-line entry from app validated to the penny against the email's updated total → store in new `line_items.final_unit_price` (original never overwritten; migration folds into S10) → proportional-allocation fallback marked `estimated_allocation` which blocks settlement per ADR-019 → Kohl's Cash re-check in same flow.
- Fixture: `tests/fixtures/emails/kohls/order_updated_6718166823.txt`. Parser trap: Gmail threaded 4 different orders' updates into ONE thread (same subject) — process per-message, never per-thread.
- New open question: refund tender on partial cancel — "automatically refunded" to GC or card? Verify against the June 28 orders.

**Not done (deferred):** email_enricher.py itself (build in VS Code session, using the spec + fixtures); Agent 1B live test still pending (tokens need refresh — 7-day expiry); Ollama/local-LLM idea discussed and logged as CONTEXT.md Open Question #18 (LLM enrichment layer — pluggable backend: Ollama / API / off, never load-bearing, review queue is the insertion point) — revisit at Phase 3 community launch.

**Commit message:**
```
Cowork 2026-07-05: LEGO email parser spec + 5 real fixtures, A-007 order-confirmation correction
```

---

### Cowork 2026-06-26 — Decisions Locked + ADRs + GC Import + Email Agent Design ⏳ In Progress

**ADR-021 — FIFO Costing Method (Locked):**
- FIFO confirmed as the costing method going forward. CPA confirmed 2026-06-10 this is a personal-preference choice.
- `ADR-021-fifo-costing-method.md` written to repo root.
- CONTEXT.md Architecture Decisions table updated: costing method row now reads "locked 2026-06-26."
- Do not change after data accumulates — every `true_cost_basis` would need recalculation.

**ADR-022 — Cashback Tax Treatment + Capital One Chain (Locked):**
- Layer 4 (cashback allocation) is now ACTIVE for all cash-payout platforms (Rakuten, RMN, Microsoft Shopping, Honey, TopCashback).
- Capital One Shopping can only redeem as gift cards (no cash option). Chain ends at GC acquisition: GC recorded at `price_paid = $0`, Layer 2 applies full face value as discount. No chain-following into inventory cost basis.
- New `cashback_transactions.status = 'redeemed_as_gc'` prevents Layer 4 double-counting for C1 GC redemptions.
- `ADR-022-cashback-treatment-capital-one-chain.md` written to repo root.
- DECISION 020 added to CONTEXT.md.
- **Code changes needed (S10 or standalone):**
  - `agent_07_cashback.py` Mode 2: add cash/GC branch; GC path creates `gift_cards` row at $0, sets `redeemed_as_gc`
  - `agent_08_cost_basis.py` Layer 4: add `redeemed_as_gc` to skip filter
  - Check if `cashback_transactions.status` has a check constraint needing a migration

**Non-LEGO gift card import (completed 2026-06-28):**
- `lgc_2026.xlsx` sanitized: last 4 digits only, no access codes/PINs stored.
- 175 rows inserted into Supabase `gift_cards` table: B&N (139), Kohl's (15), Target (21). All use `ON CONFLICT DO NOTHING`.
- Active balances: B&N 19 cards $601.69, Kohl's 4 cards $2,000.00 (4× $500), Target 21 cards $1,030.00. Total: $3,631.69.
- Depleted cards (131) retained as historical record. Purchase dates all placeholder `2024-01-01` — actual dates not available from ledger.
- Note: Kohl's depleted $100 cards correspond to real orders in the system; gift card ↔ order linkage will be resolved when email enricher agents are built.
- purchase_price = face_value for all non-LEGO cards (no discount data available; update manually if known).

**Email agent architecture design (see Email Agent Architecture section in Start Here):**
- Decision: one configurable `email_enricher.py` agent, not 7 separate agents.
- Per-retailer parser modules, shared A-007 matching cascade, shared review queue, shared write path.
- Copy-to-business approach (extend Agent 1B Mode 4 pattern) rather than Gmail forwarding filters.
- Agents fill: order number, retailer, date, line items, GWP flags, totals, rewards earned, CC last 4.
- Agents never fill: gift_card_last4, buy_reason, purchase_trigger, cashback_rate.

**Files modified this session:**
- `ADR-021-fifo-costing-method.md` — new
- `ADR-022-cashback-treatment-capital-one-chain.md` — new
- `CONTEXT.md` — costing method row updated, DECISION 020 added
- `SESSION_LOG.md` — this update

**Commit message:**
```
Cowork 2026-06-26: ADR-021 (FIFO locked), ADR-022 (cashback Layer 4 + C1 chain), DECISION 020
```

---

### Cowork 2026-06-22 — Order Entry + Gift Card Bulk Load + ADR-019 ✓ Done — 2026-06-22

**Context:** Outside VS Code, Cowork chat session. Continuation of pre-S10 order capture + gift card loading work.

**Gift card bulk load — 36 LEGO cards into Supabase:**
- lgc_2026.xlsx sanitized: full card numbers → last 4 digits only (security). Access codes stay in local spreadsheet only — never in Supabase or any file.
- 35 new LEGO gift cards inserted into `gift_cards` table; GC *2275 (inserted earlier same session, purchase_date placeholder corrected from 2026-06-22 → 2026-06-14).
- All 36 cards: retailer=LEGO, face_value=$250, purchase_price=$225, discount_pct=10%, source=giftcards.com, source_type=third_party, cashback_expected=$3.38 (1.5% CC cashback), cashback_status=pending.
- Purchase dates: Jun 14 (18 cards, *1863–*2333), Jun 17 (6 cards, *0011–*0177), Jun 20 (6 cards, *0597–*0225), Jun 21 (6 cards, *0494–*0627).
- Total face value loaded: $9,000.
- `lego_gift_cards_master.csv` updated: 24 existing lgc_2026 rows enriched with purchase metadata (amount_paid, discount_pct, purchase_date, balance, status, notes); 12 new rows added for Jun 20/21 cards. Total: 385 rows.

**3 LEGO orders entered into Supabase:**

| Order | Date | Subtotal | Tax | Total | GC(s) | Sets | GWP | Insiders Pts |
|-------|------|----------|-----|-------|-------|------|-----|-------------|
| T508041747 | 2026-06-22 | (from prior session context) | | | | | 40902 | 2× |
| T508056398 | 2026-06-22 | $152.96 | $16.37 | $169.33 | *2309 ($169.00) + Visa ••••3013 ($0.33) | 72032, 42658, 31208, 11204 | 40902 | 1989 (2×) |
| T508059246 | 2026-06-22 | $154.95 | $16.58 | $171.53 | *2325 ($171.53) | 11043×4, 31378 | 40902 | 2015 (2×) |

- All orders: order_status=confirmed, cost_basis_state=estimated, shipping_address=Edmonds WA.
- All have GWP 40902 (Tribute to Leonardo da Vinci): unit_price=$0.00, gwp.status=pending, cost_basis_treatment=proceeds_reduce_order (Philosophy C).
- GC *2309 remaining balance after T508056398: $81.00. GC *2325 remaining balance after T508059246: $78.47.
- Columns confirmed live during this session: subtotal, tax_paid, total, insider_points_earned (not subtotal_amount etc). gwp table: market_value (not msrp). gift_card_assignments: applied_date NOT NULL.

**ADR-019 — Order Settlement Gate:**
- Drafted and written to `C:\Users\joshu\Documents\ResellOS\ADR-019-order-settlement-gate.md`.
- DECISION 019 added to CONTEXT.md Architecture Decisions table.
- Three trigger events that prompt a settlement review: (1) a unit from this order sells on Walmart (FIFO match), (2) any GWP from this order sells, (3) 12-month window from order_date elapses.
- Three conditions that must be met before `cost_basis_state` → `settled`: cashback_status='confirmed' for all cashback_transactions rows on this order, all GWPs resolved (sold/retained/donated/lost) or 12-month window elapsed, current cost_basis_state='placed'.
- Override allowed with required `override_note` field for edge cases.
- At settlement: `true_cost_basis` locks permanently; `extended_cost_basis` continues to accumulate carrying cost; any returns after settlement → `pl_adjustments` table only.
- FIFO is per-order (acquisition event), not per-unit (sale event). GWP $0 cost basis is permanent and correct under Philosophy C.
- **Note on ADR numbering:** ADR-019 is now taken by the settlement gate. The FIFO costing method decision (previously noted as "write ADR-019") will be ADR-021 (ADR-020 = cost basis regression testing, proposed).

**Multi-retailer gift card ledger scoped:**
- lgc_2026.xlsx confirmed to have 5 retailer tabs: lego, GC (giftcards.com — contains LEGO cards), B&N, WM, Kohl's, Target.
- Supabase `gift_cards` table has `retailer` column — one table handles all retailers, no separate tables needed.
- Non-LEGO tabs (WM, Target, B&N, Kohl's) will be read, sanitized, and imported into Supabase in next Cowork session. Historical spend tracking on non-LEGO cards is incomplete — forward-track from today; historical gap is acknowledged.
- Cards have access codes (PINs) — these stay in local spreadsheet only. lego_gift_cards_master.csv is LEGO-specific; Walmart/other GC tracking will be done directly in Supabase from this point.
- Full card numbers never stored. Access codes never stored.

**GWP Philosophy C + FIFO confirmed:**
- GWP $0 cost basis is permanent and correct. Net proceeds reduce originating order economic cost (Layer 5) when GWP sells.
- FIFO settlement is per-order (acquisition event), not per-unit (sale event). All units from one order share the same cost basis calculation.
- cashback and GWP sale are the two cost basis update events after order entry. Rakuten is the most automatable (email-matchable by order number). Cap1 and RetailMeNot will need manual capture.

**Files modified this session (local, need GitHub commit):**
- `C:\Users\joshu\Documents\ResellOS\ADR-019-order-settlement-gate.md` — new file
- `C:\Users\joshu\Documents\ResellOS\CONTEXT.md` — DECISION 019 added
- `C:\Users\joshu\Documents\ResellOS\lego_gift_cards_master.csv` — updated

**Commit message:**
```
Cowork 2026-06-22: 3 orders entered, 36 LEGO GCs loaded, ADR-019 (settlement gate), DECISION 019 in CONTEXT.md
```

---

### Cowork 2026-06-21 (part 2) — Data Validation Layer Built ✓ Done — 2026-06-21

**Context:** Continuation of the same Cowork session (see part 1 below). Josh asked to build agents that review invoice/order data before it's written and catch cost-basis issues — built directly in Cowork rather than handed off to Claude Code, since Cowork now has write access to this repo.

**New files:**
- **`order_validators.py`** — shared pre-write checks, called from both Agent 1A (`db_writer.write_invoice`) and Agent 02 (`agent_02_order_entry.write_order`) right before their write-confirmation prompt. Never blocks, only warns (matches the existing warn-then-ask pattern already in agent_02). Checks: cross-shipment duplicate set_number (the documented "duplicate line items" risk — confirmed zero exist today via live query, but nothing previously stopped a new one), GWP-flag-vs-price agreement (agent_02 currently lets `is_gwp` and the price paid disagree — a real gap, not theoretical), missing set_number (informational), line-items-sum-vs-expected-subtotal.
- **`cost_basis_checks.py`** — read-only checks on what Agent 08 (Mode 1) actually wrote to inventory: every GWP unit is exactly $0.00 cost basis, unit count matches line-item quantities, surfaces the known `tax_paid_allocated` always-0 gap as a standing reminder. Scope note: gift card savings (Layer 2) is collected interactively in Mode 1 and never persisted anywhere, so a true independent re-derivation of `net_economic_cost` isn't possible from stored data alone — flagged as a new open question (see below), not fixed this session.
- **`cost_basis_status_report.py`** — read-only report answering "which orders need a human to go run Agent 08?" Not an auto-advancer — DECISION 017 deliberately keeps cost basis behind explicit confirmation, and that's correct for a financial system. This is the missing reminder, not automation: flags orders where Mode 1 has never run, where GWP is still pending (genuinely blocks settlement per `mode_compute`'s M2 logic), or where cashback is pending (does NOT block settlement in the real code — surfaced as a note, not a blocker, after first writing it the other way and catching the mismatch in code review).

**Real finding from running the report's logic live against Supabase:** all 5 orders currently have zero inventory rows — Mode 1 has never been run on any of them, including T487170400 whose GWP fully sold and settled back on 2026-05-27. Confirms the "nothing reminds anyone an order is ready" gap directly.

**Code review (resell-os-code-review skill, 4-pass) — no CRITICAL issues.** MODERATE: status report's cashback-pending status didn't match `mode_compute`'s actual gating (only GWP blocks settlement, not cashback) — fixed before logging this entry. MINOR (fixed): `set_number` whitespace not normalized before duplicate comparison; `client or get_client()` truthiness pattern tightened to `is not None`. MINOR (not fixed, low priority): `print_warnings` duplicated with different signatures across two files; per-order queries in the status report are N+1-shaped and would want batching once order volume grows well past today's 5.

**Environment note:** the Cowork sandbox's bash mount repeatedly showed stale/truncated content for files edited multiple times in one session (`db_writer.py`, `order_validators.py`, `cost_basis_checks.py` all intermittently failed `py_compile` via bash with truncation errors that did not match the real file). The Read/Edit/Write/Grep tools consistently showed correct, complete content throughout — confirmed by full re-reads. Treat bash-side verification of recently-edited files with suspicion in Cowork; trust the Read tool. Could not run the new scripts end-to-end against Supabase from this bash sandbox either — the sandbox's network egress blocks the Supabase REST domain directly (the dedicated Supabase MCP tool reaches it fine; raw `httpx`/`supabase-py` from bash does not). Logic was verified by running equivalent SQL through the MCP tool instead.

**New open questions added (see Open Questions section):** (1) gift card savings (Layer 2 input) isn't persisted anywhere, blocking any future audit of a cost-basis run; (2) none of the 5 live orders have ever had Mode 1 run on them.

**Not done this session (deferred):** wiring `cost_basis_checks.py` / `cost_basis_status_report.py` into a single CLI entry point (right now they're three separate scripts); the ADR-020 pytest-style regression suite itself (`/tests/test_cost_basis.py`) — these validators are upstream of that work, not a replacement for it.

**Commit message:**
```
Cowork 2026-06-21 (2): data validation layer — order_validators.py, cost_basis_checks.py, cost_basis_status_report.py, wired into Agent 1A + Agent 02, code-reviewed
```

---

### Cowork 2026-06-21 (part 1) — Architecture Review, Cost-Basis Test Gap, Data Consolidation, Cross-Surface Context Fix ✓ Done — 2026-06-21

**Context:** Outside VS Code, Cowork chat session. Started as a software-development-consultant style architecture review, then a deep dive into one finding, then a tooling/process conversation.

**Architecture review — punch list + ADR-020:**
- Reviewed Master Architecture Document (v2.1), Project Map (v2.0), and SESSION_LOG.md.
- Strongest existing decisions: cost basis locking at settlement (DECISION 011), order edit lifecycle / cost basis trigger gate (DECISION 017), multi-vertical catalog schema designed ahead of need.
- Highest-leverage gap identified: the cost basis engine (`agent_08_cost_basis.py`) has no automated regression suite — correctness gate is manual code review + one golden-record order (T487170400). Manual review already caught 2 CRITICAL bugs in this exact module in S08, which is a leaky-net signal, not a solid one.
- **`ADR-020-cost-basis-regression-testing.md`** written and saved in repo root (status: Proposed). Recommends a small fixture-based test suite (T487170400 + Barnes Scrapyard rewards case + the 4 known S08 minor-deferred bugs) before Agent 1C's ~635-order historical backfill runs at scale, since settled cost basis can't be corrected after the fact — only adjustment entries.
- Two items originally flagged in the review were corrected by Josh and are NOT open concerns: (1) the 2026-06-20 authenticated-scraping approach is an intentional, acknowledged stopgap until a Chrome extension + Purchase Planner replace it — not a long-term architecture risk needing hardening right now; (2) FIFO and cashback tax treatment are NOT CPA-blocked — the June 10 CPA meeting concluded both are personal-preference choices the CPA will accommodate either way (see Open Questions update below).

**Real data check — cost basis state machine doesn't self-advance:**
- Queried Supabase directly (project `svztskmvugggdaysqbsj`). Confirmed: only 5 orders exist total. Only T487170400 has GWP records (all 3 line items `status = sold`, `settlement_date` populated 2026-05-27) — but `orders.cost_basis_state` for that order still reads `estimated`, never advanced to `provisional` or `settled`. Only one `cashback_transactions` row exists (order T504031563, `status = pending`).
- Finding: there isn't yet enough real order variety to build the full "what's known vs. pending" test matrix Josh described (gift card/rewards known instantly, cashback resolves within ~120 days, GWP within 14 days–12 months), and the one fully-resolved order never had its status field updated — the state machine exists in schema but nothing is actively driving transitions yet. Flagged as a prerequisite to building the ADR-020 test suite properly.

**Data consolidation — fixed a real fracturing problem:**
- Found that working files for the LEGO order-scrape backlog had been saved into the Claude Project folder **"ResellOS software development"** instead of this repo, including `brickprobe_purchases_2026-06-19.csv` (this is what "Brickprobe" turned out to be — a file, not a separate tool). Unintentional drift from a prior Cowork session defaulting to the wrong connected folder.
- Moved into this repo (root): `brickprobe_purchases_2026-06-19.csv`, `lego_gift_cards_master.csv`, `lego_orders_todo.txt`, `lego_order_numbers_master.txt`, `lego_priority3_line_items.csv`, `lego_priority3_manual_worklist.csv`, `lego_priority3_orders.csv`, `lego_scrape_priority.csv`, `order_gift_card_links.csv`, and `skills/lego-order-capture/SKILL.md`.
- Deleted the originals from the "ResellOS software development" folder after confirming the copies landed (required an explicit Cowork file-delete permission grant from Josh). That folder is now empty. **CONTEXT.md's "LEGO Order Scrape — Priority System" section updated to reflect the new file location.**
- Obsidian / ResellOS-Knowledge vault was left untouched — out of scope for this cleanup by design.

**Connector check — GitHub, Gmail, Drive confirmed live in Cowork:**
- `get_me` confirmed GitHub connected as `theroyalcrate`. Gmail `list_labels` confirmed the connected account is the actual ResellOS business inbox (`theroyalcratellc@gmail.com`, labels `ResellOS-Invoices` / `ResellOS-Filed`). Drive `list_recent_files` confirmed the same account's Lego folder structure and scrape files.
- Resolves the open question below about GitHub MCP connectivity, at least for the Cowork/chat surface. Distinct from whatever Claude Code/VS Code uses locally — if Claude Code still has trouble with its own GitHub MCP, that needs its own separate check.

**GSD ("get-shit-done") investigated and rejected:**
- Josh asked about connecting the GSD/"get-shit-done" Claude Code framework (meta-prompting / spec-driven workflow) for its skill/agent loop.
- Investigation found: the original maintainer (TÂCHES) went silent ~7 weeks, deleted his accounts, and a crypto token tied to the project was independently reported by multiple outlets as a ~$500K rug pull. The original npm package is permanently compromised — that maintainer can still push updates to it at will.
- The community fork (`open-gsd/get-shit-done-redux`) was independently security-audited: no backdoor found, but the audit flagged unresolved gaps — safety hooks are advisory-only (warn, don't block), and a documented file-read pattern (`@~/...`) could be tricked into inlining secrets like SSH keys or credentials into the AI's context.
- **Decision: do not install GSD (original or redux) into this repo.** This repo holds live credentials (`.env`, `credentials/`, OAuth tokens) that make that specific risk concrete, not theoretical. Logged as a guardrail in CONTEXT.md.

**Cross-surface context drift — root cause found and fixed:**
- This session started from a stale Claude-Project-knowledge snapshot of CONTEXT.md (dated 2026-06-04) instead of the live repo file (last touched 2026-06-18) — directly demonstrating the "memories get lost between chat, Cowork, and Claude Code" problem Josh raised.
- Root cause: the Claude.ai Project kept a separate pasted-in copy of CONTEXT.md/SESSION_LOG.md that drifted out of date, and Cowork sessions were defaulting to that stale snapshot instead of reading the live repo files they already had direct access to.
- Fix: Josh deleted the stale CONTEXT.md/SESSION_LOG.md copies from the Claude Project's knowledge files (2026-06-21) — this repo is now the only copy. A new skill, **`skills/resell-os-session-start.md`**, instructs any Claude surface (chat, Cowork, or Claude Code) to read CLAUDE.md → CONTEXT.md → SESSION_LOG.md → `stages/CURRENT/CONTEXT.md` (if present) live from the repo (or fetched fresh from GitHub if no folder access) at the start of every ResellOS session, and to update SESSION_LOG.md at the end — never relying on memory or a cached copy.
- **Manual step still needed from Josh:** add `resell-os-session-start` as an enabled skill in Settings → Capabilities so plain chat and Cowork actually load it (skills can't self-register from inside a session). Claude Code doesn't need this step — it already auto-loads CLAUDE.md every session, and CLAUDE.md already states the same read-order rule.

**Commit message:**
```
Cowork 2026-06-21: architecture review (ADR-020 proposed), Supabase data check, project-folder consolidation, GSD security rejection, cross-surface context-drift fix + resell-os-session-start skill
```

---

### Pre-S10 Agent 1B+1C — Personal Gmail Backfill + Safety Filter ✓ Built — 2026-06-17

**What was built (consolidates previously planned Agent 1C into Agent 1B):**
- **`setup_oauth.py`** — rewritten to handle two OAuth sessions: business account (gmail.modify + drive → `token_business.json`) and personal account (gmail.modify + gmail.settings.basic → `token_personal.json`). Legacy `token.json` auto-migrated to `token_business.json` on first run. `setup_oauth.py --business` and `--personal` flags allow individual setup. Two browser windows prompt on first run with clear console labels (BUSINESS / PERSONAL).
- **`.gitignore`** — added explicit entries for `token_business.json` and `token_personal.json` (belt-and-suspenders; `credentials/` already covers them).
- **`agents/agent_01b_invoice_filing.py`** — extended with two new modes:
  - **Mode 4 — Personal Gmail backfill** (Part 2): searches personal Gmail for LEGO emails from `e.lego.com` with attachments, not yet labeled `ResellOS-Processed`. For each: checks business Gmail via `rfc822msgid:` search (dedup guard), copies raw message to business Gmail with `ResellOS-Invoices` label, then labels personal copy `ResellOS-Processed`. Partial-failure safe: if business insert succeeds but personal labeling fails, the `rfc822msgid:` check on the next run detects the existing copy and retries only the labeling.
  - **Mode 5 — Safety-net filter** (Part 3): creates a Gmail filter on the personal account matching `from:(e.lego.com)`, applying label `ResellOS-Needs-Copy` to any new matching email. Safety net only — P0 forwarding rule handles most new LEGO invoices directly to business.
  - Auth refactored: `_load_creds()` now properly returns None (not a broken Credentials object) when token is expired with no refresh_token. `build_business_services()` and `build_personal_gmail()` are separate functions; each mode loads only the credentials it needs.

**Code review — 4 bugs fixed before commit:**
1. CRITICAL (base64 padding): `raw_b64 + "=="` always corrupts the raw message when `len(raw_b64) % 4 == 3`. Fixed: `"=" * (-len(raw_b64) % 4)`.
2. HIGH (expired credential): Expired token with revoked refresh_token returned non-None, causing `build()` to succeed but first API call to 401 with no actionable error. Fixed: `_load_creds` returns `None` when `not creds.valid` and refresh is impossible.
3. MEDIUM (rfc822msgid query): Bare unquoted Message-ID in search query breaks silently if ID contains colons/spaces. Fixed: normalise to `<id>` angle-bracket form that Gmail expects.
4. EFFICIENCY (double-fetch): Mode 4 made two API calls per message (metadata + full). Fixed: added `Message-ID` to `metadataHeaders`; second fetch eliminated.

**Credentials structure (all gitignored via `credentials/`):**
- `credentials/credentials.json` — OAuth client secret (download from Cloud Console, never regenerated)
- `credentials/token_business.json` — business Gmail + Drive (gmail.modify + drive)
- `credentials/token_personal.json` — personal Gmail (gmail.modify + gmail.settings.basic)
- `credentials/token.json` — legacy name from pre-S10 setup; auto-migrated by `setup_oauth.py`

**Scope note:** If setup_oauth.py fails with a scope error for the personal account, the OAuth consent screen needs `gmail.settings.basic` added under APIs & Services → OAuth consent screen → Data Access.

**Pending — do before broad use (all 5 modes):**
1. Run `python setup_oauth.py` to create `token_personal.json` (business token migrates automatically from `token.json`).
2. Run Mode 4 to backfill personal Gmail history. Review summary log.
3. Run Mode 5 to create the personal safety-net filter.
4. Run Mode 1 (Preview) to confirm business queue looks right.
5. Run Mode 2 to file one invoice end-to-end. Verify Drive path + ledger + label.
6. User asked: "Ask me before processing any real emails — test on one or two first."

**Commit message:**
```
S10: Agent 1B — invoice filing from business + personal Gmail to Drive, idempotent, with personal-side safety net filter
```

---

### Pre-S10 Agent 1C — Historical Invoice Backfill (Standalone) ✓ Complete — 2026-06-17

**What was built:**
- **`agents/agent_01c_historical_backfill.py`** — standalone historical backfill agent. Separate from Agent 1B. Three modes:
  - **Mode 1 — Preview**: searches personal Gmail for `from:(no-reply-billing03@lego.com OR receipts@m.lego.com) after:2025/2/1 before:2026/6/2`, prints total count and first 5 emails by date. No writes.
  - **Mode 2 — Copy**: for each email found: fetches RFC 2822 Message-ID → checks business Gmail via `rfc822msgid:` search (idempotency) → if absent, exports raw from personal Gmail and imports to business Gmail via `messages.import_()` with `ResellOS-Invoices` label. Logs COPY / SKIP / ERROR per message with subject + date + business message ID. Summary at end. Safe to re-run.
  - **Mode 3 — Ledger**: lists all messages in business Gmail with `ResellOS-Invoices` label from LEGO billing senders, sorted by date descending.
- **`.gitignore`** — added `credentials.json` at repo root (was untracked and would have been committed accidentally).

**Run results:**
- Mode 1 Preview: **748 emails** found in personal Gmail matching LEGO billing senders in date range.
- Mode 2 Copy: executed — 748 emails copied to business Gmail under ResellOS-Invoices.

**OAuth issues resolved this session:**
- `Token_personal.json` was the wrong file (contained OAuth client secrets, not a token). Deleted + re-ran `setup_oauth.py --personal`. Root cause: file was saved with wrong content at setup time.
- Personal Gmail account not in Google Cloud test users list → 403 access_denied. Fixed: added personal Gmail address to test users in the Agent 1B Google Cloud project (the one holding `credentials.json`).
- Business token `invalid_grant` on Mode 2 — 7-day expiry limit on test-mode OAuth apps. Business token was generated 2026-06-10 (exactly 7 days prior). Fixed: deleted `token_business.json`, re-ran `setup_oauth.py --business`. **Note: this will recur every 7 days until the Google Cloud app is moved out of testing mode (publish it or set to production in OAuth consent screen).**

**What this agent does NOT do (by design):**
- Does not rename, modify, or reprocess email content — raw RFC 2822 copy only.
- Does not label anything in personal Gmail (unlike Agent 1B Mode 4).
- Does not process any retailer other than the two LEGO billing senders.
- Does not delete anything from personal Gmail.

**Commit message:**
```
Pre-S10 Agent 1C: historical LEGO invoice backfill — 748 emails copied personal → business Gmail
```

---

### Cowork 2026-06-20 — Auth Scraping Decision + Scrape Priority System ✓ Done — 2026-06-20

**Context:** Outside VS Code, Cowork chat session. Encountered a stray `.git/index.lock` from a prior stuck push — removed on next session start (confirmed no git process was running before removing).

**Architecture decision logged (CONTEXT.md — Architecture Decisions table):**
- **Authenticated account scraping vs. enrichment scraping (data acquisition boundary):** Two trust tiers, two tools. Authenticated account data (LEGO order history, gift card balances — anything behind a login) is only ever pulled through the user's own already-authenticated real browser session (Claude in Chrome), one order at a time, at a deliberately slow/human-paced rate. Never use third-party scraping/proxy services (e.g. Apify) for this tier — proxy rotation against a logged-in account looks like account-takeover to retailer fraud detection, risking an account lock. Public/enrichment data (deal alerts, stock, retirement data) has no such constraint — Apify or similar is the right tool there. (Decided 2026-06-20)

**Scrape priority system documented (CONTEXT.md — new section "LEGO Order Scrape — Priority System"):**
- Backlog files live in the Claude Project folder "ResellOS software development" (not this repo).
- Key files: `lego_orders_todo.txt` (532 orders needing attention), `lego_scrape_priority.csv` (tier per order), `lego_order_numbers_master.txt` (635 total), Brickprobe cross-reference CSV, gift card master ledgers.
- Priority tiers: 3 = Not in Brickprobe (55 orders — scrape first), 2 = In Brickprobe no GC (378), 1 = GC confirmed (133 — lowest value, can likely skip).
- Rule: future sessions pull next target from `lego_orders_todo.txt` by priority 3 → 2 → 1. Do NOT walk the live order history page newest-first.
- ⚠ Priority direction to verify: tier 3 = "scrape first" is counterintuitive numbering — confirm before bulk session.

**4 orders captured outside priority backlog this session:**
These were captured by walking the live LEGO order history page newest-first — not from the priority backlog. They are newer than anything in the backlog and weren't in `lego_orders_todo.txt`. Data is in `lego_order_scrape.csv` and will reconcile normally via Brickprobe/invoice matching; the process miss was using the wrong target source.

| Order | Date | Total | Notes |
|-------|------|-------|-------|
| T507760965 | 2026-06-19 | $169.27 | GC 2051 + Visa ••••3013; GWP Leonardo da Vinci; Mickey Mouse Clubhouse backordered |
| T507761629 | 2026-06-19 | $169.35 | GC 2036 + GC 1996 + Visa ••••3013; GWP Leonardo da Vinci |
| T507771505 | 2026-06-19 | $169.29 | GC 2093 + Visa ••••3013; GWP Leonardo da Vinci; Mickey Mouse Clubhouse backordered |
| T507787478 | 2026-06-20 | $169.34 | Full GC 2135; GWP Leonardo da Vinci |

**Next session:** Resume scraping from `lego_orders_todo.txt` starting at priority 3 (55 orders not in Brickprobe). Verify priority direction (3 = first) before starting bulk session.

**Commit message:**
```
Cowork 2026-06-20: auth scraping decision, scrape priority system, 4 orders captured outside backlog
```

---

### Pre-S10 Agent 1B — Invoice Filing Automation ✓ Built — 2026-06-10

**What was built:**
- **`.gitignore`** — rewrote from scratch as clean UTF-8 (was UTF-16 with NUL bytes; last line was corrupted, merging `*.log` and `mcp.json`). Added `credentials/` section for OAuth tokens.
- **`setup_oauth.py`** (repo root, tracked) — one-time Gmail + Drive OAuth setup script. Paths point to `credentials/` (gitignored). Run once, generates `credentials/token.json`.
- **`migrations/012_invoice_files_ledger.sql`** — idempotent `IF NOT EXISTS`. Schema: `id uuid PK`, `user_id uuid NOT NULL`, `gmail_message_id text UNIQUE NOT NULL`, `drive_file_id text`, `order_id uuid FK→orders ON DELETE SET NULL`, `retailer text`, `filed_filename text`, `filed_at timestamptz`, `created_at timestamptz DEFAULT now()`. RLS enabled with DO $$ guard. **Note:** This takes migration 012; the planned `account_type` column migration for `retailer_profiles` is now 013.
- **`agents/agent_01b_invoice_filing.py`** — invoice filing agent. Three modes: (1) Preview (read-only scan), (2) File one (explicit confirmation per invoice), (3) Ledger review. A-007 Tier 1 order matching. Gmail label two-stage move: `ResellOS-Invoices` → `ResellOS-Filed`. Walmart routing rule §7.5: `businessinfo@walmart.com` → `Walmart Business/`.
- **`tests/test_agent_01b_pure_logic.py`** — 50 unit tests, all pure-logic (no network/DB/API). 50/50 passing.

**Code review — 6 bugs fixed before commit:**
1. WALMART_BUSINESS key mismatch: `_SENDER_RETAILER` used underscore key (`WALMART_BUSINESS`) but `RETAILER_DRIVE_FOLDER` used space key (`WALMART BUSINESS`) — unmatched Walmart Business emails routed to a `"Walmart_Business"` folder that doesn't exist. Fixed: aligned key to `"WALMART BUSINESS"` with space.
2. Shipment count off-by-one: `max(shipment_count, 1)` should be `shipment_count + 1`. A second shipment would have been named `_ship1` (colliding with existing), not `_ship2`.
3. Unmatched + multi-PDF crash: `build_filename(None, ...)` for unmatched invoices with 2+ PDFs produced `None_RETAILER_date_ship2.pdf`. Fixed: separate branch for matched vs unmatched multi-PDF.
4. mode_file "0" bug: `plans[int("0") - 1]` = `plans[-1]` (last item) silently. Fixed: explicit `1 <= idx <= len(plans)` guard.
5. Drive pagination miss: `_find_folder` only read first page of results — existing folder silently missed → duplicate created. Fixed: server-side `name = '{name}'` filter in query.
6. list_intake_messages 50-message hard cap: changed to paginated loop (maxResults=100 + nextPageToken).

**Pending — do before broad use:**
- Apply migration 012 to Supabase (paste `migrations/012_invoice_files_ledger.sql` in SQL editor or Supabase MCP) if not already done.
- Run Mode 1 preview, review the queue.
- Run Mode 2 to file one invoice. Verify: (a) PDF in Drive at correct path, (b) ledger row in `invoice_files`, (c) message label changed to `ResellOS-Filed`.
- User said: "Ask me before processing any real emails — test on one or two first."

**OAuth credentials confirmed (2026-06-10/11):**
- `credentials/credentials.json` — gitignored, not committed
- `credentials/token.json` — gitignored, generated by `setup_oauth.py` which was run successfully
- Scopes: `gmail.modify` + `drive`

**Commit message to use:**
```
Pre-S10 Agent 1B: invoice filing — pure logic + I/O + 50 tests, migration 012, .gitignore UTF-8 fix
```

---

### Pre-S10 — Knowledge Vault Phase 2 ✓ Done — 2026-06-07

**What was done:**
- **CPA prep note** (`Projects/cpa-meeting/cpa-meeting-2026-06-10.md`) — all 5 questions documented with current system state, downstream build impact, and a post-meeting answer table. Three build gates called out: Q1 (FIFO), Q2 (cashback treatment), Q5 (Capital One chain).
- **Macy's retailer note** (`Areas/retailers/macys.md`) — verified against 2 real orders (4660889947 Nov 2025 pickup, 4697809433 Dec 2025 ship+cancel). Key findings: (1) `rewards_reduce_taxable_base = false` confirmed — Star Money is post-tax tender; tax computed on full merchandise subtotal even when order paid entirely with Star Money. Closes open question OQ#6. (2) Dual reward mechanism: regular points (1pt/$1 → 1000pts = $10 Star Money) + promotional Star Money events ($10 blocks per ~$50 spend, same cliff structure as Kohl's Cash). (3) Order detail page is the worst parsing surface confirmed — no payment tender breakdown, no reward earn details; high human-input dependency for email agent. (4) Partial cancellation observed: Dec 17 order had Leviathan Qty 3 cancelled Dec 19, Iron Man Qty 4 delivered. (5) Gift cards earn 0 points (unlike Kohl's). (6) Holiday return window closes Jan 31 on both Nov and Dec orders.
- **Amazon retailer note** (`Areas/retailers/amazon.md`) — verified against 3 real orders (2 Business, 1 Personal). Key findings: (1) Dual account setup: Business (preferred, tax-exempt via resale cert) and Personal (fallback, taxable). (2) Account disambiguation is multi-signal — email format/subject language + invoice layout + order number prefix (112- Business, 114- Personal observed) + tax; no single signal sufficient; conflicts → flag for human review. (3) Tax exemption covers all purchases including third-party sellers; Amazon remits. Exemption is intentionally toggleable (shipping supplies want tax). (4) Amazon Business occasional delayed shipment reward: 1% opt-in at checkout for 1–3 day delay — offered inconsistently, must be prompted at order entry, track in `rewards_transactions`. (5) Quantity limits: ~9 units at discount price, ~60 at full retail. (6) Two clean invoice formats (Business "Final Details" table, Personal "Order Summary" card). (7) No loyalty program, no cashback portal. Amazon Prime Visa planned Q4 2026 (5% back).

**Architecture decision (unresolved — gates Migration 012):**
- `retailer_profiles` needs `account_type text DEFAULT 'default'` column + updated unique constraint `UNIQUE (user_id, retailer_key, account_type)`. Required for Amazon (Business/Personal) AND Walmart (Business/personal). Design once in Migration 012, apply to both before seeding either profile.

**Knowledge vault files committed:**
- `C:\ResellOS-Knowledge\ResellOS-Knowledge\Projects\cpa-meeting\cpa-meeting-2026-06-10.md`
- `C:\ResellOS-Knowledge\ResellOS-Knowledge\Areas\retailers\macys.md`
- `C:\ResellOS-Knowledge\ResellOS-Knowledge\Areas\retailers\amazon.md`

---

### S09 — Kohl's Retailer Note + Tax Correction + Migration 011 ✓ Done — 2026-06-05

**What was done:**
- Kohl's retailer note (`kohls.md`) committed to ResellOS-Knowledge vault — verified against 5 real orders (6714029349, 6702180930, 6661403431, 6659072095, 6668175554). Note covers: variable earn rate (5–15%, card-independent), Kohl's Cash block model (earn threshold ~$50 post-coupon, block value varies by event), redemption window duration (6–13 days observed), free shipping threshold ($49 post-Kohl's-Cash), cancellation behavior (Kohl's Cash retained; stranded gift card balance is the real risk), gift cards earn normally (unlike Macy's), no GWP observed.
- **Tax correction (DECISION 018):** Kohl's Cash and coupons are pre-tax discounts (reduce taxable base). Confirmed two independent ways from real invoices. Overturns prior assumption that Kohl's Cash is post-tax tender. `rewards_reduce_taxable_base = true` in the Kohl's profile.
- Migration 011 applied: added `retailer_key`, `rewards_reduce_taxable_base`, `supports_pickup`, `free_shipping_threshold` columns to `retailer_profiles`. Composite unique constraint `UNIQUE (user_id, retailer_key)` added (idempotent guard). Kohl's profile row seeded.
- ADR-018 created: `ADR-018-kohls-rewards-pretax-correction.md` — full decision record with evidence, consequences, no-backfill confirmation, Macy's re-check flag.
- agent_08_cost_basis.py docstring updated: Layer 1 note that `tax_paid` is actual invoice amount, never recomputed; `rewards_reduce_taxable_base = true` means actual tax is lower.
- CONTEXT.md + SESSION_LOG.md updated: Kohl's retailer row corrected, DECISION 018 added to Architecture Decisions, Open Questions renumbered and updated (Kohl's cancellation, earn cliff, Macy's re-check, agent_08 naming collision added).

**Phase 3 deferred to S10:** Variable-earn schema (per-order observed rewards + Kohl's Cash block model with explicit expiration per block) — touches `orders`, `promotional_cash`, `agent_02`. Code review required before commit.

**Also still deferred (original S09 scope):** Barnes Scrapyard Layer 3 verification, Agent 1B invoice filing, Gmail/Drive connection, S08 minor cleanup items.

**Pre-flight finding:** `retailer_profiles` was empty (no rows for any retailer). `PHASE_1_USER_ID` confirmed as `00000000-0000-0000-0000-000000000001`.

**Commit message:**
```
S09: Kohl's tax correction — DECISION 018, migration 011, retailer profile seeded, ADR-018
```

---

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

**CPA/Attorney Meeting — June 10, 9:00-9:30am (all three previously-open decisions now resolved 2026-06-26):** (1) ✅ FIFO — locked as ADR-021. (2) ✅ Cashback/credit card rewards — Layer 4 active, rebate treatment. ADR-022. (3) WA State tax recovery — still open: reduces COGS retroactively or separate income in period received? (4) S-Corp vs Schedule C — still open. (5) ✅ Capital One Shopping chain — resolved: chain ends at GC acquisition, price_paid = $0. ADR-022.

**LEGO Set Number Mapping — resolved for parser:** Parser now captures set_number (Pre-S08 task complete). Still needed: Set Reference Agent — local DB of all LEGO sets with retirement status, EOL date, UPC, EAN, dimensions. Source: Brickset API (validate vs Bricktap lists on 20-30 sets first). LEGO.com catalog endpoints — rewatch Brick Dynasty episode. Initial seed from Bricktap retirement lists.

**Backfill set_number on old line items:** Code captures it now, but rows written before that change have null set_number. Re-parse old invoices to backfill.

**Duplicate line items:** Cross-path (manual + parser) historical artifact, not an ongoing bug. Inspect and clean before further cost-basis work. Email agents must enrich existing orders, not duplicate.

**Google Drive Migration:** 15 months of historical invoices in personal Drive. Move to business Drive before Agent 1B filing automation runs against historical data. Connect Gmail (personal + business temporarily) and Drive MCPs in S09.

**Walmart Business Rewards Basis:** 2% likely on original order value at placement, not final pickup total. Real example: $290 placed, $204 final, $8.40 credited. Confirm from more order data before automating.

**Kohl's Cancellation Behavior (updated 2026-06-05):** Community sources say Kohl's Cash is *retained* on cancellation (not eliminated). Real risk is stranded gift card balances — must call Kohl's to recover (replacement cards mailed). Verify against a real cancellation if one occurs.

**Kohl's Cash Earn Cliff — exact sub-$50 boundary:** Pin against June 8th orders (S10 task).

**~~Macy's Star Money pre-tax vs post-tax~~** ✅ RESOLVED 2026-06-07: Star Money is post-tax tender (`rewards_reduce_taxable_base = false`). Confirmed from Dec 17, 2025 order paid entirely with Star Money — tax computed at 10.39% on full merchandise subtotal. macys.md note built with evidence.

**Amazon + Walmart dual-account architecture (new 2026-06-07):** `retailer_profiles` needs `account_type text DEFAULT 'default'` column + updated unique constraint `UNIQUE (user_id, retailer_key, account_type)`. Required for Amazon (Business/Personal) AND Walmart (Business/personal). Will be Migration 012 in S10. Design once, apply to both before seeding either profile.

**Amazon Business delayed shipment reward:** 1% credit offered occasionally at checkout for accepting 1–3 day delivery delay. Offered inconsistently — must be prompted at order entry. Capture in `rewards_transactions`. Redemption path on future invoices not yet documented.

**agent_08 naming collision:** `agent_08_cost_basis.py` was named after session S08 but conceptual agent numbering calls it "Agent 04," reserving "Agent 08" for Product Catalog. When Product Catalog is built, `agent_08_product_catalog.py` would collide. Decide renaming convention before that session.

**WFS 365-Day Aging Alert — build priority:** WFS storage fee triples at day 366 ($0.75 → $2.25/cu ft/month). New 450+ day tier at $7.50 effective June 30 2026. Aging alert needed before WFS volume grows. 60-day, 30-day, at-threshold alerts. Cubic footage per set from Brickset dimensions.

**S08 Minor Deferred Items — cleanup sprint in S09:** tax_paid_allocated always 0. Mode 3 never writes gwp.settlement_date. Dead elif branch in collect_gwp_proceeds. net_economic_cost calculated twice. _test_setup_t487170400.py → /tests.

**~~GitHub MCP not connecting~~** ✅ RESOLVED 2026-06-21 — confirmed live in Cowork via `get_me` (connected as `theroyalcrate`). Gmail and Google Drive also confirmed live and connected to the real ResellOS business account. If Claude Code's own local GitHub MCP still has trouble, that's a separate check.

**~~Stale project Instructions field~~** ✅ RESOLVED 2026-06-21 — superseded by a bigger fix: the pasted CONTEXT.md/SESSION_LOG.md copies were deleted from the Claude Project's knowledge files entirely, and the `resell-os-session-start` skill now directs every surface to read live from this repo instead. Josh still needs to add the skill in Settings → Capabilities for plain chat and Cowork (see Cowork 2026-06-21 session card).

**Cost basis state machine doesn't self-advance (new 2026-06-21):** Confirmed against live Supabase data — order T487170400 has all GWP fully sold and settled, but `orders.cost_basis_state` never moved off `estimated`. The estimated → provisional → settled states exist in schema but nothing currently drives the transition automatically. Needs a real trigger (cron, agent run, or explicit step) before the ADR-020 test suite can be considered meaningful — testing a state machine that never advances proves little.

**Cost basis regression testing — ADR-020 (Proposed, 2026-06-21):** See `ADR-020-cost-basis-regression-testing.md` in repo root. Recommends a small fixture-based test suite for `agent_08_cost_basis.py` before Agent 1C's ~635-order historical backfill runs at scale. Not yet built — next concrete step is creating `/tests/test_cost_basis.py` with the T487170400 fixture.

**Gift card savings (cost basis Layer 2) is never persisted (new 2026-06-21):** `agent_08_cost_basis.py`'s Mode 1 collects gift card savings interactively each run and uses it in that one calculation, but never writes it anywhere. There's no way to independently audit or re-derive a past `net_economic_cost` from stored data alone — only the final per-unit `inventory.cost_basis` survives. Worth a small schema addition (e.g. persist the layer inputs somewhere) before this matters at scale.

**None of the 5 live orders have ever had Mode 1 run on them (new 2026-06-21):** confirmed live — every order, including T487170400 whose GWP fully sold a month ago, still has zero inventory rows. `cost_basis_status_report.py` (built this session) surfaces this; running it periodically is currently a manual habit, not automatic (DECISION 017 means it shouldn't be automatic).

**Do not install GSD / "get-shit-done" into this repo (new 2026-06-21):** Original maintainer confirmed compromised (crypto rug-pull, retains npm publish rights to the original package). Community fork (`get-shit-done-redux`) audited clean of backdoors but has unresolved advisory-only security guardrails and a file-exfiltration risk pattern. This repo holds live credentials (`.env`, `credentials/`, OAuth tokens) — don't install either version here. See CONTEXT.md guardrail note.

**Agent 1B Tier 2 PDF-content matching not built (new 2026-07-18, high priority):** `extract_order_number_from_subject()` only matches subjects with "Order"/"Invoice" + digits. LEGO's "Receipt" email type — the only LEGO email type carrying a PDF attachment — has neither, so subject-based matching fails on it regardless of Supabase state. Likely affects most/all of the 201-email business-inbox backlog. `invoice_parser.py` (Agent 1A) already does PDF extraction elsewhere in this repo — next step is designing how it hooks into Agent 1B's matching cascade as the real Tier 2.

**Historical gift-card linkage gap (new 2026-07-18):** Orders backfilled from old invoices (e.g. T469280178) show "paid by gift card" on the invoice but the invoice never prints which card. Needs either manual entry from memory/records or a future LEGO-account scrape to recover card numbers. Entered as unlinked gift card payment for now — a planned gap, not a bug.

**Cosmetic Unicode crash in transition_label() (new 2026-07-18):** The success print statement uses a `→` character that crashes on Windows cp1252 console encoding; the crash is caught by the same try/except wrapping the real API call, producing a false "Label transition failed" warning on actual success. Low priority but should be fixed since it undermines trust in the script's own error messages — a real future failure would look identical to this false one.

**Local migrations/ folder missing 012b (new 2026-07-18):** `invoice_files.user_id` + RLS policy fix was applied directly to Supabase via MCP (table was empty, no backfill needed) but has no corresponding file in the repo's `migrations/` folder yet. Add `012b_invoice_files_user_id_fix.sql` next Claude Code session so the local reference stops silently diverging from live state again.

---

## How to Use This Document

**Start of session:** Open this document. Read "Start Here — Next Session" and "Current Sprint." Do not open VS Code until you've confirmed the database state matches what's recorded here.

**End of session:** Update this document before closing VS Code. Record what was completed, what was deferred, commit message, and next session goal. Update the repo copy via Claude Code first, then sync the project copy.

**Tool access reality:** Chat-Claude (claude.ai) can reach Supabase directly but NOT GitHub or the local repo. Claude Code reads/writes the local repo. Route local file work through Claude Code. **Cowork is a distinct third surface** with broader access than plain chat-Claude — confirmed live 2026-07-18: direct read/write to the local repo folder (mounted), direct GitHub commit access (`create_or_update_file`/`push_files`), and direct Supabase access including schema DDL (`apply_migration`). When working in Cowork, don't assume the older two-surface split above still applies — verify what's actually connected rather than defaulting to "can't reach GitHub."

**What this document supersedes:** The Project Map session descriptions, the Ideas doc sequencing section, and any Claude memory about SQLite. If there's a conflict, this document wins.
