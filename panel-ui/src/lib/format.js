import { token, csrf } from "../api.js";
import { toast } from "../store.js";

export function fmtCount(n) {
  n = Number(n) || 0;
  return n >= 1000 ? (n / 1000).toFixed(1).replace(".", ",") + "k" : String(n);
}

export function relTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  const diff = d.getTime() - Date.now();
  const abs = Math.abs(diff);
  const mins = Math.round(abs / 60000);
  let unit;
  if (mins < 60) unit = `${mins} мин`;
  else if (mins < 1440) unit = `${Math.round(mins / 60)} ч`;
  else unit = `${Math.round(mins / 1440)} дн`;
  return diff >= 0 ? `через ${unit}` : `${unit} назад`;
}

export function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("ru-RU");
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("✅ Скопировано", true);
  } catch {
    toast("❌ Не удалось скопировать", false);
  }
}

export async function downloadAuthed(url, fallbackName = "download") {
  try {
    const r = await fetch(url, { headers: { "X-Panel-Token": token() } });
    if (r.status === 401) {
      window.dispatchEvent(new CustomEvent("panel:login"));
      return false;
    }
    if (!r.ok) {
      toast("❌ Ошибка: " + r.status, false);
      return false;
    }
    let filename = fallbackName;
    const cd = r.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^";]+)"?/i);
    if (m) filename = m[1];
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    return true;
  } catch {
    toast("❌ Не удалось скачать", false);
    return false;
  }
}

export function errToast(r, fallback = "Ошибка") {
  return r.data && r.data.error ? "❌ " + r.data.error : "❌ " + fallback;
}

export async function uploadFile(file) {
  if (!file) return null;
  if (!/\.(png|jpe?g|gif|webp)$/i.test(file.name)) {
    toast("Формат не поддерживается: " + file.name, false);
    return null;
  }
  if (file.size > 8 * 1024 * 1024) {
    toast("Файл больше 8 МБ", false);
    return null;
  }
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/api/upload", {
    method: "POST",
    headers: { "X-Panel-Token": token(), ...(csrf() ? { "X-Panel-CSRF": csrf() } : {}) },
    body: fd,
  });
  const d = await r.json().catch(() => ({}));
  if (r.status === 401) window.dispatchEvent(new CustomEvent("panel:login"));
  if (d && d.ok && d.url) {
    toast("✅ Картинка загружена", true);
    return d.url;
  }
  toast(d.error ? "❌ " + d.error : "❌ Ошибка загрузки картинки", false);
  return null;
}
