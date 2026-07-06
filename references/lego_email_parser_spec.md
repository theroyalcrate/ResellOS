# LEGO Email Parser Spec — for email_enricher.py (LEGO module)

**Created: 2026-07-05 (Cowork session). Source: real emails in the business Gmail inbox, verified against live Supabase order rows (T508041747, T508056398). Fixtures: `tests/fixtures/emails/lego/`.**

This spec feeds the per-retailer parser module design decided 2026-06-26 (one configurable `email_enricher.py`, per-retailer parsers, shared A-007 cascade). Everything below was observed in real 2026 emails — not assumed.

---

## Email family (senders + subjects)

| Type | Sender | Subject pattern | Order # location |
|------|--------|----------------|------------------|
| Order confirmation | `Noreply@t.crm.lego.com` | `We've got it! Your LEGO® order is confirmed, {name}` | **Body** (`Order: T#########`) |
| Shipping confirmation | `Noreply@t.crm.lego.com` | `Your LEGO Order {T#} is on its way {name}` | **Subject + body** |
| Invoice/receipt | `no-reply-billing03@lego.com` | `LEGO® Shop  Receipt {invoice#} from {MM/DD/YYYY}` (double space after "Shop") | **Neither** — invoice # only (Tier 2 via PDF) |
| Payment declined | `Noreply@t.crm.lego.com` | `Your payment was unsuccessful` | **Body** (`order T#########, placed on M/D/YYYY`) |
| Survey (ignore) | `Noreply@t.crm.lego.com` | `Thank you for your recent LEGO® purchase.` | n/a — skip |
| BrickLink Designer Program variant | `Noreply@t.crm.lego.com` | Same "on its way" subject; body says "BrickLink® Designer Program" | Subject |

Historical senders (from Agent 1C backfill): `no-reply-billing03@lego.com`, `receipts@m.lego.com`. The `e.lego.com` sender used by Agent 1B Mode 4 filters is the older CRM domain — **2026 emails come from `t.crm.lego.com`**; agent filters must cover both.

## ⚠ Correction to A-007 / CONTEXT.md

CONTEXT.md states the order number "first appears in the shipping confirmation subject — never in the order confirmation email." **Wrong for 2026 templates:** the order confirmation body contains `Order: T508221251`, order date, full line items, and totals. Order confirmations are Tier 1 matchable. Update CONTEXT.md A-007 section when convenient; cascade logic is unchanged (order number remains the only true identity), it just fires earlier.

## Order confirmation — extractable fields

From fixture `order_confirmation_T508221251.txt`:

- `Order: T#########`, `Order date: M/D/YYYY`
- Shipping address block
- `SUB TOTAL / SHIPPING / TAX / ORDER TOTAL` (order-level)
- Line items: `{set_number} {name} V{nn}` then price / qty / line-total / `Status: In Process`

**Parser traps (all observed):**
1. The per-line **price column is unreliable** — showed `$0.00` for paid items in the confirmation while line totals were correct. Derive `unit_price = line_total / qty`; never trust the price column.
2. Set names carry a trailing ` V{nn}` variant suffix (`V39`) and get truncated with `..` (`Mack® LR Electric Garbage Tr..`) — strip suffix, don't name-match on truncated names (resolve by set_number, which is always present and clean).
3. GWP lines look like normal lines with line-total `0` — flag `is_gwp` when line_total == 0 and qty ≥ 1.
4. Columns arrive garbled in plaintext (`PriceQTD.TOTAL` mashed together) — parse the HTML body or use tolerant regex on the plaintext, don't assume clean columns.

## Shipping confirmation — extractable fields

From fixtures `shipping_confirmation_T508041747_ship{1,2}.txt`:

- Order number (subject + body), order date, UPS tracking number (`ups.com/track?...tracknum={id}` + bare id in body)
- Line items **for that shipment only**, `Status: Shipped`; here the price column WAS correct — still prefer line_total/qty for safety

**Parser traps:**
1. **One email per shipment, identical subjects.** T508041747 got two "on its way" emails same day with different tracking + different items. These are NOT duplicates — each is a `shipments` row. Dedup at gmail message-id level only (A-007 confirmed by real data).
2. The `SUB TOTAL / TAX / ORDER TOTAL` block in a shipping email is **per-shipment**, despite being labeled "ORDER TOTAL" ($99.95/$10.70/$110.65 for ship1 vs $39.98/$4.28/$44.26 for ship2 of the same $169.28 order). Never write these to `orders` totals — they map to `shipments.subtotal / tax_amount`.
3. **Order date skews +1 day** vs DB: email said 6/23/2026, order was placed 6/22 (DB + confirmation email agree on 6/22 basis). Any date-window matching needs ±1 day tolerance.

## Payment declined — new lifecycle event

Not previously documented. Carries order number + placed date. Order is held 5 business days pending phone call, then presumably cancelled. Enricher action: flag the matching order for review (do NOT auto-cancel). If no matching order exists (T507979974 is not in Supabase), queue as an orphan stub with a `payment_declined` note.

## Receipt email — envelope only

Body has invoice number + purchase date, no order number. PDF attachment (named same as subject) is Agent 1A's job. Enricher's only job: Tier 2 match via the parsed invoice, and record `invoice_number` linkage.

## Field-fill rules (DECISION 017 — restated)

Agents fill: order number, retailer, order date, line items (set_number, name, qty, line_total, is_gwp), totals, tracking numbers, rewards earned, CC last 4 (from invoice PDF).
Agents NEVER fill: `gift_card_last4`, `buy_reason`, `purchase_trigger`, `cashback_rate`. Leave null.
New orders from email = `stub` / `pending_review` status. Cost basis never runs on agent-written data without explicit confirmation.

## Matching examples from real data (test cases for the cascade)

1. **Tier 1 direct**: shipping email T508041747 → order exists → attach shipment + tracking. (Fixtures ship1/ship2.)
2. **Identical totals, different orders**: T508056398 and T508221251 both total $169.33 with different items — totals alone must never match orders.
3. **Orphan**: T508221251, T508206446, T508133224 exist in email but not in Supabase → create stub orders (`pending_review`), never silently drop.
4. **Split shipment**: two shipment rows, one order, from two same-subject emails.
5. **Declined**: T507979974 → orphan stub + `payment_declined` flag.

## Known data gap (found 2026-07-05)

Orders placed ~June 23–25 (T508133224, T508206446, T508221251) and declined T507979974 are in the business inbox but not in Supabase. First live run of the enricher should surface exactly these as stubs — a natural acceptance test.
