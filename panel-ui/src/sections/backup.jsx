import { useEffect, useState } from "preact/hooks";
import { api, downloadAuthed } from "../lib/exports.js";

const MODULE_LABELS = {
  welcome: "Приветствия",
  role_menu: "Роль по меню",
  birthdays: "Дни рождения",
  temp_voices: "Темп-голосовые",
  donations: "Донаты",
  overlay: "Overlay",
  logs: "Логи (исключения)",
  kick: "Kick",
  twitch: "Twitch",
  automod: "Автомод",
  ai_chat: "AI-чат",
  server_stats: "Статистика сервера",
  seasons: "Сезоны",
  rules_gate: "Правила",
  ram_report: "Отчёт об ОЗУ",
};

export default function BackupSection() {
  const [modules, setModules] = useState(null);
  const [engine, setEngine] = useState("");
  const [info, setInfo] = useState("");

  useEffect(() => {
    (async () => {
      const r = await api("/api/settings");
      if (r.data && r.data.ok) {
        setModules(r.data.modules || null);
        setEngine(r.data.db_engine || "");
      } else setModules(false);
    })();
  }, []);

  async function download(url, label) {
    setInfo(label);
    const ok = await downloadAuthed(url);
    setInfo(ok ? "Скачано." : "Ошибка.");
  }

  return (
    <div class="stack">
      <div class="card hl-card">
        <h3 class="sec">Бэкап и экспорт</h3>
        <p class="muted small" style={{ margin: "0 0 6px" }}>
          Скачайте настройки, конфигурацию и данные бота одним файлом JSON либо снапшот всей базы данных
          {engine ? ` (${engine})` : ""}.
        </p>
        <div class="row-actions" style={{ marginTop: 10 }}>
          <button class="btn primary" type="button" onClick={() => download("/api/backup", "Готовим бэкап…")}>Бэкап JSON</button>
          <button class="btn" type="button" onClick={() => download("/api/backup/db", "Готовим снапшот БД…")}>
            Снапшот БД{engine ? ` (${engine})` : ""}
          </button>
        </div>
        <div class="muted small" style={{ marginTop: 10 }}>{info}</div>
      </div>
      <div class="card">
        <h3 class="sec">Активные модули</h3>
        {modules === null && <div class="muted small">Загрузка…</div>}
        {modules === false && <div class="muted small">Не удалось загрузить модули — откройте «Настройки».</div>}
        {modules && !Object.keys(modules).length && <div class="muted small">Модули не найдены в .env</div>}
        {modules && !!Object.keys(modules).length && (
          <div class="grid cols">
            {Object.entries(modules).map(([k, mod]) => (
              <div class="module-card" key={k}>
                <h5>
                  {MODULE_LABELS[k] || k}
                  <span class="mod-env">.env</span>
                </h5>
                <div class="kv">
                  Включён: <b>{mod && mod.enabled !== undefined ? (mod.enabled ? "да" : "нет") : "—"}</b>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
