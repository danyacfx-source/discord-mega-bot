import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";
import { Chip, Empty, ListRow, Loading } from "../components/ui.jsx";

export default function TempVoice() {
  const [data, setData] = useState(null);

  async function load() {
    const r = await api("/api/tempvoice");
    if (r.status !== 200) {
      if (r.data.error) toast("❌ " + r.data.error, false);
      return;
    }
    setData(r.data);
  }

  useEffect(() => {
    load();
  }, []);

  async function transfer(rm, ownerId) {
    if (!ownerId) return;
    const r = await api(`/api/tempvoice/${rm.channel_id}/transfer`, { owner_id: ownerId });
    if (r.status === 200 && r.data.ok) toast("🔁 Владелец: " + r.data.owner_name, true);
    else toast(errToast(r), false);
    load();
  }

  async function remove(rm) {
    if (!confirm(`Удалить комнату «${rm.name || rm.channel_id}»?`)) return;
    const r = await api(`/api/tempvoice/${rm.channel_id}/delete`, {});
    if (r.status === 200 && r.data.ok) toast("🔊 Комната удалена", true);
    else toast(errToast(r), false);
    load();
  }

  if (!data) return <Loading />;

  const triggers = (data.triggers || []).length
    ? data.triggers.map((t) => t.name || t.id).join(", ")
    : "—";
  const rooms = data.rooms || [];
  const members = data.members || [];

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">🔊 Временные голосовые</h3>
        <p class="muted small" style={{ margin: 0 }}>
          Триггер-каналы и категория задаются в <code>.env</code> (TEMP_VOICE_TRIGGER_IDS /
          TEMP_VOICE_CATEGORY_ID); здесь — список активных комнат, удаление и передача владельца.
        </p>
        <div class="chips-row">
          <Chip>
            Триггер-каналы: <b>{triggers}</b>
          </Chip>
          <Chip>
            Категория: <b>{data.category_name || "—"}</b>
          </Chip>
          <Chip>
            Комнат: <b>{rooms.length}</b>
          </Chip>
        </div>
      </div>

      <div class="card">
        <h3 class="sec">Комнаты</h3>
        <div class="list">
          {!rooms.length && <Empty>Активных голосовых комнат нет</Empty>}
          {rooms.map((rm) => (
            <ListRow key={rm.channel_id}>
              <Chip>🔊</Chip>
              <span class="grow">
                <b>{rm.name || "(канал удалён)"}</b> <span class="sub">· владелец: {rm.owner_name || rm.owner_id}</span>
              </span>
              <div class="row-actions">
                <select
                  class="input mini-select"
                  title="Передать владельца"
                  value=""
                  onChange={(e) => transfer(rm, e.target.value)}
                >
                  <option value="">— передать —</option>
                  {members
                    .filter((m) => m.id !== rm.owner_id)
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                </select>
                <button class="btn mini danger" type="button" onClick={() => remove(rm)}>
                  🗑 Удалить
                </button>
              </div>
            </ListRow>
          ))}
        </div>
      </div>
    </div>
  );
}
