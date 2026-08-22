// ResellOS Capture — popup script.
// Talks only to background.js (via chrome.runtime.sendMessage), never
// directly to Supabase -- background.js owns the session and tokens.

const loginView = document.getElementById("loginView");
const loggedInView = document.getElementById("loggedInView");
const loggedInEmail = document.getElementById("loggedInEmail");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const loginBtn = document.getElementById("loginBtn");
const logoutBtn = document.getElementById("logoutBtn");
const forgotLink = document.getElementById("forgotLink");
const messageEl = document.getElementById("message");

function setMessage(text, kind) {
  messageEl.textContent = text || "";
  messageEl.className = kind || "";
}

function showLoggedIn(email) {
  loginView.style.display = "none";
  loggedInView.style.display = "block";
  loggedInEmail.textContent = email;
}

function showLoggedOut() {
  loginView.style.display = "block";
  loggedInView.style.display = "none";
}

async function refreshView() {
  const status = await chrome.runtime.sendMessage({ type: "GET_SESSION_STATUS" });
  if (status && status.loggedIn) {
    showLoggedIn(status.email);
  } else {
    showLoggedOut();
  }
}

loginBtn.addEventListener("click", async () => {
  const email = emailInput.value.trim();
  const password = passwordInput.value;
  if (!email || !password) {
    setMessage("Enter both email and password.", "error");
    return;
  }
  loginBtn.disabled = true;
  setMessage("Logging in…");
  const result = await chrome.runtime.sendMessage({ type: "LOGIN", email, password });
  loginBtn.disabled = false;
  if (result.success) {
    passwordInput.value = "";
    setMessage("Logged in.", "ok");
    showLoggedIn(result.email);
  } else {
    setMessage(result.error || "Login failed.", "error");
  }
});

logoutBtn.addEventListener("click", async () => {
  logoutBtn.disabled = true;
  await chrome.runtime.sendMessage({ type: "LOGOUT" });
  logoutBtn.disabled = false;
  setMessage("Logged out.", "ok");
  showLoggedOut();
});

forgotLink.addEventListener("click", async () => {
  const email = emailInput.value.trim();
  if (!email) {
    setMessage("Enter your email above first, then click Forgot password.", "error");
    return;
  }
  setMessage("Sending reset email…");
  const result = await chrome.runtime.sendMessage({ type: "REQUEST_PASSWORD_RESET", email });
  if (result.success) {
    setMessage("If that email has an account, a reset link was sent.", "ok");
  } else {
    setMessage(result.error || "Could not send reset email.", "error");
  }
});

refreshView();
