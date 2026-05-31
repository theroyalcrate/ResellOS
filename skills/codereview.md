---
name: resell-os-code-review
description: Reviews ResellOS Python code written or modified during a build session. Checks for logic errors, edge cases, overly complex code, inconsistent naming, and anything fragile that could cause problems as data accumulates. Use this skill whenever the user says "review the code", "check for errors", "clean up the code", "audit this session's work", "is the code solid?", or at the end of any ResellOS build session before committing. Also trigger when the user asks Claude Code to review a specific agent file by name. Always run this before a commit if the user asks.
---

# ResellOS Code Review Skill

A structured code review process for ResellOS build sessions. The goal is to catch problems before they compound — logic errors are cheap to fix now and expensive to fix after real data accumulates on top of them.

## When to Run

- End of every build session before committing
- After any agent is modified mid-session to fix a bug
- When something "worked" but felt fragile
- Any time the user explicitly asks for a review

---

## Review Process

### Step 1 — Identify Scope

Determine which files were written or modified this session. If not explicitly told, check git status:

```bash
git diff --name-only
```

Focus the review on those files. Don't review unchanged files unless the user asks.

---

### Step 2 — Run the Four-Pass Review

For each file in scope, run these four passes in order:

#### Pass 1 — Logic Correctness
Check that the code does what it's supposed to do:
- Does every calculation match the business rule? (e.g. stamp calculation: floor(subtotal / 10) × multiplier)
- Are conditional branches correct? (e.g. Insider points only for LEGO retailer, not all retailers)
- Are database writes happening in the right order? (order before shipment before line_items)
- Does rollback logic actually undo everything if a write fails partway through?
- Are foreign key relationships being respected?

#### Pass 2 — Edge Cases
Look for inputs that could break the code silently:
- What happens if a field is None or empty string?
- What if the user enters a negative number where a positive is expected?
- What if a Supabase query returns zero rows — does the code handle that gracefully?
- What if the user hits Enter without typing anything at a prompt?
- What if a retailer name is entered with different capitalization than expected?
- What if a duplicate record is attempted — does idempotency hold?

#### Pass 3 — Code Quality
Look for unnecessary complexity:
- Any repeated logic that should be a function?
- Any hardcoded values that should be constants or config?
- Variable names that are unclear or misleading?
- Functions doing more than one job that should be split?
- Dead code — anything imported but not used, or unreachable branches?
- Overly long functions (more than ~50 lines usually signals it should be split)

#### Pass 4 — ResellOS-Specific Rules
Check against known ResellOS conventions:
- Retailer gating: Insider points only for `retailer == 'LEGO'`, Barnes stamps only for `retailer == 'Barnes'`
- Payment method: must be one of `gift_card | credit_card | mixed | rewards | cash`
- All DB writes must go through `db_writer.py` — no direct Supabase calls in agent files
- Every write that touches multiple tables must have rollback logic
- Confirm-before-write prompt must appear before ANY database write
- Idempotency check must run before creating any new record
- `discount_pct` on gift cards must be calculated as `round((face_value - price_paid) / face_value * 100, 2)`
- Status fields must use the defined enum values — no freeform strings

---

### Step 3 — Prioritize and Report

After all four passes, produce a report in this format:

```
CODE REVIEW — [filename] — [date]
========================================

CRITICAL (must fix before commit)
----------------------------------
[Issue] — [file, line if known] — [what's wrong and suggested fix]

MODERATE (fix soon, won't block commit)
----------------------------------------
[Issue] — [suggested fix]

MINOR (clean up when convenient)
----------------------------------
[Issue] — [suggested fix]

NO ISSUES FOUND
----------------
[List passes that were clean]

RECOMMENDATION: [Commit clean / Fix before commit / Needs significant rework]
```

If nothing is found: say so clearly. Don't manufacture issues.

---

### Step 4 — Fix or Defer

For each CRITICAL issue:
- Offer to fix it immediately in Claude Code
- Show the specific line change needed
- Re-run the affected pass after fixing to confirm clean

For MODERATE and MINOR issues:
- Ask the user whether to fix now or defer to a cleanup session
- If deferred, log them as a note in the session log under "Known Issues"

---

## Prompts to Use in Claude Code

### Full session review (end of session):
```
Review all files modified this session using git diff --name-only. For each file run a four-pass review: (1) logic correctness against the business rules we built today, (2) edge cases that could cause silent failures, (3) code quality and unnecessary complexity, (4) ResellOS conventions — retailer gating, confirm-before-write, rollback logic, idempotency. Report findings as CRITICAL / MODERATE / MINOR. Fix any CRITICAL issues before the commit.
```

### Single file review:
```
Review [filename] for logic errors, edge cases, code quality, and ResellOS conventions. Report findings as CRITICAL / MODERATE / MINOR with specific line references where possible.
```

### Quick pre-commit check:
```
Quick pre-commit review — any CRITICAL issues in the files staged for this commit? If clean, confirm and I'll push.
```

---

## ResellOS Business Rules Reference

Keep these in mind during Pass 1 — these are the rules the code must implement correctly:

| Rule | Detail |
|---|---|
| Insider points | LEGO only. 6.5 pts per $1 eligible spend × multiplier |
| Barnes stamps | Barnes only. floor(subtotal / 10) × multiplier (1/2/3) |
| Gift card discount | (face_value - price_paid) / face_value × 100, rounded to 2dp |
| Reconciliation | 'reconciled' if invoice total matches order total ±$0.01, else 'discrepancy' |
| Payment method | gift_card / credit_card / mixed / rewards / cash — no other values |
| Split payments | payment_legs list captures each leg with method + amount |
| Rollback | If any write in a multi-table sequence fails, undo all prior writes in that sequence |
| Idempotency | Always check for existing record before writing. Skip with message if found. |
| GWP line items | unit_price = 0.00, is_gwp = True, msrp = retail price |
