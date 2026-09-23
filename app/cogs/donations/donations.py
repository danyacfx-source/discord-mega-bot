"""Донаты DonationAlerts: поллинг, персональный код, роль «Спонсор» по порогу суммы, спонсор-кнопка."""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import tasks

from app.core import embeds
from app.core.base import MegaCog
from app.services.donation_service import DonationService

if TYPE_CHECKING:
    from app.config import Config
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

_SPONSOR_TITLE = "⭐ Поддержать стрим"


class DonateButtonView(discord.ui.View):
    """Кнопка «Задонатить» из статичного спонсор-сообщения."""

    def __init__(self, donations: DonationService) -> None:
        super().__init__(timeout=None)
        self.donations = donations

    @discord.ui.button(label="Задонатить", style=discord.ButtonStyle.success, custom_id="donate:btn", emoji="🎁")
    async def on_donate(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        bot: MegaBot = interaction.client
        config: Config = bot.config
        if not config.donations_token:
            await interaction.response.send_message(
                "Связь с DonationAlerts ещё не настроена — попроси администратора добавить токен.",
                ephemeral=True,
            )
            return
        code = await self.donations.create_code(
            interaction.user.id,
            interaction.guild_id or 0,
            config.donation_role_name,
            config.donation_role_id,
        )
        url = config.donate_url
        embed = embeds.info(
            "Донат и роль",
            f"Твой персональный код: **`{code}`**\n\n"
            f"1. Нажми кнопку ниже.\n"
            f"2. В поле сообщения доната напиши код **`{code}`**.\n"
            f"3. После оплаты роль **«{config.donation_role_name}»** выдастся автоматически."
            + (f"\n\nМинимальная сумма для роли: **{config.donation_min_amount:g} ₽**" if config.donation_min_amount > 0 else ""),
        )
        view = discord.ui.View(timeout=None)
        if url:
            view.add_item(discord.ui.Button(label="Открыть страницу доната", style=discord.ButtonStyle.link, url=url))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class DonationsCog(MegaCog, name="Donations"):
    def __init__(self, bot: MegaBot, donations: DonationService) -> None:
        super().__init__(bot)
        self.donations = donations
        self._base_seconds = 15.0
        self._failures = 0
        self._failure_started_at: float | None = None
        self._last_warning_at = 0.0

    async def cog_load(self) -> None:
        config = self.bot.config
        self._base_seconds = max(5.0, config.donation_poll_seconds)
        if config.donations_token:
            self.donation_loop.change_interval(seconds=self._base_seconds)
            self.donation_loop.start()
        if config.donate_button_channel_id:
            self.bot.add_view(DonateButtonView(self.donations))
            self.bot.add_listener(self._on_ready_sponsor, "on_ready")

    async def cog_unload(self) -> None:
        self.donation_loop.cancel()
        self.bot.remove_listener(self._on_ready_sponsor, "on_ready")
        await self.donations.aclose()

    async def _on_ready_sponsor(self) -> None:
        if self.bot.is_ready():
            await self._ensure_sponsor_message()

    def _schedule(self) -> None:
        if self._failures:
            seconds = min(self._base_seconds * (2 ** min(self._failures, 5)), 300.0)
        else:
            seconds = self._base_seconds
        self.donation_loop.change_interval(seconds=seconds)

    @tasks.loop(seconds=15.0)
    async def donation_loop(self) -> None:
        try:
            new_donations = await self.donations.process_new(limit=50)
        except RuntimeError as exc:
            now = time.monotonic()
            self._failures += 1
            if self._failure_started_at is None:
                self._failure_started_at = now
            pause = min(self._base_seconds * (2 ** min(self._failures, 5)), 300.0)
            # 429/5xx и сетевые таймауты внешнего API — штатная деградация,
            # а не ошибка самого бота. Не засоряем ERROR и веб-ленту логов.
            if not self._last_warning_at or now - self._last_warning_at >= 900:
                logger.warning(
                    "DonationAlerts временно недоступен: %s — повтор через %.0fс",
                    exc,
                    pause,
                )
                self._last_warning_at = now
            else:
                logger.debug(
                    "DonationAlerts всё ещё недоступен (попытка %d): %s — повтор через %.0fс",
                    self._failures,
                    exc,
                    pause,
                )
            self._schedule()
            return
        except Exception:
            self._failures += 1
            logger.exception("DonationAlerts: ошибка поллинга (попытка %d)", self._failures)
            self._schedule()
            return
        failures = self._failures
        outage_started = self._failure_started_at
        self._failures = 0
        self._failure_started_at = None
        self._schedule()
        if failures >= 2 and outage_started is not None:
            logger.info(
                "DonationAlerts снова доступен после %.0fс и %d неудачных попыток",
                time.monotonic() - outage_started,
                failures,
            )
        for donation in new_donations:
            try:
                await self._handle(donation)
            except Exception:
                logger.exception("Donations: ошибка обработки доната")

    async def _handle(self, donation: dict[str, Any]) -> None:
        config = self.bot.config
        code = donation.get("code") or ""
        link = await self.donations.lookup_code(code) if code else None
        rewarded = False
        if link is not None:
            if donation["amount"] < config.donation_min_amount:
                await self.donations.delete_code(code)
                await self._dm(
                    link["user_id"],
                    f"Принят донат {donation['amount']:g} ₽, но порог для роли «{link['role'] or config.donation_role_name}» — "
                    f"{config.donation_min_amount:g} ₽. Роль не выдана.",
                )
            else:
                rewarded = await self._grant(link, code, donation)
        await self._notify(donation, rewarded, guild_id=link["guild_id"] if link else None)

    async def _grant(self, link: dict[str, Any], code: str, donation: dict[str, Any]) -> bool:
        config = self.bot.config
        guild = self.bot.get_guild(link["guild_id"]) if link["guild_id"] else (self.bot.guilds[0] if self.bot.guilds else None)
        if guild is None:
            await self.donations.delete_code(code)
            logger.warning("Donations: гильдия %s не найдена — код %s", link["guild_id"], code)
            return False
        role = guild.get_role(link["role_id"]) if link.get("role_id") else None
        if role is None:
            role = discord.utils.get(guild.roles, name=link["role"] or config.donation_role_name)
        member = guild.get_member(link["user_id"])
        if member is None:
            try:
                member = await guild.fetch_member(link["user_id"])
            except discord.HTTPException:
                member = None
        if member is None or role is None:
            await self.donations.delete_code(code)
            logger.warning("Donations: роль «%s» или участник %s не найдены — код %s", link["role"], link["user_id"], code)
            return False
        if role in member.roles:
            await self.donations.delete_code(code)
            return False
        try:
            await member.add_roles(role, reason=f"DonationAlerts: донат {donation['amount']:g} через код {code}")
        except discord.HTTPException:
            logger.exception("Donations: не удалось выдать роль %s", member.id)
            return False
        await self.donations.delete_code(code)
        logger.info("Donations: роль «%s» выдана <@%s> за донат через код %s", role.name, member.id, code)
        return True

    async def _dm(self, user_id: int, text: str) -> None:
        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except discord.HTTPException:
                return
        try:
            await user.send(text)
        except discord.HTTPException:
            logger.debug("Donations: не удалось отправить ЛС %s", user_id, exc_info=True)

    async def _donation_channel(self, guild_id: int | None) -> discord.TextChannel | None:
        config = self.bot.config
        if guild_id:
            try:
                settings = await self.bot.services.settings.get(guild_id)
            except Exception:
                logger.debug("Donations: не удалось получить настройки гильдии %s", guild_id, exc_info=True)
            else:
                channel = self.bot.get_channel(settings.get("donation_channel_id")) if settings.get("donation_channel_id") else None
                if isinstance(channel, discord.TextChannel):
                    return channel
        channel = self.bot.get_channel(config.donation_notify_channel_id) if config.donation_notify_channel_id else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _notify(self, donation: dict[str, Any], rewarded: bool, guild_id: int | None = None) -> None:
        config = self.bot.config
        channel = await self._donation_channel(guild_id)
        if channel is None:
            return
        embed = embeds.success(
            "Новый донат 💛",
            f"**{donation['username']}** отправил **{donation['amount']:g} {donation['currency']}**",
        )
        if donation["message"]:
            embed.add_field(name="Сообщение", value=donation["message"][:500], inline=False)
        if rewarded:
            embed.add_field(name="Роль", value=f"Выдана «{config.donation_role_name}»", inline=False)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.debug("Donations: не удалось отправить уведомление", exc_info=True)

    async def _ensure_sponsor_message(self) -> None:
        await self.bot.wait_until_ready()
        config = self.bot.config
        channel = self.bot.get_channel(config.donate_button_channel_id) if config.donate_button_channel_id else None
        if not isinstance(channel, discord.TextChannel) or not channel.permissions_for(channel.guild.me).send_messages:
            return
        embed = self._sponsor_embed()
        view = DonateButtonView(self.donations)
        message_id = await self.donations.get_sponsor_message_id()
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                return
            except discord.HTTPException:
                pass
        try:
            async for message in channel.history(limit=10):
                if message.author.id != self.bot.user.id or not message.embeds:
                    continue
                if message.embeds[0].title == _SPONSOR_TITLE:
                    await message.edit(embed=embed, view=view)
                    await self.donations.set_sponsor_message_id(message.id)
                    return
        except discord.HTTPException:
            logger.debug("Donations: ошибка скана истории", exc_info=True)
        message = await channel.send(embed=embed, view=view)
        await self.donations.set_sponsor_message_id(message.id)

    def _sponsor_embed(self) -> discord.Embed:
        config = self.bot.config
        embed = embeds.brand(
            _SPONSOR_TITLE,
            f"Поддержи канал — при донате от **{config.donation_min_amount:g} ₽** "
            f"роль **«{config.donation_role_name}»** выдастся автоматически.",
        )
        if config.donate_bonuses:
            embed.add_field(
                name="Бонусы спонсора",
                value="\n".join(f"• {bonus}" for bonus in config.donate_bonuses),
                inline=False,
            )
        embed.timestamp = discord.utils.utcnow()
        if self.bot.user is not None:
            embed.set_footer(text=self.bot.user.display_name, icon_url=self.bot.user.display_avatar.url)
        return embed

    @app_commands.command(name="donate", description="Поддержать проект донатом")
    @app_commands.guild_only()
    async def donate(self, interaction: discord.Interaction) -> None:
        url = self.bot.config.donate_url
        if not url:
            await interaction.response.send_message(
                embed=embeds.error("Не настроено", "Донат-страница не указана в конфигурации (DONATE_URL)."),
                ephemeral=True,
            )
            return
        embed = embeds.info("Поддержать проект 💛", f"[Открыть страницу доната]({url})")
        await interaction.response.send_message(embed=embed)
