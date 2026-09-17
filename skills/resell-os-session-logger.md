---
name: resell-os-session-logger
description: >
  Maintains ResellOS's two living docs — SESSION_LOG.md and CONTEXT.md, both plain markdown
  in the repo root — across build sessions (Claude Code, Cowork) and planning/vault sessions
  (plain chat-Claude). Use this skill whenever the user says "update the session log", "log
  this session", "wrap up the session", "what should I add to the log", "close out the
  session", "generate the Claude Code prompt", or "write up the session". Also trigger at the
  START of any session when the user says "read the session log", "what did we do last
  time", or "where did we leave off" — in that case, READ the docs and summarize; don't
  update yet. Two protocols, chosen by which surface the current session can write from, not
  by what kind of work was done: (1) a surface with direct local-file/GitHub write access
  (Claude Code, Cowork) edits SESSION_LOG.md and CONTEXT.md directly. (2) a read-only surface
  (plain chat-Claude on claude.ai) produces a ready-to-paste Claude Code prompt instead. The
  skill detects which applies from context. Never ask the user which — infer it.
---

# ResellOS Session Logger

Maintains `SESSION_LOG.md` and `CONTEXT.md` — both plain markdown files in the repo root —
so every session starts with accurate context and ends with an honest record of what was
found, what was fixed, what was decided, and what comes next.

**There is no HTML session log.** An older version of this skill described updating a
`ResellOS___Session_Log.html` file with named zones (`header-meta`, `session-card`,
`next-callout`, etc.). That file does not exist in this repo — the project moved to plain
markdown at some point and this skill was never updated to match, which meant a 2026-09-17
Claude Code session had to ignore its instructions entirely and reverse-engineer the current
convention from the existing 2026-09-14/09-15 `SESSION_LOG.md` entries instead. This version
replaces those instructions with the real, current process. If you ever find yourself being
told to write an HTML file for this project, stop and re-read this skill — the instruction is
stale.

**Where things live (repo root, `theroyalcrate/ResellOS`):**
- `SESSION_LOG.md` — single source of truth for build state, updated at the end of every
  session. Read first, before opening VS Code.
- `CONTEXT.md` — durable project orientation: architecture decisions, business logic, known
  gaps, open questions. Read second.
- `references/*.md` — reusable techniques or designs worth documenting on their own (e.g. a
  detection method, a parser spec) that don't belong inside either log.
- `ADR-XXX-*.md` (repo root) — standalone architecture decision records for a single big
  decision, written when a change is significant enough to warrant its own document rather
  than a paragraph in CONTEXT.md.

There is no project-knowledge paste-in anymore (deleted 2026-06-21 per SESSION_LOG.md's
"Document home & sync rule") — this repo is the only copy, always.

---

## When to READ vs UPDATE

**READ mode** — triggered by "where did we leave off", "what did we do last time", "catch me
up", or the start of any session before touching code.

→ Read SESSION_LOG.md's "Start Here — Next Session" section (the dated pointer paragraphs,
newest first) and the most recent "Session History" card. Skim CONTEXT.md's "Open Questions"
for anything that needs a decision before work begins. Summarize as a brief spoken briefing —
don't dump the raw text. Do NOT update anything yet.

**UPDATE mode** — triggered by "update the session log", "log this session", "wrap up" /
"close out the session", "generate the Claude Code prompt", "write up the session", or simply
finishing a session's work.

→ Detect which protocol applies (below), then follow it.

---

## WHICH PROTOCOL APPLIES

Decide by **write access this session actually has**, not by what kind of work was done —
per CLAUDE.md's "Tool Access Reality" table:

- **Claude Code or Cowork** — both can read/write the local repo directly and commit to
  GitHub (Cowork can also reach Supabase directly). → **DIRECT-WRITE PROTOCOL.**
- **Plain chat-Claude (claude.ai)** — can read GitHub via MCP but cannot write local files or
  run code. This is typically where pure planning/vault/CPA-prep sessions with no code
  changes happen. → **PROMPT-HANDOFF PROTOCOL.**

If a session had both planning work and a quick code change (e.g. vault work plus a schema
fix committed from Claude Code), just follow the DIRECT-WRITE PROTOCOL once, covering
everything in one pass — don't run both protocols separately.

---

## DIRECT-WRITE PROTOCOL (Claude Code / Cowork)

### Step 1 — Gather what happened

From conversation context (or by asking, if genuinely unclear):

1. What was found, built, fixed, or decided — specific and honest, not "worked on X"
2. What's still open or deferred — never drop these, carry them forward
3. Any commit(s) made — exact message and hash, if committed
4. Whether any architecture decision changed, or a new durable gap/limitation was found
5. One-sentence next-session goal

### Step 2 — Update SESSION_LOG.md

Real current structure, top to bottom — update whichever of these actually changed:

| Section | What it holds | Update when |
|---|---|---|
| Header table (`Last Updated`, `Next Session`) | Current date; a detailed paragraph on the standing next priority | Every session |
| `## Start Here — Next Session` | A stack of dated blockquote pointers, newest first, each starting `> **YYYY-MM-DD update — ...`, often explicitly marking older paragraphs below it as stale | Every session — add one new pointer at the top; never delete the older ones, they're the stale-marking trail |
| `## Current Sprint` / status-board table | One terse row per session: `\| Cowork/Claude Code YYYY-MM-DD \| one-paragraph summary \| ✓ Complete \|` | Every session — add a new row |
| `## Database — Current State` | Bulleted live counts (tables, orders, gift cards, etc.) | Only when a bullet's number is now stale — update the number and note what changed and why, don't just overwrite silently |
| `## Session History` | Full narrative cards, newest first: `### Cowork/Claude Code YYYY-MM-DD — Title ✓ Done — YYYY-MM-DD` followed by prose paragraphs with **bold lead-ins** per topic | Every session — add one new card at the top of this section (right after the `## Session History` heading, before the previous newest card) |
| `## Architecture Doc Corrections` | `OVERRIDE NNN` blocks — only when a previously-documented decision is now known to be wrong | Rare — only on a real reversal |
| `## Known Bugs / Build TODOs (session-level)` | Small, non-architecture bugs/TODOs only | Rare — see the note already in that section: architecture-level items go to CONTEXT.md instead (consolidated 2026-09-06) |

**Session History card — real template** (see the 2026-09-17 entry as a worked example):

```markdown
### Cowork 2026-09-17 — Found & Fixed: <short title> ✓ Done — 2026-09-17

<One-paragraph lead-in: what triggered the investigation.>

**The bug/finding.** <What's actually wrong or true, and why nothing existing caught it.>

**<Technique/method>, if one was used.** <How it was detected, verified — including any
false positives ruled out, since honesty about what didn't turn out to be a bug matters as
much as what did.>

**<Fixes/decisions made> (be specific — order numbers, file names, commit hashes, before →
after values).**

**What's still open.** <What wasn't done this session — no code fix, no automation, extending
to other cases, etc. Point at the CONTEXT.md open question if one was added.>
```

Match the prose style already in the file — dense paragraphs with **bold** lead-ins per
sub-topic, not bullet-only telegraphic notes. Specific numbers (order IDs, dollar amounts,
row counts) over vague summaries.

### Step 3 — Decide whether CONTEXT.md also needs an update

This is the judgment call this skill most needs to get right. Ask: **will this still matter
to someone reading CONTEXT.md six months from now, without today's conversation for
context?**

**Goes in CONTEXT.md** (durable — survives independent of any one session's narrative):
- A new architecture decision, or a locked decision that got confirmed/reversed → add to
  `## Architecture Decisions Already Made`, or write a full `ADR-XXX-*.md` if it's big enough
  to need its own rationale/consequences document.
- A newly-discovered **known gap or limitation** in a tool/agent that isn't fixed yet and
  would otherwise silently recur → add a new numbered item under `## Open Questions
  (Unresolved)`. Follow the file's own convention: number it one past the last existing item,
  write the finding in full (context, what was found, what was fixed vs. still open, pointers
  to any reference doc or session entry with more detail). When a question is later resolved,
  don't delete it — strike it (`~~...~~`) and prepend `✅ RESOLVED YYYY-MM-DD`, keeping the
  original text below for context (see item 21 as a worked example of this pattern).
- A retailer-specific or domain business-logic rule that will apply again later → `## Known
  Edge Cases Already Designed For`.
- A reusable technique or method (a detection script, a parsing approach) that's likely to be
  reused or re-run later → its own file under `references/`, cross-linked from wherever in
  CONTEXT.md/SESSION_LOG.md is relevant, rather than buried only in a session's prose.

**Stays in SESSION_LOG.md only** (session-specific, narrative, or still in flux):
- What was investigated and found NOT to be a bug (false positives, confirmed-fine cases) —
  useful history, not a durable fact about the system.
- In-progress work, partial fixes, "still needs testing" items.
- The blow-by-blow of how something was found or debugged, once the durable takeaway has
  been distilled into a CONTEXT.md entry.
- Anything that's really just "next session should do X" — that belongs in the header table's
  `Next Session` cell and/or a `Start Here` pointer, not CONTEXT.md, unless it also represents
  a standing gap worth documenting independent of the to-do (in which case it may be both).

If in doubt, write it in SESSION_LOG.md fully either way (that file is guaranteed to get
read), and only promote the durable kernel of it into CONTEXT.md.

### Step 4 — Confirm before writing (light touch)

For anything with real ambiguity (unclear scope, an architecture-level call), summarize the
planned SESSION_LOG.md/CONTEXT.md changes in 2-4 bullets and check before writing. Skip this
when the session's own request already specifies the content precisely — documentation edits
are easy to review afterward via a normal diff, so this isn't a hard gate the way it would be
for code.

### Step 5 — Write the files

Edit `SESSION_LOG.md` and `CONTEXT.md` directly in the repo root.

### Step 6 — Committing is a separate decision, not part of this skill

Writing these files is a file edit, not a commit. **Do not `git commit`/`push` unless the
user explicitly asks**, even though CLAUDE.md's "When a Session Ends" ritual describes
committing the log update as one of the closing steps — that ritual describes what *should*
eventually happen at the end of a session, not a standing authorization to commit without
being asked. Default to: write the files, then tell the user what changed and ask whether
they want it committed. (This distinction is exactly why this rewrite exists — a prior
session got asked to update the log with no accompanying "commit and push" instruction and
should not assume one.)

### Step 7 — Close out

Tell the user, in plain language:
- Which files changed and what was added (a short list, not the full diff)
- The next-session pointer, in one sentence
- Whether they want it committed (per Step 6)

---

## PROMPT-HANDOFF PROTOCOL (plain chat-Claude, no local/GitHub write access)

Used when the current session can't write files or push to GitHub itself — typically a
planning/vault/CPA-prep session on claude.ai. Output is a ready-to-paste prompt for a
direct-write surface (Claude Code or Cowork) to execute Steps 2-5 above, not a file write.

### Step 1 — Gather what happened

Same information as the direct-write protocol's Step 1, plus: any vault notes produced, any
CPA/external question sent or answered, any new open question or schema item identified.

### Step 2 — Show a confirmation summary

```
Here's what I'll put in the Claude Code prompt:

CONTEXT.md changes:
• [bullet per change, or "none"]

SESSION_LOG.md changes:
• One new Session History entry dated YYYY-MM-DD
• [open questions closed / added, or "none"]

Does this look right? Anything missing?
```

Only produce the prompt after the user confirms.

### Step 3 — Produce the prompt

The prompt must:
1. Instruct Claude Code to read the current SESSION_LOG.md and CONTEXT.md from the repo
   (`theroyalcrate/ResellOS`) first — never assume their prior state
2. List every CONTEXT.md change as a specific, named instruction (section, old state briefly,
   exact new content) — vague instructions cause drift
3. Include a complete Session History card (using the template above) to add to SESSION_LOG.md
4. Follow the same "what belongs where" guidance from the direct-write protocol's Step 3
5. Explicitly say: write the files, then report back and ask before committing — don't commit
   automatically
6. Ask for confirmation (line count / a short excerpt) once done, so the handoff can be
   verified

### Step 4 — Present the prompt

Output it in a code block, ready to copy. Add a line after: "Paste this into Claude Code (or
hand it to a Cowork session) to apply these updates."

---

## RULES (apply to both protocols)

**Never mark something done if it isn't actually committed/verified.** "Works locally" or
"wrote the code" is not the same as "committed" — say which one is true.

**Never remove deferred items — carry them forward.** If something was deferred, it stays
visible in the next relevant entry until it's actually resolved.

**One next-session goal at a time.** The header table's `Next Session` cell and the top
`Start Here` pointer should each name one clear next priority, even if the surrounding prose
is long.

**Architecture overrides and resolved-open-questions accumulate — never delete history.**
Strike through and mark resolved; don't erase.

**Be conservative about marking an Open Question resolved.** "We talked about it" isn't
resolution. "Confirmed via X" or "built and verified" is.

**Dates matter — always record the actual session date**, not today's date if they differ
(e.g. a session logged after the fact).

**Every session is a potential bug-finding session, not just build sessions.** If a planning
or data-review session overturns a locked decision or finds a real gap, that belongs in
CONTEXT.md via the Prompt-Handoff protocol just as much as a build session would via the
direct-write one.

---

## Reading the log at session start (example briefing)

> "Last session (2026-09-17) found a real bug: `agent_1e_pdf_backfill` can silently drop an
> entire shipment on a multi-box order, and no existing validator catches it. Six orders were
> corrected via direct SQL, one was rebuilt from scratch. No code was fixed — that's still
> open, tracked as CONTEXT.md Open Question #22. Standing next priority underneath that:
> `order_confirm_review_app.py` is built and safe to run against the 665-order
> `pending_review` backlog, just not run against production yet."

Pull that from: the newest `Start Here` pointer, the newest `Session History` card, and a scan
of CONTEXT.md's `Open Questions` for anything needing a decision before new work starts.

---

## Document structure (reference)

```
SESSION_LOG.md  (repo root, markdown)
│
├── Header table — Last Updated / Sessions Complete / Next Session / Phase / GitHub
├── Start Here — Next Session (stacked dated pointers, newest first)
├── Current Sprint — status-board table (one terse row per session)
├── Database — Current State (live count bullets)
├── Session History (full narrative cards, newest first)
├── Architecture Doc Corrections (OVERRIDE blocks, rare)
├── Known Bugs / Build TODOs (session-level only — architecture items live in CONTEXT.md)
└── How to Use This Document

CONTEXT.md  (repo root, markdown)
│
├── What ResellOS Is / tech stack / build state
├── Key Business Logic
├── Known Edge Cases Already Designed For
├── Planned Future Systems (Not Yet Built)
├── Architecture Decisions Already Made (Do Not Reverse Without Flagging)
├── Open Questions (Unresolved) — numbered, strike + ✅ RESOLVED when closed
└── Document Hierarchy — What Supersedes What

references/*.md — standalone reusable techniques/specs, cross-linked from the above
ADR-XXX-*.md — standalone decision records for single large decisions
```
