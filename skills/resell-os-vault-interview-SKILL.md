---
name: resell-os-vault-interview
description: >
  Conducts structured interview sessions to build retailer knowledge notes and LEGO investing reference notes for the ResellOS Obsidian knowledge vault. Use this skill whenever the user says "let's build the vault note for [retailer]", "interview me on [retailer]", "let's do a vault session", "start the Macy's note", "let's work on the Obsidian vault", or any phrase indicating they want to document a retailer's mechanics, tax behavior, reward structure, or LEGO investing knowledge. Also trigger when building any reference knowledge for the vault — not just retailer notes. CRITICAL rule locked in from prior sessions: ask ALL questions and gather ALL answers BEFORE writing a single line of markdown. Never scaffold first. Treat every vault session as a bug-hunting exercise — invoice analysis routinely surfaces incorrect architecture assumptions before they reach the database.
---

# ResellOS Vault Interview Skill

Builds knowledge notes for the ResellOS Obsidian vault through structured interview. The vault captures retailer mechanics, tax behavior, reward structures, edge cases, and LEGO investing reference knowledge that informs the ResellOS schema and cost basis engine.

## The One Non-Negotiable Rule

**Ask ALL questions. Receive ALL answers. Then write markdown.**

Never scaffold first. Never write a section while questions remain open. This rule exists because invoice analysis during these sessions consistently surfaces bugs and incorrect architecture assumptions before they reach the database. The Kohl's session proved `rewards_reduce_taxable_base` was wrong for a "locked" decision. Every vault session is a bug-hunting exercise dressed as documentation.

---

## Session Types

### Type 1 — Retailer Note

Documents a retailer's full economic mechanics for ResellOS: reward structure, tax behavior, shipping thresholds, pickup support, gift card behavior, GWP behavior, cancellation behavior, email parsing patterns, and schema implications.

### Type 2 — LEGO Investing Reference

Documents investing knowledge: retirement signals, price history patterns, set category behavior, community sourcing patterns, velocity indicators, storage strategy, etc.

### Type 3 — Business Logic Reference

Documents cross-cutting patterns: cost basis edge cases, cashback portal behavior, tax recovery mechanics, etc.

---

## Retailer Note Interview Protocol

### Step 1 — Pre-session prep (do this silently before asking anything)

Read the project CONTEXT.md to check:
- What is already known about this retailer (Architecture Decisions table, Retailers section)
- What open questions exist for this retailer (Open Questions section)
- What the prior note flagged for follow-up (if a partial note already exists)
- What assumptions are "locked" that this session might overturn

Flag anything that looks like an assumption baked in without invoice evidence.

### Step 2 — Gather invoices

Ask the user to have real invoices in front of them before proceeding. The interview is grounded in real transactions — never in memory or community hearsay alone.

```
Before we start — pull up your [Retailer] invoices/order confirmations. 
We want real numbers to verify against, not just what you remember. 
How many orders do you have to work with?
```

Label every answer with its evidence basis:
- ✅ verified — confirmed against a real invoice
- `[community]` — community-sourced, not personally verified
- `[personal]` — personal practice, not generalizable rule
- ❓ — open / uncertain

### Step 3 — Core interview questions

Ask these in batches, not one at a time. Group related questions together so the user can answer in a flow. Wait for all answers before moving to the next batch.

**Batch A — Reward structure**
- What reward program does this retailer use? What's it called?
- Is the earn rate fixed or variable? Have you observed different rates on real orders?
- What is the earn base — pre-tax, post-coupon, post-discount, post-rewards-redemption?
- Are rewards earned as points, currency, or something else? When do they become spendable?
- Is there a threshold or cliff (earn only above $X spend)?
- Do gift card purchases earn rewards? (Critical — Macy's = no, Kohl's = yes)
- Is there a store credit card that changes the earn rate?

**Batch B — Tax behavior (most likely to find bugs)**
- Walk through a real order: what was the subtotal, what discounts were applied, what was the tax, what was the total?
- Do rewards / promotional currency / coupons apply BEFORE or AFTER tax is calculated?
- Test: take the post-discount merchandise net and multiply by your local WA tax rate (~10.5%). Does that match the invoice tax exactly?
- If they don't match: what's the taxable base the retailer is actually using?

> This batch is where architecture bugs surface. The Kohl's session found that Kohl's Cash is pre-tax (reduces taxable base), overturning a "locked" decision. Do the math against a real invoice — don't trust the assumption.

**Batch C — Shipping & pickup**
- Free shipping threshold? What is the net evaluated against (gross? post-discount? post-rewards?)?
- Does this retailer support in-store pickup?
- Is there a pickup bonus? Does it stack across multiple pickup orders in one session?
- Has shipping cost ever been triggered unexpectedly by a discount reducing the net below threshold?

**Batch D — Gift cards**
- Does this retailer accept gift cards?
- Can gift cards be purchased at a discount elsewhere (discount gift card sites)?
- Do gift card purchases earn loyalty rewards? (This distinguishes Kohl's vs Macy's behavior)
- Does gift card redemption affect tax calculation?

**Batch E — GWP (Gift With Purchase)**
- Has this retailer run LEGO GWP promotions?
- If yes: what was the qualifying threshold? Was it evaluated pre- or post-discount?
- Was the GWP shipped automatically or required a claim?
- Did cancellations affect GWP eligibility?

**Batch F — Cancellation behavior**
- What happens to earned rewards when an order is cancelled?
- What happens to gift card balances used on a cancelled order? (Are they auto-refunded or require action?)
- Is there a threshold cliff where cancellation eliminates rewards entirely?

**Batch G — Cashback portal**
- Does portal cashback (Rakuten, RetailMeNot, etc.) work at this retailer?
- What rate is typical? Is it worth chasing or treated as a bonus when it lands?
- Any known portal restrictions or exclusions?

**Batch H — Email / order confirmation structure**
- What does an order confirmation email look like? What's in the subject line?
- What does a shipping confirmation look like? When does the order number first appear?
- What does an invoice look like? Key fields: line items, SKUs, discounts applied, tax, rewards earned.
- How are payment methods labeled? (Especially rewards/promo currency — the label is the classifier for the email agent)
- What are the retailer's internal SKU/product identifier fields vs the public product number (e.g., LEGO set number)?

**Batch I — `buy_reason` interaction**
- Is this a retailer where `promo_expiration` intent commonly applies? (i.e., buying to burn expiring promotional currency)
- Is this a retailer where `opportunistic` buys are common (clearance, sale-first discovery)?

### Step 4 — Architecture implication scan

Before writing anything, explicitly check:

1. **`rewards_reduce_taxable_base`** — what does the invoice math say? Never assume false without checking.
2. **Read vs compute** — can rewards be computed from a rate, or must they be read from the invoice? (Variable rates = read-don't-compute)
3. **Earn cliff** — is there a threshold where behavior changes sharply?
4. **Schema gaps** — does anything in these answers require a new field, table, or migration?
5. **Conflicts with current architecture** — does anything contradict a locked decision in CONTEXT.md?

Surface any conflicts explicitly to the user before writing the note. These are bugs found before they hit the database.

### Step 5 — Write the note

Only after all questions are answered and architecture implications are scanned. Use the structure below.

---

## Retailer Note Structure

```markdown
---
type: retailer-note
retailer: "[Full Name]"
retailer_key: "[key matching retailer_profiles table]"
sharing: generalizable
status: partial | complete
reward_mechanic: "[short description]"
rewards_reduce_taxable_base: true | false
supports_pickup: true | false
free_shipping_threshold: [number or null]
last_reviewed: YYYY-MM-DD
related:
  - "[[other-retailer]]"
aliases:
  - "[domain.com]"
  - "[alternate name]"
---

## What this is
[2-3 sentence orientation: what kind of channel, what defines its economics, what makes it distinct]

> [!note] Verification basis
> [List real order numbers used, date range, and what remains unverified]

---

## Reward mechanic
[One subsection per reward type. Mark each claim ✅ verified / [community] / [personal] / ❓]

> [!important] Schema rule — read, don't compute (if applicable)
> [Explain if rates are variable and must be read from invoice]

---

## Tax behavior
[Document what the taxable base actually is. Show the invoice math. Flag rewards_reduce_taxable_base value and why.]

> [!warning] (if this overturns a locked decision)

---

## Free shipping
[Threshold, what net it's evaluated against, interaction with discounts/rewards]

---

## Cancellation behavior
[Per-reward-type behavior. Gift card refund process. Any cliff risks.]

---

## `buy_reason` interaction
[Which intent values commonly apply at this retailer and why]

---

## Gift cards
[Earn behavior, purchase availability, redemption mechanics]

---

## Membership / card tiers
[Tiers, card options, rate changes]

---

## Cashback / portal interaction
[Portal compatibility, typical rates, personal practice]

---

## GWP behavior
[If applicable. Otherwise: "No GWP at [Retailer] — capture an example here only if that changes."]

---

## Order confirmation signature — for the email agent
[Key parsing structure: subject line patterns, payment method label taxonomy, earnings block location, SKU vs public product number]

Critical (all email agents): enrich/match existing orders, never duplicate line items.

---

## Edge cases & observed behavior
[Surprises found during invoice analysis. Split shipments, partial fulfillment states, etc.]

---

## Open questions / to verify
- [ ] [Unresolved items]
- [x] [Verified items]

---

## Schema / Claude Code notes (cross-doc — do not lose)
[Explicit propagation instructions: what needs to change in retailer_profiles, cost basis engine, CONTEXT.md, Architecture Doc]
[Migration needed? New fields? New tables?]
[Sequencing: this note → schema → seed profile → verify → email agent]

---

## Changelog
- **YYYY-MM-DD** — [What was documented, what was corrected, what was left open]
```

---

## Security Markers

Every item in the note should be tagged:
- `[generalizable]` — safe to share; describes the retailer's public mechanics
- `[personal]` — personal operational practice (rates observed, accounts held, purchasing patterns)
- `[community]` — community-sourced, not personally verified

The YAML frontmatter `sharing: generalizable` applies to the note as a whole for the public-facing version. Personal items stay in the full vault copy.

---

## Cross-Retailer Consistency Rules

When writing a new retailer note, explicitly compare to prior notes:
- **Gift card earn behavior** — Kohl's (earns normally) vs Macy's (earns 0 points) is a documented contrast. Any new retailer: determine which camp.
- **`rewards_reduce_taxable_base`** — never assume false. Always verify with invoice math.
- **Read vs compute** — if rate varies by promo event, it must be read from invoice, not computed. Same rule as Kohl's Rewards and Barnes stamps.
- **Cancellation cliff risk** — flag any retailer with a threshold mechanic (Kohl's Cash, Walmart Business 2%) for cancellation cliff warnings.

---

## LEGO Investing Reference Note Protocol

For Type 2 (investing knowledge) sessions, the interview is more open-ended:

1. Ask what topic the user wants to capture
2. Ask what the current practice or belief is
3. Ask what evidence (real data, community consensus, personal observation) supports it
4. Ask what exceptions or edge cases they've encountered
5. Ask what the ResellOS system needs to know to act on this knowledge

Structure: use the same verification-basis approach — mark everything ✅ / `[community]` / `[personal]` / ❓.

---

## Session Close Protocol

At the end of every vault session:

1. Surface any architecture bugs found — explicitly name the conflict, the old assumption, and what the invoice evidence says
2. List schema changes needed (new fields, migrations, profile record updates)
3. List CONTEXT.md / Architecture Doc propagation needed
4. List open questions to carry forward
5. Confirm note is saved to the vault at the correct path: `Areas/retailers/[retailer-key].md` or `Areas/business-logic/[topic].md`
6. Remind user to update CONTEXT.md and SESSION_LOG.md with any architectural corrections found
