"""Persistent cross-platform stream voting without Twitch/Kick write credentials.

One vote per (platform, username). Votes are stored in KV on each change
so an active poll and its results survive Docker redeploys.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Sequence
from typing import Any

from app.services.kv_service import KvService

_KEY = "stream:live-vote:v1"
_MAX_VOTERS = 2000
_CHAT_VOTE = re.compile(r"^!(?:vote|голос|v)\s+([1-5])\s*$", re.IGNORECASE)


class VoteError(ValueError):
    """Bad input or an incompatible poll state."""


class LiveVoteService:
    def __init__(self, kv: KvService) -> None:
        self._kv = kv
        self._state: dict[str, Any] | None = None
        self._loaded = False
        self._lock = asyncio.Lock()

    async def _load(self) -> None:
        if self._loaded:
            return
        raw = await self._kv.get(_KEY)
        if raw:
            try:
                state = json.loads(raw)
                if (
                    isinstance(state, dict)
                    and isinstance(state.get("question"), str)
                    and isinstance(state.get("options"), list)
                    and 2 <= len(state["options"]) <= 5
                    and isinstance(state.get("votes"), dict)
                    and state.get("status") in {"active", "closed"}
                ):
                    self._state = state
            except (ValueError, TypeError):
                pass
        self._loaded = True

    async def _store(self) -> None:
        if self._state is None:
            await self._kv.delete(_KEY)
        else:
            await self._kv.set(_KEY, json.dumps(self._state, ensure_ascii=False, separators=(",", ":")))

    async def _expire(self) -> None:
        state = self._state
        if state is not None and state["status"] == "active" and time.time() >= state["ends_at"]:
            state["status"] = "closed"
            await self._store()

    @staticmethod
    def _public(state: dict[str, Any] | None) -> dict[str, Any] | None:
        if state is None:
            return None
        counts = [0] * len(state["options"])
        for choice in state["votes"].values():
            if type(choice) is int and 0 <= choice < len(counts):
                counts[choice] += 1
        total = sum(counts)
        best = max(counts, default=0)
        leaders = [
            index + 1 for index, count in enumerate(counts)
            if best > 0 and count == best
        ]
        return {
            "question": state["question"],
            "options": list(state["options"]),
            "counts": counts,
            "total": total,
            "status": state["status"],
            "ends_at": state["ends_at"],
            "leaders": leaders if state["status"] == "closed" else [],
            "command": "!vote 1",
        }

    async def status(self) -> dict[str, Any] | None:
        async with self._lock:
            await self._load()
            await self._expire()
            return self._public(self._state)

    async def start(self, question: Any, options: Any, seconds: Any) -> dict[str, Any]:
        q = " ".join(question.split())[:140] if isinstance(question, str) else ""
        if not q:
            raise VoteError("Напиши вопрос голосования")
        if not isinstance(options, (list, tuple)) or not 2 <= len(options) <= 5:
            raise VoteError("Нужно от 2 до 5 вариантов")
        cleaned = [" ".join(item.split())[:70] if isinstance(item, str) else "" for item in options]
        if not all(cleaned) or len({option.casefold() for option in cleaned}) != len(cleaned):
            raise VoteError("Варианты не должны быть пустыми или одинаковыми")
        if type(seconds) is not int or not 30 <= seconds <= 3600:
            raise VoteError("Длительность от 30 до 3600 секунд")
        async with self._lock:
            await self._load()
            await self._expire()
            if self._state is not None and self._state["status"] == "active":
                raise VoteError("Сначала заверши текущее голосование")
            self._state = {
                "question": q,
                "options": cleaned,
                "votes": {},
                "status": "active",
                "ends_at": time.time() + seconds,
            }
            await self._store()
            result = self._public(self._state)
            assert result is not None
            return result

    async def finish(self) -> dict[str, Any] | None:
        async with self._lock:
            await self._load()
            if self._state is not None and self._state["status"] == "active":
                self._state["status"] = "closed"
                await self._store()
            return self._public(self._state)

    async def clear(self) -> None:
        async with self._lock:
            await self._load()
            self._state = None
            await self._store()

    async def register_message(self, platform: str, username: str, content: str) -> bool:
        """Only explicit commands count; a read-only IRC session can vote."""
        if platform not in {"twitch", "kick"} or not username:
            return False
        match = _CHAT_VOTE.fullmatch(content.strip())
        if match is None:
            return False
        choice = int(match.group(1)) - 1
        voter_key = platform + ":" + username.casefold()[:64]
        async with self._lock:
            await self._load()
            await self._expire()
            state = self._state
            if state is None or state["status"] != "active" or choice >= len(state["options"]):
                return False
            votes: dict[str, int] = state["votes"]
            if voter_key not in votes and len(votes) >= _MAX_VOTERS:
                return False
            if votes.get(voter_key) == choice:
                return True
            votes[voter_key] = choice
            await self._store()
            return True
