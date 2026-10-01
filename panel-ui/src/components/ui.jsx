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
