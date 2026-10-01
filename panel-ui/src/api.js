const boot = window.__PANEL__ || {};

let TOKEN = boot.token || localStorage.getItem("panel-token") || "";
let CSRF = localStorage.getItem("panel-csrf") || "";

export const PASSWORD_LOGIN = boot.login === "1";
export const OAUTH_ENABLED = boot.oauth === "1";

const oauthSource = typeof location.hash === "string" && location.hash.length > 1
  ? location.hash.slice(1)
  : location.search;
const oauthParams = typeof URLSearchParams === "function" ? new URLSearchParams(oauthSource) : null;
const oauthToken = oauthParams && oauthParams.get("oauth_token");
if (oauthToken) {
  TOKEN = oauthToken;
  CSRF = oauthParams.get("oauth_csrf") || "";
  localStorage.setItem("panel-token", TOKEN);
  if (CSRF) localStorage.setItem("panel-csrf", CSRF);
  history.replaceState({}, document.title, location.pathname);
}

export function token() {
  return TOKEN;
}

export function csrf() {
  return CSRF;
}

function unauthorized() {
  if (PASSWORD_LOGIN) {
    window.dispatchEvent(new CustomEvent("panel:login"));
  } else if (TOKEN) {
    location.reload();
  }
}

export async function api(url, body, method) {
  const requestMethod = method || (body ? "POST" : "GET");
  const opts = { method: requestMethod, headers: { "X-Panel-Token": TOKEN } };
  if (requestMethod !== "GET" && CSRF) opts.headers["X-Panel-CSRF"] = CSRF;
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  try {
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => ({}));
    if (r.status === 401) unauthorized();
    return { status: r.status, data };
  } catch {
    return { status: 0, data: {} };
  }
}

export async function doLogin(password) {
  const r = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  const d = await r.json().catch(() => ({}));
  if (d && d.token) {
    TOKEN = d.token;
    CSRF = d.csrf || "";
    localStorage.setItem("panel-token", TOKEN);
    if (CSRF) localStorage.setItem("panel-csrf", CSRF);
    return true;
  }
  return false;
}

export async function doLogout() {
  await api("/api/logout", null, "POST");
  localStorage.removeItem("panel-token");
  localStorage.removeItem("panel-csrf");
  location.reload();
}

export function startOauth() {
  location.href = "/oauth/discord";
}
