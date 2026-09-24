"""Регрессионные тесты управления музыкальной очередью."""

from unittest.mock import MagicMock

from app.db.database import Database
from app.db.music_repository import MusicRepository
from app.services.audio.player import GuildPlayer
from app.services.audio.track import Track


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
