import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { chromium } from "playwright";

const base = process.env.PANEL_TEST_URL || "http://127.0.0.1:4173";
const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
const errors = [];
const sample = {
  ok: true,
  guild: { name: "DENDICH HQ", members: 1240, online: 107, created_days: 388 },
  bot: { name: "DENDICH" },
  settings: {
    hero_title: "Тактическое сообщество",
    about: "Игровые стримы Arma Reforger, WARDOGS, юмор и связь с чатом.",
    invite_url: "https://discord.gg/example",
    youtube_url: "https://www.youtube.com/@dendich",
    donate_url: "https://example.org/donations",
    avatar_url: ""
  },
  stats: { by_day: [{ n: 3 }, { n: 5 }, { n: 2 }, { n: 8 }, { n: 6 }] },
  streams: [
    { platform: "twitch", url: "https://www.twitch.tv/dendich", live: true, title: "Arma Reforger — в бой", viewers: 58 },
    { platform: "kick", url: "https://kick.com/dendich", live: false },
    { platform: "youtube", url: "https://www.youtube.com/@dendich", live: false, content_only: true }
  ],
  schedule: [{ title: "Сбор сообщества", send_at: "2026-10-23 20:00:00" }],
  media: [{ id: 1, title: "Наши моменты", url: "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%3E%3C/svg%3E" }],
  donors: [{ name: "Тестовый меценат", total: 100, currency: "RUB" }]
};

async function checkShowcase(width, height, file) {
  const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/public/showcase", route =>
    route.fulfill({ status: 200, contentType: "application/json; charset=utf-8", body: JSON.stringify(sample) })
  );
  await page.goto(base + "/showcase", { waitUntil: "networkidle" });
  await page.locator(".sc-command-content h1").waitFor();
  assert.match(await page.locator(".sc-command-content h1").innerText(), /DENDICH/);
  assert.equal(await page.locator(".sc-channel-card").count(), 3);
  const youtube = page.locator('.sc-channel-card[href="https://www.youtube.com/@dendich"]');
  assert.equal(await youtube.count(), 1, "YouTube must be visible as a channel card");
  assert.match(await youtube.innerText(), /ВИДЕО/);
  assert.doesNotMatch(await youtube.innerText(), /ОФЛАЙН/);
  assert.equal(await page.locator(".sc-operational-stats .sc-stat").count(), 3);
  assert.equal(await page.locator(".sc-content-section").count(), 4);
  assert.equal(await page.locator(".sc-featured-live").count(), 1);
  assert.equal(await page.locator(".sc-hero-kicker").count(), 1);
  assert.equal(await page.locator(".sc-command-emblem").count(), 0,
    "Old overlapping logo must not cover the hero illustration");
  const heroPhoto = await page.evaluate(async () => {
    const bg = getComputedStyle(document.querySelector(".sc-command-hero")).backgroundImage;
    const source = bg.match(/data:image\/webp;base64,[A-Za-z0-9+/=]+/);
    if (!source) return { loaded: false, reason: "Missing embedded WebP source" };
    const img = new Image();
    img.src = source[0];
    try {
      await img.decode();
      return { loaded: img.naturalWidth >= 500 && img.naturalHeight >= 200,
        width: img.naturalWidth, height: img.naturalHeight };
    } catch {
      return { loaded: false, reason: "Invalid WebP image" };
    }
  });
  assert.equal(heroPhoto.loaded, true,
    "The real Showcase photo should decode correctly at " + width + "px: " + JSON.stringify(heroPhoto));
  const horizontalOverflow = await page.evaluate(() =>
    document.documentElement.scrollWidth > window.innerWidth + 3
  );
  assert.equal(horizontalOverflow, false, "Unexpected horizontal scrolling on showcase at " + width + "px");
  await page.screenshot({ path: "artifacts/" + file, fullPage: true, animations: "disabled" });
  await context.close();
}

async function checkAdmin() {
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/**", route => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.goto(base + "/admin", { waitUntil: "domcontentloaded" });
  await page.locator(".brand-copy").waitFor();
  assert.match(await page.locator(".brand-copy").innerText(), /DENDICH/);
  assert.equal(await page.locator(".nav-item").count() > 15, true);
  const bodyCss = await page.evaluate(() => getComputedStyle(document.body).backgroundImage);
  assert.match(bodyCss, /radio-terrain\.svg/);
  await page.screenshot({ path: "artifacts/admin-desktop.png", fullPage: true, animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".mobile-menu").click();
  assert.equal(await page.locator(".sidebar.open").count(), 1);
  await page.screenshot({ path: "artifacts/admin-mobile.png", fullPage: true, animations: "disabled" });
  await context.close();
}

async function checkCommandCenter() {
  const context = await browser.newContext({ viewport: { width: 1280, height: 850 } });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  let board = [];
  await page.route("**/api/workboard", async route => {
    const req = route.request();
    if (req.method() === "POST") {
      const payload = req.postDataJSON();
      if (payload.action === "create") {
        board.unshift({ id: "a".repeat(32), type: payload.type, title: payload.title,
          note: payload.note, priority: payload.priority, status: "todo",
          created_at: new Date().toISOString(), updated_at: new Date().toISOString() });
      } else if (payload.action === "update") {
        board = board.map(item => item.id === payload.id ? { ...item, status: payload.status } : item);
      } else if (payload.action === "delete") {
        board = board.filter(item => item.id !== payload.id);
      }
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, items: board, limit: 120 }) });
  });
  await page.route("**/api/session", route => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ ok: true, permissions: { read: true, moderate: true, admin: true } }),
  }));
  let scheduled = [];
  await page.route("**/api/bot/channels", route => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ channels: [{ id: "123456789", name: "анонсы", category: "DENDICH" }] }),
  }));
  await page.route("**/api/schedule", async route => {
    if (route.request().method() === "POST") {
      const payload = route.request().postDataJSON();
      scheduled.push(payload);
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ ok: true, id: 77, send_at: payload.send_at }) });
    } else {
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ ok: true, upcoming: [], done: [] }) });
    }
  });
  await page.goto(base + "/admin#/command-center", { waitUntil: "networkidle" });
  await page.locator(".cc-hero h2").waitFor();
  assert.match(await page.locator(".cc-hero").innerText(), /оперативный центр/i);
  await page.locator(".cc-compose input[required]").fill("Проверить модерацию");
  await page.locator(".cc-compose button[type=submit]").click();
  await page.locator(".cc-entry").waitFor();
  assert.equal(await page.locator(".cc-entry").count(), 1);
  await page.locator(".cc-entry select").selectOption("done");
  await page.locator(".cc-entry.is-complete").waitFor();
  await page.screenshot({ path: "artifacts/command-center-desktop.png", fullPage: true, animations: "disabled" });
  await page.locator(".cc-schedule-btn").click();
  await page.locator(".scheduler-source").waitFor();
  assert.equal(await page.locator(".scroll").evaluate(el => el.scrollTop), 0,
    "Changing from workboard to scheduler must reset panel scroll");
  await page.screenshot({ path: "artifacts/publishing-desk-draft-desktop.png", fullPage: true, animations: "disabled" });
  assert.equal(await page.locator(".scheduler-source b").innerText(), "Проверить модерацию");
  assert.equal(await page.locator('input[maxlength="256"]').inputValue(), "Проверить модерацию");
  assert.equal(await page.locator(".three select").inputValue(), "");
  assert.equal(scheduled.length, 0, "Draft transfer must never publish or queue by itself");

  // A Discord channel and a future time must be explicitly selected.
  await page.getByRole("button", { name: "Запланировать", exact: true }).click();
  assert.equal(scheduled.length, 0, "No destination means no scheduled post");
  await page.locator(".three select").selectOption("123456789");
  const due = await page.evaluate(() => {
    const d = new Date(Date.now() + 2 * 86400000);
    const p = v => String(v).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  });
  await page.locator('input[type="datetime-local"]').fill(due);
  const responsePromise = page.waitForResponse(r => r.url().endsWith("/api/schedule") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Запланировать", exact: true }).click();
  await responsePromise;
  assert.equal(scheduled.length, 1);
  assert.equal(scheduled[0].channel_id, "123456789");
  assert.equal(scheduled[0].embed.title, "Проверить модерацию");
  assert.equal(await page.locator(".scheduler-source").count(), 0);
  await page.screenshot({ path: "artifacts/publishing-desk-desktop.png", fullPage: true, animations: "disabled" });

  // Scheduler can also pick an existing workboard record without route handoff.
  await page.locator(".scheduler-picker select").selectOption("a".repeat(32));
  await page.locator(".scheduler-picker button").click();
  await page.locator(".scheduler-source").waitFor();
  assert.equal(await page.locator('input[maxlength="256"]').inputValue(), "Проверить модерацию");
  assert.equal(scheduled.length, 1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".scroll").evaluate(el => { el.scrollTop = 0; });
  await page.screenshot({ path: "artifacts/publishing-desk-mobile.png", fullPage: true, animations: "disabled" });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 3), false,
    "Publishing desk overflows horizontally on phone");
  await context.close();
}

await fs.mkdir("artifacts", { recursive: true });
try {
  await checkShowcase(1440, 900, "showcase-desktop.png");
  await checkShowcase(390, 844, "showcase-mobile.png");
  await checkAdmin();
  await checkCommandCenter();
  assert.equal(errors.length, 0, "Browser errors:\n" + errors.join("\n"));
  console.log("DENDICH: Showcase, admin, and mobile smoke checks passed.");
} finally {
  await browser.close();
}
