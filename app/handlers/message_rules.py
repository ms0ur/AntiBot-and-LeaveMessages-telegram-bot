import logging
from typing import Iterable
from aiogram import Bot, Router
from aiogram.enums import ChatType, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database import Database
from app.utils import is_admin

router = Router()
logger = logging.getLogger(__name__)
MEDIA_CONTENT_TYPES: set[ContentType] = {
    ContentType.ANIMATION,
    ContentType.AUDIO,
    ContentType.DOCUMENT,
    ContentType.PHOTO,
    ContentType.STICKER,
    ContentType.VIDEO,
    ContentType.VIDEO_NOTE,
    ContentType.VOICE,
    ContentType.CONTACT,
}


def extract_text(message: Message) -> str:
    return (message.text or message.caption or "").lower()


async def is_confirmed_user(bot: Bot, db: Database, chat_id: int, user_id: int) -> bool:
    if await is_admin(bot, chat_id, user_id):
        return True
    return await db.is_confirmed(chat_id, user_id)


def contains_banned_word(text: str, banned_words: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in banned_words)


@router.message(Command(commands=["start", "help"]))
async def start_command(message: Message) -> None:
    if message.chat.type != ChatType.PRIVATE:
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ Настройки (выбор чата)", callback_data="settings")
    builder.button(text="👥 Управление пользователями", callback_data="menu:users")
    builder.button(text="🚫 Банлист слов", callback_data="menu:words")
    builder.button(text="ℹ️ Помощь", callback_data="menu:help")
    builder.adjust(1)
    await message.answer(
        "🤖 <b>Добро пожаловать!</b>\n\n"
        "Этот бот помогает модерировать группы:\n"
        "• Удаляет ботов, добавленных не-админами\n"
        "• Удаляет сообщения о входе/выходе\n"
        "• Фильтрует медиа от неподтверждённых пользователей\n"
        "• Блокирует сообщения с запрещёнными словами\n\n"
        "<b>Начните с настроек — выберите группу для управления.</b>",
        reply_markup=builder.as_markup(),
    )


@router.message()
async def enforce_rules(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user:
        return

    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    chat_title = message.chat.title or str(message.chat.id)
    await db.upsert_chat(message.chat.id, chat_title)

    if message.content_type == ContentType.NEW_CHAT_MEMBERS:
        return

    if await db.is_banned_user(message.chat.id, message.from_user.id):
        await _delete_quietly(message)
        return

    user_is_confirmed = await is_confirmed_user(bot, db, message.chat.id, message.from_user.id)

    if user_is_confirmed:
        return

    if message.content_type in MEDIA_CONTENT_TYPES:
        await _delete_quietly(message)
        return

    text_content = extract_text(message)
    banned_words = await db.get_banned_words(message.chat.id)
    if banned_words and contains_banned_word(text_content, banned_words):
        await _delete_quietly(message)
        return


async def _delete_quietly(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        logger.debug("Message already removed or cannot be deleted: %s", message.message_id)
    except TelegramAPIError as exc:
        logger.warning("Failed to delete message %s: %s", message.message_id, exc)
