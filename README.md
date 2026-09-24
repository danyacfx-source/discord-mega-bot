# Discord Mega Bot

Дискорд-бот по «ахуеннейшим стандартам качества»: модульная архитектура, слой данных и сервисов, набор когов по категориям.

## Возможности

- **Модерация**: kick, ban, unban, timeout, purge, warn-система, moderation cases, роли, slowmode, точечное снятие варнов.
- **Авто-мод**: стоп-слова, приглашения, флуд упоминаниями, CAPS-детектор.
- **Музыка**: поиск/воспроизведение (yt-dlp + FFmpeg), очередь, skip/skipvote/seek/history/stop/pause/resume/shuffle/remove/volume/loop, импорт YouTube/Spotify Playlist и SQLite-плейлисты.
- **Администрирование**: тикеты с транскриптами, настройка приветствий/прощаний, логирование событий.
- **Напоминания**: `/remindme`, список, отмена, чистка (фоновая доставка).
- **Опросы**: до 5 вариантов, голосование кнопками, подведение итогов.
- **Розыгрыши**: таймер, участие кнопкой, розыгрыш и перерозыгрыш победителей.
- **Reaction-роли**: выдача ролей по реакции, устойчивые к рестарту.
- **Утилиты**: lock/unlock каналов, avatar, servericon, emoji, roleinfo, channelinfo, whois.
- **Snipe**: удалённые и изменённые сообщения.
- **Общее**: ping, health-диагностика, serverinfo, userinfo, справка, пагинация, embed-фабрика.
- **Backup/restore**: проверка SQLite integrity и безопасное восстановление через `scripts/restore_db.py`.
- **Донаты (DonationAlerts)**: роль «Спонсор» за донат, VIP-код в сообщении, `/donate`, спонсор-кнопка (генерирует персональный код и выдаёт роль по сумме).
- **Стримы**: Twitch, Kick и VK Видео Live — автоуведомления о старте/конце (sticky-сообщение, пинг роли), статусы командой, присутствие бота «🔴 стрим: …» во время эфира.
- **API-слой**: общий aiohttp-клиент для Twitch/Kick/VK/DonationAlerts с таймаутами, ограничением параллелизма, retry для 429/5xx, `Retry-After`, circuit breaker, User-Agent и прокси через `API_PROXY`.
- **Kick-модерация**: `/kick_ban`, `/kick_timeout`, `/kick_unban`, автомод чата через Pusher.
- **Расширенные логи**: join/leave, голосовые, изменение сообщений/ролей/никнов, старт бота (embed «🚀 Бот запущен и готов к работе»).
- **Правила-гейт**: реакция ✅ на правилах выдаёт роль.
- **TempVoice**: персональные голосовые каналы с панелью управления (переименовать/лимит/выгнать/передать).
- **Конструктор эмбеда**: `/embed` (кнопки/модалки с превью) + вебпанель в браузере (отправка через вебхук или от бота).
- **Дни рождения**: `/birthday set/list/remove` и ежедневный анонс именинников.
- **Оверлей (OBS)**: aiohttp-виджет статуса стрима и донат-цели (`/overlay`, токен-защита, автогенерация `OVERLAY_TOKEN` в `data/.overlay-token`).
- **Панель**: RBAC, парольный вход или Discord OAuth2, Argon2-хэши паролей, CSRF-защита для изменяющих запросов, аудит, `/api/health`, JSON `/api/metrics` и защищённый Prometheus `/metrics`.
- **Хранилище**: SQLite по умолчанию (WAL, `busy_timeout`, автоматический консистентный backup и retention) или PostgreSQL через `DATABASE_URL`; сервисы и репозитории используют общий backend API.
- **RamReport**: периодический отчёт «📊 Память бота» (RSS и пик) + трассировка аллокаций (tracemalloc) в назначенный канал.

Портированы ключевые функции из Node.js-бота (`Бот-Node`): донаты, Twitch/Kick, логи, правила-гейт, tempvoice, конструктор эмбедов, дни рождения, оверлей, RamReport, стартовый embed и присутствие по статусу стрима. Все они опциональны (`env`-гейт) и выключены без токенов.

## Установка (локальная разработка)

Требуется Python 3.11+ и внешние бинарники:

- **FFmpeg** — обязателен для музыки.
- **libopus** — для голосовых каналов (на Windows `opus.dll`, на Linux пакет `libopus0`).
  Без них бот запустится, но музыка/голос будут недоступны (предупреждение в логах).

### Windows

```
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env        # вписать BOT_TOKEN
.venv\Scripts\python scripts\preflight.py
.venv\Scripts\python main.py
```

### Linux (Ubuntu/Debian)

```
sudo apt install python3-venv ffmpeg libopus0 python3-pip
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # вписать BOT_TOKEN
.venv/bin/python main.py
```

## Деплой на сервер через Docker (рекомендуется)

Образ ставит `ffmpeg`, `libopus0`, `libopus-dev` и `curl` — музыка и голос работают из коробки.

> **Правило, которое выучивается один раз:** после **каждого** `git pull` контейнер надо
> **пересобрать**, иначе хост крутит старый образ, и правки кода не применяются.
> Предупреждение «libopus не загружен» в свежем логе после пуша = контейнер не пересобран,
> а не то, что правка не сработала.

```
git pull
docker compose up -d --build
docker compose logs -f --tail=100
```

- Без `--build` изменения `app/`, `requirements.txt` и `Dockerfile` игнорируются.
- Откат: `git checkout <commit> && docker compose up -d --build`.
- Токены и `.env` живут вне образа (volume), при пересборке не теряются.
- Если канал-счётчик (ServerStats) ловит `429 PATCH /channels/...` — это лимит Discord
  «2 переименования за 10 минут»; в коге стоит троттлинг, менять интервал в `.env`
  на значение **меньше 360 секунд** не стоит.

## Деплой на сервер (Ubuntu + systemd)

Готовый установщик и юнит:

```
# локально, из корня проекта (rsync: apt install rsync):
rsync -av --exclude={.venv,logs,data,.git,__pycache__} ./ user@host:/tmp/discord-mega-bot/

# на сервере:
sudo bash /tmp/discord-mega-bot/scripts/install_ubuntu.sh
nano /opt/discord-mega-bot/.env    # вписать BOT_TOKEN
sudo systemctl start discord-mega-bot
```

Сервис автоматически перезапускается при падении (`Restart=always`), логи — через `journalctl -u discord-mega-bot -f`. БД хранится в `/opt/discord-mega-bot/data/bot.db`.

## Структура

```
main.py                 # точка входа
app/
  config.py             # конфигурация из .env
  core/                 # ядро: бот, composition root (assemble), порты, логгер, загрузчик когов, embed-фабрика, views, checks
  db/                   # слой данных: БД (SQLite) + репозитории
  services/             # бизнес-логика: settings, moderation, tickets, logging, music, reminders…
  services/audio/       # Track, GuildPlayer (очередь/воспроизведение), yt-dlp resolver
  cogs/                 # коги: сервисы приходят конструктором (собирает loader по COG_PROVIDERS)
  utils/                # helpers: time, format, pagination
systemd/                # юнит для автозапуска на Linux
scripts/                # install_ubuntu.sh — установка на Ubuntu/Debian
tests/                  # unit-тесты утилит
```

## Тесты и линт

```
.venv\Scripts\pip install -r requirements-dev.txt        # Windows
.venv/bin/pip install -r requirements-dev.txt            # Linux
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
```

Для полного Windows-прогона одной командой:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_windows.ps1
```

Для Argon2-пароля веб-панели:

```bat
.venv\Scripts\python scripts\create_panel_hash.py --role owner
```

Команда напечатает строку `PANEL_OWNER_PASSWORD_HASH=...` — её можно
скопировать в `.env`. `scripts\preflight.py --strict` проверяет окружение и
наличие `BOT_TOKEN` перед запуском.

### PostgreSQL

PostgreSQL включается без изменения команд и сервисов:

```env
DATABASE_URL=postgresql://megabot:пароль@127.0.0.1:5432/megabot
POSTGRES_POOL_SIZE=8
```

При старте приложение создаёт финальную схему и индексы автоматически.
Для backup PostgreSQL нужен установленный `pg_dump`; `scripts/restore_db.py`
остаётся SQLite-инструментом, а PostgreSQL восстанавливается через `pg_restore`.
Перед боевым переключением рекомендуется сначала экспортировать SQLite и
проверить данные на копии PostgreSQL. Готовый перенос:

```bat
.venv\Scripts\python scripts\migrate_sqlite_to_postgres.py ^
  --source data\bot.db ^
  --target "%DATABASE_URL%"
```

Скрипт не пишет в непустую БД без `--force`, переносит все текущие таблицы и
восстанавливает последовательности автоинкрементных ID.

Для запуска PostgreSQL вместе с Docker-ботом используй имя сервиса `postgres`
вместо `127.0.0.1`:

```env
DATABASE_URL=postgresql://megabot:пароль@postgres:5432/megabot
```

Сначала запусти базу и дождись healthcheck, затем бота:

```bat
docker compose --profile postgres up -d postgres
docker compose ps
docker compose up -d bot
```

Порт PostgreSQL опубликован только на `127.0.0.1`, поэтому база не торчит в
интернет. Для мигратора, запущенного на Windows-хосте, используй:

```env
DATABASE_URL=postgresql://megabot:пароль@127.0.0.1:5432/megabot
```

## Лицензия

MIT.
