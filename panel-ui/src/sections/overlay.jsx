import { useEffect, useRef, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";

const EMPTY_LAYOUT = null;

const TYPE_META = {
  stream: { label: "Стрим" },
  goal: { label: "Донат-цель" },
  donation: { label: "Последний донат" },
  slots: { label: "Выигрыш слотов" },
  poll: { label: "Последний опрос" },
  chat_top: { label: "Топ чата" },
  chat: { label: "Лента чата" },
  countdown: { label: "Обратный отсчёт" },
  text: { label: "Текст" },
  image: { label: "Картинка" },
};

const SIZES = {
  stream: [560, 190],
  goal: [560, 150],
  donation: [270, 150],
  slots: [270, 150],
  poll: [320, 160],
  chat_top: [270, 150],
  chat: [340, 260],
  countdown: [300, 140],
  text: [400, 120],
  image: [400, 240],
};

function newWidgetId() {
  return Math.random().toString(36).slice(2, 10);
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function defaultProps(type) {
  const base = { bg: "", radius: 14 };
  if (type === "text") return { ...base, text: "Новый текст", size: 36, color: "#ffffff", align: "left", bold: false };
  if (type === "image") return { ...base, url: "" };
  if (type === "countdown") return { ...base, label: "До стрима", date: "", color: "#ff5a36" };
  if (type === "chat_top") return { ...base, title: "Топ чата", limit: 3 };
  if (type === "chat") return { ...base, title: "Лента чата", limit: 10 };
  if (type === "stream") return { ...base, title: "" };
  const titles = { goal: "Донат-цель", donation: "Последний донат", slots: "Последний выигрыш", poll: "Последний опрос" };
  return { ...base, title: titles[type] || "" };
}

function widgetPreview(w) {
  const p = w.props || {};
  if (w.type === "text") {
    return (
      <div
        class="ovl-text"
        style={{
          fontSize: `${p.size || 36}px`,
          color: p.color || "#fff",
          textAlign: p.align || "left",
          fontWeight: p.bold ? 800 : 400,
        }}
      >
        {p.text || ""}
      </div>
    );
  }
  if (w.type === "image") {
    return p.url ? <img class="ovl-img" src={p.url} alt="" /> : <div class="ovl-ph">URL картинки пуст</div>;
  }
  if (w.type === "countdown") {
    return (
      <div class="ovl-ph">
        <b style={{ color: p.color || "#ff5a36", fontSize: 22 }}>00:00:00</b>
        <div class="muted">{p.label || "До стрима"}</div>
      </div>
    );
  }
  if (w.type === "stream") {
    return (
      <div class="ovl-ph">
        <b>{p.title || "В эфире · название"}</b>
        <div class="muted">Зрители 123 · Пик 456</div>
      </div>
    );
  }
  if (w.type === "goal") {
    return (
      <div class="ovl-ph">
        <b>{p.title || "Донат-цель"}</b>
        <div class="muted">1 200 / 3 000 ₽</div>
        <div class="ovl-bar">
          <i style={{ width: "40%" }} />
        </div>
      </div>
    );
  }
  if (w.type === "chat_top") {
    return (
      <div class="ovl-ph">
        <b>{p.title || "Топ чата"}</b>
        <div class="muted">1. Алиса · 120</div>
        <div class="muted">2. Боб · 90</div>
      </div>
    );
  }
  if (w.type === "chat") {
    return (
      <div class="ovl-ph">
        <b>{p.title || "Лента чата"}</b>
        <div class="muted">
          <b style={{ color: "#53fc18" }}>Алиса:</b> привет всем
        </div>
        <div class="muted">
          <b style={{ color: "#9146ff" }}>Борис:</b> кота покажи
        </div>
      </div>
    );
  }
  return (
    <div class="ovl-ph">
      <b>{p.title || TYPE_META[w.type].label}</b>
      <div class="muted">пример данных</div>
    </div>
  );
}

export default function OverlaySection() {
  const [meta, setMeta] = useState({ enabled: false, host: "", port: null, token: "", layouts: [], canvas_presets: [], widget_types: [] });
  const [layout, setLayout] = useState(EMPTY_LAYOUT);
  const [selected, setSelected] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const canvasRef = useRef(null);

  async function loadMeta() {
    const r = await api("/api/overlay");
    if (r.status !== 200) return toast(errToast(r), false);
    setMeta(r.data);
  }

  useEffect(() => {
    loadMeta();
  }, []);

  function scale() {
    if (!canvasRef.current || !layout) return 1;
    return (canvasRef.current.clientWidth || 1) / layout.width;
  }

  function mutate(fn) {
    setLayout((cur) => {
      if (!cur) return cur;
      const next = { ...cur, widgets: fn(cur.widgets) };
      return next;
    });
    setDirty(true);
  }

  function updateWidget(id, fn) {
    mutate((widgets) => widgets.map((w) => (w.id === id ? fn(w) : w)));
  }

  function addWidget(type) {
    if (!layout) return;
    const [w, h] = SIZES[type] || [300, 140];
    const offset = (layout.widgets.length % 6) * 24;
    const widget = {
      id: newWidgetId(),
      type,
      x: clamp(Math.round((layout.width - w) / 2) + offset, 0, layout.width - w),
      y: clamp(Math.round((layout.height - h) / 2) + offset, 0, layout.height - h),
      w,
      h,
      props: defaultProps(type),
    };
    mutate((widgets) => [...widgets, widget]);
    setSelected(widget.id);
  }

  function removeWidget(id) {
    mutate((widgets) => widgets.filter((w) => w.id !== id));
    if (selected === id) setSelected("");
  }

  function startDrag(e, widget, mode) {
    if (e.button !== 0 || !layout) return;
    e.stopPropagation();
    setSelected(widget.id);
    const k = scale();
    const startX = e.clientX;
    const startY = e.clientY;
    const orig = { x: widget.x, y: widget.y, w: widget.w, h: widget.h };
    const onMove = (ev) => {
      const dx = Math.round((ev.clientX - startX) / k / 8) * 8;
      const dy = Math.round((ev.clientY - startY) / k / 8) * 8;
      updateWidget(widget.id, (cur) => {
        if (mode === "resize") {
          return {
            ...cur,
            w: clamp(orig.w + dx, 40, layout.width - cur.x),
            h: clamp(orig.h + dy, 30, layout.height - cur.y),
          };
        }
        return {
          ...cur,
          x: clamp(orig.x + dx, 0, Math.max(0, layout.width - cur.w)),
          y: clamp(orig.y + dy, 0, Math.max(0, layout.height - cur.h)),
        };
      });
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  async function createLayout() {
    const name = prompt("Название раскладки:", `Раскладка ${(meta.layouts || []).length + 1}`);
    if (name === null) return;
    const r = await api("/api/overlay/layouts", { name: name.trim() });
    if (r.status === 200 && r.data.ok) {
      setMeta((m) => ({ ...m, layouts: r.data.layouts }));
      setLayout(r.data.layout);
      setSelected("");
      setDirty(false);
      toast("Раскладка создана", true);
    } else toast(errToast(r), false);
  }

  async function openLayout(id) {
    const r = await api(`/api/overlay/layout?id=${encodeURIComponent(id)}`);
    if (r.status === 200 && r.data.ok) {
      setLayout(r.data.layout);
      setSelected("");
      setDirty(false);
    } else toast(errToast(r), false);
  }

  async function renameLayout(id, current) {
    const name = prompt("Новое имя раскладки:", current);
    if (name === null || !name.trim()) return;
    const r = await api("/api/overlay/layout/rename", { id, name: name.trim() });
    if (r.status === 200 && r.data.ok) {
      setMeta((m) => ({ ...m, layouts: r.data.layouts }));
      toast("Переименовано", true);
    } else toast(errToast(r), false);
  }

  async function removeLayout(id, name) {
    if (!confirm(`Удалить раскладку «${name}»?`)) return;
    const r = await api("/api/overlay/layout/delete", { id });
    if (r.status === 200 && r.data.ok) {
      setMeta((m) => ({ ...m, layouts: r.data.layouts }));
      toast("Раскладка удалена", true);
    } else toast(errToast(r), false);
  }

  async function saveLayout() {
    if (!layout) return;
    setSaving(true);
    const r = await api("/api/overlay/layout", { layout });
    setSaving(false);
    if (r.status === 200 && r.data.ok) {
      setLayout(r.data.layout);
      setMeta((m) => ({ ...m, layouts: r.data.layouts }));
      setDirty(false);
      toast("Раскладка сохранена", true);
    } else toast(errToast(r), false);
  }

  async function deleteLayout() {
    if (!layout || !confirm(`Удалить раскладку «${layout.name}»?`)) return;
    const r = await api("/api/overlay/layout/delete", { id: layout.id });
    if (r.status === 200 && r.data.ok) {
      setMeta((m) => ({ ...m, layouts: r.data.layouts }));
      setLayout(EMPTY_LAYOUT);
      setSelected("");
      setDirty(false);
      toast("Раскладка удалена", true);
    } else toast(errToast(r), false);
  }

  const obsHost = meta.host === "0.0.0.0" || meta.host === "::" ? location.hostname : meta.host;
  const overlayUrl =
    layout && meta.enabled
      ? `${meta.url_base || `${location.protocol}//${obsHost}:${meta.port}`}/overlay/${layout.id}?token=${meta.token}`
      : "";
  const chatUrl =
    meta.enabled && meta.token
      ? `${meta.url_base || `${location.protocol}//${obsHost}:${meta.port}`}/overlay/chat?token=${meta.token}`
      : "";

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(overlayUrl);
      toast("Ссылка скопирована — вставьте в OBS Browser Source", true);
    } catch (_) {
      prompt("Ссылка для OBS:", overlayUrl);
    }
  }

  async function copyChatUrl() {
    try {
      await navigator.clipboard.writeText(chatUrl);
      toast("Ссылка на ленту чата скопирована", true);
    } catch (_) {
      prompt("Лента чата для OBS:", chatUrl);
    }
  }

  // --------------------------------------------------------------- список
  if (!layout) {
    return (
      <div class="stack">
        <div class="card">
          <h3 class="sec">Оверлей для OBS</h3>
          {!meta.enabled && (
            <div class="env-box muted small" style={{ marginBottom: 10 }}>
              Оверлей выключен — задайте <b>OVERLAY_PORT</b> в .env. Раскладки сохранятся и заработают после перезапуска.
            </div>
          )}
          <div class="row-inline" style={{ marginBottom: 12 }}>
            <button class="btn success" type="button" onClick={createLayout}>
              + Новая раскладка
            </button>
            <span class="muted small">{(meta.layouts || []).length} раскладок · виджетов на штуку — до 30</span>
          </div>
          <div class="list">
            {!meta.layouts?.length && <div class="muted small">Раскладок пока нет — создайте первую.</div>}
            {(meta.layouts || []).map((l) => (
              <div class="listline" key={l.id}>
                <span class="chip">{l.name}</span>
                <span class="grow sub">/overlay/{l.id}</span>
                <button class="btn mini" type="button" onClick={() => openLayout(l.id)}>
                  Открыть
                </button>
                <button class="btn mini" type="button" onClick={() => renameLayout(l.id, l.name)}>
                </button>
                <button class="btn mini danger" type="button" onClick={() => removeLayout(l.id, l.name)}>
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ------------------------------------------------------------- редактор
  const widget = layout.widgets.find((w) => w.id === selected) || null;
  const ar = `${layout.width} / ${layout.height}`;

  return (
    <div class="stack">
      <div class="card">
        <div class="ovl-top">
          <button class="btn" type="button" onClick={() => { if (dirty && !confirm("Есть несохранённые изменения. Выйти?")) return; setLayout(EMPTY_LAYOUT); }}>
            ← К списку
          </button>
          <input
            class="input ovl-name"
            type="text"
            value={layout.name}
            onInput={(e) => { setLayout((cur) => ({ ...cur, name: e.target.value })); setDirty(true); }}
          />
          <select
            class="input ovl-size"
            value={`${layout.width}x${layout.height}`}
            onChange={(e) => {
              const [w, h] = e.target.value.split("x").map(Number);
              setLayout((cur) => ({ ...cur, width: w, height: h }));
              setDirty(true);
            }}
          >
            {(meta.canvas_presets || []).map(([w, h]) => (
              <option key={`${w}x${h}`} value={`${w}x${h}`}>
                {w}×{h}
              </option>
            ))}
            {!meta.canvas_presets?.some(([w, h]) => w === layout.width && h === layout.height) && (
              <option value={`${layout.width}x${layout.height}`}>
                {layout.width}×{layout.height}
              </option>
            )}
          </select>
          <button class="btn success" type="button" onClick={saveLayout} disabled={saving || !dirty}>Сохранить{dirty ? "*" : ""}
          </button>
          {meta.enabled && meta.token ? (
            <button class="btn" type="button" onClick={copyUrl}>Ссылка для OBS
            </button>
          ) : null}
          {meta.enabled && meta.token ? (
            <button class="btn" type="button" onClick={copyChatUrl}>Лента чата для OBS
            </button>
          ) : null}
          <button class="btn danger" type="button" onClick={deleteLayout}>
            Удалить
          </button>
        </div>

        <div class="ovl-palette">
          {(meta.widget_types?.length ? meta.widget_types : Object.keys(TYPE_META)).map((type) => (
            <button class="chip ovl-add" type="button" key={type} onClick={() => addWidget(type)}>
              {TYPE_META[type].label}
            </button>
          ))}
        </div>

        <div class="ovl-editor">
          <div class="ovl-canvas-wrap">
            <div class="ovl-canvas" ref={canvasRef} style={{ aspectRatio: ar }} onClick={() => setSelected("")}>
              {layout.widgets.map((w) => (
                <div
                  key={w.id}
                  class={"ovl-w" + (selected === w.id ? " sel" : "")}
                  style={{
                    left: `${(w.x / layout.width) * 100}%`,
                    top: `${(w.y / layout.height) * 100}%`,
                    width: `${(w.w / layout.width) * 100}%`,
                    height: `${(w.h / layout.height) * 100}%`,
                    borderRadius: `${w.props?.radius ?? 14}px`,
                    background: w.props?.bg || undefined,
                  }}
                  onPointerDown={(e) => startDrag(e, w, "move")}
                >
                  <div class="ovl-wlabel">
                    {TYPE_META[w.type].label}
                  </div>
                  {widgetPreview(w)}
                  <span class="ovl-h" onPointerDown={(e) => startDrag(e, w, "resize")} />
                </div>
              ))}
              {!layout.widgets.length && <div class="ovl-empty">Добавьте первый виджет кнопками выше</div>}
            </div>
            <div class="muted small" style={{ marginTop: 6 }}>
              {layout.width}×{layout.height} · {layout.widgets.length} виджетов · сетка 8px{dirty ? " · несохранено" : ""}
            </div>
          </div>

          <div class="ovl-inspector">
            {!widget ? (
              <div class="muted small">Кликните виджет на холсте, чтобы настроить его.</div>
            ) : (
              <div class="stack">
                <div class="row-inline">
                  <b>{TYPE_META[widget.type].label}</b>
                  <button class="btn mini danger" type="button" onClick={() => removeWidget(widget.id)}>
                    Удалить
                  </button>
                </div>
                <label class="ovl-field">
                  Заголовок
                  <input
                    class="input"
                    type="text"
                    value={widget.props.title ?? ""}
                    onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, title: e.target.value } }))}
                  />
                </label>
                {widget.type === "text" && (
                  <>
                    <label class="ovl-field">
                      Текст
                      <textarea
                        class="input"
                        rows="3"
                        value={widget.props.text || ""}
                        onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, text: e.target.value } }))}
                      />
                    </label>
                    <label class="ovl-field">
                      Размер — {widget.props.size}px
                      <input
                        class="range"
                        type="range"
                        min="10"
                        max="120"
                        value={widget.props.size || 36}
                        onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, size: +e.target.value } }))}
                      />
                    </label>
                    <label class="ovl-field">
                      Выравнивание
                      <select
                        class="input"
                        value={widget.props.align || "left"}
                        onChange={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, align: e.target.value } }))}
                      >
                        <option value="left">Влево</option>
                        <option value="center">По центру</option>
                        <option value="right">Вправо</option>
                      </select>
                    </label>
                    <label class="ovl-check">
                      <input
                        type="checkbox"
                        checked={Boolean(widget.props.bold)}
                        onChange={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, bold: e.currentTarget.checked } }))}
                      />
                      Жирный
                    </label>
                    <label class="ovl-field">
                      Цвет текста
                      <input
                        type="color"
                        value={widget.props.color || "#ffffff"}
                        onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, color: e.target.value } }))}
                      />
                    </label>
                  </>
                )}
                {widget.type === "image" && (
                  <label class="ovl-field">
                    URL картинки
                    <input
                      class="input"
                      type="text"
                      placeholder="https://… или /uploads/pic.png"
                      value={widget.props.url || ""}
                      onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, url: e.target.value } }))}
                    />
                  </label>
                )}
                {widget.type === "countdown" && (
                  <>
                    <label class="ovl-field">
                      Подпись
                      <input
                        class="input"
                        type="text"
                        value={widget.props.label || ""}
                        onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, label: e.target.value } }))}
                      />
                    </label>
                    <label class="ovl-field">
                      Дата и время
                      <input
                        class="input"
                        type="datetime-local"
                        value={(widget.props.date || "").slice(0, 16)}
                        onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, date: e.target.value } }))}
                      />
                    </label>
                    <label class="ovl-field">
                      Цвет цифр
                      <input
                        type="color"
                        value={widget.props.color || "#ff5a36"}
                        onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, color: e.target.value } }))}
                      />
                    </label>
                  </>
                )}
                {widget.type === "chat_top" && (
                  <label class="ovl-field">
                    Строк — {widget.props.limit || 3}
                    <input
                      class="range"
                      type="range"
                      min="1"
                      max="10"
                      value={widget.props.limit || 3}
                      onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, limit: +e.target.value } }))}
                    />
                  </label>
                )}
                {widget.type === "chat" && (
                  <label class="ovl-field">
                    Сообщений — {widget.props.limit || 10}
                    <input
                      class="range"
                      type="range"
                      min="1"
                      max="25"
                      value={widget.props.limit || 10}
                      onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, limit: +e.target.value } }))}
                    />
                  </label>
                )}
                <label class="ovl-field">
                  Фон (пусто — стиль по умолчанию)
                  <span class="color-row">
                    <input
                      type="color"
                      value={widget.props.bg || "#141926"}
                      onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, bg: e.target.value } }))}
                    />
                    <button class="btn mini" type="button" onClick={() => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, bg: "" } }))}>
                      сброс
                    </button>
                  </span>
                </label>
                <label class="ovl-field">
                  Скругление — {widget.props.radius ?? 14}px
                  <input
                    class="range"
                    type="range"
                    min="0"
                    max="48"
                    value={widget.props.radius ?? 14}
                    onInput={(e) => updateWidget(widget.id, (w) => ({ ...w, props: { ...w.props, radius: +e.target.value } }))}
                  />
                </label>
                <div class="two">
                  <label class="ovl-field">
                    X
                    <input
                      class="input"
                      type="number"
                      value={widget.x}
                      onChange={(e) => updateWidget(widget.id, (w) => ({ ...w, x: clamp(+e.target.value, 0, layout.width - w.w) }))}
                    />
                  </label>
                  <label class="ovl-field">
                    Y
                    <input
                      class="input"
                      type="number"
                      value={widget.y}
                      onChange={(e) => updateWidget(widget.id, (w) => ({ ...w, y: clamp(+e.target.value, 0, layout.height - w.h) }))}
                    />
                  </label>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
