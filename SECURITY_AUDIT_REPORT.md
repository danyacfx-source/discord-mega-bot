# Отчёт по аудиту безопасности — discord-mega-bot

**Дата**: 10.10.2026  
**Коммит**: `b53c69e` (ветка `main`)  
**Статус**: все найденные уязвимости исправлены, 436 тестов пройдены

---

## Что было сделано

Полный аудит кодовой базы бота. Найдено и исправлено **14 уязвимостей** разных уровней — от критичных (полный обход аутентификации панели) до низких (утечка данных между гильдиями).

---

## Критичные (C1)

### C1 — Обход аутентификации веб-панели при OAuth

**Файл**: `app/core/webpanel/webpanel.py`, `app/core/webpanel/auth.py`

**Суть**: При включённом OAuth (вход через Discord) статический токен `owner` всё равно инжектился в HTML каждой страницы панели. Любой посетитель мог скопировать его из исходного кода и получить полный доступ к панели без логина.

**Что исправлено**:
- Статический токен теперь генерируется **только** для localhost без пароля и без OAuth
- При OAuth или пароле токен = `None`, в HTML инжектится пустая строка
- CSRF-защита теперь обязательна и для OAuth-сессий (раньше — только для парольных)
- Проверка сессий работает в OAuth-режиме (раньше — только при пароле)

---

## Высокие (H1–H5)

### H1 — Доступ к каналам чужих гильдий

**Файл**: `app/core/webpanel/core_api.py`

**Суть**: Panel-admin одной гильдии мог писать сообщения, редактировать и удалять их в каналах **других** гильдий, куда добавлен бот.

**Исправление**: `_resolve_channel` теперь резолвит каналы только через основную гильдию бота.

---

### H2 — Избыточные права panel-admin

**Файл**: `app/core/webpanel/auth.py`

**Суть**: Роль `MANAGE_GUILD` (управление сервером) давала полный panel-admin — доступ к дампу БД, отправке от имени бота, переконфигурации.

**Исправление**:
- Panel-admin теперь только для Discord **ADMINISTRATOR** (бит 3)
- `MANAGE_GUILD` и `MANAGE_MESSAGES` → уровень **moderator**

---

### H3 — Делегирование ролей выше своей

**Файл**: `app/core/webpanel/guild_api.py`

**Суть**: Пользователь с `MANAGE_GUILD` (который через H2 получал panel-admin) мог назначать любые роли, включая Administrator.

**Исправление**: Смягчено фиксом H2 — panel-admin теперь только реальный Discord-админ, который и так может назначать роли.

---

### H4 — Утечка overlay-токена

**Файл**: `app/core/webpanel/tools_api.py`

**Суть**: Полный overlay-секрет (для OBS-виджетов) отдавался любой роли viewer.

**Исправление**:
- Полный токен — только **admin/owner**
- Viewer получает маску `tok_…last4` + флаг `token_redacted: true`

---

### H5 — Утечка кредов AI-прокси

**Файл**: `app/core/webpanel/profiles_api.py`

**Суть**: URL AI-прокси мог содержать `user:pass@host` — пароль прокси отдавался в открытом виде.

**Исправление**: `_redact_proxy()` отдаёт только `хост:порт` без кредов.

---

## Средние (M1–M7)

### M1 — IDOR плейлистов

**Файл**: `app/db/music_repository.py`, `app/services/music_service.py`, `app/cogs/music/music.py`

**Суть**: Любой пользователь мог перезаписать или удалить чужой плейлист по имени.

**Исправление**:
- `save_playlist` — перезапись только своего плейлиста
- `delete_playlist` — фильтр по `created_by`

---

### M2 — Модератор мог банить/кикать

**Файл**: `app/core/webpanel/routes.py`

**Суть**: Panel-роль `moderator` (Manage_Messages) могла банить, кикать, размучивать.

**Исправление**: `ban`, `kick`, `unban`, `timeout` → роль **admin**.

---

### M3 — Транскрипты тикетов у viewer

**Файл**: `app/core/webpanel/routes.py`

**Суть**: Список тикетов и их транскрипты (содержимое переписки) были доступны минимальной роли viewer.

**Исправление**: Оба эндпоинта → роль **moderator**.

---

### M4 — Слабые коды донатов

**Файл**: `app/services/donation_service.py`

**Суть**: Коды активации (`VIP-XXXX`) содержали 32 бита энтропии — перебором можно было получить роль спонсора.

**Исправление**: `token_hex(8)` — 64 бита вместо 32.

---

### M5 — Bridge-запросы без аудита

**Файл**: `app/core/webpanel/auth.py`

**Суть**: Запросы с bridge-токеном (для WARDOGS) проходили мимо CSRF, ролей и аудита. Утечка bridge-токена давала невидимые деструктивные действия.

**Исправление**: Bridge-запросы пишутся в `_record_admin_audit`.

---

### M6 — Origin localhost для публичной панели

**Файл**: `app/core/webpanel/auth.py`

**Суть**: Любой локальный приложение мог слать кросс-ориджин-запросы к публичной панели.

**Исправление**: localhost-Origin доверен только если сама панель запущена локально.

---

### M7 — Слабый гейт kick-модерации

**Файл**: `app/cogs/streams/kick.py`

**Суть**: Kick-модерация (бан/пост в чат от имени стримера) открывалась при `Manage_Messages`.

**Исправление**: Требуется `Manage_Guild` или Administrator.

---

## Низкие (LOW)

### Дни рождения — утечка между гильдиями

**Файл**: `app/db/birthdays_repository.py`, `app/db/database.py`, `app/db/postgres_database.py`, `app/services/birthday_service.py`, `app/cogs/birthdays/birthdays.py`, `app/core/webpanel/profiles_api.py`

**Суть**: Даты рождения не были скоуплены по гильдиям — пользователь, установивший дату в одной гильдии, появлялся в календаре всех остальных.

**Исправление**:
- Схема: `PRIMARY KEY (user_id, guild_id)` вместо `user_id`
- Миграция 10 (SQLite + PostgreSQL)
- Все запросы (repo/service/cog/panel) скоупятся по `guild_id`
- Старые строки переносятся с `guild_id=0` (скрыты, нужен re-set)

### Прочее

- `/metrics` (Prometheus) → роль **admin**
- AI-прокси: креды вырезаются из ответа API (H5)

---

## Верификация

| Проверка | Результат |
|----------|-----------|
| `py_compile` (18 файлов) | OK |
| `ruff check` | All checks passed |
| `pytest` (полный сьют) | **436 passed, 1 skipped** |

---

## Затронутые файлы (19)

```
app/cogs/birthdays/birthdays.py
app/cogs/music/music.py
app/cogs/streams/kick.py
app/core/webpanel/auth.py
app/core/webpanel/core_api.py
app/core/webpanel/profiles_api.py
app/core/webpanel/routes.py
app/core/webpanel/tools_api.py
app/core/webpanel/webpanel.py
app/db/birthdays_repository.py
app/db/database.py
app/db/music_repository.py
app/db/postgres_database.py
app/services/birthday_service.py
app/services/donation_service.py
app/services/music_service.py
tests/test_database_hardening.py
tests/test_music_player.py
tests/test_port.py
```

---

## Статус деплоя

- Ветка `main`: `b53c69e` (все фиксы) — **запушен**
- Ветка `deploy`: `650b983` (до фиксов) — **не обновлена** (по решению Operator)
- На хосте: `650b983` — фиксы ещё не активны

Для активации фиксов на хосте: обновить `deploy` до `main` и перезапустить бота.
