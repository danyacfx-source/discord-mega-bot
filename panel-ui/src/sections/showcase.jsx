import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast, copyText } from "../lib/exports.js";
import { Field } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";
import ShowcasePage from "../showcase-page.jsx";

export default function ShowcaseSection() {
  const [settings, setSettings] = useState({ hero_title: "", about: "", invite_url: "" });
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const url = location.origin + "/showcase";

  async function load() {
    const r = await api("/api/showcase/settings");
    if (r.status === 200 && r.data.ok) {
      setSettings(r.data.settings);
      setLoaded(true);
    } else if (r.data.error) toast(r.data.error, false);
  }

  useEffect(() => {
    load();
  }, []);

  function set(key, value) {
    setSettings((s) => ({ ...s, [key]: value }));
  }

  async function save() {
    setBusy(true);
    const r = await api("/api/showcase/settings", settings, "POST");
    setBusy(false);
    if (r.status === 200 && r.data.ok) {
      toast("Настройки витрины сохранены", true);
      setSettings(r.data.settings);
    } else toast(errToast(r), false);
  }

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">Витрина сообщества</h3>
        <p class="muted small">
          Публичная страница для гостей — без входа в панель. Показывает живую статистику, эфиры, расписание и медиа
          с флагом «показывать на витрине».
        </p>
        <div class="two">
          <div class="stack">
            <Field label="Ссылка для гостей">
              <div class="row-inline">
                <input class="input" type="text" readOnly value={url} onFocus={(e) => e.target.select()} />
                <button class="btn" type="button" onClick={() => copyText(url)}>
                  <Icon name="copy" size={14} /> Копировать
                </button>
                <a class="btn" href="/showcase" target="_blank" rel="noreferrer">
                  <Icon name="globe" size={14} /> Открыть
                </a>
              </div>
            </Field>
            <Field label="Заголовок над героем" hint="Пусто — покажется название сервера">
              <input class="input" type="text" maxLength={120} placeholder="Наше сообщество" value={settings.hero_title} onInput={(e) => set("hero_title", e.target.value)} />
            </Field>
            <Field label="Описание для гостей">
              <textarea class="input" rows={3} maxLength={600} placeholder="Стримы, события и живое сообщество…" value={settings.about} onInput={(e) => set("about", e.target.value)} />
            </Field>
            <Field label="Ссылка «Вступить»" hint="Приглашение в Discord или другой канал">
              <input class="input" type="url" placeholder="https://discord.gg/…" value={settings.invite_url} onInput={(e) => set("invite_url", e.target.value)} />
            </Field>
            <div class="row-inline">
              <button class="btn success" type="button" disabled={busy || !loaded} onClick={save}>
                {busy ? "Сохраняем…" : "Сохранить"}
              </button>
              <span class="muted small">Данные берутся автоматически: участники, эфиры, расписание, медиатека.</span>
            </div>
          </div>
          <div class="stack">
            <span class="field-label">Что видят гости</span>
            <div class="showcase-preview">
              <ShowcasePage />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
