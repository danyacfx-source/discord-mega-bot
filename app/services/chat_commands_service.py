"""Команды чата стримов (Kick/Twitch): экономика на монетах, опросы, топ, шоуауты.

Коги платформ регистрируются через ``register_platform`` и при входящем
сообщении зовут ``handle``. Ответ уходит в тот же чат, откуда пришло
сообщение (``reply_to`` — логин Twitch-канала или пустая строка для Kick).
"""
from __future__ import annotations

import json
import logging
import random
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services.twitch_command_settings import (
    load_twitch_command_settings,
    twitch_command_alias_map,
)

if TYPE_CHECKING:
    from app.config import Config
    from app.services.chat_coins_service import ChatCoinsService
    from app.services.chat_feed import ChatFeed
    from app.services.kv_service import KvService
    from app.services.live_vote_service import LiveVoteService

logger = logging.getLogger("bot.services")

LiveFn = Callable[[], Awaitable[dict[str, Any] | None]]
ScheduleFn = Callable[[], Awaitable[list[dict[str, Any]] | None]]
ReplyFn = Callable[[str, str], Awaitable[None]]

#: пассивное начисление монет за сообщение, сек
_PASSIVE_SECONDS = 45.0
#: предохранитель от раздувания словарей кулдаунов
_SWEEP_AFTER = 10_000
_MAX_STAKE = 10_000

_SLOT_ROWS = ("7️⃣", "💎", "🔔", "🍋", "🍒")
_SLOT_MULT = {"7️⃣": 10, "💎": 8, "🔔": 5, "🍋": 3, "🍒": 2}

_BALL_ANSWERS = (
    "Бесспорно, да", "Нет и не будет", "Скорее всего", "Сомневаюсь",
    "Спроси ещё раз ближе к концу стрима", "Точно да", "Точка",
    "Не думаю", "Шансы неплохие", "Да, но погоди-ка",
    "Было бы лучше не знать", "Определённо нет",
)

_VOTE_EMOJI = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣"}


@dataclass(slots=True)
class ChatMessage:
    """Входящее сообщение чата стрима."""

    platform: str
    username: str  # логин в нижнем регистре
    display_name: str
    content: str
    is_mod: bool = False
    is_bot: bool = False
    reply_to: str = ""  # логин Twitch-канала; "" — Kick (единственный чат)


@dataclass(slots=True)
class ChatPlatform:
    reply: ReplyFn
    live: LiveFn | None = None
    schedule: ScheduleFn | None = None


@dataclass(slots=True)
class _Poll:
    question: str
    options: list[str]
    votes: dict[str, int] = field(default_factory=dict)
    ends: float = 0.0


class ChatCommandsService:
    """Диспетчер команд чата: единая логика для всех платформ."""

    def __init__(
        self,
        config: Config,
        coins: ChatCoinsService,
        kv: KvService,
        feed: ChatFeed | None = None,
        live_vote: LiveVoteService | None = None,
    ) -> None:
        self._config = config
        self._coins = coins
        self._kv = kv
        self._feed = feed
        self._live_vote = live_vote
        self._platforms: dict[str, ChatPlatform] = {}
        self._polls: dict[str, _Poll] = {}
        self._cmd_ready: dict[tuple[str, str], float] = {}
        self._passive_ready: dict[tuple[str, str], float] = {}
        self._twitch_settings: dict[str, dict[str, Any]] | None = None
        self._twitch_settings_at = 0.0

    async def _remember(self, key: str, payload: dict[str, Any]) -> None:
        """Персистентное событие для оверлея (последний выигрыш/опрос)."""
        try:
            await self._kv.set(key, json.dumps(payload, ensure_ascii=False))
        except Exception:
            logger.debug("ChatCommands: не удалось записать %s", key, exc_info=True)

    # ------------------------------------------------------------- регистрация

    def register_platform(
        self,
        platform: str,
        *,
        reply: ReplyFn,
        live: LiveFn | None = None,
        schedule: ScheduleFn | None = None,
    ) -> None:
        self._platforms[platform] = ChatPlatform(reply=reply, live=live, schedule=schedule)

    def unregister_platform(self, platform: str) -> None:
        self._platforms.pop(platform, None)

    @property
    def platforms(self) -> tuple[str, ...]:
        return tuple(self._platforms)

    # ------------------------------------------------------------- диспетчер

    async def handle(self, msg: ChatMessage) -> None:
        """Единый вход: лента оверлея, пассивные монеты, голосование, команды."""
        text = msg.content.strip()
        # Cross-platform votes work on anonymous/read-only Twitch/Kick listeners,
        # even when ordinary reply-capable chat commands are disabled.
        if text and not msg.is_bot and self._live_vote is not None:
            try:
                if await self._live_vote.register_message(msg.platform, msg.username, text):
                    return
            except Exception:
                logger.exception("LiveVote: не удалось засчитать голос")
        # Accepted vote commands should not flood the ordinary OBS chat feed.
        if text and not msg.is_bot and self._feed is not None:
            self._feed.push(msg.platform, msg.display_name or msg.username, text, is_mod=msg.is_mod)
        if not self._config.chat_commands_enabled or msg.is_bot:
            return
        content = text
        if not content or msg.platform not in self._platforms:
            return
        self._sweep()
        # Голос в опросе — голая цифра, без префикса команды.
        vote_text = self._try_vote(msg, content)
        if vote_text is not None:
            await self._send(msg, vote_text)
            return
        prefix = self._config.chat_command_prefix
        if not content.startswith(prefix):
            await self._passive(msg)
            return
        raw = content[len(prefix) :].strip()
        if not raw:
            return
        cmd, _, rest = raw.partition(" ")
        cmd = cmd.lower()
        if not self._allowed_now(msg, cmd):
            return
        command_id = _ALIASES.get(cmd, cmd)
        twitch_command: dict[str, Any] | None = None
        if msg.platform == "twitch":
            settings = await self.twitch_command_settings()
            command_id = twitch_command_alias_map(settings).get(cmd, "")
            twitch_command = settings.get(command_id)
            if (
                twitch_command is None
                or not twitch_command["enabled"]
                or (twitch_command["moderator_only"] and not msg.is_mod)
            ):
                return
        elif command_id in _MODERATOR_COMMANDS and not msg.is_mod:
            return
        handler = _COMMANDS.get(command_id)
        if handler is None:
            return
        try:
            text = await handler(self, msg, rest.strip())
        except Exception:
            logger.exception("ChatCommands: сбой команды !%s (%s)", cmd, msg.platform)
            return
        if text and twitch_command is not None:
            text = self._format_twitch_response(
                twitch_command["response"],
                text,
                msg,
                rest.strip(),
            )
        if text:
            await self._send(msg, text[:450])

    async def twitch_command_settings(
        self, *, force: bool = False
    ) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        if force or self._twitch_settings is None or now - self._twitch_settings_at >= 5.0:
            self._twitch_settings = await load_twitch_command_settings(self._kv)
            self._twitch_settings_at = now
        return self._twitch_settings

    def invalidate_twitch_command_settings(self) -> None:
        self._twitch_settings = None
        self._twitch_settings_at = 0.0

    async def match_twitch_command(
        self, msg: ChatMessage
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Разбирает Twitch-команду с учётом алиасов и прав из панели."""
        prefix = self._config.chat_command_prefix
        content = msg.content.strip()
        if not content.startswith(prefix):
            return None
        raw = content[len(prefix) :].strip()
        if not raw:
            return None
        alias, _, rest = raw.partition(" ")
        settings = await self.twitch_command_settings()
        command_id = twitch_command_alias_map(settings).get(alias.lower())
        if command_id is None:
            return None
        command = settings[command_id]
        if not command["enabled"] or (command["moderator_only"] and not msg.is_mod):
            return None
        return command_id, rest.strip(), command

    async def format_twitch_response(
        self,
        command_id: str,
        default: str,
        msg: ChatMessage,
        args: str = "",
    ) -> str:
        settings = await self.twitch_command_settings()
        command = settings.get(command_id)
        if command is None:
            return default
        return self._format_twitch_response(command["response"], default, msg, args)

    @staticmethod
    def _format_twitch_response(
        template: str,
        default: str,
        msg: ChatMessage,
        args: str,
    ) -> str:
        if not template:
            return default
        return (
            template.replace("{default}", default)
            .replace("{user}", msg.display_name or msg.username)
            .replace("{args}", args)
            .replace("{channel}", msg.reply_to)
        )[:450]

    async def tick(self) -> None:
        """Завершает опросы, у которых вышло время (зовётся когом по таймеру)."""
        now = time.monotonic()
        for platform, poll in list(self._polls.items()):
            if now < poll.ends:
                continue
            del self._polls[platform]
            await self._send_poll_results(platform, poll)

    def poll_remaining(self, platform: str) -> float | None:
        poll = self._polls.get(platform)
        if poll is None:
            return None
        return max(0.0, poll.ends - time.monotonic())

    # ------------------------------------------------------------- внутренности

    async def _send(self, msg: ChatMessage, text: str) -> None:
        platform = self._platforms.get(msg.platform)
        if platform is None:
            return
        try:
            await platform.reply(msg.reply_to, text)
        except Exception:
            logger.warning("ChatCommands: не удалось ответить в чат %s", msg.platform, exc_info=True)

    async def _passive(self, msg: ChatMessage) -> None:
        reward = self._config.chat_coin_reward
        if reward <= 0:
            return
        now = time.monotonic()
        key = (msg.platform, msg.username)
        last = self._passive_ready.get(key)
        if last is not None and now - last < _PASSIVE_SECONDS:
            return
        self._passive_ready[key] = now
        try:
            await self._coins.add(
                msg.platform, msg.username, msg.display_name, reward, count_message=True
            )
        except Exception:
            logger.debug("ChatCommands: не удалось начислить монеты %s", msg.username, exc_info=True)

    def _allowed_now(self, msg: ChatMessage, cmd: str) -> bool:
        cooldown = max(0.0, self._config.chat_cmd_cooldown)
        if cooldown <= 0:
            return True
        now = time.monotonic()
        key = (msg.platform, msg.username)
        last = self._cmd_ready.get(key)
        if last is not None and now < last:
            return False
        self._cmd_ready[key] = now + cooldown
        return True

    def _try_vote(self, msg: ChatMessage, raw: str) -> str | None:
        """Голос в активном опросе: голая цифра 1..N (без префикса команды)."""
        poll = self._polls.get(msg.platform)
        if poll is None or not raw.isdigit():
            return None
        choice = int(raw)
        if not 1 <= choice <= len(poll.options):
            return None
        poll.votes[msg.username] = choice - 1
        return "✅ голос учтён"

    def _sweep(self) -> None:
        if len(self._cmd_ready) <= _SWEEP_AFTER and len(self._passive_ready) <= _SWEEP_AFTER:
            return
        cutoff = time.monotonic() - 3600
        self._cmd_ready = {k: v for k, v in self._cmd_ready.items() if v > cutoff}
        self._passive_ready = {k: v for k, v in self._passive_ready.items() if v > cutoff}

    async def _send_poll_results(self, platform: str, poll: _Poll) -> None:
        total = len(poll.votes)
        counts = [0] * len(poll.options)
        for choice in poll.votes.values():
            counts[choice] += 1
        lines = []
        for index, option in enumerate(poll.options):
            share = round(counts[index] * 100 / total) if total else 0
            lines.append(f"**{option}** — {counts[index]} ({share}%)")
        best = max(counts, default=0)
        winners = [poll.options[i] for i, count in enumerate(counts) if count == best and best > 0]
        head = f"📊 Опрос завершён: {poll.question} — голосов {total}"
        if len(winners) == 1:
            head += f"\n🏆 Победил: **{winners[0]}**"
        await self._remember(
            "overlay:last_poll",
            {
                "question": poll.question[:200],
                "options": [{"name": option[:80], "votes": counts[i]} for i, option in enumerate(poll.options)],
                "winner": winners[0][:80] if len(winners) == 1 else "",
                "total": total,
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        await self._send(
            ChatMessage(platform=platform, username="", display_name="", content=""),
            head + "\n" + "\n".join(lines),
        )

    # ------------------------------------------------------------- команды

    async def _cmd_ping(self, msg: ChatMessage, rest: str) -> str:
        return "🏓 pong! Команды: !help"

    async def _cmd_help(self, msg: ChatMessage, rest: str) -> str:
        if msg.platform == "twitch":
            settings = await self.twitch_command_settings()
            prefix = self._config.chat_command_prefix
            aliases = [
                f"{prefix}{command['aliases'][0]}"
                for command in settings.values()
                if command["enabled"]
                and command["aliases"]
                and (not command["moderator_only"] or msg.is_mod)
            ]
            return "📜 Команды чата: " + ", ".join(aliases)
        lines = [
            "📜 Команды чата:",
            "!uptime — эфир, !links — ссылки, !расписание — стримы",
            "!discord, !youtube, !игра, !сигналы, !награды, !позывной",
            "!баланс / !топ — монеты и лидерборд",
            "!слоты [ставка] / !монетка [ставка] [орёл|решка] — азарт",
            "!8ball [вопрос] — шар предсказаний",
            "!poll вопр|вар1|вар2 — опрос (модераторы), голос — цифрой",
            "!so ник — шоуаут (модераторы)",
        ]
        return "\n".join(lines)

    async def _cmd_uptime(self, msg: ChatMessage, rest: str) -> str:
        platform = self._platforms.get(msg.platform)
        status = None
        if platform is not None and platform.live is not None:
            try:
                status = await platform.live()
            except Exception:
                logger.debug("ChatCommands: статус эфира недоступен (%s)", msg.platform, exc_info=True)
        if not status or not status.get("started_at"):
            return "⛔ Сейчас эфир не идёт."
        try:
            started = datetime.fromisoformat(str(status["started_at"]).replace("Z", "+00:00"))
            delta = datetime.now(UTC) - started
        except ValueError:
            return "⛔ Сейчас эфир не идёт."
        if delta.total_seconds() < 0:
            return "⛔ Сейчас эфир не идёт."
        hours, seconds = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(seconds, 60)
        viewers = status.get("viewers")
        tail = f" · 👁 {viewers}" if viewers else ""
        return f"🔴 В эфире уже {hours}:{minutes:02d}:{seconds:02d}{tail}"

    async def _cmd_links(self, msg: ChatMessage, rest: str) -> str:
        config = self._config
        lines = []
        if config.socials_discord:
            lines.append(f"💬 Discord: {config.socials_discord}")
        if config.kick_channel_slug:
            lines.append(f"📺 Kick: https://kick.com/{config.kick_channel_slug}")
        if config.twitch_channels:
            lines.append(f"🟣 Twitch: https://www.twitch.tv/{config.twitch_channels[0]}")
        if config.socials_youtube:
            lines.append(f"▶️ YouTube: {config.socials_youtube}")
        if config.socials_donate:
            lines.append(f"💰 Донат: {config.socials_donate}")
        if not lines:
            return "🔗 Ссылки ещё не настроены."
        return "🔗 Наши ссылки:\n" + "\n".join(lines)

    async def _cmd_discord(self, msg: ChatMessage, rest: str) -> str:
        url = getattr(self._config, "twitch_discord_url", "") or self._config.socials_discord
        return f"📡 Штаб в Discord: {url}" if url else "📡 Ссылка на Discord ещё не настроена."

    async def _cmd_donate(self, msg: ChatMessage, rest: str) -> str:
        url = getattr(self._config, "twitch_donate_url", "") or self._config.socials_donate
        return f"💰 Поддержать стрим: {url}" if url else "💰 Ссылка на донат ещё не настроена."

    async def _cmd_youtube(self, msg: ChatMessage, rest: str) -> str:
        url = self._config.socials_youtube or "https://www.youtube.com/@Dendosich"
        return f"▶️ Архив операций на YouTube: {url}"

    async def _cmd_game(self, msg: ChatMessage, rest: str) -> str:
        platform = self._platforms.get(msg.platform)
        if platform is None or platform.live is None:
            return "🎮 Информация об игре сейчас недоступна."
        try:
            stream = await platform.live()
        except Exception:
            logger.debug("ChatCommands: статус игры недоступен", exc_info=True)
            return "🎮 Не удалось получить категорию стрима."
        if not stream:
            return "📡 Сейчас вне эфира."
        category = str(stream.get("category") or "").strip()
        return f"🎮 Сейчас в эфире: {category}" if category and category != "—" else "🎮 Игра пока не указана."

    async def _cmd_signals(self, msg: ChatMessage, rest: str) -> str:
        return (
            "📡 СИГНАЛЫ — бесплатные баллы канала Twitch. Копи за просмотр и "
            "трать через значок баллов под чатом. Это НЕ монеты нашего бота. "
            "Список наград: !награды"
        )

    async def _cmd_rewards(self, msg: ChatMessage, rest: str) -> str:
        return (
            "🎖 СИГНАЛЫ: 📻 Проверка связи 100 | 🔭 Разведданные 250 | "
            "🎙 Перехват эфира 500 | 🎧 Позывной 800 | 🗺 План 1500 | "
            "🔀 Отмена плана 2500 | 🚩 Операция зрителей 5000. "
            "Награды открываются через баллы канала Twitch."
        )

    async def _cmd_callsign(self, msg: ChatMessage, rest: str) -> str:
        import random

        names = (
            "Гроза", "Барс", "Шторм", "Маяк", "Ворон", "Рысь",
            "Скат", "Филин", "Бастион", "Радиус", "Призрак", "Кедр",
        )
        return f"📻 {msg.display_name or msg.username}, твой позывной: {random.choice(names)}. Приём!"

    async def _cmd_schedule(self, msg: ChatMessage, rest: str) -> str:
        platform = self._platforms.get(msg.platform)
        if platform is None or platform.schedule is None:
            return "📅 Расписание для этой площадки не настроено."
        try:
            segments = await platform.schedule()
        except Exception:
            logger.debug("ChatCommands: расписание недоступно (%s)", msg.platform, exc_info=True)
            return "📅 Расписание сейчас недоступно, попробуй позже."
        if not segments:
            return "📅 Расписание пока пустое."
        lines = []
        for segment in segments[:3]:
            title = str(segment.get("title") or segment.get("category") or "Стрим")
            start = str(segment.get("start_time") or "")
            try:
                moment = datetime.fromisoformat(start.replace("Z", "+00:00"))
                stamp = moment.astimezone(UTC).strftime("%d.%m %H:%M UTC")
            except ValueError:
                stamp = start[:16]
            lines.append(f"• {stamp} — {title}")
        return "📅 Ближайшие эфиры:\n" + "\n".join(lines)

    async def _cmd_bal(self, msg: ChatMessage, rest: str) -> str:
        if self._config.chat_coin_reward <= 0:
            return "💰 Монеты выключены."
        row = await self._coins.get(msg.platform, msg.username)
        if row is None:
            return f"{msg.display_name}, у тебя пока 0 💰 — пиши в чат и копи!"
        return f"💰 {msg.display_name}: {row['coins']} монет · сообщений {row['messages']}"

    async def _cmd_top(self, msg: ChatMessage, rest: str) -> str:
        if self._config.chat_coin_reward <= 0:
            return "💰 Монеты выключены."
        rows = await self._coins.top(msg.platform, 10)
        if not rows:
            return "🏆 Лидерборд пуст — пишите в чат и становитесь первыми!"
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = [
            f"{medal.get(i, f'{i}.')} **{row['display_name']}** — {row['coins']} 💰"
            for i, row in enumerate(rows, start=1)
        ]
        return "🏆 Топ по монетам:\n" + "\n".join(lines)

    async def _cmd_slots(self, msg: ChatMessage, rest: str) -> str:
        if self._config.chat_coin_reward <= 0:
            return "💰 Монеты выключены."
        stake = _parse_stake(rest, default=10)
        ok = await self._coins.spend(msg.platform, msg.username, msg.display_name, stake)
        if ok is None:
            row = await self._coins.get(msg.platform, msg.username)
            balance = row["coins"] if row else 0
            return f"💸 Ставка {stake} больше твоего баланса ({balance} 💰)."
        reels = [secrets.choice(_SLOT_ROWS) for _ in range(3)]
        if reels[0] == reels[1] == reels[2]:
            win = stake * _SLOT_MULT[reels[0]]
        elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
            win = stake
        else:
            win = 0
        if win:
            balance = await self._coins.add(msg.platform, msg.username, msg.display_name, win)
            verdict = f"🎉 ВЫИГРЫШ {win} 💰 (баланс {balance})"
            await self._remember(
                "overlay:last_slot",
                {
                    "user": msg.display_name[:32],
                    "result": " | ".join(reels),
                    "win": win,
                    "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            )
        else:
            verdict = "😵 Минус ставка. Удачи в следующий раз!"
        return f"🎰 {' | '.join(reels)} — {verdict}"

    async def _cmd_flip(self, msg: ChatMessage, rest: str) -> str:
        if self._config.chat_coin_reward <= 0:
            return "💰 Монеты выключены."
        parts = rest.split()
        stake = _parse_stake(parts[0] if parts else "", default=10)
        label = {"heads": "орёл", "tails": "решка"}
        call = ""
        for word in parts[1:] if len(parts) > 1 else []:
            lowered = word.lower()
            if lowered in ("орёл", "орел", "heads", "o"):
                call = "heads"
                break
            if lowered in ("решка", "tails", "r"):
                call = "tails"
                break
        if not call:
            call = secrets.choice(("heads", "tails"))
        ok = await self._coins.spend(msg.platform, msg.username, msg.display_name, stake)
        if ok is None:
            row = await self._coins.get(msg.platform, msg.username)
            balance = row["coins"] if row else 0
            return f"💸 Ставка {stake} больше твоего баланса ({balance} 💰)."
        toss = secrets.choice(("heads", "tails"))
        if toss == call:
            win = stake * 2
            balance = await self._coins.add(msg.platform, msg.username, msg.display_name, win)
            return f"🪙 {label[toss].upper()}! Угадал — выигрыш {win} 💰 (баланс {balance})"
        return f"🪙 {label[toss].upper()} — мимо. Ставка {stake} сгорела."

    async def _cmd_8ball(self, msg: ChatMessage, rest: str) -> str:
        if not rest:
            return "🔮 Задай вопрос после !8ball"
        return f"🔮 {random.choice(_BALL_ANSWERS)}"

    async def _cmd_so(self, msg: ChatMessage, rest: str) -> str:
        nick = rest.strip().lstrip("@").split()[0] if rest.strip() else ""
        if not nick:
            return "Использование: !so ник"
        return f"👋 Шоуаут: @{nick} — заходи, спасибо что тут!"

    async def _cmd_poll(self, msg: ChatMessage, rest: str) -> str:
        if msg.platform in self._polls:
            return "⏳ Опрос уже идёт — дождитесь итогов."
        parts = [part.strip() for part in rest.split("|")]
        if len(parts) < 3:
            return "Использование: !poll вопрос|вариант 1|вариант 2"
        question, options = parts[0], parts[1:]
        if len(question) > 120 or len(options) > 9 or any(len(option) > 60 for option in options):
            return "Слишком длинный опрос: вопрос ≤120, варианты ≤9 по 60 символов."
        seconds = max(30, min(600, self._config.chat_poll_seconds))
        poll = _Poll(
            question=question,
            options=options,
            ends=time.monotonic() + seconds,
        )
        self._polls[msg.platform] = poll
        lines = [f"📊 **{question}** (голосуем цифрой, {seconds} сек):"]
        for index, option in enumerate(options, start=1):
            lines.append(f"{_VOTE_EMOJI[index]} {option}")
        return "\n".join(lines)


def _parse_stake(text: str, *, default: int) -> int:
    token = text.split()[0] if text.split() else ""
    if not token.isdigit():
        return default
    return max(1, min(_MAX_STAKE, int(token)))


_ALIASES: dict[str, str] = {
    "discord": "discord", "дискорд": "discord", "дс": "discord",
    "donate": "donate", "донат": "donate",
    "youtube": "youtube", "ютуб": "youtube",
    "game": "game", "игра": "game",
    "signals": "signals", "сигналы": "signals",
    "rewards": "rewards", "награды": "rewards",
    "callsign": "callsign", "позывной": "callsign",
    "ping": "ping", "пинг": "ping",
    "uptime": "uptime", "аптайм": "uptime", "эфир": "uptime", "live": "uptime",
    "links": "links", "ссылки": "links", "ссылка": "links",
    "schedule": "schedule", "расписание": "schedule",
    "top": "top", "топ": "top", "лидерборд": "top",
    "bal": "bal", "balance": "bal", "баланс": "bal", "монеты": "bal", "coins": "bal", "кэш": "bal",
    "slots": "slots", "слоты": "slots", "слот": "slots", "казино": "slots",
    "flip": "flip", "монетка": "flip", "coin": "flip", "флип": "flip",
    "8ball": "8ball", "шар": "8ball", "шарик": "8ball",
    "so": "so", "shoutout": "so",
    "poll": "poll", "опрос": "poll",
    "help": "help", "помощь": "help", "хелп": "help", "команды": "help",
}

_COMMANDS: dict[str, Callable[..., Awaitable[str | None]]] = {
    "discord": ChatCommandsService._cmd_discord,
    "donate": ChatCommandsService._cmd_donate,
    "youtube": ChatCommandsService._cmd_youtube,
    "game": ChatCommandsService._cmd_game,
    "signals": ChatCommandsService._cmd_signals,
    "rewards": ChatCommandsService._cmd_rewards,
    "callsign": ChatCommandsService._cmd_callsign,
    "ping": ChatCommandsService._cmd_ping,
    "help": ChatCommandsService._cmd_help,
    "uptime": ChatCommandsService._cmd_uptime,
    "links": ChatCommandsService._cmd_links,
    "schedule": ChatCommandsService._cmd_schedule,
    "bal": ChatCommandsService._cmd_bal,
    "top": ChatCommandsService._cmd_top,
    "slots": ChatCommandsService._cmd_slots,
    "flip": ChatCommandsService._cmd_flip,
    "8ball": ChatCommandsService._cmd_8ball,
    "so": ChatCommandsService._cmd_so,
    "poll": ChatCommandsService._cmd_poll,
}

_MODERATOR_COMMANDS = {"so", "poll"}
