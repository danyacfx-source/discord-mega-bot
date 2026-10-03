import { useEffect, useState } from "preact/hooks";
import { api, toast, copyText } from "../lib/exports.js";

export default function FilesSection() {
  const [files, setFiles] = useState(null);

  async function load() {
    const r = await api("/api/uploads");
    setFiles((r.data && r.data.files) || []);
  }

  useEffect(() => {
    load();
  }, []);

  async function remove(name) {
    if (!confirm("Удалить файл " + name + "?")) return;
    const r = await api("/api/uploads/" + encodeURIComponent(name), null, "DELETE");
    if (r.status === 200 && r.data.ok) {
      toast("Файл удалён", true);
      load();
    } else toast("Ошибка удаления", false);
  }

  return (
    <div class="card">
      <h3 class="sec">Загруженные изображения</h3>
      <div class="muted small" style={{ marginBottom: 10 }}>
        Изображения, загруженные для эмбедов. Кнопка «URL» копирует прямую ссылку.
      </div>
      {!files && <div class="muted small">Загрузка…</div>}
      {files && !files.length && <div class="muted">Загруженных файлов пока нет.</div>}
      {files && !!files.length && (
        <div class="grid cols4">
          {files.map((f) => (
            <div class="file-card" key={f.name}>
              <img class="file-thumb" loading="lazy" src={f.url} alt={f.name} />
              <div class="file-name">{f.name}</div>
              <div class="file-size muted">{f.size || ""}</div>
              <div class="file-actions">
                <button class="btn mini" type="button" onClick={() => copyText(f.url)}>URL</button>
                <button class="btn mini danger" type="button" title="Удалить" onClick={() => remove(f.name)}>×</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
