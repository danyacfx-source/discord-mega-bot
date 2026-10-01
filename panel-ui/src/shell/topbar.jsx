import { navOpen, route } from "../store.js";
import { sectionById } from "../sections/registry.jsx";

export default function Topbar() {
  const sec = sectionById(route.value);
  return (
    <header class="topbar">
      <div class="topbar-left">
        <button class="mobile-menu" type="button" onClick={() => (navOpen.value = !navOpen.value)} aria-label="Меню">
          ☰
        </button>
        <div class="topbar-title">
          <h1>
            {sec.icon} {sec.title}
          </h1>
          <p class="topbar-desc muted">{sec.desc}</p>
        </div>
      </div>
    </header>
  );
}
