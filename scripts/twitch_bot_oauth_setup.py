"""Local OAuth wizard for a dedicated Twitch IRC bot.

Run on the computer with your browser, not your VPS. No third-party token
generators, tokens printed to terminal, or secrets committed to GitHub.
Python stdlib only.
"""
from __future__ import annotations

import getpass
import json
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

REDIRECT_URI = "http://localhost:3000/callback"
AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
SCOPES = ("chat:read", "chat:edit")
OUTPUT_PATH = Path.home() / "dendich_twitch_bot_credentials.env"


def authorization_url(client_id: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "force_verify": "true",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    body = urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    } ).encode()
    request = Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def validate_token(access_token: str) -> dict:
    request = Request(
        VALIDATE_URL,
        headers={"Authorization": f"OAuth {access_token}"},
    )
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def write_credentials(
    path: Path, *, bot_login: str, client_id: str, client_secret: str, refresh_token: str,
) -> None:
    """Create a new private credentials file; never overwrite existing secrets."""
    # Twitch tokens and client credentials should never contain CR, LF or quotes.
    fields = (bot_login, client_id, client_secret, refresh_token)
    if not all(fields) or any(any(char in field for char in "\r\n\"") for field in fields):
        raise ValueError("Invalid credentials")
    content = (
        "# PRIVATE — transfer these values into the SERVER's .env. Never commit or share.\n"
        f"TWITCH_BOT_LOGIN={bot_login}\n"
        f"TWITCH_CLIENT_ID={client_id}\n"
        f"TWITCH_CLIENT_SECRET={client_secret}\n"
        f"TWITCH_BOT_REFRESH_TOKEN={refresh_token}\n"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(content)
    if os.name == "posix":
        os.chmod(path, 0o600)


def await_code(state: str, *, timeout_seconds: int = 240) -> str:
    """Serve only the OAuth redirect callback on loopback; verify CSRF state."""
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            # Never log OAuth authorization code or state from callback URLs.
            return

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            params = parse_qs(parsed.query)
            if params.get("state", [""])[0] != state:
                self.send_error(403, "Authorization session mismatch")
                return
            if "error" in params:
                result["error"] = "Twitch authorization was declined or failed"
            else:
                result["code"] = params.get("code", [""])[0]

            body = (
                "<!doctype html><html lang='ru'><meta charset='utf-8'>"
                "<title>DENDICH Twitch</title>"
                "<body style='background:#121713;color:#ddc9a6;font:20px sans-serif;"
                "padding:4rem'>Авторизация обработана. Вернись в терминал.</body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        server = HTTPServer(("127.0.0.1", 3000), Handler)
    except OSError as exc:
        raise RuntimeError(
            "Cannot start localhost:3000. Stop any program using port 3000 and retry."
        ) from exc
    server.timeout = 3
    try:
        end = time.monotonic() + timeout_seconds
        while time.monotonic() < end and not result:
            server.handle_request()
    finally:
        server.server_close()

    if result.get("error"):
        raise RuntimeError(result["error"])
    if not result.get("code"):
        raise RuntimeError("Timed out waiting for OAuth redirect")
    return result["code"]


def main() -> None:
    print("=== DENDICH / RADIO SILENCE — Twitch bot authorization ===")
    print("Use the TWITCH BOT account for Twitch authorization, not your streamer account.")
    print("In your Twitch Developer app register this exact OAuth Redirect URL:")
    print("  " + REDIRECT_URI)
    print("Your tokens will be saved locally, NOT displayed or sent to ChatGPT.")
    client_id = input("\nTwitch application Client ID: ").strip()
    client_secret = getpass.getpass("Twitch application Client Secret (hidden): ").strip()
    expected_login = input("Twitch BOT account login (not channel): ").strip().lower().lstrip("@")
    if not (client_id and client_secret and expected_login):
        raise RuntimeError("Client ID, Client Secret and bot login are all required")
    state = secrets.token_urlsafe(32)
    url = authorization_url(client_id, state)
    print("\nOpening Twitch's official authorization page in your browser.")
    print("Switch your browser to the BOT account before approving.")
    print("If your browser does not open, use this OAuth link privately:")
    print(url)
    webbrowser.open(url)
    code = await_code(state)
    print("Exchanging authorization code with Twitch...")
    credentials = exchange_code(client_id, client_secret, code)
    identity = validate_token(str(credentials["access_token"]))
    login = str(identity.get("login") or "").lower()
    scopes = set(identity.get("scopes") or [])
    if login != expected_login:
        raise RuntimeError(
            "Wrong Twitch account authorized. Log into the BOT account and retry."
        )
    if not set(SCOPES).issubset(scopes) or identity.get("client_id") != client_id:
        raise RuntimeError("Twitch token missing chat scopes or Client ID mismatch")
    refresh = str(credentials.get("refresh_token") or "")
    if not refresh:
        raise RuntimeError("Twitch returned no refresh token; use Authorization Code flow")
    write_credentials(
        OUTPUT_PATH, bot_login=login, client_id=client_id,
        client_secret=client_secret, refresh_token=refresh,
    )
    print("\nSUCCESS: Twitch bot authorized as @" + login)
    print("Local private config saved to: " + str(OUTPUT_PATH))
    print("Copy these values securely into your SERVER .env, then restart the bot.")
    print("Do NOT share the file, screenshot it, or commit it to GitHub.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, HTTPError, URLError, FileExistsError) as exc:
        # Do not dump HTTP response bodies or credentials into exception logs.
        if isinstance(exc, (HTTPError, URLError)):
            print("Twitch connection/authentication failed; check app settings and retry.")
        elif isinstance(exc, FileExistsError):
            print("Credentials file already exists: " + str(OUTPUT_PATH))
            print("Move the old file somewhere safe before attempting authorization again.")
        else:
            print("ERROR: " + str(exc))
        raise SystemExit(1) from None
