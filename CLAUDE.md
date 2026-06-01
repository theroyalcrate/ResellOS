# ResellOS — Workspace Identity
**Layer 0 — Read this first. Every session. No exceptions.**

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
The stage folder for the current session. Contains the specific job for today, what files to touch, and what the expected output is. If no stages/CURRENT folder exists yet, proceed from SESSION_LOG.md next session instructions.

---

## Folder Structure

```
ResellOS/
├── CLAUDE.md                    ← You are here (Layer 0)
├── CONTEXT.md                   ← Project orientation (Layer 1)
├── SESSION_LOG.md               ← Build state, always current (Layer 1)
├── stages/                      ← One folder per session (Layer 2)
│   └── S09_barnes_agent1b/      ← Current session (example)
│       ├── CONTEXT.md           ← Today's job, scoped to this session
│       ├── references/          ← Stable rules relevant to this session (Layer 3)
│       └── output/              ← Files produced this session (Layer 4)
├── references/                  ← Shared stable reference material (Layer 3)
│   ├── business_logic.md        ← Cost basis rules, GWP, retailers
│   ├── database_schema.md       ← Table structures, field names
│   └── coding_standards.md      ← Code review rules, patterns
├── tests/                       ← Test and verification scripts
├── migrations/                  ← Database migration files
└── skills/                      ← Claude Code skill files
```

> **Note:** The stages/ and references/ folders are being set up. They will be populated before S09 begins. Until then, read SESSION_LOG.md for all session direction.

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
| Claude Code (VS Code) | Read/write local files, run Python, commit + push to GitHub | Query Supabase without Python script |
| Chat-Claude (claude.ai) | Query Supabase directly via MCP, read GitHub repo | Write to local files, run code locally |

Route local file work through Claude Code. Route Supabase queries through chat-Claude when possible.

---

## Current Session

**→ S09** — Barnes Scrapyard Layer 3 verification + Gmail/Drive MCP connection + Agent 1B invoice filing

See SESSION_LOG.md → "Start Here — Next Session" for full S09 scope.

---

## When a Session Ends

1. Update SESSION_LOG.md with what was completed, what was deferred, and what S10 should start with
2. If a new stage folder was used, ensure output/ contains the completed files
3. Commit SESSION_LOG.md update with message: `Session log: S0X complete — next: S0Y`
4. Push to main
