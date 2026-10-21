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
    donate_url: "https://example.org/donations",
    avatar_url: ""
  },
  stats: { by_day: [{ n: 3 }, { n: 5 }, { n: 2 }, { n: 8 }, { n: 6 }] },
  streams: [
    { platform: "twitch", url: "https://www.twitch.tv/dendich", live: true, title: "Arma Reforger — в бой", viewers: 58 },
    { platform: "kick", url: "https://kick.com/dendich", live: false }
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
  assert.equal(await page.locator(".sc-channel-card").count(), 2);
  assert.equal(await page.locator(".sc-operational-stats .sc-stat").count(), 3);
  assert.equal(await page.locator(".sc-content-section").count(), 4);
  assert.equal(await page.locator(".sc-featured-live").count(), 1);
  assert.equal(await page.locator(".sc-hero-kicker").count(), 1);
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

await fs.mkdir("artifacts", { recursive: true });
try {
  await checkShowcase(1440, 900, "showcase-desktop.png");
  await checkShowcase(390, 844, "showcase-mobile.png");
  await checkAdmin();
  assert.equal(errors.length, 0, "Browser errors:\n" + errors.join("\n"));
  console.log("DENDICH: Showcase, admin, and mobile smoke checks passed.");
} finally {
  await browser.close();
}
