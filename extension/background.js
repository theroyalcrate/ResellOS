// ResellOS Capture — background service worker (Manifest V3)
//
// Why this doesn't use supabase-js: the SDK expects browser localStorage for
// session persistence, which an MV3 service worker doesn't have (it can be
// torn down and restarted at any time, and has no DOM/localStorage at all).
// Instead this talks to Supabase Auth + PostgREST directly over fetch(), and
// persists the session in chrome.storage.local. See ADR-023 and SESSION_LOG.md
// (this session's entry) for the full reasoning.
//
// SECURITY BOUNDARY: SUPABASE_PUBLISHABLE_KEY below is the public/publishable
// key, not the service-role secret key db_client.py uses for backend scripts.
// It is safe to ship in extension source — RLS on every table (migration 017)
// is the real security boundary, not key secrecy. NEVER put the service-role
// key here or anywhere else in extension code.
//
// FAIL-CLOSED RULE: every write path below returns an explicit
// { success: false, error } when there is no valid session. There is no
// silent-success fallback — a failed write must look like a failure to the
// content script, never like a completed capture.

const SUPABASE_URL = "https://svztskmvugggdaysqbsj.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_HPoE_9kyV9Xv1_n8WHVzjg_Gu9OFQFX";

const AUTH_TOKEN_URL = `${SUPABASE_URL}/auth/v1/token`;
const AUTH_RECOVER_URL = `${SUPABASE_URL}/auth/v1/recover`;
const AUTH_LOGOUT_URL = `${SUPABASE_URL}/auth/v1/logout`;
const CAPTURE_QUEUE_URL = `${SUPABASE_URL}/rest/v1/capture_queue`;

const SESSION_KEYS = ["access_token", "refresh_token", "expires_at", "user_id", "email"];

// -- session storage ---------------------------------------------------------

async function getStoredSession() {
  const stored = await chrome.storage.local.get(SESSION_KEYS);
  if (!stored.access_token || !stored.refresh_token || !stored.user_id) {
    return null;
  }
  return stored;
}

async function saveSession(authResponse) {
  const expiresInSeconds = authResponse.expires_in || 3600;
  const session = {
    access_token: authResponse.access_token,
    refresh_token: authResponse.refresh_token,
    // 30s safety buffer so we refresh slightly before actual expiry.
    expires_at: Date.now() + expiresInSeconds * 1000 - 30000,
    user_id: authResponse.user && authResponse.user.id,
    email: authResponse.user && authResponse.user.email,
  };
  await chrome.storage.local.set(session);
  return session;
}

async function clearSession() {
  await chrome.storage.local.remove(SESSION_KEYS);
}

// -- auth ---------------------------------------------------------------------

async function login(email, password) {
  let response;
  try {
    response = await fetch(`${AUTH_TOKEN_URL}?grant_type=password`, {
      method: "POST",
      headers: {
        apikey: SUPABASE_PUBLISHABLE_KEY,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    });
  } catch (networkErr) {
    return { success: false, error: `Network error: ${networkErr.message}` };
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    return {
      success: false,
      error: data.error_description || data.msg || `Login failed (${response.status})`,
    };
  }

  const session = await saveSession(data);
  return { success: true, email: session.email };
}

async function requestPasswordReset(email) {
  try {
    await fetch(AUTH_RECOVER_URL, {
      method: "POST",
      headers: {
        apikey: SUPABASE_PUBLISHABLE_KEY,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email }),
    });
  } catch (networkErr) {
    return { success: false, error: `Network error: ${networkErr.message}` };
  }
  // Supabase returns 200 regardless of whether the email exists (no user
  // enumeration) -- there is nothing meaningful to branch on beyond "sent".
  return { success: true };
}

async function refreshSession() {
  const stored = await getStoredSession();
  if (!stored) return null;

  let response;
  try {
    response = await fetch(`${AUTH_TOKEN_URL}?grant_type=refresh_token`, {
      method: "POST",
      headers: {
        apikey: SUPABASE_PUBLISHABLE_KEY,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ refresh_token: stored.refresh_token }),
    });
  } catch (networkErr) {
    return null;
  }

  if (!response.ok) {
    // Refresh token is dead (revoked, expired, or user changed password).
    // Fail closed: drop the session entirely rather than keep retrying with
    // a token that will never work again.
    await clearSession();
    return null;
  }

  const data = await response.json().catch(() => null);
  if (!data) {
    await clearSession();
    return null;
  }
  return saveSession(data);
}

// Returns a session with a live (or freshly refreshed) access_token, or null
// if there is no way to get a valid session. Never throws.
async function ensureValidSession() {
  const stored = await getStoredSession();
  if (!stored) return null;

  if (Date.now() < stored.expires_at) {
    return stored;
  }
  return refreshSession();
}

async function logout() {
  const stored = await getStoredSession();
  if (stored) {
    try {
      await fetch(AUTH_LOGOUT_URL, {
        method: "POST",
        headers: {
          apikey: SUPABASE_PUBLISHABLE_KEY,
          Authorization: `Bearer ${stored.access_token}`,
        },
      });
    } catch (_networkErr) {
      // Best-effort server-side revocation. Even if this fails (offline,
      // already-expired token, etc.) we still clear the local session below
      // so the extension stops trying to use it.
    }
  }
  await clearSession();
  return { success: true };
}

async function getSessionStatus() {
  const stored = await getStoredSession();
  if (!stored) return { loggedIn: false };
  return { loggedIn: true, email: stored.email };
}

// -- capture_queue write ------------------------------------------------------

async function insertCaptureRow(payload, attemptedRefresh = false) {
  const session = await ensureValidSession();
  if (!session) {
    return {
      success: false,
      error: "Not logged in. Open the ResellOS extension icon and log in, then try capturing again.",
    };
  }

  const row = {
    user_id: session.user_id,
    retailer: payload.raw_data.retailer,
    source_url: payload.source_url,
    raw_data: payload.raw_data,
    order_number: payload.raw_data.order_number || null,
    order_date: payload.raw_data.order_date || null,
    total: payload.raw_data.total ?? null,
  };

  let response;
  try {
    response = await fetch(CAPTURE_QUEUE_URL, {
      method: "POST",
      headers: {
        apikey: SUPABASE_PUBLISHABLE_KEY,
        Authorization: `Bearer ${session.access_token}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify(row),
    });
  } catch (networkErr) {
    return { success: false, error: `Network error: ${networkErr.message}` };
  }

  if (response.status === 401 && !attemptedRefresh) {
    // Access token expired between ensureValidSession() and the request
    // landing (or was revoked). One retry after a forced refresh, then fail
    // closed -- never silently drop the capture.
    const refreshed = await refreshSession();
    if (refreshed) {
      return insertCaptureRow(payload, true);
    }
    return {
      success: false,
      error: "Session expired and could not be refreshed. Log in again via the extension popup.",
    };
  }

  if (!response.ok) {
    const errBody = await response.json().catch(() => ({}));
    return {
      success: false,
      error: errBody.message || errBody.error_description || `Write failed (${response.status})`,
    };
  }

  const data = await response.json().catch(() => null);
  return { success: true, data };
}

// -- message router ------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    switch (message.type) {
      case "GET_SESSION_STATUS":
        sendResponse(await getSessionStatus());
        break;
      case "LOGIN":
        sendResponse(await login(message.email, message.password));
        break;
      case "LOGOUT":
        sendResponse(await logout());
        break;
      case "REQUEST_PASSWORD_RESET":
        sendResponse(await requestPasswordReset(message.email));
        break;
      case "CAPTURE_ORDER":
        sendResponse(await insertCaptureRow(message.payload));
        break;
      default:
        sendResponse({ success: false, error: `Unknown message type: ${message.type}` });
    }
  })();
  return true; // keep the message channel open for the async response above
});
