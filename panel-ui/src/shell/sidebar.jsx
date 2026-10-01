import { navQuery, navOpen, navigate, route, theme, setTheme, accent, setAccent, ACCENT_LIST, toasts } from "../store.js";
import { NAV } from "../sections/registry.jsx";
import { doLogout } from "../api.js";

export default function Sidebar() {
  const q = navQuery.value.trim().toLowerCase();
  return (
    <>
      <div class="sidebar-scrim" onClick={() => (navOpen.value = false)} />
      <aside class={"sidebar" + (navOpen.value ? " open" : "")}>
        <div class="brand">
          <span class="brand-ic">A</span>
          <span class="brand-copy">
            Асуна Юки<small>Control center</small>
          </span>
        </div>

        <div class="nav-search">
          <span class="nav-search-ic">⌕</span>
          <input
            id="nav-search"
            type="text"
            placeholder="Найти раздел…"
            autocomplete="off"
            value={navQuery.value}
            onInput={(e) => (navQuery.value = e.target.value)}
          />
          <kbd>Ctrl K</kbd>
        </div>

        <nav>
          {NAV.map((group) => {
            const items = group.items.filter((s) => !q || s.title.toLowerCase().includes(q));
            if (!items.length) return null;
            return (
              <div class="nav-group" key={group.label}>
                <div class="nav-label">{group.label}</div>
                {items.map((s) => (
                  <button
                    type="button"
                    key={s.id}
                    class={"nav-item" + (route.value === s.id ? " active" : "")}
                    onClick={() => (s.href ? window.open(s.href, "_blank") : navigate(s.id))}
                  >
                    <span>{s.icon}</span>
                    <span>{s.title}</span>
                  </button>
                ))}
              </div>
            );
          })}
          {q && !NAV.some((g) => g.items.some((s) => s.title.toLowerCase().includes(q))) && (
            <div class="nav-empty">Ничего не найдено</div>
          )}
        </nav>

        <div class="theme-block">
          <label>Тема</label>
          <div class="seg">
            <button type="button" class={"seg-btn" + (theme.value === "dark" ? " active" : "")} onClick={() => setTheme("dark")}>
              🌙
            </button>
            <button type="button" class={"seg-btn" + (theme.value === "light" ? " active" : "")} onClick={() => setTheme("light")}>
              ☀️
            </button>
          </div>
          <label>Акцент</label>
          <div class="accents">
            {ACCENT_LIST.map((c) => (
              <button
                type="button"
                key={c}
                class={"accent-dot" + (accent.value === c ? " active" : "")}
                style={{ background: c }}
                onClick={() => setAccent(c)}
                aria-label={c}
              />
            ))}
          </div>
        </div>

        <div class="sidebar-foot">
          <button class="link-btn" onClick={doLogout} type="button">
            Выйти
          </button>
          <span class="badge">v2</span>
        </div>
      </aside>

      <div class="toasts" id="toasts">
        {toasts.value.map((t) => (
          <div key={t.id} class={"toast " + (t.ok ? "ok" : "bad")}>
            {t.msg}
          </div>
        ))}
      </div>
    </>
  );
}
