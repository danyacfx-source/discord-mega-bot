# Discord Mega Bot — структура и возможности

Версия: **3.3.0** · discord.py 2.x · Python 3.11+ · SQLite (aiosqlite)

---

## Структура проекта

```
discord-mega-bot/
├── main.py                    # точка входа: запуск бота (логи, исключения, graceful shutdown)
├── requirements.txt           # прод-зависимости (discord.py, aiosqlite, python-dotenv, yt-dlp, PyNaCl, psutil)
├── requirements-dev.txt       # pytest, ruff
├── pyproject.toml             # конфиг ruff (line-length 140) и pytest (asyncio_mode=auto)
├── .env.example               # шаблон конфигурации
├── systemd/                   # юнит автозапуска на Linux
└── scripts/install_ubuntu.sh  # установка на Ubuntu/Debian

app/
├── config.py                  # конфигурация из .env (dataclass)
├── core/                      # ядро
│   ├── bot.py                 #   MegaBot: intents, setup_hook, обработчик ошибок команд
│   ├── composition.py         #   composition root: assemble() — один граф зависимостей
│   ├── root.py                #   Root: типизированное владение графом
│   ├── base.py                #   MegaCog (типизированный доступ к сервисам) и BaseService
│   ├── loader.py              #   сборка когов по COG_PROVIDERS + persistent views
│   ├── views.py               #   ConfirmView, TicketOpen/CloseView, GiveawayView, PollView
│   ├── embeds.py              #   единый стиль embed (success/error/info/warning)
│   ├── checks.py              #   права/роли: bot_has_permissions, can_moderate
│   └── logger.py              #   логгер: консоль + ротация файлов
├── db/                        # слой данных
│   ├── __init__.py            #   реэкспорт репозиториев
│   ├── database.py            #   подключение, WAL, PRAGMAs, схема всех таблиц
│   ├── base_repository.py
│   ├── settings_repository.py #   настройки серверов
│   ├── warns_repository.py    #   предупреждения
│   ├── tickets_repository.py  #   тикеты
│   ├── reminders_repository.py#   напоминания
│   ├── polls_repository.py    #   опросы + голоса
│   ├── giveaways_repository.py#   розыгрыши + участники
│   ├── reaction_roles_repository.py
│   ├── kv_repository.py      #   key-value хранилище (sticky-сообщения стримов)
│   ├── donations_repository.py#  обработанные донаты DonationAlerts
│   └── temp_voices_repository.py # владельцы временных голосовых
├── services/                  # бизнес-логика (сервисы поверх репозиториев)
│   ├── __init__.py            #   типизированная Services-обвязка (15 сервисов)
│   ├── settings_service.py
│   ├── moderation_service.py  #   warn-система и иерархия
│   ├── music_service.py
│   ├── ticket_service.py      #   открытие/закрытие тикетов, транскрипты
│   ├── logging_service.py     #   логирование мод-действий
│   ├── reminder_service.py
│   ├── poll_service.py        #   голоса, результаты, рендер опроса
│   ├── giveaway_service.py    #   участие, жеребьёвка, рендер
│   ├── reaction_roles_service.py
│   ├── donation_service.py   #   DonationAlerts: поллинг, refresh токена, VIP-код
│   ├── twitch_service.py     #   статус стрима (Helix), sticky-сообщения
│   ├── kick_service.py       #   статус стрима + модерация Kick (Dev API)
│   ├── temp_voice_service.py #   владельцы персональных голосовых
│   └── audio/                #   Track, GuildPlayer (очередь, FFmpeg), yt-dlp resolver
├── cogs/                      # 33 модуля (32 кога), сервисы приходят конструктором
│   ├── di.py                  #   границы пакета: сервисы доступны, слой данных запрещён
│   ├── general/               #   Ping, Info, About, Help
│   ├── moderation/            #   Moderation, AutoMod, Warns
│   ├── music/                 #   Music
│   ├── administration/        #   Setup, Tickets, LoggingEvents (расширенные логи), Greetings
│   ├── events/start.py        #   Lifecycle (on_ready, статус)
│   ├── reminders/             #   Reminders + фоновая доставка
│   ├── polls/                 #   Polls
│   ├── giveaways/             #   Giveaways + фоновая проверка таймеров
│   ├── reaction_roles/        #   ReactionRoles
│   ├── snipe/                 #   Snipe
│   ├── utility/               #   Utility
│   ├── donations/             #   Donations: поллинг донатов, роль «Спонсор», /donate
│   ├── streams/               #   TwitchStatus и Kick: уведомления о стримах
│   ├── streams/kick.py        #   модерация Kick + автомод чата (Pusher)
│   ├── rules_gate/            #   RulesGate: реакция ✅ → роль
│   ├── role_menu/             #   RoleMenu: select-панели «получить/снять роль» (порт с Node)
│   ├── socials/               #   Socials: /socials — ссылки на соцсети (порт с Node)
│   ├── permissions/           #   Permissions: права категорий из конфига (порт с Node)
│   ├── server_stats/          #   ServerStats: счётчики сервера в голосовых каналах (порт с Node)
│   ├── ai/                    #   ChatAI: Gemini-ответы в разрешённых каналах (порт с Node)
│   ├── embed/                 #   EmbedBuilder: дискорд-конструктор эмбеда /embed
│   ├── birthdays/             #   Birthdays: /birthday (set/remove/list) + ежедневный анонс
│   ├── monitoring/            #   RamReport: периодический отчёт по ОЗУ в канал
│   └── tempvoice/             #   TempVoice: персональные голосовые + панель
├── core/webpanel/             #   вебпанель конструктора эмбедов (aiohttp, /api/*)
├── core/overlay/              #   OBS-оверлей OBS (aiohttp): /overlay + /overlay/api + /overlay/health
└── utils/
    ├── time.py                # парсинг/формат длительности (1d 2h 30m)
    ├── format.py              # плюрализация, относительное время
    └── pagination.py          # PaginatorView (кнопки ◀ ▶)

tests/                         # 285 тестов: структуры (модель-без-контейнера), времени, формата, автомода, БД, репозиториев, вебпанели, оверлея, tracemalloc, heartbeat/дайджеста/starboard/автореспондера/welcome-карточки и smoke-сборки
```

### Как собираются объекты: composition root вместо DI-контейнеров

`app/core/composition.py` — **composition root**: весь граф зависимостей собирается
вручную в одной функции `assemble(config, db)`. Порядок построения и есть граф:
репозитории → сервисы → бот → сервисы, зависящие от бота. Замена реализации
(фейк, другая БД) — параметры `assemble(...)`, а не правка потребителей.

```

app/core/composition.assemble(config, db)
├── app.db.*Repository(db)            → репозитории
├── app.services.*Service(repo, ...)  → сервисы (настройки, моды, подписки…)
├── app.services.*Service(settings, bot)  ← сервисы, зависящие от бота (логи, тикеты)
└── Services → прошивается в MegaBot (bot.services)
    ↓
app/core/loader.load_cogs(bot)        → коги по таблице COG_PROVIDERS
```

1. **Сборка**: каждый сервис создаётся явным вызовом конструктора в одном месте
   (`assemble`); дубликатов и рефлексии нет — синглтон гарантирован порядком сборки.
2. **Внедрение в коги**: `app/core/loader.py` использует читаемую таблицу
   `COG_PROVIDERS` — имя параметра конструктора → сервис из `bot.services`.
3. **Коги**:
   ```python
   class ModerationCog(MegaCog, name="Moderation"):
       def __init__(self, bot: MegaBot, moderation: ModerationService, logging: LoggingService) -> None:
           super().__init__(bot)
           self.moderation = moderation
   ```
4. **Граница слоёв статическая**: параметры конструкторов когов допускают только
   `bot` и ключи `COG_PROVIDERS` → репозитории/БД в коги не попадают, проверяется тестом.
5. **Безопасность**: секреты читаются только из Config (env), литералами в коде
   их не хранят — проверяется тестом.
6. **Тестимость**: `assemble(..., kick=FakeKick())` подменяет реализацию без
   изменения потребителей — фейк попадает в Root и далее в коги.

---

## Возможности по категориям

### Модерация
| Команда | Описание | Права |
|---|---|---|
| `/kick` | Выгнать участника | kick_members |
| `/ban` / `/unban` | Бан по ник/ID | ban_members |
| `/timeout` | Тайм-аут (1m–7d, автокомплит) | moderate_members |
| `/purge` | Массовая очистка сообщений | manage_messages |
| `/warn` | Предупреждение (+ warn-система) | moderate_members |
| `/warns` | История предупреждений (пагинация) | moderate_members |
| `/warn_remove` | Снять одно предупреждение по ID | moderate_members |
| `/warn_clear` | Снять все (с подтверждением) | moderate_members |
| `/clearwarns` | Быстрая очистка всех варнов | moderate_members |
| `/slowmode` | Задержка сообщений (off–1h) | manage_channels |
| `/case` / `/cases` | Просмотр единой истории модерационных действий | moderate_members |
| `/roles` | Выдать/снять роль(и) | manage_roles |
| `/lock` / `/unlock` | Закрыть/открыть канал для @everyone | manage_channels |

### Авто-модерация (файл automod.py)
- Стоп-слова из конфига (`AUTOMOD_BANNED_WORDS`)
- Блокировка ссылок на неразрешённые домены (`AUTOMOD_BLOCK_LINKS` / `AUTOMOD_ALLOWED_LINKS`)
- CAPS-детектор (порог/минимальная длина из конфига), растянутый спам ((.)\1{5,})
- Спам-окно 5с (`AUTOMOD_MAX_MESSAGES_IN_WINDOW`); игнор по ролям (`AUTOMOD_IGNORE_ROLES`) и каналам
- Реакция как на Node: удаление → тайм-аут `AUTOMOD_TIMEOUT_SECONDS` →
  бан после `AUTOMOD_BAN_AFTER_TIMEOUTS` нарушений за `AUTOMOD_BAN_WINDOW_SECONDS`

### Меню ролей (RoleMenu)
- Две select-панели «Получить роль…»/«Снять роль…» (custom_id `role_menu_add`/`role_menu_remove`),
  до 10 ролей за раз, эфемерный ответ; persistent (переживает рестарт)
- Панель создаётся/обновляется автоматически в `ROLE_MENU_CHANNEL_ID` (футер «Роли через меню выбора»)

### ИИ-чат (ChatAI, Gemini)
- `AI_CHANNELS` — каналы, где бот отвечает (кулдаун 45с по каналу, дебаунс), модель `AI_MODEL`,
  температура/макс-токены/история/таймаут — из конфига, системный промпт — `AI_SYSTEM_PROMPT`
- Ответ репликой с учётом последних `AI_HISTORY_SIZE` сообщений; ретраи 429/5xx с backoff
- `/ai_status` — статус (модель, кулдаун, каналы, наличие ключа)
- Нужен `GEMINI_API_KEY`; без ключа ИИ выключен

### Соцсети (Socials)
- `/socials` — embed «🔗 Наши ссылки» со ссылками из конфига (`SOCIALS_DISCORD/_SITE/_YOUTUBE/_TWITCH/_DONATE`)

### Права категорий (Permissions)
- `/apply_permissions` + автоприменение при старте (`PERMISSIONS_AUTO_APPLY`) для `GUILD_ID`;
  правила категорий — JSON `PERMISSIONS_CATEGORIES` (как permissions.js: роль → view_channel/connect/…)

### Счётчики сервера (ServerStats)
- Голосовые каналы-счётчики в категории `SERVER_STATS_CATEGORY_ID` («Участники 👥» / «Онлайн 🟢»),
  обновление каждые `SERVER_STATS_UPDATE_SECONDS`; лишние каналы удаляются

### Музыка (yt-dlp + FFmpeg, группа `/music`)
`play` · `skip [n]` · `skipvote` · `seek` · `history` · `stop` · `pause` · `resume` · `nowplaying` · `queue` · `shuffle` · `remove` · `volume 0-200` · `loop` · `leave`
`playlist save/load/list/delete/import` (YouTube/Spotify при заданных Spotify Client Credentials)
- Очередь на сервер, повтор трека, авто-выход при пустой очереди через 60 сек
- Плейлисты хранятся в SQLite, ограничены 100 треками, а stream URL обновляется при загрузке

### Администрирование
- Тикеты: `/ticket panel` (кнопка 🎫), закрытие 🔒, транскрипты в отдельный канал
- `/setup` welcome/farewell/log/ticket channels, `unset`, `show`
- Приветствия/прощания при входе и выходе: новичку в ЛС — каталог каналов/голосовых с описаниями
  (порт welcome.js), публичные посты по флагам `WELCOME_CHANNEL_ENABLED`/`WELCOME_LEAVE_CHANNEL_ENABLED`
- Логирование мод-действий (AuditLog)

### Напоминания (Reminders)
| Команда | Описание |
|---|---|
| `/remindme <5m|2h|1d>` `<текст>` | Создать напоминание (до 30 дней, до 20 активных) |
| `/remind` | Список своих напоминаний |
| `/remind_cancel <id>` | Отменить одно |
| `/remind_clear` | Удалить все |

Фоновая проверка каждые 30 сек: напоминание уходит в канал или в ЛС. Команды доступны и в личных сообщениях. Переживает рестарт (хранится в БД).

Для защиты от дублей несколько экземпляров бота используют SQLite lease-claim: одно напоминание или scheduled-сообщение в каждый момент обрабатывает только один worker.

### Опросы (Polls)
- `/poll <вопрос> <вариант1…5>` — 2–5 вариантов, голосование кнопками, счётчики в реальном времени
- `/poll_end <id>` — завершить, показать итоги с процентами (права: manage_messages)
- Голоса и итоги переживают рестарт (данные в БД)

### Розыгрыши (Giveaways)
- `/gstart <10m|1h|1d> <приз> [победители]` — кнопка «Участвовать», счётчик участников
- `/gend <message_id>` — завершить досрочно и разыграть
- `/greroll <message_id>` — перерозыгрыш
- Автозавершение по таймеру (проверка каждые 20 сек), победители по CRNG. Persistent-кнопка переживает рестарт.

### Reaction-роли (ReactionRoles)
- `/reactrole <message_id> <эмодзи> <роль>` — привязка реакции к роли
- `/reactrole_remove` / `_clear` / `_list` — управление
- Работают на обычных и серверных эмодзи, выдаются/снимаются автоматически

### Snipe
- `/snipe` — последнее удалённое сообщение в канале
- `/editsnipe` — последнее изменённое сообщение

### Утилиты (Utility)
`avatar` · `servericon` · `emoji` (список) · `roleinfo` · `channelinfo` · `whois` — инфо-команды

### Общее (General)
`ping` · `health` · `serverinfo` · `userinfo` · `about` · `help` — всё в embed, пагинация кнопками

### Донаты (DonationAlerts)
- Поллинг API каждые 15 сек: новый донат → роль «Спонсор» + уведомление в канал
- Персональный код `VIP-XXXXXXXX`: кнопка «🎁 Задонатить» → код в kv → роль выдаётся,
  если сумма доната ≥ `DONATION_MIN_AMOUNT`; при меньшей сумме участнику уходит ЛС
- Статичное спонсор-сообщение «⭐ Поддержать стрим» с кнопкой (канал `DONATE_BUTTON_CHANNEL_ID`,
  обновляется идемпотентно); бонусы спонсора — `DONATE_BONUSES`
- `/donate` — кнопка-ссылка на страницу доната
- OAuth: автообновление токена (`DONATIONS_REFRESH_TOKEN`); без токена поллинг выключен (кнопка работает)

### Стримы (общее для Twitch/Kick/VK Видео)
- Карточки эфира: платформа-цвет, превью, зрители/пик/длительность/категория;
  тренд «▲ +N за 10 мин» и спарклайн `▂▅▇█` из истории сэмплов в KV
- Карточка после эфира: итоги, пик, длительность и ссылка на запись
  (Twitch — последний VOD через Helix, иначе `/videos`; Kick — `/videos`; VK — страница видео)
- `/stream_stats` — история завершённых эфиров из архива KV: пики, длительность, записи,
  средний/лучший пик и суммарное время; живой эфир показывается сверху 🔴
- Архив хранит последние `STREAM_ARCHIVE_DAYS` дней (по умолчанию 90) и не больше 50 эфиров на канал
- Роль «В эфире» (`STREAM_ROLE_ID` + `STREAM_ROLE_USER_IDS`): выдаётся на старте, снимается на финише
- Тихий час `STREAM_QUIET_HOURS=23-8` — по московскому времени (`STREAM_QUIET_TZ`, по умолчанию
  `Europe/Moscow`, не зависит от таймзоны хоста): в окно пинг роли при старте не шлётся (карточка появляется)
- Табло живёт быстрее базового поллинга: во время эфира обновление каждые `STREAM_STICKY_POLL_SECONDS` (60 с)
- Старт-анонс отдельным постом с реакций 🔔 → `/stream_rsvp [платформа]` — кто откликнулся
- Стрим-пост закрепляется на время эфира и открепляется на финише
- Алерт «⚠️ Стрим прерван», если эфир длился меньше `STREAM_ABORT_ALERT_MINUTES` (0 — выкл)
- Дедуп ошибок поллинга: первая ошибка серии — со стеком, повторы — редкие, после восстановления — info
- Сессия последнего эфира хранится в KV (не чистится на офлайне) — её видят карточки, оверлей и панель
- Панель: секция «Стримы» (`/api/streams`) + виджет на «Обзоре»

### Twitch
- `/twitch_status [канал]` — статус: зрители, категория, превью, тренд
- `/stream_schedule [канал]` — ближайшие эфиры из расписания Twitch (Helix, время московское)
- `/twitch_clip [название]` — клип с живого эфира (Helix clips; нужен `TWITCH_REFRESH_TOKEN`
  со scope `clips:edit`, токен обновляется автоматически)
- Автоуведомления о старте/конце стрима: sticky-сообщение, пинг роли, смена присутствия бота на «🔴 стрим: …»

### Kick
- `/kick_status` — статус стрима (публичный API v2), sticky-сообщение и пинг роли
- `/kick_watchers` — онлайн-сессии зрителей из чата (Pusher): участники сервера отдельным списком
- Модерация (Dev API, права: админ/управление сообщениями):
  `/kick_ban`, `/kick_timeout <1–10080 мин>`, `/kick_unban` — по нику на Kick
- Автомод чата через Pusher WebSocket: бан-слово → таймаут 10 мин
- Все модули Kick выключены без `KICK_ACCESS_TOKEN`/`KICK_CHANNEL_SLUG`

### Оверлей (OBS)
- aiohttp-сервер (включается `OVERLAY_PORT`): `/overlay` — страница-виджет, `/overlay/api` — JSON, `/overlay/health`
- Токен (`X-Overlay-Token` или `?token=`): `OVERLAY_TOKEN`; если пуст — генерится и сохраняется в `data/.overlay-token`
  (в оверлей-ссылку подставляется автоматически)
- Показывает: статус стрима (Kick приоритет, иначе первый Twitch-канал): зрители/пик/категория/длительность,
  тренд и спарклайн за эфир, офлайн — «последний эфир» с пиком; статус опрашивается не чаще раза в 60 с;
  донат-цель (`OVERLAY_DONATION_GOAL_*`)

### Отчёт по ОЗУ (RamReport)
- Каждые `RAM_REPORT_INTERVAL_MINUTES` мин (первый сразу после старта) в канал `RAM_REPORT_CHANNEL_ID`
  — embed «📊 Память бота»: текущее потребление (RSS) и пик (psutil); выключен без канала
- Поле «📊 Отчёт о памяти (tracemalloc)» — топ аллокаций (файл:строка | МБ | блоки) и «Всего отслежено»
  (`RAM_REPORT_TRACEMALLOC=1`; трассировка стартует в `main.py` до импорта приложений;
  оверхед производительности, выключить — `RAM_REPORT_TRACEMALLOC=0`)

### Heartbeat (алерт о тишине)
- `HEARTBEAT_SILENCE_MINUTES=N` (0 — выключен): если бот не видел/не отправил ни одного
  сообщения дольше N минут, в канал(ы) «Бот» (`/setup log-channel bot` или `BOT_LOG_CHANNEL_ID`)
  уходит embed «Heartbeat: бот молчит» с временем последней активности
- Один эпизод тишины — один алерт: любое сообщение (входящее или от бота) сбрасывает счётчик
- Отдельно ловится залипание: сообщение, обработанное с опозданием больше порога (event loop
  или шлюз Discord висели) — алерт уходит сразу, без ожидания нового окна
- Проверка идёт каждые `min(30, N/4)` мин; после старта окно считается с готовности бота,
  чтобы не алертить сразу при запуске
- Рядом живут два порога-наблюдателя: `DISK_ALERT_MB` (свободно на диске меньше N МБ —
  embed с путём и размером), `DISCORD_LATENCY_ALERT_SECONDS` (шлюз деградирует дольше N сек
  подряд — embed с текущей задержкой); оба выключены при `0`

### Дайджест суток (Digest)
- `DIGEST_HOUR=H` (0–23; `-1` — выключен): раз в сутки в канал(ы) «Бот» уходит embed
  «Дайджест за дату» — сообщения/уникальные авторы/реакции/команды/ошибки за сутки,
  модерация (таймауты/кики/баны из кейсов) и новые записи архива стримов
- Счётчики ведутся в памяти и раз в минуту сбрасываются в KV как дельта
  (`digest:counts:{guild}:{date}`) — рестарт не теряет накопленное; публикация дедуплицируется
  ключом `digest:posted:{guild}:{date}`; хвосты 21–51д и 45–75д подрезаются автоматически

### Starboard
- `STARBOARD_CHANNEL_ID` + `STARBOARD_THRESHOLD` (по умолчанию 5) + `STARBOARD_EMOJI` (⭐):
  сообщение, набравшее порог реакций, публикуется в starboard-канал с копией контента,
  автором и ссылкой на оригинал
- Живёт вместе с сообщением: +1 реакция — пост публикуется, +1 — обновляется счётчик,
  −1 до порога — пост удаляется; удалённое оригинал-сообщение не роняет ког

### Автореспондер
- `AUTORESPOND_RULES=триггер=>ответ|...` — подстрока в тексте (регистронезависимо)
  → ответ ботом; `AUTORESPOND_COOLDOWN` (сек) — пауза одному пользователю
- `AUTORESPOND_ROLE_RULES=фраза1,фраза2` + `AUTORESPOND_ROLE_ID` — точное совпадение
  сообщения выдаёт роль (без cooldown-дублей); кулдаун-стейт ограничен 5000 ключей

### Расписание стримов в канал
- `TWITCH_SCHEDULE_CHANNEL_ID` + `SCHEDULE_POST_HOUR` (0–23, `-1` — любой час):
  при смене расписания Twitch в канал падает пост со списком ближайших эфиров
- Дедуп по сегментам в KV (`schedpost:{login}:{start_iso}`) — один сегмент постится один раз

### Ошибки → канал модерации
- Необработанные ошибки команд/слушателей дополнительно уходят embed-ом в канал модерации
  (`/setup log-channel mod` или `MOD_LOG_CHANNEL_ID`) — видно, что сломалось, не листая лог бота

### Приветствие с карточкой (Pillow)
- `WELCOME_CARD=1` — публичный пост о входе шлёт PNG-карточку (аватар по кругу, имя,
  номер участника, градиент) вместо плоского эмбеда; шрифт DejaVu (в образе Docker установлен)
- Любой сбой рендера/аватара — тихий фолбэк на обычный эмбед, пост не теряется

### Вебпанель: история действий и экспорт
- «История действий» в разделе Модерация: кейсы участника (`/api/moderation/cases`,
  404 для неизвестного участника), фильтр по всем/одному пользователю
- «⬇ CSV» в разделе Стримы: экспорт всего архива эфиров всех платформ
  (`/api/streams/archive/export`, `;`-разделитель, BOM для Excel)

### Расширенные логи
- join/leave участников, голосовые (заход/выход/переход), удаление/изменение сообщений,
  смена ника и ролей, бан/разбан, старт/рестарт бота (embed «🚀 Бот запущен и готов к работе» с версией и числом серверов)
- 5 лог-каналов (как на Node): `member_log_channel_id`, `message_log_channel_id`, `voice_log_channel_id`,
  `mod_log_channel_id`, `bot_log_channel_id` — задаются `/setup` или сидируются в БД
- Исключение каналов/категорий: `LOGS_IGNORE_CHANNEL_IDS`, `LOGS_IGNORE_CATEGORY_IDS`

### Правила-гейт (RulesGate)
- На закреплённом сообщении правил бот ставит реакцию ✅; реакция выдаёт роль,
  снятие реакции — снимает роль (`RULES_MESSAGE_ID`/`RULES_ROLE_ID`)

### Временные голосовые (TempVoice)
- Триггер-канал (`TEMP_VOICE_TRIGGER_IDS`) при заходе создаёт личный голосовой канал
  в категории триггера (или `TEMP_VOICE_CATEGORY_ID`)
- Панель управления только у владельца: ✏️ переименовать, 👥 лимит, 🚫 выгнать,
  👑 передать владельца, 🗑️ удалить
- Пустые каналы автоматически убираются раз в 60 сек

### Конструктор эмбеда
- **Дискорд**: `/embed` (для администраторов) — кнопки/модалки: заголовок, описание,
  цвет (hex/имя), автор, футер, медиа, поля (≤25, inline), время; выбор канала отправки; живое превью
- **Вебпанель**: `http://host:3000/admin` — админка (Обзор / Настройки / Эмбеды) с превью:
  отправка через вебхук (прокси через бота) или от имени бота в выбранный канал,
  загрузка/редактирование сообщения по ID
- Авторизация: пароль панели (`PANEL_PASSWORD`) или токен из `data/.panel-token`;
  дополнительные роли `admin`, `moderator`, `viewer` задаются через `PANEL_*_PASSWORD`;
  изменяющие действия сохраняются в `/api/admin-audit`;
  лимит 5 попыток входа в минуту, Origin-проверка
- Панель включается переменной `PANEL_PORT`, без неё модуль не стартует

### Дни рождения
- `/birthday set дд.мм` — сохранить свою дату, `/birthday remove` — удалить,
  `/birthday list` — ближайшие именинники
- Ежедневный анонс в `BIRTHDAY_CHANNEL_ID` в заданный час с пингом роли

---

## Persistent views (переживают рестарт)

| custom_id | View | Где |
|---|---|---|
| `ticket:open` | TicketOpenView | button on ticket panel |
| `ticket:close` | TicketCloseView | тикет-канал |
| `giveaway:enter` | GiveawayView | каждое активное сообщение розыгрыша |
| `poll:<id>:<i>` | PollView | каждое активное сообщение опроса |
| `role_menu_add` / `role_menu_remove` | RoleMenuView | панель ролей (persistent, message_id=None) |

---

## Схема БД (SQLite, WAL)

- `guild_settings` — настройки сервера (каналы, автомод, стоп-слова JSON)
- `warns` — предупреждения
- `tickets` — тикеты
- `reminders` — напоминания
- `polls`, `poll_votes` — опросы и голоса
- `giveaways`, `giveaway_entries` — розыгрыши и участники
- `reaction_roles` — привязки реакций
- `kv` — ключ-значение (дайджест, starboard, дедупликация постов расписания)
- `moderation_cases` — журнал действий модерации (для панели и дайджеста)
- `admin_audit` — аудит действий админов (веб-панель)
- `activity_hourly` — почасовая активность сообщений (графики панели)
- `donations`, `temp_voices`, `birthdays`, `season_points`, `scheduled_messages`
- `music_playlists`, `music_playlist_tracks`, `music_queue`, `music_history`

Схема эволюционирует через версионированные миграции: `schema_migrations`
(`_run_migrations` в `app/db/database.py`, версии 1–8) — при старте применяются
только недостающие версии, повторный запуск идемпотентен. PostgreSQL-бэкенд
держит финальную схему сразу (`app/db/postgres_database.py`).

---

## Конфигурация (.env)

### Приоритет настроек

Для одного параметра не должно быть двух «истин». Источник определяется типом
настройки, а не местом, из которого её удобно прочитать:

| Тип | Источник истины | Когда применяется |
|---|---|---|
| Инфраструктура и секреты (`BOT_TOKEN`, `DATABASE_URL`, `PANEL_*`, API-ключи, адреса/порты) | `.env` | Только при старте процесса; изменение требует перезапуска. |
| Глобальные правила модуля (`AUTOMOD_*`, `AI_*`, интервалы polling, ограничения) | `.env` | При старте; это политика владельца бота для всего процесса. |
| Настройки конкретного Discord-сервера (каналы, категория тикетов, тексты тикета, список слов, включение AutoMod) | `guild_settings` в БД | Сразу после `/setup` или сохранения в веб-панели; кэш сбрасывается сервисом настроек. |
| Каналы логирования | `guild_settings` для указанного типа → соответствующий `*_LOG_CHANNEL_ID` из `.env` как fallback → не отправлять | Позволяет задать безопасный глобальный fallback, но настройка сервера всегда выигрывает. |

Веб-панель и `/setup` меняют только `guild_settings`; они **не перезаписывают**
`.env`. Если параметра нет в таблице, его не следует добавлять в панель без
отдельного решения о миграции и приоритете. Это правило не позволяет
рассинхронизировать конфигурацию между панелью, slash-командами и деплоем.

| Переменная | По умолчанию |
|---|---|
| `BOT_TOKEN` | — (обязательна) |
| `BOT_PREFIX` | `!` (зарезерв legacy-команд) |
| `DB_PATH` | `data/bot.db` |
| `LOG_LEVEL` | `INFO` |
| `STATUS_ACTIVITY` | `играет с кодом` |
| `OWNER_ID` | пусто |
| `DONATIONS_TOKEN/_CLIENT_ID/_REFRESH_TOKEN` | пусто (модуль донатов выключен) |
| `DONATION_ROLE_NAME` / `DONATION_CODE_PREFIX` | `Спонсор` / `VIP` |
| `DONATION_ROLE_ID` / `DONATION_MIN_AMOUNT` | пусто / `0` (порог суммы) |
| `DONATE_BUTTON_CHANNEL_ID` / `DONATE_BONUSES` | пусто (без спонсор-кнопки) |
| `DONATION_NOTIFY_CHANNEL_ID` / `DONATE_URL` | пусто |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | пусто (Twitch выключен) |
| `TWITCH_REFRESH_TOKEN` | пусто (без `/twitch_clip`) |
| `TWITCH_CHANNELS` | пусто (список через запятую) |
| `TWITCH_NOTIFY_CHANNEL_ID` / `TWITCH_PING_ROLE_ID` | пусто |
| `STREAM_ROLE_ID` / `STREAM_ROLE_USER_IDS` | пусто (роль «В эфире» выключена) |
| `STREAM_STICKY_POLL_SECONDS` / `STREAM_QUIET_HOURS` / `STREAM_QUIET_TZ` / `STREAM_ABORT_ALERT_MINUTES` / `STREAM_ARCHIVE_DAYS` | `60` / пусто / `Europe/Moscow` / `10` / `90` |
| `KICK_CHANNEL_SLUG` | пусто (Kick выключен) |
| `KICK_MOD_CHANNEL_ID` / `KICK_ACCESS_TOKEN` / `KICK_BAN_WORDS` | пусто (модерация выключена) |
| `RULES_MESSAGE_ID` / `RULES_ROLE_ID` | пусто (гейт выключен) |
| `TEMP_VOICE_TRIGGER_IDS` / `TEMP_VOICE_CATEGORY_ID` | пусто (tempvoice выключен) |
| `LOGS_IGNORE_CHANNEL_IDS` / `LOGS_IGNORE_CATEGORY_IDS` | пусто |
| `HEARTBEAT_SILENCE_MINUTES` | `0` (алерт о тишине выключен) |
| `DISK_ALERT_MB` / `DISCORD_LATENCY_ALERT_SECONDS` | `0` / `0` (наблюдатели выключены) |
| `DIGEST_HOUR` | `21` (`-1` — дайджест выключен) |
| `STARBOARD_CHANNEL_ID` / `STARBOARD_THRESHOLD` / `STARBOARD_EMOJI` | пусто (выключен) / `5` / `⭐` |
| `AUTORESPOND_RULES` / `AUTORESPOND_ROLE_RULES` / `AUTORESPOND_ROLE_ID` / `AUTORESPOND_COOLDOWN` | пусто / пусто / пусто / `15` |
| `TWITCH_SCHEDULE_CHANNEL_ID` / `SCHEDULE_POST_HOUR` | пусто (выключен) / `-1` |
| `WELCOME_CARD` | `0` (карточка выключена) |
| `PANEL_PORT` | пусто (вебпанель выключена) |
| `PANEL_HOST` / `PANEL_PASSWORD` / `PANEL_PUBLIC_URL` | `127.0.0.1` / пусто / пусто |
| `OVERLAY_PORT` / `OVERLAY_HOST` / `OVERLAY_TOKEN` | пусто (оверлей выключен) / `127.0.0.1` / пусто |
| `OVERLAY_DONATION_GOAL_ENABLED/_TARGET/_CURRENCY/_LABEL/_CURRENT` | `0` / `500` / `₽` / `Донат-цель` / `0` |
| `RAM_REPORT_CHANNEL_ID` / `RAM_REPORT_INTERVAL_MINUTES` / `RAM_REPORT_TRACEMALLOC` | пусто (выключен) / `30` / `1` |
| `BIRTHDAY_CHANNEL_ID` / `BIRTHDAY_ANNOUNCE_HOUR` / `BIRTHDAY_PING_ROLE_ID` | пусто / `9` / пусто |
| `ROLE_MENU_ENABLED` / `ROLE_MENU_CHANNEL_ID` / `ROLE_MENU_MESSAGE` / `ROLE_MENU_ROLES` / `ROLE_MENU_MAX_VALUES` | `1` / пусто / «Уведомления и роли меню» / пусто / `10` |
| `GEMINI_API_KEY` / `AI_ENABLED` / `AI_CHANNELS` / `AI_MODEL` / `AI_COOLDOWN_SECONDS` / `AI_TEMPERATURE` / `AI_MAX_TOKENS` / `AI_HISTORY_SIZE` / `AI_TIMEOUT_SECONDS` | пусто / `0` / пусто / `gemini-1.5-flash` / `45` / `0.9` / `220` / `12` / `45` |
| `SOCIALS_DISCORD/_SITE/_YOUTUBE/_TWITCH/_DONATE` | пусто |
| `GUILD_ID` / `PERMISSIONS_AUTO_APPLY` / `PERMISSIONS_CATEGORIES` | пусто / `0` / пусто (JSON) |
| `SERVER_STATS_ENABLED` / `SERVER_STATS_CATEGORY_ID` / `SERVER_STATS_UPDATE_SECONDS` / `SERVER_STATS_CHANNELS` | `0` / пусто / `300` / пусто (JSON) |
| `WELCOME_*` (send_dm, channel/leave ids, flags, title/intro/footer, descriptions JSON) | включено, пост/уход выключены |
| `AUTOMOD_*` (banned_words, block/allowed links, caps, spam window, timeout, ban, ignore) | конфиг Node перенесён в .env |

---

## Качество

- 285 юнит- и интеграционных тестов (pytest, asyncio), в т.ч. smoke-сборка бота без сети и тесты вебпанели/оверлея
- `ruff check .` — чисто (line-length 140)
- Единые паттерны: cog → service → repository → БД; граф собирается в composition root (`app/core/composition.py`)
- Деплой на Ubuntu: `scripts/install_ubuntu.sh` + `systemd/discord-mega-bot.service`
