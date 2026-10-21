import { useEffect, useState } from "preact/hooks";
import { api, fmtCount } from "./lib/exports.js";
import { Icon } from "./components/icons.jsx";

const CURRENCY_SYMBOLS = { RUB: "₽", USD: "$", EUR: "€", UAH: "₴", KZT: "₸" };

function fmtDonation(total, currency) {
  const amount = Number(total) || 0;
  const text = Number.isInteger(amount) ? String(amount) : amount.toFixed(1);
  const symbol = CURRENCY_SYMBOLS[String(currency || "").toUpperCase()] || currency || "";
  return symbol ? `${text} ${symbol}` : text;
}

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

  useEffect(() => {
    if (data) {
      const g = data.guild;
      document.title = "DENDICH / Radio Silence — " + ((g && g.name) || "сообщество");
    } else if (failed) {
      document.title = "DENDICH — нет соединения";
    } else {
      document.title = "DENDICH — загрузка";
    }
  }, [data, failed]);

  if (failed || !data) {
    return (
      <div class="sc-page">
        <header class="sc-top sc-masthead">
          <a class="sc-wordmark" href="/showcase" aria-label="DENDICH — главная">
            <img src="/icon.svg" alt="" width="44" height="44" />
            <span><b>DENDICH</b><small>RADIO SILENCE</small></span>
          </a>
        </header>
        <div class="sc-state">
          <img src="/icon.svg" alt="" width="72" height="72" />
          <span class="sc-eyebrow">{failed ? "КАНАЛ НЕДОСТУПЕН" : "УСТАНАВЛИВАЕМ СВЯЗЬ"}</span>
          <h1>{failed ? "СВЯЗЬ ПОТЕРЯНА" : "ПРОВЕРКА КАНАЛА"}</h1>
          <p>{failed ? "Не удалось получить данные сервера. Попробуй обновить страницу позже." : "Загружаем эфиры, активность сервера и события."}</p>
          {failed ? <button type="button" class="sc-btn primary" onClick={() => location.reload()}>Повторить попытку</button> : <span class="sc-loading-line" aria-hidden="true" />}
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
  const donors = data.donors || [];
  const liveStreams = streams.filter((s) => s.live);
  const name = (g && g.name) || bot.name || "Сообщество";
  const title = settings.hero_title || "Наше сообщество";
  const byDay = stats.by_day || [];
  const maxDay = Math.max(1, ...byDay.map((d) => d.n || 0));

  const statItems = g
    ? [
        { value: g.members, label: "участников" },
        { value: g.online, label: "онлайн сейчас" },
        { value: g.created_days || 0, label: "дней вместе" },
      ]
    : [];

  return (
    <div class="sc-page">
      <header class="sc-top sc-masthead">
        <a class="sc-wordmark" href="/showcase" aria-label="DENDICH — витрина">
          <img src="/icon.svg" alt="" width="44" height="44" />
          <span><b>DENDICH</b><small>RADIO SILENCE / COMMUNITY</small></span>
        </a>
        <nav class="sc-site-nav" aria-label="Навигация по витрине">
          {streams.length ? <a href="#sc-streams">Эфиры</a> : null}
          {schedule.length ? <a href="#sc-schedule">События</a> : null}
          {media.length ? <a href="#sc-media">Медиа</a> : null}
          {settings.invite_url ? (
            <a class="sc-nav-join" href={settings.invite_url} target="_blank" rel="noopener noreferrer">
              <Icon name="send" size={14} /> В Discord
            </a>
          ) : null}
        </nav>
      </header>

      <main class="sc-main">
        <section class="sc-command-hero" aria-label="DENDICH">
          <div class="sc-command-coordinates" aria-hidden="true">OPERATION / DENDICH · 01—04</div>
          <div class="sc-command-content">
            <p class="sc-hero-kicker"><span class="sc-indicator" /> {title}</p>
            <h1>DENDICH<span class="sc-command-subtitle">RADIO SILENCE</span></h1>
            <p class="sc-command-tagline">СВЯЗЬ ЕСТЬ. <span>ПЛАНА НЕТ.</span></p>
            <p class="sc-command-about">
              {settings.about || "Тактические игры, неожиданные решения, живой чат и команда, с которой не бывает скучно. Arma Reforger, WARDOGS и просто хорошие вечера на связи."}
            </p>
            <div class="sc-command-actions">
              {settings.invite_url ? (
                <a class="sc-btn primary" href={settings.invite_url} target="_blank" rel="noopener noreferrer">
                  <Icon name="send" size={16} /> Присоединиться к Discord
                </a>
              ) : null}
              {liveStreams.length ? (
                <a class="sc-btn" href={liveStreams[0].url} target="_blank" rel="noopener noreferrer">
                  <Icon name="monitor" size={16} /> Смотреть эфир
                </a>
              ) : streams.length ? (
                <a class="sc-btn" href="#sc-streams"><Icon name="monitor" size={16} /> Площадки</a>
              ) : null}
              {settings.donate_url ? (
                <a class="sc-btn sc-btn-ghost" href={settings.donate_url} target="_blank" rel="noopener noreferrer">
                  <Icon name="heart" size={16} /> Поддержать
                </a>
              ) : null}
            </div>
          </div>
          <div class="sc-command-emblem" aria-hidden="true">
            <img src={settings.avatar_url || "/icon.svg"} alt="" />
            <span>D / R-S</span>
            <small>СООБЩЕСТВО НА СВЯЗИ</small>
          </div>
          <div class="sc-command-bottom" aria-hidden="true">
            <span>TACTICAL STREAMS // OPEN FREQUENCY</span>
            <span>EST. DENDICH</span>
          </div>
        </section>

        {liveStreams.length ? (
          <a class="sc-featured-live" href={liveStreams[0].url} target="_blank" rel="noopener noreferrer">
            <div class="sc-featured-live-label"><span class="sc-indicator" /> ПРЯМО СЕЙЧАС В ЭФИРЕ</div>
            {liveStreams[0].thumbnail ? <img src={liveStreams[0].thumbnail} alt="" loading="lazy" /> : <span class="sc-featured-placeholder"><Icon name="monitor" size={26}/></span>}
            <div class="sc-featured-live-copy">
              <small>{PLATFORM[liveStreams[0].platform]?.label || liveStreams[0].platform}</small>
              <b>{liveStreams[0].title || "Прямой эфир DENDICH"}</b>
              {liveStreams[0].viewers ? <span>{fmtCount(liveStreams[0].viewers)} зрителей</span> : null}
            </div>
            <span class="sc-featured-live-arrow"><Icon name="chevron-right" size={19}/></span>
          </a>
        ) : (
          <div class="sc-offline-notice"><span class="sc-offline-mark" /> <b>СЕЙЧАС ВНЕ ЭФИРА</b><span>Следующая операция скоро. До связи в Discord.</span></div>
        )}

        {statItems.length ? (
          <section class="sc-stat-section" aria-label="Сервер в цифрах">
            <div class="sc-stats sc-operational-stats">
              {statItems.map((s, i) => (
                <div class="sc-stat" key={s.label}>
                  <small>0{i + 1} / СЕРВЕР</small>
                  <b>{fmtCount(s.value)}</b>
                  <span>{s.label}</span>
                </div>
              ))}
            </div>
            {byDay.length > 1 ? (
              <div class="sc-activity-panel">
                <div><span class="sc-eyebrow">АКТИВНОСТЬ СООБЩЕСТВА</span><small>Динамика по дням</small></div>
                <div class="sc-spark" role="img" aria-label="График активности сервера">
                  {byDay.map((d, i) => <i key={i} style={{ height: Math.max(6, Math.round(((d.n || 0) / maxDay) * 100)) + "%" }} />)}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {streams.length ? (
          <section class="sc-section sc-content-section" id="sc-streams">
            <div class="sc-section-heading"><span class="sc-section-num">01 /</span><div><span class="sc-section-eyebrow">НАШИ ЧАСТОТЫ</span><h2>Площадки и эфиры</h2></div></div>
            <div class="sc-streams sc-channel-grid">
              {streams.map((s) => {
                const p = PLATFORM[s.platform] || { label: s.platform, color: "var(--accent)" };
                return (
                  <a class={"sc-stream sc-channel-card" + (s.live ? " live" : "")} key={s.url} href={s.url} target="_blank" rel="noopener noreferrer">
                    <span class="sc-channel-symbol"><Icon name="monitor" size={24}/></span>
                    <span class="sc-channel-body"><span class="sc-channel-type">ПЛАТФОРМА / {p.label}</span><b>{p.label}</b><small>{s.live ? "Идёт прямой эфир" : "Следи за следующими трансляциями"}</small></span>
                    <span class={"sc-channel-state" + (s.live ? " is-live" : "")}>{s.live ? "● В ЭФИРЕ" : "○ ОФЛАЙН"}</span>
                    <Icon name="chevron-right" size={18}/>
                  </a>
                );
              })}
            </div>
          </section>
        ) : null}

        {schedule.length ? (
          <section class="sc-section sc-content-section" id="sc-schedule">
            <div class="sc-section-heading"><span class="sc-section-num">02 /</span><div><span class="sc-section-eyebrow">КАЛЕНДАРЬ СОБЫТИЙ</span><h2>Ближайшие операции</h2></div></div>
            <div class="sc-schedule sc-briefing-list">
              {schedule.map((row, i) => (
                <div class="sc-event sc-briefing-row" key={i}>
                  <span class="sc-event-icon"><Icon name="clock" size={19}/></span>
                  <span class="grow"><b>{row.title || "Событие сообщества"}</b><small>Запланированная публикация</small></span>
                  <time>{fmtWhen(row.send_at)}</time>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {media.length ? (
          <section class="sc-section sc-content-section" id="sc-media">
            <div class="sc-section-heading"><span class="sc-section-num">03 /</span><div><span class="sc-section-eyebrow">АРХИВ ОПЕРАЦИЙ</span><h2>Медиатека</h2></div></div>
            <div class="sc-media sc-archive-grid">
              {media.map((m) => (
                <a class="sc-media-card" key={m.id} href={m.url} target="_blank" rel="noopener noreferrer" title={m.title}>
                  <img src={m.url} alt={m.title || "Медиа DENDICH"} loading="lazy" />
                  <span class="sc-media-title">{m.title || "Кадр с операции"}</span>
                </a>
              ))}
            </div>
          </section>
        ) : null}

        {donors.length ? (
          <section class="sc-section sc-content-section" id="sc-donors">
            <div class="sc-section-heading"><span class="sc-section-num">04 /</span><div><span class="sc-section-eyebrow">ПОДДЕРЖКА ПРОЕКТА</span><h2>Меценаты</h2></div></div>
            <div class="sc-donors">
              {donors.map((d, i) => (
                <div class="sc-donor" key={i}><span class="sc-donor-rank">{String(i + 1).padStart(2, "0")}</span><b>{d.name}</b><span class="sc-donor-sum">{fmtDonation(d.total, d.currency)}</span></div>
              ))}
            </div>
          </section>
        ) : null}
      </main>

      <footer class="sc-footer sc-site-footer">
        <div class="sc-footer-id"><img src="/icon.svg" width="28" height="28" alt="" /><span><b>DENDICH</b><small>RADIO SILENCE · COMMUNITY</small></span></div>
        <span class="sc-footer-right">СВЯЗЬ ЕСТЬ. ПЛАНА НЕТ.</span>
        <a href="#top" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Наверх ↑</a>
      </footer>
    </div>
  );
}
