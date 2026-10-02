import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast, fmtDateTime } from "../lib/exports.js";
import { Chip, Empty, Field, ListRow, Loading } from "../components/ui.jsx";

async function findMember(query) {
  if (!query) return null;
  const r = await api("/api/server/members?q=" + encodeURIComponent(query));
  const list = (r.data && r.data.members) || [];
  if (list.length === 1) return list[0];
  const q = query.toLowerCase();
  const exact = list.find(
    (m) => m.display_name.toLowerCase() === q || m.name.toLowerCase() === q || m.id === query.replace(/[#\s]/g, ""),
  );
  return exact || (list.length ? list[0] : null);
}

const ACTION_TONES = { ban: "bad", kick: "bad", timeout: "warn", warn: "warn", unban: "ok", untimeout: "ok" };

export default function Moderation() {
  const [warns, setWarns] = useState(null);
  const [filter, setFilter] = useState("");
  const [target, setTarget] = useState("");
  const [member, setMember] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(10);
  const [cases, setCases] = useState(null);
  const [casesScope, setCasesScope] = useState("guild");

  async function loadWarns() {
    const r = await api("/api/moderation/warns");
    setWarns((r.data && r.data.warns) || []);
  }

  async function loadCases(scope, memberArg) {
    const s = scope || "guild";
    const targetMember = memberArg !== undefined ? memberArg : member;
    if (s === "user" && !targetMember) return;
    setCasesScope(s);
    setCases(null);
    const url = s === "user" ? "/api/moderation/cases?user_id=" + targetMember.id : "/api/moderation/cases";
    const r = await api(url);
    if (r.status === 200 && r.data.ok) setCases(r.data.cases || []);
    else {
      setCases([]);
      toast(errToast(r), false);
    }
  }

  useEffect(() => {
    loadWarns();
    loadCases("guild");
  }, []);

  async function search() {
    if (!target.trim()) return toast("Введите участника", false);
    const m = await findMember(target.trim());
    if (!m) {
      setMember(null);
      setNotFound(true);
      return;
    }
    setNotFound(false);
    setMember(m);
    loadCases("user", m);
  }

  async function act(url, body, okMsg, method) {
    if (!member) {
      toast("Сначала найдите участника", false);
      return false;
    }
    const r = await api(url, body, method);
    if (r.status === 200 && r.data.ok) {
      if (okMsg) toast(okMsg(r.data), true);
      return true;
    }
    toast(errToast(r), false);
    return false;
  }

  async function doWarn() {
    if (
      await act("/api/moderation/warn", { member: member.id, reason: reason.trim() || "Без причины" }, (d) => `⚠ Варн выдан, всего: ${d.count}`)
    ) {
      setReason("");
      loadWarns();
      const m = await findMember(target.trim() || member.id);
      if (m) setMember(m);
    }
  }

  async function doKick() {
    if (!confirm("Кикнуть " + member.display_name + "?")) return;
    if (await act("/api/moderation/kick", { member: member.id, reason }, () => "👢 Участник кикнут")) {
      setMember(null);
      setTarget("");
    }
  }

  async function doBan() {
    if (!confirm("Забанить " + member.display_name + "?")) return;
    if (await act("/api/moderation/ban", { member: member.id, reason, delete_days: 0 }, () => "🔨 Участник забанен")) {
      setMember(null);
      setTarget("");
    }
  }

  async function doTimeout() {
    if (!confirm(`Тайм-аут ${member.display_name} на ${minutes} мин?`)) return;
    await act(
      "/api/moderation/timeout",
      { member: member.id, duration_seconds: minutes * 60, reason },
      (d) => "⏳ Тайм-аут до " + new Date(d.until).toLocaleTimeString("ru-RU"),
    );
  }

  async function doClear() {
    if (!confirm("Снять все предупреждения у " + member.display_name + "?")) return;
    if (await act("/api/moderation/clear", { member: member.id }, (d) => `🧹 Снято варнов: ${d.cleared}`)) loadWarns();
  }

  async function doUnban() {
    const userId = prompt("ID пользователя для разбана:");
    if (!userId) return;
    const r = await api("/api/moderation/unban", { user_id: userId.trim(), reason: "Разбан из панели" });
    if (r.status === 200 && r.data.ok) toast("♻️ Разбанен: " + r.data.user_name, true);
    else toast(errToast(r), false);
  }

  async function removeWarn(id) {
    const r = await api("/api/moderation/warns/" + id, null, "DELETE");
    if (r.status === 200 && r.data.ok) {
      toast(`✅ Предупреждение #${id} снято`, true);
      loadWarns();
      if (member) {
        const m = await findMember(target.trim() || member.id);
        if (m) setMember(m);
      }
    } else {
      toast("❌ Не удалось снять", false);
    }
  }

  const q = filter.toLowerCase().trim();
  const list = warns == null ? null : q ? warns.filter((w) => (w.user_name || "").toLowerCase().includes(q) || String(w.user_id).includes(q)) : warns;

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">🛡 Модерация</h3>
        <Field label="Участник (имя, ник или ID)">
          <div class="row-inline">
            <input
              class="input"
              type="text"
              placeholder="Например: admin или 123456789…"
              value={target}
              onInput={(e) => setTarget(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search()}
            />
            <button class="btn" type="button" onClick={search}>
              🔍 Найти
            </button>
          </div>
        </Field>

        <div class="mod-member" style={{ marginTop: "10px" }}>
          {notFound && <div class="muted small">Участник не найден.</div>}
          {member && (
            <ListRow>
              <img class="av" src={member.avatar} alt="" />
              <span class="grow">
                <b>{member.display_name}</b> <span class="sub">{member.name} # {member.id}</span>
              </span>
              <Chip>{member.top_role}</Chip>
              {member.is_bot ? <Chip>бот</Chip> : null}
              <Chip tone={member.warnings ? "warn" : undefined}>варнов: {member.warnings || 0}</Chip>
            </ListRow>
          )}
          {!member && !notFound && <div class="muted small">Введите участника и нажмите «Найти».</div>}
        </div>

        {member && (
          <div class="mod-actions">
            <Field label="Причина">
              <input class="input" type="text" placeholder="Причина (для варна / кика / бана)" value={reason} onInput={(e) => setReason(e.target.value)} />
            </Field>
            <Field label="Тайм-аут, минут">
              <input class="input" type="number" min="1" max="40320" value={minutes} onInput={(e) => setMinutes(parseInt(e.target.value, 10) || 10)} />
            </Field>
            <div class="row-actions wrap">
              <button class="btn" type="button" onClick={doWarn}>⚠ Варн</button>
              <button class="btn" type="button" onClick={doKick}>👢 Кик</button>
              <button class="btn danger" type="button" onClick={doBan}>🔨 Бан</button>
              <button class="btn" type="button" onClick={doTimeout}>⏳ Тайм-аут</button>
              <button class="btn" type="button" onClick={doClear}>🧹 Снять варны</button>
            </div>
          </div>
        )}

        <div class="row-inline" style={{ marginTop: "12px" }}>
          <button class="btn" type="button" onClick={doUnban}>
            ♻️ Разбан по ID
          </button>
        </div>
      </div>

      <div class="card">
        <h3 class="sec">
          Предупреждения {list && list.length ? <span class="muted small">· всего: {list.length}</span> : null}
        </h3>
        <div class="row-inline" style={{ margin: "0 0 10px" }}>
          <input class="input" type="text" placeholder="Фильтр по участнику…" value={filter} onInput={(e) => setFilter(e.target.value)} />
          <button class="btn" type="button" onClick={loadWarns}>⟳</button>
        </div>
        <div class="list">
          {list == null && <Loading />}
          {list != null && !list.length && <Empty>Предупреждений нет</Empty>}
          {list &&
            list.map((w) => (
              <ListRow key={w.id}>
                <Chip tone="bad">#{w.id}</Chip>
                <span class="grow">
                  <b>{w.user_name || w.user_id}</b> <span class="sub">· модератор: {w.moderator_name || w.moderator_id}</span>
                </span>
                <span class="sub nowrap">{fmtDateTime(w.created_at)}</span>
                <span class="sub grow ellipsis">{w.reason}</span>
                <button class="btn mini danger" type="button" title="Снять предупреждение" onClick={() => removeWarn(w.id)}>
                  ✖
                </button>
              </ListRow>
            ))}
        </div>
      </div>

      <div class="card">
        <h3 class="sec">
          📋 История действий {cases && cases.length ? <span class="muted small">· всего: {cases.length}</span> : null}
        </h3>
        <div class="row-inline" style={{ margin: "0 0 10px" }}>
          <button class={"btn" + (casesScope === "guild" ? " success" : "")} type="button" onClick={() => loadCases("guild")}>
            Все действия
          </button>
          <button
            class={"btn" + (casesScope === "user" ? " success" : "")}
            type="button"
            disabled={!member}
            title={member ? "" : "Сначала найдите участника"}
            onClick={() => member && loadCases("user", member)}
          >
            По участнику
          </button>
        </div>
        <div class="list">
          {cases == null && <Loading />}
          {cases != null && !cases.length && <Empty>Действий не было</Empty>}
          {cases &&
            cases.map((c) => (
              <ListRow key={c.case_id}>
                <Chip tone={ACTION_TONES[c.action]}>{c.action}</Chip>
                <span class="grow">
                  <b>{c.user_name || c.user_id}</b> <span class="sub">· модератор: {c.moderator_name || c.moderator_id}</span>
                </span>
                <span class="sub nowrap">{fmtDateTime(c.created_at)}</span>
                <span class="sub grow ellipsis">{c.reason || "—"}</span>
                {c.active ? <Chip tone="warn">active</Chip> : null}
              </ListRow>
            ))}
        </div>
      </div>
    </div>
  );
}
