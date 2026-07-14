---
name: resell-os-session-start
description: >
  MANDATORY at the start of every ResellOS conversation, on every Claude surface — plain
  chat, Cowork, or Claude Code. Self-trigger this automatically as the very first action in
  any new conversation that touches ResellOS, even if the user hasn't said anything that
  matches a keyword — do not wait to be asked. Reads CLAUDE.md, CONTEXT.md, and
  SESSION_LOG.md live from the repo (theroyalcrate/ResellOS) before making any claim about
  what's built, what's decided, or what's next. Exists because this project previously kept
  a separate pasted copy of CONTEXT.md/SESSION_LOG.md inside the Claude Project, which went
  stale repeatedly and caused sessions to start from outdated context (confirmed 2026-06-21 —
  a session started from a CONTEXT.md snapshot two and a half weeks out of date). That pasted
  copy has been deleted. This repo is now the only copy, on purpose. Also governs the
  end-of-session update: SESSION_LOG.md (and CONTEXT.md if anything durable changed) must be
  updated before the session ends, on whichever surface the session happened on.
---

# ResellOS Session Start

## Why this skill exists

Three different Claude surfaces touch this project: plain chat (claude.ai), Cowork, and
Claude Code (VS Code). None of them automatically tell the others what happened. For a
while, the fix was a manually-pasted copy of CONTEXT.md and SESSION_LOG.md kept inside the
Claude Project so chat-Claude would start current. That copy drifted out of date repeatedly
— on 2026-06-21 a Cowork session started from a CONTEXT.md snapshot dated 2026-06-04, while
the real file in the repo had already moved on to 2026-06-18. A stale copy is worse than no
copy, because it looks authoritative.

The fix: there is no copy. This repo (`theroyalcrate/ResellOS`) is the only place
CLAUDE.md, CONTEXT.md, and SESSION_LOG.md live. Every session, on every surface, reads them
fresh.

## What to do at the START of every ResellOS session

Before answering any question, making any claim about what's built or decided, or starting
any work:

1. **Determine what access you have.**
   - If you have direct file access to the ResellOS repo folder (Cowork with the folder
     connected, or Claude Code): read the files directly.
   - If you only have GitHub access and no folder access (plain chat without Cowork):
     fetch the same files fresh from `theroyalcrate/ResellOS` via GitHub instead.
   - If you have neither: say so plainly and ask the user to connect one before proceeding
     on anything that depends on current ResellOS state.

2. **Read, in this order:**
   - `CLAUDE.md` — workspace identity, critical rules, folder structure
   - `CONTEXT.md` — business logic, architecture decisions, open questions
   - `SESSION_LOG.md` — current build state, what's next, what's deferred
   - `stages/CURRENT/CONTEXT.md` — if it exists, the specific job for this session

3. **Do not substitute memory for this read.** Even if you (or a prior turn in this same
   conversation) already read these files earlier in the session, re-check `SESSION_LOG.md`
   if meaningful time has passed or if the user references something you don't recognize —
   don't assume your earlier read is still the latest state, especially across long sessions
   where the user may be working in Claude Code in parallel.

4. **If something the user says conflicts with what these files say, trust the files** and
   flag the conflict — don't silently defer to a remembered version of events. If the user
   corrects something that turns out to be a real gap in these files, that's a sign the
   files need updating before the session ends (see below), not a sign to keep relying on
   conversation memory going forward.

## What to do at the END of every ResellOS session

1. Update `SESSION_LOG.md` with what happened: what was completed, what was decided, what
   was deferred, and what the next session should pick up. Be honest — "we discussed it" is
   not the same as "it's decided," and "decided" is not the same as "built and committed."
2. If anything durable changed — a new architecture decision, a corrected fact, a new open
   question, a resolved one — update `CONTEXT.md` too. Session narrative belongs in
   SESSION_LOG.md; durable facts and decisions belong in CONTEXT.md. Don't duplicate one
   into the other.
3. Whichever surface you're on, write the changes to the actual repo files (direct write if
   you have folder access; otherwise produce the exact GitHub commit or hand off the exact
   edits for Claude Code to apply — don't just describe the update in chat and leave the
   files untouched).
4. Never delete a deferred item — move it forward to the next session's open items instead.

## What this skill does NOT cover

- The Obsidian / ResellOS-Knowledge vault is a separate, slower-moving system for distilled
  business-logic patterns (retailer notes, edge cases). It is not part of this read/write
  loop and should stay that way — see CONTEXT.md's "Document Hierarchy" section.
- This skill doesn't replace `resell-os-session-logger` (which handles the detailed
  write-up format) or `resell-os-environment-check` (which verifies specific claims about
  where something lives). Use those for their specific jobs; use this skill for the
  always-on start/end ritual that wraps every session regardless of what else happens in it.

## Setup note (for Josh, not for Claude to act on)

For this skill to actually load automatically in plain chat and Cowork, it needs to be
added as an enabled skill in Settings → Capabilities — a skill can't register itself from
inside a running session. Claude Code doesn't need this step: it already auto-loads
CLAUDE.md on every session, and CLAUDE.md already states the same read-order rule this
skill describes.
