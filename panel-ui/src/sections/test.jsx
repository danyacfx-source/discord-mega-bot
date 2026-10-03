import { useEffect, useState } from "preact/hooks";
import { api, toast } from "../lib/exports.js";
import { Icon } from "../components/icons.jsx";

export default function TestSection() {
  const [channels, setChannels] = useState([]);
  const [channelId, setChannelId] = useState("");
  const [content, setContent] = useState("");
  const [result, setResult] = useState("Сообщение отправляется от имени бота в выбранный канал.");

  async function loadChannels() {
    const r = await api("/api/bot/channels");
    const list = (r.data && r.data.channels) || [];
    setChannels(list);
    if (list.length && !channelId) setChannelId(list[0].id);
  }

  useEffect(() => {
    loadChannels();
  }, []);

  async function sendTest() {
    if (!channelId) return toast("Выберите канал", false);
    if (!content.trim()) return toast("Введите текст", false);
    const r = await api("/api/bot/send", { channel_id: channelId, content: content.slice(0, 2000), embeds: [] });
    setResult(r.status === 200 && r.data.ok ? "Отправлено" : (r.data.error || "Ошибка"));
  }

  return (
    <div class="card">
      <h3 class="sec">Тестовая отправка</h3>
      <label class="field">
        <span class="field-label">Канал</span>
        <div class="row-inline">
          <select class="input" style={{ flex: 1 }} value={channelId} onChange={(e) => setChannelId(e.target.value)}>
            {!channels.length && <option value="">Нет каналов</option>}
            {channels.map((c) => (
              <option key={c.id} value={c.id}>{c.name || c.id}</option>
            ))}
          </select>
          <button class="btn mini" type="button" onClick={loadChannels} title="Обновить"><Icon name="refresh" size={14} /></button>
        </div>
      </label>
      <label class="field">
        <span class="field-label">Сообщение</span>
        <textarea class="input" rows="4" placeholder="Текст тестового сообщения…" value={content} onInput={(e) => setContent(e.target.value)} />
      </label>
      <button class="btn primary" type="button" onClick={sendTest}>Отправить тест</button>
      <div class="muted small" style={{ marginTop: 10 }}>{result}</div>
    </div>
  );
}
