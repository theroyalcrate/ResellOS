// ResellOS Capture — LEGO.com order-confirmation content script.
//
// Added 2026-08-27, verified live against one real order (T513379536,
// single gift card, 3 paid items + 1 GWP). This page
// (lego.com/en-us/page/static/order-confirmation/{orderNumber}) only
// appears right after checkout -- unlike the order-details page, it is NOT
// confirmed to remain reachable later for an old order. This is the
// "checkout" capture stage; content.js's order-details capture is the
// "shipped" stage. capture_queue_promotion.py tells the two apart via
// raw_data.capture_stage and merges a later "shipped" capture into an
// already-promoted "checkout" order instead of creating a duplicate.
//
// What this page has that order-details doesn't: Insiders points broken
// out per line item (plus the order total), payment tenders shown as
// itemized dollar deductions ("Gift Card -$116.20"), and -- confirmed live
// 2026-08-26 on T513381170 -- a card's last4 named directly under a
// "Payment Method" heading, separate from the itemized deductions. What's
// still missing here that order-details has: gift card last4s (LEGO never
// shows the per-gift-card split on either page, only order-details shows
// each card's own last4), no tracking numbers (order hasn't shipped yet),
// and GWP items show name-only (no set number, no points line) --
// order-details remains the authoritative source for full
// gift-card-identity/GWP/tracking detail.
//
// Fixed 2026-08-26: "Order Total" is not the order's total value -- it's
// the balance still owed after gift-card deductions, which reads $0.00 on
// any order fully paid by gift card (confirmed live on T513380643). The
// real total is now computed as subtotal + tax and kept as `total`; the
// raw LEGO field is kept separately as `balance_due`. When balance_due is
// still positive after itemized gift-card deductions, a card must have
// covered the rest -- LEGO doesn't itemize card charges as a deduction
// line the way it does gift cards, so that remainder is added as an
// inferred card tender (payment_methods entry with inferred: true). Also
// confirmed live 2026-08-26 on T513381170 (a real card-paid order, card
// ...3013, balance_due $0.66 exactly matching the card charge): the
// card's last4 is readable directly and now attached to that inferred
// entry -- only its dollar amount stays flagged inferred, since it's
// still not an itemized line.
//
// Fixed 2026-08-26: an item on sale shows both "Price $X.XX" (list) and
// "Sale Price $Y.YY" (what's actually charged) -- confirmed live on
// T513381170 (Mirabel Key Chain). unit_price now prefers the sale price
// when present; the list price is kept separately as list_price.
//
// NOT verified live: a second gift card tender on this page (only ever
// seen one gift card line across the orders checked so far -- content.js
// confirms multi-gift-card orders exist, just not observed here yet), a
// branded card name/type (only last4 is shown, no "VISA"/"Mastercard"
// text observed), and whether this URL is reachable again for an order
// placed in an earlier session. Watch the console ("[ResellOS]" prefix)
// on the first captures of those cases.

const BUTTON_ID = "resellos-capture-confirmation-btn";
const LOG_PREFIX = "[ResellOS]";

function log(...args) {
  console.log(LOG_PREFIX, ...args);
}
function warn(...args) {
  console.warn(LOG_PREFIX, ...args);
}

function parseMoney(text) {
  if (!text) return null;
  const match = text.replace(/,/g, "").match(/-?\$?\s*(-?\d+(?:\.\d{1,2})?)/);
  return match ? parseFloat(match[1]) : null;
}

function pageLooksReady() {
  // "Order Details" heading confirmed live to render once the page's data
  // has loaded -- same text-search-over-selector reasoning as content.js.
  return /Order Details/.test(document.body.innerText || "");
}

function waitForContent(callback, { timeoutMs = 20000, intervalMs = 500 } = {}) {
  const start = Date.now();
  const observer = new MutationObserver(() => {
    if (pageLooksReady()) {
      observer.disconnect();
      clearInterval(poll);
      callback(true);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  const poll = setInterval(() => {
    if (pageLooksReady()) {
      observer.disconnect();
      clearInterval(poll);
      callback(true);
    } else if (Date.now() - start > timeoutMs) {
      observer.disconnect();
      clearInterval(poll);
      warn("Timed out waiting for order-confirmation content to render. Injecting button anyway.");
      callback(false);
    }
  }, intervalMs);
}

// -- extraction helpers -------------------------------------------------------

function extractOrderNumberFromUrl() {
  const segments = window.location.pathname.split("/").filter(Boolean);
  return segments[segments.length - 1] || null;
}

// Returns the first non-empty line of body text after a line matching
// labelRegex -- confirmed live: this page renders each Order Summary label
// on its own line with the value on the line right after it (unlike
// order-details, which needed DOM-row climbing because of a different
// layout).
function valueAfterLabel(body, labelRegex) {
  const lines = body.split("\n").map((s) => s.trim());
  for (let i = 0; i < lines.length; i++) {
    if (labelRegex.test(lines[i])) {
      for (let j = i + 1; j < lines.length; j++) {
        if (lines[j]) return lines[j];
      }
    }
  }
  return null;
}

function extractTotals() {
  const body = document.body.innerText || "";
  const subtotal = parseMoney(valueAfterLabel(body, /^\d+\s+items?$/i));
  const tax = parseMoney(valueAfterLabel(body, /^TAX$/i));
  // LEGO labels this line "Order Total" but it's actually the remaining
  // BALANCE still to be charged to a card -- confirmed live 2026-08-26 on
  // T513380643: subtotal $102.96 + tax $11.02 = $113.98, fully covered by
  // two gift card deductions ($19.81 + $94.17), and this line read
  // "$0.00". Kept as balance_due. The real order total is computed below
  // as subtotal + tax so it's never silently wrong just because the order
  // happened to be paid off entirely by gift card.
  const balanceDue = parseMoney(valueAfterLabel(body, /^Order Total$/i));
  const total =
    subtotal != null && tax != null
      ? Math.round((subtotal + tax) * 100) / 100
      : null;
  return { subtotal, tax, total, balance_due: balanceDue };
}

// Card last4 shown under a "Payment Method" heading near the top of the
// page (confirmed live on T513381170: "Payment Method\n**** 3013"), separate
// from the itemized "Order Summary" deductions -- gift cards show there as
// "-$X" lines, but a card is only ever named here, as a masked number, with
// no dollar amount attached. No brand text observed live yet.
function extractPaymentMethodCardLast4() {
  const body = document.body.innerText || "";
  const match = body.match(/Payment Method\s*\n\s*\**\s*(\d{4})\b/i);
  return match ? match[1] : null;
}

function extractPointsEarned() {
  const body = document.body.innerText || "";
  const match = body.match(/You will earn\s*\n\s*(\d+)\s*\n\s*points on this purchase/i);
  return match ? parseInt(match[1], 10) : null;
}

// Payment tenders shown as itemized deductions in the Order Summary block,
// between the "{N} items" line and "TAX". Confirmed live: "Gift Card" is
// one such label; "Standard shipping"/"Free" sits in the same block but
// isn't a tender, so it's explicitly excluded. Any other label immediately
// followed by a dollar-shaped line is treated as a tender -- written
// generically since only "Gift Card" has been seen live.
function extractPaymentBreakdown() {
  const body = document.body.innerText || "";
  const summaryMatch = body.match(/Order Summary\s*\n([\s\S]*?)\n\s*(?:LEGO® Insiders points|Order Details)/i);
  if (!summaryMatch) {
    warn("Could not find the Order Summary block.");
    return [];
  }
  const lines = summaryMatch[1].split("\n").map((s) => s.trim()).filter(Boolean);
  const NON_TENDER_LABELS = /^(\d+\s+items?|Standard shipping|Free|TAX|Order Total)$/i;
  const MONEY_LINE = /^-?\$\s*\d/;

  const tenders = [];
  for (let i = 0; i < lines.length - 1; i++) {
    if (NON_TENDER_LABELS.test(lines[i])) continue;
    if (MONEY_LINE.test(lines[i])) continue; // this line IS a value, not a label
    if (MONEY_LINE.test(lines[i + 1])) {
      tenders.push({
        label: lines[i],
        type: /gift card/i.test(lines[i]) ? "gift_card" : "other",
        amount: parseMoney(lines[i + 1]),
      });
    }
  }
  if (tenders.length === 0) {
    warn("No payment tender lines found in Order Summary -- verify live.");
  }
  return tenders;
}

// Line items with per-item Insiders points. Paid items and GWP items render
// differently on this page (confirmed live): paid items have "Item:
// {number}", "Insiders Points on this order: {n}", and a price; the GWP
// item is just "Gift with Purchase" followed by a bare name, no item
// number, no points line, no price. GWP set numbers/quantities remain
// order-details' job -- this only adds points_earned per item where LEGO
// actually shows it.
//
// Fixed 2026-08-28: "Insiders Points on this order: {n}" is PER UNIT, not
// per line -- confirmed live on T513265219 (Sonic: Speedster Lightning,
// Qty: 2, page showed "65"; the order-level "You will earn 682 points"
// only reconciles as 390 + 162 + 65*2 + 0, not 390 + 162 + 65 + 0). Same
// per-unit-vs-line distinction unit_price/list_price already handle for
// price -- points_earned below is now the QUANTITY-ADJUSTED total for the
// line (what net_price-style downstream consumers want), with the raw
// per-unit number kept separately as points_per_unit.
function extractLineItemsWithPoints() {
  const body = document.body.innerText || "";
  const detailsMatch = body.match(/Order Details\s*\n([\s\S]*?)(?:\n\s*Support\s*\n|$)/i);
  if (!detailsMatch) {
    warn("Could not find the Order Details block.");
    return [];
  }
  const section = detailsMatch[1];
  const items = [];

  // Paid items: description line, then "Item: {number}" -- confirmed live
  // the name always renders on its own line right before "Item:", same
  // reading-order assumption content.js makes for the order-details page.
  // Fixed 2026-08-26: an item on sale shows BOTH "Price $X.XX" (list) and
  // "Sale Price $Y.YY" (what's actually charged) inside the same block --
  // confirmed live on T513381170 (Mirabel Key Chain: Price $5.99, Sale
  // Price $3.59, subtotal only adds up with $3.59). The old regex always
  // grabbed the first dollar amount after "Price", which is the list
  // price, silently overstating unit_price on any sale item. Now captures
  // the whole block between the points line and "Qty:", then prefers
  // "Sale Price" over "Price" within it.
  const itemBlockRegex = /([^\n]+)\nItem:\s*(\S+)\s*\nInsiders Points on this order:\s*(\d+)\s*\n([\s\S]*?)\nQty:\s*(\d+)/gi;
  let match;
  while ((match = itemBlockRegex.exec(section)) !== null) {
    const priceBlock = match[4];
    const listPriceMatch = priceBlock.match(/^Price\s*\$(\d+(?:\.\d{1,2})?)/im);
    const salePriceMatch = priceBlock.match(/Sale Price\s*\$(\d+(?:\.\d{1,2})?)/i);
    const unitPrice = salePriceMatch
      ? parseFloat(salePriceMatch[1])
      : listPriceMatch
      ? parseFloat(listPriceMatch[1])
      : null;
    if (unitPrice == null) {
      warn(`Could not find a price for "${match[1].trim()}" -- skipping unit_price.`);
    }
    const quantity = parseInt(match[5], 10);
    const pointsPerUnit = parseInt(match[3], 10);
    items.push({
      description: match[1].trim(),
      set_number: match[2],
      points_earned: pointsPerUnit * quantity,
      points_per_unit: pointsPerUnit,
      unit_price: unitPrice,
      list_price: listPriceMatch ? parseFloat(listPriceMatch[1]) : null,
      quantity: quantity,
      is_gwp: false,
    });
  }

  // GWP items: "Gift with Purchase" followed by a bare description line.
  const gwpRegex = /Gift with Purchase\s*\n(.+)/gi;
  while ((match = gwpRegex.exec(section)) !== null) {
    items.push({
      set_number: null,
      description: match[1].trim(),
      points_earned: 0,
      unit_price: 0,
      quantity: 1,
      is_gwp: true,
    });
  }

  if (items.length === 0) {
    warn('No line items found under "Order Details" -- verify live.');
  }
  return items;
}

function buildRawData() {
  const orderNumber = extractOrderNumberFromUrl();
  const totals = extractTotals();
  const pointsEarned = extractPointsEarned();
  const paymentBreakdown = extractPaymentBreakdown();
  const lineItems = extractLineItemsWithPoints();

  const paymentMethods = paymentBreakdown.map((t) => ({
    type: t.type,
    label: t.label,
    amount: t.amount,
  }));

  // If gift-card/other itemized deductions don't cover the full total,
  // the remainder was charged to a card. LEGO's summary block only shows
  // gift cards as itemized "-$X" lines (confirmed live, see extractPaymentBreakdown) --
  // a card payment isn't observed live yet, so it's inferred here from
  // balance_due rather than read directly, and flagged inferred: true so
  // it's obvious at review time in capture_queue_promotion.py.
  if (totals.balance_due != null && totals.balance_due > 0.01) {
    // Confirmed live 2026-08-26 on T513381170 (subtotal $103.58 + tax
    // $11.08 = $114.66, one $114.00 gift card, "Order Total" $0.66,
    // "Payment Method" showed card **** 3013): the leftover balance really
    // is what got charged to the card named under "Payment Method". last4
    // is read directly off the page when present; the dollar amount still
    // isn't an itemized line here (LEGO doesn't show "Visa -$0.66" the way
    // it shows "Gift Card -$114.00"), so it's derived from balance_due and
    // kept flagged inferred: true for review either way.
    const cardLast4 = extractPaymentMethodCardLast4();
    paymentMethods.push({
      type: "card",
      label: cardLast4 ? `Card ...${cardLast4}` : "Card (inferred from balance due)",
      last4: cardLast4,
      amount: totals.balance_due,
      inferred: true,
    });
    warn(`Order Total showed a balance due of $${totals.balance_due}${cardLast4 ? ` -- matched to card ...${cardLast4}` : ""}, verify at review.`);
  }

  // Sanity check: line item points_earned (now quantity-adjusted) should
  // sum to the page's own "You will earn N points" total. Cheap way to
  // catch the next per-unit-vs-line-quantity surprise before it silently
  // ships bad data, the way the T513265219 case did.
  const lineItemPointsSum = lineItems.reduce((sum, li) => sum + (li.points_earned || 0), 0);
  if (pointsEarned != null && lineItemPointsSum !== pointsEarned) {
    warn(`Line item points (${lineItemPointsSum}) don't sum to the page total (${pointsEarned}) -- verify at review.`);
  }

  log("Extracted (checkout stage):", { orderNumber, totals, pointsEarned, lineItemPointsSum, paymentMethods, lineItems });

  return {
    source: "chrome_extension",
    capture_stage: "checkout", // distinguishes from content.js's "shipped" stage -- see capture_queue_promotion.py
    retailer: "lego",
    order_number: orderNumber,
    order_date: new Date().toISOString().slice(0, 10), // this page only exists at checkout -- today is correct
    line_items: lineItems,
    subtotal: totals.subtotal,
    tax: totals.tax,
    total: totals.total, // computed: subtotal + tax -- the order's real value, not LEGO's "Order Total" balance-due field
    balance_due: totals.balance_due, // raw "Order Total" as LEGO shows it -- amount left to charge a card, should net to $0 once payment_methods fully covers total
    rewards_earned: pointsEarned,
    payment_methods: paymentMethods,
    gift_card_last4: null, // not shown on this page -- order-details fills this in later
    shipments: [], // order hasn't shipped yet
  };
}

// -- capture button ------------------------------------------------------------

function injectButton() {
  if (document.getElementById(BUTTON_ID)) return;

  const btn = document.createElement("button");
  btn.id = BUTTON_ID;
  btn.textContent = "Capture to ResellOS (checkout)";
  Object.assign(btn.style, {
    position: "fixed",
    top: "16px",
    right: "16px",
    zIndex: "999999",
    padding: "10px 16px",
    background: "#1a5",
    color: "#fff",
    border: "none",
    borderRadius: "6px",
    fontSize: "14px",
    fontFamily: "system-ui, sans-serif",
    cursor: "pointer",
    boxShadow: "0 2px 8px rgba(0,0,0,0.25)",
  });

  btn.addEventListener("click", () => onCaptureClick(btn));
  document.body.appendChild(btn);
  log("Capture button injected.");
}

function setButtonState(btn, state, detail) {
  switch (state) {
    case "capturing":
      btn.textContent = "Capturing…";
      btn.disabled = true;
      btn.style.background = "#888";
      break;
    case "success":
      btn.textContent = "✓ Captured";
      btn.disabled = false;
      btn.style.background = "#1a5";
      setTimeout(() => setButtonState(btn, "idle"), 3000);
      break;
    case "error":
      btn.textContent = "✗ Capture failed (see console)";
      btn.disabled = false;
      btn.style.background = "#c22";
      btn.title = detail || "";
      warn("Capture failed:", detail);
      break;
    case "idle":
    default:
      btn.textContent = "Capture to ResellOS (checkout)";
      btn.disabled = false;
      btn.style.background = "#1a5";
      btn.removeAttribute("title");
  }
}

async function onCaptureClick(btn) {
  setButtonState(btn, "capturing");

  const rawData = buildRawData();

  if (!rawData.order_number) {
    setButtonState(btn, "error", "Could not determine order number from the URL.");
    return;
  }

  const payload = {
    source_url: window.location.href,
    raw_data: rawData,
  };

  let result;
  try {
    result = await chrome.runtime.sendMessage({ type: "CAPTURE_ORDER", payload });
  } catch (err) {
    setButtonState(btn, "error", err.message);
    return;
  }

  if (result && result.success) {
    log("Capture written to capture_queue.", result.data);
    setButtonState(btn, "success");
  } else {
    setButtonState(btn, "error", (result && result.error) || "Unknown error.");
  }
}

// -- entry point ---------------------------------------------------------------

log("Order-confirmation content script loaded on", window.location.href);
waitForContent(() => injectButton());
