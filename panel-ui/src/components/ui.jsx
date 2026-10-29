import { useEffect, useState } from "preact/hooks";

const PALETTE = ["#f7f5ee", "#b9a47a", "#e7c36c", "#92b188", "#78a9d1", "#bc8acd", "#d37c6d", "#303b33"];

export function ColorControl({ value, onChange, label }) {
  const fallback = "#b9a47a";
  const color = /^#[0-9a-fA-F]{6}$/.test(value || "") ? value : fallback;
  const [draft, setDraft] = useState(color);
  useEffect(() => { setDraft(color); }, [color]);
  function setColor(next) {
    const normalized = String(next).trim();
    setDraft(normalized);
    if (/^#[0-9a-fA-F]{6}$/.test(normalized)) onChange(normalized.toLowerCase());
  }
  return (
    <label class="color-control">
      {label && <span>{label}</span>}
      <span class="color-control-row">
        <span class="color-swatches" aria-label={label || "Выбор цвета"}>
          {PALETTE.map((swatch) => (
            <button class={"color-swatch" + (color.toLowerCase() === swatch ? " selected" : "")} type="button" title={swatch} style={{ "--swatch": swatch }} onClick={() => setColor(swatch)} />
          ))}
        </span>
        <input class="input color-hex" type="text" maxLength="7" value={draft} aria-label={label || "HEX-цвет"} onInput={(e) => setColor(e.currentTarget.value)} onBlur={() => setColor(color)} />
      </span>
    </label>
  );
}

export function Field({ label, children, hint }) {
  return (
    <label class="field">
      <span class="field-label">{label}</span>
      {children}
      {hint ? <span class="field-hint muted small">{hint}</span> : null}
    </label>
  );
}

export function Empty({ children = "Пусто" }) {
  return <div class="empty muted">{children}</div>;
}

export function Loading() {
  return <div class="empty muted">Загрузка…</div>;
}

export function Chip({ children, tone, title, onClick }) {
  const cls = "chip" + (tone ? " tone-" + tone : "") + (onClick ? " clickable" : "");
  if (onClick) {
    return (
      <span class={cls} title={title} onClick={onClick} role="button">
        {children}
      </span>
    );
  }
  return (
    <span class={cls} title={title}>
      {children}
    </span>
  );
}

export function ListRow({ children, onClick, title }) {
  return (
    <div class={"listline" + (onClick ? " clickable" : "")} onClick={onClick} title={title}>
      {children}
    </div>
  );
}

export function Actions({ children }) {
  return <div class="row-actions">{children}</div>;
}

export function Toggle({ checked, onChange, label }) {
  return (
    <label class="toggle-holder">
      <span class="switch">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span class="slider" />
      </span>
      <span>{label}</span>
    </label>
  );
}
