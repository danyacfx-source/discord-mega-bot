"""Команда /scanbans: список банов сканеров веб-панели и снятие бана по IP."""
from __future__ import annotations

import time

import discord
from discord import app_commands

from app.core import embeds
from app.core.base import MegaCog
from app.core.checks import is_owner

scanbans_group = app_commands.Group(name="scanbans", description="Баны сканеров веб-панели")


class ScanBansCog(MegaCog, name="ScanBans"):
    """Управление банами IP за сканирование веб-панели (только владелец бота)."""
    # The group must be a class attribute for discord.py's CogMeta to collect
    # it when the cog is loaded.
    scanbans = scanbans_group

    @scanbans_group.command(name="list", description="Нарушители сканирования и их баны")
    @is_owner()
    async def list_bans(self, interaction: discord.Interaction) -> None:
        panel = self.bot.webpanel
        if panel is None:
            await interaction.response.send_message("Веб-панель не запущена.", ephemeral=True)
            return
        now = time.time()
        lines = []
        for ip, (count, until) in sorted(panel._scan_offenses.items(), key=lambda item: -item[1][0]):
            if until == float("inf"):
                status = "бан навсегда"
            elif until > now:
                status = f"бан ещё {int(until - now) // 60} мин"
            else:
                status = "бана нет"
            lines.append(f"`{ip}` — нарушений: {count}, {status}")
        body = "\n".join(lines[:20]) or "Нарушителей нет."
        await interaction.response.send_message(embed=embeds.brand("Баны сканеров", body), ephemeral=True)

    @scanbans_group.command(name="unban", description="Снять бан с IP (счётчик нарушений сохранится)")
    @app_commands.describe(ip="IP-адрес из списка /scanbans list")
    @is_owner()
    async def unban(self, interaction: discord.Interaction, ip: str) -> None:
        panel = self.bot.webpanel
        if panel is None:
            await interaction.response.send_message("Веб-панель не запущена.", ephemeral=True)
            return
        count = await panel.clear_scan_ban(ip.strip(), f"Discord: {interaction.user}")
        if count is None:
            await interaction.response.send_message(f"`{ip}` нет среди нарушителей.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Бан с `{ip}` снят. Нарушений всего: {count}.", ephemeral=True
        )
