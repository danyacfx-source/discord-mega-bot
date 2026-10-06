import { Icon } from "./icons.jsx";

export function Sparkline({ points = [], height = 56, color = "var(--accent)", label = "" }) {
  const values = points.map((p) => (typeof p === "number" ? p : p.v)).filter((v) => Number.isFinite(v));
  if (values.length < 2) {
    return <div class="spark-empty muted small">{label ? label + ": " : ""}недостаточно данных</div>;
  }
  const w = 300;
  const h = height;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i) => (i / (values.length - 1)) * w;
  const y = (v) => h - 6 - ((v - min) / span) * (h - 14);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${w},${h} L0,${h} Z`;
  const last = { cx: x(values.length - 1), cy: y(values[values.length - 1]) };
  const gid = "sg" + Math.abs(hash(label + color));
  return (
    <svg class="spark" style={{ height: `${h}px` }} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color={color} stop-opacity="0.35" />
          <stop offset="100%" stop-color={color} stop-opacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={color} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
      <circle cx={last.cx} cy={last.cy} r="3" fill={color} />
    </svg>
  );
}

function hash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}

export function Stat({ icon, label, value, sub, tone }) {
  return (
    <div class={"stat-card" + (tone ? " tone-" + tone : "")}>
      <div class="stat-ic">{typeof icon === "string" ? <Icon name={icon} size={18} /> : icon}</div>
      <div class="stat-body">
        <div class="stat-label">{label}</div>
        <div class="stat-value">{value}</div>
        {sub ? <div class="stat-sub">{sub}</div> : null}
      </div>
    </div>
  );
}
