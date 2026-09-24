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
playlist_group = app_commands.Group(name="playlist", description="Сохранённые плейлисты", parent=music_group)


class MusicCog(MegaCog, name="Music"):
    # The group must be a class attribute for discord.py's CogMeta to collect
    # it when the cog is loaded.
    music = music_group

    def __init__(self, bot: MegaBot, music: MusicService) -> None:
        super().__init__(bot)
        self.music = music

    def _voice_chat_or_none(self, interaction: discord.Interaction):
        vc = interaction.user.voice
        return vc.channel if vc else None

    def _player(self, interaction: discord.Interaction):
        return self.music.get_player(interaction.guild.id)

    async def _restore_queue(self, interaction: discord.Interaction) -> None:
        if interaction.guild is not None:
            await self.music.restore_queue(interaction.guild.id)

    @music_group.command(name="play", description="Воспроизвести трек по названию или ссылке")
    @app_commands.describe(query="Название трека или ссылка на YouTube")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        await self._restore_queue(interaction)
        if not ffmpeg_available():
            await interaction.response.send_message(
                embed=embeds.error("FFmpeg не найден", "Установите FFmpeg для воспроизведения музыки (см. README)."),
                ephemeral=True,
            )
            return
        await interaction.response.defer()

        voice_chat = self._voice_chat_or_none(interaction)
        if voice_chat is None:
            await interaction.followup.send(embed=embeds.error("Ошибка", "Сначала зайдите в голосовой канал."), ephemeral=True)
            return

        try:
            track = await self.music.resolve(query.strip())
        except Exception as exc:
            await interaction.followup.send(embed=embeds.error("Не удалось найти трек", str(exc)), ephemeral=True)
            return

        player = self._player(interaction)
        if player.voice is None or not player.voice.is_connected():
            if player.voice is not None:
                await player.voice.disconnect()
            try:
                player.voice = await voice_chat.connect()
            except (discord.HTTPException, discord.ClientException) as exc:
                await interaction.followup.send(embed=embeds.error("Не удалось подключиться к каналу", str(exc)), ephemeral=True)
                return

        player.notify_channel_id = interaction.channel_id
        player.enqueue(track)
        if not player.is_playing:
            await player.play_next()
            embed = self._now_playing(track, player, added=False)
        else:
            embed = self._now_playing(track, player, added=True)
        await interaction.followup.send(embed=embed)
        await self.music.persist_queue(interaction.guild.id)
        await self.music.record_history(interaction.guild.id, interaction.user.id, track)

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
    async def skip(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 50] = 1) -> None:
        await self._restore_queue(interaction)
        player = self._player(interaction)
        if player.voice is None or not player.voice.is_connected():
            await interaction.response.send_message(embed=embeds.error("Бот не в голосовом канале"), ephemeral=True)
            return
        skipped = await player.skip(amount)
        await interaction.response.send_message(embed=embeds.success("Пропуск", f"Пропущен трек: **{skipped or '—'}**"))
        await self.music.persist_queue(interaction.guild.id)

    @music_group.command(name="skipvote", description="Проголосовать за пропуск текущего трека")
    @app_commands.guild_only()
    async def skipvote(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        voice = player.voice
        if player.current is None or voice is None or voice.channel is None:
            await interaction.response.send_message(
                embed=embeds.error("Голосование", "Сейчас нет активного трека."),
                ephemeral=True,
            )
            return
        listeners = [member for member in voice.channel.members if not member.bot]
        required = max(2, (len(listeners) + 1) // 2)
        player.skip_votes.add(interaction.user.id)
        if len(player.skip_votes) >= required:
            await player.skip()
            await self.music.persist_queue(interaction.guild.id)
            await interaction.response.send_message(
                embed=embeds.success("Голосование", "Большинство проголосовало — трек пропущен.")
            )
            return
        await interaction.response.send_message(
            embed=embeds.info("Голосование", f"Голосов: **{len(player.skip_votes)}/{required}**")
        )

    @music_group.command(name="stop", description="Остановить воспроизведение и очистить очередь")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        await self._restore_queue(interaction)
        player = self._player(interaction)
        await player.stop()
        await interaction.response.send_message(embed=embeds.success("Стоп", "Воспроизведение остановлено, очередь очищена."))
        await self.music.persist_queue(interaction.guild.id)

    @music_group.command(name="pause", description="Поставить на паузу")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        embed = (
            embeds.info("Пауза", "⏸ Воспроизведение приостановлено.")
            if player.pause()
            else embeds.warning("Пауза", "Сейчас нет активного воспроизведения.")
        )
        await interaction.response.send_message(embed=embed)

    @music_group.command(name="resume", description="Продолжить воспроизведение")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        embed = (
            embeds.info("Продолжаем", "▶ Воспроизведение продолжено.")
            if player.resume()
            else embeds.warning("Продолжаем", "Плеер не находится на паузе.")
        )
        await interaction.response.send_message(embed=embed)

    @music_group.command(name="shuffle", description="Перемешать очередь")
    @app_commands.guild_only()
    async def shuffle(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction)
        if len(player.queue) < 2:
            await interaction.response.send_message(
                embed=embeds.info("Очередь", "Для перемешивания нужно хотя бы два трека."),
                ephemeral=True,
            )
            return
        player.shuffle()
        await interaction.response.send_message(
            embed=embeds.success("Очередь перемешана", f"Треков в очереди: **{len(player.queue)}**")
        )
        await self.music.persist_queue(interaction.guild.id)

    @music_group.command(name="remove", description="Удалить трек из очереди")
    @app_commands.describe(position="Позиция трека в очереди")
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, position: app_commands.Range[int, 1, 1000]) -> None:
        await self._restore_queue(interaction)
        player = self._player(interaction)
        removed = player.remove(position)
        if removed is None:
            await interaction.response.send_message(
                embed=embeds.error("Не найдено", "Трека с такой позицией в очереди нет."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Удалено из очереди", f"**{removed.title}**")
        )
        await self.music.persist_queue(interaction.guild.id)

    @music_group.command(name="seek", description="Перемотать текущий трек")
    @app_commands.describe(seconds="Позиция в секундах")
    @app_commands.guild_only()
    async def seek(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 86400]) -> None:
        player = self._player(interaction)
        if not await player.seek(seconds):
            await interaction.response.send_message(
                embed=embeds.error("Перемотка", "Сейчас нет активного трека."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Перемотка", f"Позиция установлена: **{seconds}с**")
        )

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
        await self._restore_queue(interaction)
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
        await self.music.persist_queue(interaction.guild.id)
        await player.disconnect()
        await interaction.response.send_message(embed=embeds.info("До свидания", "Бот вышел из голосового канала."))

    @playlist_group.command(name="save", description="Сохранить текущую очередь как плейлист")
    @app_commands.describe(name="Имя плейлиста")
    @app_commands.guild_only()
    async def playlist_save(self, interaction: discord.Interaction, name: str) -> None:
        player = self._player(interaction)
        tracks = ([player.current] if player.current is not None else []) + list(player.queue)
        if not tracks:
            await interaction.response.send_message(
                embed=embeds.warning("Плейлист", "Очередь пуста — сохранять нечего."),
                ephemeral=True,
            )
            return
        try:
            await self.music.save_playlist(interaction.guild.id, name, interaction.user.id, tracks)
        except ValueError:
            await interaction.response.send_message(
                embed=embeds.error("Плейлист", "Укажи непустое имя до 64 символов."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=embeds.success("Плейлист сохранён", f"**{name.strip()[:64]}** · треков: **{len(tracks[:100])}**")
        )

    @playlist_group.command(name="load", description="Загрузить плейлист в очередь")
    @app_commands.describe(name="Имя плейлиста")
    @app_commands.guild_only()
    async def playlist_load(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer()
        tracks = await self.music.load_playlist(interaction.guild.id, name)
        if not tracks:
            await interaction.followup.send(
                embed=embeds.error("Плейлист", "Плейлист не найден или треки больше недоступны."),
                ephemeral=True,
            )
            return
        player = self._player(interaction)
        for track in tracks[:100]:
            player.enqueue(track)
        await self.music.persist_queue(interaction.guild.id)
        await interaction.followup.send(
            embed=embeds.success("Плейлист загружен", f"Добавлено треков: **{len(tracks[:100])}**")
        )

    @playlist_group.command(name="import", description="Импортировать YouTube Playlist в сохранённый плейлист")
    @app_commands.describe(url="Ссылка на публичный YouTube Playlist", name="Имя плейлиста")
    @app_commands.guild_only()
    async def playlist_import(self, interaction: discord.Interaction, url: str, name: str) -> None:
        await interaction.response.defer()
        try:
            tracks = await self.music.resolve_many(url.strip())
        except Exception as exc:
            await interaction.followup.send(embed=embeds.error("Импорт", str(exc)), ephemeral=True)
            return
        if not tracks:
            await interaction.followup.send(
                embed=embeds.error("Импорт", "В плейлисте не найдено доступных треков."),
                ephemeral=True,
            )
            return
        try:
            await self.music.save_playlist(interaction.guild.id, name, interaction.user.id, tracks)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error("Импорт", "Укажи непустое имя плейлиста до 64 символов."),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=embeds.success("Плейлист импортирован", f"**{name.strip()[:64]}** · треков: **{len(tracks)}**")
        )

    @playlist_group.command(name="list", description="Показать сохранённые плейлисты")
    @app_commands.guild_only()
    async def playlist_list(self, interaction: discord.Interaction) -> None:
        rows = await self.music.list_playlists(interaction.guild.id)
        if not rows:
            await interaction.response.send_message(embed=embeds.info("Плейлисты", "Сохранённых плейлистов пока нет."))
            return
        lines = [f"• **{row['name']}** — {row['tracks']} тр." for row in rows[:25]]
        await interaction.response.send_message(embed=embeds.info("Плейлисты", "\n".join(lines)))

    @playlist_group.command(name="delete", description="Удалить сохранённый плейлист")
    @app_commands.describe(name="Имя плейлиста")
    @app_commands.guild_only()
    async def playlist_delete(self, interaction: discord.Interaction, name: str) -> None:
        removed = await self.music.delete_playlist(interaction.guild.id, name)
        await interaction.response.send_message(
            embed=(
                embeds.success("Плейлист удалён", f"**{name}**")
                if removed
                else embeds.error("Плейлист", "Плейлист с таким именем не найден.")
            ),
            ephemeral=True,
        )

    @music_group.command(name="history", description="Показать историю прослушивания")
    @app_commands.guild_only()
    async def history(self, interaction: discord.Interaction) -> None:
        rows = await self.music.history(interaction.guild.id, 20)
        if not rows:
            await interaction.response.send_message(embed=embeds.info("История", "История прослушивания пуста."))
            return
        lines = [
            f"**{index}.** {row['title'][:80]} · <@{row['user_id']}>"
            for index, row in enumerate(rows, start=1)
        ]
        await interaction.response.send_message(embed=embeds.info("История прослушивания", "\n".join(lines)))
