import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast } from "../lib/exports.js";
import { Field, Loading, Toggle } from "../components/ui.jsx";

export default function Automod() {
  const [data, setData] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [words, setWords] = useState("");

  async function load() {
    const r = await api("/api/automod");
    if (r.status !== 200) {
      if (r.data.error) toast(r.data.error, false);
      return;
    }
    setData(r.data);
    setEnabled(!!r.data.db_enabled);
    setWords((r.data.blocked_words || []).join("\n"));
  }

  useEffect(() => {
    load();
  }, []);

  async function save() {
    const r = await api("/api/automod", {
      enabled,
      words: words.split("\n").map((w) => w.trim()).filter(Boolean),
    });
    if (r.status === 200 && r.data.ok) {
      toast("Автомод сохранён", true);
      load();
    } else toast(errToast(r), false);
  }

  async function lockdown() {
    if (!confirm("Закрыть отправку сообщений для @everyone на время lockdown?")) return;
    const r = await api("/api/automod/lockdown", { seconds: 300 });
    if (r.status === 200 && r.data.ok) toast("Lockdown включён для " + r.data.channels + " каналов", true);
    else toast(errToast(r, "Не удалось включить lockdown"), false);
  }

  if (!data) return <Loading />;

  const cfg = data.env || {};
  const ignored = (cfg.ignored_channels || []).map((c) => c.name || c.id).join(", ") || "—";

  return (
    <div class="card">
      <h3 class="sec">Автомод</h3>
      <p class="muted small" style={{ margin: "0 0 12px" }}>
        Фильтр спама, стоп-слов, ссылок, капса и растяжек. Сохранённые здесь стоп-слова применяются сразу; пороги,
        игнор-роли и каналы — в <code>.env</code> (снизу, только чтение).
      </p>

      <div class="row-inline">
        <Toggle checked={enabled} onChange={setEnabled} label="Фильтр автомода включён (БД)" />
        <span class="muted small">{data.enabled ? "— активен" : "— выключен"}</span>
      </div>

      <div class="two" style={{ marginTop: "12px" }}>
        <div class="stack">
          <Field label="Стоп-слова (по одному на строку)">
            <textarea class="input" rows="6" placeholder={"слово1\nслово2"} value={words} onInput={(e) => setWords(e.target.value)} />
          </Field>
          <div class="row-inline">
            <button class="btn primary" type="button" onClick={save}>Сохранить</button>
            <button class="btn danger" type="button" onClick={lockdown}>Lockdown</button>
          </div>
          <span class="muted small">Совпадают с настройками в Discord (/setup), включая регистр.</span>
        </div>

        <div>
          <Field label="Параметры из .env (AUTOMOD_*) — только чтение">
            <div class="env-box muted small">
              <div>Стоп-слова (.env): <b>{cfg.banned_words || "—"}</b></div>
              <div>Блок ссылок: <b>{cfg.block_links ? "вкл" : "выкл"}</b></div>
              <div>Капс: порог <b>{cfg.caps_threshold}</b>, мин. длина <b>{cfg.caps_min_len}</b></div>
              <div>Сообщений в окне: <b>{cfg.max_messages}</b> · таймаут: <b>{cfg.timeout_seconds}с</b></div>
              <div>Бан после <b>{cfg.ban_after}</b> нарушений за <b>{cfg.ban_window}с</b></div>
              <div>Игнор-роли: <b>{(cfg.ignore_roles || []).join(", ") || "—"}</b></div>
              <div>Игнор-каналы: <b>{ignored}</b></div>
              <div>
                Anti-raid: <b>{cfg.anti_raid && cfg.anti_raid.enabled ? "вкл" : "выкл"}</b> · порог входов:{" "}
                <b>{cfg.anti_raid ? cfg.anti_raid.join_threshold : "—"}</b>
              </div>
              <div>Regex-исключения: <b>{cfg.exempt_regex || "—"}</b></div>
            </div>
          </Field>
        </div>
      </div>
    </div>
  );
}
