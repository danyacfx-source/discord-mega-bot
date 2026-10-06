import { useEffect, useRef, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";
import { token, csrf } from "../api.js";
import { Field, Loading } from "../components/ui.jsx";

const DEFAULTS = {
  bg_top: "#1e2444",
  bg_bottom: "#3d2a63",
  title: "Добро пожаловать,",
  title_color: "#ffffff",
  name_color: "#ffd678",
  subtitle: "{guild}  •  {count}-й участник",
  text_color: "#ced4e6",
  ring_color: "#ffffff",
  avatar_size: 180,
  font_scale: 1.0,
};

const COLOR_ROWS = [
  [
    ["bg_top", "Фон сверху"],
    ["bg_bottom", "Фон снизу"],
  ],
  [
    ["title_color", "Заголовок"],
    ["name_color", "Имя участника"],
  ],
  [
    ["text_color", "Подпись"],
    ["ring_color", "Обводка аватара"],
  ],
];

export default function WelcomeSection() {
  const [preset, setPreset] = useState(DEFAULTS);
  const [custom, setCustom] = useState(false);
  const [cardEnabled, setCardEnabled] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const timer = useRef(null);
  const urlRef = useRef("");

  function set(key, value) {
    setPreset((p) => ({ ...p, [key]: value }));
  }

  async function load() {
    const r = await api("/api/welcome");
    if (r.status !== 200) return toast(errToast(r), false);
    setPreset({ ...DEFAULTS, ...r.data.preset });
    setCustom(Boolean(r.data.custom));
    setCardEnabled(Boolean(r.data.card_enabled));
    setLoaded(true);
  }

  useEffect(() => {
    load();
  }, []);

  // живое превью: перерисовка PNG через дебаунс
  useEffect(() => {
    if (!loaded) return undefined;
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const headers = { "Content-Type": "application/json", "X-Panel-Token": token() };
      const csrfToken = csrf();
      if (csrfToken) headers["X-Panel-CSRF"] = csrfToken;
      try {
        const r = await fetch("/api/welcome/preview", {
          method: "POST",
          headers,
          body: JSON.stringify({ preset, name: "Алиса", guild: "Тестовый сервер", count: 42 }),
        });
        if (!r.ok) return;
        const next = URL.createObjectURL(await r.blob());
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = next;
        setPreviewUrl(next);
      } catch (_) {}
    }, 400);
    return () => clearTimeout(timer.current);
  }, [preset, loaded]);

  useEffect(
    () => () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    },
    [],
  );

  async function save() {
    setSaving(true);
    const r = await api("/api/welcome", { preset });
    setSaving(false);
    if (r.status === 200 && r.data.ok) {
      setCustom(true);
      toast("Приветствие сохранено", true);
    } else {
      toast(errToast(r), false);
    }
  }

  async function reset() {
    if (!confirm("Вернуть вид карточки по умолчанию?")) return;
    const r = await api("/api/welcome", { reset: true });
    if (r.status === 200 && r.data.ok) {
      setPreset({ ...DEFAULTS, ...r.data.preset });
      setCustom(false);
      toast("Вид сброшен к умолчанию", true);
    } else {
      toast(errToast(r), false);
    }
  }

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">Приветственная карточка</h3>
        {!cardEnabled && (
          <div class="env-box muted small" style={{ marginBottom: 10 }}>
            В .env выключен <b>WELCOME_CARD</b> — карточка в Discord не отправляется, но пресет здесь сохранится.
          </div>
        )}
        <div class="welcome-layout">
          <div class="stack">
            <div class="welcome-group">
              <h4>Текст карточки</h4>
              <Field label="Заголовок над именем">
                <input class="input" type="text" value={preset.title} onInput={(e) => set("title", e.target.value)} />
              </Field>
              <Field label="Подпись под именем" hint='Плейсхолдеры: {name} · {guild} · {count}'>
                <input class="input" type="text" value={preset.subtitle} onInput={(e) => set("subtitle", e.target.value)} />
              </Field>
            </div>
            <div class="welcome-group">
              <h4>Цветовая палитра</h4>
              {COLOR_ROWS.map((row, i) => (
                <div class="two" key={i}>
                  {row.map(([key, label]) => (
                    <Field key={key} label={label}>
                      <span class="color-row">
                        <input type="color" value={preset[key]} onInput={(e) => set(key, e.target.value)} aria-label={label} />
                        <code class="muted small">{preset[key]}</code>
                      </span>
                    </Field>
                  ))}
                </div>
              ))}
            </div>
            <div class="welcome-group">
              <h4>Размеры и композиция</h4>
              <Field label={`Размер аватара — ${preset.avatar_size} px`}>
                <input class="range" type="range" min="120" max="240" step="2" value={preset.avatar_size} onInput={(e) => set("avatar_size", +e.target.value)} />
              </Field>
              <Field label={`Масштаб шрифта — ${preset.font_scale}`}>
                <input class="range" type="range" min="0.7" max="1.5" step="0.05" value={preset.font_scale} onInput={(e) => set("font_scale", +e.target.value)} />
              </Field>
            </div>
          </div>

          <div class="stack welcome-preview-col">
            <Field label="Превью · 800×300">
              {previewUrl ? (
                <div class="welcome-preview-frame"><img class="welcome-preview" src={previewUrl} alt="Превью приветственной карточки" /></div>
              ) : (
                <Loading />
              )}
            </Field>
            <div class="row-inline">
              <button class="btn success" type="button" onClick={save} disabled={saving}>Сохранить
              </button>
              <button class="btn" type="button" onClick={reset}>
                Сброс
              </button>
            </div>
            <span class="muted small">
              {custom
                ? "В Discord используется сохранённый пресет."
                : "Сейчас — вид по умолчанию из кода."}
            </span>
            <span class="muted small">
              Вход участника → картинка-приветствие в канал с этим оформлением.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
