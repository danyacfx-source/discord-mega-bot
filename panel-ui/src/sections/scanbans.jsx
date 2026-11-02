import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";
import { Chip, Empty, Loading } from "../components/ui.jsx";

function fmtUntil(seconds) {
  return new Date(seconds * 1000).toLocaleString("ru-RU");
}

export default function ScanBansSection() {
  const [items, setItems] = useState(null);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState("");

  async function load() {
    const r = await api("/api/scan-bans");
    if (r.status === 200 && r.data.ok) {
      setItems(r.data.items || []);
      setTotal(r.data.total || 0);
    } else {
      setItems([]);
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(() => {
      if (!document.hidden) load();
    }, 10000);
    return () => clearInterval(timer);
  }, []);

  async function unban(ip) {
    if (!confirm(`Снять бан с ${ip}? Счётчик нарушений сохранится, эскалация продолжится.`)) return;
    setBusy(ip);
    const r = await api("/api/scan-bans/clear", { ip });
    setBusy("");
    if (r.status === 200 && r.data.ok) {
      toast("Бан снят: " + ip, true);
      load();
    } else {
      toast(errToast(r), false);
    }
  }

  const active = (items || []).filter((item) => item.banned);

  return (
    <div class="card">
      <div class="row-inline" style={{ justifyContent: "space-between" }}>
        <h3 class="sec" style={{ margin: 0 }}>Защита от сканеров</h3>
        <button class="btn mini" type="button" onClick={load}>Обновить</button>
      </div>
      <p class="muted" style={{ fontSize: "13px" }}>
        Активных банов: {active.length}. Всего нарушителей: {total}. Попытки во время бана тоже учитываются.
      </p>
      {items == null && <Loading />}
      {items != null && !items.length && <Empty>Нарушителей сканирования нет</Empty>}
      {items != null &&
        items.map((item) => (
          <div class="row-inline" key={item.ip} style={{ justifyContent: "space-between", padding: "6px 0" }}>
            <div class="row-inline" style={{ margin: 0 }}>
              <code>{item.ip}</code>
              <Chip tone={item.banned ? "bad" : "ok"}>
                {item.permanent ? "Постоянный бан" : item.banned ? "Бан до " + fmtUntil(item.until) : "Бана нет"}
              </Chip>
              <span class="muted" style={{ fontSize: "13px" }}>Нарушений: {item.offenses}</span>
            </div>
            {item.banned && (
              <button
                class="btn mini danger"
                type="button"
                disabled={busy === item.ip}
                onClick={() => unban(item.ip)}
              >
                Снять бан
              </button>
            )}
          </div>
        ))}
    </div>
  );
}
