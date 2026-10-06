import { useEffect, useState } from "preact/hooks";
import { api } from "../api.js";
import { navigate } from "../store.js";
import { fmtCount } from "../lib/exports.js";
import { subscribeEvents } from "../lib/events.js";
import { Sparkline, Stat } from "../components/widgets.jsx";
import { Icon } from "../components/icons.jsx";

const EMPTY = {
  bot_online: false,
  bot_name: "…",
  uptime: "—",
  uptime_seconds: 0,
  latency_ms: 0,
  mem_mb: 0,
  mem_peak_mb: 0,
};

const PLATFORM = {
  twitch: { label: "Twitch", color: "#9146ff" },
  kick: { label: "Kick", color: "#53fc18" },
  vk_video: { label: "VK Видео", color: "#0077ff" },
  discord: { label: "Discord", color: "#5865f2" },
};

function meta(platform) {
  return PLATFORM[platform] || { label: platform || "?", color: "var(--accent)" };
}

function uptime(iso, now) {
  const start = Date.parse(iso || "");
  if (isNaN(start)) return "—";
  const total = Math.max(0, Math.floor((now - start) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
}

function chatTime(ts) {
  const d = new Date(Number(ts) * 1000);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function feedLine(ev) {
  const d = ev.data || {};
  const t = String(ev.ts || "").slice(11, 19);
  if (ev.type === "stream") {
    const live = d.status === "live";
    const label = d.platform === "kick" ? "Kick" : "Twitch";
    return {
      key: ev.seq,
      icon: "monitor",
      tag: `${label}${live ? " ● LIVE" : " ○ офлайн"}`,
      tone: live ? "tone-ok" : "tone-bad",
      msg: live
        ? `${d.title || "Без названия"}${d.viewers ? ` · ${d.viewers}` : ""}`
        : d.url || "",
      t,
    };
  }
  if (ev.type === "donation") {
    return {
      key: ev.seq,
      icon: "banknote",
      tag: "Донат",
      tone: "tone-ok",
      msg: `${d.username} — ${d.amount} ${d.currency}${d.message ? ` · ${String(d.message).slice(0, 120)}` : ""}`,
      t,
    };
  }
  if (ev.type === "error") {
    return { key: ev.seq, icon: "circle-x", tag: "Ошибка", tone: "tone-bad", msg: d.msg || "", t };
  }
  const audit = Boolean(d.cat && d.cat !== "sys");
  return {
    key: ev.seq,
    icon: audit ? "bell" : "alert",
    tag: audit ? `Аудит · ${d.cat}` : d.level || "WARNING",
    tone: audit ? "" : "warn",
    msg: d.msg || "",
    t,
  };
}

function LiveCard({ stream, now, rsvpHint }) {
  const s = stream;
  const pm = meta(s.platform);
  const session = s.session || {};
  const history = session.history || [];
  const values = history.map((h) => (typeof h === "number" ? h : h.v)).filter((v) => Number.isFinite(v));
  return (
    <div class="card live-card">
      <div class="card-head">
        <span class="row-inline" style={{ gap: 8 }}>
          <span class="live-badge">
            <span class="live-dot" /> LIVE
          </span>
          <b>{s.label}</b>
        </span>
        <a class="pill link" href={s.url} target="_blank" rel="noreferrer">
          открыть ↗
        </a>
      </div>
      <div class="live-title">{session.title || "Без названия"}</div>
      <div class="live-grid">
        <div class="live-stats">
          <div class="live-num" style={{ color: pm.color }}>
            {fmtCount(session.viewers || 0)}
          </div>
          <div class="muted small">зрителей сейчас</div>
          <div class="live-row small">
            <span>⏱ {uptime(session.started_at, now)}</span>
            <span>пик {fmtCount(session.peak || 0)}</span>
            {s.trend != null ? <span>{s.trend >= 0 ? `▲ +${s.trend}` : `▼ ${s.trend}`} за 10 мин</span> : null}
            <span class="rsvp-hint">🔔 {rsvpHint}</span>
          </div>
        </div>
        <div class="live-spark">
          <Sparkline points={history} height={96} color={pm.color} label="зрители" />
        </div>
      </div>
    </div>
  );
}

export default function Overview() {
  const [ov, setOv] = useState(EMPTY);
  const [mon, setMon] = useState({ latency: [], mem: [], online: [] });
  const [streams, setStreams] = useState([]);
  const [chat, setChat] = useState([]);
  const [feed, setFeed] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  async function loadAll() {
    const [a, b, c] = await Promise.all([api("/api/overview"), api("/api/monitor"), api("/api/streams")]);
    if (a.status === 200) setOv({ ...EMPTY, ...a.data });
    if (b.status === 200) setMon({ latency: b.data.latency || [], mem: b.data.mem || [], online: b.data.online || [] });
    if (c.status === 200) setStreams(c.data.streams || []);
    setLoaded(true);
  }

  useEffect(() => {
    loadAll();
    const t = setInterval(() => {
      if (!document.hidden) loadAll();
    }, 10000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let alive = true;
    async function loadChat() {
      if (document.hidden) return;
      const r = await api("/api/streams/chat?n=80");
      if (alive && r.status === 200) setChat((r.data.messages || []).slice().reverse());
    }
    loadChat();
    const t = setInterval(loadChat, 4000);
    document.addEventListener("visibilitychange", loadChat);
    return () => {
      alive = false;
      clearInterval(t);
      document.removeEventListener("visibilitychange", loadChat);
    };
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(
    () =>
      subscribeEvents((ev) => {
        setFeed((prev) => [feedLine(ev), ...prev].slice(0, 40));
        if (ev.type === "stream") loadAll();
      }),
    [],
  );

  const g = ov.guild || {};
  const online = ov.bot_online;
  const live = streams.filter((s) => s.live);
  const last = streams
    .filter((s) => s.session)
    .sort((a, b) => String(b.session.captured_at).localeCompare(String(a.session.captured_at)))[0];

  return (
    <div class="ov">
      <div class="hero card">
        <div class="hero-main">
          <div class={"hero-status" + (online ? " on" : "")}>
            <span class="dot" />
            {online ? "Бот онлайн" : "Оффлайн"}
          </div>
          <h2 class="hero-name">{ov.bot_name}</h2>
          <div class="hero-sub muted">
            {g.name ? `Сервер: ${g.name}` : "Сервер не подключён"} · аптайм {ov.uptime}
          </div>
        </div>
        <div class="hero-actions">
          <button class="btn" onClick={() => navigate("settings")}> Настройки</button>
          <button class="btn" onClick={() => navigate("backup")}>Бэкап</button>
          <button class="btn" onClick={() => navigate("logs")}>Логи</button>
          <button class="btn" onClick={() => navigate("audit")}>Аудит</button>
        </div>
      </div>

      <div class="stack">
        {live.length > 0 ? (
          live.map((s) => (
            <LiveCard
              key={s.label}
              stream={s}
              now={now}
              rsvpHint={
                s.rsvp_count > 0 ? `${s.rsvp_count} откликнулись` : "пока никто не откликнулся 🔔"
              }
            />
          ))
        ) : (
          <div class="card live-card offline">
            <div class="row-inline" style={{ gap: 10 }}>
              <span class="chip">○ не в эфире</span>
              <span class="muted small">
                {last
                  ? `Последний эфир: ${last.label} — ${fmtCount((last.session && last.session.viewers) || 0)} зрителей (пик ${fmtCount((last.session && last.session.peak) || 0)})`
                  : "Стримы не настроены — раздел «Стримы» в панели."}
              </span>
            </div>
          </div>
        )}
      </div>

      <div class="grid stats-grid">
        <Stat icon="activity" label="Задержка" value={loaded ? `${ov.latency_ms} мс` : "…"} sub="gateway ping" tone={ov.latency_ms > 300 ? "warn" : undefined} />
        <Stat icon="cpu" label="Память" value={loaded ? `${ov.mem_mb} МБ` : "…"} sub={`пик ${ov.mem_peak_mb} МБ`} />
        <Stat icon="users" label="Участники" value={loaded && g.members != null ? g.members : "…"} sub={g.online != null ? `${g.online} онлайн` : "—"} />
        <Stat icon="message" label="Каналы" value={loaded && g.channels != null ? g.channels : "…"} sub={g.roles != null ? `${g.roles} ролей` : "—"} />
        <Stat
          icon="monitor"
          label="Эфир"
          value={live.length ? `LIVE × ${live.length}` : "офлайн"}
          sub={live.length ? `${fmtCount(live.reduce((n, s) => n + ((s.session && s.session.viewers) || 0), 0))} зрителей суммарно` : "ничего не транслируется"}
          tone={live.length ? "ok" : undefined}
        />
      </div>

      <div class="grid two">
        <div class="card">
          <div class="card-head">
            <h3>Чат стрима</h3>
            <span class="muted small">twitch · kick · discord — живая лента, обновление 4 с</span>
          </div>
          <div class="list scroll-box">
            {chat.length === 0 && (
              <div class="muted small">Пока тишина — сообщения появятся здесь автоматически.</div>
            )}
            {chat.slice(0, 40).map((m, i) => {
              const pm = meta(m.platform);
              return (
                <div class="listline chatline" key={`${m.ts || ""}-${i}`}>
                  <span class="chat-plat" style={{ background: pm.color }} title={pm.label} />
                  <span class="grow">
                    <b style={{ color: pm.color }}>{m.name}</b>
                    {m.mod ? <span class="chat-mod">mod</span> : null}
                    <span class="chat-text">{m.text}</span>
                  </span>
                  <span class="muted small nowrap">{chatTime(m.ts)}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div class="card">
          <div class="card-head">
            <h3>Лента</h3>
            <span class="muted small">живые события · стримы, донаты, ошибки, аудит</span>
          </div>
          <div class="list scroll-box">
            {feed.length === 0 && (
              <div class="muted small">Событий пока нет — появятся здесь в реальном времени.</div>
            )}
            {feed.map((f) => (
              <div class="listline" key={f.key}>
                <span class={"chip " + (f.tone || "")}>
                  <Icon name={f.icon} size={13} /> {f.tag}
                </span>
                <span class="grow">
                  <div class="sub">{f.msg}</div>
                </span>
                <span class="muted small">{f.t}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div class="grid charts-grid">
        <div class="card chart-card">
          <div class="card-head">
            <h3>Задержка</h3>
            <span class="muted small">последние замеры</span>
          </div>
          <Sparkline points={mon.latency} label="latency" color="#5865f2" />
        </div>
        <div class="card chart-card">
          <div class="card-head">
            <h3>Память</h3>
            <span class="muted small">МБ</span>
          </div>
          <Sparkline points={mon.mem} label="mem" color="#1abc9c" />
        </div>
        <div class="card chart-card">
          <div class="card-head">
            <h3>Онлайн</h3>
            <span class="muted small">участники в сети</span>
          </div>
          <Sparkline points={mon.online} label="online" color="#23a55a" />
        </div>
      </div>

      {streams.length > 0 && (
        <div class="card">
          <div class="card-head">
            <h3>Стримы</h3>
            <span class="muted small">по данным последнего поллинга</span>
          </div>
          <div class="list">
            {streams.map((s) => (
              <div class="listline" key={s.label}>
                <span class={"chip " + (s.live ? "tone-ok" : "tone-bad")}>
                  {s.live ? "● LIVE" : "○ офлайн"}
                </span>
                <span class="grow">
                  <b>{s.label}</b>
                  <div class="sub">
                    {s.live && s.session
                      ? `${s.session.title || "Без названия"}${s.session.viewers != null ? ` · ${s.session.viewers}` : ""}${s.session.peak ? ` · пик ${s.session.peak}` : ""}${s.trend != null ? ` · ${s.trend >= 0 ? "▲ +" : "▼ "}${s.trend} за 10 мин` : ""}`
                      : `поллинг каждые ${s.poll_seconds} с`}
                  </div>
                </span>
                <span class="muted small nowrap">🔔 {s.rsvp_count || 0}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
