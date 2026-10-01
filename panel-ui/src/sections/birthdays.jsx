import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";
import { Chip, Empty, Field, ListRow, Loading } from "../components/ui.jsx";

export default function Birthdays() {
  const [data, setData] = useState(null);
  const [memberId, setMemberId] = useState("");
  const [date, setDate] = useState("");

  async function load() {
    const r = await api("/api/birthdays");
    if (r.status !== 200) {
      if (r.data.error) toast("❌ " + r.data.error, false);
      return;
    }
    setData(r.data);
    setMemberId((cur) => cur || "");
  }

  useEffect(() => {
    load();
  }, []);

  async function add() {
    if (!memberId) return toast("Выберите участника", false);
    const m = /^(\d{1,2})\.(\d{1,2})$/.exec(date.trim());
    if (!m) return toast("Дата в формате дд.мм (например, 15.08)", false);
    const r = await api("/api/birthdays", { member_id: memberId, day: +m[1], month: +m[2] });
    if (r.status === 200 && r.data.ok) {
      toast("🎂 Добавлено: " + r.data.name, true);
      setDate("");
      load();
    } else toast(errToast(r), false);
  }

  async function remove(b) {
    if (!confirm(`Убрать день рождения ${b.name}?`)) return;
    const r = await api(`/api/birthdays/${b.user_id}/remove`, {}, "POST");
    if (r.status === 200 && r.data.ok) toast("🎂 Удалено", true);
    else toast(errToast(r), false);
    load();
  }

  const members = (data && data.members) || [];
  const list = (data && data.birthdays) || [];

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">🎂 Дни рождения</h3>
        <div class="two">
          <div class="stack">
            <Field label="Участник">
              <select class="input" value={memberId} onChange={(e) => setMemberId(e.target.value)}>
                <option value="">— выберите участника —</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Дата (дд.мм)">
              <input class="input" type="text" placeholder="15.08" value={date} onInput={(e) => setDate(e.target.value)} />
            </Field>
          </div>
          <div class="stack">
            <Field label="Канал анонса (из .env BIRTHDAY_CHANNEL_ID)">
              <div class="env-box muted small">
                {data && data.channel_id ? (
                  <span>Канал <b>#{data.channel_id}</b></span>
                ) : (
                  <span>не задан — анонс не отправляется</span>
                )}
              </div>
            </Field>
            <div class="row-inline">
              <button class="btn success" type="button" onClick={add}>🎂 Добавить</button>
              <span class="muted small">Анонс в указанный час — как у /birthday.</span>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Список</h3>
        <div class="list">
          {!data && <Loading />}
          {data && !list.length && <Empty>Дней рождения ещё нет</Empty>}
          {list.map((b) => (
            <ListRow key={b.user_id}>
              <Chip>
                {String(b.day).padStart(2, "0")}.{String(b.month).padStart(2, "0")}
              </Chip>
              <span class="grow">
                <b>{b.name}</b> <span class="sub">· {b.user_id}</span>
              </span>
              <button class="btn mini danger" type="button" title="Удалить" onClick={() => remove(b)}>
                ✕
              </button>
            </ListRow>
          ))}
        </div>
      </div>
    </div>
  );
}
