---
name: resell-os-session-logger
description: Manages ResellOS session state across two documents — SESSION_LOG.md (build history) and CONTEXT.md (Claude orientation). Has two modes: SESSION START (triggered by "read the session log", "where did we leave off", "session start") and SESSION END (triggered by "log the session", "update the session log", "wrap up", "end of session"). SESSION START reads both docs, reports latest state, and cross-checks database state against live Supabase. SESSION END updates both documents, writes them to the repo, and prints ready-to-paste copies for the Claude project files.
---

# ResellOS Session Logger Skill

Manages the two documents that keep Claude oriented across sessions:

- **SESSION_LOG.md** — build history, per-session cards, carry-forward items, open questions
- **CONTEXT.md** — Claude orientation: stack, build state, business logic, architecture decisions

Both documents live in the repo root. Identical copies live in the Claude project (project files + Instructions panel). The repo is always the source of truth; the project copies are updated manually after each commit.

---

## MODE 1 — SESSION START

**Triggers:** "read the session log", "where did we leave off", "session start", "what's the current state", "catch me up"

### Step 1 — Read Both Documents

Read `SESSION_LOG.md` and `CONTEXT.md` from the repo root. Extract:
- Last Updated date from both documents
- Current session number and next session goal from SESSION_LOG.md
- Database state line from CONTEXT.md (table count, migration level, order count)
- Any carry-forward items flagged with ⚠ in the most recent session card

### Step 2 — Cross-Check Live Supabase State

Query Supabase to verify the recorded database state is accurate. Run these checks:

**Table count:**
```sql
SELECT COUNT(*) FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
```

**Order count:**
```sql
SELECT COUNT(*) FROM orders WHERE user_id = '00000000-0000-0000-0000-000000000001';
```

**Latest migration applied:** Check the `supabase_migrations.schema_migrations` table or the highest-numbered migration file present.

**cost_basis_state column exists:**
```sql
SELECT column_name FROM information_schema.columns
WHERE table_name = 'orders' AND column_name = 'cost_basis_state';
```

### Step 3 — Report and Flag Mismatches

Output a session-start summary in this format:

```
SESSION START — ResellOS
========================
Docs last updated: [date from SESSION_LOG.md]
Next session: [session number and title]

RECORDED DB STATE
-----------------
Tables: [n from doc]
Orders: [n from doc]
Migrations through: [n from doc]

LIVE DB STATE (just checked)
-----------------------------
Tables: [actual count]
Orders: [actual count]
Latest migration: [actual]

[MATCH ✓ or MISMATCH ⚠ — list any discrepancies]

CARRY-FORWARD FROM LAST SESSION
--------------------------------
[List ⚠ items from the most recent session card]

READY TO START — [next session goal]
```

Flag any mismatch clearly before the user plans work. A mismatch means the docs are stale and need to be updated before relying on them.

---

## MODE 2 — SESSION END

**Triggers:** "log the session", "update the session log", "wrap up", "end of session", "session complete", "update both docs"

### Step 1 — Gather Session Content

Collect from the current conversation:
- Session number and title
- Date (today's date)
- What was built or changed
- Verification results if any
- Code review findings and their resolution status
- Deferred items (carry-forward ⚠)
- Commit message(s) used
- Any new design decisions made
- Any new open questions raised

If any of these are unclear, ask before writing — a wrong session card is worse than a delayed one.

### Step 2 — Update SESSION_LOG.md

Read the current `SESSION_LOG.md`. Make these updates:

1. **Header table** — update `Last Updated`, `Sessions Complete`, and `Next Session`
2. **Current Sprint table** — mark the just-completed session ✓ Complete, update next session row to → Next
3. **Add new session card** — insert at the top of Session History, above the previous most-recent card. Use this format:

```markdown
### S[N] — [Title] ✓ Done — [YYYY-MM-DD]

**What was built:**
- [bullet list]

**Verification:** [if applicable]

**Code review results:** [if applicable — CRITICAL/MODERATE/MINOR with resolution status]

**Design decisions:** [any new decisions made this session]

**Carry-forward:**
- ⚠ [items deferred, not yet resolved]

**Commit message:**
```
[exact commit message used]
```
```

4. **Open Questions** — add any new open questions raised this session. Remove or mark resolved any questions that were answered.

5. **Architecture Doc Corrections** — add a new OVERRIDE entry if any previous documented decision was changed this session.

### Step 3 — Update CONTEXT.md

Read the current `CONTEXT.md`. Make these targeted updates — do NOT rewrite sections that haven't changed:

1. **Last Updated** date in the header
2. **Build State table** — mark the just-completed session ✓ Done, update next session to → Next
3. **Database state line** — update table count, migration level, order count to match what was actually built
4. **Any section whose content changed this session** — decisions, business logic, edge cases, planned systems. Be surgical; don't touch what didn't change.

### Step 4 — Write Both Files to the Repo

Write the updated content to:
- `SESSION_LOG.md` (repo root)
- `CONTEXT.md` (repo root)

### Step 5 — Print Ready-to-Paste Copies

Print the full updated content of both files as clearly labeled code blocks:

```
╔══════════════════════════════════════════════════════════════════╗
║  SESSION_LOG.md — FULL UPDATED CONTENT — PASTE INTO PROJECT FILE ║
╚══════════════════════════════════════════════════════════════════╝

[full file content here]


╔══════════════════════════════════════════════════════════════════╗
║  CONTEXT.md — FULL UPDATED CONTENT — PASTE INTO PROJECT FILE    ║
║  Also paste into the Claude project Instructions panel           ║
╚══════════════════════════════════════════════════════════════════╝

[full file content here]
```

### Step 6 — Print Sync Reminder

After the paste blocks, always print:

```
─────────────────────────────────────────────────────────
MANUAL SYNC REQUIRED — DO THIS BEFORE STARTING S[N+1]
─────────────────────────────────────────────────────────
1. Commit both files to the repo (if not already done)
2. Open the Claude project → Files tab
   → Replace SESSION_LOG.md with the content above
   → Replace CONTEXT.md with the content above
3. Open the Claude project → Instructions panel
   → Replace the full contents with the CONTEXT.md content above
4. Verify: the Last Updated date in the project copy
   matches the repo copy.

Drift between repo and project copies causes re-walking
completed work at the start of the next session.
─────────────────────────────────────────────────────────
```

---

## Document Format Rules

### SESSION_LOG.md
- Session cards newest-first (most recent at top of Session History)
- Carry-forward items use ⚠ prefix so they're scannable
- Commit messages in fenced code blocks
- Dates as YYYY-MM-DD

### CONTEXT.md
- Build State table stays compact — one row per session, status column only
- Database state line: `N tables live, migrations through NNN applied, N orders in DB`
- Architecture Decisions table — add rows, never delete rows (use strikethrough + note for reversals)
- Open Questions numbered list — remove when resolved, add when raised

---

## Key Constants (Do Not Prompt For)

```
PHASE_1_USER_ID = '00000000-0000-0000-0000-000000000001'
Repo: theroyalcrate/ResellOS
Docs location: repo root (SESSION_LOG.md, CONTEXT.md)
```
