"""Регрессионные тесты управления музыкальной очередью."""

from unittest.mock import MagicMock

import discord
import pytest

from app.db.database import Database
from app.db.music_repository import MusicRepository
from app.services.audio.player import GuildPlayer
from app.services.audio.track import Track
from app.services.music_service import MusicService


@pytest.fixture
def patched_ffmpeg(monkeypatch):
    monkeypatch.setattr(discord, "FFmpegPCMAudio", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(discord, "PCMVolumeTransformer", MagicMock(return_value=MagicMock()))


def _make_voice(*, playing: bool = False, paused: bool = False) -> MagicMock:
    voice = MagicMock()
    voice.is_connected.return_value = True
    voice.is_playing.return_value = playing
    voice.is_paused.return_value = paused
    return voice


async def test_stale_finish_callback_is_ignored(patched_ffmpeg) -> None:
    player = GuildPlayer(MagicMock(), guild_id=1)
    voice = _make_voice()
    player.voice = voice
    track = Track(title="A", url="", stream_url="stream")
    player.queue.append(Track(title="B", url="", stream_url="stream"))
    await player.play(track)

    player._on_finished(None, player._gen - 1)

    assert player.current is track
    assert player._ended is False
    assert len(player.queue) == 1
    assert voice.play.call_count == 1


async def test_skip_advances_exactly_once(patched_ffmpeg) -> None:
    player = GuildPlayer(MagicMock(), guild_id=1)
    voice = _make_voice()
    player.voice = voice
    tracks = [Track(title=name, url="", stream_url="stream") for name in ("A", "B", "C")]
    for track in tracks:
        player.queue.append(track)
    await player.play_next()

    old_after = voice.play.call_args_list[0].kwargs["after"]

    def stop_triggers_old_callback() -> None:
        old_after(None)

    voice.stop.side_effect = stop_triggers_old_callback

    skipped = await player.skip()

    assert skipped is tracks[0]
    assert player.current is tracks[1]
    assert list(player.queue) == [tracks[2]]


async def test_skip_while_advance_pending_advances_once(patched_ffmpeg) -> None:
    player = GuildPlayer(MagicMock(), guild_id=1)
    voice = _make_voice()
    player.voice = voice
    tracks = [Track(title=name, url="", stream_url="stream") for name in ("A", "B", "C")]
    for track in tracks:
        player.queue.append(track)
    await player.play_next()
    player._ended = True

    skipped = await player.skip()

    assert skipped is tracks[0]
    assert list(player.queue) == [tracks[1], tracks[2]]

    await player._after_source(player._gen)

    assert player.current is tracks[1]
    assert list(player.queue) == [tracks[2]]


async def test_start_stops_paused_source_before_new_play(patched_ffmpeg) -> None:
    player = GuildPlayer(MagicMock(), guild_id=1)
    voice = _make_voice(paused=True)
    player.voice = voice

    await player.play(Track(title="A", url="", stream_url="stream"))

    voice.stop.assert_called_once()
    voice.play.assert_called_once()


async def test_service_releases_player_on_disconnect() -> None:
    service = MusicService(MagicMock())
    player = service.get_player(1)
    assert service.peek(1) is player

    await player.disconnect()

    assert service.peek(1) is None


async def test_service_handle_bot_disconnected_drops_player() -> None:
    service = MusicService(MagicMock())
    player = service.get_player(2)
    player.voice = _make_voice()
    player.queue.append(Track(title="A", url="", stream_url="stream"))

    await service.handle_bot_disconnected(2)

    assert service.peek(2) is None
    assert player.voice is None


async def test_music_queue_tools_are_safe() -> None:
    player = GuildPlayer(MagicMock(), guild_id=1)
    tracks = [Track(title=f"Track {index}", url="", stream_url="") for index in range(3)]
    for track in tracks:
        player.enqueue(track)

    removed = player.remove(2)
    assert removed is tracks[1]
    assert player.remove(99) is None
    assert list(player.queue) == [tracks[0], tracks[2]]

    player.enqueue(tracks[1])
    player.shuffle()
    assert {track.title for track in player.queue} == {track.title for track in tracks}
    assert player.pause() is False
    assert player.resume() is False


async def test_music_playlists_round_trip(tmp_path) -> None:
    database = Database(str(tmp_path / "music.db"))
    await database.connect()
    try:
        repo = MusicRepository(database)
        tracks = [
            Track(title="Песня", url="https://example.test/song", stream_url="stream", duration=42, uploader="artist")
        ]
        await repo.save_playlist(1, "Избранное", 7, tracks)
        rows = await repo.list_playlists(1)
        assert rows[0]["name"] == "избранное"
        assert rows[0]["tracks"] == 1
        loaded = await repo.get_playlist(1, "Избранное")
        assert loaded[0].title == "Песня" and loaded[0].duration == 42
        await repo.save_queue(1, tracks)
        restored = await repo.load_queue(1)
        assert restored[0].url == tracks[0].url
        await repo.record_history(1, 7, tracks[0])
        assert (await repo.history(1))[0]["title"] == "Песня"
        assert await repo.delete_playlist(1, "ИЗБРАННОЕ") is True
        assert await repo.list_playlists(1) == []
    finally:
        await database.close()
