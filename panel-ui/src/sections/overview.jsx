import { useEffect, useState } from "preact/hooks";
import { api } from "../api.js";
import { navigate } from "../store.js";
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

export default function Overview() {
  const [ov, setOv] = useState(EMPTY);
  const [mon, setMon] = useState({ latency: [], mem: [], online: [] });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    async function tick() {
      const [a, b] = await Promise.all([api("/api/overview"), api("/api/monitor")]);
      if (!alive) return;
      if (a.status === 200) setOv({ ...EMPTY, ...a.data });
      if (b.status === 200) setMon({ latency: b.data.latency || [], mem: b.data.mem || [], online: b.data.online || [] });
      setLoaded(true);
    }
    tick();
    const t = setInterval(tick, 10000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

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
    </div>
  );
}
