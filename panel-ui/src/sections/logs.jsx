import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../lib/exports.js";

export default function LogsSection() {
  const [logs, setLogs] = useState([]);
  const [count, setCount] = useState(0);
  const [ok, setOk] = useState(true);
  const [level, setLevel] = useState("");
  const [auto, setAuto] = useState(false);
  const [updated, setUpdated] = useState("");
  const boxRef = useRef(null);
  const autoRef = useRef(auto);
  autoRef.current = auto;

  async function load() {
    const r = await api("/api/logs?n=500");
    if (!r.data.ok) return setOk(false);
    setOk(true);
    setLogs((r.data.logs || []));
    setCount(r.data.count || 0);
    setUpdated(new Date().toLocaleTimeString("ru-RU"));
  }

  useEffect(() => {
    load();
    const timer = setInterval(() => {
      if (document.hidden || !autoRef.current) return;
      load();
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (boxRef.current && filtered.length) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [logs, level]);

  const filtered = level ? logs.filter((l) => l.level === level) : logs;

  return (
    <div class="card">
      <div class="row-inline" style={{ justifyContent: "space-between" }}>
        <h3 class="sec" style={{ margin: 0 }}>Логи бота</h3>
        <div class="row-inline" style={{ margin: 0 }}>
          <select class="input mini-select" value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">Все уровни</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
          <label class="toggle-holder" style={{ margin: 0, fontSize: "13px" }}>
            <span class="switch">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              <span class="slider" />
            </span>
            <span>Авто</span>
          </label>
          <button class="btn mini" type="button" onClick={load}>Обновить</button>
        </div>
      </div>

      <div class="log-box" ref={boxRef}>
        {!ok && <div class="muted small">Логи недоступны</div>}
        {ok && !filtered.length && <div class="muted small">Записей нет</div>}
        {ok &&
          filtered.slice(-300).map((l, i) => (
            <div class="log-line" key={i}>
              <span class="log-t">{l.t || ""}</span>
              <span class={"log-lvl " + (l.level === "ERROR" ? "err" : l.level === "WARNING" ? "warn" : "info")}>{l.level || ""}</span>
              <span class="log-msg">{(l.name ? "[" + l.name + "] " : "") + l.msg}</span>
            </div>
          ))}
      </div>
      <div class="muted small" style={{ marginTop: 8 }}>
        {ok ? `Показано ${filtered.length} из ${count}${updated ? " · обновлено " + updated : ""}` : ""}
      </div>
    </div>
  );
}
