"""Лёгкий DI-контейнер: сборка графа зависимостей по именам и аннотациям.

Как работает разрешение параметра при сборке компонента:
  1. по имени параметра (например ``settings``);
  2. по аннотации — классу (``SettingsService``), его ``__name__`` или полному пути;
  3. если зависимость не найдена и параметр имеет значение по умолчанию — оно используется;
  4. иначе поднимается :class:`ResolutionError`.

Все зарегистрированные компоненты — синглтоны: первый резолв кешируется.
Циклы в графе обнаруживаются и превращаются в :class:`CycleError`.

Пример:
    container = DependencyContainer()
    container.supply("db", db)
    container.register_class(SettingsRepository)
    container.register_class(SettingsService)
    container.alias("settings", "SettingsService")
    settings = container.resolve("settings")  # репозиторий подтянулся сам
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from app.core.errors import CycleError, ResolutionError

T = TypeVar("T")

_UNRESOLVED = object()


def _is_injectable_type(value: type) -> bool:
    """Тип можно собирать из контейнера: пользовательские классы, не builtins/discord/api."""
    module = getattr(value, "__module__", "") or ""
    if module in ("builtins", "typing") or module.startswith(("typing.", "discord.")):
        return False
    return True


class _Provider:
    def resolve(self, container: DependencyContainer, stack: list[str]) -> Any:
        raise NotImplementedError


class _InstanceProvider(_Provider):
    def __init__(self, instance: Any) -> None:
        self.instance = instance

    def resolve(self, container: DependencyContainer, stack: list[str]) -> Any:
        return self.instance


class _FactoryProvider(_Provider):
    def __init__(self, factory: Callable[[], Any]) -> None:
        self.factory = factory

    def resolve(self, container: DependencyContainer, stack: list[str]) -> Any:
        return self.factory()


class _ClassProvider(_Provider):
    def __init__(self, cls: type) -> None:
        self.cls = cls

    def resolve(self, container: DependencyContainer, stack: list[str]) -> Any:
        kwargs = container._inject(self.cls, stack)
        try:
            return self.cls(**kwargs)
        except TypeError as exc:
            raise TypeError(
                f"Не удалось собрать {self.cls.__module__}.{self.cls.__qualname__}: "
                f"аргументы {', '.join(kwargs) or '—'}. {exc}"
            ) from exc


class DependencyContainer:
    """Реестр провайдеров с разрешением зависимостей и кешем синглтонов.

    Может иметь родителя: ребёнок сначала ищет у себя, затем делегирует вверх по цепочке.
    Аргумент ``denied`` запрещает разрешение конкретных ключей (границы слоёв).
    """

    def __init__(
        self,
        *,
        parent: DependencyContainer | None = None,
        denied: frozenset[str] = frozenset(),
    ) -> None:
        self._parent = parent
        self._denied = denied
        self._registry: dict[str, _Provider] = {}
        self._aliases: dict[str, str] = {}
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ регистрация

    def supply(self, key: str, instance: Any) -> None:
        """Зарегистрировать готовый экземпляр как синглтон."""
        self._registry[key] = _InstanceProvider(instance)

    def register(self, key: str, factory: Callable[..., Any]) -> None:
        """Зарегистрировать фабрику компонента."""
        self._registry[key] = _FactoryProvider(factory)

    def register_class(self, cls: type, *, aliases: tuple[str, ...] = ()) -> str:
        """Зарегистрировать класс: аргументы конструктора собираются из контейнера."""
        key = self._normalize(cls)
        self._registry[key] = _ClassProvider(cls)
        self.alias(cls.__name__, key)
        for alias in aliases:
            self.alias(alias, key)
        return key

    def alias(self, alias: str, target: str) -> None:
        """Имя-ссылка на другой компонент (разрешается при обращении)."""
        self._aliases[alias] = target

    # ------------------------------------------------------------------ разрешение

    def resolvable(self, key: Any) -> bool:
        key = self._normalize(key)
        if key in self._registry or key in self._aliases:
            return True
        if self._parent is not None:
            return self._parent.resolvable(key)
        return False

    def resolve(self, key: Any) -> Any:
        return self._resolve(key, stack=[])

    def build(self, cls_or_key: type[T] | str) -> T:
        """Синхронная сборка компонента (для когов и тестов)."""
        return self.resolve(cls_or_key)

    # ------------------------------------------------------------------ внутренне

    def _normalize(self, key: Any) -> str:
        if isinstance(key, str):
            return key
        if isinstance(key, type):
            return f"{key.__module__}.{key.__qualname__}"
        return f"{type(key).__module__}.{type(key).__qualname__}"

    def _resolve(self, key: Any, stack: list[str]) -> Any:
        normalized = self._normalize(key)

        if normalized in self._denied:
            raise ResolutionError(f"{normalized} (слой запрещает доступ к этому компоненту)")

        if normalized in self._aliases:
            return self._resolve(self._aliases[normalized], stack)

        if normalized in self._cache:
            return self._cache[normalized]

        if normalized in stack:
            raise CycleError(stack + [normalized])

        provider = self._registry.get(normalized)
        if provider is None:
            if self._parent is not None and not isinstance(key, type):
                try:
                    return self._parent._resolve(key, stack)
                except ResolutionError:
                    pass
            if isinstance(key, type) and _is_injectable_type(key):
                provider = _ClassProvider(key)
                self._registry[normalized] = provider
            else:
                raise ResolutionError(normalized)

        stack.append(normalized)
        try:
            instance = provider.resolve(self, stack)
        finally:
            stack.pop()

        self._cache[normalized] = instance
        return instance

    def _inject(self, cls: type, stack: list[str]) -> dict[str, Any]:
        signature = inspect.signature(cls)
        params = [p for p in signature.parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
        kwargs: dict[str, Any] = {}
        for param in params:
            resolved = self._try_resolve_param(param, stack)
            if resolved is _UNRESOLVED:
                if param.default is not inspect.Parameter.empty:
                    continue
                raise ResolutionError(f"{cls.__module__}.{cls.__qualname__}", param.name)
            kwargs[param.name] = resolved
        return kwargs

    def _try_resolve_param(self, param, stack: list[str]) -> Any:
        annotation = param.annotation

        candidates: list[Any] = [param.name]
        if annotation is not inspect.Parameter.empty:
            if isinstance(annotation, str):
                candidates.append(annotation)
            elif _is_injectable_type(annotation):
                candidates.append(annotation)
                candidates.append(annotation.__name__)
                candidates.append(f"{annotation.__module__}.{annotation.__qualname__}")

        last_error: Exception | None = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return self._resolve(candidate, stack)
            except ResolutionError as exc:
                last_error = exc
                continue
        if last_error is not None:
            return _UNRESOLVED
        return _UNRESOLVED


__all__ = ["DependencyContainer"]
