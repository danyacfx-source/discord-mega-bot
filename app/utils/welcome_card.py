"""Генерация PNG-карточки приветствия (Pillow).

Тёмный градиентный фон, круглый аватар, имя участника и счётчик человек.
Шрифты: системные (Windows Arial / Linux DejaVu), иначе встроенный в Pillow.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

_WIDTH = 800
_HEIGHT = 300
_AVATAR_SIZE = 180
_AVATAR_POS = (40, 60)


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    suffix = "Bold" if bold else ""
    candidates = [
        f"C:/Windows/Fonts/arial{'bd' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf",
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


def _gradient() -> Image.Image:
    """Вертикальный градиент #1e2444 → #3d2a63 (300 строк — быстро)."""
    top = (30, 36, 68)
    bottom = (61, 42, 99)
    image = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = image.load()
    for y in range(_HEIGHT):
        t = y / (_HEIGHT - 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(_WIDTH):
            pixels[x, y] = color
    return image


def render_welcome_card(
    *,
    avatar_png: bytes,
    display_name: str,
    member_count: int,
    guild_name: str,
) -> bytes:
    """Собирает карточку и отдаёт PNG-байты."""
    card = _gradient()

    avatar = Image.open(io.BytesIO(avatar_png)).convert("RGB").resize(
        (_AVATAR_SIZE, _AVATAR_SIZE), Image.Resampling.LANCZOS
    )
    mask = Image.new("L", (_AVATAR_SIZE, _AVATAR_SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, _AVATAR_SIZE - 1, _AVATAR_SIZE - 1), fill=255)
    card.paste(avatar, _AVATAR_POS, mask)

    draw = ImageDraw.Draw(card)
    x0, y0 = _AVATAR_POS
    ring = (255, 255, 255)
    draw.ellipse(
        (x0 - 4, y0 - 4, x0 + _AVATAR_SIZE + 3, y0 + _AVATAR_SIZE + 3),
        outline=ring,
        width=4,
    )

    text_x = x0 + _AVATAR_SIZE + 40
    name = display_name if len(display_name) <= 22 else display_name[:21] + "…"
    draw.text((text_x, 70), "Добро пожаловать,", font=_font(30, bold=True), fill=ring)
    draw.text((text_x, 115), name, font=_font(46, bold=True), fill=(255, 214, 120))
    guild = guild_name if len(guild_name) <= 26 else guild_name[:25] + "…"
    draw.text(
        (text_x, 195),
        f"{guild}  •  {member_count}-й участник",
        font=_font(22),
        fill=(206, 212, 230),
    )

    buffer = io.BytesIO()
    card.save(buffer, format="PNG")
    return buffer.getvalue()
