import { useEffect, useState } from "preact/hooks";
import { api, fmtCount } from "./lib/exports.js";
import { Icon } from "./components/icons.jsx";

const PLATFORM = {
  twitch: { label: "Twitch", color: "#9146ff" },
  kick: { label: "Kick", color: "#53fc18" },
  vk_video: { label: "VK Видео", color: "#0077ff" },
};

function fmtWhen(raw) {
  if (!raw) return "";
  const d = new Date(String(raw).replace(" ", "T"));
  if (isNaN(d.getTime())) return String(raw);
  return d.toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function ShowcasePage() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    api("/api/public/showcase").then((r) => {
      if (!alive) return;
      if (r.status === 200 && r.data && r.data.ok) setData(r.data);
      else setFailed(true);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (failed) {
    return (
      <div class="sc-page">
        <div class="sc-hero">
          <span class="sc-eyebrow">витрина</span>
          <h1>Не удалось загрузить</h1>
          <p>Сервер немного прилёг. Обнови страницу через минуту.</p>
          <div class="sc-cta">
            <span class="sc-eyebrow">попробуйте позже</span>
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div class="sc-page">
        <div class="sc-loading">
          <span class="sc-eyebrow">загрузка</span>
        </div>
      </div>
    );
  }

  const g = data.guild;
  const bot = data.bot || {};
  const settings = data.settings || {};
  const stats = data.stats || {};
  const streams = data.streams || [];
  const media = data.media || [];
  const schedule = data.schedule || [];
  const liveStreams = streams.filter((s) => s.live);
  const name = (g && g.name) || bot.name || "Сообщество";
  const title = settings.hero_title || "Наше сообщество";
  const byDay = stats.by_day || [];
  const maxDay = Math.max(1, ...byDay.map((d) => d.n || 0));

  const statItems = g
    ? [
        { value: g.members, label: "участников" },
        { value: g.online, label: "онлайн сейчас" },
        { value: bot.uptime_days || 0, label: "дней вместе" },
      ]
    : [];

  return (
    <div class="sc-page">
      <header class="sc-top">
        <div class="sc-brand">
          <img src="/icon.svg" alt="" width="26" height="26" />
          <b>{name}</b>
        </div>
      </header>

      <section class="sc-hero">
        <div class="sc-petals" aria-hidden="true">
          <i /><i /><i /><i /><i />
        </div>
        {liveStreams.length ? (
          <a class="sc-live" href={liveStreams[0].url} target="_blank" rel="noreferrer">
            <span class="sc-live-dot" /> В эфире · {PLATFORM[liveStreams[0].platform]?.label || liveStreams[0].platform}
          </a>
        ) : (
          <span class="sc-eyebrow">{title}</span>
        )}
        {bot.avatar ? (
          <img class="sc-avatar" src={bot.avatar} alt="" width="72" height="72" />
        ) : null}
        <h1>{name}</h1>
        {settings.about ? <p class="sc-about">{settings.about}</p> : <p class="sc-about">Стримы, события и живое сообщество. Заходи — здесь всегда что-то происходит.</p>}
        <div class="sc-cta">
          {settings.invite_url ? (
            <a class="sc-btn primary" href={settings.invite_url} target="_blank" rel="noreferrer">
              <Icon name="send" size={16} /> Вступить
            </a>
          ) : null}
          {liveStreams.length ? (
            <a class="sc-btn" href={liveStreams[0].url} target="_blank" rel="noreferrer">
              <Icon name="monitor" size={16} /> Смотреть эфир
            </a>
          ) : null}
          {media.length ? (
            <a class="sc-btn" href="#sc-media">
              <Icon name="film" size={16} /> Медиатека
            </a>
          ) : null}
        </div>
        {statItems.length ? (
          <div class="sc-stats">
            {statItems.map((s) => (
              <div class="sc-stat" key={s.label}>
                <b>{fmtCount(s.value)}</b>
                <span>{s.label}</span>
              </div>
            ))}
          </div>
        ) : null}
        {byDay.length > 1 ? (
          <div class="sc-spark" title="Активность по дням">
            {byDay.map((d, i) => (
              <i key={i} style={{ height: Math.max(6, Math.round(((d.n || 0) / maxDay) * 100)) + "%" }} />
            ))}
          </div>
        ) : null}
      </section>

      {streams.length ? (
        <section class="sc-section">
          <h2>Эфиры</h2>
          <div class="sc-streams">
            {streams.map((s) => {
              const p = PLATFORM[s.platform] || { label: s.platform, color: "var(--accent)" };
              return (
                <a class={"sc-stream" + (s.live ? " live" : "")} key={s.url} href={s.url} target="_blank" rel="noreferrer">
                  <span class="sc-stream-dot" style={{ background: p.color }} />
                  <span class="grow">
                    <b>{p.label}</b>
                    <small>{s.live ? "идёт эфир — заходи" : "не в эфире"}</small>
                  </span>
                  {s.live ? <span class="sc-badge-live">LIVE</span> : <Icon name="chevron-right" size={16} />}
                </a>
              );
            })}
          </div>
        </section>
      ) : null}

      {schedule.length ? (
        <section class="sc-section">
          <h2>Ближайшее расписание</h2>
          <div class="sc-schedule">
            {schedule.map((row, i) => (
              <div class="sc-event" key={i}>
                <Icon name="clock" size={16} />
                <span class="grow">
                  <b>{row.title || "Событие"}</b>
                </span>
                <time>{fmtWhen(row.send_at)}</time>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {media.length ? (
        <section class="sc-section" id="sc-media">
          <h2>Медиатека</h2>
          <div class="sc-media">
            {media.map((m) => (
              <a class="sc-media-card" key={m.id} href={m.url} target="_blank" rel="noreferrer" title={m.title}>
                <img src={m.url} alt={m.title} loading="lazy" />
                <span class="sc-media-title">{m.title}</span>
              </a>
            ))}
          </div>
        </section>
      ) : null}

      <footer class="sc-footer">
        <span>{name}</span>
      </footer>
    </div>
  );
}
