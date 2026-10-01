import { useEffect } from "preact/hooks";
import Sidebar from "./shell/sidebar.jsx";
import Topbar from "./shell/topbar.jsx";
import Login from "./shell/login.jsx";
import { route, navQuery, navOpen } from "./store.js";
import { sectionById, renderSection } from "./sections/registry.jsx";

export default function App() {
  const section = sectionById(route.value);

  useEffect(() => {
    function onKey(e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        navOpen.value = true;
        const el = document.getElementById("nav-search");
        if (el) el.focus();
      }
      if (e.key === "Escape") navOpen.value = false;
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div class="app">
      <Sidebar />
      <main class="main">
        <Topbar />
        <div class="scroll">
          <div class="section active" key={section.id}>
            {renderSection(section)}
          </div>
        </div>
      </main>
      <Login />
    </div>
  );
}
