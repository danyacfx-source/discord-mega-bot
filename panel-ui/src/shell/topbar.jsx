import { navOpen, route } from "../store.js";
import { sectionById } from "../sections/registry.jsx";
import { Icon } from "../components/icons.jsx";

export default function Topbar() {
  const sec = sectionById(route.value);
  return (
    <header class="topbar">
      <div class="topbar-left">
        <button class="mobile-menu" type="button" onClick={() => (navOpen.value = !navOpen.value)} aria-label="Меню">
          <Icon name="menu" size={18} />
        </button>
        <div class="topbar-title">
          <div class="topbar-kicker">DENDICH <span>/</span> ADMIN CONSOLE</div>
          <h1>
            <Icon name={sec.icon} size={19} />
            {sec.title}
          </h1>
          <p class="topbar-desc muted">{sec.desc}</p>
        </div>
      </div>
      <div class="topbar-radio" aria-label="DENDICH Radio Silence"><span class="radio-dot" aria-hidden="true" /> <b>RADIO SILENCE</b><em>/</em> ПАНЕЛЬ УПРАВЛЕНИЯ</div>
    </header>
  );
}
