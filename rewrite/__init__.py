"""Rewrite проекта: та же бизнес-логика, но без DI-контейнера.

Вместо дерева ``DependencyContainer``/``PackageContainers`` (app/core/container.py,
app/core/packages.py) весь граф зависимостей собирается вручную в одном месте —
composition root (rewrite/composition.py). Потребители (коги) по-прежнему получают
готовые сервисы инъекцией, но источник байдингов теперь — читаемая функция, а
не рефлексия по именам.

Границы слоёв описываются Protocol-контрактами в rewrite/ports.py; реальные
классы из app/ объявляются их адаптерами (rewrite/adapters.py) и проверяются
структурно (isinstance по runtime_checkable-портам).
"""
