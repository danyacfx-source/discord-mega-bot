"""Резолвер треков Яндекс Музыки (только по ссылкам music.yandex.*).

Для прямых ссылок на воспроизведение нужен токен аккаунта с Яндекс Плюс
(``YANDEX_MUSIC_TOKEN``) — библиотека ``yandex-music`` отдаёт direct-ссылки
только для премиум-доступа.
"""
from __future__ import annotations

import asyncio
import logging
import re

from app.services.audio.resolver import TrackNotFoundError
from app.services.audio.track import Track

logger = logging.getLogger("bot.audio")

_YANDEX_HOST_RE = re.compile(r"music\.yandex\.\w+")
_TRACK_SEGMENT_RE = re.compile(r"/track/(\d+)")
_COVER_SIZE = "400x400"


def parse_yandex_track_id(query: str) -> int | None:
    """Извлекает id трека из ссылки music.yandex.*/…/track/<id> (иначе None).

    Берётся последний сегмент ``/track/<id>`` — путь трека всегда оканчивается им.
    """
    if not _YANDEX_HOST_RE.search(query):
        return None
    matches = _TRACK_SEGMENT_RE.findall(query)
    if not matches:
        return None
    return int(matches[-1])


class YandexMusicResolver:
    def __init__(self, token: str) -> None:
        self._token = token
        self._client = None

    def _get_client(self):
        if self._client is None:
            from yandex_music import Client

            self._client = Client(token=self._token).init()
        return self._client

    async def resolve(self, url: str, track_id: int) -> Track:
        try:
            return await asyncio.to_thread(self._resolve_sync, url, track_id)
        except TrackNotFoundError:
            raise
        except ImportError:
            raise TrackNotFoundError(
                "Не установлена библиотека yandex-music (см. requirements.txt)."
            ) from None
        except Exception as exc:
            logger.exception("Яндекс Музыка: ошибка резолва трека %s", track_id)
            raise TrackNotFoundError(f"Яндекс Музыка: {exc}") from exc

    def _resolve_sync(self, url: str, track_id: int) -> Track:
        client = self._get_client()
        tracks = client.tracks([track_id])
        if not tracks or tracks[0] is None:
            raise TrackNotFoundError("Яндекс Музыка: трек не найден")
        track = tracks[0]

        uploader = ""
        try:
            uploader = track.artists_name or ""
        except Exception:
            uploader = ""

        duration = None
        if getattr(track, "duration_ms", None):
            duration = int(track.duration_ms) // 1000

        cover = None
        cover_uri = getattr(track, "cover_uri", None)
        if cover_uri and cover_uri.endswith("/$"):
            cover = "https://" + cover_uri[:-1] + _COVER_SIZE

        stream_url = self._pick_stream(track, url)

        return Track(
            title=track.title or "Неизвестный трек",
            url=url,
            stream_url=stream_url,
            duration=duration,
            uploader=uploader,
            thumbnail=cover,
        )

    @staticmethod
    def _pick_stream(track, url: str) -> str:
        infos = track.get_download_info(get_direct_links=True) or []
        for info in reversed(infos):
            direct = getattr(info, "direct_link", None) or getattr(info, "direct", None)
            if not direct:
                try:
                    direct = info.get_direct_link()
                except Exception:
                    direct = None
            if direct:
                return str(direct)
        raise TrackNotFoundError(
            "Яндекс Музыка: нет прямой ссылки для воспроизведения — "
            f"{url} требует токен аккаунта с Яндекс Плюс (YANDEX_MUSIC_TOKEN)."
        )


__all__ = ["YandexMusicResolver", "parse_yandex_track_id"]
