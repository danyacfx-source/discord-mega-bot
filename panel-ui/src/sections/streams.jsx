import { useEffect, useState } from "preact/hooks";
import { api, toast } from "../lib/exports.js";
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

  async function load() {
    const r = await api("/api/streams");
    if (r.status !== 200) {
      if (r.data.error) toast("❌ " + r.data.error, false);
      return;
    }
    setData(r.data);
  }

  async function loadWatch() {
    const r = await api("/api/streams/watchers");
    if (r.status === 200) setWatch(r.data);
  }

  useEffect(() => {
    load();
    loadWatch();
    const t = setInterval(() => {
      load();
      loadWatch();
    }, 30000);
    return () => clearInterval(t);
  }, []);

  const streams = (data && data.streams) || [];

  return (
    <div class="stack">
      <div class="card">
        <div class="card-head">
          <h3>📺 Стримы</h3>
          <button class="btn mini" type="button" onClick={load}>↻ Обновить</button>
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
                        {session.viewers != null ? ` · 👁 ${session.viewers}` : ""}
                        {session.peak ? ` · 📈 пик ${session.peak}` : ""}
                        {s.trend != null ? ` · ${s.trend >= 0 ? "▲ +" : "▼ "}${s.trend} за 10 мин` : ""}
                        {liveFor(session) ? ` · ⏱ ${liveFor(session)}` : ""}
                        {session.category && session.category !== "—" ? ` · 🎮 ${session.category}` : ""}
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
          <h3>👀 Зрители Kick</h3>
          <button class="btn mini" type="button" onClick={loadWatch}>↻ Обновить</button>
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
