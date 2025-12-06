import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from app.config import load_config
from app.database import Database
from app.handlers import admin, membership, message_rules
from app.middlewares import DatabaseMiddleware


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    database = Database(config.database_path)
    await database.setup()

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=config.default_parse_mode),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(DatabaseMiddleware(database))
    dp.callback_query.middleware(DatabaseMiddleware(database))

    dp.include_router(admin.router)
    dp.include_router(membership.router)
    dp.include_router(message_rules.router)

    try:
        await dp.start_polling(bot)
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
