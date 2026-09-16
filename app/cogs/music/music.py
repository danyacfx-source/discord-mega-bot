"""Команды музыкального плеера."""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from app.core import embeds
from app.core.base import MegaCog
from app.services.audio.track import Track
from app.services.music_service import MusicService, ffmpeg_available
from app.utils.pagination import PaginatorView

if TYPE_CHECKING:
    from app.core.bot import MegaBot

music_group = app_commands.Group(name="music", description="Музыкальный плеер")


class MusicCog(MegaCog, name="Music"):
    def __init__(self, bot: MegaBot, music: MusicService) -> None:
        super().__init__(bot)
        self.music = music

    def _voice_chat_or_none(self, interaction: discord.Interaction):
        vc = interaction.user.voice
        return vc.channel if vc else None

    def _player(self, interaction: discord.Interaction):
        return self.music.get_player(interaction.guild.id)

    async def _ensure_ffmpeg(self, interaction: discord.Interaction) -> bool:
        if not ffmpeg_available():
            await interaction.response.send_message(
                embed=embeds.error("FFmpeg не найден", "Установите FFmpeg для воспроизведения музыки (см. README)."),
                ephemeral=True,
            )
            return False
        return True

    @music_group.command(name="play", description="Воспроизвести трек по названию или ссылке")
    @app_commands.describe(query="Название трека или ссылка (YouTube / Яндекс Музыка)")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        if not await self._ensure_ffmpeg(interaction):
            return

        voice_chat = self._voice_chat_or_none(interaction)
        if voice_chat is None:
            await interaction.followup.send(embed=embeds.error("Ошибка", "Сначала зайдите в голосовой канал."), ephemeral=True)
            return

        player = self._player(interaction)
        if player.voice is None or not player.voice.is_connected():
            if player.voice is not None:
                await player.voice.disconnect()
            try:
                player.voice = await voice_chat.connect()
            except discord.HTTPException as exc:
                await interaction.followup.send(embed=embeds.error("Не удалось подключиться к каналу", str(exc)), ephemeral=True)
                return

        try:
            track = await self.music.resolve(query)
        except Exception as exc:
            await interaction.followup.send(embed=embeds.error("Не удалось найти трек", str(exc)), ephemeral=True)
            return

        player.notify_channel_id = interaction.channel_id
        player.enqueue(track)
        if not player.is_playing:
            await player.play_next()
            embed = self._now_playing(track, player, added=False)
        else:
            embed = self._now_playing(track, player, added=True)
        await interaction.followup.send(embed=embed)

    @staticmethod
    def _now_playing(track: Track, player, added: bool) -> discord.Embed:
        if added:
            embed = embeds.info("В очередь", f"**{track.title}**\nИсполнитель: {track.uploader or '—'}")
            embed.add_field(name="Длительность", value=track.duration_str)
            embed.add_field(name="В очереди", value=str(len(player.queue)))
        else:
            embed = embeds.success("Сейчас играет", f"**{track.title}**\nИсполнитель: {track.uploader or '—'}")
            embed.add_field(name="Длительность", value=track.duration_str)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.add_field(name="Ссылка", value=track.url[:220], inline=False)
        return embed

    @music_group.command(name="skip", description="Пропустить текущий трек")
    @app_commands.describe(amount="Сколько треков пропустить")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction, amount: int = 1) -> None:
        player = self._player(interaction)
        if player.voice is None or not player.voice.is_connected():
            await interaction.response.send_message(embed=embeds.error("Бот не в голосовом канале"), ephemeral=True)
            return
        skipped = await player.skip(amount)
        await interaction.response.send_message(embed=embeds.success("Пропуск", f"Пропущен трек: **{skipped or '—'}**"))

    @music_group.command(name="stop", description="Остановить воспроизведение и очистить очередь")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        await player.stop()
        await interaction.response.send_message(embed=embeds.success("Стоп", "Воспроизведение остановлено, очередь очищена."))

    @music_group.command(name="pause", description="Поставить на паузу")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        player.pause()
        await interaction.response.send_message(embed=embeds.info("Пауза", "⏸ Воспроизведение приостановлено."))

    @music_group.command(name="resume", description="Продолжить воспроизведение")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        player.resume()
        await interaction.response.send_message(embed=embeds.info("Продолжаем", "▶ Воспроизведение продолжено."))

    @music_group.command(name="nowplaying", description="Что играет сейчас")
    @app_commands.guild_only()
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        track = player.current
        if track is None:
            await interaction.response.send_message(embed=embeds.info("Сейчас ничего не играет"))
            return
        embed = embeds.success("Сейчас играет", f"**{track.title}**\nИсполнитель: {track.uploader or '—'}")
        embed.add_field(name="Длительность", value=track.duration_str)
        embed.add_field(name="В очереди", value=str(len(player.queue)))
        await interaction.response.send_message(embed=embed)

    @music_group.command(name="queue", description="Показать очередь треков")
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        entries = list(player.queue)
        if not entries:
            await interaction.response.send_message(embed=embeds.info("Очередь пуста"))
            return

        chunk_size = 10
        pages: list[discord.Embed] = []
        for start in range(0, len(entries), chunk_size):
            embed = embeds.info("Очередь", f"Всего треков: **{len(entries)}**")
            for idx, track in enumerate(entries[start : start + chunk_size], start=start + 1):
                embed.add_field(
                    name=f"{idx}. {track.title}",
                    value=f"{track.duration_str} • {track.uploader or '—'}"[:150],
                    inline=False,
                )
                embed.set_footer(text=f"Страница {start // chunk_size + 1}")
            pages.append(embed)

        view = PaginatorView(pages, interaction.user)
        await interaction.response.send_message(embed=pages[0], view=view)

    @music_group.command(name="volume", description="Громкость (0–200%)")
    @app_commands.describe(value="Значение громкости в процентах")
    @app_commands.guild_only()
    async def volume(self, interaction: discord.Interaction, value: app_commands.Range[int, 0, 200]) -> None:
        player = self._player(interaction)
        player.set_volume(value / 100)
        await interaction.response.send_message(embed=embeds.success("Громкость", f"Установлена громкость: **{value}%**"))

    @music_group.command(name="loop", description="Включить/выключить повтор текущего трека")
    @app_commands.guild_only()
    async def loop(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        player.loop_one = not player.loop_one
        state = "включён" if player.loop_one else "выключен"
        await interaction.response.send_message(embed=embeds.info("Повтор", f"Повтор трека {state}."))

    @music_group.command(name="leave", description="Бот покидает голосовой канал")
    @app_commands.guild_only()
    async def leave(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        await player.disconnect()
        await interaction.response.send_message(embed=embeds.info("До свидания", "Бот вышел из голосового канала."))
