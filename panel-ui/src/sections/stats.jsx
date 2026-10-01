import { useEffect, useRef, useState } from "preact/hooks";
import { api, token } from "../lib/exports.js";

function shortLbl(item, i) {
  if (item.t != null) {
    const d = new Date(item.t * 1000);
    return String(d.getHours()).padStart(2, "0") + ":00";
  }
  if (item.d != null) return String(item.d).slice(5);
  return String(i);
}

function Bars({ items, height }) {
  const ref = useRef(null);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const W = c.width;
    const H = height || c.height;
    const ctx = c.getContext("2d");
    const pad = { l: 30, r: 8, t: 12, b: 22 };
    ctx.clearRect(0, 0, W, H);
    if (!items || !items.length) return;
    const n = items.length;
    const cw = (W - pad.l - pad.r) / n;
    const maxV = Math.max(...items.map((i) => i.n || 0), 1);
    ctx.font = "10px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.fillStyle = "#8a8f98";
    for (let g = 0; g <= 4; g++) {
      const v = Math.round((maxV * g) / 4);
      const y = pad.t + (H - pad.t - pad.b) - ((H - pad.t - pad.b) * g) / 4;
      ctx.strokeStyle = "#ffffff14";
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(W - pad.r, y);
      ctx.stroke();
      ctx.fillText(String(v), pad.l - 6, y + 3);
    }
    for (let i = 0; i < n; i++) {
      const hue = `hsla(${210 + (i / (n || 1)) * 90}, 78%, ${52 + 8 * Math.sin(i * 0.6)}%, 0.9)`;
      const h = ((items[i].n || 0) / maxV) * (H - pad.t - pad.b);
      const x = pad.l + i * cw + cw * 0.18;
      const w = cw * 0.64;
      const y = H - pad.b - h;
      ctx.fillStyle = hue;
      ctx.fillRect(x, y, w, h);
      if (cw > 22 && (i % 4 === 0 || i === n - 1)) {
        ctx.textAlign = "center";
        ctx.fillStyle = "#8a8f98";
        ctx.fillText(shortLbl(items[i], i), x + w / 2, H - 8);
      }
    }
  }, [items, height]);

  return <canvas ref={ref} width="760" height={height || 220} class="chart-canvas" />;
}

export default function StatsSection() {
  const [today, setToday] = useState("–");
  const [week, setWeek] = useState("–");
  const [total, setTotal] = useState("–");
  const [rate, setRate] = useState("–");
  const [hours, setHours] = useState([]);
  const [days, setDays] = useState([]);

  useEffect(() => {
    let socket = null;
    let reconnectTimer = null;
    let closed = false;

    function applyPersistent(payload) {
      const rows = (payload && payload.rows) || [];
      if (!rows.length) return;
      const hourly = rows
        .slice()
        .reverse()
        .map((row) => ({ t: new Date(row.bucket).getTime() / 1000, n: Number(row.messages || 0) }));
      if (!hourly.length) return;
      const todayStr = new Date().toISOString().slice(0, 10);
      const todayRows = hourly.filter((row) => new Date(row.t * 1000).toISOString().slice(0, 10) === todayStr);
      setToday(String(todayRows.reduce((s, row) => s + row.n, 0)));
      setTotal(String(hourly.reduce((s, row) => s + row.n, 0)));
      setHours(hourly.slice(-24));
    }

    function connect() {
      if (closed || socket || !window.WebSocket || !token()) return;
      const scheme = location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${scheme}//${location.host}/ws/analytics`);
      socket.onopen = () => socket.send(JSON.stringify({ token: token() }));
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === "analytics") applyPersistent(message.data);
        } catch (_) {}
      };
      socket.onclose = () => {
        socket = null;
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connect, 10000);
      };
    }

    (async () => {
      const r = await api("/api/stats");
      if (!r.data || !r.data.ok) return;
      const byHour = r.data.by_hour || [];
      const byDay = r.data.by_day || [];
      const hourN = byHour.reduce((s, i) => s + (i.n || 0), 0);
      setToday(byDay.length ? byDay[byDay.length - 1].n : 0);
      setWeek(byHour.slice(-24 * 7).reduce((s, i) => s + (i.n || 0), 0));
      setTotal(r.data.total ?? hourN);
      const now = Date.now();
      setRate(
        byHour.length === 0
          ? "нет данных"
          : Math.round(((byHour[byHour.length - 1].n || 0) / Math.max(now - byHour[byHour.length - 1].t * 1000, 1000)) * 3600000),
      );
      setHours(byHour.slice(-24));
      setDays(byDay.slice(-14));
      connect();
    })();

    return () => {
      closed = true;
      clearTimeout(reconnectTimer);
      if (socket) socket.close();
    };
  }, []);

  return (
    <div class="card">
      <h3 class="sec">📊 Статистика активности</h3>
      <p class="muted small" style={{ margin: "0 0 12px" }}>
        Реальные сообщения сервера: по часам (первые 7 дней) и по дням (первый 45 при полном деплое). Внизу — тренд латентности.
      </p>
      <div class="stats-grid">
        <div class="card mini"><div class="muted small">За сутки</div><div class="stat-big">{today}</div></div>
        <div class="card mini"><div class="muted small">За неделю</div><div class="stat-big">{week}</div></div>
        <div class="card mini"><div class="muted small">Всего</div><div class="stat-big">{total}</div></div>
        <div class="card mini"><div class="muted small">Скорость</div><div class="stat-big">{rate}</div></div>
      </div>
      <Bars items={hours} height={220} />
      <Bars items={days} height={180} />
    </div>
  );
}
