import { signal } from "@preact/signals";

const ACCENTS = ["#b9a47a", "#7d8869", "#c58c59", "#e1d4b7", "#8ba6ac", "#b37d72"];

export const route = signal(parseRoute());
export const navQuery = signal("");
export const navOpen = signal(false);
export const loginVisible = signal(false);
export const authed = signal(true);

export const theme = signal(localStorage.getItem("panel-theme") || "dark");
export const accent = signal(ACCENTS.includes(localStorage.getItem("panel-accent")) ? localStorage.getItem("panel-accent") : ACCENTS[0]);
export const ACCENT_LIST = ACCENTS;

function parseRoute() {
  const h = location.hash || "";
  const m = h.match(/^#\/([a-z-]+)/);
  return m ? m[1] : "overview";
}

function resetPanelScroll() {
  // The main layout scrolls inside .scroll; changing sections should start at the top.
  const panel = document.querySelector(".scroll");
  if (panel) panel.scrollTop = 0;
}

export function navigate(id) {
  if (location.hash !== "#/" + id) location.hash = "#/" + id;
  route.value = id;
  navOpen.value = false;
  resetPanelScroll();
}

window.addEventListener("hashchange", () => {
  route.value = parseRoute();
  navOpen.value = false;
  resetPanelScroll();
});

export function applyTheme() {
  document.body.dataset.theme = theme.value;
  document.body.style.setProperty("--accent", accent.value);
  document.body.style.setProperty("--accent-soft", accent.value + "26");
}

export function setTheme(t) {
  theme.value = t;
  localStorage.setItem("panel-theme", t);
  applyTheme();
}

export function setAccent(c) {
  accent.value = c;
  localStorage.setItem("panel-accent", c);
  applyTheme();
}

export const toasts = signal([]);

let toastId = 0;
export function toast(msg, ok = true) {
  const id = ++toastId;
  toasts.value = [...toasts.value, { id, msg, ok }];
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  }, 4200);
}

window.addEventListener("panel:login", () => {
  loginVisible.value = true;
});
