---
name: resell-os-session-logger
description: >
  Maintains the ResellOS Session Log and CONTEXT.md across both VS Code build sessions and
  planning/vault sessions. Use this skill whenever the user says "update the session log",
  "log this session", "wrap up the session", "what should I add to the log", "close out the
  session", "generate the Claude Code prompt", or "write up the session". Also trigger at the
  START of any session when the user says "read the session log", "what did we do last time",
  or "where did we leave off" — in that case, READ the log and summarize it; don't update yet.
  Two session types handled: (1) VS Code build sessions — update the HTML session log file
  directly. (2) Planning/vault/CPA sessions — produce a ready-to-paste Claude Code prompt
  that updates CONTEXT.md and SESSION_LOG.md. The skill detects which type from context and
  routes accordingly. Never ask the user which type — infer it.
---

# ResellOS Session Logger

Maintains the living Session Log and CONTEXT.md so every session starts with accurate context
and ends with an honest record of what was completed, what was decided, and what comes next.

---

## When to READ vs UPDATE

**READ mode** — triggered by:
- "Where did we leave off?"
- "What did we do last time?"
- "Catch me up"
- Start of a session before opening VS Code

→ Pull the Session Log from GitHub. Summarize: current sprint position, next session goal,
any open questions or blockers. Do NOT update anything yet.

**UPDATE mode** — triggered by:
- "Update the session log"
- "Log this session"
- "Wrap up" / "Close out the session"
- "Generate the Claude Code prompt"
- "Write up the session"
- End of any session — VS Code build or planning/vault

→ Detect session type (see below), then follow the matching protocol.

---

## SESSION TYPE DETECTION

Before doing anything else, determine which type of session just ended. Do NOT ask — infer
from conversation context.

**VS Code build session** signals:
- Code was written, reviewed, or committed
- Migrations were run
- Agents were built or modified
- A commit message exists or was discussed
- GitHub repo files were changed

→ Follow: VS CODE BUILD SESSION PROTOCOL

**Planning / vault / CPA session** signals:
- Vault notes were built (retailer interviews, knowledge docs)
- Architecture decisions were discussed or confirmed
- CPA/accounting questions were worked through
- Open questions were resolved or added
- No code was written, no commits made

→ Follow: PLANNING/VAULT SESSION PROTOCOL

If a session had BOTH (e.g. vault work + a quick schema fix committed) — run the
PLANNING/VAULT PROTOCOL first to produce the Claude Code prompt, then note the VS Code
work inside that prompt's SESSION_LOG.md entry. Do not run both protocols separately.

---

## VS CODE BUILD SESSION PROTOCOL

### Step 1 — Gather what happened

Ask (or pull from conversation context) if not already known:

1. **Session ID** — what was the session number? (e.g. S10)
2. **Date** — today's date
3. **What was completed** — list of specific things that now work and are committed to GitHub
4. **What was deferred** — things attempted but not finished, or descoped
5. **Commit message** — exact commit message used (ask if not stated)
6. **Did any architecture decisions change?** — new tables, changed approach, reversed decision
7. **What is the next session goal?** — one sentence

If the user says "just write it up" or "you know what we did" — infer from conversation
history and confirm before writing.

### Step 2 — Identify what needs to change in the HTML

The Session Log HTML file (ResellOS___Session_Log.html) has these key zones:

| Zone | What it contains | When to update |
|------|-----------------|----------------|
| `header-meta` | Last Updated date, Sessions Complete range, Next Session ID, Phase | Every session |
| `next-callout` | Next session goal and step-by-step plan | Every session — replace entirely |
| `status-board` | Sprint rows with status pills | Update completed sessions to `pill-done`, advance `pill-next` |
| `session-card` blocks | One card per session with full detail | Add new card for the session just completed |
| `override` blocks | Architecture corrections | Add one if a decision changed |
| `open questions` | Unresolved blockers and ADRs | Add, remove, or update as needed |

### Step 3 — Write the updates

Produce the exact HTML changes needed. For each change:
- State which zone is being updated
- Show the old content (brief) and new content (full)
- For new session cards: use the existing card HTML structure as a template

**Session card template:**
```html
<div class="session-card open">
  <div class="sc-header" onclick="this.parentElement.classList.toggle('open')">
    <div class="sc-num">SXX</div>
    <div class="sc-title">[Title] <span class="tag tag-done">✓ Done</span></div>
    <div class="sc-date">YYYY-MM-DD</div>
    <div class="sc-chevron">▾</div>
  </div>
  <div class="sc-body">
    <div class="sc-section">
      <div class="sc-section-label">What Was Built</div>
      <ul class="sc-list">
        <li class="done">[completed item]</li>
        <li class="warn">[partial / deferred item]</li>
        <li class="blocked">[blocked item]</li>
      </ul>
    </div>
    <div class="sc-section">
      <div class="sc-section-label">Commit Message</div>
      <div class="sc-code">[exact commit message]</div>
    </div>
  </div>
</div>
```

**Status pill classes:**
- `pill-done` — complete and committed
- `pill-partial` — attempted, flaw found, or not finished
- `pill-next` — the very next session to run
- `pill-upcoming` — planned but not yet started

**Sprint row status note pattern:**
```html
<span class="note">[One sentence of key facts — what was done, what changed, what was deferred]</span>
```

**Override block template (use when a decision reversed or an architecture doc is now wrong):**
```html
<div class="override">
  <div class="override-header">
    <div class="override-id">OVERRIDE XXX — [Topic]</div>
    <div class="override-date">YYYY-MM-DD</div>
  </div>
  <div class="override-body">[Explanation of what changed and why]</div>
  <div class="override-old">[What the old docs say — quoted or paraphrased]</div>
  <div class="override-new">[What is now true]</div>
</div>
```

### Step 4 — Confirm with the user

Before writing the file, show:
1. A plain-English summary of what you're adding/changing (2-4 bullet points)
2. Ask: "Does this look right? Anything I'm missing?"

Only write the file after the user confirms.

### Step 5 — Write the updated file

Apply all changes to the HTML. The file lives at:
```
ResellOS___Session_Log.html
```

(In Claude.ai, present the updated file for download. In VS Code / Claude Code, write it
to the project root or wherever the other ResellOS HTML docs live.)

### Step 6 — Close out

Tell the user:
- What was updated
- What the next session number and goal is
- One reminder if there's anything to check before starting next time

---

## PLANNING/VAULT SESSION PROTOCOL

Used when a session involved decisions, vault notes, CPA prep, or design work — but no
VS Code code commits. Output is a ready-to-paste Claude Code prompt, not an HTML file write.

### Step 1 — Gather what happened

Pull from conversation history. Confirm anything unclear. Collect:

1. **Date** — today's date
2. **Session type** — planning / vault / CPA prep / mixed (label honestly)
3. **Vault notes completed** — for each: retailer/topic name, key findings, architecture
   implications found, files produced
4. **Architecture decisions confirmed** — decisions that were already locked but are now
   evidence-based (e.g. `rewards_reduce_taxable_base` verified against invoice)
5. **Architecture decisions changed or reversed** — anything that was "locked" but proved
   wrong; must propagate to CONTEXT.md and Architecture Doc
6. **Open questions resolved** — which OQ number, what the resolution was
7. **New open questions added** — description of each
8. **New schema items needed** — new fields, tables, or migrations identified but not yet built
9. **CPA/external items** — questions sent, answers received, decisions pending
10. **Files produced** — vault notes, skills, docs created this session
11. **Next session goal** — one sentence

If the user says "just write it up" — infer everything from conversation history, then show
a confirmation summary before producing the prompt.

### Step 2 — Show confirmation summary

Before producing the prompt, show a plain-English summary:

```
Here's what I'm writing into the Claude Code prompt:

CONTEXT.md changes:
• [bullet per change]

SESSION_LOG.md changes:
• [one new session entry dated YYYY-MM-DD]
• [open questions closed: OQ#X]
• [new open questions: description]

Does this look right? Anything missing?
```

Only produce the prompt after the user confirms.

### Step 3 — Produce the Claude Code prompt

Generate a complete, ready-to-paste prompt for Claude Code. The prompt must:

1. Instruct Claude Code to read CONTEXT.md and SESSION_LOG.md from GitHub first
2. List every CONTEXT.md change as a specific named instruction (not vague)
3. Include the full SESSION_LOG.md entry as a block to append
4. Instruct Claude Code to write both files back
5. Ask Claude Code to confirm with line count and last-updated timestamp on each file

**Prompt template:**

```
Read the current CONTEXT.md and SESSION_LOG.md from the GitHub repo
(theroyalcrate/ResellOS), then apply the following updates and write both files back.

**CONTEXT.md updates:**

[Numbered list of specific changes. Each item names the section, the old state briefly,
and the exact new content. Be precise — vague instructions cause drift.]

**SESSION_LOG.md — append this entry:**

SESSION: [DATE] ([Session type])
TYPE: [Planning / Vault / CPA prep / Mixed]

COMPLETED:
- [bullet per completed item — specific, honest]

OPEN ITEMS CLOSED:
- [OQ number and resolution, or "none"]

NEW OPEN ITEMS:
- [description of each new question]

NEW SCHEMA ITEMS IDENTIFIED (not yet built):
- [field/table/migration needed, or "none"]

FILES PRODUCED THIS SESSION:
- [filename — description, save location]

NEXT SESSION ([next session ID if known]):
- [one sentence goal]

---

After writing both files, confirm the line count and last-updated timestamp on each
so I can verify the writes landed correctly.
```

### Step 4 — Present the prompt

Output the prompt in a code block so it's easy to copy. Add one line after:
"Paste this into Claude Code to update both files."

---

## RULES (apply to both session types)

**Never mark something done if it wasn't committed to GitHub.**
"Works locally" is not done. "We decided it" is not done — it's a pending decision.

**Never remove deferred items — move them.**
If something was deferred, record it in the session entry. Don't delete it.

**One next session at a time.**
The `next-callout` block (HTML) and the NEXT SESSION line (markdown prompt) always
contain exactly one session's goal.

**Architecture overrides accumulate — don't delete old ones.**
Each override is a record of what changed and when.

**Open questions: be conservative about closing them.**
Only close a question if it was definitively resolved with evidence or a committed decision.
"We talked about it" is not resolved. "CPA confirmed X" is resolved.

**Dates matter.**
Always record the actual date of the session, not an approximation.

**For vault sessions — flag architecture bugs found.**
Every vault session is a potential bug-finding exercise. If a session overturns a locked
decision (e.g. rewards_reduce_taxable_base), that must appear in CONTEXT.md changes AND
as a named override in the HTML session log when the next VS Code session runs.

---

## Reading the Log at Session Start

When the user starts a session and asks where they left off:

1. Read the `next-callout` block — this is the session goal
2. Read the most recent session card — this is what was last done
3. Check open questions for anything that needs a decision before work begins
4. Check the database stats — remind the user to verify live DB state before writing code

Deliver as a brief spoken briefing, not a list. Example:

> "Last session you finished the Kohl's vault note and confirmed `rewards_reduce_taxable_base = true`.
> The CONTEXT.md and SESSION_LOG.md were updated via Claude Code. Next up is S10: variable-earn
> schema for Kohl's, pin the earn cliff against the June 8th orders. Before you open VS Code,
> verify the Kohl's retailer_profiles row is seeded correctly in Supabase."

---

## Session Log Document Structure (Reference)

```
ResellOS___Session_Log.html  (VS Code sessions)
│
├── Header — metadata (last updated, next session, phase)
├── Start Here — Next Session (callout + pre-session checklist)
├── Current Sprint — status board (all sessions with pills)
├── Database — Current State (live stats)
├── Architecture Doc Corrections (override blocks)
├── Session History (expandable cards, newest first)
├── Open Questions (unresolved blockers and ADRs)
└── How to Use This Document (protocol reminder)

SESSION_LOG.md  (planning/vault sessions — updated via Claude Code prompt)
│
└── Chronological session entries, newest appended at bottom
    Each entry: date, type, completed, closed OQs, new OQs, schema items, files, next goal
```
