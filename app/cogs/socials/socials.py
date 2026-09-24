"""Ссылки на соцсети (порт socials.js из Node)."""
from __future__ import annotations

import discord

from app.core import embeds
from app.core.base import MegaCog

_DEFAULT_LINKS: dict[str, str] = {
    "discord": "https://discord.gg/rEDcPBuk6c",
    "site": "https://danyacfx-source.github.io/dendich/",
    "youtube": "https://www.youtube.com/@Dendosich",
    "donate": "https://donatty.com/dendich",
}

_ICONS: dict[str, str] = {
    "discord": "💬",
    "site": "🌐",
    "youtube": "▶️",
    "donate": "💝",
    "twitch": "🎥",
    "kick": "🎥",
}


class SocialsCog(MegaCog, name="Socials"):
    @discord.app_commands.command(name="socials", description="Все полезные ссылки")
    @discord.app_commands.guild_only()
    async def socials(self, interaction: discord.Interaction) -> None:
        links = dict(_DEFAULT_LINKS)
        for key, value in self._configured().items():
            if isinstance(value, str) and value:
                links[key] = value
        embed = embeds.info("🔗 Наши ссылки", "Подписывайся и приходи на стримы!")
        embed.color = discord.Color(0x2ECC71)
        for key, url in links.items():
            if not url or not url.startswith(("http://", "https://")):
                continue
            icon = _ICONS.get(key, "•")
            embed.add_field(name=f"{icon} {key.capitalize()}", value=url, inline=False)
        await interaction.response.send_message(embed=embed)

    def _configured(self) -> dict[str, str | None]:
        return {
            "discord": self.bot.config.socials_discord,
            "site": self.bot.config.socials_site,
            "youtube": self.bot.config.socials_youtube,
            "twitch": self.bot.config.socials_twitch,
            "donate": self.bot.config.socials_donate,
        }
