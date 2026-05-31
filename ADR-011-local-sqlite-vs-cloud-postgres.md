# ADR-011: Local SQLite vs Cloud Postgres as the Starting Database

**Status:** Proposed
**Date:** 2026-05-16
**Deciders:** Josh (owner / builder)

## Context

ResellOS v1.0 architecture (existing master doc, Decision 001 + Tech Stack item 3) specifies SQLite as the local data layer for personal use, with a migration to PostgreSQL planned at community launch. That choice was made when offline operation was a hard requirement.

Two facts have since changed the calculus:

1. **Offline-only is no longer required.** The system can assume internet during normal use; offline support, if needed at all, becomes a nice-to-have rather than a foundational constraint.
2. **SaaS is the stated end goal.** Other resellers paying a subscription is the destination, not a maybe. That means every line of code written for "personal use" either ports to multi-tenant production or has to be rewritten.

The owner is also brand new to coding, which weights this decision unusually heavily toward "pick the path that minimizes total rework," because the cost of a rewrite for a beginner is much higher than for an experienced engineer — both in calendar time and in the risk of abandoning the project mid-rewrite.

The core question: does keeping SQLite as a Phase 1 step pay for itself, or does it create a migration tax that's larger than the simplicity it buys?

## Decision

**Adopt cloud-hosted Postgres (specifically Supabase) from day one. Skip the SQLite phase entirely.**

Build the schema once, in the production database, on a free tier. Treat the "personal use" period as a single-tenant production deployment with one user (the owner) — not a different architecture.

## Options Considered

### Option A: Current plan — SQLite first, Postgres at community launch

| Dimension | Assessment |
|---|---|
| Complexity (now) | Low — `sqlite3` is in the Python standard library; no signup, no auth, no network |
| Complexity (later) | High — schema migration, data migration, auth bolt-on, rewriting any SQL that used SQLite-specific syntax, redoing every CRUD path against a network database |
| Cost | $0 now, $0–$25/mo later |
| Scalability | Single-user only |
| Team familiarity | SQLite is the friendliest possible database — single file, no server |
| SaaS readiness | Requires a full migration project before any second user can sign up |

**Pros**
- Lowest possible friction to first working code
- No accounts, no networking, no auth — purely "open file, read rows"
- Backs up trivially (it's just a file in GitHub)
- The local file is easy to inspect with free tools (DB Browser for SQLite)

**Cons**
- The migration to Postgres is a project, not a flip — auth, hosted infra, schema port, data move, code changes for every query, redoing the agent loop to talk to a network DB
- Some SQLite features don't have Postgres equivalents (and vice versa); learning two databases is harder than learning one
- "Multi-user impossible in Sheets" (per Decision 001) is correct, but multi-user is also nearly impossible in SQLite — pushing that problem to v2 means writing v1 in a way that has to be rewritten
- Beginner coders rarely complete a rewrite-the-database project — the abandoned-side-project graveyard is full of them

### Option B: Cloud Postgres from day one (recommended — Supabase)

| Dimension | Assessment |
|---|---|
| Complexity (now) | Medium — sign up for Supabase, get a connection string, learn `psycopg` or use the Supabase Python SDK |
| Complexity (later) | Low — same database, just add users to the existing schema |
| Cost | $0 on Supabase free tier (500MB DB, 50K monthly active users) until real SaaS traction; $25/mo Pro tier handles serious scale |
| Scalability | Multi-tenant from line one with Row-Level Security (RLS) |
| Team familiarity | Postgres is the industry standard; every tutorial, AI assistant, and Stack Overflow answer assumes it |
| SaaS readiness | Already there — auth, RLS, REST API, and realtime sync are built in |

**Pros**
- No migration project later. Ever. The schema you write Saturday is the schema your first paying customer uses.
- Supabase provides auth, storage, and an auto-generated REST API for free — you write less code, not more
- Row-Level Security means the same database serves you alone today and 1,000 resellers later, with the same query code
- The free tier is generous enough that personal use will never hit a paywall
- Postgres has every feature SQLite has plus features you'll want (proper date types, JSON columns for flexible reseller-specific fields, full-text search for set descriptions)
- The web dashboard lets you inspect and edit data without writing code — same convenience SQLite has

**Cons**
- Requires internet for the app to function (no longer a hard constraint, but still a real change from SQLite)
- One extra account to manage (Supabase sign-in)
- A connection string in a `.env` file — slightly more setup than "open file"
- The free tier pauses databases after 7 days of inactivity (auto-resumes on first request, ~1-second delay)

### Option C: Local-first with sync (CRDTs / replication)

The architecturally elegant answer for "works offline AND becomes multi-tenant" — use a library like ElectricSQL, RxDB, or PowerSync to keep a local SQLite mirror that syncs to cloud Postgres.

| Dimension | Assessment |
|---|---|
| Complexity (now) | High — sync engines have steep learning curves and edge cases (conflict resolution, schema migrations across versions) |
| Complexity (later) | Medium |
| Cost | Varies; usually $0 to start |
| Scalability | Excellent |
| Team familiarity | Niche — small communities, fewer tutorials, AI assistants are weaker here |

**Pros**
- Truly offline-capable
- "Local-first software" is a beautiful pattern when it works

**Cons**
- Wrong tool for a brand-new coder; sync conflict bugs are some of the hardest in software
- Offline is no longer a hard requirement, so the cost no longer pays for itself
- Adds a third dependency (Postgres + SQLite + sync engine) instead of removing one

## Trade-off Analysis

The decisive factor is **migration cost vs. setup cost**, weighted by builder skill level.

For an experienced engineer, Option A is defensible — SQLite-first is genuinely faster to a working prototype, and the migration is a 1–2 week project for someone who's done it before. The math favors A.

For a first-time coder, the math inverts. The setup cost of Supabase (one signup, one connection string, ten minutes) is small. The migration cost of SQLite → Postgres is large: it requires confidence in schema design, comfort with two query dialects, and the willingness to refactor every working agent. That's a project most first-time coders don't finish, and the existing v1 then becomes a trap rather than a stepping stone.

Option B trades a small one-time setup for elimination of the migration entirely. Given the SaaS endgame is explicit, the migration is non-optional — only the timing is in question. Doing it on day one, with no data and no users, is strictly cheaper than doing it later with both.

Option C is correct for a different project (one where offline genuinely matters). It's wrong for this one.

## Consequences

**What becomes easier**
- Architecture stays single-track. No "v1 architecture" and "v2 architecture" — just "the architecture."
- Auth, multi-user, and SaaS readiness are free, not a future project.
- Every tutorial, every AI assistant, and every reseller community member running Postgres can help with your queries.
- Data is backed up by Supabase automatically; no manual export/commit dance.
- The agent loop can stay almost identical — `sqlite3` becomes `psycopg` or `supabase-py`, but the SQL itself is 95% portable.

**What becomes harder**
- The dev environment now requires an internet connection. (For Cowork users this is true anyway.)
- One extra account at sign-up. One `.env` file to keep out of GitHub.
- Inspecting data goes through the Supabase web dashboard instead of a local file viewer (the dashboard is actually nicer, but it's different).

**What we'll need to revisit**
- **Decision 001** (in the master doc) needs to be amended: "All truth lives in SQLite locally, upgrading to PostgreSQL at community launch" → "All truth lives in cloud Postgres (Supabase) from day one. Google Sheets remains the read-only view layer."
- **Tech Stack item 3** ("SQLite → PostgreSQL") collapses to just "PostgreSQL via Supabase."
- **Tech Stack item 5** (MCP connector priority) shifts: the Supabase MCP enters the priority list, likely between filesystem and GitHub.
- **Decision 010** (Build Environment) stays unchanged — VS Code, Claude Code, Python venv all remain correct.

## Action Items

1. [ ] Create a free Supabase project at supabase.com (10 minutes)
2. [ ] Save the project's connection string and `anon` API key to a local `.env` file; add `.env` to `.gitignore` before the first commit
3. [ ] Install Python dependencies: `pip install supabase python-dotenv psycopg[binary]`
4. [ ] Translate the existing 9-table SQLite schema into Postgres-flavored `CREATE TABLE` statements (mostly identical; main changes: `INTEGER PK` becomes `BIGSERIAL PRIMARY KEY` or `UUID PRIMARY KEY`, `DATETIME` becomes `TIMESTAMPTZ`, `BOOLEAN` is native)
5. [ ] Run the schema in the Supabase SQL editor — this is your single source of truth going forward
6. [ ] Enable Row-Level Security on every table from day one, with a placeholder policy of `auth.uid() = user_id` — even though there's only one user today, this prevents the worst class of SaaS data-leak bugs at launch
7. [ ] Update the master architecture doc to reflect Decisions 001 amendment and Tech Stack consolidation
8. [ ] Re-point Agent 02 (manual order entry) and Agent 01A (invoice parser) at the Supabase connection as the first agent migration test

---

## Open questions for the next session

- Do you want auth from day one (so your future SaaS users sign in), or run it as a single-user system with auth bolted on at community launch? (My recommendation: from day one, since Supabase makes it free and the RLS pattern works correctly only if `user_id` is on every row from the start.)
- Should Google Sheets stay the bookkeeper/CPA view layer, or does Supabase's built-in dashboard plus a simple Streamlit/Next.js read-only page replace it? (Worth its own ADR.)
- Python is fine for the agent loop, but the SaaS web app — when it arrives — will need a frontend. Want to think about that now, or defer until the data layer and agents are working?
