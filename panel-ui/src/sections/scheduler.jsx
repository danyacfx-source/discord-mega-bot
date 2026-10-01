import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast, fmtDateTime } from "../lib/exports.js";
import { Chip, Empty, Field, ListRow, Loading } from "../components/ui.jsx";

const EMPTY_FORM = { channel_id: "", at: "", content: "", title: "", desc: "", color: "" };

export default function Scheduler() {
  const [channels, setChannels] = useState([]);
  const [data, setData] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);

  async function load() {
    if (!channels.length) {
      const ch = await api("/api/bot/channels");
      const list = (ch.data && ch.data.channels) || [];
      setChannels(list);
      setForm((f) => ({ ...f, channel_id: f.channel_id || (list[0] && list[0].id) || "" }));
    }
    const r = await api("/api/schedule");
    setData(r.data || { upcoming: [], done: [] });
  }

  useEffect(() => {
    load();
  }, []);

  async function create() {
    if (!form.channel_id) return toast("Выберите канал", false);
    if (!form.at) return toast("Укажите дату и время", false);
    if (!form.content && !form.title && !form.desc) return toast("Укажите текст или эмбед", false);
    const when = new Date(form.at);
    if (isNaN(when)) return toast("Некорректная дата", false);
    if (when <= Date.now()) return toast("Дата должна быть в будущем", false);
    const embed = {};
    if (form.title) embed.title = form.title;
    if (form.desc) embed.description = form.desc;
    if (form.color) embed.color = form.color;
    const r = await api("/api/schedule", { channel_id: form.channel_id, send_at: when.toISOString(), content: form.content, embed });
    if (r.status === 200 && r.data.ok) {
      toast("🗓 Запланировано на " + new Date(r.data.send_at).toLocaleString("ru-RU"), true);
      setForm({ ...EMPTY_FORM, channel_id: form.channel_id });
      load();
    } else toast(errToast(r), false);
  }

  async function cancel(s) {
    if (!confirm(`Отменить запланированное #${s.id}?`)) return;
    const r = await api(`/api/schedule/${s.id}`, null, "DELETE");
    if (r.status === 200 && r.data.ok) {
      toast("🗑 Отменено", true);
      load();
    } else toast("❌ Не удалось отменить", false);
  }

  function schLine(s, done) {
    return (
      <ListRow key={s.id}>
        <Chip tone={done ? undefined : "ok"}>#{s.id}</Chip>
        <span class="grow">
          <b>{s.title || s.content || "Без заголовка"}</b>{" "}
          <span class="sub">
            {s.channel_name} · {String(s.content || "").slice(0, 80)}
          </span>
        </span>
        <Chip>{fmtDateTime(s.send_at)}</Chip>
        {!done && (
          <button class="btn mini danger" type="button" title="Отменить" onClick={() => cancel(s)}>
            ✖
          </button>
        )}
      </ListRow>
    );
  }

  const upcoming = (data && data.upcoming) || [];
  const done = (data && data.done) || [];

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">⏰ Отложенное сообщение</h3>
        <div class="three">
          <div class="stack">
            <Field label="Канал">
              <select class="input" value={form.channel_id} onChange={(e) => setForm({ ...form, channel_id: e.target.value })}>
                {!channels.length && <option value="">— нет каналов —</option>}
                {channels.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.category ? c.category + " / " : ""}
                    {c.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Дата и время отправки">
              <input class="input" type="datetime-local" value={form.at} onInput={(e) => setForm({ ...form, at: e.target.value })} />
            </Field>
          </div>
          <Field label="Текст">
            <textarea class="input" rows="4" maxlength="2000" placeholder="Текст сообщения…" value={form.content} onInput={(e) => setForm({ ...form, content: e.target.value })} />
          </Field>
          <div class="stack">
            <Field label="Заголовок эмбеда">
              <input class="input" type="text" maxlength="256" value={form.title} onInput={(e) => setForm({ ...form, title: e.target.value })} />
            </Field>
            <Field label="Описание">
              <textarea class="input" rows="2" maxlength="4000" value={form.desc} onInput={(e) => setForm({ ...form, desc: e.target.value })} />
            </Field>
            <Field label="Цвет">
              <input class="input" type="text" placeholder="#5865f2" value={form.color} onInput={(e) => setForm({ ...form, color: e.target.value })} />
            </Field>
          </div>
        </div>
        <div class="row-inline">
          <button class="btn primary" type="button" onClick={create}>🗓 Запланировать</button>
          <span class="muted small">Отправка — от имени бота в выбранный канал.</span>
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Ожидают отправки</h3>
        <div class="list">
          {!data && <Loading />}
          {data && !upcoming.length && <Empty>Ожидающих отправки нет</Empty>}
          {upcoming.map((s) => schLine(s, false))}
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Отправленные</h3>
        <div class="list">
          {!data && <Loading />}
          {data && !done.length && <Empty>Отправленных пока нет</Empty>}
          {done.map((s) => schLine(s, true))}
        </div>
      </div>
    </div>
  );
}
