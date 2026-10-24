"""Safety and URL details of the local OAuth setup helper."""
from __future__ import annotations

import importlib.util
from pathlib import Path
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
