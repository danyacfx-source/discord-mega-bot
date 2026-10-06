import { useEffect, useState } from "preact/hooks";
import { api, navigate, fmtCount, relTime } from "../lib/exports.js";
import { subscribeEvents } from "../lib/events.js";
import { Sparkline, Stat } from "../components/widgets.jsx";
import { Icon } from "../components/icons.jsx";

const PLATFORM = {
  twitch: { label: "Twitch", color: "#9146ff" },
  kick: { label: "Kick", color: "#53fc18" },
  vk_video: { label: "VK Видео", color: "#0077ff" },
};

function meta(platform) {
  return PLATFORM[platform] || { label: platform || "?", color: "var(--accent)" };
}

function duration(iso) {
  const start = Date.parse(iso || "");
  if (isNaN(start)) return "";
  const total = Math.max(0, Math.floor((Date.now() - start) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return h ? `${h} ч ${m} мин` : `${m} мин`;
}

function hhmm(iso) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export default function ViewersSection() {
  const [streams, setStreams] = useState([]);
  const [watchers, setWatchers] = useState(null);
  const [sel, setSel] = useState("");

  async function load() {
    const [a, b] = await Promise.all([api("/api/streams"), api("/api/streams/watchers")]);
    if (a.status === 200 && Array.isArray(a.data.streams)) {
      const list = a.data.streams;
      setStreams(list);
      setSel((cur) => {
        if (cur && list.some((s) => s.label === cur)) return cur;
        return (list.find((s) => s.live) || list[0] || {}).label || "";
      });
    }
    if (b.status === 200) setWatchers(b.data);
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);
    const off = subscribeEvents((ev) => {
      if (ev.type === "stream") load();
    });
    return () => {
      clearInterval(timer);
      off();
    };
  }, []);

  if (!streams.length) {
    return (
      <div class="ov">
        <div class="card">
          <div class="card-head">
            <h3>Зрители</h3>
            <span class="muted small">живой счётчик без открытия Twitch</span>
          </div>
          <div class="muted small">Данных пока нет — бот отдаёт статус стримов после первого поллинга.</div>
          <div class="row-inline" style={{ marginTop: 12 }}>
            <button class="btn" type="button" onClick={() => navigate("streams")}>
              Настроить стримы
            </button>
          </div>
        </div>
      </div>
    );
  }

  const cur = streams.find((s) => s.label === sel) || streams[0];
  const pm = meta(cur.platform);
  const session = cur.session || null;
  const live = Boolean(cur.live);
  const history = (Array.isArray(session?.history) ? session.history : []).filter((p) => Number.isFinite(Number(p.v)));
  const values = history.map((p) => Number(p.v));
  const viewers = live && session ? Number(session.viewers || 0) : null;
  const peak = session ? Number(session.peak || 0) : 0;
  const wb = watchers && watchers.platforms ? watchers.platforms[cur.platform] : null;
  const chatOn = Boolean(wb && wb.enabled);
  const active = chatOn ? wb.active : [];
  const top = chatOn ? wb.top : [];

  return (
    <div class="ov">
      <div class="card">
        <div class="card-head">
          <h3>Зрители</h3>
          <span class="muted small">опрос каждые 10 с · событие со стрима обновляет сразу</span>
        </div>
        {streams.length > 1 && (
          <div class="chips-row">
            {streams.map((s) => (
              <button
                type="button"
                key={s.label}
                class={"chip" + (s.label === cur.label ? " on" : "") + (s.live ? " tone-ok" : "")}
                onClick={() => setSel(s.label)}
              >
                {meta(s.platform).label} · {s.live ? "LIVE" : "офлайн"}
              </button>
            ))}
          </div>
        )}
        <div class="row-inline" style={{ marginTop: 12, gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <span class={"chip " + (live ? "tone-ok" : "tone-bad")}>{live ? "● LIVE" : "○ офлайн"}</span>
          <b>{live && session ? session.title || "Без названия" : pm.label}</b>
          {live && session?.started_at && <span class="muted small">в эфире {duration(session.started_at)}</span>}
          {live && cur.trend != null && (
            <span class={"chip " + (cur.trend >= 0 ? "tone-ok" : "tone-bad")}>
              {cur.trend >= 0 ? "▲ +" : "▼ "}
              {cur.trend} за 10 мин
            </span>
          )}
          {session?.captured_at && <span class="muted small">обновлено {relTime(session.captured_at)}</span>}
          {cur.url && (
            <a class="muted small" href={cur.url} target="_blank" rel="noreferrer">
              открыть {pm.label}
            </a>
          )}
        </div>
      </div>

      <div class="grid stats-grid">
        <Stat
          icon="eye"
          label="Сейчас смотрят"
          value={viewers != null ? fmtCount(viewers) : "—"}
          sub={live ? `опрос каждые ${cur.poll_seconds} с` : "стрим офлайн"}
        />
        <Stat icon="trending" label="Пик эфира" value={peak ? fmtCount(peak) : "—"} sub={session?.started_at ? `с ${hhmm(session.started_at)}` : "нет данных"} />
        <Stat
          icon="activity"
          label="Тренд"
          value={live && cur.trend != null ? (cur.trend >= 0 ? `▲ +${cur.trend}` : `▼ ${cur.trend}`) : "—"}
          sub="за последние 10 мин"
          tone={live && cur.trend != null && cur.trend < 0 ? "warn" : undefined}
        />
        <Stat
          icon="message"
          label={`В чате ${pm.label}`}
          value={chatOn ? String(active.length) : "—"}
          sub={
            chatOn
              ? "активны прямо сейчас"
              : cur.platform === "vk_video"
                ? "чат не отслеживается"
                : `${pm.label} не подключён`
          }
        />
      </div>

      <div class="grid charts-grid">
        <div class="card chart-card">
          <div class="card-head">
            <h3>График зрителей</h3>
            <span class="muted small">
              {history.length > 1 ? `${hhmm(history[0].t)} → ${hhmm(history[history.length - 1].t)}` : "нет сэмплов"}
            </span>
          </div>
          <Sparkline points={history} height={180} color={pm.color} label="зрители" />
          {values.length > 1 && (
            <div class="row-inline muted small" style={{ justifyContent: "space-between", marginTop: 6 }}>
              <span>мин {fmtCount(Math.min(...values))}</span>
              <span>сэмплов: {values.length} (раз в минуту)</span>
              <span>макс {fmtCount(Math.max(...values))}</span>
            </div>
          )}
        </div>

        <div class="card">
          <div class="card-head">
            <h3>Чат</h3>
            <span class="muted small">
              {chatOn ? `${pm.label} · кто сейчас пишет и топ за эфир` : "недоступно"}
            </span>
          </div>
          {!chatOn ? (
            <div class="muted small">
              {cur.platform === "vk_video"
                ? "Для VK Видео чат не отслеживается — активные и топ есть для Twitch и Kick."
                : `${pm.label} не подключён — активные в чате и топ говорящих недоступны.`}
            </div>
          ) : (
            <div class="stack">
              <div>
                <div class="muted small" style={{ marginBottom: 6 }}>
                  Сейчас в чате: <b>{active.length}</b>
                </div>
                <div class="chips-row">
                  {active.length === 0 && <span class="muted small">пока никого — первый же сообщение откроет сессию</span>}
                  {active.slice(0, 12).map((a) => (
                    <span class="chip" key={a.name}>
                      {a.name}
                      {a.messages ? <b> · {a.messages}</b> : null}
                    </span>
                  ))}
                </div>
              </div>
              <div class="list">
                <div class="muted small" style={{ marginBottom: 4 }}>
                  Топ говорящих за эфир
                </div>
                {top.length === 0 && <div class="muted small">Сообщений пока нет.</div>}
                {top.slice(0, 5).map((t, i) => (
                  <div class="listline" key={t.name}>
                    <span class="chip">{i + 1}</span>
                    <span class="grow">
                      <b>{t.name}</b>
                    </span>
                    <span class="muted small">{t.count} сообщ.</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div class="muted small">
        <Icon name="eye" size={13} /> Источник: поллинг Twitch/Kick/VK ботом, история хранит последние 60 замеров
        (час эфира).
      </div>
    </div>
  );
}
