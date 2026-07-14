---
name: lego-order-capture
description: >
  Captures a LEGO order from the confirmation page into a structured CSV row for ResellOS import.
  Triggered by the user saying "record", "/record", "capture this order", or "log this order"
  while on a LEGO order confirmation or order detail page. Asks only for gift card details
  (the one piece of data not visible on the page), then extracts everything else automatically.
---

# LEGO Order Capture

Captures a LEGO order from the current browser page into a structured CSV row ready for ResellOS import. Asks the user only for gift card information — everything else comes from the page.

---

## WHEN TO RUN

Run when the user is on one of these LEGO pages:
- Order confirmation: `lego.com/en-us/member/orders/confirmation/*`
- Order detail: `lego.com/en-us/member/orders/details/T*`
- Any page showing a single LEGO order summary

Do NOT run on cart, checkout, or product pages.

---

## STEP 1 — READ THE PAGE

Use `get_page_text` to extract the full text of the current page. From it, identify:

| Field | Where to find it |
|-------|-----------------|
| Order number | "Order number" or "T" + 9 digits in the heading |
| Order date | "Order placed" date |
| Line items | Set number, name, price, quantity for each item |
| GWP items | Any item with $0.00 price — flag as Gift With Purchase |
| Subtotal | "Subtotal" line |
| Tax | "TAX" or "Tax" line |
| Discount | Any negative dollar amount (coupon, Insiders discount) |
| Order total | "Order Total" or "Total" line |
| Insiders points earned | "Insiders Points Earned" line |
| Payment methods | Visa/ApplePay/PayPal/GiftCard indicators |
| Shipping address | Full address block |

---

## STEP 2 — ASK FOR GIFT CARD INFO

Only ask this question if the page shows gift card payment was used (any mention of "Gift Card" in payment methods or a negative line for gift card amount).

Ask the user:

> "I see gift cards were used. Please tell me:
> - Last 4 digits of each card and the amount charged to it
> - Example: '1965 → $29.96, 1913 → $139.39'
> - If you don't know the split, just give me the last 4 digits and I'll note the total as unallocated."

If NO gift card was used, skip this step entirely.

---

## STEP 3 — BUILD THE OUTPUT

Produce two outputs:

### A) Summary confirmation (show to user)

```
Order: T[number] — [date]
Items: [count] paid + [count] GWP
Total: $[total] | Subtotal: $[subtotal] | Tax: $[tax] | Discount: $[discount or 'none']
Payment: [methods]
Gift Cards: [last4 → $amount, ...] or 'None'
Insiders Points: [points earned]
Shipping to: [city, state]
```

### B) CSV row (matching lego_order_scrape.csv schema)

Schema:
```
order_number,order_date,order_total,subtotal,tax,discount,payment_methods,gift_card_last4s,has_apple_pay,has_paypal,notes,scraped_date
```

Rules:
- `payment_methods`: `+`-joined list (e.g. `GiftCard+Visa`, `InsidersPoints+GiftCard+GiftCard`)
- `gift_card_last4s`: pipe-delimited last 4s (e.g. `1965|1913`). Include per-card amounts in notes if known.
- `has_apple_pay`: TRUE/FALSE
- `has_paypal`: TRUE/FALSE
- `discount`: negative number if a discount was applied, blank if none
- `notes`: Visa last 4 if Visa used; per-card GC amounts if known; Insiders discount amount; anything notable
- `scraped_date`: today's date in YYYY-MM-DD format

### C) Line items CSV (separate — for future ResellOS import)

Schema:
```
order_number,set_number,set_name,price,quantity,is_gwp,insiders_points
```

Output one row per line item including GWPs (with `is_gwp=TRUE` and `price=0.00`).

---

## STEP 4 — PRESENT OUTPUT

Show the summary confirmation first so the user can spot errors quickly.

Then show both CSV rows formatted as a code block so they're easy to copy.

Finally ask: "Want me to append this to your lego_order_scrape.csv file?"

If yes — use the file write tools to append the order summary row to:
`C:\Users\joshu\Claude\Projects\ResellOS software development\lego_order_scrape.csv`

Do NOT append the line items CSV there — that file has a different schema. The line items are for future use.

---

## RULES

- **Never store full card numbers** — last 4 digits only, always.
- **Never guess gift card amounts** — if the user doesn't know the split, record the last 4s and note "amounts unknown" in the notes field.
- **GWP price is always $0.00** — do not infer a price from MSRP or any other source.
- **Insiders Points discount reduces the order total but is NOT a gift card** — record it in notes as "Insiders discount -$X.XX".
- **Cancelled orders**: if total is $0.00, add "CANCELLED - $0 total" to notes. Still capture GC last 4s if shown.
- **Multiple GCs**: list all of them in `gift_card_last4s` pipe-delimited. Each gets its own amount in notes if the user provides it.

---

## EXAMPLE OUTPUT

For an order with two gift cards (1965 → $29.96, 1913 → $139.39), a GWP, and Insiders points:

**Summary:**
```
Order: T507494537 — 2026-06-18
Items: 2 paid + 1 GWP (Tribute to Leonardo da Vinci)
Total: $0.00 | Subtotal: $152.98 | Tax: $16.37 | Discount: none
Payment: GiftCard + GiftCard
Gift Cards: 1965 → $29.96 | 1913 → $139.39
Insiders Points: 1,989 earned
Shipping to: Edmonds, WA
```

**lego_order_scrape.csv row:**
```
T507494537,2026-06-18,0.00,152.98,16.37,,GiftCard+GiftCard,1965|1913,FALSE,FALSE,GC 1965 → $29.96; GC 1913 → $139.39; 1989 Insiders pts earned,2026-06-18
```

**Line items:**
```
T507494537,21058,Great Pyramid of Giza,129.99,1,FALSE,845
T507494537,11204,Mermaid Gabby's Aquarium Adventure,22.99,1,FALSE,149
T507494537,,Tribute to Leonardo da Vinci,0.00,1,TRUE,0
```
