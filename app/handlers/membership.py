import asyncio
import logging
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message
from app.database import Database
from app.utils import is_admin

router = Router()

logger = logging.getLogger(__name__)


async def _delete_join_leave(message: Message) -> None:
    try:
        await asyncio.sleep(3)
        await message.delete()
    except TelegramBadRequest:
        logger.debug("Join/leave message already removed or too old: %s", message.message_id)
    except TelegramAPIError as exc:
        logger.warning("Failed to delete join/leave message %s: %s", message.message_id, exc)


@router.message(F.new_chat_members)
async def handle_new_members(message: Message, bot: Bot, db: Database) -> None:
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    if not message.from_user:
        return

    chat_title = message.chat.title or str(message.chat.id)
    await db.upsert_chat(message.chat.id, chat_title)

    adder_is_admin = await is_admin(bot, message.chat.id, message.from_user.id)

    for member in message.new_chat_members:
        if member.is_bot and not adder_is_admin:
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=member.id)
            try:
                await message.delete()
            except TelegramBadRequest:
                logger.debug("Join message for banned bot already removed: %s", message.message_id)
            except TelegramAPIError as exc:
                logger.warning("Failed to delete join message for bot %s: %s", member.id, exc)
        elif not member.is_bot:
            await _delete_join_leave(message)


@router.message(F.left_chat_member)
async def handle_left_member(message: Message) -> None:
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    await _delete_join_leave(message)
