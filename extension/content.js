// ResellOS Capture — LEGO.com order-detail content script.
//
// DOM extraction verified live 2026-08-21 against two real signed-in orders
// (T512438222, T512392873) via Claude in Chrome + direct JS execution in the
// page -- not just written from the 2026-07-30/31 recon notes. Confirmed:
// URL shape (/en-us/member/orders/details/{orderNumber}), "Order placed" +
// date label, Subtotal/Tax/Total labeled rows, payment method as
// "VISA ••••3013" / "••••6186", "Item: {number}" as two sibling <span>s
// under a per-build hashed class name (not hardcoded here -- see
// extractLineItems), description text preceding "Item:" in reading order,
// GWP items showing a literal "-" with no $ amount, and description strings
// containing markup entities (®, ™, curly apostrophes) that render fine as
// plain text.
//
// CRITICAL thing this verification caught: LEGO's displayed line price(s)
// are LINE TOTALS for the full quantity, not per-unit -- confirmed against
// a real qty-4 discounted line where dividing by quantity was required to
// make the sum of lines equal the order's real Subtotal. See the divisor
// comment in extractLineItems. Getting this wrong would have silently
// overcounted every multi-quantity line once promoted to a real order.
//
// NOT verified live: the waitForContent() timing on a cold page load, and
// the full button-click -> background.js -> Supabase write path (that
// requires the unpacked extension actually loaded in Chrome, which is
// Josh's manual test per SESSION_LOG.md, not something done here). Also
// only two orders were checked -- neither had a strikethrough MSRP without
// a matching sale price, an order with >2 shipment groups, or a
// international/non-en-us locale page, so watch the console ("[ResellOS]"
// prefix) on the first real captures for anything those cases expose.
//
// Deliberate-capture only: nothing here runs automatically. A button is
// injected once the page looks populated; only a click triggers a write.
// Revisiting an old order to look something up does not create a row unless
// that button is clicked.

const BUTTON_ID = "resellos-capture-btn";
const LOG_PREFIX = "[ResellOS]";

function log(...args) {
  console.log(LOG_PREFIX, ...args);
}
function warn(...args) {
  console.warn(LOG_PREFIX, ...args);
}

// -- waiting for the client-rendered page to actually have content ----------

function pageLooksReady() {
  // "Item: {number}" is confirmed live to render once line items are
  // populated -- a text search rather than a selector so it survives LEGO
  // changing element/class structure around it.
  return /Item:\s*\S+/.test(document.body.innerText || "");
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

  // Belt-and-suspenders poll in case mutations are batched/missed.
  const poll = setInterval(() => {
    if (pageLooksReady()) {
      observer.disconnect();
      clearInterval(poll);
      callback(true);
    } else if (Date.now() - start > timeoutMs) {
      observer.disconnect();
      clearInterval(poll);
      warn("Timed out waiting for order content to render. Injecting button anyway.");
      callback(false);
    }
  }, intervalMs);
}

// -- extraction helpers -------------------------------------------------------

function parseMoney(text) {
  if (!text) return null;
  const match = text.replace(/,/g, "").match(/\$?\s*(-?\d+(?:\.\d{1,2})?)/);
  return match ? parseFloat(match[1]) : null;
}

function extractOrderNumberFromUrl() {
  // Detail URL: /en-us/member/orders/details/{orderNumber} -- reliable
  // regardless of DOM render state, unlike everything else on this page.
  const segments = window.location.pathname.split("/").filter(Boolean);
  return segments[segments.length - 1] || null;
}

function extractOrderDate() {
  const body = document.body.innerText || "";
  // Try common label phrasings, then fall back to any date-shaped string
  // near the top of the page.
  const labeled = body.match(/(?:Order date|Placed on|Order placed)[:\s]*([A-Za-z]+ \d{1,2},?\s*\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4})/i);
  const raw = labeled ? labeled[1] : null;
  if (!raw) {
    warn("Could not find an order date label on the page.");
    return null;
  }
  const parsed = new Date(raw);
  if (isNaN(parsed.getTime())) {
    warn(`Found order-date text "${raw}" but could not parse it as a date.`);
    return null;
  }
  return parsed.toISOString().slice(0, 10); // YYYY-MM-DD
}

function extractLabeledAmount(label) {
  // Find an element whose own text is exactly the label, then look for a
  // dollar amount in its parent row (sibling text or a nearby child).
  const candidates = Array.from(document.querySelectorAll("body *")).filter((el) => {
    if (el.children.length > 0) return false; // leaf nodes only
    const text = (el.textContent || "").trim();
    return new RegExp(`^${label}\\b`, "i").test(text);
  });

  for (const el of candidates) {
    const row = el.closest("tr, li, div") || el.parentElement;
    if (!row) continue;
    const amount = parseMoney(row.textContent);
    if (amount !== null) return amount;
  }
  return null;
}

function extractCardLast4() {
  const body = document.body.innerText || "";
  const match = body.match(/(?:ending in|ending\s)\D{0,10}(\d{4})\b/i) || body.match(/•{2,}\s*(\d{4})\b/);
  return match ? match[1] : null;
}

function isItemMarker(el) {
  return /^Item:\s*\S+/i.test((el.textContent || "").trim());
}

function extractLineItems() {
  const items = [];
  // No leaf-only restriction here -- confirmed live 2026-08-21 (real order
  // T512438222) that "Item:" and the set number render as two separate
  // sibling <span>s inside one small div, so only the *parent's* combined
  // text matches this pattern. Nothing above it in the DOM also starts with
  // "Item:" (the product description always renders first), so this regex
  // alone already finds the innermost/correct match without needing a
  // leaf-node filter.
  const itemMarkers = Array.from(document.querySelectorAll("body *")).filter(isItemMarker);

  if (itemMarkers.length === 0) {
    warn('No "Item: {number}" markers found -- LEGO may have changed the page layout, verify live.');
  }

  for (const marker of itemMarkers) {
    const setMatch = (marker.textContent || "").match(/Item:\s*(\S+)/i);
    const setNumber = setMatch ? setMatch[1] : null;

    // Confirmed live 2026-08-21: the actual item row is several levels above
    // the "Item:" marker, under a class name LEGO generates per-build
    // (e.g. "ItemGroupBody-module__lJKLQq__itemBase") that WILL change on
    // LEGO's next deploy -- so instead of hardcoding it, climb ancestors
    // until one's rendered text also contains "Quantity" (confirmed to
    // always sit in the same row as the item marker and price).
    let container = marker.parentElement;
    for (let i = 0; i < 5 && container; i++) {
      if (/Quantity/i.test(container.innerText || "")) break;
      container = container.parentElement;
    }
    if (!container) container = marker.parentElement || marker;

    // innerText (not textContent) -- textContent doesn't insert line breaks
    // between elements, which would collapse the description/qty/price line
    // parsing below into one unsplittable blob on a real element tree.
    const containerText = container.innerText || container.textContent || "";

    const qtyMatch = containerText.match(/Quantity[:\s]*(\d+)/i) || containerText.match(/Qty\D{0,5}(\d+)/i);
    const quantity = qtyMatch ? parseInt(qtyMatch[1], 10) : 1;

    const moneyMatches = containerText.match(/\$\s*-?\d[\d,]*(?:\.\d{1,2})?/g) || [];
    const prices = moneyMatches.map(parseMoney).filter((n) => n !== null);

    let unitPrice = null;
    let netPrice = null;
    let isGwp = false;

    if (prices.length === 0) {
      // No dollar amount at all near this item -- check for the bare-dash
      // GWP signal specifically (confirmed live: LEGO shows a literal "-"
      // in the price column for $0 GWP items), otherwise leave both prices
      // null so a human reviewer notices rather than silently recording $0.
      if (/[–—]|(?:^|\s)-(?:\s|$)/.test(containerText)) {
        isGwp = true;
        unitPrice = 0;
        netPrice = 0;
      }
    } else {
      // CRITICAL, confirmed live 2026-08-21 against real order T512392873:
      // the price(s) LEGO shows per line are LINE TOTALS for the full
      // quantity, not per-unit prices -- e.g. a qty-4 line showed "$131.96"
      // struck through next to "$105.56", and dividing each by 4 gives
      // $32.99 / $26.39, which is what exactly sums to the order's real
      // Subtotal across all lines (undivided sums do not match). ADR-023's
      // raw_data contract and capture_queue_promotion.py's
      // line_total = net_price * quantity both assume PER-UNIT prices --
      // storing the raw line totals here would silently overcount every
      // multi-quantity line by a factor of quantity once promoted to a
      // real order. Divide by quantity before storing.
      const divisor = quantity > 0 ? quantity : 1;
      if (prices.length === 1) {
        unitPrice = Math.round((prices[0] / divisor) * 100) / 100;
        netPrice = unitPrice;
      } else {
        // Strikethrough MSRP total first, discounted total second.
        unitPrice = Math.round((Math.max(...prices) / divisor) * 100) / 100;
        netPrice = Math.round((Math.min(...prices) / divisor) * 100) / 100;
      }
    }

    // Confirmed live: the product description always renders before
    // "Item:" in the row's reading order (e.g. "Sonic: Speedster
    // Lightning\nItem: 77117\nQuantity: 1\nPrice\n$9.99").
    const itemIdx = containerText.search(/Item:/i);
    let description = itemIdx > 0 ? containerText.slice(0, itemIdx).trim() : null;
    if (!description) {
      // Fallback for a layout where description doesn't precede "Item:".
      const textNodes = containerText
        .split("\n")
        .map((s) => s.trim())
        .filter((s) => s && !/^Item:/i.test(s) && !/^\$/.test(s) && !/^Quantity/i.test(s) && !/^Price$/i.test(s));
      if (textNodes.length > 0) {
        description = textNodes.reduce((a, b) => (b.length > a.length ? b : a), "");
      }
    }

    items.push({
      set_number: setNumber,
      description: description || "(description not found — verify selector)",
      quantity,
      unit_price: unitPrice,
      net_price: netPrice,
      is_gwp: isGwp,
    });
  }

  return items;
}

function buildRawData() {
  const orderNumber = extractOrderNumberFromUrl();
  const orderDate = extractOrderDate();
  const lineItems = extractLineItems();
  const subtotal = extractLabeledAmount("Subtotal");
  const tax = extractLabeledAmount("Tax");
  const total = extractLabeledAmount("Total") ?? extractLabeledAmount("Order total");
  const gwpCardLast4 = extractCardLast4();

  log("Extracted:", { orderNumber, orderDate, subtotal, tax, total, gwpCardLast4, lineItems });

  return {
    source: "chrome_extension",
    retailer: "lego",
    order_number: orderNumber,
    order_date: orderDate,
    line_items: lineItems,
    subtotal,
    tax,
    total,
    rewards_earned: null, // Points History is a separate page -- out of scope this session per ADR-023 sequencing.
    gift_card_last4: gwpCardLast4,
  };
}

// -- capture button ------------------------------------------------------------

function injectButton() {
  if (document.getElementById(BUTTON_ID)) return;

  const btn = document.createElement("button");
  btn.id = BUTTON_ID;
  btn.textContent = "Capture to ResellOS";
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
      btn.textContent = "Capture to ResellOS";
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

log("Content script loaded on", window.location.href);
waitForContent(() => injectButton());
