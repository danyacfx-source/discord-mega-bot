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

if TYPE_CHECKING:
    from app.config import Config
    from app.db.kv_repository import KvRepository

logger = logging.getLogger("bot.services")

_VK_BASE = "https://vkvideo.ru"
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
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------ стримы

    async def channel_status(self, slug: str) -> dict[str, Any] | None:
        """Статус канала: None — страница недоступна, иначе dict с ``live`` и ``title``."""
        slug = slug.strip().lstrip("@")
        if not slug:
            return None
        url = f"{_VK_BASE}/@{slug}"
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with self.session.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT}) as response:
                if response.status != 200:
                    logger.warning("VK Видео %s: статус %s", slug, response.status)
                    return None
                page = await response.text()
        except aiohttp.ClientError:
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
