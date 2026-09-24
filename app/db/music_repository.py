"""Хранилище пользовательских музыкальных плейлистов."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db.base_repository import BaseRepository
from app.services.audio.track import Track


class MusicRepository(BaseRepository):
    @staticmethod
    def _track_params(guild_id: int, position: int, track: Track) -> tuple[Any, ...]:
        return (
            guild_id,
            position,
            track.title[:256],
            track.url[:2048],
            track.stream_url[:4096],
            track.duration,
            (track.uploader or "")[:256],
            (track.thumbnail or "")[:2048],
        )

    async def save_playlist(self, guild_id: int, name: str, author_id: int, tracks: list[Track]) -> None:
        normalized = name.strip().lower()[:64]
        if not normalized:
            raise ValueError("Название плейлиста не может быть пустым")
        await self.db.execute(
            """
            INSERT INTO music_playlists(guild_id, name, created_by, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, name) DO UPDATE SET
                created_by = excluded.created_by,
                created_at = excluded.created_at
            """,
            (guild_id, normalized, author_id, datetime.now(UTC).isoformat()),
        )
        await self.db.execute(
            "DELETE FROM music_playlist_tracks WHERE guild_id = ? AND playlist_name = ?",
            (guild_id, normalized),
        )
        for position, track in enumerate(tracks[:100], start=1):
            await self.db.execute(
                """
                INSERT INTO music_playlist_tracks
                    (guild_id, playlist_name, position, title, url, stream_url, duration, uploader, thumbnail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    normalized,
                    position,
                    track.title[:256],
                    track.url[:2048],
                    track.stream_url[:4096],
                    track.duration,
                    (track.uploader or "")[:256],
                    (track.thumbnail or "")[:2048],
                ),
            )

    async def list_playlists(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT p.name, p.created_by, p.created_at, COUNT(t.position) AS tracks
            FROM music_playlists p
            LEFT JOIN music_playlist_tracks t
              ON t.guild_id = p.guild_id AND t.playlist_name = p.name
            WHERE p.guild_id = ?
            GROUP BY p.guild_id, p.name
            ORDER BY p.name
            """,
            (guild_id,),
        )
        return [dict(row) for row in rows]

    async def get_playlist(self, guild_id: int, name: str) -> list[Track]:
        rows = await self.db.fetchall(
            """
            SELECT title, url, stream_url, duration, uploader, thumbnail
            FROM music_playlist_tracks
            WHERE guild_id = ? AND playlist_name = ?
            ORDER BY position
            """,
            (guild_id, name.strip().lower()[:64]),
        )
        return [
            Track(
                title=str(row["title"]),
                url=str(row["url"]),
                stream_url=str(row["stream_url"] or ""),
                duration=int(row["duration"]) if row["duration"] is not None else None,
                uploader=str(row["uploader"] or "") or None,
                thumbnail=str(row["thumbnail"] or "") or None,
            )
            for row in rows
        ]

    async def delete_playlist(self, guild_id: int, name: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM music_playlists WHERE guild_id = ? AND name = ?",
            (guild_id, name.strip().lower()[:64]),
        )
        return cursor.rowcount > 0

    async def save_queue(self, guild_id: int, tracks: list[Track]) -> None:
        await self.db.execute("DELETE FROM music_queue WHERE guild_id = ?", (guild_id,))
        for position, track in enumerate(tracks[:100], start=1):
            await self.db.execute(
                """
                INSERT INTO music_queue
                    (guild_id, position, title, url, stream_url, duration, uploader, thumbnail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._track_params(guild_id, position, track),
            )

    async def load_queue(self, guild_id: int) -> list[Track]:
        rows = await self.db.fetchall(
            """
            SELECT title, url, stream_url, duration, uploader, thumbnail
            FROM music_queue WHERE guild_id = ? ORDER BY position
            """,
            (guild_id,),
        )
        return [
            Track(
                title=str(row["title"]),
                url=str(row["url"]),
                stream_url=str(row["stream_url"] or ""),
                duration=int(row["duration"]) if row["duration"] is not None else None,
                uploader=str(row["uploader"] or "") or None,
                thumbnail=str(row["thumbnail"] or "") or None,
            )
            for row in rows
        ]

    async def record_history(self, guild_id: int, user_id: int, track: Track) -> None:
        await self.db.execute(
            """
            INSERT INTO music_history(guild_id, user_id, title, url, duration, played_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (guild_id, user_id, track.title[:256], track.url[:2048], track.duration),
        )
        await self.db.execute(
            """
            DELETE FROM music_history
            WHERE guild_id = ? AND id NOT IN (
                SELECT id FROM music_history WHERE guild_id = ? ORDER BY played_at DESC LIMIT 500
            )
            """,
            (guild_id, guild_id),
        )

    async def history(self, guild_id: int, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT title, url, duration, user_id, played_at
            FROM music_history
            WHERE guild_id = ?
            ORDER BY played_at DESC, id DESC
            LIMIT ?
            """,
            (guild_id, max(1, min(limit, 100))),
        )
        return [dict(row) for row in rows]
