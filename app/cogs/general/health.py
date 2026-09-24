"""Команда health с полным мониторингом сервисов."""
from __future__ import annotations

import discord
from discord import app_commands

from app.core import embeds
from app.core.base import MegaCog
from app.core.health import HealthChecker, HealthStatus
from app.utils.time import format_duration


class HealthCog(MegaCog, name="Health"):
    """Мониторинг здоровья бота и всех сервисов."""

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self._checker = HealthChecker(bot)

    @app_commands.command(name="health", description="Полная диагностика состояния бота")
    async def health(self, interaction: discord.Interaction) -> None:
        """Показывает детальное состояние всех сервисов."""
        await interaction.response.defer(ephemeral=True)

        # Run health checks
        results = await self._checker.check_all()
        summary = self._checker.get_summary(results)

        # Build embed
        embed = embeds.brand(
            "Диагностика системы",
            f"Сводка состояния компонентов • **{summary['overall'].upper()}**"
        )

        # Group by status
        for name, health in results.items():
            if health.status == HealthStatus.HEALTHY:
                emoji = "🟢"
            elif health.status == HealthStatus.DEGRADED:
                emoji = "🟡"
            else:
                emoji = "🔴"

            value = f"{emoji} {health.status.value}"
            if health.latency_ms > 0:
                value += f" • `{round(health.latency_ms)}ms`"
            if health.error:
                value += f"\n└ *{health.error[:100]}*"

            embed.add_field(name=name.title(), value=value, inline=True)

        # Add summary
        embed.add_field(
            name="─" * 20,
            value="",
            inline=False
        )
        embed.add_field(
            name="Статистика",
            value=(
                f"**Аптайм:** `{format_duration(int(summary['uptime_seconds']))}`\n"
                f"**Здоровы:** `{summary['healthy']}`\n"
                f"**Деградация:** `{summary['degraded']}`\n"
                f"**Недоступны:** `{summary['unhealthy']}`"
            ),
            inline=True
        )

        # Memory info
        memory_health = results.get("memory")
        if memory_health and memory_health.details:
            memory_mb = memory_health.details.get("rss_mb", 0)
            embed.add_field(
                name="Память",
                value=f"**RSS:** `{memory_mb:.1f} MB`",
                inline=True
            )

        embed.set_footer(text=f"Проверено: {summary['timestamp'][:19]}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="Краткий статус бота")
    async def status(self, interaction: discord.Interaction) -> None:
        """Показывает краткий статус бота."""
        latency = round(self.bot.latency * 1000)
        quality = "отлично" if latency < 100 else "стабильно" if latency < 200 else "высокая задержка"

        embed = embeds.brand(
            "Система на связи",
            f"Ответ получен за **{latency} мс** • {quality}"
        )
        embed.add_field(name="ЗАДЕРЖКА", value=f"`{latency} ms`", inline=True)
        embed.add_field(name="АПТАЙМ", value=f"`{format_duration(int(self.bot.uptime.total_seconds()))}`", inline=True)
        embed.add_field(name="ВЕРСИЯ", value=f"`v{self.config.version}`", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping", description="Проверка задержки бота")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Простая проверка задержки."""
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            embed=embeds.info("Pong!", f"Задержка: **{latency} ms**"),
            ephemeral=True
        )
