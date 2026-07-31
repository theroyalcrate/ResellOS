# ResellOS — Workspace Identity
**Layer 0 — Read this first. Every session. No exceptions.**
**Last updated: 2026-07-30** — this file drifts easily since it doesn't get touched every session like SESSION_LOG.md does; if anything here conflicts with SESSION_LOG.md, SESSION_LOG.md wins.

---

## What You Are Working On

ResellOS is a personal business operating system for LEGO resellers. Built by a complete beginner to coding — step-by-step guidance required, no assumed knowledge. Every instruction must be explicit.

**Core principle:** Own your data, rent enrichment. Core functions never depend on third-party APIs.

**Database:** Supabase PostgreSQL — permanent. No SQLite. No migration planned.

**Repo:** theroyalcrate/ResellOS

---

## Read These Files In This Order

### 1. SESSION_LOG.md — Read First
Single source of truth for build state. Shows what was built, what is next, and what is deferred. If anything in any other document conflicts with SESSION_LOG.md, the Session Log wins.

### 2. CONTEXT.md — Read Second
Full project orientation — business logic, architecture decisions, retailers, cost basis rules, open questions. Everything Claude needs to understand the domain.

### 3. stages/CURRENT/CONTEXT.md — Read Third (if it exists)
The stage folder for the current session. Contains the specific job for today, what files to touch, and what the expected output is. **In practice, `stages/` has never been populated** — session direction has lived entirely in SESSION_LOG.md's "Start Here — Next Session" section since S01. Check for `stages/CURRENT/` but don't expect it.

---

## Folder Structure

```
ResellOS/
├── CLAUDE.md                    ← You are here (Layer 0)
├── CONTEXT.md                   ← Project orientation (Layer 1)
├── SESSION_LOG.md               ← Build state, always current (Layer 1)
├── stages/                      ← Not in use — see note below
├── references/                  ← Shared stable reference material — populated
│   ├── retailer_email_sources.md   ← Per-retailer sender/subject filter definitions
│   ├── lego_email_parser_spec.md   ← LEGO order-confirmation/receipt parser spec
│   └── kohls_repricing_review_design.md ← Kohl's partial-cancel repricing design
├── agents/                      ← Agent 1B (invoice filing), 1C (historical backfill), 09 (Purchase Planner), 10 (Stock Watch), email_enricher.py
├── tests/                       ← Test and verification scripts (161 passing as of 2026-07-19)
├── migrations/                  ← Database migration files (through 016; next open slot 017 — see SESSION_LOG numbering note)
└── skills/                      ← Claude Code skill files
```

> **Note (revised 2026-07-30):** `stages/` was never actually used — every session since S01 has taken its direction from SESSION_LOG.md's "Start Here — Next Session" section instead. `references/` did get populated (3 files, listed above). Don't expect a `stages/CURRENT/` folder to exist; if the Session Log and this file's folder diagram ever disagree, trust the Session Log.

---

## Critical Rules — Never Violate

1. **Read SESSION_LOG.md before writing any code.** Never assume what was built last session.
2. **Never duplicate line items.** Email agents enrich existing orders only.
3. **Never set buy_reason or purchase_trigger in agents.** Agents never guess intent or channel. Leave null.
4. **Cost basis locks at settlement.** Never reopen. Returns create P&L adjustments.
5. **Negative cost basis is valid.** Never suppress.
6. **is_retiring defaults TRUE** on every line item. Only toggle if the set is confirmed NOT retiring.
7. **Supabase is the only database.** No SQLite. No local files as data store.
8. **Commit working code before starting the next agent.** Never lose a working session.
9. **Code review before every commit.** Check for CRITICAL issues — wrong data in cost basis is worse than no data.

---

## Tool Access Reality

| Tool | Can Do | Cannot Do |
|------|--------|-----------|
| Claude Code (VS Code) | Read/write local files, run Python, commit + push to GitHub | Query Supabase without a Python script |
| Chat-Claude (claude.ai) | Query Supabase directly via MCP, read GitHub repo | Write to local files, run code locally |
| Cowork (confirmed 2026-07-18) | Direct read/write to the local repo folder (mounted), direct GitHub commit access, direct Supabase access including schema DDL — broader than either surface above | — |

Cowork is a distinct third surface, not a hybrid of the other two — verify what's actually connected in a given session rather than assuming the two-surface split still applies everywhere.

---

## Current Session

**Do not trust the label below — it goes stale fast.** Always open SESSION_LOG.md → "Start Here — Next Session" for the real, current scope before doing anything. As of the last update to this file (2026-07-30, reflecting state through 2026-07-19):

**→ S10** — Variable-earn schema (per-order observed rewards, Kohl's Cash block model) + Kohl's earn-cliff pin, competing for priority against **Tier 2 PDF-content matching for Agent 1B** (flagged 2026-07-18 as the higher-leverage item — most LEGO receipt emails have no order number in the subject line, so the ~200-email invoice backlog can't bulk-file until this exists).

Also live and usable but not yet exercised for real: Agent 09 (Purchase Planner, built 2026-07-18, untested against a real buying session) and Agent 10 (buy-side stock/discount watch, built 2026-07-19, only the Walmart checker proven — needs `APIFY_API_TOKEN`/`FIRECRAWL_API_KEY` in `.env` before it runs standalone).

---

## When a Session Ends

1. Update SESSION_LOG.md with what was completed, what was deferred, and what the next session should start with
2. Update CONTEXT.md too if anything durable changed (a new architecture decision, a corrected fact, a resolved open question) — session narrative belongs in SESSION_LOG.md, durable facts belong in CONTEXT.md, don't duplicate one into the other
3. Commit with message: `Session log: <session> complete — next: <session>`
4. Push to main (or, on Cowork, commit directly via GitHub MCP — see Tool Access Reality above)

The `resell-os-session-start` skill (`skills/resell-os-session-start.md`) is meant to enforce this start/end ritual automatically on every surface. It only self-triggers in Claude Code (which auto-loads this file); on plain chat and Cowork it has to be enabled manually under Settings → Capabilities.
