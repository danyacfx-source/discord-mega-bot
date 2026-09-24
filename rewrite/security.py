"""Безопасность rewrite: модель угроз и проверяемые инварианты склейки.

Смена архитектуры (DI-контейнер → composition root) НЕ меняет модель безопасности:
проверка прав доступа, валидация данных и секреты живут в классах app/ и не
зависят от того, кто конструирует объекты. Вклад composition root — в том, что
вместо «волшебной» рефлексии по именам мы получаем одну читаемую сборку и можем
зафиксировать инварианты склейки, которые проверяются тестами:

    1. Привилегированные коги получают ровно те сервисы, что собраны в Root
       (подмена или missing-значение здесь означает дыру в авторизации).
    2. Rewrite не содержит секретов литералами — только чтение из Config (env).
    3. Rewrite не открывает новых сетевых поверхностей: вебпанель/оверлей
       слушают только на сконфигурированных адресах (webpanel.py / overlay.py),
       всё остальное — Discord WebSocket, как и раньше.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rewrite.root import Root

#: Коги, имеющие полномочия (модерация/автомод/настройка) → (атрибут кога, сервис в Root).
#: Оба индекса разрешены явно — «кого-то не в той роли» здесь не может пройти рефлексия.
PRIVILEGED_WIRING: dict[str, tuple[tuple[str, str], ...]] = {
    "Moderation": (("moderation", "moderation"), ("logging", "logging")),
    "Warns": (("moderation", "moderation"),),
    "AutoMod": (("settings", "settings"),),
    "Setup": (("settings", "settings"),),
}


def assert_wiring(root: Root) -> None:
    """Гарантирует, что привилегированные коги привязаны к реальным сервисам Root."""
    for cog_name, pairs in PRIVILEGED_WIRING.items():
        cog = root.bot.get_cog(cog_name)
        if cog is None:
            raise RuntimeError(f"привилегированный ког {cog_name} не загружен")
        for attr, svc in pairs:
            got = getattr(cog, attr, None)
            want = getattr(root.services, svc)
            if got is not want:
                raise RuntimeError(
                    f"пинниг {cog_name}.{attr} указывает не на root.services.{svc} "
                    f"(got {type(got).__name__})"
                )
