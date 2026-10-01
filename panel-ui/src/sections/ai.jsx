import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";
import { Loading } from "../components/ui.jsx";

export default function AIChat() {
  const [data, setData] = useState(null);

  async function load() {
    const r = await api("/api/ai");
    if (r.status !== 200) {
      if (r.data.error) toast("❌ " + r.data.error, false);
      return;
    }
    setData(r.data);
  }

  useEffect(() => {
    load();
  }, []);

  async function togglePause() {
    const r = await api("/api/ai", { paused: !data.paused });
    if (r.status === 200 && r.data.ok) {
      toast(data.paused ? "▶ AI-чат снят с паузы" : "⏸ AI-чат на паузе", true);
      load();
    } else toast(errToast(r), false);
  }

  if (!data) return <Loading />;

  const chans = (data.channels || []).map((c) => c.name || c.id).join(", ") || "—";

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">🤖 AI-чат (Gemini)</h3>
        <div class="row-inline">
          <button class="btn primary" type="button" onClick={togglePause}>
            {data.paused ? "▶ Снять паузу" : "⏸ Пауза"}
          </button>
          <span class="muted small">
            {data.paused ? (
              <>
                ⏸ <b>пауза</b> — ответы временно приостановлены
              </>
            ) : data.enabled ? (
              <>
                🟢 <b>активен</b>
              </>
            ) : (
              <>
                ⚫ <b>выключен</b> — включите AI_ENABLED + GEMINI_API_KEY + AI_CHANNELS в .env
              </>
            )}
          </span>
        </div>
        <p class="muted small" style={{ margin: "10px 0 0" }}>
          Все параметры (модель, каналы, промпт, температура) задаются в <code>.env</code> (AI_*,
          GEMINI_API_KEY) и применяются после рестарта. Кнопка паузы действует сразу — до следующего
          рестарта.
        </p>
      </div>

      <div class="card">
        <h3 class="sec">Конфигурация</h3>
        <div class="env-box muted small">
          <div>Модель: <b>{data.model}</b></div>
          <div>Каналы: <b>{chans}</b></div>
          <div>
            Температура: <b>{data.temperature}</b> · макс. токенов: <b>{data.max_tokens}</b> · история:{" "}
            <b>{data.history_size}</b>
          </div>
          <div>
            Кулдаун: <b>{data.cooldown_seconds}с</b> · таймаут: <b>{data.timeout_seconds}с</b>
          </div>
          <div>
            Ключ: <b>{data.has_key ? "задан" : "не задан"}</b> · прокси: <b>{data.proxy ? "задан" : "нет"}</b>
          </div>
          {data.system_prompt ? (
            <div>Промпт (начало):<br />{data.system_prompt.slice(0, 240)}</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
