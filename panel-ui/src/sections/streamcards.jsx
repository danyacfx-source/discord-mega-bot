import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";

const PLATFORMS = [
  { id: "twitch", label: "Twitch" },
  { id: "kick", label: "Kick" },
  { id: "vk_video", label: "VK Видео" },
];

const TABS = [
  { id: "live", label: "🔴 Во время эфира" },
  { id: "offline", label: "📺 После эфира" },
];

const DEFAULTS = {
  live: {
    titles: {
      twitch: "🔴 Twitch: стрим идёт",
      kick: "🔴 Kick: стрим идёт",
      vk_video: "🔴 VK Видео: трансляция идёт",
    },
    colors: { twitch: "#9146ff", kick: "#53fc18", vk_video: "#0077ff" },
    footer: "",
    fields: {},
  },
  offline: {
    titles: {
      twitch: "📺 Twitch: стрим завершён",
      kick: "📺 Kick: стрим завершён",
      vk_video: "📺 VK Видео: трансляция завершена",
    },
    colors: { twitch: "#272d3a", kick: "#272d3a", vk_video: "#272d3a" },
    footer: "",
    fields: {},
  },
};

const FIELD_DEFS = {
  live: [
    ["viewers", "Зрители", "👁 Зрители", "100"],
    ["peak", "Пик", "📈 Пик", "300"],
    ["duration", "В эфире", "⏱ В эфире", "1:05:00"],
    ["trend", "Тренд", "📈 Тренд", "▲ 12 за 10 мин · ▂▃▅▇"],
    ["category", "Категория", "🎮 Категория", "Just Chatting"],
    ["description", "Описание", "📝 Описание", "Сегодня играем в хоррор"],
  ],
  offline: [
    ["vod", "Запись", "📼 Запись", "Посмотреть запись"],
    ["peak", "Пик зрителей", "📈 Пик зрителей", "450"],
    ["duration", "Длительность", "⏱ Длительность", "2:05:00"],
    ["category", "Категория", "🎮 Категория", "Just Chatting"],
    ["talkers", "Говорили в чате", "💬 Говорили в чате", "vasya — 42"],
  ],
};

const PREVIEW_TEXT = {
  live: "Вечерний стрим",
  offline: "Вечерний стрим",
};

function normalize(preset) {
  const out = {};
  for (const sec of ["live", "offline"]) {
    const raw = (preset && preset[sec]) || {};
    out[sec] = {
      titles: { ...(raw.titles || {}) },
      colors: { ...(raw.colors || {}) },
      footer: raw.footer || "",
      fields: { ...(raw.fields || {}) },
    };
  }
  return out;
}

function sectionPatch(preset, sec, patch) {
  return { ...preset, [sec]: { ...preset[sec], ...patch } };
}

function EmbedPreview({ tab, platform, preset }) {
  const sec = preset[tab];
  const fallback = DEFAULTS[tab];
  const title = sec.titles[platform] || fallback.titles[platform];
  const color = sec.colors[platform] || fallback.colors[platform];
  const footer = sec.footer || (tab === "live" ? "Twitch • MegaBot" : "Спасибо за просмотр • MegaBot");
  const label = (PLATFORMS.find((p) => p.id === platform) || {}).label || platform;

  return (
    <div class="sc-preview" style={{ borderLeftColor: color }}>
      <div class="sc-embed">
        <div class="muted small">{label}</div>
        <div class="sc-title">{title}</div>
        <div class="sc-desc">**{PREVIEW_TEXT[tab]}**</div>
        <div class="sc-fields">
          {FIELD_DEFS[tab].map(([key, , defaultName, sample]) => (
            <div class="sc-field" key={key}>
              <b>{sec.fields[key] || defaultName}</b>
              <span>{sample}</span>
            </div>
          ))}
        </div>
        <div class="sc-footer">{footer}</div>
      </div>
    </div>
  );
}

export default function StreamCardsSection() {
  const [preset, setPreset] = useState(() => normalize(null));
  const [tab, setTab] = useState("live");
  const [platform, setPlatform] = useState("twitch");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  async function load() {
    const r = await api("/api/stream-cards");
    if (r.status !== 200) return toast(errToast(r), false);
    setPreset(normalize(r.data.preset));
  }

  useEffect(() => {
    load();
  }, []);

  function patch(p) {
    setPreset((cur) => sectionPatch(cur, tab, p));
    setDirty(true);
  }

  async function save() {
    setSaving(true);
    const r = await api("/api/stream-cards", { preset });
    setSaving(false);
    if (r.status === 200 && r.data.ok) {
      setPreset(normalize(r.data.preset));
      setDirty(false);
      toast("🎴 Карточки сохранены", true);
    } else toast(errToast(r), false);
  }

  async function reset() {
    if (!confirm("Вернуть карточки к стандартному виду?")) return;
    const r = await api("/api/stream-cards", { reset: true });
    if (r.status === 200 && r.data.ok) {
      setPreset(normalize(r.data.preset));
      setDirty(false);
      toast("Карточки сброшены", true);
    } else toast(errToast(r), false);
  }

  const sec = preset[tab];

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">🎴 Карточки стримов</h3>
        <div class="muted small" style={{ marginBottom: 10 }}>
          Заголовки, цвета, футер и названия полей для анонсов Twitch/Kick/VK. Пустое поле — используется стандартный вид.
        </div>

        <div class="row-inline" style={{ marginBottom: 12 }}>
          {TABS.map((t) => (
            <button key={t.id} class={"chip sc-tab" + (tab === t.id ? " on" : "")} type="button" onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
          <span class="grow" />
          <button class="btn success" type="button" onClick={save} disabled={saving || !dirty}>
            💾 Сохранить{dirty ? "*" : ""}
          </button>
          <button class="btn" type="button" onClick={reset}>
            Сброс
          </button>
        </div>

        <div class="two">
          <div class="stack">
            <div class="row-inline">
              <span class="small muted">Платформа для превью:</span>
              {PLATFORMS.map((p) => (
                <button
                  key={p.id}
                  class={"chip" + (platform === p.id ? " on" : "")}
                  type="button"
                  onClick={() => setPlatform(p.id)}
                >
                  {p.label}
                </button>
              ))}
            </div>

            <label class="field">
              <span class="field-label">Заголовок — {PLATFORMS.find((p) => p.id === platform).label}</span>
              <input
                class="input"
                type="text"
                placeholder={DEFAULTS[tab].titles[platform]}
                value={sec.titles[platform] || ""}
                onInput={(e) => patch({ titles: { ...sec.titles, [platform]: e.target.value } })}
              />
            </label>

            <div class="field">
              <span class="field-label">Цвет акцента</span>
              <span class="color-row">
                <input
                  type="color"
                  value={sec.colors[platform] || DEFAULTS[tab].colors[platform]}
                  onInput={(e) => patch({ colors: { ...sec.colors, [platform]: e.target.value } })}
                />
                <button
                  class="btn mini"
                  type="button"
                  onClick={() => {
                    const colors = { ...sec.colors };
                    delete colors[platform];
                    patch({ colors });
                  }}
                >
                  дефолт
                </button>
              </span>
            </div>

            <label class="field">
              <span class="field-label">Футер (пусто — стандартный; {"{bot}"} подставит имя бота)</span>
              <input
                class="input"
                type="text"
                value={sec.footer || ""}
                onInput={(e) => patch({ footer: e.target.value })}
              />
            </label>
          </div>

          <EmbedPreview tab={tab} platform={platform} preset={preset} />
        </div>

        <div class="two" style={{ marginTop: 12 }}>
          {FIELD_DEFS[tab].map(([key, label, defaultName, sample]) => (
            <label class="field" key={key}>
              <span class="field-label">
                Поле «{label}» — {sample}
              </span>
              <input
                class="input"
                type="text"
                placeholder={defaultName}
                value={sec.fields[key] || ""}
                onInput={(e) => patch({ fields: { ...sec.fields, [key]: e.target.value } })}
              />
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
