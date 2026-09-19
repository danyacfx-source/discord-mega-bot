let TOKEN = "__PANEL_TOKEN__" || localStorage.getItem("panel-token") || "";
const PANEL_LOGIN = "__PANEL_LOGIN__" === "1";
const COLORS = {blurple: 0x5865f2, green: 0x23a55a, red: 0xf23f43, yellow: 0xf0b232, dark: 0x111214, grey: 0x96989d, orange: 0xf2780d, teal: 0x1abc9c, pink: 0xeb459e};
const hex6 = /^#?([0-9a-f]{6})$/i;
const ACCENTS = ["#5865f2", "#23a55a", "#f23f43", "#1abc9c", "#eb459e", "#f2780d"];
const TITLES = {overview: "Обзор", server: "Сервер", moderation: "Модерация", giveaways: "Розыгрыши", embed: "Эмбеды", scheduler: "Планировщик", settings: "Настройки", test: "Тест", files: "Файлы", logs: "Логи", audit: "Логи Discord", backup: "Бэкап"};
const SETTINGS_GROUPS = [
  { title: "👋 Приветствия", cols: [["welcome_channel_id", "Канал приветствий"], ["farewell_channel_id", "Канал прощаний"]] },
  { title: "🧾 Логи аудита", cols: [["log_channel_id", "Общий лог"], ["member_log_channel_id", "Лог участников"], ["message_log_channel_id", "Лог сообщений"], ["voice_log_channel_id", "Лог голосовых"], ["mod_log_channel_id", "Лог модерации"], ["bot_log_channel_id", "Лог бота"]] },
  { title: "🎟️ Тикеты", cols: [["ticket_category_id", "Категория тикетов"]] },
  { title: "💸 Донаты", cols: [["donation_channel_id", "Канал донатов"]] },
];
const MODULE_LABELS = {
  welcome: "Приветствия", role_menu: "Роль по меню", birthdays: "Дни рождения", temp_voices: "Темп-голосовые",
  donations: "Донаты", overlay: "Overlay", logs: "Логи (исключения)", kick: "Kick", twitch: "Twitch",
  automod: "Автомод", ai_chat: "AI-чат", server_stats: "Статистика сервера", seasons: "Сезоны", rules_gate: "Правила", ram_report: "Отчёт об ОЗУ",
};

let mode = "webhook";
let fields = [];
let btnRows = [[]];
let settingsLoaded = false;
let settingsData = null;
let logsTimer = null;
let auditTimer = null;
let overviewTimer = null;

const $ = (id) => document.getElementById(id);

function tag(t, cls, html) {
  const el = document.createElement(t);
  if (cls) el.className = cls;
  if (html !== undefined) el.innerHTML = html;
  return el;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg, ok) {
  const t = tag("div", "toast " + (ok ? "ok" : "bad"), escapeHtml(msg));
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

async function api(url, body, method) {
  const opts = { method: method || (body ? "POST" : "GET"), headers: { "X-Panel-Token": TOKEN } };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  try {
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => ({}));
    if (r.status === 401) {
      if (PANEL_LOGIN) showLogin();
      else if (TOKEN) location.reload();
    }
    return { status: r.status, data };
  } catch (e) {
    return { status: 0, data: {} };
  }
}

async function doLogin() {
  const r = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: $("login_pw").value }),
  });
  const d = await r.json().catch(() => ({}));
  if (d && d.token) {
    TOKEN = d.token;
    localStorage.setItem("panel-token", d.token);
    $("login_pw").value = "";
    hideLogin();
    bootInit();
    toast("✅ Добро пожаловать", true);
    return true;
  }
  toast("❌ Неверный пароль", false);
  return false;
}

function showLogin() {
  $("login").style.display = "flex";
  if ($("login_pw")) $("login_pw").focus();
}
function hideLogin() {
  $("login").style.display = "none";
}

async function logout() {
  await api("/api/logout", null, "POST");
  localStorage.removeItem("panel-token");
  location.reload();
}

async function uploadFile(file, targetId) {
  if (!file) return;
  if (!/\.(png|jpe?g|gif|webp)$/i.test(file.name)) return toast("Формат не поддерживается: " + file.name, false);
  if (file.size > 8 * 1024 * 1024) return toast("Файл больше 8 МБ", false);
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/upload", { method: "POST", headers: { "X-Panel-Token": TOKEN }, body: fd });
  const d = await r.json().catch(() => ({}));
  if (r.status === 401) {
    if (PANEL_LOGIN) showLogin(); else if (TOKEN) location.reload();
  }
  if (d && d.ok && d.url) { $(targetId).value = d.url; renderPreview(); toast("✅ Картинка загружена", true); }
  else toast(d.error ? "❌ " + d.error : "❌ Ошибка загрузки картинки", false);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("✅ Скопировано", true);
  } catch (e) {
    toast("❌ Не удалось скопировать", false);
  }
}

/* --- тема --- */
let theme = localStorage.getItem("panel-theme") || "dark";
let accent = localStorage.getItem("panel-accent") || ACCENTS[0];
function applyTheme() {
  document.body.dataset.theme = theme;
  document.body.style.setProperty("--accent", accent);
  document.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b.dataset.theme === theme));
  document.querySelectorAll(".accent-dot").forEach((d) => d.classList.toggle("active", d.dataset.color === accent));
}
function buildAccents() {
  const box = $("accents");
  box.innerHTML = "";
  ACCENTS.forEach((c) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "accent-dot"; b.dataset.color = c;
    b.style.background = c;
    b.onclick = () => { accent = c; localStorage.setItem("panel-accent", c); applyTheme(); };
    box.appendChild(b);
  });
}
document.querySelectorAll(".seg-btn").forEach((b) => {
  b.addEventListener("click", () => { theme = b.dataset.theme; localStorage.setItem("panel-theme", theme); applyTheme(); });
});

/* --- навигация --- */
document.querySelectorAll(".nav-item").forEach((b) => {
  b.addEventListener("click", () => switchSection(b.dataset.section));
});
document.querySelectorAll(".quick-link").forEach((a) => {
  a.addEventListener("click", () => switchSection(a.dataset.goto));
});
function switchSection(name) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.section === name));
  document.querySelectorAll(".section").forEach((s) => s.classList.toggle("active", s.id === "sec-" + name));
  $("section-title").textContent = TITLES[name] || name;
  if (name === "settings" && !settingsLoaded) loadSettings();
  if (name === "test") loadTestChannels();
  if (name === "embed") renderPreview();
  if (name === "logs") { loadLogs(); startLogsTimer(); }
  else stopLogsTimer();
  if (name === "audit") { loadAudit(); startAuditTimer(); }
  else stopAuditTimer();
  if (name === "files") loadFiles();
  if (name === "overview") startOverviewTimer();
  else stopOverviewTimer();
  if (name === "server" && !srvLoaded) loadServer();
  if (name === "moderation") loadModeration();
  if (name === "giveaways") loadGiveaways();
  if (name === "scheduler") loadScheduler();
  if (name === "backup") loadBackup();
}

function resolveColor(str) {
  if (!str) return null;
  const s = String(str).trim().toLowerCase();
  if (COLORS[s] !== undefined) return COLORS[s];
  const m = hex6.exec(s);
  if (m) return parseInt(m[1], 16);
  return null;
}

function renderColor() {
  const c = resolveColor($("f_color").value);
  const el = document.getElementById("colsw");
  if (el) el.style.background = c === null ? "transparent" : "#" + c.toString(16).padStart(6, "0");
  const picker = document.getElementById("f_color_picker");
  if (picker) picker.value = c === null ? "#5865f2" : "#" + c.toString(16).padStart(6, "0");
}
function pickColor(hex) {
  const c = resolveColor(hex);
  if (c === null) return;
  const text = document.getElementById("f_color");
  if (text) text.value = "#" + c.toString(16).padStart(6, "0");
  renderColor();
  renderPreview();
}

/* --- обзор --- */
async function loadOverview() {
  const r = await api("/api/overview");
  const d = r.data || {};
  const online = !!d.bot_online;
  const st = $("status");
  $("ov_status").textContent = online ? "Онлайн" : "Офлайн";
  $("ov_status").className = "badge " + (online ? "ok" : "off");
  st.textContent = online ? ("бот онлайн: " + (d.bot_name || "—")) : "бот офлайн";
  st.className = "badge " + (online ? "ok" : "off");
  $("guildname").textContent = d.guild && d.guild.name ? "сервер: " + d.guild.name : "";
  $("ov_uptime").textContent = d.uptime || "—";
  $("ov_ping").textContent = (d.latency_ms !== undefined ? String(d.latency_ms) : "—") + " мс";
  $("ov_mem").textContent = d.mem_mb !== undefined ? d.mem_mb + " МБ" : "—";
  $("ov_guild").textContent = d.guild ? d.guild.name : "—";
  $("ov_members").textContent = d.guild ? String(d.guild.members) : "—";
  $("ov_online").textContent = d.guild ? String(d.guild.online) : "—";
  $("ov_channels").textContent = d.guild ? String(d.guild.channels) + " / " + String(d.guild.roles) : "—";
  if (d.bot_name) {
    $("ov_botname").textContent = "Бот: " + d.bot_name;
    $("panel-name").textContent = d.bot_name;
    document.title = "Панель — " + d.bot_name;
  }
  loadMonitorSparks();
}
function startOverviewTimer() {
  if (overviewTimer) return;
  overviewTimer = setInterval(() => {
    if (document.hidden) return;
    if (!$("sec-overview").classList.contains("active")) return;
    loadOverview();
  }, 15000);
}
function stopOverviewTimer() {
  if (overviewTimer) { clearInterval(overviewTimer); overviewTimer = null; }
}

/* --- каналы --- */
async function loadChannels() {
  const r = await api("/api/bot/channels");
  const list = (r.data && r.data.channels) || [];
  const sel = $("sel_channel");
  sel.innerHTML = "";
  if (list.length === 0) {
    const o = document.createElement("option");
    o.value = ""; o.textContent = "Нет каналов";
    sel.appendChild(o);
    return;
  }
  list.forEach((ch) => {
    const o = document.createElement("option");
    o.value = ch.id;
    o.textContent = ch.name || ch.id;
    sel.appendChild(o);
  });
}
async function refreshChannels() {
  toast("Загрузка каналов…");
  await loadChannels();
}
/* --- конструктор эмбедов --- */
function setMode(m) {
  mode = m;
  const wb = $("mode-webhook"), bb = $("mode-bot");
  if (wb) wb.classList.toggle("active", m === "webhook");
  if (bb) bb.classList.toggle("active", m === "bot");
  $("block-webhook").style.display = m === "webhook" ? "" : "none";
  $("block-bot").style.display = m === "bot" ? "" : "none";
  if (m === "bot") loadChannels();
}

function renderButtons() {
  const box = $("btn_editor");
  box.innerHTML = "";
  if (btnRows.length === 0) btnRows = [[]];
  btnRows.forEach((row, ri) => {
    const line = tag("div", "btn-row");
    const t = tag("div", "inlinebox", "Ряд " + (ri + 1) + ":");
    line.appendChild(t);
    row.forEach((btn, bi) => {
      const l = tag("input", null);
      l.type = "text"; l.placeholder = "Текст"; l.value = btn.label; l.maxLength = 80;
      l.oninput = () => { btn.label = l.value; renderPreview(); };
      const u = tag("input", null);
      u.type = "url"; u.placeholder = "URL (стиль Ссылка)"; u.value = btn.url || ""; u.maxLength = 255;
      u.oninput = () => { btn.url = u.value.trim(); renderPreview(); };
      const s = tag("select", null);
      ["Primary", "Secondary", "Success", "Danger", "Link"].forEach((n, k) => {
        const o = document.createElement("option");
        o.value = String(k + 1); o.textContent = n;
        s.appendChild(o);
      });
      s.value = String(btn.style || 2);
      s.onchange = () => { btn.style = parseInt(s.value, 10); renderPreview(); };
      const del = tag("button", "btn mini", "✖");
      del.type = "button"; del.title = "Удалить кнопку";
      del.onclick = () => { row.splice(bi, 1); renderButtons(); renderPreview(); };
      line.append(l, u, s, del);
    });
    box.appendChild(line);
  });
}
function addButton() {
  let row = btnRows[btnRows.length - 1];
  if (!row || row.length >= 5) {
    if (btnRows.length >= 5) return toast("Максимум 5 рядов", false);
    row = [];
    btnRows.push(row);
  }
  row.push({ label: "Кнопка", style: 2, url: "" });
  renderButtons(); renderPreview();
}
function addButtonRow() {
  if (btnRows.length >= 5) return toast("Максимум 5 рядов", false);
  btnRows.push([]);
  renderButtons();
}

function renderFields() {
  const box = $("fields");
  box.innerHTML = "";
  if (fields.length === 0) box.appendChild(tag("div", "hint muted", "Поля не добавлены"));
  fields.forEach((f, i) => {
    const item = tag("div", "field-item");
    const row = tag("div", "row");
    const n = tag("input", null);
    n.type = "text"; n.placeholder = "Название"; n.value = f.name; n.maxLength = 256;
    n.oninput = () => { f.name = n.value; renderPreview(); };
    const v = tag("input", null);
    v.type = "text"; v.placeholder = "Значение"; v.value = f.value; v.maxLength = 1024;
    v.oninput = () => { f.value = v.value; renderPreview(); };
    const inl = tag("select", null);
    ["В ряд", "В столбец"].forEach((t, k) => {
      const o = document.createElement("option");
      o.value = String(k); o.textContent = t;
      inl.appendChild(o);
    });
    inl.value = String(f.inline ? 1 : 0);
    inl.onchange = () => { f.inline = inl.value === "1"; renderPreview(); };
    const del = tag("button", "btn mini", "✖");
    del.type = "button"; del.title = "Удалить поле";
    del.onclick = () => { fields.splice(i, 1); renderFields(); renderPreview(); };
    row.append(n, v, inl, del);
    item.appendChild(row);
    box.appendChild(item);
  });
}
function addField() {
  if (fields.length >= 25) return toast("Максимум 25 полей", false);
  fields.push({ name: "Поле", value: "Описание", inline: false });
  renderFields(); renderPreview();
}

function readEmbed() {
  const e = {};
  const t = $("f_title").value.trim().slice(0, 256);
  const d = $("f_desc").value.trim().slice(0, 4000);
  if (t) e.title = t;
  if (d) e.description = d;
  const co = resolveColor($("f_color").value);
  if (co !== null) e.color = co;
  const an = $("f_author_name").value.trim().slice(0, 256);
  if (an) e.author = { name: an, icon_url: $("f_author_icon").value.trim().slice(0, 2048) || undefined, url: $("f_author_url").value.trim().slice(0, 2048) || undefined };
  const ft = $("f_footer_text").value.trim().slice(0, 2048);
  if (ft) e.footer = { text: ft, icon_url: $("f_footer_icon").value.trim().slice(0, 2048) || undefined };
  const im = $("f_image").value.trim().slice(0, 2048);
  if (im) e.image = { url: im };
  const th = $("f_thumb").value.trim().slice(0, 2048);
  if (th) e.thumbnail = { url: th };
  const fs = fields.slice(0, 25).filter((f) => f.name.trim() || f.value.trim());
  if (fs.length) e.fields = fs.map((f) => ({ name: f.name.trim().slice(0, 256), value: f.value.trim().slice(0, 1024), inline: !!f.inline }));
  if (Object.keys(e).length === 0) return null;
  return e;
}
function buildPayload() {
  const embed = readEmbed();
  const isBot = mode === "bot";
  const p = {
    content: ($("f_content").value || "").slice(0, 2000) || null,
    embeds: embed ? [embed] : [],
    components: btnRows.filter((r) => r.length),
  };
  if (isBot) p.channel_id = $("sel_channel").value;
  else p.webhook_url = $("wh_url").value;
  return p;
}
async function sendMsg() {
  const payload = buildPayload();
  const target = mode === "bot" ? payload.channel_id : payload.webhook_url;
  if (!target) return toast(mode === "bot" ? "Укажите канал" : "Укажите Webhook URL", false);
  if (payload.embeds.length === 0 && !payload.content) return toast("Пустое сообщение", false);
  const r = await api("/api/" + (mode === "bot" ? "bot/send" : "webhook/send"), payload);
  if (r.status === 200 && r.data.ok) {
    toast("✅ Отправлено", true);
    if (mode === "bot") loadMsg();
  } else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}
async function editMsg() {
  const mid = $("msg_id").value.trim();
  if (!mid) return toast("Укажите ID сообщения", false);
  const payload = buildPayload();
  const target = mode === "bot" ? payload.channel_id : payload.webhook_url;
  if (!target) return toast(mode === "bot" ? "Укажите канал" : "Укажите Webhook URL", false);
  payload.message_id = mid;
  const r = await api("/api/" + (mode === "bot" ? "bot/edit" : "webhook/edit"), payload);
  if (r.status === 200 && r.data.ok) toast("✅ Сообщение изменено", true);
  else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}
function clearBuilder() {
  fields = [];
  btnRows = [[]];
  ["f_content", "f_title", "f_desc", "f_color", "f_author_name", "f_author_icon", "f_author_url", "f_footer_text", "f_footer_icon", "f_image", "f_thumb"].forEach((id) => { $(id).value = ""; });
  $("f_ts").checked = false;
  renderFields(); renderButtons(); renderPreview();
  toast("🧹 Поля очищены", true);
}
async function loadMsg() {
  const mid = $("msg_id").value.trim().replace(/^https:\/\/discord(a)?\.com\/channels\/\d+\/\d+\//, "");
  if (!mid) return toast("Укажите ID сообщения", false);
  const payload = { message_id: mid };
  if (mode === "bot") {
    payload.channel_id = $("sel_channel").value;
    if (!payload.channel_id) return toast("Укажите канал", false);
  } else {
    payload.webhook_url = $("wh_url").value;
    if (!payload.webhook_url) return toast("Укажите Webhook URL", false);
  }
  const r = await api("/api/" + (mode === "bot" ? "bot/fetch" : "webhook/fetch"), payload);
  if (r.status !== 200 || !r.data.ok || !r.data.data) return toast("❌ Сообщение не найдено", false);
  fillEmbed(r.data.data);
  toast("✅ Загружено в конструктор", true);
}
function fillEmbed(msg) {
  const em = (msg.embeds && msg.embeds[0]) ? msg.embeds[0] : null;
  $("f_content").value = msg.content || "";
  const c = $("f_color"); c.value = (em && em.color) ? em.color : ""; renderColor();
  $("f_title").value = (em && em.title) ? em.title : "";
  $("f_desc").value = (em && em.description) ? em.description : "";
  const a = (em && em.author) ? em.author : {};
  $("f_author_name").value = a.name || "";
  $("f_author_icon").value = a.icon_url || "";
  $("f_author_url").value = a.url || "";
  const fo = (em && em.footer) ? em.footer : {};
  $("f_footer_text").value = fo.text || "";
  $("f_footer_icon").value = fo.icon_url || "";
  $("f_image").value = (em && em.image && em.image.url) ? em.image.url : "";
  $("f_thumb").value = (em && em.thumbnail && em.thumbnail.url) ? em.thumbnail.url : "";
  fields = (em && em.fields) ? em.fields.map((f) => ({ name: f.name || "", value: f.value || "", inline: !!f.inline })) : [];
  btnRows = msg.components && msg.components.length ? msg.components : [[]];
  renderFields(); renderButtons(); renderPreview();
}

function renderPreview() {
  const box = $("preview");
  const c = resolveColor($("f_color").value);
  const colorHex = c === null ? "#5865f2" : "#" + c.toString(16).padStart(6, "0");
  const content = ($("f_content").value || "").trim();
  const title = $("f_title").value.trim();
  const desc = $("f_desc").value.trim();
  const an = $("f_author_name").value.trim();
  const ft = $("f_footer_text").value.trim();
  const im = $("f_image").value.trim();
  const th = $("f_thumb").value.trim();
  if (!content && !title && !desc && !an && !ft && !im && $("f_color").value.trim() === "" && fields.length === 0 && btnRows.every((r) => r.length === 0)) {
    box.innerHTML = '<div class="empty">Заполните форму, чтобы увидеть предпросмотр</div>';
    return;
  }
  let html = "";
  if (content) html += '<div class="content-preview">' + escapeHtml(content) + "</div>";
  html += '<div class="embed-card" style="border-left-color:' + colorHex + '">';
  if (an) html += '<div class="embed-author">' + escapeHtml(an) + (th ? '<img class="embed-thumb" src="' + escapeHtml(th) + '" alt="">' : "") + "</div>";
  if (title) html += '<div class="embed-title">' + escapeHtml(title) + "</div>";
  if (desc) html += '<div class="embed-desc">' + escapeHtml(desc) + "</div>";
  const view = (obj) => escapeHtml(obj);
  if (fields.length) {
    html += '<div class="fields">';
    fields.forEach((f) => {
      html += '<div class="fname">' + view(f.name) + "</div><div class=\"fvalue\">" + view(f.value) + "</div>";
    });
    html += "</div>";
  }
  if (im) html += '<img class="embed-image" src="' + escapeHtml(im) + '" alt="">';
  if (ft) html += '<div class="embed-footer">' + view(ft) + "</div>";
  if ($("f_ts").checked) html += '<div class="embed-ts">' + new Date().toLocaleString("ru-RU") + "</div>";
  html += "</div>";
  if (btnRows.some((r) => r.length)) {
    html += "<div style=\"margin-top:8px\">";
    btnRows.filter((r) => r.length).forEach((row) => {
      html += "<div style=\"display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap\">";
      row.forEach((b) => {
        const style = b.style === 5 ? "link" : "s" + (b.style || 2);
        html += b.style === 5
          ? '<a class="btn ' + style + '" style="text-decoration:none" href="' + escapeHtml(b.url || "#") + '" target="_blank" rel="noopener">' + view(b.label || "Кнопка") + "</a>"
          : '<span class="btn ' + style + '">' + view(b.label || "Кнопка") + "</span>";
      });
      html += "</div>";
    });
    html += "</div>";
  }
  box.innerHTML = html;
}
/* --- настройки --- */
async function loadSettings() {
  const r = await api("/api/settings");
  if (r.status !== 200 || !r.data.ok) { toast("❌ Не удалось загрузить настройки", false); return; }
  settingsData = r.data;
  settingsLoaded = true;
  renderSettings();
  renderModules();
  const am = $("set_automod_enabled");
  am.checked = !!r.data.automod_enabled;
  $("set_blocked_words").value = (r.data.blocked_words || []).join("\n");
}
function channelName(id) {
  if (!id) return "";
  const all = (settingsData && (settingsData.channels || [])) || [];
  for (const c of all) if (c.id === String(id)) return c.name;
  return String(id);
}
function renderSettings() {
  const box = $("settings-groups");
  box.innerHTML = "";
  SETTINGS_GROUPS.forEach((g) => {
    const card = tag("div", "set-group");
    const h = tag("h4", null, g.title);
    card.appendChild(h);
    g.cols.forEach(([col, label]) => {
      const lb = tag("label", "field", label);
      const sel = document.createElement("select");
      const empty = document.createElement("option");
      empty.value = ""; empty.textContent = "* автовыбор (не задано)";
      sel.appendChild(empty);
      (settingsData.channels || []).forEach((ch) => {
        const o = document.createElement("option");
        o.value = ch.id; o.textContent = (ch.category ? ch.category + " / " : "") + ch.name;
        sel.appendChild(o);
      });
      const saved = (settingsData.settings && settingsData.settings[col]) || "";
      if (saved) sel.value = String(saved);
      sel.dataset.col = col;
      sel.onchange = () => { sel.classList.add("touched"); };
      card.append(lb, sel);
    });
    box.appendChild(card);
  });
  renderEffectiveLogs();
}
function renderEffectiveLogs() {
  const effBox = $("effective-logs");
  if (!effBox) return;
  effBox.innerHTML = "";
  const eff = (settingsData && settingsData.effective_logs) || {};
  const names = { log: "Общий лог", member: "Лог участников", message: "Лог сообщений", voice: "Лог голосовых", mod: "Лог модерации", bot: "Лог бота" };
  const keys = Object.keys(names);
  if (keys.every((k) => !eff[k])) {
    effBox.appendChild(tag("div", "muted", "Не задано"));
    return;
  }
  keys.forEach((k) => {
    const v = eff[k];
    const line = tag("div", "kv", null);
    line.append(tag("b", null, escapeHtml(names[k]) + ": "));
    line.append(document.createTextNode(v ? escapeHtml(channelName(v)) + " (#" + v + ")" : "не задан"));
    effBox.appendChild(line);
  });
}
async function saveSettings() {
  const payload = {};
  document.querySelectorAll("#settings-groups select[data-col]").forEach((sel) => {
    payload[sel.dataset.col] = sel.value || "";
  });
  payload.automod_enabled = $("set_automod_enabled").checked;
  payload.blocked_words = $("set_blocked_words").value;
  const r = await api("/api/settings", payload);
  if (r.status === 200 && r.data.ok) toast("✅ Настройки сохранены", true);
  else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка сохранения", false);
}
function renderModules() {
  const box = $("modules-grid");
  box.innerHTML = "";
  const modules = (settingsData && settingsData.modules) || {};
  const entries = Object.entries(modules);
  if (entries.length === 0) {
    box.appendChild(tag("div", "muted", "Модули не найдены в .env"));
    return;
  }
  entries.forEach(([key, mod]) => {
    const card = tag("div", "module-card");
    const h = tag("h5", null, escapeHtml(MODULE_LABELS[key] || key) + '<span class="mod-env">.env</span>');
    card.appendChild(h);
    const vals = (Array.isArray(mod) ? mod : [mod]).slice(0, 3);
    vals.forEach((v) => {
      const kv = tag("div", "kv", null);
      const prefix = typeof v === "object" && v && v.name ? v.name + ": " : "";
      kv.append(tag("b", null, escapeHtml(prefix + String(v && v.name ? v.name : v))));
      card.appendChild(kv);
    });
    box.appendChild(card);
  });
}

/* --- тест --- */
async function loadTestChannels() {
  const r = await api("/api/bot/channels");
  const list = (r.data && r.data.channels) || [];
  const sel = $("test_channel");
  sel.innerHTML = "";
  if (list.length === 0) {
    const o = document.createElement("option");
    o.value = ""; o.textContent = "Нет каналов";
    sel.appendChild(o);
    return;
  }
  list.forEach((ch) => {
    const o = document.createElement("option");
    o.value = ch.id; o.textContent = ch.name || ch.id;
    sel.appendChild(o);
  });
}
async function sendTest() {
  const channel_id = $("test_channel").value;
  const content = $("test_content").value.trim();
  if (!channel_id) return toast("Выберите канал", false);
  if (!content) return toast("Введите текст", false);
  const r = await api("/api/bot/send", { channel_id, content: content.slice(0, 2000), embeds: [] });
  $("test_result").textContent = r.status === 200 && r.data.ok ? "✅ Отправлено" : ("❌ " + (r.data.error || "Ошибка"));
}

/* --- мониторинг (мини-графики) --- */
function drawSpark(id, series, color) {
  const c = $(id);
  if (!c) return;
  const dpr = window.devicePixelRatio || 1;
  const w = (c.parentElement.clientWidth || 280) * dpr;
  const h = 56 * dpr;
  if (c.width !== w) c.width = w;
  if (c.height !== h) c.height = h;
  const ctx = c.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  const vals = (series || []).map((p) => Number(p && p.v)).filter((v) => Number.isFinite(v));
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2 * dpr; ctx.lineJoin = "round"; ctx.lineCap = "round";
  if (vals.length === 0) {
    ctx.font = (11 * dpr) + "px Segoe UI";
    ctx.fillStyle = "rgba(152,160,179,.7)";
    ctx.textAlign = "center";
    ctx.fillText("нет данных", w / 2, h / 2);
    return;
  }
  let min = Math.min(...vals), max = Math.max(...vals);
  if (max === min) { max = min + 1; min = min - 1; }
  const pad = 6 * dpr;
  const px = (i) => pad + (vals.length <= 1 ? 0 : i * (w - pad * 2) / (vals.length - 1));
  const py = (v) => h - pad - (v - min) / (max - min) * (h - pad * 2);
  ctx.beginPath();
  vals.forEach((v, i) => (i === 0 ? ctx.moveTo(px(i), py(v)) : ctx.lineTo(px(i), py(v))));
  ctx.stroke();
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, color + "44"); grad.addColorStop(1, color + "00");
  ctx.lineTo(px(vals.length - 1), h); ctx.lineTo(px(0), h); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();
  const cur = vals[vals.length - 1];
  ctx.beginPath(); ctx.arc(px(vals.length - 1), py(cur), 3 * dpr, 0, Math.PI * 2); ctx.fill();
}
async function loadMonitorSparks() {
  const r = await api("/api/monitor");
  const d = r.data || {};
  drawSpark("spark_lat", d.latency || [], "#23a55a");
  drawSpark("spark_mem", d.mem || [], "#f2780d");
  drawSpark("spark_online", d.online || [], "#5865f2");
  const set = (id, v) => { const el = $(id); if (el) el.textContent = v; };
  const lastOf = (arr) => Array.isArray(arr) && arr.length ? arr[arr.length - 1].v : null;
  set("spark_lat_num", d.latency_ms != null ? d.latency_ms + " мс" : (lastOf(d.latency) != null ? lastOf(d.latency) + " мс" : "—"));
  set("spark_mem_num", d.mem_mb != null ? d.mem_mb + " МБ" : (lastOf(d.mem) != null ? lastOf(d.mem) + " МБ" : "—"));
  const onl = d.guild && d.guild.online != null ? d.guild.online : lastOf(d.online);
  set("spark_online_num", onl != null ? String(onl) : "—");
  const last = $("mon_last");
  if (last) last.textContent = r.status === 200 ? "· обновлено " + new Date().toLocaleTimeString("ru-RU") : "";
}

/* --- сервер --- */
let srvLoaded = false;
let srvCat = [];
let srvMembersFull = [];
let srvRoles = [];
function fmtCount(n) { return n >= 1000 ? (n / 1000).toFixed(1).replace(".", ",") + "k" : String(n); }
function relTime(iso) {
  const d = new Date(iso); if (isNaN(d)) return iso;
  const s = Math.round((d - Date.now()) / 1000), sign = s < 0 ? -1 : 1, a = Math.abs(s);
  const txt = a < 60 ? a + " с" : a < 3600 ? Math.floor(a / 60) + " мин" : a < 86400 ? Math.floor(a / 3600) + " ч" : Math.floor(a / 86400) + " д";
  return (sign < 0 ? "через " : a > 0 ? "" : "сейчас") + txt;
}
async function loadServer() {
  const r = await api("/api/server");
  if (r.status !== 200 || !r.data.ok) { $("srv_head").innerHTML = '<div class="muted">Не удалось загрузить сервер</div>'; return; }
  srvLoaded = true;
  const d = r.data.guild || {};
  srvCat = r.data.categories || [];
  srvRoles = r.data.roles || [];
  $("srv_head").innerHTML =
    '<div class="guild-hero">' +
    (d.icon ? '<img src="' + escapeHtml(d.icon) + '" alt="">' : '<div class="brand-ic" style="width:64px;height:64px;line-height:64px;font-size:28px">' + escapeHtml((d.name || "?").charAt(0).toUpperCase()) + "</div>") +
    "<div>" +
    '<h4>' + escapeHtml(d.name || "—") + (d.level ? ' <span class="chip">' + escapeHtml(d.level) + "</span>" : "") + "</h4>" +
    (d.description ? '<p>' + escapeHtml(d.description) + "</p>" : "") +
    '<div class="row-actions" style="margin-top:6px">' +
    '<span class="chip">Участников <b>' + fmtCount(d.members || 0) + "</b></span>" +
    '<span class="chip">Онлайн <b>' + fmtCount(d.online || 0) + "</b></span>" +
    '<span class="chip">Бустов <b>' + fmtCount(d.boosts || 0) + "</b></span>" +
    '<span class="chip">Каналов <b>' + (d.channels || 0) + "</b></span>" +
    '<span class="chip">Ролей <b>' + (d.roles || 0) + "</b></span>" +
    (d.owner ? '<span class="chip">Владелец <b>' + escapeHtml(d.owner) + "</b></span>" : "") +
    "</div>" +
    '<div class="row-actions" style="margin-top:6px">' +
    (d.created_at ? '<span class="chip">Создан ' + new Date(d.created_at).toLocaleDateString("ru-RU") + "</span>" : "") +
    (d.me_permissions || []).map((p) => '<span class="chip">Бот: ' + escapeHtml(p) + "</span>").join("") +
    "</div>" +
    "</div></div>";
  renderChannelsTree();
  renderRoles();
  fillRoleSelect();
  loadServerMembers();
}
function renderChannelsTree() {
  const box = $("srv_channels");
  box.innerHTML = "";
  if (!srvCat.length) { box.appendChild(tag("div", "muted", "Каналы недоступны")); return; }
  srvCat.forEach((cat) => {
    box.appendChild(tag("div", "cat-name", escapeHtml(cat.name || "Без категории")));
    cat.channels.forEach((ch) => {
      const isV = ch.type === "voice";
      const row = tag("div", "channel-row");
      row.title = "Клик — копировать ID";
      row.onclick = () => copyText(ch.id);
      row.innerHTML =
        '<span class="ic">' + (isV ? "🔊" : "#") + "</span>" +
        '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHtml(ch.name) + "</span>" +
        (ch.nsfw ? '<span class="chip">NSFW</span>' : "") +
        (ch.slowmode ? '<span class="chip small">' + ch.slowmode + " с</span>" : "") +
        (isV ? '<span class="chip small">' + (ch.voice_online || 0) + " 🎤</span>" : "");
      box.appendChild(row);
      if (isV && ch.voice_users && ch.voice_users.length) {
        box.appendChild(tag("div", "vc-users", "🎤 " + ch.voice_users.map((u) => escapeHtml(u.display_name)).join(", ")));
      }
    });
  });
}
function renderRoles() {
  const box = $("srv_roles");
  box.innerHTML = "";
  if (!srvRoles.length) { box.appendChild(tag("div", "muted", "Роли недоступны")); return; }
  srvRoles.forEach((role) => {
    const line = tag("div", "listline");
    line.title = "Клик — копировать ID";
    line.onclick = () => copyText(role.id);
    line.innerHTML =
      '<span class="pill-role" style="background:' + escapeHtml(role.color) + "22;color:" + escapeHtml(role.color) + '">●</span>' +
      '<span class="grow">' + escapeHtml(role.name) + (role.managed ? ' <span class="chip">интегрированная</span>' : "") + "</span>" +
      (role.hoist ? '<span class="chip">в списке</span>' : "") +
      '<span class="chip">' + fmtCount(role.member_count) + "</span>";
    box.appendChild(line);
  });
}
function fillRoleSelect() {
  const sel = $("role_select");
  sel.innerHTML = "";
  srvRoles.forEach((role) => {
    const o = document.createElement("option");
    o.value = role.id; o.textContent = role.name;
    sel.appendChild(o);
  });
}
async function loadServerMembers() {
  const r = await api("/api/server/members?q=");
  const list = (r.data && r.data.members) || [];
  srvMembersFull = list;
  ["member_list", "member_list_mod"].forEach((id) => {
    const dl = $(id);
    if (!dl) return;
    dl.innerHTML = "";
    list.forEach((m) => {
      const o = document.createElement("option");
      o.value = m.is_bot ? m.name + " (бот) #" + m.id : m.display_name + " #" + m.id;
      dl.appendChild(o);
    });
  });
}
async function roleAction(act) {
  const member = $("role_member").value.trim();
  const role = $("role_select").value;
  $("role_result").textContent = "";
  if (!member) return toast("Укажите участника", false);
  if (!role) return toast("Укажите роль", false);
  const r = await api("/api/server/members/roles", { member, role_id: role, action: act });
  if (r.status === 200 && r.data.ok) {
    $("role_result").textContent = (act === "add" ? "✅ Роль выдана" : "✅ Роль снята") + ": " + r.data.member_name + " → " + r.data.role_name;
    loadServerMembers();
    toast(r.data.applied ? "✅ Готово" : "ℹ️ Уже в таком состоянии", r.data.applied);
  } else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}

/* --- модерация --- */
let allWarns = [];
let modMember = null;
async function loadModeration() {
  loadServerMembers();
  loadWarns();
  const info = $("mod_member");
  if (info) info.textContent = "Введите участника и нажмите «Найти».";
  $("mod_actions").style.display = "none";
}
async function loadWarns() {
  const r = await api("/api/moderation/warns");
  allWarns = (r.data && r.data.warns) || [];
  renderWarns();
}
function renderWarns() {
  const box = $("warns_box");
  const q = ($("warn_search").value || "").toLowerCase().trim();
  box.innerHTML = "";
  const list = q ? allWarns.filter((w) => (w.user_name || "").toLowerCase().includes(q) || (w.user_id || "").includes(q)) : allWarns;
  $("warns_total").textContent = list.length ? "· всего: " + list.length : "";
  if (!list.length) { box.appendChild(tag("div", "muted", "Предупреждений нет")); return; }
  list.forEach((w) => {
    const line = tag("div", "listline");
    line.innerHTML =
      '<span class="chip" style="background:rgba(242,63,67,.14);color:#f23f43">#' + w.id + "</span>" +
      '<span class="grow"><b>' + escapeHtml(w.user_name || w.user_id) + '</b> <span class="sub">· модератор: ' + escapeHtml(w.moderator_name || w.moderator_id) + "</span></span>" +
      '<span class="sub">' + new Date(w.created_at).toLocaleString("ru-RU") + "</span>" +
      '<span class="sub" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1">' + escapeHtml(w.reason) + "</span>";
    const del = tag("button", "btn mini danger", "✖");
    del.type = "button"; del.title = "Снять предупреждение";
    del.onclick = async () => {
      const rr = await api("/api/moderation/warns/" + w.id, null, "DELETE");
      if (rr.status === 200 && rr.data.ok) { toast("✅ Предупреждение #" + w.id + " снято", true); loadWarns(); if (modMember) refreshModMember(); }
      else toast("❌ Не удалось снять", false);
    };
    line.appendChild(del);
    box.appendChild(line);
  });
}
async function findMember(query) {
  if (!query) return null;
  const r = await api("/api/server/members?q=" + encodeURIComponent(query));
  const list = (r.data && r.data.members) || [];
  if (list.length === 1) return list[0];
  const q = query.toLowerCase();
  const exact = list.find((m) => m.display_name.toLowerCase() === q || m.name.toLowerCase() === q || m.id === query.replace(/[#\s]/g, ""));
  return exact || (list.length ? list[0] : null);
}
async function loadModMember() {
  const v = $("mod_target").value.trim();
  if (!v) return toast("Введите участника", false);
  const m = await findMember(v);
  if (!m) { $("mod_member").textContent = "Участник не найден."; $("mod_actions").style.display = "none"; return; }
  modMember = m;
  $("mod_member").innerHTML = "";
  const p = $("mod_member");
  const line = tag("div", "listline");
  line.innerHTML =
    '<img class="av" src="' + escapeHtml(m.avatar) + '" alt="">' +
    '<span class="grow"><b>' + escapeHtml(m.display_name) + '</b> <span class="sub">' + escapeHtml(m.name) + " # " + m.id + "</span></span>" +
    '<span class="chip" style="color:' + escapeHtml(m.top_role_color) + '">' + escapeHtml(m.top_role) + "</span>" +
    (m.is_bot ? '<span class="chip">бот</span>' : "") +
    '<span class="chip">варнов: ' + (m.warnings || 0) + "</span>";
  p.appendChild(line);
  $("mod_actions").style.display = "";
}
async function refreshModMember() {
  const v = $("mod_target").value.trim() || (modMember && modMember.id);
  if (!v) return;
  const m = await findMember(v);
  if (m) { modMember = m; const el = $("mod_member"); el.innerHTML = ""; const line = tag("div", "listline"); line.innerHTML =
    '<img class="av" src="' + escapeHtml(m.avatar) + '" alt="">' +
    '<span class="grow"><b>' + escapeHtml(m.display_name) + '</b> <span class="sub">#' + m.id + "</span></span>" +
    '<span class="chip">варнов: ' + (m.warnings || 0) + "</span>"; el.appendChild(line); }
}
function modReason() { return $("mod_reason").value.trim(); }
async function modWarn() {
  if (!modMember) return toast("Сначала найдите участника", false);
  const r = await api("/api/moderation/warn", { member: modMember.id, reason: modReason() || "Без причины" });
  if (r.status === 200 && r.data.ok) { toast("⚠ Варн выдан, всего: " + r.data.count, true); $("mod_reason").value = ""; loadWarns(); refreshModMember(); }
  else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}
async function modKick() {
  if (!modMember) return toast("Сначала найдите участника", false);
  if (!confirm("Кикнуть " + modMember.display_name + "?")) return;
  const r = await api("/api/moderation/kick", { member: modMember.id, reason: modReason() });
  if (r.status === 200 && r.data.ok) { toast("👢 Участник кикнут", true); $("mod_actions").style.display = "none"; modMember = null; $("mod_target").value = ""; }
  else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}
async function modBan() {
  if (!modMember) return toast("Сначала найдите участника", false);
  if (!confirm("Забанить " + modMember.display_name + "?")) return;
  const r = await api("/api/moderation/ban", { member: modMember.id, reason: modReason(), delete_days: 0 });
  if (r.status === 200 && r.data.ok) { toast("🔨 Участник забанен", true); $("mod_actions").style.display = "none"; modMember = null; $("mod_target").value = ""; }
  else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}
async function modTimeout() {
  if (!modMember) return toast("Сначала найдите участника", false);
  const minutes = parseInt($("mod_timeout_min").value, 10) || 10;
  if (!confirm("Тайм-аут " + modMember.display_name + " на " + minutes + " мин?")) return;
  const r = await api("/api/moderation/timeout", { member: modMember.id, duration_seconds: minutes * 60, reason: modReason() });
  if (r.status === 200 && r.data.ok) toast("⏳ Тайм-аут до " + new Date(r.data.until).toLocaleTimeString("ru-RU"), true);
  else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}
async function modClear() {
  if (!modMember) return toast("Сначала найдите участника", false);
  if (!confirm("Снять все предупреждения у " + modMember.display_name + "?")) return;
  const r = await api("/api/moderation/clear", { member: modMember.id });
  if (r.status === 200 && r.data.ok) { toast("🧹 Снято варнов: " + r.data.cleared, true); loadWarns(); refreshModMember(); }
  else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}
async function modUnban() {
  const promptId = prompt("ID пользователя для разбана:");
  if (!promptId) return;
  const r = await api("/api/moderation/unban", { user_id: promptId.trim(), reason: "Разбан из панели" });
  if (r.status === 200 && r.data.ok) toast("♻️ Разбанен: " + r.data.user_name, true);
  else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}

/* --- розыгрыши --- */
let gvData = null;
async function loadGiveaways() {
  const chSel = $("gv_channel");
  if (chSel && !chSel.options.length) {
    const ch = await api("/api/bot/channels");
    const list = (ch.data && ch.data.channels) || [];
    chSel.innerHTML = "";
    list.forEach((c) => {
      const o = document.createElement("option");
      o.value = c.id; o.textContent = (c.category ? c.category + " / " : "") + c.name;
      chSel.appendChild(o);
    });
  }
  const r = await api("/api/giveaways");
  gvData = r.data || {};
  renderGiveaways();
}
function gvLine(g, finished) {
  const line = tag("div", "listline");
  line.innerHTML =
    '<span class="chip" style="background:rgba(35,165,90,.14);color:#23a55a">#' + g.id + "</span>" +
    '<span class="grow"><b>' + escapeHtml(g.prize) + '</b> <span class="sub">· ' + escapeHtml(g.channel_name) + " · автор: " + escapeHtml(g.author_name) + "</span></span>" +
    '<span class="chip">👥 ' + g.entries + (g.min_days ? " · 🕛 " + g.min_days + " дн" : "") + "</span>" +
    '<span class="chip">🏆 ' + g.winners + "</span>" +
    '<span class="chip">' + (finished ? "завершён" : "до " + relTime(g.ends_at)) + "</span>";
  const acts = tag("div", "row-actions");
  const jump = tag("button", "btn mini", "🔗");
  jump.type = "button"; jump.title = "Скопировать ID сообщения: " + (g.message_id || "—");
  jump.onclick = () => copyText(g.message_id || "—");
  acts.appendChild(jump);
  if (!finished) {
    const end = tag("button", "btn mini", "⏹ Завершить");
    end.type = "button";
    end.onclick = async () => {
      if (!confirm("Завершить розыгрыш «" + g.prize + "»?")) return;
      const rr = await api("/api/giveaways/end", { message_id: g.message_id });
      if (rr.status === 200 && rr.data.ok) toast("🎉 Завершён. Победители: " + rr.data.winners, true);
      else toast(rr.data.error ? "❌ " + rr.data.error : "❌ Ошибка", false);
      loadGiveaways();
    };
    acts.appendChild(end);
  } else {
    const rer = tag("button", "btn mini", "🔁 Переразыграть");
    rer.type = "button";
    rer.onclick = async () => {
      if (!confirm("Переразыграть приз «" + g.prize + "»?")) return;
      const rr = await api("/api/giveaways/reroll", { message_id: g.message_id });
      if (rr.status === 200 && rr.data.ok) toast("🔁 Новые победители: " + rr.data.winners, true);
      else toast(rr.data.error ? "❌ " + rr.data.error : "❌ Ошибка", false);
      loadGiveaways();
    };
    acts.appendChild(rer);
  }
  line.appendChild(acts);
  return line;
}
function renderGiveaways() {
  const aBox = $("gv_active"), fBox = $("gv_finished");
  aBox.innerHTML = "";
  fBox.innerHTML = "";
  const act = (gvData.active || []), fin = (gvData.finished || []);
  if (!act.length) aBox.appendChild(tag("div", "muted", "Активных розыгрышей нет"));
  act.forEach((g) => aBox.appendChild(gvLine(g, false)));
  if (!fin.length) fBox.appendChild(tag("div", "muted", "Завершённых пока нет"));
  fin.forEach((g) => fBox.appendChild(gvLine(g, true)));
}
async function createGiveaway() {
  const channel_id = $("gv_channel").value;
  const prize = $("gv_prize").value.trim();
  const winners = parseInt($("gv_winners").value, 10) || 1;
  const minutes = parseInt($("gv_minutes").value, 10) || 60;
  const min_days = parseInt($("gv_mindays").value, 10) || 0;
  if (!channel_id) return toast("Выберите канал", false);
  if (!prize) return toast("Укажите приз", false);
  const r = await api("/api/giveaways/create", { channel_id, prize, winners, duration_minutes: minutes, min_days });
  if (r.status === 200 && r.data.ok) {
    toast("🎯 Розыгрыш запущен (#" + r.data.id + ")", true);
    $("gv_prize").value = "";
    loadGiveaways();
  } else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}

/* --- планировщик --- */
let schData = null;
async function loadScheduler() {
  const chSel = $("sch_channel");
  if (chSel && !chSel.options.length) {
    const ch = await api("/api/bot/channels");
    const list = (ch.data && ch.data.channels) || [];
    chSel.innerHTML = "";
    list.forEach((c) => {
      const o = document.createElement("option");
      o.value = c.id; o.textContent = (c.category ? c.category + " / " : "") + c.name;
      chSel.appendChild(o);
    });
  }
  const r = await api("/api/schedule");
  schData = r.data || { upcoming: [], done: [] };
  renderScheduled();
}
function schLine(s, doneFlag) {
  const line = tag("div", "listline");
  line.innerHTML =
    '<span class="chip" style="background:rgba(35,165,90,.14);color:#23a55a">#' + s.id + "</span>" +
    '<span class="grow"><b>' + escapeHtml(s.title || s.content || "Без заголовка") + '</b> <span class="sub">' + escapeHtml(s.channel_name) + " · " + escapeHtml(String(s.content || "").slice(0, 80)) + "</span></span>" +
    '<span class="chip">' + new Date(s.send_at).toLocaleString("ru-RU") + "</span>";
  if (!doneFlag) {
    const del = tag("button", "btn mini danger", "✖");
    del.type = "button"; del.title = "Отменить";
    del.onclick = async () => {
      if (!confirm("Отменить запланированное #" + s.id + "?")) return;
      const rr = await api("/api/schedule/" + s.id, null, "DELETE");
      if (rr.status === 200 && rr.data.ok) { toast("🗑 Отменено", true); loadScheduler(); }
      else toast("❌ Не удалось отменить", false);
    };
    line.appendChild(del);
  }
  return line;
}
function renderScheduled() {
  const uBox = $("sch_upcoming"), dBox = $("sch_done");
  uBox.innerHTML = ""; dBox.innerHTML = "";
  const up = schData.upcoming || [], dn = schData.done || [];
  if (!up.length) uBox.appendChild(tag("div", "muted", "Ожидающих отправки нет"));
  up.forEach((s) => uBox.appendChild(schLine(s, false)));
  if (!dn.length) dBox.appendChild(tag("div", "muted", "Отправленных пока нет"));
  dn.forEach((s) => dBox.appendChild(schLine(s, true)));
}
async function createScheduled() {
  const channel_id = $("sch_channel").value;
  const atRaw = $("sch_at").value;
  const content = $("sch_content").value.trim();
  const title = $("sch_title").value.trim();
  const desc = $("sch_desc").value.trim();
  const color = $("sch_color").value.trim();
  if (!channel_id) return toast("Выберите канал", false);
  if (!atRaw) return toast("Укажите дату и время", false);
  if (!content && !title && !desc) return toast("Укажите текст или эмбед", false);
  const when = new Date(atRaw);
  if (isNaN(when)) return toast("Некорректная дата", false);
  if (when <= Date.now()) return toast("Дата должна быть в будущем", false);
  const embed = {};
  if (title) embed.title = title;
  if (desc) embed.description = desc;
  if (color) embed.color = color;
  const r = await api("/api/schedule", { channel_id, send_at: when.toISOString(), content, embed });
  if (r.status === 200 && r.data.ok) {
    toast("🗓 Запланировано на " + new Date(r.data.send_at).toLocaleString("ru-RU"), true);
    ["sch_at", "sch_content", "sch_title", "sch_desc", "sch_color"].forEach((id) => { $(id).value = ""; });
    loadScheduler();
  } else toast(r.data.error ? "❌ " + r.data.error : "❌ Ошибка", false);
}

/* --- бэкап --- */
async function downloadBlob(url) {
  try {
    const r = await fetch(url, { headers: { "X-Panel-Token": TOKEN } });
    if (r.status === 401) { if (PANEL_LOGIN) showLogin(); else if (TOKEN) location.reload(); return false; }
    if (!r.ok) { toast("❌ Ошибка: " + r.status, false); return false; }
    let filename = "backup";
    const cd = r.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^";]+)"?/i);
    if (m) filename = m[1];
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    return true;
  } catch (e) { toast("❌ Не удалось скачать", false); return false; }
}
async function downloadBackup() {
  $("backup_info").textContent = "Готовим бэкап…";
  const ok = await downloadBlob("/api/backup");
  $("backup_info").textContent = ok ? "✅ Бэкап скачан." : "Ошибка.";
}
async function downloadBackupDb() {
  $("backup_info").textContent = "Готовим снапшот БД…";
  const ok = await downloadBlob("/api/backup/db");
  $("backup_info").textContent = ok ? "✅ Снапшот БД скачан." : "Ошибка.";
}
function loadBackup() {
  const cfg = $("backup_config");
  const modules = settingsData && settingsData.modules;
  if (modules) {
    cfg.innerHTML = '<div class="grid cols">' + Object.entries(modules).map(([k, mod]) =>
      '<div class="module-card"><h5>' + escapeHtml(MODULE_LABELS[k] || k) + '<span class="mod-env">.env</span></h5>' +
      '<div class="kv">Включён: <b>' + (mod && mod.enabled !== undefined ? (mod.enabled ? "да" : "нет") : "—") + "</b></div>" +
      "</div>"
    ).join("") + "</div>";
  } else {
    cfg.innerHTML = 'Модули загрузятся после открытия «Настройки». <button class="btn small op" type="button" onclick="switchSection(\'settings\')">Открыть</button>';
  }
}

/* --- файлы --- */
async function loadFiles() {
  const box = $("files_grid");
  box.innerHTML = '<div class="muted">Загрузка…</div>';
  const r = await api("/api/uploads");
  const list = (r.data && r.data.files) || [];
  box.innerHTML = "";
  if (list.length === 0) {
    box.appendChild(tag("div", "muted", "Загруженных файлов пока нет."));
    return;
  }
  list.forEach((f) => {
    const card = tag("div", "file-card");
    const img = document.createElement("img");
    img.className = "file-thumb"; img.loading = "lazy";
    img.src = f.url; img.alt = f.name;
    card.appendChild(img);
    const name = tag("div", "file-name", escapeHtml(f.name));
    const size = tag("div", "file-size", escapeHtml(f.size || ""));
    const actions = tag("div", "file-actions", null);
    const cp = tag("button", "btn mini", "📋 URL");
    cp.type = "button"; cp.onclick = () => copyText(f.url);
    const del = tag("button", "btn mini danger", "✖");
    del.type = "button";
    del.onclick = async () => {
      if (!confirm("Удалить файл " + f.name + "?")) return;
      const rr = await api("/api/uploads/" + encodeURIComponent(f.name), null, "DELETE");
      if (rr.status === 200 && rr.data.ok) { toast("🗑 Файл удалён", true); loadFiles(); }
      else toast("❌ Ошибка удаления", false);
    };
    actions.append(cp, del);
    card.append(name, size, actions);
    box.appendChild(card);
  });
}

/* --- логи --- */
async function loadLogs() {
  const r = await api("/api/logs?n=500");
  const logs = (r.data && r.data.logs) || [];
  const level = $("log_level").value;
  const box = $("logs_box");
  box.innerHTML = "";
  if (!r.data.ok) { box.appendChild(tag("div", "muted", "Логи недоступны")); return; }
  const filtered = level ? logs.filter((l) => l.level === level) : logs;
  if (filtered.length === 0) box.appendChild(tag("div", "muted", "Записей нет"));
  filtered.slice(-300).forEach((l) => {
    const line = tag("div", "log-line");
    const t = tag("span", "log-t", escapeHtml(l.t || ""));
    const lv = tag("span", "log-lvl " + (l.level === "ERROR" ? "err" : l.level === "WARNING" ? "warn" : "info"), escapeHtml(l.level || ""));
    const m = tag("span", "log-msg", escapeHtml((l.name ? "[" + l.name + "] " : "") + l.msg));
    line.append(t, lv, m);
    box.appendChild(line);
  });
  if (filtered.length) box.scrollTop = box.scrollHeight;
  $("logs_last").textContent = "Показано " + filtered.length + " из " + r.data.count + " · обновлено " + new Date().toLocaleTimeString("ru-RU");
}
function startLogsTimer() {
  stopLogsTimer();
  logsTimer = setInterval(() => {
    if (!$("sec-logs").classList.contains("active")) return;
    if (document.hidden) return;
    if (!$("log_auto").checked) return;
    loadLogs();
  }, 5000);
}
function stopLogsTimer() {
  if (logsTimer) { clearInterval(logsTimer); logsTimer = null; }
}

/* --- логи Discord (события) --- */
const AUDIT_CATS = {bot: "Бот", member: "Участники", message: "Сообщения", voice: "Голосовые", mod: "Модерация", general: "Общее"};
async function loadAudit() {
  const r = await api("/api/logs?n=500&audit=1");
  const logs = (r.data && r.data.logs) || [];
  const cat = $("audit_level").value;
  const box = $("audit_box");
  box.innerHTML = "";
  if (!r.data.ok) { box.appendChild(tag("div", "muted", "Логи недоступны")); return; }
  const filtered = cat ? logs.filter((l) => l.cat === cat) : logs;
  if (filtered.length === 0) box.appendChild(tag("div", "muted", "Событий нет"));
  filtered.slice(-300).forEach((l) => {
    const line = tag("div", "log-line");
    const t = tag("span", "log-t", escapeHtml(l.t || ""));
    const c = tag("span", "log-cat", escapeHtml(AUDIT_CATS[l.cat] || l.cat || ""));
    const m = tag("span", "log-msg", escapeHtml(l.msg));
    line.append(t, c, m);
    box.appendChild(line);
  });
  if (filtered.length) box.scrollTop = box.scrollHeight;
  $("audit_last").textContent = "Показано " + filtered.length + " из " + r.data.count + " · обновлено " + new Date().toLocaleTimeString("ru-RU");
}
function startAuditTimer() {
  stopAuditTimer();
  auditTimer = setInterval(() => {
    if (!$("sec-audit").classList.contains("active")) return;
    if (document.hidden) return;
    if (!$("audit_auto").checked) return;
    loadAudit();
  }, 5000);
}
function stopAuditTimer() {
  if (auditTimer) { clearInterval(auditTimer); auditTimer = null; }
}

/* --- инициализация --- */
applyTheme();
buildAccents();
$("btn_login").onclick = doLogin;
$("login_pw").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });

function bootInit() {
  renderFields();
  renderButtons();
  renderPreview();
  setMode("webhook");
  loadTestChannels();
  loadOverview();
  startOverviewTimer();
  if (settingsData) renderSettings();
}
if (PANEL_LOGIN) { showLogin(); startOverviewTimer(); }
else bootInit();