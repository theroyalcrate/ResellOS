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
// out per line item (plus the order total), and payment tenders shown as
// itemized dollar deductions ("Gift Card -$116.20") rather than just
// masked last-4s. What it's missing that order-details has: no card
// last4s at all, no tracking numbers (order hasn't shipped yet), and GWP
// items show name-only (no set number, no points line) -- order-details
// remains the authoritative source for full line-item/GWP/tracking detail.
//
// NOT verified live: a second tender type (only one gift card on the test
// order -- Josh confirmed multi-gift-card orders show one "Gift Card -$X"
// line per card here, but that's not directly observed by this script
// yet), a branded-card deduction line (e.g. "Visa -$X"), and whether this
// URL is reachable again for an order placed in an earlier session. Watch
// the console ("[ResellOS]" prefix) on the first captures of those cases.

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
  return {
    subtotal: parseMoney(valueAfterLabel(body, /^\d+\s+items?$/i)),
    tax: parseMoney(valueAfterLabel(body, /^TAX$/i)),
    total: parseMoney(valueAfterLabel(body, /^Order Total$/i)),
  };
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
  const itemRegex = /([^\n]+)\nItem:\s*(\S+)\s*\nInsiders Points on this order:\s*(\d+)\s*\nPrice[\s\S]*?\$(\d+(?:\.\d{1,2})?)[\s\S]*?\nQty:\s*(\d+)/gi;
  let match;
  while ((match = itemRegex.exec(section)) !== null) {
    items.push({
      description: match[1].trim(),
      set_number: match[2],
      points_earned: parseInt(match[3], 10),
      unit_price: parseFloat(match[4]),
      quantity: parseInt(match[5], 10),
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

  log("Extracted (checkout stage):", { orderNumber, totals, pointsEarned, paymentBreakdown, lineItems });

  return {
    source: "chrome_extension",
    capture_stage: "checkout", // distinguishes from content.js's "shipped" stage -- see capture_queue_promotion.py
    retailer: "lego",
    order_number: orderNumber,
    order_date: new Date().toISOString().slice(0, 10), // this page only exists at checkout -- today is correct
    line_items: lineItems,
    subtotal: totals.subtotal,
    tax: totals.tax,
    total: totals.total,
    rewards_earned: pointsEarned,
    payment_methods: paymentBreakdown.map((t) => ({
      type: t.type,
      label: t.label,
      amount: t.amount,
    })),
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
