import Overview from "./overview.jsx";
import Placeholder from "./placeholder.jsx";
import Server from "./server.jsx";
import Moderation from "./moderation.jsx";
import Giveaways from "./giveaways.jsx";
import Tickets from "./tickets.jsx";
import Automod from "./automod.jsx";
import Polls from "./polls.jsx";
import Birthdays from "./birthdays.jsx";
import TempVoice from "./tempvoice.jsx";
import Streams from "./streams.jsx";
import AIChat from "./ai.jsx";
import Scheduler from "./scheduler.jsx";
import EmbedBuilder from "./embed.jsx";
import WelcomeSection from "./welcome.jsx";
import OverlaySection from "./overlay.jsx";
import StreamCardsSection from "./streamcards.jsx";
import SettingsSection from "./settings.jsx";
import TestSection from "./test.jsx";
import FilesSection from "./files.jsx";
import LogsSection from "./logs.jsx";
import AuditSection from "./audit.jsx";
import StatsSection from "./stats.jsx";
import BackupSection from "./backup.jsx";

export const NAV = [
  {
    label: "Главное",
    items: [
      { id: "overview", icon: "home", title: "Обзор", desc: "Состояние сервера и главные действия в одном месте.", Component: Overview },
      { id: "server", icon: "server", title: "Сервер", desc: "Участники, каналы и голосовая активность сервера.", Component: Server },
    ],
  },
  {
    label: "Сообщество",
    items: [
      { id: "moderation", icon: "shield", title: "Модерация", desc: "Действия модераторов и история нарушений.", Component: Moderation },
      { id: "giveaways", icon: "gift", title: "Розыгрыши", desc: "Активные и завершённые розыгрыши сообщества.", Component: Giveaways },
      { id: "tickets", icon: "ticket", title: "Тикеты", desc: "Обращения участников и их история.", Component: Tickets },
      { id: "automod", icon: "eraser", title: "Автомод", desc: "Автоматическая защита, правила и быстрый lockdown.", Component: Automod },
      { id: "polls", icon: "pie", title: "Опросы", desc: "Опросы, голоса и результаты.", Component: Polls },
      { id: "birthdays", icon: "cake", title: "Дни рождения", desc: "Календарь поздравлений для участников.", Component: Birthdays },
      { id: "tempvoice", icon: "speaker", title: "Голосовые", desc: "Активные временные голосовые комнаты.", Component: TempVoice },
      { id: "streams", icon: "monitor", title: "Стримы", desc: "Twitch, Kick и VK: статус эфира, табло и настройки.", Component: Streams },
      { id: "ai", icon: "bot", title: "AI-чат", desc: "Состояние и управление AI-чатом.", Component: AIChat },
    ],
  },
  {
    label: "Контент",
    items: [
      { id: "embed", icon: "file-text", title: "Эмбеды", desc: "Создание сообщений и эмбедов с предпросмотром.", Component: EmbedBuilder },
      { id: "welcome", icon: "user-plus", title: "Приветствие", desc: "Конструктор PNG-карточки для новых участников.", Component: WelcomeSection },
      { id: "overlay", icon: "layout", title: "Оверлей", desc: "Конструктор раскладки виджетов для OBS.", Component: OverlaySection },
      { id: "streamcards", icon: "cards", title: "Карточки стримов", desc: "Заголовки, цвета и поля анонсов Twitch/Kick/VK.", Component: StreamCardsSection },
      { id: "scheduler", icon: "clock", title: "Планировщик", desc: "Планирование будущих публикаций.", Component: Scheduler },
    ],
  },
  {
    label: "Система",
    items: [
      { id: "settings", icon: "sliders", title: "Настройки", desc: "Каналы и рабочие настройки сервера.", Component: SettingsSection },
      { id: "test", icon: "flask", title: "Тест", desc: "Проверка отправки сообщений от имени бота.", Component: TestSection },
      { id: "files", icon: "image", title: "Файлы", desc: "Изображения, доступные для оформления сообщений.", Component: FilesSection },
      { id: "logs", icon: "file-text", title: "Логи", desc: "Технические события и ошибки в реальном времени.", Component: LogsSection },
      { id: "audit", icon: "eye", title: "Логи Discord", desc: "События Discord: сообщения, участники и модерация.", Component: AuditSection },
      { id: "stats", icon: "trending", title: "Статистика", desc: "Аналитика активности и динамика сообщества.", Component: StatsSection },
      { id: "backup", icon: "database", title: "Бэкап", desc: "Экспорт данных и состояние резервных копий.", Component: BackupSection },
    ],
  },
];

export const SECTIONS = NAV.flatMap((g) => g.items);

export function sectionById(id) {
  return SECTIONS.find((s) => s.id === id) || SECTIONS[0];
}

export function renderSection(section) {
  return section.Component ? <section.Component /> : <Placeholder section={section} />;
}
