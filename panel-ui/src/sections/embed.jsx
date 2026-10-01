import { useEffect, useState } from "preact/hooks";
import { api, toast, errToast, uploadFile } from "../lib/exports.js";

const COLORS = {
  blurple: 0x5865f2,
  green: 0x23a55a,
  red: 0xf23f43,
  yellow: 0xf0b232,
  dark: 0x111214,
  grey: 0x96989d,
  orange: 0xf2780d,
  teal: 0x1abc9c,
  pink: 0xeb459e,
};
const hex6 = /^#?([0-9a-f]{6})$/i;

function resolveColor(str) {
  if (str === "" || str === null || str === undefined) return null;
  if (typeof str === "number" && Number.isFinite(str)) return str;
  const s = String(str).trim().toLowerCase();
  if (COLORS[s] !== undefined) return COLORS[s];
  const m = hex6.exec(s);
  if (m) return parseInt(m[1], 16);
  return null;
}

function colorHex(str) {
  const c = resolveColor(str);
  return c === null ? "#5865f2" : "#" + c.toString(16).padStart(6, "0");
}

function newEmbed() {
  return {
    title: "",
    desc: "",
    color: "",
    author_name: "",
    author_icon: "",
    author_url: "",
    footer_text: "",
    footer_icon: "",
    image: "",
    thumb: "",
    ts: false,
    fields: [],
  };
}

function readEmbed(e) {
  const out = {};
  const t = e.title.trim().slice(0, 256);
  const d = e.desc.trim().slice(0, 4000);
  if (t) out.title = t;
  if (d) out.description = d;
  const co = resolveColor(e.color);
  if (co !== null) out.color = co;
  const an = e.author_name.trim().slice(0, 256);
  if (an)
    out.author = {
      name: an,
      icon_url: e.author_icon.trim().slice(0, 2048) || undefined,
      url: e.author_url.trim().slice(0, 2048) || undefined,
    };
  const ft = e.footer_text.trim().slice(0, 2048);
  if (ft) out.footer = { text: ft, icon_url: e.footer_icon.trim().slice(0, 2048) || undefined };
  const im = e.image.trim().slice(0, 2048);
  if (im) out.image = { url: im };
  const th = e.thumb.trim().slice(0, 2048);
  if (th) out.thumbnail = { url: th };
  if (e.ts) out.timestamp = new Date().toISOString();
  const fs = e.fields.slice(0, 25).filter((f) => f.name.trim() || f.value.trim());
  if (fs.length)
    out.fields = fs.map((f) => ({
      name: f.name.trim().slice(0, 256),
      value: f.value.trim().slice(0, 1024),
      inline: !!f.inline,
    }));
  return Object.keys(out).length === 0 ? null : out;
}

function embedHasContent(e) {
  return !!(
    e.title.trim() ||
    e.desc.trim() ||
    e.color.trim() ||
    e.author_name.trim() ||
    e.footer_text.trim() ||
    e.image.trim() ||
    e.thumb.trim() ||
    e.fields.some((f) => f.name.trim() || f.value.trim())
  );
}

function Preview({ content, embeds, btnRows }) {
  const trimmed = content.trim();
  const ems = embeds.slice(0, 10);
  const hasEmbed = ems.some(embedHasContent);
  const hasButtons = btnRows.some((r) => r.length);
  if (!trimmed && !hasEmbed && !hasButtons) {
    return <div class="empty muted">Заполните форму, чтобы увидеть предпросмотр</div>;
  }
  const sum =
    trimmed.length +
    ems.reduce(
      (acc, e) =>
        acc +
        e.title.trim().length +
        e.desc.trim().length +
        e.fields.reduce((a, f) => a + f.name.trim().length + f.value.trim().length, 0),
      0,
    );

  return (
    <div class="dc-preview">
      {trimmed && <div class="content-preview">{trimmed}</div>}
      <div class={"sum-line" + (sum > 6000 ? " over" : "")}>
        Суммарно: {sum} / 6000 символов{sum > 6000 ? " — лимит превышен" : ""}
      </div>
      {ems.filter(embedHasContent).map((e, i) => (
        <div class="embed-card" style={{ borderLeftColor: colorHex(e.color) }} key={i}>
          {e.author_name.trim() && (
            <div class="embed-author">
              {e.author_name.trim()}
              {e.thumb.trim() && <img class="embed-thumb" src={e.thumb.trim()} alt="" />}
            </div>
          )}
          {e.title.trim() && <div class="embed-title">{e.title.trim()}</div>}
          {e.desc.trim() && <div class="embed-desc">{e.desc.trim()}</div>}
          {e.fields.length > 0 && (
            <div class="fields">
              {e.fields.map((f, fi) => (
                <div class={"embed-field" + (f.inline ? " inline" : "")} key={fi}>
                  <div class="fname">{f.name}</div>
                  <div class="fvalue">{f.value}</div>
                </div>
              ))}
            </div>
          )}
          {e.image.trim() && <img class="embed-image" src={e.image.trim()} alt="" />}
          {e.footer_text.trim() && <div class="embed-footer">{e.footer_text.trim()}</div>}
          {e.ts && <div class="embed-ts">{new Date().toLocaleString("ru-RU")}</div>}
        </div>
      ))}
      {hasButtons && (
        <div class="preview-buttons">
          {btnRows.filter((r) => r.length).map((row, ri) => (
            <div class="preview-btn-row" key={ri}>
              {row.map((b, bi) =>
                b.style === 5 ? (
                  <a class={"dc-btn s" + b.style} href={b.url || "#"} target="_blank" rel="noopener" key={bi}>
                    {b.label || "Кнопка"}
                  </a>
                ) : (
                  <span class={"dc-btn s" + (b.style || 2)} key={bi}>
                    {b.label || "Кнопка"}
                  </span>
                ),
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EmbedEditor({ embed, index, total, onChange, onDup, onDelete }) {
  const set = (key, value) => onChange({ ...embed, [key]: value });

  const setField = (fi, key, value) => {
    const fields = embed.fields.map((f, i) => (i === fi ? { ...f, [key]: value } : f));
    set("fields", fields);
  };

  async function pickFile(kind, file) {
    if (!file) return;
    const url = await uploadFile(file);
    if (url) set(kind, url);
  }

  return (
    <div class="embed-ed">
      <div class="embed-ed-head">
        Эмбед {index + 1} <span class="muted small">({index + 1}/{total})</span>
        <div class="row-actions">
          <button class="btn mini" type="button" title="Дублировать эмбед" onClick={onDup}>
            ⧉ Дублировать
          </button>
          <button class="btn mini danger" type="button" title="Удалить эмбед" onClick={onDelete}>
            ✖
          </button>
        </div>
      </div>

      <label class="field"><span class="field-label">Заголовок</span>
        <input class="input" type="text" maxlength="256" placeholder="Заголовок" value={embed.title} onInput={(e) => set("title", e.target.value)} />
      </label>
      <label class="field"><span class="field-label">Описание</span>
        <textarea class="input" rows="4" maxlength="4000" placeholder="Описание" value={embed.desc} onInput={(e) => set("desc", e.target.value)} />
      </label>

      <label class="field"><span class="field-label">Цвет полоски</span>
        <div class="row-inline">
          <input class="input" type="text" placeholder="например #5865f2 или blurple" value={embed.color} onInput={(e) => set("color", e.target.value)} />
          <input
            type="color"
            class="color-picker"
            value={colorHex(embed.color)}
            onInput={(e) => set("color", e.target.value)}
          />
          <span class="color-swatch" style={{ background: colorHex(embed.color) }} />
        </div>
      </label>

      <label class="field"><span class="field-label">Автор — имя</span>
        <input class="input" type="text" maxlength="256" value={embed.author_name} onInput={(e) => set("author_name", e.target.value)} />
      </label>
      <label class="field"><span class="field-label">Автор — иконка (URL)</span>
        <input class="input" type="url" value={embed.author_icon} onInput={(e) => set("author_icon", e.target.value)} />
      </label>
      <label class="field"><span class="field-label">Автор — ссылка</span>
        <input class="input" type="url" value={embed.author_url} onInput={(e) => set("author_url", e.target.value)} />
      </label>

      <label class="field"><span class="field-label">Подвал — текст</span>
        <input class="input" type="text" maxlength="2048" value={embed.footer_text} onInput={(e) => set("footer_text", e.target.value)} />
      </label>
      <label class="field"><span class="field-label">Подвал — иконка (URL)</span>
        <input class="input" type="url" value={embed.footer_icon} onInput={(e) => set("footer_icon", e.target.value)} />
      </label>

      <label class="field"><span class="field-label">Изображение</span>
        <div class="row-inline">
          <input class="input" type="url" value={embed.image} onInput={(e) => set("image", e.target.value)} />
          <label class="btn mini upload-btn">
            ⬆ Загрузить
            <input
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                pickFile("image", e.target.files[0]);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </label>

      <label class="field"><span class="field-label">Миниатюра</span>
        <div class="row-inline">
          <input class="input" type="url" value={embed.thumb} onInput={(e) => set("thumb", e.target.value)} />
          <label class="btn mini upload-btn">
            ⬆ Загрузить
            <input
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                pickFile("thumb", e.target.files[0]);
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </label>

      <div style={{ margin: "8px 0" }}>
        <label class="toggle-holder">
          <span class="switch">
            <input type="checkbox" checked={embed.ts} onChange={(e) => set("ts", e.target.checked)} />
            <span class="slider" />
          </span>
          <span>Время отправки</span>
        </label>
      </div>

      <h5 class="sec">Поля (до 25)</h5>
      <div class="embed-fields">
        {!embed.fields.length && <div class="hint muted small">Поля не добавлены</div>}
        {embed.fields.map((f, fi) => (
          <div class="field-item" key={fi}>
            <div class="row-inline">
              <input class="input" type="text" placeholder="Название" maxlength="256" value={f.name} onInput={(e) => setField(fi, "name", e.target.value)} />
              <input class="input" type="text" placeholder="Значение" maxlength="1024" value={f.value} onInput={(e) => setField(fi, "value", e.target.value)} />
              <select class="input mini-select" value={f.inline ? "1" : "0"} onChange={(e) => setField(fi, "inline", e.target.value === "1")}>
                <option value="0">В столбец</option>
                <option value="1">В ряд</option>
              </select>
              <button
                class="btn mini danger"
                type="button"
                title="Удалить поле"
                onClick={() => set("fields", embed.fields.filter((_, i) => i !== fi))}
              >
                ✖
              </button>
            </div>
          </div>
        ))}
      </div>
      <button
        class="btn mini"
        type="button"
        style={{ marginTop: "10px" }}
        onClick={() => {
          if (embed.fields.length >= 25) return toast("Максимум 25 полей", false);
          set("fields", [...embed.fields, { name: "Поле", value: "Описание", inline: false }]);
        }}
      >
        ＋ Добавить поле
      </button>
    </div>
  );
}

export default function EmbedBuilder() {
  const [mode, setModeState] = useState("webhook");
  const [content, setContent] = useState("");
  const [embeds, setEmbeds] = useState([newEmbed()]);
  const [btnRows, setBtnRows] = useState([[]]);
  const [whUrl, setWhUrl] = useState("");
  const [channels, setChannels] = useState([]);
  const [channelId, setChannelId] = useState("");
  const [msgId, setMsgId] = useState("");

  async function loadChannels() {
    const r = await api("/api/bot/channels");
    const list = (r.data && r.data.channels) || [];
    setChannels(list);
    setChannelId((cur) => cur || (list[0] && list[0].id) || "");
  }

  function setMode(m) {
    setModeState(m);
    if (m === "bot") loadChannels();
  }

  function buildPayload() {
    const p = {
      content: content.slice(0, 2000) || null,
      embeds: embeds.slice(0, 10).map(readEmbed).filter(Boolean),
      components: btnRows.filter((r) => r.length),
    };
    if (mode === "bot") p.channel_id = channelId;
    else p.webhook_url = whUrl;
    return p;
  }

  async function sendMsg() {
    const payload = buildPayload();
    const target = mode === "bot" ? payload.channel_id : payload.webhook_url;
    if (!target) return toast(mode === "bot" ? "Укажите канал" : "Укажите Webhook URL", false);
    if (payload.embeds.length === 0 && !payload.content) return toast("Пустое сообщение", false);
    const r = await api("/api/" + (mode === "bot" ? "bot/send" : "webhook/send"), payload);
    if (r.status === 200 && r.data.ok) {
      toast("✅ Отправлено", true);
      if (mode === "bot") loadMsg();
    } else toast(errToast(r), false);
  }

  async function editMsg() {
    const mid = msgId.trim();
    if (!mid) return toast("Укажите ID сообщения", false);
    const payload = buildPayload();
    const target = mode === "bot" ? payload.channel_id : payload.webhook_url;
    if (!target) return toast(mode === "bot" ? "Укажите канал" : "Укажите Webhook URL", false);
    payload.message_id = mid;
    const r = await api("/api/" + (mode === "bot" ? "bot/edit" : "webhook/edit"), payload);
    if (r.status === 200 && r.data.ok) toast("✅ Сообщение изменено", true);
    else toast(errToast(r), false);
  }

  async function loadMsg() {
    const mid = msgId.trim().replace(/^https:\/\/discord(a)?\.com\/channels\/\d+\/\d+\//, "");
    if (!mid) return toast("Укажите ID сообщения", false);
    const payload = { message_id: mid };
    if (mode === "bot") {
      if (!channelId) return toast("Укажите канал", false);
      payload.channel_id = channelId;
    } else {
      if (!whUrl) return toast("Укажите Webhook URL", false);
      payload.webhook_url = whUrl;
    }
    const r = await api("/api/" + (mode === "bot" ? "bot/fetch" : "webhook/fetch"), payload);
    if (r.status !== 200 || !r.data.ok || !r.data.data) return toast("❌ Сообщение не найдено", false);
    const msg = r.data.data;
    const src = msg.embeds && msg.embeds.length ? msg.embeds : [null];
    setEmbeds(
      src.slice(0, 10).map((em) => ({
        title: (em && em.title) || "",
        desc: (em && em.description) || "",
        color: (em && em.color) || "",
        author_name: (em && em.author && em.author.name) || "",
        author_icon: (em && em.author && em.author.icon_url) || "",
        author_url: (em && em.author && em.author.url) || "",
        footer_text: (em && em.footer && em.footer.text) || "",
        footer_icon: (em && em.footer && em.footer.icon_url) || "",
        image: (em && em.image && em.image.url) || "",
        thumb: (em && em.thumbnail && em.thumbnail.url) || "",
        ts: false,
        fields: (em && em.fields ? em.fields : []).map((f) => ({
          name: f.name || "",
          value: f.value || "",
          inline: !!f.inline,
        })),
      })),
    );
    setContent(msg.content || "");
    setBtnRows(msg.components && msg.components.length ? msg.components : [[]]);
    toast("✅ Загружено в конструктор", true);
  }

  function clearBuilder() {
    setEmbeds([newEmbed()]);
    setBtnRows([[]]);
    setContent("");
    toast("🧹 Поля очищены", true);
  }

  function addEmbed() {
    if (embeds.length >= 10) return toast("Максимум 10 эмбедов в сообщении", false);
    setEmbeds([...embeds, newEmbed()]);
  }

  function dupEmbed(i) {
    if (embeds.length >= 10) return toast("Максимум 10 эмбедов в сообщении", false);
    const copy = JSON.parse(JSON.stringify(embeds[i]));
    setEmbeds([...embeds.slice(0, i + 1), copy, ...embeds.slice(i + 1)]);
  }

  function delEmbed(i) {
    if (embeds.length <= 1) return toast("Должен остаться минимум 1 эмбед", false);
    setEmbeds(embeds.filter((_, k) => k !== i));
  }

  function addButton() {
    let rows = btnRows.length ? btnRows : [[]];
    const last = rows[rows.length - 1];
    if (!last || last.length >= 5) {
      if (rows.length >= 5) return toast("Максимум 5 рядов", false);
      rows = [...rows, []];
    }
    const rowIdx = rows.length - 1;
    rows[rowIdx] = [...rows[rowIdx], { label: "Кнопка", style: 2, url: "" }];
    setBtnRows(rows);
  }

  function addButtonRow() {
    if (btnRows.length >= 5) return toast("Максимум 5 рядов", false);
    setBtnRows([...btnRows, []]);
  }

  function setButton(ri, bi, key, value) {
    setBtnRows(btnRows.map((row, r) => (r === ri ? row.map((b, i) => (i === bi ? { ...b, [key]: value } : b)) : row)));
  }

  function delButton(ri, bi) {
    setBtnRows(btnRows.map((row, r) => (r === ri ? row.filter((_, i) => i !== bi) : row)).filter((r) => r.length));
  }

  return (
    <div class="embed-layout">
      <div class="card" style={{ gridColumn: "1 / -1" }}>
        <h3 class="sec">Предпросмотр</h3>
        <Preview content={content} embeds={embeds} btnRows={btnRows} />
      </div>

      <div class="stack">
        <div class="card">
          <h3 class="sec">Содержимое (текст выше эмбедов)</h3>
          <input class="input" type="text" maxlength="2000" placeholder="Текст…" value={content} onInput={(e) => setContent(e.target.value)} />
        </div>

        <div class="card">
          <h3 class="sec">
            Эмбеды <span class="muted small">(макс. 10, до 6000 символов вместе)</span>
          </h3>
          <div class="embeds-box">
            {embeds.map((e, i) => (
              <EmbedEditor
                key={i}
                embed={e}
                index={i}
                total={embeds.length}
                onChange={(next) => setEmbeds(embeds.map((x, k) => (k === i ? next : x)))}
                onDup={() => dupEmbed(i)}
                onDelete={() => delEmbed(i)}
              />
            ))}
          </div>
          <button class="btn" type="button" style={{ marginTop: "10px" }} onClick={addEmbed}>
            ＋ Добавить эмбед
          </button>
        </div>
      </div>

      <div class="stack">
        <div class="card">
          <h3 class="sec">Кнопки (до 5×5)</h3>
          <p class="muted small" style={{ margin: "0 0 8px" }}>
            Стиль «Ссылка» → URL, остальные стили — декоративные.
          </p>
          <div class="btn-editor">
            {btnRows.map((row, ri) => (
              <div class="btn-row-edit" key={ri}>
                <div class="inlinebox muted small">Ряд {ri + 1}:</div>
                {row.map((b, bi) => (
                  <div class="btn-cell" key={bi}>
                    <input class="input" type="text" placeholder="Текст" maxlength="80" value={b.label} onInput={(e) => setButton(ri, bi, "label", e.target.value)} />
                    <input class="input" type="url" placeholder="URL (стиль Ссылка)" maxlength="255" value={b.url || ""} onInput={(e) => setButton(ri, bi, "url", e.target.value.trim())} />
                    <select class="input mini-select" value={String(b.style || 2)} onChange={(e) => setButton(ri, bi, "style", parseInt(e.target.value, 10))}>
                      <option value="1">Primary</option>
                      <option value="2">Secondary</option>
                      <option value="3">Success</option>
                      <option value="4">Danger</option>
                      <option value="5">Link</option>
                    </select>
                    <button class="btn mini danger" type="button" title="Удалить кнопку" onClick={() => delButton(ri, bi)}>
                      ✖
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div class="row-inline">
            <button class="btn" type="button" onClick={addButton}>＋ Добавить кнопку</button>
            <button class="btn" type="button" onClick={addButtonRow}>＋ Новая строка</button>
          </div>
        </div>

        <div class="card">
          <h3 class="sec">Отправка</h3>
          <div class="row-inline">
            <button class={"btn" + (mode === "webhook" ? " active" : "")} type="button" onClick={() => setMode("webhook")}>
              Webhook
            </button>
            <button class={"btn" + (mode === "bot" ? " active" : "")} type="button" onClick={() => setMode("bot")}>
              Через бота
            </button>
          </div>
          {mode === "webhook" ? (
            <label class="field"><span class="field-label">Webhook URL</span>
              <input class="input" type="url" placeholder="https://discord.com/api/webhooks/…" value={whUrl} onInput={(e) => setWhUrl(e.target.value)} />
            </label>
          ) : (
            <label class="field"><span class="field-label">Канал</span>
              <div class="row-inline">
                <select class="input" value={channelId} onChange={(e) => setChannelId(e.target.value)}>
                  {!channels.length && <option value="">Нет каналов</option>}
                  {channels.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name || c.id}
                    </option>
                  ))}
                </select>
                <button class="btn" type="button" onClick={loadChannels} title="Обновить каналы">⟳</button>
              </div>
            </label>
          )}
          <label class="field"><span class="field-label">ID сообщения для изменения / загрузки</span>
            <input class="input" type="text" placeholder="1234567890123456789" value={msgId} onInput={(e) => setMsgId(e.target.value)} />
          </label>
          <div class="row-inline">
            <button class="btn primary" type="button" onClick={sendMsg}>➤ Отправить</button>
            <button class="btn" type="button" onClick={editMsg}>✎ Изменить</button>
            <button class="btn" type="button" onClick={loadMsg}>⇣ Загрузить</button>
            <button class="btn" type="button" onClick={clearBuilder}>🧹 Очистить</button>
          </div>
        </div>
      </div>
    </div>
  );
}
