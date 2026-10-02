import { useEffect, useState } from "preact/hooks";
import { api } from "../api.js";
import { navigate } from "../store.js";
import { subscribeEvents } from "../lib/events.js";
import { Sparkline, Stat } from "../components/widgets.jsx";

const EMPTY = {
  bot_online: false,
  bot_name: "…",
  uptime: "—",
  uptime_seconds: 0,
  latency_ms: 0,
  mem_mb: 0,
  mem_peak_mb: 0,
};

function feedLine(ev) {
  const d = ev.data || {};
  const t = String(ev.ts || "").slice(11, 19);
  if (ev.type === "stream") {
    const live = d.status === "live";
    const label = d.platform === "kick" ? "Kick" : "Twitch";
    return {
      key: ev.seq,
      icon: "📺",
      tag: `${label}${live ? " ● LIVE" : " ○ офлайн"}`,
      tone: live ? "tone-ok" : "tone-bad",
      msg: live
        ? `${d.title || "Без названия"}${d.viewers ? ` · 👁 ${d.viewers}` : ""}`
        : d.url || "",
      t,
    };
  }
  if (ev.type === "donation") {
    return {
      key: ev.seq,
      icon: "💰",
      tag: "Донат",
      tone: "tone-ok",
      msg: `${d.username} — ${d.amount} ${d.currency}${d.message ? ` · ${String(d.message).slice(0, 120)}` : ""}`,
      t,
    };
  }
  if (ev.type === "error") {
    return { key: ev.seq, icon: "⛔", tag: "Ошибка", tone: "tone-bad", msg: d.msg || "", t };
  }
  const audit = Boolean(d.cat && d.cat !== "sys");
  return {
    key: ev.seq,
    icon: audit ? "🛰️" : "⚠️",
    tag: audit ? `Аудит · ${d.cat}` : d.level || "WARNING",
    tone: audit ? "" : "warn",
    msg: d.msg || "",
    t,
  };
}

export default function Overview() {
  const [ov, setOv] = useState(EMPTY);
  const [mon, setMon] = useState({ latency: [], mem: [], online: [] });
  const [streams, setStreams] = useState([]);
  const [feed, setFeed] = useState([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    async function tick() {
      const [a, b, c] = await Promise.all([api("/api/overview"), api("/api/monitor"), api("/api/streams")]);
      if (!alive) return;
      if (a.status === 200) setOv({ ...EMPTY, ...a.data });
      if (b.status === 200) setMon({ latency: b.data.latency || [], mem: b.data.mem || [], online: b.data.online || [] });
      if (c.status === 200) setStreams(c.data.streams || []);
      setLoaded(true);
    }
    tick();
    const t = setInterval(tick, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  useEffect(
    () =>
      subscribeEvents((ev) => {
        setFeed((prev) => [feedLine(ev), ...prev].slice(0, 40));
      }),
    [],
  );

  const g = ov.guild || {};
  const online = ov.bot_online;

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
          <button class="btn" onClick={() => navigate("settings")}>⚙️ Настройки</button>
          <button class="btn" onClick={() => navigate("backup")}>💾 Бэкап</button>
          <button class="btn" onClick={() => navigate("logs")}>📄 Логи</button>
          <button class="btn" onClick={() => navigate("audit")}>👁 Аудит</button>
        </div>
      </div>

      <div class="grid stats-grid">
        <Stat icon="⚡" label="Задержка" value={loaded ? `${ov.latency_ms} мс` : "…"} sub="gateway ping" tone={ov.latency_ms > 300 ? "warn" : undefined} />
        <Stat icon="🧠" label="Память" value={loaded ? `${ov.mem_mb} МБ` : "…"} sub={`пик ${ov.mem_peak_mb} МБ`} />
        <Stat icon="👥" label="Участники" value={loaded && g.members != null ? g.members : "…"} sub={g.online != null ? `${g.online} онлайн` : "—"} />
        <Stat icon="💬" label="Каналы" value={loaded && g.channels != null ? g.channels : "…"} sub={g.roles != null ? `${g.roles} ролей` : "—"} />
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
      <div class="card">
        <div class="card-head">
          <h3>📡 Лента</h3>
          <span class="muted small">живые события · стримы, донаты, ошибки, аудит</span>
        </div>
        <div class="list">
          {feed.length === 0 && (
            <div class="muted small">Событий пока нет — появятся здесь в реальном времени.</div>
          )}
          {feed.map((f) => (
            <div class="listline" key={f.key}>
              <span class={"chip " + (f.tone || "")}>
                {f.icon} {f.tag}
              </span>
              <span class="grow">
                <div class="sub">{f.msg}</div>
              </span>
              <span class="muted small">{f.t}</span>
            </div>
          ))}
        </div>
      </div>
      {streams.length > 0 && (
        <div class="card">
          <div class="card-head">
            <h3>📺 Стримы</h3>
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
                      ? `${s.session.title || "Без названия"}${s.session.viewers != null ? ` · 👁 ${s.session.viewers}` : ""}${s.session.peak ? ` · пик ${s.session.peak}` : ""}${s.trend != null ? ` · ${s.trend >= 0 ? "▲ +" : "▼ "}${s.trend} за 10 мин` : ""}`
                      : `поллинг каждые ${s.poll_seconds} с`}
                  </div>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
