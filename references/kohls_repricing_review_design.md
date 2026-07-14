# Kohl's Partial-Cancel Repricing — Review Mechanic Design

**Created: 2026-07-05 (Cowork session). Status: designed, not built. Target: S10+ (touches the same Kohl's schema work as migrations 013/014).**

## The problem

When Kohl's partially cancels an order, remaining items get **repriced** (promo/threshold discounts recalculate). The data surfaces inconsistently:

| Surface | Per-line adjusted prices | Correct final total | Machine-readable |
|---------|--------------------------|--------------------|------------------|
| Kohl's website order details | ✗ (shows ORIGINAL prices) | ✓ | scrape-hostile |
| Kohl's mobile app | ✓ (only source) | ✓ | ✗ (manual read) |
| "Order updated" email | ✗ | ✓ (updated subtotal/tax/total) | ✓ |

So per-line truth exists only in the app, but the *target numbers* arrive automatically by email.

## The email (verified against 4 real emails, 2026-06-28)

Sender `Kohls@t.kohls.com`, subject `Joshua, your Kohl's order has been updated.` Fixture: `tests/fixtures/emails/kohls/order_updated_6718166823.txt`.

Contains: order number (body only, `Order #NNNNNNNNNN`), cancelled items with qty + Kohl's SKU + reason ("Recently Sold Out" / "Only N available"), remaining items with qty + SKU, and **updated order summary** (subtotal / shipping / tax / updated total). LEGO set numbers are embedded in product names. Pickup orders use a variant layout (pickup location block, "DIRECTIONS TO STORE").

**Parser traps:** (1) Gmail threads multiple same-subject updates into one thread — 4 different orders arrived as one thread on 6/28; process per-message, dedup per message-id, never per-thread. (2) Order number is not in the subject. (3) Updated summary shows only NEW totals — the differential requires comparing against stored order data.

## The mechanic (5 parts)

1. **Detect (automatic).** "Order updated" email → Tier 1 match on order number → write cancelled-line facts + updated order totals, set `orders.reconciliation_status = 'repricing_review'`, put the human-readable summary in `discrepancy_notes`. Columns already exist. Fallback detection (missed email): sum(line_totals) + actual tax ≠ orders.total.
2. **Capture (manual, self-checking).** Review mode shows original lines, the computed differential, and the target (email's updated total). Josh enters per-line adjusted prices from the mobile app. Validation: entered lines + actual tax must equal the updated total **to the penny** or the save is refused. The email gives the answer key before anyone types anything.
3. **Store without overwriting.** New nullable column (proposed `line_items.final_unit_price`, null = never repriced) keeps original `unit_price` as audit trail. Small migration — fold into the S10 Kohl's schema batch.
4. **Fallback allocation.** If app data is unavailable, allocate the differential proportionally across remaining lines, mark `reconciliation_status = 'estimated_allocation'`. Per ADR-019, such an order cannot settle — cost basis stays provisional until real per-line numbers are entered. The settlement gate enforces this for free.
5. **Kohl's Cash re-check in the same flow.** Partial cancel can cross the earn cliff (~$50 post-coupon) and shrink/kill Kohl's Cash blocks. While the app is open, prompt for actual Kohl's Cash earned — read, never computed (DECISION 018).

## Field rules

The email agent writes: cancelled item facts, updated order totals, reconciliation flag. It never writes per-line adjusted prices (only the app shows them — human enters, validator confirms) and never touches buy_reason / purchase_trigger / gift_card fields (DECISION 017).

## Open questions raised

- **Refund tender on partial cancel:** email says "automatically refunded" — to gift card or card? If GC, does the balance actually return (vs the stranded-balance problem on full cancellations)? Verify against the June 28 orders' actual refunds.
- Do these four orders (6718163821, 6718165953, 6718166823, 6718167062) exist in Supabase yet? If not, they enter as stubs when the Kohl's parser is built.
