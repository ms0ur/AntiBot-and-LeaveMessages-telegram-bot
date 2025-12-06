from pathlib import Path
from typing import Iterable, List
import aiosqlite


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._connection = await aiosqlite.connect(self.path)
        await self._connection.execute("PRAGMA journal_mode=WAL;")
        await self._connection.execute("PRAGMA foreign_keys=ON;")
        await self._connection.execute("PRAGMA synchronous=NORMAL;")
        await self._connection.commit()

    async def setup(self) -> None:
        if self._connection is None:
            await self.connect()

        await self._connection.executescript(
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

            CREATE TABLE IF NOT EXISTS banned_users (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS known_chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS admin_selected_chat (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES known_chats(chat_id) ON DELETE CASCADE
            );
            """
        )
        await self._connection.commit()

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

    async def add_banned_user(self, chat_id: int, user_id: int) -> None:
        await self._execute(
            "INSERT OR IGNORE INTO banned_users(chat_id, user_id) VALUES (?, ?)",
            (chat_id, user_id),
        )

    async def remove_banned_user(self, chat_id: int, user_id: int) -> None:
        await self._execute(
            "DELETE FROM banned_users WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )

    async def is_banned_user(self, chat_id: int, user_id: int) -> bool:
        row = await self._fetchone(
            "SELECT 1 FROM banned_users WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        return bool(row)

    async def get_banned_users(self, chat_id: int) -> List[int]:
        rows = await self._fetchall("SELECT user_id FROM banned_users WHERE chat_id = ?", (chat_id,))
        return [row[0] for row in rows]

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

    async def _execute(self, query: str, params: Iterable) -> None:
        if self._connection is None:
            await self.connect()
        assert self._connection is not None
        await self._connection.execute(query, tuple(params))
        await self._connection.commit()

    async def _fetchone(self, query: str, params: Iterable) -> tuple | None:
        if self._connection is None:
            await self.connect()
        assert self._connection is not None
        async with self._connection.execute(query, tuple(params)) as cursor:
            return await cursor.fetchone()

    async def _fetchall(self, query: str, params: Iterable) -> List[tuple]:
        if self._connection is None:
            await self.connect()
        assert self._connection is not None
        async with self._connection.execute(query, tuple(params)) as cursor:
            return await cursor.fetchall()
