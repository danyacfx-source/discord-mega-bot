"""Тренд и спарклайн зрителей из сэмплов истории стрима (KV).

Сэмплы кладёт ``StreamSessionStore.capture``: ``{"t": iso, "v": viewers}``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

_SPARK_STEPS = "▁▂▃▄▅▆▇█"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        from datetime import UTC

        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def trend(history: Any, minutes: int = 10) -> int | None:
    """Δ зрителей за последние N минут; None если сэмплов за окно нет."""
    if not isinstance(history, list) or len(history) < 2:
        return None
    latest = history[-1]
    if not isinstance(latest, dict):
        return None
    latest_t = _parse_dt(latest.get("t"))
    if latest_t is None:
        return None
    border = latest_t.timestamp() - minutes * 60
    for sample in reversed(history[:-1]):
        if not isinstance(sample, dict):
            continue
        sample_t = _parse_dt(sample.get("t"))
        if sample_t is None or sample_t.timestamp() > border:
            continue
        try:
            return int(latest.get("v") or 0) - int(sample.get("v") or 0)
        except (TypeError, ValueError):
            return None
    return None


def sparkline(history: Any, *, limit: int = 24) -> str | None:
    """Юникод-график зрителей (▁▂▃▄▅▆▇█); None если сэмплов меньше двух."""
    if not isinstance(history, list):
        return None
    values: list[int] = []
    for sample in history[-limit:]:
        if not isinstance(sample, dict):
            continue
        try:
            values.append(int(sample.get("v") or 0))
        except (TypeError, ValueError):
            continue
    if len(values) < 2:
        return None
    lo, hi = min(values), max(values)
    if hi == lo:
        return _SPARK_STEPS[0] * len(values)
    span = hi - lo
    return "".join(_SPARK_STEPS[int((v - lo) / span * (len(_SPARK_STEPS) - 1))] for v in values)
