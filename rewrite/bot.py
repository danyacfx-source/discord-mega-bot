"""Дискорд-бот без контейнера.

Повторяет прикладную часть ``app.core.bot.MegaBot`` (обработка ошибок команд,
старт вебпанели/оверлея, синк команд), но не строит выражения DI-контейнеров:
коги собираются из ``Root`` в setup_hook через ``rewrite.cogs.build_all_cogs``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.config import Config
from app.core import embeds
from app.core.stream_state import stream_activity

if TYPE_CHECKING:
    from app.db.database import Database
    from app.services import Services
    from rewrite.root import Root

logger = logging.getLogger("bot")

_SUPPORT_HINT = "Если ошибка повторяется — посмотрите логи или обратитесь к поддержке."


class Bot(commands.Bot):
    config: Config
    db: Database | None
    services: Services | None
    root: Root | None

    def __init__(self, config: Config) -> None:
        super().__init__(
            command_prefix=config.prefix,
            intents=discord.Intents.all(),
            help_command=None,
            activity=stream_activity(None),
        )
        self.config = config
        self.db = None
        self.services = None
        self.root = None
        self.start_time = datetime.now(UTC)
        self.tree.on_error = self.on_app_command_error

    @property
    def uptime(self) -> timedelta:
        return datetime.now(UTC) - self.start_time

    async def setup_hook(self) -> None:
        root = self.root
        if root is None:
            # Резервный путь: обычно бот конструируется в rewrite.composition.assemble(),
            # который сразу проставляет root, но оставляем защиту от ручного запуска.
            logger.warning("Bot.setup_hook: root не назначен — коги не загружались")
            await self._sync_commands()
            return

        from app.core.loader import register_persistent_views
        from rewrite.cogs import build_all_cogs

        self.db = root.db
        self.services = root.services
        loaded = await build_all_cogs(root)
        await register_persistent_views(self)
        if self.config.panel_port is not None:
            from app.core.webpanel import WebPanel

            self.webpanel = WebPanel(self)
            await self.webpanel.start()
        if self.config.overlay_port is not None:
            from app.core.overlay import Overlay

            self.overlay = Overlay(self)
            await self.overlay.start()
        await self._sync_commands()
        logger.info("Хук установки завершён: когов %d, views зарегистрированы", len(loaded))

    async def _sync_commands(self) -> None:
        if self.user is None or self.application_id is None:
            logger.debug("Синк команд: application_id ещё не известен — пропуск")
            return
        try:
            synced = await self.tree.sync()
        except (discord.HTTPException, discord.MissingApplicationID, discord.ConnectionClosed) as exc:
            logger.warning("Не удалось синхронизировать команды: %s", exc)
            return
        names = [command.name for command in synced if getattr(command, "name", None)]
        logger.info("Синхронизировано команд: %d (%s)", len(synced), ", ".join(names[:20]))

    async def close(self) -> None:
        webpanel = getattr(self, "webpanel", None)
        if webpanel is not None:
            try:
                await webpanel.stop()
            except Exception:
                logger.exception("Ошибка при остановке вебпанели")
            self.webpanel = None
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            try:
                await overlay.stop()
            except Exception:
                logger.exception("Ошибка при остановке оверлея")
            self.overlay = None
        db = self.db
        try:
            await super().close()
        finally:
            if db is not None:
                try:
                    await db.close()
                except Exception:
                    logger.exception("Ошибка при закрытии БД")
                self.db = None

    async def on_app_command_error(self, interaction: discord.Interaction, error: Exception) -> None:
        original = getattr(error, "original", error)

        if isinstance(original, _BotMissingPermissions):
            embed = embeds.error(
                "Боту не хватает прав",
                "Для этой команды боту нужны права: " + ", ".join(f"`{name}`" for name in original.missing) + ".",
            )
        elif isinstance(original, app_commands.MissingPermissions):
            names = ", ".join(f"`{name}`" for name in original.missing_permissions)
            embed = embeds.error("Недостаточно прав", f"Вам нужны права: {names}.")
        elif isinstance(original, app_commands.NotOwner):
            embed = embeds.error("Только для владельца", "Эта команда доступна владельцу бота.")
        elif isinstance(original, app_commands.CommandOnCooldown):
            embed = embeds.warning("Подождите", f"Команда на перезарядке: {original.retry_after:.1f} сек.")
        elif isinstance(original, discord.Forbidden):
            embed = embeds.error("Боту не хватает прав", "Проверьте права бота и иерархию ролей.")
        elif isinstance(original, discord.HTTPException):
            embed = embeds.error("Ошибка Discord API", str(original))
        elif isinstance(original, discord.NotFound):
            embed = embeds.error("Не найдено", "Объект (сообщение/пользователь/канал) больше не существует.")
        elif isinstance(original, app_commands.TransformerError):
            embed = embeds.error("Неверный аргумент", "Некоторые параметры не распознаны. Проверьте ввод.")
        elif isinstance(original, app_commands.CommandInvokeError):
            logger.exception(
                "Ошибка выполнения команды %s", interaction.command.qualified_name if interaction.command else "?"
            )
            embed = embeds.error("Ошибка выполнения", _SUPPORT_HINT)
        elif isinstance(original, (app_commands.CheckFailure, commands.CommandError)):
            embed = embeds.error("Команда недоступна", str(original) or _SUPPORT_HINT)
        else:
            logger.exception("Необработанная ошибка команды %s", interaction.command.qualified_name if interaction.command else "?")
            embed = embeds.error("Ошибка команды", _SUPPORT_HINT)

        await self._reply_error(interaction, embed)

    @staticmethod
    async def _reply_error(interaction: discord.Interaction, embed: discord.Embed) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException:
            logger.debug("Не удалось отправить сообщение об ошибке", exc_info=True)


class _BotMissingPermissions(app_commands.CheckFailure):
    """Собственная ошибка: у самого бота не хватает прав для команды."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Боту не хватает прав: {', '.join(missing)}")
