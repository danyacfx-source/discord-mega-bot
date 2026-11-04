"""Модель музыкального трека."""
from __future__ import annotations

from dataclasses import dataclass

from app.utils.time import format_duration


@dataclass(slots=True)
class Track:
    title: str
    url: str
    stream_url: str
    duration: int | None = None
    uploader: str | None = None
    thumbnail: str | None = None

    @property
    def duration_str(self) -> str:
        return format_duration(self.duration)

    def __str__(self) -> str:
        return self.title
