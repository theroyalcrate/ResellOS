# ADR-023 — Capture Queue Promotion Workflow + Chrome Extension Primacy

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-08-18 |
| **Decided by** | Josh Buckingham |

---

## Decision

### Part 1 — Chrome extension becomes the primary order-capture method, going forward, for retailers it supports

Once built for a given retailer, new orders are captured live at the point of purchase via a browser content script — not reconstructed after the fact from an email or PDF.

### Part 2 — Agent 1A/1B (PDF/email parsing) become the backstop, not the primary path

They continue to run exactly as built. Their job going forward is catching anything the extension didn't capture: retailers the extension doesn't cover yet, a capture that failed, or historical orders that predate the extension entirely. This is a role change, not a rebuild — no existing Agent 1A/1B code changes because of this decision.

### Part 3 — This supersedes the 2026-07-18 manual-entry-first decision

That decision paused agent-created orders because "set numbers, gift card linkage, and reward detail are unreliable or absent from confirmation/receipt emails." The 2026-08-17 Tier 2 matching work (see SESSION_LOG.md) proved PDF extraction is reliable — 86% of a 1,032-message backlog yielded a clean order number. The stated blocker is resolved. The manual-entry-first row in CONTEXT.md's Architecture Decisions table has been updated to point here rather than deleted.

### Part 4 — `capture_queue` is the single landing zone for every non-manual capture path

Both the Chrome extension and the new PDF-based backfill agent (Agent 1D, built later per this ADR) write into the same table, using the same shape (below), reviewed through the same promote-to-order workflow. There is one review gate, not two.

---

## capture_queue — verified live 2026-08-18

Confirmed directly via Supabase (not assumed): the table exists, 0 rows, and the column list matches `migrations/019_capture_queue.sql` exactly —

`capture_id` (uuid, PK) | `user_id` (uuid) | `retailer` (text) | `source_url` (text, nullable) | `captured_at` (timestamptz) | `raw_data` (jsonb) | `order_number` (text, nullable) | `order_date` (date, nullable) | `total` (numeric, nullable) | `status` (text, default `'pending'`) | `promoted_order_id` (uuid, nullable) | `reviewed_at` (timestamptz, nullable) | `review_note` (text, nullable) | `created_at` (timestamptz)

**Status vocabulary note:** the migration's `CHECK` constraint allows exactly `'pending' | 'promoted' | 'discarded'`. An earlier draft of this ADR used `'rejected'` for the reject path — corrected here to `'discarded'` to match the live constraint (0 rows in the table today, so this was a documentation fix, not a schema change).

---

## raw_data contract — NEW, defined by this ADR

Every writer into `capture_queue` (extension content scripts, Agent 1D) must shape `raw_data` as:

```json
{
  "source": "chrome_extension" | "agent_1d_pdf_backfill",
  "retailer": "lego" | "kohls" | "walmart" | "walmart_business" | "macys",
  "order_number": "string",
  "order_date": "YYYY-MM-DD",
  "line_items": [
    {
      "set_number": "string | null",
      "description": "string",
      "quantity": "int",
      "unit_price": "number",
      "net_price": "number",
      "is_gwp": "bool"
    }
  ],
  "subtotal": "number | null",
  "tax": "number | null",
  "total": "number",
  "rewards_earned": "number | null",
  "gift_card_last4": "string | null"
}
```

`gift_card_last4` — the extension may fill this when visible on the order-detail page (confirmed present on LEGO's page per recon); Agent 1D leaves this null always — PDFs never print it.

Writers also populate the top-level `order_number` / `order_date` / `total` columns (not just inside `raw_data`) so the review list can be queried without parsing JSON.

This mirrors DECISION 017's existing field split (agents/extension fill order data; Josh fills `gift_card_last4` [when the extension didn't already capture it], `buy_reason`, `purchase_trigger`, `cashback_rate`) — this ADR does not change that split, it defines the wire format that carries it.

---

## Implementation Requirements

1. **Promote-to-order workflow** (next session) — reads a pending `capture_queue` row, shows it to Josh, collects the Josh-only fields, writes a real order via the same creation path `agent_02` already uses, sets `capture_queue.status = 'promoted'` + `promoted_order_id`. Reject path sets `status = 'discarded'` with a `review_note`.
2. **Chrome extension** (later session) — Supabase client + login + LEGO.com content script first, writing `raw_data` in the shape above.
3. **Agent 1D** (later session) — reuses Agent 1A's `parse_invoice()`, writes into `capture_queue` in the same shape, `source = 'agent_1d_pdf_backfill'`, for the ~876-order historical backlog found 2026-08-17. Built last, once the promote workflow already exists and is proven on real extension data.

---

## What Does NOT Change

- Agent 1B's Tier 1/Tier 2 matching cascade — unchanged, still the backstop filing path for invoices tied to orders already in the system
- Cost basis gating (DECISION 017) — a promoted order still starts at whatever status DECISION 017 already defines; cost basis still never runs before `confirmed`
- Agent 02 manual entry — remains the true fallback for any retailer the extension never covers

---

## Consequences

- The ~876-order LEGO backlog found 2026-08-17, and the ~1,000-file personal Drive backlog found 2026-08-15, are very likely the same underlying gap viewed from two angles (invoice emails vs. Drive files) — worth checking overlap before building Agent 1D, not assuming they're separate
- Kohl's variable-earn (S10) is effectively solved once the extension covers Kohl's — Kohl's Rewards Activity ledger gives exact figures directly, no separate schema-guessing session needed
- The other retailers without extension coverage (Barnes, Target, Best Buy, Amazon) stay manual-entry-only until the extension expands to them

---

## Related Decisions

- DECISION 017: Order Edit Lifecycle & Cost Basis Trigger Gate (field split this ADR reuses)
- Supersedes: Manual-entry-first order architecture (2026-07-18)
