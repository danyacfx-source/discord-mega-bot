import { useEffect, useMemo, useState } from "preact/hooks";
import { api } from "../api.js";
import { navigate } from "../store.js";
import { Icon } from "../components/icons.jsx";
import { prepareScheduleDraft } from "../lib/schedule-draft.js";

const STATUSES = {
  task: [["todo", "В очереди"], ["doing", "В работе"], ["done", "Готово"]],
  idea: [["draft", "Черновик"], ["ready", "Готово к выпуску"], ["published", "Опубликовано"]],
};
const QUICK = [
  { label: "Модерация", icon: "shield", section: "moderation", desc: "Нарушения и действия" },
  { label: "Тикеты", icon: "ticket", section: "tickets", desc: "Запросы участников" },
  { label: "Эфиры", icon: "monitor", section: "streams", desc: "Twitch и Kick" },
  { label: "Медиатека", icon: "film", section: "media", desc: "Фото и видео" },
  { label: "Планировщик", icon: "clock", section: "scheduler", desc: "Публикации в Discord" },
  { label: "Аналитика", icon: "trending", section: "stats", desc: "Цифры сообщества" },
];

function Item({ item, canEdit, busy, onUpdate, onDelete, onSchedule }) {
  return (
    <article class={"cc-entry" + (item.status === "done" || item.status === "published" ? " is-complete" : "")}>
      <div class="cc-entry-info">
        <div class="cc-entry-heading">
          <b>{item.title}</b>
          {item.priority === "high" ? <span class="cc-priority">ПРИОРИТЕТ</span> : null}
        </div>
        {item.note ? <p>{item.note}</p> : null}
        <small>Изменено: {new Date(item.updated_at).toLocaleDateString("ru-RU")}</small>
      </div>
      <div class="cc-entry-controls">
        <button class="btn mini cc-schedule-btn" type="button" disabled={busy}
          aria-label={"В планировщик: " + item.title} title="Подготовить публикацию (без отправки)"
          onClick={() => onSchedule(item)}><Icon name="clock" size={15} /> В планировщик</button>
        <label class="cc-status-control">
          <span class="sr-only">Статус записи</span>
          <select class="input" aria-label={"Статус: " + item.title} value={item.status}
            disabled={!canEdit || busy}
            onChange={(e) => onUpdate(item, { status: e.currentTarget.value })}>
            {STATUSES[item.type].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        {canEdit ? <button class="cc-icon-btn" aria-label={"Удалить " + item.title}
          title="Удалить запись" type="button" disabled={busy} onClick={() => onDelete(item)}>
          <Icon name="trash" size={16} />
        </button> : null}
      </div>
    </article>
  );
}

export default function CommandCenter() {
  const [items, setItems] = useState([]);
  const [kind, setKind] = useState("task");
  const [query, setQuery] = useState("");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [priority, setPriority] = useState("normal");
  const [canEdit, setCanEdit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function refresh() {
    setError("");
    const [board, session] = await Promise.all([api("/api/workboard"), api("/api/session")]);
    setLoading(false);
    if (board.status === 200 && board.data.ok) setItems(board.data.items || []);
    else setError(board.status === 403 ? "Нет прав для просмотра оперативного центра." : "Не удалось получить записи с сервера.");
    if (session.status === 200) setCanEdit(Boolean(session.data.permissions?.admin));
  }
  useEffect(() => { refresh(); }, []);

  const filtered = useMemo(() => items.filter((item) =>
    item.type === kind && (item.title + " " + item.note).toLowerCase().includes(query.trim().toLowerCase())
  ), [items, kind, query]);
  const openTasks = items.filter((i) => i.type === "task" && i.status !== "done").length;
  const readyIdeas = items.filter((i) => i.type === "idea" && i.status === "ready").length;

  async function change(payload) {
    if (busy) return false;
    setBusy(true);
    setError("");
    setSuccess("");
    const result = await api("/api/workboard", payload, "POST");
    setBusy(false);
    if (result.status !== 200 || !result.data.ok) {
      setError(result.data.error || "Не удалось сохранить изменения. Проверь подключение.");
      return false;
    }
    setItems(result.data.items);
    return true;
  }

  async function create(e) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    const saved = await change({ action: "create", type: kind, title: title.trim(), note, priority });
    if (saved) {
      setTitle(""); setNote(""); setPriority("normal");
      setSuccess(kind === "task" ? "Задача сохранена." : "Идея сохранена.");
    }
  }
  async function update(item, patch) {
    const saved = await change({ action: "update", id: item.id, ...patch });
    if (saved) setSuccess("Статус обновлён.");
  }
  function scheduleItem(item) {
    if (prepareScheduleDraft(item)) navigate("scheduler");
  }
  async function remove(item) {
    if (!window.confirm("Удалить запись «" + item.title + "»?")) return;
    const saved = await change({ action: "delete", id: item.id });
    if (saved) setSuccess("Запись удалена.");
  }

  return (
    <div class="cc-page stack">
      <header class="cc-hero">
        <span class="cc-kicker">DENDICH / RADIO SILENCE / OPERATIONS</span>
        <h2>Оперативный центр</h2>
        <p>Общий рабочий план команды: задачи Discord-сервера и идеи для будущих роликов и стримов. Данные хранятся в базе бота.</p>
        <div class="cc-overview">
          <div><b>{loading ? "…" : openTasks}</b><span>активных задач</span></div>
          <div><b>{loading ? "…" : readyIdeas}</b><span>идей к выпуску</span></div>
          <div><b>{loading ? "…" : items.length}</b><span>всего записей</span></div>
        </div>
      </header>

      <div class="cc-layout">
        <section class="card cc-work">
          <div class="cc-section-head">
            <div><span class="cc-kicker">MISSION BOARD</span><h3>Рабочие записи</h3></div>
            <button class="btn" type="button" onClick={refresh} disabled={busy}><Icon name="refresh" size={15}/> Обновить</button>
          </div>

          <div class="cc-toolbar">
            <div class="cc-tabs" role="group" aria-label="Тип записей">
              <button class={kind === "task" ? "active" : ""} type="button" onClick={() => { setKind("task"); setTitle(""); setNote(""); }}>Задачи</button>
              <button class={kind === "idea" ? "active" : ""} type="button" onClick={() => { setKind("idea"); setTitle(""); setNote(""); }}>Идеи контента</button>
            </div>
            <input class="input cc-search" type="search" placeholder="Поиск по записям…" value={query} onInput={(e) => setQuery(e.currentTarget.value)}/>
          </div>
          {error ? <div class="cc-feedback cc-error" role="alert">{error}</div> : null}
          {success ? <div class="cc-feedback cc-success" role="status">{success}</div> : null}

          {canEdit ? <form class="cc-compose" onSubmit={create}>
            <label>
              <span>{kind === "task" ? "Новая задача" : "Новая идея"}</span>
              <input class="input" maxLength={120} required value={title} onInput={(e) => setTitle(e.currentTarget.value)}
                placeholder={kind === "task" ? "Например: обновить правила сервера" : "Например: лучшие моменты из Arma Reforger"}/>
            </label>
            <label>
              <span>Детали (необязательно)</span>
              <textarea class="input" rows={2} maxLength={2000} value={note} onInput={(e) => setNote(e.currentTarget.value)}
                placeholder="Что нужно сделать, ссылки, заметки…"/>
            </label>
            <div class="cc-compose-foot">
              <label class="cc-select-row">Приоритет
                <select class="input" value={priority} onChange={(e) => setPriority(e.currentTarget.value)}>
                  <option value="normal">Обычный</option><option value="high">Высокий</option>
                </select>
              </label>
              <button class="btn primary" type="submit" disabled={busy || !title.trim()}>
                <Icon name="plus" size={16}/> {busy ? "Сохранение…" : "Добавить"}
              </button>
            </div>
          </form> : <p class="muted small cc-readonly">Просмотр доступен модераторам. Добавление и изменение записей — администраторам.</p>}

          <div class="cc-entries">
            {loading ? <p class="muted">Загрузка записей…</p> : filtered.length === 0
              ? <div class="cc-empty">Здесь пока ничего нет. {canEdit ? "Создай первую запись выше." : ""}</div>
              : filtered.map((item) => <Item key={item.id} item={item} canEdit={canEdit} busy={busy} onUpdate={update} onDelete={remove} onSchedule={scheduleItem}/>)}
          </div>
        </section>

        <aside class="cc-links card">
          <div class="cc-section-head"><div><span class="cc-kicker">QUICK ACCESS</span><h3>Управление сервером</h3></div></div>
          <p class="muted small">Быстрый переход к уже работающим инструментам бота.</p>
          <div class="cc-links-grid">
            {QUICK.map((link) => <button key={link.section} type="button" class="cc-nav-card" onClick={() => navigate(link.section)}>
              <Icon name={link.icon} size={20} />
              <span><b>{link.label}</b><small>{link.desc}</small></span>
              <Icon name="chevron-right" size={16}/>
            </button>)}
          </div>
          <div class="cc-note">
            <span class="cc-kicker">ВАЖНО</span>
            <p>Записи в этом разделе — внутренний план команды. Нажми «В планировщик», чтобы подготовить публикацию. Сообщение уйдёт в Discord только после выбора канала, времени и подтверждения расписания.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
