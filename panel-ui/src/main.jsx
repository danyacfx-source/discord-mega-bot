import { render } from "preact";
import App from "./app.jsx";
import { applyTheme, loginVisible } from "./store.js";
import { PASSWORD_LOGIN, token } from "./api.js";
import "./styles/app.css";
import "./styles/anime.css";

applyTheme();
if (PASSWORD_LOGIN && !token()) loginVisible.value = true;

render(<App />, document.getElementById("app"));

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
