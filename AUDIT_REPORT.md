# Глубокий аудит `discord-mega-bot`

## Что исправлено

- Исправлен owner-only error path: используется `commands.NotOwner`, добавлено понятное сообщение в Discord.
- Убрана двойная глобальная синхронизация slash-команд при отсутствии `GUILD_ID`.
- Розыгрыши выбирают победителей через `secrets.SystemRandom` без повторов.
- Исправлена кнопка подтверждения: вместо отсутствующего в `discord.py` `disable_all_items()` используется безопасное отключение всех controls.
- Убраны runtime-`assert` из пользовательских команд, views, startup wiring и web-панели; вместо них добавлены контролируемые ответы или `RuntimeError`.
- Тикеты теперь откатывают частично созданный канал/запись при ошибке, перематывают файл транскрипта при fallback-отправке и отменяют фоновые delete-задачи при выгрузке cog.
- Усилены проверки музыкального плеера и каналов уведомлений.
- Музыка получила перемешивание и удаление треков из очереди, корректные ответы для pause/resume и graceful shutdown голосовых плееров.
- Напоминания теперь можно создавать и управлять ими прямо из личных сообщений.
- Опросы и розыгрыши защищены от завершения с другого сервера; добавлена очистка сиротских записей при сбое публикации.
- Добавлена команда `/health` с диагностикой Discord, SQLite, latency, cog/voice-состояния и включённых модулей.
- Внешние интеграции переведены на общий retry-aware API-клиент: таймауты, повтор временных ошибок, `Retry-After`, прокси и единый User-Agent настраиваются через Config.
- API-клиент дополнен ограничением параллелизма, circuit breaker и диагностическими метриками по сервисам.
- Исправлена передача прокси в aiohttp: прокси задаётся на каждый запрос, а не как неподдерживаемый аргумент `ClientSession`.
- Gemini также использует общий API-клиент, поэтому AI-запросы получили те же таймауты, retry и proxy-настройки.
- Добавлены миграции SQLite, integrity check, консистентный backup через SQLite backup API и lease-claim для напоминаний, scheduler и giveaways.
- Веб-панель получила RBAC `owner`/`admin`/`moderator`/`viewer`, endpoint сессии и сохраняемый аудит изменяющих действий.
- Для password-сессий панели добавлена CSRF-защита изменяющих запросов; `/api/metrics` показывает состояние API-клиентов и панели.
- Добавлен защищённый Prometheus endpoint `/metrics` с API retries/failures/circuit и показателями панели.
- В single-server режиме панель при наличии `GUILD_ID` использует именно настроенный сервер, а не первый сервер из cache.
- SQLite настроен для WAL single-server deployment: busy timeout, `synchronous=NORMAL`, memory temp store и `PRAGMA optimize`.
- Добавлен опциональный Discord OAuth2-вход с проверкой членства и Discord permissions на сервере бота.
- Для панели добавлена поддержка Argon2-хэшей (`PANEL_*_PASSWORD_HASH`); plaintext-переменные сохранены только для обратной совместимости.
- Добавлена единая moderation-case история с командами `/case` и `/cases`.
- AutoMod получил опциональный anti-raid режим: порог массового входа, автоматический slowmode с восстановлением и фильтр возраста аккаунта.
- Музыка получила сохраняемые плейлисты `/music playlist save|load|list|delete` с лимитом 100 треков и обновлением stream URL при загрузке.
- Музыка дополнена импортом YouTube Playlist, `seek` и голосованием `/music skipvote`.
- Добавлена история прослушивания `/music history` с хранением последних 500 записей на сервер.
- Добавлена Spotify Client Credentials интеграция: треки и публичные плейлисты превращаются в поисковые запросы для yt-dlp.
- Добавлен безопасный CLI restore-flow `scripts/restore_db.py`: backup проверяется до замены, текущая БД сохраняется в `.before-restore-*.bak`.
- Backup SQLite теперь пишется атомарно во временный файл, проверяется `integrity_check`, создаётся автоматически после старта и чистится по retention.
- Первый автоматический backup запускается после bootstrap и регистрации persistent views, чтобы не блокировать стартовые запросы SQLite.
- Добавлены Windows-friendly `scripts/preflight.py`, `scripts/check_windows.ps1/.bat` и генератор Argon2-хэшей для безопасного запуска без ручной диагностики.
- Добавлен dual-backend слой PostgreSQL: `DATABASE_URL`, asyncpg pool, финальная схема/индексы, placeholder translation для существующих репозиториев и `pg_dump` backup; SQLite остаётся backend по умолчанию.
- Добавлен переносчик `scripts/migrate_sqlite_to_postgres.py` с защитой от непустой целевой БД, копированием всех таблиц и восстановлением sequence ID; в Compose добавлен опциональный профиль PostgreSQL.
- Текущая музыкальная очередь теперь сохраняется в SQLite при изменениях и shutdown, а при следующем использовании восстанавливается с обновлением ссылок.
- Для AutoMod добавлены regex-исключения и управляемый lockdown через `/api/automod/lockdown` с автоматическим восстановлением прав.
- Аналитика сообщений теперь сохраняется в SQLite, доступна через `/api/analytics`, экспортируется JSON/CSV и отдаётся live-клиентам через `/ws/analytics`.
- Безопаснее обработаны динамические имена колонок настроек: допускаются только поля из фиксированного whitelist.
- Добавлены регрессионные тесты для owner-only ошибок и интерактивных views.

## Проверки

- `pytest`: **110 passed**
- `ruff check`: **OK**
- Python compileall: **OK**
- JavaScript parse + DOM smoke: **OK**
- shell syntax checks: **OK**
- `pip check`: **OK**
- `pip-audit`: **No known vulnerabilities**
- `mypy`: **OK** для всех 142 Python-файлов проекта (`mypy app rewrite --no-incremental`) и для configured gate.
- Bandit: **0 medium / 0 high**; оставшиеся low — в основном намеренные graceful-fallback места и false positives.

Docker-образ в текущем окружении не собирался: Docker CLI/daemon недоступен. Исходники и Dockerfile проверены отдельно.