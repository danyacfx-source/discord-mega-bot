"""Команда со статусом и подключением к серверу WARDOGS."""
from __future__ import annotations

import discord

from app.core.base import MegaCog
from app.services.wardogs_service import WardogsService, WardogsUnavailable


class WardogsCog(MegaCog, name="Wardogs"):
    @discord.app_commands.command(name="wardogs", description="Статус и подключение к нашему серверу WARDOGS")
    @discord.app_commands.guild_only()
    async def wardogs(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        service = WardogsService(
            server_name=self.config.wardogs_server_name,
            server_id=self.config.wardogs_server_id,
            timeout=self.config.api_timeout_seconds,
        )
        try:
            server = await service.get_server()
        except WardogsUnavailable as exc:
            embed = discord.Embed(
                title="⚠️ Сервер пока не виден",
                description=f"{exc}\n\nПопробуй снова через пару минут — Асуна Юки проверит каталог ещё раз.",
                color=discord.Color(0xF59E0B),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        occupancy = round(server.players / server.max_players * 100) if server.max_players else 0
        embed = discord.Embed(
            title="⚔️ WARDOGS — сервер найден",
            description=f"**{server.name}**\nСкопируй Join ID и вставь его в игре через **Join By ID**.",
            color=discord.Color(0x7C3AED),
        )
        embed.add_field(name="👥 Онлайн", value=f"**{server.players}/{server.max_players}** · {occupancy}%", inline=True)
        embed.add_field(name="🗺️ Карта", value=server.map_name, inline=True)
        embed.add_field(name="🌍 Регион", value=server.region, inline=True)
        embed.add_field(name="🎮 Режим", value=server.mode, inline=False)
        embed.add_field(name="🔑 Join ID", value=f"```{server.join_id}```", inline=False)
        embed.set_footer(text="Асуна Юки • живой статус WARDOGS")

        view = discord.ui.View(timeout=180)
        join_url = self.config.wardogs_join_url
        if not join_url and self.config.panel_public_url:
            join_url = f"{self.config.panel_public_url.rstrip('/')}/wardogs/join"
        if join_url and join_url.startswith(("https://", "http://")):
            view.add_item(discord.ui.Button(label="Подключиться", emoji="🚀", style=discord.ButtonStyle.link, url=join_url))
        await interaction.followup.send(embed=embed, view=view)
