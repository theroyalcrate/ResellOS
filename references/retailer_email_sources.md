# Retailer Email Sources — Personal → Business Gmail Map

**Created:** 2026-07-13 (Cowork session). **Status:** partial — built from real searches against personal Gmail via the Zapier Gmail connector (confirmed as `joshua.buckingham@gmail.com`), not guessed. Fields marked "NOT YET CONFIRMED" still need a targeted search or a forwarded sample before anything is built against them — see CLAUDE.md rule on verifying before assuming.

This doc answers two separate questions per retailer:
1. **Map 1 — Historical backfill:** what sender(s) to search personal Gmail for for a one-time copy of past receipts/confirmations into the business account (the pattern Agent 1C already built for LEGO).
2. **Map 2 — Going forward:** how new emails from this retailer should get from personal Gmail into the business account's `ResellOS-Invoices` queue.

## Capability gap found this session (read before building anything on Map 2)

The Zapier Gmail connector available in Cowork can search, label, archive, forward, and reply — but it has **no action to create a Gmail filter** (a rule that auto-applies to future incoming mail without a human or agent running each time). Agent 1B's Mode 5 (the existing LEGO-only safety net) used the real Gmail API's `users.settings.filters.create` endpoint directly, which isn't exposed through this connector.

That leaves three real options for Map 2, not one:
- **(a) Native Gmail filter** — created either via Agent 1B's local script (extend Mode 5 past LEGO) or by hand in Gmail settings. Runs with zero ongoing agent involvement.
- **(b) A Zap** — built in Zapier's own dashboard (trigger: new Gmail matching sender → action: label or forward to business). Different surface than this MCP connector; I can't create Zaps from here, only execute already-enabled actions.
- **(c) Manual/session-based** — periodically run a Zapier search + forward from Cowork, same shape as what I just did to build this map. Works today, no setup, but isn't "set and forget."

Recommend (a) once senders are fully confirmed — it's what LEGO already uses and needs no new infrastructure. Not decided yet; flagging for Josh.

---

## Per-Retailer Status

### LEGO — CONFIRMED (already built, Pre-S10 Agent 1B+1C)
- Senders: `no-reply-billing03@lego.com` (receipt), `receipts@m.lego.com`, `Noreply@t.crm.lego.com` (2026 order/shipping/survey/decline templates — note: NOT `e.lego.com`, that was the pre-2026 domain).
- Map 2 already live: Mode 5 filter labels `from:(e.lego.com)` → `ResellOS-Needs-Copy` on personal Gmail. **Needs updating to also cover `t.crm.lego.com`** per the 2026-07-05 finding — not yet done.

### Barnes & Noble — CONFIRMED
- `barnesandnoble@t.barnesandnoble.com` — order confirmation / order-failed notices.
- `noreply@orderstatus.barnesandnoble.com` — "your order is here" / status updates.
- `kohls@kohls.narvar.com`-style third-party shipping tracker pattern NOT seen for B&N in this pass — if B&N uses Narvar too, confirm on next real order.
- Marketing-only (exclude): `barnesandnoble@e.barnesandnoble.com`, `noreply@barnesandnoble.com` (login codes), `noreply@getbonusrewards.com`.

### Kohl's — CONFIRMED
- `Kohls@t.kohls.com` — order confirmation, order-updated/repricing emails (matches the repricing design already built 2026-07-05).
- `kohls@kohls.narvar.com` — shipping/delivery tracker (Narvar is Kohl's 3rd-party shipping notification vendor).
- `noreply@kohls.com` — post-purchase review requests (marketing-adjacent, probably exclude).

### Macy's — CONFIRMED
- `CustomerService@oes.macys.com` — order/pickup confirmation and reminders.
- Marketing-only (exclude): `no-reply@em.macys.com`, `noreply@macys.com`, `shop@em.macys.com`, `shop@emails.macys.com`.

### Amazon (Business + Personal) — CONFIRMED, Business account senders
- `auto-confirm@amazon.com` — order confirmation.
- `shipment-tracking@amazon.com` — shipped notice.
- `order-update@amazon.com` / `no-reply@amazon.com` — delivery estimate updates.
- `qla@amazon.com` — cancellation notice.
- All samples pulled showed order-number prefix `112-`, consistent with amazon.md's existing finding that `112-` = Business account. **Personal account (`114-` prefix) senders not separately confirmed this pass** — Amazon likely uses the same sender addresses for both accounts and the order-number prefix is the only differentiator, but that needs one real Personal-account email to confirm rather than assume.

### Target — CONFIRMED (2026-07-13, Josh's own inspection)
- **`orders@oe1.target.com` — order confirmation, good readable data** (price/line-item detail usable for ResellOS entry, per Josh's direct check). Corrects the earlier guess in this doc, which had this address down as "login codes" from a thin sample — it's actually the real transactional sender.
- Guessed `orders@target.com` / `shipment-tracking@target.com` — **zero matches, confirmed wrong, do not use.**
- `orders@oe.target.com` — Target 360 membership receipt (not a purchase order, separate from item purchases).
- Marketing-only (exclude): `Target@express.medallia.com` (survey), `targetnews@em.target.com`.

### Best Buy — DEFERRED, different problem than Target/Walmart (2026-07-13, Josh)
- Not a sender-identification problem: the Best Buy account was originally set up under an email address on a domain **that no longer exists**, so historical order confirmations can't be retrieved from any inbox — Josh had already worked around this by downloading invoices directly from bestbuy.com. Checked the Drive `Invoices/Best Buy/2025/` and `2026/` folders — both empty (year-folder skeleton only, same as every other retailer today), so those manually-downloaded historical invoices are sitting somewhere outside Drive still (local disk?), not yet filed into the project structure.
- **Going forward:** Josh has since pointed Best Buy order confirmations at the business email (`theroyalcratellc@gmail.com`) directly — meaning new orders should need **no personal→business copy step at all**, unlike every other retailer here. Only marketing/account senders (`BestBuy@email.bestbuy.com`, Capital One Shopping gift-card notice) turned up in the personal-inbox search, consistent with new order mail no longer landing there.
- **Historical invoices located (2026-07-13):** confirmed via the Zapier Google Drive connector (also personal account, defaults to personal Drive) — a "Best Buy" folder exists in personal Drive containing at least 3 invoice PDFs: `McLaren.pdf`, `Knuckles Guardian Mech.pdf`, `Peely Bone.pdf`. Named after the LEGO set purchased, not by order number/retailer convention like the business Drive structure expects. Not yet moved into `Invoices/Best Buy/` (still empty there).
- **Action needed (deferred, not urgent):** (1) confirm the real order-confirmation sender once a new Best Buy order actually lands in the business inbox; (2) move/rename the personal-Drive Best Buy PDFs into `Invoices/Best Buy/{Year}/{Month Year}/` per the standard naming convention — needs matching each file to an order number first (not yet done).

### Walmart (Personal, non-Business) — EMAIL PATH RULED OUT (2026-07-13, Josh's own inspection)
- Pass surfaced Walmart Business/seller-tools senders (`newsletter@em.business.walmart.com`, `mp-payments@relay.walmart.com`, `no-reply@es.relay.walmart.com` — these are seller/marketplace tools, likely tied to reselling on Walmart Marketplace, not purchase confirmations) plus one pickup notice from `help@walmart.com`.
- **Josh manually reviewed the actual Walmart order emails and confirmed they don't carry price or line-item detail usable for ResellOS entry.** Unlike LEGO/B&N/Kohl's/Macy's/Amazon, this isn't a "find the right sender" problem — the email content itself is insufficient regardless of which sender is parsed.
- **Conclusion: Walmart personal orders need the Chrome-extension / authenticated-browser-capture path, not an email parser.** This matches the architecture decision already on record (CONTEXT.md — "Authenticated account scraping vs. enrichment scraping": the browser extension is the long-term design for point-of-purchase capture; LEGO's order-history scrape via Claude in Chrome is the existing precedent for this pattern). Do not build a Walmart email_enricher parser module — route this retailer through that work instead when it's built.
- `help@walmart.com` "Picked up at 10:59am: LEGO Super Mario Piran..." confirms LEGO sets do get bought via Walmart pickup — still worth adding as a distinct retailer/channel note if not already tracked elsewhere.

### Fred Meyer, Walgreens, Disney Store — NOT SEARCHED YET
These three have Drive folders already (created 2026-05-19) but aren't in CONTEXT.md's "Retailers Currently in the System" table at all — meaning orders exist for these outside the documented 7-retailer set. Not searched this session; flagging their existence as a documentation gap for CONTEXT.md, separate from this email-sourcing task.

---

## Personal Drive Historical Receipts — Real Structure Found (2026-07-13/14)

This directly resolves/updates CONTEXT.md Open Question #2 ("Google Drive migration — 15 months of historical invoices in personal Drive"). The structure is more fragmented than that open question implied — not one folder, several:

- **"Lego inventory and purchase tracker."** (personal Drive root) — LEGO.com + LEGO in-store only. Organized by month subfolders: `06.2025`, `11.2025`, `12.2025`, `04-05.2025`, `Missing 2025`, and likely more (2026 months not yet fully enumerated). This is the one retailer that stayed consistently organized.
- **"The Royal Crate LLC receipts"** (personal Drive root) — an earlier consolidation attempt, per Josh: started and last touched ~April 2025, then abandoned as day-to-day business got busy. Contains "Walmart purchases," "Target purchases," "Barnes and noble purchases," "Kohls purchases" subfolders — not confirmed whether Best Buy/LEGO subfolders exist inside it too.
- **Everything since ~April 2025** scattered into new ad-hoc root-level folders per retailer instead of landing in the LLC folder: "Walmart Business Purchases," "Walmart.com," "Walmart Missed?," "Target receipts," "Barnes And Noble," "Kohls," "Kohl's 2026," "Best Buy" (3 files, confirmed complete — all Best Buy receipts are PDFs per Josh).

**Not yet done:** a complete inventory (every root-level folder, file counts, date ranges) — what's captured above came from targeted searches per retailer, not an exhaustive root listing. Before any migration/move work starts, build that full inventory first so nothing gets missed or double-moved.

**Mechanism for moving files personal → business Drive** (once inventory is done and Josh confirms scope): share the file/folder from personal Drive with `theroyalcratellc@gmail.com`, then use the business account's own Drive connection to create an owned copy in the right `Invoices/{Retailer}/{Year}/{Month Year}/` destination. Two separate steps because the Zapier Drive connector is scoped to the personal account only and can't write directly into a different Google account's Drive.

## Suggested Next Step

Walmart personal is resolved (Chrome-extension path, not email_enricher); Target is resolved (email parser is viable, `orders@oe1.target.com` confirmed); Best Buy is deferred (no rush — new orders already land in the business inbox natively, historical invoices are handled outside this pipeline). Decide the Map 2 mechanism (native filter vs. Zap vs. manual) for the retailers that need a personal→business copy step: LEGO, Barnes & Noble, Kohl's, Macy's, Amazon Business. Best Buy needs no Map 2 at all once confirmed. Update this doc in place as each retailer's status changes — don't create a second copy.
