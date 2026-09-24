"""Сервис VK Видео: статус LIVE-трансляции по открытой странице канала.

Парсится только общедоступный HTML: ``<title>`` и мета-теги ``og:title`` /
``og:description``. Никаких токенов, приватных API и чата — как в KickService.
"""
from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp

from app.core.api_client import ApiClient, ApiRequestError

if TYPE_CHECKING:
    from app.config import Config
    from app.db.kv_repository import KvRepository

logger = logging.getLogger("bot.services")

_VK_BASE = "https://vkvideo.ru"
_LIVE_BASE = "https://live.vkvideo.ru"
_USER_AGENT = "Mozilla/5.0 (compatible; MegaBot/1.0; +https://vkvideo.ru)"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r'([a-zA-Z:_-]+)\s*=\s*["\'](.*?)["\']', re.DOTALL)
_LIVE_RE = re.compile(r"прямой\s+эфир|прямая\s+трансляция|\blive\b", re.IGNORECASE)


def _clean(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _meta(page: str, prop: str) -> str | None:
    """Достаёт ``content`` мета-тега с ``property``/``name`` равным ``prop``."""
    for tag in _META_TAG_RE.findall(page):
        attrs = {key.lower(): value for key, value in _ATTR_RE.findall(tag)}
        key = attrs.get("property") or attrs.get("name")
        if key and key.lower() == prop.lower():
            return attrs.get("content")
    return None


class VkVideoService:
    def __init__(self, repo: KvRepository, config: Config) -> None:
        self._repo = repo
        self._config = config
        self._http = ApiClient(
            "VK Видео",
            timeout=config.api_timeout_seconds,
            user_agent=_USER_AGENT,
            proxy=config.api_proxy,
            max_concurrency=config.api_max_concurrency,
            circuit_failure_threshold=config.api_circuit_failure_threshold,
            circuit_reset_seconds=config.api_circuit_reset_seconds,
        )

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._http.session

    async def aclose(self) -> None:
        await self._http.close()

    # ------------------------------------------------------------------ стримы

    async def channel_status(self, slug: str) -> dict[str, Any] | None:
        """Статус канала: None — страница недоступна, иначе dict с ``live`` и ``title``."""
        slug = slug.strip().lstrip("@")
        if not slug:
            return None
        # LIVE-стенд: live.vkvideo.ru/<slug> (устаревший vkvideo.ru/@<slug> — обзорная карточка)
        candidates = (
            f"{_LIVE_BASE}/{slug}",  # актуальный LIVE-хост из url пользователя
            f"{_VK_BASE}/@{slug}",   # фолбэк: старый формат
        )
        for url in candidates:
            data = await self._channel_status_url(url, slug)
            if data is not None:
                return data
        return None

    async def _channel_status_url(self, url: str, slug: str) -> dict[str, Any] | None:
        try:
            status, page, _ = await self._http.text(
                "GET", url, attempts=2, acceptable=(200, 404), headers={"User-Agent": _USER_AGENT}
            )
            if status == 404:
                return None
        except ApiRequestError:
            logger.exception("VK Видео: сеть при статусе канала %s", slug)
            return None

        title_match = _TITLE_RE.search(page)
        title = _clean(_meta(page, "og:title")) or _clean(title_match.group(1) if title_match else None) or slug
        description = _clean(_meta(page, "og:description"))
        live = bool(_LIVE_RE.search(f"{title} {description}"))
        return {
            "slug": slug,
            "title": title,
            "description": description,
            "live": live,
            "url": url,
        }

    # ------------------------------------------------------------------ sticky

    @staticmethod
    def _sticky_key() -> str:
        return "vk_video:sticky"

    async def sticky_message_id(self) -> int | None:
        raw = await self._repo.get(self._sticky_key())
        return int(raw) if raw and raw.isdigit() else None

    async def set_sticky_message(self, message_id: int) -> None:
        await self._repo.set(self._sticky_key(), str(message_id))

    async def clear_sticky_message(self) -> None:
        await self._repo.delete(self._sticky_key())
