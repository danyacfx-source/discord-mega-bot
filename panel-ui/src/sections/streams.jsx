import { useEffect, useState } from "preact/hooks";
import { api, toast, downloadAuthed } from "../lib/exports.js";
import { Chip, Empty, Field, ListRow, Loading } from "../components/ui.jsx";

function liveFor(session) {
  if (!session || !session.started_at) return "";
  const started = Date.parse(session.started_at);
  if (Number.isNaN(started)) return "";
  const mins = Math.max(0, Math.round((Date.now() - started) / 60000));
  if (mins < 60) return `${mins} мин`;
  return `${Math.floor(mins / 60)} ч ${mins % 60} мин`;
}

export default function Streams() {
  const [data, setData] = useState(null);
  const [watch, setWatch] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [promo, setPromo] = useState({ enabled: true, text: "", interval_minutes: 30 });
  const [savingPromo, setSavingPromo] = useState(false);
  const [sendingPromo, setSendingPromo] = useState(false);
  const [commands, setCommands] = useState(null);
  const [savingCommands, setSavingCommands] = useState(false);
  const [control, setControl] = useState(null);
  const [controlBusy, setControlBusy] = useState(false);

  async function load() {
    const r = await api("/api/streams");
    if (r.status !== 200) {
      if (r.data.error) toast(r.data.error, false);
      return;
    }
    setData(r.data);
  }

  async function loadWatch() {
    const r = await api("/api/streams/watchers");
    if (r.status === 200) setWatch(r.data);
  }

  async function loadPromo() {
    const r = await api("/api/twitch/promo");
    if (r.status === 200 && r.data.ok) setPromo(r.data.promo);
  }

  async function savePromo() {
    setSavingPromo(true);
    const r = await api("/api/twitch/promo", promo);
    setSavingPromo(false);
    if (r.status === 200 && r.data.ok) {
      setPromo(r.data.promo);
      toast("Автосообщение Twitch сохранено", true);
    } else toast(r.data.error || "Не удалось сохранить", false);
  }

  async function sendPromoNow() {
    setSendingPromo(true);
    const r = await api("/api/twitch/promo/send", { text: promo.text });
    setSendingPromo(false);
    if (r.status === 200 && r.data.ok) {
      if (r.data.sent.length) {
        toast(`Отправлено в: ${r.data.sent.join(", ")}`, true);
      } else {
        toast("Сейчас ни один настроенный Twitch-канал не в эфире", false);
      }
    } else toast(r.data.error || "Не удалось отправить сообщение", false);
  }

  async function loadCommands() {
    const r = await api("/api/twitch/commands");
    if (r.status === 200 && r.data.ok) setCommands(r.data.commands);
  }

  async function loadControl() {
    const r = await api("/api/twitch/control");
    if (r.status === 200 && r.data.ok) setControl(r.data.control);
  }

  async function setCommandsPaused(paused) {
    setControlBusy(true);
    const r = await api("/api/twitch/control", { action: "commands_paused", paused });
    setControlBusy(false);
    if (r.status === 200 && r.data.ok) {
      setControl({ ...control, commands_paused: r.data.commands_paused });
      toast(r.data.commands_paused ? "Команды Twitch приостановлены" : "Команды Twitch включены", true);
    } else toast(r.data.error || "Не удалось изменить режим команд", false);
  }

  async function reconnectChat() {
    setControlBusy(true);
    const r = await api("/api/twitch/control", { action: "reconnect" });
    setControlBusy(false);
    if (r.status === 200 && r.data.ok) {
      toast("Переподключение Twitch-чата запрошено", true);
      setTimeout(loadControl, 1200);
    } else toast(r.data.error || "Не удалось переподключить чат", false);
  }

  function updateCommand(id, patch) {
    setCommands((current) => current.map((command) => command.id === id ? { ...command, ...patch } : command));
  }

  async function saveCommands(nextCommands = commands) {
    if (!nextCommands) return;
    setSavingCommands(true);
    const payload = Object.fromEntries(nextCommands.map((command) => [command.id, {
      enabled: command.enabled,
      aliases: command.aliases,
      moderator_only: command.moderator_only,
      response: command.response,
    }]));
    const r = await api("/api/twitch/commands", { commands: payload });
    setSavingCommands(false);
    if (r.status === 200 && r.data.ok) {
      setCommands(r.data.commands);
      toast("Команды Twitch сохранены", true);
    } else toast(r.data.error || "Не удалось сохранить команды", false);
  }

  async function resetCommands() {
    if (!commands || !confirm("Вернуть все команды Twitch к стандартным настройкам?")) return;
    const reset = commands.map((command) => ({
      ...command,
      enabled: true,
      aliases: command.default_aliases,
      moderator_only: command.default_moderator_only,
      response: "",
    }));
    setCommands(reset);
    await saveCommands(reset);
  }

  async function exportCsv() {
    setExporting(true);
    try {
      const ok = await downloadAuthed("/api/streams/archive/export", "streams-archive.csv");
      if (ok) toast("Архив эфиров выгружен", true);
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    load();
    loadWatch();
    loadPromo();
    loadCommands();
    loadControl();
    const t = setInterval(() => {
      load();
      loadWatch();
      loadControl();
    }, 30000);
    return () => clearInterval(t);
  }, []);

  const streams = (data && data.streams) || [];

  return (
    <div class="stack">
      <div class="card">
        <div class="card-head">
          <h3>Стримы</h3>
          <div class="row-inline">
            <button class="btn mini" type="button" onClick={exportCsv} disabled={exporting} title="Экспорт архива завершённых эфиров в CSV">CSV
            </button>
            <button class="btn mini" type="button" onClick={load}>Обновить</button>
          </div>
        </div>
        <div class="list">
          {!data && <Loading />}
          {data && !streams.length && (
            <Empty>Не настроены TWITCH_CHANNELS, KICK_CHANNEL_SLUG или VK_CHANNEL_SLUG</Empty>
          )}
          {streams.map((s) => {
            const session = s.session;
            const isLive = !!s.live;
            return (
              <ListRow key={s.label}>
                <Chip tone={isLive ? "ok" : "bad"}>{isLive ? "● LIVE" : "○ офлайн"}</Chip>
                <span class="grow">
                  <b>{s.label}</b>
                  <div class="sub">
                    {isLive ? (
                      <>
                        {session.title || "Без названия"}
                        {session.viewers != null ? ` · ${session.viewers}` : ""}
                        {session.peak ? ` · пик ${session.peak}` : ""}
                        {s.trend != null ? ` · ${s.trend >= 0 ? "▲ +" : "▼ "}${s.trend} за 10 мин` : ""}
                        {liveFor(session) ? ` · ${liveFor(session)}` : ""}
                        {session.category && session.category !== "—" ? ` · ${session.category}` : ""}
                      </>
                    ) : (
                      <>
                        {session ? `Последний эфир: ${session.title || "Без названия"}${session.peak ? ` · пик ${session.peak}` : ""}` : "Эфиров ещё не было"}
                        {" "}· поллинг каждые {s.poll_seconds} с
                        {s.notify_channel_id ? ` · канал #${s.notify_channel_id}` : " · канал уведомлений не задан"}
                      </>
                    )}
                  </div>
                </span>
                <a class="btn mini" href={s.url} target="_blank" rel="noreferrer">открыть ↗</a>
              </ListRow>
            );
          })}
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div>
            <h3 class="sec">Пульт Twitch</h3>
            <p class="muted small">Состояние чат-бота и быстрые действия во время эфира.</p>
          </div>
          <button class="btn mini" type="button" onClick={loadControl}>Обновить</button>
        </div>
        {!control && <Loading />}
        {control && <div class="stack">
          <div class="two">
            <div class="env-box">
              <b>{control.connected ? "● Чат подключён" : "○ Чат не подключён"}</b>
              <div class="muted small">Режим: {control.mode} · переподключений: {control.reconnects}</div>
              {control.last_connected_at && <div class="muted small">Последнее подключение: {new Date(control.last_connected_at).toLocaleString()}</div>}
              {control.last_error && <div class="muted small">Последнее состояние: {control.last_error}</div>}
            </div>
            <div class="env-box">
              <b>{control.commands_paused ? "Команды на паузе" : "Команды активны"}</b>
              <div class="muted small">Каналы: {control.channels.join(", ") || "не настроены"}</div>
              <div class="muted small">Пауза не отключает чтение чата для OBS и не мешает автосообщениям.</div>
            </div>
          </div>
          <div class="row-inline">
            <button class="btn danger" type="button" disabled={controlBusy} onClick={() => setCommandsPaused(!control.commands_paused)}>{control.commands_paused ? "Включить команды" : "Пауза всех команд"}</button>
            <button class="btn" type="button" disabled={controlBusy || !control.connected} onClick={reconnectChat}>Переподключить чат</button>
          </div>
        </div>}
      </div>

      <div class="card">
        <div class="card-head">
          <div>
            <h3 class="sec">Команды Twitch</h3>
            <p class="muted small">Настройки действуют только на основном Twitch-канале с командами. Kick и второй промо-канал не затрагиваются.</p>
          </div>
          <div class="row-inline">
            <button class="btn" type="button" onClick={resetCommands} disabled={!commands || savingCommands}>Сбросить</button>
            <button class="btn success" type="button" onClick={() => saveCommands()} disabled={!commands || savingCommands}>{savingCommands ? "Сохраняем…" : "Сохранить команды"}</button>
          </div>
        </div>
        {!commands && <Loading />}
        {commands && <div class="stack">
          <div class="env-box muted small">Шаблоны ответа: <b>{"{default}"}</b> — стандартный динамический ответ, <b>{"{user}"}</b> — имя зрителя, <b>{"{args}"}</b> — текст после команды, <b>{"{channel}"}</b> — Twitch-канал. Пустое поле оставляет стандартный ответ.</div>
          {commands.map((command) => (
            <details class="env-box" key={command.id}>
              <summary style={{ cursor: "pointer" }}>
                <b>{command.label}</b>
                <span class="muted small"> · {command.aliases.map((alias) => `!${alias}`).join(", ")} · {command.enabled ? "включена" : "выключена"}</span>
              </summary>
              <div class="stack" style={{ marginTop: 12 }}>
                <div class="muted small">{command.description}</div>
                <div class="row-inline">
                  <label class="row-inline">
                    <input type="checkbox" checked={command.enabled} onInput={(e) => updateCommand(command.id, { enabled: e.target.checked })} />
                    Включить команду
                  </label>
                  <label class="row-inline">
                    <input type="checkbox" checked={command.moderator_only} onInput={(e) => updateCommand(command.id, { moderator_only: e.target.checked })} />
                    Только модераторы
                  </label>
                </div>
                <Field label="Алиасы" hint="Через запятую, без восклицательного знака. Один алиас нельзя назначить двум командам.">
                  <input class="input" type="text" value={command.aliases.join(", ")} onInput={(e) => updateCommand(command.id, { aliases: e.target.value.split(",").map((value) => value.trim()).filter(Boolean) })} />
                </Field>
                <Field label="Шаблон ответа" hint="До 450 символов; пусто — стандартный ответ.">
                  <textarea class="input" rows="2" maxLength="450" value={command.response} onInput={(e) => updateCommand(command.id, { response: e.target.value })} />
                </Field>
              </div>
            </details>
          ))}
        </div>}
      </div>

      <div class="card">
        <h3 class="sec">Автосообщение Twitch</h3>
        <p class="muted small">Отправляется с заданным интервалом только в каналы из TWITCH_CHANNELS, где идёт эфир.</p>
        <div class="stack">
          <label class="row-inline">
            <input type="checkbox" checked={promo.enabled} onInput={(e) => setPromo({ ...promo, enabled: e.target.checked })} />
            Включить автосообщение
          </label>
          <Field label="Текст сообщения" hint="До 450 символов; Twitch-ссылки лучше указывать полностью.">
            <textarea class="input" rows="3" maxLength="450" value={promo.text} onInput={(e) => setPromo({ ...promo, text: e.target.value })} />
          </Field>
          <Field label="Интервал автосообщения" hint="От 5 до 180 минут. Применяется сразу после сохранения.">
            <input class="input" type="number" min="5" max="180" step="1" value={promo.interval_minutes} onInput={(e) => setPromo({ ...promo, interval_minutes: Number(e.target.value) })} />
          </Field>
          <div class="row-inline">
            <button class="btn success" type="button" onClick={savePromo} disabled={savingPromo}>{savingPromo ? "Сохраняем…" : "Сохранить"}</button>
            <button class="btn" type="button" onClick={sendPromoNow} disabled={sendingPromo}>{sendingPromo ? "Отправляем…" : "Отправить сейчас"}</button>
          </div>
          <p class="muted small">Ручная отправка использует текст из поля и работает независимо от переключателя автосообщения. В офлайн-каналы сообщение не уходит.</p>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <h3>Зрители Kick</h3>
          <button class="btn mini" type="button" onClick={loadWatch}>Обновить</button>
        </div>
        {!watch && <Loading />}
        {watch && !watch.kick_enabled && <Empty>Не задан KICK_CHANNEL_SLUG — сессии зрителей выключены</Empty>}
        {watch && watch.kick_enabled && (
          <div class="two">
            <div class="stack">
              <div class="muted small">Сейчас в чате · {watch.active.length}</div>
              <div class="list">
                {!watch.active.length && <Empty>никого нет — зритель появляется после первого сообщения</Empty>}
                {watch.active.slice(0, 10).map((v) => (
                  <ListRow key={v.name}>
                    <Chip tone="ok">онлайн</Chip>
                    <span class="grow">
                      <b>{v.name}</b>
                      <div class="sub">сообщений за сессию: {v.messages}</div>
                    </span>
                  </ListRow>
                ))}
              </div>
            </div>
            <div class="stack">
              <div class="muted small">Топ говорящих за эфир</div>
              <div class="list">
                {!watch.top.length && <Empty>пока пусто</Empty>}
                {watch.top.map((t, i) => (
                  <ListRow key={t.name}>
                    <Chip tone={i === 0 ? "warn" : ""}>#{i + 1}</Chip>
                    <span class="grow">
                      <b>{t.name}</b>
                      <div class="sub">сообщений: {t.count}</div>
                    </span>
                  </ListRow>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div class="card">
        <h3 class="sec">Глобальные настройки</h3>
        <div class="two">
          <Field label="Роль «В эфире»">
            <div class="env-box muted small">
              {data && data.role_id ? (
                <span>
                  Роль <b>{data.role_id}</b>
                  {data.role_user_ids.length ? ` · броадкастеры: ${data.role_user_ids.join(", ")}` : ""}
                </span>
              ) : (
                <span>не задана — STREAM_ROLE_ID выключен</span>
              )}
            </div>
          </Field>
          <Field label="Тихий час (без пинга роли)">
            <div class="env-box muted small">
              {data && data.quiet_hours ? (
                <span>
                  ежедневно <b>{data.quiet_hours}</b> (часы сервера)
                </span>
              ) : (
                <span>выключен — STREAM_QUIET_HOURS не задан</span>
              )}
            </div>
          </Field>
        </div>
        <Field label="Роль «На стриме» (🔔 RSVP)">
          <div class="env-box muted small">
            {data && data.rsvp_role_id ? (
              <span>
                Роль <b>{data.rsvp_role_id}</b> · {data.rsvp_role_name}
              </span>
            ) : data ? (
              <span>не найдена — создайте роль «На стриме» или задайте STREAM_RSVP_ROLE_ID</span>
            ) : (
              <span>…</span>
            )}
          </div>
        </Field>
        <Field label="Табло во время эфира">
          <div class="env-box muted small">
            {data ? (
              <span>
                обновление каждые <b>{data.sticky_poll_seconds} с</b>, вне эфира — базовый интервал поллинга
              </span>
            ) : (
              <span>…</span>
            )}
          </div>
        </Field>
      </div>
    </div>
  );
}
