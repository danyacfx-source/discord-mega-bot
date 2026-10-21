import { useState } from "preact/hooks";
import { loginVisible, toast } from "../store.js";
import { doLogin, startOauth, OAUTH_ENABLED, PASSWORD_LOGIN } from "../api.js";

export default function Login() {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);

  if (!loginVisible.value) return null;

  async function submit(e) {
    e.preventDefault();
    if (busy || !pw) return;
    setBusy(true);
    const ok = await doLogin(pw);
    setBusy(false);
    if (ok) {
      loginVisible.value = false;
      setPw("");
      toast("Добро пожаловать", true);
      setTimeout(() => location.reload(), 300);
    } else {
      toast("Неверный пароль", false);
    }
  }

  return (
    <div class="login" id="login">
      <form class="login-card" onSubmit={submit}>
        <div class="login-logo"><img src="/icon.svg" alt="" /></div>
        <p class="login-eyebrow">DENDICH / RADIO SILENCE</p>
        <h2>COMMAND CENTER</h2>
        <p class="login-tagline">Связь есть. Плана нет.</p>
        {PASSWORD_LOGIN ? (
          <>
            <p class="login-sub muted">Введите пароль, чтобы продолжить</p>
            <input
              type="password"
              placeholder="Пароль"
              autocomplete="current-password"
              value={pw}
              onInput={(e) => setPw(e.target.value)}
              autoFocus
            />
            <button class="btn primary block" type="submit" disabled={busy}>
              {busy ? "…" : "Войти"}
            </button>
          </>
        ) : (
          <p class="login-sub muted">Авторизуйтесь, чтобы продолжить</p>
        )}
        {OAUTH_ENABLED && (
          <button class="btn primary block" type="button" onClick={startOauth}>
            Войти через Discord
          </button>
        )}
      </form>
    </div>
  );
}
