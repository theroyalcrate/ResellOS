# ADR-018: Per-Retailer Tax Behavior Flag — Kohl's Cash Is a Pre-Tax Discount

**Status:** Accepted
**Date:** 2026-06-05
**Deciders:** Josh (owner / builder)
**Supersedes:** Prior framing in CONTEXT.md and SESSION_LOG.md that treated Kohl's Cash as post-tax tender (same category as Macy's Star Money)

---

## Context

The original retailer rewards model assumed that promotional cash (Kohl's Cash) and coupons function as post-tax tender — i.e., they are applied after the retailer computes tax on the full merchandise subtotal. This assumption was never verified against a real invoice. It was bucketed with Macy's Star Money as a shared assumption.

During the Kohl's knowledge vault session (2026-06-05), five real Kohl's invoices were reviewed in detail:

- **Order 6714029349 (Jun 2026):** Sales tax $10.50 ÷ $99.14 subtotal (post–$10 Kohl's Cash) ≈ 10.6%. Tax was computed on the post-Kohl's-Cash net — not the gross merchandise amount.
- **Order 6702180930 (Mar 2026):** $63.96 merchandise fully covered by Kohl's Cash + TOYS10 coupon → taxable merchandise base = $0. Sales tax was $0.94, which is ~10.5% of the $8.95 shipping charge only. If Kohl's Cash were post-tax tender, ~$6.70 in merchandise tax would have appeared. It did not.

This establishes two independent confirmation paths that Kohl's Cash and coupons reduce the taxable base — they are pre-tax discounts, not post-tax tender.

---

## Decision

**Introduce a per-retailer `rewards_reduce_taxable_base` boolean flag on `retailer_profiles`.**

- Default: `false` — preserves existing semantics for all other retailers where this has not been verified.
- Set from real invoice evidence only — never assumed.
- `true` means: promo-cash and coupons are pre-tax discounts; the taxable base is the post-discount merchandise net; use actual invoice tax, never recompute it.

**Kohl's profile seeded with `rewards_reduce_taxable_base = true`** (Migration 011, 2026-06-05).

The cost basis engine (agent_08_cost_basis.py) reads `order.tax_paid` — the actual invoice dollar amount entered at order entry time. It does not recompute tax. The engine is correct as written. The flag informs documentation, future analytics, and any code that might otherwise attempt a tax estimate.

---

## What Is Not Changing

- The cost basis formula is unchanged. It already uses actual invoice tax.
- No existing order's `true_cost_basis` is affected. No recompute or backfill required (confirmed: no path in any .py file multiplies a rate by a taxable base or recomputes tax_paid).
- No change to any other retailer. Default `false` is safe.

---

## Options Considered

### Option A: Correct Kohl's only — no generalizable flag

Add a Kohl's-specific boolean directly to the Kohl's profile, or document it as a note.

**Rejected** — other retailers will eventually need the same verification pass (Macy's is the immediate example). A per-retailer flag makes the pattern explicit and queryable; a prose note does not.

### Option B: Rename the flag to `coupons_are_pretax`

More literal, but less useful — "promo-cash" and "coupons" are both covered, and the existing term `rewards_reduce_taxable_base` matches the intended scope (all order-level promotional discounts applied by the retailer before computing tax).

**Rejected** — `rewards_reduce_taxable_base` is clearer in context.

### Option C (chosen): Per-retailer flag, default false, set from evidence

Generalizable, conservative by default, evidence-driven. The flag's value is a claim about how the retailer's systems work — it must be set from a real invoice, not guessed.

---

## Consequences

### What becomes clearer

- Future devs cannot accidentally reintroduce a tax-recompute by reading `loyalty_earn_rate` (now NULL for Kohl's) and multiplying. The flag + NULL rate + loyalty_notes together make the read-don't-compute rule explicit.
- Macy's Star Money now has an open verification task rather than a silent wrong assumption.
- Future retailer onboarding has a clear signal: leave `rewards_reduce_taxable_base = false` until a real invoice proves otherwise.

### What needs follow-up

- **Macy's Star Money** — was on the same false assumption. Do not change Macy's flag without a real Macy's invoice. Open question recorded in CONTEXT.md.
- **Kohl's Cash earn cliff** — exact sub-$50 boundary (post-coupon) remains open. Pin against June 8th orders.
- **agent_08_cost_basis.py naming** — file is named after session S08 but conceptual agent numbering calls the cost basis engine "Agent 04" (Product Catalog = Agent 08). Collision risk when Product Catalog is built. Open question recorded in CONTEXT.md.

---

## Migration

**Migration 011** (`migrations/011_retailer_profiles_tax_behavior.sql`) — applied 2026-06-05:

```sql
ALTER TABLE retailer_profiles
  ADD COLUMN IF NOT EXISTS retailer_key            text,
  ADD COLUMN IF NOT EXISTS rewards_reduce_taxable_base
                                                   boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS supports_pickup         boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS free_shipping_threshold numeric;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_retailer_profiles_user_key'
      AND conrelid = 'retailer_profiles'::regclass
  ) THEN
    ALTER TABLE retailer_profiles
      ADD CONSTRAINT uq_retailer_profiles_user_key UNIQUE (user_id, retailer_key);
  END IF;
END $$;
```

Kohl's profile seeded via `ON CONFLICT (user_id, retailer_key) DO UPDATE` upsert. Verified: `rewards_reduce_taxable_base = true`, `loyalty_earn_rate = NULL`, `free_shipping_threshold = 49.00`.
