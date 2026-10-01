import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";
import { Chip, Empty, Field, ListRow, Loading } from "../components/ui.jsx";

function PollRow({ p, active, onEnd }) {
  const counts = p.counts || {};
  return (
    <ListRow>
      <Chip>#{p.id}</Chip>
      <span class="grow">
        <b>{p.question}</b>{" "}
        <span class="sub">
          · {p.author_name} · {p.channel_name} · голосов: {p.total}
        </span>
        <div class="poll-bars">
          {(p.options || []).map((opt, i) => {
            const votes = counts[i] || 0;
            const pct = p.total ? Math.round((votes / p.total) * 100) : 0;
            return (
              <div class="poll-bar" key={opt}>
                <span class="grow">{opt}</span>
                <div class="poll-track">
                  <div class="poll-fill" style={{ width: pct + "%" }} />
                </div>
                <Chip>
                  {votes} ({pct}%)
                </Chip>
              </div>
            );
          })}
        </div>
      </span>
      {active && (
        <div class="row-actions">
          <button class="btn mini danger" type="button" onClick={() => onEnd(p)}>
            ⬛ Завершить
          </button>
        </div>
      )}
    </ListRow>
  );
}

export default function Polls() {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ channel_id: "", question: "", options: "" });

  async function load() {
    const r = await api("/api/polls");
    if (r.status !== 200) {
      if (r.data.error) toast("❌ " + r.data.error, false);
      return;
    }
    setData(r.data);
    setForm((f) => ({ ...f, channel_id: f.channel_id || ((r.data.channels || [])[0] || {}).id || "" }));
  }

  useEffect(() => {
    load();
  }, []);

  async function create() {
    const options = form.options.split("\n").map((o) => o.trim()).filter(Boolean);
    if (!options.length) return toast("Введите варианты ответа", false);
    const r = await api("/api/polls/create", { channel_id: form.channel_id, question: form.question, options });
    if (r.status === 200 && r.data.ok) {
      toast(`🗳 Опрос #${r.data.poll_id} создан`, true);
      setForm({ ...form, question: "", options: "" });
      load();
    } else toast(errToast(r), false);
  }

  async function endPoll(p) {
    if (!confirm(`Завершить опрос #${p.id}? Итоги уйдут в канал.`)) return;
    const r = await api(`/api/polls/${p.id}/end`, {});
    if (r.status === 200 && r.data.ok) toast(`📊 Опрос #${p.id} завершён`, true);
    else toast(errToast(r), false);
    load();
  }

  const channels = (data && data.channels) || [];
  const polls = (data && data.polls) || [];
  const active = polls.filter((p) => p.active);
  const finished = polls.filter((p) => !p.active);

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">🗳 Новый опрос</h3>
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
            <Field label="Вопрос">
              <input class="input" type="text" maxlength="256" placeholder="За какой вариант?" value={form.question} onInput={(e) => setForm({ ...form, question: e.target.value })} />
            </Field>
          </div>
          <div class="stack">
            <Field label="Варианты (2–5, по одному на строку)">
              <textarea class="input" rows="5" placeholder={"Вариант 1\nВариант 2"} value={form.options} onInput={(e) => setForm({ ...form, options: e.target.value })} />
            </Field>
            <div class="row-inline">
              <button class="btn success" type="button" onClick={create}>🗳 Создать опрос</button>
              <span class="muted small">Участники голосуют кнопками в Discord.</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Активные</h3>
        <div class="list">
          {!data && <Loading />}
          {data && !active.length && <Empty>Активных опросов нет</Empty>}
          {active.map((p) => (
            <PollRow key={p.id} p={p} active onEnd={endPoll} />
          ))}
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Завершённые</h3>
        <div class="list">
          {!data && <Loading />}
          {data && !finished.length && <Empty>Завершённых опросов нет</Empty>}
          {finished.map((p) => (
            <PollRow key={p.id} p={p} active={false} onEnd={endPoll} />
          ))}
        </div>
      </div>
    </div>
  );
}
