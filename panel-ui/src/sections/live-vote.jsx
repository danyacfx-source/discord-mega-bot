import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";

function pluralVotes(n) {
  return n + " " + (n % 10 === 1 && n % 100 !== 11 ? "голос" :
    n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? "голоса" : "голосов");
}

export default function LiveVotePanel({ meta }) {
  const [poll, setPoll] = useState(null);
  const [question, setQuestion] = useState("Что делаем дальше?");
  const [options, setOptions] = useState("Продолжаем игру\nМеняем игру\nЧат выбирает наказание");
  const [duration, setDuration] = useState(120);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let alive = true;
    async function refresh() {
      const r = await api("/api/live-vote");
      if (alive && r.status === 200 && r.data.ok) setPoll(r.data.poll);
    }
    refresh();
    const interval = setInterval(refresh, 3000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { alive = false; clearInterval(interval); clearInterval(clock); };
  }, []);

  async function doAction(action) {
    setBusy(true);
    const data = { action };
    if (action === "start") {
      data.question = question;
      data.options = options.split("\n").map((v) => v.trim()).filter(Boolean);
      data.seconds = Number(duration);
    }
    const r = await api("/api/live-vote", data);
    setBusy(false);
    if (r.status === 200 && r.data.ok) {
      setPoll(r.data.poll);
      toast(action === "start" ? "Голосование запущено — зрители выбирают!" :
        action === "finish" ? "Голосование завершено" : "Голосование убрано из OBS", true);
    } else toast(errToast(r), false);
  }

  async function copySource() {
    const host = meta.url_base || location.origin;
    const link = host + "/overlay/vote?token=" + encodeURIComponent(meta.token);
    try {
      await navigator.clipboard.writeText(link);
      toast("Ссылка голосования скопирована для OBS", true);
    } catch (_) {
      prompt("Ссылка голосования для OBS:", link);
    }
  }

  const active = poll?.status === "active";
  const total = poll?.total || 0;
  const secondsLeft = active ? Math.max(0, Math.ceil(poll.ends_at - now / 1000)) : 0;
  const canEdit = !meta.token_redacted;

  return (
    <div class="card">
      <h3 class="sec">📡 Зрители решают · Twitch + Kick</h3>
      <p class="muted small">Общее голосование двух чатов. Зрители пишут <b>!vote 1</b>, <b>!vote 2</b> или <b>!голос 1</b>. Один голос на аккаунт в каждой платформе, можно поменять выбор. Бот читает сообщения, не отправляя ничего в Twitch или Kick.</p>
      {poll ? (
        <div class="stack" style={{ padding: 14, borderRadius: 12, background: "#10201b", border: "1px solid #416c51" }}>
          <div class="row-inline" style={{ justifyContent: "space-between" }}>
            <span class="chip">{active ? "🟢 ГОЛОСОВАНИЕ ИДЁТ" : "🏁 РЕЗУЛЬТАТЫ"}</span>
            <b>{active ? secondsLeft + " с" : "Завершено"}</b>
          </div>
          <b style={{ fontSize: 18 }}>{poll.question}</b>
          {poll.options.map((option, i) => {
            const n = poll.counts[i] || 0;
            const pct = total ? Math.round(100 * n / total) : 0;
            const winning = !active && poll.leaders.includes(i + 1);
            return (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 58px", gap: 8 }}>
                <div style={{ minWidth: 0 }}>
                  <div class="row-inline" style={{ marginBottom: 5 }}>
                    <span style={{ color: winning ? "#ffe795" : "#d5e5db", overflowWrap: "anywhere" }}>{i + 1}. {option}</span>
                    <span class="muted small">({n})</span>
                  </div>
                  <div style={{ height: 9, background: "#314c3d", borderRadius: 99, overflow: "hidden" }}>
                    <div style={{ height: "100%", borderRadius: 99, width: pct + "%", background: winning ? "#f5cc70" : "#72d7a3", transition: "width .4s ease" }} />
                  </div>
                </div>
                <b style={{ textAlign: "right", alignSelf: "end" }}>{pct}%</b>
              </div>
            );
          })}
          <span class="muted small">{pluralVotes(total)} · Варианты на экране обновляются автоматически.</span>
        </div>
      ) : null}
      {!active && (
        <div class="stack">
          <label class="ovl-field">Вопрос
            <input class="input" value={question} maxLength={140} onInput={(e) => setQuestion(e.target.value)} />
          </label>
          <label class="ovl-field">Варианты — каждый с новой строки (от 2 до 5)
            <textarea class="input" rows="4" value={options} onInput={(e) => setOptions(e.target.value)} />
          </label>
          <label class="ovl-field">Длительность
            <select class="input" value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
              <option value={60}>1 минута</option>
              <option value={120}>2 минуты</option>
              <option value={300}>5 минут</option>
              <option value={600}>10 минут</option>
              <option value={900}>15 минут</option>
            </select>
          </label>
        </div>
      )}
      <div class="row-inline" style={{ flexWrap: "wrap", gap: 9 }}>
        {!active ? (
          <button class="btn success" disabled={!canEdit || busy} type="button" onClick={() => doAction("start")}>🔥 Запустить голосование</button>
        ) : (
          <button class="btn" disabled={!canEdit || busy} type="button" onClick={() => doAction("finish")}>🏁 Завершить досрочно</button>
        )}
        <button class="btn" disabled={!canEdit || !meta.enabled || !meta.token || busy} type="button" onClick={copySource}>📋 Ссылка голосования для OBS</button>
        {poll && !active && <button class="btn danger" disabled={!canEdit || busy} type="button" onClick={() => doAction("clear")}>Убрать с экрана</button>}
      </div>
      <p class="muted small">Голосование и результаты сохраняются в базе и переживают редеплой. Существующая ссылка чата не меняется; для голосования нужен отдельный Browser Source в OBS.</p>
    </div>
  );
}
