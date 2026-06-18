# Agent 1B — Invoice Filing Agent — Design Doc (Draft)

**Status:** Design fully decided, OAuth credentials configured, and Drive folders ready (2026-06-10/11). All open questions resolved — ready to scaffold/build per §8.

**Goal:** Automate downloading invoice PDFs from Gmail, renaming them to a standard convention, and filing them into the existing Drive folder structure — replacing manual invoice archiving.

---

## 1. Scope for first build

**Forward-looking only.** New invoices arriving in the connected business Gmail account (`theroyalcratellc@gmail.com`) get filed into the matching business Drive folder.

**Out of scope (deferred):**
- Migrating ~15 months of historical invoices currently sitting in the personal Drive/Gmail account. Per CONTEXT.md open question #2, this needs to happen before any backfill automation runs. Planned for the end-of-month vacation session when the personal Gmail/Drive connector is swapped in.
- Linking filed invoices back to `orders` rows in Supabase — possible future enhancement, not in v1.

---

## 2. Confirmed current state (verified 2026-06-10)

**Gmail:** Connected to `theroyalcratellc@gmail.com`. Label `ResellOS-Invoices` exists (`Label_2573281147792874926`) — this is the intake queue.

**Drive folder structure (already scaffolded, currently empty):**

```
Invoices/
  Lego/
    2024/
    2025/
      Q1 2025/
      April 2025/
      May 2025/
      June 2025/
      July 2025/
      August 2025/
      September 2025/
      October 2025/
      November 2025/
      December 2025/
    2026/
      January 2026/ ... December 2026/   ← all 12 months present, correctly named
  Barnes and Noble/
  Kohls/
  Macy's/
  Best Buy/
  Fred Meyer/
  Disney Store/
  Walgreens/
  Amazon Business/
  Amazon personal/
  Walmart/            ← personal Walmart purchases
  Walmart Business/   ← created 2026-06-11, business-account purchases (2% rewards on $250+ online orders)
  Target/    ← confirmed exists
```

**Folder naming pattern observed:** `{Retailer}/{Year}/{Month Year}/` — months spelled out in full (e.g. "December 2025"), Q1 2025 used as a quarter rollup for the earliest data only.

**Folder cleanup status (2026-06-10):** The Drive MCP connector has no rename/move/delete tool for existing files or folders (only `create_file`, `copy_file`, metadata reads). The trailing-space folder names ("Q1 2025 ", "May 2025 ", "June 2025 ", "July 2025 ") can't be fixed programmatically this session — see §9 for the manual steps and Agent 1B's fallback (trim-on-comparison) so a missed manual fix doesn't cause duplicate folders.

---

## 3. Naming convention (decided — confirm field order)

`{order_number}_{RETAILER}_{YYYY-MM-DD}.pdf`

Example: `6714029349_LEGO_2026-06-08.pdf`

**Confirmed:** order-number-first, as selected ("order number + retailer + date").

**Split shipments:** Per A-007, one order can produce multiple invoices/shipments. Append a shipment suffix:

`6714029349_LEGO_2026-06-08_ship2.pdf`

**Unmatched invoices** (order number can't be resolved — see §4): file to `Invoices/{Retailer}/_unmatched/` using `{gmail_message_id}_{RETAILER}_{YYYY-MM-DD}.pdf` so it's still findable, with the email message-id preserved for manual triage.

---

## 4. Order matching

Reuse the existing A-007 email-order-matching cascade (ResellOS-Knowledge vault, Areas/business-logic/email-order-matching.md) rather than building new matching logic:

1. **Order number** from the invoice email (or shipping confirmation) — primary key. Look up in `orders` table to get retailer + order date for foldering/naming.
2. **Set/article number** from invoice line items — fallback if order number isn't on the invoice itself.
3. If neither resolves to an existing order → unmatched review folder (§3).

This keeps Agent 1B consistent with the matching logic the per-retailer email agents will eventually use, rather than inventing a parallel scheme.

---

## 5. Idempotency / tracking — DECIDED

Both mechanisms, built now:

- **Supabase ledger table** `invoice_files` — created 2026-06-10 via migration `012_invoice_files_ledger`. Columns: `id` (uuid PK), `gmail_message_id` (unique), `drive_file_id`, `order_id` (FK → `orders.order_id`), `retailer`, `filed_filename`, `filed_at`, `created_at`. RLS enabled, scoped via `orders.user_id`. This is the source of truth for "what's been filed" and supports re-filing/auditing.
- **Gmail labels** — two-stage workflow (see §6 for exact mechanics): `ResellOS-Invoices` (intake/received) and `ResellOS-Filed` (processed), the latter created 2026-06-10 (`Label_1`).

Agent 1B's scan step: query `label:ResellOS-Invoices`, cross-check `gmail_message_id` against `invoice_files` before processing (belt-and-suspenders against a label update failing silently).

---

## 6. Architecture — DECIDED: Option B (local Python script)

`agent_01b_invoice_filing.py`, matching the existing pattern (agents 02/05/07/08) — run via VS Code/Claude Code, own Gmail API + Google Drive API credentials (OAuth), own connection to Supabase for the `invoice_files` ledger.

**Rationale (Josh, 2026-06-10):** "the local python seems like the way to go, even though it may be harder up front, the long term token savings and ability to run most everything on this pc, or on the mac mini once it ships will create efficiencies going forward, kind of like setting up the supabase postgres vs starting with sql lite."

**Implications:**
- Consistent with agents 02/05/07/08 — one mental model, one place agents live.
- Schedulable (cron / Task Scheduler) without opening a chat.
- Can run against both personal and business accounts with separate credential sets — useful for the end-of-month historical migration too.
- Setup cost: Gmail API + Drive API OAuth credentials for the local Python environment (Google Cloud Console project, OAuth consent screen, `credentials.json`, token refresh handling). This is new territory — per CONTEXT.md, plan for step-by-step guidance during the build session.
- Still worth structuring the **logic** (matching, naming, foldering, idempotency check) as pure functions separate from the Gmail/Drive I/O layer — makes it testable and keeps the door open if any piece ever needs to move to MCP-based execution.

### Gmail label semantics — DECIDED

Two-stage workflow, both labels kept in existence as a pipeline:

- `ResellOS-Invoices` (`Label_2573281147792874926`) = received/queue. Scan target: `label:ResellOS-Invoices`.
- `ResellOS-Filed` (`Label_1`, created 2026-06-10) = processed.

**Rationale (Josh, 2026-06-10):** "keep both, invoices show received, moved to filed once processed." Read as: a message starts in `ResellOS-Invoices`; once Agent 1B successfully downloads, renames, and files the attachment (and records it in `invoice_files`), it removes `ResellOS-Invoices` and adds `ResellOS-Filed` — the message *moves* from received to filed rather than carrying both labels simultaneously. This keeps the scan query simple (`label:ResellOS-Invoices` always means "still needs processing") while `ResellOS-Filed` gives a quick visual/searchable record of what's done.

---

## 7. Open questions — all resolved 2026-06-10

1. **Architecture** → Option B, local Python. See §6.
2. **December 2026 folder** → false alarm — all 12 months for 2026 exist and are correctly named (verified 2026-06-11). No action needed.
3. **Folder name whitespace** → clean up now, manually. See §9. Agent 1B will *also* trim on comparison as a safety net regardless.
4. **Ledger table vs. label-only** → both, built now. See §5.
5. **Walmart Business / Target Drive folders** → DECIDED 2026-06-11: split mirrors Amazon Business / Amazon personal. `Walmart/` = personal purchases, `Walmart Business/` (created 2026-06-11) = business-account purchases — Walmart Business gets a 2% rewards bonus on online orders over $250, so the accounts are tracked separately for that reason. **Routing rule (confirmed 2026-06-11):** Walmart Business order emails come from `Walmart Business <businessinfo@walmart.com>`, with "Walmart Business" in the email body — match on sender `businessinfo@walmart.com` to route to `Walmart Business/`. Personal Walmart order emails come from `Walmart.com <help@walmart.com>`, with just "Walmart" in the body — match on sender `help@walmart.com` to route to `Walmart/`. `Target/` already exists, no split needed.
6. **Filed-label semantics** → two-stage move (`ResellOS-Invoices` → `ResellOS-Filed`). See §6.

---

## 8. Suggested next session flow

1. Manual Drive cleanup per §9 (5 minutes, your end).
2. Decide the Walmart vs. Walmart Business folder question (§7.5).
3. Build session: set up Google Cloud Console project + OAuth credentials for Gmail API & Drive API (step-by-step, since this is new).
4. Scaffold the pure-logic functions (naming, A-007 matching call, folder-path resolution, label transition) with unit tests against a few real invoice examples (e.g. the June 8th Kohl's orders already in the system).
5. Wire up the I/O layer (Gmail API, Drive API, Supabase client for `invoice_files`).
6. Run the resell-os-code-review skill before committing, per project convention.
7. Update SESSION_LOG.md / CONTEXT.md with the decision and outcome.

---

## 9. Drive folder cleanup — DONE

All folder cleanup is complete and verified (2026-06-11):

- `Invoices/Lego/2025/` now has clean Jan–Dec 2025 month folders, no trailing spaces, no "Q1 2025" rollup folder. ✅
- `Invoices/Lego/2026/` has all 12 months, correctly named. ✅ (the earlier "December 2026 only" note was based on an incomplete page of results — false alarm)

Done programmatically (this session, 2026-06-10):
- Created Gmail label `ResellOS-Filed` (`Label_1`).
- Applied Supabase migration `012_invoice_files_ledger`, creating `public.invoice_files` with RLS.

**Remaining open item:** the Walmart vs. "Walmart Business" folder naming question (§7.5) — otherwise Agent 1B's design inputs are fully settled.

---

## 10. OAuth credential setup — DONE (2026-06-11)

Completed for `theroyalcratellc@gmail.com`:

- Google Cloud project `ResellOS-Agent1B` created; Gmail API and Drive API enabled.
- Google Auth Platform configured (External, Testing publishing status), test user `theroyalcratellc@gmail.com` added under Audience.
- OAuth Desktop-app client created; client secret saved as `credentials/credentials.json` (gitignored, never committed).
- Python libraries installed in venv: `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`.
- One-time auth script `setup_oauth.py` (repo root, tracked in git — no secrets) created and run successfully; generated `credentials/token.json` (gitignored).
- Scopes granted: `gmail.modify` (read messages, download attachments, manage labels) and `drive` (full read/write — needed for existing folder structure, `drive.file` would be too narrow).

Agent 1B's I/O layer can authenticate via `Credentials.from_authorized_user_file('credentials/token.json', SCOPES)` with auto-refresh, matching the pattern in `setup_oauth.py`.

**Walmart routing rule (confirmed 2026-06-11):** `businessinfo@walmart.com` ("Walmart Business" in body) → `Walmart Business/`; `help@walmart.com` ("Walmart" in body) → `Walmart/`. See §7.5.

**Next up:** §8 build steps (scaffold pure-logic functions, wire up I/O, code review, update logs).
