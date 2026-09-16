"""Ошибки DI-контейнера."""


class ResolutionError(RuntimeError):
    """Компонент не зарегистрирован или параметр не удалось разрешить."""

    def __init__(self, component: str, param: str | None = None) -> None:
        self.component = component
        self.param = param
        if param:
            super().__init__(f"Контейнер: не удалось разрешить «{param}» для {component}")
        else:
            super().__init__(f"Контейнер: компонент не зарегистрирован: {component}")


class CycleError(RuntimeError):
    """В графе зависимостей обнаружен цикл."""

    def __init__(self, chain: list[str]) -> None:
        self.chain = chain
        super().__init__("Контейнер: циклическая зависимость: " + " → ".join(chain + [chain[0]]))
