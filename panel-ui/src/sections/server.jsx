import { useEffect, useState } from "preact/hooks";
import { api, toast } from "../lib/exports.js";
import { Icon } from "../components/icons.jsx";
import { Chip, Empty, Field, ListRow, Loading } from "../components/ui.jsx";

export default function Server() {
  const [data, setData] = useState(null);
  const [members, setMembers] = useState([]);
  const [member, setMember] = useState("");
  const [roleId, setRoleId] = useState("");
  const [result, setResult] = useState("");
  const [failed, setFailed] = useState(false);

  async function loadMembers() {
    const r = await api("/api/server/members?q=");
    setMembers((r.data && r.data.members) || []);
  }

  useEffect(() => {
    let alive = true;
    (async () => {
      const r = await api("/api/server");
      if (!alive) return;
      if (r.status !== 200 || !r.data.ok) {
        setFailed(true);
        return;
      }
      setData(r.data);
      if (r.data.roles && r.data.roles.length) setRoleId(String(r.data.roles[0].id));
    })();
    loadMembers();
    return () => {
      alive = false;
    };
  }, []);

  if (failed) return <div class="card">Не удалось загрузить сервер</div>;
  if (!data) return <Loading />;

  const g = data.guild || {};
  const cats = data.categories || [];
  const roles = data.roles || [];

  async function roleAction(act) {
    setResult("");
    if (!member) return toast("Укажите участника", false);
    if (!roleId) return toast("Укажите роль", false);
    const r = await api("/api/server/members/roles", { member, role_id: roleId, action: act });
    if (r.status === 200 && r.data.ok) {
      setResult((act === "add" ? "Роль выдана" : "Роль снята") + ": " + r.data.member_name + " → " + r.data.role_name);
      loadMembers();
      toast(r.data.applied ? "Готово" : "Уже в таком состоянии", r.data.applied);
    } else {
      toast(r.data.error ? r.data.error : "Ошибка", false);
    }
  }

  return (
    <div class="stack">
      <div class="card guild-hero-card">
        <div class="guild-hero">
          {g.icon ? (
            <img class="guild-icon" src={g.icon} alt="" />
          ) : (
            <div class="brand-ic guild-icon">{(g.name || "?").charAt(0).toUpperCase()}</div>
          )}
          <div class="guild-copy">
            <h3>
              {g.name || "—"} {g.level ? <Chip>{g.level}</Chip> : null}
            </h3>
            {g.description ? <p class="muted small">{g.description}</p> : null}
            <div class="chips-row">
              <Chip>Участников <b>{g.members || 0}</b></Chip>
              <Chip>Онлайн <b>{g.online || 0}</b></Chip>
              <Chip>Бустов <b>{g.boosts || 0}</b></Chip>
              <Chip>Каналов <b>{g.channels || 0}</b></Chip>
              <Chip>Ролей <b>{g.roles || 0}</b></Chip>
              {g.owner ? <Chip>Владелец <b>{g.owner}</b></Chip> : null}
            </div>
            <div class="chips-row">
              {g.created_at ? <Chip>Создан {new Date(g.created_at).toLocaleDateString("ru-RU")}</Chip> : null}
              {(g.me_permissions || []).map((p) => (
                <Chip key={p}>Бот: {p}</Chip>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div class="two">
        <div class="card">
          <h3 class="sec">Каналы <span class="muted small">· клик по строке копирует ID</span></h3>
          <div class="channels-tree">
            {!cats.length && <Empty>Каналы недоступны</Empty>}
            {cats.map((cat) => (
              <div class="cat-block" key={cat.name || "none"}>
                <div class="cat-name">{cat.name || "Без категории"}</div>
                {(cat.channels || []).map((ch) => {
                  const isV = ch.type === "voice";
                  return (
                    <div key={ch.id}>
                      <div
                        class="channel-row clickable"
                        title="Клик — копировать ID"
                        onClick={() => navigator.clipboard && navigator.clipboard.writeText(String(ch.id))}
                      >
                        <span class="ic">{isV ? <Icon name="speaker" size={14} /> : "#"}</span>
                        <span class="grow">{ch.name}</span>
                        {ch.nsfw ? <Chip>NSFW</Chip> : null}
                        {ch.slowmode ? <Chip>{ch.slowmode} с</Chip> : null}
                        {isV ? <Chip>{ch.voice_online || 0}</Chip> : null}
                      </div>
                      {isV && ch.voice_users && ch.voice_users.length ? (
                        <div class="vc-users muted small">{ch.voice_users.map((u) => u.display_name).join(", ")}</div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <div class="card">
          <h3 class="sec">Роли</h3>
          <div class="list">
            {!roles.length && <Empty>Роли недоступны</Empty>}
            {roles.map((role) => (
              <ListRow key={role.id} title="Клик — копировать ID" onClick={() => navigator.clipboard && navigator.clipboard.writeText(String(role.id))}>
                <span class="role-dot" style={{ background: role.color }} />
                <span class="grow">
                  {role.name} {role.managed ? <Chip>интегрированная</Chip> : null}
                </span>
                {role.hoist ? <Chip>в списке</Chip> : null}
                <Chip>{role.member_count}</Chip>
              </ListRow>
            ))}
          </div>

          <hr class="divider" />
          <h3 class="sec">Выдача ролей</h3>
          <Field label="Участник (имя или ID)">
            <div class="row-inline">
              <input
                class="input"
                type="text"
                list="member_list_srv"
                placeholder="Начните писать…"
                value={member}
                onInput={(e) => setMember(e.target.value)}
              />
              <datalist id="member_list_srv">
                {members.map((m) => (
                  <option key={m.id} value={m.is_bot ? `${m.name} (бот) #${m.id}` : `${m.display_name} #${m.id}`} />
                ))}
              </datalist>
              <button class="btn" type="button" onClick={loadMembers} title="Обновить список">
                <Icon name="refresh" size={15} />
              </button>
            </div>
          </Field>
          <Field label="Роль">
            <select class="input" value={roleId} onChange={(e) => setRoleId(e.target.value)}>
              {roles.map((role) => (
                <option key={role.id} value={String(role.id)}>
                  {role.name}
                </option>
              ))}
            </select>
          </Field>
          <div class="row-inline">
            <button class="btn primary" type="button" onClick={() => roleAction("add")}>
              ＋ Выдать
            </button>
            <button class="btn danger" type="button" onClick={() => roleAction("remove")}>
              − Снять
            </button>
          </div>
          {result ? <div class="muted small" style={{ marginTop: "8px" }}>{result}</div> : null}
        </div>
      </div>
    </div>
  );
}
