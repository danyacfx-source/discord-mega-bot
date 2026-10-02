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
      { id: "overview", icon: "🏠", title: "Обзор", desc: "Состояние сервера и главные действия в одном месте.", Component: Overview },
      { id: "server", icon: "🖥", title: "Сервер", desc: "Участники, каналы и голосовая активность сервера.", Component: Server },
    ],
  },
  {
    label: "Сообщество",
    items: [
      { id: "moderation", icon: "🛡", title: "Модерация", desc: "Действия модераторов и история нарушений.", Component: Moderation },
      { id: "giveaways", icon: "🎁", title: "Розыгрыши", desc: "Активные и завершённые розыгрыши сообщества.", Component: Giveaways },
      { id: "tickets", icon: "🎫", title: "Тикеты", desc: "Обращения участников и их история.", Component: Tickets },
      { id: "automod", icon: "🧹", title: "Автомод", desc: "Автоматическая защита, правила и быстрый lockdown.", Component: Automod },
      { id: "polls", icon: "🗳", title: "Опросы", desc: "Опросы, голоса и результаты.", Component: Polls },
      { id: "birthdays", icon: "🎂", title: "Дни рождения", desc: "Календарь поздравлений для участников.", Component: Birthdays },
      { id: "tempvoice", icon: "🔊", title: "Голосовые", desc: "Активные временные голосовые комнаты.", Component: TempVoice },
      { id: "streams", icon: "📺", title: "Стримы", desc: "Twitch, Kick и VK: статус эфира, табло и настройки.", Component: Streams },
      { id: "ai", icon: "🤖", title: "AI-чат", desc: "Состояние и управление AI-чатом.", Component: AIChat },
    ],
  },
  {
    label: "Контент",
    items: [
      { id: "embed", icon: "📝", title: "Эмбеды", desc: "Создание сообщений и эмбедов с предпросмотром.", Component: EmbedBuilder },
      { id: "welcome", icon: "👋", title: "Приветствие", desc: "Конструктор PNG-карточки для новых участников.", Component: WelcomeSection },
      { id: "overlay", icon: "🪟", title: "Оверлей", desc: "Конструктор раскладки виджетов для OBS.", Component: OverlaySection },
      { id: "streamcards", icon: "🎴", title: "Карточки стримов", desc: "Заголовки, цвета и поля анонсов Twitch/Kick/VK.", Component: StreamCardsSection },
      { id: "scheduler", icon: "⏰", title: "Планировщик", desc: "Планирование будущих публикаций.", Component: Scheduler },
    ],
  },
  {
    label: "Система",
    items: [
      { id: "settings", icon: "⚙️", title: "Настройки", desc: "Каналы и рабочие настройки сервера.", Component: SettingsSection },
      { id: "test", icon: "🧪", title: "Тест", desc: "Проверка отправки сообщений от имени бота.", Component: TestSection },
      { id: "files", icon: "🖼", title: "Файлы", desc: "Изображения, доступные для оформления сообщений.", Component: FilesSection },
      { id: "logs", icon: "📄", title: "Логи", desc: "Технические события и ошибки в реальном времени.", Component: LogsSection },
      { id: "audit", icon: "👁", title: "Логи Discord", desc: "События Discord: сообщения, участники и модерация.", Component: AuditSection },
      { id: "stats", icon: "📊", title: "Статистика", desc: "Аналитика активности и динамика сообщества.", Component: StatsSection },
      { id: "backup", icon: "💾", title: "Бэкап", desc: "Экспорт данных и состояние резервных копий.", Component: BackupSection },
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
