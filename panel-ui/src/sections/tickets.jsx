import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast, downloadAuthed, fmtDateTime } from "../lib/exports.js";
import { Chip, Empty, Field, ListRow, Loading } from "../components/ui.jsx";

const TEXT_FIELDS = [
  ["tk_title", "ticket_panel_title", "Заголовок панели", "Поддержка", 256],
  ["tk_desc", "ticket_panel_description", "Описание панели", "Нажмите на кнопку, чтобы открыть тикет.", 4000],
  ["tk_footer", "ticket_panel_footer", "Футер панели (пусто — без футера)", "Тикеты помогают решать личные вопросы без шума в каналах.", 2048],
  ["tk_open_label", "ticket_open_label", "Кнопка «Открыть тикет» — текст", "Открыть тикет", 80],
  ["tk_open_emoji", "ticket_open_emoji", "… — эмодзи (пусто — без эмодзи)", "🎫", 16],
  ["tk_intro_title", "ticket_intro_title", "Заголовок внутри тикета", "Новый тикет", 256],
  ["tk_intro_desc", "ticket_intro_description", "Текст внутри тикета ({member} — упоминание)", "Опишите свою проблему, {member}.", 4000],
  ["tk_intro_footer", "ticket_intro_footer", "Футер внутри тикета", "Нажмите кнопку ниже, чтобы закрыть тикет по завершении.", 2048],
  ["tk_prefix", "ticket_channel_prefix", "Префикс названия канала", "ticket", 24],
  ["tk_close_label", "ticket_close_label", "Кнопка «Закрыть тикет» — текст", "Закрыть тикет", 80],
  ["tk_close_emoji", "ticket_close_emoji", "… — эмодзи (пусто — без эмодзи)", "🔒", 16],
];

export default function Tickets() {
  const [data, setData] = useState(null);
  const [panel, setPanel] = useState(null);
  const [categoryId, setCategoryId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [texts, setTexts] = useState({});

  async function load() {
    const [r, p] = await Promise.all([api("/api/tickets"), api("/api/tickets/panel")]);
    setData(r.data || { open: [], closed: [] });
    if (p.data && p.data.ok) {
      setPanel(p.data);
      if (p.data.category_id) setCategoryId(String(p.data.category_id));
      const list = p.data.channels || [];
      setChannelId((cur) => cur || (list[0] && String(list[0].id)) || "");
      setTexts({ ...(p.data.texts || {}) });
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function saveCategory() {
    if (!categoryId) return toast("Выберите категорию", false);
    const r = await api("/api/tickets/panel", { category_id: categoryId });
    if (r.status === 200 && r.data.ok) toast("💾 Категория тикетов сохранена", true);
    else toast(errToast(r), false);
  }

  async function sendPanel() {
    if (!channelId) return toast("Выберите канал", false);
    const r = await api("/api/tickets/panel", { channel_id: channelId, category_id: categoryId || "" });
    if (r.status === 200 && r.data.ok) toast("🎫 Панель отправлена", true);
    else toast(errToast(r), false);
  }

  async function saveTexts() {
    const payload = {};
    for (const [local, apiKey] of TEXT_FIELDS) payload[apiKey] = texts[local] !== undefined ? texts[local] : "";
    const r = await api("/api/tickets/panel", payload);
    if (r.status === 200 && r.data.ok) toast("💾 Тексты тикетов сохранены", true);
    else toast(errToast(r), false);
  }

  async function closeTicket(t) {
    if (!confirm(`Закрыть тикет #${t.id} (${t.creator_name || t.creator_id})? Канал будет удалён.`)) return;
    const r = await api(`/api/tickets/${t.id}/close`, {});
    if (r.status === 200 && r.data.ok) toast(`🔒 Тикет #${t.id} закрыт`, true);
    else toast(errToast(r), false);
    load();
  }

  function tkLine(t, open) {
    return (
      <ListRow key={t.id}>
        <Chip>#{t.id}</Chip>
        <span class="grow">
          <b>{t.creator_name || t.creator_id}</b>{" "}
          <span class="sub">
            · {t.channel_name || "(канал удалён)"} · открыт {fmtDateTime(t.created_at)}
            {!open ? " · закрыт " + fmtDateTime(t.closed_at) : ""}
            {t.has_transcript ? " · 📄 транскрипт" : ""}
          </span>
        </span>
        <Chip tone={open ? "ok" : undefined}>{open ? "открыт" : "закрыт"}</Chip>
        <div class="row-actions">
          {t.has_transcript && (
            <button class="btn mini" type="button" title="Скачать транскрипт" onClick={() => downloadAuthed(`/api/tickets/${t.id}/transcript`, `ticket-${t.id}.txt`)}>
              📄
            </button>
          )}
          {open && (
            <button class="btn mini danger" type="button" onClick={() => closeTicket(t)}>
              🔒 Закрыть
            </button>
          )}
        </div>
      </ListRow>
    );
  }

  const open = (data && data.open) || [];
  const closed = (data && data.closed) || [];
  const categories = (panel && panel.categories) || [];
  const channels = (panel && panel.channels) || [];

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">🎟️ Панель тикетов</h3>
        <div class="two">
          <Field label="Категория для новых тикетов">
            <select class="input" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              <option value="">— не выбрана —</option>
              {categories.map((c) => (
                <option key={c.id} value={String(c.id)}>{c.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Канал для панели-кнопки «Открыть тикет»">
            <select class="input" value={channelId} onChange={(e) => setChannelId(e.target.value)}>
              {!channels.length && <option value="">— нет доступных каналов —</option>}
              {channels.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.category ? c.category + " / " : ""}
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div class="row-inline" style={{ marginTop: "14px" }}>
          <button class="btn primary" type="button" onClick={saveCategory}>💾 Сохранить категорию</button>
          <button class="btn success" type="button" onClick={sendPanel}>🎫 Отправить панель</button>
          <span class="muted small">Панель отправится сообщением с кнопкой.</span>
        </div>
      </div>

      <div class="card">
        <h3 class="sec">✏️ Внешний вид и тексты</h3>
        <p class="muted small" style={{ margin: "0 0 12px" }}>
          Тексты панели, кнопок и сообщения внутри тикета. Применяется к новым панелям и тикетам.
        </p>
        {!panel ? (
          <Loading />
        ) : (
          <>
            <div class="form-grid">
              {TEXT_FIELDS.map(([local, , label, ph, max]) => (
                <Field key={local} label={label}>
                  <input
                    class="input"
                    type="text"
                    maxlength={max}
                    placeholder={ph}
                    value={texts[local] !== undefined ? texts[local] : ""}
                    onInput={(e) => setTexts({ ...texts, [local]: e.target.value })}
                  />
                </Field>
              ))}
            </div>
            <div class="row-inline" style={{ marginTop: "14px" }}>
              <button class="btn success" type="button" onClick={saveTexts}>💾 Сохранить тексты</button>
              <span class="muted small">Изменения применятся к новым панелям и тикетам.</span>
            </div>
          </>
        )}
      </div>

      <div class="card">
        <div class="card-head">
          <h3>🎫 Тикеты</h3>
          <span class="muted small">Открытые и закрытые обращения сервера.</span>
        </div>
        <div class="list">
          {!data && <Loading />}
          {data && !open.length && <Empty>Открытых тикетов нет</Empty>}
          {open.map((t) => tkLine(t, true))}
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Закрытые</h3>
        <div class="list">
          {!data && <Loading />}
          {data && !closed.length && <Empty>Закрытых тикетов нет</Empty>}
          {closed.map((t) => tkLine(t, false))}
        </div>
      </div>
    </div>
  );
}
