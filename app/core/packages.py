"""Контейнер на каждый пакет: дерево DI повторяет структуру исходников.

Каждый Python-пакет под ``app/`` получает собственный :class:`DependencyContainer`.
Родитель по умолчанию — контейнер родительского пакета; пакет может переопределить
подключение в своём ``di.py``:

    PARENT = "app.services"             # контейнер, в который мы включаемся как ребёнок
    DENIED = frozenset({"db"})          # ключи, которые этот слой не резолвит
    def register(container) -> None:    # регистрация локальных компонентов пакета

Как пакет-модуль из Node.js-порта подключается к боту: кладётся в ``app/…/new_module/``
с собственным ``di.py`` — контейнер создаётся автоматически, регистрация локальная,
зависимости резолвятся вверх по цепочке к общим сервисам.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from app.core.container import DependencyContainer

TYPE_ALIAS_SUFFIXES = 0


class PackageContainers:
    """Реестр контейнеров по именам пакетов с поиском владельца модуля."""

    def __init__(self, by_module: dict[str, DependencyContainer]) -> None:
        self._by_module = by_module

    def __iter__(self):
        return iter(self._by_module.items())

    def __len__(self) -> int:
        return len(self._by_module)

    def __contains__(self, module: str) -> bool:
        return module in self._by_module

    def __getitem__(self, module: str) -> DependencyContainer:
        return self._by_module[module]

    def modules(self) -> tuple[str, ...]:
        return tuple(self._by_module)

    def container_for(self, module_name: str) -> DependencyContainer | None:
        """Контейнер самого глубокого пакета-владельца модуля (или ``None``)."""
        parts = module_name.split(".")
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if candidate in self._by_module:
                return self._by_module[candidate]
        return None


def _package_di(module_name: str):
    """Загружает ``di.py`` пакета (или возвращает ``None``)."""
    try:
        return importlib.import_module(f"{module_name}.di")
    except ModuleNotFoundError:
        return None


def _collect_packages(root_module: str) -> list[str]:
    root = importlib.import_module(root_module)
    packages: list[str] = []
    for info in pkgutil.walk_packages(root.__path__, prefix=f"{root_module}."):
        if info.ispkg:
            packages.append(info.name)
    return packages


def build_package_containers(
    root_module: str = "app",
    *,
    supplied: dict[str, dict[str, Any]] | None = None,
) -> PackageContainers:
    """Собирает дерево контейнеров «пакет → контейнер» и регистрирует компоненты.

    ``supplied`` — готовые экземпляры для конкретных пакетов:
        {"app.core": {"bot": bot, "config": config}, "app.data": {"db": db}}
    Для каждого экземпляра дополнительно регистрируются алиасы по типу
    (``MegaBot``/``app.core.bot.MegaBot`` и т.п.), чтобы инъекция работала по аннотациям.
    """
    root_container = DependencyContainer()
    by_module: dict[str, DependencyContainer] = {"app": root_container}

    packages = sorted(_collect_packages(root_module), key=lambda name: (name.count("."), name))
    overrides: dict[str, tuple[str, frozenset[str], bool]] = {}
    for name in packages:
        di = _package_di(name)
        parent = ".".join(name.split(".")[:-1])
        denied: frozenset[str] = frozenset()
        if di is not None:
            parent = getattr(di, "PARENT", parent) or parent
            denied = frozenset(getattr(di, "DENIED", ()) or ())
        overrides[name] = (parent, denied, di is not None)

    created: set[str] = {"app"}
    pending = dict(overrides)
    while pending:
        progressed = False
        for name in list(pending):
            parent, denied, has_di = pending[name]
            if parent not in created:
                continue
            by_module[name] = DependencyContainer(parent=by_module[parent], denied=denied)
            created.add(name)
            del pending[name]
            progressed = True
        if not progressed:
            missing = ", ".join(pending)
            raise RuntimeError(f"Контейнеры пакетов не могут быть созданы (неопределённый родитель): {missing}")

    if supplied:
        for module, instances in supplied.items():
            target = by_module[module]
            for name, instance in instances.items():
                target.supply(name, instance)
                for alias in _type_aliases(instance):
                    target.alias(alias, name)

    for name, (_, _, has_di) in overrides.items():
        if not has_di:
            continue
        register = getattr(_package_di(name), "register", None)
        if register is not None:
            register(by_module[name])

    return PackageContainers(by_module)


def _type_aliases(instance: Any) -> tuple[str, ...]:
    cls = type(instance)
    aliases: list[str] = [cls.__name__]
    module_path = f"{cls.__module__}.{cls.__qualname__}"
    if module_path not in aliases:
        aliases.append(module_path)
    return tuple(aliases)


__all__ = ["PackageContainers", "build_package_containers"]
