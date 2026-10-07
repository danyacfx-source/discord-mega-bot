import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, toast, errToast, uploadFile } from "../lib/exports.js";
import { Chip, Empty, Field, Loading, Toggle } from "../components/ui.jsx";
import { Icon } from "../components/icons.jsx";

export default function Media() {
  const [items, setItems] = useState(null);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [tags, setTags] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(-1);
  const fileRef = useRef(null);

  async function load() {
    const r = await api("/api/media");
    if (r.status === 200 && r.data.ok) setItems(r.data.items || []);
    else {
      setItems([]);
      if (r.data.error) toast(r.data.error, false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const filtered = useMemo(() => {
    const list = items || [];
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (it) =>
        (it.title || "").toLowerCase().includes(q) ||
        (it.tags || []).some((t) => String(t).toLowerCase().includes(q))
    );
  }, [items, query]);

  useEffect(() => {
    if (open < 0) return undefined;
    function onKey(e) {
      if (e.key === "Escape") setOpen(-1);
      if (e.key === "ArrowRight") setOpen((i) => (filtered.length ? (i + 1) % filtered.length : -1));
      if (e.key === "ArrowLeft") setOpen((i) => (filtered.length ? (i - 1 + filtered.length) % filtered.length : -1));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtered.length]);

  async function pickFile(e) {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const uploaded = await uploadFile(file);
    if (uploaded) {
      setUrl(uploaded);
      if (!title.trim()) setTitle(file.name.replace(/\.[^.]+$/, "").slice(0, 100));
    }
  }

  async function add() {
    if (!url) return toast("Загрузите файл или вставьте ссылку", false);
    const r = await api("/api/media", { title, url, tags, public: isPublic });
    if (r.status === 200 && r.data.ok) {
      toast("Добавлено в медиатеку", true);
      setTitle("");
      setUrl("");
      setTags("");
      load();
    } else toast(errToast(r), false);
  }

  async function like(id) {
    const r = await api(`/api/media/${id}/like`, {}, "POST");
    if (r.status !== 200 || !r.data.ok) return;
    setItems((list) =>
      (list || []).map((it) => (it.id === id ? { ...it, likes: r.data.likes, liked: r.data.liked } : it))
    );
  }

  async function remove(id) {
    if (!confirm("Удалить элемент из медиатеки?")) return;
    const r = await api(`/api/media/${id}`, {}, "DELETE");
    if (r.status === 200 && r.data.ok) {
      toast("Удалено", true);
      setOpen(-1);
      load();
    } else toast(errToast(r), false);
  }

  const current = open >= 0 ? filtered[open] : null;

  return (
    <div class="stack">
      <div class="card">
        <h3 class="sec">Добавить в медиатеку</h3>
        <div class="two">
          <div class="stack">
            <Field label="Файл (PNG, JPG, GIF, WEBP до 8 МБ)">
              <div class="row-inline">
                <button class="btn" type="button" onClick={() => fileRef.current && fileRef.current.click()}>
                  <Icon name="plus" size={14} /> Выбрать файл
                </button>
                <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/gif,image/webp" style={{ display: "none" }} onChange={pickFile} />
                {url ? <Chip tone="ok">{url.split("/").pop()}</Chip> : <span class="muted small">или вставьте ссылку справа</span>}
              </div>
            </Field>
            <Field label="Название">
              <input class="input" type="text" placeholder="Кадр со стрима" value={title} onInput={(e) => setTitle(e.target.value)} />
            </Field>
          </div>
          <div class="stack">
            <Field label="Ссылка (заполняется после загрузки)">
              <input class="input" type="text" placeholder="/uploads/…" value={url} onInput={(e) => setUrl(e.target.value)} />
            </Field>
            <Field label="Теги через запятую">
              <input class="input" type="text" placeholder="стрим, сакура, мем" value={tags} onInput={(e) => setTags(e.target.value)} />
            </Field>
            <div class="row-inline">
              <button class="btn success" type="button" onClick={add}>
                В галерею
              </button>
              <Toggle checked={isPublic} onChange={setIsPublic} label="Показывать на витрине" />
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="media-head">
          <h3 class="sec">Галерея</h3>
          <input class="input media-search" type="search" placeholder="Поиск по названию и тегам…" value={query} onInput={(e) => setQuery(e.target.value)} />
        </div>
        {!items && <Loading />}
        {items && !filtered.length && <Empty>{query ? "Ничего не найдено" : "Медиатека пуста — добавьте первый кадр"}</Empty>}
        {filtered.length ? (
          <div class="media-grid">
            {filtered.map((it, idx) => (
              <div class="media-card" key={it.id} onClick={() => setOpen(idx)}>
                <div class="media-thumb">
                  <img src={it.url} alt={it.title} loading="lazy" />
                  {it.type === "gif" ? <span class="media-flag">GIF</span> : null}
                  {!it.public ? <span class="media-flag priv">приват</span> : null}
                </div>
                <div class="media-meta">
                  <b>{it.title}</b>
                  <div class="media-foot">
                    <span class="media-tags">
                      {(it.tags || []).slice(0, 2).map((t) => (
                        <Chip key={t}>{t}</Chip>
                      ))}
                    </span>
                    <button
                      class={"media-like" + (it.liked ? " on" : "")}
                      type="button"
                      title="Лайк"
                      onClick={(e) => {
                        e.stopPropagation();
                        like(it.id);
                      }}
                    >
                      <Icon name="heart" size={13} /> {it.likes}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      {current ? (
        <div class="lightbox" onClick={() => setOpen(-1)}>
          <div class="lightbox-box" onClick={(e) => e.stopPropagation()}>
            <div class="lightbox-img">
              <img src={current.url} alt={current.title} />
            </div>
            <div class="lightbox-bar">
              <div class="lightbox-info">
                <b>{current.title}</b>
                <span class="muted small">
                  {current.author ? `${current.author} · ` : ""}
                  {current.likes} ♥
                  {current.tags && current.tags.length ? ` · ${current.tags.join(", ")}` : ""}
                </span>
              </div>
              <div class="row-inline">
                <button class={"btn mini" + (current.liked ? " success" : "")} type="button" onClick={() => like(current.id)}>
                  <Icon name="heart" size={13} /> {current.likes}
                </button>
                <button class="btn mini danger" type="button" onClick={() => remove(current.id)}>
                  <Icon name="trash" size={13} />
                </button>
                <button class="btn mini" type="button" onClick={() => setOpen((i) => (i - 1 + filtered.length) % filtered.length)} title="Назад">
                  <Icon name="chevron-left" size={14} />
                </button>
                <button class="btn mini" type="button" onClick={() => setOpen((i) => (i + 1) % filtered.length)} title="Вперёд">
                  <Icon name="chevron-right" size={14} />
                </button>
                <button class="btn mini" type="button" onClick={() => setOpen(-1)} title="Закрыть">
                  <Icon name="x" size={14} />
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
