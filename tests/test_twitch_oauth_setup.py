"""Safety and URL details of the local OAuth setup helper."""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.fixture
def wizard():
    path = Path(__file__).resolve().parents[1] / "scripts" / "twitch_bot_oauth_setup.py"
    spec = importlib.util.spec_from_file_location("twitch_setup", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authorize_link_has_correct_callback_and_scopes(wizard) -> None:
    url = wizard.authorization_url("my-app", "anti-csrf-state")
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "id.twitch.tv"
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["http://localhost:3000/callback"]
    assert set(query["scope"][0].split(" ")) == {"chat:read", "chat:edit"}
    assert query["state"] == ["anti-csrf-state"]


def test_credentials_private_and_no_overwrite(tmp_path, wizard) -> None:
    path = tmp_path / "local.env"
    wizard.write_credentials(
        path, bot_login="radiobot", client_id="abc",
        client_secret="private", refresh_token="rotating",
    )
    text = path.read_text()
    assert "TWITCH_BOT_LOGIN=radiobot" in text
    assert "TWITCH_BOT_REFRESH_TOKEN=rotating" in text
    with pytest.raises(FileExistsError):
        wizard.write_credentials(
            path, bot_login="bad", client_id="abc",
            client_secret="bad", refresh_token="bad",
        )
    assert path.read_text() == text


def test_disallow_injected_line_breaks(wizard, tmp_path) -> None:
    with pytest.raises(ValueError):
        wizard.write_credentials(
            tmp_path / "secrets.env", bot_login="radiobot\nINJECTED=value",
            client_id="abc", client_secret="private", refresh_token="safe",
        )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b'{"status":400,"message":"Invalid client secret"}', "Client Secret"),
        (b'{"status":400,"message":"Invalid authorization code"}', "single-use"),
        (b'{"status":400,"message":"Invalid redirect URI"}', "http://localhost"),
        (b'{"status":400,"message":"Unexpected value"}', "Check Client ID"),
        (b'not JSON', "Check Client ID"),
    ],
)
def test_diagnostics_are_safe_and_actionable(wizard, body, expected) -> None:
    error = HTTPError(
        "https://id.twitch.tv/oauth2/token",
        400,
        "bad request",
        None,
        io.BytesIO(body),
    )
    diagnosis = wizard.describe_twitch_http_error(error)
    assert diagnosis.startswith("Twitch OAuth HTTP 400.")
    assert expected in diagnosis
    assert "Unexpected value" not in diagnosis


def test_http_diagnostics_never_echo_tokens(wizard) -> None:
    private_token = "ultraprivatesecrettoken9381"
    body = ('{"status":400,"message":"Unknown token ' + private_token + '"}').encode()
    error = HTTPError("https://id.twitch.tv/oauth2/token", 400, "bad", None, io.BytesIO(body))
    assert private_token not in wizard.describe_twitch_http_error(error)
