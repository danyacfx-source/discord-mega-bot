import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast, relTime } from "../lib/exports.js";
import { Chip, Empty, Field, ListRow, Loading } from "../components/ui.jsx";

export default function Giveaways() {
  const [channels, setChannels] = useState([]);
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ channel_id: "", prize: "", winners: 1, minutes: 60, min_days: 0 });

  async function load() {
    if (!channels.length) {
      const ch = await api("/api/bot/channels");
      const list = (ch.data && ch.data.channels) || [];
      setChannels(list);
      setForm((f) => ({ ...f, channel_id: f.channel_id || (list[0] && list[0].id) || "" }));
    }
    const r = await api("/api/giveaways");
    setData(r.data || {});
  }

  useEffect(() => {
    load();
  }, []);

  async function create() {
    if (!form.channel_id) return toast("Выберите канал", false);
    if (!form.prize.trim()) return toast("Укажите приз", false);
    const r = await api("/api/giveaways/create", {
      channel_id: form.channel_id,
      prize: form.prize.trim(),
      winners: form.winners,
      duration_minutes: form.minutes,
      min_days: form.min_days,
    });
    if (r.status === 200 && r.data.ok) {
      toast(`Розыгрыш запущен (#${r.data.id})`, true);
      setForm((f) => ({ ...f, prize: "" }));
      load();
    } else toast(errToast(r), false);
  }

  async function endGv(g) {
    if (!confirm(`Завершить розыгрыш «${g.prize}»?`)) return;
    const r = await api("/api/giveaways/end", { message_id: g.message_id });
    if (r.status === 200 && r.data.ok) toast("Завершён. Победители: " + r.data.winners, true);
    else toast(errToast(r), false);
    load();
  }

  async function reroll(g) {
    if (!confirm(`Переразыграть приз «${g.prize}»?`)) return;
    const r = await api("/api/giveaways/reroll", { message_id: g.message_id });
    if (r.status === 200 && r.data.ok) toast("Новые победители: " + r.data.winners, true);
    else toast(errToast(r), false);
    load();
  }

  const active = (data && data.active) || [];
  const finished = (data && data.finished) || [];

  function gvLine(g, isFinished) {
    return (
      <ListRow key={g.id}>
        <Chip tone="ok">#{g.id}</Chip>
        <span class="grow">
          <b>{g.prize}</b> <span class="sub">· {g.channel_name} · автор: {g.author_name}</span>
        </span>
        <Chip>{g.entries}
          {g.min_days ? ` · ${g.min_days} дн` : ""}
        </Chip>
        <Chip>{g.winners}</Chip>
        <Chip>{isFinished ? "завершён" : "до " + relTime(g.ends_at)}</Chip>
        <div class="row-actions">
          <button class="btn mini" type="button" title={`Скопировать ID сообщения: ${g.message_id || "—"}`} onClick={() => navigator.clipboard && navigator.clipboard.writeText(g.message_id || "")}>
            ID
          </button>
          {isFinished ? (
            <button class="btn mini" type="button" onClick={() => reroll(g)}>Переразыграть
            </button>
          ) : (
            <button class="btn mini" type="button" onClick={() => endGv(g)}>
              Завершить
            </button>
          )}
        </div>
      </ListRow>
    );
  }

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">Новый розыгрыш</h3>
        <div class="two">
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
            <Field label="Приз">
              <input class="input" type="text" maxlength="256" placeholder="Что разыгрываем?" value={form.prize} onInput={(e) => setForm({ ...form, prize: e.target.value })} />
            </Field>
          </div>
          <div class="stack">
            <div class="grid cols4">
              <Field label="Победителей">
                <input class="input" type="number" min="1" max="20" value={form.winners} onInput={(e) => setForm({ ...form, winners: parseInt(e.target.value, 10) || 1 })} />
              </Field>
              <Field label="Длительность, мин">
                <input class="input" type="number" min="1" max="43200" value={form.minutes} onInput={(e) => setForm({ ...form, minutes: parseInt(e.target.value, 10) || 60 })} />
              </Field>
              <Field label="Мин. дней на сервере">
                <input class="input" type="number" min="0" value={form.min_days} onInput={(e) => setForm({ ...form, min_days: parseInt(e.target.value, 10) || 0 })} />
              </Field>
            </div>
            <div class="row-inline" style={{ marginTop: "8px" }}>
              <button class="btn success" type="button" onClick={create}>Запустить
              </button>
              <span class="muted small">Максимум — 30 дней, победителей до 20.</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Активные розыгрыши</h3>
        <div class="list">
          {!data && <Loading />}
          {data && !active.length && <Empty>Активных розыгрышей нет</Empty>}
          {active.map((g) => gvLine(g, false))}
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Завершённые</h3>
        <div class="list">
          {!data && <Loading />}
          {data && !finished.length && <Empty>Завершённых пока нет</Empty>}
          {finished.map((g) => gvLine(g, true))}
        </div>
      </div>
    </div>
  );
}
