# NoMoreBots — Telegram Moderation Bot

## Overview
NoMoreBots automatically keeps group chats clean by deleting join/leave notifications, banning bots that were added by non-admins, and enforcing message rules defined by human moderators. The bot targets community managers who need a simple way to protect chats without monitoring them 24/7.

## Feature Highlights
- **Anti-bot protection**: instantly bans any bot invited by a non-admin member (configurable action).
- **Join/leave cleanup**: quietly removes Telegram system messages about members joining or leaving.
- **Flexible content restrictions**: configure media, stickers, links, and voice messages filtering separately for regular and trusted users per chat.
- **Configurable actions**: choose what to do for each violation — nothing, delete, warn, kick, or ban via Telegram API.
- **Trusted users**: let specific users bypass restrictions even when general posting is limited.
- **Auto-trust for boosters**: users who boost the group automatically become trusted.
- **Quick trust commands**: use `/trust` and `/untrust` by replying to messages in groups.
- **Global ban list**: super admins can ban users across all connected chats.
- **Bot statistics**: track deleted messages, banned bots, and connected groups.
- **Banned words**: maintain keyword ban lists per chat.
- **Button-driven admin UI**: manage chats, confirmed users, ban lists, restrictions, actions and help text through inline keyboards.
- **Super admin panel**: global bot management for users listed in `superadmins.txt`.
- **Multi-chat aware**: detects every chat the bot sees and lets admins pick an "active chat" for management.
- **SQLite persistence**: lightweight storage using WAL mode to survive restarts.

## Architecture
```
bot.py → Dispatcher (aiogram 3.22) → Routers
  • app/handlers/message_rules.py  — generic message moderation & /start
  • app/handlers/membership.py     — join/leave logic & bot bans
  • app/handlers/admin.py          — admin commands + inline UI
Storage: app/database.py (SQLite via aiosqlite)
Middleware: app/middlewares.py injects Database into handlers
Utilities: app/utils.py shared helpers (admin checks, etc.)
```

## Requirements
- Python 3.12+
- `pip install -r requirements.txt` (aiogram 3.22, aiosqlite, python-dotenv)
- SQLite write access to `data/bot_data.sqlite`
- Telegram Bot API token from @BotFather

Optional: Docker + Docker Compose for containerized deployments.

## Configuration (.env)
```
BOT_TOKEN=your_botfather_token
DATABASE_PATH=data/bot_data.sqlite   # optional custom path
PARSE_MODE=HTML                      # any aiogram ParseMode name
DEBUG=false                          # set to true for verbose logging
```
`load_config()` (app/config.py) validates BOT_TOKEN and ensures the database directory exists before startup.

## Running Locally
```powershell
cd U:\tgBots\NoMoreBots
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```
The bot logs to STDOUT (INFO level). Stop with Ctrl+C.

## Running via Docker Compose
```powershell
cd U:\tgBots\NoMoreBots
docker compose up --build
```
- `docker-compose.yml` mounts `./data` into the container so your SQLite file persists.
- Restart policy `unless-stopped` keeps the bot online.

## Admin Workflow
1. Add the bot to a group and promote it to admin (it needs message deletion & ban rights).
2. Send any message in that group so the bot registers it.
3. In a private chat with the bot, run `/start` and use the inline buttons:
   - **⚙️ Settings**: choose which group you're managing. Shows refresh/back buttons and instructions if no groups found.
   - **🛡️ Restrictions**: configure media, stickers, links and voice messages filtering separately for regular users and trusted users.
   - **⚡ Actions**: configure what to do for each violation type (nothing, delete, warn, kick, or ban).
   - **👥 Users**: view confirmed users (allowed to bypass restrictions). 
   - **🚫 Words**: see the banned-word list per chat.
   - **ℹ️ Help**: overview of every feature and the manual command equivalents.

### Slash Commands (Private chat)
All commands accept an optional `chat_id`. If you selected a chat through the UI, you can omit it.
- `/confirm [chat_id] <user_id>` / `/unconfirm` — manage trusted members.
- `/banword [chat_id] <слово>` / `/unbanword` — update banned keywords.
- `/confirmed [chat_id]`, `/banwords [chat_id]` — list current settings.

### Group Commands
- `/trust` — reply to a message to add user to trusted list.
- `/untrust` — reply to a message to remove user from trusted list.

### Super Admin Commands
Super admins are defined in `superadmins.txt` (one user ID per line).
- `/gban <user_id> [reason]` — add user to global ban list.
- `/ungban <user_id>` — remove user from global ban list.
- `/botstats` — show bot statistics.

## Deployment Tips
- Store `.env` securely. For multiple environments, create separate files (e.g., `.env.prod`).
- Keep `data/` persistent (Docker volume, mounted directory, or remote disk) to avoid wiping the SQLite DB.
- Enable structured logging (e.g., `logging.basicConfig(level=logging.INFO)`) and ship logs to your platform of choice.
- Monitor bot permissions after Telegram updates; missing ban/delete rights will reduce functionality.

## Troubleshooting
| Symptom | Likely Cause | Fix |
| --- | --- | --- |
| `BOT_TOKEN environment variable is not set` | `.env` missing or not loaded | Update `.env` or set env var before launch |
| `TypeError: Passing parse_mode to Bot` | Old aiogram init syntax | Already fixed by `DefaultBotProperties`; reinstall dependencies |
| `message is not modified` errors | Pressed “Refresh” with no changes | The bot now shows a tooltip instead of crashing |
| Buttons show “Select a chat first” | Bot hasn’t seen your group | Send any message in the target group, then tap Refresh |
| Bot fails to ban/delete | Bot lacks admin rights | Promote bot to admin with delete & ban permissions |

## Project Structure
```
bot.py                    # entrypoint
superadmins.txt           # list of super admin user IDs
app/
  config.py               # env loading / ParseMode config
  database.py             # SQLite access layer
  handlers/
    admin.py              # inline UI + commands + super admin panel
    membership.py         # join/leave moderation
    message_rules.py      # message filtering, /start, /trust, /untrust
  middlewares.py          # DatabaseMiddleware
  utils.py                # admin helper, superadmin check
requirements.txt
Dockerfile
docker-compose.yml
data/                     # SQLite WAL files
```

## Contributing & Support
Issues and PRs are welcome. If you run into Telegram-side errors, include bot logs, aiogram version, and reproduction steps when reporting.

---

# NoMoreBots — Телеграм-бот для модерации чатов

## Обзор
NoMoreBots автоматически поддерживает чистоту в групповых чатах: удаляет уведомления о входе/выходе, банит ботов, добавленных не-админами, и применяет правила сообщений, заданные модераторами. Бот предназначен для администраторов, которым нужен простой инструмент для защиты чатов без постоянного контроля.

## Основные возможности
- **Защита от ботов**: мгновенно банит любого бота, добавленного не-админом (настраиваемое действие).
- **Удаление уведомлений**: тихо удаляет системные сообщения Telegram о входе/выходе участников.
- **Гибкие ограничения контента**: настройка фильтрации медиа, стикеров, ссылок и голосовых отдельно для обычных и доверенных пользователей.
- **Настраиваемые действия**: выбор что делать за каждое нарушение — ничего, удалить, предупредить, кикнуть или забанить через Telegram API.
- **Доверенные пользователи**: отдельный список пользователей, которые могут обходить ограничения.
- **Авто-доверие для бустеров**: пользователи, бустящие группу, автоматически становятся доверенными.
- **Быстрые команды доверия**: используйте `/trust` и `/untrust` отвечая на сообщения в группе.
- **Глобальный бан-лист**: супер-админы могут банить пользователей во всех подключенных чатах.
- **Статистика бота**: отслеживание удалённых сообщений, забаненных ботов и подключенных групп.
- **Запрещённые слова**: списки слов для каждого чата.
- **Админ-панель на кнопках**: управление чатами, списками, ограничениями, действиями и справкой через инлайн-клавиатуры.
- **Супер-админ панель**: глобальное управление ботом для пользователей из `superadmins.txt`.
- **Работа с несколькими чатами**: бот видит все чаты и позволяет выбрать "активный чат" для управления.
- **Хранение в SQLite**: лёгкая база данных с режимом WAL для устойчивости к перезапускам.

## Архитектура
```
bot.py → Dispatcher (aiogram 3.22) → Routers
  • app/handlers/message_rules.py  — фильтрация сообщений и /start
  • app/handlers/membership.py     — логика входа/выхода и бан ботов
  • app/handlers/admin.py          — команды и инлайн-UI для админов
Хранилище: app/database.py (SQLite через aiosqlite)
Middleware: app/middlewares.py — внедрение Database в обработчики
Утилиты: app/utils.py — общие функции (проверка админов и др.)
```

## Требования
- Python 3.12+
- `pip install -r requirements.txt` (aiogram 3.22, aiosqlite, python-dotenv)
- Доступ на запись в SQLite-файл `data/bot_data.sqlite`
- Токен Telegram-бота от @BotFather

Опционально: Docker + Docker Compose для контейнеризации.

## Конфигурация (.env)
```
BOT_TOKEN=токен_бота_от_BotFather
DATABASE_PATH=data/bot_data.sqlite   # путь к базе (опционально)
PARSE_MODE=HTML                      # любой ParseMode из aiogram
DEBUG=false                          # true для подробных логов
```
`load_config()` (app/config.py) проверяет BOT_TOKEN и создаёт папку для базы при запуске.

## Запуск локально
```powershell
cd U:\tgBots\NoMoreBots
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```
Бот пишет логи в STDOUT (уровень INFO). Остановить — Ctrl+C.

## Запуск через Docker Compose
```powershell
cd U:\tgBots\NoMoreBots
docker compose up --build
```
- `docker-compose.yml` монтирует `./data` в контейнер для сохранения базы.
- Политика рестарта `unless-stopped` — бот всегда онлайн.

## Работа администратора
1. Добавьте бота в группу и дайте ему права администратора (нужны права на удаление сообщений и бан).
2. Напишите любое сообщение в группе, чтобы бот её "увидел".
3. В личке с ботом отправьте `/start` и используйте кнопки:
   - **⚙️ Настройки**: выбор группы для управления. Есть кнопки обновления/назад и подсказки, если групп нет.
   - **🛡️ Ограничения**: настройка фильтрации медиа, стикеров, ссылок и голосовых отдельно для обычных и доверенных пользователей.
   - **⚡ Действия**: выбор действия за каждое нарушение (ничего, удалить, предупредить, кикнуть, забанить).
   - **👥 Пользователи**: просмотр доверенных пользователей.
   - **🚫 Слова**: просмотр списка запрещённых слов для чата.
   - **ℹ️ Помощь**: описание всех функций и команд.

### Слэш-команды (в личке)
Все команды принимают необязательный `chat_id`. Если чат выбран через UI, можно не указывать.
- `/confirm [chat_id] <user_id>` / `/unconfirm` — управление доверенными.
- `/banword [chat_id] <слово>` / `/unbanword` — работа со списком слов.
- `/confirmed [chat_id]`, `/banwords [chat_id]` — просмотр текущих списков.

### Команды в группе
- `/trust` — ответьте на сообщение, чтобы добавить пользователя в доверенные.
- `/untrust` — ответьте на сообщение, чтобы убрать пользователя из доверенных.

### Команды супер-админов
Супер-админы указываются в `superadmins.txt` (по одному ID на строку).
- `/gban <user_id> [причина]` — добавить в глобальный бан-лист.
- `/ungban <user_id>` — убрать из глобального бан-листа.
- `/botstats` — показать статистику бота.

## Советы по развёртыванию
- Храните `.env` в безопасности. Для разных окружений — отдельные файлы (например, `.env.prod`).
- Директорию `data/` делайте постоянной (Docker volume, монтируемая папка, удалённый диск), чтобы не потерять базу.
- Включите структурированные логи (`logging.basicConfig(level=logging.INFO)`) и отправляйте их в нужную систему.
- После обновлений Telegram проверяйте права бота — отсутствие прав на удаление/бан ограничит функционал.

## Решение проблем
| Симптом | Возможная причина | Решение |
| --- | --- | --- |
| `BOT_TOKEN environment variable is not set` | Нет `.env` или переменная не загружена | Проверьте `.env` или задайте переменную окружения |
| `TypeError: Passing parse_mode to Bot` | Старый синтаксис инициализации aiogram | Уже исправлено через `DefaultBotProperties`; переустановите зависимости |
| `message is not modified` errors | Нажата "Обновить", но изменений нет | Теперь бот показывает подсказку вместо ошибки |
| Кнопки требуют "Выберите чат" | Бот не видел вашу группу | Напишите сообщение в группе, затем нажмите "Обновить" |
| Бот не банит/не удаляет | Нет прав администратора | Дайте боту права на удаление и бан |

## Структура проекта
```
bot.py                    # точка входа
superadmins.txt           # список ID супер-админов
app/
  config.py               # загрузка env / ParseMode
  database.py             # работа с SQLite
  handlers/
    admin.py              # инлайн-UI, команды, супер-админ панель
    membership.py         # модерация входа/выхода
    message_rules.py      # фильтрация сообщений, /start, /trust, /untrust
  middlewares.py          # DatabaseMiddleware
  utils.py                # вспомогательные функции, проверка супер-админов
requirements.txt
Dockerfile
docker-compose.yml
data/                     # файлы SQLite WAL
```

## Вклад и поддержка
Пулл-реквесты и баг-репорты приветствуются. Если столкнулись с ошибками Telegram, приложите логи, версию aiogram и шаги для воспроизведения.
