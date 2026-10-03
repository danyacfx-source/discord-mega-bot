import { useEffect, useRef, useState } from "preact/hooks";
import { api } from "../lib/exports.js";

const AUDIT_CATS = { bot: "Бот", member: "Участники", message: "Сообщения", voice: "Голосовые", mod: "Модерация", general: "Общее" };

export default function AuditSection() {
  const [logs, setLogs] = useState([]);
  const [count, setCount] = useState(0);
  const [ok, setOk] = useState(true);
  const [cat, setCat] = useState("");
  const [auto, setAuto] = useState(true);
  const [updated, setUpdated] = useState("");
  const boxRef = useRef(null);
  const autoRef = useRef(auto);
  autoRef.current = auto;

  async function load() {
    const r = await api("/api/logs?n=500&audit=1");
    if (!r.data.ok) return setOk(false);
    setOk(true);
    setLogs(r.data.logs || []);
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

  const filtered = cat ? logs.filter((l) => l.cat === cat) : logs;

  useEffect(() => {
    if (boxRef.current && filtered.length) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [logs, cat]);

  return (
    <div class="card">
      <div class="row-inline" style={{ justifyContent: "space-between" }}>
        <h3 class="sec" style={{ margin: 0 }}>Логи Discord</h3>
        <div class="row-inline" style={{ margin: 0 }}>
          <select class="input mini-select" value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">Все категории</option>
            {Object.entries(AUDIT_CATS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
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
        {ok && !filtered.length && <div class="muted small">Событий нет</div>}
        {ok &&
          filtered.slice(-300).map((l, i) => (
            <div class="log-line" key={i}>
              <span class="log-t">{l.t || ""}</span>
              <span class="log-cat">{AUDIT_CATS[l.cat] || l.cat || ""}</span>
              <span class="log-msg">{l.msg}</span>
            </div>
          ))}
      </div>
      <div class="muted small" style={{ marginTop: 8 }}>
        {ok ? `Показано ${filtered.length} из ${count}${updated ? " · обновлено " + updated : ""}` : ""}
      </div>
    </div>
  );
}
