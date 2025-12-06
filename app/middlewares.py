from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from app.database import Database


class DatabaseMiddleware(BaseMiddleware):
    def __init__(self, database: Database):
        super().__init__()
        self.database = database

    async def __call__(
        self, handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]], event: Any, data: Dict[str, Any]
    ) -> Any:
        data["db"] = self.database
        return await handler(event, data)
