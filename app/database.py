import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List
import aiosqlite


# Действия при нарушениях
ACTION_NONE = 0           # Ничего не делать (тишина)
ACTION_DELETE = 1         # Только удалить сообщение
ACTION_WARN = 2           # Удалить + предупредить пользователя
ACTION_KICK = 3           # Удалить + кикнуть (без бана)
ACTION_BAN = 4            # Удалить + забанить через Telegram API

ACTION_LABELS = {
    ACTION_NONE: "🟢 Ничего",
    ACTION_DELETE: "🗑️ Удалить",
    ACTION_WARN: "⚠️ Предупредить",
    ACTION_KICK: "👢 Кикнуть",
    ACTION_BAN: "🚫 Забанить",
}


@dataclass
class ChatSettings:
    """Настройки ограничений для чата."""
    chat_id: int
    # Ограничения (по умолчанию всё разрешено)
    restrict_media_regular: bool = False     # Ограничивать медиа для обычных
    restrict_stickers_regular: bool = False  # Ограничивать стикеры для обычных
    restrict_links_regular: bool = False     # Ограничивать ссылки для обычных
    restrict_voice_regular: bool = False     # Ограничивать голосовые для обычных
    restrict_media_confirmed: bool = False   # Ограничивать медиа для доверенных
    restrict_stickers_confirmed: bool = False # Ограничивать стикеры для доверенных
    restrict_links_confirmed: bool = False   # Ограничивать ссылки для доверенных
    restrict_voice_confirmed: bool = False   # Ограничивать голосовые для доверенных
    # Действия при нарушениях (по умолчанию просто удалять)
    action_media: int = ACTION_DELETE        # Действие при запрещённом медиа
    action_stickers: int = ACTION_DELETE     # Действие при запрещённых стикерах
    action_links: int = ACTION_DELETE        # Действие при запрещённых ссылках
    action_voice: int = ACTION_DELETE        # Действие при запрещённых голосовых
    action_words: int = ACTION_DELETE        # Действие при запрещённых словах
    action_bots: int = ACTION_BAN            # Действие при добавлении бота не-админом
    action_global_ban: int = ACTION_BAN      # Действие для глобально забаненных
    # Дополнительные настройки
    trust_boosters: bool = True              # Автоматически доверять бустерам группы
    # Кастомные сообщения при нарушениях ({user} будет заменён на упоминание)
    warn_message_media: str = ""             # Сообщение при запрещённом медиа
    warn_message_stickers: str = ""          # Сообщение при запрещённых стикерах
    warn_message_links: str = ""             # Сообщение при запрещённых ссылках
    warn_message_voice: str = ""             # Сообщение при запрещённых голосовых
    warn_message_words: str = ""             # Сообщение при запрещённых словах
    warn_message_bots: str = ""              # Сообщение при добавлении ботов
    warn_message_global_ban: str = ""        # Сообщение для глобально забаненных


# Сообщения по умолчанию
DEFAULT_WARN_MESSAGES = {
    "media": "⚠️ {user}, отправка медиа запрещена в этом чате.",
    "stickers": "⚠️ {user}, отправка стикеров запрещена в этом чате.",
    "links": "⚠️ {user}, отправка ссылок запрещена в этом чате.",
    "voice": "⚠️ {user}, отправка голосовых сообщений запрещена в этом чате.",
    "words": "⚠️ {user}, ваше сообщение содержит запрещённые слова.",
    "bots": "⚠️ {user}, добавлять ботов могут только администраторы!",
    "global_ban": "⚠️ {user}, вы находитесь в глобальном бан-листе.",
}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._connection: aiosqlite.Connection | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        self._connection = await aiosqlite.connect(self.path)
        await self._connection.execute("PRAGMA journal_mode=WAL;")
        await self._connection.execute("PRAGMA foreign_keys=ON;")
        await self._connection.execute("PRAGMA synchronous=NORMAL;")
        await self._connection.commit()

    async def setup(self) -> None:
        connection = await self._ensure_connected()

        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS confirmed_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS banned_words (
                chat_id INTEGER NOT NULL,
                word TEXT NOT NULL,
                PRIMARY KEY (chat_id, word)
            );

            CREATE TABLE IF NOT EXISTS global_banned_users (
                user_id INTEGER PRIMARY KEY,
                banned_by INTEGER NOT NULL,
                banned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reason TEXT
            );

            CREATE TABLE IF NOT EXISTS known_chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS admin_selected_chat (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES known_chats(chat_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                restrict_media_regular INTEGER NOT NULL DEFAULT 0,
                restrict_stickers_regular INTEGER NOT NULL DEFAULT 0,
                restrict_links_regular INTEGER NOT NULL DEFAULT 0,
                restrict_voice_regular INTEGER NOT NULL DEFAULT 0,
                restrict_media_confirmed INTEGER NOT NULL DEFAULT 0,
                restrict_stickers_confirmed INTEGER NOT NULL DEFAULT 0,
                restrict_links_confirmed INTEGER NOT NULL DEFAULT 0,
                restrict_voice_confirmed INTEGER NOT NULL DEFAULT 0,
                action_media INTEGER NOT NULL DEFAULT 1,
                action_stickers INTEGER NOT NULL DEFAULT 1,
                action_links INTEGER NOT NULL DEFAULT 1,
                action_voice INTEGER NOT NULL DEFAULT 1,
                action_words INTEGER NOT NULL DEFAULT 1,
                action_bots INTEGER NOT NULL DEFAULT 4,
                action_global_ban INTEGER NOT NULL DEFAULT 4,
                trust_boosters INTEGER NOT NULL DEFAULT 1,
                warn_message_media TEXT NOT NULL DEFAULT '',
                warn_message_stickers TEXT NOT NULL DEFAULT '',
                warn_message_links TEXT NOT NULL DEFAULT '',
                warn_message_voice TEXT NOT NULL DEFAULT '',
                warn_message_words TEXT NOT NULL DEFAULT '',
                warn_message_bots TEXT NOT NULL DEFAULT '',
                warn_message_global_ban TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (chat_id) REFERENCES known_chats(chat_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS bot_stats (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                messages_deleted INTEGER NOT NULL DEFAULT 0,
                bots_banned INTEGER NOT NULL DEFAULT 0,
                users_globally_banned INTEGER NOT NULL DEFAULT 0
            );

            INSERT OR IGNORE INTO bot_stats (id) VALUES (1);

            DROP TABLE IF EXISTS banned_users;
            """
        )
        await connection.commit()

        # Миграция: добавляем новые колонки, если их нет
        await self._migrate_chat_settings(connection)

    async def _migrate_chat_settings(self, connection: aiosqlite.Connection) -> None:
        """Добавляет недостающие колонки в таблицу chat_settings."""
        # Получаем список существующих колонок
        async with connection.execute("PRAGMA table_info(chat_settings)") as cursor:
            existing_columns = {row[1] for row in await cursor.fetchall()}

        # Список новых колонок с их определениями
        new_columns = [
            ("restrict_voice_regular", "INTEGER NOT NULL DEFAULT 0"),
            ("restrict_voice_confirmed", "INTEGER NOT NULL DEFAULT 0"),
            ("action_media", "INTEGER NOT NULL DEFAULT 1"),
            ("action_stickers", "INTEGER NOT NULL DEFAULT 1"),
            ("action_links", "INTEGER NOT NULL DEFAULT 1"),
            ("action_voice", "INTEGER NOT NULL DEFAULT 1"),
            ("action_words", "INTEGER NOT NULL DEFAULT 1"),
            ("action_bots", "INTEGER NOT NULL DEFAULT 4"),
            ("action_global_ban", "INTEGER NOT NULL DEFAULT 4"),
            ("trust_boosters", "INTEGER NOT NULL DEFAULT 1"),
            ("warn_message_media", "TEXT NOT NULL DEFAULT ''"),
            ("warn_message_stickers", "TEXT NOT NULL DEFAULT ''"),
            ("warn_message_links", "TEXT NOT NULL DEFAULT ''"),
            ("warn_message_voice", "TEXT NOT NULL DEFAULT ''"),
            ("warn_message_words", "TEXT NOT NULL DEFAULT ''"),
            ("warn_message_bots", "TEXT NOT NULL DEFAULT ''"),
            ("warn_message_global_ban", "TEXT NOT NULL DEFAULT ''"),
        ]

        for column_name, column_def in new_columns:
            if column_name not in existing_columns:
                try:
                    await connection.execute(
                        f"ALTER TABLE chat_settings ADD COLUMN {column_name} {column_def}"
                    )
                except Exception:
                    pass  # Колонка уже существует

        await connection.commit()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def add_confirmed_user(self, chat_id: int, user_id: int) -> None:
        await self._execute(
            "INSERT OR IGNORE INTO confirmed_users(chat_id, user_id) VALUES (?, ?)",
            (chat_id, user_id),
        )

    async def remove_confirmed_user(self, chat_id: int, user_id: int) -> None:
        await self._execute(
            "DELETE FROM confirmed_users WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )

    async def get_confirmed_users(self, chat_id: int) -> List[int]:
        rows = await self._fetchall("SELECT user_id FROM confirmed_users WHERE chat_id = ?", (chat_id,))
        return [row[0] for row in rows]

    async def is_confirmed(self, chat_id: int, user_id: int) -> bool:
        row = await self._fetchone(
            "SELECT 1 FROM confirmed_users WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        return bool(row)

    async def add_banned_word(self, chat_id: int, word: str) -> None:
        await self._execute(
            "INSERT OR IGNORE INTO banned_words(chat_id, word) VALUES (?, ?)",
            (chat_id, word.lower()),
        )

    async def remove_banned_word(self, chat_id: int, word: str) -> None:
        await self._execute(
            "DELETE FROM banned_words WHERE chat_id = ? AND word = ?",
            (chat_id, word.lower()),
        )

    async def get_banned_words(self, chat_id: int) -> List[str]:
        rows = await self._fetchall("SELECT word FROM banned_words WHERE chat_id = ?", (chat_id,))
        return [row[0] for row in rows]

    # === Глобальный бан-лист ===

    async def add_global_banned_user(self, user_id: int, banned_by: int, reason: str | None = None) -> None:
        await self._execute(
            "INSERT OR IGNORE INTO global_banned_users(user_id, banned_by, reason) VALUES (?, ?, ?)",
            (user_id, banned_by, reason),
        )
        await self.increment_stat("users_globally_banned")

    async def remove_global_banned_user(self, user_id: int) -> None:
        await self._execute(
            "DELETE FROM global_banned_users WHERE user_id = ?",
            (user_id,),
        )

    async def is_global_banned(self, user_id: int) -> bool:
        row = await self._fetchone(
            "SELECT 1 FROM global_banned_users WHERE user_id = ?",
            (user_id,),
        )
        return bool(row)

    async def get_global_banned_users(self) -> List[tuple[int, int, str, str | None]]:
        """Возвращает список (user_id, banned_by, banned_at, reason)."""
        rows = await self._fetchall(
            "SELECT user_id, banned_by, banned_at, reason FROM global_banned_users ORDER BY banned_at DESC",
            (),
        )
        return [(row[0], row[1], row[2], row[3]) for row in rows]

    async def get_global_banned_count(self) -> int:
        row = await self._fetchone("SELECT COUNT(*) FROM global_banned_users", ())
        return row[0] if row else 0

    async def upsert_chat(self, chat_id: int, title: str) -> None:
        await self._execute(
            "INSERT INTO known_chats(chat_id, title) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title",
            (chat_id, title),
        )

    async def get_known_chats(self) -> List[tuple[int, str]]:
        rows = await self._fetchall("SELECT chat_id, title FROM known_chats", ())
        return [(row[0], row[1]) for row in rows]

    async def set_admin_selected_chat(self, user_id: int, chat_id: int) -> None:
        await self._execute(
            "INSERT INTO admin_selected_chat(user_id, chat_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET chat_id = excluded.chat_id",
            (user_id, chat_id),
        )

    async def get_admin_selected_chat(self, user_id: int) -> int | None:
        row = await self._fetchone(
            "SELECT chat_id FROM admin_selected_chat WHERE user_id = ?",
            (user_id,),
        )
        if row:
            return int(row[0])
        return None

    async def get_chat_settings(self, chat_id: int) -> ChatSettings:
        """Получить настройки чата. Если нет — вернёт настройки по умолчанию."""
        row = await self._fetchone(
            """SELECT chat_id, restrict_media_regular, restrict_stickers_regular,
                      restrict_links_regular, restrict_voice_regular,
                      restrict_media_confirmed, restrict_stickers_confirmed,
                      restrict_links_confirmed, restrict_voice_confirmed,
                      action_media, action_stickers, action_links, action_voice,
                      action_words, action_bots, action_global_ban, trust_boosters,
                      warn_message_media, warn_message_stickers, warn_message_links,
                      warn_message_voice, warn_message_words, warn_message_bots,
                      warn_message_global_ban
               FROM chat_settings WHERE chat_id = ?""",
            (chat_id,),
        )
        if row:
            return ChatSettings(
                chat_id=row[0],
                restrict_media_regular=bool(row[1]),
                restrict_stickers_regular=bool(row[2]),
                restrict_links_regular=bool(row[3]),
                restrict_voice_regular=bool(row[4]),
                restrict_media_confirmed=bool(row[5]),
                restrict_stickers_confirmed=bool(row[6]),
                restrict_links_confirmed=bool(row[7]),
                restrict_voice_confirmed=bool(row[8]),
                action_media=row[9],
                action_stickers=row[10],
                action_links=row[11],
                action_voice=row[12],
                action_words=row[13],
                action_bots=row[14],
                action_global_ban=row[15],
                trust_boosters=bool(row[16]),
                warn_message_media=row[17] or "",
                warn_message_stickers=row[18] or "",
                warn_message_links=row[19] or "",
                warn_message_voice=row[20] or "",
                warn_message_words=row[21] or "",
                warn_message_bots=row[22] or "",
                warn_message_global_ban=row[23] or "",
            )
        return ChatSettings(chat_id=chat_id)

    async def update_chat_settings(self, settings: ChatSettings) -> None:
        """Создать или обновить настройки чата."""
        await self._execute(
            """INSERT INTO chat_settings (
                   chat_id, restrict_media_regular, restrict_stickers_regular,
                   restrict_links_regular, restrict_voice_regular,
                   restrict_media_confirmed, restrict_stickers_confirmed,
                   restrict_links_confirmed, restrict_voice_confirmed,
                   action_media, action_stickers, action_links, action_voice,
                   action_words, action_bots, action_global_ban, trust_boosters,
                   warn_message_media, warn_message_stickers, warn_message_links,
                   warn_message_voice, warn_message_words, warn_message_bots,
                   warn_message_global_ban
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                   restrict_media_regular = excluded.restrict_media_regular,
                   restrict_stickers_regular = excluded.restrict_stickers_regular,
                   restrict_links_regular = excluded.restrict_links_regular,
                   restrict_voice_regular = excluded.restrict_voice_regular,
                   restrict_media_confirmed = excluded.restrict_media_confirmed,
                   restrict_stickers_confirmed = excluded.restrict_stickers_confirmed,
                   restrict_links_confirmed = excluded.restrict_links_confirmed,
                   restrict_voice_confirmed = excluded.restrict_voice_confirmed,
                   action_media = excluded.action_media,
                   action_stickers = excluded.action_stickers,
                   action_links = excluded.action_links,
                   action_voice = excluded.action_voice,
                   action_words = excluded.action_words,
                   action_bots = excluded.action_bots,
                   action_global_ban = excluded.action_global_ban,
                   trust_boosters = excluded.trust_boosters,
                   warn_message_media = excluded.warn_message_media,
                   warn_message_stickers = excluded.warn_message_stickers,
                   warn_message_links = excluded.warn_message_links,
                   warn_message_voice = excluded.warn_message_voice,
                   warn_message_words = excluded.warn_message_words,
                   warn_message_bots = excluded.warn_message_bots,
                   warn_message_global_ban = excluded.warn_message_global_ban""",
            (
                settings.chat_id,
                int(settings.restrict_media_regular),
                int(settings.restrict_stickers_regular),
                int(settings.restrict_links_regular),
                int(settings.restrict_voice_regular),
                int(settings.restrict_media_confirmed),
                int(settings.restrict_stickers_confirmed),
                int(settings.restrict_links_confirmed),
                int(settings.restrict_voice_confirmed),
                settings.action_media,
                settings.action_stickers,
                settings.action_links,
                settings.action_voice,
                settings.action_words,
                settings.action_bots,
                settings.action_global_ban,
                int(settings.trust_boosters),
                settings.warn_message_media,
                settings.warn_message_stickers,
                settings.warn_message_links,
                settings.warn_message_voice,
                settings.warn_message_words,
                settings.warn_message_bots,
                settings.warn_message_global_ban,
            ),
        )

    async def toggle_chat_setting(self, chat_id: int, setting_name: str) -> bool:
        """Переключить настройку чата. Возвращает новое значение."""
        settings = await self.get_chat_settings(chat_id)
        current_value = getattr(settings, setting_name, False)
        new_value = not current_value
        setattr(settings, setting_name, new_value)
        await self.update_chat_settings(settings)
        return new_value

    async def cycle_action_setting(self, chat_id: int, setting_name: str) -> int:
        """Переключить действие по кругу (0->1->2->3->4->0). Возвращает новое значение."""
        settings = await self.get_chat_settings(chat_id)
        current_value = getattr(settings, setting_name, ACTION_DELETE)
        new_value = (current_value + 1) % 5  # 0-4
        setattr(settings, setting_name, new_value)
        await self.update_chat_settings(settings)
        return new_value

    async def set_warn_message(self, chat_id: int, message_type: str, text: str) -> None:
        """Установить кастомное сообщение для типа нарушения."""
        settings = await self.get_chat_settings(chat_id)
        field_name = f"warn_message_{message_type}"
        if hasattr(settings, field_name):
            setattr(settings, field_name, text)
            await self.update_chat_settings(settings)

    async def reset_warn_message(self, chat_id: int, message_type: str) -> None:
        """Сбросить кастомное сообщение на стандартное."""
        await self.set_warn_message(chat_id, message_type, "")

    # === Статистика ===

    async def increment_stat(self, stat_name: str, amount: int = 1) -> None:
        """Увеличить счётчик статистики."""
        await self._execute(
            f"UPDATE bot_stats SET {stat_name} = {stat_name} + ? WHERE id = 1",
            (amount,),
        )

    async def get_stats(self) -> dict:
        """Получить статистику бота."""
        row = await self._fetchone(
            "SELECT messages_deleted, bots_banned, users_globally_banned FROM bot_stats WHERE id = 1",
            (),
        )
        if row:
            return {
                "messages_deleted": row[0],
                "bots_banned": row[1],
                "users_globally_banned": row[2],
            }
        return {"messages_deleted": 0, "bots_banned": 0, "users_globally_banned": 0}

    # === Управление чатами ===

    async def remove_chat(self, chat_id: int) -> None:
        """Удалить чат из списка известных."""
        await self._execute("DELETE FROM known_chats WHERE chat_id = ?", (chat_id,))

    async def migrate_chat(self, old_chat_id: int, new_chat_id: int) -> None:
        """Перенести все данные чата на новый ID (при миграции группы в супергруппу)."""
        connection = await self._ensure_connected()

        # Переносим подтверждённых пользователей
        await connection.execute(
            "UPDATE OR IGNORE confirmed_users SET chat_id = ? WHERE chat_id = ?",
            (new_chat_id, old_chat_id),
        )
        # Удаляем оставшиеся дубликаты
        await connection.execute(
            "DELETE FROM confirmed_users WHERE chat_id = ?",
            (old_chat_id,),
        )

        # Переносим запрещённые слова
        await connection.execute(
            "UPDATE OR IGNORE banned_words SET chat_id = ? WHERE chat_id = ?",
            (new_chat_id, old_chat_id),
        )
        await connection.execute(
            "DELETE FROM banned_words WHERE chat_id = ?",
            (old_chat_id,),
        )

        # Переносим настройки чата
        await connection.execute(
            "UPDATE OR IGNORE chat_settings SET chat_id = ? WHERE chat_id = ?",
            (new_chat_id, old_chat_id),
        )
        await connection.execute(
            "DELETE FROM chat_settings WHERE chat_id = ?",
            (old_chat_id,),
        )

        # Переносим выбор чата у админов
        await connection.execute(
            "UPDATE admin_selected_chat SET chat_id = ? WHERE chat_id = ?",
            (new_chat_id, old_chat_id),
        )

        # Удаляем старый чат из known_chats
        await connection.execute(
            "DELETE FROM known_chats WHERE chat_id = ?",
            (old_chat_id,),
        )

        await connection.commit()

    async def get_chats_count(self) -> int:
        """Получить количество подключенных чатов."""
        row = await self._fetchone("SELECT COUNT(*) FROM known_chats", ())
        return row[0] if row else 0

    async def get_confirmed_users_count(self) -> int:
        """Получить общее количество доверенных пользователей."""
        row = await self._fetchone("SELECT COUNT(*) FROM confirmed_users", ())
        return row[0] if row else 0

    async def _execute(self, query: str, params: Iterable) -> None:
        connection = await self._ensure_connected()
        await connection.execute(query, tuple(params))
        await connection.commit()

    async def _fetchone(self, query: str, params: Iterable) -> tuple | None:
        connection = await self._ensure_connected()
        async with connection.execute(query, tuple(params)) as cursor:
            return await cursor.fetchone()

    async def _fetchall(self, query: str, params: Iterable) -> List[tuple]:
        connection = await self._ensure_connected()
        async with connection.execute(query, tuple(params)) as cursor:
            return await cursor.fetchall()

    async def _ensure_connected(self) -> aiosqlite.Connection:
        if self._connection is None:
            async with self._connect_lock:
                if self._connection is None:
                    await self.connect()
        if self._connection is None:
            raise RuntimeError("Database connection not established")
        return self._connection
