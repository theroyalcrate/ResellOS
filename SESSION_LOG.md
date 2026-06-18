# ResellOS — Session Log

**Single source of truth for build state. Updated at the end of every session. Read this first before opening VS Code.**

| | |
|---|---|
| **Last Updated** | 2026-06-17 |
| **Sessions Complete** | S01 → S09 ✓, S8.5 ✓, Pre-S10 ✓, Pre-S10 Agent 1B ✓, Pre-S10 Agent 1B+1C ✓, Pre-S10 Agent 1C standalone ✓ |
| **Next Session** | S10 (variable-earn schema, after CPA meeting) + Agent 1B live test |
| **Phase** | P1 — Week 2 |
| **GitHub** | theroyalcrate/ResellOS |

> **Document home & sync rule:** Source-of-truth copy lives in the GitHub repo, edited via Claude Code. GitHub MCP read access confirmed 2026-06-03 — chat-Claude can read the repo directly. Manual paste into project copy is no longer required. Writes still route through Claude Code.

---

## Start Here — Next Session

### S10 — Variable-Earn Schema + Agent 1B Live Test *(after June 10 CPA meeting)*

**Step 1 — Agent 1B live test (do this first, takes 5 minutes):**
- Agent 1B is built (50/50 unit tests passing). Now has 5 modes: 1=Preview, 2=File one, 3=Ledger, 4=Personal backfill, 5=Safety filter.
- Run `python setup_oauth.py` first — this now sets up BOTH business token (token_business.json) and personal token (token_personal.json). Two browser windows will open — follow console prompts.
- Then run Mode 1 preview: `python agents/agent_01b_invoice_filing.py` → select 1. Review the queue, confirm one invoice looks right.
- Then run Mode 4 to backfill personal Gmail history → select 4. Review the summary log.
- Then run Mode 2 to file one business invoice → select 2.
- Then run Mode 5 to create the personal safety-net filter → select 5.
- **Do not file broadly until at least one real invoice is verified end-to-end** (Gmail → Drive → ledger → label transition).
- Migration 012 (`invoice_files` ledger) was applied 2026-06-10 — already in Supabase.

**Step 2 — CPA meeting takeaways:**
- Record answers to Q1–Q5 in `Projects/cpa-meeting/cpa-meeting-2026-06-10.md`.
- Apply gated decisions: ADR-019 (FIFO), cashback layer activation, Capital One chain `gift_cards.price_paid` write path.

**Step 3 — S10 schema work (see S10 section below).**

**Note on Migration 012 numbering:** The local file is `012_invoice_files_ledger.sql` but S10 had planned to use 012 for `account_type` on `retailer_profiles`. The invoice_files migration was applied in Supabase during this session (2026-06-10) and takes 012. The `account_type` migration is now 013, and `block_identifier` is 014.

---

### S10 — Phase 3: Variable-Earn Schema + Kohl's Cash Earn Cliff Pin *(after June 10 CPA meeting)*

**Goal:** Two-part session. (1) Build the variable-earn schema: per-order observed rewards capture (not computed from fixed rates) + Kohl's Cash block model with explicit expiration_date per block. This touches `orders`, `promotional_cash`, and `agent_02_order_entry.py`. Run the resell-os-code-review skill on engine changes before committing. (2) Pin the exact sub-$50 Kohl's Cash earn cliff boundary against the June 8th orders.

**Phase 3 schema tasks:**
1. Migration 013 (was 012 — bumped by invoice_files): `account_type` column on `retailer_profiles` + updated unique constraint. Seed Amazon Business and Amazon Personal profiles. Seed Walmart Business profile.
2. Migration 014 (was 013): add `block_identifier` to `promotional_cash` (for xNNNN matching against invoice payment lines). Review whether any other columns are needed for the block model (see kohls.md Schema notes).
3. `agent_02_order_entry.py` — replace the computed Kohl's rewards section (`_kohls_rewards()`, `_kohls_event_cash()`) with read-from-invoice prompts: capture actual earned amounts from the invoice, not derived from hardcoded constants. Capture expiration window dates for Kohl's Cash blocks and write to `promotional_cash`.
4. Confirm `orders.kohls_rewards_earned` and `orders.kohls_event_cash_earned` columns exist and stay — but population path changes from compute to capture.
5. Code review the agent_02 diff before commit (resell-os-code-review skill — look for any path that still derives a reward amount from a rate).
6. Commit: "S10: Variable-earn schema — read rewards from invoice, Kohl's Cash block model, migrations 013-014"

**CPA-gated decisions to apply in S10:**
- Q1 (FIFO): write ADR-019, lock `users.costing_method` docs
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
| Pre-S10 Agent 1B (2026-06-10) | Agent 1B invoice filing built: pure-logic functions, 50 unit tests, I/O layer (Gmail/Drive/Supabase), migration 012 (invoice_files), .gitignore UTF-8 fix, setup_oauth.py. Code-reviewed — 6 bugs fixed. Needs live test (Mode 1 preview, then Mode 2 one invoice). | ✓ Built, pending live test |
| Pre-S10 Agent 1B+1C (2026-06-17) | Agent 1B extended with personal Gmail backfill (Mode 4) + safety-net filter (Mode 5). setup_oauth.py rewritten for two tokens. 4 code-review bugs fixed. Needs live test of all 5 modes. | ✓ Built, pending live test |
| Pre-S10 Agent 1C standalone (2026-06-17) | Agent 1C built as separate script (agents/agent_01c_historical_backfill.py). 3 modes: Preview, Copy, Ledger. LEGO senders only (billing03 + m.lego.com), Feb 2025–Jun 2026. Mode 1 confirmed 748 emails. Mode 2 copy run. OAuth issues resolved (personal token was wrong file; business token 7-day expiry on test app). | ✓ Complete |
| S10 | Phase 3: variable-earn schema + account_type migration (013) + Kohl's Cash block model (014) + CPA-gated decisions applied + Agent 1B live test (all 5 modes) | ⏳ After CPA |

---

## Database — Current State

**Supabase PostgreSQL — Live**

- **23** tables live (invoice_files added — migration 012 applied 2026-06-10)
- Migrations applied through **012**
- **5** orders in DB
- **RLS ON** — every table secured
- **Multi-user** — user_id on every table
- Code committed to GitHub (note: GitHub MCP not currently connecting — verify via Claude Code)

**Key tables confirmed live:** orders (+ cost_basis_state, buy_reason, purchase_trigger), shipments, line_items (+ set_number, is_retiring), inventory, sales, gift_cards, gift_card_assignments, rewards_transactions, cashback_transactions, gwp (+ status, net_proceeds, sale_date, settlement_date), tax_recovery, market_events, promotional_cash, returns, retailer_profiles, retailer_cashback_profiles, portal_health, business_expenses, inventory_check_sessions, inventory_check_items, users (+ gwp_cost_treatment, costing_method) — 22 tables total.

---

## Session History

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

**CPA/Attorney Meeting — June 10, 9:00-9:30am:** (1) Confirm FIFO — locks permanently once data accumulates. (2) Cashback/credit card rewards — cost reduction or income? Determines whether cashback layer activates. (3) WA State tax recovery — reduces COGS retroactively or separate income in period received? (4) S-Corp vs Schedule C — at $72K net profit year one, 2026 or 2027? (5) Capital One Shopping chain — cashback → Macy's gift card → inventory. Does rebate treatment follow the chain or does gift card redemption create a new cost basis event?

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

**GitHub MCP not connecting:** Does not appear under connections. Standalone troubleshoot. Chat-Claude cannot reach GitHub or local repo regardless — route local file work through Claude Code.

**Stale project Instructions field:** The project's Instructions panel still holds the old 2026-05-26 context. Sync it to the current context doc so fresh conversations don't start stale.

---

## How to Use This Document

**Start of session:** Open this document. Read "Start Here — Next Session" and "Current Sprint." Do not open VS Code until you've confirmed the database state matches what's recorded here.

**End of session:** Update this document before closing VS Code. Record what was completed, what was deferred, commit message, and next session goal. Update the repo copy via Claude Code first, then sync the project copy.

**Tool access reality:** Chat-Claude can reach Supabase directly but NOT GitHub or the local repo. Claude Code reads/writes the local repo. Route local file work through Claude Code.

**What this document supersedes:** The Project Map session descriptions, the Ideas doc sequencing section, and any Claude memory about SQLite. If there's a conflict, this document wins.
