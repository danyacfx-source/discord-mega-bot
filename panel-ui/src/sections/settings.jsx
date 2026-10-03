import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";

const SETTINGS_GROUPS = [
  { title: "Приветствия", cols: [["welcome_channel_id", "Канал приветствий"], ["farewell_channel_id", "Канал прощаний"]] },
  {
    title: "Логи аудита",
    cols: [
      ["log_channel_id", "Общий лог"],
      ["member_log_channel_id", "Лог участников"],
      ["message_log_channel_id", "Лог сообщений"],
      ["voice_log_channel_id", "Лог голосовых"],
      ["mod_log_channel_id", "Лог модерации"],
      ["bot_log_channel_id", "Лог бота"],
    ],
  },
  { title: "Тикеты", cols: [["ticket_category_id", "Категория тикетов"]] },
  { title: "Донаты", cols: [["donation_channel_id", "Канал донатов"]] },
];

const MODULE_LABELS = {
  welcome: "Приветствия",
  role_menu: "Роль по меню",
  birthdays: "Дни рождения",
  temp_voices: "Темп-голосовые",
  donations: "Донаты",
  overlay: "Overlay",
  logs: "Логи (исключения)",
  kick: "Kick",
  twitch: "Twitch",
  automod: "Автомод",
  ai_chat: "AI-чат",
  server_stats: "Статистика сервера",
  seasons: "Сезоны",
  rules_gate: "Правила",
  ram_report: "Отчёт об ОЗУ",
};

const EFF_NAMES = {
  log: "Общий лог",
  member: "Лог участников",
  message: "Лог сообщений",
  voice: "Лог голосовых",
  mod: "Лог модерации",
  bot: "Лог бота",
};

function channelName(channels, id) {
  if (!id) return "";
  const found = channels.find((c) => String(c.id) === String(id));
  return found ? found.name : String(id);
}

export default function SettingsSection() {
  const [data, setData] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [form, setForm] = useState({});
  const [automod, setAutomod] = useState(false);
  const [words, setWords] = useState("");

  async function load() {
    const r = await api("/api/settings");
    if (r.status !== 200 || !r.data.ok) return toast("Не удалось загрузить настройки", false);
    setData(r.data);
    setForm({ ...(r.data.settings || {}) });
    setAutomod(!!r.data.automod_enabled);
    setWords((r.data.blocked_words || []).join("\n"));
    setLoaded(true);
  }

  useEffect(() => {
    load();
  }, []);

  async function save() {
    const payload = { ...form, automod_enabled: automod, blocked_words: words };
    const r = await api("/api/settings", payload);
    if (r.status === 200 && r.data.ok) toast("Настройки сохранены", true);
    else toast(errToast(r, "Ошибка сохранения"), false);
  }

  const channels = (data && data.channels) || [];
  const eff = (data && data.effective_logs) || {};
  const modules = (data && data.modules) || null;

  return (
    <div class="stack">
      <div class="card">
        <div class="row-inline" style={{ justifyContent: "space-between" }}>
          <h3 class="sec" style={{ margin: 0 }}>Каналы сервера</h3>
          <div class="row-inline" style={{ margin: 0 }}>
            <button class="btn mini" type="button" onClick={load}>Обновить список</button>
            <span class="muted small">Данные бота; сохраняются по кнопке «Сохранить» ниже.</span>
          </div>
        </div>

        {!loaded && <div class="muted small" style={{ marginTop: 10 }}>Загрузка…</div>}

        <div class="grid cols" style={{ marginTop: loaded ? 12 : 0 }}>
          {SETTINGS_GROUPS.map((g) => (
            <div class="set-group" key={g.title}>
              <h4>{g.title}</h4>
              {g.cols.map(([col, label]) => (
                <label class="field" key={col}>
                  <span class="field-label">{label}</span>
                  <select class="input" value={form[col] ? String(form[col]) : ""} onChange={(e) => setForm({ ...form, [col]: e.target.value })}>
                    <option value="">* автовыбор (не задано)</option>
                    {channels.map((ch) => (
                      <option key={ch.id} value={ch.id}>
                        {ch.category ? ch.category + " / " : ""}
                        {ch.name}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Эффективные каналы логирования</h3>
        <div class="muted small" style={{ marginBottom: 8 }}>
          Фактические каналы с учётом fallback из <code>.env</code> (если в БД не задано).
        </div>
        {Object.keys(EFF_NAMES).every((k) => !eff[k]) ? (
          <div class="muted">Не задано</div>
        ) : (
          Object.entries(EFF_NAMES).map(([k, name]) => (
            <div class="kv" key={k}>
              <b>{name}: </b>
              {eff[k] ? `${channelName(channels, eff[k])} (#${eff[k]})` : "не задан"}
            </div>
          ))
        )}
      </div>

      <div class="card">
        <h3 class="sec">Автомод</h3>
        <label class="toggle-holder">
          <span class="switch">
            <input type="checkbox" checked={automod} onChange={(e) => setAutomod(e.target.checked)} />
            <span class="slider" />
          </span>
          <span>Включить фильтр запрещённых слов</span>
        </label>
        <label class="field">
          <span class="field-label">Запрещённые слова (по одному на строку)</span>
          <textarea class="input" rows="5" placeholder={"слово1\nслово2"} value={words} onInput={(e) => setWords(e.target.value)} />
        </label>
        <button class="btn success" type="button" onClick={save}>Сохранить</button>
      </div>

      <div class="card">
        <h3 class="sec">
          Модули — из <code>.env</code> <span class="pill-env">только чтение</span>
        </h3>
        {!modules || !Object.keys(modules).length ? (
          <div class="muted">Модули не найдены в .env</div>
        ) : (
          <div class="grid cols">
            {Object.entries(modules).map(([key, mod]) => (
              <div class="module-card" key={key}>
                <h5>
                  {MODULE_LABELS[key] || key}
                  <span class="mod-env">.env</span>
                </h5>
                {(Array.isArray(mod) ? mod : [mod])
                  .slice(0, 3)
                  .map((v, i) => (
                    <div class="kv" key={i}>
                      <b>
                        {(v && typeof v === "object" && v.name ? v.name + ": " : "") + String(v && v.name ? v.name : v)}
                      </b>
                    </div>
                  ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
