"""Генерация PNG-карточки приветствия (Pillow).

Тёмный градиентный фон, круглый аватар, имя участника и счётчик человек.
Шрифты: системные (Windows Arial / Linux DejaVu), иначе встроенный в Pillow.

Внешний вид задаётся пресетом ``WelcomePreset`` (хранится в KV под ключом
``welcome_preset``, редактируется в вебпанели); дефолтный пресет полностью
повторяет прежний захардкоженный вид. Тексты поддерживают плейсхолдеры
``{name}``, ``{guild}``, ``{count}``.
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import asdict, dataclass, fields

from PIL import Image, ImageDraw, ImageFont

_WIDTH = 800
_HEIGHT = 300

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_COLOR_FIELDS = ("bg_top", "bg_bottom", "title_color", "name_color", "text_color", "ring_color")
_TEXT_FIELDS = ("title", "subtitle")


def _hex_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _clean(name: str, value: object, default: object) -> object:
    if name in _COLOR_FIELDS:
        return value if isinstance(value, str) and _HEX.match(value) else default
    if name in _TEXT_FIELDS:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped[:120]
        return default
    if name == "avatar_size":
        try:
            return max(120, min(240, int(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
    if name == "font_scale":
        try:
            return round(max(0.7, min(1.5, float(value))), 2)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
    return default


@dataclass(frozen=True, slots=True)
class WelcomePreset:
    bg_top: str = "#1e2444"
    bg_bottom: str = "#3d2a63"
    title: str = "Добро пожаловать,"
    title_color: str = "#ffffff"
    name_color: str = "#ffd678"
    subtitle: str = "{guild}  •  {count}-й участник"
    text_color: str = "#ced4e6"
    ring_color: str = "#ffffff"
    avatar_size: int = 180
    font_scale: float = 1.0

    @classmethod
    def from_json(cls, raw: str | dict[str, object] | None) -> WelcomePreset:
        """Собирает пресет из JSON-строки или dict; мусор и неизвестные поля — дефолт."""
        data: dict[str, object] = {}
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                data = parsed
        elif isinstance(raw, dict):
            data = raw
        defaults = cls()
        values = {f.name: _clean(f.name, data.get(f.name, getattr(defaults, f.name)), getattr(defaults, f.name)) for f in fields(cls)}
        return cls(**values)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def _fmt(template: str, *, name: str, guild: str, count: int) -> str:
    try:
        return template.format(name=name, guild=guild, count=count)
    except (KeyError, IndexError, ValueError):
        return template


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        f"C:/Windows/Fonts/arial{'bd' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans{'-Bold' if bold else '-Regular'}.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # старый Pillow без параметра size
        return ImageFont.load_default()


def _gradient(top: str, bottom: str) -> Image.Image:
    """Вертикальный градиент из двух hex-цветов (300 строк — быстро)."""
    start = _hex_rgb(top)
    end = _hex_rgb(bottom)
    image = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = image.load()
    for y in range(_HEIGHT):
        t = y / (_HEIGHT - 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(start, end))
        for x in range(_WIDTH):
            pixels[x, y] = color
    return image


def make_placeholder_avatar(name: str, *, bg: str = "#37407a") -> bytes:
    """256×256 PNG-заглушка с силуэтом — без битой картинки и зависимости от шрифта."""
    if not _HEX.match(bg):
        bg = "#37407a"
    image = Image.new("RGB", (256, 256), _hex_rgb(bg))
    draw = ImageDraw.Draw(image)
    draw.ellipse((82, 42, 174, 134), fill=(255, 255, 255))
    draw.rounded_rectangle((42, 122, 214, 236), radius=58, fill=(255, 255, 255))
    draw.ellipse((18, 18, 38, 38), fill=(255, 255, 255))
    draw.ellipse((208, 58, 232, 82), fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def render_welcome_card(
    *,
    avatar_png: bytes,
    display_name: str,
    member_count: int,
    guild_name: str,
    preset: WelcomePreset | None = None,
) -> bytes:
    """Собирает карточку и отдаёт PNG-байты; ``preset=None`` — прежний вид."""
    p = preset or WelcomePreset()
    scale = p.font_scale
    size = p.avatar_size
    card = _gradient(p.bg_top, p.bg_bottom)

    avatar = Image.open(io.BytesIO(avatar_png)).convert("RGB").resize(
        (size, size), Image.Resampling.LANCZOS
    )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)

    x0, y0 = 40, (_HEIGHT - size) // 2
    card.paste(avatar, (x0, y0), mask)

    draw = ImageDraw.Draw(card)
    ring = _hex_rgb(p.ring_color)
    draw.ellipse(
        (x0 - 4, y0 - 4, x0 + size + 3, y0 + size + 3),
        outline=ring,
        width=4,
    )

    name = display_name if len(display_name) <= 22 else display_name[:21] + "…"
    guild = guild_name if len(guild_name) <= 26 else guild_name[:25] + "…"
    title_text = _fmt(p.title, name=name, guild=guild, count=member_count)[:60]
    subtitle = _fmt(p.subtitle, name=name, guild=guild, count=member_count)[:60]

    title_size = int(30 * scale)
    name_size = int(46 * scale)
    sub_size = int(22 * scale)
    block = title_size + 8 + name_size + 16 + sub_size + 10
    text_y = (_HEIGHT - block) // 2
    text_x = x0 + size + 40

    draw.text((text_x, text_y), title_text, font=_font(title_size, bold=True), fill=_hex_rgb(p.title_color))
    text_y += title_size + 8
    draw.text((text_x, text_y), name, font=_font(name_size, bold=True), fill=_hex_rgb(p.name_color))
    text_y += name_size + 16
    draw.text((text_x, text_y), subtitle, font=_font(sub_size), fill=_hex_rgb(p.text_color))

    buffer = io.BytesIO()
    card.save(buffer, format="PNG")
    return buffer.getvalue()
