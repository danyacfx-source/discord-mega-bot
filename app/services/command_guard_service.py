"""Глобальный guard: скользящий лимит инвоков команд и kill-switch.

Отвечает на единственный вопрос «можно ли прямо сейчас выполнить эту команду».
Проверка синхронная и без I/O — её дергает ``CommandTree.interaction_check``
на каждой интеракции, поэтому состояние живёт в памяти, а в KV переживают
только флаги (пауза, блокировки, муты), которые должны пережить рестарт.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Config
    from app.services.kv_service import KvService

logger = logging.getLogger("bot.guard")

_PAUSE_KEY = "guard:paused"
_BLOCKED_KEY = "guard:blocked"
_MUTED_KEY = "guard:muted_guilds"
_GC_EVERY = 512


@dataclass(slots=True, frozen=True)
class GuardVerdict:
    """Вердикт по одной интеракции."""

    allowed: bool
    reason: str = ""
    retry_after: float = 0.0


class CommandGuardService:
    """Rate-limit и kill-switch для slash- и префикс-команд."""

    def __init__(self, config: Config, kv: KvService) -> None:
        self._config = config
        self._kv = kv
        self._user_hits: dict[int, deque[float]] = defaultdict(deque)
        self._guild_hits: dict[int, deque[float]] = defaultdict(deque)
        self._paused = False
        self._blocked: set[str] = set()
        self._muted_guilds: set[int] = set()
        self._loaded = False
        self._checks = 0
        self.blocked_total = 0
        self.last_reason: str = ""
        self.last_blocked_at: float | None = None

    # --- состояние ---

    async def load(self) -> None:
        """Гидратирует kill-switch из KV. Сбой KV не оставляет guard молча выключенным."""
        if self._loaded:
            return
        self._loaded = True
        try:
            paused = await self._kv.get(_PAUSE_KEY)
            blocked = await self._kv.get(_BLOCKED_KEY)
            muted = await self._kv.get(_MUTED_KEY)
        except Exception:
            logger.exception("Guard: KV недоступен, работаем с настройками из окружения")
            return
        self._paused = str(paused) == "1"
        self._blocked = {name.strip().lower() for name in (blocked or "").split(",") if name.strip()}
        self._muted_guilds = {
            int(guild_id) for guild_id in (muted or "").split(",") if guild_id.strip().isdigit()
        }
        if self._paused or self._blocked or self._muted_guilds:
            logger.warning(
                "Guard: поднято сохранённое состояние — пауза=%s, команд отключено=%d, серверов в муте=%d",
                self._paused,
                len(self._blocked),
                len(self._muted_guilds),
            )

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def loaded(self) -> bool:
        return self._loaded

    # --- проверка ---

    def check(
        self,
        user_id: int | None,
        guild_id: int | None,
        command: str,
        *,
        bypass: bool = False,
    ) -> GuardVerdict:
        """Возвращает вердикт по интеракции. Без I/O, безопасно на каждом вызове."""
        self._checks += 1
        if self._checks % _GC_EVERY == 0:
            self._prune()
        if not self._config.guard_enabled:
            return GuardVerdict(True)
        if bypass:
            return GuardVerdict(True)

        name = (command or "").strip().lower()
        if name and name in self._blocked:
            return self._deny(f"Команда `/{name}` отключена оператором.")
        if self._paused:
            return self._deny("Бот переведён в режим обслуживания. Команды временно приостановлены.")
        if guild_id is not None and guild_id in self._muted_guilds:
            return self._deny("Команды на этом сервере отключены guard-ом.")

        now = time.monotonic()
        if guild_id is not None:
            verdict = self._window(
                self._guild_hits[guild_id],
                self._config.guard_guild_max,
                self._config.guard_guild_window,
                now,
                "На сервере слишком много команд подряд",
            )
            if verdict is not None:
                return self._record(verdict)
        if user_id is not None:
            verdict = self._window(
                self._user_hits[user_id],
                self._config.guard_user_max,
                self._config.guard_user_window,
                now,
                "Слишком много команд подряд",
            )
            if verdict is not None:
                return self._record(verdict)
        return GuardVerdict(True)

    @staticmethod
    def _window(
        bucket: deque[float],
        limit: int,
        window: float,
        now: float,
        message: str,
    ) -> GuardVerdict | None:
        """Один скользящий бакет: пропускает и записывает либо отвечает с паузой."""
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(0.05, bucket[0] + window - now)
            return GuardVerdict(False, f"{message}.", round(retry_after, 1))
        bucket.append(now)
        return None

    def _deny(self, reason: str) -> GuardVerdict:
        return self._record(GuardVerdict(False, reason))

    def _record(self, verdict: GuardVerdict) -> GuardVerdict:
        """Считает отказ и запоминает последнюю причину (для /guard status)."""
        self.blocked_total += 1
        self.last_reason = verdict.reason
        logger.warning("Guard: %s", verdict.reason)
        return verdict

    def _prune(self) -> None:
        """Сбрасывает опустевшие бакеты, чтобы словари не росли бесконечно."""
        now = time.monotonic()
        for store, window in (
            (self._user_hits, self._config.guard_user_window),
            (self._guild_hits, self._config.guard_guild_window),
        ):
            empty = [
                key
                for key, bucket in store.items()
                if not bucket or bucket[-1] <= now - window
            ]
            for key in empty:
                store.pop(key, None)

    # --- kill-switch (переживает рестарт через KV) ---

    async def set_paused(self, paused: bool) -> None:
        self._paused = paused
        await self._persist(_PAUSE_KEY, "1" if paused else None)
        logger.warning("Guard: режим обслуживания %s", "включён" if paused else "снят")

    async def block_command(self, command: str) -> bool:
        name = (command or "").strip().lower()
        if not name or name in self._blocked:
            return False
        self._blocked.add(name)
        await self._persist(_BLOCKED_KEY, ",".join(sorted(self._blocked)))
        logger.warning("Guard: команда /%s отключена", name)
        return True

    async def unblock_command(self, command: str) -> bool:
        name = (command or "").strip().lower()
        if name not in self._blocked:
            return False
        self._blocked.discard(name)
        await self._persist(_BLOCKED_KEY, ",".join(sorted(self._blocked)) or None)
        logger.warning("Guard: команда /%s включена обратно", name)
        return True

    async def mute_guild(self, guild_id: int) -> bool:
        if guild_id in self._muted_guilds:
            return False
        self._muted_guilds.add(guild_id)
        await self._persist(_MUTED_KEY, ",".join(str(g) for g in sorted(self._muted_guilds)))
        logger.warning("Guard: сервер %s переведён в мут", guild_id)
        return True

    async def unmute_guild(self, guild_id: int) -> bool:
        if guild_id not in self._muted_guilds:
            return False
        self._muted_guilds.discard(guild_id)
        await self._persist(_MUTED_KEY, ",".join(str(g) for g in sorted(self._muted_guilds)) or None)
        logger.warning("Guard: мут сервера %s снят", guild_id)
        return True

    async def _persist(self, key: str, value: str | None) -> None:
        """Сохраняет флаг; падение KV не откатывает уже принятое состояние."""
        try:
            if value is None:
                await self._kv.delete(key)
            else:
                await self._kv.set(key, value)
        except Exception:
            logger.exception("Guard: не удалось сохранить %s в KV", key)

    # --- отчётность ---

    @property
    def blocked_commands(self) -> tuple[str, ...]:
        return tuple(sorted(self._blocked))

    @property
    def muted_guilds(self) -> tuple[int, ...]:
        return tuple(sorted(self._muted_guilds))

    def snapshot(self) -> dict[str, Any]:
        cfg = self._config
        return {
            "enabled": cfg.guard_enabled,
            "paused": self._paused,
            "loaded": self._loaded,
            "blocked_commands": list(self.blocked_commands),
            "muted_guilds": list(self.muted_guilds),
            "blocked_total": self.blocked_total,
            "last_reason": self.last_reason,
            "checks": self._checks,
            "tracked_users": len(self._user_hits),
            "tracked_guilds": len(self._guild_hits),
            "limits": {
                "user_max": cfg.guard_user_max,
                "user_window": cfg.guard_user_window,
                "guild_max": cfg.guard_guild_max,
                "guild_window": cfg.guard_guild_window,
                "bypass_admin": cfg.guard_bypass_admin,
            },
        }

    def reset(self) -> None:
        """Чистит окна (нужно тестам и ручному сбросу после инцидента)."""
        self._user_hits.clear()
        self._guild_hits.clear()
        self.blocked_total = 0
        self.last_reason = ""
