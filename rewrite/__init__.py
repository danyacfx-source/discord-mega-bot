"""Legacy-эксперимент с альтернативной сборкой графа зависимостей.

Рабочая точка входа — ``main.py`` и ``app.core.composition.assemble``.
Пакет ``rewrite`` сохранён только как историческая reference-реализация для
сравнения подходов к composition root. Новые возможности в него не добавлять.
Подробности и критерии удаления: ``rewrite/README.md``.

Вместо дерева ``DependencyContainer``/``PackageContainers`` (app/core/container.py,
app/core/packages.py) весь граф зависимостей собирается вручную в одном месте —
composition root (rewrite/composition.py). Потребители (коги) по-прежнему получают
готовые сервисы инъекцией, но источник байдингов теперь — читаемая функция, а
не рефлексия по именам.

Границы слоёв описываются Protocol-контрактами в rewrite/ports.py; реальные
классы из app/ объявляются их адаптерами (rewrite/adapters.py) и проверяются
структурно (isinstance по runtime_checkable-портам).
"""
